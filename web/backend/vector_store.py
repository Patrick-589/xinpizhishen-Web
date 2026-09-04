from __future__ import annotations

import json
import hashlib
import math
import os
import re
import threading
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .chunking import ChunkRecord
from .database import Database, utc_now


@dataclass(frozen=True)
class SearchResult:
    chunk_id: str
    document_id: str
    content: str
    title: str
    source: str
    date: str | None
    page: int | None
    paragraph: int | None
    section: str | None
    document_type: str
    score: float
    source_url: str | None
    version: str | None
    metadata: dict[str, Any]

    def citation(self) -> dict[str, Any]:
        citation = {
            "chunk_id": self.chunk_id,
            "document_id": self.document_id,
            "title": self.title,
            "source": self.source,
            "source_url": self.source_url or "",
            "date": self.date or "",
            "version": self.version or "",
            "page": self.page,
            "paragraph": self.paragraph,
            "section": self.section or "",
            "document_type": self.document_type,
            "score": round(self.score, 6),
            "content": self.content,
            "metadata": self.metadata,
        }
        for key in (
            "file_name", "document_name", "csv_row_start", "csv_row_end",
            "original_text_position", "regulation_name", "document_updated_at",
        ):
            citation[key] = self.metadata.get(key)
        return citation


class VectorStore(ABC):
    @contextmanager
    def batch_updates(self):
        yield self

    @abstractmethod
    def add_chunks(
        self,
        chunks: Iterable[ChunkRecord],
        vectors: Iterable[list[float]],
        model: str,
        *,
        document_id: str | None = None,
        knowledge_document_id: str | None = None,
    ) -> int:
        raise NotImplementedError

    @abstractmethod
    def search(self, query_vector: list[float], top_k: int = 8, threshold: float = 0.08, filters: dict[str, Any] | None = None) -> list[SearchResult]:
        raise NotImplementedError

    def search_batch(
        self,
        query_vectors: list[list[float]],
        top_k: int = 8,
        threshold: float = 0.08,
        filters: dict[str, Any] | None = None,
    ) -> list[list[SearchResult]]:
        """Search several queries together when the backend can optimize it."""
        return [
            self.search(vector, top_k=top_k, threshold=threshold, filters=filters)
            for vector in query_vectors
        ]

    @abstractmethod
    def keyword_search(
        self,
        query: str,
        top_k: int = 8,
        threshold: float = 0.02,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        raise NotImplementedError

    @abstractmethod
    def delete_chunks(self, document_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def exists(self, content_hash: str, model: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def get_by_document(self, document_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def get_by_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        raise NotImplementedError


class SQLiteVectorStore(VectorStore):
    """Persistent vector store for the bundled local runtime.

    Vectors are stored with chunk metadata in SQLite and cosine similarity is
    calculated at query time. The interface isolates this implementation from
    a future pgvector deployment.
    """

    def __init__(self, database: Database):
        self.database = database

    def add_chunks(
        self,
        chunks: Iterable[ChunkRecord],
        vectors: Iterable[list[float]],
        model: str,
        *,
        document_id: str | None = None,
        knowledge_document_id: str | None = None,
    ) -> int:
        now = utc_now()
        rows = []
        for chunk, vector in zip(chunks, vectors, strict=True):
            rows.append((
                chunk.id,
                document_id,
                knowledge_document_id,
                chunk.content,
                chunk.page,
                chunk.section,
                chunk.paragraph,
                chunk.chunk_index,
                chunk.content_hash,
                "ready",
                model,
                json.dumps(vector, separators=(",", ":")),
                json.dumps(chunk.metadata, ensure_ascii=False),
                now,
                now,
            ))
        self.database.executemany(
            """
            INSERT INTO chunks (
                id,document_id,knowledge_document_id,content,page,section,paragraph,chunk_index,
                content_hash,embedding_status,embedding_model,vector_json,metadata_json,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                content=excluded.content,page=excluded.page,section=excluded.section,paragraph=excluded.paragraph,
                content_hash=excluded.content_hash,embedding_status=excluded.embedding_status,
                embedding_model=excluded.embedding_model,vector_json=excluded.vector_json,
                metadata_json=excluded.metadata_json,updated_at=excluded.updated_at
            """,
            rows,
        )
        return len(rows)

    @staticmethod
    def _cosine(left: list[float], right: list[float]) -> float:
        if len(left) != len(right) or not left:
            return -1.0
        dot = sum(a * b for a, b in zip(left, right))
        left_norm = math.sqrt(sum(value * value for value in left)) or 1.0
        right_norm = math.sqrt(sum(value * value for value in right)) or 1.0
        return dot / (left_norm * right_norm)

    def _filtered_rows(self, filters: dict[str, Any], *, require_vector: bool) -> list[dict[str, Any]]:
        filters = filters or {}
        conditions = ["c.content IS NOT NULL"]
        if require_vector:
            conditions.extend(["c.embedding_status='ready'", "c.vector_json IS NOT NULL"])
        params: list[Any] = []
        user_id = filters.get("user_id")
        if not user_id:
            return []
        document_types = filters.get("document_types") or []
        if document_types:
            placeholders = ",".join("?" for _ in document_types)
            conditions.append(f"COALESCE(k.document_type, json_extract(c.metadata_json, '$.document_type')) IN ({placeholders})")
            params.extend(document_types)
        if filters.get("company"):
            conditions.append("k.company=?")
            params.append(filters["company"])
        if filters.get("document_id"):
            conditions.append("COALESCE(c.document_id,c.knowledge_document_id)=?")
            params.append(filters["document_id"])
        if filters.get("date_from"):
            conditions.append("COALESCE(k.publication_date,'')>=?")
            params.append(filters["date_from"])
        if filters.get("date_to"):
            conditions.append("COALESCE(k.publication_date,'')<=?")
            params.append(filters["date_to"])
        excluded_versions = list(filters.get("exclude_regulation_versions") or [])
        if excluded_versions:
            placeholders = ",".join("?" for _ in excluded_versions)
            conditions.append(
                f"(COALESCE(k.document_type,json_extract(c.metadata_json, '$.document_type'))<>'regulations' "
                f"OR COALESCE(k.version,'') NOT IN ({placeholders}))"
            )
            params.extend(excluded_versions)
        conditions.append(
            "((k.id IS NOT NULL AND (k.owner_user_id IS NULL OR k.owner_user_id=?)) "
            "OR (d.id IS NOT NULL AND d.owner_user_id=?))"
        )
        params.extend([user_id, user_id])
        return self.database.fetch_all(
            f"""
            SELECT c.*,k.title AS knowledge_title,k.source,k.source_url,k.publication_date,k.version,
                   k.document_type AS knowledge_type,d.filename AS upload_title,d.document_type AS upload_type
            FROM chunks c
            LEFT JOIN knowledge_documents k ON k.id=c.knowledge_document_id AND k.status='active'
            LEFT JOIN documents d ON d.id=c.document_id
            WHERE {' AND '.join(conditions)}
            """,
            params,
        )

    def search(self, query_vector: list[float], top_k: int = 8, threshold: float = 0.08, filters: dict[str, Any] | None = None) -> list[SearchResult]:
        rows = self._filtered_rows(filters or {}, require_vector=True)
        scored: list[SearchResult] = []
        for row in rows:
            try:
                vector = json.loads(row["vector_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            raw_score = self._cosine(query_vector, vector)
            document_type = row["knowledge_type"] or row["upload_type"] or json.loads(row["metadata_json"]).get("document_type", "user_documents")
            priority = {
                "company_profile": 1.18,
                "internal_rules": 1.14,
                "regulations": 1.10,
                "cases": 1.04,
                "announcements": 1.00,
                "drafting_materials": 0.96,
                "user_documents": 1.08,
            }.get(document_type, 1.0)
            score = raw_score * priority
            if score < threshold:
                continue
            metadata = json.loads(row["metadata_json"] or "{}")
            scored.append(SearchResult(
                chunk_id=row["id"],
                document_id=row["knowledge_document_id"] or row["document_id"],
                content=row["content"],
                title=row["knowledge_title"] or row["upload_title"] or "未命名文档",
                source=row["source"] or "当前审查材料",
                date=row["publication_date"],
                page=row["page"],
                paragraph=row["paragraph"],
                section=row["section"],
                document_type=document_type,
                score=score,
                source_url=row["source_url"],
                version=row["version"],
                metadata=metadata,
            ))
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:max(1, min(top_k, 30))]

    @staticmethod
    def _keyword_features(value: str) -> set[str]:
        normalized = re.sub(r"\s+", "", value.lower())
        features = set(re.findall(r"\d+(?:\.\d+)*|[a-z][a-z0-9_-]+", normalized))
        chinese = "".join(re.findall(r"[\u4e00-\u9fff]", normalized))
        for size in (2, 3):
            features.update(chinese[index:index + size] for index in range(max(0, len(chinese) - size + 1)))
        return {feature for feature in features if feature}

    def keyword_search(
        self,
        query: str,
        top_k: int = 8,
        threshold: float = 0.02,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        query = query.strip()
        if not query:
            return []
        rows = self._filtered_rows(filters or {}, require_vector=False)
        query_features = self._keyword_features(query)
        scored: list[SearchResult] = []
        for row in rows:
            content = row["content"] or ""
            content_features = self._keyword_features(content)
            overlap = len(query_features & content_features) / max(1, len(query_features))
            exact_bonus = 0.25 if re.sub(r"\s+", "", query.lower()) in re.sub(r"\s+", "", content.lower()) else 0.0
            raw_score = min(1.0, overlap + exact_bonus)
            document_type = row["knowledge_type"] or row["upload_type"] or json.loads(row["metadata_json"]).get("document_type", "user_documents")
            priority = {
                "company_profile": 1.18, "internal_rules": 1.14, "regulations": 1.10,
                "cases": 1.04, "announcements": 1.00,
                "drafting_materials": 0.96, "user_documents": 1.08,
            }.get(document_type, 1.0)
            score = raw_score * priority
            if score < threshold:
                continue
            metadata = json.loads(row["metadata_json"] or "{}")
            scored.append(SearchResult(
                chunk_id=row["id"], document_id=row["knowledge_document_id"] or row["document_id"],
                content=content, title=row["knowledge_title"] or row["upload_title"] or "未命名文档",
                source=row["source"] or "当前审查材料", date=row["publication_date"], page=row["page"],
                paragraph=row["paragraph"], section=row["section"], document_type=document_type, score=score,
                source_url=row["source_url"], version=row["version"], metadata=metadata,
            ))
        scored.sort(key=lambda item: item.score, reverse=True)
        return scored[:max(1, min(top_k, 30))]

    def delete_chunks(self, document_id: str) -> None:
        self.database.execute("DELETE FROM chunks WHERE document_id=? OR knowledge_document_id=?", (document_id, document_id))

    def exists(self, content_hash: str, model: str) -> bool:
        return self.database.fetch_one(
            "SELECT id FROM chunks WHERE content_hash=? AND embedding_model=? AND embedding_status='ready' LIMIT 1",
            (content_hash, model),
        ) is not None

    def get_by_document(self, document_id: str) -> list[dict[str, Any]]:
        return self.database.fetch_all(
            "SELECT * FROM chunks WHERE document_id=? OR knowledge_document_id=? ORDER BY chunk_index",
            (document_id, document_id),
        )

    def get_by_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        return self.database.fetch_one("SELECT * FROM chunks WHERE id=?", (chunk_id,))


class FaissVectorStore(SQLiteVectorStore):
    """Project-local FAISS cosine index with an auditable metadata sidecar."""

    def __init__(self, database: Database, index_root: Path, model: str):
        super().__init__(database)
        try:
            import faiss  # type: ignore[import-not-found]
            import numpy as np  # type: ignore[import-not-found]
        except ImportError as error:
            raise RuntimeError("VECTOR_BACKEND=faiss 需要安装 faiss-cpu 和 numpy。") from error
        digest = hashlib.sha256(model.encode("utf-8")).hexdigest()[:12]
        slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", model).strip("-")[-64:] or "embedding"
        self.root = (index_root / f"{slug}-{digest}").resolve()
        self.index_path = self.root / "index.faiss"
        self.metadata_path = self.root / "metadata.json"
        self.manifest_path = self.root / "manifest.json"
        self.lock_path = self.root / "write.lock"
        self.model = model
        self._faiss = faiss
        self._np = np
        self._lock = threading.RLock()
        self._index: Any | None = None
        self._records: dict[str, dict[str, Any]] = {}
        self._chunk_numeric_ids: dict[str, int] = {}
        self._dimension = 0
        self._manifest_mtime_ns = 0
        self._batch_depth = 0
        self._batch_dirty = False
        try:
            self._load()
            if self._database_vector_count() != self.index_count:
                self._recover_from_database(force=True)
        except RuntimeError:
            self._recover_from_database()

    @property
    def index_count(self) -> int:
        with self._lock:
            self._reload_if_changed()
            return int(self._index.ntotal) if self._index is not None else 0

    def _load(self) -> None:
        present = [self.index_path.is_file(), self.metadata_path.is_file(), self.manifest_path.is_file()]
        if not any(present):
            self._manifest_mtime_ns = 0
            return
        if not all(present):
            raise RuntimeError(f"FAISS 索引文件不完整，请重建：{self.root}")
        try:
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            payload = json.loads(self.metadata_path.read_text(encoding="utf-8"))
            serialized = self._np.frombuffer(self.index_path.read_bytes(), dtype="uint8")
            index = self._faiss.deserialize_index(serialized)
        except Exception as error:
            raise RuntimeError(f"FAISS 索引无法读取，请重建：{self.root}") from error
        if manifest.get("embedding_model") != self.model:
            raise RuntimeError("FAISS 索引模型与当前 Embedding 模型不一致，请重建索引。")
        records = payload.get("records") or {}
        if int(index.ntotal) != len(records):
            raise RuntimeError("FAISS 索引与 metadata 数量不一致，请重建索引。")
        self._index = index
        self._records = {str(key): value for key, value in records.items()}
        self._chunk_numeric_ids = {
            str(record.get("chunk_id")): int(numeric)
            for numeric, record in self._records.items()
            if record.get("chunk_id")
        }
        self._dimension = int(manifest.get("dimension") or getattr(index, "d", 0))
        self._manifest_mtime_ns = self.manifest_path.stat().st_mtime_ns

    def _database_vector_count(self) -> int:
        row = self.database.fetch_one(
            """SELECT COUNT(*) AS total FROM chunks
               WHERE embedding_status='ready' AND embedding_model=?""",
            (self.model,),
        ) or {"total": 0}
        return int(row["total"] or 0)

    def _recover_from_database(self, *, force: bool = False) -> None:
        with self._exclusive_file_lock():
            if not force:
                try:
                    self._load()
                    return
                except RuntimeError:
                    pass
            self._index = None
            self._records = {}
            self._chunk_numeric_ids = {}
            self._dimension = 0
            document_metadata: dict[tuple[str | None, str | None], dict[str, Any]] = {}
            offset = 0
            batch_size = 500
            while True:
                rows = self.database.fetch_all(
                    """SELECT id,document_id,knowledge_document_id,content,page,section,paragraph,
                              chunk_index,content_hash,vector_json,metadata_json
                         FROM chunks
                        WHERE embedding_status='ready' AND embedding_model=? AND vector_json IS NOT NULL
                        ORDER BY id LIMIT ? OFFSET ?""",
                    (self.model, batch_size, offset),
                )
                if not rows:
                    break
                vectors: list[list[float]] = []
                numeric_ids: list[int] = []
                for row in rows:
                    vector = json.loads(row["vector_json"])
                    if not isinstance(vector, list) or not vector:
                        raise RuntimeError("SQLite 中存在无效的 Embedding 向量，无法恢复 FAISS。")
                    self._ensure_index(len(vector))
                    document_key = (row.get("document_id"), row.get("knowledge_document_id"))
                    base = document_metadata.get(document_key)
                    if base is None:
                        base = self._document_metadata(*document_key)
                        document_metadata[document_key] = base
                    metadata = json.loads(row.get("metadata_json") or "{}")
                    metadata.setdefault("file_name", base.get("filename") or Path(str(base.get("file_path") or "")).name)
                    metadata.setdefault("document_name", base.get("document_name") or base.get("title"))
                    metadata.setdefault(
                        "regulation_name",
                        base.get("title") if base.get("document_type") in {"regulations", "internal_rules"} else None,
                    )
                    metadata.setdefault("document_updated_at", base.get("updated_at"))
                    numeric_id = self._numeric_id(str(row["id"]))
                    self._records[str(numeric_id)] = {
                        "numeric_id": numeric_id,
                        "chunk_id": row["id"],
                        "document_id": row.get("knowledge_document_id") or row.get("document_id"),
                        "document_id_private": row.get("document_id"),
                        "knowledge_document_id": row.get("knowledge_document_id"),
                        "content": row["content"],
                        "page": row.get("page"),
                        "paragraph": row.get("paragraph"),
                        "section": row.get("section"),
                        "document_type": base.get("document_type") or metadata.get("document_type") or "user_documents",
                        "title": base.get("title") or base.get("filename") or "未命名文档",
                        "source": base.get("source") or "当前审查材料",
                        "source_url": base.get("source_url"),
                        "date": base.get("publication_date"),
                        "version": base.get("version"),
                        "company": base.get("company"),
                        "owner_user_id": base.get("owner_user_id"),
                        "status": base.get("status") or "active",
                        "kind": base.get("kind"),
                        "metadata": metadata,
                    }
                    self._chunk_numeric_ids[str(row["id"])] = numeric_id
                    vectors.append([float(value) for value in vector])
                    numeric_ids.append(numeric_id)
                matrix = self._np.asarray(vectors, dtype="float32")
                self._faiss.normalize_L2(matrix)
                self._index.add_with_ids(matrix, self._np.asarray(numeric_ids, dtype="int64"))
                offset += len(rows)
            if self._index is None:
                raise RuntimeError(f"FAISS 索引损坏且 SQLite 中没有可恢复向量：{self.root}")
            self._persist()

    def _reload_if_changed(self) -> None:
        current_mtime = self.manifest_path.stat().st_mtime_ns if self.manifest_path.is_file() else 0
        if current_mtime != self._manifest_mtime_ns:
            self._load()

    @contextmanager
    def batch_updates(self):
        with self._lock:
            if self._batch_depth > 0:
                self._batch_depth += 1
                try:
                    yield self
                finally:
                    self._batch_depth -= 1
                return
            with self._exclusive_file_lock(timeout_seconds=86400.0):
                self._reload_if_changed()
                self._batch_depth = 1
                self._batch_dirty = False
                try:
                    yield self
                finally:
                    self._batch_depth = 0
                    if self._batch_dirty:
                        self._persist()
                    self._batch_dirty = False

    @contextmanager
    def _exclusive_file_lock(self, timeout_seconds: float = 120.0):
        self.root.mkdir(parents=True, exist_ok=True)
        started = time.monotonic()
        with self.lock_path.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            if os.name == "nt":
                import msvcrt

                while True:
                    try:
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                        break
                    except OSError:
                        if time.monotonic() - started >= timeout_seconds:
                            raise TimeoutError("等待 FAISS 跨进程写入锁超时。")
                        time.sleep(0.1)
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                return

            import fcntl

            while True:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() - started >= timeout_seconds:
                        raise TimeoutError("等待 FAISS 跨进程写入锁超时。")
                    time.sleep(0.1)
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def _ensure_index(self, dimension: int) -> None:
        if dimension <= 0:
            raise ValueError("Embedding 向量不能为空。")
        if self._index is None:
            self._index = self._faiss.IndexIDMap2(self._faiss.IndexFlatIP(dimension))
            self._dimension = dimension
        elif self._dimension != dimension:
            raise RuntimeError("Embedding 维度已变化，请使用重建索引命令。")

    def _persist(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if self._index is None:
            return
        token = f"{os.getpid()}.{threading.get_ident()}"
        index_tmp = self.index_path.with_name(f"{self.index_path.name}.{token}.tmp")
        metadata_tmp = self.metadata_path.with_name(f"{self.metadata_path.name}.{token}.tmp")
        manifest_tmp = self.manifest_path.with_name(f"{self.manifest_path.name}.{token}.tmp")
        serialized = self._faiss.serialize_index(self._index)
        self._write_durable(index_tmp, serialized.tobytes())
        self._write_durable(
            metadata_tmp,
            json.dumps({"records": self._records}, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        )
        self._write_durable(
            manifest_tmp,
            json.dumps(
                {
                    "format": 1,
                    "embedding_model": self.model,
                    "dimension": self._dimension,
                    "vectors": int(self._index.ntotal),
                    "updated_at": utc_now(),
                },
                ensure_ascii=False,
                indent=2,
            ).encode("utf-8"),
        )
        os.replace(index_tmp, self.index_path)
        os.replace(metadata_tmp, self.metadata_path)
        os.replace(manifest_tmp, self.manifest_path)
        self._manifest_mtime_ns = self.manifest_path.stat().st_mtime_ns

    @staticmethod
    def _write_durable(path: Path, content: bytes) -> None:
        with path.open("wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())

    def _numeric_id(self, chunk_id: str) -> int:
        existing = self._chunk_numeric_ids.get(chunk_id)
        if existing is not None:
            return existing
        candidate = int.from_bytes(hashlib.blake2b(chunk_id.encode("utf-8"), digest_size=8).digest(), "big") & ((1 << 63) - 1)
        candidate = candidate or 1
        while str(candidate) in self._records:
            candidate = (candidate + 1) & ((1 << 63) - 1) or 1
        self._chunk_numeric_ids[chunk_id] = candidate
        return candidate

    def _document_metadata(
        self,
        document_id: str | None,
        knowledge_document_id: str | None,
    ) -> dict[str, Any]:
        if knowledge_document_id:
            row = self.database.fetch_one(
                """SELECT title,document_type,company,source,source_url,publication_date,version,
                          file_path,owner_user_id,status,updated_at
                   FROM knowledge_documents WHERE id=?""",
                (knowledge_document_id,),
            ) or {}
            return {**row, "kind": "knowledge", "document_name": row.get("title")}
        row = self.database.fetch_one(
            """SELECT filename,document_type,owner_user_id,status,updated_at,metadata_json
               FROM documents WHERE id=?""",
            (document_id,),
        ) or {}
        parsed = json.loads(row.get("metadata_json") or "{}")
        return {
            **row,
            "kind": "document",
            "title": parsed.get("title") or row.get("filename"),
            "document_name": parsed.get("title") or row.get("filename"),
            "source": "当前审查材料",
            "source_url": None,
            "publication_date": None,
            "version": None,
        }

    def add_chunks(
        self,
        chunks: Iterable[ChunkRecord],
        vectors: Iterable[list[float]],
        model: str,
        *,
        document_id: str | None = None,
        knowledge_document_id: str | None = None,
    ) -> int:
        chunk_values = list(chunks)
        vector_values = list(vectors)
        if model != self.model:
            raise RuntimeError("FAISS 索引模型与写入模型不一致。")
        if len(chunk_values) != len(vector_values):
            raise ValueError("Chunk 与 Embedding 数量不一致。")
        if not chunk_values:
            return 0
        super().add_chunks(
            chunk_values,
            vector_values,
            model,
            document_id=document_id,
            knowledge_document_id=knowledge_document_id,
        )
        base = self._document_metadata(document_id, knowledge_document_id)
        with self._lock:
            if self._batch_depth > 0:
                self._add_chunk_values(chunk_values, vector_values, base, document_id, knowledge_document_id)
                self._batch_dirty = True
                return len(chunk_values)
            with self._exclusive_file_lock():
                self._reload_if_changed()
                self._add_chunk_values(chunk_values, vector_values, base, document_id, knowledge_document_id)
                self._persist()
        return len(chunk_values)

    def _add_chunk_values(
        self,
        chunk_values: list[ChunkRecord],
        vector_values: list[list[float]],
        base: dict[str, Any],
        document_id: str | None,
        knowledge_document_id: str | None,
    ) -> None:
        self._ensure_index(len(vector_values[0]))
        matrix = self._np.asarray(vector_values, dtype="float32")
        self._faiss.normalize_L2(matrix)
        numeric_ids = [self._numeric_id(chunk.id) for chunk in chunk_values]
        self._index.remove_ids(self._np.asarray(numeric_ids, dtype="int64"))
        for numeric_id, chunk in zip(numeric_ids, chunk_values, strict=True):
            metadata = {**chunk.metadata}
            metadata.setdefault("file_name", base.get("filename") or Path(str(base.get("file_path") or "")).name)
            metadata.setdefault("document_name", base.get("document_name") or base.get("title"))
            metadata.setdefault("regulation_name", base.get("title") if base.get("document_type") in {"regulations", "internal_rules"} else None)
            metadata.setdefault("document_updated_at", base.get("updated_at"))
            self._records[str(numeric_id)] = {
                "numeric_id": numeric_id,
                "chunk_id": chunk.id,
                "document_id": knowledge_document_id or document_id,
                "document_id_private": document_id,
                "knowledge_document_id": knowledge_document_id,
                "content": chunk.content,
                "page": chunk.page,
                "paragraph": chunk.paragraph,
                "section": chunk.section,
                "document_type": base.get("document_type") or metadata.get("document_type") or "user_documents",
                "title": base.get("title") or base.get("filename") or "未命名文档",
                "source": base.get("source") or "当前审查材料",
                "source_url": base.get("source_url"),
                "date": base.get("publication_date"),
                "version": base.get("version"),
                "company": base.get("company"),
                "owner_user_id": base.get("owner_user_id"),
                "status": base.get("status") or "active",
                "kind": base.get("kind"),
                "metadata": metadata,
            }
            self._chunk_numeric_ids[chunk.id] = numeric_id
        self._index.add_with_ids(matrix, self._np.asarray(numeric_ids, dtype="int64"))

    @staticmethod
    def _record_allowed(
        record: dict[str, Any],
        filters: dict[str, Any],
        active_knowledge_ids: set[str],
    ) -> bool:
        user_id = filters.get("user_id")
        if not user_id:
            return False
        if record.get("kind") == "knowledge":
            if str(record.get("knowledge_document_id") or record.get("document_id") or "") not in active_knowledge_ids:
                return False
            owner = record.get("owner_user_id")
            if owner is not None and owner != user_id:
                return False
        else:
            if record.get("status") not in {"active", "parsed"} or record.get("owner_user_id") != user_id:
                return False
        requested_types = set(filters.get("document_types") or [])
        if requested_types and record.get("document_type") not in requested_types:
            return False
        if filters.get("company") and record.get("company") != filters["company"]:
            return False
        if filters.get("document_id") and record.get("document_id") != filters["document_id"]:
            return False
        if filters.get("date_from") and (record.get("date") or "") < filters["date_from"]:
            return False
        if filters.get("date_to") and (record.get("date") or "") > filters["date_to"]:
            return False
        if (
            record.get("document_type") == "regulations"
            and record.get("version") in set(filters.get("exclude_regulation_versions") or [])
        ):
            return False
        return True

    def search(self, query_vector: list[float], top_k: int = 8, threshold: float = 0.08, filters: dict[str, Any] | None = None) -> list[SearchResult]:
        batches = self.search_batch(
            [query_vector], top_k=top_k, threshold=threshold, filters=filters,
        )
        return batches[0] if batches else []

    def search_batch(
        self,
        query_vectors: list[list[float]],
        top_k: int = 8,
        threshold: float = 0.08,
        filters: dict[str, Any] | None = None,
    ) -> list[list[SearchResult]]:
        if not query_vectors:
            return []
        filters = filters or {}
        with self._lock:
            self._reload_if_changed()
            if self._index is None or self._index.ntotal == 0:
                return [[] for _ in query_vectors]
            user_id = filters.get("user_id")
            active_knowledge_ids = {
                str(row["id"])
                for row in self.database.fetch_all(
                    """SELECT id FROM knowledge_documents
                       WHERE status='active' AND (owner_user_id IS NULL OR owner_user_id=?)""",
                    (user_id,),
                )
            } if user_id else set()
            query = self._np.asarray(query_vectors, dtype="float32")
            if query.ndim != 2 or query.shape[1] != self._dimension:
                raise RuntimeError("查询 Embedding 维度与 FAISS 索引不一致，请重建索引。")
            self._faiss.normalize_L2(query)
            target = max(1, min(top_k, 30))
            total = int(self._index.ntotal)
            candidate_count = min(total, max(4096, target * 256))
            unresolved = list(range(len(query_vectors)))
            results_by_query: list[list[SearchResult]] = [[] for _ in query_vectors]

            while unresolved:
                scores, ids = self._index.search(query[unresolved], candidate_count)
                next_unresolved: list[int] = []
                for batch_index, query_index in enumerate(unresolved):
                    results: list[SearchResult] = []
                    for raw_score, numeric_id in zip(scores[batch_index], ids[batch_index], strict=True):
                        record = self._records.get(str(int(numeric_id)))
                        if not record or not self._record_allowed(record, filters, active_knowledge_ids):
                            continue
                        priority = {
                            "company_profile": 1.18, "internal_rules": 1.14, "regulations": 1.10,
                            "cases": 1.04, "announcements": 1.00, "user_documents": 1.08,
                            "drafting_materials": 0.96,
                        }.get(record["document_type"], 1.0)
                        score = float(raw_score) * priority
                        if score < threshold:
                            continue
                        results.append(SearchResult(
                            chunk_id=record["chunk_id"], document_id=record["document_id"],
                            content=record["content"], title=record["title"], source=record["source"],
                            date=record.get("date"), page=record.get("page"),
                            paragraph=record.get("paragraph"), section=record.get("section"),
                            document_type=record["document_type"], score=score,
                            source_url=record.get("source_url"), version=record.get("version"),
                            metadata=record.get("metadata") or {},
                        ))
                    results.sort(key=lambda item: item.score, reverse=True)
                    results_by_query[query_index] = results[:target]
                    if len(results) < target and candidate_count < total:
                        next_unresolved.append(query_index)
                if not next_unresolved or candidate_count >= total:
                    break
                candidate_count = min(total, candidate_count * 4)
                unresolved = next_unresolved
            return results_by_query

    def delete_chunks(self, document_id: str) -> None:
        super().delete_chunks(document_id)
        with self._lock:
            if self._batch_depth > 0:
                if self._remove_document_records(document_id):
                    self._batch_dirty = True
                return
            with self._exclusive_file_lock():
                self._reload_if_changed()
                if self._remove_document_records(document_id):
                    self._persist()

    def _remove_document_records(self, document_id: str) -> bool:
        numeric_ids = [
            int(numeric) for numeric, record in self._records.items()
            if record.get("document_id") == document_id
        ]
        if not numeric_ids or self._index is None:
            return False
        self._index.remove_ids(self._np.asarray(numeric_ids, dtype="int64"))
        for numeric_id in numeric_ids:
            removed = self._records.pop(str(numeric_id), None)
            if removed and removed.get("chunk_id"):
                self._chunk_numeric_ids.pop(str(removed["chunk_id"]), None)
        return True


class PgVectorStore(VectorStore):
    """pgvector implementation selected explicitly for production deployments."""

    def __init__(self, url: str, database: Database):
        if not url:
            raise RuntimeError("VECTOR_DB_URL 不能为空。")
        try:
            import psycopg  # type: ignore[import-not-found]
            from psycopg.rows import dict_row  # type: ignore[import-not-found]
        except ImportError as error:
            raise RuntimeError("VECTOR_BACKEND=pgvector 需要安装 psycopg[binary]。") from error
        self.url = url
        self.database = database
        self._psycopg = psycopg
        self._dict_row = dict_row
        try:
            with self._connection() as connection:
                connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
                connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS compliance_vectors (
                        chunk_id TEXT PRIMARY KEY,
                        document_id TEXT,
                        knowledge_document_id TEXT,
                        content TEXT NOT NULL,
                        page INTEGER,
                        section TEXT,
                        paragraph INTEGER,
                        chunk_index INTEGER NOT NULL,
                        content_hash TEXT NOT NULL,
                        embedding_model TEXT NOT NULL,
                        embedding vector NOT NULL,
                        metadata_json JSONB NOT NULL DEFAULT '{}'::jsonb,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_compliance_vectors_document ON compliance_vectors(document_id, knowledge_document_id)"
                )
                connection.execute(
                    "CREATE INDEX IF NOT EXISTS idx_compliance_vectors_hash ON compliance_vectors(content_hash, embedding_model)"
                )
        except Exception as error:
            raise RuntimeError("无法初始化 PostgreSQL/pgvector，请检查连接地址和 vector 扩展。") from error

    def _connection(self):
        return self._psycopg.connect(self.url, row_factory=self._dict_row)

    @staticmethod
    def _vector_literal(vector: list[float]) -> str:
        if not vector:
            raise ValueError("Embedding 向量不能为空。")
        return "[" + ",".join(format(float(value), ".10g") for value in vector) + "]"

    def add_chunks(
        self,
        chunks: Iterable[ChunkRecord],
        vectors: Iterable[list[float]],
        model: str,
        *,
        document_id: str | None = None,
        knowledge_document_id: str | None = None,
    ) -> int:
        rows = [
            (
                chunk.id, document_id, knowledge_document_id, chunk.content, chunk.page, chunk.section,
                chunk.paragraph, chunk.chunk_index, chunk.content_hash, model, self._vector_literal(vector),
                json.dumps(chunk.metadata, ensure_ascii=False),
            )
            for chunk, vector in zip(chunks, vectors, strict=True)
        ]
        if not rows:
            return 0
        with self._connection() as connection:
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO compliance_vectors (
                        chunk_id,document_id,knowledge_document_id,content,page,section,paragraph,
                        chunk_index,content_hash,embedding_model,embedding,metadata_json
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s::jsonb)
                    ON CONFLICT(chunk_id) DO UPDATE SET
                        content=EXCLUDED.content,page=EXCLUDED.page,section=EXCLUDED.section,
                        paragraph=EXCLUDED.paragraph,chunk_index=EXCLUDED.chunk_index,
                        content_hash=EXCLUDED.content_hash,embedding_model=EXCLUDED.embedding_model,
                        embedding=EXCLUDED.embedding,metadata_json=EXCLUDED.metadata_json,updated_at=NOW()
                    """,
                    rows,
                )
        return len(rows)

    def _citation_metadata(self, row: dict[str, Any]) -> dict[str, Any]:
        knowledge_id = row.get("knowledge_document_id")
        if knowledge_id:
            metadata = self.database.fetch_one(
                """SELECT title,source,source_url,publication_date,version,document_type,status,owner_user_id
                   FROM knowledge_documents WHERE id=?""",
                (knowledge_id,),
            ) or {}
            if metadata.get("status") != "active":
                return {}
            return metadata
        document = self.database.fetch_one(
            "SELECT filename AS title,document_type,owner_user_id FROM documents WHERE id=?",
            (row.get("document_id"),),
        ) or {}
        return {**document, "source": "当前审查材料"}

    def search(self, query_vector: list[float], top_k: int = 8, threshold: float = 0.08, filters: dict[str, Any] | None = None) -> list[SearchResult]:
        filters = filters or {}
        user_id = filters.get("user_id")
        if not user_id:
            return []
        clauses = ["embedding_model IS NOT NULL"]
        params: list[Any] = [self._vector_literal(query_vector)]
        requested_types = list(filters.get("document_types") or [])
        knowledge_conditions = ["status='active'", "(owner_user_id IS NULL OR owner_user_id=?)"]
        knowledge_params: list[Any] = [user_id]
        document_conditions = ["owner_user_id=?"]
        document_params: list[Any] = [user_id]
        if requested_types:
            placeholders = ",".join("?" for _ in requested_types)
            knowledge_conditions.append(f"document_type IN ({placeholders})")
            document_conditions.append(f"document_type IN ({placeholders})")
            knowledge_params.extend(requested_types)
            document_params.extend(requested_types)
        if filters.get("company"):
            knowledge_conditions.append("company=?")
            knowledge_params.append(filters["company"])
            document_conditions.append("1=0")
        excluded_versions = list(filters.get("exclude_regulation_versions") or [])
        if excluded_versions:
            placeholders = ",".join("?" for _ in excluded_versions)
            knowledge_conditions.append(
                f"(document_type<>'regulations' OR COALESCE(version,'') NOT IN ({placeholders}))"
            )
            knowledge_params.extend(excluded_versions)
        allowed_knowledge = [
            row["id"] for row in self.database.fetch_all(
                f"SELECT id FROM knowledge_documents WHERE {' AND '.join(knowledge_conditions)}",
                knowledge_params,
            )
        ]
        allowed_documents = [
            row["id"] for row in self.database.fetch_all(
                f"SELECT id FROM documents WHERE {' AND '.join(document_conditions)}",
                document_params,
            )
        ]
        requested_document_id = filters.get("document_id")
        if requested_document_id:
            allowed_knowledge = [item for item in allowed_knowledge if item == requested_document_id]
            allowed_documents = [item for item in allowed_documents if item == requested_document_id]
        if not allowed_knowledge and not allowed_documents:
            return []
        scope_clauses = []
        if allowed_knowledge:
            scope_clauses.append("knowledge_document_id = ANY(%s)")
            params.append(allowed_knowledge)
        if allowed_documents:
            scope_clauses.append("document_id = ANY(%s)")
            params.append(allowed_documents)
        clauses.append("(" + " OR ".join(scope_clauses) + ")")
        params.extend([self._vector_literal(query_vector), max(20, min(top_k * 8, 200))])
        sql = f"""
            SELECT *,1-(embedding <=> %s::vector) AS raw_score
            FROM compliance_vectors WHERE {' AND '.join(clauses)}
            ORDER BY embedding <=> %s::vector LIMIT %s
        """
        with self._connection() as connection:
            rows = list(connection.execute(sql, params).fetchall())
        results: list[SearchResult] = []
        requested_types = set(requested_types)
        for row in rows:
            citation = self._citation_metadata(row)
            if not citation:
                continue
            owner_user_id = citation.get("owner_user_id")
            if row.get("knowledge_document_id"):
                if owner_user_id is not None and owner_user_id != user_id:
                    continue
            elif not user_id or owner_user_id != user_id:
                continue
            document_type = citation.get("document_type") or row.get("metadata_json", {}).get("document_type", "user_documents")
            if requested_types and document_type not in requested_types:
                continue
            if filters.get("company") and row.get("knowledge_document_id"):
                company = self.database.fetch_one("SELECT company FROM knowledge_documents WHERE id=?", (row["knowledge_document_id"],)) or {}
                if company.get("company") != filters["company"]:
                    continue
            priority = {
                "company_profile": 1.18, "internal_rules": 1.14,
                "regulations": 1.10, "cases": 1.04, "announcements": 1.0,
                "drafting_materials": 0.96, "user_documents": 1.08,
            }.get(document_type, 1.0)
            score = float(row["raw_score"]) * priority
            if score < threshold:
                continue
            metadata = row.get("metadata_json") or {}
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            results.append(SearchResult(
                chunk_id=row["chunk_id"], document_id=row.get("knowledge_document_id") or row.get("document_id"),
                content=row["content"], title=citation.get("title") or "未命名文档",
                source=citation.get("source") or "当前审查材料", date=citation.get("publication_date"),
                page=row.get("page"), paragraph=row.get("paragraph"), section=row.get("section"), document_type=document_type, score=score,
                source_url=citation.get("source_url"), version=citation.get("version"), metadata=metadata,
            ))
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:max(1, min(top_k, 30))]

    def keyword_search(
        self,
        query: str,
        top_k: int = 8,
        threshold: float = 0.02,
        filters: dict[str, Any] | None = None,
    ) -> list[SearchResult]:
        filters = filters or {}
        user_id = filters.get("user_id")
        if not query.strip() or not user_id:
            return []
        query_features = SQLiteVectorStore._keyword_features(query)
        with self._connection() as connection:
            rows = list(connection.execute("SELECT * FROM compliance_vectors").fetchall())
        results: list[SearchResult] = []
        requested_types = set(filters.get("document_types") or [])
        for row in rows:
            row = dict(row)
            citation = self._citation_metadata(row)
            if not citation:
                continue
            owner = citation.get("owner_user_id")
            if row.get("knowledge_document_id"):
                if owner is not None and owner != user_id:
                    continue
            elif owner != user_id:
                continue
            document_id = row.get("knowledge_document_id") or row.get("document_id")
            if filters.get("document_id") and document_id != filters["document_id"]:
                continue
            document_type = citation.get("document_type") or "user_documents"
            if requested_types and document_type not in requested_types:
                continue
            if (
                document_type == "regulations"
                and citation.get("version") in set(filters.get("exclude_regulation_versions") or [])
            ):
                continue
            content_features = SQLiteVectorStore._keyword_features(row.get("content") or "")
            score = len(query_features & content_features) / max(1, len(query_features))
            if score < threshold:
                continue
            metadata = row.get("metadata_json") or {}
            if isinstance(metadata, str):
                metadata = json.loads(metadata)
            results.append(SearchResult(
                chunk_id=row["chunk_id"], document_id=document_id, content=row["content"],
                title=citation.get("title") or "未命名文档", source=citation.get("source") or "当前审查材料",
                date=citation.get("publication_date"), page=row.get("page"), paragraph=row.get("paragraph"),
                section=row.get("section"), document_type=document_type, score=score,
                source_url=citation.get("source_url"), version=citation.get("version"), metadata=metadata,
            ))
        results.sort(key=lambda item: item.score, reverse=True)
        return results[:max(1, min(top_k, 30))]

    def delete_chunks(self, document_id: str) -> None:
        with self._connection() as connection:
            connection.execute(
                "DELETE FROM compliance_vectors WHERE document_id=%s OR knowledge_document_id=%s",
                (document_id, document_id),
            )

    def exists(self, content_hash: str, model: str) -> bool:
        with self._connection() as connection:
            return connection.execute(
                "SELECT 1 FROM compliance_vectors WHERE content_hash=%s AND embedding_model=%s LIMIT 1",
                (content_hash, model),
            ).fetchone() is not None

    def get_by_document(self, document_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            return list(connection.execute(
                "SELECT * FROM compliance_vectors WHERE document_id=%s OR knowledge_document_id=%s ORDER BY chunk_index",
                (document_id, document_id),
            ).fetchall())

    def get_by_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM compliance_vectors WHERE chunk_id=%s", (chunk_id,)).fetchone()
            return dict(row) if row else None
