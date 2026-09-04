from __future__ import annotations

"""Deterministic cross-section checks for major related-party transactions.

This module deliberately does not decide whether a transaction is legally
"material".  It reconciles facts that the report itself presents in the
related-party and major-related-transaction sections and leaves the legal
threshold question to the local RAG sources and a reviewer.
"""

import re
import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from .parsers import ParsedBlock, ParsedDocument


ENGINE_VERSION = "major_related_transaction_audit_v1"

_COMPACT_RE = re.compile(r"\s+")
_SECTION_MARKERS = (
    "重大关联交易",
    "重大关联方交易",
    "关联方及关联交易",
    "关联方和关联交易",
    "关联方与关联交易",
    "关联交易情况",
    "关联方交易",
    "关联交易",
)

_NATURE_PATTERNS: tuple[tuple[str, str, str], ...] = (
    ("establishment", "设立子公司", r"(?:投资)?设立(?:全资|控股)?子公司|新设子公司|成立子公司"),
    ("acquisition", "收购/取得子公司或股权", r"(?:收购|取得|购买)(?:全资|控股)?子公司|收购股权|购买股权|取得股权"),
    ("capital_injection", "子公司增资", r"(?:向|对|为)(?:全资|控股)?子公司增资|子公司增资|增资子公司"),
    ("equity_transfer", "股权转让", r"股权转让|转让股权|受让股权|出售股权"),
    ("external_investment", "对外投资", r"对外投资|投资设立|投资入股|追加投资"),
    ("business_acquisition", "资产/业务收购", r"收购资产|购买资产|收购业务|取得营业单位"),
)

_AMOUNT_RE = re.compile(
    r"(?<![\d])([+\-－−(（]?\d[\d,，]*(?:\.\d+)?[)）]?)\s*(亿元|亿|万元|万|千元|千|元)"
)
_UNIT_HINT_RE = re.compile(r"(?:单位|金额单位)\s*[：:]?\s*(亿元|亿|万元|万|千元|千|元)")
_BARE_AMOUNT_RE = re.compile(
    r"(?:交易金额|投资金额|出资额|增资额|收购价款|交易价款|对价|金额|总额)"
    r"[^\d]{0,18}([+\-－−(（]?\d[\d,，]*(?:\.\d+)?[)）]?)"
)
_COUNTERPARTY_RE = re.compile(
    r"(?:交易对方|关联方|关联人|被投资单位|标的公司|交易对象|对方)"
    r"\s*[：:|]?\s*([^|；;，,。\n]{2,80})"
)


def _compact(value: str) -> str:
    return _COMPACT_RE.sub("", str(value or ""))


def _section_kind(value: str) -> str | None:
    compact = _compact(value)
    if not compact:
        return None
    if "重大关联交易" in compact or "重大关联方交易" in compact:
        return "major"
    if any(marker in compact for marker in _SECTION_MARKERS[2:]):
        return "related"
    return None


def _nature(line: str) -> tuple[str, str] | None:
    compact = _compact(line)
    for family, label, pattern in _NATURE_PATTERNS:
        if re.search(pattern, compact):
            return family, label
    # A generic related-party row is useful when it carries an amount or
    # counterparty, but a bare table heading "关联交易" is not a transaction.
    if "关联交易" in compact and any(term in compact for term in ("金额", "交易对方", "关联方", "交易类型")):
        return "generic_related", "关联交易"
    return None


def _to_decimal(raw: str) -> Decimal | None:
    value = str(raw or "").strip().replace(",", "").replace("，", "")
    negative = value.startswith(("(", "（")) and value.endswith((")", "）"))
    value = value.strip("()（）").replace("－", "-").replace("−", "-")
    try:
        number = Decimal(value)
    except InvalidOperation:
        return None
    return -abs(number) if negative else number


def _unit_multiplier(unit: str) -> Decimal:
    return {
        "亿元": Decimal("100000000"),
        "亿": Decimal("100000000"),
        "万元": Decimal("10000"),
        "万": Decimal("10000"),
        "千元": Decimal("1000"),
        "千": Decimal("1000"),
        "元": Decimal("1"),
    }.get(unit, Decimal("1"))


def _extract_amounts(text: str, unit_hint: str | None = None) -> tuple[Decimal, ...]:
    values: list[Decimal] = []
    for match in _AMOUNT_RE.finditer(text.replace("|", " ")):
        value = _to_decimal(match.group(1))
        if value is not None:
            values.append(value * _unit_multiplier(match.group(2)))
    if values:
        return tuple(dict.fromkeys(values))
    if unit_hint and any(term in _compact(text) for term in ("金额", "对价", "出资", "增资", "投资")):
        for match in _BARE_AMOUNT_RE.finditer(text):
            value = _to_decimal(match.group(1))
            if value is not None:
                values.append(value * _unit_multiplier(unit_hint))
    return tuple(dict.fromkeys(values))


def _counterparty(text: str) -> str:
    match = _COUNTERPARTY_RE.search(text)
    if not match:
        return ""
    value = re.split(r"交易类型|交易金额|金额|性质|说明", match.group(1), maxsplit=1)[0]
    value = value.strip(" ：:|；;，,。\t")[:80]
    if _compact(value) in {
        "关联方", "关联人", "交易对方", "交易对象", "被投资单位", "标的公司", "金额",
    }:
        return ""
    return value


def _location(block: ParsedBlock, text: str, label: str) -> dict[str, Any]:
    return {
        "label": label,
        "page": block.page,
        "section": block.section,
        "paragraphIndex": block.paragraph_index,
        "text": text,
    }


def _record(block: ParsedBlock, line: str, nature: tuple[str, str], unit_hint: str | None, kind: str) -> dict[str, Any]:
    family, label = nature
    return {
        "block": block,
        "line": line,
        "kind": kind,
        "nature_family": family,
        "nature": label,
        "amounts": _extract_amounts(line, unit_hint),
        "counterparty": _counterparty(line),
        "location": _location(block, line, f"{'关联方' if kind == 'related' else '重大关联交易'}章节：{label}"),
    }


def _extract_records(parsed: ParsedDocument) -> tuple[list[dict[str, Any]], list[dict[str, Any]], bool]:
    related: list[dict[str, Any]] = []
    major: list[dict[str, Any]] = []
    major_section_found = False
    context: str | None = None

    for block in parsed.blocks:
        section_context = _section_kind(block.section)
        if section_context:
            context = section_context
            if context == "major":
                major_section_found = True
        elif block.block_type == "heading":
            # A new ordinary heading closes an unstructured section context.
            context = None
        unit_hint_match = _UNIT_HINT_RE.search(block.text)
        unit_hint = unit_hint_match.group(1) if unit_hint_match else None
        lines = [line.strip() for line in block.text.splitlines() if line.strip()]
        if not lines:
            lines = [block.text.strip()]
        for line in lines:
            marker_context = _section_kind(line)
            if marker_context:
                context = marker_context
                if context == "major":
                    major_section_found = True
                # A section heading is context only. This also prevents the
                # generic "关联交易" matcher from treating the heading's
                # words as a transaction counterparty.
                if block.block_type == "heading" or len(lines) == 1:
                    continue
            nature = _nature(line)
            if nature is None or context not in {"related", "major"}:
                continue
            # Generic headings/table headers do not carry a transaction fact.
            if nature[0] == "generic_related" and not (
                _extract_amounts(line, unit_hint) or _counterparty(line)
            ):
                continue
            item = _record(block, line, nature, unit_hint, context)
            if context == "related":
                related.append(item)
            else:
                major.append(item)
    return related, major, major_section_found


def _text_overlap(left: str, right: str) -> bool:
    left_compact = _compact(left)
    right_compact = _compact(right)
    if not left_compact or not right_compact:
        return False
    return left_compact in right_compact or right_compact in left_compact


def _matches(related: dict[str, Any], major: dict[str, Any]) -> bool:
    if related["amounts"] and major["amounts"]:
        if any(left == right for left in related["amounts"] for right in major["amounts"]):
            return True
    if related["counterparty"] and major["counterparty"]:
        if not _text_overlap(related["counterparty"], major["counterparty"]):
            return False
        # A shared counterparty is enough to compare the two descriptions. If
        # the nature differs, that is precisely a finding we need to surface.
        return True
    return related["nature_family"] == major["nature_family"]


def _amount_text(values: tuple[Decimal, ...]) -> str:
    if not values:
        return "未提取到金额"
    return "、".join(f"{value:,.2f}元" for value in values)


def _risk(
    title: str,
    description: str,
    recommendation: str,
    primary: dict[str, Any],
    locations: list[dict[str, Any]],
    *,
    status: str,
) -> dict[str, Any]:
    block: ParsedBlock = primary["block"]
    return {
        "id": str(uuid.uuid4()),
        "level": "needs_review",
        "type": "重大关联交易披露勾稽",
        "title": title,
        "description": description,
        "evidence": primary["line"],
        "source_text": primary["line"],
        "page": block.page,
        "section": block.section,
        "paragraph_index": block.paragraph_index,
        "location": {
            "page": block.page,
            "section": block.section,
            "paragraph": block.paragraph_index + 1,
            "items": locations,
        },
        "regulation_basis": [],
        "company_basis": [],
        "internal_rule_basis": [],
        "historical_cases": [],
        "source_documents": [],
        "recommendation": recommendation,
        "confidence": 0.89,
        "calculation": {
            "engine": ENGINE_VERSION,
            "status": status,
            "transaction": {
                "nature": primary["nature"],
                "natureFamily": primary["nature_family"],
                "counterparty": primary["counterparty"],
                "amounts": [str(value) for value in primary["amounts"]],
            },
        },
    }


def _comparison_facts(item: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "relatedPartySection": {
            "nature": item["nature"],
            "natureFamily": item["nature_family"],
            "counterparty": item["counterparty"],
            "amounts": [str(value) for value in item["amounts"]],
        },
        "majorRelatedTransactionSection": {
            "nature": candidate["nature"],
            "natureFamily": candidate["nature_family"],
            "counterparty": candidate["counterparty"],
            "amounts": [str(value) for value in candidate["amounts"]],
        },
    }


def _dedupe(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    values: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for record in records:
        key = (
            record["nature_family"],
            _compact(record["counterparty"]),
            tuple(record["amounts"]),
            record["line"],
        )
        if key in seen:
            continue
        seen.add(key)
        values.append(record)
    return values


def analyze_major_related_transactions(parsed: ParsedDocument) -> list[dict[str, Any]]:
    """Return review findings for related-party facts not reconciled in the report.

    The caller should invoke this for annual reports. Findings are deliberately
    ``needs_review`` because this pass cannot determine legal materiality from
    the report alone.
    """
    related, major, major_section_found = _extract_records(parsed)
    related = _dedupe(related)[:40]
    major = _dedupe(major)[:80]
    if not related:
        return []

    findings: list[dict[str, Any]] = []
    for item in related:
        matches = [candidate for candidate in major if _matches(item, candidate)]
        if not matches:
            section_note = (
                "未检索到重大关联交易章节。"
                if not major_section_found
                else "重大关联交易章节未检索到与该事项相匹配的条目，或仅披露了‘不存在重大关联交易’。"
            )
            amount_note = _amount_text(item["amounts"])
            findings.append(_risk(
                "关联方交易可能未在重大关联交易章节完整说明",
                f"关联方章节识别到“{item['nature']}”事项，交易对方为“{item['counterparty'] or '未明确'}”，"
                f"金额为{amount_note}；{section_note}需要核对该事项是否应在重大关联交易中单独说明。",
                "核对交易协议、立项/审批材料和合并范围，确认交易性质、关联关系及连续十二个月累计金额；如达到适用规则或公司制度标准，在重大关联交易章节补充交易对方、金额、定价、审批及披露情况。",
                item,
                [item["location"]],
                status="related_without_major_match",
            ))
            continue

        candidate = matches[0]
        locations = [item["location"], candidate["location"]]
        if item["amounts"] and candidate["amounts"] and not any(
            left == right for left in item["amounts"] for right in candidate["amounts"]
        ):
            finding = _risk(
                "关联交易金额跨章节不一致",
                f"关联方章节披露金额为{_amount_text(item['amounts'])}，重大关联交易章节披露金额为{_amount_text(candidate['amounts'])}；两处未找到相同金额。",
                "回到协议、付款凭证和财务附注核对金额口径（含税/不含税、币种、累计或单笔）；确认后同步修改关联方及重大关联交易章节，并保留调整原因。",
                item,
                locations,
                status="amount_mismatch",
            )
            finding["calculation"]["comparison"] = _comparison_facts(item, candidate)
            findings.append(finding)
        elif bool(item["amounts"]) != bool(candidate["amounts"]):
            finding = _risk(
                "重大关联交易金额披露需核对",
                f"同一“{item['nature']}”事项已在两个章节出现，但一处金额为{_amount_text(item['amounts'])}，另一处为{_amount_text(candidate['amounts'])}，金额披露不完整。",
                "核对交易金额、计价单位和累计口径；在重大关联交易章节补充与关联方章节一致的金额及计算说明，无法确认时提交人工复核。",
                item,
                locations,
                status="amount_missing_in_one_section",
            )
            finding["calculation"]["comparison"] = _comparison_facts(item, candidate)
            findings.append(finding)
        if item["nature_family"] != candidate["nature_family"]:
            finding = _risk(
                "关联交易性质跨章节表述不一致",
                f"关联方章节将事项性质表述为“{item['nature']}”，重大关联交易章节表述为“{candidate['nature']}”；需确认是否为同一事项及性质归类是否准确。",
                "依据协议、董事会/股东会材料和会计处理确认交易实质；统一使用准确的交易性质（如设立、收购、增资或股权转让），并核对重大关联交易章节是否已说明关联关系和审批披露情况。",
                item,
                locations,
                status="nature_mismatch",
            )
            finding["calculation"]["comparison"] = _comparison_facts(item, candidate)
            findings.append(finding)

    return findings[:80]


__all__ = ["ENGINE_VERSION", "analyze_major_related_transactions"]
