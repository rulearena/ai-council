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

    assert "返還價金" in civil and "量刑" not in civil
    assert "竊盜罪" in criminal and "量刑考量：犯後態度" in criminal


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
