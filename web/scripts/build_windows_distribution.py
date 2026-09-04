from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = WEB_ROOT.parent
RUNTIME_ROOT = WEB_ROOT / "runtime"
SOURCE_DATABASE = RUNTIME_ROOT / "xinpizhishen.db"
SOURCE_MODEL = RUNTIME_ROOT / "models" / "bge-m3"
SOURCE_FAISS_ROOT = RUNTIME_ROOT / "faiss"
MODEL_NAME = "local:BAAI/bge-m3"
ROOT_FILES = (
    ".env.example",
    "安装信披智审_Windows.cmd",
    "打开信披智审_Windows.cmd",
    "打开信披智审.url",
    "设置信披智审开机与更新_Windows.cmd",
)
WEB_EXCLUDES = {"runtime", "tests", "__pycache__"}
PRIVATE_TABLES = (
    "messages",
    "memory_summaries",
    "reviews",
    "financial_audit_results",
    "meeting_generation_records",
    "draft_documents",
    "risks",
    "conversations",
    "usage_records",
    "analysis_jobs",
    "analysis_tasks",
    "documents",
    "sessions",
    "company_profiles",
    "audit_logs",
    "users",
)


def log(message: str) -> None:
    print(message, flush=True)


def copy_application(destination: Path) -> None:
    destination.mkdir(parents=True)
    for name in ROOT_FILES:
        source = PROJECT_ROOT / name
        if source.is_file():
            shutil.copy2(source, destination / name)

    target_web = destination / "web"
    target_web.mkdir()
    for source in WEB_ROOT.iterdir():
        if source.name in WEB_EXCLUDES:
            continue
        target = target_web / source.name
        if source.is_dir():
            shutil.copytree(
                source,
                target,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.log"),
            )
        elif source.suffix.lower() not in {".pyc", ".log"}:
            shutil.copy2(source, target)


def backup_and_sanitize_database(destination: Path) -> tuple[set[str], dict[str, str], int]:
    if not SOURCE_DATABASE.is_file():
        raise RuntimeError(f"找不到当前知识数据库：{SOURCE_DATABASE}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    log("正在生成一致的共享知识数据库快照...")
    source = sqlite3.connect(f"file:{SOURCE_DATABASE.as_posix()}?mode=ro", uri=True, timeout=60)
    target = sqlite3.connect(destination, timeout=60)
    try:
        source.backup(target, pages=8192)
    finally:
        source.close()

    knowledge_root = (WEB_ROOT / "knowledge").resolve()
    target.row_factory = sqlite3.Row
    target.execute("PRAGMA foreign_keys=OFF")
    target.execute(
        """DELETE FROM chunks
              WHERE knowledge_document_id IS NULL
                 OR knowledge_document_id NOT IN (
                     SELECT id FROM knowledge_documents WHERE owner_user_id IS NULL
                 )"""
    )
    target.execute(
        """DELETE FROM structured_facts
              WHERE owner_user_id IS NOT NULL OR document_id IS NOT NULL
                 OR knowledge_document_id IS NULL
                 OR knowledge_document_id NOT IN (
                     SELECT id FROM knowledge_documents WHERE owner_user_id IS NULL
                 )"""
    )
    target.execute("DELETE FROM structured_fact_conflicts")
    target.execute("DELETE FROM knowledge_documents WHERE owner_user_id IS NOT NULL")
    for table in PRIVATE_TABLES:
        target.execute(f"DELETE FROM {table}")
    target.execute(
        """DELETE FROM embedding_cache
              WHERE NOT EXISTS (
                    SELECT 1 FROM chunks c
                     WHERE c.content_hash=embedding_cache.content_hash
                       AND c.embedding_model=embedding_cache.embedding_model
              )"""
    )

    path_map: dict[str, str] = {}
    for row in target.execute("SELECT id,file_path FROM knowledge_documents").fetchall():
        source_path = Path(str(row["file_path"])).resolve()
        try:
            relative = source_path.relative_to(knowledge_root)
        except ValueError as error:
            raise RuntimeError(f"共享知识文件不在知识库目录中：{source_path}") from error
        if not source_path.is_file():
            raise RuntimeError(f"共享知识文件不存在：{source_path}")
        path_map[str(row["id"])] = relative.as_posix()
        target.execute(
            "UPDATE knowledge_documents SET file_path=? WHERE id=?",
            (f"__WEB_ROOT__/knowledge/{relative.as_posix()}", row["id"]),
        )
    target.execute(
        """UPDATE structured_facts
              SET file_path=(SELECT k.file_path FROM knowledge_documents k
                              WHERE k.id=structured_facts.knowledge_document_id)
            WHERE knowledge_document_id IS NOT NULL"""
    )
    target.commit()
    allowed_documents = {
        str(row[0]) for row in target.execute("SELECT id FROM knowledge_documents").fetchall()
    }
    chunk_count = int(
        target.execute(
            "SELECT COUNT(*) FROM chunks WHERE embedding_status='ready' AND embedding_model=?",
            (MODEL_NAME,),
        ).fetchone()[0]
    )
    target.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    target.close()
    return allowed_documents, path_map, chunk_count


def find_faiss_source() -> Path:
    candidates = [
        path for path in SOURCE_FAISS_ROOT.iterdir()
        if path.is_dir()
        and (path / "index.faiss").is_file()
        and (path / "metadata.json").is_file()
        and (path / "manifest.json").is_file()
    ] if SOURCE_FAISS_ROOT.is_dir() else []
    for candidate in candidates:
        manifest = json.loads((candidate / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("embedding_model") == MODEL_NAME:
            return candidate
    raise RuntimeError("找不到与 BGE-M3 对应的完整 FAISS 索引。")


def sanitize_faiss(
    source_root: Path,
    destination_root: Path,
    allowed_documents: set[str],
    expected_chunks: int,
) -> int:
    try:
        import faiss  # type: ignore[import-not-found]
        import numpy as np
    except ImportError as error:
        raise RuntimeError("制作安装包需要当前项目环境中的 faiss-cpu 和 numpy。") from error

    log("正在复制并清理 FAISS 索引中的用户上传文档...")
    serialized = np.frombuffer((source_root / "index.faiss").read_bytes(), dtype="uint8")
    index = faiss.deserialize_index(serialized)
    payload = json.loads((source_root / "metadata.json").read_text(encoding="utf-8"))
    records = payload.get("records") or {}
    if int(index.ntotal) != len(records):
        raise RuntimeError("当前 FAISS 索引与 metadata 数量不一致，请先修复索引。")

    kept: dict[str, dict[str, object]] = {}
    removed_ids: list[int] = []
    for numeric_id, record in records.items():
        knowledge_id = str(record.get("knowledge_document_id") or "")
        if knowledge_id in allowed_documents and not record.get("document_id_private"):
            kept[str(numeric_id)] = record
        else:
            removed_ids.append(int(numeric_id))
    if removed_ids:
        index.remove_ids(np.asarray(removed_ids, dtype="int64"))
    if int(index.ntotal) != len(kept) or len(kept) != expected_chunks:
        raise RuntimeError(
            f"清理后向量数量不一致：FAISS={int(index.ntotal)}，metadata={len(kept)}，数据库={expected_chunks}"
        )

    destination_root.mkdir(parents=True, exist_ok=True)
    (destination_root / "index.faiss").write_bytes(faiss.serialize_index(index).tobytes())
    (destination_root / "metadata.json").write_text(
        json.dumps({"records": kept}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    manifest = json.loads((source_root / "manifest.json").read_text(encoding="utf-8"))
    manifest["vectors"] = int(index.ntotal)
    manifest["distribution_sanitized"] = True
    manifest["updated_at"] = datetime.now(UTC).replace(microsecond=0).isoformat()
    (destination_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (destination_root / "write.lock").write_bytes(b"\0")
    return int(index.ntotal)


def write_distribution_files(
    destination: Path,
    path_map: dict[str, str],
    knowledge_documents: int,
    indexed_chunks: int,
) -> None:
    runtime = destination / "web" / "runtime"
    (runtime / "knowledge-paths.json").write_text(
        json.dumps(path_map, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    manifest = {
        "format": 1,
        "product": "信披智审",
        "built_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "shared_knowledge_documents": knowledge_documents,
        "indexed_chunks": indexed_chunks,
        "embedding_model": MODEL_NAME,
        "contains_accounts": False,
        "contains_sessions": False,
        "contains_user_uploads": False,
        "contains_review_history": False,
    }
    (runtime / "distribution-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    readme = """信披智审 Windows 安装版

安装步骤：
1. 将整个文件夹复制到新电脑，建议放在 D:\\信披智审，不要只复制其中部分文件。
2. 确保磁盘至少保留 30GB 可用空间，首次安装建议联网下载 Python、Node.js 和项目依赖。
3. 双击“安装信披智审_Windows.cmd”，等待安装完成并自动打开浏览器。
4. 打开同目录生成的“首次登录信息.txt”，使用其中的管理员账号登录并立即修改密码。
5. 安装程序会在桌面创建“信披智审”图标，以后双击图标即可使用；Windows 登录后服务也会自动启动。

数据边界：
- 本安装包包含共享资料库、规则库、本地 BGE-M3 模型和 FAISS 向量索引。
- 不包含制作电脑上的账号、密码、登录会话、上传文档、审查任务、报告、对话或日志。
- 每台电脑安装后拥有独立账号和独立业务数据，不会与其他电脑自动共享。
- 共享知识库可能包含公司制度和案例，只应发送给获得授权的人员。

运行说明：
- 本地解析、Embedding 和向量检索不调用外部 AI API。
- 安装器会自动检测并安装 Python 3.11/3.12、Node.js LTS；Node.js 仅用于每日官方资料更新，未能安装时不影响本地审查。Poppler 用于扫描 PDF 页面渲染，能自动安装时也会自动安装。
- 如果电脑没有 winget，普通 PDF、Word、Excel 仍可使用；扫描 PDF OCR 需要管理员另行安装 Poppler。
- 电脑完全关机时本机应用无法访问；开机并登录 Windows 后会自动恢复。
- 若首次打开暂时无法连接，请等待约 1 分钟让本地知识数据库完成加载，然后刷新页面。
"""
    (destination / "安装说明.txt").write_text(readme, encoding="utf-8")


def verify_distribution(destination: Path, expected_chunks: int) -> None:
    database_path = destination / "web" / "runtime" / "xinpizhishen.db"
    connection = sqlite3.connect(database_path)
    try:
        private_counts = {
            table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
            for table in PRIVATE_TABLES
        }
        if any(private_counts.values()):
            raise RuntimeError(f"安装包仍包含用户数据：{private_counts}")
        chunks = int(
            connection.execute(
                "SELECT COUNT(*) FROM chunks WHERE embedding_status='ready' AND embedding_model=?",
                (MODEL_NAME,),
            ).fetchone()[0]
        )
        if chunks != expected_chunks:
            raise RuntimeError(f"安装包数据库向量数量异常：{chunks} != {expected_chunks}")
    finally:
        connection.close()
    if (destination / ".env").exists():
        raise RuntimeError("安装包不得包含当前电脑的 .env。")


def main() -> None:
    parser = argparse.ArgumentParser(description="制作不含当前用户私有数据的 Windows 分发安装包")
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "发布包" / f"信披智审_Windows安装版_{datetime.now():%Y%m%d}"),
    )
    args = parser.parse_args()
    destination = Path(args.output).expanduser().resolve()
    if destination.exists():
        raise RuntimeError(f"输出文件夹已存在，为避免覆盖请更换名称：{destination}")
    if destination == PROJECT_ROOT or destination.is_relative_to(WEB_ROOT):
        raise RuntimeError("输出文件夹不能是项目根目录或 web 目录内部。")

    log(f"开始制作安装包：{destination}")
    copy_application(destination)
    target_runtime = destination / "web" / "runtime"
    for name in ("uploads", "logs", "drafts", "reports", "parsed-cache", "imports", "backups"):
        (target_runtime / name).mkdir(parents=True, exist_ok=True)

    database_path = target_runtime / "xinpizhishen.db"
    allowed_documents, path_map, chunk_count = backup_and_sanitize_database(database_path)
    log(f"共享知识数据库已清理：{len(allowed_documents)} 份文档，{chunk_count} 个向量块。")

    if not SOURCE_MODEL.is_dir():
        raise RuntimeError(f"找不到本地 BGE-M3 模型：{SOURCE_MODEL}")
    log("正在复制本地 BGE-M3 模型...")
    shutil.copytree(SOURCE_MODEL, target_runtime / "models" / "bge-m3")

    source_faiss = find_faiss_source()
    target_faiss = target_runtime / "faiss" / source_faiss.name
    vector_count = sanitize_faiss(source_faiss, target_faiss, allowed_documents, chunk_count)
    write_distribution_files(destination, path_map, len(allowed_documents), vector_count)
    verify_distribution(destination, vector_count)
    total_size = sum(path.stat().st_size for path in destination.rglob("*") if path.is_file())
    log(f"安装包制作完成：{destination}")
    log(f"大小：{total_size / (1024 ** 3):.2f} GB")
    log("隐私检查通过：不含当前账号、会话、上传文件、审查记录和 .env。")


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"制作失败：{error}", file=sys.stderr, flush=True)
        raise
