from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP


ZERO = Decimal("0")
CENT = Decimal("0.01")
UNIT_FACTORS = {
    "元": Decimal("1"),
    "万元": Decimal("10000"),
    "亿元": Decimal("100000000"),
}
BLANK_VALUES = {"", "-", "--", "—", "－", "/", "不适用", "无", "nil", "n/a"}


def normalize_label(value: str) -> str:
    return re.sub(r"[\s：:（）()\[\]【】、,.，。]", "", str(value or "")).strip()


def parse_decimal(value: str | Decimal | int, *, blank_as_zero: bool = False) -> Decimal | None:
    if isinstance(value, Decimal):
        return value
    compact = str(value or "").strip().replace(" ", "")
    if compact.casefold() in BLANK_VALUES:
        return ZERO if blank_as_zero else None
    compact = compact.replace("−", "-").replace("—", "-").replace("－", "-")
    compact = compact.replace("，", ",").replace(",", "")
    compact = re.sub(r"(?:人民币)?(?:亿元|万元|元)(?:/股)?$", "", compact)
    compact = compact.rstrip("%％")
    negative_parentheses = compact.startswith("(") and compact.endswith(")")
    if negative_parentheses:
        compact = compact[1:-1]
    if not re.fullmatch(r"[+\-]?\d+(?:\.\d+)?", compact):
        return None
    try:
        number = Decimal(compact)
    except InvalidOperation:
        return None
    if negative_parentheses:
        number = -abs(number)
    return ZERO if number == ZERO else number


def detect_unit(*values: str) -> str:
    text = " ".join(str(value or "") for value in values)
    if "亿元" in text:
        return "亿元"
    if "万元" in text:
        return "万元"
    if re.search(r"(?:人民币)?元(?:[^/股]|$)", text):
        return "元"
    return ""


def to_base_amount(value: Decimal | None, unit: str) -> Decimal | None:
    if value is None:
        return None
    return value * UNIT_FACTORS.get(unit, Decimal("1"))


def decimal_text(value: Decimal | None, places: str = "0.01") -> str:
    if value is None:
        return "-"
    quantum = Decimal(places)
    return f"{value.quantize(quantum, rounding=ROUND_HALF_UP):,.{abs(quantum.as_tuple().exponent)}f}"


def close_enough(left: Decimal, right: Decimal, *, absolute: Decimal = CENT) -> bool:
    tolerance = max(absolute, abs(right) * Decimal("0.000000001"))
    return abs(left - right) <= tolerance


def percentage_difference(reported: Decimal, calculated: Decimal) -> Decimal:
    return abs(reported - calculated).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def is_order_of_magnitude_error(reported: Decimal, calculated: Decimal) -> bool:
    if reported == 0 or calculated == 0:
        return abs(calculated - reported) >= Decimal("0.1")
    ratio = abs(calculated / reported)
    return any(abs(ratio - factor) <= factor * Decimal("0.03") for factor in (Decimal(10), Decimal(100), Decimal(1000)))


__all__ = [
    "CENT",
    "ZERO",
    "close_enough",
    "decimal_text",
    "detect_unit",
    "is_order_of_magnitude_error",
    "normalize_label",
    "parse_decimal",
    "percentage_difference",
    "to_base_amount",
]
