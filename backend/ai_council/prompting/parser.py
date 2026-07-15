from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class OutputItem:
    title: str
    detail: str


@dataclass(frozen=True)
class RoleOutput:
    summary: str
    arguments: list[OutputItem]
    risks: list[OutputItem]
    recommendation: str


VerdictDecision = Literal[
    "approve",
    "approve-with-conditions",
    "reject",
    "insufficient-evidence",
]
VERDICT_DECISIONS = {
    "approve",
    "approve-with-conditions",
    "reject",
    "insufficient-evidence",
}
EVIDENCE_REF_PATTERN = re.compile(r"\[證物[零一二三四五六七八九十百千萬]+\]")
STRUCTURED_VERDICT_FIELDS = {
    "summary",
    "decision",
    "findings",
    "risks",
    "recommendation",
    "conditions",
    "unresolved_questions",
}
VERDICT_ITEM_FIELDS = {"title", "detail", "evidence_refs"}


@dataclass(frozen=True)
class VerdictItem:
    title: str
    detail: str
    evidence_refs: list[str]


@dataclass(frozen=True)
class StructuredVerdict:
    summary: str
    decision: VerdictDecision
    findings: list[VerdictItem]
    risks: list[VerdictItem]
    recommendation: str
    conditions: list[str]
    unresolved_questions: list[str]


class OutputParseError(ValueError):
    def __init__(self, message: str, *, raw_output: object) -> None:
        super().__init__(message)
        self.raw_output = raw_output


class RoleOutputParser:
    def parse(self, raw_output: str) -> RoleOutput:
        try:
            payload = json.loads(extract_first_json_object(raw_output))
            return RoleOutput(
                summary=require_string(payload, "summary"),
                arguments=parse_items(payload, "arguments"),
                risks=parse_items(payload, "risks"),
                recommendation=require_string(payload, "recommendation"),
            )
        except (json.JSONDecodeError, TypeError, KeyError) as error:
            raise OutputParseError(str(error), raw_output=raw_output) from error


class StructuredVerdictParser:
    def parse(self, raw_output: str) -> StructuredVerdict:
        try:
            payload = json.loads(extract_first_json_object(raw_output))
            if not isinstance(payload, dict):
                raise TypeError("verdict must be an object")
            require_exact_keys(payload, STRUCTURED_VERDICT_FIELDS, "verdict")
            decision = require_string(payload, "decision")
            if decision not in VERDICT_DECISIONS:
                raise ValueError(f"Unknown verdict decision: {decision}")
            return StructuredVerdict(
                summary=require_string(payload, "summary"),
                decision=decision,
                findings=parse_verdict_items(payload, "findings"),
                risks=parse_verdict_items(payload, "risks"),
                recommendation=require_string(payload, "recommendation"),
                conditions=parse_strings(payload, "conditions"),
                unresolved_questions=parse_strings(payload, "unresolved_questions"),
            )
        except (json.JSONDecodeError, TypeError, KeyError, ValueError) as error:
            raise OutputParseError(str(error), raw_output=raw_output) from error


class CourtroomIssueDraftParser:
    def parse(self, raw_output: str) -> dict[str, Any]:
        try:
            payload = json.loads(extract_first_json_object(raw_output))
            if not isinstance(payload, dict):
                raise TypeError("courtroom issue draft must be an object")
            require_exact_keys(payload, {"issues"}, "courtroom issue draft")
            issues = payload["issues"]
            if not isinstance(issues, list) or not issues:
                raise TypeError("issues must be a non-empty list")
            normalized = []
            seen_titles: set[str] = set()
            for issue in issues:
                if not isinstance(issue, dict):
                    raise TypeError("courtroom issue must be an object")
                require_exact_keys(issue, {"title"}, "courtroom issue")
                title = require_string(issue, "title").strip()
                if not title:
                    raise ValueError("courtroom issue title must not be blank")
                if title in seen_titles:
                    raise ValueError("courtroom issue titles must be unique")
                seen_titles.add(title)
                normalized.append({"title": title})
            return {"issues": normalized}
        except (json.JSONDecodeError, TypeError, KeyError, ValueError) as error:
            raise OutputParseError(str(error), raw_output=raw_output) from error


COURTROOM_RULING_OUTCOMES = {
    "proponent-wins",
    "respondent-wins",
    "partially-upheld",
    "insufficient-evidence",
}


class CourtroomRulingParser:
    def parse(self, raw_output: str) -> dict[str, Any]:
        try:
            payload = json.loads(extract_first_json_object(raw_output))
            if not isinstance(payload, dict):
                raise TypeError("courtroom ruling must be an object")
            require_exact_keys(
                payload,
                {"outcome", "reasoning", "evidence_refs", "unresolved_questions"},
                "courtroom ruling",
            )
            outcome = require_string(payload, "outcome")
            if outcome not in COURTROOM_RULING_OUTCOMES:
                raise ValueError(f"Unknown courtroom ruling outcome: {outcome}")
            evidence_refs = parse_strings(payload, "evidence_refs")
            for evidence_ref in evidence_refs:
                if EVIDENCE_REF_PATTERN.fullmatch(evidence_ref) is None:
                    raise ValueError(f"Invalid evidence ref: {evidence_ref}")
            return {
                "outcome": outcome,
                "reasoning": require_string(payload, "reasoning"),
                "evidence_refs": evidence_refs,
                "unresolved_questions": parse_strings(payload, "unresolved_questions"),
            }
        except (json.JSONDecodeError, TypeError, KeyError, ValueError) as error:
            raise OutputParseError(str(error), raw_output=raw_output) from error


def _validated_evidence_refs(payload: dict[str, Any]) -> list[str]:
    evidence_refs = parse_strings(payload, "evidence_refs")
    for evidence_ref in evidence_refs:
        if EVIDENCE_REF_PATTERN.fullmatch(evidence_ref) is None:
            raise ValueError(f"Invalid evidence ref: {evidence_ref}")
    return evidence_refs


class CourtroomCivilFinalParser:
    def parse(self, raw_output: str) -> dict[str, Any]:
        try:
            payload = json.loads(extract_first_json_object(raw_output))
            if not isinstance(payload, dict):
                raise TypeError("civil final verdict must be an object")
            require_exact_keys(
                payload, {"summary", "claims", "unresolved_questions"}, "civil final verdict"
            )
            claims = payload["claims"]
            if not isinstance(claims, list):
                raise TypeError("claims must be a list")
            normalized = []
            for claim in claims:
                if not isinstance(claim, dict):
                    raise TypeError("civil claim must be an object")
                require_exact_keys(
                    claim,
                    {"claim", "outcome", "reasoning", "evidence_refs", "relief"},
                    "civil claim",
                )
                outcome = require_string(claim, "outcome")
                if outcome not in {"upheld", "partially-upheld", "rejected", "insufficient-evidence"}:
                    raise ValueError(f"Unknown civil outcome: {outcome}")
                refs = _validated_evidence_refs(claim)
                relief = claim["relief"]
                if not isinstance(relief, dict):
                    raise TypeError("relief must be an object")
                require_exact_keys(
                    relief, {"obligation", "monetary_amount", "calculation_basis"}, "civil relief"
                )
                amount = relief["monetary_amount"]
                basis = relief["calculation_basis"]
                if amount is not None and not isinstance(amount, str):
                    raise TypeError("monetary_amount must be a string or null")
                if basis is not None and not isinstance(basis, str):
                    raise TypeError("calculation_basis must be a string or null")
                if isinstance(amount, str) and amount.strip():
                    if not refs:
                        raise ValueError("monetary relief requires evidence refs")
                    if not isinstance(basis, str) or not basis.strip():
                        raise ValueError("monetary relief requires a calculation basis")
                normalized.append({
                    "claim": require_string(claim, "claim"),
                    "outcome": outcome,
                    "reasoning": require_string(claim, "reasoning"),
                    "evidence_refs": refs,
                    "relief": {
                        "obligation": require_string(relief, "obligation"),
                        "monetary_amount": amount,
                        "calculation_basis": basis,
                    },
                })
            return {
                "summary": require_string(payload, "summary"),
                "claims": normalized,
                "unresolved_questions": parse_strings(payload, "unresolved_questions"),
            }
        except (json.JSONDecodeError, TypeError, KeyError, ValueError) as error:
            raise OutputParseError(str(error), raw_output=raw_output) from error


class CourtroomCriminalFinalParser:
    def parse(self, raw_output: str) -> dict[str, Any]:
        try:
            payload = json.loads(extract_first_json_object(raw_output))
            if not isinstance(payload, dict):
                raise TypeError("criminal final verdict must be an object")
            require_exact_keys(
                payload,
                {"summary", "charges", "sentencing_factors", "unresolved_questions"},
                "criminal final verdict",
            )
            charges = payload["charges"]
            if not isinstance(charges, list):
                raise TypeError("charges must be a list")
            normalized = []
            for charge in charges:
                if not isinstance(charge, dict):
                    raise TypeError("criminal charge must be an object")
                require_exact_keys(
                    charge, {"charge", "decision", "reasoning", "evidence_refs"}, "criminal charge"
                )
                decision = require_string(charge, "decision")
                if decision not in {"guilty", "not-guilty", "insufficient-evidence"}:
                    raise ValueError(f"Unknown criminal decision: {decision}")
                normalized.append({
                    "charge": require_string(charge, "charge"),
                    "decision": decision,
                    "reasoning": require_string(charge, "reasoning"),
                    "evidence_refs": _validated_evidence_refs(charge),
                })
            sentencing_factors = parse_strings(payload, "sentencing_factors")
            concrete_penalty = re.compile(
                r"有期徒刑|無期徒刑|死刑|拘役|罰金|處以|宣告刑|應執行"
            )
            if any(concrete_penalty.search(factor) for factor in sentencing_factors):
                raise ValueError("sentencing_factors must not state a concrete penalty")
            return {
                "summary": require_string(payload, "summary"),
                "charges": normalized,
                "sentencing_factors": sentencing_factors,
                "unresolved_questions": parse_strings(payload, "unresolved_questions"),
            }
        except (json.JSONDecodeError, TypeError, KeyError, ValueError) as error:
            raise OutputParseError(str(error), raw_output=raw_output) from error


def extract_first_json_object(raw_output: str) -> str:
    start = raw_output.find("{")
    if start == -1:
        raise json.JSONDecodeError("No JSON object found", raw_output, 0)

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(raw_output)):
        char = raw_output[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue

        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return raw_output[start : index + 1]

    raise json.JSONDecodeError("Unterminated JSON object", raw_output, start)


def require_string(payload: dict[str, Any], key: str) -> str:
    value = payload[key]
    if not isinstance(value, str):
        raise TypeError(f"{key} must be a string")
    return value


def parse_items(payload: dict[str, Any], key: str) -> list[OutputItem]:
    value = payload[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} must be a list")
    return [parse_item(item) for item in value]


def parse_item(item: Any) -> OutputItem:
    if not isinstance(item, dict):
        raise TypeError("item must be an object")
    return OutputItem(
        title=require_string(item, "title"),
        detail=require_string(item, "detail"),
    )


def parse_strings(payload: dict[str, Any], key: str) -> list[str]:
    value = payload[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} must be a list")
    if not all(isinstance(item, str) for item in value):
        raise TypeError(f"{key} items must be strings")
    return value


def parse_verdict_items(payload: dict[str, Any], key: str) -> list[VerdictItem]:
    value = payload[key]
    if not isinstance(value, list):
        raise TypeError(f"{key} must be a list")
    return [parse_verdict_item(item) for item in value]


def parse_verdict_item(item: Any) -> VerdictItem:
    if not isinstance(item, dict):
        raise TypeError("verdict item must be an object")
    require_exact_keys(item, VERDICT_ITEM_FIELDS, "verdict item")
    evidence_refs = parse_strings(item, "evidence_refs")
    for evidence_ref in evidence_refs:
        if EVIDENCE_REF_PATTERN.fullmatch(evidence_ref) is None:
            raise ValueError(f"Invalid evidence ref: {evidence_ref}")
    return VerdictItem(
        title=require_string(item, "title"),
        detail=require_string(item, "detail"),
        evidence_refs=evidence_refs,
    )


def require_exact_keys(
    payload: dict[str, Any],
    expected: set[str],
    context: str,
) -> None:
    actual = set(payload)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        details = []
        if missing:
            details.append(f"missing {', '.join(missing)}")
        if unknown:
            details.append(f"unknown {', '.join(unknown)}")
        raise TypeError(f"{context} has invalid fields: {'; '.join(details)}")
