from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


def file_inventory(root: Path) -> dict[str, int]:
    return {
        path.relative_to(root).as_posix(): path.stat().st_size
        for path in root.rglob("*")
        if path.is_file()
    }


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def scalar(connection: sqlite3.Connection, query: str) -> int | str:
    return connection.execute(query).fetchone()[0]


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify an extracted XinPiZhiShen delivery.")
    parser.add_argument("source", type=Path)
    parser.add_argument("extracted", type=Path)
    args = parser.parse_args()

    source = args.source.resolve()
    extracted = args.extracted.resolve()
    if not source.is_dir() or not extracted.is_dir():
        raise SystemExit("Source or extracted delivery directory is missing.")

    source_files = file_inventory(source)
    extracted_files = file_inventory(extracted)
    if source_files != extracted_files:
        missing = sorted(set(source_files) - set(extracted_files))
        extra = sorted(set(extracted_files) - set(source_files))
        changed = sorted(
            path
            for path in set(source_files) & set(extracted_files)
            if source_files[path] != extracted_files[path]
        )
        raise SystemExit(
            f"File inventory mismatch: missing={missing[:5]}, extra={extra[:5]}, changed={changed[:5]}"
        )

    database = extracted / "web" / "runtime" / "xinpizhishen.db"
    faiss_manifests = list((extracted / "web" / "runtime" / "faiss").glob("*/manifest.json"))
    faiss_indexes = list((extracted / "web" / "runtime" / "faiss").glob("*/index.faiss"))
    if len(faiss_manifests) != 1 or len(faiss_indexes) != 1:
        raise SystemExit("Expected exactly one packaged FAISS index and manifest.")

    manifest = json.loads(faiss_manifests[0].read_text(encoding="utf-8"))
    connection = sqlite3.connect(database)
    try:
        integrity = str(scalar(connection, "PRAGMA integrity_check"))
        users = int(scalar(connection, "SELECT COUNT(*) FROM users"))
        private_documents = int(scalar(connection, "SELECT COUNT(*) FROM documents"))
        knowledge_documents = int(scalar(connection, "SELECT COUNT(*) FROM knowledge_documents"))
        ready_chunks = int(
            scalar(
                connection,
                "SELECT COUNT(*) FROM chunks WHERE embedding_status='ready' "
                "AND embedding_model='local:BAAI/bge-m3'",
            )
        )
        sqlite_vectors = int(scalar(connection, "SELECT COUNT(*) FROM chunks WHERE vector_json IS NOT NULL"))
        embedding_cache = int(scalar(connection, "SELECT COUNT(*) FROM embedding_cache"))
    finally:
        connection.close()

    knowledge_files = sum(1 for path in (extracted / "web" / "knowledge").rglob("*") if path.is_file())
    if integrity != "ok":
        raise SystemExit(f"SQLite integrity check failed: {integrity}")
    if users != 0 or private_documents != 0:
        raise SystemExit("Distribution database contains private accounts or documents.")
    if knowledge_documents != 4909 or knowledge_files != 4910:
        raise SystemExit(
            f"Knowledge count mismatch: database={knowledge_documents}, files={knowledge_files}"
        )
    if ready_chunks != 280166 or int(manifest.get("vectors") or 0) != ready_chunks:
        raise SystemExit(
            f"FAISS/database vector mismatch: ready={ready_chunks}, manifest={manifest.get('vectors')}"
        )
    if sqlite_vectors != 0 or embedding_cache != 0:
        raise SystemExit("Duplicate SQLite vectors or embedding cache were not pruned.")

    key_paths = [
        Path("web/app.js"),
        Path("web/runtime/xinpizhishen.db"),
        faiss_indexes[0].relative_to(extracted),
    ]
    for relative in key_paths:
        if sha256(source / relative) != sha256(extracted / relative):
            raise SystemExit(f"Hash mismatch: {relative.as_posix()}")

    print("status=ok")
    print(f"files={len(extracted_files)}")
    print(f"bytes={sum(extracted_files.values())}")
    print(f"knowledge_documents={knowledge_documents}")
    print(f"knowledge_files={knowledge_files}")
    print(f"ready_chunks={ready_chunks}")
    print(f"faiss_bytes={faiss_indexes[0].stat().st_size}")
    print(f"sqlite_integrity={integrity}")
    print(f"private_users={users}")
    print(f"private_documents={private_documents}")


if __name__ == "__main__":
    main()
