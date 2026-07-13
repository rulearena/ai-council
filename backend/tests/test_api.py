from __future__ import annotations

import json
import shutil
import sys
import threading
import time
import urllib.error
from pathlib import Path

from fastapi.testclient import TestClient

from ai_council.api import create_app
from ai_council.models.adapters import MockModelAdapter, ModelResponse

TEST_BLUE_PROPOSE_TEMPLATE_HASH = "81abba70bd2c176005a3fd28dd13ef9bda68f441de574976e8d7161e23fb5f9d"
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

    assert deleted.status_code == 204
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

    missing_adapter = client.put("/models/broken", json={})

    assert missing_adapter.status_code == 422


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


def test_meeting_create_list_get_start_and_transcript(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    created = client.post("/meetings", json={"topic": "先做後端？"}).json()

    assert created["topic"] == "先做後端？"
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
    transcript = client.get(f"/meetings/{meeting_id}/transcript.md")
    assert transcript.status_code == 200
    assert transcript.text.startswith("# 先做後端？\n")
    assert "## Blue - blue-propose" in transcript.text


def test_meeting_read_models_include_total_token_usage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def complete_with_usage(self, request):
        return ModelResponse(
            raw_output='{"summary":"OK","arguments":[],"risks":[],"recommendation":"Go"}',
            token_usage={"prompt_tokens": 2, "completion_tokens": 3, "total_tokens": 5},
        )

    monkeypatch.setattr(MockModelAdapter, "complete", complete_with_usage)
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"topic": "usage test"}).json()["meeting_id"]

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
    def complete_with_usage(self, request):
        return ModelResponse(
            raw_output='{"summary":"OK","arguments":[],"risks":[],"recommendation":"Go"}',
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
    meeting_id = client.post("/meetings", json={"topic": "cost test"}).json()["meeting_id"]

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

    def slow_complete(self, request):
        model_entered.set()
        release_model.wait(timeout=2)
        return ModelResponse(
            raw_output='{"summary":"OK","arguments":[],"risks":[],"recommendation":"Go"}'
        )

    monkeypatch.setattr(MockModelAdapter, "complete", slow_complete)
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"topic": "背景執行"}).json()["meeting_id"]

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
    finally:
        release_model.set()
        wait_for_activity(client, meeting_id, "completed")


def test_running_step_persists_and_clears_recovery_state(
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
    meeting_id = client.post("/meetings", json={"topic": "恢復狀態"}).json()["meeting_id"]
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
        assert state["output_schema_hash"] == TEST_OUTPUT_SCHEMA_HASH
    finally:
        release_model.set()

    wait_for_activity(client, meeting_id, "completed")

    assert not execution_state_path.exists()


def test_app_startup_marks_leftover_execution_state_failed(tmp_path: Path) -> None:
    first_app = create_test_app(tmp_path)
    first_client = TestClient(first_app)
    meeting_id = first_client.post("/meetings", json={"topic": "重啟恢復"}).json()["meeting_id"]
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
                "prompt_template_name": "blue_propose",
                "prompt_template_hash": TEST_BLUE_PROPOSE_TEMPLATE_HASH,
                "output_schema_hash": TEST_OUTPUT_SCHEMA_HASH,
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
    assert "interrupted" in meeting["events"][-1]["error"].lower()
    assert not execution_state_path.exists()


def test_start_rejects_missing_fixed_flow_model_assignments(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"topic": "缺少角色"}).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/start",
        json={"models": {"Blue": "mock-fast", "Red": "mock-fast"}},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Missing model assignments: Judge"
    assert client.get(f"/meetings/{meeting_id}").json()["activity_status"] == "idle"


def test_list_meetings_filters_by_transcript_content(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    matching_id = client.post("/meetings", json={"topic": "後端優先"}).json()["meeting_id"]
    other_id = client.post("/meetings", json={"topic": "前端優先"}).json()["meeting_id"]
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
    tagged_id = client.post("/meetings", json={"topic": "會議 A"}).json()["meeting_id"]
    other_id = client.post("/meetings", json={"topic": "會議 B"}).json()["meeting_id"]
    client.put(f"/meetings/{tagged_id}/tags", json={"tags": ["needs-review"]})

    response = client.get("/meetings", params={"q": "needs-review"})

    returned_ids = [meeting["meeting_id"] for meeting in response.json()]
    assert returned_ids == [tagged_id]
    assert other_id not in returned_ids


def test_list_meetings_without_query_returns_everything(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    client.post("/meetings", json={"topic": "會議 A"})
    client.post("/meetings", json={"topic": "會議 B"})

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
    meeting_id = client.post("/meetings", json={"topic": "失敗測試"}).json()["meeting_id"]

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
    meeting_id = client.post("/meetings", json={"topic": "取消測試"}).json()["meeting_id"]

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
    meeting_id = client.post("/meetings", json={"topic": "背景取消"}).json()["meeting_id"]
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
    events = client.get(f"/meetings/{meeting_id}").json()["events"]
    assert [event["status"] for event in events] == ["cancelled"]


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
    meeting_id = client.post("/meetings", json={"topic": "CLI 取消測試"}).json()["meeting_id"]

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
    meeting_id = client.post("/meetings", json={"topic": "結案測試"}).json()["meeting_id"]

    response = client.post(f"/meetings/{meeting_id}/close")

    assert response.status_code == 200
    events = client.get(f"/meetings/{meeting_id}").json()["events"]
    assert events[-1]["status"] == "closed"
    assert client.get(f"/meetings/{meeting_id}").json()["status"] == "closed"
    assert client.get("/meetings").json()[0]["status"] == "closed"
    transcript = client.get(f"/meetings/{meeting_id}/transcript.md").text
    assert "## System - meeting" in transcript
    assert "**Status:** closed" in transcript


def test_update_meeting_tags_replaces_tag_list(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"topic": "標籤測試"}).json()["meeting_id"]

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
    meeting_id = client.post("/meetings", json={"topic": "已結案"}).json()["meeting_id"]
    client.post(f"/meetings/{meeting_id}/close")

    response = client.put(f"/meetings/{meeting_id}/tags", json={"tags": ["archived"]})

    assert response.status_code == 200
    assert response.json()["tags"] == ["archived"]


def test_update_meeting_pinned_toggles_and_persists(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"topic": "釘選測試"}).json()["meeting_id"]
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
    meeting_id = client.post("/meetings", json={"topic": "已結案"}).json()["meeting_id"]
    client.post(f"/meetings/{meeting_id}/close")

    response = client.put(f"/meetings/{meeting_id}/pinned", json={"pinned": True})

    assert response.status_code == 200
    assert response.json()["pinned"] is True


def test_meeting_delete_removes_meeting_and_derived_transcript(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"topic": "刪除測試"}).json()["meeting_id"]
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
    meeting_id = client.post("/meetings", json={"topic": "已結案"}).json()["meeting_id"]
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
        json={
            "models": {
                "Blue": "mock-fast",
                "Red": "mock-fast",
                "Judge": "mock-fast",
            }
        },
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
    meeting_id = client.post("/meetings", json={"topic": "互動會議"}).json()["meeting_id"]

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
    assert "## Human - human-message" in transcript
    assert "我先補充限制：只能花一週做 MVP。" in transcript


def test_chair_can_correct_a_human_message(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"topic": "互動會議"}).json()["meeting_id"]
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
    meeting_id = client.post("/meetings", json={"topic": "互動會議"}).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/messages/does-not-exist/correct",
        json={"content": "修正內容"},
    )

    assert response.status_code == 404


def test_correct_human_message_rejects_non_human_message_event(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"topic": "互動會議"}).json()["meeting_id"]
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
    meeting_id = client.post("/meetings", json={"topic": "已結案"}).json()["meeting_id"]
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
    meeting_id = client.post("/meetings", json={"topic": "互動會議"}).json()["meeting_id"]
    client.post(
        f"/meetings/{meeting_id}/messages",
        json={"content": "請 Blue 先回答最小可行方案。"},
    )

    response = client.post(
        f"/meetings/{meeting_id}/roles/Blue/respond",
        json={
            "models": {
                "Blue": "mock-fast",
                "Red": "mock-fast",
                "Judge": "mock-fast",
            }
        },
    )

    assert response.status_code == 200
    events = client.get(f"/meetings/{meeting_id}").json()["events"]
    assert events[-1]["step_id"] == "directed-1-blue-response"
    assert events[-1]["role"] == "Blue"
    assert events[-1]["interaction_type"] == "directed-role-response"
    transcript = client.get(f"/meetings/{meeting_id}/transcript.md").text
    assert "## Blue - directed-1-blue-response" in transcript


def test_chair_can_request_role_sequence_response(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"topic": "互動會議"}).json()["meeting_id"]
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

    assert response.status_code == 200
    events = client.get(f"/meetings/{meeting_id}").json()["events"]
    ai_events = [event for event in events if event["role"] != "Human"]
    assert [event["step_id"] for event in ai_events] == [
        "sequence-1-red-response",
        "sequence-1-blue-response",
        "sequence-1-judge-response",
    ]
    assert {event["interaction_type"] for event in ai_events} == {"role-sequence-response"}
    assert [event["sequence_index"] for event in ai_events] == [1, 2, 3]
    transcript = client.get(f"/meetings/{meeting_id}/transcript.md").text
    assert "## Red - sequence-1-red-response" in transcript
    assert "## Judge - sequence-1-judge-response" in transcript


def test_chair_role_sequence_rejects_unknown_role(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"topic": "互動會議"}).json()["meeting_id"]

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
    meeting_id = client.post("/meetings", json={"topic": "互動會議"}).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/sequences",
        json={
            "roles": ["Blue", "Blue"],
            "models": {"Blue": "mock-fast"},
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Role sequence cannot contain duplicate roles"


def test_chair_role_response_requires_model_for_requested_role(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"topic": "互動會議"}).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/roles/Blue/respond",
        json={"models": {"Red": "mock-fast", "Judge": "mock-fast"}},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Missing model assignment for role: Blue"


def test_retry_step_returns_bad_request_when_step_is_not_failed(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"topic": "retry 邊界"}).json()["meeting_id"]

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
    assert red_blue["steps"] == [
        {"role": "Blue", "template": "blue_propose", "label": "藍軍提案"},
        {"role": "Red", "template": "red_critique", "label": "紅軍質詢"},
        {"role": "Blue", "template": "blue_revise", "label": "藍軍修訂"},
        {"role": "Judge", "template": "judge_decide", "label": "裁判裁決"},
    ]
    brainstorm = next(mode for mode in modes if mode["id"] == "brainstorm")
    assert brainstorm["available"] is False
    assert brainstorm["fanout"]["min_instances"] == 2


def test_create_meeting_defaults_to_red_blue(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.post("/meetings", json={"topic": "舊版建立會議"})

    assert response.status_code == 200
    created = response.json()
    assert created["mode_id"] == "red-blue"
    assert created["participants"] == [
        {
            "role_id": "Blue",
            "name": "藍軍",
            "color": "#4d8dff",
            "kind": "member",
            "portrait": "blue",
            "model_config_id": None,
            "display_name": "藍軍",
            "instance_prompt": None,
        },
        {
            "role_id": "Red",
            "name": "紅軍",
            "color": "#ff6b5e",
            "kind": "member",
            "portrait": "red",
            "model_config_id": None,
            "display_name": "紅軍",
            "instance_prompt": None,
        },
        {
            "role_id": "Judge",
            "name": "裁判",
            "color": "#e8b44c",
            "kind": "adjudicator",
            "portrait": "judge",
            "model_config_id": None,
            "display_name": "裁判",
            "instance_prompt": None,
        },
    ]


def test_create_meeting_with_courtroom_mode(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/meetings",
        json={"topic": "法庭審理案例", "mode_id": "courtroom"},
    )

    assert response.status_code == 200
    participants = response.json()["participants"]
    assert [p["role_id"] for p in participants] == ["Prosecutor", "Defense", "Judge"]


def test_create_meeting_rejects_unknown_mode(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.post("/meetings", json={"topic": "T", "mode_id": "does-not-exist"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown mode: does-not-exist"


def test_create_meeting_rejects_parallel_mode(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.post("/meetings", json={"topic": "T", "mode_id": "brainstorm"})

    assert response.status_code == 400
    assert response.json()["detail"] == "Mode is not yet supported: brainstorm"


def test_create_meeting_requires_debate_positions(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    missing_both = client.post("/meetings", json={"topic": "辯論", "mode_id": "debate"})
    assert missing_both.status_code == 400
    assert missing_both.json()["detail"] == "Missing required input: position_a"

    missing_one = client.post(
        "/meetings",
        json={
            "topic": "辯論",
            "mode_id": "debate",
            "inputs": {"position_a": "先做後端"},
        },
    )
    assert missing_one.status_code == 400
    assert missing_one.json()["detail"] == "Missing required input: position_b"

    ok = client.post(
        "/meetings",
        json={
            "topic": "辯論",
            "mode_id": "debate",
            "inputs": {"position_a": "先做後端", "position_b": "先做前端"},
        },
    )
    assert ok.status_code == 200
    assert ok.json()["inputs"] == {"position_a": "先做後端", "position_b": "先做前端"}


def test_create_meeting_rejects_unknown_input_keys(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.post("/meetings", json={"topic": "T", "inputs": {"x": "y"}})

    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown input for mode red-blue: x"


def test_create_meeting_rejects_participant_role_not_in_mode(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/meetings",
        json={
            "topic": "T",
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
            "topic": "T",
            "mode_id": "courtroom",
            "participants": [{"role_id": "Prosecutor", "model_config_id": "mock-fast"}],
        },
    ).json()

    fetched = client.get(f"/meetings/{created['meeting_id']}").json()
    prosecutor = next(p for p in fetched["participants"] if p["role_id"] == "Prosecutor")
    assert prosecutor["model_config_id"] == "mock-fast"


def test_create_meeting_rejects_unknown_participant_model(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.post(
        "/meetings",
        json={
            "topic": "T",
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
                "topic": "舊資料",
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


def test_start_courtroom_meeting_runs_courtroom_steps(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={"topic": "法庭審理", "mode_id": "courtroom"},
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

    assert response.status_code == 202
    meeting = wait_for_activity(client, meeting_id, "completed")
    completed_steps = [
        event["step_id"] for event in meeting["events"] if event["status"] == "completed"
    ]
    assert completed_steps == [
        "courtroom-charge",
        "courtroom-defense",
        "courtroom-rebuttal",
        "courtroom-verdict",
    ]


def test_start_rejects_missing_roles_for_mode(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={"topic": "法庭審理", "mode_id": "courtroom"},
    ).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/start",
        json={"models": {"Judge": "mock-fast"}},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Missing model assignments: Defense, Prosecutor"


def test_debate_inputs_reach_prompts(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={
            "topic": "辯論",
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


def test_respond_as_role_accepts_mode_roles(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={"topic": "法庭審理", "mode_id": "courtroom"},
    ).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/roles/Prosecutor/respond",
        json={
            "models": {
                "Prosecutor": "mock-fast",
                "Defense": "mock-fast",
                "Judge": "mock-fast",
            }
        },
    )
    assert response.status_code == 200
    events = client.get(f"/meetings/{meeting_id}").json()["events"]
    assert events[-1]["step_id"] == "directed-1-prosecutor-response"

    rejected = client.post(
        f"/meetings/{meeting_id}/roles/Blue/respond",
        json={"models": {"Blue": "mock-fast"}},
    )
    assert rejected.status_code == 400


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
    "debate_statement_pro",
    "debate_statement_con",
    "debate_cross_pro",
    "debate_cross_con",
    "debate_verdict",
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
            f"{template} {{{{ role }}}} {{{{ topic }}}} "
            "{{ prior_transcript }} {{ required_json_schema }}"
        )
        if template in DEBATE_PROMPT_TEMPLATES:
            content += " {{ position_a }} {{ position_b }}"
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
    timeout: float = 2,
) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        meeting = client.get(f"/meetings/{meeting_id}").json()
        if meeting["activity_status"] == expected_status:
            return meeting
        time.sleep(0.01)
    raise AssertionError(f"Meeting did not reach activity status: {expected_status}")


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
