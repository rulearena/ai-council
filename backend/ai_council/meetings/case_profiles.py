from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


class CourtroomCaseProfileError(ValueError):
    """Raised when a courtroom meeting has no usable explicit case type."""


@dataclass(frozen=True)
class CourtroomStepProfile:
    id: str
    role_id: str
    display: str
    prompt_template: str
    output_schema_id: str


@dataclass(frozen=True)
class CourtroomArgumentPhase(CourtroomStepProfile):
    limited_rebuttal: bool = False


@dataclass(frozen=True)
class CourtroomCaseProfile:
    case_type: str
    roles: Mapping[str, str]
    draft: CourtroomStepProfile
    argument_phases: tuple[CourtroomArgumentPhase, ...]
    ruling: CourtroomStepProfile
    final: CourtroomStepProfile
    outcomes: Mapping[str, str]

    @classmethod
    def for_metadata(cls, metadata: Mapping[str, object]) -> CourtroomCaseProfile:
        case_type = metadata.get("case_type")
        if not isinstance(case_type, str) or not case_type:
            raise CourtroomCaseProfileError(
                "A courtroom case type must be explicitly selected"
            )
        return cls.for_type(case_type)

    @classmethod
    def for_type(cls, case_type: str) -> CourtroomCaseProfile:
        try:
            return _CASE_PROFILES[case_type]
        except KeyError as error:
            raise CourtroomCaseProfileError(
                f"Unknown courtroom case type: {case_type}"
            ) from error

    def role_display(self, role_id: str) -> str:
        return self.roles.get(role_id, role_id)

    def phase_display(self, phase_id: str) -> str:
        if phase_id == self.ruling.id:
            return self.ruling.display
        if phase_id == self.final.id:
            return self.final.display
        for phase in self.argument_phases:
            if phase.id == phase_id:
                return phase.display
        return phase_id

    def outcome_display(self, outcome: str) -> str:
        return self.outcomes.get(outcome, outcome)

    def render_final(self, parsed: Mapping[str, object]) -> str:
        lines = [str(parsed.get("summary", ""))]
        if self.case_type == "civil":
            for claim in parsed.get("claims", []) if isinstance(parsed.get("claims"), list) else []:
                if isinstance(claim, dict):
                    lines.append(
                        f"{claim.get('claim', '')}：{claim.get('outcome', '')}｜{claim.get('reasoning', '')}"
                    )
        else:
            for charge in parsed.get("charges", []) if isinstance(parsed.get("charges"), list) else []:
                if isinstance(charge, dict):
                    lines.append(
                        f"{charge.get('charge', '')}：{charge.get('decision', '')}｜{charge.get('reasoning', '')}"
                    )
            factors = parsed.get("sentencing_factors")
            if isinstance(factors, list) and factors:
                lines.append(f"量刑考量：{'、'.join(str(item) for item in factors)}")
        return "\n".join(line for line in lines if line)


def _profile(
    case_type: str,
    *,
    proponent: str,
    respondent: str,
    proponent_outcome: str,
    respondent_outcome: str,
) -> CourtroomCaseProfile:
    prefix = f"courtroom_{case_type}"
    return CourtroomCaseProfile(
        case_type=case_type,
        roles={
            "Prosecutor": proponent,
            "Defense": respondent,
            "Judge": "法官",
        },
        draft=CourtroomStepProfile(
            id="issue-draft",
            role_id="Judge",
            display="爭點草稿",
            prompt_template=f"{prefix}_issue_draft",
            output_schema_id="courtroom-issue-draft/v1",
        ),
        argument_phases=(
            CourtroomArgumentPhase(
                id="charge",
                role_id="Prosecutor",
                display="主張方陳述",
                prompt_template=f"{prefix}_proponent_statement",
                output_schema_id="role-output/v1",
            ),
            CourtroomArgumentPhase(
                id="defense",
                role_id="Defense",
                display="答辯方答辯",
                prompt_template=f"{prefix}_respondent_defense",
                output_schema_id="role-output/v1",
            ),
            CourtroomArgumentPhase(
                id="rebuttal",
                role_id="Prosecutor",
                display="主張方限縮反駁",
                prompt_template=f"{prefix}_limited_rebuttal",
                output_schema_id="role-output/v1",
                limited_rebuttal=True,
            ),
        ),
        ruling=CourtroomStepProfile(
            id="ruling",
            role_id="Judge",
            display="法官對此爭點的判斷",
            prompt_template=f"{prefix}_issue_ruling",
            output_schema_id="courtroom-ruling/v1",
        ),
        final=CourtroomStepProfile(
            id="final",
            role_id="Judge",
            display="全案最終判決",
            prompt_template=f"{prefix}_final_verdict",
            output_schema_id=f"courtroom-{case_type}-final/v1",
        ),
        outcomes={
            "proponent-wins": proponent_outcome,
            "respondent-wins": respondent_outcome,
            "partially-upheld": "部分主張成立",
            "insufficient-evidence": "證據不足",
        },
    )


_CASE_PROFILES = {
    "civil": _profile(
        "civil",
        proponent="原告代理人",
        respondent="被告代理人",
        proponent_outcome="原告主張成立",
        respondent_outcome="被告抗辯成立",
    ),
    "criminal": _profile(
        "criminal",
        proponent="檢察官",
        respondent="辯護人",
        proponent_outcome="檢方主張成立",
        respondent_outcome="辯方主張成立",
    ),
}
