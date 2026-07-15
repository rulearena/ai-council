from __future__ import annotations

import shutil
import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from ai_council.api import create_app
from ai_council.models.adapters import MockModelAdapter

PROJECT_CONFIG_DIR = Path(__file__).resolve().parents[2] / "config"


def test_meeting_websocket_replays_existing_events(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings", json={"title": "WS 測試", "goal": "WS 測試"}
    ).json()["meeting_id"]
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

    with client.websocket_connect(f"/meetings/{meeting_id}/events") as websocket:
        payload = websocket.receive_json()

    assert payload["type"] == "snapshot"
    assert payload["activity_status"] == "completed"
    assert [
        event["step_id"]
        for event in payload["events"]
        if event["status"] == "completed"
    ] == [
        "blue-propose",
        "red-critique",
        "blue-revise",
        "judge-decide",
    ]


def test_meeting_websocket_streams_background_run_status_and_events(
    tmp_path: Path,
    monkeypatch,
) -> None:
    release_model = threading.Event()
    original_complete = MockModelAdapter.complete

    def slow_complete(self, request):
        release_model.wait(timeout=2)
        return original_complete(self, request)

    monkeypatch.setattr(MockModelAdapter, "complete", slow_complete)
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings", json={"title": "WS 背景執行", "goal": "WS 背景執行"}
    ).json()["meeting_id"]

    with client.websocket_connect(f"/meetings/{meeting_id}/events") as websocket:
        snapshot = websocket.receive_json()
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

        assert snapshot == {
            "type": "snapshot",
            "events": [],
            "stream_events": [],
            "activity_status": "idle",
        }
        assert response.status_code == 202
        running = websocket.receive_json()
        assert running["activity_status"] == "running"

        release_model.set()
        streamed_events = []
        while True:
            update = websocket.receive_json()
            streamed_events.extend(update["events"])
            if update["activity_status"] == "completed":
                break

    assert [event["step_id"] for event in streamed_events] == [
        "blue-propose",
        "red-critique",
        "blue-revise",
        "judge-decide",
    ]


def test_meeting_websocket_streams_ephemeral_token_deltas(tmp_path: Path) -> None:
    app = create_test_app(
        tmp_path,
        models_yaml="""
models:
  - id: mock-streaming
    adapter: mock
    extra_body:
      mock_stream_chunks:
        - Hel
        - lo
""".strip(),
    )
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings",
        json={"title": "WS token streaming", "goal": "WS token streaming"},
    ).json()["meeting_id"]

    with client.websocket_connect(f"/meetings/{meeting_id}/events") as websocket:
        snapshot = websocket.receive_json()
        response = client.post(
            f"/meetings/{meeting_id}/start",
            json={
                "models": {
                    "Blue": "mock-streaming",
                    "Red": "mock-streaming",
                    "Judge": "mock-streaming",
                }
            },
        )

        assert snapshot == {
            "type": "snapshot",
            "events": [],
            "stream_events": [],
            "activity_status": "idle",
        }
        assert response.status_code == 202

        stream_events = []
        while True:
            update = websocket.receive_json()
            stream_events.extend(update.get("stream_events", []))
            if update["activity_status"] == "completed":
                break

    assert [event["content"] for event in stream_events[:2]] == ["Hel", "lo"]
    assert stream_events[0]["type"] == "token_delta"
    assert stream_events[0]["step_id"] == "blue-propose"
    persisted_events = client.get(f"/meetings/{meeting_id}").json()["events"]
    assert all(event.get("type") != "token_delta" for event in persisted_events)


def test_meeting_websocket_replaces_snapshot_when_deliberation_epoch_changes(
    tmp_path: Path,
) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post(
        "/meetings", json={"title": "WS restart", "goal": "WS restart"}
    ).json()["meeting_id"]
    assert client.post(f"/meetings/{meeting_id}/start", json={}).status_code == 202
    wait_for_activity(client, meeting_id, "completed")

    with client.websocket_connect(f"/meetings/{meeting_id}/events") as websocket:
        initial = websocket.receive_json()
        restarted = client.post(
            f"/meetings/{meeting_id}/deliberations/restart",
            json={"scope": "all_deliberation", "reason": "WS full replace"},
        )
        replacement = websocket.receive_json()

    assert len(initial["events"]) == 4
    assert restarted.status_code == 200
    assert replacement == {
        "type": "snapshot",
        "events": [],
        "stream_events": [],
        "activity_status": "idle",
    }


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
    config_dir.mkdir()
    (config_dir / "models.yaml").write_text(models_yaml, encoding="utf-8")
    shutil.copy(PROJECT_CONFIG_DIR / "modes.yaml", config_dir / "modes.yaml")
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    for template in ["blue_propose", "red_critique", "blue_revise", "judge_decide"]:
        (prompt_dir / f"{template}.md").write_text(
            "{{ role }} {{ goal }} {{ prior_transcript }} {{ required_json_schema }}",
            encoding="utf-8",
        )
    return create_app(
        data_dir=tmp_path / "data",
        model_config_path=config_dir / "models.yaml",
        modes_config_path=config_dir / "modes.yaml",
        prompt_dir=prompt_dir,
    )


def wait_for_activity(
    client: TestClient,
    meeting_id: str,
    expected_status: str,
    timeout: float = 2,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if client.get(f"/meetings/{meeting_id}").json()["activity_status"] == expected_status:
            return
        time.sleep(0.01)
    raise AssertionError(f"Meeting did not reach activity status: {expected_status}")
