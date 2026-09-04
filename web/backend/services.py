from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
import uuid
from pathlib import Path
from typing import Any, Callable

from .ai import AIProvider, AIResult, AIServiceError, LocalRagProvider, create_ai_provider
from .casting import review_casting
from .chunking import ChunkRecord, SecuritiesChunker
from .config import Settings
from .database import Database, utc_now
from .docx_comments import create_annotated_docx
from .drafting import DOCUMENT_TYPES, _select_company_style_sources, build_docx, build_draft
from .embeddings import EmbeddingProvider, create_embedding_provider
from .financial_audit import FinancialAuditEngine
from .financial_audit.engine import ENGINE_VERSION as FINANCIAL_AUDIT_ENGINE_VERSION
from .financial_audit.report import generate_reports
from .meeting_case_compare import MeetingCaseComparator, baseline_score
from .meeting_case_library import (
    MEETING_DOCUMENT_TYPES,
    infer_case_role,
    infer_meeting_kind,
    extract_meeting_details,
    meeting_term,
)
from .parsers import PARSER_VERSION, DocumentParseError, ParsedBlock, ParsedDocument, parse_document
from .ocr import LocalOCRService
from .periodic_compare import compare_periodic_report
from .rag import REPEALED_REGULATION_VERSIONS, RAGContext, RAGService
from .rule_compare import compare_documents as compare_rule_documents
from .rules import DeterministicRuleEngine
from .summary_compare import compare_summary_to_original
from .structured_facts import COMPANY_NAME, StructuredFactEngine
from .vector_store import FaissVectorStore, PgVectorStore, SQLiteVectorStore, SearchResult, VectorStore


KNOWLEDGE_TYPES = {
    "company_profile",
    "regulations",
    "internal_rules",
    "announcements",
    "cases",
    # Shared company-authored templates and prior drafting materials. These
    # sources guide wording and structure only; they are never treated as
    # regulatory authority by review retrieval.
    "drafting_materials",
    "user_documents",
}

AUTO_SELECTION = "auto"
DEFAULT_TASK_TYPE = "临时公告通用审查"
DEFAULT_RULE_PACK = "上市公司信披基础包"
RULE_PACK_BY_TASK_TYPE = {
    DEFAULT_TASK_TYPE: DEFAULT_RULE_PACK,
    "关联交易专项审查": "关联交易专项规则包",
    "定期报告一致性审查": "创业板定期报告规则包",
    "重大事项披露审查": "创业板持续监管规则包",
    "会议决议与公告审查": "已确认案例与现行规则包",
}

REVIEW_CLASSIFIERS = (
    {
        "key": "meeting_governance",
        "task_type": "会议决议与公告审查",
        "rule_pack": "已确认案例与现行规则包",
        "filename_terms": ("董事会决议", "股东会决议", "股东会通知", "会议决议", "决议公告"),
        "title_terms": ("董事会决议", "股东会决议", "股东会通知", "董事会会议"),
        "body_terms": ("同意", "反对", "弃权", "回避表决", "提交股东会审议", "董事会会议"),
    },
    {
        "key": "periodic_report",
        "task_type": "定期报告一致性审查",
        "rule_pack": "创业板定期报告规则包",
        "filename_terms": (
            "年度报告", "半年度报告", "季度报告", "第一季度报告", "第三季度报告", "定期报告",
        ),
        "title_terms": (
            "年度报告", "半年度报告", "季度报告", "第一节 重要提示", "公司简介和主要财务指标",
        ),
        "body_terms": (
            "定期报告", "报告期末", "管理层讨论与分析", "财务报表", "董监高书面确认意见",
        ),
    },
    {
        "key": "related_transaction",
        "task_type": "关联交易专项审查",
        "rule_pack": "关联交易专项规则包",
        "filename_terms": ("关联交易", "关联方", "关联关系"),
        "title_terms": ("关联交易", "关联方", "关联关系", "回避表决"),
        "body_terms": ("构成关联交易", "关联董事回避表决", "关联股东回避表决", "关联关系"),
    },
    {
        "key": "material_matter",
        "task_type": "重大事项披露审查",
        "rule_pack": "创业板持续监管规则包",
        "filename_terms": (
            "股权转让", "股权交易", "对外投资", "增资", "对外担保", "重大合同", "合同", "资产重组",
            "购买资产", "出售资产", "回购股份", "股份回购", "重大事项",
        ),
        "title_terms": (
            "股权转让", "股权交易", "对外投资", "增资", "对外担保", "重大合同", "资产重组",
            "购买资产", "出售资产", "回购股份", "股份回购", "重大事项",
        ),
        "body_terms": (
            "交易标的", "交易对方", "交易金额", "对外投资", "对外担保", "股权转让", "增资协议",
            "重大合同", "合同金额", "合同标的", "购买资产", "出售资产", "回购股份",
        ),
    },
)


PERIODIC_REPORT_FILENAME_TERMS = (
    "年度报告",
    "半年度报告",
    "季度报告",
    "第一季度报告",
    "第三季度报告",
    "定期报告",
)

MEETING_DOCUMENT_FILENAME_PATTERNS = (
    re.compile(r"董事会.*(?:会议)?决议(?:公告)?"),
    re.compile(r"股东(?:会|大会).*(?:通知|决议(?:公告)?)"),
    re.compile(r"(?:审计|薪酬与考核|提名|战略|可持续发展|ESG)委员会.*(?:会议)?决议"),
    re.compile(r"专门委员会.*(?:会议)?决议"),
)


def _normalized_filename(filename: str) -> str:
    return re.sub(r"[\s_\-—]+", "", Path(str(filename or "")).stem)


def is_periodic_report_document(filename: str) -> bool:
    normalized = _normalized_filename(filename)
    return any(term in normalized for term in PERIODIC_REPORT_FILENAME_TERMS)


def is_meeting_governance_document(filename: str) -> bool:
    """Only explicit meeting-document filenames may activate governance checks."""
    normalized = _normalized_filename(filename)
    if is_periodic_report_document(filename):
        return False
    return any(pattern.search(normalized) for pattern in MEETING_DOCUMENT_FILENAME_PATTERNS)


def detect_review_configuration(filename: str, parsed: ParsedDocument) -> dict[str, Any]:
    """Classify locally; uncertain documents deliberately fall back to the general pack."""
    normalized_filename = _normalized_filename(filename)
    title_text = "\n".join(parsed.paragraphs[:8])[:5000]
    body_text = "\n".join(parsed.paragraphs)[:100000]

    # File type has priority over body keywords. Periodic reports routinely mention
    # boards, shareholder meetings and recusal, but are not meeting documents.
    if is_periodic_report_document(filename):
        return {
            "detectedCategory": "periodic_report",
            "taskType": "定期报告一致性审查",
            "rulePack": "创业板定期报告规则包",
            "confidence": 0.98,
            "reasons": ["文件名明确属于定期报告，已排除会议程序专项审查"],
            "needsReview": False,
        }
    if is_meeting_governance_document(filename):
        return {
            "detectedCategory": "meeting_governance",
            "taskType": "会议决议与公告审查",
            "rulePack": "已确认案例与现行规则包",
            "confidence": 0.98,
            "reasons": ["文件名明确属于会议决议、通知或公告"],
            "needsReview": False,
        }

    scored: list[dict[str, Any]] = []
    for classifier in REVIEW_CLASSIFIERS:
        if classifier["key"] == "meeting_governance":
            continue
        filename_hits = [term for term in classifier["filename_terms"] if term in normalized_filename]
        title_hits = [term for term in classifier["title_terms"] if term in title_text]
        body_hits = [term for term in classifier["body_terms"] if term in body_text]
        score = len(filename_hits) * 8 + len(title_hits) * 4 + len(body_hits)
        reasons = []
        if filename_hits:
            reasons.append(f"文件名包含“{'、'.join(filename_hits[:2])}”")
        if title_hits:
            reasons.append(f"标题或开头包含“{'、'.join(title_hits[:2])}”")
        if body_hits:
            reasons.append(f"正文包含“{'、'.join(body_hits[:2])}”")
        scored.append({**classifier, "score": score, "reasons": reasons})

    ranked = sorted(scored, key=lambda item: item["score"], reverse=True)
    best = ranked[0]
    runner_up_score = ranked[1]["score"] if len(ranked) > 1 else 0
    margin = best["score"] - runner_up_score
    confident = best["score"] >= 8 and margin >= 3
    if not confident:
        reason = "未发现足以确定专项类型的文件名或正文特征"
        if best["score"] > 0 and margin < 3:
            reason = "文档同时包含多类事项特征，无法可靠确定单一专项类型"
        return {
            "detectedCategory": "general",
            "taskType": DEFAULT_TASK_TYPE,
            "rulePack": DEFAULT_RULE_PACK,
            "confidence": 0.42 if best["score"] else 0.30,
            "reasons": [reason, "已采用通用信披规则包，建议人工复核适用范围"],
            "needsReview": True,
        }

    confidence = min(0.98, 0.72 + min(best["score"], 24) / 100 + min(margin, 10) / 100)
    return {
        "detectedCategory": best["key"],
        "taskType": best["task_type"],
        "rulePack": best["rule_pack"],
        "confidence": round(confidence, 2),
        "reasons": best["reasons"][:3],
        "needsReview": confidence < 0.80,
    }


def resolve_review_configuration(
    requested_task_type: str,
    requested_rule_pack: str,
    detected: dict[str, Any],
) -> dict[str, Any]:
    requested_task_type = str(requested_task_type or AUTO_SELECTION).strip()
    requested_rule_pack = str(requested_rule_pack or AUTO_SELECTION).strip()
    task_is_auto = requested_task_type == AUTO_SELECTION
    rule_is_auto = requested_rule_pack == AUTO_SELECTION
    final_task_type = detected["taskType"] if task_is_auto else requested_task_type
    final_rule_pack = (
        RULE_PACK_BY_TASK_TYPE.get(final_task_type, detected["rulePack"])
        if rule_is_auto else requested_rule_pack
    )
    if task_is_auto and rule_is_auto:
        method = "automatic"
    elif not task_is_auto and not rule_is_auto:
        method = "manual"
    else:
        method = "mixed"
    reasons = list(detected.get("reasons", []))
    if not task_is_auto:
        reasons.insert(0, "审查类型由用户手动选择")
    if not rule_is_auto:
        reasons.insert(0, "规则包由用户手动选择")
    return {
        **detected,
        "detectedTaskType": detected["taskType"],
        "detectedRulePack": detected["rulePack"],
        "taskType": final_task_type,
        "rulePack": final_rule_pack,
        "requestedTaskType": requested_task_type,
        "requestedRulePack": requested_rule_pack,
        "taskTypeSource": "automatic" if task_is_auto else "manual",
        "rulePackSource": "automatic" if rule_is_auto else "manual",
        "method": method,
        "reasons": reasons[:4],
        "needsReview": bool(detected.get("needsReview")) and (task_is_auto or rule_is_auto),
    }


def safe_filename(value: str) -> str:
    name = Path(value).name.strip()
    name = re.sub(r"[^\w\-.()\u4e00-\u9fff]+", "_", name, flags=re.UNICODE)
    return name[:160] or "document"


def _infer_draft_document_type(requested: str, subject: str, facts: str, requirements: str) -> str:
    """Infer a drafting type from a direct natural-language request."""
    requested = str(requested or "").strip()
    if requested not in {"", AUTO_SELECTION, "temporary_announcement"}:
        return requested
    prompt = "".join((subject, facts, requirements)).replace(" ", "")
    # Specific meeting bodies win over the generic "会议记录/议案" cues.
    # This makes automatic drafting select the right speaking perspective.
    if "签到" in prompt:
        return "meeting_sign_in"
    if "主要议案" in prompt or "议案概述" in prompt:
        return "meeting_agenda_summary"
    if "授权委托" in prompt or "委托书" in prompt:
        return "proxy_authorization"
    if "法律意见书" in prompt or "法律意见" in prompt:
        return "legal_opinion"
    if "表决票" in prompt:
        return "ballot"
    if "总经理会议" in prompt or "总经理办公会" in prompt:
        return "general_manager_meeting"
    if "独立董事" in prompt and ("专门会议" in prompt or "决议" in prompt):
        return "independent_director_resolution"
    if "审计委员会" in prompt and "决议" in prompt:
        return "committee_resolution"
    if "审计委员会" in prompt and ("记录" in prompt or "发言" in prompt):
        return "committee_record"
    if "董事会" in prompt and "决议" in prompt:
        return "board_resolution"
    if ("股东会" in prompt or "股东大会" in prompt) and "决议" in prompt:
        return "shareholder_resolution"
    meeting_cues = (
        ("会议记录", "记录"),
        ("会议发言", "议案"),
        ("会议议案",),
        ("会议通知",),
        ("会议决议",),
        ("审计委员会", "发言"),
        ("审计委员会", "议案"),
        ("独立董事", "专门会议"),
        ("表决票",),
    )
    if any(all(cue in prompt for cue in group) for group in meeting_cues):
        if "通知" in prompt:
            return "meeting_notice"
        if "议案" in prompt and "记录" not in prompt and "发言" not in prompt:
            return "meeting_proposal"
        if "独立董事" in prompt and ("决议" in prompt or "专门会议" in prompt):
            return "independent_director_resolution"
        if "审计委员会" in prompt and "决议" in prompt:
            return "committee_resolution"
        if "审计委员会" in prompt or "委员会" in prompt:
            return "committee_record"
        if "决议" in prompt:
            return "board_resolution"
        return "meeting_record"
    szse_cue_groups = (
        ("深交所", "汇报"),
        ("一页纸", "重组"),
        ("业务发展历史", "重组进展"),
        ("主营业务", "重组进展"),
    )
    if any(all(cue in prompt for cue in group) for group in szse_cue_groups):
        return "szse_report_brief"
    return "temporary_announcement" if requested in {"", AUTO_SELECTION} else requested


def file_digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def json_value(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def parse_json(value: str | None, fallback: Any) -> Any:
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return fallback


class PlatformService:
    def __init__(self, settings: Settings, database: Database):
        self.settings = settings
        self.database = database
        self.embedding_provider: EmbeddingProvider = create_embedding_provider(settings)
        if settings.vector_backend == "pgvector":
            vector_url = settings.vector_db_url or settings.database_url
            if not vector_url:
                raise RuntimeError("VECTOR_BACKEND=pgvector 时必须配置 VECTOR_DB_URL 或 DATABASE_URL。")
            self.vector_store = PgVectorStore(vector_url, database)
        elif settings.vector_backend == "faiss":
            self.vector_store = FaissVectorStore(
                database,
                settings.faiss_index_root,
                self.embedding_provider.model_name(),
            )
        else:
            self.vector_store = SQLiteVectorStore(database)
        self.rag = RAGService(self.embedding_provider, self.vector_store, settings.retrieval_mode)
        self.fact_engine = StructuredFactEngine(database)
        self.rule_engine = DeterministicRuleEngine()
        self.financial_audit_engine = FinancialAuditEngine()
        self.meeting_case_comparator = MeetingCaseComparator()
        self.chunker = SecuritiesChunker()
        self.task_chunker = SecuritiesChunker(max_chars=1800, overlap_chars=120)
        self.ocr_service = LocalOCRService(settings)
        self._analysis_lock = threading.Lock()
        self._background_embedding_lock = threading.Lock()
        self._parsed_baseline_cache_lock = threading.Lock()
        self._parsed_baseline_cache: dict[str, ParsedDocument] = {}
        self._rule_compare_cache_lock = threading.Lock()
        self._rule_compare_cache: dict[tuple[str, str], dict[str, Any]] = {}
        self.bind_address = "127.0.0.1"
        self.ai_provider: AIProvider | None = None
        self.ai_configuration_error = ""
        try:
            self.ai_provider = create_ai_provider(settings)
        except AIServiceError as error:
            self.ai_configuration_error = str(error)

    def initialize(self) -> None:
        self.settings.upload_root.mkdir(parents=True, exist_ok=True)
        self.settings.knowledge_root.mkdir(parents=True, exist_ok=True)
        for knowledge_type in KNOWLEDGE_TYPES:
            (self.settings.knowledge_root / knowledge_type).mkdir(parents=True, exist_ok=True)
        self._ensure_builtin_financial_case_knowledge()
        now = utc_now()
        self.database.execute(
            """UPDATE analysis_jobs SET status='failed',stage='failed',
                   message='服务曾中断，请重新提交；已完成的本地向量缓存会自动复用。',
                   error_message='服务在任务完成前重新启动。',completed_at=?,updated_at=?
               WHERE status IN ('queued','processing')""",
            (now, now),
        )
        pending_documents = self.database.fetch_all(
            """SELECT d.id,d.filename,d.file_path,d.owner_user_id,d.metadata_json
                 FROM documents d JOIN analysis_tasks t ON t.document_id=d.id
                WHERE d.status IN ('embedding_pending','embedding')
                  AND t.status IN ('review','completed')"""
        )
        for index, document in enumerate(pending_documents):
            try:
                path = Path(str(document["file_path"])).resolve()
                if not path.is_relative_to(self.settings.upload_root.resolve()) or not path.is_file():
                    continue
                parsed = parse_document(document["filename"], path.read_bytes(), self.ocr_service)
                metadata = parse_json(document.get("metadata_json"), {})
                chunks = self.task_chunker.chunk(
                    document["id"], parsed, "user_documents",
                    {
                        "file_name": document["filename"],
                        "document_name": metadata.get("title") or Path(document["filename"]).stem,
                        "regulation_name": None,
                        "document_updated_at": metadata.get("documentUpdatedAt") or now,
                    },
                )
                self._store_pending_chunks(chunks, document["id"])
                self._schedule_background_embedding(
                    document["id"], chunks, str(document["owner_user_id"]),
                    delay_seconds=2.0 + index * 0.1,
                )
            except Exception:
                self.database.execute(
                    "UPDATE documents SET status='embedding_failed',updated_at=? WHERE id=?",
                    (utc_now(), document["id"]),
                )

    def backfill_structured_facts(self, *, limit: int = 0, include_private: bool = True) -> dict[str, int]:
        """Extract deterministic facts from already-indexed local chunks.

        This operation only reads local SQLite/FAISS metadata and can be safely
        repeated; each document's facts are replaced atomically.
        """
        params: list[Any] = []
        conditions = ["k.status='active'"]
        if not include_private:
            conditions.append("k.owner_user_id IS NULL")
        if limit > 0:
            limit_clause = " LIMIT ?"
            params.append(max(1, min(limit, 100000)))
        else:
            limit_clause = ""
        documents = self.database.fetch_all(
            f"""SELECT k.id,k.title,k.document_type,k.company,k.source,k.source_url,k.source_type,
                       k.file_path,k.publication_date,k.version,k.owner_user_id,k.updated_at
                  FROM knowledge_documents k
                 WHERE {' AND '.join(conditions)}
                 ORDER BY k.updated_at DESC{limit_clause}""",
            params,
        )
        extracted = 0
        processed = 0
        for document in documents:
            rows = self.database.fetch_all(
                """SELECT id,content,page,section,paragraph,chunk_index,content_hash,metadata_json
                     FROM chunks WHERE knowledge_document_id=? ORDER BY chunk_index""",
                (document["id"],),
            )
            chunks = [
                ChunkRecord(
                    id=row["id"], content=row["content"], page=int(row.get("page") or 1),
                    section=str(row.get("section") or ""), paragraph=int(row.get("paragraph") or 0),
                    chunk_index=int(row.get("chunk_index") or 0), content_hash=row["content_hash"],
                    metadata=parse_json(row.get("metadata_json"), {}),
                )
                for row in rows
            ]
            extracted += self.fact_engine.replace_document_facts(
                document["id"], chunks, knowledge=True, reconcile=False,
            )
            processed += 1
        self.fact_engine.reconcile()
        return {"documents": processed, "facts": extracted}

    def _ensure_builtin_financial_case_knowledge(self) -> None:
        """Expose validated case annotations to the shared local RAG corpus.

        The deterministic financial engine also reads these records directly for
        pattern calibration.  Indexing the same compact JSON as a `cases`
        knowledge document lets the AI assistant cite the case through the
        normal local-RAG path without uploading the original sensitive files.
        """
        case_root = self.settings.knowledge_root / "cases"
        if not case_root.is_dir():
            return
        for case_path in sorted(case_root.glob("*.json")):
            try:
                content = case_path.read_bytes()
                digest = file_digest(content)
                existing = self.database.fetch_one(
                    """SELECT id FROM knowledge_documents
                       WHERE owner_user_id IS NULL AND document_type='cases'
                         AND source_type='approved_financial_case' AND source_name=?""",
                    (case_path.name,),
                )
                if existing:
                    continue
                case_payload = json.loads(content.decode("utf-8"))
                if not isinstance(case_payload, dict) or not case_payload.get("validated"):
                    continue
                parsed = parse_document(case_path.name, content, self.ocr_service)
                knowledge_id = str(uuid.uuid4())
                now = utc_now()
                title = str(case_payload.get("title") or case_path.stem)
                self.database.execute(
                    """INSERT INTO knowledge_documents (
                           id,owner_user_id,title,document_type,company,source,source_url,announcement_id,publication_date,
                           effective_date,expiry_date,version,file_path,file_hash,page_count,status,source_type,
                           source_name,retrieved_at,created_at,updated_at
                       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        knowledge_id, None, title, "cases", "创业黑马科技集团股份有限公司",
                        str(case_payload.get("source") or "本地已确认案例"), None, None, None, None, None,
                        "validated-financial-case-v1", str(case_path), digest, parsed.page_count, "processing",
                        "approved_financial_case", case_path.name, now, now, now,
                    ),
                )
                chunks = self.chunker.chunk(
                    knowledge_id, parsed, "cases",
                    {
                        "file_name": case_path.name,
                        "document_name": title,
                        "regulation_name": None,
                        "document_updated_at": now,
                    },
                )
                self._index_chunks(chunks, knowledge_document_id=knowledge_id)
                self.database.execute(
                    "UPDATE knowledge_documents SET status='active',updated_at=? WHERE id=?",
                    (utc_now(), knowledge_id),
                )
            except Exception:
                # A corrupt optional case must never prevent the application from
                # starting; the deterministic corpus remains available.
                continue

    @staticmethod
    def _merge_rag_contexts(primary: RAGContext, supplemental: RAGContext, max_results: int) -> RAGContext:
        merged = list(primary.results)
        seen = {result.chunk_id for result in merged}
        for result in supplemental.results:
            if result.chunk_id in seen:
                continue
            merged.append(result)
            seen.add(result.chunk_id)
            if len(merged) >= max_results:
                break
        return RAGContext(primary.query, merged[:max_results])

    @staticmethod
    def _basis_citations(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        citations: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict) or not item.get("title"):
                continue
            citations.append({
                "chunk_id": "",
                "document_id": "",
                "title": str(item.get("title") or ""),
                "source": str(item.get("source") or "监管规则"),
                "source_url": str(item.get("source_url") or ""),
                "date": str(item.get("date") or ""),
                "version": str(item.get("version") or ""),
                "page": item.get("page"),
                "paragraph": None,
                "section": str(item.get("article") or ""),
                "article": str(item.get("article") or ""),
                "document_type": "regulations",
                "score": 1.0,
                "content": str(item.get("detail") or ""),
                "metadata": {"citation_kind": "deterministic_rule"},
                "citation_kind": "deterministic_rule",
            })
        return citations

    @staticmethod
    def _merge_citations(*groups: list[dict[str, Any]]) -> list[dict[str, Any]]:
        merged: list[dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        for group in groups:
            for source in group:
                item = dict(source)
                item.setdefault("citation_kind", "local_rag")
                key = (
                    item.get("citation_kind"), item.get("chunk_id"), item.get("title"),
                    item.get("source_url"), item.get("page"), item.get("section"),
                    str(item.get("content") or "")[:160],
                )
                if key in seen:
                    continue
                seen.add(key)
                merged.append(item)
        return merged

    @staticmethod
    def _substantive_rag_citation(source: dict[str, Any]) -> dict[str, Any] | None:
        item = dict(source)
        if str(item.get("document_type") or "") != "regulations":
            return item
        article = str(item.get("article") or item.get("section") or "").strip()
        content = re.sub(r"\s+", " ", str(item.get("content") or "")).strip()
        article_match = re.search(
            r"(?:第[一二三四五六七八九十百零〇0-9]+条|第\d+(?:\.\d+){1,3}条?|(?<!\d)\d+\.\d+(?:\.\d+)?条?)",
            f"{article} {content}",
        )
        if not article_match:
            return None
        item["article"] = article_match.group(0)
        if not article or article in {"目录", "总则", "第一章"}:
            item["section"] = article_match.group(0)
        return item

    @staticmethod
    def _select_primary_regulation_basis(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Select one precise, current rule for the default reviewer view.

        The complete list remains in ``regulation_basis`` for auditability.  A
        deterministic rule with an explicit article is preferred over broad
        RAG hits, chapter headings, or duplicate chunks.  Returning one item
        keeps the report actionable while preserving the full evidence trail.
        """
        candidates: list[tuple[float, int, dict[str, Any]]] = []
        seen: set[tuple[str, str, str]] = set()
        article_pattern = re.compile(
            r"(?:第[一二三四五六七八九十百零〇0-9]+条|第\d+(?:\.\d+){1,3}条?|(?<!\d)\d+(?:\.\d+){1,3}条?)"
        )
        generic_sections = {"目录", "总则", "第一章", "第二章", "第三章"}
        for index, raw in enumerate(items):
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title") or raw.get("document_name") or "").strip()
            if not title:
                continue
            article = str(raw.get("article") or raw.get("section") or "").strip()
            content = str(raw.get("detail") or raw.get("content") or "").strip()
            article_match = article_pattern.search(f"{article} {content}")
            normalized_article = article_match.group(0) if article_match else ""
            key = (title, normalized_article or article, str(raw.get("source_url") or ""))
            if key in seen:
                continue
            seen.add(key)
            metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
            citation_kind = str(raw.get("citation_kind") or metadata.get("citation_kind") or "")
            score = 0.0
            if citation_kind == "deterministic_rule":
                score += 100
            if normalized_article:
                score += 50
            elif article and article not in generic_sections:
                score += 8
            if raw.get("source_url"):
                score += 3
            if content:
                score += 1
            candidates.append((score, -index, raw))
        if not candidates:
            return []
        candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
        selected = dict(candidates[0][2])
        article = str(selected.get("article") or selected.get("section") or "").strip()
        content = str(selected.get("detail") or selected.get("content") or "")
        match = article_pattern.search(f"{article} {content}")
        if match and not str(selected.get("article") or "").strip():
            selected["article"] = match.group(0)
            selected.setdefault("section", match.group(0))
        selected["citation_kind"] = "deterministic_rule"
        selected.setdefault("metadata", {})
        if isinstance(selected["metadata"], dict):
            selected["metadata"]["citation_kind"] = "deterministic_rule"
        return [selected]

    def _regulation_search_scope(self, user_id: str) -> dict[str, int]:
        row = self.database.fetch_one(
            """
            SELECT COUNT(DISTINCT k.id) AS documents,COUNT(c.id) AS chunks
            FROM chunks c JOIN knowledge_documents k ON k.id=c.knowledge_document_id
            WHERE k.status='active' AND k.document_type='regulations'
              AND COALESCE(k.version,'') NOT IN ('repealed-list','已被废止')
              AND c.embedding_status='ready' AND c.embedding_model=?
              AND (k.owner_user_id IS NULL OR k.owner_user_id=?)
            """,
            (self.embedding_provider.model_name(), user_id),
        ) or {"documents": 0, "chunks": 0}
        return {"documents": int(row["documents"] or 0), "chunks": int(row["chunks"] or 0)}

    def status(self) -> dict[str, Any]:
        knowledge = self.database.fetch_one(
            "SELECT COUNT(*) AS total FROM knowledge_documents WHERE status='active' AND owner_user_id IS NULL"
        ) or {"total": 0}
        chunks = self.database.fetch_one(
            """SELECT COUNT(*) AS total FROM chunks c JOIN knowledge_documents k ON k.id=c.knowledge_document_id
               WHERE c.embedding_status='ready' AND c.embedding_model=?
                 AND k.status='active' AND k.owner_user_id IS NULL""",
            (self.embedding_provider.model_name(),),
        ) or {"total": 0}
        embedding_documents = self.database.fetch_one(
            """SELECT
                   SUM(CASE WHEN EXISTS (
                       SELECT 1 FROM chunks c WHERE c.knowledge_document_id=k.id
                         AND c.embedding_status='ready' AND c.embedding_model=?
                   ) THEN 1 ELSE 0 END) AS embedded,
                   SUM(CASE WHEN k.status='active' AND NOT EXISTS (
                       SELECT 1 FROM chunks c WHERE c.knowledge_document_id=k.id
                         AND c.embedding_status='ready' AND c.embedding_model=?
                   ) THEN 1 ELSE 0 END) AS pending,
                   SUM(CASE WHEN k.status='failed' OR EXISTS (
                       SELECT 1 FROM chunks c WHERE c.knowledge_document_id=k.id
                         AND c.embedding_status='failed' AND c.embedding_model=?
                   ) THEN 1 ELSE 0 END) AS failed
               FROM knowledge_documents k WHERE k.owner_user_id IS NULL""",
            (self.embedding_provider.model_name(),) * 3,
        ) or {"embedded": 0, "pending": 0, "failed": 0}
        ocr_status = self.ocr_service.status()
        return {
            "status": "ok",
            "serviceId": "xinpizhishen-platform",
            "service": "上市公司证券合规风险管理与 AI 智能审阅平台",
            "aiMode": self.settings.ai_mode,
            "aiConfigured": self.ai_provider is not None,
            "aiMessage": self.ai_configuration_error,
            "embeddingProvider": self.embedding_provider.model_name(),
            "embeddingDimension": self.embedding_provider.dimension(),
            "embeddingModelPath": self.embedding_provider.local_model_path(),
            "embeddingExternalApi": False,
            "vectorStore": "faiss" if isinstance(self.vector_store, FaissVectorStore) else (
                "sqlite-vector" if type(self.vector_store) is SQLiteVectorStore else self.settings.vector_backend
            ),
            "vectorIndexPath": str(self.vector_store.root) if isinstance(self.vector_store, FaissVectorStore) else "",
            "retrievalMode": self.settings.retrieval_mode,
            "fastReviewBackgroundEmbedding": self.settings.fast_review_background_embedding,
            "reviewPerformanceVersion": 2,
            "knowledgeDocuments": int(knowledge["total"]),
            "indexedChunks": int(chunks["total"]),
            "embeddingDocuments": int(embedding_documents.get("embedded") or 0),
            "embeddingPendingDocuments": int(embedding_documents.get("pending") or 0),
            "embeddingFailedDocuments": int(embedding_documents.get("failed") or 0),
            "financialCaseCorpus": {
                "enabled": bool(self.financial_audit_engine.financial_cases),
                "cases": len(self.financial_audit_engine.financial_cases),
                "annotations": sum(
                    len(case.get("annotations", []))
                    for case in self.financial_audit_engine.financial_cases
                    if isinstance(case, dict)
                ),
                "validatedOnly": True,
            },
            "registrationEnabled": self.settings.allow_registration,
            "lanAccess": self.bind_address in {"0.0.0.0", "::"},
            "ocrEnabled": ocr_status["enabled"],
            "ocrAvailable": ocr_status["available"],
            "ocrEngine": ocr_status["engine"],
            "ocrLanguage": ocr_status["language"],
            "ocrMessage": ocr_status["message"],
        }

    def _save_binary(self, root: Path, digest: str, original_name: str, content: bytes) -> Path:
        directory = root / digest[:2] / digest[2:4]
        directory.mkdir(parents=True, exist_ok=True)
        destination = directory / f"{digest[:16]}_{safe_filename(original_name)}"
        if not destination.exists():
            destination.write_bytes(content)
        return destination

    def _load_cached_baseline_document(self, row: dict[str, Any]) -> ParsedDocument:
        """Load a historical report from a local parser cache keyed by file hash and parser version."""
        source_path = Path(str(row.get("file_path") or "")).resolve()
        if not source_path.is_relative_to(self.settings.knowledge_root.resolve()) or not source_path.is_file():
            raise FileNotFoundError("本地公告原文件不存在")
        source_hash = str(row.get("file_hash") or "").strip()
        if not source_hash:
            source_hash = file_digest(source_path.read_bytes())
        cache_key = f"{source_hash}-v{PARSER_VERSION}"
        with self._parsed_baseline_cache_lock:
            cached = self._parsed_baseline_cache.get(cache_key)
            if cached is not None:
                return cached
            cache_root = self.settings.upload_root.parent / "parsed-cache"
            cache_path = cache_root / f"{cache_key}.json"
            if cache_path.is_file():
                try:
                    payload = json.loads(cache_path.read_text(encoding="utf-8"))
                    parsed = ParsedDocument(
                        filename=str(payload["filename"]),
                        file_type=str(payload["fileType"]),
                        page_count=int(payload["pageCount"]),
                        blocks=[
                            ParsedBlock(
                                text=str(block["text"]),
                                page=int(block["page"]),
                                section=str(block.get("section") or "正文"),
                                paragraph_index=int(block["paragraphIndex"]),
                                block_type=str(block.get("blockType") or "paragraph"),
                                source_start=int(block.get("sourceStart") or 0),
                                source_end=int(block.get("sourceEnd") or 0),
                                csv_row_number=(
                                    int(block["csvRowNumber"])
                                    if block.get("csvRowNumber") is not None else None
                                ),
                                source_row_numbers=tuple(
                                    int(value) for value in block.get("sourceRowNumbers", [])
                                ),
                                sheet_name=str(block.get("sheetName") or ""),
                            )
                            for block in payload.get("blocks", [])
                        ],
                        scanned_suspected=bool(payload.get("scannedSuspected")),
                        ocr_used=bool(payload.get("ocrUsed")),
                        ocr_pages=tuple(int(value) for value in payload.get("ocrPages", [])),
                        ocr_engine=str(payload.get("ocrEngine") or ""),
                    )
                    if parsed.blocks:
                        self._parsed_baseline_cache[cache_key] = parsed
                        return parsed
                except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
                    pass

            original_name = source_path.name.split("_", 1)[-1]
            parsed = parse_document(original_name, source_path.read_bytes(), self.ocr_service)
            cache_root.mkdir(parents=True, exist_ok=True)
            payload = {
                "parserVersion": PARSER_VERSION,
                "fileHash": source_hash,
                "filename": parsed.filename,
                "fileType": parsed.file_type,
                "pageCount": parsed.page_count,
                "scannedSuspected": parsed.scanned_suspected,
                "ocrUsed": parsed.ocr_used,
                "ocrPages": list(parsed.ocr_pages),
                "ocrEngine": parsed.ocr_engine,
                "blocks": [
                    {
                        "text": block.text,
                        "page": block.page,
                        "section": block.section,
                        "paragraphIndex": block.paragraph_index,
                        "blockType": block.block_type,
                        "sourceStart": block.source_start,
                        "sourceEnd": block.source_end,
                        "csvRowNumber": block.csv_row_number,
                        "sourceRowNumbers": list(block.source_row_numbers),
                        "sheetName": block.sheet_name,
                    }
                    for block in parsed.blocks
                ],
            }
            temporary = cache_path.with_suffix(f".{uuid.uuid4().hex}.tmp")
            temporary.write_text(json_value(payload), encoding="utf-8")
            temporary.replace(cache_path)
            self._parsed_baseline_cache[cache_key] = parsed
            return parsed

    def _index_chunks(
        self,
        chunks: list[ChunkRecord],
        *,
        document_id: str | None = None,
        knowledge_document_id: str | None = None,
        progress_callback: Callable[[int, int, int], None] | None = None,
    ) -> int:
        model = self.embedding_provider.model_name()
        vectors: list[list[float] | None] = [None] * len(chunks)
        unique_hashes = list(dict.fromkeys(chunk.content_hash for chunk in chunks))
        cached_by_hash: dict[str, list[float]] = {}
        query_batch_size = 400
        for start in range(0, len(unique_hashes), query_batch_size):
            hash_batch = unique_hashes[start:start + query_batch_size]
            placeholders = ",".join("?" for _ in hash_batch)
            params = [model, *hash_batch]
            rows = self.database.fetch_all(
                f"SELECT content_hash,vector_json FROM embedding_cache WHERE embedding_model=? AND content_hash IN ({placeholders})",
                params,
            )
            for row in rows:
                vector = parse_json(row["vector_json"], None)
                if vector:
                    cached_by_hash[row["content_hash"]] = vector
            missing_hashes = [value for value in hash_batch if value not in cached_by_hash]
            if not missing_hashes:
                continue
            missing_placeholders = ",".join("?" for _ in missing_hashes)
            fallback_rows = self.database.fetch_all(
                f"""SELECT content_hash,vector_json FROM chunks
                    WHERE embedding_model=? AND embedding_status='ready' AND vector_json IS NOT NULL
                      AND content_hash IN ({missing_placeholders})""",
                [model, *missing_hashes],
            )
            for row in fallback_rows:
                vector = parse_json(row["vector_json"], None)
                if vector:
                    cached_by_hash[row["content_hash"]] = vector

        missing_by_hash: dict[str, list[int]] = {}
        for index, chunk in enumerate(chunks):
            vectors[index] = cached_by_hash.get(chunk.content_hash)
            if vectors[index] is None:
                missing_by_hash.setdefault(chunk.content_hash, []).append(index)
        cached_items = sum(1 for vector in vectors if vector is not None)
        if progress_callback:
            progress_callback(cached_items, len(chunks), cached_items)
        missing_indexes = [indexes[0] for indexes in missing_by_hash.values()]
        batch_size = max(1, self.settings.embedding_batch_size)
        for start in range(0, len(missing_indexes), batch_size):
            batch_indexes = missing_indexes[start:start + batch_size]
            embedded = self.embedding_provider.embed_batch([chunks[index].embedding_text for index in batch_indexes])
            now = utc_now()
            cache_rows = []
            for index, vector in zip(batch_indexes, embedded, strict=True):
                for duplicate_index in missing_by_hash[chunks[index].content_hash]:
                    vectors[duplicate_index] = vector
                cache_rows.append((
                    chunks[index].content_hash, model, len(vector), json_value(vector), now, now,
                ))
            self.database.executemany(
                """INSERT INTO embedding_cache (
                       content_hash,embedding_model,dimension,vector_json,created_at,updated_at
                   ) VALUES (?,?,?,?,?,?)
                   ON CONFLICT(content_hash,embedding_model) DO UPDATE SET
                       dimension=excluded.dimension,vector_json=excluded.vector_json,updated_at=excluded.updated_at""",
                cache_rows,
            )
            if progress_callback:
                completed = sum(1 for vector in vectors if vector is not None)
                progress_callback(completed, len(chunks), cached_items)
        ready_vectors = [vector if vector is not None else [] for vector in vectors]
        return self.vector_store.add_chunks(
            chunks,
            ready_vectors,
            model,
            document_id=document_id,
            knowledge_document_id=knowledge_document_id,
        )

    def _store_pending_chunks(self, chunks: list[ChunkRecord], document_id: str) -> int:
        """Persist searchable text immediately and defer only vector computation."""
        if not chunks:
            return 0
        now = utc_now()
        model = self.embedding_provider.model_name()
        self.database.executemany(
            """
            INSERT INTO chunks (
                id,document_id,knowledge_document_id,content,page,section,paragraph,chunk_index,
                content_hash,embedding_status,embedding_model,vector_json,metadata_json,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                content=excluded.content,page=excluded.page,section=excluded.section,
                paragraph=excluded.paragraph,chunk_index=excluded.chunk_index,
                content_hash=excluded.content_hash,embedding_status=excluded.embedding_status,
                embedding_model=excluded.embedding_model,vector_json=NULL,
                metadata_json=excluded.metadata_json,updated_at=excluded.updated_at
            """,
            [
                (
                    chunk.id, document_id, None, chunk.content, chunk.page, chunk.section,
                    chunk.paragraph, chunk.chunk_index, chunk.content_hash, "pending", model,
                    None, json_value(chunk.metadata), now, now,
                )
                for chunk in chunks
            ],
        )
        self.database.execute(
            "UPDATE documents SET status='embedding_pending',updated_at=? WHERE id=?",
            (now, document_id),
        )
        return len(chunks)

    def _schedule_background_embedding(
        self,
        document_id: str,
        chunks: list[ChunkRecord],
        user_id: str,
        *,
        delay_seconds: float = 0.5,
    ) -> None:
        """Finish full local task embeddings after deterministic review is available."""
        chunk_values = list(chunks)

        def worker() -> None:
            try:
                with self._background_embedding_lock:
                    document = self.database.fetch_one(
                        "SELECT id,metadata_json FROM documents WHERE id=?",
                        (document_id,),
                    )
                    if not document:
                        return
                    self.database.execute(
                        "UPDATE documents SET status='embedding',updated_at=? WHERE id=?",
                        (utc_now(), document_id),
                    )
                    indexed = self._index_chunks(chunk_values, document_id=document_id)
                    refreshed = self.database.fetch_one(
                        "SELECT metadata_json FROM documents WHERE id=?",
                        (document_id,),
                    )
                    if not refreshed:
                        return
                    metadata = parse_json(refreshed.get("metadata_json"), {})
                    metadata["embeddingStatus"] = "ready"
                    metadata["embeddedChunks"] = indexed
                    metadata["embeddingCompletedAt"] = utc_now()
                    self.database.execute(
                        "UPDATE documents SET status='indexed',metadata_json=?,updated_at=? WHERE id=?",
                        (json_value(metadata), utc_now(), document_id),
                    )
                    self.database.audit(
                        user_id, "background_embedding_complete", "document", document_id, None,
                        after={"chunks": indexed, "model": self.embedding_provider.model_name()},
                    )
            except Exception as error:
                document = self.database.fetch_one(
                    "SELECT metadata_json FROM documents WHERE id=?",
                    (document_id,),
                )
                if not document:
                    return
                metadata = parse_json(document.get("metadata_json"), {})
                metadata["embeddingStatus"] = "failed"
                metadata["embeddingError"] = type(error).__name__
                self.database.execute(
                    "UPDATE documents SET status='embedding_failed',metadata_json=?,updated_at=? WHERE id=?",
                    (json_value(metadata), utc_now(), document_id),
                )

        timer = threading.Timer(delay_seconds, worker)
        timer.name = f"embedding-{document_id[:8]}"
        timer.daemon = True
        timer.start()

    def _update_analysis_job(
        self,
        job_id: str,
        *,
        status: str,
        stage: str,
        progress: int,
        message: str,
        completed_items: int | None = None,
        total_items: int | None = None,
        task_id: str | None = None,
        error_message: str = "",
        started: bool = False,
        completed: bool = False,
    ) -> None:
        now = utc_now()
        self.database.execute(
            """UPDATE analysis_jobs SET status=?,stage=?,progress=?,message=?,
                   completed_items=COALESCE(?,completed_items),total_items=COALESCE(?,total_items),
                   task_id=COALESCE(?,task_id),error_message=?,started_at=CASE WHEN ? THEN COALESCE(started_at,?) ELSE started_at END,
                   completed_at=CASE WHEN ? THEN ? ELSE completed_at END,updated_at=? WHERE id=?""",
            (
                status, stage, max(0, min(int(progress), 100)), message,
                int(completed_items) if completed_items is not None else None,
                int(total_items) if total_items is not None else None,
                task_id, error_message, int(started), now, int(completed), now, now, job_id,
            ),
        )

    def create_analysis_job(
        self,
        filename: str,
        content: bytes,
        task_name: str,
        task_type: str,
        rule_pack: str,
        user: dict[str, Any],
        ip: str | None,
        comparison_document: tuple[str, bytes] | None = None,
        comparison_documents: list[tuple[str, bytes]] | None = None,
    ) -> dict[str, Any]:
        digest = file_digest(content)
        staged_path = self._save_binary(self.settings.upload_root, digest, filename, content)
        if comparison_documents is None:
            comparison_documents = [comparison_document] if comparison_document else []
        if len(comparison_documents) > 8:
            raise ValueError("最多可添加 8 份对比文件。")
        comparison_staged: list[tuple[str, Path]] = []
        for comparison_filename, comparison_content in comparison_documents:
            comparison_digest = file_digest(comparison_content)
            comparison_path = self._save_binary(
                self.settings.upload_root, comparison_digest, comparison_filename, comparison_content,
            )
            comparison_staged.append((comparison_filename, comparison_path))
        job_id = str(uuid.uuid4())
        now = utc_now()
        self.database.execute(
            """INSERT INTO analysis_jobs (
                   id,owner_user_id,filename,task_name,task_type,rule_pack,status,stage,progress,message,
                   completed_items,total_items,error_message,created_at,updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                job_id, user["id"], filename, task_name or Path(filename).stem, task_type, rule_pack,
                "queued", "queued", 1, "文件已接收，等待本地分析。", 0, 0, "", now, now,
            ),
        )
        worker = threading.Thread(
            target=self._run_analysis_job,
            args=(job_id, staged_path, filename, task_name, task_type, rule_pack, dict(user), ip, comparison_staged),
            name=f"analysis-{job_id[:8]}",
            daemon=True,
        )
        worker.start()
        return self.get_analysis_job(job_id, user)

    def _run_analysis_job(
        self,
        job_id: str,
        staged_path: Path,
        filename: str,
        task_name: str,
        task_type: str,
        rule_pack: str,
        user: dict[str, Any],
        ip: str | None,
        comparison_staged: list[tuple[str, Path]] | None = None,
    ) -> None:
        try:
            with self._analysis_lock:
                self._update_analysis_job(
                    job_id, status="processing", stage="parsing", progress=3,
                    message="正在解析文档结构和表格。", started=True,
                )

                def progress(
                    stage: str,
                    percent: int,
                    message: str,
                    completed_items: int | None = None,
                    total_items: int | None = None,
                ) -> None:
                    self._update_analysis_job(
                        job_id, status="processing", stage=stage, progress=percent, message=message,
                        completed_items=completed_items, total_items=total_items,
                    )

                result = self.create_task(
                    filename, staged_path.read_bytes(), task_name, task_type, rule_pack, user, ip,
                    progress_callback=progress, analysis_job_id=job_id,
                    comparison_documents=(
                        [(name, path.read_bytes()) for name, path in comparison_staged]
                        if comparison_staged else []
                    ),
                )
                self.database.execute(
                    "UPDATE analysis_jobs SET task_type=?,rule_pack=?,updated_at=? WHERE id=?",
                    (result["taskType"], result["rulePack"], utc_now(), job_id),
                )
                self._update_analysis_job(
                    job_id, status="completed", stage="completed", progress=100,
                    message="审查完成，可以查看风险与原文依据。", task_id=result["taskId"], completed=True,
                )
        except Exception as error:
            partial = self.database.fetch_one(
                "SELECT task_id FROM analysis_jobs WHERE id=? AND owner_user_id=?",
                (job_id, user["id"]),
            )
            partial_task_id = str(partial.get("task_id") or "") if partial else ""
            if partial_task_id:
                try:
                    self.delete_task(partial_task_id, user, ip)
                except Exception:
                    # Preserve the original failure state; incomplete tasks are also hidden by list_tasks.
                    pass
            if isinstance(error, (DocumentParseError, ValueError, AIServiceError)):
                display_error = str(error)
            else:
                display_error = "本地分析未完成，系统已清理未完成结果。请直接重新提交；如仍失败，请联系管理员检查服务日志。"
            self._update_analysis_job(
                job_id, status="failed", stage="failed", progress=100,
                message="本地分析未完成，未保存不完整结果。", error_message=display_error, completed=True,
            )

    def get_analysis_job(self, job_id: str, user: dict[str, Any]) -> dict[str, Any]:
        row = self.database.fetch_one("SELECT * FROM analysis_jobs WHERE id=?", (job_id,))
        if not row:
            raise ValueError("分析任务不存在。")
        if str(row["owner_user_id"]) != str(user["id"]):
            raise PermissionError("无权查看该分析进度。")
        return {
            "jobId": row["id"],
            "status": row["status"],
            "stage": row["stage"],
            "progress": int(row["progress"]),
            "message": row["message"],
            "completedItems": int(row["completed_items"]),
            "totalItems": int(row["total_items"]),
            "taskId": row["task_id"],
            "taskType": row["task_type"],
            "rulePack": row["rule_pack"],
            "error": row["error_message"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }

    def _cache_existing_chunk_vectors(self, document_id: str) -> None:
        rows = self.database.fetch_all(
            """SELECT content_hash,embedding_model,vector_json FROM chunks
               WHERE (document_id=? OR knowledge_document_id=?)
                 AND embedding_status='ready' AND embedding_model IS NOT NULL AND vector_json IS NOT NULL""",
            (document_id, document_id),
        )
        now = utc_now()
        values = []
        seen = set()
        for row in rows:
            key = (row["content_hash"], row["embedding_model"])
            if key in seen:
                continue
            seen.add(key)
            vector = parse_json(row["vector_json"], [])
            if vector:
                values.append((row["content_hash"], row["embedding_model"], len(vector), row["vector_json"], now, now))
        self.database.executemany(
            """INSERT INTO embedding_cache (
                   content_hash,embedding_model,dimension,vector_json,created_at,updated_at
               ) VALUES (?,?,?,?,?,?) ON CONFLICT(content_hash,embedding_model) DO UPDATE SET
                   dimension=excluded.dimension,vector_json=excluded.vector_json,updated_at=excluded.updated_at""",
            values,
        )

    def import_knowledge(
        self,
        filename: str,
        content: bytes,
        metadata: dict[str, Any],
        user: dict[str, Any],
        ip: str | None,
        progress_callback: Callable[[int, int, int], None] | None = None,
    ) -> dict[str, Any]:
        if user.get("role") != "admin":
            raise PermissionError("只有管理员可以维护资料库。")
        document_type = str(metadata.get("document_type") or "user_documents").strip()
        if document_type not in KNOWLEDGE_TYPES:
            raise ValueError("知识库类型无效。")
        category_id = str(metadata.get("category_id") or "").strip() or None
        if category_id:
            category = self.database.fetch_one(
                "SELECT id,name,active FROM knowledge_categories WHERE id=?",
                (category_id,),
            )
            if not category or not int(category.get("active") or 0):
                raise ValueError("资料分类不存在或已停用。")
        digest = file_digest(content)
        existing = self.database.fetch_one(
            """SELECT k.id,k.title,k.status,
                      (SELECT COUNT(*) FROM chunks c
                       WHERE c.knowledge_document_id=k.id AND c.embedding_status='ready') AS chunk_count
               FROM knowledge_documents k
               WHERE k.owner_user_id IS NULL AND k.document_type=? AND k.file_hash=?""",
            (document_type, digest),
        )
        if existing:
            return {"status": "skipped", "reason": "同一文件已经入库。", "document": existing}
        parsed = parse_document(filename, content, self.ocr_service)
        knowledge_id = str(uuid.uuid4())
        relative_path = str(metadata.get("relative_path") or "").replace("\\", "/").strip("/")
        destination = self._save_binary(
            self.settings.knowledge_root / document_type,
            digest,
            filename,
            content,
        )
        now = utc_now()
        first_paragraph = parsed.paragraphs[0] if parsed.paragraphs else ""
        title = str(metadata.get("title") or first_paragraph[:120] or Path(filename).stem)
        source = str(metadata.get("source") or filename)
        self.database.execute(
            """
            INSERT INTO knowledge_documents (
                id,owner_user_id,title,document_type,category_id,company,source,source_url,announcement_id,publication_date,
                effective_date,expiry_date,version,file_path,file_hash,page_count,status,source_type,
                source_name,retrieved_at,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                knowledge_id, None, title, document_type, category_id, metadata.get("company"), source,
                metadata.get("source_url"), metadata.get("announcement_id"), metadata.get("date"),
                metadata.get("effective_date"), metadata.get("expiry_date"), metadata.get("version"),
                str(destination), digest, parsed.page_count, "processing", metadata.get("source_type") or "uploaded",
                metadata.get("source_name") or relative_path or source, now, now, now,
            ),
        )
        try:
            chunks = self.chunker.chunk(
                knowledge_id,
                parsed,
                document_type,
                {
                    "file_name": filename,
                    "document_name": title,
                    "regulation_name": title if document_type in {"regulations", "internal_rules"} else None,
                    "document_updated_at": metadata.get("updated_at") or now,
                    "publication_date": metadata.get("date"),
                    "effective_date": metadata.get("effective_date"),
                    "version": metadata.get("version"),
                    "relative_path": relative_path or None,
                    # Meeting-case fields are persisted on every chunk so the
                    # local RAG layer can distinguish a notice, proposal,
                    # record, resolution and ballot without relying on a
                    # filename at generation time.
                    **{
                        key: metadata[key]
                        for key in (
                            "case_role", "meeting_type", "meeting_term",
                            "case_status", "case_set_id", "proposal_titles",
                        )
                        if metadata.get(key) not in (None, "", [], {})
                    },
                },
            )
            indexed = self._index_chunks(
                chunks,
                knowledge_document_id=knowledge_id,
                progress_callback=progress_callback,
            )
            fact_count = self.fact_engine.replace_document_facts(knowledge_id, chunks, knowledge=True)
            self.database.execute(
                "UPDATE knowledge_documents SET status='active',updated_at=? WHERE id=?",
                (utc_now(), knowledge_id),
            )
        except BaseException:
            self.database.execute("UPDATE knowledge_documents SET status='failed',updated_at=? WHERE id=?", (utc_now(), knowledge_id))
            raise
        self.database.audit(user["id"], "knowledge_import", "knowledge_document", knowledge_id, ip, after={
            "title": title,
            "document_type": document_type,
            "file_hash": digest,
            "chunks": indexed,
            "ocr_used": parsed.ocr_used,
            "ocr_pages": list(parsed.ocr_pages),
            "ocr_engine": parsed.ocr_engine,
            "structured_facts": fact_count,
            "relative_path": relative_path or None,
        })
        return {
            "status": "success",
            "document": {
                "id": knowledge_id,
                "title": title,
                "document_type": document_type,
                "category_id": category_id,
                "source": source,
                "sourceName": relative_path or metadata.get("source_name") or source,
                "relativePath": relative_path or None,
                "page_count": parsed.page_count,
                "file_hash": digest,
                "chunks": indexed,
                "ocrUsed": parsed.ocr_used,
                "ocrPages": list(parsed.ocr_pages),
                "ocrEngine": parsed.ocr_engine,
                "structuredFacts": fact_count,
                "scope": "shared",
            },
        }

    def list_knowledge(
        self,
        user: dict[str, Any],
        document_type: str | None = None,
        category_id: str | None = None,
    ) -> list[dict[str, Any]]:
        is_admin = user.get("role") == "admin"
        params: list[Any] = []
        conditions = [] if is_admin else ["(k.owner_user_id IS NULL OR k.owner_user_id=?)"]
        if not is_admin:
            params.append(user["id"])
        if document_type:
            conditions.append("k.document_type=?")
            params.append(document_type)
        if category_id:
            conditions.append("k.category_id=?")
            params.append(category_id)
        where_clause = " AND ".join(conditions) if conditions else "1=1"
        return self.database.fetch_all(
            f"""
            SELECT k.id,k.title,k.document_type,k.category_id,k.company,k.source,k.source_url,k.announcement_id,
                   k.publication_date,k.effective_date,k.expiry_date,k.version,k.file_hash,k.page_count,
                   k.status,k.source_type,k.source_name,k.retrieved_at,k.created_at,k.updated_at,
                   kc.name AS category_name,kc.slug AS category_slug,
                   CASE WHEN k.owner_user_id IS NULL THEN 'shared' ELSE 'private' END AS scope,
                   {1 if is_admin else 0} AS can_manage,
                   COUNT(c.id) AS chunk_count,
                   SUM(CASE WHEN c.embedding_status='ready' AND c.embedding_model=? THEN 1 ELSE 0 END) AS embedded_chunk_count,
                   SUM(CASE WHEN c.embedding_status='failed' AND c.embedding_model=? THEN 1 ELSE 0 END) AS failed_chunk_count
            FROM knowledge_documents k
            LEFT JOIN knowledge_categories kc ON kc.id=k.category_id
            LEFT JOIN chunks c ON c.knowledge_document_id=k.id
            WHERE {where_clause} GROUP BY k.id ORDER BY k.updated_at DESC
            """,
            [self.embedding_provider.model_name(), self.embedding_provider.model_name(), *params],
        )

    def list_knowledge_categories(self, user: dict[str, Any]) -> list[dict[str, Any]]:
        """Return shared administrator-managed labels visible to every account."""
        return self.database.fetch_all(
            """SELECT id,name,slug,description,sort_order,active,created_at,updated_at
                 FROM knowledge_categories
                WHERE active=1
                ORDER BY sort_order,name COLLATE NOCASE""",
        )

    def create_knowledge_category(
        self, name: str, description: str, user: dict[str, Any], ip: str | None,
    ) -> dict[str, Any]:
        if user.get("role") != "admin":
            raise PermissionError("只有管理员可以管理资料分类。")
        name = str(name or "").strip()
        description = str(description or "").strip()
        if not name or len(name) > 40:
            raise ValueError("分类名称不能为空且不能超过 40 个字符。")
        if len(description) > 200:
            raise ValueError("分类说明不能超过 200 个字符。")
        if self.database.fetch_one("SELECT id FROM knowledge_categories WHERE name=? COLLATE NOCASE AND active=1", (name,)):
            raise ValueError("该资料分类已经存在。")
        category_id = str(uuid.uuid4())
        now = utc_now()
        slug = f"custom-{category_id.replace('-', '')[:16]}"
        self.database.execute(
            """INSERT INTO knowledge_categories
               (id,owner_user_id,name,slug,description,sort_order,active,created_at,updated_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (category_id, None, name, slug, description, 100, 1, now, now),
        )
        self.database.audit(user["id"], "knowledge_category_create", "knowledge_category", category_id, ip, after={"name": name})
        return {"id": category_id, "name": name, "slug": slug, "description": description, "active": 1}

    def delete_knowledge_category(self, category_id: str, user: dict[str, Any], ip: str | None) -> dict[str, Any]:
        if user.get("role") != "admin":
            raise PermissionError("只有管理员可以管理资料分类。")
        category = self.database.fetch_one("SELECT id,name,active FROM knowledge_categories WHERE id=?", (category_id,))
        if not category:
            raise ValueError("资料分类不存在。")
        self.database.execute("UPDATE knowledge_categories SET active=0,updated_at=? WHERE id=?", (utc_now(), category_id))
        self.database.audit(user["id"], "knowledge_category_delete", "knowledge_category", category_id, ip, before=category, after={"active": 0})
        return {"status": "inactive", "id": category_id}

    def workspace_chat(
        self,
        question: str,
        conversation_id: str | None,
        user: dict[str, Any],
        ip: str | None,
    ) -> dict[str, Any]:
        """Independent knowledge chat; task_id remains NULL for strict separation."""
        question = str(question or "").strip()
        if not question:
            raise ValueError("请输入问题。")
        now = utc_now()
        conversation = None
        if conversation_id:
            conversation = self.database.fetch_one(
                "SELECT * FROM conversations WHERE id=? AND user_id=? AND task_id IS NULL",
                (conversation_id, user["id"]),
            )
            if not conversation:
                raise ValueError("独立对话不存在或无权访问。")
        else:
            conversation_id = str(uuid.uuid4())
            self.database.execute(
                "INSERT INTO conversations (id,task_id,user_id,title,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                (conversation_id, None, user["id"], question[:80], now, now),
            )
        self.database.execute(
            "INSERT INTO messages (id,conversation_id,role,content,created_at) VALUES (?,?,?,?,?)",
            (str(uuid.uuid4()), conversation_id, "user", question, now),
        )
        history = self.database.fetch_all(
            "SELECT role,content FROM messages WHERE conversation_id=? ORDER BY created_at DESC LIMIT 12",
            (conversation_id,),
        )
        context = self.rag.retrieve(
            question,
            top_k=8,
            threshold=0.06,
            document_types=sorted(KNOWLEDGE_TYPES),
            current_regulations_only=True,
            user_id=str(user["id"]),
        )
        # This entry point is deliberately offline.  A future LLM provider can
        # be introduced behind this service boundary without changing the UI
        # or conversation storage, but no configured cloud mode is used here.
        local_result = RAGService.local_answer(context)
        result = AIResult(local_result["answer"], local_result["source_documents"], model="local-rag-retrieval")
        self.database.execute(
            "INSERT INTO messages (id,conversation_id,role,content,citations_json,input_tokens,output_tokens,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), conversation_id, "assistant", result.content, json_value(result.citations), result.input_tokens, result.output_tokens, utc_now()),
        )
        self.database.execute("UPDATE conversations SET updated_at=? WHERE id=?", (utc_now(), conversation_id))
        self._update_summary_memory(None, conversation_id, user["id"])
        self.database.audit(user["id"], "workspace_chat", "conversation", conversation_id, ip, after={
            "task_id": None, "mode": "local_rag", "citations": len(result.citations), "external_ai_used": False,
        })
        return {
            "conversation_id": conversation_id,
            "answer": result.content,
            "source_documents": result.citations,
            "mode": "local_rag",
            "provider": result.model or (self.ai_provider.name() if self.ai_provider else "local-rag-retrieval"),
            "usage": {"input_tokens": result.input_tokens, "output_tokens": result.output_tokens},
        }

    def list_workspace_conversations(self, user: dict[str, Any]) -> list[dict[str, Any]]:
        return self.database.fetch_all(
            "SELECT * FROM conversations WHERE user_id=? AND task_id IS NULL ORDER BY updated_at DESC",
            (user["id"],),
        )

    @staticmethod
    def _rule_family_name(title: str) -> str:
        """Normalize a notification title to the underlying rule family."""
        value = str(title or "").strip()
        match = re.search(r"(深圳证券交易所[^《》]*?)（20\d{2}年", value)
        if not match:
            match = re.search(r"(深圳证券交易所[^《》]*?)\(20\d{2}年", value)
        if match:
            return match.group(1).strip()
        inner = re.search(r"《([^》]+)》", value)
        candidate = inner.group(1) if inner else value
        candidate = re.sub(r"[（(]\s*20\d{2}年[^）)]*[）)]", "", candidate)
        candidate = re.sub(r"^关于发布", "", candidate)
        candidate = re.sub(r"的通知$", "", candidate)
        return candidate.strip("《》 ")

    def _find_rule_version_document(
        self,
        family: str,
        year: str,
        user: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Choose the full local rule text, ignoring short index notices."""
        rows = self.database.fetch_all(
            """SELECT id,title,source,source_url,publication_date,effective_date,version,
                      file_path,file_hash,page_count,status,owner_user_id
                 FROM knowledge_documents
                WHERE document_type='regulations'
                  AND status='active'
                  AND title LIKE ?
                  AND title LIKE ?
                  AND (owner_user_id IS NULL OR owner_user_id=?)""",
            (f"%{family}%", f"%{year}%", str(user.get("id") or "")),
        )
        candidates = []
        knowledge_root = self.settings.knowledge_root.resolve()
        for row in rows:
            try:
                path = Path(str(row.get("file_path") or "")).resolve()
                path_is_local = path.is_relative_to(knowledge_root) and path.is_file()
            except (OSError, RuntimeError, ValueError):
                path_is_local = False
                path = Path()
            if not path_is_local or path.suffix.lower() not in {".pdf", ".doc", ".docx"}:
                continue
            if int(row.get("page_count") or 0) < 10:
                continue
            candidates.append(row)
        if not candidates:
            return None
        return max(candidates, key=lambda item: int(item.get("page_count") or 0))

    def compare_rule_versions(
        self,
        title: str,
        new_year: str,
        old_year: str,
        user: dict[str, Any],
        ip: str | None,
    ) -> dict[str, Any]:
        """Compare two local full-text versions of one official rule."""
        new_year = str(new_year or "").strip()
        old_year = str(old_year or "").strip()
        if not re.fullmatch(r"20\d{2}", new_year) or not re.fullmatch(r"20\d{2}", old_year):
            raise ValueError("规则版本年份无效。")
        if new_year == old_year:
            raise ValueError("请选择两个不同的规则版本。")
        family = self._rule_family_name(title)
        if not family:
            raise ValueError("无法识别规则名称，请从规则列表中选择具体规则。")
        new_document = self._find_rule_version_document(family, new_year, user)
        old_document = self._find_rule_version_document(family, old_year, user)
        if not new_document or not old_document:
            missing = []
            if not new_document:
                missing.append(f"{new_year}年")
            if not old_document:
                missing.append(f"{old_year}年")
            raise ValueError(
                f"本地规则库未找到{family}的{'、'.join(missing)}完整正文。"
                "请管理员先导入对应官方 PDF 后再比较。"
            )

        cache_key = (str(old_document.get("file_hash") or old_document["id"]), str(new_document.get("file_hash") or new_document["id"]))
        with self._rule_compare_cache_lock:
            comparison = self._rule_compare_cache.get(cache_key)
        if comparison is None:
            old_parsed = self._load_cached_baseline_document(old_document)
            new_parsed = self._load_cached_baseline_document(new_document)
            comparison = compare_rule_documents(old_parsed, new_parsed)
            with self._rule_compare_cache_lock:
                self._rule_compare_cache[cache_key] = comparison

        def descriptor(row: dict[str, Any]) -> dict[str, Any]:
            return {
                "id": row["id"],
                "title": row["title"],
                "version": row.get("version") or f"{new_year if row['id'] == new_document['id'] else old_year}年修订",
                "publishedAt": row.get("publication_date") or "",
                "effectiveAt": row.get("effective_date") or "",
                "pageCount": int(row.get("page_count") or 0),
                "source": row.get("source") or "深圳证券交易所",
                "sourceUrl": row.get("source_url") or "",
                "localUrl": f"/api/knowledge/{row['id']}/document",
            }

        self.database.audit(
            user["id"], "rule_version_compare", "regulation", f"{old_document['id']}:{new_document['id']}", ip,
            after={"family": family, "old_year": old_year, "new_year": new_year, "changed": len(comparison.get("changes", []))},
        )
        return {
            "status": "ok",
            "family": family,
            "oldVersion": descriptor(old_document),
            "newVersion": descriptor(new_document),
            "summary": comparison["summary"],
            "changes": comparison["changes"],
            "note": "差异由本地 PDF 文本按规则编号比较；新增内容在新版列标为绿色，删除内容标为红色。正式适用版本和条款效力仍以深交所官网为准。",
        }

    def get_knowledge_document(
        self,
        document_id: str,
        user: dict[str, Any],
        ip: str | None,
    ) -> tuple[str, bytes]:
        document = self.database.fetch_one(
            "SELECT id,title,owner_user_id,file_path,status FROM knowledge_documents WHERE id=?",
            (document_id,),
        )
        if not document:
            raise ValueError("知识文档不存在。")
        owner_user_id = document.get("owner_user_id")
        if owner_user_id and owner_user_id != user.get("id"):
            raise PermissionError("无权打开其他账号的私有资料。")
        if not owner_user_id and document.get("status") != "active" and user.get("role") != "admin":
            raise PermissionError("该共享资料当前未启用，无法打开。")

        path = Path(str(document["file_path"])).resolve()
        if not path.is_relative_to(self.settings.knowledge_root.resolve()) or not path.is_file():
            raise ValueError("知识文档原文件不存在或路径无效。")
        filename = path.name.split("_", 1)[-1] if "_" in path.name else path.name
        self.database.audit(
            user["id"], "knowledge_document_view", "knowledge_document", document_id, ip,
            after={"title": document["title"], "status": document["status"]},
        )
        return filename, path.read_bytes()

    def get_knowledge_document_preview(
        self,
        document_id: str,
        user: dict[str, Any],
        ip: str | None,
    ) -> dict[str, Any]:
        """Parse a knowledge source for an in-app preview without rewriting it."""
        document = self.database.fetch_one(
            "SELECT id,title,owner_user_id,file_path,status,file_hash,updated_at FROM knowledge_documents WHERE id=?",
            (document_id,),
        )
        if not document:
            raise ValueError("知识文档不存在。")
        owner_user_id = document.get("owner_user_id")
        if owner_user_id and owner_user_id != user.get("id"):
            raise PermissionError("无权打开其他账号的私有资料。")
        if not owner_user_id and document.get("status") != "active" and user.get("role") != "admin":
            raise PermissionError("该共享资料当前未启用，无法打开。")

        path = Path(str(document["file_path"])).resolve()
        if not path.is_relative_to(self.settings.knowledge_root.resolve()) or not path.is_file():
            raise ValueError("知识文档原文件不存在或路径无效。")
        filename = path.name.split("_", 1)[-1] if "_" in path.name else path.name
        parsed = parse_document(filename, path.read_bytes(), self.ocr_service)
        self.database.audit(
            user["id"], "knowledge_document_preview", "knowledge_document", document_id, ip,
            after={"title": document["title"], "file_hash": document["file_hash"]},
        )
        return {
            "documentId": document["id"],
            "filename": filename,
            "fileHash": document["file_hash"],
            "updatedAt": document["updated_at"],
            "title": parsed.paragraphs[0] if parsed.paragraphs and len(parsed.paragraphs[0]) <= 100 else document["title"],
            "fileType": parsed.file_type,
            "pageCount": parsed.page_count,
            "paragraphCount": len(parsed.blocks),
            "characterCount": parsed.character_count,
            "tableCount": sum(block.block_type == "table" for block in parsed.blocks),
            "paragraphs": parsed.paragraphs,
            "headings": parsed.headings,
            "scannedSuspected": parsed.scanned_suspected,
            "ocrUsed": parsed.ocr_used,
            "ocrPages": list(parsed.ocr_pages),
            "ocrEngine": parsed.ocr_engine,
            "blocks": [
                {
                    "text": block.text,
                    "page": block.page,
                    "section": block.section,
                    "paragraphIndex": block.paragraph_index,
                    "blockType": block.block_type,
                    "sheetName": block.sheet_name,
                    "sourceRowNumbers": list(block.source_row_numbers),
                }
                for block in parsed.blocks
            ],
        }

    def rebuild_knowledge(self, document_id: str, user: dict[str, Any], ip: str | None) -> dict[str, Any]:
        document = self.database.fetch_one("SELECT * FROM knowledge_documents WHERE id=?", (document_id,))
        if not document:
            raise ValueError("知识文档不存在。")
        if user.get("role") != "admin":
            raise PermissionError("只有管理员可以维护资料库。")
        self.database.execute(
            "UPDATE knowledge_documents SET status='processing',updated_at=? WHERE id=?",
            (utc_now(), document_id),
        )
        try:
            path = Path(document["file_path"])
            if not path.exists():
                raise ValueError("知识文档原文件不存在，无法重新索引。")
            parsed = parse_document(path.name.split("_", 1)[-1], path.read_bytes(), self.ocr_service)
            self._cache_existing_chunk_vectors(document_id)
            self.vector_store.delete_chunks(document_id)
            original_name = path.name.split("_", 1)[-1]
            chunks = self.chunker.chunk(
                document_id,
                parsed,
                document["document_type"],
                {
                    "file_name": original_name,
                    "document_name": document["title"],
                    "regulation_name": document["title"] if document["document_type"] in {"regulations", "internal_rules"} else None,
                    "document_updated_at": document.get("updated_at"),
                    "publication_date": document.get("publication_date"),
                    "effective_date": document.get("effective_date"),
                    "version": document.get("version"),
                },
            )
            indexed = self._index_chunks(chunks, knowledge_document_id=document_id)
            fact_count = self.fact_engine.replace_document_facts(document_id, chunks, knowledge=True)
            self.database.execute("UPDATE knowledge_documents SET status='active',updated_at=? WHERE id=?", (utc_now(), document_id))
        except BaseException:
            self.database.execute("UPDATE knowledge_documents SET status='failed',updated_at=? WHERE id=?", (utc_now(), document_id))
            raise
        self.database.audit(user["id"], "knowledge_rebuild", "knowledge_document", document_id, ip, after={
            "chunks": indexed,
            "ocr_used": parsed.ocr_used,
            "ocr_pages": list(parsed.ocr_pages),
            "ocr_engine": parsed.ocr_engine,
            "structured_facts": fact_count,
        })
        return {
            "status": "success",
            "document_id": document_id,
            "chunks": indexed,
            "ocrUsed": parsed.ocr_used,
            "ocrPages": list(parsed.ocr_pages),
            "ocrEngine": parsed.ocr_engine,
            "structuredFacts": fact_count,
        }

    def delete_knowledge(self, document_id: str, user: dict[str, Any], ip: str | None) -> None:
        document = self.database.fetch_one("SELECT id,title,status,company FROM knowledge_documents WHERE id=?", (document_id,))
        if not document:
            raise ValueError("知识文档不存在。")
        if user.get("role") != "admin":
            raise PermissionError("只有管理员可以维护资料库。")
        self.database.execute("UPDATE knowledge_documents SET status='inactive',updated_at=? WHERE id=?", (utc_now(), document_id))
        self.vector_store.delete_chunks(document_id)
        self.database.execute("DELETE FROM structured_facts WHERE knowledge_document_id=?", (document_id,))
        self.fact_engine.reconcile(document.get("company"))
        self.database.audit(user["id"], "knowledge_disable", "knowledge_document", document_id, ip, before=document, after={"status": "inactive"})

    def _run_financial_audit(
        self,
        parsed: ParsedDocument,
        *,
        task_id: str,
        document_id: str,
        owner_user_id: str,
        file_hash: str,
        comparison_parsed: ParsedDocument | None = None,
        comparison_document_id: str | None = None,
        comparison_documents: list[tuple[ParsedDocument, str]] | None = None,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        if comparison_documents is None:
            comparison_documents = (
                [(comparison_parsed, comparison_document_id or "")]
                if comparison_parsed is not None else []
            )
        cached = None if comparison_documents else self.database.fetch_one(
            """SELECT * FROM financial_audit_results
               WHERE owner_user_id=? AND file_hash=? AND engine_version=? AND status='completed'
               ORDER BY updated_at DESC LIMIT 1""",
            (owner_user_id, file_hash, FINANCIAL_AUDIT_ENGINE_VERSION),
        )
        cache_reused = bool(cached and cached.get("task_id") != task_id)
        if cached:
            payload = {
                "engineVersion": cached["engine_version"],
                "documentId": document_id,
                "filename": parsed.filename,
                "fileHash": file_hash,
                "status": cached["status"],
                "summary": parse_json(cached["summary_json"], {}),
                "periodRegistry": parse_json(cached["period_json"], {}),
                "checks": parse_json(cached["checks_json"], []),
                "facts": parse_json(cached["facts_json"], []),
                "tables": parse_json(cached["tables_json"], []),
                "externalAiUsed": False,
                "cacheReused": cache_reused,
            }
        else:
            result = self.financial_audit_engine.analyze(
                parsed,
                document_id=document_id,
                file_hash=file_hash,
                comparison_documents=comparison_documents,
            )
            payload = result.to_dict(include_facts=True)
            payload["cacheReused"] = False

        now = utc_now()
        existing = self.database.fetch_one(
            "SELECT id FROM financial_audit_results WHERE task_id=?", (task_id,)
        )
        result_id = str(existing["id"]) if existing else str(uuid.uuid4())
        with self.database.connection() as connection:
            connection.execute(
                """INSERT INTO financial_audit_results (
                       id,task_id,document_id,owner_user_id,file_hash,engine_version,status,
                       summary_json,checks_json,facts_json,tables_json,period_json,created_at,updated_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(task_id) DO UPDATE SET
                       document_id=excluded.document_id,owner_user_id=excluded.owner_user_id,
                       file_hash=excluded.file_hash,engine_version=excluded.engine_version,status=excluded.status,
                       summary_json=excluded.summary_json,checks_json=excluded.checks_json,
                       facts_json=excluded.facts_json,tables_json=excluded.tables_json,
                       period_json=excluded.period_json,updated_at=excluded.updated_at""",
                (
                    result_id, task_id, document_id, owner_user_id, file_hash,
                    payload["engineVersion"], payload["status"], json_value(payload["summary"]),
                    json_value(payload["checks"]), json_value(payload.get("facts", [])),
                    json_value(payload["tables"]), json_value(payload["periodRegistry"]), now, now,
                ),
            )
        return payload, FinancialAuditEngine.payload_issue_risks(payload)

    def _refresh_stale_financial_audit(
        self,
        task_id: str,
        row: dict[str, Any],
        user: dict[str, Any],
    ) -> dict[str, Any]:
        """Re-run an old persisted result after the deterministic engine changes."""
        if str(row.get("engine_version") or "") == FINANCIAL_AUDIT_ENGINE_VERSION:
            return row
        source = self.database.fetch_one(
            "SELECT id,owner_user_id,filename,file_path,file_hash,metadata_json FROM documents WHERE id=?",
            (row.get("document_id"),),
        )
        if not source:
            return row
        source_path = Path(str(source.get("file_path") or "")).resolve()
        upload_root = self.settings.upload_root.resolve()
        if not source_path.is_relative_to(upload_root) or not source_path.is_file():
            return row
        comparison_rows = []
        for candidate in self.database.fetch_all(
            "SELECT id,filename,file_path,file_hash,metadata_json FROM documents WHERE task_id=? AND id<>?",
            (task_id, source["id"]),
        ):
            metadata = parse_json(candidate.get("metadata_json"), {})
            usage = str(metadata.get("usage") or "")
            suffix = Path(str(candidate.get("filename") or "")).suffix.lower()
            if usage == "deterministic_financial_reconciliation" or suffix in {".xls", ".xlsx", ".csv"}:
                comparison_rows.append(candidate)
        try:
            parsed = parse_document(source["filename"], source_path.read_bytes(), self.ocr_service)
            comparison_documents = []
            for comparison_row in comparison_rows:
                comparison_path = Path(str(comparison_row.get("file_path") or "")).resolve()
                if comparison_path.is_relative_to(upload_root) and comparison_path.is_file():
                    parsed_comparison = parse_document(
                        comparison_row["filename"], comparison_path.read_bytes(), self.ocr_service,
                    )
                    comparison_documents.append((parsed_comparison, str(comparison_row["id"])))
            _refreshed_payload, refreshed_risks = self._run_financial_audit(
                parsed,
                task_id=task_id,
                document_id=str(source["id"]),
                owner_user_id=str(source["owner_user_id"]),
                file_hash=str(source["file_hash"]),
                comparison_documents=comparison_documents,
            )
            self._sync_refreshed_financial_risks(task_id, str(source["id"]), refreshed_risks)
            refreshed_metadata = parse_json(source.get("metadata_json"), {})
            refreshed_metadata["financialAudit"] = {
                **_refreshed_payload.get("summary", {}),
                "engineVersion": _refreshed_payload.get("engineVersion"),
                "externalAiUsed": False,
                "cacheReused": False,
            }
            self.database.execute(
                "UPDATE documents SET metadata_json=?,updated_at=? WHERE id=?",
                (json_value(refreshed_metadata), utc_now(), source["id"]),
            )
            # A report generated by an older engine must be regenerated from
            # the new checks rather than served from its old cached path.
            self.database.execute(
                """UPDATE financial_audit_results
                   SET html_report_path=NULL,pdf_report_path=NULL,docx_report_path=NULL,updated_at=?
                   WHERE task_id=?""",
                (utc_now(), task_id),
            )
            self.database.audit(
                user["id"], "financial_audit_engine_refresh", "analysis_task", task_id, None,
                before={"engine_version": row.get("engine_version")},
                after={"engine_version": FINANCIAL_AUDIT_ENGINE_VERSION},
            )
        except (OSError, ValueError):
            # Keep the last complete result if a legacy source file has been
            # removed or cannot be parsed; do not replace it with partial data.
            return row
        refreshed = self.database.fetch_one(
            """SELECT f.*,t.owner_user_id,d.filename
               FROM financial_audit_results f
               JOIN analysis_tasks t ON t.id=f.task_id
               JOIN documents d ON d.id=f.document_id
               WHERE f.task_id=?""",
            (task_id,),
        )
        return refreshed or row

    def _sync_refreshed_financial_risks(
        self,
        task_id: str,
        document_id: str,
        fresh_risks: list[dict[str, Any]],
    ) -> None:
        """Update task-level financial risks after a deterministic engine refresh.

        Financial audit checks carry a stable ``calculation.check_id``.  Use it
        to update an existing row in place so a manual confirmation/false
        positive and its review history survive an engine upgrade.  Pending
        rows that no longer exist are removed; reviewed rows remain as audit
        history rather than being silently overwritten.
        """
        existing = self.database.fetch_all(
            "SELECT * FROM risks WHERE task_id=? AND type=?",
            (task_id, "财务数据勾稽审计"),
        )
        by_check_id: dict[str, dict[str, Any]] = {}
        for row in existing:
            calculation = parse_json(row.get("calculation_json"), {})
            check_id = calculation.get("check_id") if isinstance(calculation, dict) else None
            if check_id:
                by_check_id[str(check_id)] = row

        now = utc_now()
        seen_ids: set[str] = set()
        with self.database.connection() as connection:
            for risk in fresh_risks:
                calculation = risk.get("calculation") or {}
                check_id = str(calculation.get("check_id") or risk.get("id") or "")
                current = by_check_id.get(check_id)
                if current is None:
                    self._insert_risk(task_id, document_id, risk, connection=connection)
                    continue
                seen_ids.add(str(current["id"]))
                connection.execute(
                    """UPDATE risks SET level=?,type=?,title=?,description=?,evidence=?,source_text=?,
                       page=?,section=?,paragraph_index=?,location_json=?,regulation_basis_json=?,
                       company_basis_json=?,internal_rule_basis_json=?,historical_cases_json=?,
                       source_documents_json=?,calculation_json=?,recommendation=?,confidence=?,updated_at=?
                       WHERE id=?""",
                    (
                        risk.get("level", "needs_review"), risk.get("type", "财务数据勾稽审计"),
                        risk.get("title", "待确认风险"), risk.get("description", ""),
                        risk.get("evidence", ""), risk.get("source_text", risk.get("evidence", "")),
                        risk.get("page"), risk.get("section", ""), risk.get("paragraph_index", 0),
                        json_value(risk.get("location", {})), json_value(risk.get("regulation_basis", [])),
                        json_value(risk.get("company_basis", [])), json_value(risk.get("internal_rule_basis", [])),
                        json_value(risk.get("historical_cases", [])), json_value(risk.get("source_documents", [])),
                        json_value(calculation), risk.get("recommendation", "请人工进一步确认。"),
                        float(risk.get("confidence", 0.5)), now, current["id"],
                    ),
                )
            for row in existing:
                if str(row["id"]) in seen_ids:
                    continue
                if str(row.get("status") or "pending") == "pending":
                    connection.execute("DELETE FROM risks WHERE id=?", (row["id"],))

            active_count = connection.execute(
                "SELECT COUNT(*) FROM risks WHERE task_id=?", (task_id,)
            ).fetchone()[0]
            high_count = connection.execute(
                "SELECT COUNT(*) FROM risks WHERE task_id=? AND level='high' AND status<>'false_positive'",
                (task_id,),
            ).fetchone()[0]
            connection.execute(
                "UPDATE analysis_tasks SET risk_count=?,high_count=?,updated_at=? WHERE id=?",
                (active_count, high_count, now, task_id),
            )

    def get_financial_audit(self, task_id: str, user: dict[str, Any]) -> dict[str, Any]:
        row = self.database.fetch_one(
            """SELECT f.*,t.owner_user_id,d.filename
               FROM financial_audit_results f
               JOIN analysis_tasks t ON t.id=f.task_id
               JOIN documents d ON d.id=f.document_id
               WHERE f.task_id=?""",
            (task_id,),
        )
        if not row:
            raise ValueError("该任务尚未生成财务数据勾稽结果。")
        if not self._may_access_owned_resource(user, row.get("owner_user_id")):
            raise PermissionError("无权访问该财务审计结果。")
        if str(row.get("engine_version") or "") != FINANCIAL_AUDIT_ENGINE_VERSION:
            row = self._refresh_stale_financial_audit(task_id, row, user)
        return {
            "taskId": task_id,
            "documentId": row["document_id"],
            "filename": row["filename"],
            "fileHash": row["file_hash"],
            "engineVersion": row["engine_version"],
            "status": row["status"],
            "summary": parse_json(row["summary_json"], {}),
            "periodRegistry": parse_json(row["period_json"], {}),
            "checks": parse_json(row["checks_json"], []),
            "tables": parse_json(row["tables_json"], []),
            "externalAiUsed": False,
            "caseCalibration": {
                "enabled": any(
                    isinstance(check, dict) and bool(check.get("case_references"))
                    for check in parse_json(row["checks_json"], [])
                ),
                "validatedOnly": True,
            },
            "reports": {
                "html": bool(row.get("html_report_path")),
                "docx": bool(row.get("docx_report_path")),
                "pdf": bool(row.get("pdf_report_path")),
            },
        }

    def get_financial_audit_report(
        self,
        task_id: str,
        report_format: str,
        user: dict[str, Any],
        ip: str | None,
    ) -> tuple[str, bytes]:
        report_format = str(report_format or "html").strip().lower()
        if report_format not in {"html", "docx", "pdf"}:
            raise ValueError("财务审核报告仅支持 HTML、DOCX 或 PDF。")
        payload = self.get_financial_audit(task_id, user)
        row = self.database.fetch_one(
            "SELECT * FROM financial_audit_results WHERE task_id=?", (task_id,)
        )
        if not row:
            raise ValueError("该任务尚未生成财务数据勾稽结果。")
        path_column = f"{report_format}_report_path"
        existing_path = Path(str(row.get(path_column) or "")).resolve() if row.get(path_column) else None
        report_root = (self.settings.upload_root.parent / "reports").resolve()
        if existing_path is None or not existing_path.is_relative_to(report_root) or not existing_path.is_file():
            output_dir = report_root / str(user["id"]) / task_id
            paths = generate_reports(payload, output_dir)
            self.database.execute(
                """UPDATE financial_audit_results
                   SET html_report_path=?,docx_report_path=?,pdf_report_path=?,updated_at=? WHERE task_id=?""",
                (str(paths["html"]), str(paths["docx"]), str(paths["pdf"]), utc_now(), task_id),
            )
            existing_path = paths[report_format].resolve()
        if not existing_path.is_relative_to(report_root) or not existing_path.is_file():
            raise ValueError("财务审核报告文件不可用。")
        self.database.audit(
            user["id"], "financial_audit_report_download", "analysis_task", task_id, ip,
            after={"format": report_format, "engine_version": payload["engineVersion"]},
        )
        return existing_path.name, existing_path.read_bytes()

    def create_task(
        self,
        filename: str,
        content: bytes,
        task_name: str,
        task_type: str,
        rule_pack: str,
        user: dict[str, Any],
        ip: str | None,
        progress_callback: Callable[[str, int, str, int | None, int | None], None] | None = None,
        analysis_job_id: str | None = None,
        comparison_document: tuple[str, bytes] | None = None,
        comparison_documents: list[tuple[str, bytes]] | None = None,
    ) -> dict[str, Any]:
        def report(
            stage: str,
            percent: int,
            message: str,
            completed: int | None = None,
            total: int | None = None,
        ) -> None:
            if progress_callback:
                progress_callback(stage, percent, message, completed, total)

        report("parsing", 4, "正在读取正文、章节和表格。")
        parsed = parse_document(filename, content, self.ocr_service)
        if comparison_documents is None:
            comparison_documents = [comparison_document] if comparison_document else []
        if len(comparison_documents) > 8:
            raise ValueError("最多可添加 8 份对比文件。")
        comparison_entries: list[dict[str, Any]] = []
        for comparison_index, (comparison_filename, comparison_content) in enumerate(comparison_documents, 1):
            comparison_is_spreadsheet = Path(comparison_filename).suffix.lower() in {".xls", ".xlsx", ".csv"}
            comparison_label = "勾稽表格" if comparison_is_spreadsheet else "对比文档"
            report(
                "parsing", 5 + min(6, comparison_index),
                f"正在读取{comparison_label} {comparison_index}/{len(comparison_documents)}：{comparison_filename}。",
            )
            comparison_entries.append({
                "filename": comparison_filename,
                "content": comparison_content,
                "parsed": parse_document(comparison_filename, comparison_content, self.ocr_service),
                "is_spreadsheet": comparison_is_spreadsheet,
            })
        report("parsing", 12, f"已解析 {len(parsed.blocks)} 个内容块。", len(parsed.blocks), len(parsed.blocks))
        detected_configuration = detect_review_configuration(filename, parsed)
        classification = resolve_review_configuration(task_type, rule_pack, detected_configuration)
        task_type = classification["taskType"]
        rule_pack = classification["rulePack"]
        confidence_label = f"{round(float(classification['confidence']) * 100)}%"
        review_note = "，建议人工确认" if classification["needsReview"] else ""
        report(
            "classification", 14,
            f"已采用“{task_type}”和“{rule_pack}”（识别置信度 {confidence_label}{review_note}）。",
        )
        digest = file_digest(content)
        task_id = str(uuid.uuid4())
        document_id = str(uuid.uuid4())
        destination = self._save_binary(self.settings.upload_root, digest, filename, content)
        now = utc_now()
        parsed_metadata = {
            "parserVersion": PARSER_VERSION,
            "title": parsed.paragraphs[0] if len(parsed.paragraphs[0]) <= 100 else Path(filename).stem,
            "paragraphs": parsed.paragraphs,
            "tableCount": sum(block.block_type == "table" for block in parsed.blocks),
            "blocks": [
                {
                    "text": block.text,
                    "page": block.page,
                    "section": block.section,
                    "paragraphIndex": block.paragraph_index,
                    "blockType": block.block_type,
                    "sheetName": block.sheet_name,
                    "sourceRowNumbers": list(block.source_row_numbers),
                }
                for block in parsed.blocks
            ],
            "headings": parsed.headings,
            "scannedSuspected": parsed.scanned_suspected,
            "ocrUsed": parsed.ocr_used,
            "ocrPages": list(parsed.ocr_pages),
            "ocrEngine": parsed.ocr_engine,
            "classification": classification,
            "comparisonDocuments": [
                {
                    "filename": entry["filename"],
                    "fileHash": file_digest(entry["content"]),
                    "fileType": entry["parsed"].file_type,
                    "pageCount": entry["parsed"].page_count,
                    "comparisonKind": "spreadsheet" if entry["is_spreadsheet"] else "document",
                }
                for entry in comparison_entries
            ],
            "summaryComparisons": [],
        }
        with self.database.connection() as connection:
            connection.execute(
                """
                INSERT INTO documents (id,owner_user_id,task_id,filename,safe_filename,document_type,file_path,file_hash,
                    page_count,paragraph_count,character_count,status,metadata_json,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    document_id, user["id"], task_id, filename, safe_filename(filename), parsed.file_type.lower(),
                    str(destination), digest, parsed.page_count, len(parsed.blocks), parsed.character_count,
                    "parsed", json_value(parsed_metadata), now, now,
                ),
            )
            connection.execute(
                """
                INSERT INTO analysis_tasks (id,name,task_type,rule_pack,status,owner_user_id,document_id,ai_mode,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (task_id, task_name or Path(filename).stem, task_type, rule_pack, "review", user["id"], document_id, self.settings.ai_mode, now, now),
            )
            if analysis_job_id:
                connection.execute(
                    "UPDATE analysis_jobs SET task_id=?,updated_at=? WHERE id=? AND owner_user_id=?",
                    (task_id, now, analysis_job_id, user["id"]),
                )

        report("chunking", 15, "正在按原文位置切分检索片段。")
        chunks = self.task_chunker.chunk(
            document_id,
            parsed,
            "user_documents",
            {
                "file_name": filename,
                "document_name": parsed_metadata["title"],
                "regulation_name": None,
                "document_updated_at": now,
            },
        )
        report("chunking", 18, f"已生成 {len(chunks)} 个检索片段。", 0, len(chunks))

        defer_task_embedding = bool(
            analysis_job_id
            and self.settings.ai_mode == "local_rag"
            and self.settings.fast_review_background_embedding
        )

        def embedding_progress(completed: int, total: int, cached: int) -> None:
            ratio = completed / max(1, total)
            percent = 20 + round(ratio * 50)
            cache_note = f"，复用缓存 {cached} 个" if cached else ""
            report("embedding", percent, f"本地 Embedding {completed}/{total}{cache_note}。", completed, total)

        if defer_task_embedding:
            self._store_pending_chunks(chunks, document_id)
            indexed = 0
            parsed_metadata["embeddingStatus"] = "pending"
            parsed_metadata["embeddingPlannedChunks"] = len(chunks)
            report(
                "fast_review", 70,
                "已启用快速审查；完整本地 Embedding 将在审查结果生成后于后台继续。",
                0, len(chunks),
            )
        else:
            indexed = self._index_chunks(chunks, document_id=document_id, progress_callback=embedding_progress)
        structured_fact_count = self.fact_engine.replace_document_facts(document_id, chunks, knowledge=False)
        parsed_metadata["structuredFacts"] = structured_fact_count
        self.database.execute(
            "UPDATE documents SET metadata_json=?,updated_at=? WHERE id=?",
            (json_value(parsed_metadata), utc_now(), document_id),
        )
        # Save every supplied comparison document as a task-owned original.  It
        # is intentionally not embedded: comparison files are deterministic
        # audit inputs and remain available for exact page/sheet references.
        for comparison_index, entry in enumerate(comparison_entries):
            comparison_filename = str(entry["filename"])
            comparison_content = bytes(entry["content"])
            comparison_parsed = entry["parsed"]
            comparison_document_id = str(uuid.uuid4())
            comparison_digest = file_digest(comparison_content)
            comparison_destination = self._save_binary(
                self.settings.upload_root, comparison_digest, comparison_filename, comparison_content,
            )
            comparison_metadata = {
                "parserVersion": PARSER_VERSION,
                "title": comparison_parsed.paragraphs[0][:100] if comparison_parsed.paragraphs else Path(comparison_filename).stem,
                "paragraphs": comparison_parsed.paragraphs,
                "blocks": [
                    {
                        "text": block.text,
                        "page": block.page,
                        "section": block.section,
                        "paragraphIndex": block.paragraph_index,
                        "blockType": block.block_type,
                        "sheetName": block.sheet_name,
                        "sourceRowNumbers": list(block.source_row_numbers),
                    }
                    for block in comparison_parsed.blocks
                ],
                "comparisonFor": document_id,
                "embeddingStatus": "not_required",
                "usage": (
                    "deterministic_financial_reconciliation"
                    if entry["is_spreadsheet"] else "deterministic_summary_fulltext_comparison"
                ),
            }
            self.database.execute(
                """INSERT INTO documents (
                       id,owner_user_id,task_id,filename,safe_filename,document_type,file_path,file_hash,
                       page_count,paragraph_count,character_count,status,metadata_json,created_at,updated_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    comparison_document_id, user["id"], task_id, comparison_filename,
                    safe_filename(comparison_filename), comparison_parsed.file_type.lower(),
                    str(comparison_destination), comparison_digest, comparison_parsed.page_count,
                    len(comparison_parsed.blocks), comparison_parsed.character_count, "parsed",
                    json_value(comparison_metadata), now, now,
                ),
            )
            metadata_entry = parsed_metadata["comparisonDocuments"][comparison_index]
            metadata_entry["documentId"] = comparison_document_id
            metadata_entry["chunks"] = 0
            metadata_entry["embeddingStatus"] = "not_required"
            entry["document_id"] = comparison_document_id
            self.database.execute(
                "UPDATE documents SET metadata_json=?,updated_at=? WHERE id=?",
                (json_value(comparison_metadata), utc_now(), comparison_document_id),
            )
        if defer_task_embedding:
            report("vector_persist", 73, "快速审查准备完成，语义索引将在后台补齐。", 0, len(chunks))
        else:
            report("vector_persist", 73, f"本地向量索引已保存，共 {indexed} 个片段。", indexed, indexed)
        report("financial_audit", 75, "正在本地执行财务结构化、Decimal 复算与跨表勾稽。")
        financial_audit, financial_risks = self._run_financial_audit(
            parsed,
            task_id=task_id,
            document_id=document_id,
            owner_user_id=str(user["id"]),
            file_hash=digest,
            comparison_documents=[
                (entry["parsed"], str(entry["document_id"]))
                for entry in comparison_entries
                if entry["is_spreadsheet"]
            ],
        )
        parsed_metadata["financialAudit"] = {
            **financial_audit["summary"],
            "engineVersion": financial_audit["engineVersion"],
            "externalAiUsed": False,
            "cacheReused": bool(financial_audit.get("cacheReused")),
        }
        summary_comparison: dict[str, Any] = {}
        summary_comparisons: list[dict[str, Any]] = []
        summary_comparison_risks: list[dict[str, Any]] = []
        document_comparisons = [entry for entry in comparison_entries if not entry["is_spreadsheet"]]
        for comparison_index, entry in enumerate(document_comparisons, 1):
            report(
                "summary_compare", 76,
                f"正在核对对比文档 {comparison_index}/{len(document_comparisons)}：{entry['filename']}。",
            )
            comparison_risks, comparison_result = compare_summary_to_original(
                parsed,
                entry["parsed"],
                primary_filename=filename,
                comparison_filename=str(entry["filename"]),
                primary_document_id=document_id,
                comparison_document_id=str(entry["document_id"]),
            )
            summary_comparison_risks.extend(comparison_risks)
            summary_comparisons.append(comparison_result)
        if len(summary_comparisons) == 1:
            summary_comparison = summary_comparisons[0]
        elif summary_comparisons:
            completed_comparisons = [
                item for item in summary_comparisons if item.get("status") == "completed"
            ]
            summary_comparison = {
                "status": "completed" if completed_comparisons else "not_summary_pair",
                "multi": True,
                "comparisons": summary_comparisons,
                "checkedItems": sum(int(item.get("checkedItems") or 0) for item in summary_comparisons),
                "mismatches": sum(int(item.get("mismatches") or 0) for item in summary_comparisons),
                "summaryDetected": bool(completed_comparisons),
                "message": f"已分别核对 {len(summary_comparisons)} 份对比文档。",
            }
        meeting_case_comparison: dict[str, Any] = {}
        if is_meeting_governance_document(filename):
            report("case_comparison", 76, "正在与证券部确认的正确会议文书案例逐项比对。")
            risks, meeting_case_comparison = self._review_meeting_case(parsed, filename, digest)
        else:
            rule_stage_message = "正在运行创业板定期报告规则检查。" if "定期报告" in task_type else "正在运行确定性规则检查。"
            report("rules", 76, rule_stage_message)
            risks = self.rule_engine.analyze(parsed, task_type)
            risks.extend(financial_risks)
        risks.extend(summary_comparison_risks)
        period_comparison: dict[str, Any] = {}
        casting_review: dict[str, Any] = {}
        if "定期报告" in task_type:
            report("rules", 77, "正在本地执行财务附注 Casting 复算。")
            casting_risks, casting_review = review_casting(parsed)
            risks.extend(casting_risks)
            report("comparison", 77, "正在与上年同期报告和上年度报告进行财务数据及重要文字章节对比。")
            baseline_rows = self.database.fetch_all(
                """SELECT id,title,source,source_url,announcement_id,publication_date,version,file_path,file_hash
                   FROM knowledge_documents
                   WHERE status='active' AND document_type='announcements'
                     AND (company LIKE '%创业黑马%' OR title LIKE '%创业黑马%' OR title LIKE '%年度报告%')
                   ORDER BY publication_date DESC,updated_at DESC"""
            )
            comparison_risks, period_comparison = compare_periodic_report(
                parsed,
                filename,
                baseline_rows,
                baseline_loader=self._load_cached_baseline_document,
            )
            for comparison_risk in comparison_risks:
                comparison_risk.setdefault("id", str(uuid.uuid4()))
            risks.extend(comparison_risks)
        full_text = "\n".join(parsed.paragraphs)
        periodic_scope = (
            "深圳证券交易所创业板股票上市规则 2026年修订 第六章 定期报告 "
            "公开发行证券的公司信息披露编报规则第15号 财务报告的一般规定 "
            "监管规则适用指引 会计类 会计政策 会计估计 财务报表 列报 披露"
            if "定期报告" in task_type else ""
        )

        accounting_context = RAGContext("", [])
        if periodic_scope:
            report("rag", 78, "正在通过本地向量定位财务会计规则。", 0, len(risks))
            accounting_candidates = self.rag.retrieve(
                "监管规则适用指引 会计类",
                top_k=20,
                threshold=0.06,
                document_types=["regulations"],
                current_regulations_only=True,
                user_id=str(user["id"]),
            )
            accounting_context = RAGContext(
                accounting_candidates.query,
                [
                    result for result in accounting_candidates.results
                    if result.title.startswith("监管规则适用指引——会计类")
                    or "财务报告的一般规定" in result.title
                ][:4],
            )

        total_risks = len(risks)
        regulation_scope = self._regulation_search_scope(str(user["id"]))
        regulation_context_cache: dict[str, RAGContext] = {}
        supplemental_context_cache: dict[str, RAGContext] = {}
        matched_regulation_documents: set[str] = set()

        def retrieval_query(risk: dict[str, Any]) -> str:
            if str(risk.get("type") or "").startswith("模板选项"):
                return (
                    f"{periodic_scope} 定期报告 内容格式 适用 不适用 是 否 有 无 "
                    "选项 披露完整性 格式准则"
                )
            regulation_terms = " ".join(
                f"{item.get('title', '')} {item.get('article', '')} {item.get('detail', '')}"
                for item in risk.get("regulation_basis", [])
                if isinstance(item, dict)
            )
            return " ".join((
                periodic_scope,
                regulation_terms,
                str(risk.get("title") or ""),
                str(risk.get("type") or ""),
                str(risk.get("description") or ""),
            )).strip()

        risk_queries = [retrieval_query(risk) for risk in risks]
        unique_risk_queries = list(dict.fromkeys(query for query in risk_queries if query))
        if unique_risk_queries:
            report(
                "rag", 78,
                f"正在批量准备 {len(unique_risk_queries)} 组本地风险检索。",
                0, total_risks,
            )
            query_vectors = self.rag.embed_queries(unique_risk_queries)
            regulation_context_cache = self.rag.retrieve_many(
                unique_risk_queries,
                top_k=12,
                threshold=0.06,
                document_types=["regulations"],
                current_regulations_only=True,
                user_id=str(user["id"]),
                query_vectors=query_vectors,
            )
            supplemental_context_cache = self.rag.retrieve_many(
                unique_risk_queries,
                top_k=5,
                threshold=0.06,
                document_types=["company_profile", "internal_rules", "announcements", "cases"],
                user_id=str(user["id"]),
                query_vectors=query_vectors,
            )

        for risk_index, risk in enumerate(risks, start=1):
            report(
                "rag", 78 + round((risk_index - 1) / max(1, total_risks) * 10),
                f"正在为风险检索本地依据 {risk_index}/{total_risks}。", risk_index - 1, total_risks,
            )
            query = retrieval_query(risk)
            regulation_context = regulation_context_cache.get(query, RAGContext(query, []))
            financial_signal = " ".join((
                str(risk.get("title", "")),
                str(risk.get("type", "")),
                str(risk.get("description", "")),
            ))
            if accounting_context.results and any(
                term in financial_signal for term in ("财务", "会计", "审计", "报表", "损益", "资产")
            ):
                regulation_context = self._merge_rag_contexts(accounting_context, regulation_context, 12)

            supplemental_context = supplemental_context_cache.get(query, RAGContext(query, []))
            matched_regulation_documents.update(
                str(result.document_id) for result in regulation_context.results if result.document_id
            )
            rag_citations: list[dict[str, Any]] = []
            has_direct_basis = bool(risk.get("regulation_basis"))
            supplemental_limit = 2
            if str(risk.get("type") or "").startswith("模板选项") or str(risk.get("type") or "") == "跨期及勾稽一致性":
                supplemental_limit = 0
            supplemental_added = 0
            for citation in regulation_context.citations + supplemental_context.citations:
                prepared = self._substantive_rag_citation(citation)
                if prepared is None:
                    continue
                if has_direct_basis and prepared.get("document_type") == "regulations":
                    # The validated deterministic citation is the visible rule basis. RAG still
                    # searches the complete local rule corpus, but duplicate or broader hits do
                    # not obscure the exact article presented to the reviewer.
                    continue
                if has_direct_basis and prepared.get("document_type") != "regulations":
                    if supplemental_added >= supplemental_limit:
                        continue
                    supplemental_added += 1
                rag_citations.append({**prepared, "citation_kind": "local_rag"})
            risk["source_documents"] = self._merge_citations(
                self._basis_citations(risk.get("regulation_basis", [])),
                risk.get("source_documents", []),
                rag_citations,
            )

        parsed_metadata["ragCoverage"] = {
            "scope": "all_indexed_regulations",
            "ruleDocumentsScanned": regulation_scope["documents"],
            "ruleChunksScanned": regulation_scope["chunks"],
            "matchedRuleDocuments": len(matched_regulation_documents),
            "riskQueries": total_risks,
            "uniqueQueries": len(regulation_context_cache),
            "topKPerRisk": 12,
            "retrievalMode": self.settings.retrieval_mode,
        }
        parsed_metadata["periodComparison"] = period_comparison
        parsed_metadata["summaryComparison"] = summary_comparison
        parsed_metadata["summaryComparisons"] = summary_comparisons
        parsed_metadata["castingReview"] = casting_review
        parsed_metadata["meetingCaseComparison"] = meeting_case_comparison
        parsed_metadata["comparisonDocuments"] = parsed_metadata.get("comparisonDocuments", [])
        self.database.execute(
            "UPDATE documents SET metadata_json=?,updated_at=? WHERE id=?",
            (json_value(parsed_metadata), utc_now(), document_id),
        )
        report("rag", 89, "本地法规、制度与历史资料检索完成。", total_risks, total_risks)

        ai_report = None
        ai_message = ""
        if self.settings.ai_mode in {"cloud", "local_llm"}:
            if not self.ai_provider:
                ai_message = self.ai_configuration_error or "AI 服务尚未配置，请联系管理员。"
            else:
                report("ai_analysis", 91, "正在基于最小必要上下文生成 AI 分析。")
                analysis_context = self.rag.retrieve(
                    f"{task_type} {rule_pack} {periodic_scope} {full_text[:6000]}",
                    top_k=10,
                    threshold=0.06,
                    document_types=["company_profile", "internal_rules", "regulations", "announcements", "cases"],
                    current_regulations_only=True,
                    task_document_id=document_id,
                    user_id=str(user["id"]),
                )
                if accounting_context.results:
                    analysis_context = self._merge_rag_contexts(analysis_context, accounting_context, 12)
                try:
                    ai_result = self.ai_provider.analyze(full_text, analysis_context)
                    ai_report = ai_result.structured
                    self._record_usage(user["id"], task_id, self.ai_provider.name(), ai_result.model, "analysis", ai_result.input_tokens, ai_result.output_tokens)
                    for item in (ai_report or {}).get("risks", []):
                        item["id"] = str(uuid.uuid4())
                        item.setdefault("source_text", item.get("evidence", ""))
                        page_values = item.get("page") or []
                        item["page"] = page_values[0] if page_values else None
                        item.setdefault("section", "AI 分析")
                        item.setdefault("paragraph_index", 0)
                        item.setdefault("location", {"page": item["page"], "section": item["section"], "paragraph": None})
                        risks.append(item)
                except AIServiceError as error:
                    ai_message = str(error)

        high_count = sum(1 for risk in risks if risk.get("level") == "high")
        with self.database.connection() as connection:
            for risk in risks:
                self._insert_risk(task_id, document_id, risk, connection=connection)
            connection.execute(
                "UPDATE analysis_tasks SET risk_count=?,high_count=?,updated_at=? WHERE id=?",
                (len(risks), high_count, utc_now(), task_id),
            )
        report("saving", 97, "正在保存风险结果和审计记录。", len(risks), len(risks))
        self.database.audit(user["id"], "upload_analyze", "analysis_task", task_id, ip, after={
            "document_id": document_id,
            "file_hash": digest,
            "chunks": indexed,
            "risks": len(risks),
            "ai_mode": self.settings.ai_mode,
            "task_type": task_type,
            "rule_pack": rule_pack,
            "ocr_used": parsed.ocr_used,
            "ocr_pages": list(parsed.ocr_pages),
            "ocr_engine": parsed.ocr_engine,
            "background_embedding": defer_task_embedding,
        })
        if defer_task_embedding:
            self._schedule_background_embedding(document_id, chunks, str(user["id"]))
        return self.get_task_result(task_id, ai_message=ai_message, ai_report=ai_report, user=user)

    def _review_meeting_case(
        self,
        parsed: ParsedDocument,
        filename: str,
        file_hash: str,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        rows = self.database.fetch_all(
            """SELECT id,title,source,source_name,publication_date,version,file_path,file_hash,updated_at
               FROM knowledge_documents
               WHERE status='active' AND document_type='cases' AND source_type='approved_meeting_case'
               ORDER BY updated_at DESC"""
        )
        candidates: list[tuple[int, dict[str, Any], ParsedDocument]] = []
        for row in rows:
            path = Path(str(row.get("file_path") or ""))
            if not path.is_file():
                continue
            try:
                baseline_parsed = parse_document(path.name.split("_", 1)[-1], path.read_bytes(), self.ocr_service)
            except (OSError, ValueError):
                continue
            score = baseline_score(filename, parsed, file_hash, row, baseline_parsed)
            if score:
                candidates.append((score, row, baseline_parsed))
        if candidates:
            _, baseline, baseline_parsed = max(candidates, key=lambda item: item[0])
            return self.meeting_case_comparator.review(
                parsed, filename, file_hash, baseline, baseline_parsed,
            )

        block = parsed.blocks[0]
        risk = {
            "id": str(uuid.uuid4()),
            "level": "needs_review",
            "type": "案例依据完整性",
            "title": "未找到可用于对比的已确认会议文书案例",
            "description": "资料库中没有与当前会议文书类型匹配且由管理员标记为已确认正确版本的案例，系统未对事实差异作确定性判断。",
            "evidence": block.text,
            "source_text": block.text,
            "page": block.page,
            "section": block.section,
            "paragraph_index": block.paragraph_index,
            "location": {"page": block.page, "section": block.section, "paragraph": block.paragraph_index + 1},
            "regulation_basis": [],
            "company_basis": [],
            "internal_rule_basis": [],
            "historical_cases": [],
            "source_documents": [],
            "calculation": {"engine": "meeting_case_compare_v1", "status": "no_approved_case"},
            "recommendation": "由管理员将同类型、已经证券部确认无误的最终文书导入案例库后重新审查；在此之前仅依据本地 RAG 规则来源人工复核。",
            "confidence": 1.0,
        }
        return [risk], {
            "status": "no_approved_case",
            "engineVersion": "meeting_case_compare_v1",
            "riskCount": 1,
            "sourceDocuments": [],
        }

    def _insert_risk(
        self,
        task_id: str,
        document_id: str,
        risk: dict[str, Any],
        *,
        connection: Any | None = None,
    ) -> None:
        now = utc_now()
        risk_id = str(uuid.uuid4())
        risk["id"] = risk_id
        calculation = dict(risk.get("calculation") or {})
        if risk.get("revision_text"):
            calculation["revision_text"] = str(risk["revision_text"])[:240]
        params = (
            risk_id, task_id, document_id, risk.get("level", "needs_review"), risk.get("type", "AI审阅"),
            risk.get("title", "待确认风险"), risk.get("description", ""), risk.get("evidence", ""),
            risk.get("source_text", risk.get("evidence", "")), risk.get("page"), risk.get("section", ""),
            risk.get("paragraph_index", 0), json_value(risk.get("location", {})),
            json_value(risk.get("regulation_basis", [])), json_value(risk.get("company_basis", [])),
            json_value(risk.get("internal_rule_basis", [])), json_value(risk.get("historical_cases", [])),
            json_value(risk.get("source_documents", [])), json_value(calculation),
            risk.get("recommendation", "请人工进一步确认。"),
            float(risk.get("confidence", 0.5)), "pending", now, now,
        )
        sql = """
            INSERT INTO risks (
                id,task_id,document_id,level,type,title,description,evidence,source_text,page,section,paragraph_index,
                location_json,regulation_basis_json,company_basis_json,internal_rule_basis_json,historical_cases_json,
                source_documents_json,calculation_json,recommendation,confidence,status,created_at,updated_at
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """
        if connection is None:
            self.database.execute(sql, params)
        else:
            connection.execute(sql, params)

    def list_tasks(self, user: dict[str, Any]) -> list[dict[str, Any]]:
        rows = self.database.fetch_all(
            """
            SELECT t.*,d.filename,u.display_name AS owner_name
            FROM analysis_tasks t LEFT JOIN documents d ON d.id=t.document_id
            LEFT JOIN users u ON u.id=t.owner_user_id
            WHERE t.owner_user_id=?
              AND t.risk_count=(SELECT COUNT(*) FROM risks r WHERE r.task_id=t.id)
            ORDER BY t.updated_at DESC
            """,
            (user["id"],),
        )
        return [
            {
                "id": row["id"], "name": row["name"], "file": row["filename"], "type": row["task_type"],
                "status": row["status"], "risks": row["risk_count"], "highRisks": row["high_count"],
                "owner": row["owner_name"] or "未指定", "updatedAt": row["updated_at"], "aiMode": row["ai_mode"],
            }
            for row in rows
        ]

    def delete_task(self, task_id: str, user: dict[str, Any], ip: str | None) -> dict[str, Any]:
        task = self.database.fetch_one(
            """SELECT t.id,t.owner_user_id,t.document_id,d.file_path,
                      f.html_report_path,f.docx_report_path,f.pdf_report_path
               FROM analysis_tasks t JOIN documents d ON d.id=t.document_id
               LEFT JOIN financial_audit_results f ON f.task_id=t.id WHERE t.id=?""",
            (task_id,),
        )
        if not task:
            raise ValueError("审查任务不存在。")
        if not self._may_access_owned_resource(user, task.get("owner_user_id")):
            raise PermissionError("无权删除该审查任务。")

        document_id = str(task["document_id"])
        related_documents = self.database.fetch_all(
            "SELECT id,file_path,file_hash FROM documents WHERE task_id=?",
            (task_id,),
        )
        if not related_documents:
            related_documents = [{"id": document_id, "file_path": task["file_path"], "file_hash": ""}]
        related_ids = [str(item["id"]) for item in related_documents]
        cached_hashes = [
            row["content_hash"] for related_id in related_ids
            for row in self.database.fetch_all(
                "SELECT DISTINCT content_hash FROM chunks WHERE document_id=?", (related_id,)
            )
        ]
        file_path = Path(str(task["file_path"])).resolve()
        upload_root = self.settings.upload_root.resolve()
        with self.database.connection() as connection:
            deleted = {
                "chunks": sum(
                    connection.execute("SELECT COUNT(*) FROM chunks WHERE document_id=?", (related_id,)).fetchone()[0]
                    for related_id in related_ids
                ),
                "risks": connection.execute("SELECT COUNT(*) FROM risks WHERE task_id=?", (task_id,)).fetchone()[0],
                "reviews": connection.execute(
                    "SELECT COUNT(*) FROM reviews r JOIN risks k ON k.id=r.risk_id WHERE k.task_id=?", (task_id,)
                ).fetchone()[0],
                "conversations": connection.execute("SELECT COUNT(*) FROM conversations WHERE task_id=?", (task_id,)).fetchone()[0],
                "messages": connection.execute(
                    "SELECT COUNT(*) FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE c.task_id=?", (task_id,)
                ).fetchone()[0],
                "memories": connection.execute("SELECT COUNT(*) FROM memory_summaries WHERE task_id=?", (task_id,)).fetchone()[0],
                "usage_records": connection.execute("SELECT COUNT(*) FROM usage_records WHERE task_id=?", (task_id,)).fetchone()[0],
                "financial_audit_results": connection.execute("SELECT COUNT(*) FROM financial_audit_results WHERE task_id=?", (task_id,)).fetchone()[0],
                "meeting_drafts": connection.execute("SELECT COUNT(*) FROM meeting_generation_records WHERE task_id=?", (task_id,)).fetchone()[0],
            }

        for related_id in related_ids:
            self.vector_store.delete_chunks(related_id)
        with self.database.connection() as connection:
            connection.execute("DELETE FROM usage_records WHERE task_id=?", (task_id,))
            connection.execute("DELETE FROM analysis_tasks WHERE id=?", (task_id,))
            placeholders = ",".join("?" for _ in related_ids)
            connection.execute(f"DELETE FROM documents WHERE id IN ({placeholders})", related_ids)
        for content_hash in cached_hashes:
            self.database.execute(
                """DELETE FROM embedding_cache WHERE content_hash=? AND NOT EXISTS (
                       SELECT 1 FROM chunks c WHERE c.content_hash=embedding_cache.content_hash
                         AND c.embedding_model=embedding_cache.embedding_model
                   )""",
                (content_hash,),
            )

        draft_root = (self.settings.upload_root / "meeting-drafts" / str(user["id"]) / task_id).resolve()
        upload_root = self.settings.upload_root.resolve()
        if draft_root.is_relative_to(upload_root) and draft_root.is_dir():
            shutil.rmtree(draft_root)

        file_deleted = False
        for related_document in related_documents:
            related_path = Path(str(related_document.get("file_path") or "")).resolve()
            remaining_file_references = self.database.fetch_one(
                "SELECT COUNT(*) AS total FROM documents WHERE file_path=?", (str(related_path),)
            ) or {"total": 0}
            if int(remaining_file_references["total"]) == 0 and related_path.is_relative_to(upload_root) and related_path.is_file():
                related_path.unlink()
                file_deleted = True

        report_root = (self.settings.upload_root.parent / "reports").resolve()
        report_files_deleted = 0
        for column in ("html_report_path", "docx_report_path", "pdf_report_path"):
            report_path_value = task.get(column)
            if not report_path_value:
                continue
            report_path = Path(str(report_path_value)).resolve()
            if report_path.is_relative_to(report_root) and report_path.is_file():
                report_path.unlink()
                report_files_deleted += 1
        deleted["report_files"] = report_files_deleted

        self.database.audit(
            user["id"], "analysis_task_delete", "analysis_task", task_id, ip,
            after={"deleted": deleted, "file_deleted": file_deleted},
        )
        return {"status": "deleted", "taskId": task_id, "deleted": deleted, "fileDeleted": file_deleted}

    def delete_tasks(self, task_ids: list[Any], user: dict[str, Any], ip: str | None) -> dict[str, Any]:
        """Delete a checked set of the current user's review tasks.

        Validate the complete set before deleting any item so a stale or
        cross-account id cannot result in a partially completed bulk action.
        The existing single-task deletion path remains the source of truth for
        cascading cleanup, vector removal, file safety checks, and audit logs.
        """
        normalized_ids: list[str] = []
        seen: set[str] = set()
        for raw_id in task_ids or []:
            task_id = str(raw_id or "").strip()
            if task_id and task_id not in seen:
                seen.add(task_id)
                normalized_ids.append(task_id)
        if not normalized_ids:
            raise ValueError("请至少选择一项文档审查。")
        if len(normalized_ids) > 100:
            raise ValueError("一次最多批量删除 100 项文档审查。")

        for task_id in normalized_ids:
            task = self.database.fetch_one(
                "SELECT id,owner_user_id FROM analysis_tasks WHERE id=?",
                (task_id,),
            )
            if not task:
                raise ValueError("部分文档审查已不存在，请刷新列表后重试。")
            if not self._may_access_owned_resource(user, task.get("owner_user_id")):
                raise PermissionError("无权删除所选文档审查。")

        # FAISS persists the index after each standalone deletion.  Keep the
        # existing cascade/file/audit path, but defer that disk write until all
        # selected tasks have been removed.
        with self.vector_store.batch_updates():
            deleted_items = [self.delete_task(task_id, user, ip) for task_id in normalized_ids]
        return {
            "status": "deleted",
            "taskCount": len(deleted_items),
            "taskIds": normalized_ids,
            "items": deleted_items,
        }

    def delete_account(
        self,
        target_user_id: str,
        actor: dict[str, Any],
        ip: str | None,
        *,
        self_service: bool = False,
    ) -> dict[str, Any]:
        target = self.database.fetch_one(
            "SELECT id,role,active,deleted_at FROM users WHERE id=?",
            (target_user_id,),
        )
        if not target or target.get("deleted_at"):
            raise ValueError("账号不存在或已经注销。")
        if self_service:
            if str(actor.get("id")) != target_user_id:
                raise PermissionError("只能注销当前登录账号。")
        else:
            if actor.get("role") != "admin":
                raise PermissionError("只有管理员可以注销其他账号。")
            if str(actor.get("id")) == target_user_id:
                raise ValueError("请通过个人注销入口验证当前密码后注销管理员账号。")

        if target["role"] == "admin":
            active_admins = self.database.fetch_one(
                "SELECT COUNT(*) AS total FROM users WHERE role='admin' AND active=1 AND deleted_at IS NULL"
            ) or {"total": 0}
            if int(active_admins["total"]) <= 1:
                raise ValueError("系统必须至少保留一个启用的管理员账号。")

        processing = self.database.fetch_one(
            """SELECT COUNT(*) AS total FROM analysis_jobs
               WHERE owner_user_id=? AND status IN ('queued','processing')""",
            (target_user_id,),
        ) or {"total": 0}
        if int(processing["total"]) > 0:
            raise ValueError("该账号仍有文档正在分析，请等待任务完成后再注销。")

        deleted_counts = {
            "tasks": 0,
            "documents": 0,
            "knowledge_documents": 0,
            "conversations": 0,
            "memories": 0,
        }
        task_ids = [
            row["id"] for row in self.database.fetch_all(
                "SELECT id FROM analysis_tasks WHERE owner_user_id=?",
                (target_user_id,),
            )
        ]
        owner_identity = {"id": target_user_id, "role": target["role"]}
        for task_id in task_ids:
            try:
                self.delete_task(task_id, owner_identity, ip)
                deleted_counts["tasks"] += 1
            except ValueError:
                self.database.execute("DELETE FROM usage_records WHERE task_id=?", (task_id,))
                self.database.execute("DELETE FROM analysis_tasks WHERE id=?", (task_id,))

        orphan_documents = self.database.fetch_all(
            "SELECT id,file_path FROM documents WHERE owner_user_id=?",
            (target_user_id,),
        )
        for document in orphan_documents:
            document_id = str(document["id"])
            hashes = [
                row["content_hash"] for row in self.database.fetch_all(
                    "SELECT DISTINCT content_hash FROM chunks WHERE document_id=?", (document_id,)
                )
            ]
            self.vector_store.delete_chunks(document_id)
            file_path = Path(str(document["file_path"])).resolve()
            self.database.execute("DELETE FROM documents WHERE id=?", (document_id,))
            remaining = self.database.fetch_one(
                "SELECT COUNT(*) AS total FROM documents WHERE file_path=?", (str(file_path),)
            ) or {"total": 0}
            if int(remaining["total"]) == 0 and file_path.is_relative_to(self.settings.upload_root.resolve()) and file_path.is_file():
                file_path.unlink()
            for content_hash in hashes:
                self.database.execute(
                    """DELETE FROM embedding_cache WHERE content_hash=? AND NOT EXISTS (
                           SELECT 1 FROM chunks c WHERE c.content_hash=embedding_cache.content_hash
                             AND c.embedding_model=embedding_cache.embedding_model
                       )""",
                    (content_hash,),
                )
            deleted_counts["documents"] += 1

        owned_knowledge = self.database.fetch_all(
            "SELECT id,file_path FROM knowledge_documents WHERE owner_user_id=?",
            (target_user_id,),
        )
        for document in owned_knowledge:
            knowledge_id = str(document["id"])
            hashes = [
                row["content_hash"] for row in self.database.fetch_all(
                    "SELECT DISTINCT content_hash FROM chunks WHERE knowledge_document_id=?", (knowledge_id,)
                )
            ]
            self.vector_store.delete_chunks(knowledge_id)
            file_path = Path(str(document["file_path"])).resolve()
            self.database.execute("DELETE FROM knowledge_documents WHERE id=?", (knowledge_id,))
            remaining = self.database.fetch_one(
                "SELECT COUNT(*) AS total FROM knowledge_documents WHERE file_path=?", (str(file_path),)
            ) or {"total": 0}
            if int(remaining["total"]) == 0 and file_path.is_relative_to(self.settings.knowledge_root.resolve()) and file_path.is_file():
                file_path.unlink()
            for content_hash in hashes:
                self.database.execute(
                    """DELETE FROM embedding_cache WHERE content_hash=? AND NOT EXISTS (
                           SELECT 1 FROM chunks c WHERE c.content_hash=embedding_cache.content_hash
                             AND c.embedding_model=embedding_cache.embedding_model
                       )""",
                    (content_hash,),
                )
            deleted_counts["knowledge_documents"] += 1

        conversations = self.database.fetch_one(
            "SELECT COUNT(*) AS total FROM conversations WHERE user_id=?", (target_user_id,)
        ) or {"total": 0}
        memories = self.database.fetch_one(
            "SELECT COUNT(*) AS total FROM memory_summaries WHERE user_id=?", (target_user_id,)
        ) or {"total": 0}
        deleted_counts["conversations"] = int(conversations["total"])
        deleted_counts["memories"] = int(memories["total"])

        now = utc_now()
        anonymized_username = f"deleted_{target_user_id.replace('-', '')[:20]}"
        with self.database.connection() as connection:
            connection.execute("DELETE FROM sessions WHERE user_id=?", (target_user_id,))
            connection.execute("DELETE FROM analysis_jobs WHERE owner_user_id=?", (target_user_id,))
            connection.execute("DELETE FROM memory_summaries WHERE user_id=?", (target_user_id,))
            connection.execute("DELETE FROM conversations WHERE user_id=?", (target_user_id,))
            connection.execute("DELETE FROM usage_records WHERE user_id=?", (target_user_id,))
            connection.execute("DELETE FROM company_profiles WHERE owner_user_id=?", (target_user_id,))
            connection.execute(
                """UPDATE users SET username=?,display_name='已注销账号',password_hash='account_deleted',
                       active=0,deleted_at=?,updated_at=? WHERE id=?""",
                (anonymized_username, now, now, target_user_id),
            )
        self.database.audit(
            actor.get("id"), "account_delete", "user", target_user_id, ip,
            after={"self_service": self_service, "deleted": deleted_counts},
        )
        return {"status": "deleted", "userId": target_user_id, "deleted": deleted_counts}

    @staticmethod
    def _may_access_owned_resource(user: dict[str, Any], owner_user_id: str | None) -> bool:
        return bool(owner_user_id) and user.get("id") == owner_user_id

    def get_task_result(
        self,
        task_id: str,
        *,
        ai_message: str = "",
        ai_report: dict[str, Any] | None = None,
        user: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        task = self.database.fetch_one(
            """SELECT t.*,d.filename,d.document_type,d.page_count,d.paragraph_count,d.character_count,d.file_hash,d.metadata_json
               FROM analysis_tasks t JOIN documents d ON d.id=t.document_id WHERE t.id=?""",
            (task_id,),
        )
        if not task:
            raise ValueError("审查任务不存在。")
        if user and not self._may_access_owned_resource(user, task.get("owner_user_id")):
            raise PermissionError("无权访问该审查任务。")
        stale_financial = self.database.fetch_one(
            "SELECT * FROM financial_audit_results WHERE task_id=?",
            (task_id,),
        )
        if (
            stale_financial
            and user
            and str(stale_financial.get("engine_version") or "") != FINANCIAL_AUDIT_ENGINE_VERSION
        ):
            self._refresh_stale_financial_audit(task_id, stale_financial, user)
        metadata = parse_json(task["metadata_json"], {})
        risk_rows = self.database.fetch_all("SELECT * FROM risks WHERE task_id=? ORDER BY created_at", (task_id,))
        risks = [self._risk_to_frontend(row) for row in risk_rows]
        counts = {"high": 0, "medium": 0, "low": 0, "needs_review": 0}
        for risk in risks:
            if risk.get("status") == "false_positive":
                continue
            counts[risk["severity"]] = counts.get(risk["severity"], 0) + 1
        return {
            "taskId": task["id"],
            "documentId": task["document_id"],
            "filename": task["filename"],
            "fileType": task["document_type"].upper(),
            "title": metadata.get("title") or task["name"],
            "pageCount": task["page_count"],
            "paragraphCount": task["paragraph_count"],
            "characterCount": task["character_count"],
            "tableCount": metadata.get("tableCount", sum(
                str(block.get("blockType") or "").lower() == "table"
                for block in metadata.get("blocks", []) if isinstance(block, dict)
            )),
            "paragraphs": metadata.get("paragraphs", []),
            "blocks": metadata.get("blocks", []),
            "headings": metadata.get("headings", []),
            "ocrUsed": bool(metadata.get("ocrUsed")),
            "ocrPages": metadata.get("ocrPages", []),
            "ocrEngine": metadata.get("ocrEngine", ""),
            "risks": risks,
            "summary": {"total": len(risks), **counts},
            "taskType": task["task_type"],
            "rulePack": task["rule_pack"],
            "classification": metadata.get("classification", {}),
            "comparisonDocuments": metadata.get("comparisonDocuments", []),
            "summaryComparisons": metadata.get("summaryComparisons", []),
            "ragCoverage": metadata.get("ragCoverage", {}),
            "periodComparison": metadata.get("periodComparison", {}),
            "summaryComparison": metadata.get("summaryComparison", {}),
            "castingReview": metadata.get("castingReview", {}),
            "meetingCaseComparison": metadata.get("meetingCaseComparison", {}),
            "financialAudit": metadata.get("financialAudit", {}),
            "analysisMode": task["ai_mode"],
            "aiUsed": task["ai_mode"] in {"cloud", "local_llm"} and ai_report is not None,
            "aiMessage": ai_message,
            "aiReport": ai_report,
            "embeddingModel": self.embedding_provider.model_name(),
            "fileHash": task["file_hash"],
            "parserVersion": metadata.get("parserVersion", 1),
            "disclaimer": "系统提供辅助审查，最终合规结论由证券事务人员确认。",
        }

    def get_task_document(self, task_id: str, user: dict[str, Any], ip: str | None) -> tuple[str, bytes]:
        document = self.database.fetch_one(
            """SELECT t.owner_user_id,d.filename,d.file_path FROM analysis_tasks t
               JOIN documents d ON d.id=t.document_id WHERE t.id=?""",
            (task_id,),
        )
        if not document:
            raise ValueError("审查任务或原始文件不存在。")
        if not self._may_access_owned_resource(user, document.get("owner_user_id")):
            raise PermissionError("无权下载该审查文件。")
        path = Path(document["file_path"]).resolve()
        if not path.is_relative_to(self.settings.upload_root.resolve()) or not path.is_file():
            raise ValueError("原始文件不可用。")
        self.database.audit(user["id"], "document_download", "analysis_task", task_id, ip)
        return document["filename"], path.read_bytes()

    def get_task_related_document(
        self,
        task_id: str,
        document_id: str,
        user: dict[str, Any],
        ip: str | None,
    ) -> tuple[str, bytes]:
        document = self.database.fetch_one(
            """SELECT t.owner_user_id,d.filename,d.file_path,d.task_id
               FROM analysis_tasks t JOIN documents d ON d.task_id=t.id
              WHERE t.id=? AND d.id=?""",
            (task_id, document_id),
        )
        if not document:
            raise ValueError("勾稽对比文件不存在。")
        if not self._may_access_owned_resource(user, document.get("owner_user_id")):
            raise PermissionError("无权下载该勾稽对比文件。")
        path = Path(document["file_path"]).resolve()
        if not path.is_relative_to(self.settings.upload_root.resolve()) or not path.is_file():
            raise ValueError("勾稽对比文件不可用。")
        self.database.audit(
            user["id"], "comparison_document_download", "analysis_task", task_id, ip,
            after={"document_id": document_id, "filename": document["filename"]},
        )
        return document["filename"], path.read_bytes()

    def get_task_related_document_preview(
        self,
        task_id: str,
        document_id: str,
        user: dict[str, Any],
        ip: str | None,
    ) -> dict[str, Any]:
        """Return parsed blocks for a comparison document without changing it."""
        document = self.database.fetch_one(
            """SELECT t.owner_user_id,d.filename,d.file_path,d.file_hash
               FROM analysis_tasks t JOIN documents d ON d.task_id=t.id
              WHERE t.id=? AND d.id=?""",
            (task_id, document_id),
        )
        if not document:
            raise ValueError("对比文件不存在。")
        if not self._may_access_owned_resource(user, document.get("owner_user_id")):
            raise PermissionError("无权查看该对比文件。")
        path = Path(document["file_path"]).resolve()
        if not path.is_relative_to(self.settings.upload_root.resolve()) or not path.is_file():
            raise ValueError("对比文件不可用。")
        parsed = parse_document(document["filename"], path.read_bytes(), self.ocr_service)
        title = parsed.paragraphs[0] if parsed.paragraphs and len(parsed.paragraphs[0]) <= 100 else Path(document["filename"]).stem
        self.database.audit(
            user["id"], "comparison_document_preview", "analysis_task", task_id, ip,
            after={"document_id": document_id, "file_hash": document["file_hash"]},
        )
        return {
            "documentId": document_id,
            "filename": document["filename"],
            "fileType": parsed.file_type,
            "fileHash": document["file_hash"],
            "parserVersion": PARSER_VERSION,
            "title": title,
            "pageCount": parsed.page_count,
            "paragraphCount": len(parsed.blocks),
            "characterCount": parsed.character_count,
            "tableCount": sum(block.block_type == "table" for block in parsed.blocks),
            "paragraphs": parsed.paragraphs,
            "headings": parsed.headings,
            "blocks": [
                {
                    "text": block.text,
                    "page": block.page,
                    "section": block.section,
                    "paragraphIndex": block.paragraph_index,
                    "blockType": block.block_type,
                    "sheetName": block.sheet_name,
                    "sourceRowNumbers": list(block.source_row_numbers),
                }
                for block in parsed.blocks
            ],
        }

    def get_annotated_task_document(
        self,
        task_id: str,
        user: dict[str, Any],
        ip: str | None,
    ) -> tuple[str, bytes]:
        document = self.database.fetch_one(
            """SELECT t.owner_user_id,d.filename,d.file_path,d.file_hash FROM analysis_tasks t
               JOIN documents d ON d.id=t.document_id WHERE t.id=?""",
            (task_id,),
        )
        if not document:
            raise ValueError("审查任务或原始文件不存在。")
        if not self._may_access_owned_resource(user, document.get("owner_user_id")):
            raise PermissionError("无权下载该审查文件的批注版。")
        path = Path(document["file_path"]).resolve()
        if not path.is_relative_to(self.settings.upload_root.resolve()) or not path.is_file():
            raise ValueError("原始文件不可用。")
        source = path.read_bytes()
        source_hash = file_digest(source)
        if source_hash != document["file_hash"]:
            raise ValueError("原始文件完整性校验失败，未生成批注版。")
        risk_rows = self.database.fetch_all(
            "SELECT * FROM risks WHERE task_id=? ORDER BY created_at",
            (task_id,),
        )
        risks = [self._risk_to_frontend(row) for row in risk_rows]
        annotated = create_annotated_docx(source, document["filename"], risks)
        if file_digest(path.read_bytes()) != source_hash:
            raise ValueError("原始文件在生成批注版期间发生变化，已中止下载。")
        active_locations = sum(
            len(risk.get("originalLocations") or [])
            for risk in risks if risk.get("status") != "false_positive"
        )
        self.database.audit(
            user["id"], "annotated_document_generate", "analysis_task", task_id, ip,
            after={
                "source_file_hash": source_hash,
                "annotated_file_hash": file_digest(annotated),
                "annotated_locations": active_locations,
            },
        )
        # Preserve the established download filename for compatibility; the
        # file now also contains real Word tracked revisions.
        output_name = f"{Path(document['filename']).stem}_AI合规审阅批注版.docx"
        return output_name, annotated

    def get_task_document_preview(self, task_id: str, user: dict[str, Any], ip: str | None) -> dict[str, Any]:
        document = self.database.fetch_one(
            """SELECT t.owner_user_id,d.filename,d.file_path,d.file_hash FROM analysis_tasks t
               JOIN documents d ON d.id=t.document_id WHERE t.id=?""",
            (task_id,),
        )
        if not document:
            raise ValueError("审查任务或原始文件不存在。")
        if not self._may_access_owned_resource(user, document.get("owner_user_id")):
            raise PermissionError("无权查看该审查文件。")
        path = Path(document["file_path"]).resolve()
        if not path.is_relative_to(self.settings.upload_root.resolve()) or not path.is_file():
            raise ValueError("原始文件不可用。")
        parsed = parse_document(document["filename"], path.read_bytes(), self.ocr_service)
        title = parsed.paragraphs[0] if len(parsed.paragraphs[0]) <= 100 else Path(document["filename"]).stem
        self.database.audit(
            user["id"], "document_preview", "analysis_task", task_id, ip,
            after={"file_hash": document["file_hash"], "parser_version": PARSER_VERSION},
        )
        return {
            "filename": document["filename"],
            "fileType": parsed.file_type,
            "fileHash": document["file_hash"],
            "parserVersion": PARSER_VERSION,
            "title": title,
            "pageCount": parsed.page_count,
            "paragraphCount": len(parsed.blocks),
            "characterCount": parsed.character_count,
            "tableCount": sum(block.block_type == "table" for block in parsed.blocks),
            "paragraphs": parsed.paragraphs,
            "headings": parsed.headings,
            "blocks": [
                {
                    "text": block.text,
                    "page": block.page,
                    "section": block.section,
                    "paragraphIndex": block.paragraph_index,
                    "blockType": block.block_type,
                    "sheetName": block.sheet_name,
                    "sourceRowNumbers": list(block.source_row_numbers),
                }
                for block in parsed.blocks
            ],
        }

    def _local_rag_recommendation(self, row: dict[str, Any], sources: list[dict[str, Any]]) -> str:
        base = str(row.get("recommendation") or "请人工进一步确认。").strip()
        risk_type = str(row.get("type") or "")
        title = str(row.get("title") or "")
        description = str(row.get("description") or "")
        source_text = str(row.get("source_text") or row.get("evidence") or "")

        steps: list[str]
        completion = "修改后逐项回查原文、引用依据和相关附件，由证券事务人员确认后再完成本项复核。"
        if "表述" in risk_type:
            base = (
                "若本句只是说明已经完成的履职过程或内部控制要求，保留原文并标记误报；"
                "若本句承诺未来增长、收益或经营结果，则删除“确保、保证、必然”等措辞，"
                "改为说明预期作用、实现条件和主要不确定性。"
            )
            steps = [
                "事实定性：先区分该句是有底稿支持的已发生事实、履职过程，还是面向未来的预测、承诺或保证。",
                "原文修改：已发生事实应补足时间、主体、程序或数据来源；未来性表述应删除绝对化词语，改成“预期作用 + 实现条件 + 主要不确定性”的结构。",
                "误报处理：若原句只是法律、制度或内部控制要求，且不构成对经营结果的保证，保留原文并在人工复核中标记误报。",
                "联动检查：搜索全文相同或近似表述，避免摘要、风险提示、董事会材料和公告正文口径不一致。",
            ]
            completion = "不存在无依据的收益或结果保证；保留的事实性表述均能对应底稿，必要的条件和风险提示已经同步补充。"
        elif "数据" in risk_type:
            steps = [
                "建立核对表：列出本风险涉及的原数值、单位、币种、含税口径、分母和计算公式。",
                "回查底稿：分别核对协议、财务测算、董事会或股东会材料以及公告中的同一数字，不以当前文档单一表述为准。",
                "原文修改：以已确认底稿为唯一口径，同步修改正文、摘要、表格、合计数和百分比；系统不自动替换具体金额。",
                "复算验证：重新计算比例与合计数，并由另一名复核人员交叉验证四舍五入和单位换算。",
            ]
            completion = "同一事项在协议、决议、公告和财务底稿中的金额、单位、比例与合计数完全一致，计算过程可复核。"
        elif risk_type.startswith("模板选项"):
            option_match = re.search(
                r"[□☑]\s*(适用|是|有)\s*[□☑]\s*(不适用|否|无)",
                source_text,
            )
            left_option = option_match.group(1) if option_match else "第一个选项"
            right_option = option_match.group(2) if option_match else "第二个选项"
            steps = [
                f"事实核验：由材料编制部门依据业务事实、会计底稿或审批材料确认应选择“{left_option}”还是“{right_option}”，系统不得代替作出选择。",
                f"原文修改：仅保留一个勾选结果，即“☑{left_option} □{right_option}”或“□{left_option} ☑{right_option}”；不得两个空白或同时勾选。",
                f"内容联动：选择“{left_option}”时核对后续说明、表格和附注是否完整；选择“{right_option}”时确认后文不存在与“不适用/否/无”相矛盾的数据或说明。",
                "解析复核：若原始 Word/PDF 视觉上已有勾选但解析文本没有，应先保存原文件并重新解析；仍不一致时记录解析异常并按原文件人工确认，不自动补勾。",
            ]
            completion = "原文仅有一个明确勾选，选项与后续说明、财务附注及相关表格一致，并已在解析视图中复核显示结果。"
        elif "关联" in risk_type:
            steps = [
                "主体核验：用最新关联方名录、股权结构和董监高任职关系确认交易对方及其控制链条。",
                "金额核验：按适用规则核对同一关联人、同类交易及连续十二个月累计口径，保留计算明细。",
                "程序核验：检查关联董事或关联股东识别、回避表决、审计委员会或独立董事程序以及董事会、股东会权限。",
                "原文修改：补充关联关系形成原因、交易历史、累计金额、回避情况和已履行/尚需履行的审批披露程序；事实不全时先补材料，不写确定性结论。",
            ]
            completion = "关联关系、累计金额、审批层级和回避表决均有可核验材料，公告中的结论与关联方名录及会议记录一致。"
        elif "期限" in risk_type or "日期" in risk_type:
            steps = [
                "整理时间轴：列明报告期结束、协议签署、审计委员会审核、董事会/股东会审议、预约披露、实际提交和生效日期。",
                "回查凭证：逐项核对通知、签到表、表决票、决议、协议签署页和交易所预约记录，不仅依据正文日期。",
                "原文修改：统一封面、正文、落款、附件和引用文件中的日期格式与时点表述，修正无效或相互矛盾的日期。",
                "期限复算：按命中的现行规则重新计算法定期限和交易日要求；外部系统时间不在上传材料中时保留待人工确认。",
            ]
            completion = "所有时间节点可由原始凭证证明，文内日期一致，法定期限和预约披露要求均已单独复算。"
        elif "审批程序" in risk_type:
            steps = [
                "材料核验：检查会议通知、议案、审核材料、签到表、表决票、会议记录和决议是否齐全。",
                "程序核验：按命中规则确认审议主体、表决比例、回避人员、会议顺序和前置审核程序。",
                "版本核验：比对提交审议版本、会议通过版本和拟披露版本的文件哈希或修订记录。",
                "原文修改：只有在底稿证明程序已经履行后，才补充“会议届次、日期、表决结果和后续程序”；不得根据模板倒推或补造程序事实。",
            ]
            completion = "审议主体、顺序、表决结果和披露版本均有会议底稿支持，正文表述与正式决议一致。"
        elif "签署" in risk_type or "确认" in risk_type:
            steps = [
                "人员清单：按报告期末及审议日名单核对所有应签署人员，确认任职变化和缺席情况。",
                "文件核验：逐一检查书面确认意见、签名页和签署日期；存在反对、弃权或异议时保留理由和处理记录。",
                "原文修改：依据已收集的签署文件补充确认情况，不使用“全体”概括尚未取得的签署。",
                "披露联动：核对重要提示、董事会决议公告和定期报告中的人员范围及措辞保持一致。",
            ]
            completion = "所有应签署人员均可逐一对应书面文件，异议处理完整，定期报告与决议公告的确认口径一致。"
        elif "审计" in risk_type:
            steps = [
                "先确认事实：核对本期财务报告是否审计、审计意见类型以及是否触发必须审计的特殊事项。",
                "检查正式文件：核对审计报告正文、意见类型、会计师事务所和注册会计师签章、报告日期及附件完整性。",
                "原文修改：未经审计时按适用格式明确标注；已经审计时按正式审计报告披露意见类型，不自行概括或改变审计结论。",
                "异常处理：非标准意见或审计状态不明时先补齐报告和说明材料，再由证券事务人员复核披露要求。",
            ]
            completion = "审计状态、意见类型、签章和报告日期均与正式审计文件一致，相关说明和附件齐全。"
        elif "财务报告完整性" in risk_type or ("完整性" in risk_type and "财务" in title + description):
            steps = [
                "原文件核验：先对照目录逐页确认资产负债表、利润表、现金流量表、所有者权益变动表及附注是否真实存在。",
                "解析核验：原文存在但系统未提取时，重新解析或执行本地 OCR，并抽查表头、单位、合计行和页码。",
                "内容补充：原文确实缺失时，由财务部门提供正式报表或附注后补入，不根据相邻数据推算缺失内容。",
                "勾稽检查：复核主表与附注、期初期末数、本期上期数及合并/母公司口径的一致性。",
            ]
            completion = "目录、主表、附注和审计文件齐全，解析文本可定位，关键金额和报表口径完成勾稽复核。"
        elif "跨期及勾稽一致性" in risk_type:
            if title.startswith("跨期比较数不一致"):
                steps = [
                    "定位两端数据：打开本报告原文位置和系统列示的巨潮官方基线页，确认指标名称、合并/母公司范围、单位和报告期间一致。",
                    "核对调整依据：检查会计政策变更、前期差错更正、同一控制合并或合并范围变动是否要求重述，并取得财务底稿和审批材料。",
                    "执行勾稽：将本报告的上年同期数、期初数分别与上年同期报告本期数、上年度报告期末数逐项核对，同时复核主表、附注和管理层分析。",
                    "修改与披露：没有调整依据时统一错误数值；存在合法重述时保留调整前后对照、原因、依据和影响金额，不得只改一处表格。",
                ]
                completion = "本报告比较数和期初数均可追溯至官方上期报告或有充分重述依据，主表、附注、摘要及文字分析口径一致。"
            else:
                steps = [
                    "定位冲突：分别打开风险标注的主表、附注或文字分析位置，确认使用的是同一主体、期间、单位和会计口径。",
                    "回查底稿：从财务报表底稿取得本期数、上期数和计算公式，重新计算合计、差额及同比比例，不以任一披露位置反推正确值。",
                    "统一修改：以经复核的底稿数为准，同时修改主表、附注、管理层讨论、摘要和相关图表，避免只修正当前标注的一处。",
                    "交叉复核：由另一名复核人员重新计算并搜索全文中的同名指标，记录修改前后数值和底稿来源。",
                ]
                completion = "同一指标在主表、附注、文字分析和摘要中数值及计算结果一致，且能够追溯至正式财务底稿。"
        elif "解析完整性" in risk_type:
            steps = [
                "打开原始文件确认页数、清晰度、密码保护、扫描页和表格是否完整。",
                "文本型文件重新解析；扫描页使用本地 OCR，并抽查首尾页、目录页和风险所在页。",
                "比较原文与解析视图的标题、数字、表格和勾选符号；解析不一致时以原始文件为准并记录异常。",
                "在解析完整前暂停对缺失内容作出确定性合规结论。",
            ]
            completion = "原始文件与解析视图的页数、章节、关键数字、表格和选项一致，缺失页或乱码已经排除。"
        elif "完整性" in risk_type:
            steps = [
                "适用性确认：先确认文件类型、事项性质和适用规则包，避免把其他公告模板要求套用到当前文件。",
                "缺项核验：对照命中规则逐项检查章节、要素和备查文件，区分原文缺失与解析遗漏。",
                "原文修改：仅补充规则明确要求且有事实材料支持的内容；缺少事实时列入补充材料，不用模板占位文字代替。",
                "交叉复核：同步检查目录、摘要、正文、附件和决议公告，确保补充内容位置正确且口径一致。",
            ]
            completion = "所有适用的必备章节和材料均已补齐并可定位；不适用项目有明确判断依据，解析遗漏已排除。"
        else:
            steps = [
                "确认风险所指原文、事项主体和业务事实，避免仅按关键词或相似片段判断。",
                "打开命中的本地法规、公司制度和历史材料，核对版本、适用范围、条款上下文和有效状态。",
                "依据已确认事实修改对应段落，并同步检查摘要、表格、附件及相关决议中的同类表述。",
                "证据不足时保留待人工确认或补充材料，不输出确定性结论。",
            ]

        direct_sources: list[tuple[str, str]] = []
        reference_sources: list[tuple[str, str]] = []
        seen: set[tuple[str, Any, str]] = set()
        priority = {
            "regulations": 0, "internal_rules": 1, "company_profile": 2,
            "cases": 3, "announcements": 4, "drafting_materials": 5,
        }
        has_validated_rule = False

        def compact_excerpt(value: Any, limit: int = 180) -> str:
            normalized = re.sub(r"\s+", " ", str(value or "")).strip()
            return normalized if len(normalized) <= limit else normalized[:limit].rstrip() + "…"

        for source in sorted(sources, key=lambda item: priority.get(str(item.get("document_type") or ""), 9)):
            if source.get("document_type") in {"user_documents", "drafting_materials"}:
                continue
            title = str(source.get("title") or "").strip()
            source_key = (title, source.get("page"), str(source.get("section") or ""))
            if not title or source_key in seen:
                continue
            seen.add(source_key)
            article = str(source.get("article") or source.get("section") or "").strip()
            location = " · ".join(
                value for value in (
                    article,
                    str(source.get("version") or "").strip(),
                    f"原文第 {source.get('page')} 页" if source.get("page") and not article else "",
                ) if value
            )
            label = f"《{title}》{f'（{location}）' if location else ''}"
            excerpt = compact_excerpt(source.get("content")) or "当前来源未保存可展示的条款摘要，请打开原文核验。"
            if source.get("document_type") in {"regulations", "internal_rules"}:
                direct_sources.append((label, excerpt))
                has_validated_rule = has_validated_rule or source.get("citation_kind") == "deterministic_rule"
            else:
                reference_sources.append((label, excerpt))
            if len(direct_sources) >= 3:
                break

        def without_prefix(value: str) -> str:
            return value.split("：", 1)[1] if "：" in value else value

        check_parts = [without_prefix(step) for step in steps[:2]]
        modify_parts = [without_prefix(step) for step in steps[2:]] or [base]
        lines = [
            "建议：" + base,
            "1. 核对：" + "；".join(check_parts),
            "2. 修改：" + "；".join(modify_parts),
            "3. 完成标准：" + completion,
        ]
        if direct_sources:
            lines.append("主要依据：" if has_validated_rule else "本地 RAG 候选依据（需核对完整条款）：")
            lines.extend(
                f"- {label}：{excerpt}"
                for label, excerpt in direct_sources[:2]
            )
        elif reference_sources:
            lines.append("本地 RAG 参考资料（非直接规则依据）：")
            lines.extend(
                f"- {label}：{excerpt}"
                for label, excerpt in reference_sources[:2]
            )
            lines.append("当前未命中直接条款，本项保留为待人工确认。")
        else:
            lines.append("本地 RAG：当前未检索到直接法规、公司制度或可核验案例；本项只能作为检查提示，请人工确认、补充材料或标记误报。")
        return "\n".join(lines)

    def _risk_to_frontend(self, row: dict[str, Any]) -> dict[str, Any]:
        location = parse_json(row["location_json"], {})
        page = row["page"] or location.get("page")
        section = row["section"] or location.get("section") or "正文"
        paragraph_index = int(row["paragraph_index"] or 0)
        raw_locations = location.get("items") if isinstance(location.get("items"), list) else []
        if not raw_locations:
            raw_locations = [{
                "label": row["title"],
                "page": page,
                "section": section,
                "paragraphIndex": paragraph_index,
                "text": row["source_text"] or row["evidence"] or "",
            }]
        original_locations = []
        seen_locations: set[tuple[Any, ...]] = set()
        for item in raw_locations:
            if not isinstance(item, dict):
                continue
            item_paragraph = item.get("paragraphIndex")
            try:
                item_paragraph = int(item_paragraph)
            except (TypeError, ValueError):
                item_paragraph = paragraph_index
            item_section = str(item.get("section") or section)
            item_text = str(item.get("text") or "")
            key = (
                item.get("documentId") or item.get("document_id") or "",
                item.get("sheetName") or item.get("sheet_name") or "",
                item.get("spreadsheetRow") or item.get("spreadsheet_row") or "",
                item_paragraph,
                item_section,
                item_text,
            )
            if key in seen_locations:
                continue
            seen_locations.add(key)
            original_locations.append({
                "label": str(item.get("label") or f"原文位置 {len(original_locations) + 1}"),
                "page": item.get("page") or page,
                "section": item_section,
                "paragraphIndex": item_paragraph,
                "text": item_text,
                "spreadsheetRow": item.get("spreadsheetRow") or item.get("spreadsheet_row"),
                "sheetName": str(item.get("sheetName") or item.get("sheet_name") or ""),
                "documentId": str(item.get("documentId") or item.get("document_id") or ""),
            })
        def prepare_sources(value: Any) -> list[dict[str, Any]]:
            prepared = [
                source for source in parse_json(value, [])
                if not (
                    isinstance(source, dict)
                    and source.get("document_type") == "regulations"
                    and source.get("version") in REPEALED_REGULATION_VERSIONS
                )
            ]
            for source in prepared:
                if not isinstance(source, dict) or source.get("citation_kind") != "approved_case":
                    continue
                knowledge_id = source.get("knowledge_document_id") or source.get("document_id")
                if knowledge_id:
                    source.setdefault("source_url", f"/api/knowledge/{knowledge_id}/document")
            return prepared

        sources = prepare_sources(row["source_documents_json"])
        regulation_basis = prepare_sources(row["regulation_basis_json"])
        if not regulation_basis:
            regulation_basis = [
                source for source in sources
                if isinstance(source, dict)
                and (
                    source.get("citation_kind")
                    or (source.get("metadata") if isinstance(source.get("metadata"), dict) else {}).get("citation_kind")
                ) == "deterministic_rule"
            ]
        primary_regulation_basis = self._select_primary_regulation_basis(regulation_basis)
        def basis_key(item: Any) -> tuple[Any, ...]:
            if not isinstance(item, dict):
                return (str(item), "", "")
            return (
                item.get("title"), item.get("article") or item.get("section"),
                item.get("source_url"),
            )

        primary_keys = {basis_key(item) for item in primary_regulation_basis}
        additional_regulation_basis = [
            item for item in regulation_basis
            if basis_key(item) not in primary_keys
        ]
        company_basis = prepare_sources(row["company_basis_json"])
        internal_rule_basis = prepare_sources(row["internal_rule_basis_json"])
        historical_cases = prepare_sources(row["historical_cases_json"])
        calculation = parse_json(row.get("calculation_json"), {})
        if isinstance(calculation, dict):
            calculation = {key: value for key, value in calculation.items() if key != "raw_yoy_rate"}
        else:
            calculation = {}
        recommendation = row["recommendation"]
        if self.settings.ai_mode == "local_rag":
            recommendation = self._local_rag_recommendation(row, sources)
        return {
            "id": row["id"], "title": row["title"], "category": row["type"], "type": row["type"],
            "severity": row["level"], "level": row["level"], "status": row["status"],
            "paragraphIndex": paragraph_index, "paragraph_index": paragraph_index,
            "sourceText": row["source_text"] or row["evidence"] or "", "evidence": row["evidence"] or "",
            "location": (
                f"涉及 {len(original_locations)} 处原文 · 第 {page or '待确认'} 页 · {section}"
                if len(original_locations) > 1
                else f"第 {page or '待确认'} 页 · {section} · 第 {paragraph_index + 1} 段"
            ),
            "page": page, "section": section, "reason": row["description"], "description": row["description"],
            "suggestion": recommendation, "recommendation": recommendation,
            "confidence": row["confidence"], "sourceDocuments": sources,
            "source_documents": sources,
            "originalLocations": original_locations,
            "original_locations": original_locations,
            "regulation_basis": regulation_basis,
            "primaryRegulationBasis": primary_regulation_basis,
            "primary_regulation_basis": primary_regulation_basis,
            "additionalRegulationBasis": additional_regulation_basis,
            "additional_regulation_basis": additional_regulation_basis,
            "regulationBasisMoreCount": len(additional_regulation_basis),
            "company_basis": company_basis,
            "internal_rule_basis": internal_rule_basis,
            "historical_cases": historical_cases,
            "calculation": calculation,
            "financialChange": calculation,
            "revision_text": str(calculation.get("revision_text") or "") if isinstance(calculation, dict) else "",
            "evidenceTitle": "检索来源与确定性规则",
            "evidenceNote": "请打开来源并由证券事务人员核验。",
            "evidenceUrl": "",
        }

    def review_risk(self, risk_id: str, action: str, comment: str, user: dict[str, Any], ip: str | None) -> dict[str, Any]:
        status_map = {
            "confirm": "confirmed",
            "ignore": "false_positive",
            "supplement": "needs_material",
            "resolve": "resolved",
            "reopen": "pending",
        }
        if action not in status_map:
            raise ValueError("复核操作无效。")
        risk = self.database.fetch_one(
            "SELECT r.*,t.owner_user_id FROM risks r JOIN analysis_tasks t ON t.id=r.task_id WHERE r.id=?",
            (risk_id,),
        )
        if not risk:
            raise ValueError("风险不存在。")
        if not self._may_access_owned_resource(user, risk.get("owner_user_id")):
            raise PermissionError("无权复核该风险。")
        if action == "reopen" and risk["status"] == "pending":
            raise ValueError("该风险尚未处理，无需撤销。")
        new_status = status_map[action]
        now = utc_now()
        review_id = str(uuid.uuid4())
        with self.database.connection() as connection:
            connection.execute("UPDATE risks SET status=?,updated_at=? WHERE id=?", (new_status, now, risk_id))
            connection.execute(
                "INSERT INTO reviews (id,risk_id,user_id,action,before_json,after_json,comment,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (review_id, risk_id, user["id"], action, json_value({"status": risk["status"]}), json_value({"status": new_status}), comment, now),
            )
            active_high = connection.execute(
                "SELECT COUNT(*) FROM risks WHERE task_id=? AND level='high' AND status<>'false_positive'",
                (risk["task_id"],),
            ).fetchone()[0]
            connection.execute(
                "UPDATE analysis_tasks SET high_count=?,updated_at=? WHERE id=?",
                (active_high, now, risk["task_id"]),
            )
        self.database.audit(user["id"], "risk_review", "risk", risk_id, ip, {"status": risk["status"]}, {"status": new_status, "comment": comment})
        return {"id": risk_id, "status": new_status, "review_id": review_id}

    def generate_report(self, task_id: str, user: dict[str, Any], ip: str | None) -> dict[str, Any]:
        report = self.get_task_result(task_id, user=user)
        report["generatedAt"] = utc_now()
        report["generatedBy"] = user.get("display_name") or user.get("username") or "当前用户"
        report["reviewSummary"] = {
            "pending": sum(1 for risk in report["risks"] if risk["status"] == "pending"),
            "confirmed": sum(1 for risk in report["risks"] if risk["status"] == "confirmed"),
            "falsePositive": sum(1 for risk in report["risks"] if risk["status"] == "false_positive"),
            "needsMaterial": sum(1 for risk in report["risks"] if risk["status"] == "needs_material"),
            "resolved": sum(1 for risk in report["risks"] if risk["status"] == "resolved"),
        }
        self.database.audit(
            user["id"], "report_generate", "analysis_task", task_id, ip,
            after={"risk_count": report["summary"]["total"], "review_summary": report["reviewSummary"]},
        )
        return report

    def list_drafts(self, user: dict[str, Any]) -> list[dict[str, Any]]:
        rows = self.database.fetch_all(
            """SELECT id,title,document_type,subject,status,created_at,updated_at,
                      source_documents_json,warnings_json
                 FROM draft_documents WHERE owner_user_id=? ORDER BY updated_at DESC""",
            (user["id"],),
        )
        return [
            {
                "id": row["id"],
                "title": row["title"],
                "document_type": row["document_type"],
                "subject": row["subject"],
                "status": row["status"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "source_count": len(parse_json(row["source_documents_json"], [])),
                "warnings": parse_json(row["warnings_json"], []),
            }
            for row in rows
        ]

    def get_draft(self, draft_id: str, user: dict[str, Any]) -> dict[str, Any]:
        row = self.database.fetch_one(
            "SELECT * FROM draft_documents WHERE id=? AND owner_user_id=?",
            (draft_id, user["id"]),
        )
        if not row:
            raise ValueError("草稿不存在或无权访问。")
        sources = parse_json(row["source_documents_json"], [])
        style_sources = _select_company_style_sources(
            sources,
            limit=2 if row["document_type"] == "szse_report_brief" else 3,
            include_all_company_announcements=row["document_type"] == "szse_report_brief",
        ) if row["document_type"] in {"periodic_report_notice", "szse_report_brief"} else []
        return {
            "id": row["id"],
            "title": row["title"],
            "document_type": row["document_type"],
            "subject": row["subject"],
            "input": parse_json(row["input_json"], {}),
            "content": row["content"],
            "sections": parse_json(row["sections_json"], []),
            "source_documents": sources,
            "style_sources": style_sources,
            "structured_facts": parse_json(row.get("structured_facts_json"), []),
            "timeline": parse_json(row.get("timeline_json"), []),
            "conflicts": parse_json(row.get("conflicts_json"), []),
            "warnings": parse_json(row["warnings_json"], []),
            "status": row["status"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def _direct_reference_context(
        self,
        filename: str,
        content: bytes,
        *,
        document_type: str,
    ) -> tuple[RAGContext, dict[str, Any]]:
        """Parse one user-supplied meeting document for this draft only.

        The reference is intentionally not inserted into the shared knowledge
        base.  This prevents a single meeting proposal from polluting later
        drafts with unrelated RAG citations while retaining page/section
        provenance in the saved draft.
        """
        allowed = {".pdf", ".doc", ".docx", ".txt", ".md", ".csv", ".xls", ".xlsx"}
        if Path(filename).suffix.lower() not in allowed:
            raise ValueError("会议参考文书仅支持 PDF、DOC/DOCX、XLS/XLSX、CSV、TXT 或 MD。")
        parsed = parse_document(filename, content, self.ocr_service)
        reference_id = f"draft-reference-{file_digest(content)[:24]}"
        title = Path(filename).stem[:120] or "本次会议参考文书"
        full_text = "\n".join(parsed.paragraphs)
        meeting_details = extract_meeting_details(full_text)
        metadata = {
            "file_name": filename,
            "document_name": title,
            "source_type": "direct_draft_reference",
            "direct_reference": True,
            "case_role": infer_case_role(filename, full_text),
            "meeting_type": infer_meeting_kind(filename, full_text),
            "meeting_term": meeting_term(filename, full_text),
            **meeting_details,
            "document_updated_at": utc_now(),
        }
        chunks = self.chunker.chunk(reference_id, parsed, "drafting_materials", metadata)
        results = [
            SearchResult(
                chunk_id=chunk.id,
                document_id=reference_id,
                content=chunk.content,
                title=filename,
                source=filename,
                date=None,
                page=chunk.page,
                paragraph=chunk.paragraph,
                section=chunk.section,
                document_type="drafting_materials",
                score=1.0,
                source_url=None,
                version=None,
                metadata=chunk.metadata,
            )
            for chunk in chunks
        ]
        if not results:
            raise DocumentParseError("会议参考文书未解析出可用正文，请检查文件内容或先进行 OCR。")
        return RAGContext(f"本次会议参考文书：{filename}", results), {
            "filename": filename,
            "content": content,
            "title": title,
            "meeting_term": metadata["meeting_term"],
            "meeting_type": metadata["meeting_type"],
        }

    def create_draft_from_reference(
        self,
        filename: str,
        content: bytes,
        payload: dict[str, Any],
        user: dict[str, Any],
        ip: str | None,
    ) -> dict[str, Any]:
        """Create a meeting draft using only the uploaded reference document."""
        requested = str(payload.get("document_type") or "meeting_sign_in").strip()
        if requested in {"", AUTO_SELECTION}:
            inferred = _infer_draft_document_type(
                AUTO_SELECTION,
                str(payload.get("subject") or ""),
                str(payload.get("facts") or ""),
                str(payload.get("requirements") or ""),
            )
            requested = inferred if inferred in MEETING_DOCUMENT_TYPES else "meeting_sign_in"
        if requested not in MEETING_DOCUMENT_TYPES and requested not in {"board_resolution", "shareholder_resolution"}:
            raise ValueError("本次参考文书导入仅适用于会议签到表、会议通知、会议议案、会议记录、总经理会议或会议决议。")
        context, reference = self._direct_reference_context(
            filename, content, document_type=requested,
        )
        next_payload = dict(payload)
        next_payload["document_type"] = requested
        subject = str(next_payload.get("subject") or "").strip()
        if not subject:
            subject = str(reference.get("meeting_term") or "").strip() or reference["title"]
            next_payload["subject"] = subject
        # Direct references are deliberately the only evidence group.  No
        # regulations, announcements or historical templates are retrieved.
        return self.create_draft(
            next_payload,
            user,
            ip,
            direct_context=context,
            direct_reference=reference,
        )

    def create_draft(
        self,
        payload: dict[str, Any],
        user: dict[str, Any],
        ip: str | None,
        *,
        direct_context: RAGContext | None = None,
        direct_reference: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        requested_document_type = str(payload.get("document_type") or "temporary_announcement").strip()
        if requested_document_type not in DOCUMENT_TYPES and requested_document_type not in {"", AUTO_SELECTION}:
            raise ValueError("文书类型无效。")
        title = str(payload.get("title") or "").strip()
        subject = str(payload.get("subject") or "").strip()
        facts = str(payload.get("facts") or "").strip()
        requirements = str(payload.get("requirements") or "").strip()
        document_type = _infer_draft_document_type(
            requested_document_type, subject, facts, requirements,
        )
        if document_type not in DOCUMENT_TYPES:
            raise ValueError("文书类型无效。")
        if len(title) > 120 or len(subject) > 4000 or len(facts) > 12000 or len(requirements) > 6000:
            raise ValueError("起草输入超过长度限制。")
        if not subject and not facts and not requirements:
            raise ValueError("请至少填写事项主题、已确认事实或起草要求。")
        meeting_draft = document_type in MEETING_DOCUMENT_TYPES or document_type in {
            "board_resolution", "shareholder_resolution",
        }
        structured_bundle = None
        if document_type == "szse_report_brief":
            structured_bundle = self.fact_engine.build_bundle(
                " ".join(value for value in (subject, facts, requirements) if value),
                user_id=str(user["id"]),
                company=COMPANY_NAME,
            )
        query = " ".join(
            value for value in (
                DOCUMENT_TYPES[document_type]["label"],
                subject,
                facts,
                requirements,
                "公司章程 信息披露管理制度 关联交易管理制度 对外投资管理制度 深交所规则 证监会规则 历史公告",
                "会议通知 会议议案 会议记录 会议决议 表决结果 会议发言" if meeting_draft else "",
            ) if value
        )
        if direct_context is not None:
            context = direct_context
        elif document_type in {"periodic_report_notice", "szse_report_brief"}:
            # Keep company wording/style references separate in retrieval
            # priority.  Rules remain evidence; historical reports only guide
            # section order and disclosure phrasing.
            if document_type == "szse_report_brief":
                style_query = " ".join((
                    "创业黑马 公司业务发展历史 主营业务演变 历史公告 起草文书 汇报材料 模板 范本 重组进展 重大事项",
                    subject,
                    facts,
                    requirements,
                )).strip()
                rule_query = " ".join((
                    query,
                    "深交所 持续监管 信息披露 重大事项 资产重组 重组进展 监管沟通",
                )).strip()
                style_top_k, rule_top_k = 6, 8
            else:
                style_query = " ".join(("创业黑马 历史 年度报告 半年度报告 定期报告 起草文书 模板 范本", subject, facts)).strip()
                rule_query = query
                style_top_k, rule_top_k = 6, 8
            # Historical announcements provide company facts and wording. A
            # separate drafting-materials retrieval supplies approved templates
            # and prior reports without making those templates regulatory basis.
            if document_type == "szse_report_brief":
                announcement_queries = [
                    " ".join((
                        "创业黑马 公司业务发展历史 主营业务演变 公司简介 核心竞争力",
                        subject,
                        requirements,
                    )).strip(),
                    " ".join((
                        "创业黑马 重组 重大资产重组 收购 出售 重组进展 方案 监管沟通",
                        subject,
                        requirements,
                    )).strip(),
                ]
                announcement_contexts = [
                    self.rag.retrieve(
                        announcement_query,
                        top_k=max(2, style_top_k // 2),
                        threshold=0.04,
                        document_types=["announcements"],
                        user_id=str(user["id"]),
                    )
                    for announcement_query in announcement_queries
                ]
                announcement_results = []
                seen_announcement_chunks: set[str] = set()
                for announcement_context in announcement_contexts:
                    for result in announcement_context.results:
                        if result.chunk_id in seen_announcement_chunks:
                            continue
                        announcement_results.append(result)
                        seen_announcement_chunks.add(result.chunk_id)
                announcement_style_context = RAGContext(style_query, announcement_results[:style_top_k])
            else:
                announcement_style_context = self.rag.retrieve(
                    style_query,
                    top_k=style_top_k,
                    threshold=0.04,
                    document_types=["announcements"],
                    user_id=str(user["id"]),
                )
            drafting_style_context = self.rag.retrieve(
                style_query,
                top_k=max(2, style_top_k // 2),
                threshold=0.04,
                document_types=["drafting_materials"],
                user_id=str(user["id"]),
            )
            style_context = self._merge_rag_contexts(
                announcement_style_context,
                drafting_style_context,
                style_top_k,
            )
            rule_context = self.rag.retrieve(
                rule_query,
                top_k=rule_top_k,
                threshold=0.06,
                document_types=["regulations", "internal_rules", "company_profile", "cases"],
                current_regulations_only=True,
                user_id=str(user["id"]),
            )
            if not announcement_style_context.results:
                if document_type == "szse_report_brief":
                    keyword_results = []
                    seen_keyword_chunks: set[str] = set()
                    for announcement_query in announcement_queries:
                        keyword_context = self.rag.retrieve_keyword(
                            announcement_query,
                            top_k=max(2, style_top_k // 2),
                            document_types=["announcements"],
                            user_id=str(user["id"]),
                        )
                        for result in keyword_context.results:
                            if result.chunk_id in seen_keyword_chunks:
                                continue
                            keyword_results.append(result)
                            seen_keyword_chunks.add(result.chunk_id)
                    announcement_style_context = RAGContext(style_query, keyword_results[:style_top_k])
                else:
                    announcement_style_context = self.rag.retrieve_keyword(
                        style_query,
                        top_k=style_top_k,
                        document_types=["announcements"],
                        user_id=str(user["id"]),
                    )
            if not drafting_style_context.results:
                drafting_style_context = self.rag.retrieve_keyword(
                    style_query,
                    top_k=max(2, style_top_k // 2),
                    document_types=["drafting_materials"],
                    user_id=str(user["id"]),
                )
            style_context = self._merge_rag_contexts(
                announcement_style_context,
                drafting_style_context,
                style_top_k,
            )
            if not rule_context.results:
                rule_context = self.rag.retrieve_keyword(
                    rule_query,
                    top_k=rule_top_k,
                    current_regulations_only=True,
                    user_id=str(user["id"]),
                )
            if document_type == "szse_report_brief":
                # Keep the one-page source list balanced: historical company
                # announcements establish wording and chronology, approved
                # drafting materials establish document structure, while rules
                # provide the reporting basis. A missing source group remains
                # visible as a待补充 warning instead of being invented.
                selected_results = []
                seen_chunks: set[str] = set()
                drafting_style_results = [
                    result for result in style_context.results
                    if result.document_type == "drafting_materials"
                ]
                announcement_style_results = [
                    result for result in style_context.results
                    if result.document_type == "announcements"
                ]
                other_style_results = [
                    result for result in style_context.results
                    if result.document_type not in {"drafting_materials", "announcements"}
                ]
                ordered_results = [
                    *drafting_style_results[:1], *announcement_style_results[:2],
                    *other_style_results[:1], *drafting_style_results[1:],
                    *announcement_style_results[2:], *rule_context.results,
                ]
                for result in ordered_results:
                    if result.chunk_id in seen_chunks:
                        continue
                    selected_results.append(result)
                    seen_chunks.add(result.chunk_id)
                    if len(selected_results) >= 8:
                        break
                context = RAGContext(query, selected_results)
            else:
                context = self._merge_rag_contexts(style_context, rule_context, 12)
        else:
            if meeting_draft:
                # Meeting documents need two independent evidence groups:
                # company wording/case material for the proposal and rules for
                # the compliance discussion. This keeps a rule heading from
                # becoming a fabricated proposal while still citing the rule.
                case_query = " ".join((query, "同类会议议案 会议记录 会议决议 公告 审议 发言")).strip()
                case_types = ["drafting_materials", "announcements", "cases", "user_documents", "company_profile"]
                case_context = self.rag.retrieve(
                    case_query,
                    top_k=10,
                    threshold=0.04,
                    document_types=case_types,
                    user_id=str(user["id"]),
                )
                rule_context = self.rag.retrieve(
                    query,
                    top_k=8,
                    threshold=0.06,
                    document_types=["regulations", "internal_rules"],
                    current_regulations_only=True,
                    user_id=str(user["id"]),
                )
                if not case_context.results:
                    case_context = self.rag.retrieve_keyword(
                        case_query, top_k=10, document_types=case_types, user_id=str(user["id"]),
                    )
                if not rule_context.results:
                    rule_context = self.rag.retrieve_keyword(
                        query, top_k=8, document_types=["regulations", "internal_rules"],
                        current_regulations_only=True, user_id=str(user["id"]),
                    )
                context = self._merge_rag_contexts(case_context, rule_context, 16)
            else:
                context = self.rag.retrieve(
                    query,
                    top_k=12,
                    threshold=0.06,
                    # Drafting templates are reserved for periodic-report and
                    # brief-drafting style retrieval; they must not become the
                    # basis of an ordinary compliance conclusion.
                    document_types=[
                        "company_profile", "internal_rules", "regulations",
                        "announcements", "cases", "user_documents",
                    ],
                    current_regulations_only=True,
                    user_id=str(user["id"]),
                )
                if not context.results:
                    # Keyword fallback keeps drafting usable while a newly imported local
                    # corpus is still waiting for semantic vectors.
                    context = self.rag.retrieve_keyword(
                        query,
                        top_k=12,
                        document_types=[
                            "company_profile", "internal_rules", "regulations",
                            "announcements", "cases", "user_documents",
                        ],
                        current_regulations_only=True,
                        user_id=str(user["id"]),
                    )
        draft = build_draft(
            document_type=document_type,
            title=title,
            subject=subject,
            facts=facts,
            requirements=requirements,
            context=context,
            structured_bundle=structured_bundle,
        )
        draft_id = str(uuid.uuid4())
        now = utc_now()
        draft_root = (self.settings.upload_root.parent / "drafts" / str(user["id"])).resolve()
        draft_root.mkdir(parents=True, exist_ok=True)
        filename = f"{draft_id}_{safe_filename(draft.title)[:80]}.docx"
        document_path = (draft_root / filename).resolve()
        runtime_root = self.settings.upload_root.parent.resolve()
        if not document_path.is_relative_to(runtime_root):
            raise ValueError("草稿保存路径无效。")
        reference_path: Path | None = None
        if direct_reference:
            reference_name = safe_filename(str(direct_reference.get("filename") or "reference.docx"))
            reference_path = (draft_root / f"{draft_id}_reference_{reference_name}").resolve()
            if not reference_path.is_relative_to(runtime_root):
                raise ValueError("会议参考文书保存路径无效。")
            reference_path.write_bytes(bytes(direct_reference.get("content") or b""))
            reference_url = f"/api/drafts/{draft_id}/reference-document"
            for source in draft.sources:
                if source.get("metadata", {}).get("direct_reference"):
                    source["source_url"] = reference_url
        document_path.write_bytes(build_docx(
            title=draft.title,
            content=draft.content,
            sources=draft.sources,
            compact=document_type == "szse_report_brief",
        ))
        input_payload = {
            "title": title,
            "subject": subject,
            "facts": facts,
            "requirements": requirements,
            "document_type": document_type,
            "retrieval_mode": self.settings.retrieval_mode,
            "embedding_model": self.embedding_provider.model_name(),
            "direct_reference": bool(direct_reference),
            "reference_filename": direct_reference.get("filename") if direct_reference else "",
            "reference_path": str(reference_path) if reference_path else "",
        }
        self.database.execute(
            """INSERT INTO draft_documents (
                 id,owner_user_id,title,document_type,subject,input_json,content,sections_json,
                 source_documents_json,structured_facts_json,timeline_json,conflicts_json,warnings_json,
                 file_path,status,created_at,updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                draft_id, user["id"], draft.title, draft.document_type, subject,
                json_value(input_payload), draft.content, json_value(draft.sections),
                json_value(draft.sources),
                json_value((structured_bundle or {}).get("facts", [])),
                json_value((structured_bundle or {}).get("timeline", [])),
                json_value((structured_bundle or {}).get("conflicts", [])),
                json_value(draft.warnings), str(document_path),
                "draft", now, now,
            ),
        )
        self.database.audit(
            user["id"], "draft_create", "draft_document", draft_id, ip,
            after={
                "document_type": draft.document_type,
                "source_count": len(draft.sources),
                "embedding_model": self.embedding_provider.model_name(),
                "external_ai_used": False,
            },
        )
        result = self.get_draft(draft_id, user)
        result["draft_type_label"] = DOCUMENT_TYPES[draft.document_type]["label"]
        result["source_count"] = len(draft.sources)
        return result

    def update_draft(self, draft_id: str, payload: dict[str, Any], user: dict[str, Any], ip: str | None) -> dict[str, Any]:
        row = self.database.fetch_one(
            "SELECT * FROM draft_documents WHERE id=? AND owner_user_id=?",
            (draft_id, user["id"]),
        )
        if not row:
            raise ValueError("草稿不存在或无权访问。")
        content = str(payload.get("content") or "")
        title = str(payload.get("title") or row["title"]).strip()[:120]
        if not content.strip() or len(content) > 200000:
            raise ValueError("草稿正文不能为空或超过长度限制。")
        now = utc_now()
        file_path = Path(str(row.get("file_path") or "")).resolve()
        runtime_root = self.settings.upload_root.parent.resolve()
        if file_path and file_path.is_relative_to(runtime_root):
            file_path.write_bytes(build_docx(
                title=title,
                content=content,
                sources=parse_json(row["source_documents_json"], []),
                compact=row["document_type"] == "szse_report_brief",
            ))
        self.database.execute(
            "UPDATE draft_documents SET title=?,content=?,status='edited',updated_at=? WHERE id=? AND owner_user_id=?",
            (title, content, now, draft_id, user["id"]),
        )
        self.database.audit(user["id"], "draft_update", "draft_document", draft_id, ip, after={"status": "edited"})
        return self.get_draft(draft_id, user)

    def get_draft_document(self, draft_id: str, user: dict[str, Any], ip: str | None) -> tuple[str, bytes]:
        row = self.database.fetch_one(
            "SELECT title,file_path,owner_user_id FROM draft_documents WHERE id=?",
            (draft_id,),
        )
        if not row:
            raise ValueError("草稿不存在。")
        if not self._may_access_owned_resource(user, row.get("owner_user_id")):
            raise PermissionError("无权下载该草稿。")
        path = Path(str(row.get("file_path") or "")).resolve()
        if not path.is_relative_to(self.settings.upload_root.parent.resolve()) or not path.is_file():
            raise ValueError("草稿文件不可用。")
        self.database.audit(user["id"], "draft_download", "draft_document", draft_id, ip)
        return f"{safe_filename(str(row['title']))}.docx", path.read_bytes()

    def get_draft_reference_document(self, draft_id: str, user: dict[str, Any], ip: str | None) -> tuple[str, bytes]:
        row = self.database.fetch_one(
            "SELECT title,owner_user_id,input_json FROM draft_documents WHERE id=?",
            (draft_id,),
        )
        if not row:
            raise ValueError("草稿不存在。")
        if not self._may_access_owned_resource(user, row.get("owner_user_id")):
            raise PermissionError("无权查看该会议参考文书。")
        payload = parse_json(row.get("input_json"), {})
        path = Path(str(payload.get("reference_path") or "")).resolve()
        runtime_root = self.settings.upload_root.parent.resolve()
        if not path or not path.is_relative_to(runtime_root) or not path.is_file():
            raise ValueError("该草稿没有可查看的会议参考文书。")
        self.database.audit(user["id"], "draft_reference_view", "draft_document", draft_id, ip)
        return str(payload.get("reference_filename") or path.name), path.read_bytes()

    def delete_draft(self, draft_id: str, user: dict[str, Any], ip: str | None) -> dict[str, Any]:
        row = self.database.fetch_one(
            "SELECT * FROM draft_documents WHERE id=? AND owner_user_id=?",
            (draft_id, user["id"]),
        )
        if not row:
            raise ValueError("草稿不存在或无权删除。")
        path = Path(str(row.get("file_path") or "")).resolve()
        runtime_root = self.settings.upload_root.parent.resolve()
        if path.is_relative_to(runtime_root) and path.is_file():
            path.unlink()
        input_payload = parse_json(row.get("input_json"), {})
        reference_path = Path(str(input_payload.get("reference_path") or "")).resolve()
        if reference_path.is_relative_to(runtime_root) and reference_path.is_file():
            reference_path.unlink()
        self.database.execute("DELETE FROM draft_documents WHERE id=? AND owner_user_id=?", (draft_id, user["id"]))
        self.database.audit(user["id"], "draft_delete", "draft_document", draft_id, ip, before={"title": row["title"]})
        return {"status": "deleted", "draftId": draft_id}

    def chat(
        self,
        task_id: str,
        question: str,
        conversation_id: str | None,
        user: dict[str, Any],
        ip: str | None,
    ) -> dict[str, Any]:
        task = self.database.fetch_one("SELECT * FROM analysis_tasks WHERE id=?", (task_id,))
        if not task:
            raise ValueError("审查任务不存在。")
        if not self._may_access_owned_resource(user, task.get("owner_user_id")):
            raise PermissionError("无权访问该审查任务。")
        if not question.strip():
            raise ValueError("请输入问题。")
        now = utc_now()
        if conversation_id:
            conversation = self.database.fetch_one("SELECT * FROM conversations WHERE id=? AND user_id=?", (conversation_id, user["id"]))
            if not conversation:
                raise ValueError("对话不存在或无权访问。")
        else:
            conversation_id = str(uuid.uuid4())
            self.database.execute(
                "INSERT INTO conversations (id,task_id,user_id,title,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                (conversation_id, task_id, user["id"], question.strip()[:80], now, now),
            )
        self.database.execute(
            "INSERT INTO messages (id,conversation_id,role,content,created_at) VALUES (?,?,?,?,?)",
            (str(uuid.uuid4()), conversation_id, "user", question.strip(), now),
        )
        message_rows = self.database.fetch_all(
            "SELECT role,content FROM messages WHERE conversation_id=? ORDER BY created_at DESC LIMIT 12",
            (conversation_id,),
        )
        memory_rows = self.database.fetch_all(
            "SELECT summary FROM memory_summaries WHERE task_id=? AND user_id=? AND conversation_id<>? ORDER BY updated_at DESC LIMIT 3",
            (task_id, user["id"], conversation_id),
        )
        risk_rows = self.database.fetch_all(
            "SELECT title,status,description FROM risks WHERE task_id=? ORDER BY created_at LIMIT 20",
            (task_id,),
        )
        memory_parts = []
        if memory_rows:
            memory_parts.append("同一任务的历史对话摘要：" + "\n".join(row["summary"] for row in memory_rows))
        if risk_rows:
            memory_parts.append("当前任务风险状态：" + "；".join(
                f"{row['title']}[{row['status']}]：{row['description'][:120]}" for row in risk_rows
            ))
        messages = list(reversed(message_rows))[-10:]
        if memory_parts:
            messages.insert(0, {"role": "system", "content": "\n\n".join(memory_parts)})
        structured_bundle = None
        if self.settings.ai_mode == "local_rag" and any(
            term in question for term in ("业务发展历史", "主营业务", "重组", "重大资产", "目前进展", "最新进展", "交易状态")
        ):
            structured_bundle = self.fact_engine.build_bundle(
                question,
                user_id=str(user["id"]),
                company=COMPANY_NAME,
            )
        if structured_bundle and structured_bundle.get("facts"):
            answer = self.fact_engine.format_answer(structured_bundle)
            citations = structured_bundle.get("citations", [])
            self.database.execute(
                "INSERT INTO messages (id,conversation_id,role,content,citations_json,input_tokens,output_tokens,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), conversation_id, "assistant", answer, json_value(citations), 0, 0, utc_now()),
            )
            self.database.execute("UPDATE conversations SET updated_at=? WHERE id=?", (utc_now(), conversation_id))
            self._update_summary_memory(task_id, conversation_id, user["id"])
            self.database.audit(user["id"], "local_structured_answer", "conversation", conversation_id, ip, after={
                "task_id": task_id,
                "fact_count": len(structured_bundle.get("facts", [])),
                "timeline_count": len(structured_bundle.get("timeline", [])),
                "conflict_count": len(structured_bundle.get("conflicts", [])),
                "external_ai_used": False,
            })
            return {
                "conversation_id": conversation_id,
                "answer": answer,
                "source_documents": citations,
                "mode": "local_rag_structured_facts",
                "structured_facts": structured_bundle.get("facts", []),
                "timeline": structured_bundle.get("timeline", []),
                "conflicts": structured_bundle.get("conflicts", []),
                "evidence_chains": structured_bundle.get("evidence_chains", []),
                "usage": {"input_tokens": 0, "output_tokens": 0},
            }
        context = self.rag.retrieve(
            question,
            top_k=8,
            threshold=0.06,
            document_types=["company_profile", "internal_rules", "regulations", "announcements", "cases"],
            current_regulations_only=True,
            task_document_id=task["document_id"],
            user_id=str(user["id"]),
        )
        provider = self.ai_provider
        if not provider:
            raise AIServiceError(self.ai_configuration_error or "AI 服务尚未配置，请联系管理员。")
        result = provider.chat(messages, context)
        self.database.execute(
            "INSERT INTO messages (id,conversation_id,role,content,citations_json,input_tokens,output_tokens,created_at) VALUES (?,?,?,?,?,?,?,?)",
            (str(uuid.uuid4()), conversation_id, "assistant", result.content, json_value(result.citations), result.input_tokens, result.output_tokens, utc_now()),
        )
        self.database.execute("UPDATE conversations SET updated_at=? WHERE id=?", (utc_now(), conversation_id))
        self._update_summary_memory(task_id, conversation_id, user["id"])
        self._record_usage(user["id"], task_id, provider.name(), result.model, "chat", result.input_tokens, result.output_tokens)
        self.database.audit(user["id"], "ai_chat", "conversation", conversation_id, ip, after={
            "task_id": task_id,
            "mode": self.settings.ai_mode,
            "citations": len(result.citations),
            "task_memory_loaded": bool(memory_parts),
        })
        return {
            "conversation_id": conversation_id,
            "answer": result.content,
            "source_documents": result.citations,
            "mode": self.settings.ai_mode,
            "usage": {"input_tokens": result.input_tokens, "output_tokens": result.output_tokens},
        }

    def _update_summary_memory(self, task_id: str, conversation_id: str, user_id: str) -> None:
        messages = self.database.fetch_all(
            "SELECT role,content FROM messages WHERE conversation_id=? ORDER BY created_at DESC LIMIT 10",
            (conversation_id,),
        )
        summary = "；".join(
            f"{('用户' if row['role']=='user' else '系统')}：{row['content'][:160]}" for row in reversed(messages)
        )
        existing = self.database.fetch_one("SELECT id FROM memory_summaries WHERE conversation_id=?", (conversation_id,))
        now = utc_now()
        if existing:
            self.database.execute(
                "UPDATE memory_summaries SET summary=?,confirmed=0,updated_at=? WHERE id=?",
                (summary, now, existing["id"]),
            )
        else:
            self.database.execute(
                "INSERT INTO memory_summaries (id,task_id,conversation_id,user_id,summary,confirmed,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)",
                (str(uuid.uuid4()), task_id, conversation_id, user_id, summary, 0, now, now),
            )

    def list_conversations(self, user: dict[str, Any], task_id: str | None = None) -> list[dict[str, Any]]:
        sql = "SELECT * FROM conversations WHERE user_id=?"
        params: list[Any] = [user["id"]]
        if task_id:
            sql += " AND task_id=?"
            params.append(task_id)
        sql += " ORDER BY updated_at DESC"
        return self.database.fetch_all(sql, params)

    def get_messages(self, conversation_id: str, user: dict[str, Any]) -> list[dict[str, Any]]:
        conversation = self.database.fetch_one("SELECT id FROM conversations WHERE id=? AND user_id=?", (conversation_id, user["id"]))
        if not conversation:
            raise ValueError("对话不存在或无权访问。")
        rows = self.database.fetch_all("SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at", (conversation_id,))
        for row in rows:
            row["citations"] = parse_json(row.pop("citations_json", "[]"), [])
        return rows

    def get_workspace_messages(self, conversation_id: str, user: dict[str, Any]) -> list[dict[str, Any]]:
        conversation = self.database.fetch_one(
            "SELECT id FROM conversations WHERE id=? AND user_id=? AND task_id IS NULL",
            (conversation_id, user["id"]),
        )
        if not conversation:
            raise ValueError("独立对话不存在或无权访问。")
        rows = self.database.fetch_all(
            "SELECT * FROM messages WHERE conversation_id=? ORDER BY created_at",
            (conversation_id,),
        )
        for row in rows:
            row["citations"] = parse_json(row.pop("citations_json", "[]"), [])
        return rows

    def _record_usage(self, user_id: str, task_id: str, provider: str, model: str, operation: str, input_tokens: int, output_tokens: int) -> None:
        total = int(input_tokens) + int(output_tokens)
        cost = (
            int(input_tokens) * self.settings.input_cost_per_million
            + int(output_tokens) * self.settings.output_cost_per_million
        ) / 1_000_000
        self.database.execute(
            """INSERT INTO usage_records (id,user_id,task_id,environment,provider,model,operation,input_tokens,output_tokens,total_tokens,estimated_cost,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (str(uuid.uuid4()), user_id, task_id, self.settings.app_env, provider, model, operation, input_tokens, output_tokens, total, cost, utc_now()),
        )

    def usage_summary(self, user: dict[str, Any]) -> dict[str, Any]:
        rows = self.database.fetch_all(
            """
            SELECT date(datetime(created_at,'+8 hours')) AS date,COUNT(*) AS analyses,SUM(input_tokens) AS input_tokens,
                   SUM(output_tokens) AS output_tokens,SUM(total_tokens) AS total_tokens,SUM(estimated_cost) AS estimated_cost
            FROM usage_records WHERE user_id=? GROUP BY date(datetime(created_at,'+8 hours')) ORDER BY date
            """
            , (user["id"],)
        )
        return {
            "environment": self.settings.app_env,
            "rates": {"input": self.settings.input_cost_per_million, "output": self.settings.output_cost_per_million},
            "records": rows,
        }

    def audit_logs(self, user: dict[str, Any], limit: int = 100) -> list[dict[str, Any]]:
        return self.database.fetch_all(
            """SELECT a.*,u.display_name,u.username FROM audit_logs a LEFT JOIN users u ON u.id=a.user_id
               WHERE a.user_id=? ORDER BY a.created_at DESC LIMIT ?""",
            (user["id"], max(1, min(limit, 500))),
        )
