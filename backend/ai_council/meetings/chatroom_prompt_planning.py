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
    prompt_tokens_for: Callable[[str, str, str, str], int],
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

    def fixed_budget(prior_transcript: str, allow_list: str) -> int:
        if not target_role_ids:
            return 0
        return max(
            prompt_budget_for(role, prior_transcript, allow_list)
            for role in target_role_ids
        )

    prior_transcript = ""

    def stable_context(allow_list: str) -> str:
        nonlocal prior_transcript
        for _ in range(8):
            fixed = fixed_budget(prior_transcript, allow_list)
            next_transcript = build_context(
                active_events, goal, instruction, quoted_event_id, fixed + 32
            )
            if next_transcript == prior_transcript:
                break
            prior_transcript = next_transcript
        return prior_transcript

    def prompt_costs(source_context: str, allow_list: str) -> tuple[str, int]:
        transcript = stable_context(allow_list)
        if fixed_budget(transcript, allow_list) >= request_budget_tokens:
            return transcript, request_budget_tokens + 1
        return transcript, max(
            prompt_tokens_for(role, transcript, source_context, allow_list)
            for role in target_role_ids
        )

    if not source_refs:
        for _ in range(8):
            fixed = fixed_budget(prior_transcript, source_allow_list)
            if fixed >= request_budget_tokens:
                raise ChatroomPromptPlanError("CHATROOM_PROMPT_TOO_LARGE")
            prior_transcript = build_context(active_events, goal, instruction, quoted_event_id, fixed + 32)
        _, prompt_tokens = prompt_costs("", "")
        if prompt_tokens > request_budget_tokens:
            raise ChatroomPromptPlanError("CHATROOM_PROMPT_TOO_LARGE")
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
    # The full snapshot gives an exact search upper bound in characters.  The
    # fitting predicate is the canonical full-message estimator, not a
    # chars-per-token conversion; this remains valid for CJK, emoji, and
    # mixed-language source bodies.
    full_snapshot = build_snapshot(2**31 - 1)
    full_context = "\n\n".join(str(item) for item in full_snapshot.get("source_excerpts", []))
    high = len(full_context)
    best: tuple[dict[str, Any], str, str] | None = None
    low = 0
    while low <= high:
        candidate_chars = (low + high) // 2
        candidate = build_snapshot(candidate_chars)
        candidate_sources = candidate["selected_source_snapshot"]["sources"]
        candidate_allow_list = source_allow_list_for(candidate_sources)
        candidate_context = "\n\n".join(
            str(item) for item in candidate.get("source_excerpts", [])
        )
        prior_transcript, prompt_tokens = prompt_costs(
            candidate_context, candidate_allow_list
        )
        if prompt_tokens <= request_budget_tokens:
            best = (candidate, prior_transcript, candidate_allow_list)
            low = candidate_chars + 1
        else:
            high = candidate_chars - 1
    if best is None:
        raise ChatroomPromptPlanError("SOURCE_CONTEXT_TOO_LARGE")
    snapshot, prior_transcript, source_allow_list = best
    source_context = "\n\n".join(
        str(item) for item in snapshot.get("source_excerpts", [])
    )
    final_prompt_tokens = max(
        prompt_tokens_for(
            role, prior_transcript, source_context, source_allow_list
        )
        for role in target_role_ids
    )
    if final_prompt_tokens > request_budget_tokens:
        raise ChatroomPromptPlanError("SOURCE_CONTEXT_TOO_LARGE")
    return ChatroomPromptPlan(
        prior_transcript=prior_transcript,
        source_snapshot=snapshot,
        source_allow_list=source_allow_list,
    )
