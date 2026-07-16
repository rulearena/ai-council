from __future__ import annotations

from decimal import Decimal
import re
import unicodedata


_CHINESE_NUMBER = "零〇一二兩三四五六七八九十百千萬億兆壹貳參肆伍陸柒捌玖拾佰仟"
_ARABIC_NUMBER = r"[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?"
_ARABIC_UNIT = "十拾百佰千仟萬億兆"
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
    "UNKNOWN:瑞士法郎": ("瑞士法郎",),
    "UNKNOWN:加元": ("加元",),
    "UNKNOWN:澳元": ("澳元",),
    "UNKNOWN:新加坡元": ("新加坡元",),
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
    rf"(?P<suffix>{_CURRENCY_MARKER}|元|圓)?"
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
_MONEY_PENALTY_SEMANTIC = re.compile(r"罰金|罰鍰|罰款|科處|處以")
_PENALTY_DURATION = re.compile(
    rf"(?<![{_TOKEN_BOUNDARY}])(?:{_ARABIC_NUMBER}|[{_CHINESE_NUMBER}]+)\s*"
    rf"(?:年|載|個月|月|日)(?![{_TOKEN_BOUNDARY}])"
)
_INHERENT_CONCRETE_PENALTY = re.compile(
    r"死刑|處死|無期徒刑|"
    r"(?:(?:永久|終身|無限期).{0,8}(?:監禁|徒刑|褫奪公權|拘禁|入監)|"
    r"(?:監禁|徒刑|褫奪公權|拘禁|入監).{0,8}(?:永久|終身|無限期))"
)
_VISIBLE_FRAGMENT_SEPARATOR = re.compile(r"[，,。.;；;\n\r！？!?]+")
_UNSUPPORTED_MAGNITUDE = re.compile(
    rf"(?<![{_TOKEN_BOUNDARY}])(?:{_ARABIC_NUMBER}|[{_CHINESE_NUMBER}]+)\s*"
    r"(?P<magnitude>[京垓秭穰溝澗正載])"
)
_NON_MONEY_QUANTITY_SUFFIX = re.compile(
    r"(?:股|人|份|件|戶|坪|平方公尺|公尺|平方公里|公斤|噸|筆)"
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
_LARGE_UNITS = {"萬": 10_000, "億": 100_000_000, "兆": 1_000_000_000_000}


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
            elif unit == "億":
                section += number or Decimal(0)
                total += (group + section) * _LARGE_UNITS[unit]
                group = section = Decimal(0)
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


def money_values(
    text: str,
    *,
    assume_money: bool = False,
) -> set[tuple[str, Decimal]]:
    """Extract complete amount expressions normalized as ``(currency, value)``."""
    normalized = unicodedata.normalize("NFKC", text)
    unsupported = _UNSUPPORTED_MAGNITUDE.search(normalized)
    if unsupported:
        raise ValueError(f"Unsupported magnitude: {unsupported.group('magnitude')}")
    values: set[tuple[str, Decimal]] = set()
    for match in _MONEY_TOKEN.finditer(normalized):
        if _NON_MONEY_QUANTITY_SUFFIX.match(normalized, match.end()):
            continue
        value = _money_value_from_match(match, assume_money=assume_money)
        if value is not None:
            values.add(value)
    return values


def parse_money_expression(
    text: str,
    *,
    assume_money: bool = False,
) -> tuple[str, Decimal]:
    """Parse one complete monetary field without accepting surrounding prose."""
    normalized = unicodedata.normalize("NFKC", text).strip()
    unsupported = _UNSUPPORTED_MAGNITUDE.search(normalized)
    if unsupported:
        raise ValueError(f"Unsupported magnitude: {unsupported.group('magnitude')}")
    match = _MONEY_TOKEN.fullmatch(normalized)
    if match is None:
        raise ValueError("Field must be one complete monetary expression")
    value = _money_value_from_match(match, assume_money=assume_money)
    if value is None:
        raise ValueError("Field must be one complete monetary expression")
    return value


def contains_concrete_penalty(visible: object) -> bool:
    """Validate clauses locally, with narrow cross-field value completion."""
    fields = [_visible_fragments(field) for field in _visible_fields(visible)]
    duration_semantic_fields: set[int] = set()
    money_semantic_fields: set[int] = set()
    pure_duration_fields: set[int] = set()
    pure_money_fields: set[int] = set()
    for field_index, fragments in enumerate(fields):
        previous_duration_semantic = False
        previous_money_semantic = False
        previous_pure_duration = False
        previous_pure_money = False
        for fragment in fragments:
            if _INHERENT_CONCRETE_PENALTY.search(fragment):
                return True
            has_duration_semantic = bool(_PUNISHMENT_SEMANTIC.search(fragment))
            has_money_semantic = bool(_MONEY_PENALTY_SEMANTIC.search(fragment))
            if previous_duration_semantic and _is_pure_duration(fragment):
                return True
            if previous_money_semantic and _is_pure_money(fragment):
                return True
            if previous_pure_duration and has_duration_semantic:
                return True
            if previous_pure_money and has_money_semantic:
                return True
            if has_duration_semantic:
                duration_semantic_fields.add(field_index)
            if has_money_semantic:
                money_semantic_fields.add(field_index)
            if has_duration_semantic and _PENALTY_DURATION.search(fragment):
                return True
            if has_money_semantic and money_values(fragment, assume_money=True):
                return True
            is_pure_duration = _is_pure_duration(fragment)
            is_pure_money = _is_pure_money(fragment)
            if is_pure_duration:
                pure_duration_fields.add(field_index)
            if is_pure_money:
                pure_money_fields.add(field_index)
            previous_duration_semantic = has_duration_semantic
            previous_money_semantic = has_money_semantic
            previous_pure_duration = is_pure_duration
            previous_pure_money = is_pure_money
    if any(left != right for left in duration_semantic_fields for right in pure_duration_fields):
        return True
    if any(left != right for left in money_semantic_fields for right in pure_money_fields):
        return True
    return False


def _currency_code(marker: str | None) -> str | None:
    if marker is None:
        return None
    normalized = marker.upper()
    if normalized in {"元", "圓"}:
        return "TWD"
    return _ALIAS_TO_CURRENCY.get(normalized, f"UNKNOWN:{normalized}")


def _money_value_from_match(
    match: re.Match[str],
    *,
    assume_money: bool,
) -> tuple[str, Decimal] | None:
    prefix = _currency_code(match.group("prefix"))
    suffix_marker = match.group("suffix")
    suffix = (
        prefix or "TWD"
        if suffix_marker in {"元", "圓"}
        else _currency_code(suffix_marker)
    )
    if prefix and suffix and prefix != suffix:
        raise ValueError("Conflicting currency markers in amount expression")
    expression = match.group("expression")
    if not prefix and not suffix:
        has_monetary_magnitude = re.search(r"[萬億兆]", expression) is not None
        if not assume_money and not has_monetary_magnitude:
            return None
        if assume_money and not re.search(rf"[0-9{_ARABIC_UNIT}]", expression):
            return None
    return prefix or suffix or "TWD", evaluate_amount_expression(expression)


def _visible_fields(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [field for item in value.values() for field in _visible_fields(item)]
    if isinstance(value, list):
        return [field for item in value for field in _visible_fields(item)]
    return []


def _visible_fragments(field: str) -> list[str]:
    normalized = unicodedata.normalize("NFKC", field)
    return [fragment.strip() for fragment in _VISIBLE_FRAGMENT_SEPARATOR.split(normalized) if fragment.strip()]


def _is_pure_duration(fragment: str) -> bool:
    return _PENALTY_DURATION.fullmatch(fragment) is not None


def _is_pure_money(fragment: str) -> bool:
    return _MONEY_TOKEN.fullmatch(fragment) is not None and bool(
        money_values(fragment, assume_money=True)
    )
