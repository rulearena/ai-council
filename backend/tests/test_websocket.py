from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from ai_council.api import create_app


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

    with client.websocket_connect(f"/meetings/{meeting_id}/events") as websocket:
        payload = websocket.receive_json()

    assert payload["type"] == "snapshot"
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
