from __future__ import annotations

import argparse
import sys
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1]
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from server import create_runtime  # noqa: E402


SUPPORTED = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".csv", ".txt", ".md", ".json"}


def main() -> None:
    parser = argparse.ArgumentParser(description="批量导入证券合规知识库")
    parser.add_argument("--input", required=True, help="文件或文件夹")
    parser.add_argument("--document-type", required=True, choices=[
        "company_profile", "regulations", "internal_rules", "announcements", "cases", "user_documents"
    ])
    parser.add_argument("--company", default="")
    parser.add_argument("--source", default="手工批量导入")
    parser.add_argument("--version", default="")
    args = parser.parse_args()

    settings, database, _, platform, _ = create_runtime()
    user = database.fetch_one("SELECT id,username,display_name,role FROM users WHERE role='admin' ORDER BY created_at LIMIT 1")
    if not user:
        raise RuntimeError("没有可用于导入审计记录的管理员账号。")
    source_path = Path(args.input).expanduser().resolve()
    files = [source_path] if source_path.is_file() else sorted(path for path in source_path.rglob("*") if path.is_file())
    files = [path for path in files if path.suffix.lower() in SUPPORTED]
    succeeded = skipped = failed = 0
    for path in files:
        try:
            result = platform.import_knowledge(
                path.name,
                path.read_bytes(),
                {
                    "title": path.stem,
                    "document_type": args.document_type,
                    "company": args.company,
                    "source": args.source,
                    "source_name": args.source,
                    "version": args.version,
                },
                user,
                "local-cli",
            )
            if result["status"] == "skipped":
                skipped += 1
                print(f"SKIP {path.name}")
            else:
                succeeded += 1
                print(f"OK   {path.name} ({result['document']['chunks']} chunks)")
        except Exception as error:
            failed += 1
            print(f"FAIL {path.name}: {error}", file=sys.stderr)
    print(f"导入完成：成功 {succeeded}，跳过 {skipped}，失败 {failed}；数据库 {settings.database_path}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
