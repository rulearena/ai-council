from __future__ import annotations

import pytest

from ai_council.meetings.case_profiles import (
    CourtroomCaseProfile,
    CourtroomCaseProfileError,
)


@pytest.mark.parametrize(
    ("case_type", "proponent", "respondent"),
    [
        ("civil", "原告代理人", "被告代理人"),
        ("criminal", "檢察官", "辯護人"),
    ],
)
def test_case_profile_centralizes_roles_phases_prompts_and_schemas(
    case_type: str,
    proponent: str,
    respondent: str,
) -> None:
    profile = CourtroomCaseProfile.for_type(case_type)

    assert profile.role_display("Prosecutor") == proponent
    assert profile.role_display("Defense") == respondent
    assert profile.role_display("Judge") == "法官"
    assert [(phase.id, phase.role_id) for phase in profile.argument_phases] == [
        ("charge", "Prosecutor"),
        ("defense", "Defense"),
        ("rebuttal", "Prosecutor"),
    ]
    assert profile.argument_phases[-1].limited_rebuttal is True
    assert profile.draft.role_id == "Judge"
    assert profile.ruling.role_id == "Judge"
    assert profile.final.role_id == "Judge"
    assert profile.draft.prompt_template.startswith(f"courtroom_{case_type}_")
    assert profile.final.output_schema_id == f"courtroom-{case_type}-final/v1"
    assert profile.phase_display("ruling") == "法官對此爭點的判斷"
    assert profile.final.display == "全案最終判決"


def test_case_profile_rejects_missing_or_unknown_type_without_inference() -> None:
    with pytest.raises(CourtroomCaseProfileError, match="explicitly selected"):
        CourtroomCaseProfile.for_metadata(
            {
                "mode_id": "courtroom",
                "title": "土地糾紛刑事案",
                "goal": "被告是否有罪",
            }
        )
    with pytest.raises(CourtroomCaseProfileError, match="Unknown"):
        CourtroomCaseProfile.for_type("family")


def test_case_profile_presents_neutral_outcomes_for_each_case_type() -> None:
    civil = CourtroomCaseProfile.for_type("civil")
    criminal = CourtroomCaseProfile.for_type("criminal")

    assert civil.outcome_display("proponent-wins") == "原告主張成立"
    assert criminal.outcome_display("proponent-wins") == "檢方主張成立"
    assert civil.outcome_display("insufficient-evidence") == "證據不足"
    assert criminal.outcome_display("insufficient-evidence") == "證據不足"


def test_case_profile_renders_case_specific_final_without_cross_domain_fields() -> None:
    civil = CourtroomCaseProfile.for_type("civil").render_final({
        "summary": "部分勝訴",
        "claims": [{
            "claim": "返還價金",
            "outcome": "upheld",
            "reasoning": "付款可證",
            "evidence_refs": ["[證物一]"],
            "relief": {"obligation": "返還", "monetary_amount": None, "calculation_basis": None},
        }],
        "unresolved_questions": [],
    })
    criminal = CourtroomCaseProfile.for_type("criminal").render_final({
        "summary": "有罪",
        "charges": [{
            "charge": "竊盜罪",
            "decision": "guilty",
            "reasoning": "證據充分",
            "evidence_refs": ["[證物一]"],
        }],
        "sentencing_factors": ["犯後態度"],
        "unresolved_questions": [],
    })

    assert "返還價金：請求成立" in civil and "upheld" not in civil and "量刑" not in civil
    assert "竊盜罪：有罪" in criminal and "guilty" not in criminal
    assert "量刑考量：犯後態度" in criminal


def test_final_semantics_validate_all_visible_penalty_and_money_text() -> None:
    criminal = CourtroomCaseProfile.for_type("criminal")
    with pytest.raises(ValueError, match="concrete penalty"):
        criminal.validate_final_semantics(
            {
                "summary": "有罪",
                "charges": [{"reasoning": "應處有期徒刑一年"}],
                "sentencing_factors": [],
                "unresolved_questions": [],
            },
            None,
        )

    civil = CourtroomCaseProfile.for_type("civil")
    inputs = {
        "__case_files_by_role": {
            "Judge": "### [證物一] 匯款\n被告收受新臺幣 100 元"
        }
    }
    civil.validate_final_semantics(
        {"summary": "返還新臺幣 100 元", "claims": [{"evidence_refs": ["[證物一]"]}]},
        inputs,
    )
    with pytest.raises(ValueError, match="not supported"):
        civil.validate_final_semantics(
            {"summary": "返還新臺幣 999 元", "claims": [{"evidence_refs": ["[證物一]"]}]},
            inputs,
        )
    with pytest.raises(ValueError, match="unknown or invisible"):
        civil.validate_final_semantics(
            {"summary": "無金額", "claims": [{"evidence_refs": ["[證物二]"]}]},
            inputs,
        )


@pytest.mark.parametrize(
    "penalty_text",
    ["判處一年", "判處徒刑五年", "緩刑三年"],
)
def test_criminal_final_rejects_common_chinese_concrete_penalty_phrases(
    penalty_text: str,
) -> None:
    with pytest.raises(ValueError, match="concrete penalty"):
        CourtroomCaseProfile.for_type("criminal").validate_final_semantics(
            {"summary": penalty_text},
            None,
        )


def test_civil_final_compares_traditional_chinese_money_values_to_visible_evidence() -> None:
    profile = CourtroomCaseProfile.for_type("civil")
    inputs = {
        "__case_files_by_role": {
            "Judge": "### [證物一] 收據\n價款為新臺幣一百萬元"
        }
    }

    profile.validate_final_semantics(
        {
            "summary": "應返還新臺幣1000000元",
            "claims": [{"evidence_refs": ["[證物一]"]}],
        },
        inputs,
    )
    for unsupported in ("新臺幣一百元", "新臺幣二百萬元"):
        with pytest.raises(ValueError, match="not supported"):
            profile.validate_final_semantics(
                {
                    "summary": f"應返還{unsupported}",
                    "claims": [{"evidence_refs": ["[證物一]"]}],
                },
                inputs,
            )


@pytest.mark.parametrize(
    ("evidence_amount", "verdict_amount"),
    [
        ("100元", "新臺幣100元"),
        ("100萬元", "新臺幣1,000,000元"),
        ("新臺幣100元", "100元"),
        ("新臺幣100萬元", "一百萬元"),
        ("TWD 100萬", "新臺幣100萬元"),
        ("一百元", "１００元"),
        ("一百萬元", "1,000,000元"),
        ("十萬元", "新臺幣100,000元"),
        ("１，０００元", "新臺幣1,000元"),
        ("1萬5千元", "新臺幣15,000元"),
        ("1萬5000元", "一萬五千元"),
        ("9萬9千元", "99,000元"),
        ("1億2,000萬元", "新臺幣120,000,000元"),
        ("2億3,000萬元", "230000000元"),
        ("2千萬元", "20,000,000元"),
        ("1百萬元", "1,000,000元"),
        ("1億2千3百萬元", "123,000,000元"),
        ("2兆元", "2,000,000,000,000元"),
        ("100美元", "USD 100"),
        ("100萬美元", "USD 1,000,000"),
        ("100萬新臺幣", "新臺幣1,000,000元"),
    ],
)
def test_civil_money_tokenizer_normalizes_complete_equivalent_amounts(
    evidence_amount: str,
    verdict_amount: str,
) -> None:
    CourtroomCaseProfile.for_type("civil").validate_final_semantics(
        {
            "summary": f"應返還{verdict_amount}",
            "claims": [{"evidence_refs": ["[證物一]"]}],
        },
        {
            "__case_files_by_role": {
                "Judge": f"### [證物一] 金額\n案卷記載{evidence_amount}"
            }
        },
    )


@pytest.mark.parametrize(
    ("evidence_amount", "unsupported_amount"),
    [
        ("100元", "100萬元"),
        ("100萬元", "100元"),
        ("十萬", "一百萬元"),
        ("１，０００元", "１，０００萬元"),
        ("100美元", "100元"),
        ("100萬美元", "100萬新臺幣"),
        ("1億2,000萬元", "2億3,000萬元"),
        ("2千萬元", "2,000元"),
        ("人民幣100", "新臺幣100元"),
        ("2兆元", "2元"),
        ("100萬股", "100萬元"),
    ],
)
def test_civil_money_tokenizer_never_truncates_or_changes_magnitude(
    evidence_amount: str,
    unsupported_amount: str,
) -> None:
    with pytest.raises(ValueError, match="not supported"):
        CourtroomCaseProfile.for_type("civil").validate_final_semantics(
            {
                "summary": f"應返還{unsupported_amount}",
                "claims": [{"evidence_refs": ["[證物一]"]}],
            },
            {
                "__case_files_by_role": {
                    "Judge": f"### [證物一] 金額\n案卷記載{evidence_amount}"
                }
            },
        )


def test_civil_money_tokenizer_rejects_bare_magnitude_without_visible_evidence() -> None:
    with pytest.raises(ValueError, match="not supported"):
        CourtroomCaseProfile.for_type("civil").validate_final_semantics(
            {
                "summary": "應返還100萬元",
                "claims": [{"evidence_refs": []}],
            },
            {"__case_files_by_role": {"Judge": ""}},
        )


def test_civil_verdict_bare_amount_is_checked_but_bare_evidence_quantity_is_not_money() -> None:
    with pytest.raises(ValueError, match="not supported"):
        CourtroomCaseProfile.for_type("civil").validate_final_semantics(
            {"summary": "應返還100萬", "claims": [{"evidence_refs": ["[證物一]"]}]},
            {"__case_files_by_role": {"Judge": "[證物一] 持有100萬股"}},
        )


@pytest.mark.parametrize(
    "penalty_text",
    [
        "判刑五年",
        "入監五年",
        "監禁三年",
        "科刑二年",
        "褫奪公權三年",
        "科處新臺幣十萬元",
        "判處一年",
        "判處徒刑五年",
        "緩刑三年",
    ],
)
def test_criminal_penalty_guard_rejects_structured_concrete_penalties_in_any_field(
    penalty_text: str,
) -> None:
    with pytest.raises(ValueError, match="concrete penalty"):
        CourtroomCaseProfile.for_type("criminal").validate_final_semantics(
            {
                "summary": "罪責判斷",
                "charges": [{"reasoning": penalty_text}],
                "sentencing_factors": ["犯後態度"],
            },
            None,
        )


@pytest.mark.parametrize(
    "factor",
    ["犯後態度", "是否坦承犯行", "家庭支持與再犯風險", "可能適用緩刑", "罰金可能性"],
)
def test_criminal_penalty_guard_allows_non_concrete_sentencing_factors(
    factor: str,
) -> None:
    CourtroomCaseProfile.for_type("criminal").validate_final_semantics(
        {"summary": "罪責判斷", "sentencing_factors": [factor]},
        None,
    )


@pytest.mark.parametrize(
    "parsed",
    [
        {"summary": "建議判刑", "sentencing_factors": ["刑期三年"]},
        {"summary": "認定有罪", "charges": [{"reasoning": "入監五年"}]},
        {"summary": "認定有罪", "sentencing_factors": ["科處新臺幣十萬元"]},
    ],
)
def test_criminal_penalty_guard_aggregates_all_visible_structured_fields(
    parsed: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="concrete penalty"):
        CourtroomCaseProfile.for_type("criminal").validate_final_semantics(parsed, None)


def test_criminal_penalty_guard_does_not_join_unrelated_visible_fields() -> None:
    CourtroomCaseProfile.for_type("criminal").validate_final_semantics(
        {
            "summary": "刑期另行審酌",
            "charges": [{"reasoning": "案發三年前"}],
            "sentencing_factors": ["罰金可能性", "犯罪所得100萬"],
        },
        None,
    )
