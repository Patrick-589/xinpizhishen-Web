from __future__ import annotations

import argparse
import socket
import sys
from dataclasses import replace
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1]
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from backend.config import load_settings  # noqa: E402
from backend.database import Database  # noqa: E402
from backend.embeddings import create_embedding_provider  # noqa: E402
from backend.vector_store import FaissVectorStore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="断网条件下验证本地 Embedding 与 FAISS 检索")
    parser.add_argument("--query", default="关联交易审议和信息披露标准")
    parser.add_argument("--user-id", default="", help="检索私有任务时指定账号 ID")
    args = parser.parse_args()
    settings = replace(load_settings(), local_embedding_allow_download=False, vector_backend="faiss")

    original_connect = socket.socket.connect

    def deny_network(sock: socket.socket, address: object) -> None:
        raise RuntimeError(f"离线验证禁止网络连接：{address}")

    socket.socket.connect = deny_network
    try:
        provider = create_embedding_provider(settings)
        store = FaissVectorStore(Database(settings.database_path), settings.faiss_index_root, provider.model_name())
        vector = provider.embed_text(args.query)
        user_id = args.user_id
        if not user_id:
            database = Database(settings.database_path)
            admin = database.fetch_one("SELECT id FROM users ORDER BY created_at LIMIT 1") or {}
            user_id = str(admin.get("id") or "offline-check")
        results = store.search(vector, top_k=5, threshold=-1.0, filters={"user_id": user_id})
    finally:
        socket.socket.connect = original_connect

    print(f"MODEL: {provider.model_name()}")
    print(f"MODEL_PATH: {provider.local_model_path()}")
    print(f"FAISS_PATH: {store.root}")
    print(f"INDEX_VECTORS: {store.index_count}")
    print(f"RESULTS: {len(results)}")
    print("EXTERNAL_EMBEDDING_API: BLOCKED_AND_NOT_USED")


if __name__ == "__main__":
    main()
