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
