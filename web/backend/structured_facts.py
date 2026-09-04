from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from .chunking import ChunkRecord
from .database import Database, utc_now


COMPANY_NAME = "创业黑马科技集团股份有限公司"
MATTER_RESTRUCTURING = "major_asset_restructuring"
MATTER_BUSINESS = "business_development"

STATUS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("终止", re.compile(r"(?:(?:决定|拟|已经|已)终止(?:本次|该)?(?:交易|重组|事项|审核)?|终止本次(?:交易|重组|事项))")),
    ("取消", re.compile(r"(?:(?:决定|已经|已)取消(?:本次|该)?(?:交易|重组|事项|审核)?|取消本次(?:交易|重组|事项))")),
    ("已完成", re.compile(r"(?:已经|已)(?:完成|实施完毕|交割完毕|办理完毕|过户完成)")),
    ("注册生效", re.compile(r"(?:注册申请|注册批复|注册)(?:已经|已)?生效|同意注册")),
    ("尚需审批", re.compile(r"(?:尚需|仍需|还需|有待).{0,18}(?:批准|审批|审核|审议|注册|核准|同意|履行)")),
    ("暂缓审议", re.compile(r"暂缓(?:审核|审议)|中止(?:审核|审议)")),
    ("审核通过", re.compile(r"(?:审核|审议|会议)(?:已经|已)?通过|予以通过|获得通过")),
    ("已受理", re.compile(r"(?:申请|材料|事项)?(?:已经|已)?(?:获|被)?受理")),
    ("已提交", re.compile(r"(?:申请|材料|方案|事项)?(?:已经|已)?提交|报送")),
    ("审议中", re.compile(r"正在(?:审核|审议)|审核中|审议中")),
    ("推进中", re.compile(r"(?:正在|持续|有序|积极)?推进中|正在推进|持续推进")),
    ("拟进行", re.compile(r"(?:拟|计划|筹划)(?:进行|实施|收购|购买|发行|重组|交易|募集)")),
)

RESTRUCTURING_TERMS = (
    "重大资产重组", "发行股份及支付现金购买资产", "购买资产", "募集配套资金",
    "标的资产", "交易标的", "交易对方", "重组报告书", "并购重组委员会",
)
BUSINESS_TERMS = (
    "主营业务", "主要业务", "业务发展", "业务模式", "核心业务", "公司成立",
    "公司上市", "上市以来", "发展历程", "业务布局", "核心竞争力",
)
HISTORICAL_BUSINESS_TERMS = (
    "成立于", "成立以来", "上市以来", "上市之初", "发展历程", "历史上", "早期",
)
SCHEME_TERMS = (
    "发行股份及支付现金购买资产", "发行股份购买资产", "支付现金购买资产",
    "募集配套资金", "交易标的", "标的资产", "交易对方", "交易作价", "交易价格",
)
REGULATORY_TERMS = ("问询函", "落实函", "审核问询", "审议意见", "监管意见", "回复")
FUTURE_TERMS = ("尚需", "仍需", "后续", "下一步", "拟", "计划", "将继续", "待")
PUBLICITY_TERMS = ("行业领先", "国际一流", "最具", "第一品牌", "绝对领先")

AMOUNT_PATTERN = re.compile(r"(?:人民币)?\s*([0-9][0-9,]*(?:\.[0-9]+)?)\s*(亿元|万元|元)")
SHARE_PATTERN = re.compile(r"([0-9][0-9,]*(?:\.[0-9]+)?)\s*(万股|亿股|股)")
RATIO_PATTERN = re.compile(r"([0-9]+(?:\.[0-9]+)?)\s*%")
DATE_PATTERN = re.compile(
    r"(?P<year>20\d{2})\s*[年./-]\s*(?P<month>\d{1,2})\s*[月./-]\s*(?P<day>\d{1,2})\s*日?"
)
STATUS_CONTEXT_TERMS = (
    "交易", "重组", "发行股份", "购买资产", "募集配套资金", "标的资产",
    "报告书", "深交所", "证券交易所", "证监会", "监管机构", "董事会",
    "股东会", "交割", "过户",
)


def source_priority(document_type: str, title: str, source: str, source_type: str = "") -> int:
    """Deterministic source authority score used by facts and RAG reranking."""
    combined = f"{title} {source} {source_type}"
    if document_type == "regulations" or re.search(r"证监会|证券交易所|深交所|上交所|监管机构", combined):
        return 100
    if document_type == "announcements" and re.search(r"公告|通知|决议", title):
        return 90
    if re.search(r"重组报告书|重大资产重组报告", title):
        return 85
    if re.search(r"年度报告", title):
        return 70
    if re.search(r"半年度报告", title):
        return 65
    if document_type == "announcements" and source_type == "official":
        return 80
    return {
        "company_profile": 88,
        "internal_rules": 82,
        "cases": 72,
        "announcements": 75,
        # Drafting sources are company wording references, not regulatory
        # authority. Keep them below formal rules and announcements.
        "drafting_materials": 68,
        "user_documents": 60,
    }.get(document_type, 55)


def parse_as_of_date(text: str) -> str | None:
    exact = DATE_PATTERN.search(text or "")
    if exact:
        return _valid_date(exact.group("year"), exact.group("month"), exact.group("day"))
    month_match = re.search(r"(20\d{2})年(\d{1,2})月", text or "")
    if month_match:
        year, month = int(month_match.group(1)), int(month_match.group(2))
        if 1 <= month <= 12:
            next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
            return date.fromordinal(next_month.toordinal() - 1).isoformat()
    year_match = re.search(r"截至\s*(20\d{2})年", text or "")
    if year_match:
        return f"{year_match.group(1)}-12-31"
    return None


def _valid_date(year: str, month: str, day: str) -> str | None:
    try:
        return date(int(year), int(month), int(day)).isoformat()
    except ValueError:
        return None


def _event_date(text: str) -> str | None:
    match = DATE_PATTERN.search(text)
    return _valid_date(match.group("year"), match.group("month"), match.group("day")) if match else None


def _fact_recency(fact: dict[str, Any], *, status: bool = False) -> str:
    """Return the date used to decide which version is current.

    Status statements often appear in a later report while describing an
    earlier transaction step. For status facts the event date is therefore
    more meaningful than the containing document's publication date; other
    facts continue to follow disclosure date first.
    """
    if status:
        return str(fact.get("event_date") or fact.get("publication_date") or "")
    return str(fact.get("publication_date") or fact.get("event_date") or "")


def _normalize_number(raw: str, unit: str) -> str | None:
    factors = {"元": Decimal("1"), "万元": Decimal("10000"), "亿元": Decimal("100000000"),
               "股": Decimal("1"), "万股": Decimal("10000"), "亿股": Decimal("100000000")}
    try:
        value = Decimal(raw.replace(",", "")) * factors[unit]
    except (InvalidOperation, KeyError):
        return None
    normalized = format(value, "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    return normalized or "0"


def _sentences(text: str) -> list[str]:
    values = []
    for sentence in re.split(r"(?<=[。！？；])|\n+", text.replace("\x00", "")):
        cleaned = re.sub(r"\s+", " ", sentence).strip(" \t\r\n|；")
        if 8 <= len(cleaned) <= 900:
            values.append(cleaned)
    return values


def _status(text: str) -> str | None:
    for name, pattern in STATUS_PATTERNS:
        if not pattern.search(text):
            continue
        if any(term in text for term in STATUS_CONTEXT_TERMS):
            return name
        # A short sentence such as "申请已获受理" can omit the transaction
        # subject because it is already established by the surrounding
        # document. Keep that explicit application phrase, while excluding
        # unrelated operational text such as "订单提交、审核出证".
        if name == "已受理" and re.search(r"(?:申请|材料)\s*(?:已经|已)?\s*(?:获|被)?\s*受理", text):
            return name
        if name == "已提交" and re.search(r"(?:申请|材料|方案|报告书)\s*(?:已经|已)?\s*提交", text):
            return name
    return None


def _matter(text: str, default: str | None = None) -> str | None:
    if any(term in text for term in RESTRUCTURING_TERMS):
        return MATTER_RESTRUCTURING
    if any(term in text for term in BUSINESS_TERMS):
        return MATTER_BUSINESS
    return default


def _amount_key(context: str) -> str | None:
    if "募集" in context:
        return "raised_funds_amount"
    if re.search(r"交易作价|交易价格|标的资产作价|收购价格", context):
        return "transaction_price"
    if "支付现金" in context or "现金对价" in context:
        return "cash_consideration"
    if "注册资本" in context:
        return "registered_capital"
    return None


def _share_key(context: str) -> str | None:
    if re.search(r"发行股份|发行数量|新增股份", context):
        return "issued_shares"
    if re.search(r"持有|持股", context):
        return "shares_held"
    return None


def _ratio_key(context: str) -> str | None:
    if re.search(r"持股|持有.*比例", context):
        return "shareholding_ratio"
    if "募集" in context:
        return "fundraising_ratio"
    if "增值率" in context:
        return "valuation_increase_ratio"
    return None


@dataclass(frozen=True)
class ExtractedFact:
    matter: str
    fact_type: str
    fact_key: str
    fact_value: str
    normalized_value: str | None
    value_unit: str | None
    event_date: str | None
    status: str | None
    original_text: str
    chunk: ChunkRecord


class StructuredFactEngine:
    def __init__(self, database: Database):
        self.database = database

    @staticmethod
    def _default_matter(title: str) -> str | None:
        if any(term in title for term in RESTRUCTURING_TERMS):
            return MATTER_RESTRUCTURING
        if re.search(r"年度报告|半年度报告|公司简介|业务发展", title):
            return MATTER_BUSINESS
        return None

    def extract(self, document: dict[str, Any], chunks: Iterable[ChunkRecord]) -> list[ExtractedFact]:
        document_type = str(document.get("document_type") or "user_documents")
        if document_type in {"regulations", "internal_rules"}:
            return []
        title = str(document.get("title") or document.get("filename") or "")
        default_matter = self._default_matter(title)
        facts: list[ExtractedFact] = []
        seen: set[tuple[str, str, str, str, str]] = set()

        def add(
            matter: str,
            fact_type: str,
            fact_key: str,
            value: str,
            sentence: str,
            chunk: ChunkRecord,
            *,
            normalized: str | None = None,
            unit: str | None = None,
            event_date: str | None = None,
            status: str | None = None,
        ) -> None:
            key = (chunk.id, fact_type, fact_key, value, sentence)
            if key in seen:
                return
            seen.add(key)
            facts.append(ExtractedFact(
                matter, fact_type, fact_key, value[:800], normalized, unit,
                event_date, status, sentence[:1200], chunk,
            ))

        for chunk in chunks:
            emitted_for_chunk = 0
            for sentence in _sentences(chunk.content):
                matter = _matter(sentence, default_matter)
                if not matter:
                    continue
                status = _status(sentence)
                event_date = _event_date(sentence)
                has_hard_fact = bool(status or AMOUNT_PATTERN.search(sentence) or SHARE_PATTERN.search(sentence) or RATIO_PATTERN.search(sentence))
                if any(term in sentence for term in PUBLICITY_TERMS) and not has_hard_fact:
                    continue

                if status and matter == MATTER_RESTRUCTURING:
                    add(matter, "status", "transaction_status", status, sentence, chunk,
                        normalized=status, event_date=event_date, status=status)
                    emitted_for_chunk += 1
                if matter == MATTER_RESTRUCTURING and any(term in sentence for term in SCHEME_TERMS):
                    add(matter, "scheme", "restructuring_scheme", sentence, sentence, chunk,
                        event_date=event_date, status=status)
                    emitted_for_chunk += 1
                if matter == MATTER_RESTRUCTURING and any(term in sentence for term in REGULATORY_TERMS):
                    add(matter, "regulatory_opinion", "regulatory_progress", sentence, sentence, chunk,
                        event_date=event_date, status=status)
                    emitted_for_chunk += 1
                if matter == MATTER_BUSINESS:
                    # Historical statements must remain historical even when
                    # they also mention the company's business, otherwise a
                    # sentence such as "上市以来持续..." is mislabeled as a
                    # current operating fact.
                    if any(term in sentence for term in HISTORICAL_BUSINESS_TERMS) and not re.search(r"目前|当前|本报告期|报告期内", sentence):
                        fact_type = "business_history"
                    else:
                        fact_type = "business_current" if re.search(r"目前|当前|报告期|主要从事|主营业务", sentence) else "business_history"
                    add(matter, fact_type, fact_type, sentence, sentence, chunk, event_date=event_date)
                    emitted_for_chunk += 1
                if matter == MATTER_RESTRUCTURING and any(term in sentence for term in FUTURE_TERMS):
                    add(matter, "future_plan", "next_step", sentence, sentence, chunk,
                        event_date=event_date, status=status)
                    emitted_for_chunk += 1

                for match in AMOUNT_PATTERN.finditer(sentence):
                    context = sentence[max(0, match.start() - 28):min(len(sentence), match.end() + 20)]
                    fact_key = _amount_key(context)
                    if fact_key:
                        normalized = _normalize_number(match.group(1), match.group(2))
                        add(matter, "amount", fact_key, match.group(0), sentence, chunk,
                            normalized=normalized, unit="元", event_date=event_date, status=status)
                        emitted_for_chunk += 1
                for match in SHARE_PATTERN.finditer(sentence):
                    context = sentence[max(0, match.start() - 28):min(len(sentence), match.end() + 20)]
                    fact_key = _share_key(context)
                    if fact_key:
                        normalized = _normalize_number(match.group(1), match.group(2))
                        add(matter, "shares", fact_key, match.group(0), sentence, chunk,
                            normalized=normalized, unit="股", event_date=event_date, status=status)
                        emitted_for_chunk += 1
                for match in RATIO_PATTERN.finditer(sentence):
                    context = sentence[max(0, match.start() - 28):min(len(sentence), match.end() + 20)]
                    fact_key = _ratio_key(context)
                    if fact_key:
                        add(matter, "ratio", fact_key, match.group(0), sentence, chunk,
                            normalized=match.group(1), unit="%", event_date=event_date, status=status)
                        emitted_for_chunk += 1
                if event_date:
                    date_key = "status_date" if status else "event_date"
                    add(matter, "date", date_key, event_date, sentence, chunk,
                        normalized=event_date, unit="date", event_date=event_date, status=status)
                    emitted_for_chunk += 1
                if emitted_for_chunk >= 12:
                    break
        return facts

    def replace_document_facts(
        self,
        document_id: str,
        chunks: Iterable[ChunkRecord],
        *,
        knowledge: bool,
        reconcile: bool = True,
    ) -> int:
        """Replace facts for one document.

        ``reconcile=False`` is used by bulk backfills so current-state and
        conflict resolution runs once after all documents have been refreshed.
        """
        table = "knowledge_documents" if knowledge else "documents"
        document = self.database.fetch_one(f"SELECT * FROM {table} WHERE id=?", (document_id,))
        if not document:
            return 0
        title = str(document.get("title") or document.get("filename") or "")
        file_path = str(document.get("file_path") or "")
        file_name = Path(file_path).name.split("_", 1)[-1] if file_path else str(document.get("filename") or title)
        document_type = str(document.get("document_type") or "user_documents")
        source = str(document.get("source") or ("当前审查材料" if not knowledge else file_name))
        priority = source_priority(document_type, title, source, str(document.get("source_type") or ""))
        company = str(document.get("company") or "") or None
        extracted = self.extract({**document, "title": title, "document_type": document_type}, chunks)
        now = utc_now()
        owner_user_id = document.get("owner_user_id")
        knowledge_id = document_id if knowledge else None
        private_document_id = None if knowledge else document_id
        with self.database.connection() as connection:
            connection.execute(
                "DELETE FROM structured_facts WHERE knowledge_document_id=? OR document_id=?",
                (knowledge_id, private_document_id),
            )
            for fact in extracted:
                digest = hashlib.sha256(
                    f"{document_id}|{fact.chunk.id}|{fact.fact_type}|{fact.fact_key}|{fact.fact_value}|{fact.original_text}".encode("utf-8")
                ).hexdigest()
                connection.execute(
                    """INSERT OR IGNORE INTO structured_facts (
                           id,owner_user_id,knowledge_document_id,document_id,chunk_id,company,matter,
                           fact_type,fact_key,fact_value,normalized_value,value_unit,publication_date,event_date,
                           status,is_current,file_name,file_type,page,section,paragraph,original_text,file_path,
                           source,source_url,source_priority,metadata_json,extracted_at,updated_at
                       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        digest, owner_user_id, knowledge_id, private_document_id, fact.chunk.id,
                        company, fact.matter, fact.fact_type, fact.fact_key, fact.fact_value,
                        fact.normalized_value, fact.value_unit,
                        document.get("publication_date") or document.get("created_at"), fact.event_date,
                        fact.status, 0, file_name, Path(file_name).suffix.lower().lstrip(".") or document_type,
                        fact.chunk.page, fact.chunk.section, fact.chunk.paragraph, fact.original_text,
                        file_path, source, document.get("source_url"), priority,
                        json.dumps(fact.chunk.metadata, ensure_ascii=False, separators=(",", ":")), now, now,
                    ),
                )
        if reconcile:
            self.reconcile(company)
        return len(extracted)

    def reconcile(self, company: str | None = None) -> None:
        params: list[Any] = []
        where = ""
        if company:
            where = " WHERE company=?"
            params.append(company)
        rows = self.database.fetch_all(
            f"""SELECT id,company,matter,fact_type,fact_key,normalized_value,fact_value,
                       publication_date,event_date,status,source_priority,source,file_name,page,section
                  FROM structured_facts{where}
                 ORDER BY company,matter,fact_type,fact_key,publication_date DESC,source_priority DESC""",
            params,
        )
        grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = {}
        for row in rows:
            key = (str(row.get("company") or ""), row["matter"], row["fact_type"], row["fact_key"])
            grouped.setdefault(key, []).append(row)
        with self.database.connection() as connection:
            if company:
                connection.execute("UPDATE structured_facts SET is_current=0 WHERE company=?", (company,))
                connection.execute("DELETE FROM structured_fact_conflicts WHERE company=?", (company,))
            else:
                connection.execute("UPDATE structured_facts SET is_current=0")
                connection.execute("DELETE FROM structured_fact_conflicts")
            now = utc_now()
            for (group_company, matter, fact_type, fact_key), facts in grouped.items():
                latest_date = max(
                    _fact_recency(fact, status=fact_type == "status") for fact in facts
                )
                latest = [
                    fact for fact in facts
                    if _fact_recency(fact, status=fact_type == "status") == latest_date
                ]
                if fact_type == "status" and latest:
                    latest_publication = max(str(fact.get("publication_date") or "") for fact in latest)
                    latest = [
                        fact for fact in latest
                        if str(fact.get("publication_date") or "") == latest_publication
                    ]
                highest_priority = max(int(fact.get("source_priority") or 0) for fact in latest)
                current = [fact for fact in latest if int(fact.get("source_priority") or 0) == highest_priority]
                connection.executemany(
                    "UPDATE structured_facts SET is_current=1,updated_at=? WHERE id=?",
                    [(now, fact["id"]) for fact in current],
                )
                conflict_kind = ""
                conflict_facts: list[dict[str, Any]] = []
                if fact_type in {"amount", "shares", "ratio", "date"}:
                    values = {str(fact.get("normalized_value") or fact.get("fact_value") or "") for fact in facts}
                    if len(values) > 1:
                        conflict_kind = "version_difference"
                        conflict_facts = facts
                elif fact_type == "status":
                    values = {str(fact.get("status") or fact.get("fact_value") or "") for fact in latest}
                    if len(values) > 1:
                        conflict_kind = "current_status_conflict"
                        conflict_facts = latest
                if not conflict_kind:
                    continue
                values_payload = [
                    {
                        "value": fact.get("fact_value"),
                        "normalizedValue": fact.get("normalized_value"),
                        "publicationDate": fact.get("publication_date"),
                        "eventDate": fact.get("event_date"),
                        "status": fact.get("status"),
                        "fileName": fact.get("file_name"),
                        "source": fact.get("source"),
                        "page": fact.get("page"),
                        "section": fact.get("section"),
                    }
                    for fact in conflict_facts
                ]
                conflict_id = hashlib.sha256(
                    f"{group_company}|{matter}|{fact_type}|{fact_key}|{conflict_kind}".encode("utf-8")
                ).hexdigest()
                connection.execute(
                    """INSERT INTO structured_fact_conflicts (
                           id,company,matter,fact_type,fact_key,conflict_kind,values_json,fact_ids_json,detected_at,updated_at
                       ) VALUES (?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(company,matter,fact_type,fact_key,conflict_kind) DO UPDATE SET
                           values_json=excluded.values_json,fact_ids_json=excluded.fact_ids_json,updated_at=excluded.updated_at""",
                    (
                        conflict_id, group_company or None, matter, fact_type, fact_key, conflict_kind,
                        json.dumps(values_payload, ensure_ascii=False, separators=(",", ":")),
                        json.dumps([fact["id"] for fact in conflict_facts], separators=(",", ":")), now, now,
                    ),
                )

    @staticmethod
    def _fact_citation(fact: dict[str, Any]) -> dict[str, Any]:
        document_id = fact.get("knowledge_document_id") or fact.get("document_id") or ""
        source_url = fact.get("source_url") or ""
        if not source_url and fact.get("knowledge_document_id"):
            source_url = f"/api/knowledge/{fact['knowledge_document_id']}/document"
        return {
            "title": fact.get("file_name") or "未命名资料",
            "document_id": document_id,
            "chunk_id": fact.get("chunk_id") or "",
            "source": fact.get("source") or "",
            "source_url": source_url,
            "date": fact.get("publication_date") or "",
            "page": fact.get("page"),
            "section": fact.get("section") or "",
            "document_type": "structured_fact",
            "content": fact.get("original_text") or "",
            "score": 1.0,
            "file_path": fact.get("file_path") or "",
            "source_priority": fact.get("source_priority") or 0,
            "fact_id": fact.get("id") or "",
        }

    def build_bundle(
        self,
        question: str,
        *,
        user_id: str,
        company: str = COMPANY_NAME,
        limit: int = 300,
    ) -> dict[str, Any]:
        as_of = parse_as_of_date(question)
        wants_restructuring = any(term in question for term in ("重组", "购买资产", "募集配套资金", "并购"))
        wants_business = any(term in question for term in ("业务", "发展历史", "公司简介", "主营"))
        matters = []
        if wants_restructuring:
            matters.append(MATTER_RESTRUCTURING)
        if wants_business:
            matters.append(MATTER_BUSINESS)
        if not matters:
            matters = [MATTER_BUSINESS, MATTER_RESTRUCTURING]
        placeholders = ",".join("?" for _ in matters)
        conditions = ["(owner_user_id IS NULL OR owner_user_id=?)", f"matter IN ({placeholders})"]
        params: list[Any] = [user_id, *matters]
        if company:
            conditions.append("(company=? OR company IS NULL OR company='')")
            params.append(company)
        if as_of:
            conditions.append("COALESCE(publication_date,event_date,'')<=?")
            params.append(as_of)
        facts = self.database.fetch_all(
            f"""SELECT * FROM structured_facts WHERE {' AND '.join(conditions)}
                 ORDER BY COALESCE(publication_date,event_date,'') DESC,source_priority DESC,id LIMIT ?""",
            [*params, max(1, min(limit, 1000))],
        )

        def fact_date(fact: dict[str, Any]) -> str:
            return _fact_recency(fact, status=fact.get("fact_type") == "status")

        status_facts = [fact for fact in facts if fact["fact_type"] == "status"]
        current_status = None
        if status_facts:
            latest_date = max(fact_date(fact) for fact in status_facts)
            latest_statuses = [fact for fact in status_facts if fact_date(fact) == latest_date]
            latest_publication = max(str(fact.get("publication_date") or "") for fact in latest_statuses)
            latest_statuses = [
                fact for fact in latest_statuses
                if str(fact.get("publication_date") or "") == latest_publication
            ]
            # If one report repeats historical statuses without event dates,
            # prefer the earlier page (usually the current-status summary)
            # after source authority has been considered.
            latest_statuses.sort(
                key=lambda fact: (
                    int(fact.get("source_priority") or 0),
                    -(int(fact.get("page") or 10**9)),
                ),
                reverse=True,
            )
            current_status = latest_statuses[0]
        timeline = []
        seen_timeline: set[tuple[str, str]] = set()
        for fact in sorted(status_facts, key=lambda item: (fact_date(item), int(item.get("source_priority") or 0))):
            key = (fact_date(fact), str(fact.get("status") or fact.get("fact_value") or ""))
            if key in seen_timeline:
                continue
            seen_timeline.add(key)
            current_key = (
                fact_date(current_status),
                str(current_status.get("status") or current_status.get("fact_value") or ""),
            ) if current_status else None
            timeline.append({
                "date": key[0],
                "status": key[1],
                "historical": key != current_key,
                "fact": fact,
                "evidence": self._fact_citation(fact),
            })

        grouped = {
            "business_history": [fact for fact in facts if fact["fact_type"] == "business_history"],
            "business_current": [fact for fact in facts if fact["fact_type"] == "business_current"],
            "restructuring_scheme": [fact for fact in facts if fact["fact_type"] == "scheme"],
            "regulatory_progress": [fact for fact in facts if fact["fact_type"] == "regulatory_opinion"],
            "future_plan": [fact for fact in facts if fact["fact_type"] == "future_plan"],
            "numeric_facts": [fact for fact in facts if fact["fact_type"] in {"amount", "shares", "ratio", "date"}],
        }
        # A history question is more useful when business milestones are
        # presented chronologically; current status and transaction evidence
        # remain newest-first for operational review.
        grouped["business_history"].sort(key=fact_date)
        for key in ("business_current", "restructuring_scheme", "regulatory_progress", "future_plan", "numeric_facts"):
            grouped[key].sort(key=fact_date, reverse=True)
        conflict_rows = self.database.fetch_all(
            f"""SELECT * FROM structured_fact_conflicts
                 WHERE (company=? OR company IS NULL OR company='') AND matter IN ({placeholders})
                 ORDER BY updated_at DESC""",
            [company, *matters],
        )
        conflicts = []
        for conflict in conflict_rows:
            fact_ids = json.loads(conflict.get("fact_ids_json") or "[]")
            conflicts.append({
                "id": conflict["id"],
                "matter": conflict["matter"],
                "factType": conflict["fact_type"],
                "factKey": conflict["fact_key"],
                "kind": conflict["conflict_kind"],
                "values": json.loads(conflict["values_json"] or "[]"),
            })
        citation_facts = []
        if current_status:
            citation_facts.append(current_status)
        for key in ("business_history", "business_current", "restructuring_scheme", "regulatory_progress", "future_plan", "numeric_facts"):
            citation_facts.extend(grouped[key][:3])
        citations = []
        seen_citations: set[tuple[str, str]] = set()
        for fact in citation_facts:
            citation = self._fact_citation(fact)
            key = (citation["document_id"], citation["chunk_id"])
            if key in seen_citations:
                continue
            seen_citations.add(key)
            citations.append(citation)
        evidence_chains = []
        evidence_seen: set[str] = set()
        if current_status:
            evidence_chains.append({
                "conclusion": f"截至{as_of or fact_date(current_status) or '最新披露日'}，事项当前状态为“{current_status.get('status') or current_status.get('fact_value')}”。",
                "factId": current_status["id"],
                "fact": current_status,
                "evidence": self._fact_citation(current_status),
            })
            evidence_seen.add(str(current_status["id"]))
        evidence_labels = {
            "business_history": "公司业务发展历史",
            "business_current": "公司当前业务情况",
            "restructuring_scheme": "重大资产重组方案",
            "regulatory_progress": "监管审核进展",
            "future_plan": "后续工作安排",
            "numeric_facts": "交易数字事实",
        }
        for key, label in evidence_labels.items():
            for fact in grouped[key][:3]:
                fact_id = str(fact.get("id") or "")
                if not fact_id or fact_id in evidence_seen:
                    continue
                evidence_seen.add(fact_id)
                evidence_chains.append({
                    "conclusion": f"{label}：{fact.get('fact_value') or fact.get('original_text') or '事实待确认'}。",
                    "factId": fact_id,
                    "fact": fact,
                    "evidence": self._fact_citation(fact),
                })
        return {
            "company": company,
            "query": question,
            "asOfDate": as_of,
            "matters": matters,
            "facts": facts,
            **grouped,
            "current_status": current_status,
            "timeline": timeline,
            "conflicts": conflicts,
            "evidence_chains": evidence_chains,
            "citations": citations,
        }

    @staticmethod
    def format_answer(bundle: dict[str, Any]) -> str:
        if not bundle.get("facts"):
            return "当前知识库未检索到直接依据，请人工进一步确认。"
        lines = [f"公司：{bundle.get('company')}"]
        as_of = bundle.get("asOfDate")
        current = bundle.get("current_status")
        if current:
            lines.extend([
                f"当前状态：{current.get('status') or current.get('fact_value')}",
                f"状态依据：{current.get('original_text')}",
                f"披露日期：{current.get('publication_date') or '待确认'}；页码：{current.get('page') or '待确认'}；文件：{current.get('file_name')}",
            ])
        elif MATTER_RESTRUCTURING in bundle.get("matters", []):
            lines.append("当前状态：当前知识库未检索到可核验的状态事实，请人工进一步确认。")
        if as_of:
            lines.append(f"查询截止日：{as_of}")
        if bundle.get("timeline"):
            lines.append("状态时间轴：")
            for item in bundle["timeline"][-8:]:
                marker = "当前" if not item["historical"] else "历史"
                lines.append(f"- {item['date'] or '日期待确认'}｜{item['status']}｜{marker}｜{item['evidence']['title']} 第{item['evidence']['page'] or '待确认'}页")
        if bundle.get("restructuring_scheme"):
            lines.append("交易方案事实：")
            for fact in bundle["restructuring_scheme"][:3]:
                lines.append(f"- {fact['fact_value']}（{fact['file_name']}，第{fact.get('page') or '待确认'}页）")
        if bundle.get("business_history") or bundle.get("business_current"):
            lines.append("业务事实：")
            for fact in [*bundle.get("business_history", [])[:2], *bundle.get("business_current", [])[:2]]:
                lines.append(f"- {fact['fact_value']}（{fact['file_name']}，第{fact.get('page') or '待确认'}页）")
        if bundle.get("conflicts"):
            lines.append("冲突提示：")
            for conflict in bundle["conflicts"][:5]:
                values = "；".join(
                    f"{item.get('value')}（{item.get('publicationDate') or '日期待确认'}，{item.get('fileName')}）"
                    for item in conflict.get("values", [])[:6]
                )
                lines.append(f"- {conflict['factKey']}存在差异：{values}")
        lines.append("说明：以上内容由本地结构化事实、状态规则和证据链生成，未调用任何 LLM 或外部 API。")
        return "\n".join(lines)


__all__ = [
    "COMPANY_NAME", "MATTER_BUSINESS", "MATTER_RESTRUCTURING", "StructuredFactEngine",
    "parse_as_of_date", "source_priority",
]
