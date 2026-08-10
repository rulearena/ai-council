from __future__ import annotations

import pytest

from ai_council.meetings.chatroom_prompt_planning import (
    ChatroomPromptPlanError,
    plan_chatroom_prompt,
)


def test_planner_uses_actual_frozen_segment_allow_list() -> None:
    snapshot_calls: list[int] = []

    def build_snapshot(source_char_budget: int) -> dict:
        snapshot_calls.append(source_char_budget)
        return {
            "selected_source_snapshot": {
                "schema_version": "chatroom-source-context/v1",
                "source_refs": ["evidence:source-1"],
                "sources": [{
                    "source_ref": "evidence:source-1",
                    "available_segment_refs": [
                        "paragraph:0001",
                        "paragraph:0002",
                        "paragraph:0003",
                    ],
                }],
            },
            "source_excerpts": [],
        }

    plan = plan_chatroom_prompt(
        request_budget_tokens=1050,
        target_role_ids=["host"],
        source_refs=["evidence:source-1"],
        selected_sources=[{
            "source_ref": "evidence:source-1",
            "available_segment_refs": ["full"],
        }],
        active_events=[],
        goal="answer",
        instruction="use the source",
        quoted_event_id=None,
        prompt_budget_for=lambda _role, _transcript, allow_list, retry: (
            100 + len(allow_list) + len(retry)
        ),
        build_context=lambda *_args: "prior",
        build_snapshot=build_snapshot,
        source_allow_list_for=lambda sources: ",".join(
            ref for source in sources for ref in source["available_segment_refs"]
        ),
        retry_feedback_for=lambda sources: "retry:" + ",".join(
            ref for source in sources for ref in source["available_segment_refs"]
        ),
    )

    assert snapshot_calls
    assert plan.source_snapshot["selected_source_snapshot"]["sources"][0][
        "available_segment_refs"
    ] == ["paragraph:0001", "paragraph:0002", "paragraph:0003"]
    assert "paragraph:0001" in plan.source_allow_list
    assert "full" not in plan.source_allow_list


def test_planner_fails_safe_when_fixed_retry_envelope_cannot_fit() -> None:
    with pytest.raises(ChatroomPromptPlanError) as raised:
        plan_chatroom_prompt(
            request_budget_tokens=1050,
            target_role_ids=["host"],
            source_refs=["evidence:source-1"],
            selected_sources=[{"source_ref": "evidence:source-1"}],
            active_events=[],
            goal="answer",
            instruction="use the source",
            quoted_event_id=None,
            prompt_budget_for=lambda *_args: 1050,
            build_context=lambda *_args: "prior",
            build_snapshot=lambda _budget: {
                "selected_source_snapshot": {"sources": []},
                "source_excerpts": [],
            },
            source_allow_list_for=lambda _sources: "",
            retry_feedback_for=lambda _sources: "",
        )

    assert raised.value.code == "SOURCE_CONTEXT_TOO_LARGE"
