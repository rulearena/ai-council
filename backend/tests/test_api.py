from __future__ import annotations

import json
import shutil
import sys
import threading
import time
import urllib.error
import urllib.parse
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_council.api import (
    MeetingJobManager,
    MeetingMetadataStore,
    ModelHealthCheckResult,
    ModelHealthCheckStore,
    create_app,
    live_meeting_snapshot,
)
from ai_council.models.adapters import AdapterError, MockModelAdapter, ModelRequest, ModelResponse
from ai_council.meetings.chatroom_context import estimate_tokens
from ai_council.models.config import ModelConfigRepository
from ai_council.meetings.repository import MeetingRepository
from ai_council.meetings.deliberation import DeliberationEpochs, RestartCommand
from ai_council.meetings.case_materials import CaseMaterials
from ai_council.meetings.modes import ModeDefinition

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


def test_meeting_settings_are_saved_atomically_with_scene_and_complete_model_roster(
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
        "/meetings", json={"title": "原名稱", "goal": "原目標"}
    ).json()

    response = client.put(
        f"/meetings/{created['meeting_id']}/settings",
        json={
            "expected_revision": 0,
            "title": "新名稱",
            "goal": "新目標",
            "case_type": None,
            "scene": "default-chamber",
            "participant_models": {
                "Blue": "mock-careful",
                "Red": "mock-fast",
                "Judge": "mock-careful",
            },
        },
    )

    assert response.status_code == 200
    saved = response.json()
    assert saved["settings_revision"] == 1
    assert (saved["title"], saved["goal"], saved["scene"]) == (
        "新名稱",
        "新目標",
        "default-chamber",
    )
    assert {
        participant["role_id"]: participant["model_config_id"]
        for participant in saved["participants"]
    } == {
        "Blue": "mock-careful",
        "Red": "mock-fast",
        "Judge": "mock-careful",
    }


def test_invalid_meeting_settings_leave_every_field_unchanged(tmp_path: Path) -> None:
    client = TestClient(create_test_app(tmp_path))
    created = client.post(
        "/meetings", json={"title": "原名稱", "goal": "原目標"}
    ).json()
    meeting_id = created["meeting_id"]

    rejected = client.put(
        f"/meetings/{meeting_id}/settings",
        json={
            "expected_revision": 0,
            "title": "不應保存",
            "goal": "不應保存",
            "case_type": None,
            "scene": "not-a-scene",
            "participant_models": {
                "Blue": "missing-model",
                "Red": "mock-fast",
                "Judge": "mock-fast",
            },
        },
    )

    assert rejected.status_code == 422
    unchanged = client.get(f"/meetings/{meeting_id}").json()
    assert unchanged["settings_revision"] == 0
    assert unchanged["title"] == "原名稱"
    assert unchanged["goal"] == "原目標"
    assert unchanged["scene"] == "meeting-room"
    assert {participant["model_config_id"] for participant in unchanged["participants"]} == {
        "mock-fast"
    }


def test_meeting_settings_reject_stale_revision_and_confirmed_courtroom_goal_or_type(
    tmp_path: Path,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings",
        json={
            "title": "土地案",
            "goal": "是否返還土地",
            "mode_id": "courtroom",
            "case_type": "civil",
        },
    ).json()["meeting_id"]
    client.put(
        f"/meetings/{meeting_id}/courtroom/issues",
        json={"revision": 0, "issues": [{"title": "占有權源"}]},
    )
    client.post(
        f"/meetings/{meeting_id}/courtroom/issues/confirm", json={"revision": 1}
    )
    roster = {"Prosecutor": "mock-fast", "Defense": "mock-fast", "Judge": "mock-fast"}

    locked = client.put(
        f"/meetings/{meeting_id}/settings",
        json={
            "expected_revision": 0,
            "title": "可改名稱",
            "goal": "改掉目標",
            "case_type": "criminal",
            "scene": "courtroom",
            "participant_models": roster,
        },
    )
    assert locked.status_code == 409

    saved = client.put(
        f"/meetings/{meeting_id}/settings",
        json={
            "expected_revision": 0,
            "title": "可改名稱",
            "goal": "是否返還土地",
            "case_type": "civil",
            "scene": "courtroom",
            "participant_models": roster,
        },
    )
    assert saved.status_code == 200
    stale = client.put(
        f"/meetings/{meeting_id}/settings",
        json={
            "expected_revision": 0,
            "title": "過期名稱",
            "goal": "是否返還土地",
            "case_type": "civil",
            "scene": "courtroom",
            "participant_models": roster,
        },
    )
    assert stale.status_code == 409
    assert client.get(f"/meetings/{meeting_id}").json()["title"] == "可改名稱"


def test_meeting_settings_allow_title_change_but_reject_all_changes_while_running(
    tmp_path: Path,
    monkeypatch,
) -> None:
    entered = threading.Event()
    release = threading.Event()
    original_complete = MockModelAdapter.complete

    def slow_complete(self, request):
        entered.set()
        release.wait(timeout=3)
        return original_complete(self, request)

    monkeypatch.setattr(MockModelAdapter, "complete", slow_complete)
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings", json={"title": "執行中的會議", "goal": "形成建議"}
    ).json()["meeting_id"]
    try:
        response = client.post(f"/meetings/{meeting_id}/start", json={})
        assert response.status_code == 202
        assert entered.wait(timeout=2)

        rejected = client.put(
            f"/meetings/{meeting_id}/settings",
            json={
                "expected_revision": 0,
                "title": "不應保存",
                "goal": "形成建議",
                "case_type": None,
                "scene": "meeting-room",
                "participant_models": {
                    "Blue": "mock-fast",
                    "Red": "mock-fast",
                    "Judge": "mock-fast",
                },
            },
        )

        assert rejected.status_code == 409
        unchanged = client.get(f"/meetings/{meeting_id}").json()
        assert unchanged["title"] == "執行中的會議"
        assert unchanged["settings_revision"] == 0
    finally:
        release.set()


def test_atomic_meeting_settings_keep_the_goal_change_audit_after_ai_output(
    tmp_path: Path,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings", json={"title": "原名稱", "goal": "原目標"}
    ).json()["meeting_id"]
    assert client.post(f"/meetings/{meeting_id}/start", json={}).status_code == 202
    wait_for_activity(client, meeting_id, "completed")

    response = client.put(
        f"/meetings/{meeting_id}/settings",
        json={
            "expected_revision": 0,
            "title": "新名稱",
            "goal": "新目標",
            "case_type": None,
            "scene": "meeting-room",
            "participant_models": {
                "Blue": "mock-fast",
                "Red": "mock-fast",
                "Judge": "mock-fast",
            },
        },
    )

    assert response.status_code == 200
    audit = [
        event
        for event in client.get(f"/meetings/{meeting_id}").json()["events"]
        if event.get("interaction_type") == "meeting-goal-changed"
    ]
    assert len(audit) == 1
    assert audit[0]["content"] == "主席修改會議目標\n舊目標：原目標\n新目標：新目標"


@pytest.mark.parametrize("legacy_route", ["details", "participant-models", "case-type"])
def test_legacy_setting_writes_invalidate_an_atomic_client_revision(
    tmp_path: Path, legacy_route: str
) -> None:
    client = TestClient(create_test_app(tmp_path))
    courtroom = legacy_route == "case-type"
    meeting_id = client.post(
        "/meetings",
        json={
            "title": "原名稱",
            "goal": "原目標",
            **(
                {"mode_id": "courtroom", "case_type": "civil"}
                if courtroom
                else {}
            ),
        },
    ).json()["meeting_id"]
    meeting = client.get(f"/meetings/{meeting_id}").json()
    models = {
        participant["role_id"]: "mock-fast"
        for participant in meeting["participants"]
    }
    if legacy_route == "details":
        changed = client.put(
            f"/meetings/{meeting_id}/details",
            json={"title": "另一個 client", "goal": "原目標"},
        )
    elif legacy_route == "participant-models":
        changed = client.put(
            f"/meetings/{meeting_id}/participant-models", json={"models": models}
        )
    else:
        changed = client.put(
            f"/meetings/{meeting_id}/courtroom/case-type",
            json={"case_type": "criminal"},
        )
    assert changed.status_code == 200
    assert changed.json()["settings_revision"] == 1

    stale = client.put(
        f"/meetings/{meeting_id}/settings",
        json={
            "expected_revision": 0,
            "title": "過期覆寫",
            "goal": "原目標",
            "case_type": "criminal" if courtroom else None,
            "scene": "courtroom" if courtroom else "meeting-room",
            "participant_models": models,
        },
    )
    assert stale.status_code == 409


def test_atomic_case_type_change_uses_a_new_epoch_and_archives_the_old_draft(
    tmp_path: Path,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings",
        json={
            "title": "類型切換",
            "goal": "判斷責任",
            "mode_id": "courtroom",
            "case_type": "civil",
        },
    ).json()["meeting_id"]
    client.post(f"/meetings/{meeting_id}/messages", json={"content": "舊輪討論"})

    changed = client.put(
        f"/meetings/{meeting_id}/settings",
        json={
            "expected_revision": 0,
            "title": "類型切換",
            "goal": "判斷責任",
            "case_type": "criminal",
            "scene": "courtroom",
            "participant_models": {
                "Prosecutor": "mock-fast",
                "Defense": "mock-fast",
                "Judge": "mock-fast",
            },
        },
    )

    assert changed.status_code == 200
    assert changed.json()["deliberation"]["active_epoch_number"] == 2
    epochs = client.get(f"/meetings/{meeting_id}/deliberations").json()["epochs"]
    assert epochs[0]["event_count"] == 1
    assert epochs[1]["reason"] == "case_type_changed"


def test_deliberation_history_projects_each_epochs_materials_revision_or_null(
    tmp_path: Path,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings", json={"title": "歷史案卷", "goal": "檢視當時證據"}
    ).json()["meeting_id"]
    repository = MeetingRepository(tmp_path / "data")
    repository.append_event(
        meeting_id,
        {
            "event_id": f"{meeting_id}:old",
            "meeting_id": meeting_id,
            "step_id": "old",
            "role": "Judge",
            "status": "completed",
            "materials_revision": 4,
        },
    )
    marker = DeliberationEpochs.restart_marker(
        meeting_id=meeting_id,
        events=repository.read_events(meeting_id),
        command=RestartCommand(scope="all_deliberation", reason="new evidence"),
        snapshot={"materials_revision": 5},
    )
    repository.append_event(meeting_id, marker)

    epochs = client.get(f"/meetings/{meeting_id}/deliberations").json()["epochs"]

    assert [epoch["materials_revision"] for epoch in epochs] == [4, 5]

    legacy_id = client.post(
        "/meetings", json={"title": "舊資料", "goal": "無 revision"}
    ).json()["meeting_id"]
    legacy = client.get(f"/meetings/{legacy_id}/deliberations").json()["epochs"]
    assert legacy[0]["materials_revision"] is None


def test_atomic_goal_change_event_failure_keeps_old_settings_and_is_retryable(
    tmp_path: Path, monkeypatch
) -> None:
    client = TestClient(create_test_app(tmp_path), raise_server_exceptions=False)
    meeting_id = client.post(
        "/meetings", json={"title": "原名稱", "goal": "原目標"}
    ).json()["meeting_id"]
    assert client.post(f"/meetings/{meeting_id}/start", json={}).status_code == 202
    wait_for_activity(client, meeting_id, "completed")
    original_append = MeetingRepository.append_event
    fail_audit = True

    def fail_goal_audit(self, target_meeting_id, event):
        if fail_audit and event.get("interaction_type") == "meeting-goal-changed":
            raise OSError("simulated audit failure")
        return original_append(self, target_meeting_id, event)

    monkeypatch.setattr(MeetingRepository, "append_event", fail_goal_audit)
    payload = {
        "expected_revision": 0,
        "title": "新名稱",
        "goal": "新目標",
        "case_type": None,
        "scene": "meeting-room",
        "participant_models": {
            "Blue": "mock-fast",
            "Red": "mock-fast",
            "Judge": "mock-fast",
        },
    }
    failed = client.put(f"/meetings/{meeting_id}/settings", json=payload)
    still_old = client.get(f"/meetings/{meeting_id}").json()
    blocked = client.put(
        f"/meetings/{meeting_id}/tags", json={"tags": ["must-not-pass"]}
    )
    fail_audit = False
    recovered = client.put(f"/meetings/{meeting_id}/settings", json=payload)

    assert failed.status_code == 409
    assert (still_old["title"], still_old["goal"], still_old["settings_revision"]) == (
        "原名稱",
        "原目標",
        0,
    )
    assert blocked.status_code == 409
    assert recovered.status_code == 200
    assert recovered.json()["settings_revision"] == 1


def test_atomic_settings_finalize_failure_is_reconciled_before_next_transition(
    tmp_path: Path, monkeypatch
) -> None:
    client = TestClient(create_test_app(tmp_path), raise_server_exceptions=False)
    meeting_id = client.post(
        "/meetings", json={"title": "原名稱", "goal": "原目標"}
    ).json()["meeting_id"]
    assert client.post(f"/meetings/{meeting_id}/start", json={}).status_code == 202
    wait_for_activity(client, meeting_id, "completed")
    original_update = MeetingMetadataStore.update
    fail_finalize = True

    def fail_settings_finalize(self, target_meeting_id, transform):
        nonlocal fail_finalize
        current = self.get(target_meeting_id)
        projected = transform(current)
        if (
            fail_finalize
            and current.get("pending_meeting_settings")
            and not projected.get("pending_meeting_settings")
        ):
            raise OSError("simulated settings finalize failure")
        return original_update(self, target_meeting_id, transform)

    monkeypatch.setattr(MeetingMetadataStore, "update", fail_settings_finalize)
    failed = client.put(
        f"/meetings/{meeting_id}/settings",
        json={
            "expected_revision": 0,
            "title": "新名稱",
            "goal": "新目標",
            "case_type": None,
            "scene": "meeting-room",
            "participant_models": {
                "Blue": "mock-fast",
                "Red": "mock-fast",
                "Judge": "mock-fast",
            },
        },
    )
    before_recovery = client.get(f"/meetings/{meeting_id}").json()
    fail_finalize = False
    reconciled = client.put(
        f"/meetings/{meeting_id}/tags", json={"tags": ["after-recovery"]}
    )

    assert failed.status_code == 409
    assert before_recovery["title"] == "原名稱"
    assert reconciled.status_code == 200
    assert reconciled.json()["title"] == "新名稱"
    assert reconciled.json()["settings_revision"] == 1
    audits = [
        event
        for event in client.get(f"/meetings/{meeting_id}").json()["events"]
        if event.get("interaction_type") == "meeting-goal-changed"
    ]
    assert len(audits) == 1


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
                "case_type": "civil",
                "role_display": "被告代理人",
                "phase_display": "答辯方補充",
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
    assert meeting["events"][-1]["case_type"] == "civil"
    assert meeting["events"][-1]["role_display"] == "被告代理人"
    assert meeting["events"][-1]["phase_display"] == "答辯方補充"
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


def test_list_meetings_uses_lightweight_material_summaries_without_projecting_content(
    tmp_path: Path, monkeypatch
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings",
        json={
            "title": "大型案卷",
            "goal": "只列摘要",
            "case_files": [{
                "title": "大型證據",
                "content": "CONTENT-MUST-NOT-BE-PROJECTED",
                "visible_roles": ["Judge"],
            }],
        },
    ).json()["meeting_id"]

    monkeypatch.setattr(
        CaseMaterials,
        "view",
        lambda *_args, **_kwargs: pytest.fail("list endpoint must not build full materials view"),
    )
    response = client.get("/meetings")

    assert response.status_code == 200
    listed = next(item for item in response.json() if item["meeting_id"] == meeting_id)
    assert listed["materials_revision"] == 0
    assert listed["case_materials_summary"] == {
        "revision": 0,
        "active_evidence_count": 1,
        "active_note_count": 0,
        "pending_impact": None,
    }
    assert "CONTENT-MUST-NOT-BE-PROJECTED" not in response.text


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


def test_live_snapshot_reloads_when_a_whole_job_finishes_during_the_event_read() -> None:
    meeting_id = "meeting-aba"
    completed_event = {
        "event_id": f"{meeting_id}:final",
        "meeting_id": meeting_id,
        "step_id": "courtroom-r1-final-verdict",
        "role": "Judge",
        "status": "completed",
        "interaction_type": "courtroom-final-verdict",
    }

    class ObservableJobManager(MeetingJobManager):
        def __init__(self) -> None:
            super().__init__()
            self.released = threading.Event()

        def _finish(self, finished_meeting_id: str, completed: Future[None]) -> None:
            super()._finish(finished_meeting_id, completed)
            self.released.set()

    class CompleteJobDuringRead:
        def __init__(self, manager: ObservableJobManager) -> None:
            self.manager = manager
            self.events: list[dict[str, object]] = []
            self.read_count = 0

        def read_events(self, requested_meeting_id: str) -> list[dict[str, object]]:
            assert requested_meeting_id == meeting_id
            self.read_count += 1
            snapshot = list(self.events)
            if self.read_count == 1:
                assert self.manager.start(meeting_id, lambda: self.events.append(completed_event))
                assert self.manager.released.wait(timeout=2)
            return snapshot

    manager = ObservableJobManager()
    repository = CompleteJobDuringRead(manager)
    mode = ModeDefinition(
        id="courtroom",
        name="Courtroom",
        category="relay",
        tagline="",
        when_to_use="",
        sop=[],
        default_scene="courtroom",
        inputs=[],
        roles=[],
    )

    events, status = live_meeting_snapshot(repository, manager, meeting_id, mode)  # type: ignore[arg-type]

    assert events == [completed_event]
    assert status == "completed"
    assert repository.read_count == 2


def test_live_snapshot_stays_running_when_another_job_finishes_during_the_reread() -> None:
    meeting_id = "meeting-back-to-back"
    completed_events = [
        {
            "event_id": f"{meeting_id}:completed-{index}",
            "meeting_id": meeting_id,
            "step_id": f"courtroom-step-{index}",
            "role": "Judge",
            "status": "completed",
            "interaction_type": "courtroom-final-verdict",
        }
        for index in (1, 2)
    ]

    class ObservableJobManager(MeetingJobManager):
        def __init__(self) -> None:
            super().__init__()
            self.released = [threading.Event(), threading.Event()]
            self.finish_count = 0

        def _finish(self, finished_meeting_id: str, completed: Future[None]) -> None:
            super()._finish(finished_meeting_id, completed)
            self.released[self.finish_count].set()
            self.finish_count += 1

    class CompleteOneJobPerRead:
        def __init__(self, manager: ObservableJobManager) -> None:
            self.manager = manager
            self.events: list[dict[str, object]] = []
            self.read_count = 0

        def read_events(self, requested_meeting_id: str) -> list[dict[str, object]]:
            assert requested_meeting_id == meeting_id
            snapshot = list(self.events)
            if self.read_count < 2:
                operation_index = self.read_count
                self.read_count += 1
                assert self.manager.start(
                    meeting_id,
                    lambda: self.events.append(completed_events[operation_index]),
                )
                assert self.manager.released[operation_index].wait(timeout=2)
            else:
                self.read_count += 1
            return snapshot

    manager = ObservableJobManager()
    repository = CompleteOneJobPerRead(manager)
    mode = ModeDefinition(
        id="courtroom",
        name="Courtroom",
        category="relay",
        tagline="",
        when_to_use="",
        sop=[],
        default_scene="courtroom",
        inputs=[],
        roles=[],
    )

    first_events, first_status = live_meeting_snapshot(  # type: ignore[arg-type]
        repository, manager, meeting_id, mode
    )

    assert first_events == [completed_events[0]]
    assert first_status == "running"
    assert repository.read_count == 2

    settled_events, settled_status = live_meeting_snapshot(  # type: ignore[arg-type]
        repository, manager, meeting_id, mode
    )
    assert settled_events == completed_events
    assert settled_status == "completed"


def test_job_lifecycle_revision_changes_only_for_an_accepted_start() -> None:
    entered = threading.Event()
    release = threading.Event()
    finished = threading.Event()

    class ObservableJobManager(MeetingJobManager):
        def _finish(self, meeting_id: str, completed: Future[None]) -> None:
            super()._finish(meeting_id, completed)
            finished.set()

    def operation() -> None:
        entered.set()
        assert release.wait(timeout=2)

    manager = ObservableJobManager()
    assert manager.lifecycle_state("meeting-revision") == (False, 0)
    assert manager.start("meeting-revision", operation)
    assert entered.wait(timeout=2)
    assert manager.lifecycle_state("meeting-revision") == (True, 1)

    assert not manager.start("meeting-revision", lambda: None)
    assert manager.lifecycle_state("meeting-revision") == (True, 1)

    release.set()
    assert finished.wait(timeout=2)
    assert manager.lifecycle_state("meeting-revision") == (False, 1)


def test_done_job_callback_cannot_remove_a_newer_job_or_its_revision() -> None:
    release_first = threading.Event()
    first_finish_entered = threading.Event()
    allow_first_finish = threading.Event()
    release_second = threading.Event()
    second_finished = threading.Event()

    class OrderedJobManager(MeetingJobManager):
        def __init__(self) -> None:
            super().__init__()
            self.finish_count = 0

        def _finish(self, meeting_id: str, completed: Future[None]) -> None:
            self.finish_count += 1
            if self.finish_count == 1:
                first_finish_entered.set()
                assert allow_first_finish.wait(timeout=2)
            super()._finish(meeting_id, completed)
            if self.finish_count == 2:
                second_finished.set()

    def first_operation() -> None:
        assert release_first.wait(timeout=2)

    def second_operation() -> None:
        assert release_second.wait(timeout=2)

    manager = OrderedJobManager()
    assert manager.start("meeting-replacement", first_operation)
    release_first.set()
    assert first_finish_entered.wait(timeout=2)
    assert manager.lifecycle_state("meeting-replacement") == (False, 1)

    assert manager.start("meeting-replacement", second_operation)
    assert manager.lifecycle_state("meeting-replacement") == (True, 2)
    allow_first_finish.set()
    assert manager.lifecycle_state("meeting-replacement") == (True, 2)

    release_second.set()
    assert second_finished.wait(timeout=2)
    assert manager.lifecycle_state("meeting-replacement") == (False, 2)


def test_exception_finish_preserves_the_accepted_job_revision(caplog) -> None:
    finished = threading.Event()

    class ObservableJobManager(MeetingJobManager):
        def _finish(self, meeting_id: str, completed: Future[None]) -> None:
            super()._finish(meeting_id, completed)
            finished.set()

    def fail() -> None:
        raise RuntimeError("expected test failure")

    manager = ObservableJobManager()
    with caplog.at_level("ERROR", logger="ai_council.api"):
        assert manager.start("meeting-exception-revision", fail)
        assert finished.wait(timeout=2)

    assert manager.lifecycle_state("meeting-exception-revision") == (False, 1)
    assert "Background meeting job failed unexpectedly" in caplog.text


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
        "chatroom",
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


def test_create_chatroom_meeting_without_goal(tmp_path: Path) -> None:
    client = TestClient(create_test_app(tmp_path))

    response = client.post(
        "/meetings",
        json={"title": "自由聊天", "mode_id": "chatroom"},
    )

    assert response.status_code == 200
    created = response.json()
    assert created["mode_id"] == "chatroom"
    assert created["goal"] is None
    metadata = json.loads(
        (
            tmp_path / "data" / "meetings" / created["meeting_id"] / "metadata.json"
        ).read_text(encoding="utf-8")
    )
    assert metadata["goal"] == ""


@pytest.mark.parametrize(
    ("participant_field", "expected_status", "expected_role_ids"),
    [
        pytest.param(
            None,
            200,
            ["host", "Advisor", "Critic", "Strategist", "Analyst"],
            id="participants-omitted-defaults-all-five",
        ),
        pytest.param(
            [],
            400,
            None,
            id="participants-explicit-empty-rejects-missing-host",
        ),
        pytest.param(
            [{"role_id": "Advisor", "model_config_id": "mock-fast"}],
            400,
            None,
            id="participants-explicit-nonempty-rejects-missing-host",
        ),
        pytest.param(
            [
                {"role_id": "host", "model_config_id": "mock-fast"},
                {"role_id": "host", "model_config_id": "mock-fast"},
            ],
            400,
            None,
            id="participants-explicit-duplicate-rejects",
        ),
        pytest.param(
            [
                {"role_id": "host", "model_config_id": "mock-fast"},
                {"role_id": "Advisor", "model_config_id": "mock-fast"},
            ],
            200,
            ["host", "Advisor"],
            id="participants-explicit-host-subset-is-frozen",
        ),
    ],
)
def test_create_chatroom_distinguishes_omitted_from_explicit_participant_rosters(
    tmp_path: Path,
    participant_field: list[dict[str, str]] | None,
    expected_status: int,
    expected_role_ids: list[str] | None,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    payload: dict[str, object] = {"title": "Roster contract", "mode_id": "chatroom"}
    if participant_field is not None:
        payload["participants"] = participant_field

    response = client.post("/meetings", json=payload)

    assert response.status_code == expected_status
    if expected_role_ids is not None:
        assert [
            participant["role_id"] for participant in response.json()["participants"]
        ] == expected_role_ids


def test_non_chatroom_explicit_empty_participants_preserve_default_roster(
    tmp_path: Path,
) -> None:
    client = TestClient(create_test_app(tmp_path))

    response = client.post(
        "/meetings",
        json={
            "title": "Relay explicit empty compatibility",
            "goal": "Preserve legacy defaults",
            "mode_id": "red-blue",
            "participants": [],
        },
    )

    assert response.status_code == 200
    assert [participant["role_id"] for participant in response.json()["participants"]] == [
        "Blue",
        "Red",
        "Judge",
    ]


def test_public_mode_and_meeting_projections_expose_only_persona_summaries(
    tmp_path: Path,
) -> None:
    client = TestClient(create_test_app(tmp_path))

    modes_response = client.get("/modes")
    assert modes_response.status_code == 200
    chatroom = next(mode for mode in modes_response.json() if mode["id"] == "chatroom")
    summaries_by_role = {
        role["id"]: role["persona_summary"] for role in chatroom["roles"]
    }
    assert set(summaries_by_role) == {
        "host",
        "Advisor",
        "Critic",
        "Strategist",
        "Analyst",
    }
    assert all(summary.strip() for summary in summaries_by_role.values())

    creation_response = client.post(
        "/meetings",
        json={
            "title": "Public Persona projection",
            "mode_id": "chatroom",
            "participants": [
                {"role_id": "host", "model_config_id": "mock-fast"},
                {"role_id": "Advisor", "model_config_id": "mock-fast"},
            ],
        },
    )
    assert creation_response.status_code == 200
    meeting_response = client.get(
        f"/meetings/{creation_response.json()['meeting_id']}"
    )
    assert meeting_response.status_code == 200

    for payload in (
        modes_response.json(),
        creation_response.json(),
        meeting_response.json(),
    ):
        nested_keys: set[str] = set()

        def collect_keys(value: object) -> None:
            if isinstance(value, dict):
                nested_keys.update(str(key) for key in value)
                for nested in value.values():
                    collect_keys(nested)
            elif isinstance(value, list):
                for nested in value:
                    collect_keys(nested)

        collect_keys(payload)
        assert "persona_prompt" not in nested_keys

    for projected in (creation_response.json(), meeting_response.json()):
        assert {
            participant["role_id"]: participant["persona_summary"]
            for participant in projected["participants"]
        } == {
            "host": summaries_by_role["host"],
            "Advisor": summaries_by_role["Advisor"],
        }


def test_chatroom_participant_models_update_without_goal(tmp_path: Path) -> None:
    """換模型不得因為聊天室沒有目標而失敗。

    這個端點內部沿用完整的設定驗證器，而該驗證器曾無條件要求 goal 非空，
    使得所有聊天室會議換模型一律 500（未處理例外，回應還缺 CORS 標頭，
    瀏覽器只會顯示 "Failed to fetch"）。
    """
    client = TestClient(
        create_test_app(
            tmp_path,
            models_yaml=(
                "models:\n"
                "  - id: mock-fast\n"
                "    adapter: mock\n"
                "  - id: mock-alt\n"
                "    adapter: mock\n"
            ),
        )
    )
    created = client.post(
        "/meetings",
        json={"title": "自由聊天", "mode_id": "chatroom"},
    ).json()
    meeting_id = created["meeting_id"]
    role_ids = [participant["role_id"] for participant in created["participants"]]

    response = client.put(
        f"/meetings/{meeting_id}/participant-models",
        json={"models": {role_id: "mock-alt" for role_id in role_ids}},
    )

    assert response.status_code == 200, response.text
    projected = client.get(f"/meetings/{meeting_id}").json()
    assert {p["role_id"]: p["model_config_id"] for p in projected["participants"]} == {
        role_id: "mock-alt" for role_id in role_ids
    }
    assert projected["goal"] is None


def test_chatroom_model_update_apis_enforce_frozen_active_roster_without_mutation(
    tmp_path: Path,
) -> None:
    client = TestClient(
        create_test_app(
            tmp_path,
            models_yaml=(
                "models:\n"
                "  - id: mock-fast\n"
                "    adapter: mock\n"
                "  - id: mock-alt\n"
                "    adapter: mock\n"
            ),
        )
    )
    created = client.post(
        "/meetings",
        json={
            "title": "Frozen model roster",
            "mode_id": "chatroom",
            "participants": [
                {"role_id": "host", "model_config_id": "mock-fast"},
                {"role_id": "Advisor", "model_config_id": "mock-fast"},
            ],
        },
    ).json()
    meeting_id = created["meeting_id"]
    before = client.get(f"/meetings/{meeting_id}").json()
    metadata_path = tmp_path / "data" / "meetings" / meeting_id / "metadata.json"
    metadata_before_rejections = metadata_path.read_bytes()

    def assert_rejection_did_not_mutate_roster() -> None:
        assert metadata_path.read_bytes() == metadata_before_rejections
        projected = client.get(f"/meetings/{meeting_id}").json()
        assert projected["settings_revision"] == before["settings_revision"]
        assert projected["title"] == before["title"]
        assert [
            participant["role_id"] for participant in projected["participants"]
        ] == ["host", "Advisor"]

    rejected_assignment = client.put(
        f"/meetings/{meeting_id}/participant-models",
        json={
            "models": {
                "host": "mock-fast",
                "Advisor": "mock-fast",
                "Strategist": "mock-alt",
            }
        },
    )
    assert rejected_assignment.status_code == 400
    assert "unknown roles: Strategist" in rejected_assignment.json()["detail"]
    assert_rejection_did_not_mutate_roster()

    rejected_settings = client.put(
        f"/meetings/{meeting_id}/settings",
        json={
            "expected_revision": before["settings_revision"],
            "title": "Must not persist",
            "goal": "",
            "case_type": None,
            "scene": before["scene"],
            "participant_models": {
                "host": "mock-fast",
                "Advisor": "mock-fast",
                "Strategist": "mock-alt",
            },
        },
    )
    assert rejected_settings.status_code == 400
    assert "unknown roles: Strategist" in rejected_settings.json()["detail"]
    assert_rejection_did_not_mutate_roster()

    accepted_assignment = client.put(
        f"/meetings/{meeting_id}/participant-models",
        json={"models": {"host": "mock-alt", "Advisor": "mock-alt"}},
    )
    assert accepted_assignment.status_code == 200
    after_assignment = client.get(f"/meetings/{meeting_id}").json()
    assert {
        participant["role_id"]: participant["model_config_id"]
        for participant in after_assignment["participants"]
    } == {"host": "mock-alt", "Advisor": "mock-alt"}

    accepted_settings = client.put(
        f"/meetings/{meeting_id}/settings",
        json={
            "expected_revision": after_assignment["settings_revision"],
            "title": "Accepted active roster settings",
            "goal": "",
            "case_type": None,
            "scene": after_assignment["scene"],
            "participant_models": {
                "host": "mock-fast",
                "Advisor": "mock-alt",
            },
        },
    )
    assert accepted_settings.status_code == 200
    assert accepted_settings.json()["title"] == "Accepted active roster settings"
    assert {
        participant["role_id"]: participant["model_config_id"]
        for participant in accepted_settings.json()["participants"]
    } == {"host": "mock-fast", "Advisor": "mock-alt"}


def test_chatroom_settings_update_keeps_goal_optional(tmp_path: Path) -> None:
    """聊天室存設定（改標題／場景）不得被空目標擋下。"""
    client = TestClient(create_test_app(tmp_path))
    created = client.post(
        "/meetings",
        json={"title": "自由聊天", "mode_id": "chatroom"},
    ).json()
    meeting_id = created["meeting_id"]
    role_ids = [participant["role_id"] for participant in created["participants"]]

    response = client.put(
        f"/meetings/{meeting_id}/settings",
        json={
            "expected_revision": created["settings_revision"],
            "title": "改過的聊天室名稱",
            "goal": "",
            "case_type": None,
            "scene": "meeting-room",
            "participant_models": {role_id: "mock-fast" for role_id in role_ids},
        },
    )

    assert response.status_code == 200, response.text
    projected = client.get(f"/meetings/{meeting_id}").json()
    assert projected["title"] == "改過的聊天室名稱"
    assert projected["goal"] is None


def test_relay_settings_update_still_requires_goal(tmp_path: Path) -> None:
    """非聊天室模式仍必須有目標——放寬只適用於聊天室。"""
    client = TestClient(create_test_app(tmp_path))
    created = client.post(
        "/meetings",
        json={"title": "紅藍對抗", "goal": "評估方案", "mode_id": "red-blue"},
    ).json()
    meeting_id = created["meeting_id"]
    role_ids = [participant["role_id"] for participant in created["participants"]]

    response = client.put(
        f"/meetings/{meeting_id}/settings",
        json={
            "expected_revision": created["settings_revision"],
            "title": "紅藍對抗",
            "goal": "   ",
            "case_type": None,
            "scene": "meeting-room",
            "participant_models": {role_id: "mock-fast" for role_id in role_ids},
        },
    )

    assert response.status_code == 422, response.text


def test_create_chatroom_meeting_with_goal(tmp_path: Path) -> None:
    client = TestClient(create_test_app(tmp_path))

    response = client.post(
        "/meetings",
        json={"title": "自由聊天", "goal": "討論產品方向", "mode_id": "chatroom"},
    )

    assert response.status_code == 200
    created = response.json()
    assert created["mode_id"] == "chatroom"
    assert created["goal"] == "討論產品方向"
    metadata = json.loads(
        (
            tmp_path / "data" / "meetings" / created["meeting_id"] / "metadata.json"
        ).read_text(encoding="utf-8")
    )
    assert metadata["goal"] == "討論產品方向"


def test_create_chatroom_empty_title_rejected(tmp_path: Path) -> None:
    client = TestClient(create_test_app(tmp_path))

    response = client.post(
        "/meetings",
        json={"title": "   ", "mode_id": "chatroom"},
    )

    assert response.status_code == 422


def test_create_relay_meeting_without_goal_still_422(tmp_path: Path) -> None:
    client = TestClient(create_test_app(tmp_path))

    response = client.post(
        "/meetings",
        json={"title": "土地糾紛案", "mode_id": "red-blue"},
    )

    assert response.status_code == 422


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
        json={"title": "法庭審理案例", "goal": "法庭審理案例", "mode_id": "courtroom", "case_type": "civil"},
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
                "case_type": "civil",
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
                "case_type": "civil",
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
    assert listed["case_files"] == []
    assert listed["case_materials_summary"]["active_evidence_count"] == 2
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
                "case_type": "civil",
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
                "case_type": "civil",
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
                "case_type": "civil",
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
                "case_type": "civil",
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
        json={"title": "法庭審理", "goal": "法庭審理", "mode_id": "courtroom", "case_type": "civil"},
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
        json={"title": "法庭審理", "goal": "法庭審理", "mode_id": "courtroom", "case_type": "civil"},
    ).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/start",
        json={"models": {"Judge": "mock-fast"}},
    )

    assert response.status_code == 409
    assert client.get(f"/meetings/{meeting_id}").json()["events"] == []


def test_courtroom_get_does_not_report_settled_from_an_incomplete_event_snapshot(
    tmp_path: Path,
    monkeypatch,
) -> None:
    first_phase_written = threading.Event()
    release_remaining_phases = threading.Event()
    job_released = threading.Event()
    original_complete = MockModelAdapter.complete
    original_append = MeetingRepository._append_event_unlocked
    original_read = MeetingRepository.read_events
    original_finish = MeetingJobManager._finish
    model_call_count = 0

    def controlled_complete(self: MockModelAdapter, request: ModelRequest) -> ModelResponse:
        nonlocal model_call_count
        model_call_count += 1
        if model_call_count > 1:
            assert release_remaining_phases.wait(timeout=2)
        return original_complete(self, request)

    def tracked_append(
        self: MeetingRepository,
        meeting_id: str,
        event: dict[str, object],
    ) -> None:
        original_append(self, meeting_id, event)
        if event.get("issue_phase") == "charge":
            first_phase_written.set()

    def release_after_snapshot(
        self: MeetingRepository,
        meeting_id: str,
    ) -> list[dict[str, object]]:
        events = original_read(self, meeting_id)
        if (
            first_phase_written.is_set()
            and not release_remaining_phases.is_set()
            and not threading.current_thread().name.startswith("ai-council")
        ):
            release_remaining_phases.set()
            assert job_released.wait(timeout=2)
        return events

    def track_job_release(
        self: MeetingJobManager,
        meeting_id: str,
        completed: Future[None],
    ) -> None:
        original_finish(self, meeting_id, completed)
        job_released.set()

    monkeypatch.setattr(MockModelAdapter, "complete", controlled_complete)
    monkeypatch.setattr(MeetingRepository, "_append_event_unlocked", tracked_append)
    monkeypatch.setattr(MeetingRepository, "read_events", release_after_snapshot)
    monkeypatch.setattr(MeetingJobManager, "_finish", track_job_release)

    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings",
        json={
            "title": "Deterministic settlement",
            "goal": "Project the next action",
            "mode_id": "courtroom",
            "case_type": "civil",
        },
    ).json()["meeting_id"]
    assert client.put(
        f"/meetings/{meeting_id}/courtroom/issues",
        json={"revision": 0, "issues": [{"title": "責任是否成立"}]},
    ).status_code == 200
    assert client.post(
        f"/meetings/{meeting_id}/courtroom/issues/confirm",
        json={"revision": 1},
    ).status_code == 200
    assert client.post(
        f"/meetings/{meeting_id}/courtroom/issues/issue-1/arguments"
    ).status_code == 202
    assert first_phase_written.wait(timeout=2)

    projected = client.get(f"/meetings/{meeting_id}").json()

    assert projected["activity_status"] == "completed"
    assert projected["courtroom"]["issues"][0]["status"] == "awaiting-ruling"
    assert projected["courtroom"]["available_actions"] == [
        "submit-ruling",
        "add-note",
        "directed-response",
    ]


def test_courtroom_websocket_does_not_publish_completed_with_partial_arguments(
    tmp_path: Path,
    monkeypatch,
) -> None:
    first_phase_written = threading.Event()
    release_remaining_phases = threading.Event()
    job_released = threading.Event()
    original_complete = MockModelAdapter.complete
    original_append = MeetingRepository._append_event_unlocked
    original_read = MeetingRepository.read_events
    original_finish = MeetingJobManager._finish
    model_call_count = 0

    def controlled_complete(self: MockModelAdapter, request: ModelRequest) -> ModelResponse:
        nonlocal model_call_count
        model_call_count += 1
        if model_call_count > 1:
            assert release_remaining_phases.wait(timeout=2)
        return original_complete(self, request)

    def tracked_append(
        self: MeetingRepository,
        meeting_id: str,
        event: dict[str, object],
    ) -> None:
        original_append(self, meeting_id, event)
        if event.get("issue_phase") == "charge":
            first_phase_written.set()

    def release_after_websocket_snapshot(
        self: MeetingRepository,
        meeting_id: str,
    ) -> list[dict[str, object]]:
        events = original_read(self, meeting_id)
        if (
            first_phase_written.is_set()
            and not release_remaining_phases.is_set()
            and not threading.current_thread().name.startswith("ai-council")
        ):
            release_remaining_phases.set()
            assert job_released.wait(timeout=2)
        return events

    def track_job_release(
        self: MeetingJobManager,
        meeting_id: str,
        completed: Future[None],
    ) -> None:
        original_finish(self, meeting_id, completed)
        job_released.set()

    monkeypatch.setattr(MockModelAdapter, "complete", controlled_complete)
    monkeypatch.setattr(MeetingRepository, "_append_event_unlocked", tracked_append)
    monkeypatch.setattr(MeetingRepository, "read_events", release_after_websocket_snapshot)
    monkeypatch.setattr(MeetingJobManager, "_finish", track_job_release)

    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings",
        json={
            "title": "WebSocket settlement",
            "goal": "Project all argument phases",
            "mode_id": "courtroom",
            "case_type": "civil",
        },
    ).json()["meeting_id"]
    assert client.put(
        f"/meetings/{meeting_id}/courtroom/issues",
        json={"revision": 0, "issues": [{"title": "責任是否成立"}]},
    ).status_code == 200
    assert client.post(
        f"/meetings/{meeting_id}/courtroom/issues/confirm",
        json={"revision": 1},
    ).status_code == 200

    with client.websocket_connect(f"/meetings/{meeting_id}/events") as websocket:
        assert websocket.receive_json()["activity_status"] == "idle"
        assert client.post(
            f"/meetings/{meeting_id}/courtroom/issues/issue-1/arguments"
        ).status_code == 202
        streamed_events: list[dict[str, object]] = []
        while True:
            update = websocket.receive_json()
            streamed_events.extend(update["events"])
            if update["activity_status"] == "completed":
                break

    assert [
        event.get("issue_phase")
        for event in streamed_events
        if event.get("status") == "completed"
    ] == ["charge", "defense", "rebuttal"]


def test_courtroom_each_job_release_projects_its_next_public_action(tmp_path: Path) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings",
        json={
            "title": "Every courtroom settlement",
            "goal": "Reach the final verdict",
            "mode_id": "courtroom",
            "case_type": "civil",
        },
    ).json()["meeting_id"]
    assert client.put(
        f"/meetings/{meeting_id}/courtroom/issues",
        json={"revision": 0, "issues": [{"title": "責任是否成立"}]},
    ).status_code == 200
    assert client.post(
        f"/meetings/{meeting_id}/courtroom/issues/confirm",
        json={"revision": 1},
    ).status_code == 200

    def run_and_wait(path: str) -> dict[str, object]:
        with client.websocket_connect(f"/meetings/{meeting_id}/events") as websocket:
            websocket.receive_json()
            assert client.post(path).status_code == 202
            update = websocket.receive_json()
            while update["activity_status"] != "completed":
                update = websocket.receive_json()
        return client.get(f"/meetings/{meeting_id}").json()

    after_arguments = run_and_wait(
        f"/meetings/{meeting_id}/courtroom/issues/issue-1/arguments"
    )
    assert after_arguments["courtroom"]["issues"][0]["status"] == "awaiting-ruling"
    assert after_arguments["courtroom"]["available_actions"] == [
        "submit-ruling",
        "add-note",
        "directed-response",
    ]

    after_ruling = run_and_wait(
        f"/meetings/{meeting_id}/courtroom/issues/issue-1/ruling"
    )
    assert after_ruling["courtroom"]["issues"][0]["status"] == "ruled"
    assert after_ruling["courtroom"]["final_status"] == "ready"
    assert after_ruling["courtroom"]["available_actions"] == ["final-verdict"]

    after_final = run_and_wait(f"/meetings/{meeting_id}/courtroom/final-verdict")
    assert after_final["courtroom"]["final_status"] == "completed"
    assert after_final["courtroom"]["available_actions"] == []
    final_event = next(
        event
        for event in reversed(after_final["events"])
        if event.get("interaction_type") == "courtroom-final-verdict"
    )
    assert final_event["output_schema_id"] == "courtroom-civil-final/v1"
    assert final_event["parsed_output"]["summary"]


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
                "case_type": "civil",
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


def test_api_projects_legacy_case_files_to_structured_evidence_for_final_and_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_complete = MockModelAdapter.complete
    final_reference = "[證物二]"

    def controlled_complete(
        self: MockModelAdapter, request: ModelRequest
    ) -> ModelResponse:
        if request.output_schema_id != "courtroom-civil-final/v1":
            return original_complete(self, request)
        return ModelResponse(raw_output=json.dumps({
            "summary": "部分勝訴",
            "claims": [{
                "claim": "損害賠償新臺幣十萬元",
                "outcome": "upheld",
                "reasoning": "依引用證物認定新臺幣十萬元",
                "evidence_refs": [final_reference],
                "relief": {
                    "obligation": "給付新臺幣十萬元",
                    "monetary_amount": "新臺幣十萬元",
                    "calculation_basis": "依引用證物所載金額計算",
                },
            }],
            "unresolved_questions": [],
        }, ensure_ascii=False))

    monkeypatch.setattr(MockModelAdapter, "complete", controlled_complete)
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings",
        json={
            "title": "結構化證物金額歸屬",
            "goal": "判斷損害賠償",
            "mode_id": "courtroom",
            "case_type": "civil",
            "case_files": [
                {
                    "title": "收據",
                    "content": "正文提到[證物二]後有新臺幣十萬元",
                    "visible_roles": ["Judge"],
                },
                {
                    "title": "契約",
                    "content": "本證物沒有記載金額",
                    "visible_roles": ["Judge"],
                },
            ],
        },
    ).json()["meeting_id"]
    assert isinstance(
        MeetingRepository(tmp_path / "data").read_case_materials_raw(meeting_id),
        list,
    )
    run_single_courtroom_issue(client, meeting_id, "損害金額")

    assert client.post(
        f"/meetings/{meeting_id}/courtroom/final-verdict"
    ).status_code == 202
    failed = wait_for_activity(client, meeting_id, "failed")
    failed_event = failed["events"][-1]
    assert failed_event["failure_kind"] == "parse_error"
    assert failed_event["raw_output"]

    final_reference = "[證物一]"
    assert client.post(
        f"/meetings/{meeting_id}/steps/{failed_event['step_id']}/retry",
        json={},
    ).status_code == 202
    completed = wait_for_activity(client, meeting_id, "completed")
    final_event = completed["events"][-1]
    assert final_event["status"] == "completed"
    assert final_event["materials_refs"] == [
        {
            "kind": "evidence",
            "id": completed["case_files"][0]["id"],
            "version": 1,
            "status": "active",
            "visible_roles": ["Judge"],
            "evidence_index": 1,
            "citation_anchor": "[證物一]",
        },
        {
            "kind": "evidence",
            "id": completed["case_files"][1]["id"],
            "version": 1,
            "status": "active",
            "visible_roles": ["Judge"],
            "evidence_index": 2,
            "citation_anchor": "[證物二]",
        },
    ]
    assert "__case_evidence_by_role" not in json.dumps(
        completed["events"], ensure_ascii=False
    )


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
                "case_type": "civil",
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
    assert set(completed_steps[:-1]) == {
        "fanout-1-member-1",
        "fanout-1-member-2",
    }
    assert completed_steps[-1] == "synthesis-1"


def test_parallel_partial_completion_is_live_over_http_and_websocket(
    tmp_path: Path,
    monkeypatch,
) -> None:
    member_started = {model_id: threading.Event() for model_id in ("member-1", "member-2")}
    release_member = {model_id: threading.Event() for model_id in ("member-1", "member-2")}
    synthesis_started = threading.Event()
    original_complete = MockModelAdapter.complete

    def complete_in_controlled_order(
        self: MockModelAdapter,
        request: ModelRequest,
    ) -> ModelResponse:
        model_id = request.model_config.id.removeprefix("mock-")
        if model_id == "moderator":
            synthesis_started.set()
            return original_complete(self, request)
        member_started[model_id].set()
        assert release_member[model_id].wait(timeout=10)
        return original_complete(self, request)

    monkeypatch.setattr(MockModelAdapter, "complete", complete_in_controlled_order)
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
""".strip(),
    )
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={
            "title": "平行即時顯示",
            "goal": "依完成順序顯示",
            "mode_id": "brainstorm",
            "participants": [
                {"role_id": "Member-1", "model_config_id": "mock-member-1"},
                {"role_id": "Member-2", "model_config_id": "mock-member-2"},
                {"role_id": "Moderator", "model_config_id": "mock-moderator"},
            ],
        },
    ).json()["meeting_id"]

    try:
        with client.websocket_connect(f"/meetings/{meeting_id}/events") as websocket:
            assert websocket.receive_json()["activity_status"] == "idle"
            assert client.post(f"/meetings/{meeting_id}/start", json={}).status_code == 202
            for started in member_started.values():
                assert started.wait(timeout=3)

            running = websocket.receive_json()
            assert running["activity_status"] == "running"
            release_member["member-2"].set()

            while True:
                partial = websocket.receive_json()
                if partial["events"]:
                    break

            assert partial["activity_status"] == "running"
            assert [event["role"] for event in partial["events"]] == ["Member-2"]
            http_snapshot = client.get(f"/meetings/{meeting_id}").json()
            assert http_snapshot["activity_status"] == "running"
            assert [event["role"] for event in http_snapshot["events"]] == ["Member-2"]
            assert synthesis_started.is_set() is False
    finally:
        for release in release_member.values():
            release.set()

    completed = wait_for_activity(client, meeting_id, "completed")
    assert [event["role"] for event in completed["events"]] == [
        "Member-2",
        "Member-1",
        "Moderator",
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
    assert {event["step_id"] for event in meeting["events"]} == {
        "fanout-1-member-1",
        "fanout-1-member-2",
    }
    assert any(event["status"] == "failed" for event in meeting["events"])

    failing_model_ids.clear()
    retry = client.post(
        f"/meetings/{meeting_id}/steps/fanout-1-member-2/retry",
        json={"models": request_models},
    )
    assert retry.status_code == 202
    meeting = wait_for_activity(client, meeting_id, "completed")
    assert {event["step_id"] for event in meeting["events"][:2]} == {
        "fanout-1-member-1",
        "fanout-1-member-2",
    }
    assert [event["step_id"] for event in meeting["events"][2:]] == [
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
        json={"title": "法庭審理", "goal": "法庭審理", "mode_id": "courtroom", "case_type": "civil"},
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
        f"/meetings/{meeting_id}/roles/Defense/respond",
        json={"instruction": "請補充目前答辯"},
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
    assert events[-1]["step_id"] == "directed-1-defense-response"

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
        json={"title": "法院重審", "goal": "逐點判斷", "mode_id": "courtroom", "case_type": "civil"},
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
        json={"title": "Pending rebuild", "goal": "rebuild", "mode_id": "courtroom", "case_type": "civil"},
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


def test_case_type_change_marker_failure_blocks_mutations_and_retry_keeps_full_snapshot(
    tmp_path: Path, monkeypatch
) -> None:
    client = TestClient(create_test_app(tmp_path), raise_server_exceptions=False)
    meeting_id = client.post(
        "/meetings",
        json={"title": "案件類型切換", "goal": "中立整理", "mode_id": "courtroom", "case_type": "civil"},
    ).json()["meeting_id"]
    assert client.put(
        f"/meetings/{meeting_id}/courtroom/issues",
        json={"revision": 0, "issues": [{"title": "舊爭點草稿"}]},
    ).status_code == 200
    assert client.post(
        f"/meetings/{meeting_id}/messages", json={"content": "主席舊輪指示"}
    ).status_code == 200
    original_append = MeetingRepository.append_event
    fail_marker = True

    def fail_epoch_marker(self, target_meeting_id, event):
        if fail_marker and event.get("interaction_type") == "deliberation-epoch-start":
            raise OSError("simulated case-type marker failure")
        return original_append(self, target_meeting_id, event)

    monkeypatch.setattr(MeetingRepository, "append_event", fail_epoch_marker)
    failed = client.put(
        f"/meetings/{meeting_id}/courtroom/case-type", json={"case_type": "criminal"}
    )
    blocked = client.put(
        f"/meetings/{meeting_id}/details", json={"title": "不應更新", "goal": "不應更新"}
    )
    fail_marker = False
    wrong_selection = client.put(
        f"/meetings/{meeting_id}/courtroom/case-type", json={"case_type": "civil"}
    )
    recovered = client.put(
        f"/meetings/{meeting_id}/courtroom/case-type", json={"case_type": "criminal"}
    )

    assert failed.status_code == 409
    assert blocked.status_code == 409
    assert wrong_selection.status_code == 409
    assert recovered.status_code == 200
    assert recovered.json()["case_type"] == "criminal"
    marker = MeetingRepository(tmp_path / "data").read_events(meeting_id)[-1]
    assert marker["interaction_type"] == "deliberation-epoch-start"
    assert marker["snapshot"] == {
        "goal": "中立整理",
        "courtroom_docket": {
            "schema_version": 1,
            "revision": 1,
            "confirmed": False,
            "next_issue_number": 2,
            "issues": [{"id": "issue-1", "title": "舊爭點草稿"}],
        },
        "models": [
            {"role_id": "Prosecutor", "model_config_id": "mock-fast"},
            {"role_id": "Defense", "model_config_id": "mock-fast"},
            {"role_id": "Judge", "model_config_id": "mock-fast"},
        ],
        "materials_revision": 0,
        "from_case_type": "civil",
        "to_case_type": "criminal",
    }


def test_case_type_change_metadata_failure_reconciles_completed_marker(
    tmp_path: Path, monkeypatch
) -> None:
    client = TestClient(create_test_app(tmp_path), raise_server_exceptions=False)
    meeting_id = client.post(
        "/meetings",
        json={"title": "類型 finalize", "goal": "測試", "mode_id": "courtroom", "case_type": "civil"},
    ).json()["meeting_id"]
    client.post(f"/meetings/{meeting_id}/messages", json={"content": "觸發新 epoch"})
    original_update = MeetingMetadataStore.update
    fail_finalize = True

    def fail_case_type_finalize(self, target_meeting_id, transform):
        nonlocal fail_finalize
        current = self.get(target_meeting_id)
        projected = transform(current)
        if (
            fail_finalize
            and current.get("pending_meeting_settings")
            and not projected.get("pending_meeting_settings")
        ):
            raise OSError("simulated case-type metadata finalize failure")
        return original_update(self, target_meeting_id, transform)

    monkeypatch.setattr(MeetingMetadataStore, "update", fail_case_type_finalize)
    failed = client.put(
        f"/meetings/{meeting_id}/courtroom/case-type", json={"case_type": "criminal"}
    )
    fail_finalize = False
    reconciled = client.put(
        f"/meetings/{meeting_id}/courtroom/case-type", json={"case_type": "criminal"}
    )

    assert failed.status_code == 409
    assert reconciled.status_code == 200
    assert reconciled.json()["case_type"] == "criminal"
    assert reconciled.json()["deliberation"]["active_epoch_number"] == 2


def test_case_type_change_pending_metadata_failure_writes_no_marker_and_is_retryable(
    tmp_path: Path, monkeypatch
) -> None:
    client = TestClient(create_test_app(tmp_path), raise_server_exceptions=False)
    meeting_id = client.post(
        "/meetings",
        json={"title": "pending fault", "goal": "測試", "mode_id": "courtroom", "case_type": "civil"},
    ).json()["meeting_id"]
    client.post(f"/meetings/{meeting_id}/messages", json={"content": "既有討論"})
    original_update = MeetingMetadataStore.update
    fail_pending = True

    def fail_pending_metadata_write(self, target_meeting_id, transform):
        nonlocal fail_pending
        current = self.get(target_meeting_id)
        projected = transform(current)
        if fail_pending and projected.get("pending_meeting_settings"):
            raise OSError("simulated pending metadata failure")
        return original_update(self, target_meeting_id, transform)

    monkeypatch.setattr(MeetingMetadataStore, "update", fail_pending_metadata_write)
    failed = client.put(
        f"/meetings/{meeting_id}/courtroom/case-type", json={"case_type": "criminal"}
    )
    fail_pending = False
    recovered = client.put(
        f"/meetings/{meeting_id}/courtroom/case-type", json={"case_type": "criminal"}
    )

    assert failed.status_code == 409
    assert recovered.status_code == 200
    assert recovered.json()["case_type"] == "criminal"
    markers = [
        event
        for event in MeetingRepository(tmp_path / "data").read_events(meeting_id)
        if event.get("interaction_type") == "deliberation-epoch-start"
    ]
    assert len(markers) == 1


def test_legacy_courtroom_transcript_keeps_catalog_label_after_explicit_civil_selection(
    tmp_path: Path,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings",
        json={"title": "舊法院", "goal": "舊流程", "mode_id": "courtroom", "case_type": "criminal"},
    ).json()["meeting_id"]
    MeetingMetadataStore(tmp_path / "data").update(
        meeting_id,
        lambda current: {key: value for key, value in current.items() if key != "case_type"},
    )
    MeetingRepository(tmp_path / "data").append_event(
        meeting_id,
        {
            "event_id": f"{meeting_id}:legacy-charge",
            "meeting_id": meeting_id,
            "step_id": "courtroom-charge",
            "role": "Prosecutor",
            "status": "completed",
            "interaction_type": "courtroom-issue-phase",
            "issue_phase": "charge",
            "parsed_output": {"summary": "舊檢察官主張"},
        },
    )

    assert client.put(
        f"/meetings/{meeting_id}/courtroom/case-type", json={"case_type": "civil"}
    ).status_code == 200
    transcript = client.get(f"/meetings/{meeting_id}/transcript.md?epoch=all")

    assert transcript.status_code == 200
    assert "## 檢察官" in transcript.text
    assert "## 原告代理人" not in transcript.text


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
        json={"title": "Active issue", "goal": "one at a time", "mode_id": "courtroom", "case_type": "civil"},
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
        json={"title": "Issue identity", "goal": "one at a time", "mode_id": "courtroom", "case_type": "civil"},
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
    meeting = wait_for_activity(client, meeting_id, "completed")
    assert meeting["courtroom"]["current_issue_id"] == "issue-1"

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
    # chatroom has no deliberation lifecycle yet (no runner/restart wiring), so it is
    # excluded from restart coverage alongside courtroom's issue-based flow.
    modes = [
        mode
        for mode in client.get("/modes").json()
        if mode["id"] not in {"courtroom", "chatroom"}
    ]
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
                "case_type": "civil",
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
        json={"title": "Court material gate", "goal": "block all", "mode_id": "courtroom", "case_type": "civil"},
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
        json={"title": "carried ruling", "goal": "preserve ruling", "mode_id": "courtroom", "case_type": "civil"},
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
    "courtroom_civil_issue_draft",
    "courtroom_civil_proponent_statement",
    "courtroom_civil_respondent_defense",
    "courtroom_civil_limited_rebuttal",
    "courtroom_civil_issue_ruling",
    "courtroom_civil_final_verdict",
    "courtroom_criminal_issue_draft",
    "courtroom_criminal_proponent_statement",
    "courtroom_criminal_respondent_defense",
    "courtroom_criminal_limited_rebuttal",
    "courtroom_criminal_issue_ruling",
    "courtroom_criminal_final_verdict",
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
    "chatroom_response",
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
        if template == "chatroom_response":
            content += " {{ role_display_name }} {{ instruction }}"
        if template.startswith("courtroom_issue_") or (
            template.startswith(("courtroom_civil_", "courtroom_criminal_"))
            and not template.endswith(("issue_draft", "final_verdict"))
        ):
            content += " {{ current_issue }}"
        if template == "courtroom_final_verdict" or template.endswith(("civil_final_verdict", "criminal_final_verdict")):
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


# ── Chatroom mention tests (task group 6) ──────────────────────────────


def _structured_chat_payload(
    content: str,
    *role_ids: str,
    quoted_event_id: str | None = None,
) -> dict[str, object]:
    display_names = {
        "host": "主持 AI", "Advisor": "顧問", "Critic": "評論者",
        "Strategist": "策略師", "Analyst": "分析師", "all": "全部角色",
        "Unknown": "未知", "Blue": "藍軍",
    }
    mentions = []
    cursor = 0
    for index, role_id in enumerate(role_ids, start=1):
        display_text = f"@{display_names.get(role_id, role_id)}"
        start = content.index(display_text, cursor)
        end = start + len(display_text)
        mentions.append({
            "token_id": f"mention-{index}", "role_id": role_id,
            "display_text": display_text, "start": start, "end": end,
        })
        cursor = end
    return {
        "content": content, "mentions": mentions, "source_tokens": [],
        "source_refs": [], "quoted_event_id": quoted_event_id,
    }


def test_chat_mention_single_role(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={"title": "自由聊天", "mode_id": "chatroom"},
    ).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json=_structured_chat_payload("@顧問 你怎麼看？", "Advisor"),
    )

    assert response.status_code == 202
    events = wait_for_event_count(client, meeting_id, 2)
    assert events[-2]["step_id"] == "human-directed-message"
    assert events[-2]["interaction_type"] == "directed-role-instruction"
    assert events[-2]["target_role_id"] == "Advisor"
    assert events[-2]["content"] == "@顧問 你怎麼看？"
    assert events[-1]["step_id"] == "chat-directed-1-advisor-response"
    assert events[-1]["role"] == "Advisor"
    assert events[-1]["interaction_type"] == "directed-role-response"
    assert events[-1]["in_response_to_event_id"] == events[-2]["event_id"]


def test_chat_mention_all(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={"title": "自由聊天", "mode_id": "chatroom"},
    ).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json=_structured_chat_payload("@全部角色 大家怎麼看？", "all"),
    )

    assert response.status_code == 202
    events = wait_for_event_count(client, meeting_id, 6)
    # human-message + one fanout response per role, including the fixed Host
    assert events[-6]["step_id"] == "human-message"
    assert events[-6]["content"] == "@全部角色 大家怎麼看？"
    fanout_roles = {e["role"] for e in events[-5:]}
    assert fanout_roles == {"host", "Advisor", "Critic", "Strategist", "Analyst"}
    for event in events[-5:]:
        assert event["interaction_type"] == "chatroom-fanout-response"


def test_chat_mention_empty_saves_human(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={"title": "自由聊天", "mode_id": "chatroom"},
    ).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json=_structured_chat_payload("只是一則訊息"),
    )

    assert response.status_code == 202
    assert response.json()["target_role_ids"] == ["host"]
    events = wait_for_event_count(client, meeting_id, 2)
    assert events[-2]["step_id"] == "human-directed-message"
    assert events[-2]["content"] == "只是一則訊息"
    assert events[-1]["role"] == "host"


def test_chat_single_target_system_messages_use_current_fixed_personas(
    tmp_path: Path,
) -> None:
    app = create_test_app(tmp_path)
    modes_path = tmp_path / "config" / "modes.yaml"
    modes_yaml = modes_path.read_text(encoding="utf-8")
    modes_path.write_text(
        modes_yaml.replace(
            "你負責主持對話，釐清問題、整理脈絡，並在需要時提出可執行的下一步。",
            "UNIQUE_HOST_PERSONA_FROM_CURRENT_MODE",
        ).replace(
            "你是務實的顧問，提出可行選項、說明取捨，並把建議連結到使用者真正要做的決定。",
            "UNIQUE_ADVISOR_PERSONA_FROM_CURRENT_MODE",
        ),
        encoding="utf-8",
    )
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={"title": "Persona 路由", "mode_id": "chatroom"},
    ).json()["meeting_id"]

    plain = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json=_structured_chat_payload("請主持人回答"),
    )
    assert plain.status_code == 202
    host_event = wait_for_event_count(client, meeting_id, 2)[-1]
    assert host_event["prompt_messages"][0]["role"] == "system"
    assert "UNIQUE_HOST_PERSONA_FROM_CURRENT_MODE" in host_event["prompt_messages"][0]["content"]

    advisor = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json=_structured_chat_payload("@顧問 請回答", "Advisor"),
    )
    assert advisor.status_code == 202
    advisor_event = wait_for_event_count(client, meeting_id, 4)[-1]
    assert advisor_event["role"] == "Advisor"
    assert advisor_event["prompt_messages"][0]["role"] == "system"
    assert "UNIQUE_ADVISOR_PERSONA_FROM_CURRENT_MODE" in advisor_event["prompt_messages"][0]["content"]


def test_chat_mention_invalid_role_400(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={"title": "自由聊天", "mode_id": "chatroom"},
    ).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json=_structured_chat_payload("@未知 你好嗎", "Unknown"),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "STALE_MENTION_PAYLOAD"


def test_chat_mention_rejects_non_chatroom(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={"title": "一般會議", "goal": "一般會議"},
    ).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json=_structured_chat_payload("@藍軍 test", "Blue"),
    )

    assert response.status_code == 409


def test_chat_mention_multiple_roles(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={"title": "自由聊天", "mode_id": "chatroom"},
    ).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json=_structured_chat_payload("@顧問 @評論者 你們兩個怎麼想？", "Advisor", "Critic"),
    )

    assert response.status_code == 202
    events = wait_for_event_count(client, meeting_id, 3)
    # human-message + Advisor fanout + Critic fanout
    assert events[-3]["step_id"] == "human-message"
    assert events[-3]["content"] == "@顧問 @評論者 你們兩個怎麼想？"
    fanout_roles = {e["role"] for e in events[-2:]}
    assert fanout_roles == {"Advisor", "Critic"}
    for event in events[-2:]:
        assert event["interaction_type"] == "chatroom-fanout-response"


def test_chat_mention_all_deduplicates(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={"title": "自由聊天", "mode_id": "chatroom"},
    ).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json=_structured_chat_payload("@全部角色 @顧問 大家怎麼看？", "all", "Advisor"),
    )

    assert response.status_code == 202
    events = wait_for_event_count(client, meeting_id, 6)
    # human-message + one fanout per active role, including Host
    # Advisor should NOT be double-invoked when 'all' is also present
    assert events[-6]["step_id"] == "human-message"
    fanout_roles = {e["role"] for e in events[-5:]}
    assert fanout_roles == {"host", "Advisor", "Critic", "Strategist", "Analyst"}


def test_chat_mention_empty_response_event_id_matches_persisted_event(
    tmp_path: Path,
) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={"title": "自由聊天", "mode_id": "chatroom"},
    ).json()["meeting_id"]
    quote_target = client.post(
        f"/meetings/{meeting_id}/messages",
        json={"content": "之前的訊息"},
    ).json()

    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json=_structured_chat_payload("引用這則", quoted_event_id=quote_target["event_id"]),
    )

    assert response.status_code == 202
    wait_for_event_count(client, meeting_id, 2)
    repository = MeetingRepository(tmp_path / "data")
    persisted = repository.read_events(meeting_id)
    persisted_ids = {e.get("event_id") for e in persisted}
    human_event = next(e for e in persisted if e.get("content") == "引用這則")
    assert human_event["event_id"] in persisted_ids
    assert human_event.get("quoted_event_id") == quote_target["event_id"]


def test_chat_mention_non_participant_role_returns_400(
    tmp_path: Path,
) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={
            "title": "子集聊天",
            "mode_id": "chatroom",
            "participants": [
                {"role_id": "host", "model_config_id": "mock-fast"},
                {"role_id": "Advisor", "model_config_id": "mock-fast"},
                {"role_id": "Critic", "model_config_id": "mock-fast"},
            ],
        },
    ).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json=_structured_chat_payload("@策略師 說說看", "Strategist"),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "STALE_MENTION_PAYLOAD"


def test_legacy_empty_chatroom_roster_projects_and_routes_all_five_without_migration(
    tmp_path: Path,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings",
        json={"title": "Legacy empty roster", "mode_id": "chatroom"},
    ).json()["meeting_id"]
    metadata_path = tmp_path / "data" / "meetings" / meeting_id / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["participants"] = []
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")

    projected = client.get(f"/meetings/{meeting_id}").json()
    assert [participant["role_id"] for participant in projected["participants"]] == [
        "host", "Advisor", "Critic", "Strategist", "Analyst",
    ]

    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json=_structured_chat_payload("@顧問 legacy 可用", "Advisor"),
    )
    assert response.status_code == 202
    assert response.json()["target_role_ids"] == ["Advisor"]
    assert wait_for_event_count(client, meeting_id, 2)[-1]["role"] == "Advisor"
    assert json.loads(metadata_path.read_text(encoding="utf-8"))["participants"] == []


def test_legacy_subset_projects_only_subset_plus_host_for_mentions_and_all(
    tmp_path: Path,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings",
        json={"title": "Legacy subset", "mode_id": "chatroom"},
    ).json()["meeting_id"]
    metadata_path = tmp_path / "data" / "meetings" / meeting_id / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    legacy_subset = [
        {"role_id": "Advisor", "model_config_id": "mock-fast"},
        {"role_id": "Critic", "model_config_id": "mock-fast"},
    ]
    metadata["participants"] = legacy_subset
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")

    projected = client.get(f"/meetings/{meeting_id}").json()
    assert [participant["role_id"] for participant in projected["participants"]] == [
        "host", "Advisor", "Critic",
    ]

    advisor = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json=_structured_chat_payload("@顧問 subset 可用", "Advisor"),
    )
    assert advisor.status_code == 202
    wait_for_event_count(client, meeting_id, 2)

    inactive = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json=_structured_chat_payload("@策略師 不應啟用", "Strategist"),
    )
    assert inactive.status_code == 400
    assert inactive.json()["error"]["code"] == "STALE_MENTION_PAYLOAD"
    assert len(client.get(f"/meetings/{meeting_id}").json()["events"]) == 2

    all_response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json=_structured_chat_payload("@全部角色 subset all", "all"),
    )
    assert all_response.status_code == 202
    assert all_response.json()["target_role_ids"] == ["host", "Advisor", "Critic"]
    events = wait_for_event_count(client, meeting_id, 6)
    assert {event["role"] for event in events[-3:]} == {"host", "Advisor", "Critic"}
    assert json.loads(metadata_path.read_text(encoding="utf-8"))["participants"] == legacy_subset


def test_new_chatroom_selected_roster_is_frozen_for_mentions_and_all(
    tmp_path: Path,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    selected_role_ids = ["host", "Advisor", "Critic", "Analyst"]
    created = client.post(
        "/meetings",
        json={
            "title": "Selected roster authority",
            "mode_id": "chatroom",
            "participants": [
                {"role_id": role_id, "model_config_id": "mock-fast"}
                for role_id in selected_role_ids
            ],
        },
    )
    assert created.status_code == 200
    meeting_id = created.json()["meeting_id"]
    assert [participant["role_id"] for participant in created.json()["participants"]] == selected_role_ids

    inactive = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json=_structured_chat_payload("@策略師 不在 roster", "Strategist"),
    )
    assert inactive.status_code == 400
    assert inactive.json()["error"]["code"] == "STALE_MENTION_PAYLOAD"

    all_response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json=_structured_chat_payload("@全部角色 selected all", "all"),
    )
    assert all_response.status_code == 202
    assert all_response.json()["target_role_ids"] == selected_role_ids
    events = wait_for_event_count(client, meeting_id, 5)
    assert {event["role"] for event in events[-4:]} == set(selected_role_ids)
    assert all(event["role"] != "Strategist" for event in events)


def test_chat_mention_with_quoted_event_passes_content_to_runner(
    tmp_path: Path,
) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={"title": "自由聊天", "mode_id": "chatroom"},
    ).json()["meeting_id"]
    quote_target = client.post(
        f"/meetings/{meeting_id}/messages",
        json={"content": "這是一則關於架構的重要訊息"},
    ).json()

    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json=_structured_chat_payload("@顧問 你怎麼看？", "Advisor", quoted_event_id=quote_target["event_id"]),
    )

    assert response.status_code == 202
    events = wait_for_event_count(client, meeting_id, 3)
    response_event = events[-1]
    assert response_event["status"] == "completed"
    prompt_messages = response_event.get("prompt_messages", [])
    assert len(prompt_messages) >= 1
    prompt_content = "\n".join(message["content"] for message in prompt_messages)
    assert "這是一則關於架構的重要訊息" in prompt_content


def test_chatroom_human_message_no_ai(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={"title": "自由聊天", "mode_id": "chatroom"},
    ).json()["meeting_id"]

    response = client.post(
        f"/meetings/{meeting_id}/messages",
        json={"content": "純粹聊天"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["step_id"] == "human-message"
    assert body["role"] == "Human"
    assert body["content"] == "純粹聊天"

    events = client.get(f"/meetings/{meeting_id}").json()["events"]
    assert len(events) == 1
    assert events[0]["step_id"] == "human-message"
    assert events[0]["role"] == "Human"
    non_human_roles = {e["role"] for e in events if e["role"] not in ("Human", "System")}
    assert non_human_roles == set()


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


def _upload_attachment(
    client: TestClient,
    meeting_id: str,
    *,
    filename: str,
    content: bytes,
    content_type: str,
) -> tuple[int, dict[str, object]]:
    response = client.post(
        f"/meetings/{meeting_id}/attachments",
        files={"file": (filename, content, content_type)},
    )
    return response.status_code, response.json()


def _create_chatroom_meeting(client: TestClient) -> str:
    return client.post(
        "/meetings",
        json={"title": "附件測試", "mode_id": "chatroom"},
    ).json()["meeting_id"]


def test_upload_binary_attachment_writes_blob_and_event(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = _create_chatroom_meeting(client)
    pdf_bytes = b"%PDF-1.4 fake pdf content"

    status, body = _upload_attachment(
        client,
        meeting_id,
        filename="report.pdf",
        content=pdf_bytes,
        content_type="application/pdf",
    )

    assert status == 200
    assert body["step_id"] == "attachment-added"
    assert body["role"] == "Human"
    assert body["status"] == "completed"
    assert body["meeting_id"] == meeting_id
    assert body["filename"] == "report.pdf"
    assert body["size"] == len(pdf_bytes)
    assert body["mime_type"] == "application/pdf"
    assert body["extension"] == ".pdf"
    assert body["file_id"].startswith("attachment-")

    blob = (
        tmp_path / "data" / "meetings" / meeting_id / "attachments" / body["file_id"]
    )
    assert blob.read_bytes() == pdf_bytes

    events = client.get(f"/meetings/{meeting_id}").json()["events"]
    attachment_events = [e for e in events if e["step_id"] == "attachment-added"]
    assert len(attachment_events) == 1
    assert attachment_events[0]["file_id"] == body["file_id"]


def test_upload_text_file_in_chatroom_ingests_evidence_and_attachment(
    tmp_path: Path,
) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = _create_chatroom_meeting(client)

    cases = [
        ("note.txt", "text/plain", ".txt", "這是純文字內容"),
        ("大綱.md", "text/markdown", ".md", "# 標題\n內容"),
    ]
    for filename, expected_mime, extension, text_content in cases:
        status, body = _upload_attachment(
            client,
            meeting_id,
            filename=filename,
            content=text_content.encode("utf-8"),
            content_type=expected_mime,
        )
        assert status == 200
        assert body["step_id"] == "attachment-added"
        assert body["mime_type"] == expected_mime
        assert body["extension"] == extension
        assert body["filename"] == filename
        assert body["size"] == len(text_content.encode("utf-8"))

        # The same upload is mirrored into the AI-visible case-files contract:
        # title = stem, content = full text, every role can see it, active.
        meeting = client.get(f"/meetings/{meeting_id}").json()
        evidence = meeting["case_materials"]["evidence"]
        assert evidence[-1]["status"] == "active"
        active_version = evidence[-1]["versions"][0]
        assert active_version["title"] == Path(filename).stem
        assert active_version["content"] == text_content
        assert set(active_version["visible_roles"]) == {
            "host",
            "Advisor",
            "Critic",
            "Strategist",
            "Analyst",
        }
        assert active_version["host_acl_explicit"] is True

        # The blob serves the full text through the file_id download endpoint.
        download = client.get(f"/meetings/{meeting_id}/attachments/{body['file_id']}")
        assert download.status_code == 200
        assert download.content == text_content.encode("utf-8")

    events = client.get(f"/meetings/{meeting_id}").json()["events"]
    attachment_events = [e for e in events if e["step_id"] == "attachment-added"]
    assert len(attachment_events) == 2
    blob_dir = tmp_path / "data" / "meetings" / meeting_id / "attachments"
    assert sorted(p.name for p in blob_dir.iterdir()) == sorted(
        e["file_id"] for e in attachment_events
    )


def test_chatroom_sources_project_mirror_once_and_freezes_selected_context(
    tmp_path: Path,
) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = _create_chatroom_meeting(client)
    status, upload = _upload_attachment(
        client,
        meeting_id,
        filename="待辦總覽.md",
        content="deadline: tomorrow\n",
        content_type="text/markdown",
    )
    assert status == 200

    sources = client.get(f"/meetings/{meeting_id}/chat/sources").json()
    assert [item["source_ref"] for item in sources].count(
        f"attachment:{upload['file_id']}"
    ) == 1
    assert not any(item["source_ref"].startswith("evidence:") for item in sources)
    source = next(item for item in sources if item["source_ref"].startswith("attachment:"))
    assert source["label"] == "待辦總覽.md"

    content = "@顧問 請查看 #待辦總覽.md"
    source_start = content.index("#")
    payload = _structured_chat_payload(content, "Advisor")
    payload["mentions"] = [{
        "token_id": "mention-1", "role_id": "Advisor", "display_text": "@顧問",
        "start": 0, "end": 3,
    }]
    payload["source_tokens"] = [{
        "token_id": "source-1", "source_ref": source["source_ref"],
        "display_text": "#待辦總覽.md", "start": source_start,
        "end": source_start + len("#待辦總覽.md"),
    }]
    payload["source_refs"] = [source["source_ref"]]
    response = client.post(f"/meetings/{meeting_id}/chat/mention", json=payload)
    assert response.status_code == 202, response.json()
    events = wait_for_event_count(client, meeting_id, 3)
    human = events[-2]
    assert human["source_refs"] == [source["source_ref"]]
    response_event = events[-1]
    snapshot = response_event["selected_source_snapshot"]
    assert snapshot["schema_version"] == "chatroom-source-context/v1"
    assert "deadline: tomorrow" not in str(snapshot)
    assert snapshot["sources"][0]["available_segment_refs"] == ["full"]
    assert "deadline: tomorrow" in str(response_event["prompt_messages"])


def test_chatroom_no_source_reference_never_reads_blob_or_material_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = _create_chatroom_meeting(client)
    material = client.post(
        f"/meetings/{meeting_id}/materials/evidence",
        json={"revision": 0, "title": "機密.md", "content": "TOP SECRET BODY", "visible_roles": ["host"]},
    )
    assert material.status_code == 200
    before = client.get(f"/meetings/{meeting_id}").json()["events"]
    read_calls: list[str] = []
    original_read_bytes = Path.read_bytes
    original_material_read = MeetingRepository.read_case_materials_raw

    def spy_read_bytes(path: Path) -> bytes:
        read_calls.append(str(path))
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", spy_read_bytes)
    monkeypatch.setattr(
        MeetingRepository,
        "read_case_materials_raw",
        lambda repository, current_meeting_id: (
            read_calls.append("case_files.json")
            or original_material_read(repository, current_meeting_id)
        ),
    )
    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json=_structured_chat_payload("請看機密.md 並回答"),
    )
    assert response.status_code == 202
    assert read_calls == []
    events = wait_for_event_count(client, meeting_id, len(before) + 2)
    prompt_events = [event for event in events if event.get("prompt_messages")]
    assert prompt_events
    assert all("TOP SECRET BODY" not in str(event) for event in prompt_events)
    assert all(event.get("selected_source_snapshot", {}).get("source_refs") == [] for event in prompt_events)


def test_chatroom_valid_selected_source_reads_only_selected_material_body(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = _create_chatroom_meeting(client)
    created = client.post(
        f"/meetings/{meeting_id}/materials/evidence",
        json={"revision": 0, "title": "指定來源", "content": "SELECTED_BODY", "visible_roles": ["host"]},
    )
    assert created.status_code == 200
    source = client.get(f"/meetings/{meeting_id}/chat/sources").json()[0]
    body_reads: list[str] = []
    original_material_read = MeetingRepository.read_case_materials_raw

    def spy_material_read(repository: MeetingRepository, current_meeting_id: str):
        body_reads.append(current_meeting_id)
        return original_material_read(repository, current_meeting_id)

    monkeypatch.setattr(MeetingRepository, "read_case_materials_raw", spy_material_read)
    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json={
            "content": "#指定來源 請回答",
            "mentions": [],
            "source_tokens": [{
                "token_id": "s-1", "source_ref": source["source_ref"],
                "display_text": "#指定來源", "start": 0, "end": 5,
            }],
            "source_refs": [source["source_ref"]],
            "quoted_event_id": None,
        },
    )
    assert response.status_code == 202
    assert body_reads == [meeting_id]


@pytest.mark.parametrize(("raw_body", "expected_blob_reads"), [(b"", 0), (b"   ", 1)])
def test_chatroom_selected_text_attachment_rejects_zero_or_blank_decoded_body(
    tmp_path: Path,
    raw_body: bytes,
    expected_blob_reads: int,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = _create_chatroom_meeting(client)
    status, upload = _upload_attachment(
        client,
        meeting_id,
        filename="selected.txt",
        content=b"valid attachment body",
        content_type="text/plain",
    )
    assert status == 200
    source = next(
        item for item in client.get(f"/meetings/{meeting_id}/chat/sources").json()
        if item["kind"] == "attachment"
    )
    blob = Path(tmp_path / "data" / "meetings" / meeting_id / "attachments" / upload["file_id"])
    blob.write_bytes(raw_body)
    reads = 0
    original_read_bytes = Path.read_bytes

    def counted_read(path: Path) -> bytes:
        nonlocal reads
        if path == blob:
            reads += 1
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", counted_read)
    before = client.get(f"/meetings/{meeting_id}").json()["events"]
    display_text = f"#{source['label']}"
    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json={
            "content": f"{display_text} 請回答",
            "mentions": [],
            "source_tokens": [{
                "token_id": "s-1",
                "source_ref": source["source_ref"],
                "display_text": display_text,
                "start": 0,
                "end": len(display_text),
            }],
            "source_refs": [source["source_ref"]],
            "quoted_event_id": None,
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SOURCE_NOT_READABLE"
    assert reads == expected_blob_reads
    assert client.get(f"/meetings/{meeting_id}").json()["events"] == before


def test_chatroom_inactive_source_rejects_body_free_without_event_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = _create_chatroom_meeting(client)
    created = client.post(
        f"/meetings/{meeting_id}/materials/evidence",
        json={"revision": 0, "title": "停用來源", "content": "HIDDEN_BODY", "visible_roles": ["host"]},
    )
    assert created.status_code == 200
    source = client.get(f"/meetings/{meeting_id}/chat/sources").json()[0]
    assert client.post(
        f"/meetings/{meeting_id}/materials/evidence/{source['source_ref'].split(':', 1)[1]}/deactivate",
        json={"revision": 1},
    ).status_code == 200
    client.get(f"/meetings/{meeting_id}/chat/sources")  # refresh the metadata-only header
    before = client.get(f"/meetings/{meeting_id}").json()["events"]
    reads: list[str] = []
    original_material_read = MeetingRepository.read_case_materials_raw
    monkeypatch.setattr(
        MeetingRepository,
        "read_case_materials_raw",
        lambda repository, current_meeting_id: (
            reads.append("case_files.json")
            or original_material_read(repository, current_meeting_id)
        ),
    )
    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json={
            "content": "#停用來源 請回答",
            "mentions": [],
            "source_tokens": [{
                "token_id": "s-1", "source_ref": source["source_ref"],
                "display_text": "#停用來源", "start": 0, "end": 5,
            }],
            "source_refs": [source["source_ref"]],
            "quoted_event_id": None,
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_SOURCE_REF"
    assert reads == []
    assert client.get(f"/meetings/{meeting_id}").json()["events"] == before


@pytest.mark.parametrize("marker", [None, False, "true", 0, 1])
def test_chatroom_persisted_present_non_true_acl_marker_fails_closed_before_send(
    tmp_path: Path, marker: object,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = _create_chatroom_meeting(client)
    created = client.post(
        f"/meetings/{meeting_id}/materials/evidence",
        json={
            "revision": 0,
            "title": "顧問限定",
            "content": "advisor-only body",
            "visible_roles": ["Advisor"],
        },
    )
    assert created.status_code == 200

    repository = MeetingRepository(tmp_path / "data")
    persisted = repository.read_case_materials_raw(meeting_id)
    assert isinstance(persisted, dict)
    version = persisted["evidence"][0]["versions"][0]
    version["host_acl_explicit"] = marker
    repository.save_case_materials(meeting_id, persisted)

    source = client.get(f"/meetings/{meeting_id}/chat/sources").json()[0]
    assert source["acl_invalid"] is True
    assert source["readable"] is False
    assert "host" not in source["visible_roles"]

    before = client.get(f"/meetings/{meeting_id}").json()["events"]
    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json={
            "content": "#顧問限定 請查看",
            "mentions": [],
            "source_tokens": [{
                "token_id": "source-1",
                "source_ref": source["source_ref"],
                "display_text": "#顧問限定",
                "start": 0,
                "end": len("#顧問限定"),
            }],
            "source_refs": [source["source_ref"]],
            "quoted_event_id": None,
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_SOURCE_REF"
    assert client.get(f"/meetings/{meeting_id}").json()["events"] == before


def test_chatroom_persisted_absent_acl_marker_keeps_legacy_host_fallback(
    tmp_path: Path,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = _create_chatroom_meeting(client)
    created = client.post(
        f"/meetings/{meeting_id}/materials/evidence",
        json={
            "revision": 0,
            "title": "舊資料",
            "content": "legacy body",
            "visible_roles": ["Advisor"],
        },
    )
    assert created.status_code == 200

    repository = MeetingRepository(tmp_path / "data")
    persisted = repository.read_case_materials_raw(meeting_id)
    assert isinstance(persisted, dict)
    persisted["evidence"][0]["versions"][0].pop("host_acl_explicit")
    repository.save_case_materials(meeting_id, persisted)

    source = client.get(f"/meetings/{meeting_id}/chat/sources").json()[0]
    assert source["acl_invalid"] is False
    assert source["readable"] is True
    assert "host" in source["visible_roles"]


def test_chatroom_all_rejects_partially_visible_source_before_human_event(
    tmp_path: Path,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = _create_chatroom_meeting(client)
    created = client.post(
        f"/meetings/{meeting_id}/materials/evidence",
        json={"revision": 0, "title": "顧問限定", "content": "advisor only", "visible_roles": ["Advisor"]},
    )
    assert created.status_code == 200
    source = client.get(f"/meetings/{meeting_id}/chat/sources").json()[0]
    before = client.get(f"/meetings/{meeting_id}").json()["events"]
    content = "@全部角色 #顧問限定 請比較"
    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json={
            "content": content,
            "mentions": [{"token_id": "m-1", "role_id": "all", "display_text": "@全部角色", "start": 0, "end": 5}],
            "source_tokens": [{"token_id": "s-1", "source_ref": source["source_ref"], "display_text": "#顧問限定", "start": 6, "end": 11}],
            "source_refs": [source["source_ref"]],
            "quoted_event_id": None,
        },
    )
    assert response.status_code == 400
    assert response.json() == {
        "status": "rejected",
        "error": {"code": "SOURCE_NOT_VISIBLE_TO_TARGET", "field": "source_refs", "details": [{"source_ref": source["source_ref"], "role_id": "host"}]},
    }
    assert client.get(f"/meetings/{meeting_id}").json()["events"] == before


def test_chatroom_large_selected_source_keeps_real_segment_and_prompt_excerpt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_COUNCIL_CHATROOM_CONTEXT_TOKEN_BUDGET", "400")
    client = TestClient(create_test_app(tmp_path))
    meeting_id = _create_chatroom_meeting(client)
    content = "deadline " + ("x" * 2000)
    created = client.post(
        f"/meetings/{meeting_id}/materials/evidence",
        json={"revision": 0, "title": "長段落", "content": content, "visible_roles": ["host"]},
    )
    assert created.status_code == 200
    source = client.get(f"/meetings/{meeting_id}/chat/sources").json()[0]
    text = "#長段落 deadline"
    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json={
            "content": text,
            "mentions": [],
            "source_tokens": [{"token_id": "s-1", "source_ref": source["source_ref"], "display_text": "#長段落", "start": 0, "end": 4}],
            "source_refs": [source["source_ref"]],
            "quoted_event_id": None,
        },
    )
    assert response.status_code == 202
    events = wait_for_event_count(client, meeting_id, 2)
    completed = events[-1]
    snapshot = completed["selected_source_snapshot"]["sources"][0]
    assert snapshot["available_segment_refs"]
    assert snapshot["omission"]["omitted"] is True
    assert content not in str(completed["selected_source_snapshot"])
    assert "deadline" in str(completed["prompt_messages"])


@pytest.mark.parametrize("body", ["", "   ", None, {"not": "text"}])
def test_chatroom_selected_evidence_body_must_be_non_blank_after_metadata_acceptance(
    tmp_path: Path, body: object,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = _create_chatroom_meeting(client)
    created = client.post(
        f"/meetings/{meeting_id}/materials/evidence",
        json={
            "revision": 0,
            "title": "將被竄改的來源",
            "content": "原本有效的正文",
            "visible_roles": ["host"],
        },
    )
    assert created.status_code == 200
    source = client.get(f"/meetings/{meeting_id}/chat/sources").json()[0]
    raw_path = tmp_path / "data" / "meetings" / meeting_id / "case_files.json"
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    raw["evidence"][0]["versions"][0]["content"] = body
    raw_path.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    before = client.get(f"/meetings/{meeting_id}").json()["events"]

    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json={
            "content": "#將被竄改的來源 請回答",
            "mentions": [],
            "source_tokens": [{
                "token_id": "s-1",
                "source_ref": source["source_ref"],
                "display_text": "#將被竄改的來源",
                "start": 0,
                "end": len("#將被竄改的來源"),
            }],
            "source_refs": [source["source_ref"]],
            "quoted_event_id": None,
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SOURCE_NOT_READABLE"
    assert client.get(f"/meetings/{meeting_id}").json()["events"] == before


@pytest.mark.parametrize("marker", ["missing", False])
def test_chatroom_source_metadata_marker_fails_closed_without_reading_body(
    tmp_path: Path, marker: str | bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = _create_chatroom_meeting(client)
    created = client.post(
        f"/meetings/{meeting_id}/materials/evidence",
        json={
            "revision": 0,
            "title": "標記缺失來源",
            "content": "有效正文",
            "visible_roles": ["host"],
        },
    )
    assert created.status_code == 200
    metadata_path = tmp_path / "data" / "meetings" / meeting_id / "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    version = metadata["chatroom_source_metadata"]["evidence"][0]["versions"][0]
    if marker == "missing":
        version.pop("content_valid", None)
    else:
        version["content_valid"] = marker
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")

    reads = 0
    original_read = CaseMaterials.read_evidence_content

    def counted_read(self: CaseMaterials, meeting: str, evidence: str, version_number: int) -> str:
        nonlocal reads
        reads += 1
        return original_read(self, meeting, evidence, version_number)

    monkeypatch.setattr(CaseMaterials, "read_evidence_content", counted_read)
    before = client.get(f"/meetings/{meeting_id}").json()["events"]
    display_text = "#標記缺失來源"
    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json={
            "content": f"{display_text} 請回答",
            "mentions": [],
            "source_tokens": [{
                "token_id": "s-1",
                "source_ref": "evidence:case-file-1",
                "display_text": display_text,
                "start": 0,
                "end": len(display_text),
            }],
            "source_refs": ["evidence:case-file-1"],
            "quoted_event_id": None,
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SOURCE_NOT_READABLE"
    assert reads == 0
    assert client.get(f"/meetings/{meeting_id}").json()["events"] == before


def test_chatroom_fixed_prompt_overflow_fails_safe_without_event_or_adapter_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_COUNCIL_CHATROOM_CONTEXT_TOKEN_BUDGET", "400")
    client = TestClient(create_test_app(tmp_path))
    meeting_id = _create_chatroom_meeting(client)
    first = client.post(
        f"/meetings/{meeting_id}/messages",
        json={"content": "歷史訊息 " + ("x" * 400)},
    )
    assert first.status_code == 200
    first_events = wait_for_event_count(client, meeting_id, 1)
    quote_id = first_events[0]["event_id"]
    created = client.post(
        f"/meetings/{meeting_id}/materials/evidence",
        json={"revision": 0, "title": "滿載來源", "content": "來源正文 " + ("y" * 1200), "visible_roles": ["host"]},
    )
    assert created.status_code == 200
    source = client.get(f"/meetings/{meeting_id}/chat/sources").json()[0]
    content = "#滿載來源 請核對目前內容"
    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json={
            "content": content,
            "mentions": [],
            "source_tokens": [{"token_id": "s-1", "source_ref": source["source_ref"], "display_text": "#滿載來源", "start": 0, "end": 5}],
            "source_refs": [source["source_ref"]],
            "quoted_event_id": quote_id,
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "SOURCE_CONTEXT_TOO_LARGE"
    assert client.get(f"/meetings/{meeting_id}").json()["events"] == first_events


def test_chatroom_long_source_metadata_and_retry_stay_within_request_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_budget = 1050
    monkeypatch.setenv("AI_COUNCIL_CHATROOM_CONTEXT_TOKEN_BUDGET", str(request_budget))
    requests: list[ModelRequest] = []
    selected: dict[str, str] = {}

    def citation_retry(self: MockModelAdapter, request: ModelRequest) -> ModelResponse:
        requests.append(request)
        segment_refs = [] if len(requests) == 1 else ["full"]
        return ModelResponse(json.dumps({
            "message": "依據來源",
            "attachment_refs": [{
                "source_ref": selected["source_ref"],
                "label": selected["label"],
                "segment_refs": segment_refs,
            }],
        }, ensure_ascii=False))

    monkeypatch.setattr(MockModelAdapter, "complete", citation_retry)
    client = TestClient(create_test_app(tmp_path))
    meeting_id = _create_chatroom_meeting(client)
    long_label = "很長的來源標題" * 65
    source_body = "本週必須完成驗收與部署。"
    created = client.post(
        f"/meetings/{meeting_id}/materials/evidence",
        json={
            "revision": 0,
            "title": long_label,
            "content": source_body,
            "visible_roles": ["host"],
        },
    )
    assert created.status_code == 200
    source = client.get(f"/meetings/{meeting_id}/chat/sources").json()[0]
    selected.update(source_ref=source["source_ref"], label=source["label"])
    content = f"#{long_label} 請依附件回答"

    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json={
            "content": content,
            "mentions": [],
            "source_tokens": [{
                "token_id": "s-1",
                "source_ref": source["source_ref"],
                "display_text": f"#{long_label}",
                "start": 0,
                "end": len(long_label) + 1,
            }],
            "source_refs": [source["source_ref"]],
            "quoted_event_id": None,
        },
    )

    assert response.status_code == 202
    events = wait_for_event_count(client, meeting_id, 3)
    assert len(requests) == 2
    assert all(request.messages is not None for request in requests)
    prompt_token_counts = [
        sum(estimate_tokens(message["content"]) for message in request.messages or [])
        for request in requests
    ]
    assert prompt_token_counts and max(prompt_token_counts) <= request_budget, prompt_token_counts
    assert requests[0].messages == requests[1].messages
    assert prompt_token_counts[0] == prompt_token_counts[1]
    attempts = [event for event in events if event.get("role") == "host"]
    assert [event["status"] for event in attempts] == ["failed", "completed"]
    assert attempts[0]["prompt_messages"] == attempts[1]["prompt_messages"]
    assert attempts[0]["selected_source_snapshot"] == attempts[1]["selected_source_snapshot"]
    snapshot = attempts[-1]["selected_source_snapshot"]["sources"][0]
    assert snapshot["available_segment_refs"] == ["full"]
    assert snapshot["omission"]["omitted"] is False
    assert "content" not in snapshot
    assert source_body in requests[-1].prompt


def test_chatroom_multi_segment_snapshot_bounds_initial_and_retry_full_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    request_budget = 1050
    monkeypatch.setenv("AI_COUNCIL_CHATROOM_CONTEXT_TOKEN_BUDGET", str(request_budget))
    requests: list[ModelRequest] = []
    selected: dict[str, str] = {}

    def invalid_then_valid(self: MockModelAdapter, request: ModelRequest) -> ModelResponse:
        requests.append(request)
        segment_refs = [] if len(requests) == 1 else [
            selected["segment_ref"],
        ]
        return ModelResponse(json.dumps({
            "message": "依據多段來源",
            "attachment_refs": [{
                "source_ref": selected["source_ref"],
                "label": selected["label"],
                "segment_refs": segment_refs,
            }],
        }, ensure_ascii=False))

    monkeypatch.setattr(MockModelAdapter, "complete", invalid_then_valid)
    client = TestClient(create_test_app(tmp_path))
    meeting_id = _create_chatroom_meeting(client)
    source_body = "\n".join(
        f"paragraph {index:03d}: deadline decision detail {index:03d} " + ("x" * 60)
        for index in range(1, 301)
    )
    created = client.post(
        f"/meetings/{meeting_id}/materials/evidence",
        json={
            "revision": 0,
            "title": "三百段來源" * 20,
            "content": source_body,
            "visible_roles": ["host"],
        },
    )
    assert created.status_code == 200
    source = client.get(f"/meetings/{meeting_id}/chat/sources").json()[0]
    selected.update(
        source_ref=source["source_ref"],
        label=source["label"],
        segment_ref="paragraph:0001",
    )
    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json={
            "content": "#三百段來源 請依 deadline decision 回答",
            "mentions": [],
            "source_tokens": [{
                "token_id": "s-1",
                "source_ref": source["source_ref"],
                "display_text": "#三百段來源",
                "start": 0,
                "end": 6,
            }],
            "source_refs": [source["source_ref"]],
            "quoted_event_id": None,
        },
    )

    assert response.status_code == 202
    events = wait_for_event_count(client, meeting_id, 3)
    assert len(requests) == 2
    prompt_token_counts = [
        sum(estimate_tokens(message["content"]) for message in request.messages or [])
        for request in requests
    ]
    assert prompt_token_counts and max(prompt_token_counts) <= request_budget, prompt_token_counts
    assert requests[0].messages == requests[1].messages
    assert prompt_token_counts[0] == prompt_token_counts[1]
    attempts = [event for event in events if event.get("role") == "host"]
    assert [event["status"] for event in attempts] == ["failed", "completed"]
    assert attempts[0]["prompt_messages"] == attempts[1]["prompt_messages"]
    assert attempts[0]["selected_source_snapshot"] == attempts[1]["selected_source_snapshot"]
    snapshot = attempts[-1]["selected_source_snapshot"]["sources"][0]
    assert snapshot["available_segment_refs"]
    assert "paragraph:0001" in snapshot["available_segment_refs"]
    assert snapshot["available_segment_refs"] != ["full"]


def test_chatroom_invalid_source_rejects_before_case_body_or_attachment_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = _create_chatroom_meeting(client)
    before = client.get(f"/meetings/{meeting_id}").json()["events"]
    reads: list[str] = []

    original_raw = MeetingRepository.read_case_materials_raw
    original_blob = Path.read_bytes

    def forbidden_case_body(self: MeetingRepository, current_meeting_id: str):
        reads.append("case_files.json")
        return original_raw(self, current_meeting_id)

    def forbidden_blob(self: Path):
        if "attachments" in self.parts:
            reads.append("attachment blob")
        return original_blob(self)

    monkeypatch.setattr(MeetingRepository, "read_case_materials_raw", forbidden_case_body)
    monkeypatch.setattr(Path, "read_bytes", forbidden_blob)
    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json={
            "content": "#不存在 請回答",
            "mentions": [],
            "source_tokens": [{
                "token_id": "s-1",
                "source_ref": "evidence:stale",
                "display_text": "#不存在",
                "start": 0,
                "end": 4,
            }],
            "source_refs": ["evidence:stale"],
            "quoted_event_id": None,
        },
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_SOURCE_REF"
    assert reads == []
    assert client.get(f"/meetings/{meeting_id}").json()["events"] == before


def test_upload_text_file_in_non_chatroom_still_rejected(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={"title": "接力", "goal": "討論方案", "mode_id": "red-blue"},
    ).json()["meeting_id"]

    for filename in ("note.txt", "note.md"):
        status, body = _upload_attachment(
            client,
            meeting_id,
            filename=filename,
            content="# 標題\n內容".encode("utf-8"),
            content_type="text/plain",
        )
        assert status == 400
        assert "case" in body["detail"].lower() or "text" in body["detail"].lower()

    events = client.get(f"/meetings/{meeting_id}").json()["events"]
    assert [e for e in events if e["step_id"] == "attachment-added"] == []
    assert not (tmp_path / "data" / "meetings" / meeting_id / "attachments").exists()


def test_upload_text_file_over_case_material_char_limit_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_COUNCIL_MAX_CASE_FILE_CHARS", "10")
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = _create_chatroom_meeting(client)

    status, body = _upload_attachment(
        client,
        meeting_id,
        filename="long.txt",
        content="超過十個字元上限的內容啊啊啊啊".encode("utf-8"),
        content_type="text/plain",
    )

    assert status == 400
    assert "字元" in body["detail"] or "char" in body["detail"].lower()
    events = client.get(f"/meetings/{meeting_id}").json()["events"]
    assert [e for e in events if e["step_id"] == "attachment-added"] == []
    assert not (tmp_path / "data" / "meetings" / meeting_id / "attachments").exists()


def test_chatroom_material_change_after_ai_output_does_not_gate_ai(
    tmp_path: Path,
) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = _create_chatroom_meeting(client)

    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json=_structured_chat_payload("@顧問 你怎麼看？", "Advisor"),
    )
    assert response.status_code == 202
    wait_for_event_count(client, meeting_id, 2)

    changed = client.post(
        f"/meetings/{meeting_id}/materials/evidence",
        json={
            "revision": 0,
            "title": "補充資料",
            "content": "新內容",
            "visible_roles": ["Advisor", "Critic", "Strategist", "Analyst"],
        },
    )
    assert changed.status_code == 200
    assert changed.json()["pending_impact"] is None

    again = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json=_structured_chat_payload("@顧問 再看一次？", "Advisor"),
    )
    assert again.status_code == 202


def test_relay_material_change_after_ai_output_still_gates_ai(tmp_path: Path) -> None:
    client = TestClient(create_test_app(tmp_path))
    meeting_id = client.post(
        "/meetings",
        json={"title": "接力守門", "goal": "使用當前事實", "mode_id": "red-blue"},
    ).json()["meeting_id"]
    assert client.post(f"/meetings/{meeting_id}/start", json={}).status_code == 202
    wait_for_activity(client, meeting_id, "completed")

    changed = client.post(
        f"/meetings/{meeting_id}/materials/evidence",
        json={
            "revision": 0,
            "title": "後到證物",
            "content": "LATE_EVIDENCE",
            "visible_roles": ["Blue", "Red", "Judge"],
        },
    )
    assert changed.status_code == 200
    assert changed.json()["pending_impact"]["deliberation_epoch_id"] == "epoch-1"

    blocked = client.post(f"/meetings/{meeting_id}/start", json={})
    assert blocked.status_code == 409
    assert "materials changed" in blocked.json()["detail"].lower()


def test_chatroom_mention_recovers_when_legacy_pending_impact_present(
    tmp_path: Path,
) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = _create_chatroom_meeting(client)

    # A round 1-5 meeting could already carry a pending_impact flag. The chatroom
    # read side must suppress it (no data migration), so an old meeting unlocks.
    assert client.post(
        f"/meetings/{meeting_id}/materials/evidence",
        json={
            "revision": 0,
            "title": "既有附件",
            "content": "舊內容",
            "visible_roles": ["Advisor", "Critic", "Strategist", "Analyst"],
        },
    ).status_code == 200
    document_path = (
        tmp_path / "data" / "meetings" / meeting_id / "case_files.json"
    )
    document = json.loads(document_path.read_text(encoding="utf-8"))
    document["pending_impact"] = {
        "deliberation_epoch_id": "epoch-1",
        "reason": "prompt_material_changed_after_ai_output",
    }
    document_path.write_text(json.dumps(document), encoding="utf-8")
    assert (
        client.get(f"/meetings/{meeting_id}").json()["case_materials"]["pending_impact"]
        is None
    )

    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json=_structured_chat_payload("@顧問 你怎麼看？", "Advisor"),
    )
    assert response.status_code == 202


def test_chatroom_legacy_pending_impact_is_suppressed_in_projection(
    tmp_path: Path,
) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = _create_chatroom_meeting(client)
    assert client.post(
        f"/meetings/{meeting_id}/materials/evidence",
        json={
            "revision": 0,
            "title": "既有附件",
            "content": "舊內容",
            "visible_roles": ["Advisor", "Critic", "Strategist", "Analyst"],
        },
    ).status_code == 200
    document_path = tmp_path / "data" / "meetings" / meeting_id / "case_files.json"
    document = json.loads(document_path.read_text(encoding="utf-8"))
    document["pending_impact"] = {
        "deliberation_epoch_id": "epoch-1",
        "reason": "prompt_material_changed_after_ai_output",
    }
    document_path.write_text(json.dumps(document), encoding="utf-8")

    meeting = client.get(f"/meetings/{meeting_id}").json()
    assert meeting["case_materials"]["pending_impact"] is None

    listing = client.get("/meetings").json()
    entry = next(item for item in listing if item["meeting_id"] == meeting_id)
    assert entry["case_materials_summary"]["pending_impact"] is None

    materials = client.get(f"/meetings/{meeting_id}/materials").json()
    assert materials["pending_impact"] is None


def test_non_chatroom_pending_impact_still_projected(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={"title": "接力", "goal": "討論方案", "mode_id": "red-blue"},
    ).json()["meeting_id"]
    assert client.post(
        f"/meetings/{meeting_id}/materials/evidence",
        json={
            "revision": 0,
            "title": "第一份",
            "content": "內容",
            "visible_roles": ["Blue", "Red", "Judge"],
        },
    ).status_code == 200
    document_path = tmp_path / "data" / "meetings" / meeting_id / "case_files.json"
    document = json.loads(document_path.read_text(encoding="utf-8"))
    document["pending_impact"] = {
        "deliberation_epoch_id": "epoch-1",
        "reason": "prompt_material_changed_after_ai_output",
    }
    document_path.write_text(json.dumps(document), encoding="utf-8")

    meeting = client.get(f"/meetings/{meeting_id}").json()
    assert meeting["case_materials"]["pending_impact"] == {
        "deliberation_epoch_id": "epoch-1",
        "reason": "prompt_material_changed_after_ai_output",
    }

    listing = client.get("/meetings").json()
    entry = next(item for item in listing if item["meeting_id"] == meeting_id)
    assert entry["case_materials_summary"]["pending_impact"] == {
        "deliberation_epoch_id": "epoch-1",
        "reason": "prompt_material_changed_after_ai_output",
    }


def test_upload_rejects_oversized_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_COUNCIL_MAX_ATTACHMENT_BYTES", "10")
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = _create_chatroom_meeting(client)

    status, body = _upload_attachment(
        client,
        meeting_id,
        filename="big.png",
        content=b"x" * 11,
        content_type="image/png",
    )

    assert status == 400
    assert "limit" in body["detail"].lower()
    events = client.get(f"/meetings/{meeting_id}").json()["events"]
    assert [e for e in events if e["step_id"] == "attachment-added"] == []
    assert not (tmp_path / "data" / "meetings" / meeting_id / "attachments").exists()


def test_upload_rejects_declared_oversize_before_buffering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_COUNCIL_MAX_ATTACHMENT_BYTES", "10")
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = _create_chatroom_meeting(client)

    # A declared Content-Length far beyond the per-file limit is rejected from
    # the header alone, before the body is read or the blob/event written.
    response = client.post(
        f"/meetings/{meeting_id}/attachments",
        content=b"tiny body that must not be buffered",
        headers={
            "content-type": "multipart/form-data; boundary=zzz",
            "content-length": "999999999",
        },
    )

    assert response.status_code == 400
    assert "limit" in response.json()["detail"].lower()
    events = client.get(f"/meetings/{meeting_id}").json()["events"]
    assert [e for e in events if e["step_id"] == "attachment-added"] == []
    assert not (tmp_path / "data" / "meetings" / meeting_id / "attachments").exists()


def test_upload_rejects_meeting_over_aggregate_quota(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AI_COUNCIL_MAX_TOTAL_ATTACHMENT_BYTES", "10")
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = _create_chatroom_meeting(client)

    status, _ = _upload_attachment(
        client,
        meeting_id,
        filename="a.zip",
        content=b"a" * 6,
        content_type="application/zip",
    )
    assert status == 200

    status, body = _upload_attachment(
        client,
        meeting_id,
        filename="b.zip",
        content=b"b" * 6,
        content_type="application/zip",
    )
    assert status == 400
    assert "limit" in body["detail"].lower() or "quota" in body["detail"].lower()
    events = client.get(f"/meetings/{meeting_id}").json()["events"]
    assert len([e for e in events if e["step_id"] == "attachment-added"]) == 1


def test_unknown_extension_falls_back_to_octet_stream(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = _create_chatroom_meeting(client)

    status, body = _upload_attachment(
        client,
        meeting_id,
        filename="archive.xyz",
        content=b"data",
        content_type="application/octet-stream",
    )

    assert status == 200
    assert body["mime_type"] == "application/octet-stream"
    assert body["extension"] == ".xyz"


def test_download_attachment_serves_blob(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = _create_chatroom_meeting(client)
    pdf_bytes = b"%PDF-1.4 fake pdf content"
    file_id = _upload_attachment(
        client,
        meeting_id,
        filename="report.pdf",
        content=pdf_bytes,
        content_type="application/pdf",
    )[1]["file_id"]

    response = client.get(f"/meetings/{meeting_id}/attachments/{file_id}")

    assert response.status_code == 200
    assert response.content == pdf_bytes
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"].startswith("attachment")
    assert "report.pdf" in response.headers["content-disposition"]


def test_download_image_served_inline(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = _create_chatroom_meeting(client)
    png_bytes = b"\x89PNG\r\n\x1a\n fake png"
    file_id = _upload_attachment(
        client,
        meeting_id,
        filename="photo.png",
        content=png_bytes,
        content_type="image/png",
    )[1]["file_id"]

    response = client.get(f"/meetings/{meeting_id}/attachments/{file_id}")

    assert response.status_code == 200
    assert response.content == png_bytes
    assert response.headers["content-type"] == "image/png"
    assert response.headers["content-disposition"].startswith("inline")


def test_download_unknown_file_id_404(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = _create_chatroom_meeting(client)

    response = client.get(f"/meetings/{meeting_id}/attachments/attachment-unknown")

    assert response.status_code == 404


def test_download_unknown_meeting_404(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)

    response = client.get("/meetings/meeting-nope/attachments/attachment-x")

    assert response.status_code == 404


def test_attachments_summary_in_meeting_payloads(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = _create_chatroom_meeting(client)
    _upload_attachment(client, meeting_id, filename="a.pdf", content=b"a", content_type="application/pdf")
    _upload_attachment(client, meeting_id, filename="b.zip", content=b"bb", content_type="application/zip")

    meeting = client.get(f"/meetings/{meeting_id}").json()
    assert meeting["attachments_summary"] == {"count": 2, "total_bytes": 3}

    listing = client.get("/meetings").json()
    entry = next(item for item in listing if item["meeting_id"] == meeting_id)
    assert entry["attachments_summary"] == {"count": 2, "total_bytes": 3}


def test_upload_attachment_rejected_on_terminal_meeting(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = _create_chatroom_meeting(client)
    client.post(f"/meetings/{meeting_id}/close")

    status, body = _upload_attachment(
        client,
        meeting_id,
        filename="after.pdf",
        content=b"pdf",
        content_type="application/pdf",
    )

    assert status == 409
    assert body["detail"] == "Meeting is terminal: closed"


def test_upload_attachment_rejected_on_running_meeting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    meeting_id = client.post("/meetings", json={"title": "執行中", "goal": "執行中"}).json()["meeting_id"]

    try:
        response = client.post(
            f"/meetings/{meeting_id}/start",
            json={"models": {"Blue": "mock-fast", "Red": "mock-fast", "Judge": "mock-fast"}},
        )
        assert response.status_code == 202
        assert model_entered.wait(timeout=1)

        status, body = _upload_attachment(
            client,
            meeting_id,
            filename="during.pdf",
            content=b"pdf",
            content_type="application/pdf",
        )
        assert status == 409
        assert body["detail"] == "Meeting is already running"
    finally:
        release_model.set()


def test_binary_attachment_download_not_restricted_by_visible_roles(
    tmp_path: Path,
) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={
            "title": "角色會議",
            "goal": "討論",
            "participants": [
                {"role_id": "Blue", "model_config_id": "mock-fast"},
                {"role_id": "Red", "model_config_id": "mock-fast"},
                {"role_id": "Judge", "model_config_id": "mock-fast"},
            ],
        },
    ).json()["meeting_id"]

    evidence = client.post(
        f"/meetings/{meeting_id}/materials/evidence",
        json={
            "revision": 0,
            "title": "限縮角色",
            "content": "只有 Blue 能看",
            "visible_roles": ["Blue"],
        },
    )
    assert evidence.status_code == 200

    file_id = _upload_attachment(
        client,
        meeting_id,
        filename="shared.zip",
        content=b"zip-bytes",
        content_type="application/zip",
    )[1]["file_id"]

    download = client.get(f"/meetings/{meeting_id}/attachments/{file_id}")
    assert download.status_code == 200
    assert download.content == b"zip-bytes"


def _delete_attachment(
    client: TestClient,
    meeting_id: str,
    file_id: str,
) -> tuple[int, dict[str, object]]:
    response = client.delete(f"/meetings/{meeting_id}/attachments/{file_id}")
    return response.status_code, response.json()


def test_delete_binary_attachment_tombstones_and_releases_quota(
    tmp_path: Path,
) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = _create_chatroom_meeting(client)
    pdf_bytes = b"%PDF-1.4 fake pdf content"
    status, uploaded = _upload_attachment(
        client,
        meeting_id,
        filename="report.pdf",
        content=pdf_bytes,
        content_type="application/pdf",
    )
    assert status == 200

    delete_status, tombstone = _delete_attachment(
        client, meeting_id, uploaded["file_id"]
    )

    assert delete_status == 200
    assert tombstone["step_id"] == "attachment-removed"
    assert tombstone["role"] == "Human"
    assert tombstone["status"] == "completed"
    assert tombstone["meeting_id"] == meeting_id
    assert tombstone["file_id"] == uploaded["file_id"]
    assert tombstone["filename"] == "report.pdf"

    download = client.get(f"/meetings/{meeting_id}/attachments/{uploaded['file_id']}")
    assert download.status_code == 404

    meeting = client.get(f"/meetings/{meeting_id}").json()
    assert meeting["attachments_summary"] == {"count": 0, "total_bytes": 0}
    attachment_events = [
        event
        for event in meeting["events"]
        if event.get("step_id") == "attachment-added"
    ]
    assert len(attachment_events) == 1
    assert attachment_events[0]["file_id"] == uploaded["file_id"]
    assert attachment_events[0]["removed"] is True
    assert not any(
        event.get("step_id") == "attachment-removed" for event in meeting["events"]
    )
    assert not (
        tmp_path
        / "data"
        / "meetings"
        / meeting_id
        / "attachments"
        / uploaded["file_id"]
    ).exists()

    quota_status, _ = _upload_attachment(
        client,
        meeting_id,
        filename="again.pdf",
        content=pdf_bytes,
        content_type="application/pdf",
    )
    assert quota_status == 200


def test_delete_text_attachment_removes_mirrored_evidence_in_chatroom(
    tmp_path: Path,
) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = _create_chatroom_meeting(client)
    status, uploaded = _upload_attachment(
        client,
        meeting_id,
        filename="note.txt",
        content="第一份內容".encode("utf-8"),
        content_type="text/plain",
    )
    assert status == 200
    before = client.get(f"/meetings/{meeting_id}").json()
    assert [item["id"] for item in before["case_materials"]["evidence"]] == [
        "case-file-1"
    ]

    delete_status, tombstone = _delete_attachment(
        client, meeting_id, uploaded["file_id"]
    )

    assert delete_status == 200
    assert tombstone["step_id"] == "attachment-removed"
    meeting = client.get(f"/meetings/{meeting_id}").json()
    assert meeting["case_materials"]["evidence"] == []
    assert meeting["case_materials"]["revision"] == 2
    assert meeting["case_materials"]["pending_impact"] is None
    assert meeting["attachments_summary"] == {"count": 0, "total_bytes": 0}
    assert client.get(
        f"/meetings/{meeting_id}/attachments/{uploaded['file_id']}"
    ).status_code == 404


def test_delete_attachment_unknown_or_already_removed_returns_404(
    tmp_path: Path,
) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = _create_chatroom_meeting(client)
    file_id = _upload_attachment(
        client,
        meeting_id,
        filename="a.pdf",
        content=b"a",
        content_type="application/pdf",
    )[1]["file_id"]

    assert _delete_attachment(client, meeting_id, "attachment-unknown")[0] == 404
    assert _delete_attachment(client, meeting_id, file_id)[0] == 200
    assert _delete_attachment(client, meeting_id, file_id)[0] == 404


def test_delete_text_upload_records_evidence_id_for_mirror(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = _create_chatroom_meeting(client)
    _upload_attachment(
        client,
        meeting_id,
        filename="note.txt",
        content="第一份內容".encode("utf-8"),
        content_type="text/plain",
    )

    meeting = client.get(f"/meetings/{meeting_id}").json()
    attachment_event = next(
        event
        for event in meeting["events"]
        if event.get("step_id") == "attachment-added"
    )
    assert attachment_event["evidence_id"] == "case-file-1"
    assert meeting["case_materials"]["evidence"][0]["id"] == "case-file-1"


def test_delete_legacy_text_attachment_without_evidence_id_matches_single_title(
    tmp_path: Path,
) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = _create_chatroom_meeting(client)
    assert client.post(
        f"/meetings/{meeting_id}/materials/evidence",
        json={
            "revision": 0,
            "title": "note",
            "content": "legacy body",
            "visible_roles": ["Advisor", "Critic", "Strategist", "Analyst"],
        },
    ).status_code == 200
    repository = MeetingRepository(tmp_path / "data")
    repository.append_event(
        meeting_id,
        {
            "event_id": "meeting-1:attachment-added:legacy",
            "meeting_id": meeting_id,
            "step_id": "attachment-added",
            "role": "Human",
            "attempt": 1,
            "status": "completed",
            "file_id": "attachment-legacy",
            "filename": "note.txt",
            "size": 11,
            "mime_type": "text/plain",
            "extension": ".txt",
        },
    )

    delete_status, _ = _delete_attachment(client, meeting_id, "attachment-legacy")

    assert delete_status == 200
    meeting = client.get(f"/meetings/{meeting_id}").json()
    assert meeting["case_materials"]["evidence"] == []
    assert meeting["case_materials"]["revision"] == 2


def test_delete_legacy_text_attachment_ambiguous_title_returns_400_and_moves_nothing(
    tmp_path: Path,
) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = _create_chatroom_meeting(client)
    for revision in (0, 1):
        assert client.post(
            f"/meetings/{meeting_id}/materials/evidence",
            json={
                "revision": revision,
                "title": "note",
                "content": f"body-{revision}",
                "visible_roles": ["Advisor", "Critic", "Strategist", "Analyst"],
            },
        ).status_code == 200
    repository = MeetingRepository(tmp_path / "data")
    repository.append_event(
        meeting_id,
        {
            "event_id": "meeting-1:attachment-added:legacy",
            "meeting_id": meeting_id,
            "step_id": "attachment-added",
            "role": "Human",
            "attempt": 1,
            "status": "completed",
            "file_id": "attachment-legacy",
            "filename": "note.txt",
            "size": 11,
            "mime_type": "text/plain",
            "extension": ".txt",
        },
    )
    before = client.get(f"/meetings/{meeting_id}").json()

    response = client.delete(f"/meetings/{meeting_id}/attachments/attachment-legacy")

    assert response.status_code == 400
    meeting = client.get(f"/meetings/{meeting_id}").json()
    assert [item["id"] for item in meeting["case_materials"]["evidence"]] == [
        item["id"] for item in before["case_materials"]["evidence"]
    ]
    assert meeting["case_materials"]["revision"] == before["case_materials"]["revision"]
    assert meeting["attachments_summary"] == {"count": 1, "total_bytes": 11}


def test_delete_text_attachment_with_stale_evidence_id_still_succeeds(
    tmp_path: Path,
) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = _create_chatroom_meeting(client)
    repository = MeetingRepository(tmp_path / "data")
    repository.append_event(
        meeting_id,
        {
            "event_id": "meeting-1:attachment-added:stale",
            "meeting_id": meeting_id,
            "step_id": "attachment-added",
            "role": "Human",
            "attempt": 1,
            "status": "completed",
            "file_id": "attachment-stale",
            "filename": "gone.txt",
            "size": 11,
            "mime_type": "text/plain",
            "extension": ".txt",
            "evidence_id": "case-file-999",
        },
    )

    delete_status, tombstone = _delete_attachment(
        client, meeting_id, "attachment-stale"
    )

    assert delete_status == 200
    assert tombstone["step_id"] == "attachment-removed"
    meeting = client.get(f"/meetings/{meeting_id}").json()
    assert meeting["case_materials"]["evidence"] == []
    assert meeting["case_materials"]["revision"] == 0


def test_delete_legacy_text_attachment_without_evidence_id_and_no_match_succeeds(
    tmp_path: Path,
) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = _create_chatroom_meeting(client)
    repository = MeetingRepository(tmp_path / "data")
    repository.append_event(
        meeting_id,
        {
            "event_id": "meeting-1:attachment-added:orphan",
            "meeting_id": meeting_id,
            "step_id": "attachment-added",
            "role": "Human",
            "attempt": 1,
            "status": "completed",
            "file_id": "attachment-orphan",
            "filename": "orphan.txt",
            "size": 11,
            "mime_type": "text/plain",
            "extension": ".txt",
        },
    )

    delete_status, tombstone = _delete_attachment(
        client, meeting_id, "attachment-orphan"
    )

    assert delete_status == 200
    assert tombstone["step_id"] == "attachment-removed"
    meeting = client.get(f"/meetings/{meeting_id}").json()
    assert meeting["case_materials"]["evidence"] == []
    assert meeting["case_materials"]["revision"] == 0


def test_delete_attachment_rejected_on_terminal_meeting(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = _create_chatroom_meeting(client)
    file_id = _upload_attachment(
        client,
        meeting_id,
        filename="a.pdf",
        content=b"a",
        content_type="application/pdf",
    )[1]["file_id"]
    client.post(f"/meetings/{meeting_id}/close")

    status, body = _delete_attachment(client, meeting_id, file_id)

    assert status == 409
    assert body["detail"] == "Meeting is terminal: closed"


def test_delete_attachment_rejected_on_running_meeting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
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
    meeting_id = _create_chatroom_meeting(client)
    file_id = _upload_attachment(
        client,
        meeting_id,
        filename="a.pdf",
        content=b"a",
        content_type="application/pdf",
    )[1]["file_id"]

    try:
        response = client.post(
            f"/meetings/{meeting_id}/chat/mention",
            json=_structured_chat_payload("@顧問 你怎麼看？", "Advisor"),
        )
        assert response.status_code == 202
        assert model_entered.wait(timeout=1)

        status, body = _delete_attachment(client, meeting_id, file_id)
        assert status == 409
        assert body["detail"] == "Meeting is already running"
    finally:
        release_model.set()
