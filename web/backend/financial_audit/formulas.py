from __future__ import annotations

import hashlib
import re
from decimal import Decimal, ROUND_HALF_UP
from typing import Callable, Iterable

from ..financial_change import calculate_financial_change
from .models import AuditCheck, FinancialCell, FinancialFact, FinancialTable, SourceLocation
from .normalizer import (
    CENT,
    close_enough,
    decimal_text,
    is_order_of_magnitude_error,
    normalize_label,
    parse_decimal,
    percentage_difference,
)


PERCENT_TOLERANCE = Decimal("0.01")
RATIO_CHECK_TOLERANCE = Decimal("0.01")
OPENING_BALANCE_TERMS = ("期初余额", "年初余额", "期初数", "年初数")
CLOSING_BALANCE_TERMS = ("期末余额", "年末余额", "期末数", "年末数")
BALANCE_ALLOWANCE_TERMS = ("减值准备", "坏账准备", "跌价准备", "累计折旧", "累计摊销")
MAJOR_CROSS_TABLE_FACTS = {
    "货币资金", "应收账款", "其他应收款", "长期股权投资", "固定资产",
    "使用权资产", "合同负债", "租赁负债", "其他非流动金融资产",
    "营业收入", "净利润", "归属于母公司所有者的净利润",
    "经营活动产生的现金流量净额", "现金及现金等价物净增加额",
}


def _stable_id(rule_id: str, title: str, locations: Iterable[SourceLocation]) -> str:
    location_key = ";".join(location.cell_id for location in locations)
    digest = hashlib.sha256(f"{rule_id}|{title}|{location_key}".encode("utf-8")).hexdigest()[:20]
    return f"financial-{digest}"


def _check(
    rule_id: str,
    status: str,
    severity: str,
    category: str,
    title: str,
    explanation: str,
    suggestion: str,
    *,
    formula: str = "",
    reported_value: Decimal | str | None = None,
    calculated_value: Decimal | str | None = None,
    difference: Decimal | str | None = None,
    inputs: dict | None = None,
    locations: Iterable[SourceLocation] = (),
    source_sufficient: bool = True,
) -> AuditCheck:
    source_locations = list(locations)
    return AuditCheck(
        check_id=_stable_id(rule_id, title, source_locations),
        rule_id=rule_id,
        status=status,
        severity=severity,
        category=category,
        title=title,
        explanation=explanation,
        suggestion=suggestion,
        formula=formula,
        reported_value=reported_value,
        calculated_value=calculated_value,
        difference=difference,
        inputs=inputs or {},
        source_locations=source_locations,
        source_sufficient=source_sufficient,
    )


def _row_name(value: str) -> str:
    value = re.sub(r"^[一二三四五六七八九十]+[、.]", "", str(value or "").strip())
    value = re.sub(r"^\d+[、.]", "", value)
    value = re.sub(r"^(?:加|减|其中)[：:]", "", value)
    value = re.sub(r"[（(].*?填列[）)]", "", value)
    return normalize_label(value)


def _find_row(table: FinancialTable, term: str) -> tuple[int, list[str]] | None:
    target = normalize_label(term)
    exact: list[tuple[int, list[str]]] = []
    partial: list[tuple[int, list[str]]] = []
    for index, row in enumerate(table.rows):
        if not row:
            continue
        name = _row_name(row[0])
        if name == target:
            exact.append((index, row))
        elif target in name:
            partial.append((index, row))
    return (exact or partial or [None])[0]


def _cell(table: FinancialTable, row_index: int, column_index: int) -> FinancialCell | None:
    return next((
        item for item in table.cells
        if item.row_index == row_index and item.column_index == column_index
    ), None)


def _amount(table: FinancialTable, row_index: int, column_index: int) -> Decimal | None:
    cell = _cell(table, row_index, column_index)
    if cell is None or cell.is_percentage:
        return None
    return cell.base_amount if cell.base_amount is not None else cell.normalized_value


def _percentage(table: FinancialTable, row_index: int, column_index: int) -> Decimal | None:
    cell = _cell(table, row_index, column_index)
    return cell.normalized_value if cell is not None else None


def _amount_or_zero(table: FinancialTable, row_index: int, column_index: int) -> Decimal | None:
    value = _amount(table, row_index, column_index)
    if value is not None:
        return value
    cell = _cell(table, row_index, column_index)
    if cell is not None and not cell.raw_text.strip():
        return Decimal(0)
    return None


def _locations(table: FinancialTable, pairs: Iterable[tuple[int, int]]) -> list[SourceLocation]:
    return [cell.location for row, column in pairs if (cell := _cell(table, row, column)) is not None]


def _statement_columns(table: FinancialTable) -> list[int]:
    width = max((len(row) for row in table.rows), default=0)
    return [index for index in range(1, width) if any(_amount(table, row, index) is not None for row in range(len(table.rows)))]


def _equation_check(
    table: FinancialTable,
    rule_id: str,
    category: str,
    title: str,
    formula: str,
    column_index: int,
    terms: list[tuple[str, Decimal]],
    result_term: str,
) -> AuditCheck | None:
    inputs: list[tuple[str, int, Decimal, Decimal]] = []
    for term, sign in terms:
        row = _find_row(table, term)
        if row is None:
            return None
        value = _amount(table, row[0], column_index)
        if value is None:
            return None
        inputs.append((term, row[0], value, sign))
    result_row = _find_row(table, result_term)
    if result_row is None:
        return None
    reported = _amount(table, result_row[0], column_index)
    if reported is None:
        return None
    calculated = sum((value * sign for _term, _row, value, sign in inputs), Decimal(0))
    difference = reported - calculated
    location_pairs = [(row, column_index) for _term, row, _value, _sign in inputs]
    location_pairs.append((result_row[0], column_index))
    period = table.column_labels[column_index] if column_index < len(table.column_labels) else f"第{column_index + 1}列"
    if close_enough(reported, calculated):
        return _check(
            rule_id, "passed", "none", category, f"已核对无误：{title}（{period}）",
            f"表内列示值与本地 Decimal 复算结果一致，差异 {decimal_text(difference)}。",
            "无需修改；保留当前底稿和来源定位。",
            formula=formula,
            reported_value=reported,
            calculated_value=calculated,
            difference=difference,
            inputs={term: value for term, _row, value, _sign in inputs},
            locations=_locations(table, location_pairs),
        )
    return _check(
        rule_id, "failed", "high", category, f"{title}不一致（{period}）",
        f"本地复算应为 {decimal_text(calculated)}，表内列示 {decimal_text(reported)}，差异 {decimal_text(difference)}。",
        "核对相关科目底稿、符号与报表公式，并同步修改所有重复披露位置。",
        formula=formula,
        reported_value=reported,
        calculated_value=calculated,
        difference=difference,
        inputs={term: value for term, _row, value, _sign in inputs},
        locations=_locations(table, location_pairs),
    )


class FinancialFormulaEngine:
    def statement_checks(self, tables: list[FinancialTable]) -> list[AuditCheck]:
        checks: list[AuditCheck] = []
        for table in tables:
            columns = _statement_columns(table)[:2]
            if "资产负债表" in table.name:
                equations = [
                    ("BALANCE-ASSETS-SUBTOTAL", "资产负债表", "资产分类合计", "流动资产合计 + 非流动资产合计 = 资产总计", [("流动资产合计", Decimal(1)), ("非流动资产合计", Decimal(1))], "资产总计"),
                    ("BALANCE-LIABILITIES-SUBTOTAL", "资产负债表", "负债分类合计", "流动负债合计 + 非流动负债合计 = 负债合计", [("流动负债合计", Decimal(1)), ("非流动负债合计", Decimal(1))], "负债合计"),
                    ("BALANCE-EQUITY-TOTAL", "资产负债表", "负债和所有者权益合计", "负债合计 + 所有者权益合计 = 负债和所有者权益总计", [("负债合计", Decimal(1)), ("所有者权益合计", Decimal(1))], "负债和所有者权益总计"),
                    ("BALANCE-EQUATION", "跨表勾稽", "资产负债表平衡", "资产总计 = 负债和所有者权益总计", [("资产总计", Decimal(1))], "负债和所有者权益总计"),
                ]
            elif "利润表" in table.name:
                equations = [
                    ("PROFIT-TOTAL", "利润表勾稽", "利润总额关系", "营业利润 + 营业外收入 - 营业外支出 = 利润总额", [("营业利润", Decimal(1)), ("营业外收入", Decimal(1)), ("营业外支出", Decimal(-1))], "利润总额"),
                    ("PROFIT-NET", "利润表勾稽", "净利润关系", "利润总额 - 所得税费用 = 净利润", [("利润总额", Decimal(1)), ("所得税费用", Decimal(-1))], "净利润"),
                    ("PROFIT-ATTRIBUTABLE", "利润表勾稽", "归母净利润关系", "归属于母公司所有者的净利润 + 少数股东损益 = 净利润", [("归属于母公司所有者的净利润", Decimal(1)), ("少数股东损益", Decimal(1))], "净利润"),
                ]
            elif "现金流量表" in table.name:
                equations = [
                    ("CASH-OPERATING", "现金流勾稽", "经营活动现金流净额", "经营活动现金流入小计 - 经营活动现金流出小计 = 经营活动产生的现金流量净额", [("经营活动现金流入小计", Decimal(1)), ("经营活动现金流出小计", Decimal(-1))], "经营活动产生的现金流量净额"),
                    ("CASH-INVESTING", "现金流勾稽", "投资活动现金流净额", "投资活动现金流入小计 - 投资活动现金流出小计 = 投资活动产生的现金流量净额", [("投资活动现金流入小计", Decimal(1)), ("投资活动现金流出小计", Decimal(-1))], "投资活动产生的现金流量净额"),
                    ("CASH-FINANCING", "现金流勾稽", "筹资活动现金流净额", "筹资活动现金流入小计 - 筹资活动现金流出小计 = 筹资活动产生的现金流量净额", [("筹资活动现金流入小计", Decimal(1)), ("筹资活动现金流出小计", Decimal(-1))], "筹资活动产生的现金流量净额"),
                    ("CASH-CHANGE", "现金流勾稽", "现金净增加额", "经营净额 + 投资净额 + 筹资净额 + 汇率变动影响 = 现金及现金等价物净增加额", [("经营活动产生的现金流量净额", Decimal(1)), ("投资活动产生的现金流量净额", Decimal(1)), ("筹资活动产生的现金流量净额", Decimal(1)), ("汇率变动对现金及现金等价物的影响", Decimal(1))], "现金及现金等价物净增加额"),
                    ("CASH-CLOSING", "现金流勾稽", "期末现金余额", "期初现金及现金等价物余额 + 现金及现金等价物净增加额 = 期末现金及现金等价物余额", [("期初现金及现金等价物余额", Decimal(1)), ("现金及现金等价物净增加额", Decimal(1))], "期末现金及现金等价物余额"),
                ]
            else:
                continue
            for column in columns:
                for rule_id, category, title, formula, terms, result in equations:
                    check = _equation_check(table, rule_id, category, f"{table.name}：{title}", formula, column, terms, result)
                    if check is not None:
                        checks.append(check)
        return checks

    def yoy_checks(self, tables: list[FinancialTable]) -> list[AuditCheck]:
        checks: list[AuditCheck] = []
        for table in tables:
            labels = table.column_labels
            current_index = next((index for index, label in enumerate(labels) if "本报告期" in label or "本期发生额" in label), None)
            previous_index = next((index for index, label in enumerate(labels) if "上年同期" in label or "上期发生额" in label), None)
            yoy_index = next((index for index, label in enumerate(labels) if "同比" in label or "比上年同期增减" in label), None)
            if current_index is None or previous_index is None or yoy_index is None:
                continue
            for row_index, row in enumerate(table.rows):
                if row_index == 0 or not row or not row[0].strip():
                    continue
                label = row[0].strip()
                current_cell = _cell(table, row_index, current_index)
                previous_cell = _cell(table, row_index, previous_index)
                reported = _percentage(table, row_index, yoy_index)
                if current_cell is None or previous_cell is None or reported is None:
                    continue
                current = current_cell.normalized_value
                previous = previous_cell.normalized_value
                if current is None or previous is None:
                    continue
                locations = _locations(table, [(row_index, current_index), (row_index, previous_index), (row_index, yoy_index)])
                if "净资产收益率" in label:
                    calculated = (current - previous).quantize(CENT, rounding=ROUND_HALF_UP)
                    difference = percentage_difference(reported, calculated)
                    status = "passed" if difference <= PERCENT_TOLERANCE else "failed"
                    checks.append(_check(
                        "PERCENTAGE-POINT-CHANGE", status, "none" if status == "passed" else "high", "同比/百分比",
                        ("已核对无误：" if status == "passed" else "百分点变化计算不一致：") + label,
                        f"该指标应展示百分点变化，本期 {current}% 减上期 {previous}% 等于 {calculated} 个百分点；文档列示 {reported}%。",
                        "使用“个百分点”表述，不要与同比变化率混用。" if status != "passed" else "保留百分点口径。",
                        formula="本期百分比 - 上期百分比 = 百分点变化",
                        reported_value=reported, calculated_value=calculated, difference=difference,
                        inputs={"current_percent": current, "previous_percent": previous}, locations=locations,
                    ))
                    continue
                semantic = "cash_flow" if any(term in label for term in ("现金", "净流入", "净流出")) else "profit_loss"
                change = calculate_financial_change(current, previous, semantic=semantic, label=label)
                if change.display_yoy_rate is None:
                    checks.append(_check(
                        "YOY-NEGATIVE-SEMANTICS", "needs_review", "medium", "同比/百分比",
                        f"同比展示语义需调整：{label}",
                        f"本期 {decimal_text(current)}，上期 {decimal_text(previous)}；确定性规则判断为“{change.display_change_text}”。文档列示 {reported}%，不宜直接作为正常同比增长/下降率展示。",
                        f"将展示文案改为“{change.display_change_text}”，金额并列展示；数学计算值仅保留在内部字段。",
                        formula="负值或正负转换场景不展示传统同比百分比",
                        reported_value=reported, calculated_value=change.display_change_text,
                        inputs=change.to_dict(), locations=locations,
                    ))
                    continue
                calculated = change.display_yoy_rate
                difference = percentage_difference(reported, calculated)
                status = "passed" if difference <= PERCENT_TOLERANCE else "failed"
                severe = status == "failed" and (difference >= Decimal("1") or is_order_of_magnitude_error(reported, calculated))
                checks.append(_check(
                    "YOY-RECALCULATION", status, "none" if status == "passed" else ("high" if severe else "medium"), "同比/百分比",
                    ("已核对无误：" if status == "passed" else "同比百分比计算不一致：") + label,
                    f"本地复算为 {calculated}%，文档列示 {reported}%，差异 {difference} 个百分点。",
                    "核对本期、上期金额和百分号位置后统一修改。" if status != "passed" else "无需修改。",
                    formula="(本期 - 上期) / abs(上期) * 100%",
                    reported_value=reported, calculated_value=calculated, difference=difference,
                    inputs={"current": current, "previous": previous}, locations=locations,
                ))
        return checks

    def profit_ratio_checks(self, tables: list[FinancialTable], facts: list[FinancialFact]) -> list[AuditCheck]:
        profit_facts = [
            fact for fact in facts
            if fact.canonical_name == "利润总额" and fact.statement_scope == "consolidated"
        ]
        if not profit_facts:
            return []
        profit = next((
            fact for fact in profit_facts
            if fact.period == "current_period" or "本报告期" in fact.location.column_label
        ), profit_facts[0])
        checks: list[AuditCheck] = []
        for table in tables:
            amount_index = next((index for index, label in enumerate(table.column_labels) if normalize_label(label) == "金额"), None)
            ratio_index = next((index for index, label in enumerate(table.column_labels) if "占利润总额比例" in label), None)
            if amount_index is None or ratio_index is None:
                continue
            for row_index, row in enumerate(table.rows[1:], start=1):
                if not row or not row[0].strip():
                    continue
                amount = _amount(table, row_index, amount_index)
                reported = _percentage(table, row_index, ratio_index)
                if amount is None or reported is None or profit.value == 0:
                    continue
                calculated = (abs(amount) / abs(profit.value) * Decimal(100)).quantize(CENT, rounding=ROUND_HALF_UP)
                difference = percentage_difference(reported, calculated)
                status = "passed" if difference <= PERCENT_TOLERANCE else "failed"
                severe = status == "failed" and (difference >= Decimal("1") or is_order_of_magnitude_error(reported, calculated))
                locations = _locations(table, [(row_index, amount_index), (row_index, ratio_index)]) + [profit.location]
                label = row[0].strip()
                checks.append(_check(
                    "PROFIT-TOTAL-RATIO", status, "none" if status == "passed" else ("high" if severe else "medium"), "百分比",
                    ("已核对无误：" if status == "passed" else "占利润总额比例计算不一致：") + label,
                    f"{label}金额 {decimal_text(amount)} / 利润总额绝对值 {decimal_text(abs(profit.value))} = {calculated}%；文档列示 {reported}%。",
                    "核对利润总额取数和小数点/百分号位置，修改后同步核对本表所有行。" if status != "passed" else "无需修改。",
                    formula="abs(项目金额) / abs(利润总额) * 100%",
                    reported_value=reported, calculated_value=calculated, difference=difference,
                    inputs={"item_amount": amount, "profit_total": profit.value}, locations=locations,
                ))
        return checks

    def gross_margin_checks(self, tables: list[FinancialTable]) -> list[AuditCheck]:
        checks: list[AuditCheck] = []
        for table in tables:
            revenue_index = next((index for index, label in enumerate(table.column_labels) if normalize_label(label) == "营业收入"), None)
            cost_index = next((index for index, label in enumerate(table.column_labels) if normalize_label(label) == "营业成本"), None)
            margin_index = next((index for index, label in enumerate(table.column_labels) if normalize_label(label) == "毛利率"), None)
            if revenue_index is None or cost_index is None or margin_index is None:
                continue
            for row_index, row in enumerate(table.rows[1:], start=1):
                if not row or not row[0].strip():
                    continue
                revenue = _amount(table, row_index, revenue_index)
                cost = _amount(table, row_index, cost_index)
                reported = _percentage(table, row_index, margin_index)
                if revenue in {None, Decimal(0)} or cost is None or reported is None:
                    continue
                calculated = ((revenue - cost) / revenue * Decimal(100)).quantize(CENT, rounding=ROUND_HALF_UP)
                difference = percentage_difference(reported, calculated)
                status = "passed" if difference <= PERCENT_TOLERANCE else "failed"
                label = row[0].strip()
                checks.append(_check(
                    "GROSS-MARGIN", status, "none" if status == "passed" else "high", "百分比",
                    ("已核对无误：" if status == "passed" else "毛利率计算不一致：") + label,
                    f"(营业收入 {decimal_text(revenue)} - 营业成本 {decimal_text(cost)}) / 营业收入 = {calculated}%；文档列示 {reported}%。",
                    "核对收入、成本取数后修正毛利率。" if status != "passed" else "无需修改。",
                    formula="(营业收入 - 营业成本) / 营业收入 * 100%",
                    reported_value=reported, calculated_value=calculated, difference=difference,
                    inputs={"revenue": revenue, "cost": cost},
                    locations=_locations(table, [(row_index, revenue_index), (row_index, cost_index), (row_index, margin_index)]),
                ))
        return checks

    def table_proportion_checks(self, tables: list[FinancialTable]) -> list[AuditCheck]:
        """Recalculate row-level proportions in disclosure tables.

        A table such as the top-five receivables disclosure has a numerator
        column, a percentage column and a total row.  The total percentage is
        the only reliable denominator when the full balance is not printed in
        the table, so it is used to derive that denominator with Decimal.  A
        missing or ambiguous denominator produces a manual-review finding;
        the engine must never guess one from the visible detail rows.
        """
        checks: list[AuditCheck] = []
        for table in tables:
            if not table.rows:
                continue
            ratio_indexes = [
                index for index, label in enumerate(table.column_labels)
                if self._is_disclosure_proportion_label(label)
                and "利润总额" not in normalize_label(label)
            ]
            if not ratio_indexes:
                continue
            total_positions = [
                index for index, row in enumerate(table.rows)
                if row and normalize_label(row[0]) in {"合计", "总计"}
            ]
            if len(total_positions) != 1:
                continue
            total_index = total_positions[0]
            for ratio_index in ratio_indexes:
                numerator_index = self._proportion_numerator_column(table, ratio_index, total_index)
                if numerator_index is None:
                    continue
                total_numerator = _amount(table, total_index, numerator_index)
                total_ratio = _percentage(table, total_index, ratio_index)
                total_locations = _locations(
                    table,
                    [(total_index, numerator_index), (total_index, ratio_index)],
                )
                if total_numerator is None or total_ratio in (None, Decimal(0)):
                    # Do not infer a denominator from the sum of the displayed
                    # rows: these tables commonly show only the top five.
                    location_pairs = [
                        (row_index, ratio_index)
                        for row_index in range(1, total_index)
                        if _percentage(table, row_index, ratio_index) is not None
                    ]
                    locations = _locations(table, location_pairs) + total_locations
                    checks.append(_check(
                        "TABLE-PROPORTION-DENOMINATOR-MISSING",
                        "needs_review",
                        "medium",
                        "表格比例",
                        f"比例分母无法确认：{table.name}",
                        "表格包含“占……合计数比例”列，但未同时提供可核验的合计金额与合计比例，"
                        "不能仅用当前展示的明细行合计反推分母。",
                        "补充同口径的总余额来源（报表、附注或 Excel 底稿），确认分母后再复核每一行比例。",
                        formula="明细金额 / 唯一可核验的比例分母 * 100%",
                        inputs={
                            "ratio_column": table.column_labels[ratio_index],
                            "numerator_column": table.column_labels[numerator_index],
                            "denominator_status": "missing_or_ambiguous",
                        },
                        locations=locations,
                        source_sufficient=False,
                    ))
                    continue

                denominator = (
                    total_numerator * Decimal(100) / total_ratio
                ).quantize(CENT, rounding=ROUND_HALF_UP)
                if denominator == 0:
                    continue
                for row_index in range(1, total_index):
                    numerator = _amount(table, row_index, numerator_index)
                    reported = _percentage(table, row_index, ratio_index)
                    row = table.rows[row_index] if row_index < len(table.rows) else []
                    label = row[0].strip() if row else ""
                    if not label or numerator is None or reported is None:
                        continue
                    calculated = (
                        numerator * Decimal(100) / denominator
                    ).quantize(CENT, rounding=ROUND_HALF_UP)
                    difference = percentage_difference(reported, calculated)
                    status = "passed" if difference <= RATIO_CHECK_TOLERANCE else "failed"
                    severity = "none" if status == "passed" else (
                        "high" if difference >= Decimal(1) else "medium"
                    )
                    locations = _locations(
                        table,
                        [
                            (row_index, numerator_index),
                            (row_index, ratio_index),
                        ],
                    ) + total_locations
                    checks.append(_check(
                        "TABLE-PROPORTION-RECALCULATION",
                        status,
                        severity,
                        "表格比例",
                        (
                            ("已核对无误：" if status == "passed" else "占比计算不一致：")
                            + label
                        ),
                        (
                            f"分子 {decimal_text(numerator)} / 推导分母 {decimal_text(denominator)} "
                            f"= {decimal_text(calculated)}%；文档列示 {decimal_text(reported)}%，"
                            f"差异 {decimal_text(difference)} 个百分点。"
                        ),
                        (
                            "无需修改。"
                            if status == "passed"
                            else "以同口径总余额为分母修正该行比例，并同步检查合计行、公告及其他重复披露位置。"
                        ),
                        formula="行项目金额 / 比例分母 * 100%（分母由合计金额与合计比例反推）",
                        reported_value=reported,
                        calculated_value=calculated,
                        difference=difference,
                        inputs={
                            "row_label": label,
                            "numerator": numerator,
                            "denominator": denominator,
                            "total_numerator": total_numerator,
                            "total_ratio": total_ratio,
                            "ratio_column": table.column_labels[ratio_index],
                            "numerator_column": table.column_labels[numerator_index],
                            "denominator_source": "合计行金额与合计比例",
                            "case_pattern": "row_proportion_recalculation",
                        },
                        locations=locations,
                    ))
        return checks

    @staticmethod
    def _is_disclosure_proportion_label(label: str) -> bool:
        compact = normalize_label(label)
        return (
            "占" in compact
            and any(term in compact for term in ("比例", "比重"))
            and any(term in compact for term in ("合计数", "总额", "余额合计", "期末"))
        )

    @staticmethod
    def _proportion_numerator_column(
        table: FinancialTable,
        ratio_index: int,
        total_index: int,
    ) -> int | None:
        candidates: list[int] = []
        for index in range(1, ratio_index):
            if _amount(table, total_index, index) is None:
                continue
            if not any(
                _amount(table, row_index, index) is not None
                for row_index in range(1, total_index)
            ):
                continue
            candidates.append(index)
        if not candidates:
            return None

        def score(index: int) -> tuple[int, int]:
            label = normalize_label(table.column_labels[index])
            preferred = sum(
                1 for term in ("合计", "总额", "余额", "期末", "金额", "数")
                if term in label
            )
            # The amount immediately preceding the ratio is normally the
            # table's combined balance; use the rightmost candidate as the
            # deterministic tie-breaker.
            return preferred, index

        return max(candidates, key=score)

    def calibrated_reconciliation_checks(
        self,
        tables: list[FinancialTable],
        facts: list[FinancialFact],
    ) -> list[AuditCheck]:
        """Run reusable checks learned from reviewer-confirmed financial cases."""
        checks: list[AuditCheck] = []
        checks.extend(self._bad_debt_reconciliation(facts))
        checks.extend(self._depreciation_reconciliation(facts))
        checks.extend(self._lease_cash_reconciliation(facts))
        checks.extend(self._associate_investment_reconciliation(facts))
        checks.extend(self._minor_associate_total_reconciliation(facts))
        checks.extend(self._nonrecurring_profit_reconciliation(facts))
        return checks

    @staticmethod
    def _bad_debt_reconciliation(facts: list[FinancialFact]) -> list[AuditCheck]:
        provision = next((
            fact for fact in facts
            if "坏账准备" in fact.location.table_name
            and "应收账款坏账准备" in fact.raw_name
            and "计提" in fact.location.column_label
        ), None)
        recovery = next((
            fact for fact in facts
            if provision is not None
            and fact.location.row_id == provision.location.row_id
            and any(term in fact.location.column_label for term in ("收回", "转回"))
        ), None)
        loss = next((
            fact for fact in facts
            if "应收账款坏账损失" in fact.canonical_name
            and ("信用减值损失" in fact.location.table_name or "损失发生额" in fact.location.column_label)
        ), None)
        if provision is None or recovery is None or loss is None:
            return []
        calculated = -(provision.value - recovery.value)
        difference = loss.value - calculated
        status = "passed" if close_enough(loss.value, calculated) else "failed"
        return [_check(
            "BAD-DEBT-PROVISION-RECONCILIATION", status,
            "none" if status == "passed" else "high", "专项跨表勾稽",
            ("已核对无误：" if status == "passed" else "应收账款坏账计提与信用减值损失不一致"),
            f"本期计提 {decimal_text(provision.value)}，收回或转回 {decimal_text(recovery.value)}，"
            f"复算损失发生额 {decimal_text(calculated)}；文档列示 {decimal_text(loss.value)}，"
            f"差异 {decimal_text(difference)}。",
            "核对坏账准备计提、收回/转回和信用减值损失取数，统一符号及金额。" if status != "passed" else "无需修改。",
            formula="信用减值损失 = -(坏账准备本期计提 - 收回或转回)",
            reported_value=loss.value, calculated_value=calculated, difference=difference,
            inputs={
                "provision": provision.value,
                "recovery": recovery.value,
                "case_pattern": "bad_debt_provision_reconciliation",
            },
            locations=[provision.location, recovery.location, loss.location],
        )]

    @staticmethod
    def _depreciation_reconciliation(facts: list[FinancialFact]) -> list[AuditCheck]:
        def component(section_term: str) -> FinancialFact | None:
            candidates = [
                fact for fact in facts
                if section_term in fact.location.table_name
                and "计提" in normalize_label(fact.raw_name)
                and normalize_label(fact.location.column_label).endswith("合计")
            ]
            return candidates[0] if candidates else None

        fixed = component("固定资产")
        right_of_use = component("使用权资产")
        total = next((
            fact for fact in facts
            if "现金流量表补充资料" in fact.location.table_name
            and "固定资产折旧" in fact.raw_name
            and "使用权资产折旧" in fact.raw_name
        ), None)
        if fixed is None or right_of_use is None or total is None:
            return []
        calculated = fixed.value + right_of_use.value
        difference = total.value - calculated
        status = "passed" if close_enough(total.value, calculated) else "failed"
        return [_check(
            "DEPRECIATION-RECONCILIATION", status,
            "none" if status == "passed" else "high", "专项跨表勾稽",
            ("已核对无误：" if status == "passed" else "现金流补充资料折旧金额不一致"),
            f"固定资产折旧 {decimal_text(fixed.value)} + 使用权资产折旧 {decimal_text(right_of_use.value)} "
            f"= {decimal_text(calculated)}；现金流量表补充资料列示 {decimal_text(total.value)}，"
            f"差异 {decimal_text(difference)}。",
            "核对固定资产及使用权资产本期计提折旧，并同步修正现金流量表补充资料。" if status != "passed" else "无需修改。",
            formula="固定资产折旧 + 使用权资产折旧 = 现金流量表补充资料折旧",
            reported_value=total.value, calculated_value=calculated, difference=difference,
            inputs={
                "fixed_asset_depreciation": fixed.value,
                "right_of_use_depreciation": right_of_use.value,
                "case_pattern": "depreciation_reconciliation",
            },
            locations=[fixed.location, right_of_use.location, total.location],
        )]

    @staticmethod
    def _lease_cash_reconciliation(facts: list[FinancialFact]) -> list[AuditCheck]:
        disclosed = next((
            fact for fact in facts
            if normalize_label(fact.raw_name) == "租赁负债"
            and "支付其他与筹资活动有关的现金" in fact.location.table_name
        ), None)
        reference = next((
            fact for fact in facts
            if "偿还租赁负债本金和利息所支付的现金" in fact.raw_name
        ), None)
        if disclosed is None or reference is None:
            return []
        difference = disclosed.value - reference.value
        status = "passed" if close_enough(disclosed.value, reference.value) else "failed"
        return [_check(
            "LEASE-CASHFLOW-RECONCILIATION", status,
            "none" if status == "passed" else "high", "专项跨表勾稽",
            ("已核对无误：" if status == "passed" else "租赁负债现金流披露不一致"),
            f"支付其他与筹资活动有关的现金列示 {decimal_text(disclosed.value)}，"
            f"租赁附注“偿还租赁负债本金和利息”列示 {decimal_text(reference.value)}，"
            f"差异 {decimal_text(difference)}。",
            "统一租赁负债现金流出取数，并核对本金、利息及筹资活动分类。" if status != "passed" else "无需修改。",
            formula="支付租赁负债现金 = 偿还租赁负债本金和利息所支付的现金",
            reported_value=disclosed.value, calculated_value=reference.value, difference=difference,
            inputs={"case_pattern": "lease_liability_cashflow_reconciliation"},
            locations=[disclosed.location, reference.location],
        )]

    @staticmethod
    def _associate_investment_reconciliation(facts: list[FinancialFact]) -> list[AuditCheck]:
        long_term = [
            fact for fact in facts
            if "长期股权投资" in fact.location.table_name
            and any(term in fact.raw_name for term in ("公司", "企业"))
        ]
        important = [
            fact for fact in facts
            if "重要的合营企业或联营企业" in fact.location.table_name
            and "不重要" not in fact.location.table_name
            and fact.raw_name in {
                "按持股比例计算的净资产份额",
                "对联营企业权益投资的账面价值",
            }
        ]
        checks: list[AuditCheck] = []
        seen: set[tuple[str, str]] = set()
        for fact in long_term:
            entity = normalize_label(fact.raw_name)
            if not entity or not fact.period:
                continue
            related = [
                item for item in important
                if entity in normalize_label(item.location.column_label)
                and item.period == fact.period
            ]
            if not related:
                continue
            key = (entity, fact.period)
            if key in seen:
                continue
            seen.add(key)
            book_values = [item for item in related if "账面价值" in item.raw_name]
            if not book_values:
                continue
            book = book_values[0]
            share_values = [
                item for item in related
                if "净资产份额" in item.raw_name
                and abs(item.value - book.value) <= Decimal("0.01")
            ]
            values = [fact, book, *share_values]
            minimum = min(item.value for item in values)
            maximum = max(item.value for item in values)
            difference = maximum - minimum
            status = "passed" if difference == 0 else "failed"
            pattern = "rounding_difference" if difference <= Decimal("0.01") else "long_term_investment_repeated_amount"
            checks.append(_check(
                "ASSOCIATE-INVESTMENT-RECONCILIATION", status,
                "none" if status == "passed" else ("low" if difference <= Decimal("0.01") else "high"),
                "专项跨表勾稽",
                ("已核对无误：" if status == "passed" else "联营企业投资账面价值重复披露不一致：") + fact.raw_name,
                "、".join(
                    f"{item.location.table_name}列示 {decimal_text(item.value)}"
                    for item in values
                ) + f"；最大差异 {decimal_text(difference)}。",
                "统一长期股权投资明细、净资产份额和权益投资账面价值的尾差。" if status != "passed" else "无需修改。",
                formula="同一联营企业、同一期间的投资账面价值重复披露应一致",
                reported_value=maximum, calculated_value=minimum, difference=difference,
                inputs={"entity": fact.raw_name, "period": fact.period, "case_pattern": pattern},
                locations=[item.location for item in values],
            ))
        return checks

    @staticmethod
    def _minor_associate_total_reconciliation(facts: list[FinancialFact]) -> list[AuditCheck]:
        summary = next((
            fact for fact in facts
            if "不重要的合营企业和联营企业" in fact.location.table_name
            and normalize_label(fact.raw_name) == "投资账面价值合计"
        ), None)
        if summary is None:
            return []
        important_columns = [
            normalize_label(fact.location.column_label)
            for fact in facts
            if "重要的合营企业或联营企业" in fact.location.table_name
            and "不重要" not in fact.location.table_name
        ]
        details = [
            fact for fact in facts
            if "长期股权投资" in fact.location.table_name
            and fact.statement_scope != "parent"
            and fact.period == summary.period
            and any(term in fact.raw_name for term in ("公司", "企业"))
            and "减值准备" not in fact.location.column_label
            and "余额" in fact.location.column_label
            and not any(normalize_label(fact.raw_name) in column for column in important_columns)
        ]
        if not details:
            return []
        calculated = sum((fact.value for fact in details), Decimal(0))
        difference = summary.value - calculated
        status = "passed" if close_enough(summary.value, calculated) else "failed"
        return [_check(
            "MINOR-ASSOCIATE-TOTAL-RECONCILIATION", status,
            "none" if status == "passed" else "high", "专项跨表勾稽",
            ("已核对无误：" if status == "passed" else "不重要联营企业投资账面价值合计不一致"),
            f"长期股权投资明细中不重要联营企业合计 {decimal_text(calculated)}，"
            f"汇总财务信息列示 {decimal_text(summary.value)}，差异 {decimal_text(difference)}。",
            "核对不重要联营企业范围及各主体期末账面价值后修正合计。" if status != "passed" else "无需修改。",
            formula="不重要联营企业各期末账面价值之和 = 投资账面价值合计",
            reported_value=summary.value, calculated_value=calculated, difference=difference,
            inputs={"case_pattern": "long_term_investment_detail_total", "detail_count": len(details)},
            locations=[*[fact.location for fact in details], summary.location],
        )]

    @staticmethod
    def _nonrecurring_profit_reconciliation(facts: list[FinancialFact]) -> list[AuditCheck]:
        relevant = [fact for fact in facts if "非经常性损益明细" in fact.location.table_name]
        after_tax = next((fact for fact in relevant if "扣除所得税后非经常性损益合计" in fact.raw_name), None)
        minority = next((fact for fact in relevant if "少数股东损益影响数" in fact.raw_name), None)
        parent = next((
            fact for fact in relevant
            if "归属于母公司所有者" in fact.raw_name and "非经常性损益" in fact.raw_name
        ), None)
        if after_tax is None or minority is None or parent is None:
            return []
        calculated = after_tax.value - minority.value
        difference = parent.value - calculated
        status = "passed" if close_enough(parent.value, calculated) else "failed"
        return [_check(
            "NONRECURRING-PROFIT-RECONCILIATION", status,
            "none" if status == "passed" else "high", "非经常性损益勾稽",
            ("已核对无误：" if status == "passed" else "归母非经常性损益金额不勾稽"),
            f"税后非经常性损益 {decimal_text(after_tax.value)} - 少数股东损益影响 "
            f"{decimal_text(minority.value)} = {decimal_text(calculated)}；归母金额列示 "
            f"{decimal_text(parent.value)}，差异 {decimal_text(difference)}。",
            "补齐税前合计和所得税影响后，复核税后合计、少数股东影响与归母金额。" if status != "passed" else "无需修改。",
            formula="归母非经常性损益 = 税后非经常性损益合计 - 少数股东损益影响数",
            reported_value=parent.value, calculated_value=calculated, difference=difference,
            inputs={"case_pattern": "detail_total_reconciliation"},
            locations=[after_tax.location, minority.location, parent.location],
        )]

    def authoritative_metric_checks(
        self,
        document_tables: list[FinancialTable],
        spreadsheet_tables: list[FinancialTable],
    ) -> list[AuditCheck]:
        """Reconcile every ROE/EPS cell without crossing profit-basis axes.

        The note table separates ordinary profit from profit after non-recurring
        items.  The workbook usually separates the current period from the
        prior period.  A prior-period value is never a valid substitute for a
        deducted-profit value; when the workbook lacks an explicitly labelled
        deducted metric, the result is a traceable manual-review item.
        """
        note = next((table for table in document_tables if "净资产收益率及每股收益" in table.name), None)
        workbook = next((table for table in spreadsheet_tables if normalize_label(table.name) == "合并利润表"), None)
        if note is None or workbook is None:
            return []

        ordinary_row = next((
            index for index, row in enumerate(note.rows)
            if row and "归属于公司普通股股东的净利润" in row[0]
            and "扣除非经常" not in row[0]
        ), None)
        deducted_row = next((
            index for index, row in enumerate(note.rows)
            if row and "扣除非经常" in row[0]
        ), None)
        roe_column = next((index for index, label in enumerate(note.column_labels) if "净资产收益率" in label), None)
        basic_column = next((index for index, label in enumerate(note.column_labels) if "基本每股收益" in label), None)
        diluted_column = next((index for index, label in enumerate(note.column_labels) if "稀释每股收益" in label), None)
        if ordinary_row is None or roe_column is None or basic_column is None or diluted_column is None:
            return []

        def row_label(index: int | None) -> str:
            return normalize_label(workbook.rows[index][0]) if index is not None and workbook.rows[index] else ""

        def find_exact(label: str) -> int | None:
            target = normalize_label(label)
            return next((index for index, row in enumerate(workbook.rows) if row and row_label(index) == target), None)

        def find_deducted(label: str) -> int | None:
            return next((
                index for index, row in enumerate(workbook.rows)
                if row and label in row_label(index)
                and any(term in row_label(index) for term in ("扣非", "扣除非经常性损益", "非经常性损益后"))
            ), None)

        ordinary_basic_row = find_exact("基本每股收益")
        ordinary_diluted_row = find_exact("稀释每股收益")
        deducted_basic_row = find_deducted("基本每股收益")
        deducted_diluted_row = find_deducted("稀释每股收益")
        deducted_roe_row = next((
            index for index, row in enumerate(workbook.rows)
            if row and "净资产收益率" in row_label(index)
            and any(term in row_label(index) for term in ("扣非", "扣除非经常性损益", "非经常性损益后"))
        ), None)
        net_profit_row = next((
            index for index, row in enumerate(workbook.rows)
            if row and "归属于母公司" in row_label(index) and "净利润" in row_label(index)
        ), None)
        average_row = find_exact("平均净资产")

        def current_column(row_indexes: list[int | None]) -> int | None:
            valid_rows = [index for index in row_indexes if index is not None]
            candidates = [
                column for column in range(1, max((len(row) for row in workbook.rows), default=0))
                if any(_amount(workbook, row, column) is not None for row in valid_rows)
            ]
            if not candidates:
                return None
            labelled: list[tuple[int, int]] = []
            for column in candidates:
                label = workbook.column_labels[column] if column < len(workbook.column_labels) else ""
                years = [int(value) for value in re.findall(r"20\d{2}", label)]
                if years:
                    labelled.append((max(years), column))
            return max(labelled, key=lambda item: (item[0], item[1]))[1] if labelled else min(candidates)

        source_column = current_column([ordinary_basic_row, ordinary_diluted_row, net_profit_row, average_row])
        ordinary_roe_source: tuple[Decimal, list[SourceLocation], str, Decimal] | None = None
        if source_column is not None and net_profit_row is not None and average_row is not None:
            net_profit = _amount(workbook, net_profit_row, source_column)
            average_net_assets = _amount(workbook, average_row, source_column)
            if net_profit is not None and average_net_assets not in (None, Decimal(0)):
                ordinary_roe_source = (
                    net_profit / average_net_assets,
                    _locations(workbook, [(net_profit_row, source_column), (average_row, source_column)]),
                    "Excel 归母净利润 ÷ 平均净资产",
                    Decimal(100),
                )

        def metric_source(
            metric: str,
            row_index: int | None,
            *,
            is_rate: bool = False,
            derived: tuple[Decimal, list[SourceLocation], str, Decimal] | None = None,
        ) -> tuple[Decimal, list[SourceLocation], str, Decimal] | None:
            if derived is not None:
                return derived
            if row_index is None:
                return None
            column = current_column([row_index])
            if column is None:
                return None
            cell = _cell(workbook, row_index, column)
            if cell is None:
                return None
            if is_rate and cell.is_percentage:
                value = cell.normalized_value
                factor = Decimal(1)
            else:
                value = _amount(workbook, row_index, column)
                factor = Decimal(100) if is_rate else Decimal(1)
            if value is None:
                return None
            return value, [cell.location], f"Excel {metric}", factor

        metrics: list[tuple[int | None, int, str, bool, tuple[Decimal, list[SourceLocation], str, Decimal] | None]] = [
            (ordinary_row, roe_column, "加权平均净资产收益率", True, ordinary_roe_source),
            (ordinary_row, basic_column, "基本每股收益", False, metric_source("基本每股收益", ordinary_basic_row)),
            (ordinary_row, diluted_column, "稀释每股收益", False, metric_source("稀释每股收益", ordinary_diluted_row)),
            (deducted_row, roe_column, "扣非后加权平均净资产收益率", True, metric_source("扣非后加权平均净资产收益率", deducted_roe_row, is_rate=True)),
            (deducted_row, basic_column, "扣非后基本每股收益", False, metric_source("扣非后基本每股收益", deducted_basic_row)),
            (deducted_row, diluted_column, "扣非后稀释每股收益", False, metric_source("扣非后稀释每股收益", deducted_diluted_row)),
        ]
        checks: list[AuditCheck] = []
        for doc_row, doc_column, metric, is_rate, source in metrics:
            if doc_row is None:
                continue
            reported = _percentage(note, doc_row, doc_column) if is_rate else _amount(note, doc_row, doc_column)
            if reported is None:
                continue
            if source is None:
                checks.append(_check(
                    "AUTHORITATIVE-ROE-EPS-SOURCE-MISSING", "needs_review", "medium", "文档与 Excel 勾稽",
                    f"Excel 权威底稿缺少对应数据：{metric}",
                    f"文档列示 {decimal_text(reported)}，但上传的 Excel 未找到明确标注“{metric}”的同口径、同期间数据。"
                    "未使用上年期间或其他口径数据代替，因此当前不能判定该项是否一致。",
                    "补充同一报告期、同一合并口径的扣非计算底稿，或人工核对归母净利润、扣非金额、平均净资产和股本后确认。",
                    formula="文档指标 = Excel 同口径权威底稿指标（来源缺失）",
                    reported_value=reported,
                    inputs={"metric": metric, "source_status": "missing", "case_pattern": "negative_value_range_review"},
                    locations=_locations(note, [(doc_row, doc_column)]),
                    source_sufficient=False,
                ))
                continue
            source_value, source_locations, source_label, factor = source
            calculated = (source_value * factor).quantize(CENT, rounding=ROUND_HALF_UP)
            difference = reported - calculated
            status = "passed" if close_enough(reported, calculated) else "failed"
            checks.append(_check(
                "AUTHORITATIVE-ROE-EPS-RECONCILIATION", status,
                "none" if status == "passed" else "high", "文档与 Excel 勾稽",
                ("已核对无误：" if status == "passed" else "文档与 Excel 计算底稿不一致：") + metric,
                f"文档列示 {decimal_text(reported)}，{source_label}计算值为 {decimal_text(calculated)}，"
                f"差异 {decimal_text(difference)}。",
                "以经确认的 Excel 计算底稿为准，复核归母净利润、扣非金额、加权平均净资产和股本后修正文档。" if status != "passed" else "无需修改。",
                formula=("文档 ROE = Excel 归母净利润 ÷ 平均净资产" if is_rate else "文档 EPS = Excel 同口径每股收益"),
                reported_value=reported, calculated_value=calculated, difference=difference,
                inputs={"metric": metric, "case_pattern": "negative_value_range_review"},
                locations=_locations(note, [(doc_row, doc_column)]) + source_locations,
            ))
        return checks

    def simple_total_checks(self, tables: list[FinancialTable]) -> list[AuditCheck]:
        checks: list[AuditCheck] = []
        for table in tables:
            total_positions = [
                index for index, row in enumerate(table.rows)
                if row and normalize_label(row[0]) in {"合计", "总计"}
            ]
            if len(total_positions) != 1 or total_positions[0] != len(table.rows) - 1:
                continue
            total_index = total_positions[0]
            detail_rows = table.rows[1:total_index]
            if (
                not 2 <= len(detail_rows) <= 30
                or any(normalize_label(row[0]).startswith("其中") for row in detail_rows if row)
                or any(normalize_label(row[0]) in {"小计", "总计", "合计"} for row in detail_rows if row)
            ):
                continue
            for column_index in range(1, len(table.rows[total_index])):
                if column_index < len(table.column_labels) and any(term in table.column_labels[column_index] for term in ("比例", "率", "说明", "原因")):
                    continue
                reported = _amount(table, total_index, column_index)
                values = [_amount(table, row_index, column_index) for row_index in range(1, total_index)]
                if reported is None or any(value is None for value in values):
                    continue
                calculated = Decimal(0)
                for row_index, value in enumerate(values, start=1):
                    label = normalize_label(table.rows[row_index][0])
                    assert value is not None
                    if label.startswith("减"):
                        calculated -= abs(value)
                    elif "非经常性损益" in table.name and "少数股东权益影响额" in label:
                        calculated -= value
                    else:
                        calculated += value
                difference = reported - calculated
                status = "passed" if close_enough(reported, calculated) else "failed"
                column_label = table.column_labels[column_index]
                checks.append(_check(
                    "SIMPLE-TOTAL", status, "none" if status == "passed" else "high", "合计",
                    ("已核对无误：" if status == "passed" else "明细合计不一致：") + f"{table.name}（{column_label}）",
                    f"明细 Decimal 合计 {decimal_text(calculated)}，表内合计 {decimal_text(reported)}，差异 {decimal_text(difference)}。",
                    "逐项核对明细、减项符号和合计公式。" if status != "passed" else "无需修改。",
                    formula="明细项目代数和 = 合计",
                    reported_value=reported, calculated_value=calculated, difference=difference,
                    inputs={
                        **{f"row_{index}": value for index, value in enumerate(values, start=1)},
                        **(
                            {"case_pattern": "subtotal_reconciliation"}
                            if "其他应收款" in table.name else {}
                        ),
                    },
                    locations=_locations(table, [(row, column_index) for row in range(1, total_index + 1)]),
                ))
        return checks

    def movement_checks(self, tables: list[FinancialTable]) -> list[AuditCheck]:
        checks: list[AuditCheck] = []
        for table in tables:
            if not table.rows:
                continue
            opening = self._rollforward_balance_column(table.column_labels, OPENING_BALANCE_TERMS)
            closing = self._rollforward_balance_column(
                table.column_labels,
                CLOSING_BALANCE_TERMS,
                after=opening,
            )
            if opening is None or closing is None or closing - opening < 2:
                continue
            candidate_indexes = list(range(opening + 1, closing))
            combined_labels = self._movement_column_labels(table, candidate_indexes)
            movement_indexes = [
                index for index in candidate_indexes
                if not self._is_period_balance_column(combined_labels[index])
            ]
            if not movement_indexes:
                continue
            if not any(any(term in label for term in ("增加", "减少", "计提", "转回", "核销", "处置")) for label in combined_labels.values()):
                continue
            tracks_carrying_value = any(
                "账面价值" in normalize_label(table.column_labels[index])
                for index in (opening, closing)
            )
            for row_index in range(1, len(table.rows)):
                row = table.rows[row_index]
                if not row or not row[0].strip():
                    continue
                opening_value = _amount(table, row_index, opening)
                closing_value = _amount(table, row_index, closing)
                movements = {index: _amount_or_zero(table, row_index, index) for index in movement_indexes}
                if opening_value is None or closing_value is None or any(value is None for value in movements.values()):
                    continue
                calculated = opening_value
                formula_parts = ["期初"]
                for index, value in movements.items():
                    assert value is not None
                    label = combined_labels[index]
                    subtractive = (
                        any(term in label for term in ("减少", "收回", "转回", "核销", "处置", "股利", "转出", "出售", "摊销"))
                        or tracks_carrying_value and "计提减值准备" in normalize_label(label)
                    )
                    if subtractive and value >= 0:
                        calculated -= value
                        formula_parts.append(f"- {label or f'第{index + 1}列'}")
                    else:
                        calculated += value
                        formula_parts.append(f"+ {label or f'第{index + 1}列'}")
                difference = closing_value - calculated
                status = "passed" if close_enough(closing_value, calculated) else "failed"
                label = row[0].strip()
                checks.append(_check(
                    "MOVEMENT-ROLLFORWARD", status, "none" if status == "passed" else "high", "正负号/变动表",
                    ("已核对无误：" if status == "passed" else "变动表不闭合：") + label,
                    f"符号感知复算期末应为 {decimal_text(calculated)}，表内列示 {decimal_text(closing_value)}，差异 {decimal_text(difference)}。减少项已为负数时直接代数相加，未重复减除。",
                    "核对期初、增加、减少、其他变动和期末底稿。" if status != "passed" else "无需修改。",
                    formula=" ".join(formula_parts) + " = 期末",
                    reported_value=closing_value, calculated_value=calculated, difference=difference,
                    inputs={"opening": opening_value, **{combined_labels[index] or f"column_{index}": value for index, value in movements.items()}},
                    locations=_locations(table, [(row_index, opening), *[(row_index, index) for index in movement_indexes], (row_index, closing)]),
                ))
        return checks

    @staticmethod
    def _rollforward_balance_column(
        labels: list[str],
        period_terms: tuple[str, ...],
        *,
        after: int | None = None,
    ) -> int | None:
        candidates = [
            index for index, label in enumerate(labels)
            if (after is None or index > after)
            and any(term in normalize_label(label) for term in period_terms)
        ]
        if not candidates:
            return None

        def balance_rank(index: int) -> tuple[int, int]:
            label = normalize_label(labels[index])
            if "账面价值" in label or "账面净值" in label:
                return 0, index
            if "账面余额" in label or "账面原值" in label:
                return 1, index
            if any(term in label for term in BALANCE_ALLOWANCE_TERMS):
                return 3, index
            return 2, index

        return min(candidates, key=balance_rank)

    @staticmethod
    def _is_period_balance_column(label: str) -> bool:
        compact = normalize_label(label)
        return any(
            term in compact
            for term in (*OPENING_BALANCE_TERMS, *CLOSING_BALANCE_TERMS)
        )

    @staticmethod
    def _movement_column_labels(table: FinancialTable, indexes: list[int]) -> dict[int, str]:
        first_header = table.rows[0]
        second_header = table.rows[1] if len(table.rows) > 1 and not table.rows[1][0].strip() else []
        carried = ""
        values: dict[int, str] = {}
        for index in range(len(first_header)):
            if first_header[index].strip():
                carried = first_header[index].strip()
            if index not in indexes:
                continue
            sub = second_header[index].strip() if index < len(second_header) else ""
            values[index] = " / ".join(part for part in (carried, sub) if part)
        return values

    def cross_table_checks(self, facts: list[FinancialFact]) -> list[AuditCheck]:
        checks: list[AuditCheck] = []
        for fact_name in MAJOR_CROSS_TABLE_FACTS:
            statement = [
                fact for fact in facts
                if fact.canonical_name == fact_name and fact.statement_scope == "consolidated" and fact.unit != "%"
            ]
            references = [
                fact for fact in facts
                if fact.canonical_name == fact_name and fact.statement_scope in {"note", "disclosure"} and fact.unit != "%"
                and (
                    fact_name in fact.location.table_name
                    or any(term in fact.location.table_name for term in ("主要会计数据", "主营业务分析", "资产构成重大变动"))
                )
            ]
            for source in statement[:2]:
                same_period = [item for item in references if item.period == source.period and item.location.cell_id != source.location.cell_id]
                if not same_period:
                    continue
                matches = [item for item in same_period if close_enough(item.value, source.value)]
                if matches:
                    item = matches[0]
                    checks.append(_check(
                        "CROSS-TABLE-FACT", "passed", "none", "跨表勾稽", f"已核对无误：{fact_name}跨表一致",
                        f"合并报表与{item.location.table_name}列示金额一致，均为 {decimal_text(source.value)}。",
                        "无需修改。",
                        formula="主表金额 = 正文/附注金额",
                        reported_value=item.value, calculated_value=source.value, difference=item.value - source.value,
                        locations=[source.location, item.location],
                    ))
                    continue
                item = same_period[0]
                difference = item.value - source.value
                checks.append(_check(
                    "CROSS-TABLE-FACT", "needs_review", "medium", "正文表格/跨表勾稽", f"跨表取数需核实：{fact_name}",
                    f"合并报表列示 {decimal_text(source.value)}，{item.location.table_name}列示 {decimal_text(item.value)}，差异 {decimal_text(difference)}。系统不自行判断两处统计口径是否相同。",
                    "核实合并/母公司、受限资金、重分类及统计口径；口径一致时统一金额，口径不同时补充调节说明。",
                    formula="主表金额 与 正文/附注金额比较",
                    reported_value=item.value, calculated_value=source.value, difference=difference,
                    locations=[source.location, item.location], source_sufficient=False,
                ))
        return checks

    def required_amount_checks(self, tables: list[FinancialTable]) -> list[AuditCheck]:
        """Check mandatory financial-note rows that are present but have no amount.

        A blank amount is materially different from a zero amount.  This rule is
        deliberately limited to recurring disclosure rows where the reviewer
        confirmed that an amount is required; it does not infer values from prose.
        """
        required_terms = (
            "扣除所得税前非经常性损益合计",
            "减：所得税影响金额",
        )
        checks: list[AuditCheck] = []
        for table in tables:
            for row_index, row in enumerate(table.rows[1:], start=1):
                if not row or not row[0].strip():
                    continue
                label = normalize_label(row[0])
                term = next((item for item in required_terms if normalize_label(item) in label), None)
                if term is None:
                    continue
                amount_indexes = [
                    index for index, column in enumerate(table.column_labels)
                    if index > 0 and not any(word in column for word in ("比例", "率", "说明", "原因"))
                ]
                if not amount_indexes:
                    continue
                present = [_amount(table, row_index, index) for index in amount_indexes]
                if any(value is not None for value in present):
                    continue
                locations = _locations(table, [(row_index, index) for index in amount_indexes])
                checks.append(_check(
                    "REQUIRED-AMOUNT-MISSING", "failed", "high", "财务披露完整性",
                    f"必填金额缺失：{row[0].strip()}",
                    f"表格出现“{term}”项目，但对应金额栏为空；空白不能等同于 0，无法与非经常性损益合计勾稽。",
                    "补充经复核的金额；如确实为零，明确列示 0.00，并同步复核相关合计和所得税影响。",
                    formula="必填披露项目金额不得为空",
                    inputs={"required_item": term, "table": table.name},
                    locations=locations,
                ))
        return checks

    def repeated_fact_checks(self, facts: list[FinancialFact]) -> list[AuditCheck]:
        """Surface same-period repeated facts with different values for review.

        Notes frequently repeat an amount in a primary statement, a movement
        schedule and a summary.  This check does not assume that every repeat is
        an error (parent/consolidated scopes may differ); it creates a traceable
        review item so the user can confirm the scope and period.
        """
        targets = (
            "长期股权投资", "权益法投资收益",
            "固定资产折旧", "使用权资产折旧", "偿还租赁负债本金和利息",
            "其他非流动金融资产", "应收账款坏账准备", "应收坏账损失发生额",
        )
        normalized_targets = {normalize_label(item): item for item in targets}
        grouped: dict[tuple[str, str, str], list[FinancialFact]] = {}
        for fact in facts:
            if fact.value is None or fact.unit == "%" or not fact.period:
                continue
            name = normalize_label(fact.canonical_name)
            target = normalized_targets.get(name)
            if target:
                scope = "note" if fact.statement_scope in {"note", "disclosure"} else fact.statement_scope
                grouped.setdefault((target, fact.period, scope), []).append(fact)
        checks: list[AuditCheck] = []
        for (target, period, _scope_name), items in grouped.items():
            distinct: list[FinancialFact] = []
            for item in items:
                if not any(close_enough(item.value, previous.value) for previous in distinct):
                    distinct.append(item)
            if len(distinct) < 2:
                continue
            left, right = distinct[0], distinct[1]
            difference = right.value - left.value
            period_label = {
                "current_period": "本期",
                "comparative_period": "上年同期",
                "current_end": "期末",
                "prior_year_end": "期初/上年末",
            }.get(period, period)
            checks.append(_check(
                "REPEATED-FACT-MISMATCH", "needs_review", "medium", "专项跨表勾稽",
                f"同一指标重复披露金额不一致：{target}（{period_label}）",
                f"检测到同一期间的重复披露值 {decimal_text(left.value)} 与 {decimal_text(right.value)}，差异 {decimal_text(difference)}；可能是合并范围、取数位置或尾差不同。",
                "核对两处原文的合并/母公司范围、期间、单位和正负号；口径一致时统一金额并保留勾稽说明。",
                formula="同一指标、同一期间、同一口径的重复披露应一致",
                reported_value=left.value, calculated_value=right.value, difference=difference,
                inputs={"metric": target, "period": period, "left_scope": left.statement_scope, "right_scope": right.statement_scope},
                locations=[left.location, right.location], source_sufficient=False,
            ))
        return checks


__all__ = ["FinancialFormulaEngine", "MAJOR_CROSS_TABLE_FACTS", "PERCENT_TOLERANCE"]
