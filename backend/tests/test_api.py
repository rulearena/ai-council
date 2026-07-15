from __future__ import annotations

import json
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_council.api import (
    MeetingJobManager,
    MeetingMetadataStore,
    ModelHealthCheckResult,
    ModelHealthCheckStore,
    create_app,
)
from ai_council.models.adapters import AdapterError, MockModelAdapter, ModelRequest, ModelResponse
from ai_council.models.config import ModelConfigRepository
from ai_council.meetings.repository import MeetingRepository
from ai_council.meetings.deliberation import DeliberationEpochs, RestartCommand

TEST_BLUE_PROPOSE_TEMPLATE_HASH = "28f2086e8a3af020b64aa6f2b3e3abda9046507388e535b194eb1b9fec80fe7d"
TEST_OUTPUT_SCHEMA_HASH = "15a45919652be5c70d3fd1690a10d37f876f19a14b2a76cc0f21765def281377"


def test_models_endpoint_lists_configured_models(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.get("/models")

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": "mock-fast",
            "adapter": "mock",
            "base_url": None,
            "model": None,
            "api_key_env": None,
            "supports_json_mode": False,
            "extra_body": {},
            "pricing": None,
            "command": None,
            "timeout_seconds": 120.0,
            "status": "unknown",
            "health_checked_at": None,
            "health_error": None,
            "credential": None,
        }
    ]


def test_case_file_limits_endpoint_reports_default_limits(tmp_path: Path) -> None:
    client = TestClient(create_test_app(tmp_path))

    response = client.get("/case-file-limits")

    assert response.status_code == 200
    assert response.json() == {"per_file_chars": 50_000, "total_chars": 120_000}


def test_case_file_limits_endpoint_reports_environment_overrides(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AI_COUNCIL_MAX_CASE_FILE_CHARS", "70000")
    monkeypatch.setenv("AI_COUNCIL_MAX_TOTAL_CASE_FILE_CHARS", "150000")
    client = TestClient(create_test_app(tmp_path))

    response = client.get("/case-file-limits")

    assert response.status_code == 200
    assert response.json() == {"per_file_chars": 70_000, "total_chars": 150_000}


@pytest.mark.parametrize(
    ("per_file", "total", "message"),
    [
        ("not-a-number", "120000", "AI_COUNCIL_MAX_CASE_FILE_CHARS must be a positive integer"),
        ("0", "120000", "AI_COUNCIL_MAX_CASE_FILE_CHARS must be a positive integer"),
        ("50000", "-1", "AI_COUNCIL_MAX_TOTAL_CASE_FILE_CHARS must be a positive integer"),
        (
            "50000",
            "49999",
            "AI_COUNCIL_MAX_TOTAL_CASE_FILE_CHARS must be greater than or equal to AI_COUNCIL_MAX_CASE_FILE_CHARS",
        ),
    ],
)
def test_invalid_case_file_limit_environment_fails_app_startup_clearly(
    tmp_path: Path,
    monkeypatch,
    per_file: str,
    total: str,
    message: str,
) -> None:
    monkeypatch.setenv("AI_COUNCIL_MAX_CASE_FILE_CHARS", per_file)
    monkeypatch.setenv("AI_COUNCIL_MAX_TOTAL_CASE_FILE_CHARS", total)

    with pytest.raises(ValueError, match=f"^{message}$"):
        create_test_app(tmp_path)


def test_startup_health_check_marks_mock_model_available(tmp_path: Path) -> None:
    app = create_test_app(tmp_path, start_model_health_checks=True)
    client = TestClient(app)

    model = wait_for_model_status(client, "mock-fast", "available")

    assert model["health_checked_at"]
    assert model["health_error"] is None
    assert "available" not in (tmp_path / "config" / "models.yaml").read_text(encoding="utf-8")


def test_startup_health_check_marks_adapter_failures_unavailable(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def raise_url_error(request, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(
        "ai_council.models.adapters.urllib.request.urlopen",
        raise_url_error,
    )
    app = create_test_app(
        tmp_path,
        start_model_health_checks=True,
        models_yaml="""
models:
  - id: http-down
    adapter: openai-compatible-http
    base_url: http://example.test/v1
    model: test-model
""".strip(),
    )
    client = TestClient(app)

    model = wait_for_model_status(client, "http-down", "unavailable")

    assert model["health_checked_at"]
    assert model["health_error"] == "<urlopen error connection refused>"


def test_startup_health_check_does_not_block_app_creation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    release_health_check = threading.Event()

    def slow_urlopen(request, timeout):
        release_health_check.wait(timeout=2)
        return FakeHTTPResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"summary":"OK","arguments":[],"risks":[],"recommendation":"Go"}'
                        }
                    }
                ]
            }
        )

    monkeypatch.setattr(
        "ai_council.models.adapters.urllib.request.urlopen",
        slow_urlopen,
    )

    started_at = time.monotonic()
    try:
        create_test_app(
            tmp_path,
            start_model_health_checks=True,
            models_yaml="""
models:
  - id: slow-http
    adapter: openai-compatible-http
    base_url: http://example.test/v1
    model: test-model
""".strip(),
        )
    finally:
        release_health_check.set()

    assert time.monotonic() - started_at < 0.5


def test_model_config_crud_endpoints_update_models_yaml(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    created = client.post(
        "/models",
        json={
            "id": "qwen27",
            "adapter": "openai-compatible-http",
            "base_url": "http://192.168.50.80:8487/v1",
            "model": "bartowski/Qwen_Qwen3.6-27B-GGUF",
            "api_key_env": None,
            "supports_json_mode": True,
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        },
    )

    assert created.status_code == 201
    assert created.json()["id"] == "qwen27"
    assert created.json()["supports_json_mode"] is True
    assert [model["id"] for model in client.get("/models").json()] == ["mock-fast", "qwen27"]

    updated = client.put(
        "/models/qwen27",
        json={
            "adapter": "openai-compatible-http",
            "base_url": "http://127.0.0.1:8487/v1",
            "model": "updated-model",
            "supports_json_mode": False,
        },
    )

    assert updated.status_code == 200
    assert updated.json()["base_url"] == "http://127.0.0.1:8487/v1"
    assert updated.json()["model"] == "updated-model"

    deleted = client.delete("/models/qwen27")

    assert deleted.status_code == 200
    assert deleted.json() == {"id": "qwen27", "warning": None}
    assert [model["id"] for model in client.get("/models").json()] == ["mock-fast"]


def test_model_config_crud_reports_validation_errors(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.put(
        "/models/broken",
        json={"adapter": "openai-compatible-http"},
    )

    assert response.status_code == 422
    fields = {item["field"] for item in response.json()["detail"]}
    assert {"base_url", "model"} <= fields

    pricing_response = client.put(
        "/models/broken-pricing",
        json={
            "adapter": "mock",
            "pricing": {
                "currency": "USD",
                "input_per_1m_tokens": -1,
                "output_per_1m_tokens": 10.0,
            },
        },
    )

    assert pricing_response.status_code == 422
    assert any(
        item["field"] == "pricing.input_per_1m_tokens"
        for item in pricing_response.json()["detail"]
    )

    missing_adapter = client.put("/models/broken", json={})

    assert missing_adapter.status_code == 422
    assert any(item["field"] == "adapter" for item in missing_adapter.json()["detail"])


def test_delete_model_returns_warning_when_referenced_by_open_meeting(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    meeting_id = client.post("/meetings", json={"title": "先做後端？", "goal": "先做後端？"}).json()["meeting_id"]
    client.post(
        f"/meetings/{meeting_id}/start",
        json={"models": {"Blue": "mock-fast", "Red": "mock-fast", "Judge": "mock-fast"}},
    )
    wait_for_activity(client, meeting_id, "completed")

    deleted = client.delete("/models/mock-fast")

    assert deleted.status_code == 200
    body = deleted.json()
    assert body["id"] == "mock-fast"
    assert body["warning"] is not None
    assert meeting_id in body["warning"]
    assert client.get("/models").json() == []


def test_delete_model_no_warning_when_meeting_closed(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    meeting_id = client.post("/meetings", json={"title": "先做後端？", "goal": "先做後端？"}).json()["meeting_id"]
    client.post(
        f"/meetings/{meeting_id}/start",
        json={"models": {"Blue": "mock-fast", "Red": "mock-fast", "Judge": "mock-fast"}},
    )
    wait_for_activity(client, meeting_id, "completed")
    close_response = client.post(f"/meetings/{meeting_id}/close")
    assert close_response.status_code == 200

    deleted = client.delete("/models/mock-fast")

    assert deleted.status_code == 200
    assert deleted.json() == {"id": "mock-fast", "warning": None}


def test_delete_unknown_model_still_404(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.delete("/models/does-not-exist")

    assert response.status_code == 404


def test_post_models_creates_and_resets_status(tmp_path: Path) -> None:
    app = create_test_app(tmp_path, start_model_health_checks=True)
    client = TestClient(app)
    wait_for_model_status(client, "mock-fast", "available")

    created = client.post(
        "/models",
        json={
            "id": "qwen",
            "adapter": "openai-compatible-http",
            "base_url": "http://192.168.50.80:8487/v1",
            "model": "bartowski/Qwen_Qwen3.6-27B-GGUF",
        },
    )

    assert created.status_code == 201
    assert created.json()["id"] == "qwen"
    assert {model["id"] for model in client.get("/models").json()} == {"mock-fast", "qwen"}

    duplicate = client.post(
        "/models",
        json={
            "id": "qwen",
            "adapter": "openai-compatible-http",
            "base_url": "http://192.168.50.80:8487/v1",
            "model": "bartowski/Qwen_Qwen3.6-27B-GGUF",
        },
    )

    assert duplicate.status_code == 422
    assert any(item["field"] == "id" for item in duplicate.json()["detail"])

    # mock-fast was already marked "available" by the startup health checker;
    # saving it via PUT must clear that record so status resets to "unknown".
    updated = client.put("/models/mock-fast", json={"adapter": "mock"})

    assert updated.status_code == 200
    assert updated.json()["status"] == "unknown"
    refreshed = next(model for model in client.get("/models").json() if model["id"] == "mock-fast")
    assert refreshed["status"] == "unknown"


def test_concurrent_post_models_with_same_id_only_one_succeeds(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    # Delay the first save_model() call so it starts *after* its own
    # existence check already passed but *before* it writes to disk. If the
    # existence-check-then-save critical section isn't locked, a second POST
    # can slip its own existence check into that window and also pass.
    original_save_model = ModelConfigRepository.save_model
    first_call_started = threading.Event()
    call_count = {"n": 0}
    count_lock = threading.Lock()

    def slow_save_model(self: ModelConfigRepository, model):
        with count_lock:
            call_count["n"] += 1
            is_first_call = call_count["n"] == 1
        if is_first_call:
            first_call_started.set()
            time.sleep(0.3)
        return original_save_model(self, model)

    monkeypatch.setattr(ModelConfigRepository, "save_model", slow_save_model)

    payload = {"id": "race-model", "adapter": "mock"}
    results: dict[str, int] = {}

    def post(key: str) -> None:
        results[key] = client.post("/models", json=payload).status_code

    thread_one = threading.Thread(target=post, args=("first",))
    thread_one.start()
    assert first_call_started.wait(timeout=2)

    thread_two = threading.Thread(target=post, args=("second",))
    thread_two.start()

    thread_one.join(timeout=3)
    thread_two.join(timeout=3)

    # Without a lock serializing "check existence -> save" both requests can
    # observe "no existing model" and both succeed, creating a duplicate.
    assert sorted(results.values()) == [201, 422]
    assert sorted(model["id"] for model in client.get("/models").json()) == [
        "mock-fast",
        "race-model",
    ]


def test_post_models_validates_id_format(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    bad_characters = client.post("/models", json={"id": "bad id!", "adapter": "mock"})

    assert bad_characters.status_code == 422
    assert any(item["field"] == "id" for item in bad_characters.json()["detail"])

    leading_dash = client.post("/models", json={"id": "-leading-dash", "adapter": "mock"})

    assert leading_dash.status_code == 422
    assert any(item["field"] == "id" for item in leading_dash.json()["detail"])


def test_put_models_is_update_only(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.put("/models/never-created", json={"adapter": "mock"})

    assert response.status_code == 404


def test_model_validation_errors_are_per_field_422(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    missing_fields = client.post("/models", json={"id": "x", "adapter": "openai-compatible-http"})

    assert missing_fields.status_code == 422
    fields = {item["field"] for item in missing_fields.json()["detail"]}
    assert {"base_url", "model"} <= fields

    unknown_adapter = client.post("/models", json={"id": "y", "adapter": "no-such-adapter"})

    assert unknown_adapter.status_code == 422
    assert any(item["field"] == "adapter" for item in unknown_adapter.json()["detail"])

    missing_command = client.post("/models", json={"id": "z", "adapter": "subscription-cli"})

    assert missing_command.status_code == 422
    assert any(item["field"] == "command" for item in missing_command.json()["detail"])


def test_post_models_pydantic_errors_use_per_field_shape(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    missing_adapter = client.post("/models", json={"id": "no-adapter"})

    assert missing_adapter.status_code == 422
    assert any(item["field"] == "adapter" for item in missing_adapter.json()["detail"])

    negative_pricing = client.post(
        "/models",
        json={
            "id": "bad-pricing",
            "adapter": "mock",
            "pricing": {
                "currency": "USD",
                "input_per_1m_tokens": -1,
                "output_per_1m_tokens": 10.0,
            },
        },
    )

    assert negative_pricing.status_code == 422
    assert any(
        item["field"] == "pricing.input_per_1m_tokens"
        for item in negative_pricing.json()["detail"]
    )


def test_models_endpoint_reports_invalid_config_file(tmp_path: Path) -> None:
    app = create_test_app(
        tmp_path,
        models_yaml="""
models:
  - adapter: mock
""".strip(),
    )
    client = TestClient(app)

    response = client.get("/models")

    assert response.status_code == 400
    assert response.json()["detail"] == "Model entry requires id and adapter"


def test_models_endpoint_reports_env_credential_status_without_secret(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("PRESENT_API_KEY", "secret-value")
    app = create_test_app(
        tmp_path,
        models_yaml="""
models:
  - id: cloud-ready
    adapter: openai-compatible-http
    base_url: http://example.test/v1
    model: cloud-model
    api_key_env: PRESENT_API_KEY
  - id: cloud-missing
    adapter: openai-compatible-http
    base_url: http://example.test/v1
    model: cloud-model
    api_key_env: MISSING_API_KEY
""".strip(),
    )
    client = TestClient(app)

    models = client.get("/models").json()

    assert models[0]["credential"] == {
        "type": "env",
        "env_var": "PRESENT_API_KEY",
        "configured": True,
    }
    assert models[1]["credential"] == {
        "type": "env",
        "env_var": "MISSING_API_KEY",
        "configured": False,
    }
    assert "secret-value" not in json.dumps(models)


def test_openai_compatible_model_discovery_lists_endpoint_models(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = create_test_app(
        tmp_path,
        models_yaml="""
models:
  - id: local-endpoint
    adapter: openai-compatible-http
    base_url: http://example.test/v1
    model: configured-model
""".strip(),
    )
    client = TestClient(app)

    def fake_urlopen(request, timeout):
        assert request.full_url == "http://example.test/v1/models"
        return FakeHTTPResponse(
            {
                "data": [
                    {"id": "bartowski/Qwen_Qwen3.6-27B-GGUF"},
                    {"id": "deepreinforce-ai/Ornith-1.0-35B-GGUF"},
                ]
            }
        )

    monkeypatch.setattr("ai_council.models.adapters.urllib.request.urlopen", fake_urlopen)

    response = client.get("/models/local-endpoint/available-models")

    assert response.status_code == 200
    assert response.json() == {
        "models": [
            "bartowski/Qwen_Qwen3.6-27B-GGUF",
            "deepreinforce-ai/Ornith-1.0-35B-GGUF",
        ]
    }


def test_model_discovery_preview_lists_models_without_saving_config(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    config_path = tmp_path / "config" / "models.yaml"
    original_config = config_path.read_text(encoding="utf-8")

    def fake_urlopen(request, timeout):
        assert request.full_url == "http://preview.example.test/v1/models"
        return FakeHTTPResponse({"data": [{"id": "preview-model"}]})

    monkeypatch.setattr("ai_council.models.adapters.urllib.request.urlopen", fake_urlopen)

    response = client.post(
        "/models/available-models",
        json={
            "adapter": "openai-compatible-http",
            "base_url": "http://preview.example.test/v1",
            "api_key_env": None,
        },
    )

    assert response.status_code == 200
    assert response.json() == {"models": ["preview-model"]}
    assert config_path.read_text(encoding="utf-8") == original_config


def test_model_discovery_preview_preserves_an_empty_model_list(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "ai_council.models.adapters.urllib.request.urlopen",
        lambda request, timeout: FakeHTTPResponse({"data": []}),
    )
    client = TestClient(create_test_app(tmp_path))

    response = client.post(
        "/models/available-models",
        json={
            "adapter": "openai-compatible-http",
            "base_url": "http://empty.example.test/v1",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"models": []}


def test_anthropic_model_discovery_preview_uses_provider_contract_and_normalizes_models(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_DISCOVERY_KEY", "anthropic-secret")

    def fake_urlopen(request, timeout):
        assert request.full_url == "https://api.anthropic.test/v1/models"
        assert request.get_header("X-api-key") == "anthropic-secret"
        assert request.get_header("Anthropic-version") == "2023-06-01"
        return FakeHTTPResponse(
            {
                "data": [
                    {"id": "claude-z"},
                    {"id": "claude-a"},
                    {"id": "claude-z"},
                ],
                "has_more": False,
            }
        )

    monkeypatch.setattr("ai_council.models.adapters.urllib.request.urlopen", fake_urlopen)
    client = TestClient(create_test_app(tmp_path))

    response = client.post(
        "/models/available-models",
        json={
            "adapter": "anthropic-http",
            "base_url": "https://api.anthropic.test/v1/",
            "api_key_env": "ANTHROPIC_DISCOVERY_KEY",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"models": ["claude-a", "claude-z"]}


def test_anthropic_existing_model_discovery_follows_provider_pagination(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_EXISTING_KEY", "existing-secret")
    requests = []

    def fake_urlopen(request, timeout):
        requests.append(request)
        if request.full_url == "https://api.anthropic.test/v1/models":
            return FakeHTTPResponse(
                {
                    "data": [{"id": "claude-b"}, {"id": "claude-a"}],
                    "has_more": True,
                    "last_id": "claude-b",
                }
            )
        assert request.full_url == (
            "https://api.anthropic.test/v1/models?after_id=claude-b"
        )
        return FakeHTTPResponse(
            {
                "data": [{"id": "claude-c"}, {"id": "claude-a"}],
                "has_more": False,
            }
        )

    monkeypatch.setattr("ai_council.models.adapters.urllib.request.urlopen", fake_urlopen)
    client = TestClient(
        create_test_app(
            tmp_path,
            models_yaml="""
models:
  - id: claude-existing
    adapter: anthropic-http
    base_url: https://api.anthropic.test/v1
    model: claude-a
    api_key_env: ANTHROPIC_EXISTING_KEY
""".strip(),
        )
    )

    response = client.get("/models/claude-existing/available-models")

    assert response.status_code == 200
    assert response.json() == {"models": ["claude-a", "claude-b", "claude-c"]}
    assert len(requests) == 2
    assert all(request.get_header("X-api-key") == "existing-secret" for request in requests)


def test_gemini_model_discovery_preview_uses_provider_contract_and_paginates(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("GEMINI_DISCOVERY_KEY", "gemini-secret")
    requested_urls = []

    def fake_urlopen(request, timeout):
        requested_urls.append(request.full_url)
        if request.full_url == (
            "https://generativelanguage.googleapis.test/v1beta/models?key=gemini-secret"
        ):
            return FakeHTTPResponse(
                {
                    "models": [
                        {"name": "models/gemini-z"},
                        {"name": "models/gemini-a"},
                    ],
                    "nextPageToken": "page two",
                }
            )
        assert request.full_url == (
            "https://generativelanguage.googleapis.test/v1beta/models"
            "?key=gemini-secret&pageToken=page+two"
        )
        return FakeHTTPResponse(
            {"models": [{"name": "models/gemini-a"}, {"name": "models/gemini-m"}]}
        )

    monkeypatch.setattr("ai_council.models.adapters.urllib.request.urlopen", fake_urlopen)
    client = TestClient(create_test_app(tmp_path))

    response = client.post(
        "/models/available-models",
        json={
            "adapter": "gemini-http",
            "base_url": "https://generativelanguage.googleapis.test/v1beta/",
            "api_key_env": "GEMINI_DISCOVERY_KEY",
        },
    )

    assert response.status_code == 200
    assert response.json() == {"models": ["gemini-a", "gemini-m", "gemini-z"]}
    assert len(requested_urls) == 2


def test_gemini_existing_model_discovery_lists_only_generate_content_models(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("GEMINI_EXISTING_KEY", "existing-gemini-secret")

    def fake_urlopen(request, timeout):
        assert request.full_url == (
            "https://generativelanguage.googleapis.test/v1beta/models"
            "?key=existing-gemini-secret"
        )
        return FakeHTTPResponse(
            {
                "models": [
                    {
                        "name": "models/gemini-generative",
                        "supportedGenerationMethods": ["generateContent", "countTokens"],
                    },
                    {
                        "name": "models/text-embedding-only",
                        "supportedGenerationMethods": ["embedContent"],
                    },
                ]
            }
        )

    monkeypatch.setattr("ai_council.models.adapters.urllib.request.urlopen", fake_urlopen)
    client = TestClient(
        create_test_app(
            tmp_path,
            models_yaml="""
models:
  - id: gemini-existing
    adapter: gemini-http
    base_url: https://generativelanguage.googleapis.test/v1beta
    model: gemini-generative
    api_key_env: GEMINI_EXISTING_KEY
""".strip(),
        )
    )

    response = client.get("/models/gemini-existing/available-models")

    assert response.status_code == 200
    assert response.json() == {"models": ["gemini-generative"]}


@pytest.mark.parametrize(
    ("adapter", "payload"),
    [
        ("anthropic-http", {"data": [], "has_more": False}),
        ("gemini-http", {"models": []}),
    ],
)
def test_provider_model_discovery_preserves_empty_lists(
    tmp_path: Path,
    monkeypatch,
    adapter: str,
    payload: dict[str, object],
) -> None:
    monkeypatch.setattr(
        "ai_council.models.adapters.urllib.request.urlopen",
        lambda request, timeout: FakeHTTPResponse(payload),
    )
    client = TestClient(create_test_app(tmp_path))

    response = client.post(
        "/models/available-models",
        json={"adapter": adapter, "base_url": "https://empty.example.test/v1"},
    )

    assert response.status_code == 200
    assert response.json() == {"models": []}


@pytest.mark.parametrize("adapter", ["anthropic-http", "gemini-http"])
def test_provider_model_discovery_redacts_upstream_errors(
    tmp_path: Path,
    monkeypatch,
    adapter: str,
) -> None:
    secret = f"{adapter}-secret"
    monkeypatch.setenv("PROVIDER_DISCOVERY_KEY", secret)

    def reject_request(request, timeout):
        raise urllib.error.URLError(f"provider rejected credential {secret}")

    monkeypatch.setattr(
        "ai_council.models.adapters.urllib.request.urlopen",
        reject_request,
    )
    client = TestClient(create_test_app(tmp_path))

    response = client.post(
        "/models/available-models",
        json={
            "adapter": adapter,
            "base_url": "https://failure.example.test/v1",
            "api_key_env": "PROVIDER_DISCOVERY_KEY",
        },
    )

    assert response.status_code == 502
    serialized = json.dumps(response.json())
    assert secret not in serialized
    assert "[REDACTED]" in serialized


def test_gemini_model_discovery_redacts_encoded_credentials_from_upstream_urls(
    tmp_path: Path,
    monkeypatch,
) -> None:
    secret = "key+ /?%&"
    monkeypatch.setenv("GEMINI_RESERVED_KEY", secret)

    def echo_request_url(request, timeout):
        raise urllib.error.URLError(f"request failed: {request.full_url}")

    monkeypatch.setattr(
        "ai_council.models.adapters.urllib.request.urlopen",
        echo_request_url,
    )
    client = TestClient(create_test_app(tmp_path))

    response = client.post(
        "/models/available-models",
        json={
            "adapter": "gemini-http",
            "base_url": "https://failure.example.test/v1beta",
            "api_key_env": "GEMINI_RESERVED_KEY",
        },
    )

    assert response.status_code == 502
    serialized = json.dumps(response.json())
    encoded_variants = {
        secret,
        urllib.parse.quote(secret),
        urllib.parse.quote(secret, safe=""),
        urllib.parse.quote_plus(secret),
        urllib.parse.urlencode({"key": secret}).partition("=")[2],
    }
    assert all(variant not in serialized for variant in encoded_variants)
    assert "[REDACTED]" in serialized


@pytest.mark.parametrize("adapter", ["anthropic-http", "gemini-http"])
def test_provider_model_discovery_reports_missing_credential_environment(
    tmp_path: Path,
    monkeypatch,
    adapter: str,
) -> None:
    monkeypatch.delenv("MISSING_PROVIDER_DISCOVERY_KEY", raising=False)
    client = TestClient(create_test_app(tmp_path))

    response = client.post(
        "/models/available-models",
        json={
            "adapter": adapter,
            "base_url": "https://unused.example.test/v1",
            "api_key_env": "MISSING_PROVIDER_DISCOVERY_KEY",
        },
    )

    assert response.status_code == 502
    assert response.json() == {
        "detail": (
            "Environment variable MISSING_PROVIDER_DISCOVERY_KEY is not set for API key"
        )
    }


@pytest.mark.parametrize("adapter", ["subscription-cli", "mock"])
def test_model_discovery_preview_rejects_unsupported_adapters(
    tmp_path: Path,
    adapter: str,
) -> None:
    client = TestClient(create_test_app(tmp_path))

    response = client.post(
        "/models/available-models",
        json={"adapter": adapter, "base_url": "http://unused.example.test/v1"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": f"Model discovery is not supported for adapter: {adapter}"
    }


def test_model_discovery_preview_redacts_provider_errors(
    tmp_path: Path,
    monkeypatch,
) -> None:
    secret = "preview-secret-value"
    monkeypatch.setenv("PREVIEW_API_KEY", secret)

    def echo_secret_in_error(request, timeout):
        raise urllib.error.URLError(f"provider rejected Bearer {secret}")

    monkeypatch.setattr(
        "ai_council.models.adapters.urllib.request.urlopen",
        echo_secret_in_error,
    )
    client = TestClient(create_test_app(tmp_path))

    response = client.post(
        "/models/available-models",
        json={
            "adapter": "openai-compatible-http",
            "base_url": "http://preview.example.test/v1",
            "api_key_env": "PREVIEW_API_KEY",
        },
    )

    assert response.status_code == 502
    serialized = json.dumps(response.json())
    assert secret not in serialized
    assert "[REDACTED]" in serialized


def test_model_discovery_preview_rejects_api_key_values_without_echoing_them(
    tmp_path: Path,
) -> None:
    secret = "must-not-enter-preview-contract"
    client = TestClient(create_test_app(tmp_path))

    response = client.post(
        "/models/available-models",
        json={
            "adapter": "openai-compatible-http",
            "base_url": "http://preview.example.test/v1",
            "api_key": secret,
        },
    )

    assert response.status_code == 422
    serialized = json.dumps(response.json())
    assert secret not in serialized
    assert response.json()["detail"] == [
        {"field": "api_key", "message": "Extra inputs are not permitted"}
    ]


def test_model_discovery_rejects_unsupported_adapters(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.get("/models/mock-fast/available-models")

    assert response.status_code == 400
    assert response.json()["detail"] == "Model discovery is not supported for adapter: mock"


def test_http_model_test_endpoint_marks_available(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = create_test_app(
        tmp_path,
        models_yaml="""
models:
  - id: http-ok
    adapter: openai-compatible-http
    base_url: http://example.test/v1
    model: test-model
""".strip(),
    )
    client = TestClient(app)

    monkeypatch.setattr(
        "ai_council.models.adapters.urllib.request.urlopen",
        lambda request, timeout: FakeHTTPResponse(
            {
                "choices": [
                    {
                        "message": {
                            "content": '{"summary":"OK","arguments":[],"risks":[],"recommendation":"Go"}'
                        }
                    }
                ]
            }
        ),
    )

    response = client.post("/models/http-ok/test")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "available"
    assert payload["tested_at"]

    listed = next(model for model in client.get("/models").json() if model["id"] == "http-ok")
    assert listed["status"] == "available"


def test_http_model_test_endpoint_marks_unavailable_on_adapter_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = create_test_app(
        tmp_path,
        models_yaml="""
models:
  - id: http-down
    adapter: openai-compatible-http
    base_url: http://example.test/v1
    model: test-model
""".strip(),
    )
    client = TestClient(app)

    def raise_url_error(request, timeout):
        raise urllib.error.URLError("connection refused")

    monkeypatch.setattr(
        "ai_council.models.adapters.urllib.request.urlopen",
        raise_url_error,
    )

    response = client.post("/models/http-down/test")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["tested_at"]
    assert payload["error"] == "<urlopen error connection refused>"

    listed = next(model for model in client.get("/models").json() if model["id"] == "http-down")
    assert listed["status"] == "unavailable"


def test_model_health_store_only_records_latest_started_check() -> None:
    store = ModelHealthCheckStore()

    older_check = store.begin("m")
    newer_check = store.begin("m")

    newer_result = ModelHealthCheckResult(status="unavailable", checked_at="t2")
    store.record("m", newer_result, newer_check)

    older_result = ModelHealthCheckResult(status="available", checked_at="t1")
    store.record("m", older_result, older_check)

    assert store.get("m") == newer_result


def test_model_health_store_clear_invalidates_in_flight_check() -> None:
    store = ModelHealthCheckStore()

    in_flight_check = store.begin("m")
    store.clear("m")

    stale_result = ModelHealthCheckResult(status="available", checked_at="t1")
    store.record("m", stale_result, in_flight_check)

    assert store.get("m") is None

    fresh_check = store.begin("m")
    fresh_result = ModelHealthCheckResult(status="unavailable", checked_at="t2")
    store.record("m", fresh_result, fresh_check)

    assert store.get("m") == fresh_result


def test_concurrent_test_requests_keep_newer_health_result(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = create_test_app(tmp_path)
    older_check_started = threading.Event()
    release_older_check = threading.Event()
    call_lock = threading.Lock()
    call_count = 0

    def complete_in_reverse_order(self, request):
        nonlocal call_count
        with call_lock:
            call_count += 1
            call_number = call_count
        if call_number == 1:
            older_check_started.set()
            assert release_older_check.wait(timeout=2)
            return ModelResponse(
                raw_output='{"summary":"old","arguments":[],"risks":[],"recommendation":"old"}'
            )
        raise AdapterError("newer check failed")

    monkeypatch.setattr(MockModelAdapter, "complete", complete_in_reverse_order)

    with ThreadPoolExecutor(max_workers=2) as executor:
        older_response = executor.submit(
            lambda: TestClient(app).post("/models/mock-fast/test")
        )
        assert older_check_started.wait(timeout=2)
        newer_response = TestClient(app).post("/models/mock-fast/test")
        release_older_check.set()
        older_payload = older_response.result(timeout=2)

    assert older_payload.json()["status"] == "available"
    newer_payload = newer_response.json()
    assert newer_payload["status"] == "unavailable"
    assert newer_payload["tested_at"]
    assert newer_payload["error"] == "newer check failed"
    listed = next(
        model
        for model in TestClient(app).get("/models").json()
        if model["id"] == "mock-fast"
    )
    assert listed["status"] == "unavailable"
    assert listed["health_error"] == "newer check failed"


def test_test_model_endpoint_drops_stale_check_when_save_races_after_begin(
    tmp_path: Path,
    monkeypatch,
) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    from ai_council import api as api_module

    original_get_model = api_module.get_model

    def get_model_then_race(repository, model_id):
        # Return the model as it was read, but land a concurrent PUT (which
        # saves + clears the health record) while this check is in flight.
        # The token acquired before the config read must then be stale.
        model = original_get_model(repository, model_id)
        response = client.put(f"/models/{model_id}", json={"adapter": "mock"})
        assert response.status_code == 200
        return model

    monkeypatch.setattr(api_module, "get_model", get_model_then_race)

    test_response = client.post("/models/mock-fast/test")

    assert test_response.status_code == 200

    # The manual test's result was computed against a pre-race config read
    # and must not clobber the fresher "unknown" reset the racing PUT made.
    listed = next(model for model in client.get("/models").json() if model["id"] == "mock-fast")
    assert listed["status"] == "unknown"


def test_meeting_title_goal_contract_and_explicit_legacy_migration(tmp_path: Path) -> None:
    client = TestClient(create_test_app(tmp_path))

    legacy_contract = client.post("/meetings", json={"topic": "舊主題"})
    blank_title = client.post("/meetings", json={"title": "   ", "goal": "判斷責任"})
    blank_goal = client.post("/meetings", json={"title": "土地糾紛案", "goal": "  "})

    assert legacy_contract.status_code == 422
    assert blank_title.status_code == 422
    assert blank_goal.status_code == 422

    created = client.post(
        "/meetings",
        json={"title": "土地糾紛案", "goal": "判斷被告是否構成無權占有"},
    )

    assert created.status_code == 200
    assert created.json()["title"] == "土地糾紛案"
    assert created.json()["goal"] == "判斷被告是否構成無權占有"
    assert created.json()["requires_goal"] is False
    assert "topic" not in created.json()
    metadata_path = (
        tmp_path / "data" / "meetings" / created.json()["meeting_id"] / "metadata.json"
    )
    assert json.loads(metadata_path.read_text(encoding="utf-8"))["goal"] == "判斷被告是否構成無權占有"

    legacy_id = "meeting-legacy-goal-gate"
    legacy_dir = tmp_path / "data" / "meetings" / legacy_id
    legacy_dir.mkdir(parents=True)
    (legacy_dir / "metadata.json").write_text(
        json.dumps(
            {
                "meeting_id": legacy_id,
                "topic": "舊土地案",
                "created_at": "2026-07-14T00:00:00+00:00",
                "tags": [],
                "pinned": False,
                "mode_id": "red-blue",
                "participants": [],
                "inputs": {},
                "case_files": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    events_path = legacy_dir / "events.jsonl"
    original_events = '{"event_id":"historical","role":"Human","content":"保留"}\n'
    events_path.write_text(original_events, encoding="utf-8")

    fetched = client.get(f"/meetings/{legacy_id}")
    assert fetched.status_code == 200
    assert fetched.json()["title"] == "舊土地案"
    assert fetched.json()["goal"] is None
    assert fetched.json()["requires_goal"] is True

    for method, path, body in [
        ("post", f"/meetings/{legacy_id}/start", {}),
        (
            "post",
            f"/meetings/{legacy_id}/roles/Blue/respond",
            {"instruction": "請回答目前爭點"},
        ),
        ("post", f"/meetings/{legacy_id}/sequences", {"roles": ["Blue"]}),
        ("post", f"/meetings/{legacy_id}/steps/blue-propose/retry", {}),
    ]:
        response = getattr(client, method)(path, json=body)
        assert response.status_code == 409
        assert response.json()["detail"] == "Meeting goal must be set before execution"
    assert events_path.read_text(encoding="utf-8") == original_events

    migrated = client.put(
        f"/meetings/{legacy_id}/details",
        json={"title": "土地返還案", "goal": "判斷是否應返還土地"},
    )
    assert migrated.status_code == 200
    assert migrated.json()["title"] == "土地返還案"
    assert migrated.json()["goal"] == "判斷是否應返還土地"
    assert migrated.json()["requires_goal"] is False
    stored = json.loads((legacy_dir / "metadata.json").read_text(encoding="utf-8"))
    assert stored["title"] == "土地返還案"
    assert stored["goal"] == "判斷是否應返還土地"
    assert "topic" not in stored
    assert events_path.read_text(encoding="utf-8") == original_events


def test_meeting_create_list_get_start_and_transcript(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    created = client.post("/meetings", json={"title": "先做後端？", "goal": "先做後端？"}).json()

    assert created["title"] == "先做後端？"
    assert created["goal"] == "先做後端？"
    assert created["status"] == "open"
    assert created["activity_status"] == "idle"
    assert created["created_at"]
    assert created["updated_at"] == created["created_at"]
    assert created["last_step_id"] is None
    assert created["token_usage"] == {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }
    assert created["estimated_cost"] is None
    assert created["tags"] == []
    assert created["pinned"] is False
    meeting_id = created["meeting_id"]
    listed = client.get("/meetings").json()[0]
    assert listed["meeting_id"] == meeting_id
    assert listed["status"] == "open"
    assert listed["activity_status"] == "idle"
    fetched = client.get(f"/meetings/{meeting_id}").json()
    assert fetched["status"] == "open"
    assert fetched["activity_status"] == "idle"
    assert fetched["events"] == []

    start_response = client.post(
        f"/meetings/{meeting_id}/start",
        json={
            "models": {
                "Blue": "mock-fast",
                "Red": "mock-fast",
                "Judge": "mock-fast",
            }
        },
    )

    assert start_response.status_code == 202
    assert start_response.json()["status"] == "running"
    meeting = wait_for_activity(client, meeting_id, "completed")
    assert meeting["status"] == "open"
    assert meeting["activity_status"] == "completed"
    assert meeting["last_step_id"] == "judge-decide"
    assert meeting["updated_at"] >= meeting["created_at"]
    completed_steps = [
        event["step_id"]
        for event in meeting["events"]
        if event["status"] == "completed"
    ]
    assert completed_steps == [
        "blue-propose",
        "red-critique",
        "blue-revise",
        "judge-decide",
    ]
    judge_event = next(event for event in meeting["events"] if event["role"] == "Judge")
    assert judge_event["output_schema_id"] == "structured-verdict/v1"
    assert judge_event["output_schema_hash"]
    assert judge_event["parsed_output"]["decision"] == "approve-with-conditions"
    transcript = client.get(f"/meetings/{meeting_id}/transcript.md")
    assert transcript.status_code == 200
    assert transcript.text.startswith("# 先做後端？\n")
    assert "## 藍軍 - 藍軍提案" in transcript.text


def test_legacy_event_without_schema_id_projects_as_role_output_v1_without_rewrite(
    tmp_path: Path,
) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "legacy event", "goal": "legacy event"}).json()["meeting_id"]
    repository = MeetingRepository(tmp_path / "data")
    repository.append_event(
        meeting_id,
        {
            "event_id": "legacy-completed",
            "meeting_id": meeting_id,
            "step_id": "blue-propose",
            "role": "Blue",
            "attempt": 1,
            "status": "completed",
            "parsed_output": {
                "summary": "Legacy summary",
                "arguments": [],
                "risks": [],
                "recommendation": "Legacy recommendation",
            },
        },
    )

    event = client.get(f"/meetings/{meeting_id}").json()["events"][-1]
    transcript = client.get(f"/meetings/{meeting_id}/transcript.md")

    assert event["output_schema_id"] == "role-output/v1"
    assert transcript.status_code == 200
    assert "Legacy summary" in transcript.text
    assert "output_schema_id" not in repository.read_events(meeting_id)[-1]


def test_meeting_read_models_include_total_token_usage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    original_complete = MockModelAdapter.complete

    def complete_with_usage(self, request):
        response = original_complete(self, request)
        return ModelResponse(
            raw_output=response.raw_output,
            token_usage={"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
        )

    monkeypatch.setattr(MockModelAdapter, "complete", complete_with_usage)
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "usage test", "goal": "usage test"}).json()["meeting_id"]

    client.post(
        f"/meetings/{meeting_id}/start",
        json={
            "models": {
                "Blue": "mock-fast",
                "Red": "mock-fast",
                "Judge": "mock-fast",
            }
        },
    )
    meeting = wait_for_activity(client, meeting_id, "completed")

    assert meeting["token_usage"] == {
        "prompt_tokens": 8,
        "completion_tokens": 12,
        "total_tokens": 20,
    }
    assert client.get("/meetings").json()[0]["token_usage"] == meeting["token_usage"]


def test_meeting_read_models_include_estimated_cost_when_models_have_pricing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    original_complete = MockModelAdapter.complete

    def complete_with_usage(self, request):
        response = original_complete(self, request)
        return ModelResponse(
            raw_output=response.raw_output,
            token_usage={"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
        )

    monkeypatch.setattr(MockModelAdapter, "complete", complete_with_usage)
    app = create_test_app(
        tmp_path,
        models_yaml="""
models:
  - id: mock-fast
    adapter: mock
    pricing:
      currency: USD
      input_per_1m_tokens: 1.25
      output_per_1m_tokens: 10.0
""".strip(),
    )
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "cost test", "goal": "cost test"}).json()["meeting_id"]

    client.post(
        f"/meetings/{meeting_id}/start",
        json={
            "models": {
                "Blue": "mock-fast",
                "Red": "mock-fast",
                "Judge": "mock-fast",
            }
        },
    )
    meeting = wait_for_activity(client, meeting_id, "completed")

    assert meeting["estimated_cost"] == {"currency": "USD", "amount": 0.00013}
    assert client.get("/meetings").json()[0]["estimated_cost"] == meeting["estimated_cost"]


def test_start_returns_while_model_execution_continues_in_background(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model_entered = threading.Event()
    release_model = threading.Event()
    original_complete = MockModelAdapter.complete

    def slow_complete(self, request):
        model_entered.set()
        release_model.wait(timeout=2)
        return original_complete(self, request)

    monkeypatch.setattr(MockModelAdapter, "complete", slow_complete)
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "背景執行", "goal": "背景執行"}).json()["meeting_id"]

    try:
        response = client.post(
            f"/meetings/{meeting_id}/start",
            json={
                "models": {
                    "Blue": "mock-fast",
                    "Red": "mock-fast",
                    "Judge": "mock-fast",
                }
            },
        )

        assert response.status_code == 202
        assert response.json() == {"status": "running"}
        assert model_entered.wait(timeout=1)
        assert client.get(f"/meetings/{meeting_id}").json()["activity_status"] == "running"
        duplicate = client.post(
            f"/meetings/{meeting_id}/start",
            json={
                "models": {
                    "Blue": "mock-fast",
                    "Red": "mock-fast",
                    "Judge": "mock-fast",
                }
            },
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"] == "Meeting is already running"
        delete_response = client.delete(f"/meetings/{meeting_id}")
        assert delete_response.status_code == 409
        assert delete_response.json()["detail"] == "Cannot delete a running meeting"
        material_response = client.post(
            f"/meetings/{meeting_id}/materials/notes",
            json={
                "revision": 0,
                "title": "must wait",
                "content": "do not race an active prompt",
                "visible_roles": ["Blue"],
            },
        )
        assert material_response.status_code == 409
        assert material_response.json()["detail"] == "Meeting is already running"
    finally:
        release_model.set()
        wait_for_activity(client, meeting_id, "completed")


@pytest.mark.parametrize("operation", ["start", "sequence", "directed"])
def test_generic_ai_reservation_blocks_details_until_model_execution_finishes(
    tmp_path: Path,
    monkeypatch,
    operation: str,
) -> None:
    model_entered = threading.Event()
    release_model = threading.Event()
    original_complete = MockModelAdapter.complete

    def blocked_complete(self, request):
        model_entered.set()
        assert release_model.wait(timeout=5)
        return original_complete(self, request)

    monkeypatch.setattr(MockModelAdapter, "complete", blocked_complete)
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings",
        json={"title": "原標題", "goal": "原目標"},
    ).json()["meeting_id"]
    requests = {
        "start": (f"/meetings/{meeting_id}/start", {}),
        "sequence": (f"/meetings/{meeting_id}/sequences", {"roles": ["Blue"]}),
        "directed": (
            f"/meetings/{meeting_id}/roles/Blue/respond",
            {"instruction": "請補充"},
        ),
    }

    try:
        url, payload = requests[operation]
        response = client.post(url, json=payload)
        assert response.status_code == 202
        assert response.json() == {"status": "running"}
        assert model_entered.wait(timeout=2)

        details = client.put(
            f"/meetings/{meeting_id}/details",
            json={"title": "途中改名", "goal": "途中改目標"},
        )
        assert details.status_code == 409
        assert details.json()["detail"] == "Meeting is already running"
    finally:
        release_model.set()
        wait_for_activity(client, meeting_id, "completed")


def test_delete_that_reserves_transition_first_leaves_no_orphan_after_start_attempt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    delete_entered = threading.Event()
    release_delete = threading.Event()
    original_delete = MeetingRepository.delete

    def blocked_delete(self, meeting_id):
        delete_entered.set()
        assert release_delete.wait(timeout=5)
        return original_delete(self, meeting_id)

    monkeypatch.setattr(MeetingRepository, "delete", blocked_delete)
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings",
        json={"title": "刪除競態", "goal": "不得留下孤兒"},
    ).json()["meeting_id"]

    with ThreadPoolExecutor(max_workers=2) as executor:
        delete_future = executor.submit(client.delete, f"/meetings/{meeting_id}")
        assert delete_entered.wait(timeout=2)
        start_future = executor.submit(
            client.post,
            f"/meetings/{meeting_id}/start",
            json={},
        )
        release_delete.set()
        assert delete_future.result(timeout=5).status_code == 204
        assert start_future.result(timeout=5).status_code == 404

    assert not (tmp_path / "data" / "meetings" / meeting_id).exists()


def test_generic_retry_reservation_blocks_details_until_model_execution_finishes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model_entered = threading.Event()
    release_model = threading.Event()
    should_fail = True
    original_complete = MockModelAdapter.complete

    def controlled_complete(self, request):
        nonlocal should_fail
        if should_fail:
            raise AdapterError("retry barrier setup")
        model_entered.set()
        assert release_model.wait(timeout=5)
        return original_complete(self, request)

    monkeypatch.setattr(MockModelAdapter, "complete", controlled_complete)
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings",
        json={"title": "重試競態", "goal": "重試使用同一 snapshot"},
    ).json()["meeting_id"]
    assert client.post(f"/meetings/{meeting_id}/start", json={}).status_code == 202
    failed = wait_for_activity(client, meeting_id, "failed")["events"][-1]
    should_fail = False

    try:
        retry = client.post(
            f"/meetings/{meeting_id}/steps/{failed['step_id']}/retry",
            json={},
        )
        assert retry.status_code == 202
        assert model_entered.wait(timeout=2)
        details = client.put(
            f"/meetings/{meeting_id}/details",
            json={"title": "途中改名", "goal": "途中改目標"},
        )
        assert details.status_code == 409
        assert details.json()["detail"] == "Meeting is already running"
    finally:
        release_model.set()
        wait_for_activity(client, meeting_id, "completed")


def test_running_step_persists_and_clears_recovery_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model_entered = threading.Event()
    release_model = threading.Event()
    original_complete = MockModelAdapter.complete

    def slow_complete(self, request):
        model_entered.set()
        release_model.wait(timeout=2)
        return original_complete(self, request)

    monkeypatch.setattr(MockModelAdapter, "complete", slow_complete)
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "恢復狀態", "goal": "恢復狀態"}).json()["meeting_id"]
    execution_state_path = tmp_path / "data" / "meetings" / meeting_id / "execution.json"

    try:
        response = client.post(
            f"/meetings/{meeting_id}/start",
            json={
                "models": {
                    "Blue": "mock-fast",
                    "Red": "mock-fast",
                    "Judge": "mock-fast",
                }
            },
        )

        assert response.status_code == 202
        assert model_entered.wait(timeout=1)
        state = json.loads(execution_state_path.read_text(encoding="utf-8"))
        assert state["step_id"] == "blue-propose"
        assert state["role"] == "Blue"
        assert state["status"] == "running"
        assert state["prompt_template_name"] == "blue_propose"
        assert state["prompt_template_hash"] == TEST_BLUE_PROPOSE_TEMPLATE_HASH
        assert state["output_schema_id"] == "role-output/v1"
        assert state["output_schema_hash"] == TEST_OUTPUT_SCHEMA_HASH
    finally:
        release_model.set()

    wait_for_activity(client, meeting_id, "completed")

    assert not execution_state_path.exists()


def test_app_startup_marks_leftover_execution_state_failed(tmp_path: Path) -> None:
    first_app = create_test_app(tmp_path)
    first_client = TestClient(first_app)
    meeting_id = first_client.post("/meetings", json={"title": "重啟恢復", "goal": "重啟恢復"}).json()["meeting_id"]
    execution_state_path = tmp_path / "data" / "meetings" / meeting_id / "execution.json"
    execution_state_path.write_text(
        json.dumps(
            {
                "meeting_id": meeting_id,
                "step_id": "blue-propose",
                "base_step_id": "blue-propose",
                "round": 1,
                "role": "Blue",
                "attempt": 1,
                "model_config_id": "mock-fast",
                "adapter": "mock",
                "status": "running",
                "started_at": "2020-07-14T01:02:03+00:00",
                "prompt_messages": [{"role": "user", "content": "diagnostic prompt"}],
                "prompt_template_name": "blue_propose",
                "prompt_template_hash": TEST_BLUE_PROPOSE_TEMPLATE_HASH,
                "output_schema_hash": TEST_OUTPUT_SCHEMA_HASH,
                "interaction_type": "directed-role-response",
                "directed_sequence": 1,
                "in_response_to_event_id": "chair-instruction-1",
                "materials_revision": 4,
                "materials_refs": [
                    {
                        "kind": "note",
                        "id": "case-note-1",
                        "version": 2,
                        "status": "active",
                        "visible_roles": ["Blue"],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    restarted_app = create_test_app(tmp_path)
    restarted_client = TestClient(restarted_app)

    meeting = restarted_client.get(f"/meetings/{meeting_id}").json()

    assert meeting["activity_status"] == "failed"
    assert meeting["events"][-1]["status"] == "failed"
    assert meeting["events"][-1]["step_id"] == "blue-propose"
    assert meeting["events"][-1]["prompt_template_name"] == "blue_propose"
    assert meeting["events"][-1]["prompt_template_hash"] == TEST_BLUE_PROPOSE_TEMPLATE_HASH
    assert meeting["events"][-1]["output_schema_hash"] == TEST_OUTPUT_SCHEMA_HASH
    assert meeting["events"][-1]["materials_revision"] == 4
    assert meeting["events"][-1]["materials_refs"][0]["version"] == 2
    assert meeting["events"][-1]["interaction_type"] == "directed-role-response"
    assert meeting["events"][-1]["in_response_to_event_id"] == "chair-instruction-1"
    assert meeting["events"][-1]["failure_kind"] == "interrupted"
    assert meeting["events"][-1]["adapter"] == "mock"
    assert meeting["events"][-1]["prompt_messages"] == [
        {"role": "user", "content": "diagnostic prompt"}
    ]
    assert meeting["events"][-1]["started_at"] == "2020-07-14T01:02:03+00:00"
    assert meeting["events"][-1]["completed_at"] >= meeting["events"][-1]["started_at"]
    assert meeting["events"][-1]["duration_ms"] >= 0
    assert meeting["events"][-1]["retry_scheduled"] is False
    assert "interrupted" in meeting["events"][-1]["error"].lower()
    assert not execution_state_path.exists()


def test_crash_recovery_matches_completion_within_execution_epoch(tmp_path: Path) -> None:
    first_client = TestClient(create_test_app(tmp_path))
    meeting_id = first_client.post(
        "/meetings", json={"title": "Epoch crash", "goal": "recover current epoch"}
    ).json()["meeting_id"]
    repository = MeetingRepository(tmp_path / "data")
    repository.append_event(
        meeting_id,
        {
            "event_id": f"{meeting_id}:blue-propose:attempt-1:completed",
            "meeting_id": meeting_id,
            "step_id": "blue-propose",
            "base_step_id": "blue-propose",
            "round": 1,
            "role": "Blue",
            "attempt": 1,
            "status": "completed",
        },
    )
    marker = DeliberationEpochs.restart_marker(
        meeting_id=meeting_id,
        events=repository.read_events(meeting_id),
        command=RestartCommand(scope="all_deliberation", reason="new epoch"),
    )
    repository.append_event(meeting_id, marker)
    execution_state_path = tmp_path / "data" / "meetings" / meeting_id / "execution.json"
    execution_state_path.write_text(
        json.dumps(
            {
                "meeting_id": meeting_id,
                "step_id": "blue-propose",
                "base_step_id": "blue-propose",
                "round": 1,
                "role": "Blue",
                "attempt": 1,
                "model_config_id": "mock-fast",
                "status": "running",
                "deliberation_epoch_id": marker["epoch_id"],
            }
        ),
        encoding="utf-8",
    )

    restarted_client = TestClient(create_test_app(tmp_path))
    meeting = restarted_client.get(f"/meetings/{meeting_id}").json()

    assert meeting["events"][-1]["failure_kind"] == "interrupted"
    assert meeting["events"][-1]["deliberation_epoch_id"] == marker["epoch_id"]
    assert meeting["events"][-1]["event_id"].startswith(f"{marker['epoch_id']}:")


def test_start_ignores_incomplete_legacy_request_model_assignments(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "缺少角色", "goal": "缺少角色"}).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/start",
        json={"models": {"Blue": "mock-fast", "Red": "mock-fast"}},
    )

    assert response.status_code == 202
    meeting = wait_for_activity(client, meeting_id, "completed")
    assert {event["model_config_id"] for event in meeting["events"]} == {"mock-fast"}


def test_list_meetings_filters_by_transcript_content(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    matching_id = client.post("/meetings", json={"title": "後端優先", "goal": "後端優先"}).json()["meeting_id"]
    other_id = client.post("/meetings", json={"title": "前端優先", "goal": "前端優先"}).json()["meeting_id"]
    client.post(
        f"/meetings/{matching_id}/messages",
        json={"content": "請鎖定在一週內完成 postgres 遷移的獨特關鍵字 xyzzy123。"},
    )

    response = client.get("/meetings", params={"q": "xyzzy123"})

    assert response.status_code == 200
    returned_ids = [meeting["meeting_id"] for meeting in response.json()]
    assert returned_ids == [matching_id]
    assert other_id not in returned_ids


def test_list_meetings_query_matches_tags(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    tagged_id = client.post("/meetings", json={"title": "會議 A", "goal": "會議 A"}).json()["meeting_id"]
    other_id = client.post("/meetings", json={"title": "會議 B", "goal": "會議 B"}).json()["meeting_id"]
    client.put(f"/meetings/{tagged_id}/tags", json={"tags": ["needs-review"]})

    response = client.get("/meetings", params={"q": "needs-review"})

    returned_ids = [meeting["meeting_id"] for meeting in response.json()]
    assert returned_ids == [tagged_id]
    assert other_id not in returned_ids


def test_list_meetings_without_query_returns_everything(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    client.post("/meetings", json={"title": "會議 A", "goal": "會議 A"})
    client.post("/meetings", json={"title": "會議 B", "goal": "會議 B"})

    response = client.get("/meetings")

    assert len(response.json()) == 2


def test_meeting_activity_status_projects_failed_latest_step(tmp_path: Path) -> None:
    app = create_test_app(
        tmp_path,
        models_yaml="""
models:
  - id: broken-model
    adapter: missing-adapter
""".strip(),
    )
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "失敗測試", "goal": "失敗測試"}).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/start",
        json={
            "models": {
                "Blue": "broken-model",
                "Red": "broken-model",
                "Judge": "broken-model",
            }
        },
    )

    assert response.status_code == 202
    assert response.json()["status"] == "running"
    meeting = wait_for_activity(client, meeting_id, "failed")
    assert meeting["activity_status"] == "failed"
    assert meeting["last_step_id"] == "blue-propose"


def test_meeting_cancel_endpoint_records_cancellation(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "取消測試", "goal": "取消測試"}).json()["meeting_id"]

    response = client.post(f"/meetings/{meeting_id}/cancel")

    assert response.status_code == 200
    events = client.get(f"/meetings/{meeting_id}").json()["events"]
    assert events[-1]["status"] == "cancelled"


def test_cancelling_background_run_stays_cancelled_when_model_returns(
    tmp_path: Path,
    monkeypatch,
) -> None:
    model_entered = threading.Event()
    release_model = threading.Event()

    def slow_complete(self, request):
        model_entered.set()
        release_model.wait(timeout=2)
        return ModelResponse(
            raw_output='{"summary":"OK","arguments":[],"risks":[],"recommendation":"Go"}'
        )

    monkeypatch.setattr(MockModelAdapter, "complete", slow_complete)
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "背景取消", "goal": "背景取消"}).json()["meeting_id"]
    client.post(
        f"/meetings/{meeting_id}/start",
        json={
            "models": {
                "Blue": "mock-fast",
                "Red": "mock-fast",
                "Judge": "mock-fast",
            }
        },
    )
    assert model_entered.wait(timeout=1)

    try:
        response = client.post(f"/meetings/{meeting_id}/cancel")
        meeting = client.get(f"/meetings/{meeting_id}").json()

        assert response.status_code == 200
        assert meeting["activity_status"] == "cancelled"
    finally:
        release_model.set()

    time.sleep(0.1)
    meeting = client.get(f"/meetings/{meeting_id}").json()
    events = meeting["events"]
    assert meeting["activity_status"] == "cancelled"
    assert [event["status"] for event in events] == ["cancelled", "failed"]
    assert events[1]["failure_kind"] == "interrupted"
    assert events[1]["result_discarded"] is True
    assert events[1]["retry_scheduled"] is False
    assert events[1]["parsed_output"]["summary"] == "OK"
    transcript = client.get(f"/meetings/{meeting_id}/transcript.md").text
    assert events[1]["step_id"] not in transcript
    assert "OK" not in transcript


def test_cancel_terminates_running_subscription_cli_process(tmp_path: Path) -> None:
    started_marker = tmp_path / "started"
    completed_marker = tmp_path / "completed"
    slow_cli = tmp_path / "slow_cli.py"
    slow_cli.write_text(
        "import pathlib, time\n"
        f"pathlib.Path({str(started_marker)!r}).write_text('started')\n"
        "time.sleep(10)\n"
        f"pathlib.Path({str(completed_marker)!r}).write_text('completed')\n",
        encoding="utf-8",
    )
    models_yaml = (
        "models:\n"
        "  - id: slow-subscription\n"
        "    adapter: subscription-cli\n"
        f"    command: [{sys.executable!r}, {str(slow_cli)!r}, \"{{prompt}}\"]\n"
        "    timeout_seconds: 30\n"
    )
    app = create_test_app(tmp_path, models_yaml=models_yaml)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "CLI 取消測試", "goal": "CLI 取消測試"}).json()["meeting_id"]

    client.post(
        f"/meetings/{meeting_id}/start",
        json={
            "models": {
                "Blue": "slow-subscription",
                "Red": "slow-subscription",
                "Judge": "slow-subscription",
            }
        },
    )
    deadline = time.monotonic() + 2
    while not started_marker.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert started_marker.exists(), "subscription CLI never started"

    response = client.post(f"/meetings/{meeting_id}/cancel")
    assert response.status_code == 200

    time.sleep(0.5)
    assert not completed_marker.exists(), "subscription CLI kept running after cancel"


def test_meeting_close_endpoint_records_closure_and_projects_transcript(
    tmp_path: Path,
) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "結案測試", "goal": "結案測試"}).json()["meeting_id"]

    response = client.post(f"/meetings/{meeting_id}/close")

    assert response.status_code == 200
    events = client.get(f"/meetings/{meeting_id}").json()["events"]
    assert events[-1]["status"] == "closed"
    assert client.get(f"/meetings/{meeting_id}").json()["status"] == "closed"
    assert client.get("/meetings").json()[0]["status"] == "closed"
    transcript = client.get(f"/meetings/{meeting_id}/transcript.md").text
    assert "## 系統 - 會議結案" in transcript
    assert "**狀態：** 已結案" in transcript


def test_reopen_endpoint_restores_terminal_meeting_to_open_state(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "誤按結案", "goal": "誤按結案"}).json()["meeting_id"]
    client.post(f"/meetings/{meeting_id}/close")

    response = client.post(f"/meetings/{meeting_id}/reopen")

    assert response.status_code == 200
    assert response.json()["status"] == "open"
    reopened = client.get(f"/meetings/{meeting_id}").json()
    assert reopened["status"] == "open"
    assert reopened["activity_status"] == "waiting"
    assert [event["status"] for event in reopened["events"]] == ["closed", "reopened"]

    message_response = client.post(
        f"/meetings/{meeting_id}/messages",
        json={"content": "結案是誤按，補充脈絡。"},
    )

    assert message_response.status_code == 200
    assert client.get(f"/meetings/{meeting_id}").json()["status"] == "open"


@pytest.mark.parametrize("terminal_action", ["close", "cancel"])
def test_reopen_waits_for_the_terminal_job_to_return_before_restoring_meeting(
    tmp_path: Path,
    monkeypatch,
    terminal_action: str,
) -> None:
    model_entered = threading.Event()
    release_model = threading.Event()
    original_complete = MockModelAdapter.complete

    def blocked_complete(self, request):
        model_entered.set()
        assert release_model.wait(timeout=5)
        return original_complete(self, request)

    monkeypatch.setattr(MockModelAdapter, "complete", blocked_complete)
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings", json={"title": "終止中的會議", "goal": "避免舊工作污染重開狀態"}
    ).json()["meeting_id"]

    try:
        assert client.post(f"/meetings/{meeting_id}/start", json={}).status_code == 202
        assert model_entered.wait(timeout=2)
        assert client.post(f"/meetings/{meeting_id}/{terminal_action}").status_code == 200

        blocked = client.post(f"/meetings/{meeting_id}/reopen")

        assert blocked.status_code == 409
        assert blocked.json()["detail"] == "Meeting is still finishing its background job"
    finally:
        release_model.set()

    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        reopened = client.post(f"/meetings/{meeting_id}/reopen")
        if reopened.status_code == 200:
            break
        assert reopened.status_code == 409
        time.sleep(0.01)
    else:
        raise AssertionError("Background job did not release")

    events = client.get(f"/meetings/{meeting_id}").json()["events"]
    terminal_status = {"close": "closed", "cancel": "cancelled"}[terminal_action]
    terminal_index = next(
        index for index, event in enumerate(events) if event["status"] == terminal_status
    )
    assert events[-1]["status"] == "reopened"
    assert not any(
        event.get("status") == "completed" and event.get("role") not in {"Human", "System"}
        for event in events[terminal_index + 1 :]
    )


def test_background_job_manager_observes_unexpected_future_exceptions(caplog) -> None:
    manager = MeetingJobManager()

    def fail() -> None:
        raise RuntimeError("sensitive provider output")

    with caplog.at_level("ERROR", logger="ai_council.api"):
        assert manager.start("meeting-failure", fail)
        deadline = time.monotonic() + 2
        while (
            "Background meeting job failed unexpectedly" not in caplog.text
            and time.monotonic() < deadline
        ):
            time.sleep(0.01)

    assert "Background meeting job failed unexpectedly" in caplog.text
    assert "sensitive provider output" not in caplog.text


def test_update_meeting_tags_replaces_tag_list(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "標籤測試", "goal": "標籤測試"}).json()["meeting_id"]

    response = client.put(f"/meetings/{meeting_id}/tags", json={"tags": ["urgent", "backend"]})

    assert response.status_code == 200
    assert response.json()["tags"] == ["urgent", "backend"]
    assert client.get(f"/meetings/{meeting_id}").json()["tags"] == ["urgent", "backend"]
    assert [meeting["tags"] for meeting in client.get("/meetings").json()] == [
        ["urgent", "backend"]
    ]

    replaced = client.put(f"/meetings/{meeting_id}/tags", json={"tags": ["backend"]})
    assert replaced.json()["tags"] == ["backend"]


def test_update_meeting_tags_returns_404_for_unknown_meeting(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.put("/meetings/does-not-exist/tags", json={"tags": ["x"]})

    assert response.status_code == 404


def test_update_meeting_tags_allowed_on_terminal_meeting(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "已結案", "goal": "已結案"}).json()["meeting_id"]
    client.post(f"/meetings/{meeting_id}/close")

    response = client.put(f"/meetings/{meeting_id}/tags", json={"tags": ["archived"]})

    assert response.status_code == 200
    assert response.json()["tags"] == ["archived"]


def test_update_meeting_pinned_toggles_and_persists(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "釘選測試", "goal": "釘選測試"}).json()["meeting_id"]
    assert client.get(f"/meetings/{meeting_id}").json()["pinned"] is False

    response = client.put(f"/meetings/{meeting_id}/pinned", json={"pinned": True})

    assert response.status_code == 200
    assert response.json()["pinned"] is True
    assert client.get(f"/meetings/{meeting_id}").json()["pinned"] is True
    assert [meeting["pinned"] for meeting in client.get("/meetings").json()] == [True]

    unpinned = client.put(f"/meetings/{meeting_id}/pinned", json={"pinned": False})
    assert unpinned.json()["pinned"] is False


def test_update_meeting_pinned_returns_404_for_unknown_meeting(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.put("/meetings/does-not-exist/pinned", json={"pinned": True})

    assert response.status_code == 404


def test_update_meeting_pinned_allowed_on_terminal_meeting(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "已結案", "goal": "已結案"}).json()["meeting_id"]
    client.post(f"/meetings/{meeting_id}/close")

    response = client.put(f"/meetings/{meeting_id}/pinned", json={"pinned": True})

    assert response.status_code == 200
    assert response.json()["pinned"] is True


def test_meeting_delete_removes_meeting_and_derived_transcript(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "刪除測試", "goal": "刪除測試"}).json()["meeting_id"]
    client.post(
        f"/meetings/{meeting_id}/start",
        json={
            "models": {
                "Blue": "mock-fast",
                "Red": "mock-fast",
                "Judge": "mock-fast",
            }
        },
    )
    wait_for_activity(client, meeting_id, "completed")

    response = client.delete(f"/meetings/{meeting_id}")

    assert response.status_code == 204
    assert all(item["meeting_id"] != meeting_id for item in client.get("/meetings").json())
    assert client.get(f"/meetings/{meeting_id}").status_code == 404
    assert client.get(f"/meetings/{meeting_id}/transcript.md").status_code == 404


def test_terminal_meeting_rejects_event_creating_api_calls(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "已結案", "goal": "已結案"}).json()["meeting_id"]
    client.post(f"/meetings/{meeting_id}/close")

    start_response = client.post(
        f"/meetings/{meeting_id}/start",
        json={
            "models": {
                "Blue": "mock-fast",
                "Red": "mock-fast",
                "Judge": "mock-fast",
            }
        },
    )
    message_response = client.post(
        f"/meetings/{meeting_id}/messages",
        json={"content": "結案後不能再補充。"},
    )
    role_response = client.post(
        f"/meetings/{meeting_id}/roles/Blue/respond",
        json={"instruction": "請回答"},
    )
    sequence_response = client.post(
        f"/meetings/{meeting_id}/sequences",
        json={
            "roles": ["Red", "Blue", "Judge"],
            "models": {
                "Blue": "mock-fast",
                "Red": "mock-fast",
                "Judge": "mock-fast",
            },
        },
    )

    assert start_response.status_code == 409
    assert start_response.json()["detail"] == "Meeting is terminal: closed"
    assert message_response.status_code == 409
    assert message_response.json()["detail"] == "Meeting is terminal: closed"
    assert role_response.status_code == 409
    assert role_response.json()["detail"] == "Meeting is terminal: closed"
    assert sequence_response.status_code == 409
    assert sequence_response.json()["detail"] == "Meeting is terminal: closed"
    events = client.get(f"/meetings/{meeting_id}").json()["events"]
    assert [event["status"] for event in events] == ["closed"]


def test_human_chair_message_is_persisted_and_projected(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "互動會議", "goal": "互動會議"}).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/messages",
        json={"content": "我先補充限制：只能花一週做 MVP。"},
    )

    assert response.status_code == 200
    event = response.json()
    assert event["role"] == "Human"
    assert event["step_id"] == "human-message"
    assert event["status"] == "completed"
    assert event["content"] == "我先補充限制：只能花一週做 MVP。"
    events = client.get(f"/meetings/{meeting_id}").json()["events"]
    assert events[-1]["event_id"] == event["event_id"]
    transcript = client.get(f"/meetings/{meeting_id}/transcript.md").text
    assert "## 主席 - 主席發言" in transcript
    assert "我先補充限制：只能花一週做 MVP。" in transcript


def test_chair_can_correct_a_human_message(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "互動會議", "goal": "互動會議"}).json()["meeting_id"]
    original = client.post(
        f"/meetings/{meeting_id}/messages",
        json={"content": "只能花一週做 MVP。"},
    ).json()

    response = client.post(
        f"/meetings/{meeting_id}/messages/{original['event_id']}/correct",
        json={"content": "只能花兩週做 MVP，之前打錯字了。"},
    )

    assert response.status_code == 200
    correction = response.json()
    assert correction["role"] == "Human"
    assert correction["step_id"] == "human-message"
    assert correction["status"] == "completed"
    assert correction["content"] == "只能花兩週做 MVP，之前打錯字了。"
    assert correction["corrects_event_id"] == original["event_id"]

    events = client.get(f"/meetings/{meeting_id}").json()["events"]
    assert [event["content"] for event in events if event["role"] == "Human"] == [
        "只能花一週做 MVP。",
        "只能花兩週做 MVP，之前打錯字了。",
    ]
    transcript = client.get(f"/meetings/{meeting_id}/transcript.md").text
    assert "只能花一週做 MVP。" in transcript
    assert "只能花兩週做 MVP，之前打錯字了。" in transcript
    assert "訂正" in transcript


def test_correct_human_message_returns_404_for_unknown_event(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "互動會議", "goal": "互動會議"}).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/messages/does-not-exist/correct",
        json={"content": "修正內容"},
    )

    assert response.status_code == 404


def test_correct_human_message_rejects_non_human_message_event(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "互動會議", "goal": "互動會議"}).json()["meeting_id"]
    client.post(
        f"/meetings/{meeting_id}/start",
        json={
            "models": {
                "Blue": "mock-fast",
                "Red": "mock-fast",
                "Judge": "mock-fast",
            }
        },
    )
    meeting = wait_for_activity(client, meeting_id, "completed")
    blue_step = next(event for event in meeting["events"] if event["step_id"] == "blue-propose")

    response = client.post(
        f"/meetings/{meeting_id}/messages/{blue_step['event_id']}/correct",
        json={"content": "不能修正 AI 的回應"},
    )

    assert response.status_code == 400


def test_correct_human_message_rejects_on_terminal_meeting(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "已結案", "goal": "已結案"}).json()["meeting_id"]
    original = client.post(
        f"/meetings/{meeting_id}/messages",
        json={"content": "結案前的補充。"},
    ).json()
    client.post(f"/meetings/{meeting_id}/close")

    response = client.post(
        f"/meetings/{meeting_id}/messages/{original['event_id']}/correct",
        json={"content": "結案後想修正。"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Meeting is terminal: closed"


def test_chair_can_request_single_role_response(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "互動會議", "goal": "互動會議"}).json()["meeting_id"]
    response = client.post(
        f"/meetings/{meeting_id}/roles/Blue/respond",
        json={"instruction": "請先回答最小可行方案。"},
    )

    assert response.status_code == 202
    events = wait_for_event_count(client, meeting_id, 2)
    assert events[-2]["step_id"] == "human-directed-message"
    assert events[-2]["interaction_type"] == "directed-role-instruction"
    assert events[-2]["target_role_id"] == "Blue"
    assert events[-2]["content"] == "請先回答最小可行方案。"
    assert events[-1]["step_id"] == "directed-1-blue-response"
    assert events[-1]["role"] == "Blue"
    assert events[-1]["interaction_type"] == "directed-role-response"
    assert events[-1]["in_response_to_event_id"] == events[-2]["event_id"]
    transcript = client.get(f"/meetings/{meeting_id}/transcript.md").text
    assert "## 藍軍 - 藍軍回應主席追問" in transcript


def test_directed_role_response_rejects_blank_instruction(tmp_path: Path) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings",
        json={"title": "互動會議", "goal": "找出可行方案"},
    ).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/roles/Blue/respond",
        json={"instruction": "   "},
    )

    assert response.status_code == 422
    missing = client.post(
        f"/meetings/{meeting_id}/roles/Blue/respond",
        json={"models": {"Blue": "mock-fast"}},
    )
    assert missing.status_code == 422
    assert client.get(f"/meetings/{meeting_id}").json()["events"] == []


def test_directed_role_response_rejects_unknown_role_before_job_reservation(
    tmp_path: Path,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings",
        json={"title": "互動會議", "goal": "找出可行方案"},
    ).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/roles/Chair/respond",
        json={"instruction": "請回應。"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown role: Chair"
    assert client.get(f"/meetings/{meeting_id}").json()["events"] == []


def test_async_directed_and_retry_routes_publish_202_in_openapi(tmp_path: Path) -> None:
    schema = TestClient(create_test_app(tmp_path)).get("/openapi.json").json()

    directed = schema["paths"]["/meetings/{meeting_id}/roles/{role}/respond"]["post"]
    retry = schema["paths"]["/meetings/{meeting_id}/steps/{step_id}/retry"]["post"]

    assert "202" in directed["responses"]
    assert "200" not in directed["responses"]
    assert "202" in retry["responses"]
    assert "200" not in retry["responses"]


@pytest.mark.parametrize(
    "instruction_event",
    [
        None,
        {
            "event_id": "legacy-instruction",
            "step_id": "human-directed-message",
            "role": "Human",
            "attempt": 1,
            "status": "completed",
            "interaction_type": "directed-role-instruction",
            "target_role_id": "Red",
            "content": "回答錯誤角色",
        },
        {
            "event_id": "legacy-instruction",
            "step_id": "human-directed-message",
            "role": "Human",
            "attempt": 1,
            "status": "completed",
            "interaction_type": "directed-role-instruction",
            "target_role_id": "Blue",
            "content": "   ",
        },
    ],
)
def test_legacy_directed_retry_rejects_incomplete_instruction_before_job_start(
    tmp_path: Path,
    instruction_event: dict[str, object] | None,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings", json={"title": "舊定向失敗", "goal": "同步拒絕不可重試紀錄"}
    ).json()["meeting_id"]
    repository = MeetingRepository(tmp_path / "data")
    if instruction_event is not None:
        repository.append_event(meeting_id, {**instruction_event, "meeting_id": meeting_id})
    repository.append_event(
        meeting_id,
        {
            "event_id": "legacy-failed-response",
            "meeting_id": meeting_id,
            "step_id": "directed-1-blue-response",
            "base_step_id": "blue-response",
            "round": 1,
            "role": "Blue",
            "attempt": 1,
            "status": "failed",
            "interaction_type": "directed-role-response",
            "in_response_to_event_id": "legacy-instruction",
        },
    )
    before = client.get(f"/meetings/{meeting_id}").json()["events"]

    response = client.post(
        f"/meetings/{meeting_id}/steps/directed-1-blue-response/retry",
        json={},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Directed response instruction is unavailable for retry"
    assert client.get(f"/meetings/{meeting_id}").json()["events"] == before


def test_retry_failed_directed_response_keeps_the_original_instruction_and_linkage(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_test_app(
            tmp_path,
            models_yaml="""
models:
  - id: mock-fast
    adapter: mock
  - id: mock-broken
    adapter: openai-compatible-http
""".strip(),
        )
    )
    meeting_id = client.post(
        "/meetings",
        json={
            "title": "定向追問重試",
            "goal": "找出最小可行方案",
            "participants": [
                {"role_id": "Blue", "model_config_id": "mock-broken"},
                {"role_id": "Red", "model_config_id": "mock-fast"},
                {"role_id": "Judge", "model_config_id": "mock-fast"},
            ],
        },
    ).json()["meeting_id"]

    started = client.post(
        f"/meetings/{meeting_id}/roles/Blue/respond",
        json={"instruction": "請針對一週內交付補充說明"},
    )
    assert started.status_code == 202
    failed_events = wait_for_activity(client, meeting_id, "failed")["events"]
    instruction, failed = failed_events
    assert failed["status"] == "failed"

    client.put(
        f"/meetings/{meeting_id}/participant-models",
        json={
            "models": {
                "Blue": "mock-fast",
                "Red": "mock-fast",
                "Judge": "mock-fast",
            }
        },
    )
    retried = client.post(
        f"/meetings/{meeting_id}/steps/{failed['step_id']}/retry",
        json={},
    )

    assert retried.status_code == 202
    events = wait_for_event_count(client, meeting_id, 3)
    assert len([event for event in events if event["role"] == "Human"]) == 1
    completed = events[-1]
    assert completed["status"] == "completed"
    assert completed["attempt"] == 2
    assert completed["in_response_to_event_id"] == instruction["event_id"]
    assert "請針對一週內交付補充說明" in completed["prompt_messages"][0]["content"]
    assert "藍軍" in completed["prompt_messages"][0]["content"]


def test_transcript_uses_event_local_labels_for_directed_and_sequence_interactions(
    tmp_path: Path,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings",
        json={"title": "互動標籤", "goal": "確認每筆互動語意"},
    ).json()["meeting_id"]
    repository = MeetingRepository(tmp_path / "data")
    events = [
        {
            "event_id": "instruction-defense",
            "meeting_id": meeting_id,
            "step_id": "human-directed-message",
            "role": "Human",
            "attempt": 1,
            "status": "completed",
            "interaction_type": "directed-role-instruction",
            "target_role_id": "Blue",
            "content": "請藍軍回答",
        },
        {
            "event_id": "directed-blue",
            "meeting_id": meeting_id,
            "step_id": "directed-1-blue-response",
            "base_step_id": "blue-response",
            "role": "Blue",
            "attempt": 1,
            "status": "completed",
            "interaction_type": "directed-role-response",
            "parsed_output": {
                "summary": "藍軍定向回答",
                "arguments": [],
                "risks": [],
                "recommendation": "繼續",
            },
        },
        {
            "event_id": "sequence-blue",
            "meeting_id": meeting_id,
            "step_id": "sequence-1-blue-response",
            "base_step_id": "blue-response",
            "role": "Blue",
            "attempt": 1,
            "status": "completed",
            "interaction_type": "role-sequence-response",
            "parsed_output": {
                "summary": "藍軍依序回答",
                "arguments": [],
                "risks": [],
                "recommendation": "繼續",
            },
        },
        {
            "event_id": "instruction-judge",
            "meeting_id": meeting_id,
            "step_id": "human-directed-message",
            "role": "Human",
            "attempt": 1,
            "status": "completed",
            "interaction_type": "directed-role-instruction",
            "target_role_id": "Judge",
            "content": "請裁判回答",
        },
    ]
    for event in events:
        repository.append_event(meeting_id, event)

    transcript = client.get(f"/meetings/{meeting_id}/transcript.md").text

    assert "## 主席 - 主席追問藍軍" in transcript
    assert "## 藍軍 - 藍軍回應主席追問" in transcript
    assert "## 藍軍 - 藍軍依序回應" in transcript
    assert "## 主席 - 主席追問裁判" in transcript


def test_chair_can_request_role_sequence_response(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "互動會議", "goal": "互動會議"}).json()["meeting_id"]
    client.post(
        f"/meetings/{meeting_id}/messages",
        json={"content": "請 Red 挑戰、Blue 修正、Judge 裁決。"},
    )

    response = client.post(
        f"/meetings/{meeting_id}/sequences",
        json={
            "roles": ["Red", "Blue", "Judge"],
            "models": {
                "Blue": "mock-fast",
                "Red": "mock-fast",
                "Judge": "mock-fast",
            },
        },
    )

    assert response.status_code == 202
    events = wait_for_event_count(client, meeting_id, 4)
    ai_events = [event for event in events if event["role"] != "Human"]
    assert [event["step_id"] for event in ai_events] == [
        "sequence-1-red-response",
        "sequence-1-blue-response",
        "sequence-1-judge-response",
    ]
    assert {event["interaction_type"] for event in ai_events} == {"role-sequence-response"}
    assert [event["sequence_index"] for event in ai_events] == [1, 2, 3]
    transcript = client.get(f"/meetings/{meeting_id}/transcript.md").text
    assert "## 紅軍 - 紅軍依序回應" in transcript
    assert "## 裁判 - 裁判依序回應" in transcript


def test_directed_and_sequence_responses_use_persisted_assignments(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_test_app(
            tmp_path,
            models_yaml="""
models:
  - id: persisted-model
    adapter: mock
  - id: request-model
    adapter: mock
""".strip(),
        )
    )

    def create_meeting(topic: str) -> str:
        return client.post(
            "/meetings",
            json={
                "title": topic,
                "goal": topic,
                "participants": [
                    {"role_id": role, "model_config_id": "persisted-model"}
                    for role in ["Blue", "Red", "Judge"]
                ],
            },
        ).json()["meeting_id"]

    directed_id = create_meeting("Directed assignment")
    directed = client.post(
        f"/meetings/{directed_id}/roles/Blue/respond",
        json={"instruction": "請回答目前方案"},
    )
    sequence_id = create_meeting("Sequence assignment")
    sequence = client.post(
        f"/meetings/{sequence_id}/sequences",
        json={
            "roles": ["Red", "Blue", "Judge"],
            "models": {
                "Blue": "request-model",
                "Red": "request-model",
                "Judge": "request-model",
            },
        },
    )

    assert directed.status_code == 202
    assert sequence.status_code == 202
    directed_events = wait_for_event_count(client, directed_id, 2)
    sequence_events = wait_for_event_count(client, sequence_id, 3)
    assert directed_events[-1]["model_config_id"] == "persisted-model"
    assert {
        event["model_config_id"]
        for event in sequence_events
    } == {"persisted-model"}


def test_chair_role_sequence_rejects_unknown_role(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "互動會議", "goal": "互動會議"}).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/sequences",
        json={
            "roles": ["Blue", "Chair"],
            "models": {"Blue": "mock-fast"},
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown role: Chair"


def test_chair_role_sequence_rejects_duplicate_roles(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "互動會議", "goal": "互動會議"}).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/sequences",
        json={
            "roles": ["Blue", "Blue"],
            "models": {"Blue": "mock-fast"},
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Role sequence cannot contain duplicate roles"


def test_chair_role_response_ignores_incomplete_legacy_request_models(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "互動會議", "goal": "互動會議"}).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/roles/Blue/respond",
        json={"instruction": "請回答目前方案"},
    )

    assert response.status_code == 202
    event = wait_for_event_count(client, meeting_id, 2)[-1]
    assert event["role"] == "Blue"
    assert event["model_config_id"] == "mock-fast"


def test_retry_step_returns_bad_request_when_step_is_not_failed(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"title": "retry 邊界", "goal": "retry 邊界"}).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/steps/blue-propose/retry",
        json={"models": {"Blue": "mock-fast", "Red": "mock-fast", "Judge": "mock-fast"}},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Step is not failed: blue-propose"


def test_modes_endpoint_returns_catalog(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.get("/modes")

    assert response.status_code == 200
    modes = response.json()
    assert [mode["id"] for mode in modes] == [
        "red-blue",
        "courtroom",
        "debate",
        "brainstorm",
        "six-hats",
        "persona-testing",
    ]
    red_blue = next(mode for mode in modes if mode["id"] == "red-blue")
    assert red_blue["available"] is True
    assert {
        role["id"]: role["output_schema"] for role in red_blue["roles"]
    } == {
        "Blue": "role-output/v1",
        "Red": "role-output/v1",
        "Judge": "structured-verdict/v1",
    }
    assert red_blue["steps"] == [
        {"role": "Blue", "template": "blue_propose", "label": "藍軍提案"},
        {"role": "Red", "template": "red_critique", "label": "紅軍質詢"},
        {"role": "Blue", "template": "blue_revise", "label": "藍軍修訂"},
        {"role": "Judge", "template": "judge_decide", "label": "裁判裁決"},
    ]
    brainstorm = next(mode for mode in modes if mode["id"] == "brainstorm")
    assert brainstorm["available"] is True
    assert brainstorm["fanout"]["min_instances"] == 2
    assert brainstorm["synthesis"]["anonymize_inputs"] is True


def test_create_meeting_defaults_to_red_blue(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.post("/meetings", json={"title": "舊版建立會議", "goal": "舊版建立會議"})

    assert response.status_code == 200
    created = response.json()
    assert created["mode_id"] == "red-blue"
    assert [
        (item["role_id"], item["model_config_id"], item["model_assignment_source"])
        for item in created["participants"]
    ] == [
        ("Blue", "mock-fast", "metadata"),
        ("Red", "mock-fast", "metadata"),
        ("Judge", "mock-fast", "metadata"),
    ]
    metadata = json.loads(
        (
            tmp_path
            / "data"
            / "meetings"
            / created["meeting_id"]
            / "metadata.json"
        ).read_text(encoding="utf-8")
    )
    assert metadata["participants"] == [
        {"role_id": "Blue", "model_config_id": "mock-fast"},
        {"role_id": "Red", "model_config_id": "mock-fast"},
        {"role_id": "Judge", "model_config_id": "mock-fast"},
    ]


def test_create_parallel_without_participants_materializes_default_model_roster(
    tmp_path: Path,
) -> None:
    client = TestClient(create_test_app(tmp_path))

    created = client.post(
        "/meetings",
        json={"title": "Default brainstorm", "goal": "Default brainstorm", "mode_id": "brainstorm"},
    ).json()

    metadata = json.loads(
        (
            tmp_path
            / "data"
            / "meetings"
            / created["meeting_id"]
            / "metadata.json"
        ).read_text(encoding="utf-8")
    )
    assert metadata["participants"] == [
        {"role_id": "Member-1", "model_config_id": "mock-fast"},
        {"role_id": "Member-2", "model_config_id": "mock-fast"},
        {"role_id": "Moderator", "model_config_id": "mock-fast"},
    ]


def test_create_fixed_parallel_materializes_and_accepts_canonical_six_hats_roster(
    tmp_path: Path,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    expected_roles = [
        "HatWhite",
        "HatRed",
        "HatBlack",
        "HatYellow",
        "HatGreen",
        "HatBlue",
    ]

    defaulted = client.post(
        "/meetings",
        json={"title": "Default six hats", "goal": "Default six hats", "mode_id": "six-hats"},
    )
    explicit = client.post(
        "/meetings",
        json={
            "title": "Explicit six hats",
            "goal": "Explicit six hats",
            "mode_id": "six-hats",
            "participants": [
                {"role_id": role_id, "model_config_id": "mock-fast"}
                for role_id in expected_roles
            ],
        },
    )

    assert defaulted.status_code == 200
    assert explicit.status_code == 200
    assert [item["role_id"] for item in defaulted.json()["participants"]] == expected_roles
    assert {item["model_config_id"] for item in defaulted.json()["participants"]} == {
        "mock-fast"
    }
    metadata_path = (
        tmp_path
        / "data"
        / "meetings"
        / defaulted.json()["meeting_id"]
        / "metadata.json"
    )
    assert [
        (item["role_id"], item["model_config_id"])
        for item in json.loads(metadata_path.read_text(encoding="utf-8"))["participants"]
    ] == [(role_id, "mock-fast") for role_id in expected_roles]


def test_create_parallel_validates_fixed_roster_and_preserves_dynamic_persona_shape(
    tmp_path: Path,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    fixed_roles = ["HatWhite", "HatRed", "HatBlack", "HatYellow", "HatGreen", "HatBlue"]

    missing_role = client.post(
        "/meetings",
        json={
            "title": "Missing green hat",
            "goal": "Missing green hat",
            "mode_id": "six-hats",
            "participants": [
                {"role_id": role_id, "model_config_id": "mock-fast"}
                for role_id in fixed_roles
                if role_id != "HatGreen"
            ],
        },
    )
    unknown_role = client.post(
        "/meetings",
        json={
            "title": "Unknown hat",
            "goal": "Unknown hat",
            "mode_id": "six-hats",
            "participants": [
                {"role_id": role_id, "model_config_id": "mock-fast"}
                for role_id in [*fixed_roles[:-1], "HatPurple", "HatBlue"]
            ],
        },
    )
    missing_model = client.post(
        "/meetings",
        json={
            "title": "Missing hat model",
            "goal": "Missing hat model",
            "mode_id": "six-hats",
            "participants": [
                {
                    "role_id": role_id,
                    "model_config_id": None if role_id == "HatWhite" else "mock-fast",
                }
                for role_id in fixed_roles
            ],
        },
    )
    unknown_model = client.post(
        "/meetings",
        json={
            "title": "Unknown hat model",
            "goal": "Unknown hat model",
            "mode_id": "six-hats",
            "participants": [
                {
                    "role_id": role_id,
                    "model_config_id": "missing-model" if role_id == "HatWhite" else "mock-fast",
                }
                for role_id in fixed_roles
            ],
        },
    )
    persona = client.post(
        "/meetings",
        json={"title": "Default personas", "goal": "Default personas", "mode_id": "persona-testing"},
    )

    assert missing_role.status_code == 400
    assert unknown_role.status_code == 400
    assert missing_model.status_code == 400
    assert unknown_model.status_code == 404
    assert persona.status_code == 200
    assert [item["role_id"] for item in persona.json()["participants"]] == [
        "Persona-1",
        "Persona-2",
        "ProductAdvisor",
    ]


def test_create_meeting_with_courtroom_mode(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/meetings",
        json={"title": "法庭審理案例", "goal": "法庭審理案例", "mode_id": "courtroom"},
    )

    assert response.status_code == 200
    participants = response.json()["participants"]
    assert [p["role_id"] for p in participants] == ["Prosecutor", "Defense", "Judge"]


def test_create_meeting_stores_and_returns_case_files(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/meetings",
        json={
            "title": "事故覆盤",
            "goal": "事故覆盤",
            "mode_id": "courtroom",
            "case_files": [
                {
                    "title": "事故時間線",
                    "content": "10:00 deploy\n10:05 error rate spike",
                    "visible_roles": ["Prosecutor", "Judge"],
                },
                {
                    "title": "辯方說明",
                    "content": "The rollback was blocked by a pending migration.",
                    "visible_roles": ["Defense", "Judge"],
                },
            ],
        },
    )

    assert response.status_code == 200
    created = response.json()
    assert created["case_files"] == [
        {
            "id": "case-file-1",
            "evidence_index": 1,
            "citation_anchor": "[證物一]",
            "title": "事故時間線",
            "visible_roles": ["Prosecutor", "Judge"],
            "size": len("10:00 deploy\n10:05 error rate spike"),
        },
        {
            "id": "case-file-2",
            "evidence_index": 2,
            "citation_anchor": "[證物二]",
            "title": "辯方說明",
            "visible_roles": ["Defense", "Judge"],
            "size": len("The rollback was blocked by a pending migration."),
        },
    ]
    meeting_id = created["meeting_id"]
    stored_path = tmp_path / "data" / "meetings" / meeting_id / "case_files.json"
    assert stored_path.exists()
    stored = json.loads(stored_path.read_text(encoding="utf-8"))
    assert [(item["evidence_index"], item["citation_anchor"]) for item in stored] == [
        (1, "[證物一]"),
        (2, "[證物二]"),
    ]
    metadata = json.loads(
        (stored_path.parent / "metadata.json").read_text(encoding="utf-8")
    )
    assert "case_files" not in metadata
    assert "case_file_count" not in metadata
    assert "case_materials_revision" not in metadata

    fetched = client.get(f"/meetings/{meeting_id}").json()
    assert [(item["evidence_index"], item["citation_anchor"]) for item in fetched["case_files"]] == [
        (1, "[證物一]"),
        (2, "[證物二]"),
    ]
    assert fetched["case_files"][0]["content"] == "10:00 deploy\n10:05 error rate spike"
    assert fetched["case_files"][1]["content"] == "The rollback was blocked by a pending migration."


def test_get_meeting_derives_evidence_anchors_for_legacy_case_files_without_rewriting(
    tmp_path: Path,
) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={
            "title": "舊案卷",
            "goal": "舊案卷",
            "mode_id": "courtroom",
            "case_files": [
                {
                    "title": "事故時間線",
                    "content": "10:05 error rate spike",
                    "visible_roles": ["Judge"],
                },
                {
                    "title": "回滾紀錄",
                    "content": "10:07 rollback started",
                    "visible_roles": ["Judge"],
                },
            ],
        },
    ).json()["meeting_id"]
    meeting_dir = tmp_path / "data" / "meetings" / meeting_id
    case_file_path = meeting_dir / "case_files.json"
    legacy = json.loads(case_file_path.read_text(encoding="utf-8"))
    for item in legacy:
        item.pop("evidence_index")
        item.pop("citation_anchor")
    case_file_path.write_text(json.dumps(legacy, ensure_ascii=False), encoding="utf-8")

    fetched = client.get(f"/meetings/{meeting_id}")

    assert fetched.status_code == 200
    body = fetched.json()
    expected = [(1, "[證物一]"), (2, "[證物二]")]
    assert [(item["evidence_index"], item["citation_anchor"]) for item in body["case_files"]] == expected
    listed = next(item for item in client.get("/meetings").json() if item["meeting_id"] == meeting_id)
    assert [
        (item["evidence_index"], item["citation_anchor"])
        for item in listed["case_files"]
    ] == expected
    assert "evidence_index" not in (meeting_dir / "case_files.json").read_text(encoding="utf-8")
    metadata = json.loads((meeting_dir / "metadata.json").read_text(encoding="utf-8"))
    assert "case_files" not in metadata
    assert "case_file_count" not in metadata


def test_create_meeting_rejects_case_files_for_unknown_roles(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/meetings",
        json={
            "title": "事故覆盤",
            "goal": "事故覆盤",
            "mode_id": "courtroom",
            "case_files": [
                {
                    "title": "藍軍不屬於法庭",
                    "content": "visible role should be mode-scoped",
                    "visible_roles": ["Blue"],
                }
            ],
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown case file visible role for mode courtroom: Blue"


def test_create_meeting_uses_reported_per_file_limit(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    accepted = client.post(
        "/meetings",
        json={
            "title": "事故覆盤",
            "goal": "事故覆盤",
            "case_files": [
                {
                    "title": "at limit",
                    "content": "x" * 50_000,
                    "visible_roles": ["Blue"],
                }
            ],
        },
    )
    rejected = client.post(
        "/meetings",
        json={
            "title": "事故覆盤",
            "goal": "事故覆盤",
            "case_files": [
                {
                    "title": "too large",
                    "content": "x" * 50_001,
                    "visible_roles": ["Blue"],
                }
            ],
        },
    )

    assert accepted.status_code == 200
    assert rejected.status_code == 413
    assert rejected.json()["detail"] == "Case file content exceeds 50000 characters: too large"


def test_create_meeting_uses_reported_total_case_file_limit(tmp_path: Path) -> None:
    client = TestClient(create_test_app(tmp_path))

    response = client.post(
        "/meetings",
        json={
            "title": "事故覆盤",
            "goal": "事故覆盤",
            "case_files": [
                {
                    "title": f"part {index}",
                    "content": "x" * size,
                    "visible_roles": ["Blue"],
                }
                for index, size in enumerate((40_000, 40_000, 40_001), start=1)
            ],
        },
    )

    assert response.status_code == 413
    assert response.json()["detail"] == "Case files exceed 120000 total characters"


def test_case_file_limits_count_unicode_code_points_like_python_len(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("AI_COUNCIL_MAX_CASE_FILE_CHARS", "2")
    monkeypatch.setenv("AI_COUNCIL_MAX_TOTAL_CASE_FILE_CHARS", "2")
    client = TestClient(create_test_app(tmp_path))

    accepted = client.post(
        "/meetings",
        json={
            "title": "emoji boundary",
            "goal": "emoji boundary",
            "case_files": [
                {"title": "two", "content": "😀😀", "visible_roles": ["Blue"]}
            ],
        },
    )
    rejected = client.post(
        "/meetings",
        json={
            "title": "emoji overflow",
            "goal": "emoji overflow",
            "case_files": [
                {"title": "three", "content": "😀😀😀", "visible_roles": ["Blue"]}
            ],
        },
    )

    assert client.get("/case-file-limits").json() == {
        "per_file_chars": 2,
        "total_chars": 2,
    }
    assert accepted.status_code == 200
    assert rejected.status_code == 413
    assert rejected.json()["detail"] == "Case file content exceeds 2 characters: three"


def test_create_meeting_rejects_unknown_mode(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/meetings",
        json={"title": "T", "goal": "T", "mode_id": "does-not-exist"},
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Unknown mode: does-not-exist"


def test_create_brainstorm_meeting_accepts_member_instances(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/meetings",
        json={
            "title": "T",
            "goal": "T",
            "mode_id": "brainstorm",
            "participants": [
                {
                    "role_id": "Member-1",
                    "model_config_id": "mock-fast",
                    "display_name": "成本委員",
                    "instance_prompt": "從成本角度發想",
                },
                {
                    "role_id": "Member-2",
                    "model_config_id": "mock-fast",
                    "display_name": "使用者委員",
                    "instance_prompt": "從使用者角度發想",
                },
                {"role_id": "Moderator", "model_config_id": "mock-fast"},
            ],
        },
    )

    assert response.status_code == 200
    participants = response.json()["participants"]
    assert [p["role_id"] for p in participants] == ["Member-1", "Member-2", "Moderator"]
    assert participants[0]["display_name"] == "成本委員"
    assert participants[0]["instance_prompt"] == "從成本角度發想"


def test_create_brainstorm_rejects_member_count_outside_fanout_range(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/meetings",
        json={
            "title": "T",
            "goal": "T",
            "mode_id": "brainstorm",
            "participants": [
                {"role_id": "Member-1", "model_config_id": "mock-fast"},
                {"role_id": "Moderator", "model_config_id": "mock-fast"},
            ],
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Mode brainstorm requires 2-6 fanout members"


def test_create_meeting_requires_debate_positions(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    missing_both = client.post(
        "/meetings",
        json={"title": "辯論", "goal": "辯論", "mode_id": "debate"},
    )
    assert missing_both.status_code == 400
    assert missing_both.json()["detail"] == "Missing required input: position_a"

    missing_one = client.post(
        "/meetings",
        json={
            "title": "辯論",
            "goal": "辯論",
            "mode_id": "debate",
            "inputs": {"position_a": "先做後端"},
        },
    )
    assert missing_one.status_code == 400
    assert missing_one.json()["detail"] == "Missing required input: position_b"

    ok = client.post(
        "/meetings",
        json={
            "title": "辯論",
            "goal": "辯論",
            "mode_id": "debate",
            "inputs": {"position_a": "先做後端", "position_b": "先做前端"},
        },
    )
    assert ok.status_code == 200
    assert ok.json()["inputs"] == {"position_a": "先做後端", "position_b": "先做前端"}


def test_create_meeting_rejects_unknown_input_keys(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/meetings",
        json={"title": "T", "goal": "T", "inputs": {"x": "y"}},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown input for mode red-blue: x"


def test_create_meeting_rejects_participant_role_not_in_mode(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/meetings",
        json={
            "title": "T",
            "goal": "T",
            "mode_id": "courtroom",
            "participants": [{"role_id": "Blue", "model_config_id": "mock-fast"}],
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown role for mode courtroom: Blue"


def test_create_meeting_stores_participant_models(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    created = client.post(
        "/meetings",
        json={
            "title": "T",
            "goal": "T",
            "mode_id": "courtroom",
            "participants": [
                {"role_id": "Prosecutor", "model_config_id": "mock-fast"},
                {"role_id": "Defense", "model_config_id": "mock-fast"},
                {"role_id": "Judge", "model_config_id": "mock-fast"},
            ],
        },
    ).json()

    fetched = client.get(f"/meetings/{created['meeting_id']}").json()
    prosecutor = next(p for p in fetched["participants"] if p["role_id"] == "Prosecutor")
    assert prosecutor["model_config_id"] == "mock-fast"


def test_create_relay_meeting_requires_and_persists_complete_model_roster(
    tmp_path: Path,
) -> None:
    client = TestClient(create_test_app(tmp_path))

    incomplete = client.post(
        "/meetings",
        json={
            "title": "Incomplete assignment",
            "goal": "Incomplete assignment",
            "participants": [
                {"role_id": "Blue", "model_config_id": "mock-fast"},
                {"role_id": "Red", "model_config_id": "mock-fast"},
            ],
        },
    )

    assert incomplete.status_code == 400
    assert incomplete.json()["detail"] == "Missing participant roles: Judge"

    created = client.post(
        "/meetings",
        json={
            "title": "Complete assignment",
            "goal": "Complete assignment",
            "participants": [
                {"role_id": "Blue", "model_config_id": "mock-fast"},
                {"role_id": "Red", "model_config_id": "mock-fast"},
                {"role_id": "Judge", "model_config_id": "mock-fast"},
            ],
        },
    )

    assert created.status_code == 200
    assert [
        (participant["role_id"], participant["model_config_id"], participant["model_assignment_source"])
        for participant in created.json()["participants"]
    ] == [
        ("Blue", "mock-fast", "metadata"),
        ("Red", "mock-fast", "metadata"),
        ("Judge", "mock-fast", "metadata"),
    ]


def test_replace_participant_models_requires_complete_roster_and_preserves_metadata(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_test_app(
            tmp_path,
            models_yaml="""
models:
  - id: mock-fast
    adapter: mock
  - id: mock-careful
    adapter: mock
""".strip(),
        )
    )
    created = client.post(
        "/meetings",
        json={
            "title": "Persistent roster",
            "goal": "Persistent roster",
            "participants": [
                {
                    "role_id": "Blue",
                    "model_config_id": "mock-fast",
                    "display_name": "Proposal owner",
                    "instance_prompt": "Protect the budget",
                },
                {"role_id": "Red", "model_config_id": "mock-fast"},
                {"role_id": "Judge", "model_config_id": "mock-fast"},
            ],
        },
    ).json()
    meeting_id = created["meeting_id"]

    incomplete = client.put(
        f"/meetings/{meeting_id}/participant-models",
        json={"models": {"Blue": "mock-careful", "Red": "mock-fast"}},
    )

    assert incomplete.status_code == 400
    assert incomplete.json()["detail"] == "Participant model roster mismatch; missing roles: Judge"

    unknown = client.put(
        f"/meetings/{meeting_id}/participant-models",
        json={
            "models": {
                "Blue": "missing-model",
                "Red": "mock-fast",
                "Judge": "mock-fast",
            }
        },
    )

    assert unknown.status_code == 404
    assert unknown.json()["detail"] == "Unknown model: missing-model"

    updated = client.put(
        f"/meetings/{meeting_id}/participant-models",
        json={
            "models": {
                "Blue": "mock-careful",
                "Red": "mock-fast",
                "Judge": "mock-careful",
            }
        },
    )

    assert updated.status_code == 200
    participants = {item["role_id"]: item for item in updated.json()["participants"]}
    assert participants["Blue"]["model_config_id"] == "mock-careful"
    assert participants["Blue"]["display_name"] == "Proposal owner"
    assert participants["Blue"]["instance_prompt"] == "Protect the budget"
    assert participants["Judge"]["model_config_id"] == "mock-careful"
    assert all(item["model_assignment_source"] == "metadata" for item in participants.values())


def test_concurrent_metadata_updates_do_not_clobber_assignment_tags_or_pinned(
    tmp_path: Path,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post("/meetings", json={"title": "Concurrent metadata", "goal": "Concurrent metadata"}).json()[
        "meeting_id"
    ]

    def update_models() -> None:
        response = client.put(
            f"/meetings/{meeting_id}/participant-models",
            json={
                "models": {
                    "Blue": "mock-fast",
                    "Red": "mock-fast",
                    "Judge": "mock-fast",
                }
            },
        )
        assert response.status_code == 200

    def update_tags() -> None:
        assert client.put(
            f"/meetings/{meeting_id}/tags",
            json={"tags": ["concurrent"]},
        ).status_code == 200

    def update_pinned() -> None:
        assert client.put(
            f"/meetings/{meeting_id}/pinned",
            json={"pinned": True},
        ).status_code == 200

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(operation) for operation in (update_models, update_tags, update_pinned)]
        for future in futures:
            future.result()

    fetched = client.get(f"/meetings/{meeting_id}").json()
    assert fetched["tags"] == ["concurrent"]
    assert fetched["pinned"] is True
    assert {item["model_config_id"] for item in fetched["participants"]} == {"mock-fast"}


def test_create_meeting_rejects_unknown_participant_model(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/meetings",
        json={
            "title": "T",
            "goal": "T",
            "mode_id": "courtroom",
            "participants": [{"role_id": "Prosecutor", "model_config_id": "nope"}],
        },
    )

    assert response.status_code == 404
    assert response.json()["detail"] == "Unknown model: nope"


def test_legacy_meeting_projects_red_blue_participants(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = "meeting-legacy"
    metadata_path = tmp_path / "data" / "meetings" / meeting_id / "metadata.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(
        json.dumps(
            {
                "meeting_id": meeting_id,
                "title": "舊資料",
                "goal": "舊資料",
                "created_at": "2026-01-01T00:00:00+00:00",
                "tags": [],
                "pinned": False,
            }
        ),
        encoding="utf-8",
    )

    fetched = client.get(f"/meetings/{meeting_id}").json()

    assert fetched["mode_id"] == "red-blue"
    assert [p["role_id"] for p in fetched["participants"]] == ["Blue", "Red", "Judge"]


def test_legacy_assignment_recovery_and_deleted_model_fallback_are_read_only(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_test_app(
            tmp_path,
            models_yaml="""
models:
  - id: mock-default
    adapter: mock
  - id: mock-event
    adapter: mock
""".strip(),
        )
    )
    meeting_id = "meeting-legacy-assignment"
    meeting_dir = tmp_path / "data" / "meetings" / meeting_id
    meeting_dir.mkdir(parents=True)
    metadata_path = meeting_dir / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "meeting_id": meeting_id,
                "title": "Legacy assignments",
                "goal": "Legacy assignments",
                "created_at": "2026-01-01T00:00:00+00:00",
                "participants": [
                    {"role_id": "Blue"},
                    {"role_id": "Red"},
                    {"role_id": "Judge", "model_config_id": "deleted-model"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    events = [
        {
            "event_id": "blue-old",
            "meeting_id": meeting_id,
            "step_id": "blue-propose",
            "role": "Blue",
            "status": "completed",
            "model_config_id": "mock-default",
        },
        {
            "event_id": "judge-event",
            "meeting_id": meeting_id,
            "step_id": "judge-decide",
            "role": "Judge",
            "status": "completed",
            "model_config_id": "mock-event",
        },
        {
            "event_id": "blue-latest",
            "meeting_id": meeting_id,
            "step_id": "blue-revise",
            "role": "Blue",
            "status": "completed",
            "model_config_id": "mock-event",
        },
    ]
    events_path = meeting_dir / "events.jsonl"
    events_path.write_text(
        "".join(json.dumps(event) + "\n" for event in events),
        encoding="utf-8",
    )
    metadata_before = metadata_path.read_bytes()
    events_before = events_path.read_bytes()

    fetched = client.get(f"/meetings/{meeting_id}")
    listed = client.get("/meetings")

    assert fetched.status_code == 200
    assert listed.status_code == 200
    participants = {item["role_id"]: item for item in fetched.json()["participants"]}
    assert (participants["Blue"]["model_config_id"], participants["Blue"]["model_assignment_source"]) == (
        "mock-event",
        "latest-event",
    )
    assert (participants["Red"]["model_config_id"], participants["Red"]["model_assignment_source"]) == (
        "mock-default",
        "default",
    )
    assert (participants["Judge"]["model_config_id"], participants["Judge"]["model_assignment_source"]) == (
        "mock-default",
        "default",
    )
    assert "deleted-model" in participants["Judge"]["model_assignment_warning"]
    assert metadata_path.read_bytes() == metadata_before
    assert events_path.read_bytes() == events_before


def test_meeting_list_tolerates_removed_mode_id_metadata(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = "meeting-ghost-mode"
    metadata_path = tmp_path / "data" / "meetings" / meeting_id / "metadata.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(
        json.dumps(
            {
                "meeting_id": meeting_id,
                "title": "髒資料模式",
                "goal": "髒資料模式",
                "created_at": "2026-01-01T00:00:00+00:00",
                "tags": [],
                "pinned": False,
                "mode_id": "removed-mode",
            }
        ),
        encoding="utf-8",
    )

    response = client.get("/meetings")

    assert response.status_code == 200
    [meeting] = response.json()
    assert meeting["meeting_id"] == meeting_id
    assert meeting["mode_id"] == "red-blue"
    assert [p["role_id"] for p in meeting["participants"]] == ["Blue", "Red", "Judge"]


def test_generic_start_cannot_bypass_courtroom_issue_workflow(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={"title": "法庭審理", "goal": "法庭審理", "mode_id": "courtroom"},
    ).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/start",
        json={
            "models": {
                "Prosecutor": "mock-fast",
                "Defense": "mock-fast",
                "Judge": "mock-fast",
            }
        },
    )

    assert response.status_code == 409
    assert client.get(f"/meetings/{meeting_id}").json()["events"] == []


def test_start_uses_persisted_assignment_and_ignores_legacy_request_models(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_test_app(
            tmp_path,
            models_yaml="""
models:
  - id: persisted-model
    adapter: mock
  - id: request-model
    adapter: mock
""".strip(),
        )
    )
    meeting_id = client.post(
        "/meetings",
        json={
            "title": "Authoritative assignment",
            "goal": "Authoritative assignment",
            "participants": [
                {"role_id": role, "model_config_id": "persisted-model"}
                for role in ["Blue", "Red", "Judge"]
            ],
        },
    ).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/start",
        json={
            "models": {
                "Blue": "request-model",
                "Red": "request-model",
                "Judge": "request-model",
            }
        },
    )

    assert response.status_code == 202
    meeting = wait_for_activity(client, meeting_id, "completed")
    assert {
        event["model_config_id"]
        for event in meeting["events"]
        if event["status"] == "completed"
    } == {"persisted-model"}


def test_start_uses_default_fallback_after_persisted_model_is_deleted(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_test_app(
            tmp_path,
            models_yaml="""
models:
  - id: fallback-model
    adapter: mock
  - id: deleted-model
    adapter: mock
""".strip(),
        )
    )
    meeting_id = client.post(
        "/meetings",
        json={
            "title": "Deleted assignment",
            "goal": "Deleted assignment",
            "participants": [
                {"role_id": role, "model_config_id": "deleted-model"}
                for role in ["Blue", "Red", "Judge"]
            ],
        },
    ).json()["meeting_id"]
    assert client.delete("/models/deleted-model").status_code == 200

    projected = client.get(f"/meetings/{meeting_id}").json()
    response = client.post(f"/meetings/{meeting_id}/start", json={})

    assert {item["model_assignment_source"] for item in projected["participants"]} == {"default"}
    assert response.status_code == 202
    meeting = wait_for_activity(client, meeting_id, "completed")
    assert {event["model_config_id"] for event in meeting["events"]} == {"fallback-model"}


def test_courtroom_start_request_models_cannot_bypass_issue_workflow(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={"title": "法庭審理", "goal": "法庭審理", "mode_id": "courtroom"},
    ).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/start",
        json={"models": {"Judge": "mock-fast"}},
    )

    assert response.status_code == 409
    assert client.get(f"/meetings/{meeting_id}").json()["events"] == []


def test_debate_inputs_reach_prompts(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={
            "title": "辯論",
            "goal": "辯論",
            "mode_id": "debate",
            "inputs": {"position_a": "先做後端", "position_b": "先做前端"},
        },
    ).json()["meeting_id"]

    client.post(
        f"/meetings/{meeting_id}/start",
        json={
            "models": {
                "Pro": "mock-fast",
                "Con": "mock-fast",
                "Arbiter": "mock-fast",
            }
        },
    )
    meeting = wait_for_activity(client, meeting_id, "completed")

    first_completed = next(event for event in meeting["events"] if event["status"] == "completed")
    assert "先做後端" in first_completed["prompt_messages"][0]["content"]
    verdict = meeting["events"][-1]
    assert verdict["role"] == "Arbiter"
    assert verdict["output_schema_id"] == "structured-verdict/v1"
    assert verdict["parsed_output"]["decision"] == "approve-with-conditions"


def test_case_files_reach_only_visible_role_prompts(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={
            "title": "事故覆盤",
            "goal": "事故覆盤",
            "mode_id": "courtroom",
            "case_files": [
                {
                    "title": "檢方事故時間線",
                    "content": "10:05 error rate spike",
                    "visible_roles": ["Prosecutor", "Judge"],
                },
                {
                    "title": "辯方回滾說明",
                    "content": "rollback was blocked by migration",
                    "visible_roles": ["Defense", "Judge"],
                },
            ],
        },
    ).json()["meeting_id"]

    run_single_courtroom_issue(client, meeting_id, "事故責任")
    meeting = client.get(f"/meetings/{meeting_id}").json()

    prompts_by_role = {
        event["role"]: event["prompt_messages"][0]["content"]
        for event in meeting["events"]
        if event.get("status") == "completed"
    }
    assert "檢方事故時間線" in prompts_by_role["Prosecutor"]
    assert "### [證物一] 檢方事故時間線" in prompts_by_role["Prosecutor"]
    assert "[證物二]" not in prompts_by_role["Prosecutor"]
    assert "辯方回滾說明" not in prompts_by_role["Prosecutor"]
    assert "辯方回滾說明" in prompts_by_role["Defense"]
    assert "### [證物二] 辯方回滾說明" in prompts_by_role["Defense"]
    assert "[證物一]" not in prompts_by_role["Defense"]
    assert "檢方事故時間線" not in prompts_by_role["Defense"]
    assert "檢方事故時間線" in prompts_by_role["Judge"]
    assert "辯方回滾說明" in prompts_by_role["Judge"]
    assert "### [證物一] 檢方事故時間線" in prompts_by_role["Judge"]
    assert "### [證物二] 辯方回滾說明" in prompts_by_role["Judge"]
    for prompt in prompts_by_role.values():
        assert "引用案卷中的事實或主張時，必須附上對應的 [證物…] 引用錨點" in prompt
        assert "不可假造不存在的證物錨點" in prompt


def test_roles_without_visible_case_files_receive_citation_rules_without_evidence_leakage(
    tmp_path: Path,
) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={
            "title": "限制案卷可見範圍",
            "goal": "限制案卷可見範圍",
            "mode_id": "courtroom",
            "case_files": [
                {
                    "title": "裁判密件",
                    "content": "Only the Judge may inspect this claim.",
                    "visible_roles": ["Judge"],
                }
            ],
        },
    ).json()["meeting_id"]

    run_single_courtroom_issue(client, meeting_id, "密件主張")
    meeting = client.get(f"/meetings/{meeting_id}").json()

    prosecutor_prompt = next(
        event["prompt_messages"][0]["content"]
        for event in meeting["events"]
        if event.get("status") == "completed" and event.get("role") == "Prosecutor"
    )
    assert "引用案卷中的事實或主張時，必須附上對應的 [證物…] 引用錨點" in prosecutor_prompt
    assert "不可假造不存在的證物錨點" in prosecutor_prompt
    assert "裁判密件" not in prosecutor_prompt
    assert "Only the Judge may inspect this claim." not in prosecutor_prompt
    assert "[證物一]" not in prosecutor_prompt


def test_case_files_reach_parallel_member_instance_prompts(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={
            "title": "腦力激盪",
            "goal": "腦力激盪",
            "mode_id": "brainstorm",
            "participants": [
                {"role_id": "Member-1", "model_config_id": "mock-fast"},
                {"role_id": "Member-2", "model_config_id": "mock-fast"},
                {"role_id": "Moderator", "model_config_id": "mock-fast"},
            ],
            "case_files": [
                {
                    "title": "成本資料",
                    "content": "GPU budget is capped.",
                    "visible_roles": ["Member-1", "Moderator"],
                },
                {
                    "title": "用戶訪談",
                    "content": "Users asked for simpler onboarding.",
                    "visible_roles": ["Member-2", "Moderator"],
                },
            ],
        },
    ).json()["meeting_id"]

    client.post(
        f"/meetings/{meeting_id}/start",
        json={
            "models": {
                "Member-1": "mock-fast",
                "Member-2": "mock-fast",
                "Moderator": "mock-fast",
            }
        },
    )
    meeting = wait_for_activity(client, meeting_id, "completed")

    prompts_by_role = {
        event["role"]: event["prompt_messages"][0]["content"]
        for event in meeting["events"]
        if event.get("status") == "completed"
    }
    assert "成本資料" in prompts_by_role["Member-1"]
    assert "用戶訪談" not in prompts_by_role["Member-1"]
    assert "用戶訪談" in prompts_by_role["Member-2"]
    assert "成本資料" not in prompts_by_role["Member-2"]
    assert "成本資料" in prompts_by_role["Moderator"]
    assert "用戶訪談" in prompts_by_role["Moderator"]


def test_start_brainstorm_meeting_runs_parallel_steps(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={
            "title": "腦力激盪",
            "goal": "腦力激盪",
            "mode_id": "brainstorm",
            "participants": [
                {"role_id": "Member-1", "model_config_id": "mock-fast"},
                {"role_id": "Member-2", "model_config_id": "mock-fast"},
                {"role_id": "Moderator", "model_config_id": "mock-fast"},
            ],
        },
    ).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/start",
        json={
            "models": {
                "Member-1": "mock-fast",
                "Member-2": "mock-fast",
                "Moderator": "mock-fast",
            }
        },
    )

    assert response.status_code == 202
    meeting = wait_for_activity(client, meeting_id, "completed")
    completed_steps = [
        event["step_id"] for event in meeting["events"] if event["status"] == "completed"
    ]
    assert completed_steps == [
        "fanout-1-member-1",
        "fanout-1-member-2",
        "synthesis-1",
    ]


def test_parallel_failure_projects_waiting_and_retry_synthesizes(tmp_path: Path, monkeypatch) -> None:
    app = create_test_app(
        tmp_path,
        models_yaml="""
models:
  - id: mock-member-1
    adapter: mock
  - id: mock-member-2
    adapter: mock
  - id: mock-moderator
    adapter: mock
  - id: request-model
    adapter: mock
""".strip(),
    )
    client = TestClient(app)
    failing_model_ids = {"mock-member-2"}
    original_complete = MockModelAdapter.complete

    def fail_member_2_once(self: MockModelAdapter, request: ModelRequest) -> ModelResponse:
        if request.model_config.id in failing_model_ids:
            raise AdapterError("adapter boom")
        return original_complete(self, request)

    monkeypatch.setattr(MockModelAdapter, "complete", fail_member_2_once)
    meeting_id = client.post(
        "/meetings",
        json={
            "title": "腦力激盪",
            "goal": "腦力激盪",
            "mode_id": "brainstorm",
            "participants": [
                {"role_id": "Member-1", "model_config_id": "mock-member-1"},
                {"role_id": "Member-2", "model_config_id": "mock-member-2"},
                {"role_id": "Moderator", "model_config_id": "mock-moderator"},
            ],
        },
    ).json()["meeting_id"]
    request_models = {
        "Member-1": "request-model",
        "Member-2": "request-model",
        "Moderator": "request-model",
    }

    client.post(f"/meetings/{meeting_id}/start", json={"models": request_models})
    meeting = wait_for_activity(client, meeting_id, "waiting")
    assert [event["step_id"] for event in meeting["events"]] == [
        "fanout-1-member-1",
        "fanout-1-member-2",
    ]
    assert meeting["events"][-1]["status"] == "failed"

    failing_model_ids.clear()
    retry = client.post(
        f"/meetings/{meeting_id}/steps/fanout-1-member-2/retry",
        json={"models": request_models},
    )
    assert retry.status_code == 202
    meeting = wait_for_activity(client, meeting_id, "completed")
    assert [event["step_id"] for event in meeting["events"]] == [
        "fanout-1-member-1",
        "fanout-1-member-2",
        "fanout-1-member-2",
        "synthesis-1",
    ]
    assert meeting["events"][-2]["model_config_id"] == "mock-member-2"
    assert meeting["events"][-1]["model_config_id"] == "mock-moderator"


def test_respond_as_role_accepts_mode_roles(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={"title": "法庭審理", "goal": "法庭審理", "mode_id": "courtroom"},
    ).json()["meeting_id"]
    assert client.put(
        f"/meetings/{meeting_id}/courtroom/issues",
        json={"revision": 0, "issues": [{"title": "控方主張是否成立"}]},
    ).status_code == 200
    assert client.post(
        f"/meetings/{meeting_id}/courtroom/issues/confirm",
        json={"revision": 1},
    ).status_code == 200
    assert client.post(
        f"/meetings/{meeting_id}/courtroom/issues/issue-1/arguments"
    ).status_code == 202
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        meeting = client.get(f"/meetings/{meeting_id}").json()
        if meeting["courtroom"]["issues"][0]["status"] == "awaiting-ruling":
            break
        time.sleep(0.01)
    else:
        raise AssertionError("Courtroom issue arguments did not complete")

    response = client.post(
        f"/meetings/{meeting_id}/roles/Prosecutor/respond",
        json={"instruction": "請整理目前控方主張"},
    )
    assert response.status_code == 202
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        events = client.get(f"/meetings/{meeting_id}").json()["events"]
        if events and events[-1].get("interaction_type") == "directed-role-response":
            break
        time.sleep(0.01)
    else:
        raise AssertionError("Directed response did not complete")
    assert events[-1]["step_id"] == "directed-1-prosecutor-response"

    rejected = client.post(
        f"/meetings/{meeting_id}/roles/Blue/respond",
        json={"instruction": "請回答"},
    )
    assert rejected.status_code == 400


def test_directed_response_cannot_bypass_unresolved_fixed_relay_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    original_complete = MockModelAdapter.complete
    call_count = 0

    def fail_second_fixed_step(self: MockModelAdapter, request: ModelRequest) -> ModelResponse:
        nonlocal call_count
        call_count += 1
        if call_count == 2:
            raise AdapterError("fixed relay failure")
        return original_complete(self, request)

    monkeypatch.setattr(MockModelAdapter, "complete", fail_second_fixed_step)
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings",
        json={"title": "失敗回合", "goal": "驗證失敗 guard"},
    ).json()["meeting_id"]
    assert client.post(f"/meetings/{meeting_id}/start", json={}).status_code == 202
    meeting = wait_for_activity(client, meeting_id, "failed")
    assert meeting["events"][-1]["base_step_id"] == "red-critique"
    before = meeting["events"]

    response = client.post(
        f"/meetings/{meeting_id}/roles/Blue/respond",
        json={"instruction": "不得繞過失敗步驟"},
    )

    assert response.status_code == 409
    assert "retry" in response.json()["detail"].lower()
    assert client.get(f"/meetings/{meeting_id}").json()["events"] == before

    sequence = client.post(
        f"/meetings/{meeting_id}/sequences",
        json={"roles": ["Blue", "Red"]},
    )
    assert sequence.status_code == 409
    assert "retry" in sequence.json()["detail"].lower()
    assert client.get(f"/meetings/{meeting_id}").json()["events"] == before


def test_local_frontend_origin_can_call_api(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.options(
        "/models",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


def test_restart_archives_live_events_and_exposes_epoch_transcripts(tmp_path: Path) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings", json={"title": "重新審議", "goal": "選出方案"}
    ).json()["meeting_id"]
    assert client.post(f"/meetings/{meeting_id}/start", json={}).status_code == 202
    first = wait_for_activity(client, meeting_id, "completed")
    old_event_ids = [event["event_id"] for event in first["events"]]

    restarted = client.post(
        f"/meetings/{meeting_id}/deliberations/restart",
        json={"scope": "all_deliberation", "reason": "改用新的審議方向"},
    )

    assert restarted.status_code == 200
    assert restarted.json()["events"] == []
    assert restarted.json()["deliberation"]["active_epoch_number"] == 2
    history = client.get(f"/meetings/{meeting_id}/deliberations").json()
    assert [epoch["event_count"] for epoch in history["epochs"]] == [4, 0]
    assert history["epochs"][1]["reason"] == "改用新的審議方向"
    current_transcript = client.get(f"/meetings/{meeting_id}/transcript.md").text
    first_transcript = client.get(
        f"/meetings/{meeting_id}/transcript.md", params={"epoch": history["epochs"][0]["id"]}
    ).text
    all_transcript = client.get(
        f"/meetings/{meeting_id}/transcript.md", params={"epoch": "all"}
    ).text
    assert "blue-propose" not in current_transcript
    assert "Mock response" in first_transcript
    assert "改用新的審議方向" in all_transcript
    raw = MeetingRepository(tmp_path / "data").read_events(meeting_id)
    assert [event["event_id"] for event in raw[:4]] == old_event_ids
    assert len(raw) == 5


def test_restart_requires_idle_open_meeting_valid_reason_and_compatible_scope(
    tmp_path: Path,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings", json={"title": "重開 gate", "goal": "檢查 gate"}
    ).json()["meeting_id"]

    blank = client.post(
        f"/meetings/{meeting_id}/deliberations/restart",
        json={"scope": "all_deliberation", "reason": " "},
    )
    wrong_scope = client.post(
        f"/meetings/{meeting_id}/deliberations/restart",
        json={"scope": "current_issue", "reason": "重跑", "issue_id": "issue-1"},
    )
    assert client.post(f"/meetings/{meeting_id}/close").status_code == 200
    terminal = client.post(
        f"/meetings/{meeting_id}/deliberations/restart",
        json={"scope": "all_deliberation", "reason": "重跑"},
    )

    assert blank.status_code == 422
    assert wrong_scope.status_code == 400
    assert terminal.status_code == 409
    assert "reopen" in terminal.json()["detail"].lower()
    assert client.post(f"/meetings/{meeting_id}/reopen").status_code == 200
    assert client.post(
        f"/meetings/{meeting_id}/deliberations/restart",
        json={"scope": "all_deliberation", "reason": "重跑"},
    ).status_code == 200


def test_restart_new_run_uses_unique_event_ids_and_excludes_archived_prompt(
    tmp_path: Path,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings", json={"title": "Prompt isolation", "goal": "測試隔離"}
    ).json()["meeting_id"]
    assert client.post(f"/meetings/{meeting_id}/start", json={}).status_code == 202
    old = wait_for_activity(client, meeting_id, "completed")["events"]
    assert client.post(
        f"/meetings/{meeting_id}/messages", json={"content": "ARCHIVED_SECRET"}
    ).status_code == 200
    assert client.post(
        f"/meetings/{meeting_id}/deliberations/restart",
        json={"scope": "all_deliberation", "reason": "fresh"},
    ).status_code == 200
    assert client.post(f"/meetings/{meeting_id}/start", json={}).status_code == 202
    new = wait_for_activity(client, meeting_id, "completed")["events"]

    assert {event["event_id"] for event in old}.isdisjoint(
        event["event_id"] for event in new
    )
    assert all("ARCHIVED_SECRET" not in event["prompt_messages"][0]["content"] for event in new)


def test_courtroom_restart_scopes_preserve_only_the_promised_state(tmp_path: Path) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings",
        json={"title": "法院重審", "goal": "逐點判斷", "mode_id": "courtroom"},
    ).json()["meeting_id"]
    assert client.put(
        f"/meetings/{meeting_id}/courtroom/issues",
        json={"revision": 0, "issues": [{"title": "爭點一"}, {"title": "爭點二"}]},
    ).status_code == 200
    assert client.post(
        f"/meetings/{meeting_id}/courtroom/issues/confirm", json={"revision": 1}
    ).status_code == 200
    for issue_id in ("issue-1", "issue-2"):
        assert client.post(
            f"/meetings/{meeting_id}/courtroom/issues/{issue_id}/arguments"
        ).status_code == 202
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            meeting = client.get(f"/meetings/{meeting_id}").json()
            issue = next(item for item in meeting["courtroom"]["issues"] if item["id"] == issue_id)
            if issue["status"] == "awaiting-ruling":
                break
            time.sleep(0.01)
        assert client.post(
            f"/meetings/{meeting_id}/courtroom/issues/{issue_id}/ruling"
        ).status_code == 202
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            meeting = client.get(f"/meetings/{meeting_id}").json()
            issue = next(item for item in meeting["courtroom"]["issues"] if item["id"] == issue_id)
            if issue["status"] == "ruled":
                break
            time.sleep(0.01)

    current = client.post(
        f"/meetings/{meeting_id}/deliberations/restart",
        json={"scope": "current_issue", "reason": "重審第二點", "issue_id": "issue-2"},
    )
    assert current.status_code == 200
    assert [item["status"] for item in current.json()["courtroom"]["issues"]] == [
        "ruled",
        "pending",
    ]
    assert current.json()["courtroom"]["final_status"] == "not-ready"

    all_restart = client.post(
        f"/meetings/{meeting_id}/deliberations/restart",
        json={"scope": "all_deliberation", "reason": "全案重審"},
    )
    assert all_restart.status_code == 200
    assert [item["status"] for item in all_restart.json()["courtroom"]["issues"]] == [
        "pending",
        "pending",
    ]

    rebuilt = client.post(
        f"/meetings/{meeting_id}/deliberations/restart",
        json={"scope": "rebuild_issues", "reason": "重新整理爭點"},
    )
    assert rebuilt.status_code == 200
    assert rebuilt.json()["courtroom"]["status"] == "not-configured"
    assert client.put(
        f"/meetings/{meeting_id}/details",
        json={"title": "法院重審", "goal": "更新後的目標"},
    ).status_code == 200


def test_archived_failure_cannot_be_retried(tmp_path: Path, monkeypatch) -> None:
    original_complete = MockModelAdapter.complete
    failed_once = False

    def fail_once(self, request):
        nonlocal failed_once
        if not failed_once:
            failed_once = True
            raise AdapterError("old failure")
        return original_complete(self, request)

    monkeypatch.setattr(MockModelAdapter, "complete", fail_once)
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings", json={"title": "Retry isolation", "goal": "測試"}
    ).json()["meeting_id"]
    assert client.post(f"/meetings/{meeting_id}/start", json={}).status_code == 202
    failed = wait_for_activity(client, meeting_id, "failed")["events"][-1]
    assert client.post(
        f"/meetings/{meeting_id}/deliberations/restart",
        json={"scope": "all_deliberation", "reason": "discard failure"},
    ).status_code == 200

    retry = client.post(f"/meetings/{meeting_id}/steps/{failed['step_id']}/retry", json={})

    assert retry.status_code == 400
    assert "not failed" in retry.json()["detail"].lower()


def test_restart_event_write_failure_leaves_execution_safely_blocked(
    tmp_path: Path, monkeypatch
) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=False)
    meeting_id = client.post(
        "/meetings", json={"title": "Fault ordering", "goal": "never run half reset"}
    ).json()["meeting_id"]
    original_append = MeetingRepository.append_event
    fail_append = True

    def fail_marker(self, target_meeting_id, event):
        if fail_append and event.get("interaction_type") == "deliberation-epoch-start":
            raise OSError("simulated journal failure")
        return original_append(self, target_meeting_id, event)

    monkeypatch.setattr(MeetingRepository, "append_event", fail_marker)
    failed = client.post(
        f"/meetings/{meeting_id}/deliberations/restart",
        json={"scope": "all_deliberation", "reason": "fault test"},
    )
    blocked = client.post(f"/meetings/{meeting_id}/start", json={})
    mutation = client.put(
        f"/meetings/{meeting_id}/details",
        json={"title": "must not change", "goal": "must not change"},
    )
    fail_append = False
    recovered = client.post(
        f"/meetings/{meeting_id}/deliberations/restart",
        json={"scope": "all_deliberation", "reason": "fault retry"},
    )

    assert failed.status_code == 500
    assert blocked.status_code == 409
    assert mutation.status_code == 409
    assert recovered.status_code == 200
    assert recovered.json()["deliberation"]["active_epoch_number"] == 2
    assert recovered.json()["title"] == "Fault ordering"
    assert "retried" in blocked.json()["detail"].lower()
    raw_events = MeetingRepository(tmp_path / "data").read_events(meeting_id)
    assert len(raw_events) == 1
    assert raw_events[0]["restart_reason"] == "fault retry"


def test_pending_completed_restart_reconciles_before_mutation_and_rebuild_is_not_lost(
    tmp_path: Path, monkeypatch
) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app, raise_server_exceptions=False)
    meeting_id = client.post(
        "/meetings",
        json={"title": "Pending rebuild", "goal": "rebuild", "mode_id": "courtroom"},
    ).json()["meeting_id"]
    assert client.put(
        f"/meetings/{meeting_id}/courtroom/issues",
        json={"revision": 0, "issues": [{"title": "old issue"}]},
    ).status_code == 200
    original_update = MeetingMetadataStore.update
    fail_finalize = True

    def fail_final_metadata_write(self, target_meeting_id, transform):
        nonlocal fail_finalize
        current = self.get(target_meeting_id)
        projected = transform(current)
        if (
            fail_finalize
            and current.get("pending_deliberation_restart")
            and not projected.get("pending_deliberation_restart")
        ):
            raise OSError("simulated metadata finalize failure")
        return original_update(self, target_meeting_id, transform)

    monkeypatch.setattr(MeetingMetadataStore, "update", fail_final_metadata_write)
    failed = client.post(
        f"/meetings/{meeting_id}/deliberations/restart",
        json={"scope": "rebuild_issues", "reason": "fault after marker"},
    )
    fail_finalize = False

    stale_docket_mutation = client.put(
        f"/meetings/{meeting_id}/courtroom/issues",
        json={"revision": 1, "issues": [{"title": "must not silently survive"}]},
    )
    meeting = client.get(f"/meetings/{meeting_id}").json()

    assert failed.status_code == 500
    assert stale_docket_mutation.status_code == 409
    assert meeting["courtroom"]["status"] == "not-configured"
    assert "pending_deliberation_restart" not in meeting


def test_restart_rejects_a_truly_inflight_meeting(
    tmp_path: Path, monkeypatch
) -> None:
    release = threading.Event()
    started = threading.Event()
    original_complete = MockModelAdapter.complete

    def pause_first_argument(self, request):
        started.set()
        release.wait(timeout=3)
        return original_complete(self, request)

    monkeypatch.setattr(MockModelAdapter, "complete", pause_first_argument)
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings",
        json={"title": "Active issue", "goal": "one at a time", "mode_id": "courtroom"},
    ).json()["meeting_id"]
    assert client.put(
        f"/meetings/{meeting_id}/courtroom/issues",
        json={"revision": 0, "issues": [{"title": "one"}, {"title": "two"}]},
    ).status_code == 200
    assert client.post(
        f"/meetings/{meeting_id}/courtroom/issues/confirm", json={"revision": 1}
    ).status_code == 200
    assert client.post(
        f"/meetings/{meeting_id}/courtroom/issues/issue-1/arguments"
    ).status_code == 202
    assert started.wait(timeout=2)

    wrong = client.post(
        f"/meetings/{meeting_id}/deliberations/restart",
        json={"scope": "all_deliberation", "reason": "must wait"},
    )
    release.set()
    wait_for_activity(client, meeting_id, "completed")

    assert wrong.status_code == 409
    assert "running" in wrong.json()["detail"].lower()


def test_restart_rejects_non_active_issue_after_an_issue_has_started(tmp_path: Path) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings",
        json={"title": "Issue identity", "goal": "one at a time", "mode_id": "courtroom"},
    ).json()["meeting_id"]
    assert client.put(
        f"/meetings/{meeting_id}/courtroom/issues",
        json={"revision": 0, "issues": [{"title": "one"}, {"title": "two"}]},
    ).status_code == 200
    assert client.post(
        f"/meetings/{meeting_id}/courtroom/issues/confirm", json={"revision": 1}
    ).status_code == 200
    assert client.post(
        f"/meetings/{meeting_id}/courtroom/issues/issue-1/arguments"
    ).status_code == 202
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        meeting = client.get(f"/meetings/{meeting_id}").json()
        if meeting["courtroom"]["current_issue_id"] == "issue-1":
            break
        time.sleep(0.01)

    wrong = client.post(
        f"/meetings/{meeting_id}/deliberations/restart",
        json={"scope": "current_issue", "reason": "wrong issue", "issue_id": "issue-2"},
    )

    assert wrong.status_code == 409
    assert "active courtroom issue" in wrong.json()["detail"].lower()


def test_every_non_courtroom_mode_can_restart_without_changing_case_files(
    tmp_path: Path,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    modes = [mode for mode in client.get("/modes").json() if mode["id"] != "courtroom"]
    assert {mode["category"] for mode in modes} == {"relay", "parallel"}

    for mode in modes:
        meeting = client.post(
            "/meetings",
            json={
                "title": f"restart {mode['id']}",
                "goal": "restart safely",
                "mode_id": mode["id"],
                "inputs": {item["id"]: "test" for item in mode["inputs"]},
            },
        ).json()
        meeting_id = meeting["meeting_id"]

        restarted = client.post(
            f"/meetings/{meeting_id}/deliberations/restart",
            json={"scope": "all_deliberation", "reason": "mode coverage"},
        )

        assert restarted.status_code == 200, mode["id"]

    evidence_meeting = client.post(
        "/meetings",
        json={
            "title": "same evidence",
            "goal": "preserve evidence",
            "mode_id": "red-blue",
            "case_files": [
                {
                    "title": "same evidence",
                    "content": "byte-for-byte",
                    "visible_roles": ["Blue"],
                }
            ],
        },
    ).json()
    evidence_meeting_id = evidence_meeting["meeting_id"]
    case_file_path = (
        tmp_path / "data" / "meetings" / evidence_meeting_id / "case_files.json"
    )
    before_bytes = case_file_path.read_bytes()
    before_manifest = client.get(
        f"/meetings/{evidence_meeting_id}"
    ).json()["case_files"]

    restarted = client.post(
        f"/meetings/{evidence_meeting_id}/deliberations/restart",
        json={"scope": "all_deliberation", "reason": "evidence identity"},
    )

    assert restarted.status_code == 200
    assert restarted.json()["case_files"] == before_manifest
    assert case_file_path.read_bytes() == before_bytes


def test_case_material_http_mutations_upgrade_legacy_and_preserve_versions(
    tmp_path: Path,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings",
        json={
            "title": "Versioned evidence",
            "goal": "inspect evidence",
            "mode_id": "courtroom",
            "case_files": [
                {
                    "title": "Legacy exhibit",
                    "content": "legacy body",
                    "visible_roles": ["Judge"],
                }
            ],
        },
    ).json()["meeting_id"]
    path = tmp_path / "data" / "meetings" / meeting_id / "case_files.json"
    metadata_path = path.with_name("metadata.json")
    legacy_bytes = path.read_bytes()
    metadata_bytes = metadata_path.read_bytes()

    legacy = client.get(f"/meetings/{meeting_id}/materials")
    assert legacy.status_code == 200
    assert legacy.json()["schema_version"] == 1
    assert path.read_bytes() == legacy_bytes

    added = client.post(
        f"/meetings/{meeting_id}/materials/evidence",
        json={
            "revision": 0,
            "title": "New exhibit",
            "content": "version one",
            "visible_roles": ["Defense", "Judge"],
        },
    )
    assert added.status_code == 200
    assert added.json()["revision"] == 1
    assert added.json()["evidence"][1]["citation_anchor"] == "[證物二]"
    evidence_id = added.json()["evidence"][1]["id"]

    versioned = client.post(
        f"/meetings/{meeting_id}/materials/evidence/{evidence_id}/versions",
        json={
            "revision": 1,
            "title": "New exhibit corrected",
            "content": "version two",
            "visible_roles": ["Prosecutor"],
        },
    )
    assert versioned.status_code == 200
    assert versioned.json()["evidence"][1]["active_version"] == 2
    assert versioned.json()["evidence"][1]["versions"][0]["visible_roles"] == [
        "Defense",
        "Judge",
    ]
    assert versioned.json()["evidence"][1]["versions"][1]["visible_roles"] == [
        "Prosecutor"
    ]

    stale = client.post(
        f"/meetings/{meeting_id}/materials/evidence/{evidence_id}/deactivate",
        json={"revision": 1},
    )
    deactivated = client.post(
        f"/meetings/{meeting_id}/materials/evidence/{evidence_id}/deactivate",
        json={"revision": 2},
    )
    reactivated = client.post(
        f"/meetings/{meeting_id}/materials/evidence/{evidence_id}/reactivate",
        json={"revision": 3},
    )

    assert stale.status_code == 409
    assert deactivated.json()["evidence"][1]["status"] == "inactive"
    assert reactivated.json()["evidence"][1]["status"] == "active"
    historical = client.get(
        f"/meetings/{meeting_id}/materials", params={"revision": 1}
    )
    assert historical.status_code == 200
    assert historical.json()["revision"] == 1
    assert historical.json()["evidence"][1]["active_version"] == 1
    assert historical.json()["evidence"][1]["versions"][-1]["visible_roles"] == [
        "Defense",
        "Judge",
    ]
    history = reactivated.json()["revision_history"]
    assert [entry["revision"] for entry in history] == [0, 1, 2, 3, 4]
    assert "content" not in json.dumps(history)
    assert metadata_path.read_bytes() == metadata_bytes


def test_case_notes_and_promoted_chair_message_are_versioned_without_event_rewrite(
    tmp_path: Path,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings", json={"title": "Case notes", "goal": "remember facts"}
    ).json()["meeting_id"]
    source = client.post(
        f"/meetings/{meeting_id}/messages",
        json={"content": "The parties agree the inspection happened on Monday."},
    ).json()
    events_path = tmp_path / "data" / "meetings" / meeting_id / "events.jsonl"
    source_bytes = events_path.read_bytes()

    promoted = client.post(
        f"/meetings/{meeting_id}/messages/{source['event_id']}/promote-to-note",
        json={
            "revision": 0,
            "title": "Agreed inspection date",
            "visible_roles": ["Blue", "Red", "Judge"],
        },
    )
    assert promoted.status_code == 200
    assert events_path.read_bytes() == source_bytes
    note = promoted.json()["notes"][0]
    assert note["versions"][0]["content"] == source["content"]
    assert note["versions"][0]["source_event_id"] == source["event_id"]

    updated = client.post(
        f"/meetings/{meeting_id}/materials/notes/{note['id']}/versions",
        json={
            "revision": 1,
            "title": "Agreed inspection",
            "content": "Inspection was Monday at 10:00.",
            "visible_roles": ["Judge"],
        },
    )
    assert updated.status_code == 200
    assert updated.json()["notes"][0]["active_version"] == 2
    assert updated.json()["notes"][0]["versions"][0]["source_event_id"] == source["event_id"]

    deactivated = client.post(
        f"/meetings/{meeting_id}/materials/notes/{note['id']}/deactivate",
        json={"revision": 2},
    )
    reactivated = client.post(
        f"/meetings/{meeting_id}/materials/notes/{note['id']}/reactivate",
        json={"revision": 3},
    )
    assert deactivated.json()["notes"][0]["status"] == "inactive"
    assert reactivated.json()["notes"][0]["status"] == "active"


def test_active_materials_reach_prompts_inactive_versions_do_not_and_restart_clears_gate(
    tmp_path: Path,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings",
        json={
            "title": "Prompt materials",
            "goal": "use current facts",
            "case_files": [
                {
                    "title": "Active exhibit",
                    "content": "ACTIVE_EVIDENCE",
                    "visible_roles": ["Blue"],
                },
                {
                    "title": "Inactive exhibit",
                    "content": "INACTIVE_EVIDENCE",
                    "visible_roles": ["Blue"],
                },
            ],
        },
    ).json()["meeting_id"]
    deactivated = client.post(
        f"/meetings/{meeting_id}/materials/evidence/case-file-2/deactivate",
        json={"revision": 0},
    )
    assert deactivated.status_code == 200
    note = client.post(
        f"/meetings/{meeting_id}/materials/notes",
        json={
            "revision": 1,
            "title": "Binding fact",
            "content": "PERSISTENT_CASE_NOTE",
            "visible_roles": ["Blue"],
        },
    )
    assert note.status_code == 200
    assert client.post(f"/meetings/{meeting_id}/start", json={}).status_code == 202
    completed = wait_for_activity(client, meeting_id, "completed")
    blue_prompt = completed["events"][0]["prompt_messages"][0]["content"]
    assert "ACTIVE_EVIDENCE" in blue_prompt
    assert "PERSISTENT_CASE_NOTE" in blue_prompt
    assert "INACTIVE_EVIDENCE" not in blue_prompt
    assert {event["materials_revision"] for event in completed["events"]} == {2}
    assert {
        reference["id"]
        for reference in completed["events"][0]["materials_refs"]
    } == {"case-file-1", "case-note-1"}

    changed = client.post(
        f"/meetings/{meeting_id}/materials/notes",
        json={
            "revision": 2,
            "title": "Late fact",
            "content": "LATE_CASE_NOTE",
            "visible_roles": ["Blue", "Red", "Judge"],
        },
    )
    assert changed.status_code == 200
    assert changed.json()["pending_impact"]["deliberation_epoch_id"] == "epoch-1"

    blocked = [
        client.post(f"/meetings/{meeting_id}/start", json={}),
        client.post(
            f"/meetings/{meeting_id}/roles/Blue/respond",
            json={"instruction": "answer despite changed evidence"},
        ),
        client.post(
            f"/meetings/{meeting_id}/sequences", json={"roles": ["Blue", "Red"]}
        ),
        client.post(f"/meetings/{meeting_id}/steps/missing/retry", json={}),
    ]
    assert {response.status_code for response in blocked} == {409}
    assert all("materials changed" in response.json()["detail"].lower() for response in blocked)

    material_bytes = (
        tmp_path / "data" / "meetings" / meeting_id / "case_files.json"
    ).read_bytes()
    restarted = client.post(
        f"/meetings/{meeting_id}/deliberations/restart",
        json={"scope": "all_deliberation", "reason": "acknowledge new evidence"},
    )
    assert restarted.status_code == 200
    assert client.get(f"/meetings/{meeting_id}/materials").json()["pending_impact"] is None
    assert (
        tmp_path / "data" / "meetings" / meeting_id / "case_files.json"
    ).read_bytes() == material_bytes
    raw = MeetingRepository(tmp_path / "data").read_events(meeting_id)
    assert raw[-1]["snapshot"]["materials_revision"] == 3
    assert client.post(f"/meetings/{meeting_id}/start", json={}).status_code == 202
    wait_for_activity(client, meeting_id, "completed")


def test_pending_material_impact_blocks_every_courtroom_ai_entrypoint(tmp_path: Path) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings",
        json={"title": "Court material gate", "goal": "block all", "mode_id": "courtroom"},
    ).json()["meeting_id"]
    MeetingRepository(tmp_path / "data").append_event(
        meeting_id,
        {
            "event_id": "existing-ai-output",
            "meeting_id": meeting_id,
            "step_id": "courtroom-draft-r1",
            "base_step_id": "courtroom-issue-draft",
            "role": "Judge",
            "attempt": 1,
            "status": "completed",
            "interaction_type": "courtroom-issue-draft",
        },
    )
    assert client.post(
        f"/meetings/{meeting_id}/materials/notes",
        json={
            "revision": 0,
            "title": "changed fact",
            "content": "new fact",
            "visible_roles": ["Judge"],
        },
    ).status_code == 200

    responses = [
        client.post(
            f"/meetings/{meeting_id}/courtroom/issues/draft", json={"revision": 0}
        ),
        client.post(f"/meetings/{meeting_id}/courtroom/issues/issue-1/arguments"),
        client.post(f"/meetings/{meeting_id}/courtroom/issues/issue-1/ruling"),
        client.post(f"/meetings/{meeting_id}/courtroom/final-verdict"),
        client.post(
            f"/meetings/{meeting_id}/roles/Judge/respond",
            json={"instruction": "judge now"},
        ),
        client.post(f"/meetings/{meeting_id}/steps/missing/retry", json={}),
    ]

    assert {response.status_code for response in responses} == {409}
    assert all("materials changed" in response.json()["detail"].lower() for response in responses)


def test_inactive_note_is_excluded_from_prompt_and_inactive_version_waits_until_reactivation(
    tmp_path: Path,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings", json={"title": "inactive notes", "goal": "ignore inactive"}
    ).json()["meeting_id"]
    created = client.post(
        f"/meetings/{meeting_id}/materials/notes",
        json={
            "revision": 0,
            "title": "temporary",
            "content": "INACTIVE_NOTE_CONTENT",
            "visible_roles": ["Blue"],
        },
    ).json()
    note_id = created["notes"][0]["id"]
    assert client.post(
        f"/meetings/{meeting_id}/materials/notes/{note_id}/deactivate",
        json={"revision": 1},
    ).status_code == 200
    assert client.post(f"/meetings/{meeting_id}/start", json={}).status_code == 202
    meeting = wait_for_activity(client, meeting_id, "completed")
    assert all(
        "INACTIVE_NOTE_CONTENT" not in event["prompt_messages"][0]["content"]
        for event in meeting["events"]
    )

    versioned = client.post(
        f"/meetings/{meeting_id}/materials/notes/{note_id}/versions",
        json={
            "revision": 2,
            "title": "still inactive",
            "content": "NEW_INACTIVE_NOTE",
            "visible_roles": ["Red"],
        },
    )
    assert versioned.status_code == 200
    assert versioned.json()["pending_impact"] is None
    reactivated = client.post(
        f"/meetings/{meeting_id}/materials/notes/{note_id}/reactivate",
        json={"revision": 3},
    )
    assert reactivated.status_code == 200
    assert reactivated.json()["pending_impact"] is not None


def test_carried_ruling_counts_as_active_ai_output_and_keeps_material_references(
    tmp_path: Path,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings",
        json={"title": "carried ruling", "goal": "preserve ruling", "mode_id": "courtroom"},
    ).json()["meeting_id"]
    repository = MeetingRepository(tmp_path / "data")
    repository.append_event(
        meeting_id,
        {
            "event_id": "ruling-issue-1",
            "meeting_id": meeting_id,
            "step_id": "ruling-issue-1",
            "role": "Judge",
            "attempt": 1,
            "status": "completed",
            "interaction_type": "courtroom-issue-phase",
            "issue_id": "issue-1",
            "issue_phase": "ruling",
            "materials_revision": 5,
            "materials_refs": [
                {
                    "kind": "evidence",
                    "id": "case-file-1",
                    "version": 2,
                    "status": "active",
                    "visible_roles": ["Judge"],
                }
            ],
        },
    )
    marker = DeliberationEpochs.restart_marker(
        meeting_id=meeting_id,
        events=repository.read_events(meeting_id),
        command=RestartCommand(
            scope="current_issue", reason="retry issue two", issue_id="issue-2"
        ),
    )
    repository.append_event(meeting_id, marker)

    carried = DeliberationEpochs.view(repository.read_events(meeting_id)).workflow_events[0]
    assert carried["materials_revision"] == 5
    assert carried["materials_refs"][0]["version"] == 2
    changed = client.post(
        f"/meetings/{meeting_id}/materials/notes",
        json={
            "revision": 0,
            "title": "new fact",
            "content": "changes carried judgment context",
            "visible_roles": ["Judge"],
        },
    )
    assert changed.status_code == 200
    assert changed.json()["pending_impact"]["deliberation_epoch_id"] == marker["epoch_id"]


def test_alternate_local_frontend_origin_can_call_api(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.options(
        "/models",
        headers={
            "Origin": "http://127.0.0.1:5174",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5174"


PROJECT_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"

RELAY_PROMPT_TEMPLATES = [
    "blue_propose",
    "red_critique",
    "blue_revise",
    "judge_decide",
    "courtroom_charge",
    "courtroom_defense",
    "courtroom_rebuttal",
    "courtroom_verdict",
    "courtroom_issue_draft",
    "courtroom_issue_charge",
    "courtroom_issue_defense",
    "courtroom_issue_rebuttal",
    "courtroom_issue_ruling",
    "courtroom_final_verdict",
    "debate_statement_pro",
    "debate_statement_con",
    "debate_cross_pro",
    "debate_cross_con",
    "debate_verdict",
    "brainstorm_member",
    "brainstorm_synthesis",
    "hat_white",
    "hat_red",
    "hat_black",
    "hat_yellow",
    "hat_green",
    "hat_blue_synthesis",
    "persona_member",
    "persona_synthesis",
    "directed_role_response",
]

DEBATE_PROMPT_TEMPLATES = {
    "debate_statement_pro",
    "debate_statement_con",
    "debate_cross_pro",
    "debate_cross_con",
    "debate_verdict",
}


def create_test_app(
    tmp_path: Path,
    *,
    models_yaml: str = """
models:
  - id: mock-fast
    adapter: mock
""".strip(),
    start_model_health_checks: bool = False,
):
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "models.yaml").write_text(models_yaml, encoding="utf-8")
    shutil.copy(PROJECT_CONFIG_DIR / "modes.yaml", config_dir / "modes.yaml")
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir(exist_ok=True)
    for template in RELAY_PROMPT_TEMPLATES:
        content = (
            f"{template} {{{{ role }}}} {{{{ goal }}}} "
            "{{ prior_transcript }} {{ case_files }} {{ required_json_schema }}"
        )
        if template in DEBATE_PROMPT_TEMPLATES:
            content += " {{ position_a }} {{ position_b }}"
        if template in {"brainstorm_member", "persona_member"}:
            content += " {{ instance_prompt }}"
        if template in {"brainstorm_synthesis", "hat_blue_synthesis", "persona_synthesis"}:
            content += " {{ fanout_outputs }}"
        if template == "directed_role_response":
            content += " {{ role_display_name }} {{ instruction }}"
        if template.startswith("courtroom_issue_"):
            content += " {{ current_issue }}"
        if template == "courtroom_final_verdict":
            content += " {{ issue_rulings }}"
        (prompt_dir / f"{template}.md").write_text(content, encoding="utf-8")
    return create_app(
        data_dir=tmp_path / "data",
        model_config_path=config_dir / "models.yaml",
        modes_config_path=config_dir / "modes.yaml",
        prompt_dir=prompt_dir,
        start_model_health_checks=start_model_health_checks,
    )


class FakeHTTPResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def read(self) -> bytes:
        return json.dumps(self.payload).encode("utf-8")

    def __enter__(self) -> FakeHTTPResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def wait_for_activity(
    client: TestClient,
    meeting_id: str,
    expected_status: str,
    timeout: float = 5,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        meeting = client.get(f"/meetings/{meeting_id}").json()
        if meeting["activity_status"] == expected_status:
            return meeting
        time.sleep(0.01)
    raise AssertionError(f"Meeting did not reach activity status: {expected_status}")


def wait_for_event_count(
    client: TestClient,
    meeting_id: str,
    expected_count: int,
    timeout: float = 5,
) -> list[dict[str, object]]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        events = client.get(f"/meetings/{meeting_id}").json()["events"]
        if len(events) >= expected_count:
            return events
        time.sleep(0.01)
    raise AssertionError(f"Meeting did not reach event count: {expected_count}")


def run_single_courtroom_issue(
    client: TestClient,
    meeting_id: str,
    title: str,
) -> None:
    assert client.put(
        f"/meetings/{meeting_id}/courtroom/issues",
        json={"revision": 0, "issues": [{"title": title}]},
    ).status_code == 200
    assert client.post(
        f"/meetings/{meeting_id}/courtroom/issues/confirm",
        json={"revision": 1},
    ).status_code == 200
    assert client.post(
        f"/meetings/{meeting_id}/courtroom/issues/issue-1/arguments"
    ).status_code == 202
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        meeting = client.get(f"/meetings/{meeting_id}").json()
        if meeting["courtroom"]["issues"][0]["status"] == "awaiting-ruling":
            break
        time.sleep(0.01)
    else:
        raise AssertionError("Courtroom issue arguments did not complete")
    assert client.post(
        f"/meetings/{meeting_id}/courtroom/issues/issue-1/ruling"
    ).status_code == 202
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        meeting = client.get(f"/meetings/{meeting_id}").json()
        if meeting["courtroom"]["issues"][0]["status"] == "ruled":
            return
        time.sleep(0.01)
    raise AssertionError("Courtroom issue ruling did not complete")


def wait_for_model_status(
    client: TestClient,
    model_id: str,
    expected_status: str,
    timeout: float = 2,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        models = client.get("/models").json()
        model = next(item for item in models if item["id"] == model_id)
        if model["status"] == expected_status:
            return model
        time.sleep(0.01)
    raise AssertionError(f"Model did not reach status: {expected_status}")
