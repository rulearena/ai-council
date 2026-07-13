from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_council.meetings.repository import MeetingRepository
from ai_council.meetings.runner import (
    MeetingRunner,
    ParallelMemberStep,
    ParallelPlan,
    RelayPlan,
    RunnerAdapters,
    StepDefinition,
)
from ai_council.models.adapters import AdapterError, ModelRequest, ModelResponse
from ai_council.models.config import ModelConfig
from ai_council.prompting.renderer import PromptRenderer


VALID_OUTPUT = json.dumps(
    {
        "summary": "OK",
        "arguments": [],
        "risks": [],
        "recommendation": "Continue",
    }
)
TEST_PROMPT_TEMPLATE_HASHES = {
    "blue_propose": "81abba70bd2c176005a3fd28dd13ef9bda68f441de574976e8d7161e23fb5f9d",
    "red_critique": "604dfa9b918ab543afbde7e2098e0eb560967abb658c3ef9e06534bf37dcfb24",
    "blue_revise": "572aea2442be4b659e3cd7f4d02afc1b6e9ae485a2b1972dc40757c0fa64e06e",
    "judge_decide": "b804a5f1bb3893a45854d48085dc2ffc8496e9b61819c4a4c31ea4192b847e25",
}
TEST_OUTPUT_SCHEMA_HASH = "15a45919652be5c70d3fd1690a10d37f876f19a14b2a76cc0f21765def281377"

RED_BLUE_PLAN = RelayPlan(
    steps=[
        StepDefinition("blue-propose", "Blue", "blue_propose"),
        StepDefinition("red-critique", "Red", "red_critique"),
        StepDefinition("blue-revise", "Blue", "blue_revise"),
        StepDefinition("judge-decide", "Judge", "judge_decide"),
    ],
    directed_steps={
        "Blue": StepDefinition("blue-response", "Blue", "blue_revise"),
        "Red": StepDefinition("red-response", "Red", "red_critique"),
        "Judge": StepDefinition("judge-response", "Judge", "judge_decide"),
    },
)

COURTROOM_PLAN = RelayPlan(
    steps=[
        StepDefinition("courtroom-charge", "Prosecutor", "courtroom_charge"),
        StepDefinition("courtroom-defense", "Defense", "courtroom_defense"),
        StepDefinition("courtroom-rebuttal", "Prosecutor", "courtroom_rebuttal"),
        StepDefinition("courtroom-verdict", "Judge", "courtroom_verdict"),
    ],
    directed_steps={
        "Prosecutor": StepDefinition("prosecutor-response", "Prosecutor", "courtroom_rebuttal"),
        "Defense": StepDefinition("defense-response", "Defense", "courtroom_defense"),
        "Judge": StepDefinition("judge-response", "Judge", "courtroom_verdict"),
    },
)

PARALLEL_PLAN = ParallelPlan(
    members=[
        ParallelMemberStep(
            step_id="member-1",
            role="Member-1",
            template_name="brainstorm_member",
            display_name="委員 1",
            instance_prompt="成本視角",
            index=1,
        ),
        ParallelMemberStep(
            step_id="member-2",
            role="Member-2",
            template_name="brainstorm_member",
            display_name="委員 2",
            instance_prompt="使用者視角",
            index=2,
        ),
        ParallelMemberStep(
            step_id="member-3",
            role="Member-3",
            template_name="brainstorm_member",
            display_name="委員 3",
            instance_prompt="營運視角",
            index=3,
        ),
    ],
    synthesis=StepDefinition("synthesis", "Moderator", "brainstorm_synthesis"),
)


def test_runner_completes_fixed_red_blue_judge_flow(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, adapter=FakeAdapter([VALID_OUTPUT] * 4))

    runner.start(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        topic="先做後端？",
        model_assignments={
            "Blue": ModelConfig(id="mock-blue", adapter="mock"),
            "Red": ModelConfig(id="mock-red", adapter="mock"),
            "Judge": ModelConfig(id="mock-judge", adapter="mock"),
        },
    )

    events = runner.repository.read_events("meeting-1")
    completed_steps = [event for event in events if event["status"] == "completed"]
    assert [event["step_id"] for event in completed_steps] == [
        "blue-propose",
        "red-critique",
        "blue-revise",
        "judge-decide",
    ]
    assert [event["attempt"] for event in completed_steps] == [1, 1, 1, 1]
    assert completed_steps[0]["parsed_output"]["summary"] == "OK"


def test_runner_persists_model_token_usage_on_completed_events(tmp_path: Path) -> None:
    runner = build_runner(
        tmp_path,
        adapter=FakeAdapter(
            [VALID_OUTPUT],
            token_usage={"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
        ),
    )

    runner.respond_as_role(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        topic="先做後端？",
        role="Blue",
        model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
    )

    event = runner.repository.read_events("meeting-1")[-1]
    assert event["token_usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 8,
        "total_tokens": 20,
    }


def test_runner_persists_prompt_metadata_on_completed_events(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, adapter=FakeAdapter([VALID_OUTPUT]))

    runner.respond_as_role(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        topic="先做後端？",
        role="Blue",
        model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
    )

    event = runner.repository.read_events("meeting-1")[-1]
    assert event["prompt_template_name"] == "blue_revise"
    assert event["prompt_template_hash"] == TEST_PROMPT_TEMPLATE_HASHES["blue_revise"]
    assert event["output_schema_hash"] == TEST_OUTPUT_SCHEMA_HASH


def test_runner_persists_prompt_metadata_on_failed_events(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, adapter=FailingAdapter())

    runner.respond_as_role(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        topic="先做後端？",
        role="Red",
        model_assignments={"Red": ModelConfig(id="mock-red", adapter="mock")},
    )

    event = runner.repository.read_events("meeting-1")[-1]
    assert event["status"] == "failed"
    assert event["prompt_template_name"] == "red_critique"
    assert event["prompt_template_hash"] == TEST_PROMPT_TEMPLATE_HASHES["red_critique"]
    assert event["output_schema_hash"] == TEST_OUTPUT_SCHEMA_HASH


def test_runner_persists_prompt_template_names_for_fixed_flow(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, adapter=FakeAdapter([VALID_OUTPUT] * 4))

    runner.start(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        topic="先做後端？",
        model_assignments={
            "Blue": ModelConfig(id="mock-blue", adapter="mock"),
            "Red": ModelConfig(id="mock-red", adapter="mock"),
            "Judge": ModelConfig(id="mock-judge", adapter="mock"),
        },
    )

    events = runner.repository.read_events("meeting-1")
    assert [event["prompt_template_name"] for event in events] == [
        "blue_propose",
        "red_critique",
        "blue_revise",
        "judge_decide",
    ]
    assert [event["prompt_template_hash"] for event in events] == [
        TEST_PROMPT_TEMPLATE_HASHES["blue_propose"],
        TEST_PROMPT_TEMPLATE_HASHES["red_critique"],
        TEST_PROMPT_TEMPLATE_HASHES["blue_revise"],
        TEST_PROMPT_TEMPLATE_HASHES["judge_decide"],
    ]
    assert {event["output_schema_hash"] for event in events} == {TEST_OUTPUT_SCHEMA_HASH}


def test_runner_start_resumes_from_first_incomplete_step_after_restart(tmp_path: Path) -> None:
    adapter = FakeAdapter([VALID_OUTPUT] * 3)
    runner = build_runner(tmp_path, adapter=adapter)
    runner.repository.append_event(
        "meeting-1",
        {
            "event_id": "meeting-1:blue-propose:attempt-1:completed",
            "meeting_id": "meeting-1",
            "step_id": "blue-propose",
            "base_step_id": "blue-propose",
            "round": 1,
            "role": "Blue",
            "attempt": 1,
            "model_config_id": "mock-blue",
            "parsed_output": json.loads(VALID_OUTPUT),
            "status": "completed",
        },
    )

    runner.start(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        topic="先做後端？",
        model_assignments={
            "Blue": ModelConfig(id="mock-blue", adapter="mock"),
            "Red": ModelConfig(id="mock-red", adapter="mock"),
            "Judge": ModelConfig(id="mock-judge", adapter="mock"),
        },
    )

    events = runner.repository.read_events("meeting-1")
    completed_steps = [event for event in events if event["status"] == "completed"]
    assert [event["step_id"] for event in completed_steps] == [
        "blue-propose",
        "red-critique",
        "blue-revise",
        "judge-decide",
    ]
    assert [request.model_config.id for request in adapter.requests] == [
        "mock-red",
        "mock-blue",
        "mock-judge",
    ]


def test_runner_start_defers_to_explicit_retry_when_a_step_already_failed(
    tmp_path: Path,
) -> None:
    adapter = FakeAdapter([VALID_OUTPUT] * 4)
    runner = build_runner(tmp_path, adapter=adapter)
    runner.repository.append_event(
        "meeting-1",
        {
            "event_id": "meeting-1:blue-propose:attempt-1:completed",
            "meeting_id": "meeting-1",
            "step_id": "blue-propose",
            "base_step_id": "blue-propose",
            "round": 1,
            "role": "Blue",
            "attempt": 1,
            "model_config_id": "mock-blue",
            "parsed_output": json.loads(VALID_OUTPUT),
            "status": "completed",
        },
    )
    runner.repository.append_event(
        "meeting-1",
        {
            "event_id": "meeting-1:red-critique:attempt-1:failed",
            "meeting_id": "meeting-1",
            "step_id": "red-critique",
            "base_step_id": "red-critique",
            "round": 1,
            "role": "Red",
            "attempt": 1,
            "status": "failed",
            "error": "adapter boom",
        },
    )

    runner.start(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        topic="先做後端？",
        model_assignments={
            "Blue": ModelConfig(id="mock-blue", adapter="mock"),
            "Red": ModelConfig(id="mock-red", adapter="mock"),
            "Judge": ModelConfig(id="mock-judge", adapter="mock"),
        },
    )

    assert adapter.requests == []
    events = runner.repository.read_events("meeting-1")
    assert len(events) == 2


def test_runner_starts_follow_up_round_after_human_feedback(tmp_path: Path) -> None:
    adapter = FakeAdapter([VALID_OUTPUT] * 8)
    runner = build_runner(tmp_path, adapter=adapter)
    model_assignments = {
        "Blue": ModelConfig(id="mock-blue", adapter="mock"),
        "Red": ModelConfig(id="mock-red", adapter="mock"),
        "Judge": ModelConfig(id="mock-judge", adapter="mock"),
    }
    runner.start(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        topic="先做後端？",
        model_assignments=model_assignments,
    )
    runner.repository.append_event(
        "meeting-1",
        {
            "event_id": "human-feedback",
            "meeting_id": "meeting-1",
            "step_id": "human-message",
            "role": "Human",
            "attempt": 1,
            "status": "completed",
            "content": "主席補充：第二輪要限制在一週內完成。",
        },
    )

    runner.start(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        topic="先做後端？",
        model_assignments=model_assignments,
    )

    events = runner.repository.read_events("meeting-1")
    completed_steps = [
        event["step_id"]
        for event in events
        if event["status"] == "completed" and event["role"] != "Human"
    ]
    assert completed_steps == [
        "blue-propose",
        "red-critique",
        "blue-revise",
        "judge-decide",
        "round-2-blue-propose",
        "round-2-red-critique",
        "round-2-blue-revise",
        "round-2-judge-decide",
    ]
    assert "主席補充：第二輪要限制在一週內完成。" in adapter.requests[4].prompt


def test_runner_runs_single_chair_directed_role_response(tmp_path: Path) -> None:
    adapter = FakeAdapter([VALID_OUTPUT])
    runner = build_runner(tmp_path, adapter=adapter)
    runner.repository.append_event(
        "meeting-1",
        {
            "event_id": "human-feedback",
            "meeting_id": "meeting-1",
            "step_id": "human-message",
            "role": "Human",
            "attempt": 1,
            "status": "completed",
            "content": "主席要求：Blue 只回應最小可行方案。",
        },
    )

    runner.respond_as_role(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        topic="先做後端？",
        role="Blue",
        model_assignments={
            "Blue": ModelConfig(id="mock-blue", adapter="mock"),
        },
    )

    events = runner.repository.read_events("meeting-1")
    response_event = events[-1]
    assert response_event["step_id"] == "directed-1-blue-response"
    assert response_event["base_step_id"] == "blue-response"
    assert response_event["interaction_type"] == "directed-role-response"
    assert response_event["directed_sequence"] == 1
    assert response_event["role"] == "Blue"
    assert "主席要求：Blue 只回應最小可行方案。" in adapter.requests[0].prompt


def test_runner_runs_chair_directed_role_sequence(tmp_path: Path) -> None:
    adapter = FakeAdapter([VALID_OUTPUT] * 3)
    runner = build_runner(tmp_path, adapter=adapter)
    runner.repository.append_event(
        "meeting-1",
        {
            "event_id": "human-feedback",
            "meeting_id": "meeting-1",
            "step_id": "human-message",
            "role": "Human",
            "attempt": 1,
            "status": "completed",
            "content": "主席要求：Red 先挑戰，再由 Blue 修正，最後 Judge 裁決。",
        },
    )

    runner.respond_as_sequence(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        topic="先做後端？",
        roles=["Red", "Blue", "Judge"],
        model_assignments={
            "Blue": ModelConfig(id="mock-blue", adapter="mock"),
            "Red": ModelConfig(id="mock-red", adapter="mock"),
            "Judge": ModelConfig(id="mock-judge", adapter="mock"),
        },
    )

    completed = [
        event for event in runner.repository.read_events("meeting-1")
        if event["status"] == "completed" and event["role"] != "Human"
    ]
    assert [event["step_id"] for event in completed] == [
        "sequence-1-red-response",
        "sequence-1-blue-response",
        "sequence-1-judge-response",
    ]
    assert [event["role"] for event in completed] == ["Red", "Blue", "Judge"]
    assert {event["interaction_type"] for event in completed} == {"role-sequence-response"}
    assert {event["sequence"] for event in completed} == {1}
    assert [event["sequence_index"] for event in completed] == [1, 2, 3]
    assert "主席要求：Red 先挑戰" in adapter.requests[0].prompt


def test_runner_marks_step_failed_when_adapter_raises(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, adapter=FailingAdapter())

    runner.start(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        topic="先做後端？",
        model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
    )

    events = runner.repository.read_events("meeting-1")
    assert events[-1]["step_id"] == "blue-propose"
    assert events[-1]["status"] == "failed"
    assert "adapter boom" in events[-1]["error"]


def test_runner_marks_step_failed_when_output_cannot_be_parsed(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, adapter=FakeAdapter(["not json"]))

    runner.start(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        topic="先做後端？",
        model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
    )

    events = runner.repository.read_events("meeting-1")
    assert events[-1]["step_id"] == "blue-propose"
    assert events[-1]["status"] == "failed"
    assert events[-1]["error"]


def test_runner_retry_failed_step_creates_second_attempt_and_continues(
    tmp_path: Path,
) -> None:
    runner = build_runner(tmp_path, adapter=FakeAdapter([VALID_OUTPUT] * 4))
    runner.repository.append_event(
        "meeting-1",
        {
            "event_id": "old-failure",
            "meeting_id": "meeting-1",
            "step_id": "blue-propose",
            "role": "Blue",
            "attempt": 1,
            "status": "failed",
            "error": "bad JSON",
        },
    )

    runner.retry_failed_step(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        step_id="blue-propose",
        topic="先做後端？",
        model_assignments={
            "Blue": ModelConfig(id="mock-blue", adapter="mock"),
            "Red": ModelConfig(id="mock-red", adapter="mock"),
            "Judge": ModelConfig(id="mock-judge", adapter="mock"),
        },
    )

    events = runner.repository.read_events("meeting-1")
    completed = [event for event in events if event["status"] == "completed"]
    assert completed[0]["step_id"] == "blue-propose"
    assert completed[0]["attempt"] == 2
    assert [event["step_id"] for event in completed] == [
        "blue-propose",
        "red-critique",
        "blue-revise",
        "judge-decide",
    ]


def test_runner_retries_round_scoped_failed_step(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, adapter=FakeAdapter([VALID_OUTPUT] * 3))
    runner.repository.append_event(
        "meeting-1",
        {
            "event_id": "round-2-failure",
            "meeting_id": "meeting-1",
            "step_id": "round-2-red-critique",
            "base_step_id": "red-critique",
            "round": 2,
            "role": "Red",
            "attempt": 1,
            "status": "failed",
            "error": "bad JSON",
        },
    )

    runner.retry_failed_step(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        step_id="round-2-red-critique",
        topic="先做後端？",
        model_assignments={
            "Red": ModelConfig(id="mock-red", adapter="mock"),
            "Blue": ModelConfig(id="mock-blue", adapter="mock"),
            "Judge": ModelConfig(id="mock-judge", adapter="mock"),
        },
    )

    events = runner.repository.read_events("meeting-1")
    completed = [event for event in events if event["status"] == "completed"]
    assert [event["step_id"] for event in completed] == [
        "round-2-red-critique",
        "round-2-blue-revise",
        "round-2-judge-decide",
    ]
    assert completed[0]["attempt"] == 2


def test_runner_rejects_retry_when_step_is_not_failed(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, adapter=FakeAdapter([VALID_OUTPUT] * 4))
    runner.start(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        topic="先做後端？",
        model_assignments={
            "Blue": ModelConfig(id="mock-blue", adapter="mock"),
            "Red": ModelConfig(id="mock-red", adapter="mock"),
            "Judge": ModelConfig(id="mock-judge", adapter="mock"),
        },
    )

    with pytest.raises(ValueError):
        runner.retry_failed_step(
            plan=RED_BLUE_PLAN,
            meeting_id="meeting-1",
            step_id="blue-propose",
            topic="先做後端？",
            model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
        )


def test_runner_rejects_retry_for_unknown_step(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, adapter=FakeAdapter([VALID_OUTPUT]))

    with pytest.raises(ValueError):
        runner.retry_failed_step(
            plan=RED_BLUE_PLAN,
            meeting_id="meeting-1",
            step_id="unknown-step",
            topic="先做後端？",
            model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
        )


def test_runner_cancel_records_cancellation_and_start_does_not_run_steps(
    tmp_path: Path,
) -> None:
    runner = build_runner(tmp_path, adapter=FakeAdapter([VALID_OUTPUT] * 4))

    runner.cancel("meeting-1")
    runner.start(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        topic="先做後端？",
        model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
    )

    events = runner.repository.read_events("meeting-1")
    assert strip_created_at(events) == [
        {
            "event_id": "meeting-1:cancelled",
            "meeting_id": "meeting-1",
            "step_id": "meeting",
            "role": "System",
            "attempt": 1,
            "status": "cancelled",
        }
    ]


def test_runner_start_tags_adapter_requests_with_meeting_id(tmp_path: Path) -> None:
    adapter = FakeAdapter([VALID_OUTPUT] * 4)
    runner = build_runner(tmp_path, adapter=adapter)

    runner.start(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        topic="先做後端？",
        model_assignments={
            "Blue": ModelConfig(id="mock-blue", adapter="mock"),
            "Red": ModelConfig(id="mock-red", adapter="mock"),
            "Judge": ModelConfig(id="mock-judge", adapter="mock"),
        },
    )

    assert [request.meeting_id for request in adapter.requests] == ["meeting-1"] * 4


def test_runner_cancel_notifies_adapters_that_support_cancellation(tmp_path: Path) -> None:
    adapter = CancellableFakeAdapter([VALID_OUTPUT] * 4)
    runner = build_runner(tmp_path, adapter=adapter)

    runner.cancel("meeting-1")

    assert adapter.cancelled_meeting_ids == ["meeting-1"]


def test_runner_close_records_closure_and_blocks_future_ai_steps(tmp_path: Path) -> None:
    adapter = FakeAdapter([VALID_OUTPUT] * 2)
    runner = build_runner(tmp_path, adapter=adapter)

    runner.close("meeting-1")
    runner.start(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        topic="先做後端？",
        model_assignments={
            "Blue": ModelConfig(id="mock-blue", adapter="mock"),
            "Red": ModelConfig(id="mock-red", adapter="mock"),
            "Judge": ModelConfig(id="mock-judge", adapter="mock"),
        },
    )
    runner.respond_as_role(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        topic="先做後端？",
        role="Blue",
        model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
    )
    runner.respond_as_sequence(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        topic="先做後端？",
        roles=["Red", "Judge"],
        model_assignments={
            "Red": ModelConfig(id="mock-red", adapter="mock"),
            "Judge": ModelConfig(id="mock-judge", adapter="mock"),
        },
    )

    events = runner.repository.read_events("meeting-1")
    assert strip_created_at(events) == [
        {
            "event_id": "meeting-1:closed",
            "meeting_id": "meeting-1",
            "step_id": "meeting",
            "role": "System",
            "attempt": 1,
            "status": "closed",
        }
    ]
    assert adapter.requests == []


def test_runner_terminal_events_are_idempotent(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, adapter=FakeAdapter([]))

    runner.close("meeting-1")
    runner.close("meeting-1")
    runner.cancel("meeting-1")

    events = runner.repository.read_events("meeting-1")
    assert strip_created_at(events) == [
        {
            "event_id": "meeting-1:closed",
            "meeting_id": "meeting-1",
            "step_id": "meeting",
            "role": "System",
            "attempt": 1,
            "status": "closed",
        }
    ]


def test_runner_completes_courtroom_flow(tmp_path: Path) -> None:
    runner = build_runner(
        tmp_path,
        adapter=FakeAdapter([VALID_OUTPUT] * 8),
        templates=(
            "courtroom_charge",
            "courtroom_defense",
            "courtroom_rebuttal",
            "courtroom_verdict",
        ),
    )
    model_assignments = {
        "Prosecutor": ModelConfig(id="mock-prosecutor", adapter="mock"),
        "Defense": ModelConfig(id="mock-defense", adapter="mock"),
        "Judge": ModelConfig(id="mock-judge", adapter="mock"),
    }

    runner.start(
        plan=COURTROOM_PLAN,
        meeting_id="meeting-1",
        topic="被告是否有罪？",
        model_assignments=model_assignments,
    )

    events = runner.repository.read_events("meeting-1")
    completed_steps = [event for event in events if event["status"] == "completed"]
    assert [event["step_id"] for event in completed_steps] == [
        "courtroom-charge",
        "courtroom-defense",
        "courtroom-rebuttal",
        "courtroom-verdict",
    ]

    runner.start(
        plan=COURTROOM_PLAN,
        meeting_id="meeting-1",
        topic="被告是否有罪？",
        model_assignments=model_assignments,
    )

    events = runner.repository.read_events("meeting-1")
    completed_steps = [event for event in events if event["status"] == "completed"]
    assert [event["step_id"] for event in completed_steps] == [
        "courtroom-charge",
        "courtroom-defense",
        "courtroom-rebuttal",
        "courtroom-verdict",
        "round-2-courtroom-charge",
        "round-2-courtroom-defense",
        "round-2-courtroom-rebuttal",
        "round-2-courtroom-verdict",
    ]


def test_runner_renders_mode_inputs_into_prompt(tmp_path: Path) -> None:
    runner = build_runner(
        tmp_path,
        adapter=FakeAdapter([VALID_OUTPUT]),
        extra_placeholders=" {{ position_a }}",
    )

    runner.respond_as_role(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        topic="先做後端？",
        role="Blue",
        model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
        inputs={"position_a": "先做後端"},
    )

    events = runner.repository.read_events("meeting-1")
    completed_event = events[-1]
    assert completed_event["status"] == "completed"
    assert "先做後端" in completed_event["prompt_messages"][0]["content"]


def test_parallel_runner_completes_fanout_then_synthesis(tmp_path: Path) -> None:
    runner = build_runner(
        tmp_path,
        adapter=FakeAdapter([VALID_OUTPUT] * 4),
        templates=("brainstorm_member", "brainstorm_synthesis"),
        extra_placeholders=" {{ instance_prompt }} {{ fanout_outputs }}",
    )

    runner.start_parallel(
        plan=PARALLEL_PLAN,
        meeting_id="meeting-1",
        topic="如何改善 onboarding？",
        model_assignments=parallel_model_assignments(),
    )

    events = runner.repository.read_events("meeting-1")
    completed = [event for event in events if event["status"] == "completed"]
    assert [event["step_id"] for event in completed] == [
        "fanout-1-member-1",
        "fanout-1-member-2",
        "fanout-1-member-3",
        "synthesis-1",
    ]
    assert [event["base_step_id"] for event in completed] == [
        "member-1",
        "member-2",
        "member-3",
        "synthesis",
    ]
    synthesis_prompt = completed[-1]["prompt_messages"][0]["content"]
    assert "Member-1" in synthesis_prompt
    assert "Continue" in synthesis_prompt


def test_parallel_runner_records_individual_failures_without_stopping_other_members(
    tmp_path: Path,
) -> None:
    runner = build_runner(
        tmp_path,
        adapter=SelectiveFailingAdapter(failing_model_ids={"mock-member-2"}),
        templates=("brainstorm_member", "brainstorm_synthesis"),
    )

    runner.start_parallel(
        plan=PARALLEL_PLAN,
        meeting_id="meeting-1",
        topic="如何改善 onboarding？",
        model_assignments=parallel_model_assignments(),
    )

    events = runner.repository.read_events("meeting-1")
    assert [(event["step_id"], event["status"]) for event in events] == [
        ("fanout-1-member-1", "completed"),
        ("fanout-1-member-2", "failed"),
        ("fanout-1-member-3", "completed"),
    ]
    assert all(event["step_id"] != "synthesis-1" for event in events)


def test_parallel_runner_retry_failed_member_runs_only_that_member_then_synthesizes(
    tmp_path: Path,
) -> None:
    adapter = SelectiveFailingAdapter(failing_model_ids={"mock-member-2"})
    runner = build_runner(
        tmp_path,
        adapter=adapter,
        templates=("brainstorm_member", "brainstorm_synthesis"),
    )
    model_assignments = parallel_model_assignments()
    runner.start_parallel(
        plan=PARALLEL_PLAN,
        meeting_id="meeting-1",
        topic="如何改善 onboarding？",
        model_assignments=model_assignments,
    )
    adapter.failing_model_ids.clear()

    runner.retry_failed_parallel_step(
        plan=PARALLEL_PLAN,
        meeting_id="meeting-1",
        step_id="fanout-1-member-2",
        topic="如何改善 onboarding？",
        model_assignments=model_assignments,
    )

    events = runner.repository.read_events("meeting-1")
    assert [(event["step_id"], event["attempt"], event["status"]) for event in events] == [
        ("fanout-1-member-1", 1, "completed"),
        ("fanout-1-member-2", 1, "failed"),
        ("fanout-1-member-3", 1, "completed"),
        ("fanout-1-member-2", 2, "completed"),
        ("synthesis-1", 1, "completed"),
    ]


def test_parallel_runner_starts_next_round_after_synthesis_complete(tmp_path: Path) -> None:
    runner = build_runner(
        tmp_path,
        adapter=FakeAdapter([VALID_OUTPUT] * 8),
        templates=("brainstorm_member", "brainstorm_synthesis"),
    )
    model_assignments = parallel_model_assignments()

    runner.start_parallel(
        plan=PARALLEL_PLAN,
        meeting_id="meeting-1",
        topic="如何改善 onboarding？",
        model_assignments=model_assignments,
    )
    runner.start_parallel(
        plan=PARALLEL_PLAN,
        meeting_id="meeting-1",
        topic="如何改善 onboarding？",
        model_assignments=model_assignments,
    )

    completed_step_ids = [
        event["step_id"]
        for event in runner.repository.read_events("meeting-1")
        if event["status"] == "completed"
    ]
    assert completed_step_ids == [
        "fanout-1-member-1",
        "fanout-1-member-2",
        "fanout-1-member-3",
        "synthesis-1",
        "fanout-2-member-1",
        "fanout-2-member-2",
        "fanout-2-member-3",
        "synthesis-2",
    ]


def parallel_model_assignments() -> dict[str, ModelConfig]:
    return {
        "Member-1": ModelConfig(id="mock-member-1", adapter="mock"),
        "Member-2": ModelConfig(id="mock-member-2", adapter="mock"),
        "Member-3": ModelConfig(id="mock-member-3", adapter="mock"),
        "Moderator": ModelConfig(id="mock-moderator", adapter="mock"),
    }


def build_runner(
    tmp_path: Path,
    *,
    adapter: object,
    templates: tuple[str, ...] = ("blue_propose", "red_critique", "blue_revise", "judge_decide"),
    extra_placeholders: str = "",
) -> MeetingRunner:
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    for template in templates:
        (prompt_dir / f"{template}.md").write_text(
            f"{template} {{{{ role }}}} {{{{ topic }}}} "
            "{{ prior_transcript }} {{ required_json_schema }}" + extra_placeholders,
            encoding="utf-8",
        )

    repository = MeetingRepository(tmp_path / "data")
    return MeetingRunner(
        repository=repository,
        prompt_renderer=PromptRenderer(prompt_dir),
        adapters=RunnerAdapters(
            by_name={
                "mock": adapter,
            }
        ),
    )


def strip_created_at(events: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {key: value for key, value in event.items() if key != "created_at"}
        for event in events
    ]


class FakeAdapter:
    def __init__(
        self,
        outputs: list[str],
        token_usage: dict[str, int] | None = None,
    ) -> None:
        self.outputs = outputs
        self.token_usage = token_usage
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(raw_output=self.outputs.pop(0), token_usage=self.token_usage)


class FailingAdapter:
    def complete(self, request: ModelRequest) -> ModelResponse:
        raise AdapterError("adapter boom")


class SelectiveFailingAdapter:
    def __init__(self, failing_model_ids: set[str]) -> None:
        self.failing_model_ids = failing_model_ids
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if request.model_config.id in self.failing_model_ids:
            raise AdapterError("adapter boom")
        return ModelResponse(raw_output=VALID_OUTPUT)


class CancellableFakeAdapter(FakeAdapter):
    def __init__(self, outputs: list[str]) -> None:
        super().__init__(outputs)
        self.cancelled_meeting_ids: list[str] = []

    def cancel(self, meeting_id: str) -> None:
        self.cancelled_meeting_ids.append(meeting_id)
