from __future__ import annotations

import io
import json
import re
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from ai_council.meetings.repository import MeetingRepository
from ai_council.meetings.attachments import AttachmentStore
from ai_council.meetings.runner import (
    MeetingRunner,
    RunnerAdapters,
)
from ai_council.models.adapters import AdapterError, ModelRequest, ModelResponse, TokenUsage
from ai_council.models.config import ModelConfig
from ai_council.prompting.renderer import PromptRenderer

VALID_OUTPUT = json.dumps({"message": "可以先做小規模驗證，詳見 [附件一]。"}, ensure_ascii=False)


def persona_inputs(*roles: str) -> dict[str, dict[str, str]]:
    return {"__chatroom_persona_prompts": {role: f"{role} fixed persona" for role in roles}}


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


def test_chat_directed_prompt_excludes_binary_attachment_metadata(
    tmp_path: Path,
) -> None:
    adapter = FakeAdapter([VALID_OUTPUT])
    runner = build_chatroom_runner(tmp_path, adapter)
    repository = runner.repository
    attachments = AttachmentStore(repository)
    file_id = "attachment-secret-report"
    attachments.save_blob("meeting-1", file_id, io.BytesIO(b"%PDF fake"))
    attachments.record_attachment(
        "meeting-1",
        file_id=file_id,
        filename="top-secret-report.pdf",
        size=9,
        mime_type="application/pdf",
        extension=".pdf",
    )
    model_assignments = {"Blue": ModelConfig(id="mock-blue", adapter="mock")}

    runner.chat_respond_as_role(
        meeting_id="meeting-1",
        goal="如何改善團隊溝通？",
        role="Blue",
        role_display_name="藍軍",
        instruction="@Blue 你覺得怎麼樣？",
        model_assignments=model_assignments,
        inputs=persona_inputs("Blue"),
    )

    assert len(adapter.requests) == 1
    prompt = adapter.requests[0].prompt
    assert "@Blue 你覺得怎麼樣？" in prompt
    assert "top-secret-report.pdf" not in prompt
    assert "attachment-added" not in prompt
    assert "file_id" not in prompt


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
        inputs=persona_inputs("Blue"),
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
    assert response_event["output_schema_id"] == "chat-message/v1"
    assert response_event["parsed_output"] == {
        "message": "可以先做小規模驗證，詳見 [附件一]。",
    }
    assert response_event["raw_output"] == VALID_OUTPUT

    assert adapter.requests[0].model_config.id == "mock-blue"
    prompt = adapter.requests[0].prompt
    assert "藍軍" in prompt
    assert "@Blue 你覺得怎麼樣？" in prompt
    assert "chatroom_response" in prompt


@pytest.mark.parametrize(
    "attachment_ref",
    [
        {"source_ref": "attachment:other", "label": "brief.md", "segment_refs": ["full"]},
        {"source_ref": "attachment:brief", "label": "wrong.md", "segment_refs": ["full"]},
        {"source_ref": "attachment:brief", "label": "brief.md", "segment_refs": []},
        {"source_ref": "attachment:brief", "label": "brief.md", "segment_refs": ["paragraph:9999"]},
    ],
)
def test_invalid_chatroom_citation_becomes_retry_diagnostics_not_runner_crash(
    tmp_path: Path, attachment_ref: dict[str, object]
) -> None:
    invalid = json.dumps({"message": "依據來源", "attachment_refs": [attachment_ref]})
    adapter = FakeAdapter([invalid, invalid])
    runner = build_chatroom_runner(tmp_path, adapter)
    runner.chat_respond_as_role(
        meeting_id="meeting-1",
        goal="測試引用",
        role="host",
        role_display_name="主持 AI",
        instruction="請引用",
        model_assignments={"host": ModelConfig(id="mock-host", adapter="mock")},
        inputs={
            **persona_inputs("host"),
            "__chatroom_source_snapshot": {
                "selected_source_snapshot": {
                    "schema_version": "chatroom-source-context/v1",
                    "source_refs": ["attachment:brief"],
                    "sources": [{
                        "source_ref": "attachment:brief",
                        "label": "brief.md",
                        "available_segment_refs": ["full"],
                    }],
                },
                "source_excerpts": ["brief excerpt"],
            },
        },
    )

    attempts = [event for event in runner.repository.read_events("meeting-1") if event.get("role") == "host"]
    assert attempts
    assert all(event["status"] == "failed" for event in attempts)
    assert all(event["failure_kind"] == "parse_error" for event in attempts)
    assert all("attachment_refs" in event["error"] for event in attempts)


def test_chatroom_citation_retry_prompt_lists_exact_allowed_segments_and_recovers(
    tmp_path: Path,
) -> None:
    invalid = json.dumps({
        "message": "依據來源",
        "attachment_refs": [{
            "source_ref": "attachment:brief",
            "label": "brief.md",
            "segment_refs": [],
        }],
    })
    valid = json.dumps({
        "message": "依據來源",
        "attachment_refs": [{
            "source_ref": "attachment:brief",
            "label": "brief.md",
            "segment_refs": ["full"],
        }],
    })
    adapter = FakeAdapter([invalid, valid])
    runner = build_chatroom_runner(tmp_path, adapter)
    runner.chat_respond_as_role(
        meeting_id="meeting-1", goal="測試引用", role="host", role_display_name="主持 AI",
        instruction="請引用", model_assignments={"host": ModelConfig(id="mock-host", adapter="mock")},
        inputs={
            **persona_inputs("host"),
            "__chatroom_source_snapshot": {
                "selected_source_snapshot": {
                    "schema_version": "chatroom-source-context/v1",
                    "source_refs": ["attachment:brief"],
                    "sources": [{
                        "source_ref": "attachment:brief", "label": "brief.md",
                        "available_segment_refs": ["full"],
                    }],
                },
                "source_excerpts": ["brief excerpt"],
            },
        },
    )

    assert len(adapter.requests) == 2
    assert '"full"' in adapter.requests[0].prompt
    assert 'attachment:brief' in adapter.requests[0].prompt
    assert 'attachment_refs segment_refs must be non-empty strings' in adapter.requests[1].prompt
    assert 'Allowed segment_refs for brief.md: ["full"]' in adapter.requests[1].prompt
    response_events = [event for event in runner.repository.read_events("meeting-1") if event.get("role") == "host"]
    assert response_events[-1]["status"] == "completed"
    assert response_events[-1]["parsed_output"]["attachment_refs"][0]["segment_refs"] == ["full"]


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
        inputs=persona_inputs("Blue"),
    )
    runner.chat_respond_as_role(
        meeting_id="meeting-1",
        goal="如何改善團隊溝通？",
        role="Blue",
        role_display_name="藍軍",
        instruction="第二個問題",
        model_assignments=model_assignments,
        inputs=persona_inputs("Blue"),
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


# --- Task group 5: @all fanout tests ---


def test_chat_fanout_all_roles_invoked(tmp_path: Path) -> None:
    adapter = FakeAdapter([VALID_OUTPUT, VALID_OUTPUT, VALID_OUTPUT])
    runner = build_chatroom_runner(tmp_path, adapter)
    model_assignments = {
        "Blue": ModelConfig(id="mock-blue", adapter="mock"),
        "Red": ModelConfig(id="mock-red", adapter="mock"),
        "Green": ModelConfig(id="mock-green", adapter="mock"),
    }

    runner.fanout_chatroom_all(
        meeting_id="meeting-1",
        goal="團隊策略討論",
        instruction="@all 大家覺得怎麼樣？",
        role_display_names={"Blue": "藍軍", "Red": "紅軍", "Green": "綠軍"},
        model_assignments=model_assignments,
        inputs=persona_inputs("Blue", "Red", "Green"),
    )

    events = runner.repository.read_events("meeting-1")
    human_events = [e for e in events if e.get("role") == "Human"]
    response_events = [
        e for e in events if e.get("interaction_type") == "chatroom-fanout-response"
    ]
    assert len(human_events) == 1
    assert human_events[0]["step_id"] == "human-message"
    assert len(response_events) == 3
    roles_responded = {e["role"] for e in response_events}
    assert roles_responded == {"Blue", "Red", "Green"}
    for event in response_events:
        assert event["status"] == "completed"
        parsed = event.get("parsed_output")
        assert parsed is not None, "completed fanout event must include parsed_output"
        assert parsed["message"] == "可以先做小規模驗證，詳見 [附件一]。"
        assert event["output_schema_id"] == "chat-message/v1"
        assert event["in_response_to_event_id"] == human_events[0]["event_id"]


def test_chat_fanout_empty_model_assignments_no_crash(tmp_path: Path) -> None:
    adapter = FakeAdapter([])
    runner = build_chatroom_runner(tmp_path, adapter)
    runner.fanout_chatroom_all(
        meeting_id="meeting-1",
        goal="團隊策略討論",
        instruction="@all 大家覺得怎麼樣？",
        role_display_names={},
        model_assignments={},
    )
    events = runner.repository.read_events("meeting-1")
    response_events = [
        e for e in events if e.get("interaction_type") == "chatroom-fanout-response"
    ]
    assert len(response_events) == 0
    assert adapter.requests == []


def test_chat_fanout_completed_events_include_token_usage(tmp_path: Path) -> None:
    class TokenAdapter:
        def __init__(self) -> None:
            self.requests: list[ModelRequest] = []

        def complete(self, request: ModelRequest) -> ModelResponse:
            self.requests.append(request)
            return ModelResponse(
                raw_output=VALID_OUTPUT,
                token_usage=TokenUsage(
                    prompt_tokens=10,
                    completion_tokens=20,
                    total_tokens=30,
                ),
            )

    adapter = TokenAdapter()
    runner = build_chatroom_runner(tmp_path, adapter)
    model_assignments = {
        "Blue": ModelConfig(id="mock-blue", adapter="mock"),
        "Red": ModelConfig(id="mock-red", adapter="mock"),
    }
    runner.fanout_chatroom_all(
        meeting_id="meeting-1",
        goal="團隊策略討論",
        instruction="@all 大家覺得怎麼樣？",
        role_display_names={"Blue": "藍軍", "Red": "紅軍"},
        model_assignments=model_assignments,
        inputs=persona_inputs("Blue", "Red"),
    )

    events = runner.repository.read_events("meeting-1")
    response_events = [
        e for e in events if e.get("interaction_type") == "chatroom-fanout-response"
    ]
    assert len(response_events) == 2
    for event in response_events:
        assert event["status"] == "completed"
        assert "token_usage" in event, "completed fanout event must include token_usage"
        assert event["token_usage"]["total_tokens"] == 30


def test_chat_fanout_failed_events_include_token_usage(tmp_path: Path) -> None:
    class FailParseAdapter:
        def __init__(self) -> None:
            self.call_count = 0

        def complete(self, request: ModelRequest) -> ModelResponse:
            self.call_count += 1
            if "green" in request.model_config.id.lower():
                return ModelResponse(
                    raw_output="not valid json",
                    token_usage=TokenUsage(
                        prompt_tokens=5,
                        completion_tokens=10,
                        total_tokens=15,
                    ),
                )
            return ModelResponse(
                raw_output=VALID_OUTPUT,
                token_usage=TokenUsage(
                    prompt_tokens=10,
                    completion_tokens=20,
                    total_tokens=30,
                ),
            )

    adapter = FailParseAdapter()
    runner = build_chatroom_runner(tmp_path, adapter)
    model_assignments = {
        "Blue": ModelConfig(id="mock-blue", adapter="mock"),
        "Green": ModelConfig(id="mock-green", adapter="mock"),
    }
    runner.fanout_chatroom_all(
        meeting_id="meeting-1",
        goal="團隊策略討論",
        instruction="@all 大家覺得怎麼樣？",
        role_display_names={"Blue": "藍軍", "Green": "綠軍"},
        model_assignments=model_assignments,
        inputs=persona_inputs("Blue", "Green"),
    )

    events = runner.repository.read_events("meeting-1")
    response_events = [
        e for e in events if e.get("interaction_type") == "chatroom-fanout-response"
    ]
    assert len(response_events) == 2
    completed = [e for e in response_events if e["status"] == "completed"]
    failed = [e for e in response_events if e["status"] == "failed"]
    assert len(completed) == 1
    assert len(failed) == 1
    assert "token_usage" in completed[0]
    assert "token_usage" in failed[0]
    assert failed[0]["output_schema_id"] == "chat-message/v1"
    assert failed[0]["raw_output"] == "not valid json"
    assert failed[0]["in_response_to_event_id"]


def test_chat_fanout_frozen_context(tmp_path: Path) -> None:
    captured_requests: list[ModelRequest] = []

    class CaptureAdapter:
        def __init__(self, outputs: list[str]) -> None:
            self.outputs = outputs

        def complete(self, request: ModelRequest) -> ModelResponse:
            captured_requests.append(request)
            return ModelResponse(raw_output=self.outputs.pop(0))

    adapter = CaptureAdapter([VALID_OUTPUT, VALID_OUTPUT, VALID_OUTPUT])
    runner = build_chatroom_runner(tmp_path, adapter)
    model_assignments = {
        "Blue": ModelConfig(id="mock-blue", adapter="mock"),
        "Red": ModelConfig(id="mock-red", adapter="mock"),
        "Green": ModelConfig(id="mock-green", adapter="mock"),
    }

    runner.fanout_chatroom_all(
        meeting_id="meeting-1",
        goal="團隊策略討論",
        instruction="@all 大家覺得怎麼樣？",
        role_display_names={"Blue": "藍軍", "Red": "紅軍", "Green": "綠軍"},
        model_assignments=model_assignments,
        inputs=persona_inputs("Blue", "Red", "Green"),
    )

    assert len(captured_requests) == 3
    prompts = [req.prompt for req in captured_requests]
    instruction_suffix = "@all 大家覺得怎麼樣？"
    for prompt in prompts:
        assert prompt.endswith(instruction_suffix)
    suffixes = [p.rsplit(instruction_suffix, 1)[1] for p in prompts]
    prefixes = [p.split("@all 大家覺得怎麼樣？", 1)[0] for p in prompts]
    role_names = {"Blue", "Red", "Green"}
    display_names = {"藍軍", "紅軍", "綠軍"}
    stripped_prefixes = set()
    for prefix in prefixes:
        stripped = prefix
        for name in role_names | display_names:
            stripped = stripped.replace(name, "X")
        stripped_prefixes.add(stripped)
    assert len(stripped_prefixes) == 1, "prompts differ outside of role names"


def test_chat_fanout_arrival_order_persistence(tmp_path: Path) -> None:
    class SlowAdapter:
        def __init__(self, delays: dict[str, float], output: str) -> None:
            self.delays = delays
            self.output = output

        def complete(self, request: ModelRequest) -> ModelResponse:
            role_hint = "unknown"
            for key in ("Blue", "Red", "Green"):
                if key.lower() in request.prompt.lower() or key.lower() in str(
                    request.model_config.id
                ).lower():
                    role_hint = key
                    break
            for delay_role, delay in self.delays.items():
                if delay_role.lower() in request.model_config.id.lower():
                    time.sleep(delay)
                    break
            return ModelResponse(raw_output=self.output)

    adapter = SlowAdapter(
        delays={"blue": 0.1, "red": 0.01, "green": 0.05}, output=VALID_OUTPUT
    )
    runner = build_chatroom_runner(tmp_path, adapter)
    model_assignments = {
        "Blue": ModelConfig(id="mock-blue", adapter="mock"),
        "Red": ModelConfig(id="mock-red", adapter="mock"),
        "Green": ModelConfig(id="mock-green", adapter="mock"),
    }

    runner.fanout_chatroom_all(
        meeting_id="meeting-1",
        goal="團隊策略討論",
        instruction="@all 大家覺得怎麼樣？",
        role_display_names={"Blue": "藍軍", "Red": "紅軍", "Green": "綠軍"},
        model_assignments=model_assignments,
        inputs=persona_inputs("Blue", "Red", "Green"),
    )

    events = runner.repository.read_events("meeting-1")
    response_events = [
        e for e in events if e.get("interaction_type") == "chatroom-fanout-response"
    ]
    assert len(response_events) == 3
    assert response_events[0]["role"] == "Red"
    assert response_events[1]["role"] == "Green"
    assert response_events[2]["role"] == "Blue"


def test_chat_fanout_partial_success(tmp_path: Path) -> None:
    call_count = 0

    class PartialFailAdapter:
        def __init__(self, fail_role: str) -> None:
            self.fail_role = fail_role

        def complete(self, request: ModelRequest) -> ModelResponse:
            nonlocal call_count
            call_count += 1
            if self.fail_role in request.model_config.id:
                raise AdapterError("simulated adapter failure")
            return ModelResponse(raw_output=VALID_OUTPUT)

    adapter = PartialFailAdapter(fail_role="green")
    runner = build_chatroom_runner(tmp_path, adapter)
    model_assignments = {
        "Blue": ModelConfig(id="mock-blue", adapter="mock"),
        "Red": ModelConfig(id="mock-red", adapter="mock"),
        "Green": ModelConfig(id="mock-green", adapter="mock"),
    }

    runner.fanout_chatroom_all(
        meeting_id="meeting-1",
        goal="團隊策略討論",
        instruction="@all 大家覺得怎麼樣？",
        role_display_names={"Blue": "藍軍", "Red": "紅軍", "Green": "綠軍"},
        model_assignments=model_assignments,
        inputs=persona_inputs("Blue", "Red", "Green"),
    )

    events = runner.repository.read_events("meeting-1")
    response_events = [
        e for e in events if e.get("interaction_type") == "chatroom-fanout-response"
    ]
    assert len(response_events) == 3
    completed = [e for e in response_events if e["status"] == "completed"]
    failed = [e for e in response_events if e["status"] == "failed"]
    assert len(completed) == 2
    assert len(failed) == 1
    assert failed[0]["role"] == "Green"
    assert failed[0]["failure_kind"] == "adapter_error"


def test_chat_fanout_step_id_format(tmp_path: Path) -> None:
    adapter = FakeAdapter([VALID_OUTPUT, VALID_OUTPUT, VALID_OUTPUT])
    runner = build_chatroom_runner(tmp_path, adapter)
    model_assignments = {
        "Blue": ModelConfig(id="mock-blue", adapter="mock"),
        "Red": ModelConfig(id="mock-red", adapter="mock"),
        "Green": ModelConfig(id="mock-green", adapter="mock"),
    }

    with patch("ai_council.meetings.runner.time") as mock_time:
        mock_time.time.return_value = 1700000000.123
        mock_time.monotonic.return_value = 0.0
        runner.fanout_chatroom_all(
            meeting_id="meeting-1",
            goal="團隊策略討論",
            instruction="@all 大家覺得怎麼樣？",
            role_display_names={"Blue": "藍軍", "Red": "紅軍", "Green": "綠軍"},
            model_assignments=model_assignments,
            inputs=persona_inputs("Blue", "Red", "Green"),
        )

    events = runner.repository.read_events("meeting-1")
    response_events = [
        e for e in events if e.get("interaction_type") == "chatroom-fanout-response"
    ]
    pattern = re.compile(r"^chat-fanout-\d{13}-.+$")
    for event in response_events:
        assert pattern.match(event["step_id"]), f"bad step_id: {event['step_id']}"
        assert "Blue" in event["step_id"] or "Red" in event["step_id"] or "Green" in event["step_id"]


# --- Task group 7: quoted_event_id wiring test ---


def test_chat_directed_with_quoted_event_in_context(tmp_path: Path) -> None:
    adapter = FakeAdapter([VALID_OUTPUT])
    runner = build_chatroom_runner(tmp_path, adapter)
    model_assignments = {"Blue": ModelConfig(id="mock-blue", adapter="mock")}

    # Append a target event first so the builder can find it
    runner.repository.append_event(
        "meeting-1",
        {
            "event_id": "meeting-1:quote-target",
            "meeting_id": "meeting-1",
            "step_id": "human-message",
            "role": "Human",
            "attempt": 1,
            "status": "completed",
            "content": "This is the quoted message about architecture",
        },
    )

    runner.chat_respond_as_role(
        meeting_id="meeting-1",
        goal="How to improve?",
        role="Blue",
        role_display_name="Blue Advisor",
        instruction="@Blue what do you think?",
        model_assignments=model_assignments,
        quoted_event_id="meeting-1:quote-target",
        inputs=persona_inputs("Blue"),
    )

    assert len(adapter.requests) == 1
    prompt = adapter.requests[0].prompt
    assert "This is the quoted message about architecture" in prompt
