from __future__ import annotations

import argparse
import json
import sqlite3
from pathlib import Path


def scalar(connection: sqlite3.Connection, query: str) -> int:
    return int(connection.execute(query).fetchone()[0])


def main() -> None:
    parser = argparse.ArgumentParser(description="Remove duplicate vectors from a clean distribution database.")
    parser.add_argument("database", type=Path)
    parser.add_argument("faiss_manifest", type=Path)
    args = parser.parse_args()

    database = args.database.resolve()
    manifest_path = args.faiss_manifest.resolve()
    if not database.is_file() or not manifest_path.is_file():
        raise SystemExit("Distribution database or FAISS manifest is missing.")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    connection = sqlite3.connect(database)
    try:
        if scalar(connection, "SELECT COUNT(*) FROM users"):
            raise SystemExit("Refusing to slim a database that contains user accounts.")
        if scalar(connection, "SELECT COUNT(*) FROM documents"):
            raise SystemExit("Refusing to slim a database that contains private documents.")
        ready = scalar(
            connection,
            "SELECT COUNT(*) FROM chunks WHERE embedding_status='ready' AND embedding_model='local:BAAI/bge-m3'",
        )
        if ready != int(manifest.get("vectors") or 0):
            raise SystemExit(f"FAISS/database count mismatch: {manifest.get('vectors')} != {ready}")

        before = database.stat().st_size
        connection.execute("PRAGMA journal_mode=DELETE")
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute("UPDATE chunks SET vector_json=NULL WHERE vector_json IS NOT NULL")
        connection.execute("DELETE FROM embedding_cache")
        connection.commit()
        connection.execute("VACUUM")
        connection.execute("ANALYZE")
        connection.commit()
        after = database.stat().st_size
        print(f"ready_chunks={ready}")
        print(f"before_bytes={before}")
        print(f"after_bytes={after}")
        print(f"saved_bytes={before - after}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
