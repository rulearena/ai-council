from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_council.meetings.repository import MeetingRepository
from ai_council.meetings.runner import MeetingRunner, RunnerAdapters
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


def test_runner_completes_fixed_red_blue_judge_flow(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, adapter=FakeAdapter([VALID_OUTPUT] * 4))

    runner.start(
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


def test_runner_starts_follow_up_round_after_human_feedback(tmp_path: Path) -> None:
    adapter = FakeAdapter([VALID_OUTPUT] * 8)
    runner = build_runner(tmp_path, adapter=adapter)
    model_assignments = {
        "Blue": ModelConfig(id="mock-blue", adapter="mock"),
        "Red": ModelConfig(id="mock-red", adapter="mock"),
        "Judge": ModelConfig(id="mock-judge", adapter="mock"),
    }
    runner.start(
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
            meeting_id="meeting-1",
            step_id="blue-propose",
            topic="先做後端？",
            model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
        )


def test_runner_rejects_retry_for_unknown_step(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, adapter=FakeAdapter([VALID_OUTPUT]))

    with pytest.raises(ValueError):
        runner.retry_failed_step(
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


def test_runner_close_records_closure_and_blocks_future_ai_steps(tmp_path: Path) -> None:
    adapter = FakeAdapter([VALID_OUTPUT] * 2)
    runner = build_runner(tmp_path, adapter=adapter)

    runner.close("meeting-1")
    runner.start(
        meeting_id="meeting-1",
        topic="先做後端？",
        model_assignments={
            "Blue": ModelConfig(id="mock-blue", adapter="mock"),
            "Red": ModelConfig(id="mock-red", adapter="mock"),
            "Judge": ModelConfig(id="mock-judge", adapter="mock"),
        },
    )
    runner.respond_as_role(
        meeting_id="meeting-1",
        topic="先做後端？",
        role="Blue",
        model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
    )
    runner.respond_as_sequence(
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


def build_runner(tmp_path: Path, *, adapter: object) -> MeetingRunner:
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    for template in ["blue_propose", "red", "blue_revise", "judge"]:
        (prompt_dir / f"{template}.md").write_text(
            "{{ role }} {{ topic }} {{ prior_transcript }} {{ required_json_schema }}",
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
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(raw_output=self.outputs.pop(0))


class FailingAdapter:
    def complete(self, request: ModelRequest) -> ModelResponse:
        raise AdapterError("adapter boom")
