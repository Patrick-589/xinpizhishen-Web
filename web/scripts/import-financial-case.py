from __future__ import annotations

"""Create a local, reviewable financial-case calibration record.

Usage (from the project root):
  python web/scripts/import-financial-case.py ORIGINAL.docx ANNOTATED.docx TABLE.xls

The script stores only structured annotations and provenance.  It never sends
the files to a model or an external service.
"""

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

WEB_ROOT = Path(__file__).resolve().parents[1]
if str(WEB_ROOT) not in sys.path:
    sys.path.insert(0, str(WEB_ROOT))

from backend.financial_audit.financial_cases import extract_docx_comments  # noqa: E402
from backend.parsers import parse_document  # noqa: E402


PATTERNS: dict[str, tuple[str, tuple[str, ...]]] = {
    "0": ("cross_table_investment_income", ("利润表", "投资收益")),
    "1": ("equity_method_income_reconciliation", ("权益法变动", "权益法核算收益")),
    "2": ("bad_debt_provision_reconciliation", ("坏账", "损失发生额")),
    "3": ("depreciation_reconciliation", ("固定资产折旧", "使用权资产折旧")),
    "4": ("lease_liability_cashflow_reconciliation", ("租赁负债", "筹资流出")),
    "5": ("long_term_investment_repeated_amount", ("长投", "披露")),
    "6": ("rounding_difference", ("尾差",)),
    "7": ("long_term_investment_detail_total", ("合计数", "长投")),
    "8": ("fair_value_reconciliation", ("公允价值", "非流动金融资产")),
    "9": ("outdated_related_party_version", ("整改版本", "最新")),
    "10": ("related_party_classification", ("不是关联方",)),
    "11": ("related_party_classification", ("不是关联方",)),
    "12": ("subtotal_reconciliation", ("合计数",)),
    "13": ("opening_balance_reconciliation", ("期初数", "报表")),
    "14": ("parent_statement_reconciliation", ("母公司利润表", "投资收益")),
    "15": ("required_amount_missing", ("非经常性损益",)),
    "16": ("required_amount_missing", ("所得税影响",)),
    "17": ("detail_total_reconciliation", ("两个数", "勾稽")),
    "18": ("negative_value_range_review", ("都有问题",)),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("original", type=Path)
    parser.add_argument("annotated", type=Path)
    parser.add_argument("spreadsheet", type=Path)
    parser.add_argument("--output", type=Path, default=WEB_ROOT / "knowledge" / "cases" / "financial_annotation_case_2026.json")
    args = parser.parse_args()

    annotated_bytes = args.annotated.read_bytes()
    original_parsed = parse_document(args.original.name, args.original.read_bytes())
    annotated_parsed = parse_document(args.annotated.name, annotated_bytes)
    original_body = [(block.page, block.section, block.block_type, block.text) for block in original_parsed.blocks]
    annotated_body = [(block.page, block.section, block.block_type, block.text) for block in annotated_parsed.blocks]
    if original_body != annotated_body:
        raise SystemExit("原始 DOCX 与批注版正文/表格不一致，未导入案例；请先确认版本。")
    extracted = extract_docx_comments(annotated_bytes, args.annotated.name)
    if not extracted["comments"]:
        raise SystemExit("批注版 DOCX 没有可导入的 Word 批注。")
    annotations: list[dict[str, object]] = []
    for item in extracted["comments"]:
        comment_id = str(item.get("id") or "")
        pattern, terms = PATTERNS.get(comment_id, ("reviewer_confirmed_financial_issue", ()))
        annotations.append({
            "id": comment_id,
            "text": item.get("text", ""),
            "anchor_text": item.get("anchor_text", ""),
            "author": item.get("author", ""),
            "date": item.get("date", ""),
            "pattern": pattern,
            "match_terms": list(terms),
        })

    payload = {
        "schema_version": 1,
        "case_id": "financial-annotation-case-2026-0821",
        "title": "2026年半年度财务报表附注已确认批注案例",
        "validated": True,
        "validation_note": "批注版由复核人员确认；原始 DOCX 与批注版正文一致，批注作为问题金标准。",
        "body_match": True,
        "created_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "original_file": args.original.name,
        "annotated_file": args.annotated.name,
        "spreadsheet_file": args.spreadsheet.name,
        "original_sha256": hashlib.sha256(args.original.read_bytes()).hexdigest(),
        "annotated_sha256": hashlib.sha256(annotated_bytes).hexdigest(),
        "spreadsheet_sha256": hashlib.sha256(args.spreadsheet.read_bytes()).hexdigest(),
        "source": "本地管理员导入的已确认财务审阅案例",
        "annotations": annotations,
        "generalized_patterns": sorted({str(item["pattern"]) for item in annotations}),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"已写入 {args.output}，批注 {len(annotations)} 条。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
