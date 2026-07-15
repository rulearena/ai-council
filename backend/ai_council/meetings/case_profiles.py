from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
import re
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
            if _CONCRETE_PENALTY.search(visible_text):
                raise ValueError("Criminal verdict must not state a concrete penalty")
            return
        by_role = (inputs or {}).get("__case_files_by_role")
        judge_evidence = str(by_role.get("Judge", "")) if isinstance(by_role, dict) else ""
        visible_anchors = set(re.findall(r"\[證物[^\]]+\]", judge_evidence))
        referenced_anchors = set(re.findall(r"\[證物[^\]]+\]", visible_text))
        if not referenced_anchors.issubset(visible_anchors):
            raise ValueError("Civil verdict cites unknown or invisible evidence")
        claims = parsed.get("claims")
        for claim in claims if isinstance(claims, list) else []:
            if not isinstance(claim, dict):
                continue
            refs = claim.get("evidence_refs")
            if isinstance(refs, list) and any(str(ref) not in visible_anchors for ref in refs):
                raise ValueError("Civil verdict cites unknown or invisible evidence")
        if not _money_values(visible_text).issubset(_money_values(judge_evidence)):
            raise ValueError("Civil verdict monetary amount is not supported by visible evidence")


_CONCRETE_PENALTY = re.compile(
    r"(?:有期徒刑|無期徒刑|死刑|拘役|罰金|處以|宣告刑|應執行)|"
    r"(?:判處|處|緩刑|徒刑)\s*(?:徒刑\s*)?[0-9零〇一二兩三四五六七八九十百千萬億壹貳參肆伍陸柒捌玖拾佰仟]+\s*(?:年|月|日)"
)
_CHINESE_NUMBER = "零〇一二兩三四五六七八九十百千萬億壹貳參肆伍陸柒捌玖拾佰仟"
_MONEY = re.compile(
    rf"(?:新臺幣|臺幣|美金|美元|NT\$|\$)\s*([0-9][0-9,]*(?:\.[0-9]+)?|[{_CHINESE_NUMBER}]+)\s*元?|"
    rf"([0-9][0-9,]*(?:\.[0-9]+)?|[{_CHINESE_NUMBER}]+)\s*元"
)


def _visible_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _visible_strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in _visible_strings(item)]
    return []


def _money_values(text: str) -> set[str]:
    values: set[str] = set()
    for match in _MONEY.finditer(text):
        raw = (match.group(1) or match.group(2)).replace(",", "")
        if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", raw):
            values.add(format(Decimal(raw).normalize(), "f"))
        else:
            values.add(str(_chinese_integer(raw)))
    return values


_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "壹": 1, "二": 2, "兩": 2, "貳": 2,
    "三": 3, "參": 3, "四": 4, "肆": 4, "五": 5, "伍": 5,
    "六": 6, "陸": 6, "七": 7, "柒": 7, "八": 8, "捌": 8,
    "九": 9, "玖": 9,
}
_SMALL_UNITS = {"十": 10, "拾": 10, "百": 100, "佰": 100, "千": 1000, "仟": 1000}
_LARGE_UNITS = {"萬": 10_000, "億": 100_000_000}


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
