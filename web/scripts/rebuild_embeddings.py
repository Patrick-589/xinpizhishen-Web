from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


WEB_ROOT = Path(__file__).resolve().parents[1]
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from server import create_runtime  # noqa: E402
from backend.database import utc_now  # noqa: E402
from backend.parsers import parse_document  # noqa: E402


def rebuild_uploaded_document(platform, database, document: dict[str, object]) -> int:
    document_id = str(document["id"])
    path = Path(str(document["file_path"])).resolve()
    if not path.is_relative_to(platform.settings.upload_root.resolve()) or not path.is_file():
        raise RuntimeError(f"上传文档原文件不存在或路径无效：{document_id}")
    parsed = parse_document(str(document["filename"]), path.read_bytes(), platform.ocr_service)
    metadata = json.loads(str(document.get("metadata_json") or "{}"))
    title = str(metadata.get("title") or document["filename"])
    platform._cache_existing_chunk_vectors(document_id)
    platform.vector_store.delete_chunks(document_id)
    chunks = platform.task_chunker.chunk(
        document_id,
        parsed,
        "user_documents",
        {
            "file_name": str(document["filename"]),
            "document_name": title,
            "regulation_name": None,
            "document_updated_at": document.get("updated_at"),
        },
    )
    indexed = platform._index_chunks(chunks, document_id=document_id)
    database.execute(
        """UPDATE documents SET page_count=?,paragraph_count=?,character_count=?,
                  status='parsed',updated_at=? WHERE id=?""",
        (parsed.page_count, len(parsed.blocks), parsed.character_count, utc_now(), document_id),
    )
    return indexed


def main() -> None:
    parser = argparse.ArgumentParser(description="重建知识文档 Embedding")
    parser.add_argument("--document-id", default="", help="仅重建指定文档；留空则重建全部有效文档")
    parser.add_argument("--include-uploaded", action="store_true", help="同时处理已解析的用户上传文档")
    parser.add_argument("--uploaded-document-id", default="", help="仅处理指定用户上传文档")
    parser.add_argument("--missing-only", action="store_true", help="仅处理尚无当前模型向量的文档")
    args = parser.parse_args()
    _, database, _, platform, _ = create_runtime()
    user = database.fetch_one("SELECT id,username,display_name,role FROM users WHERE role='admin' ORDER BY created_at LIMIT 1")
    if not user:
        raise RuntimeError("没有管理员账号。")
    model = platform.embedding_provider.model_name()
    knowledge_condition = """ AND NOT EXISTS (
        SELECT 1 FROM chunks c WHERE c.knowledge_document_id=knowledge_documents.id
          AND c.embedding_status='ready' AND c.embedding_model=?
    )""" if args.missing_only else ""
    knowledge_params: list[object] = []
    if args.document_id:
        knowledge_condition += " AND id=?"
    if args.missing_only:
        knowledge_params.append(model)
    if args.document_id:
        knowledge_params.append(args.document_id)
    documents = database.fetch_all(
        f"SELECT id FROM knowledge_documents WHERE status='active'{knowledge_condition} ORDER BY created_at",
        knowledge_params,
    )
    documents = [document for document in documents if document]
    uploaded_documents: list[dict[str, object]] = []
    if args.include_uploaded or args.uploaded_document_id:
        uploaded_condition = """ AND NOT EXISTS (
            SELECT 1 FROM chunks c WHERE c.document_id=documents.id
              AND c.embedding_status='ready' AND c.embedding_model=?
        )""" if args.missing_only else ""
        uploaded_params: list[object] = []
        if args.uploaded_document_id:
            uploaded_condition += " AND id=?"
        if args.missing_only:
            uploaded_params.append(model)
        if args.uploaded_document_id:
            uploaded_params.append(args.uploaded_document_id)
        uploaded_documents = database.fetch_all(
            f"SELECT * FROM documents WHERE status='parsed'{uploaded_condition} ORDER BY created_at",
            uploaded_params,
        )

    with platform.vector_store.batch_updates():
        for document in documents:
            result = platform.rebuild_knowledge(document["id"], user, "local-cli")
            print(f"OK knowledge {result['document_id']} ({result['chunks']} chunks)")
        for document in uploaded_documents:
            indexed = rebuild_uploaded_document(platform, database, document)
            print(f"OK uploaded {document['id']} ({indexed} chunks)")
    print(f"重建完成：{len(documents)} 份共享资料，{len(uploaded_documents)} 份上传文档")
    print(f"Embedding：{platform.embedding_provider.model_name()}")
    if hasattr(platform.vector_store, "root"):
        print(f"FAISS：{platform.vector_store.root}")


if __name__ == "__main__":
    main()
