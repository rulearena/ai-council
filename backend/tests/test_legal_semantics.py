from decimal import Decimal

import pytest

from ai_council.meetings.legal_semantics import (
    contains_concrete_penalty,
    evaluate_amount_expression,
    money_values,
    parse_money_expression,
)


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("1萬5千", "15000"),
        ("1萬5000", "15000"),
        ("9萬9千", "99000"),
        ("1億2,000萬", "120000000"),
        ("2億3,000萬", "230000000"),
        ("一百", "100"),
        ("一百萬", "1000000"),
        ("十萬", "100000"),
        ("１億２，０００萬", "120000000"),
        ("2千萬", "20000000"),
        ("1百萬", "1000000"),
        ("1億2千萬", "120000000"),
        ("1億2千3百萬", "123000000"),
        ("2兆", "2000000000000"),
    ],
)
def test_amount_expression_evaluator_handles_mixed_numeric_sections(
    expression: str,
    expected: str,
) -> None:
    assert evaluate_amount_expression(expression) == Decimal(expected)


@pytest.mark.parametrize(
    ("text", "currency", "value"),
    [
        ("1萬5千元", "TWD", "15000"),
        ("1萬5000元", "TWD", "15000"),
        ("9萬9千元", "TWD", "99000"),
        ("1億2,000萬元", "TWD", "120000000"),
        ("2億3,000萬元", "TWD", "230000000"),
        ("100美元", "USD", "100"),
        ("100萬美元", "USD", "1000000"),
        ("100萬新臺幣", "TWD", "1000000"),
        ("USD 100", "USD", "100"),
        ("１００萬美元", "USD", "1000000"),
        ("新臺幣一百萬元", "TWD", "1000000"),
        ("人民幣100", "CNY", "100"),
        ("100人民幣", "CNY", "100"),
        ("RMB 100", "CNY", "100"),
        ("100日圓", "JPY", "100"),
        ("EUR 100", "EUR", "100"),
        ("100英鎊", "GBP", "100"),
        ("港幣100", "HKD", "100"),
        ("100韓元", "KRW", "100"),
        ("CAD 100", "UNKNOWN:CAD", "100"),
        ("瑞士法郎100", "UNKNOWN:瑞士法郎", "100"),
        ("100加元", "UNKNOWN:加元", "100"),
        ("澳元100", "UNKNOWN:澳元", "100"),
        ("100新加坡元", "UNKNOWN:新加坡元", "100"),
        ("USD 100元", "USD", "100"),
        ("2兆元", "TWD", "2000000000000"),
    ],
)
def test_money_values_preserves_prefix_and_suffix_currency(
    text: str,
    currency: str,
    value: str,
) -> None:
    assert money_values(text) == {(currency, Decimal(value))}


@pytest.mark.parametrize("text", ["USD 100新臺幣", "新臺幣100美元"])
def test_money_values_rejects_conflicting_currency_markers(text: str) -> None:
    with pytest.raises(ValueError, match="Conflicting currency"):
        money_values(text)


def test_money_values_requires_complete_expression_boundaries() -> None:
    assert money_values("案件A100萬元B的識別碼") == set()
    assert money_values("100萬元") == {("TWD", Decimal("1000000"))}
    assert ("TWD", Decimal("100")) not in money_values("100萬元")
    assert evaluate_amount_expression("2千萬") != Decimal("2000")
    assert money_values("2兆元") != money_values("2元")


@pytest.mark.parametrize(
    "text",
    ["100萬股", "100萬人", "100萬坪", "100萬平方公尺", "100萬公尺", "100萬份"],
)
def test_general_text_does_not_treat_unmarked_quantities_as_money(text: str) -> None:
    assert money_values(text) == set()


@pytest.mark.parametrize("text", ["100萬", "2億", "3兆"])
def test_general_text_treats_bare_monetary_magnitudes_as_twd(text: str) -> None:
    assert money_values(text)


@pytest.mark.parametrize("text", ["184", "2025", "3"])
def test_general_text_ignores_bare_numbers_without_monetary_magnitude(text: str) -> None:
    assert money_values(text) == set()


def test_assume_money_context_keeps_bare_verdict_amounts_verifiable() -> None:
    assert money_values("100萬", assume_money=True) == {("TWD", Decimal("1000000"))}
    assert money_values("100萬股", assume_money=True) == set()
    assert money_values("100萬人", assume_money=True) == set()
    assert money_values("100萬平方公尺", assume_money=True) == set()


@pytest.mark.parametrize(
    ("text", "expected"),
    [("100萬", ("TWD", Decimal("1000000"))), ("一百萬元", ("TWD", Decimal("1000000")))],
)
def test_exact_money_parser_accepts_only_a_complete_monetary_field(
    text: str,
    expected: tuple[str, Decimal],
) -> None:
    assert parse_money_expression(text, assume_money=True) == expected


@pytest.mark.parametrize("text", ["100萬坪", "100萬股", "約100萬", "100萬公尺"])
def test_exact_money_parser_rejects_non_money_or_partial_fields(text: str) -> None:
    with pytest.raises(ValueError, match="complete monetary expression"):
        parse_money_expression(text, assume_money=True)


def test_unsupported_magnitude_fails_closed_without_partial_truncation() -> None:
    with pytest.raises(ValueError, match="Unsupported magnitude"):
        money_values("2京元")


def test_different_currency_markers_never_collide_at_the_same_value() -> None:
    assert money_values("人民幣100") != money_values("新臺幣100")
    assert money_values("CAD 100") != money_values("100元")


@pytest.mark.parametrize(
    "text",
    ["死刑", "無期徒刑", "終身監禁", "終身徒刑", "永久褫奪公權"],
)
def test_penalty_guard_rejects_inherently_concrete_penalties(text: str) -> None:
    assert contains_concrete_penalty(text)


@pytest.mark.parametrize(
    "text",
    [
        "量刑考量\n刑期三年",
        "認定有罪\n入監五年",
        "認定有罪\n褫奪公權三年",
        "認定有罪\n科處新臺幣十萬元",
        "認定有罪\n罰鍰100萬元",
    ],
)
def test_penalty_guard_rejects_concrete_semantics_within_visible_fragments(text: str) -> None:
    assert contains_concrete_penalty(text)


@pytest.mark.parametrize(
    "text",
    ["犯後態度", "可能適用緩刑", "罰金可能性", "刑期應由法院另行審酌"],
)
def test_penalty_guard_allows_non_concrete_factors(text: str) -> None:
    assert not contains_concrete_penalty(text)


@pytest.mark.parametrize(
    "text",
    [
        "刑期另行審酌\n案發三年前",
        "罰金可能性\n犯罪所得100萬",
        "可能緩刑\n照顧家人五年",
    ],
)
def test_penalty_guard_does_not_cartesian_join_unrelated_fragments(text: str) -> None:
    assert not contains_concrete_penalty(text)


@pytest.mark.parametrize(
    "text",
    ["建議判刑，三年", "建議判刑\n三年", "科處；新臺幣十萬元"],
)
def test_penalty_guard_links_adjacent_pure_values_in_the_same_field(text: str) -> None:
    assert contains_concrete_penalty(text)


@pytest.mark.parametrize(
    "text",
    ["三年，作為宣告刑", "新臺幣十萬元；予以科處"],
)
def test_penalty_guard_links_reverse_adjacent_pure_values_in_the_same_field(text: str) -> None:
    assert contains_concrete_penalty(text)


@pytest.mark.parametrize(
    "text",
    ["刑期另行審酌，案發三年前", "罰金可能性；犯罪所得100萬", "可能緩刑\n照顧家人五年"],
)
def test_penalty_guard_keeps_contextual_adjacent_fragments_independent(text: str) -> None:
    assert not contains_concrete_penalty(text)


@pytest.mark.parametrize(
    "text",
    ["案發至今三年，刑期另行審酌", "犯罪所得100萬；罰金可能性", "照顧家人五年，可能緩刑"],
)
def test_penalty_guard_keeps_reverse_contextual_fragments_independent(text: str) -> None:
    assert not contains_concrete_penalty(text)


@pytest.mark.parametrize(
    "text",
    [
        "終身監禁",
        "監禁終身",
        "永久褫奪公權",
        "褫奪公權永久有效",
        "無限期拘禁",
        "入監且期限為終身",
    ],
)
def test_penalty_guard_matches_permanent_terms_around_incarceration(text: str) -> None:
    assert contains_concrete_penalty(text)


@pytest.mark.parametrize(
    "visible",
    [
        {"summary": "建議判刑", "sentencing_factors": ["三年"]},
        ["科處", "新臺幣十萬元"],
    ],
)
def test_penalty_guard_links_only_pure_cross_field_penalty_values(visible: object) -> None:
    assert contains_concrete_penalty(visible)


@pytest.mark.parametrize(
    "visible",
    [
        ["刑期另行審酌", "案發至今三年"],
        ["罰金可能性", "犯罪所得100萬"],
        ["可能緩刑", "照顧家人五年"],
    ],
)
def test_penalty_guard_does_not_link_contextual_cross_field_values(visible: object) -> None:
    assert not contains_concrete_penalty(visible)
