from __future__ import annotations

import re
import uuid
from typing import Any

from .parsers import ParsedBlock, ParsedDocument
from .periodic_compare import FINANCIAL_STATEMENT_NOTE_BASIS


AMOUNT_PATTERN = re.compile(r"^[+\-−—－]?\d[\d,]*(?:\.\d+)?$")
BLANK_AMOUNT_VALUES = {"", "-", "--", "—", "－", "/", "不适用"}
TOTAL_LABELS = {"合计", "总计"}
CARRYING_BALANCE_TERMS = ("账面余额", "原值")
CARRYING_ALLOWANCE_TERMS = ("坏账准备", "减值准备", "累计折旧", "累计摊销")
CARRYING_VALUE_TERMS = ("账面价值", "净额")
OPENING_TERMS = ("期初余额", "期初数", "年初余额")
INCREASE_TERMS = ("本期增加", "本期增加额", "增加额")
DECREASE_TERMS = ("本期减少", "本期减少额", "减少额")
CLOSING_TERMS = ("期末余额", "期末数", "年末余额")


def _normalize(value: str) -> str:
    return re.sub(r"[\s：:（）()]", "", value).strip()


def _amount(value: str, *, blank_as_zero: bool = False) -> float | None:
    compact = value.strip().replace(" ", "")
    if compact in BLANK_AMOUNT_VALUES:
        return 0.0 if blank_as_zero else None
    if compact.endswith("%"):
        return None
    negative_parentheses = compact.startswith("(") and compact.endswith(")")
    if negative_parentheses:
        compact = compact[1:-1]
    compact = compact.replace(",", "").replace("−", "-").replace("—", "-").replace("－", "-")
    if not AMOUNT_PATTERN.fullmatch(compact):
        return None
    number = float(compact)
    return -abs(number) if negative_parentheses else number


def _matches(value: str, terms: tuple[str, ...]) -> bool:
    normalized = _normalize(value)
    return any(_normalize(term) in normalized for term in terms)


def _equal(left: float, right: float) -> bool:
    tolerance = max(0.02, abs(right) * 1e-9)
    return abs(left - right) <= tolerance


def _format_amount(value: float) -> str:
    return f"{value:,.2f}"


def _signed_detail_amount(section: str, label: str, value: float) -> float:
    normalized_label = _normalize(label)
    normalized_section = _normalize(section)
    if normalized_label.startswith("减"):
        return -abs(value)
    if "财务费用" in normalized_section and "利息收入" in normalized_label:
        return -value
    if "非经常性损益" in normalized_section and "少数股东权益影响额" in normalized_label:
        return -value
    return value


def _rows(block: ParsedBlock) -> list[tuple[str, list[str]]]:
    values: list[tuple[str, list[str]]] = []
    lines = [line.strip() for line in block.text.splitlines() if line.strip()]
    markdown_wrapped = bool(lines) and all(line.startswith("|") and line.endswith("|") for line in lines)
    for line in lines:
        row_text = line[1:-1] if markdown_wrapped else line
        cells = [cell.strip() for cell in row_text.split("|")]
        if len(cells) >= 2 and any(cells):
            values.append((line, cells))
    return values


def _risk(
    block: ParsedBlock,
    *,
    title: str,
    description: str,
    recommendation: str,
    formula: str,
    source_lines: list[tuple[str, str]],
) -> dict[str, Any]:
    location_items = [
        {
            "label": label,
            "page": block.page,
            "section": block.section,
            "paragraphIndex": block.paragraph_index,
            "text": text,
        }
        for label, text in source_lines
    ]
    return {
        "id": str(uuid.uuid4()),
        "level": "high",
        "type": "财务附注 Casting",
        "title": title,
        "description": description,
        "evidence": "\n".join(text for _label, text in source_lines),
        "source_text": source_lines[0][1],
        "page": block.page,
        "section": block.section,
        "paragraph_index": block.paragraph_index,
        "location": {
            "page": block.page,
            "section": block.section,
            "paragraph": block.paragraph_index + 1,
            "items": location_items,
        },
        "regulation_basis": [dict(item) for item in FINANCIAL_STATEMENT_NOTE_BASIS],
        "company_basis": [],
        "internal_rule_basis": [],
        "historical_cases": [],
        "source_documents": [],
        "recommendation": recommendation,
        "confidence": 0.99,
        "formula": formula,
    }


class LocalCastingEngine:
    """Conservative arithmetic checks for locally parsed financial-note tables."""

    def analyze(self, parsed: ParsedDocument) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        risks: list[dict[str, Any]] = []
        checked = 0
        tables = [block for block in parsed.blocks if block.block_type == "table"]
        for block in tables:
            table_rows = _rows(block)
            if len(table_rows) < 2:
                continue
            carrying_risks, carrying_checked = self._check_carrying_value(block, table_rows)
            movement_risks, movement_checked = self._check_movement(block, table_rows)
            total_risks, total_checked = self._check_simple_total(block, table_rows)
            risks.extend(carrying_risks)
            risks.extend(movement_risks)
            risks.extend(total_risks)
            checked += carrying_checked + movement_checked + total_checked
        return risks, {
            "mode": "local_deterministic",
            "externalAiUsed": False,
            "tablesScanned": len(tables),
            "checksPerformed": checked,
            "mismatches": len(risks),
            "scope": ["simple_totals", "carrying_value", "movement_roll_forward"],
        }

    @staticmethod
    def _find_header(
        table_rows: list[tuple[str, list[str]]],
        groups: tuple[tuple[str, ...], ...],
    ) -> tuple[int, list[int]] | None:
        for row_index, (_line, cells) in enumerate(table_rows):
            indexes: list[int] = []
            for terms in groups:
                index = next((cell_index for cell_index, cell in enumerate(cells) if _matches(cell, terms)), None)
                if index is None:
                    break
                indexes.append(index)
            if len(indexes) == len(groups) and len(set(indexes)) == len(indexes):
                return row_index, indexes
        return None

    def _check_carrying_value(
        self,
        block: ParsedBlock,
        table_rows: list[tuple[str, list[str]]],
    ) -> tuple[list[dict[str, Any]], int]:
        header = self._find_header(
            table_rows,
            (CARRYING_BALANCE_TERMS, CARRYING_ALLOWANCE_TERMS, CARRYING_VALUE_TERMS),
        )
        if not header:
            return [], 0
        header_index, (balance_index, allowance_index, value_index) = header
        maximum_index = max(balance_index, allowance_index, value_index)
        risks: list[dict[str, Any]] = []
        checked = 0
        for line, cells in table_rows[header_index + 1:]:
            if len(cells) <= maximum_index or not cells[0].strip():
                continue
            balance = _amount(cells[balance_index])
            allowance = _amount(cells[allowance_index], blank_as_zero=True)
            carrying_value = _amount(cells[value_index])
            if balance is None or allowance is None or carrying_value is None:
                continue
            checked += 1
            expected = balance - allowance
            if _equal(carrying_value, expected):
                continue
            label = cells[0].strip()
            risks.append(_risk(
                block,
                title=f"账面价值计算不一致：{label}",
                description=(
                    f"按“账面余额/原值－坏账准备、减值准备、累计折旧或累计摊销”复算应为 {_format_amount(expected)}，"
                    f"表内列示 {_format_amount(carrying_value)}，差额 {_format_amount(carrying_value - expected)}。"
                ),
                recommendation=(
                    "核对该行账面余额、准备或累计折旧摊销及账面价值的底稿；确认准备金额的正负列示口径后，"
                    "同步修正附注分类、合计和财务报表对应项目。"
                ),
                formula="账面余额/原值 - 准备/累计折旧摊销 = 账面价值",
                source_lines=[(f"{label}：账面价值公式", line)],
            ))
        return risks, checked

    def _check_movement(
        self,
        block: ParsedBlock,
        table_rows: list[tuple[str, list[str]]],
    ) -> tuple[list[dict[str, Any]], int]:
        header = self._find_header(
            table_rows,
            (OPENING_TERMS, INCREASE_TERMS, DECREASE_TERMS, CLOSING_TERMS),
        )
        if not header:
            return [], 0
        header_index, (opening_index, increase_index, decrease_index, closing_index) = header
        header_width = len(table_rows[header_index][1])
        table_width = max(len(cells) for _line, cells in table_rows)
        if header_width < table_width:
            # Older parser output omitted placeholders created by Word gridSpan.
            # Recover only when the following subheaders form two identical groups.
            subheader = next((
                cells for _line, cells in table_rows[header_index + 1:header_index + 3]
                if not any(_amount(cell) is not None for cell in cells)
            ), None)
            normalized_subheaders = [
                _normalize(cell) for cell in (subheader or []) if _normalize(cell)
            ]
            midpoint = len(normalized_subheaders) // 2
            if (
                not normalized_subheaders
                or len(normalized_subheaders) % 2
                or normalized_subheaders[:midpoint] != normalized_subheaders[midpoint:]
                or table_width - opening_index - 2 != len(normalized_subheaders)
            ):
                return [], 0
            increase_index = opening_index + 1
            decrease_index = increase_index + midpoint
            closing_index = table_width - 1
        if not opening_index < increase_index < decrease_index < closing_index:
            return [], 0
        increase_indexes = range(increase_index, decrease_index)
        decrease_indexes = range(decrease_index, closing_index)
        maximum_index = max(opening_index, increase_index, decrease_index, closing_index)
        risks: list[dict[str, Any]] = []
        checked = 0
        for line, cells in table_rows[header_index + 1:]:
            if len(cells) <= maximum_index or not cells[0].strip():
                continue
            opening = _amount(cells[opening_index], blank_as_zero=True)
            increases = [_amount(cells[index], blank_as_zero=True) for index in increase_indexes]
            decreases = [_amount(cells[index], blank_as_zero=True) for index in decrease_indexes]
            closing = _amount(cells[closing_index])
            if (
                opening is None or closing is None
                or any(value is None for value in increases)
                or any(value is None for value in decreases)
            ):
                continue
            checked += 1
            increase_total = sum(value for value in increases if value is not None)
            decrease_total = sum(value for value in decreases if value is not None)
            expected = opening + increase_total - decrease_total
            if _equal(closing, expected):
                continue
            label = cells[0].strip()
            risks.append(_risk(
                block,
                title=f"变动表不闭合：{label}",
                description=(
                    f"按“期初余额＋本期增加－本期减少”复算期末余额应为 {_format_amount(expected)}，"
                    f"表内列示 {_format_amount(closing)}，差额 {_format_amount(closing - expected)}。"
                ),
                recommendation=(
                    "逐项核对期初、本期增加、本期减少和期末底稿；如存在重分类、核销、转回或其他变动，"
                    "应在表内单独列示后再复算，并同步核对报表和相关附注。"
                ),
                formula="期初余额 + 本期增加合计 - 本期减少合计 = 期末余额",
                source_lines=[(f"{label}：变动闭合公式", line)],
            ))
        return risks, checked

    def _check_simple_total(
        self,
        block: ParsedBlock,
        table_rows: list[tuple[str, list[str]]],
    ) -> tuple[list[dict[str, Any]], int]:
        total_positions = [
            index for index, (_line, cells) in enumerate(table_rows)
            if cells and _normalize(cells[0]) in TOTAL_LABELS
        ]
        if len(total_positions) != 1 or total_positions[0] != len(table_rows) - 1:
            return [], 0
        header_line, header_cells = table_rows[0]
        del header_line
        if not header_cells or not any(term in header_cells[0] for term in ("项目", "类别", "科目", "名称")):
            return [], 0
        detail_rows = table_rows[1:-1]
        total_line, total_cells = table_rows[-1]
        if not 2 <= len(detail_rows) <= 30:
            return [], 0
        if any(_normalize(cells[0]).startswith("其中") for _line, cells in detail_rows if cells):
            return [], 0
        if any(len(cells) != len(total_cells) for _line, cells in detail_rows):
            return [], 0

        differences: list[str] = []
        checked = 0
        for column_index in range(1, len(total_cells)):
            if column_index >= len(header_cells) or any(term in header_cells[column_index] for term in ("比例", "率")):
                continue
            total = _amount(total_cells[column_index])
            if total is None:
                continue
            detail_values = [_amount(cells[column_index], blank_as_zero=True) for _line, cells in detail_rows]
            if any(value is None for value in detail_values):
                continue
            checked += 1
            expected = sum(
                _signed_detail_amount(block.section, cells[0], value)
                for (_line, cells), value in zip(detail_rows, detail_values)
                if value is not None
            )
            if not _equal(total, expected):
                column_name = header_cells[column_index] or f"第{column_index + 1}列"
                differences.append(
                    f"{column_name}：明细合计 {_format_amount(expected)}，表内合计 {_format_amount(total)}，"
                    f"差额 {_format_amount(total - expected)}"
                )
        if not differences:
            return [], checked
        detail_locations = [
            (f"明细：{cells[0]}", line) for line, cells in detail_rows[:12]
        ]
        return [_risk(
            block,
            title=f"附注明细合计不一致：{block.section}",
            description="；".join(differences) + "。",
            recommendation=(
                "回查该附注明细的原始底稿，确认空白项、负数、重分类和四舍五入口径；修正明细或合计后，"
                "同步核对财务报表对应项目及其他引用该合计数的附注。"
            ),
            formula="分类明细金额之和 = 合计",
            source_lines=[("表内合计", total_line), *detail_locations],
        )], checked


def review_casting(parsed: ParsedDocument) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    return LocalCastingEngine().analyze(parsed)


__all__ = ["LocalCastingEngine", "review_casting"]
