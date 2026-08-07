from __future__ import annotations

import copy
import unicodedata
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_council.api import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _client(tmp_path: Path) -> TestClient:
    return TestClient(
        create_app(
            data_dir=tmp_path / "data",
            model_config_path=PROJECT_ROOT / "config/models.yaml.example",
            modes_config_path=PROJECT_ROOT / "config/modes.yaml",
            prompt_dir=PROJECT_ROOT / "prompts",
            start_model_health_checks=False,
        )
    )


def _meeting(client: TestClient, *, mode_id: str = "chatroom") -> str:
    response = client.post("/meetings", json={"title": "routing contract", "mode_id": mode_id})
    assert response.status_code == 200
    return response.json()["meeting_id"]


def _body(content: str = "請整理", **overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "content": content,
        "mentions": [],
        "source_tokens": [],
        "source_refs": [],
        "quoted_event_id": None,
    }
    body.update(overrides)
    return body


def _post(client: TestClient, meeting_id: str, body: dict[str, object]):
    return client.post(f"/meetings/{meeting_id}/chat/mention", json=body)


def test_api_acceptance_body_and_field_mapping_are_exact(tmp_path: Path) -> None:
    client = _client(tmp_path)
    meeting_id = _meeting(client)
    content = "@顧問 請回答"
    token = {
        "token_id": "m-1",
        "role_id": "Advisor",
        "display_text": "@顧問",
        "start": 0,
        "end": 3,
    }

    response = _post(client, meeting_id, _body(content, mentions=[token]))

    assert response.status_code == 202
    assert response.json() == {
        "status": "accepted",
        "meeting_id": meeting_id,
        "target_role_ids": ["Advisor"],
        "source_refs": [],
        "warnings": [],
    }


@pytest.mark.parametrize(
    ("label", "mutate", "field"),
    [
        ("missing content", lambda body: body.pop("content"), "content"),
        ("wrong content type", lambda body: body.update(content=42), "content"),
        ("unknown field", lambda body: body.update(extra=True), "extra"),
        ("wrong mentions type", lambda body: body.update(mentions="Advisor"), "mentions"),
        ("missing source tokens", lambda body: body.pop("source_tokens"), "source_tokens"),
        ("wrong quote type", lambda body: body.update(quoted_event_id=42), "quoted_event_id"),
    ],
)
def test_schema_rejections_are_closed_and_have_no_event_or_job_side_effects(
    tmp_path: Path,
    label: str,
    mutate,
    field: str,
) -> None:
    del label
    client = _client(tmp_path)
    meeting_id = _meeting(client)
    body = _body()
    mutate(body)

    response = _post(client, meeting_id, body)

    assert response.status_code == 400
    assert response.json() == {
        "status": "rejected",
        "error": {"code": "INVALID_REQUEST_SCHEMA", "field": field, "details": []},
    }
    assert client.get(f"/meetings/{meeting_id}").json()["events"] == []


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ("", "INVALID_REQUEST_SCHEMA"),
        ("   ", "INVALID_REQUEST_SCHEMA"),
        ("e\u0301", "INVALID_REQUEST_SCHEMA"),
        ("Email a@advisor.example", "accepted"),
        ("邱顧問，請回答！", "accepted"),
        ("在句首：@Adviser。", "INVALID_MENTION_TOKEN"),
    ],
)
def test_unicode_punctuation_email_and_nfc_boundaries(
    tmp_path: Path,
    content: str,
    expected: str,
) -> None:
    client = _client(tmp_path)
    meeting_id = _meeting(client)
    response = _post(client, meeting_id, _body(content))

    assert response.status_code == (202 if expected == "accepted" else 400)
    if expected != "accepted":
        assert response.json()["error"]["code"] == expected
    else:
        assert response.json()["target_role_ids"] == ["host"]


def test_nfc_composer_content_uses_code_point_spans_and_non_nfc_is_rejected(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    meeting_id = _meeting(client)
    composed = unicodedata.normalize("NFC", "@顧問 e\u0301")
    token = {
        "token_id": "m-1",
        "role_id": "Advisor",
        "display_text": "@顧問",
        "start": 0,
        "end": 3,
    }

    accepted = _post(client, meeting_id, _body(composed, mentions=[token]))
    assert accepted.status_code == 202

    rejected_meeting_id = _meeting(client)
    rejected_response = _post(client, rejected_meeting_id, _body("@顧問 e\u0301", mentions=[token]))
    assert rejected_response.status_code == 400
    assert rejected_response.json() == {
        "status": "rejected",
        "error": {"code": "INVALID_REQUEST_SCHEMA", "field": "content", "details": []},
    }


@pytest.mark.parametrize(
    "mutate",
    [
        lambda body: body["mentions"].append({
            "token_id": "m-1", "role_id": "Advisor", "display_text": "@顧問", "start": 0, "end": 4,
        }),
        lambda body: body["mentions"].append({
            "token_id": "m-1", "role_id": "Advisor", "display_text": "@顧問", "start": -1, "end": 2,
        }),
        lambda body: body["mentions"].extend([
            {"token_id": "m-1", "role_id": "Advisor", "display_text": "@顧問", "start": 0, "end": 3},
            {"token_id": "m-1", "role_id": "Advisor", "display_text": "@顧問", "start": 0, "end": 3},
        ]),
        lambda body: body.update(content="@顧問#需求", mentions=[
            {"token_id": "m-1", "role_id": "Advisor", "display_text": "@顧問", "start": 0, "end": 3},
        ], source_tokens=[
            {"token_id": "s-1", "source_ref": "attachment:a", "display_text": "#需求", "start": 2, "end": 5},
        ], source_refs=["attachment:a"]),
    ],
)
def test_malformed_overlap_and_duplicate_spans_reject_before_side_effects(
    tmp_path: Path,
    mutate,
) -> None:
    client = _client(tmp_path)
    meeting_id = _meeting(client)
    body = _body("@顧問")
    mutate(body)

    response = _post(client, meeting_id, body)

    assert response.status_code == 400
    assert response.json()["error"]["code"] in {
        "MENTION_TOKEN_MISMATCH",
        "SOURCE_TOKEN_MISMATCH",
    }
    assert client.get(f"/meetings/{meeting_id}").json()["events"] == []


@pytest.mark.parametrize(
    ("body_update", "code", "field"),
    [
        ({"mentions": [{"token_id": "m-1", "role_id": "Advisor", "display_text": "@評論者", "start": 0, "end": 4}]}, "STALE_MENTION_PAYLOAD", "mentions"),
        ({"mentions": [{"token_id": "m-1", "role_id": "Unknown", "display_text": "@未知", "start": 0, "end": 3}]}, "STALE_MENTION_PAYLOAD", "mentions"),
        ({"source_tokens": [{"token_id": "s-1", "source_ref": "attachment:a", "display_text": "#需求", "start": 0, "end": 3}], "source_refs": []}, "STALE_SOURCE_PAYLOAD", "source_refs"),
        ({"source_tokens": [{"token_id": "s-1", "source_ref": "attachment:a", "display_text": "需求", "start": 0, "end": 2}], "source_refs": ["attachment:a"]}, "SOURCE_TOKEN_MISMATCH", "source_tokens"),
        ({"source_tokens": [{"token_id": "s-1", "source_ref": "bad", "display_text": "#需求", "start": 0, "end": 3}], "source_refs": ["bad"]}, "INVALID_SOURCE_REF", "source_refs"),
    ],
)
def test_stale_mention_source_and_structural_source_codes_are_exact(
    tmp_path: Path,
    body_update: dict[str, object],
    code: str,
    field: str,
) -> None:
    client = _client(tmp_path)
    meeting_id = _meeting(client)
    body = _body("@評論者") if "mentions" in body_update else _body("#需求")
    if body_update.get("mentions", [{}])[0].get("role_id") == "Unknown":
        body["content"] = "@未知"
    body.update(copy.deepcopy(body_update))

    response = _post(client, meeting_id, body)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["field"] == field
    assert client.get(f"/meetings/{meeting_id}").json()["events"] == []


def test_all_warning_deduplicates_raw_candidates_and_has_chip_precedence(tmp_path: Path) -> None:
    client = _client(tmp_path)
    meeting_id = _meeting(client)
    content = "@全部角色 @Adviser @Adviser"
    response = _post(client, meeting_id, _body(content, mentions=[
        {"token_id": "all-1", "role_id": "all", "display_text": "@全部角色", "start": 0, "end": 5},
    ]))

    assert response.status_code == 202
    assert response.json()["warnings"] == [
        {"code": "IGNORED_INVALID_MENTION", "display_text": "@Adviser"},
        {"code": "IGNORED_INVALID_MENTION", "display_text": "@Adviser"},
    ]


def test_hashtag_without_source_chip_is_ordinary_text_and_source_chip_is_structural_seam(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    meeting_id = _meeting(client)

    hashtag = _post(client, meeting_id, _body("#需求說明 請整理"))
    assert hashtag.status_code == 202
    assert hashtag.json()["target_role_ids"] == ["host"]

    source_meeting_id = _meeting(client)
    source_chip = _post(client, source_meeting_id, _body(
        "#需求說明 請整理",
        source_tokens=[{
            "token_id": "s-1", "source_ref": "attachment:a", "display_text": "#需求說明", "start": 0, "end": 5,
        }],
        source_refs=["attachment:a"],
    ))
    assert source_chip.status_code == 400
    assert source_chip.json() == {
        "status": "rejected",
        "error": {"code": "INVALID_SOURCE_REF", "field": "source_refs", "details": []},
    }


def test_missing_quote_is_gracefully_ignored_but_malformed_quote_is_schema_error(
    tmp_path: Path,
) -> None:
    client = _client(tmp_path)
    meeting_id = _meeting(client)

    missing = _post(client, meeting_id, _body(quoted_event_id=f"{meeting_id}:missing"))
    assert missing.status_code == 202

    malformed_meeting_id = _meeting(client)
    malformed = _post(client, malformed_meeting_id, _body(quoted_event_id="not-a-meeting-event"))
    assert malformed.status_code == 400
    assert malformed.json() == {
        "status": "rejected",
        "error": {"code": "INVALID_REQUEST_SCHEMA", "field": "quoted_event_id", "details": []},
    }


def test_chatroom_missing_and_terminal_meeting_use_exact_envelopes(tmp_path: Path) -> None:
    client = _client(tmp_path)

    missing = _post(client, "meeting-does-not-exist", _body())
    assert missing.status_code == 404
    assert missing.json() == {
        "status": "rejected",
        "error": {"code": "MEETING_NOT_FOUND", "field": None, "details": []},
    }

    meeting_id = _meeting(client)
    assert client.post(f"/meetings/{meeting_id}/close").status_code == 200
    closed = _post(client, meeting_id, _body())
    assert closed.status_code == 409
    assert closed.json() == {
        "status": "rejected",
        "error": {"code": "CHATROOM_NOT_ACCEPTING_INPUT", "field": None, "details": []},
    }
