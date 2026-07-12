from __future__ import annotations

import json
import sys
import threading
import time
import urllib.error
from pathlib import Path

from fastapi.testclient import TestClient

from ai_council.api import create_app
from ai_council.models.adapters import MockModelAdapter, ModelResponse


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
            "command": None,
            "timeout_seconds": 120.0,
            "status": "unknown",
            "credential": None,
        }
    ]


def test_model_config_crud_endpoints_update_models_yaml(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    created = client.put(
        "/models/qwen27",
        json={
            "adapter": "openai-compatible-http",
            "base_url": "http://192.168.50.80:8487/v1",
            "model": "bartowski/Qwen_Qwen3.6-27B-GGUF",
            "api_key_env": None,
            "supports_json_mode": True,
            "extra_body": {"chat_template_kwargs": {"enable_thinking": False}},
        },
    )

    assert created.status_code == 200
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

    assert response.status_code == 400
    assert "base_url and model" in response.json()["detail"]

    missing_adapter = client.put("/models/broken", json={})

    assert missing_adapter.status_code == 400


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


def create_test_app(
    tmp_path: Path,
    *,
    models_yaml: str = """
models:
  - id: mock-fast
    adapter: mock
""".strip(),
):
    config_dir = tmp_path / "config"
    config_dir.mkdir(exist_ok=True)
    (config_dir / "models.yaml").write_text(models_yaml, encoding="utf-8")
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir(exist_ok=True)
    for template in ["blue_propose", "red", "blue_revise", "judge"]:
        (prompt_dir / f"{template}.md").write_text(
            "{{ role }} {{ topic }} {{ prior_transcript }} {{ required_json_schema }}",
            encoding="utf-8",
        )
    return create_app(
        data_dir=tmp_path / "data",
        model_config_path=config_dir / "models.yaml",
        prompt_dir=prompt_dir,
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
