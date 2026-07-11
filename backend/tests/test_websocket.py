from __future__ import annotations

import threading
import time
from pathlib import Path

from fastapi.testclient import TestClient

from ai_council.api import create_app
from ai_council.models.adapters import MockModelAdapter, ModelResponse


def test_meeting_websocket_replays_existing_events(tmp_path: Path) -> None:
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"topic": "WS 測試"}).json()["meeting_id"]
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

    def slow_complete(self, request):
        release_model.wait(timeout=2)
        return ModelResponse(
            raw_output='{"summary":"OK","arguments":[],"risks":[],"recommendation":"Go"}'
        )

    monkeypatch.setattr(MockModelAdapter, "complete", slow_complete)
    app = create_test_app(tmp_path)
    client = TestClient(app)
    meeting_id = client.post("/meetings", json={"topic": "WS 背景執行"}).json()["meeting_id"]

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

        assert snapshot == {"type": "snapshot", "events": [], "activity_status": "idle"}
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


def create_test_app(tmp_path: Path):
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "models.yaml").write_text(
        """
models:
  - id: mock-fast
    adapter: mock
""".strip(),
        encoding="utf-8",
    )
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
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
