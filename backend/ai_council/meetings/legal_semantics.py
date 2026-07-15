from __future__ import annotations

from decimal import Decimal
import re
import unicodedata


_CHINESE_NUMBER = "零〇一二兩三四五六七八九十百千萬億壹貳參肆伍陸柒捌玖拾佰仟"
_ARABIC_NUMBER = r"[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?"
_ARABIC_UNIT = "十拾百佰千仟萬億"
_AMOUNT_ATOM = rf"(?:{_ARABIC_NUMBER}\s*[{_ARABIC_UNIT}]?|[{_CHINESE_NUMBER}]+)"
_AMOUNT_EXPRESSION = rf"{_AMOUNT_ATOM}(?:\s*{_AMOUNT_ATOM})*"
_CURRENCY_ALIASES = {
    "TWD": ("新臺幣", "臺幣", "TWD", "NT$"),
    "USD": ("美元", "美金", "USD", "$"),
    "CNY": ("人民幣", "RMB", "CNY"),
    "JPY": ("日圓", "日元", "JPY"),
    "EUR": ("歐元", "EUR"),
    "GBP": ("英鎊", "GBP"),
    "HKD": ("港幣", "HKD"),
    "KRW": ("韓元", "韓圜", "KRW"),
}
_ALIAS_TO_CURRENCY = {
    alias.upper(): currency
    for currency, aliases in _CURRENCY_ALIASES.items()
    for alias in aliases
}
_KNOWN_CURRENCY_MARKERS = "|".join(
    re.escape(alias)
    for alias in sorted(_ALIAS_TO_CURRENCY, key=len, reverse=True)
)
_CURRENCY_MARKER = rf"(?:{_KNOWN_CURRENCY_MARKERS}|[A-Z]{{3}})"
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
    rf"(?P<arabic>{_ARABIC_NUMBER})|"
    rf"(?P<digit>[零〇一二兩三四五六七八九壹貳參肆伍陸柒捌玖])|"
    rf"(?P<unit>[{_ARABIC_UNIT}])"
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
    r"死刑|無期徒刑|"
    r"(?:(?:永久|終身|無限期).{0,8}(?:監禁|徒刑|褫奪公權|拘禁|入監)|"
    r"(?:監禁|徒刑|褫奪公權|拘禁|入監).{0,8}(?:永久|終身|無限期))"
)
_VISIBLE_FRAGMENT_SEPARATOR = re.compile(r"[。；;\n\r！？!?]+")

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


def evaluate_amount_expression(expression: str) -> Decimal:
    """Evaluate a complete Chinese/Arabic mixed amount expression."""
    normalized = unicodedata.normalize("NFKC", expression).strip()
    if not normalized:
        raise ValueError("Amount expression is empty")
    total = Decimal(0)
    group = Decimal(0)
    section = Decimal(0)
    number: Decimal | None = None
    previous_was_chinese_digit = False
    cursor = 0
    for match in _AMOUNT_ATOM_TOKEN.finditer(normalized):
        if normalized[cursor:match.start()].strip():
            raise ValueError(f"Invalid amount expression: {expression}")
        if match.group("arabic") is not None:
            if number is not None:
                raise ValueError(f"Invalid adjacent numbers in amount expression: {expression}")
            number = Decimal(match.group("arabic").replace(",", ""))
            previous_was_chinese_digit = False
        elif match.group("digit") is not None:
            digit = Decimal(_DIGITS[match.group("digit")])
            number = number * 10 + digit if previous_was_chinese_digit else digit
            previous_was_chinese_digit = True
        else:
            unit = match.group("unit")
            previous_was_chinese_digit = False
            if unit in _SMALL_UNITS:
                section += (number if number is not None else Decimal(1)) * _SMALL_UNITS[unit]
                number = None
            elif unit == "萬":
                section += number or Decimal(0)
                group += section * _LARGE_UNITS[unit]
                section = Decimal(0)
                number = None
            else:
                section += number or Decimal(0)
                total += (group + section) * _LARGE_UNITS[unit]
                group = section = Decimal(0)
                number = None
        cursor = match.end()
    if cursor == 0 or normalized[cursor:].strip():
        raise ValueError(f"Invalid amount expression: {expression}")
    return total + group + section + (number or Decimal(0))


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
    """Detect a concrete penalty within each visible field or sentence."""
    normalized = unicodedata.normalize("NFKC", text)
    for fragment in _VISIBLE_FRAGMENT_SEPARATOR.split(normalized):
        if _INHERENT_CONCRETE_PENALTY.search(fragment):
            return True
        if _PUNISHMENT_SEMANTIC.search(fragment) and _PENALTY_DURATION.search(fragment):
            return True
        if _MONEY_PENALTY_SEMANTIC.search(fragment) and money_values(fragment):
            return True
    return False


def _currency_code(marker: str | None) -> str | None:
    if marker is None:
        return None
    normalized = marker.upper()
    if normalized == "元":
        return "TWD"
    return _ALIAS_TO_CURRENCY.get(normalized, f"UNKNOWN:{normalized}")
