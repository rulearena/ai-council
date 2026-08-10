from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class ChatroomPromptPlan:
    prior_transcript: str
    source_snapshot: dict[str, Any]
    source_allow_list: str


class ChatroomPromptPlanError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def plan_chatroom_prompt(
    *,
    request_budget_tokens: int,
    target_role_ids: list[str],
    source_refs: list[str],
    selected_sources: list[dict[str, Any]],
    active_events: list[dict[str, Any]],
    goal: str,
    instruction: str,
    quoted_event_id: str | None,
    prompt_budget_for: Callable[[str, str, str], int],
    build_context: Callable[[list[dict[str, Any]], str, str, str | None, int], str],
    build_snapshot: Callable[[int], dict[str, Any]],
    source_allow_list_for: Callable[[list[dict[str, Any]]], str],
) -> ChatroomPromptPlan:
    """Compute one request/fanout prompt envelope from actual frozen refs.

    The planner deliberately does not read storage or append events.  It
    iterates fixed prompt reservation, transcript eviction, and selected-source
    retrieval until the source segment allow-list is stable, so callers can
    reuse the returned envelope for every target and automatic retry.
    """
    source_allow_list = source_allow_list_for(selected_sources)

    def fixed_budget(prior_transcript: str) -> int:
        if not target_role_ids:
            return 0
        return max(
            prompt_budget_for(role, prior_transcript, source_allow_list)
            for role in target_role_ids
        )

    prior_transcript = ""
    if not source_refs:
        for _ in range(2):
            fixed = fixed_budget(prior_transcript)
            if fixed >= request_budget_tokens:
                raise ChatroomPromptPlanError("CHATROOM_PROMPT_TOO_LARGE")
            prior_transcript = build_context(
                active_events, goal, instruction, quoted_event_id, fixed + 32
            )
        return ChatroomPromptPlan(
            prior_transcript=prior_transcript,
            source_snapshot={
                "selected_source_snapshot": {
                    "schema_version": "chatroom-source-context/v1",
                    "source_refs": [],
                    "sources": [],
                },
                "source_excerpts": [],
            },
            source_allow_list="",
        )

    snapshot: dict[str, Any] = {
        "selected_source_snapshot": {
            "schema_version": "chatroom-source-context/v1",
            "source_refs": list(source_refs),
            "sources": [],
        },
        "source_excerpts": [],
    }
    previous_signature: tuple[tuple[str, ...], ...] | None = None
    for _ in range(8):
        fixed = fixed_budget(prior_transcript)
        if fixed >= request_budget_tokens:
            raise ChatroomPromptPlanError("SOURCE_CONTEXT_TOO_LARGE")
        snapshot = build_snapshot(max(0, request_budget_tokens - fixed - 32) * 4)
        snapshot_sources = snapshot["selected_source_snapshot"]["sources"]
        source_allow_list = source_allow_list_for(snapshot_sources)
        prior_transcript = build_context(
            active_events,
            goal,
            instruction,
            quoted_event_id,
            fixed_budget("") + 32,
        )
        signature = tuple(
            tuple(str(ref) for ref in item.get("available_segment_refs", []))
            for item in snapshot_sources
        )
        if signature == previous_signature:
            break
        previous_signature = signature
    return ChatroomPromptPlan(
        prior_transcript=prior_transcript,
        source_snapshot=snapshot,
        source_allow_list=source_allow_list,
    )
