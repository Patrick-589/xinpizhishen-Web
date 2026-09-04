from __future__ import annotations

"""Compare a periodic-report summary with its corresponding full report.

The summary is intentionally shorter than the full report, so this module
checks facts that must be identical (key metrics and identifying fields) rather
than treating every omitted paragraph as an error.
"""

import hashlib
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from .parsers import ParsedBlock, ParsedDocument
from .periodic_compare import (
    METRIC_LABELS,
    ValueLocation,
    _normalize_label,
    extract_summary_metrics,
)


ENGINE_VERSION = "summary_fulltext_compare_v1"
SUMMARY_TERMS = ("摘要", "报告摘要", "半年度报告摘要", "年度报告摘要")
KEY_FACT_LABELS = (
    "股票简称", "股票代码", "股票上市证券交易所", "公司中文简称", "报告期",
    "报告期末普通股股东总数", "优先股股东总数", "控股股东", "实际控制人",
)
NUMBER_RE = re.compile(r"[（(]?[-+－−—]?\d[\d,，]*(?:\.\d+)?[%％]?[）)]?")


def _compact(value: str) -> str:
    return re.sub(r"\s+", "", str(value or ""))


def is_summary_document(filename: str, parsed: ParsedDocument) -> bool:
    sample = f"{filename}\n" + "\n".join(parsed.paragraphs[:20])
    compact = _compact(sample)
    return any(term in compact for term in SUMMARY_TERMS)


def _to_decimal(raw: str) -> Decimal | None:
    value = str(raw or "").strip().replace(",", "").replace("，", "")
    value = value.replace("－", "-").replace("−", "-").strip("()（）")
    value = value.rstrip("%％")
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _location(item: ValueLocation, label: str, document_id: str = "") -> dict[str, Any]:
    return {
        "label": label,
        "page": item.page,
        "section": item.section,
        "paragraphIndex": item.paragraph,
        "text": item.text,
        "documentId": document_id,
    }


def _risk(
    title: str,
    description: str,
    recommendation: str,
    summary_item: ValueLocation,
    original_item: ValueLocation,
    *,
    severity: str,
    category: str,
    status: str,
    calculation: dict[str, Any],
    summary_document_id: str = "",
    original_document_id: str = "",
) -> dict[str, Any]:
    risk_id = "summary-" + hashlib.sha256(
        f"{title}|{summary_item.paragraph}|{original_item.paragraph}|{summary_item.text}|{original_item.text}".encode("utf-8")
    ).hexdigest()[:20]
    return {
        "id": risk_id,
        "level": severity,
        "type": category,
        "title": title,
        "description": description,
        "evidence": summary_item.text,
        "source_text": summary_item.text,
        "page": summary_item.page,
        "section": summary_item.section,
        "paragraph_index": summary_item.paragraph,
        "location": {
            "page": summary_item.page,
            "section": summary_item.section,
            "paragraph": summary_item.paragraph + 1,
            "items": [
                _location(summary_item, "摘要位置", summary_document_id),
                _location(original_item, "原文位置", original_document_id),
            ],
        },
        "regulation_basis": [],
        "company_basis": [],
        "internal_rule_basis": [],
        "historical_cases": [],
        "source_documents": [],
        "recommendation": recommendation,
        "confidence": 0.98,
        "calculation": {"engine": ENGINE_VERSION, "status": status, **calculation},
    }


def _metric_map(parsed: ParsedDocument) -> dict[str, ValueLocation]:
    results = extract_summary_metrics(parsed)
    # Some PDF/DOCX parsers flatten a heading and its table into an unstructured
    # block, so the strict section-aware extractor may not see the metric table.
    # Keep a conservative label-anchored fallback for summary documents.
    for block in parsed.blocks:
        for line in block.text.splitlines():
            text = line.strip().strip("|").strip()
            normalized_text = _normalize_label(text)
            for label in METRIC_LABELS:
                normalized_label = _normalize_label(label)
                if not normalized_text.startswith(normalized_label):
                    continue
                suffix = text[len(label):]
                raw_values = tuple(NUMBER_RE.findall(suffix))
                values = tuple(value for value in (_to_decimal(item) for item in raw_values) if value is not None)
                if values:
                    results.setdefault(normalized_label, ValueLocation(
                        label,
                        tuple(float(value) for value in values),
                        raw_values[:len(values)],
                        block.page,
                        block.paragraph_index,
                        block.section,
                        line,
                    ))
                break
    return results


def _fact_lines(parsed: ParsedDocument) -> dict[str, ValueLocation]:
    results: dict[str, ValueLocation] = {}
    for block in parsed.blocks:
        for line in block.text.splitlines():
            text = line.strip().strip("|").strip()
            if not text:
                continue
            for label in KEY_FACT_LABELS:
                normalized_label = _normalize_label(label)
                normalized_text = _normalize_label(text)
                if not normalized_text.startswith(normalized_label):
                    continue
                value = text[len(label):].strip(" ：:|")
                if not value:
                    continue
                results.setdefault(normalized_label, ValueLocation(
                    label, (0.0,), (value,), block.page, block.paragraph_index,
                    block.section, line,
                ))
                break
    return results


def _fact_value(item: ValueLocation) -> str:
    return _compact(item.raw_values[0] if item.raw_values else item.text)


def _metric_equal(left: ValueLocation, right: ValueLocation) -> bool:
    if len(left.raw_values) != len(right.raw_values):
        return False
    for left_raw, right_raw in zip(left.raw_values, right.raw_values, strict=True):
        left_value = _to_decimal(left_raw)
        right_value = _to_decimal(right_raw)
        if left_value is None or right_value is None:
            if _compact(left_raw) != _compact(right_raw):
                return False
        elif left_value != right_value:
            return False
    return True


def compare_summary_to_original(
    primary: ParsedDocument,
    comparison: ParsedDocument,
    *,
    primary_filename: str,
    comparison_filename: str,
    primary_document_id: str = "",
    comparison_document_id: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Compare the summary and full report, regardless of upload order."""
    primary_is_summary = is_summary_document(primary_filename, primary)
    comparison_is_summary = is_summary_document(comparison_filename, comparison)
    if primary_is_summary == comparison_is_summary:
        return [], {
            "status": "not_summary_pair",
            "message": "未能从文件名或正文唯一识别摘要与原文，未执行摘要—原文勾稽。",
            "summaryDocument": primary_filename if primary_is_summary else "",
            "originalDocument": comparison_filename if not comparison_is_summary else "",
            "checkedItems": 0,
            "mismatches": 0,
        }

    if primary_is_summary:
        summary, original = primary, comparison
        summary_filename, original_filename = primary_filename, comparison_filename
        summary_document_id, original_document_id = primary_document_id, comparison_document_id
    else:
        summary, original = comparison, primary
        summary_filename, original_filename = comparison_filename, primary_filename
        summary_document_id, original_document_id = comparison_document_id, primary_document_id

    summary_metrics = _metric_map(summary)
    original_metrics = _metric_map(original)
    summary_facts = _fact_lines(summary)
    original_facts = _fact_lines(original)
    risks: list[dict[str, Any]] = []
    checked = 0
    missing = 0

    for normalized_label, summary_item in summary_metrics.items():
        original_item = original_metrics.get(normalized_label)
        if original_item is None:
            missing += 1
            continue
        checked += 1
        if _metric_equal(summary_item, original_item):
            continue
        severity = "high" if any(term in summary_item.label for term in ("收入", "利润", "资产", "现金", "净资产")) else "medium"
        risks.append(_risk(
            f"摘要与原文财务指标不一致：{summary_item.label}",
            f"摘要列示“{summary_item.text}”，对应原文列示“{original_item.text}”，同一财务指标的数值或同比数据不一致。",
            "以经审计或正式披露的完整报告及财务底稿为准，核对报告期、合并范围、单位、正负号和同比口径；确认后同步修改摘要和原文，不能只修改其中一处。",
            summary_item,
            original_item,
            severity=severity,
            category="摘要—原文财务一致性",
            status="metric_mismatch",
            calculation={
                "metric": summary_item.label,
                "summaryValues": list(summary_item.raw_values),
                "originalValues": list(original_item.raw_values),
            },
            summary_document_id=summary_document_id,
            original_document_id=original_document_id,
        ))

    for normalized_label, summary_item in summary_facts.items():
        original_item = original_facts.get(normalized_label)
        if original_item is None:
            missing += 1
            continue
        checked += 1
        summary_value = _fact_value(summary_item)
        original_value = _fact_value(original_item)
        if summary_value == original_value:
            continue
        risks.append(_risk(
            f"摘要与原文基本信息不一致：{summary_item.label}",
            f"摘要列示“{summary_item.text}”，对应原文列示“{original_item.text}”，基本信息需要核对。",
            "核对公司公告、证券登记资料和完整报告封面，以正式披露口径统一摘要与原文；股票代码、报告期等信息不得仅凭摘要推定。",
            summary_item,
            original_item,
            severity="high" if summary_item.label in {"股票代码", "报告期"} else "medium",
            category="摘要—原文基本信息一致性",
            status="fact_mismatch",
            calculation={
                "fact": summary_item.label,
                "summaryValue": summary_value,
                "originalValue": original_value,
            },
            summary_document_id=summary_document_id,
            original_document_id=original_document_id,
        ))

    summary_payload = {
        "status": "completed",
        "engineVersion": ENGINE_VERSION,
        "summaryDocument": summary_filename,
        "originalDocument": original_filename,
        "summaryDocumentId": summary_document_id,
        "originalDocumentId": original_document_id,
        "checkedItems": checked,
        "mismatches": len(risks),
        "missingInOriginal": missing,
        "metricsChecked": len(summary_metrics),
        "factsChecked": len(summary_facts),
        "summaryDetected": True,
    }
    return risks, summary_payload


__all__ = ["ENGINE_VERSION", "compare_summary_to_original", "is_summary_document"]
