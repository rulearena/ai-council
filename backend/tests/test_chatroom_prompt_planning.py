from __future__ import annotations

import pytest

from ai_council.meetings.chatroom_prompt_planning import (
    ChatroomPromptPlanError,
    plan_chatroom_prompt,
)
from ai_council.meetings.chatroom_context import estimate_prompt_tokens


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
        prompt_budget_for=lambda _role, _transcript, allow_list: 100 + len(allow_list),
        prompt_tokens_for=lambda _role, _transcript, source_context, allow_list: (
            100 + len(source_context) + len(allow_list)
        ),
        build_context=lambda *_args: "prior",
        build_snapshot=build_snapshot,
        source_allow_list_for=lambda sources: ",".join(
            ref for source in sources for ref in source["available_segment_refs"]
        ),
    )

    assert snapshot_calls
    assert plan.source_snapshot["selected_source_snapshot"]["sources"][0][
        "available_segment_refs"
    ] == ["paragraph:0001", "paragraph:0002", "paragraph:0003"]
    assert "paragraph:0001" in plan.source_allow_list
    assert "full" not in plan.source_allow_list


def test_planner_fails_safe_when_fixed_prompt_cannot_fit() -> None:
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
            prompt_tokens_for=lambda *_args: 1051,
            build_context=lambda *_args: "prior",
            build_snapshot=lambda _budget: {
                "selected_source_snapshot": {"sources": []},
                "source_excerpts": [],
            },
            source_allow_list_for=lambda _sources: "",
        )

    assert raised.value.code == "SOURCE_CONTEXT_TOO_LARGE"


@pytest.mark.parametrize(
    "body",
    [
        "漢" * 12000,
        "ASCII " * 2000 + "漢字🙂" * 2000,
        "第一段：" + "內容" * 4000,
        "\n".join(f"段落 {i:03d}：" + "證據" * 250 for i in range(40)),
    ],
    ids=["cjk", "mixed-emoji-cjk-ascii", "long-single-paragraph", "multi-paragraph"],
)
def test_planner_fits_actual_source_text_with_canonical_prompt_cost(body: str) -> None:
    snapshots: list[int] = []

    def build_snapshot(char_budget: int) -> dict:
        snapshots.append(char_budget)
        excerpt = body[:char_budget]
        return {
            "selected_source_snapshot": {
                "source_refs": ["evidence:source-1"],
                "sources": [{
                    "source_ref": "evidence:source-1",
                    "label": "來源",
                    "available_segment_refs": ["full"] if len(excerpt) == len(body) else ["paragraph:0001"],
                }],
            },
            "source_excerpts": [excerpt] if excerpt else [],
        }

    plan = plan_chatroom_prompt(
        request_budget_tokens=1050,
        target_role_ids=["host", "Advisor"],
        source_refs=["evidence:source-1"],
        selected_sources=[{"source_ref": "evidence:source-1"}],
        active_events=[],
        goal="目標",
        instruction="請使用來源",
        quoted_event_id=None,
        prompt_budget_for=lambda _role, _transcript, allow_list: estimate_prompt_tokens([
            {"role": "system", "content": "固定" * 600},
            {"role": "developer", "content": allow_list},
        ]),
        prompt_tokens_for=lambda _role, _transcript, source_context, allow_list: estimate_prompt_tokens([
            {"role": "system", "content": "固定" * 600},
            {"role": "user", "content": source_context},
            {"role": "developer", "content": allow_list},
        ]),
        build_context=lambda *_args: "近期對話",
        build_snapshot=build_snapshot,
        source_allow_list_for=lambda sources: ",".join(
            ref for source in sources for ref in source.get("available_segment_refs", [])
        ),
    )

    assert snapshots
    source_context = "\n\n".join(plan.source_snapshot["source_excerpts"])
    actual = estimate_prompt_tokens([
        {"role": "system", "content": "固定" * 600},
        {"role": "user", "content": source_context},
        {"role": "developer", "content": plan.source_allow_list},
    ])
    assert actual <= 1050
