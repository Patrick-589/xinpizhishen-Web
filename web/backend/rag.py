from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date
from typing import Any, Iterable

from .embeddings import EmbeddingProvider
from .structured_facts import parse_as_of_date, source_priority
from .vector_store import SearchResult, VectorStore


INSUFFICIENT_EVIDENCE = "当前知识库未检索到足够直接依据，请人工进一步确认。"
REPEALED_REGULATION_VERSIONS = {"repealed-list", "已被废止"}


@dataclass(frozen=True)
class RAGContext:
    query: str
    results: list[SearchResult]

    @property
    def citations(self) -> list[dict[str, Any]]:
        return [result.citation() for result in self.results]

    @property
    def context_text(self) -> str:
        parts = []
        for index, result in enumerate(self.results, start=1):
            parts.append(
                f"[来源{index}] 标题：{result.title}\n类型：{result.document_type}\n"
                f"页码：{result.page or '待确认'}\n章节：{result.section or '待确认'}\n"
                f"Chunk ID：{result.chunk_id}\n原文：{result.content}"
            )
        return "\n\n".join(parts)


class RAGService:
    def __init__(
        self,
        embedding_provider: EmbeddingProvider,
        vector_store: VectorStore,
        retrieval_mode: str = "semantic",
    ):
        self.embedding_provider = embedding_provider
        self.vector_store = vector_store
        self.retrieval_mode = retrieval_mode

    @staticmethod
    def _rerank(query: str, results: list[SearchResult]) -> list[SearchResult]:
        """Combine relevance, disclosure recency and source authority locally."""
        if not results:
            return []
        reference_text = parse_as_of_date(query) or date.today().isoformat()
        try:
            reference_date = date.fromisoformat(reference_text[:10])
        except ValueError:
            reference_date = date.today()
        current_query = bool(any(term in query for term in ("目前", "当前", "最新", "截至", "进展", "状态")))
        relevance_weight, recency_weight, authority_weight = (
            (0.55, 0.30, 0.15) if current_query else (0.68, 0.14, 0.18)
        )
        max_raw = max(max(float(result.score), 0.0) for result in results) or 1.0
        reranked: list[SearchResult] = []
        for result in results:
            relevance = max(0.0, min(float(result.score) / max_raw, 1.0))
            recency = 0.35
            if result.date:
                try:
                    disclosed = date.fromisoformat(str(result.date)[:10])
                    age_days = max(0, (reference_date - disclosed).days)
                    recency = max(0.0, 1.0 - age_days / 3650.0)
                    if disclosed > reference_date:
                        recency = 0.0
                except ValueError:
                    recency = 0.35
            authority = source_priority(
                result.document_type, result.title, result.source,
                str((result.metadata or {}).get("source_type") or ""),
            ) / 100.0
            combined = relevance * relevance_weight + recency * recency_weight + authority * authority_weight
            metadata = {
                **(result.metadata or {}),
                "retrieval_raw_score": round(float(result.score), 6),
                "retrieval_relevance_score": round(relevance, 6),
                "retrieval_recency_score": round(recency, 6),
                "source_priority": round(authority * 100),
                "retrieval_combined_score": round(combined, 6),
                "retrieval_as_of_date": reference_date.isoformat(),
            }
            reranked.append(replace(result, score=combined, metadata=metadata))
        reranked.sort(
            key=lambda item: (
                item.score,
                str(item.date or ""),
                int((item.metadata or {}).get("source_priority") or 0),
            ),
            reverse=True,
        )
        return reranked

    def _search(
        self,
        query: str,
        *,
        top_k: int,
        threshold: float,
        filters: dict[str, Any],
        query_vector: list[float] | None = None,
    ) -> list[SearchResult]:
        if self.retrieval_mode == "keyword":
            return self.vector_store.keyword_search(query, top_k=top_k, threshold=0.02, filters=filters)
        vector = query_vector or self.embedding_provider.embed_text(query)
        semantic = self.vector_store.search(vector, top_k=top_k, threshold=threshold, filters=filters)
        if self.retrieval_mode != "hybrid":
            return semantic
        keyword = self.vector_store.keyword_search(query, top_k=top_k, threshold=0.02, filters=filters)
        by_id = {item.chunk_id: item for item in semantic + keyword}
        reciprocal_scores: dict[str, float] = {}
        for weight, values in ((0.7, semantic), (0.3, keyword)):
            for rank, item in enumerate(values, start=1):
                reciprocal_scores[item.chunk_id] = reciprocal_scores.get(item.chunk_id, 0.0) + weight / (20 + rank)
        ranked = sorted(by_id.values(), key=lambda item: reciprocal_scores.get(item.chunk_id, 0.0), reverse=True)
        maximum = max(reciprocal_scores.values(), default=1.0)
        return [
            replace(item, score=reciprocal_scores[item.chunk_id] / maximum)
            for item in ranked[:top_k]
        ]

    def embed_queries(self, queries: Iterable[str]) -> dict[str, list[float]]:
        """Embed unique review queries in one local model batch."""
        if self.retrieval_mode == "keyword":
            return {}
        values = list(dict.fromkeys(query.strip() for query in queries if query.strip()))
        vectors = self.embedding_provider.embed_batch(values)
        return dict(zip(values, vectors, strict=True))

    def retrieve_many(
        self,
        queries: Iterable[str],
        *,
        top_k: int = 8,
        threshold: float = 0.08,
        document_types: list[str] | None = None,
        current_regulations_only: bool = False,
        user_id: str,
        query_vectors: dict[str, list[float]] | None = None,
    ) -> dict[str, RAGContext]:
        """Retrieve a shared scope for multiple queries with one FAISS batch search."""
        values = list(dict.fromkeys(query.strip() for query in queries if query.strip()))
        if not values:
            return {}
        filters: dict[str, Any] = {"user_id": user_id}
        if document_types:
            filters["document_types"] = document_types
        if current_regulations_only:
            filters["exclude_regulation_versions"] = sorted(REPEALED_REGULATION_VERSIONS)
        candidate_k = min(30, max(top_k * 4, top_k))
        if self.retrieval_mode == "keyword":
            return {
                query: RAGContext(
                    query,
                    self._rerank(
                        query,
                        self.vector_store.keyword_search(
                            query, top_k=candidate_k, threshold=0.02, filters=filters,
                        ),
                    )[:top_k],
                )
                for query in values
            }
        vectors = query_vectors or self.embed_queries(values)
        ordered_vectors = [vectors[query] for query in values]
        semantic_batches = self.vector_store.search_batch(
            ordered_vectors, top_k=candidate_k, threshold=threshold, filters=filters,
        )
        contexts: dict[str, RAGContext] = {}
        for query, semantic in zip(values, semantic_batches, strict=True):
            results = semantic
            if self.retrieval_mode == "hybrid":
                keyword = self.vector_store.keyword_search(
                    query, top_k=candidate_k, threshold=0.02, filters=filters,
                )
                by_id = {item.chunk_id: item for item in semantic + keyword}
                reciprocal_scores: dict[str, float] = {}
                for weight, candidates in ((0.7, semantic), (0.3, keyword)):
                    for rank, item in enumerate(candidates, start=1):
                        reciprocal_scores[item.chunk_id] = (
                            reciprocal_scores.get(item.chunk_id, 0.0) + weight / (20 + rank)
                        )
                ranked = sorted(
                    by_id.values(),
                    key=lambda item: reciprocal_scores.get(item.chunk_id, 0.0),
                    reverse=True,
                )
                maximum = max(reciprocal_scores.values(), default=1.0)
                results = [
                    replace(item, score=reciprocal_scores[item.chunk_id] / maximum)
                    for item in ranked[:candidate_k]
                ]
            contexts[query] = RAGContext(query, self._rerank(query, results)[:top_k])
        return contexts

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = 8,
        threshold: float = 0.08,
        document_types: list[str] | None = None,
        company: str | None = None,
        task_document_id: str | None = None,
        current_regulations_only: bool = False,
        user_id: str,
        query_vector: list[float] | None = None,
    ) -> RAGContext:
        query = query.strip()
        if not query:
            return RAGContext(query, [])
        filters: dict[str, Any] = {}
        if document_types:
            filters["document_types"] = document_types
        if company:
            filters["company"] = company
        if current_regulations_only:
            filters["exclude_regulation_versions"] = sorted(REPEALED_REGULATION_VERSIONS)
        filters["user_id"] = user_id
        candidate_k = min(30, max(top_k * 4, top_k))
        results = self._search(
            query,
            top_k=candidate_k,
            threshold=threshold,
            filters=filters,
            query_vector=query_vector,
        )
        if task_document_id:
            task_results = self._search(
                query,
                top_k=max(2, top_k // 2),
                threshold=threshold,
                filters={"document_id": task_document_id, "user_id": user_id},
                query_vector=query_vector,
            )
            if not task_results:
                # Fast-review mode may still be building the uploaded document's
                # semantic vectors. Its persisted chunks remain immediately
                # searchable without an external service.
                task_results = self.vector_store.keyword_search(
                    query,
                    top_k=max(2, top_k // 2),
                    threshold=0.02,
                    filters={"document_id": task_document_id, "user_id": user_id},
                )
            seen = {result.chunk_id for result in task_results}
            results = task_results + [result for result in results if result.chunk_id not in seen]
            results = results[:candidate_k]
        return RAGContext(query, self._rerank(query, results)[:top_k])

    def retrieve_keyword(
        self,
        query: str,
        *,
        top_k: int = 8,
        threshold: float = 0.02,
        document_types: list[str] | None = None,
        current_regulations_only: bool = False,
        user_id: str,
    ) -> RAGContext:
        query = query.strip()
        if not query:
            return RAGContext(query, [])
        filters: dict[str, Any] = {"user_id": user_id}
        if document_types:
            filters["document_types"] = document_types
        if current_regulations_only:
            filters["exclude_regulation_versions"] = sorted(REPEALED_REGULATION_VERSIONS)
        candidate_k = min(30, max(top_k * 4, top_k))
        results = self.vector_store.keyword_search(
            query,
            top_k=candidate_k,
            threshold=threshold,
            filters=filters,
        )
        return RAGContext(query, self._rerank(query, results)[:top_k])

    @staticmethod
    def local_answer(context: RAGContext) -> dict[str, Any]:
        if not context.results:
            return {"answer": INSUFFICIENT_EVIDENCE, "source_documents": []}
        excerpts = []
        for result in context.results[:5]:
            location = f"第{result.page}页" if result.page else "页码待确认"
            section = f"，{result.section}" if result.section else ""
            excerpts.append(f"《{result.title}》（{location}{section}）：\n{result.content}")
        answer = "\n\n".join(excerpts)
        answer += "\n\n当前处于本地知识检索模式，仅提供资料检索和引用，不提供 AI 推理分析。如需智能分析，请切换 AI 增强模式。"
        return {"answer": answer, "source_documents": context.citations}
