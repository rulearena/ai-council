from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ChatroomMentionToken:
    token_id: str
    role_id: str
    display_text: str
    start: int
    end: int


@dataclass(frozen=True)
class ChatroomSourceToken:
    token_id: str
    source_ref: str
    display_text: str
    start: int
    end: int


@dataclass(frozen=True)
class ValidatedChatroomRouting:
    target_role_ids: list[str]
    instruction: str
    warnings: list[dict[str, str]]


def detail(**values: Any) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}


def rejected(code: str, field: str | None, details: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "status": "rejected",
        "error": {"code": code, "field": field, "details": details or []},
    }


def _is_xid_continue(char: str) -> bool:
    category = unicodedata.category(char)
    return char == "_" or char.isalnum() or category.startswith("M")


def _raw_role_like_spans(content: str, covered: list[tuple[int, int]]) -> list[tuple[int, int]]:
    covered_ranges = sorted(covered)
    result: list[tuple[int, int]] = []
    index = 0
    while index < len(content):
        if content[index] != "@" or any(start <= index < end for start, end in covered_ranges):
            index += 1
            continue
        previous = content[index - 1] if index else ""
        if previous and (_is_xid_continue(previous) or previous in "@.+-"):
            index += 1
            continue
        end = index + 1
        while end < len(content) and _is_xid_continue(content[end]) and end - index <= 64:
            end += 1
        if end == index + 1:
            index += 1
            continue
        following = content[end] if end < len(content) else ""
        if following == "." or (following and (_is_xid_continue(following) or following == "-")):
            index = end
            continue
        result.append((index, end))
        index = end
    return result


def _validate_token_spans(
    content: str,
    tokens: list[ChatroomMentionToken | ChatroomSourceToken],
    *,
    prefix: str,
    mismatch_code: str,
    field: str,
) -> list[tuple[int, int]]:
    seen_ids: set[str] = set()
    spans: list[tuple[int, int]] = []
    for token in tokens:
        if token.token_id in seen_ids:
            raise ValueError(rejected(mismatch_code, field))
        seen_ids.add(token.token_id)
        if (
            token.start < 0
            or token.end <= token.start
            or token.end > len(content)
            or not token.display_text.startswith(prefix)
            or content[token.start : token.end] != token.display_text
        ):
            raise ValueError(rejected(mismatch_code, field, [detail(
                token_id=token.token_id,
                display_text=token.display_text,
                start=token.start,
                end=token.end,
            )]))
        spans.append((token.start, token.end))
    ordered = sorted(spans)
    if any(previous_end > start for (_, previous_end), (start, _) in zip(ordered, ordered[1:])):
        raise ValueError(rejected(mismatch_code, field))
    return spans


def validate_chatroom_routing(
    *,
    content: str,
    mentions: list[ChatroomMentionToken],
    source_tokens: list[ChatroomSourceToken],
    source_refs: list[str],
    active_role_ids: list[str],
    role_display_names: dict[str, str],
) -> ValidatedChatroomRouting:
    if content != unicodedata.normalize("NFC", content) or not content.strip():
        raise ValueError(rejected("INVALID_REQUEST_SCHEMA", "content"))

    mention_spans = _validate_token_spans(
        content, mentions, prefix="@", mismatch_code="MENTION_TOKEN_MISMATCH", field="mentions"
    )
    source_spans = _validate_token_spans(
        content, source_tokens, prefix="#", mismatch_code="SOURCE_TOKEN_MISMATCH", field="source_tokens"
    )
    if len({token.token_id for token in [*mentions, *source_tokens]}) != len(mentions) + len(source_tokens):
        raise ValueError(rejected("MENTION_TOKEN_MISMATCH", "mentions"))
    all_spans = sorted([*mention_spans, *source_spans])
    if any(previous_end > start for (_, previous_end), (start, _) in zip(all_spans, all_spans[1:])):
        raise ValueError(rejected("MENTION_TOKEN_MISMATCH", "mentions"))
    if source_refs != list(dict.fromkeys(token.source_ref for token in source_tokens)):
        raise ValueError(rejected("STALE_SOURCE_PAYLOAD", "source_refs"))
    for token in mentions:
        if token.role_id not in set(active_role_ids) | {"all"}:
            raise ValueError(rejected("STALE_MENTION_PAYLOAD", "mentions", [detail(
                token_id=token.token_id, role_id=token.role_id, display_text=token.display_text
            )]))
        expected = "@全部角色" if token.role_id == "all" else f"@{role_display_names[token.role_id]}"
        if token.display_text != expected:
            raise ValueError(rejected("STALE_MENTION_PAYLOAD", "mentions", [detail(
                token_id=token.token_id, role_id=token.role_id, display_text=token.display_text
            )]))

    all_selected = any(token.role_id == "all" for token in mentions)
    raw_spans = _raw_role_like_spans(content, mention_spans + source_spans)
    warnings: list[dict[str, str]] = []
    if raw_spans and not all_selected:
        start, end = raw_spans[0]
        raise ValueError(
            rejected(
                "INVALID_MENTION_TOKEN",
                "content",
                [detail(display_text=content[start:end], start=start, end=end)],
            )
        )
    if all_selected:
        warnings = [
            {"code": "IGNORED_INVALID_MENTION", "display_text": content[start:end]}
            for start, end in raw_spans
        ]

    if all_selected:
        target_role_ids = list(active_role_ids)
    else:
        target_role_ids = list(dict.fromkeys(token.role_id for token in mentions))
        if not target_role_ids:
            target_role_ids = ["host"]

    hidden_ranges = sorted(mention_spans + source_spans)
    instruction_parts: list[str] = []
    cursor = 0
    for start, end in hidden_ranges:
        instruction_parts.append(content[cursor:start])
        cursor = end
    instruction_parts.append(content[cursor:])
    instruction = "".join(instruction_parts).strip()
    return ValidatedChatroomRouting(target_role_ids, instruction, warnings)
