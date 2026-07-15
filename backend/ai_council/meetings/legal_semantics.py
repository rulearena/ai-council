from __future__ import annotations

from decimal import Decimal
import re
import unicodedata


_CHINESE_NUMBER = "零〇一二兩三四五六七八九十百千萬億壹貳參肆伍陸柒捌玖拾佰仟"
_NUMBER_BOUNDARY = rf"0-9{_CHINESE_NUMBER}"
_CURRENCY = r"(?:新臺幣|臺幣|NT\$|美金|美元|\$)"
_ARABIC_MONEY = re.compile(
    rf"(?<![{_NUMBER_BOUNDARY}])"
    rf"(?P<currency>{_CURRENCY})?\s*"
    r"(?P<number>[0-9]+(?:,[0-9]{3})*(?:\.[0-9]+)?)\s*"
    r"(?P<magnitude>萬|億)?\s*(?P<yuan>元)?"
    rf"(?![{_NUMBER_BOUNDARY}])"
)
_CHINESE_MONEY = re.compile(
    rf"(?<![{_NUMBER_BOUNDARY}])"
    rf"(?P<currency>{_CURRENCY})?\s*"
    rf"(?P<number>[{_CHINESE_NUMBER}]+)\s*(?P<yuan>元)?"
    rf"(?![{_NUMBER_BOUNDARY}])"
)
_PENALTY_ACTION = re.compile(
    r"判刑|判處|科刑|科處|入監|監禁|徒刑|拘役|緩刑|褫奪公權|"
    r"罰金|處以|宣告刑|應執行|應處"
)
_PENALTY_DURATION = re.compile(
    rf"(?<![{_NUMBER_BOUNDARY}])(?:[0-9]+|[{_CHINESE_NUMBER}]+)\s*"
    rf"(?:年|個月|月|日)(?![{_NUMBER_BOUNDARY}])"
)
_INHERENT_CONCRETE_PENALTY = re.compile(r"死刑|無期徒刑")
_CLAUSE_SEPARATOR = re.compile(r"[，,。；;：:\n\r！？!?]+")

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
_MAGNITUDES = {None: Decimal(1), "萬": Decimal(10_000), "億": Decimal(100_000_000)}


def money_values(text: str) -> set[tuple[str, Decimal]]:
    """Return complete, normalized currency amounts found in user-visible text."""
    normalized = unicodedata.normalize("NFKC", text)
    values: set[tuple[str, Decimal]] = set()
    occupied: list[tuple[int, int]] = []
    for match in _ARABIC_MONEY.finditer(normalized):
        currency = match.group("currency")
        magnitude = match.group("magnitude")
        if not currency and not magnitude and not match.group("yuan"):
            continue
        number = Decimal(match.group("number").replace(",", ""))
        values.add((_currency_code(currency), number * _MAGNITUDES[magnitude]))
        occupied.append(match.span())
    for match in _CHINESE_MONEY.finditer(normalized):
        if any(start < match.end() and match.start() < end for start, end in occupied):
            continue
        currency = match.group("currency")
        number = match.group("number")
        if not currency and not match.group("yuan") and not number.endswith(("萬", "億")):
            continue
        values.add((_currency_code(currency), Decimal(_chinese_integer(number))))
    return values


def contains_concrete_penalty(text: str) -> bool:
    """Detect an imposed penalty, while allowing non-concrete sentencing factors."""
    normalized = unicodedata.normalize("NFKC", text)
    if _INHERENT_CONCRETE_PENALTY.search(normalized):
        return True
    for clause in _CLAUSE_SEPARATOR.split(normalized):
        if not _PENALTY_ACTION.search(clause):
            continue
        if _PENALTY_DURATION.search(clause) or money_values(clause):
            return True
    return False


def _currency_code(currency: str | None) -> str:
    return "USD" if currency in {"美金", "美元", "$"} else "TWD"


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
