from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


WEB_ROOT = Path(__file__).resolve().parents[1]
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from backend.config import load_settings  # noqa: E402
from backend.database import Database, utc_now  # noqa: E402
from backend.parsers import parse_document  # noqa: E402
from backend.services import PlatformService  # noqa: E402


def material(path: Path, document_type: str, version: str, source_group: str) -> dict[str, Any]:
    return {
        "path": path,
        "metadata": {
            "document_type": document_type,
            "company": "创业黑马科技集团股份有限公司",
            "title": path.stem,
            "source": f"用户提供：{source_group}",
            "source_type": "uploaded",
            "source_name": source_group,
            "version": version,
        },
    }


def build_manifest(desktop: Path) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    policies = desktop / "2025年制度修订" / "1-定稿-2025年制度修订"
    for path in sorted(policies.glob("*.docx")):
        if path.name.startswith("0-"):
            continue
        items.append(material(path, "internal_rules", "2025年定稿", "2025年制度修订/定稿"))

    items.append(material(desktop / "26年公司章程修订" / "终稿—章程.docx", "company_profile", "2026年1月终稿", "26年公司章程修订"))

    for path in sorted((desktop / "完整交易类文件").glob("*.docx")):
        document_type = "announcements" if ("公告" in path.name or "通知" in path.name) else "cases"
        items.append(material(path, document_type, "2026年案例资料", "完整交易类文件"))

    for path in sorted((desktop / "子公司增资类交易").iterdir()):
        if path.suffix.lower() != ".docx":
            continue
        document_type = "announcements" if "公告" in path.name else "cases"
        items.append(material(path, document_type, "2024年案例资料", "子公司增资类交易"))

    for path in sorted((desktop / "回购事项").glob("*.docx")):
        items.append(material(path, "announcements", "2024年公告资料", "回购事项"))

    items.append(material(desktop / "关联方汇总表-2026年6月-终版.csv", "company_profile", "2026年6月终版", "关联方汇总表"))
    return items


def main() -> None:
    parser = argparse.ArgumentParser(description="导入默认测试资料到指定个人账号")
    parser.add_argument("--username", required=True)
    parser.add_argument("--desktop", type=Path, default=Path.home() / "Desktop")
    args = parser.parse_args()

    settings = load_settings()
    database = Database(settings.database_path)
    database.migrate()
    user = database.fetch_one(
        "SELECT id,username,display_name,role FROM users WHERE username=? COLLATE NOCASE AND active=1",
        (args.username,),
    )
    if not user:
        raise SystemExit(f"账号不存在或已停用：{args.username}")

    manifest = build_manifest(args.desktop)
    missing = [str(item["path"]) for item in manifest if not item["path"].is_file()]
    if missing:
        raise SystemExit("缺少待导入文件：\n" + "\n".join(missing))

    preflight = []
    for item in manifest:
        path = item["path"]
        parsed = parse_document(path.name, path.read_bytes())
        preflight.append({"file": path.name, "type": item["metadata"]["document_type"], "blocks": len(parsed.blocks)})

    platform = PlatformService(settings, database)
    platform.initialize()
    imported = []
    skipped = []
    failed = []
    for item in manifest:
        path = item["path"]
        try:
            result = platform.import_knowledge(path.name, path.read_bytes(), item["metadata"], user, "local-import")
            row = {"file": path.name, "type": item["metadata"]["document_type"], "result": result["status"]}
            if result["status"] == "success":
                row["chunks"] = result["document"]["chunks"]
                imported.append(row)
            else:
                row["reason"] = result.get("reason", "")
                skipped.append(row)
        except Exception as error:
            failed.append({"file": path.name, "error": str(error)})

    report = {
        "generatedAt": utc_now(),
        "username": user["username"],
        "userId": user["id"],
        "selected": len(manifest),
        "preflight": preflight,
        "imported": imported,
        "skipped": skipped,
        "failed": failed,
    }
    report_root = WEB_ROOT / "runtime" / "imports"
    report_root.mkdir(parents=True, exist_ok=True)
    report_path = report_root / "default-test-materials.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "report": str(report_path),
        "selected": len(manifest),
        "imported": len(imported),
        "skipped": len(skipped),
        "failed": len(failed),
        "chunks": sum(int(item.get("chunks", 0)) for item in imported),
    }, ensure_ascii=False))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
