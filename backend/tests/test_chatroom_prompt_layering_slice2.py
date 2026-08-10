import json
import sys
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from ai_council.meetings.modes import ModeCatalogRepository, ModeConfigError
from ai_council.meetings.execution_state import MeetingExecutionStateStore
from ai_council.models.adapters import (
    AdapterError,
    AnthropicHTTPAdapter,
    GeminiHTTPAdapter,
    ModelRequest,
    MockModelAdapter,
    OpenAICompatibleHTTPAdapter,
    SubscriptionCLIAdapter,
)
from ai_council.models.config import ModelConfig
from ai_council.meetings.runner import MeetingRunner, RunnerAdapters
from ai_council.models.adapters import ModelResponse
from ai_council.meetings.repository import MeetingRepository
from ai_council.prompting.renderer import PromptRenderer


def layered_request() -> ModelRequest:
    return ModelRequest(
        prompt="SYSTEM\nsystem text\n\nDEVELOPER\ndeveloper text\n\nUSER\nuser text",
        model_config=ModelConfig(id="m", adapter="mock"),
        messages=[
            {"role": "system", "content": "system text"},
            {"role": "developer", "content": "developer text"},
            {"role": "user", "content": "user text"},
        ],
    )


def test_model_request_preserves_canonical_message_layers() -> None:
    assert layered_request().messages == [
        {"role": "system", "content": "system text"},
        {"role": "developer", "content": "developer text"},
        {"role": "user", "content": "user text"},
    ]


def test_openai_layered_request_uses_native_developer_role(monkeypatch: pytest.MonkeyPatch) -> None:
    payloads: list[dict] = []
    monkeypatch.setattr(
        "ai_council.models.adapters._post_json",
        lambda url, payload, headers: payloads.append(payload) or {"choices": [{"message": {"content": "{}"}}]},
    )
    OpenAICompatibleHTTPAdapter(supports_developer_role=True).complete(
        replace(layered_request(), model_config=ModelConfig(id="m", adapter="openai-compatible-http", base_url="http://model", model="x"))
    )
    assert payloads[0]["messages"] == layered_request().messages


def test_openai_layered_request_falls_back_by_merging_system_and_developer(monkeypatch: pytest.MonkeyPatch) -> None:
    payloads: list[dict] = []
    monkeypatch.setattr(
        "ai_council.models.adapters._post_json",
        lambda url, payload, headers: payloads.append(payload) or {"choices": [{"message": {"content": "{}"}}]},
    )
    request = layered_request()
    OpenAICompatibleHTTPAdapter().complete(
        replace(request, model_config=ModelConfig(id="m", adapter="openai-compatible-http", base_url="http://model", model="x"))
    )
    assert payloads[0]["messages"] == [
        {"role": "system", "content": "system text\n\ndeveloper text"},
        {"role": "user", "content": "user text"},
    ]


def test_anthropic_layered_request_uses_top_level_system(monkeypatch: pytest.MonkeyPatch) -> None:
    payloads: list[dict] = []
    monkeypatch.setattr(
        "ai_council.models.adapters._post_json",
        lambda url, payload, headers: payloads.append(payload) or {"content": [{"text": "{}"}]},
    )
    request = layered_request()
    AnthropicHTTPAdapter().complete(
        replace(request, model_config=ModelConfig(id="m", adapter="anthropic-http", base_url="http://model", model="x"))
    )
    assert payloads[0]["system"] == "system text\n\ndeveloper text"
    assert payloads[0]["messages"] == [{"role": "user", "content": "user text"}]


def test_gemini_layered_request_uses_system_instruction_or_flattened_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    payloads: list[dict] = []
    monkeypatch.setattr(
        "ai_council.models.adapters._post_json",
        lambda url, payload, headers: payloads.append(payload) or {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]},
    )
    request = layered_request()
    GeminiHTTPAdapter().complete(
        replace(request, model_config=ModelConfig(id="m", adapter="gemini-http", base_url="http://model", model="x"))
    )
    assert payloads[0]["systemInstruction"] == {"parts": [{"text": "system text\n\ndeveloper text"}]}
    payloads.clear()
    GeminiHTTPAdapter(supports_system_instruction=False).complete(
        replace(request, model_config=ModelConfig(id="m", adapter="gemini-http", base_url="http://model", model="x"))
    )
    assert payloads[0] == {
        "contents": [{"role": "user", "parts": [{"text": request.prompt}]}],
    }


def test_subscription_cli_receives_exact_canonical_flattening_and_legacy_prompt(
    tmp_path: Path,
) -> None:
    echo_cli = tmp_path / "echo_prompt.py"
    echo_cli.write_text(
        "import sys\nprint(sys.argv[1], end='')\n",
        encoding="utf-8",
    )
    config = ModelConfig(
        id="subscription",
        adapter="subscription-cli",
        command=[sys.executable, str(echo_cli), "{prompt}"],
        timeout_seconds=5,
    )
    canonical_prompt = "SYSTEM\nsystem text\n\nDEVELOPER\ndeveloper text\n\nUSER\nuser text"
    canonical = replace(layered_request(), model_config=config)

    canonical_response = SubscriptionCLIAdapter().complete(canonical)
    legacy = ModelRequest(
        prompt="legacy formal prompt without labels",
        model_config=config,
    )
    legacy_response = SubscriptionCLIAdapter().complete(legacy)

    assert canonical.messages == [
        {"role": "system", "content": "system text"},
        {"role": "developer", "content": "developer text"},
        {"role": "user", "content": "user text"},
    ]
    assert canonical_response.raw_output == canonical_prompt
    assert legacy.messages is None
    assert legacy_response.raw_output == "legacy formal prompt without labels"


def test_mock_adapter_observably_receives_canonical_messages_and_prompt() -> None:
    adapter = MockModelAdapter()
    request = layered_request()

    adapter.complete(request)

    assert adapter.last_request is not None
    assert adapter.last_request.prompt == (
        "SYSTEM\nsystem text\n\nDEVELOPER\ndeveloper text\n\nUSER\nuser text"
    )
    assert adapter.last_request.messages == [
        {"role": "system", "content": "system text"},
        {"role": "developer", "content": "developer text"},
        {"role": "user", "content": "user text"},
    ]


def test_chatroom_roles_expose_summary_but_keep_prompt_backend_only() -> None:
    mode = ModeCatalogRepository(Path(__file__).parents[2] / "config" / "modes.yaml").get_mode("chatroom")
    assert mode is not None
    assert {role.id for role in mode.roles} == {"host", "Advisor", "Critic", "Strategist", "Analyst"}
    assert all(role.persona_summary.strip() and role.persona_prompt.strip() for role in mode.roles)


def test_non_chatroom_roles_do_not_require_persona_fields(tmp_path) -> None:
    config = tmp_path / "modes.yaml"
    config.write_text("""
modes:
  - id: formal
    name: Formal
    category: relay
    roles: [{id: A, name: A, color: '#fff', kind: member}]
    steps: [{role: A, template: a, label: A}]
""", encoding="utf-8")
    assert ModeCatalogRepository(config).get_mode("formal") is not None


def test_chatroom_attempt_audit_contains_exact_three_layers(tmp_path) -> None:
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "chatroom_response.md").write_text("unused", encoding="utf-8")

    class Adapter:
        def complete(self, request: ModelRequest) -> ModelResponse:
            return ModelResponse('{"message":"ok"}')

    runner = MeetingRunner(
        repository=MeetingRepository(tmp_path / "data"),
        prompt_renderer=PromptRenderer(prompt_dir),
        adapters=RunnerAdapters(by_name={"mock": Adapter()}),
    )
    runner.chat_respond_as_role(
        meeting_id="meeting-1",
        goal="測試",
        role="host",
        role_display_name="主持 AI",
        instruction="請簡短回答",
        model_assignments={"host": ModelConfig(id="m", adapter="mock")},
        inputs={"__chatroom_persona_prompts": {"host": "固定主持 Persona"}},
    )
    event = runner.repository.read_events("meeting-1")[-1]
    assert [message["role"] for message in event["prompt_messages"]] == [
        "system", "developer", "user"
    ]
    assert event["prompt_messages"][-1]["content"].endswith("請簡短回答")
    assert "Case files visible to you" not in "".join(
        message["content"] for message in event["prompt_messages"]
    )


def test_chatroom_running_and_adapter_failure_persist_identical_canonical_messages(
    tmp_path: Path,
) -> None:
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "chatroom_response.md").write_text("unused", encoding="utf-8")
    entered = threading.Event()
    release = threading.Event()

    class Adapter:
        def complete(self, request: ModelRequest) -> ModelResponse:
            entered.set()
            assert release.wait(timeout=5)
            raise AdapterError("transport failed")

    state_store = MeetingExecutionStateStore(tmp_path / "data")
    runner = MeetingRunner(
        repository=MeetingRepository(tmp_path / "data"),
        prompt_renderer=PromptRenderer(prompt_dir),
        adapters=RunnerAdapters(by_name={"mock": Adapter()}),
        execution_state_store=state_store,
    )
    worker = threading.Thread(
        target=runner.chat_respond_as_role,
        kwargs={
            "meeting_id": "meeting-1",
            "goal": "Audit persistence",
            "role": "host",
            "role_display_name": "Host AI",
            "instruction": "Keep these layers exact.",
            "model_assignments": {"host": ModelConfig(id="m", adapter="mock")},
            "inputs": {"__chatroom_persona_prompts": {"host": "Fixed Host Persona"}},
        },
    )

    worker.start()
    try:
        assert entered.wait(timeout=2)
        running = state_store.read_active("meeting-1")
        assert running is not None
        assert running["status"] == "running"
        canonical_messages = running["prompt_messages"]
        assert [message["role"] for message in canonical_messages] == [
            "system",
            "developer",
            "user",
        ]
    finally:
        release.set()
        worker.join(timeout=5)

    assert not worker.is_alive()
    failed = runner.repository.read_events("meeting-1")[-1]
    assert failed["status"] == "failed"
    assert failed["failure_kind"] == "adapter_error"
    assert failed["prompt_messages"] == canonical_messages
    assert state_store.read_active("meeting-1") is None


def test_chatroom_prompt_audit_uses_current_conversation_language_not_template_language(
    tmp_path,
) -> None:
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "chatroom_response.md").write_text("unused", encoding="utf-8")

    class Adapter:
        def complete(self, request: ModelRequest) -> ModelResponse:
            return ModelResponse('{"message":"ok"}')

    runner = MeetingRunner(
        repository=MeetingRepository(tmp_path / "data"),
        prompt_renderer=PromptRenderer(prompt_dir),
        adapters=RunnerAdapters(by_name={"mock": Adapter()}),
    )
    instruction = "Please compare the two options and recommend one."
    persona = "UNIQUE_HOST_PERSONA"

    runner.chat_respond_as_role(
        meeting_id="meeting-1",
        goal="Product decision",
        role="host",
        role_display_name="Host AI",
        instruction=instruction,
        model_assignments={"host": ModelConfig(id="m", adapter="mock")},
        inputs={"__chatroom_persona_prompts": {"host": persona}},
    )

    messages = runner.repository.read_events("meeting-1")[-1]["prompt_messages"]
    assert [message["role"] for message in messages] == ["system", "developer", "user"]
    system, developer, user = [message["content"] for message in messages]
    assert (
        "Answer in the language of the current user message and meeting conversation "
        "unless the user explicitly requests another language."
    ) in system
    assert (
        "The language used by this prompt template must not determine the answer language."
    ) in developer
    assert persona in system
    assert persona not in developer
    assert persona not in user
    assert "chat-message/v1" not in system
    assert "chat-message/v1" in developer
    assert "chat-message/v1" not in user
    assert instruction not in system
    assert instruction not in developer
    assert user.endswith(instruction)


def test_chatroom_parse_retry_reuses_identical_canonical_prompt(tmp_path) -> None:
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "chatroom_response.md").write_text("unused", encoding="utf-8")

    class Adapter:
        def __init__(self) -> None:
            self.calls = 0

        def complete(self, request: ModelRequest) -> ModelResponse:
            self.calls += 1
            return ModelResponse("not-json" if self.calls == 1 else '{"message":"ok"}')

    runner = MeetingRunner(
        repository=MeetingRepository(tmp_path / "data"),
        prompt_renderer=PromptRenderer(prompt_dir),
        adapters=RunnerAdapters(by_name={"mock": (adapter := Adapter())}),
    )
    runner.chat_respond_as_role(
        meeting_id="meeting-1",
        goal="測試",
        role="host",
        role_display_name="主持 AI",
        instruction="請重試",
        model_assignments={"host": ModelConfig(id="m", adapter="mock")},
        inputs={"__chatroom_persona_prompts": {"host": "固定主持 Persona"}},
    )
    events = runner.repository.read_events("meeting-1")
    attempts = [event for event in events if event.get("role") == "host"]
    assert [event["status"] for event in attempts] == ["failed", "completed"]
    assert attempts[0]["prompt_messages"] == attempts[1]["prompt_messages"]


def test_chatroom_execution_rejects_a_missing_persona_before_transport(tmp_path) -> None:
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "chatroom_response.md").write_text("unused", encoding="utf-8")

    class Adapter:
        def __init__(self) -> None:
            self.called = False

        def complete(self, request: ModelRequest) -> ModelResponse:
            self.called = True
            return ModelResponse('{"message":"must not run"}')

    adapter = Adapter()
    runner = MeetingRunner(
        repository=MeetingRepository(tmp_path / "data"),
        prompt_renderer=PromptRenderer(prompt_dir),
        adapters=RunnerAdapters(by_name={"mock": adapter}),
    )

    with pytest.raises(ValueError, match="persona_prompt"):
        runner.chat_respond_as_role(
            meeting_id="meeting-1",
            goal="測試",
            role="host",
            role_display_name="主持 AI",
            instruction="不得使用 fallback",
            model_assignments={"host": ModelConfig(id="m", adapter="mock")},
            inputs={"__chatroom_persona_prompts": {"host": "   "}},
        )

    assert adapter.called is False
