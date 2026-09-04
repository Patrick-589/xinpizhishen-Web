from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Literal


FinancialSemantic = Literal["profit_loss", "cash_flow"]
PERCENT_QUANTUM = Decimal("0.01")


def decimal_value(value: Decimal | int | float | str) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("布尔值不能作为财务金额。")
    if isinstance(value, Decimal):
        result = value
    else:
        normalized = str(value).strip().replace(",", "")
        normalized = normalized.replace("−", "-").replace("—", "-").replace("－", "-")
        negative_parentheses = normalized.startswith("(") and normalized.endswith(")")
        normalized = normalized.strip("()")
        try:
            result = Decimal(normalized)
        except InvalidOperation as error:
            raise ValueError(f"无法解析财务金额：{value}") from error
        if negative_parentheses:
            result = -abs(result)
    if not result.is_finite():
        raise ValueError("财务金额必须是有限数值。")
    return Decimal(0) if result == 0 else result


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def format_financial_amount(value: Decimal) -> str:
    return f"{value.quantize(PERCENT_QUANTUM, rounding=ROUND_HALF_UP):,.2f}"


@dataclass(frozen=True)
class FinancialChange:
    current: Decimal
    previous: Decimal
    absolute_change: Decimal
    yoy_rate: Decimal | None
    raw_yoy_rate: Decimal | None
    change_type: str
    display_change_type: str
    display_change_text: str
    display_yoy_rate: Decimal | None
    semantic: FinancialSemantic

    def to_dict(self) -> dict[str, Any]:
        return {
            "current": _decimal_text(self.current),
            "previous": _decimal_text(self.previous),
            "absolute_change": _decimal_text(self.absolute_change),
            "yoy_rate": _decimal_text(self.yoy_rate),
            "raw_yoy_rate": _decimal_text(self.raw_yoy_rate),
            "change_type": self.change_type,
            "display_change_type": self.display_change_type,
            "display_change_text": self.display_change_text,
            "display_yoy_rate": _decimal_text(self.display_yoy_rate),
            "semantic": self.semantic,
        }


def calculate_financial_change(
    current: Decimal | int | float | str,
    previous: Decimal | int | float | str,
    *,
    semantic: FinancialSemantic = "profit_loss",
    label: str = "",
) -> FinancialChange:
    if semantic not in {"profit_loss", "cash_flow"}:
        raise ValueError(f"不支持的财务语义：{semantic}")

    current_value = decimal_value(current)
    previous_value = decimal_value(previous)
    absolute_change = current_value - previous_value
    raw_yoy_rate = None
    if previous_value != 0:
        raw_yoy_rate = (
            absolute_change / abs(previous_value) * Decimal(100)
        ).quantize(PERCENT_QUANTUM, rounding=ROUND_HALF_UP)

    prefix = label.strip()
    yoy_rate: Decimal | None = None
    display_yoy_rate: Decimal | None = None

    if previous_value == 0:
        if current_value == 0:
            change_type = "unchanged"
            display_change_type = "无变化"
            display_change_text = f"{prefix}无变化"
        else:
            change_type = "previous_zero"
            display_change_type = "上期为0，本期增加" if current_value > 0 else "上期为0，本期减少"
            display_change_text = f"{prefix}{display_change_type}"
    elif previous_value > 0 and current_value >= 0:
        yoy_rate = raw_yoy_rate
        display_yoy_rate = raw_yoy_rate
        if current_value > previous_value:
            change_type = "normal_growth"
            display_change_type = "同比增长"
            display_change_text = f"{prefix}同比增长 {abs(display_yoy_rate):.2f}%"
        elif current_value < previous_value:
            change_type = "normal_decline"
            display_change_type = "同比下降"
            display_change_text = f"{prefix}同比下降 {abs(display_yoy_rate):.2f}%"
        else:
            change_type = "unchanged"
            display_change_type = "金额未发生变化"
            display_change_text = f"{prefix}金额未发生变化"
    elif previous_value < 0 and current_value > 0:
        change_type = "negative_to_positive"
        if semantic == "cash_flow":
            display_change_type = "由净流出转为净流入"
        else:
            display_change_type = "由负转正"
        display_change_text = f"{prefix}{display_change_type}"
    elif previous_value > 0 and current_value < 0:
        change_type = "positive_to_negative"
        if semantic == "cash_flow":
            display_change_type = "由净流入转为净流出"
        else:
            display_change_type = "由正转负"
        display_change_text = f"{prefix}{display_change_type}"
    else:
        if abs(current_value) < abs(previous_value):
            change_type = "net_outflow_narrowed" if semantic == "cash_flow" else "loss_narrowed"
            display_change_type = "净流出收窄" if semantic == "cash_flow" else "亏损收窄"
        elif abs(current_value) > abs(previous_value):
            change_type = "net_outflow_expanded" if semantic == "cash_flow" else "loss_expanded"
            display_change_type = "净流出扩大" if semantic == "cash_flow" else "亏损扩大"
        else:
            change_type = "unchanged"
            display_change_type = "金额未发生变化"
        display_change_text = f"{prefix}{display_change_type}"

    return FinancialChange(
        current=current_value,
        previous=previous_value,
        absolute_change=absolute_change,
        yoy_rate=yoy_rate,
        raw_yoy_rate=raw_yoy_rate,
        change_type=change_type,
        display_change_type=display_change_type,
        display_change_text=display_change_text,
        display_yoy_rate=display_yoy_rate,
        semantic=semantic,
    )


__all__ = [
    "FinancialChange",
    "FinancialSemantic",
    "calculate_financial_change",
    "decimal_value",
    "format_financial_amount",
]
