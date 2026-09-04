"""Import the supplied company meeting documents as shared local drafting cases.

Usage (from the project root):
  python web/scripts/import-meeting-cases.py <案例文件夹>

The importer is intentionally explicit about the case role and never marks a
historical case as a current company fact.  It is safe to run repeatedly because
the platform skips identical file hashes.
"""

from __future__ import annotations

import re
import sys
from datetime import date
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parents[1]
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from backend.config import load_settings  # noqa: E402
from backend.database import Database  # noqa: E402
from backend.meeting_case_library import infer_case_role, infer_meeting_kind, meeting_term  # noqa: E402
from backend.ocr import LocalOCRService  # noqa: E402
from backend.parsers import parse_document  # noqa: E402
from backend.services import PlatformService  # noqa: E402


CASE_NAMES = (
    "1、2026年第【】次审计委员会会议通知(1).doc",
    "2.第四届董事会独立董事专门会议决议(1).docx",
    "4、2026第【】次审计委员会会议  会议决议(1).doc",
    "1-1第四届董事会第二十二次会议文件(1).docx",
    "2、2026第【】次审计委员会会议 表决票(1).doc",
    "5、2026第【】次审计委员会会议 议案(1).doc",
    "第四届董事会第二十一次会议通知及议案(1).docx",
    "2026第四次股东会记录(1).docx",
    "2025年第二次临时股东大会记录(1).docx",
    "3、2026第【】次审计委员会会议 会议记录(1).doc",
    "2025年度会议议程议案(1).docx",
    "25年第一次临时股东会议案(1).docx",
)


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
    folder = Path(sys.argv[1]).expanduser() if len(sys.argv) > 1 else Path.home() / "Desktop"
    settings = load_settings()
    database = Database(settings.database_path)
    database.migrate()
    platform = PlatformService(settings, database)
    platform.initialize()
    admin = database.fetch_one("SELECT id,username,role FROM users WHERE role='admin' AND active=1 ORDER BY created_at LIMIT 1")
    if not admin:
        raise SystemExit("未找到启用中的管理员账号，请先启动应用完成初始化。")
    ocr_service = LocalOCRService(settings)
    imported = 0
    skipped = 0
    failed = 0
    names = list(CASE_NAMES)
    if len(sys.argv) > 2:
        names = sys.argv[2:]
    for name in names:
        path = folder / name
        if not path.is_file():
            print(f"SKIP missing: {path}")
            continue
        try:
            content = path.read_bytes()
            parsed = parse_document(path.name, content, ocr_service)
            text = "\n".join(parsed.paragraphs)
            role = infer_case_role(path.name, text)
            meeting_type = infer_meeting_kind(path.name, text)
            metadata = {
                "title": path.stem,
                "document_type": "drafting_materials",
                "company": "创业黑马科技集团股份有限公司",
                "source": f"公司会议起草案例：{path.name}",
                "source_name": "公司已提供会议起草案例",
                "source_type": "approved_meeting_case",
                "date": _date_from_text(text),
                "updated_at": _date_from_text(text),
                "case_role": role,
                "meeting_type": meeting_type,
                "meeting_term": meeting_term(path.name, text),
                "case_status": "用户提供的起草案例，事实仅作格式与表达参考",
                "case_set_id": "创业黑马-会议起草案例-2026-09",
            }
            result = platform.import_knowledge(path.name, content, metadata, admin, "127.0.0.1")
            if result.get("status") == "skipped":
                skipped += 1
                print(f"SKIP existing: {path.name}")
            else:
                imported += 1
                print(f"IMPORTED {role}/{meeting_type}: {path.name} -> {result['document']['id']}")
        except Exception as error:  # keep remaining cases importable
            failed += 1
            print(f"FAILED {path.name}: {type(error).__name__}: {error}")
    print(f"SUMMARY imported={imported} skipped={skipped} failed={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
