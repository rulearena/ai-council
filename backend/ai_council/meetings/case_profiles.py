from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
from typing import Mapping

from ai_council.meetings.input_envelope import CASE_EVIDENCE_BY_ROLE_INPUT

from ai_council.meetings.legal_semantics import (
    contains_concrete_penalty,
    money_values,
    parse_money_expression,
)


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
                    relief = claim.get("relief") if isinstance(claim.get("relief"), dict) else {}
                    refs = claim.get("evidence_refs") if isinstance(claim.get("evidence_refs"), list) else []
                    lines.extend([
                        f"{claim.get('claim', '')}：{_civil_final_outcome(str(claim.get('outcome', '')))}",
                        f"理由：{claim.get('reasoning', '')}",
                        f"給付／義務：{relief.get('obligation', '')}",
                        f"金額：{relief.get('monetary_amount') or '無'}",
                        f"計算基礎：{relief.get('calculation_basis') or '無'}",
                        f"證據：{'、'.join(str(ref) for ref in refs) or '未引用證據'}",
                    ])
        else:
            for charge in parsed.get("charges", []) if isinstance(parsed.get("charges"), list) else []:
                if isinstance(charge, dict):
                    refs = charge.get("evidence_refs") if isinstance(charge.get("evidence_refs"), list) else []
                    lines.extend([
                        f"{charge.get('charge', '')}：{_criminal_final_decision(str(charge.get('decision', '')))}",
                        f"理由：{charge.get('reasoning', '')}",
                        f"證據：{'、'.join(str(ref) for ref in refs) or '未引用證據'}",
                    ])
            factors = parsed.get("sentencing_factors")
            if isinstance(factors, list) and factors:
                lines.append(f"量刑考量：{'、'.join(str(item) for item in factors)}")
        return "\n".join(line for line in lines if line)

    def validate_final_semantics(
        self,
        parsed: dict[str, object],
        inputs: dict[str, object] | None,
    ) -> None:
        visible_text = "\n".join(_visible_strings(parsed))
        if self.case_type == "criminal":
            if contains_concrete_penalty(parsed):
                raise ValueError("Criminal verdict must not state a concrete penalty")
            return
        evidence_by_anchor = _judge_evidence_by_anchor(inputs)
        judge_evidence = "\n".join(evidence_by_anchor.values())
        visible_anchors = set(evidence_by_anchor)
        referenced_anchors = set(re.findall(r"\[證物[^\]]+\]", visible_text))
        if not referenced_anchors.issubset(visible_anchors):
            raise ValueError("Civil verdict cites unknown or invisible evidence")
        claims = parsed.get("claims")
        supported_claim_money: set[tuple[str, Decimal]] = set()
        top_level_supports: list[set[tuple[str, Decimal]]] = []
        for claim in claims if isinstance(claims, list) else []:
            if not isinstance(claim, dict):
                continue
            refs = claim.get("evidence_refs")
            if isinstance(refs, list) and any(str(ref) not in visible_anchors for ref in refs):
                raise ValueError("Civil verdict cites unknown or invisible evidence")
            claim_money = _structured_money_values(claim)
            relief = claim.get("relief")
            calculation_basis = (
                relief.get("calculation_basis")
                if isinstance(relief, dict)
                else None
            )
            normalized_refs = [str(ref) for ref in refs] if isinstance(refs, list) else []
            has_calculation = isinstance(calculation_basis, str) and bool(
                calculation_basis.strip()
            )
            if normalized_refs and has_calculation:
                top_level_supports.append(
                    _money_for_anchors(evidence_by_anchor, normalized_refs)
                )
            if not claim_money:
                continue
            if not normalized_refs or not has_calculation:
                raise ValueError(
                    "Civil monetary claim is not supported without evidence_refs and calculation_basis"
                )
            if not claim_money.issubset(
                _money_for_anchors(evidence_by_anchor, normalized_refs)
            ):
                raise ValueError(
                    "Civil verdict monetary amount is not supported by the claim's visible evidence"
                )
            supported_claim_money.update(claim_money)

        top_level_money = _structured_money_values(
            {key: value for key, value in parsed.items() if key != "claims"}
        )
        safely_linked_top_level = (
            top_level_supports[0]
            if len(top_level_supports) == 1
            else supported_claim_money
        )
        if not top_level_money.issubset(safely_linked_top_level):
            raise ValueError(
                "Civil top-level monetary amount is not supported by explicit claim support"
            )
        verdict_money = money_values("\n".join(_visible_strings_without_monetary_amount(parsed)))
        verdict_money.update(
            parse_money_expression(amount, assume_money=True)
            for amount in _civil_monetary_amounts(parsed)
        )
        if not verdict_money.issubset(money_values(judge_evidence)):
            raise ValueError("Civil verdict monetary amount is not supported by visible evidence")


def _structured_money_values(value: object) -> set[tuple[str, Decimal]]:
    values: set[tuple[str, Decimal]] = set(
        money_values("\n".join(_visible_strings_without_monetary_amount(value)))
    )
    values.update(
        parse_money_expression(amount, assume_money=True)
        for amount in _civil_monetary_amounts(value)
    )
    return values


def _judge_evidence_by_anchor(
    inputs: dict[str, object] | None,
) -> dict[str, str]:
    structured_by_role = (inputs or {}).get(CASE_EVIDENCE_BY_ROLE_INPUT)
    if structured_by_role is not None:
        if not isinstance(structured_by_role, dict):
            raise ValueError(
                "Civil verdict received an invalid structured evidence envelope"
            )
        blocks = structured_by_role.get("Judge", [])
        if not isinstance(blocks, list):
            raise ValueError(
                "Civil verdict received an invalid structured evidence envelope"
            )
        evidence: dict[str, str] = {}
        for block in blocks:
            if not isinstance(block, dict):
                raise ValueError(
                    "Civil verdict received an invalid structured evidence envelope"
                )
            anchor = block.get("citation_anchor")
            evidence_id = block.get("id")
            version = block.get("version")
            content = block.get("content")
            if (
                not isinstance(anchor, str)
                or re.fullmatch(r"\[證物[^\[\]\n]+\]", anchor) is None
                or not isinstance(evidence_id, str)
                or not evidence_id.strip()
                or not isinstance(version, int)
                or isinstance(version, bool)
                or version < 1
                or not isinstance(content, str)
                or anchor in evidence
            ):
                raise ValueError(
                    "Civil verdict received an invalid structured evidence envelope"
                )
            evidence[anchor] = content
        return evidence

    rendered_by_role = (inputs or {}).get("__case_files_by_role")
    rendered = (
        str(rendered_by_role.get("Judge", ""))
        if isinstance(rendered_by_role, dict)
        else ""
    )
    headings = list(
        re.finditer(
            r"^### (\[證物[^\[\]\n]+\])(?: [^\n]*)?\n",
            rendered,
            re.MULTILINE,
        )
    )
    evidence = {}
    for index, heading in enumerate(headings):
        anchor = heading.group(1)
        if anchor in evidence:
            raise ValueError(
                "Civil verdict received ambiguous legacy evidence headings"
            )
        end = headings[index + 1].start() if index + 1 < len(headings) else len(rendered)
        evidence[anchor] = rendered[heading.end():end]
    return evidence


def _money_for_anchors(
    evidence_by_anchor: dict[str, str], anchors: list[str]
) -> set[tuple[str, Decimal]]:
    return money_values("\n".join(evidence_by_anchor[anchor] for anchor in anchors))


def _visible_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _visible_strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in _visible_strings(item)]
    return []


def _visible_strings_without_monetary_amount(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [
            text
            for key, item in value.items()
            if key != "monetary_amount"
            for text in _visible_strings_without_monetary_amount(item)
        ]
    if isinstance(value, list):
        return [text for item in value for text in _visible_strings_without_monetary_amount(item)]
    return []


def _civil_monetary_amounts(value: object) -> list[str]:
    if isinstance(value, dict):
        amounts: list[str] = []
        for key, item in value.items():
            if key == "monetary_amount" and item is not None:
                if not isinstance(item, str):
                    raise ValueError("monetary_amount must be a string or null")
                amounts.append(item)
            else:
                amounts.extend(_civil_monetary_amounts(item))
        return amounts
    if isinstance(value, list):
        return [amount for item in value for amount in _civil_monetary_amounts(item)]
    return []

def _civil_final_outcome(value: str) -> str:
    return {
        "upheld": "請求成立",
        "partially-upheld": "部分請求成立",
        "rejected": "請求不成立",
        "insufficient-evidence": "證據不足",
    }.get(value, value)


def _criminal_final_decision(value: str) -> str:
    return {
        "guilty": "有罪",
        "not-guilty": "無罪",
        "insufficient-evidence": "證據不足",
    }.get(value, value)


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
