from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_council.meetings.repository import MeetingRepository
from ai_council.meetings.runner import (
    MeetingRunner,
    RunnerAdapters,
)
from ai_council.models.adapters import ModelRequest, ModelResponse
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


class FakeAdapter:
    def __init__(self, outputs: list[str]) -> None:
        self.outputs = outputs
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(raw_output=self.outputs.pop(0))


def build_chatroom_runner(
    tmp_path: Path,
    adapter: FakeAdapter,
) -> MeetingRunner:
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "chatroom_response.md").write_text(
        "chatroom_response {{ role }} {{ goal }} "
        "{{ prior_transcript }} {{ required_json_schema }} "
        "{{ role_display_name }} {{ instruction }}",
        encoding="utf-8",
    )
    repository = MeetingRepository(tmp_path / "data")
    return MeetingRunner(
        repository=repository,
        prompt_renderer=PromptRenderer(prompt_dir),
        adapters=RunnerAdapters(by_name={"mock": adapter}),
    )


def test_chat_directed_single_role_response(tmp_path: Path) -> None:
    adapter = FakeAdapter([VALID_OUTPUT])
    runner = build_chatroom_runner(tmp_path, adapter)
    model_assignments = {"Blue": ModelConfig(id="mock-blue", adapter="mock")}

    runner.chat_respond_as_role(
        meeting_id="meeting-1",
        goal="如何改善團隊溝通？",
        role="Blue",
        role_display_name="藍軍",
        instruction="@Blue 你覺得怎麼樣？",
        model_assignments=model_assignments,
    )

    events = runner.repository.read_events("meeting-1")
    assert len(events) == 2

    instruction_event = events[0]
    assert instruction_event["step_id"] == "human-directed-message"
    assert instruction_event["role"] == "Human"
    assert instruction_event["interaction_type"] == "directed-role-instruction"
    assert instruction_event["target_role_id"] == "Blue"
    assert instruction_event["content"] == "@Blue 你覺得怎麼樣？"
    assert instruction_event["status"] == "completed"

    response_event = events[1]
    assert response_event["step_id"] == "chat-directed-1-blue-response"
    assert response_event["role"] == "Blue"
    assert response_event["status"] == "completed"
    assert response_event["interaction_type"] == "directed-role-response"
    assert response_event["directed_sequence"] == 1
    assert response_event["in_response_to_event_id"] == instruction_event["event_id"]

    assert adapter.requests[0].model_config.id == "mock-blue"
    prompt = adapter.requests[0].prompt
    assert "藍軍" in prompt
    assert "@Blue 你覺得怎麼樣？" in prompt
    assert "chatroom_response" in prompt


def test_chat_directed_increments_sequence(tmp_path: Path) -> None:
    adapter = FakeAdapter([VALID_OUTPUT, VALID_OUTPUT])
    runner = build_chatroom_runner(tmp_path, adapter)
    model_assignments = {"Blue": ModelConfig(id="mock-blue", adapter="mock")}

    runner.chat_respond_as_role(
        meeting_id="meeting-1",
        goal="如何改善團隊溝通？",
        role="Blue",
        role_display_name="藍軍",
        instruction="第一個問題",
        model_assignments=model_assignments,
    )
    runner.chat_respond_as_role(
        meeting_id="meeting-1",
        goal="如何改善團隊溝通？",
        role="Blue",
        role_display_name="藍軍",
        instruction="第二個問題",
        model_assignments=model_assignments,
    )

    events = runner.repository.read_events("meeting-1")
    response_events = [
        event for event in events if event.get("interaction_type") == "directed-role-response"
    ]
    assert len(response_events) == 2
    assert [event["step_id"] for event in response_events] == [
        "chat-directed-1-blue-response",
        "chat-directed-2-blue-response",
    ]
    assert [event["directed_sequence"] for event in response_events] == [1, 2]


def test_chat_directed_unknown_role_saves_human_only(tmp_path: Path) -> None:
    adapter = FakeAdapter([])
    runner = build_chatroom_runner(tmp_path, adapter)
    model_assignments = {"Blue": ModelConfig(id="mock-blue", adapter="mock")}

    runner.chat_respond_as_role(
        meeting_id="meeting-1",
        goal="如何改善團隊溝通？",
        role="Unknown",
        role_display_name="未知",
        instruction="@Unknown 你好",
        model_assignments=model_assignments,
    )

    events = runner.repository.read_events("meeting-1")
    assert len(events) == 1
    human_event = events[0]
    assert human_event["step_id"] == "human-message"
    assert human_event["role"] == "Human"
    assert human_event["status"] == "completed"
    assert human_event["content"] == "@Unknown 你好"

    assert adapter.requests == []
