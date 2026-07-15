from decimal import Decimal

import pytest

from ai_council.meetings.legal_semantics import (
    contains_concrete_penalty,
    evaluate_amount_expression,
    money_values,
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
    ],
)
def test_money_values_preserves_prefix_and_suffix_currency(
    text: str,
    currency: str,
    value: str,
) -> None:
    assert money_values(text) == {(currency, Decimal(value))}


@pytest.mark.parametrize("text", ["USD 100新臺幣", "新臺幣100美元", "美元100元"])
def test_money_values_rejects_conflicting_currency_markers(text: str) -> None:
    with pytest.raises(ValueError, match="Conflicting currency"):
        money_values(text)


def test_money_values_requires_complete_expression_boundaries() -> None:
    assert money_values("案件A100萬元B的識別碼") == set()
    assert money_values("100萬元") == {("TWD", Decimal("1000000"))}
    assert ("TWD", Decimal("100")) not in money_values("100萬元")


@pytest.mark.parametrize(
    "text",
    ["死刑", "無期徒刑", "終身監禁", "終身徒刑", "永久褫奪公權"],
)
def test_penalty_guard_rejects_inherently_concrete_penalties(text: str) -> None:
    assert contains_concrete_penalty(text)


@pytest.mark.parametrize(
    "text",
    [
        "建議判刑\n三年",
        "量刑考量\n刑期三年",
        "認定有罪\n入監\n五年",
        "認定有罪\n褫奪公權\n三年",
        "認定有罪\n科處\n新臺幣十萬元",
        "認定有罪\n罰鍰\n100萬元",
    ],
)
def test_penalty_guard_aggregates_semantics_across_visible_fields(text: str) -> None:
    assert contains_concrete_penalty(text)


@pytest.mark.parametrize(
    "text",
    ["犯後態度", "可能適用緩刑", "罰金可能性", "刑期應由法院另行審酌"],
)
def test_penalty_guard_allows_non_concrete_factors(text: str) -> None:
    assert not contains_concrete_penalty(text)
