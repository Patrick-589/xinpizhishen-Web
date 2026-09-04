from __future__ import annotations

import calendar
import re
from dataclasses import dataclass
from decimal import Decimal

from ..parsers import ParsedBlock, ParsedDocument
from .models import FinancialCell, FinancialFact, FinancialTable, PeriodRegistry, SourceLocation
from .normalizer import detect_unit, normalize_label, parse_decimal, to_base_amount


PERCENT_TERMS = ("同比", "环比", "比例", "比重", "率", "幅度")
PERCENT_CHANGE_TERMS = (
    "比上年同期增减", "较上年同期增减", "比上期增减", "较上期增减",
)
PERIOD_TERMS = (
    ("本报告期末", "current_end"),
    ("期末余额", "current_end"),
    ("期末数", "current_end"),
    ("上年度末", "prior_year_end"),
    ("期初余额", "prior_year_end"),
    ("期初数", "prior_year_end"),
    ("本报告期", "current_period"),
    ("本期发生额", "current_period"),
    ("本期金额", "current_period"),
    ("上年同期", "comparative_period"),
    ("上期发生额", "comparative_period"),
    ("上期金额", "comparative_period"),
)


@dataclass(frozen=True)
class ExtractedFinancialData:
    tables: list[FinancialTable]
    facts: list[FinancialFact]
    periods: PeriodRegistry


def split_table_rows(text: str) -> list[list[str]]:
    rows: list[list[str]] = []
    lines = [line.strip() for line in str(text or "").splitlines() if line.strip()]
    markdown_wrapped = bool(lines) and all(line.startswith("|") and line.endswith("|") for line in lines)
    for line in lines:
        row_text = line[1:-1] if markdown_wrapped else line
        cells = [cell.strip() for cell in row_text.split("|")]
        if len(cells) >= 2 and any(cells):
            rows.append(cells)
    width = max((len(row) for row in rows), default=0)
    return [row + [""] * (width - len(row)) for row in rows]


def _header_row_count(rows: list[list[str]]) -> int:
    if not rows:
        return 0
    count = 1
    for row in rows[1:4]:
        first = normalize_label(row[0] if row else "")
        numeric_count = sum(parse_decimal(cell) is not None for cell in row)
        if not first and numeric_count == 0:
            count += 1
            continue
        break
    return count


def _header_start(rows: list[list[str]]) -> int:
    """Skip spreadsheet title/unit rows before the actual column header."""
    for index, row in enumerate(rows[:6]):
        compact = [normalize_label(cell) for cell in row]
        if any(value in {"项目", "项目名称", "报告期利润", "被投资单位", "单位名称"} for value in compact):
            return index
    return 0


def _column_labels(rows: list[list[str]], header_count: int) -> list[str]:
    width = max((len(row) for row in rows), default=0)
    labels: list[str] = []
    for column_index in range(width):
        parts: list[str] = []
        for row in rows[:header_count]:
            value = row[column_index].strip()
            if value and value not in parts:
                parts.append(value)
        labels.append(" / ".join(parts) or ("项目" if column_index == 0 else f"第{column_index + 1}列"))
    return labels


def _period_from_label(label: str) -> str:
    compact = normalize_label(label)
    for term, period in PERIOD_TERMS:
        if normalize_label(term) in compact:
            return period
    date_match = re.search(r"(20\d{2})年(?:([1-9]|1[0-2])月(?:([1-9]|[12]\d|3[01])日)?)?", label)
    if date_match:
        return date_match.group(0)
    if any(term in compact for term in ("本期增减变动", "本期变动", "本年增加", "本期增加")):
        return "current_period"
    return ""


def _canonical_name(label: str) -> str:
    value = re.sub(r"^[一二三四五六七八九十]+[、.]", "", str(label or "").strip())
    value = re.sub(r"^\d+[.、]", "", value)
    value = re.sub(r"（(?:元|万元|亿元|元/股|%|％)）", "", value)
    value = re.sub(r"\((?:元|万元|亿元|元/股|%|％)\)", "", value)
    value = re.sub(r"（.*?填列）", "", value)
    value = re.sub(r"\(.*?填列\)", "", value)
    value = re.sub(r"^(?:加|减|其中)[：:]", "", value)
    value = re.sub(r"\s+", "", value)
    aliases = {
        "资产总额": "资产总计",
        "负债和所有者权益总额": "负债和所有者权益总计",
        "归属于上市公司股东的净利润": "归属于母公司所有者的净利润",
        "归母净利润": "归属于母公司所有者的净利润",
        "归属于上市公司股东的净资产": "归属于母公司所有者权益合计",
        "现金及现金等价物增加额": "现金及现金等价物净增加额",
        "权益法下确认的投资损益": "权益法投资收益",
        "权益法核算的长期股权投资收益": "权益法投资收益",
        "对联营企业和合营企业的投资收益": "权益法投资收益",
    }
    return aliases.get(value, value)


def _fact_name(row_label: str, section: str, column_label: str = "") -> str:
    canonical = _canonical_name(row_label)
    if normalize_label(canonical) not in {"合计", "总计", "小计"}:
        if "期末公允价值" in section and "权益工具投资" in canonical:
            return "其他非流动金融资产"
        return canonical
    column_name = _canonical_name(column_label)
    if column_name == "权益法投资收益":
        return column_name
    section_name = _canonical_name(section)
    if any(term in column_name for term in ("减值准备", "坏账准备", "累计折旧", "累计摊销")):
        for candidate in ("长期股权投资", "固定资产", "使用权资产", "应收账款"):
            if candidate in section_name:
                return f"{candidate}减值准备"
    for candidate in (
        "货币资金", "应收账款", "其他应收款", "长期股权投资", "固定资产",
        "使用权资产", "合同负债", "租赁负债", "其他非流动金融资产",
        "应付账款", "其他应付款", "应付职工薪酬", "应交税费",
        "其他非流动资产", "合同资产", "应收票据", "应收款项融资",
    ):
        if candidate in section_name:
            return candidate
    return canonical


def _scope(table_name: str) -> str:
    if "母公司" in table_name:
        return "parent"
    if "合并" in table_name:
        return "consolidated"
    compact = normalize_label(table_name)
    if compact in {
        "资产表", "负债表", "利润表", "现金流量表",
        "股东权益变动表", "所有者权益变动表",
    }:
        return "parent"
    if re.search(r"^(?:\d+|[（(]\d+[）)])[、.]?", table_name) or "附注" in table_name:
        return "note"
    return "disclosure"


def _report_period(filename: str, parsed: ParsedDocument) -> PeriodRegistry:
    sample = filename + "\n" + "\n".join(block.text for block in parsed.blocks[:80])
    match = re.search(r"(20\d{2})年(半年度|年度|第一季度|第三季度)报告", sample)
    if not match:
        return PeriodRegistry()
    year = int(match.group(1))
    report_type = match.group(2)
    if report_type == "半年度":
        start, end = f"{year}-01-01", f"{year}-06-30"
        comparative_end = f"{year - 1}-06-30"
    elif report_type == "第一季度":
        start, end = f"{year}-01-01", f"{year}-03-31"
        comparative_end = f"{year - 1}-03-31"
    elif report_type == "第三季度":
        start, end = f"{year}-01-01", f"{year}-09-30"
        comparative_end = f"{year - 1}-09-30"
    else:
        start, end = f"{year}-01-01", f"{year}-12-31"
        comparative_end = f"{year - 1}-12-31"
    approval_date = ""
    approval_match = re.search(
        r"(?:董事会|批准报出).{0,30}(20\d{2})年(\d{1,2})月(\d{1,2})日",
        sample,
    )
    if approval_match:
        approval_date = f"{int(approval_match.group(1)):04d}-{int(approval_match.group(2)):02d}-{int(approval_match.group(3)):02d}"
    comparative_year = year - 1
    return PeriodRegistry(
        report_type=report_type,
        period_start=start,
        period_end=end,
        as_of_date=end,
        comparative_start=f"{comparative_year}-01-01",
        comparative_end=comparative_end,
        prior_year_end=f"{comparative_year}-12-{calendar.monthrange(comparative_year, 12)[1]:02d}",
        approval_date=approval_date,
    )


class FinancialExtractor:
    def extract(self, parsed: ParsedDocument, document_id: str) -> ExtractedFinancialData:
        tables: list[FinancialTable] = []
        facts: list[FinancialFact] = []
        parent_note_scope = False
        for block_position, block in enumerate(parsed.blocks):
            scope_marker = normalize_label(f"{block.section} {block.text[:160]}")
            if "母公司财务报表主要项目注释" in scope_marker:
                parent_note_scope = True
            elif "合并财务报表主要项目注释" in scope_marker:
                parent_note_scope = False
            if block.block_type != "table":
                continue
            raw_rows = split_table_rows(block.text)
            if len(raw_rows) < 2:
                continue
            header_start = _header_start(raw_rows)
            skipped_rows = raw_rows[:header_start]
            rows = raw_rows[header_start:]
            if len(rows) < 2:
                continue
            header_count = _header_row_count(rows)
            column_labels = _column_labels(rows, header_count)
            nearby_text = " ".join(
                item.text for item in parsed.blocks[max(0, block_position - 4):block_position]
                if item.block_type != "table"
            )
            table_unit = detect_unit(
                block.section,
                nearby_text,
                *(" ".join(row) for row in skipped_rows),
            )
            table_id = f"table-{block.paragraph_index}"
            cells: list[FinancialCell] = []
            row_labels: list[str] = []
            running_offset = block.source_start + sum(len(" | ".join(row)) + 1 for row in skipped_rows)
            source_rows = block.source_row_numbers[header_start:]
            fact_scope = _scope(block.section)
            if parent_note_scope and fact_scope in {"note", "disclosure"}:
                fact_scope = "parent"
            for row_index, row in enumerate(rows):
                row_text = " | ".join(row)
                row_label = next((cell.strip() for cell in row if cell.strip() and parse_decimal(cell) is None), "")
                row_labels.append(row_label)
                cursor = 0
                for column_index, raw_text in enumerate(row):
                    column_label = column_labels[column_index]
                    value = parse_decimal(raw_text)
                    is_percentage = bool(
                        "%" in raw_text
                        or "％" in raw_text
                        or any(term in column_label for term in PERCENT_TERMS)
                        or any(term in column_label for term in PERCENT_CHANGE_TERMS)
                    )
                    original_unit = "%" if is_percentage else detect_unit(row_label, column_label, raw_text) or table_unit
                    normalized_unit = "%" if is_percentage else "元" if original_unit in {"元", "万元", "亿元"} else original_unit
                    period = _period_from_label(column_label)
                    source_start = running_offset + max(0, row_text.find(raw_text, cursor))
                    source_end = source_start + len(raw_text)
                    cursor = max(cursor, source_end - running_offset)
                    row_id = f"{table_id}-row-{row_index}"
                    column_id = f"{table_id}-column-{column_index}"
                    cell_id = f"{row_id}-cell-{column_index}"
                    location = SourceLocation(
                        document_id=document_id,
                        page=block.page,
                        table_id=table_id,
                        table_name=block.section,
                        row_id=row_id,
                        row_label=row_label,
                        column_id=column_id,
                        column_label=column_label,
                        cell_id=cell_id,
                        paragraph_index=block.paragraph_index,
                        source_start=source_start,
                        source_end=source_end,
                        source_text=row_text,
                        spreadsheet_row=source_rows[row_index] if row_index < len(source_rows) else None,
                        sheet_name=block.sheet_name,
                    )
                    cell = FinancialCell(
                        cell_id=cell_id,
                        document_id=document_id,
                        table_id=table_id,
                        table_name=block.section,
                        row_id=row_id,
                        row_index=row_index,
                        row_label=row_label,
                        column_id=column_id,
                        column_index=column_index,
                        column_label=column_label,
                        raw_text=raw_text,
                        normalized_value=value,
                        original_unit=original_unit,
                        normalized_unit=normalized_unit,
                        base_amount=None if is_percentage else to_base_amount(value, original_unit),
                        is_percentage=is_percentage,
                        period=period,
                        location=location,
                    )
                    cells.append(cell)
                    if row_index >= header_count and value is not None and row_label:
                        fact_value = value if is_percentage else (cell.base_amount if cell.base_amount is not None else value)
                        fact_name = _fact_name(row_label, block.section, column_label)
                        if not period and fact_name == "权益法投资收益":
                            period = "current_period"
                        if not period and fact_name == "其他非流动金融资产" and "期末公允价值" in block.section:
                            period = "current_end"
                        facts.append(FinancialFact(
                            fact_id=f"fact-{cell_id}",
                            canonical_name=fact_name,
                            raw_name=row_label,
                            value=fact_value,
                            unit=normalized_unit,
                            period=period,
                            statement_scope=fact_scope,
                            location=location,
                        ))
                running_offset += len(row_text) + 1
            tables.append(FinancialTable(
                table_id=table_id,
                document_id=document_id,
                name=block.section or f"表格 {len(tables) + 1}",
                page=block.page,
                section=block.section,
                paragraph_index=block.paragraph_index,
                rows=rows,
                row_labels=row_labels,
                column_labels=column_labels,
                cells=cells,
                unit=table_unit,
                source_text=block.text,
            ))
        return ExtractedFinancialData(tables, facts, _report_period(parsed.filename, parsed))


__all__ = ["ExtractedFinancialData", "FinancialExtractor", "split_table_rows"]
