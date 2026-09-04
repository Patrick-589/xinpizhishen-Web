"""Import a folder tree of supplied meeting materials into shared drafting knowledge.

Usage:
    python web/scripts/import-meeting-materials.py <folder>

All supported files below ``folder`` are imported as shared ``drafting_materials``.
ZIP files should be expanded before running this script.  File hashes make the
operation repeatable: files already present in the shared library are skipped.
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parents[1]
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from backend.config import load_settings  # noqa: E402
from backend.database import Database  # noqa: E402
from backend.meeting_case_library import (  # noqa: E402
    infer_case_role,
    infer_meeting_kind,
    meeting_term,
)
from backend.ocr import LocalOCRService  # noqa: E402
from backend.parsers import ALLOWED_EXTENSIONS, parse_document  # noqa: E402
from backend.services import PlatformService  # noqa: E402


def _date_from_text(text: str) -> str | None:
    match = re.search(r"(20\d{2})年\s*(\d{1,2})月\s*(\d{1,2})日", text)
    if not match:
        match = re.search(r"(20\d{2})年\s*(\d{1,2})月", text)
        if not match:
            return None
        year, month = int(match.group(1)), int(match.group(2))
        try:
            return date(year, month, 1).isoformat()
        except ValueError:
            return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
    except ValueError:
        return None


def main() -> int:
    if len(sys.argv) < 2:
        raise SystemExit("用法：python web/scripts/import-meeting-materials.py <资料文件夹>")
    folder = Path(sys.argv[1]).expanduser().resolve()
    if not folder.is_dir():
        raise SystemExit(f"资料文件夹不存在：{folder}")

    files = sorted(
        (
            path
            for path in folder.rglob("*")
            if path.is_file() and path.suffix.casefold() in ALLOWED_EXTENSIONS
        ),
        key=lambda path: path.relative_to(folder).as_posix().casefold(),
    )
    if not files:
        raise SystemExit("资料文件夹中没有可解析文件。")

    settings = load_settings()
    database = Database(settings.database_path)
    database.migrate()
    platform = PlatformService(settings, database)
    platform.initialize()
    admin = database.fetch_one(
        "SELECT id,username,display_name,role FROM users "
        "WHERE role='admin' AND active=1 ORDER BY created_at LIMIT 1"
    )
    if not admin:
        raise SystemExit("未找到启用中的管理员账号，请先启动应用完成初始化。")

    ocr_service = LocalOCRService(settings)
    report: dict[str, object] = {
        "folder": str(folder),
        "total": len(files),
        "imported": 0,
        "skipped": 0,
        "failed": 0,
        "items": [],
    }
    # One FAISS write lock and one metadata persist for the whole batch keeps
    # a large existing index responsive and leaves an atomic final index.
    batch_context = getattr(platform.vector_store, "batch_updates", None)
    context = batch_context() if callable(batch_context) else None
    if context is None:
        from contextlib import nullcontext

        context = nullcontext()
    with context:
        for number, path in enumerate(files, 1):
            relative = path.relative_to(folder).as_posix()
            item: dict[str, object] = {"path": relative, "status": "failed"}
            try:
                content = path.read_bytes()
                parsed = parse_document(path.name, content, ocr_service)
                text = "\n".join(parsed.paragraphs)
                role = infer_case_role(path.name, text)
                meeting_type = infer_meeting_kind(path.name, text)
                title = relative.rsplit(".", 1)[0]
                metadata = {
                    "title": title,
                    "document_type": "drafting_materials",
                    "company": "创业黑马科技集团股份有限公司",
                    "source": f"用户提供的会议起草案例：{relative}",
                    "source_name": relative,
                    "source_type": "approved_meeting_case",
                    "relative_path": relative,
                    "date": _date_from_text(text),
                    "updated_at": _date_from_text(text),
                    "case_role": role,
                    "meeting_type": meeting_type,
                    "meeting_term": meeting_term(path.name, text),
                    "case_status": "用户提供的起草案例，事实仅作格式与表达参考",
                    "case_set_id": "创业黑马-会议起草案例-2026-09",
                }
                result = platform.import_knowledge(
                    path.name, content, metadata, admin, "127.0.0.1"
                )
                status = str(result.get("status") or "success")
                item["status"] = status
                document = result.get("document") or {}
                item["document_id"] = document.get("id")
                item["chunks"] = document.get("chunks", 0)
                if status == "skipped":
                    report["skipped"] = int(report["skipped"]) + 1
                else:
                    report["imported"] = int(report["imported"]) + 1
                print(
                    f"[{number}/{len(files)}] {status.upper()} {relative} "
                    f"chunks={document.get('chunks', 0)}",
                    flush=True,
                )
            except Exception as error:  # keep remaining files importable
                report["failed"] = int(report["failed"]) + 1
                item["error"] = f"{type(error).__name__}: {error}"
                print(f"[{number}/{len(files)}] FAILED {relative}: {item['error']}", flush=True)
            report["items"].append(item)

    report_path = folder / "import-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        "SUMMARY "
        f"total={report['total']} imported={report['imported']} "
        f"skipped={report['skipped']} failed={report['failed']}"
    )
    print(f"REPORT {report_path}")
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
