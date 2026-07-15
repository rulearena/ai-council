from __future__ import annotations

from decimal import Decimal
import re
import unicodedata


_CHINESE_NUMBER = "零〇一二兩三四五六七八九十百千萬億壹貳參肆伍陸柒捌玖拾佰仟"
_ARABIC_NUMBER = r"[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?"
_ARABIC_UNIT = "十拾百佰千仟萬億"
_AMOUNT_ATOM = rf"(?:{_ARABIC_NUMBER}\s*[{_ARABIC_UNIT}]?|[{_CHINESE_NUMBER}]+)"
_AMOUNT_EXPRESSION = rf"{_AMOUNT_ATOM}(?:\s*{_AMOUNT_ATOM})*"
_CURRENCY_MARKER = r"(?:新臺幣|臺幣|TWD|NT\$|美元|美金|USD|\$)"
_TOKEN_BOUNDARY = rf"A-Za-z0-9_{_CHINESE_NUMBER}"
_MONEY_TOKEN = re.compile(
    rf"(?<![{_TOKEN_BOUNDARY}])"
    rf"(?P<prefix>{_CURRENCY_MARKER})?\s*"
    rf"(?P<expression>{_AMOUNT_EXPRESSION})\s*"
    rf"(?P<suffix>{_CURRENCY_MARKER}|元)?"
    rf"(?![{_TOKEN_BOUNDARY}])",
    re.IGNORECASE,
)
_AMOUNT_ATOM_TOKEN = re.compile(
    rf"(?P<arabic>{_ARABIC_NUMBER})\s*(?P<unit>[{_ARABIC_UNIT}])?|"
    rf"(?P<chinese>[{_CHINESE_NUMBER}]+)"
)
_PUNISHMENT_SEMANTIC = re.compile(
    r"判刑|判處|科刑|刑期|徒刑|拘役|緩刑|監禁|入監|褫奪公權|"
    r"宣告刑|應執行|應處"
)
_MONEY_PENALTY_SEMANTIC = re.compile(r"罰金|罰鍰|科處|處以")
_PENALTY_DURATION = re.compile(
    rf"(?<![{_TOKEN_BOUNDARY}])(?:{_ARABIC_NUMBER}|[{_CHINESE_NUMBER}]+)\s*"
    rf"(?:年|個月|月|日)(?![{_TOKEN_BOUNDARY}])"
)
_INHERENT_CONCRETE_PENALTY = re.compile(
    r"死刑|無期徒刑|終身監禁|終身徒刑|永久褫奪公權"
)

_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "壹": 1, "二": 2, "兩": 2, "貳": 2,
    "三": 3, "參": 3, "四": 4, "肆": 4, "五": 5, "伍": 5,
    "六": 6, "陸": 6, "七": 7, "柒": 7, "八": 8, "捌": 8,
    "九": 9, "玖": 9,
}
_SMALL_UNITS = {
    "十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000,
}
_LARGE_UNITS = {"萬": 10_000, "億": 100_000_000}
_UNITS = {**_SMALL_UNITS, **_LARGE_UNITS}


def evaluate_amount_expression(expression: str) -> Decimal:
    """Evaluate a complete Chinese/Arabic mixed amount expression."""
    normalized = unicodedata.normalize("NFKC", expression).strip()
    if not normalized:
        raise ValueError("Amount expression is empty")
    total = Decimal(0)
    cursor = 0
    for match in _AMOUNT_ATOM_TOKEN.finditer(normalized):
        if normalized[cursor:match.start()].strip():
            raise ValueError(f"Invalid amount expression: {expression}")
        if match.group("arabic") is not None:
            value = Decimal(match.group("arabic").replace(",", ""))
            unit = match.group("unit")
            total += value * Decimal(_UNITS.get(unit, 1))
        else:
            total += Decimal(_chinese_integer(match.group("chinese")))
        cursor = match.end()
    if cursor == 0 or normalized[cursor:].strip():
        raise ValueError(f"Invalid amount expression: {expression}")
    return total


def money_values(text: str) -> set[tuple[str, Decimal]]:
    """Extract complete amount expressions normalized as ``(currency, value)``."""
    normalized = unicodedata.normalize("NFKC", text)
    values: set[tuple[str, Decimal]] = set()
    for match in _MONEY_TOKEN.finditer(normalized):
        prefix = _currency_code(match.group("prefix"))
        suffix = _currency_code(match.group("suffix"))
        if prefix and suffix and prefix != suffix:
            raise ValueError("Conflicting currency markers in amount expression")
        expression = match.group("expression")
        if not prefix and not suffix and not re.search(r"[萬億]", expression):
            continue
        values.add((prefix or suffix or "TWD", evaluate_amount_expression(expression)))
    return values


def contains_concrete_penalty(text: str) -> bool:
    """Detect a concrete penalty across the complete visible structured output."""
    normalized = unicodedata.normalize("NFKC", text)
    if _INHERENT_CONCRETE_PENALTY.search(normalized):
        return True
    if _PUNISHMENT_SEMANTIC.search(normalized) and _PENALTY_DURATION.search(normalized):
        return True
    return bool(_MONEY_PENALTY_SEMANTIC.search(normalized) and money_values(normalized))


def _currency_code(marker: str | None) -> str | None:
    if marker is None:
        return None
    normalized = marker.upper()
    if normalized in {"美元", "美金", "USD", "$"}:
        return "USD"
    return "TWD"


def _chinese_integer(value: str) -> int:
    total = section = number = 0
    for character in value:
        if character in _DIGITS:
            number = _DIGITS[character]
        elif character in _SMALL_UNITS:
            section += (number or 1) * _SMALL_UNITS[character]
            number = 0
        elif character in _LARGE_UNITS:
            total += (section + number) * _LARGE_UNITS[character]
            section = number = 0
    return total + section + number
