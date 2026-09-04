from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = WEB_ROOT / "runtime"
DATABASE_PATH = RUNTIME_ROOT / "xinpizhishen.db"
MANIFEST_PATH = RUNTIME_ROOT / "distribution-manifest.json"
PATHS_PATH = RUNTIME_ROOT / "knowledge-paths.json"


def main() -> None:
    parser = argparse.ArgumentParser(description="调整分发安装包的共享知识文件路径")
    parser.add_argument(
        "--reset-for-distribution",
        action="store_true",
        help="将路径恢复为安装包占位符，供发送前清理使用",
    )
    args = parser.parse_args()
    if not MANIFEST_PATH.is_file():
        print("当前不是分发安装包，无需调整路径。")
        return
    if not DATABASE_PATH.is_file() or not PATHS_PATH.is_file():
        raise RuntimeError("安装包缺少共享知识数据库或路径清单。")

    path_map = json.loads(PATHS_PATH.read_text(encoding="utf-8"))
    if not isinstance(path_map, dict) or not path_map:
        raise RuntimeError("共享知识路径清单为空。")

    updates: list[tuple[str, str]] = []
    knowledge_root = (WEB_ROOT / "knowledge").resolve()
    for document_id, relative_value in path_map.items():
        relative_path = Path(str(relative_value))
        destination = (knowledge_root / relative_path).resolve()
        if not destination.is_relative_to(knowledge_root):
            raise RuntimeError(f"知识文件路径越界：{relative_value}")
        if not destination.is_file():
            raise RuntimeError(f"安装包缺少知识文件：{relative_value}")
        value = f"__WEB_ROOT__/knowledge/{relative_path.as_posix()}" if args.reset_for_distribution else str(destination)
        updates.append((value, str(document_id)))

    connection = sqlite3.connect(DATABASE_PATH, timeout=60)
    try:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.executemany(
            "UPDATE knowledge_documents SET file_path=? WHERE id=?",
            updates,
        )
        connection.execute(
            """UPDATE structured_facts
                  SET file_path=(SELECT k.file_path FROM knowledge_documents k
                                  WHERE k.id=structured_facts.knowledge_document_id)
                WHERE knowledge_document_id IS NOT NULL"""
        )
        connection.commit()
    finally:
        connection.close()

    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    manifest.pop("installed_web_root", None)
    manifest.pop("installed_at", None)
    if not args.reset_for_distribution:
        manifest["installed_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    if args.reset_for_distribution:
        print(f"共享知识库路径已恢复为分发状态：{len(updates)} 份文档")
    else:
        print(f"共享知识库路径已适配当前电脑：{len(updates)} 份文档")


if __name__ == "__main__":
    main()
