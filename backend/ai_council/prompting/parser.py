from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


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


class OutputParseError(ValueError):
    def __init__(self, message: str, *, raw_output: str) -> None:
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
