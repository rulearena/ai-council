from __future__ import annotations

import time
from pathlib import Path

from fastapi.testclient import TestClient

from ai_council.api import create_app

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _create_chatroom(client: TestClient) -> str:
    response = client.post(
        "/meetings",
        json={"title": "Slice 1 routing", "mode_id": "chatroom"},
    )
    assert response.status_code == 200
    return response.json()["meeting_id"]


def _wait_for_events(client: TestClient, meeting_id: str, count: int) -> list[dict[str, object]]:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        events = client.get(f"/meetings/{meeting_id}").json()["events"]
        if len(events) >= count:
            return events
        time.sleep(0.01)
    raise AssertionError(f"meeting did not reach {count} events")


def _valid_request(content: str, mentions: list[dict[str, object]] | None = None) -> dict[str, object]:
    return {
        "content": content,
        "mentions": mentions or [],
        "source_tokens": [],
        "source_refs": [],
        "quoted_event_id": None,
    }


def test_chatroom_mode_projects_fixed_host_role(tmp_path: Path) -> None:
    app = create_app(
        data_dir=tmp_path / "data",
        model_config_path=PROJECT_ROOT / "config/models.yaml.example",
        modes_config_path=PROJECT_ROOT / "config/modes.yaml",
        prompt_dir=PROJECT_ROOT / "prompts",
        start_model_health_checks=False,
    )
    client = TestClient(app)

    mode = next(item for item in client.get("/modes").json() if item["id"] == "chatroom")

    host = next(role for role in mode["roles"] if role["id"] == "host")
    assert host["name"] == "主持 AI"
    assert host["kind"] == "member"


def test_plain_chatroom_input_accepts_and_routes_to_host(tmp_path: Path) -> None:
    app = create_app(
        data_dir=tmp_path / "data",
        model_config_path=PROJECT_ROOT / "config/models.yaml.example",
        modes_config_path=PROJECT_ROOT / "config/modes.yaml",
        prompt_dir=PROJECT_ROOT / "prompts",
        start_model_health_checks=False,
    )
    client = TestClient(app)
    meeting_id = _create_chatroom(client)

    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json=_valid_request("請幫我整理目前討論"),
    )

    assert response.status_code == 202
    assert response.json() == {
        "status": "accepted",
        "meeting_id": meeting_id,
        "target_role_ids": ["host"],
        "source_refs": [],
        "warnings": [],
    }
    events = _wait_for_events(client, meeting_id, 2)
    assert events[-2]["role"] == "Human"
    assert events[-1]["role"] == "host"


def test_valid_display_name_chip_routes_by_stable_role_id(tmp_path: Path) -> None:
    app = create_app(
        data_dir=tmp_path / "data",
        model_config_path=PROJECT_ROOT / "config/models.yaml.example",
        modes_config_path=PROJECT_ROOT / "config/modes.yaml",
        prompt_dir=PROJECT_ROOT / "prompts",
        start_model_health_checks=False,
    )
    client = TestClient(app)
    meeting_id = _create_chatroom(client)
    content = "@顧問 請回答"

    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json=_valid_request(
            content,
            [{
                "token_id": "mention-1",
                "role_id": "Advisor",
                "display_text": "@顧問",
                "start": 0,
                "end": 3,
            }],
        ),
    )

    assert response.status_code == 202
    assert response.json()["target_role_ids"] == ["Advisor"]
    events = _wait_for_events(client, meeting_id, 2)
    assert events[-2]["mentions"][0]["role_id"] == "Advisor"
    assert events[-2]["mentions"][0]["display_text"] == "@顧問"


def test_hand_typed_role_like_token_is_rejected_without_side_effects(tmp_path: Path) -> None:
    app = create_app(
        data_dir=tmp_path / "data",
        model_config_path=PROJECT_ROOT / "config/models.yaml.example",
        modes_config_path=PROJECT_ROOT / "config/modes.yaml",
        prompt_dir=PROJECT_ROOT / "prompts",
        start_model_health_checks=False,
    )
    client = TestClient(app)
    meeting_id = _create_chatroom(client)

    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json=_valid_request("@Adviser 請回答"),
    )

    assert response.status_code == 400
    assert response.json() == {
        "status": "rejected",
        "error": {
            "code": "INVALID_MENTION_TOKEN",
            "field": "content",
            "details": [{"display_text": "@Adviser", "start": 0, "end": 8}],
        },
    }
    assert client.get(f"/meetings/{meeting_id}").json()["events"] == []


def test_all_chip_has_precedence_and_warns_about_raw_role_token(tmp_path: Path) -> None:
    app = create_app(
        data_dir=tmp_path / "data",
        model_config_path=PROJECT_ROOT / "config/models.yaml.example",
        modes_config_path=PROJECT_ROOT / "config/modes.yaml",
        prompt_dir=PROJECT_ROOT / "prompts",
        start_model_health_checks=False,
    )
    client = TestClient(app)
    meeting_id = _create_chatroom(client)
    content = "@全部角色 @Adviser"

    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json=_valid_request(
            content,
            [{
                "token_id": "all-1",
                "role_id": "all",
                "display_text": "@全部角色",
                "start": 0,
                "end": 5,
            }],
        ),
    )

    assert response.status_code == 202
    assert response.json()["target_role_ids"] == ["host", "Advisor", "Critic", "Strategist", "Analyst"]
    assert response.json()["warnings"] == [
        {"code": "IGNORED_INVALID_MENTION", "display_text": "@Adviser"}
    ]
    events = _wait_for_events(client, meeting_id, 6)
    assert {event["role"] for event in events[-5:]} == {
        "host", "Advisor", "Critic", "Strategist", "Analyst"
    }


def test_mention_only_chip_still_invokes_one_role(tmp_path: Path) -> None:
    app = create_app(
        data_dir=tmp_path / "data",
        model_config_path=PROJECT_ROOT / "config/models.yaml.example",
        modes_config_path=PROJECT_ROOT / "config/modes.yaml",
        prompt_dir=PROJECT_ROOT / "prompts",
        start_model_health_checks=False,
    )
    client = TestClient(app)
    meeting_id = _create_chatroom(client)

    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json=_valid_request(
            "@顧問",
            [{
                "token_id": "mention-1",
                "role_id": "Advisor",
                "display_text": "@顧問",
                "start": 0,
                "end": 3,
            }],
        ),
    )

    assert response.status_code == 202
    events = _wait_for_events(client, meeting_id, 2)
    assert events[-1]["role"] == "Advisor"


def test_stale_chip_is_rejected_without_side_effects(tmp_path: Path) -> None:
    app = create_app(
        data_dir=tmp_path / "data",
        model_config_path=PROJECT_ROOT / "config/models.yaml.example",
        modes_config_path=PROJECT_ROOT / "config/modes.yaml",
        prompt_dir=PROJECT_ROOT / "prompts",
        start_model_health_checks=False,
    )
    client = TestClient(app)
    meeting_id = _create_chatroom(client)

    response = client.post(
        f"/meetings/{meeting_id}/chat/mention",
        json=_valid_request(
            "@顧問",
            [{
                "token_id": "mention-1",
                "role_id": "Advisor",
                "display_text": "@評論者",
                "start": 0,
                "end": 3,
            }],
        ),
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MENTION_TOKEN_MISMATCH"
    assert client.get(f"/meetings/{meeting_id}").json()["events"] == []
