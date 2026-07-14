from __future__ import annotations

import shutil
import time
from pathlib import Path

from fastapi.testclient import TestClient

from ai_council.api import create_app


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def create_client(tmp_path: Path) -> TestClient:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "models.yaml").write_text(
        "models:\n  - id: mock-fast\n    adapter: mock\n",
        encoding="utf-8",
    )
    shutil.copy(PROJECT_ROOT / "config" / "modes.yaml", config_dir / "modes.yaml")
    return TestClient(
        create_app(
            data_dir=tmp_path / "data",
            model_config_path=config_dir / "models.yaml",
            modes_config_path=config_dir / "modes.yaml",
            prompt_dir=PROJECT_ROOT / "prompts",
            start_model_health_checks=False,
        )
    )


def create_courtroom(client: TestClient) -> str:
    response = client.post(
        "/meetings",
        json={"title": "土地糾紛案", "goal": "被告是否應返還土地？", "mode_id": "courtroom"},
    )
    assert response.status_code == 200
    return response.json()["meeting_id"]


def test_chairman_can_edit_reorder_and_confirm_a_persistent_courtroom_docket(
    tmp_path: Path,
) -> None:
    client = create_client(tmp_path)
    meeting_id = create_courtroom(client)

    created = client.put(
        f"/meetings/{meeting_id}/courtroom/issues",
        json={
            "revision": 0,
            "issues": [
                {"title": "被告是否無權占有"},
                {"title": "被告是否應返還土地"},
            ],
        },
    )

    assert created.status_code == 200
    assert created.json()["courtroom"] == {
        "schema_version": 1,
        "revision": 1,
        "status": "draft",
        "issues": [
            {"id": "issue-1", "title": "被告是否無權占有", "position": 1, "status": "pending"},
            {"id": "issue-2", "title": "被告是否應返還土地", "position": 2, "status": "pending"},
        ],
        "current_issue_id": None,
        "final_status": "not-ready",
    }

    reordered = client.put(
        f"/meetings/{meeting_id}/courtroom/issues",
        json={
            "revision": 1,
            "issues": [
                {"id": "issue-2", "title": "是否應返還土地及孳息"},
                {"id": "issue-1", "title": "被告是否無權占有"},
            ],
        },
    )
    assert reordered.status_code == 200
    assert [issue["id"] for issue in reordered.json()["courtroom"]["issues"]] == [
        "issue-2",
        "issue-1",
    ]
    assert reordered.json()["courtroom"]["issues"][0]["title"] == "是否應返還土地及孳息"

    confirmed = client.post(
        f"/meetings/{meeting_id}/courtroom/issues/confirm",
        json={"revision": 2},
    )

    assert confirmed.status_code == 200
    assert confirmed.json()["courtroom"]["status"] == "confirmed"
    reloaded = client.get(f"/meetings/{meeting_id}").json()
    assert reloaded["courtroom"] == confirmed.json()["courtroom"]


def test_courtroom_docket_guards_wrong_mode_stale_revision_and_confirmed_edits(
    tmp_path: Path,
) -> None:
    client = create_client(tmp_path)
    ordinary_id = client.post(
        "/meetings",
        json={"title": "一般會議", "goal": "決定方案"},
    ).json()["meeting_id"]
    wrong_mode = client.put(
        f"/meetings/{ordinary_id}/courtroom/issues",
        json={"revision": 0, "issues": [{"title": "不應建立"}]},
    )
    assert wrong_mode.status_code == 400

    meeting_id = create_courtroom(client)
    assert client.post(f"/meetings/{meeting_id}/start", json={}).status_code == 409
    created = client.put(
        f"/meetings/{meeting_id}/courtroom/issues",
        json={"revision": 0, "issues": [{"title": "占有權源"}]},
    )
    assert created.status_code == 200
    stale = client.put(
        f"/meetings/{meeting_id}/courtroom/issues",
        json={"revision": 0, "issues": [{"title": "另一爭點"}]},
    )
    assert stale.status_code == 409
    assert "Stale" in stale.json()["detail"]
    assert client.post(
        f"/meetings/{meeting_id}/courtroom/issues/confirm",
        json={"revision": 1},
    ).status_code == 200
    immutable = client.put(
        f"/meetings/{meeting_id}/courtroom/issues",
        json={"revision": 2, "issues": [{"id": "issue-1", "title": "竄改"}]},
    )
    assert immutable.status_code == 409

    reloaded = client.get(f"/meetings/{meeting_id}").json()
    assert reloaded["courtroom"]["issues"][0]["title"] == "占有權源"
    assert reloaded["events"] == []


def wait_for_courtroom(
    client: TestClient,
    meeting_id: str,
    predicate,
    timeout: float = 5,
) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        meeting = client.get(f"/meetings/{meeting_id}").json()
        if predicate(meeting["courtroom"]):
            return meeting
        time.sleep(0.01)
    raise AssertionError("Courtroom projection did not reach expected state")


def test_ai_draft_remains_editable_and_does_not_confirm_itself(tmp_path: Path) -> None:
    client = create_client(tmp_path)
    meeting_id = create_courtroom(client)

    response = client.post(
        f"/meetings/{meeting_id}/courtroom/issues/draft",
        json={"revision": 0},
    )

    assert response.status_code == 202
    meeting = wait_for_courtroom(
        client,
        meeting_id,
        lambda courtroom: courtroom["status"] == "draft" and courtroom["revision"] == 1,
    )
    assert meeting["courtroom"]["issues"] == [
        {
            "id": "issue-1",
            "title": "Mock generated issue",
            "position": 1,
            "status": "pending",
        }
    ]
    draft_event = next(
        event
        for event in meeting["events"]
        if event.get("interaction_type") == "courtroom-issue-draft"
        and event["status"] == "completed"
    )
    assert draft_event["role"] == "Judge"
    assert draft_event["output_schema_id"] == "courtroom-issue-draft/v1"


def test_each_courtroom_issue_stops_for_ruling_and_final_waits_for_all_rulings(
    tmp_path: Path,
) -> None:
    client = create_client(tmp_path)
    meeting_id = create_courtroom(client)
    client.put(
        f"/meetings/{meeting_id}/courtroom/issues",
        json={
            "revision": 0,
            "issues": [{"title": "占有權源"}, {"title": "返還及孳息"}],
        },
    )
    client.post(
        f"/meetings/{meeting_id}/courtroom/issues/confirm",
        json={"revision": 1},
    )

    started = client.post(
        f"/meetings/{meeting_id}/courtroom/issues/issue-1/arguments"
    )
    assert started.status_code == 202
    after_arguments = wait_for_courtroom(
        client,
        meeting_id,
        lambda courtroom: courtroom["issues"][0]["status"] == "awaiting-ruling",
    )
    issue_events = [
        event
        for event in after_arguments["events"]
        if event.get("issue_id") == "issue-1"
        and event.get("interaction_type") == "courtroom-issue-phase"
        and event["status"] == "completed"
    ]
    assert [(event["issue_phase"], event["role"]) for event in issue_events] == [
        ("charge", "Prosecutor"),
        ("defense", "Defense"),
        ("rebuttal", "Prosecutor"),
    ]
    assert all("占有權源" in event["prompt_messages"][0]["content"] for event in issue_events)
    assert all("返還及孳息" not in event["prompt_messages"][0]["content"] for event in issue_events)
    assert client.post(f"/meetings/{meeting_id}/courtroom/final-verdict").status_code == 409

    assert client.post(
        f"/meetings/{meeting_id}/courtroom/issues/issue-1/ruling"
    ).status_code == 202
    after_ruling = wait_for_courtroom(
        client,
        meeting_id,
        lambda courtroom: courtroom["issues"][0]["status"] == "ruled",
    )
    assert after_ruling["courtroom"]["issues"][0]["ruling"]["outcome"] == "partially-upheld"
    assert after_ruling["courtroom"]["issues"][1]["status"] == "pending"
    assert after_ruling["courtroom"]["current_issue_id"] is None

    assert client.post(
        f"/meetings/{meeting_id}/courtroom/issues/issue-2/arguments"
    ).status_code == 202
    wait_for_courtroom(
        client,
        meeting_id,
        lambda courtroom: courtroom["issues"][1]["status"] == "awaiting-ruling",
    )
    assert client.post(
        f"/meetings/{meeting_id}/courtroom/issues/issue-2/ruling"
    ).status_code == 202
    ready = wait_for_courtroom(
        client,
        meeting_id,
        lambda courtroom: courtroom["final_status"] == "ready",
    )
    assert all(issue["status"] == "ruled" for issue in ready["courtroom"]["issues"])

    assert client.post(f"/meetings/{meeting_id}/courtroom/final-verdict").status_code == 202
    completed = wait_for_courtroom(
        client,
        meeting_id,
        lambda courtroom: courtroom["final_status"] == "completed",
    )
    final_events = [
        event
        for event in completed["events"]
        if event.get("interaction_type") == "courtroom-final-verdict"
        and event["status"] == "completed"
    ]
    assert len(final_events) == 1
    final_prompt = final_events[0]["prompt_messages"][0]["content"]
    assert "占有權源" in final_prompt
    assert "返還及孳息" in final_prompt


def test_confirmed_docket_locks_goal_but_allows_idle_title_change(tmp_path: Path) -> None:
    client = create_client(tmp_path)
    meeting_id = create_courtroom(client)
    client.put(
        f"/meetings/{meeting_id}/courtroom/issues",
        json={"revision": 0, "issues": [{"title": "占有權源"}]},
    )
    client.post(
        f"/meetings/{meeting_id}/courtroom/issues/confirm",
        json={"revision": 1},
    )

    changed_goal = client.put(
        f"/meetings/{meeting_id}/details",
        json={"title": "土地糾紛案（修訂）", "goal": "改判損害賠償？"},
    )
    assert changed_goal.status_code == 409

    changed_title = client.put(
        f"/meetings/{meeting_id}/details",
        json={"title": "土地糾紛案（修訂）", "goal": "被告是否應返還土地？"},
    )
    assert changed_title.status_code == 200
    assert changed_title.json()["title"] == "土地糾紛案（修訂）"
    assert changed_title.json()["goal"] == "被告是否應返還土地？"


def test_running_courtroom_job_rejects_details_assignments_and_messages(tmp_path: Path) -> None:
    client = create_client(tmp_path)
    meeting_id = create_courtroom(client)
    client.put(
        f"/meetings/{meeting_id}/courtroom/issues",
        json={"revision": 0, "issues": [{"title": "占有權源"}]},
    )
    client.post(
        f"/meetings/{meeting_id}/courtroom/issues/confirm",
        json={"revision": 1},
    )
    # Make the assigned mock model observably slow through the public model API.
    assert client.put(
        "/models/mock-fast",
        json={"adapter": "mock", "extra_body": {"mock_delay_ms": 150}},
    ).status_code == 200
    assert client.post(
        f"/meetings/{meeting_id}/courtroom/issues/issue-1/arguments"
    ).status_code == 202

    details = client.put(
        f"/meetings/{meeting_id}/details",
        json={"title": "途中改名", "goal": "被告是否應返還土地？"},
    )
    assignments = client.put(
        f"/meetings/{meeting_id}/participant-models",
        json={
            "models": {
                "Prosecutor": "mock-fast",
                "Defense": "mock-fast",
                "Judge": "mock-fast",
            }
        },
    )
    message = client.post(
        f"/meetings/{meeting_id}/messages",
        json={"content": "途中加入的事實"},
    )
    assert (details.status_code, assignments.status_code, message.status_code) == (409, 409, 409)

    wait_for_courtroom(
        client,
        meeting_id,
        lambda courtroom: courtroom["issues"][0]["status"] == "awaiting-ruling",
    )


def test_failed_issue_phase_retry_preserves_issue_revision_and_continues_arguments(
    tmp_path: Path,
) -> None:
    client = create_client(tmp_path)
    meeting_id = create_courtroom(client)
    client.put(
        f"/meetings/{meeting_id}/courtroom/issues",
        json={"revision": 0, "issues": [{"title": "占有權源"}]},
    )
    client.post(
        f"/meetings/{meeting_id}/courtroom/issues/confirm",
        json={"revision": 1},
    )
    client.put(
        "/models/mock-fast",
        json={"adapter": "mock", "extra_body": {"mock_error": "planned failure"}},
    )
    client.post(f"/meetings/{meeting_id}/courtroom/issues/issue-1/arguments")
    failed = wait_for_courtroom(
        client,
        meeting_id,
        lambda courtroom: courtroom["issues"][0]["status"] == "arguments-in-progress",
    )
    failed_charge = next(
        event
        for event in failed["events"]
        if event.get("issue_phase") == "charge" and event["status"] == "failed"
    )
    client.put(
        "/models/mock-fast",
        json={"adapter": "mock", "extra_body": {}},
    )

    retry = client.post(
        f"/meetings/{meeting_id}/steps/{failed_charge['step_id']}/retry",
        json={},
    )
    assert retry.status_code in {200, 202}
    completed = wait_for_courtroom(
        client,
        meeting_id,
        lambda courtroom: courtroom["issues"][0]["status"] == "awaiting-ruling",
    )
    charge_attempts = [
        event
        for event in completed["events"]
        if event.get("issue_phase") == "charge"
    ]
    assert [(event["attempt"], event["status"]) for event in charge_attempts] == [
        (1, "failed"),
        (2, "completed"),
    ]
    assert {event["issue_id"] for event in charge_attempts} == {"issue-1"}
    assert {event["docket_revision"] for event in charge_attempts} == {2}


def test_concurrent_issue_submit_reserves_only_one_argument_flow(tmp_path: Path) -> None:
    client = create_client(tmp_path)
    meeting_id = create_courtroom(client)
    client.put(
        f"/meetings/{meeting_id}/courtroom/issues",
        json={"revision": 0, "issues": [{"title": "占有權源"}]},
    )
    client.post(
        f"/meetings/{meeting_id}/courtroom/issues/confirm",
        json={"revision": 1},
    )
    client.put(
        "/models/mock-fast",
        json={"adapter": "mock", "extra_body": {"mock_delay_ms": 100}},
    )

    first = client.post(f"/meetings/{meeting_id}/courtroom/issues/issue-1/arguments")
    second = client.post(f"/meetings/{meeting_id}/courtroom/issues/issue-1/arguments")

    assert first.status_code == 202
    assert second.status_code == 409
    meeting = wait_for_courtroom(
        client,
        meeting_id,
        lambda courtroom: courtroom["issues"][0]["status"] == "awaiting-ruling",
    )
    completed_charge = [
        event
        for event in meeting["events"]
        if event.get("issue_phase") == "charge" and event["status"] == "completed"
    ]
    assert len(completed_charge) == 1


def test_legacy_courtroom_cannot_bypass_docket_and_preserves_existing_events(
    tmp_path: Path,
) -> None:
    client = create_client(tmp_path)
    meeting_id = create_courtroom(client)
    assert client.post(
        f"/meetings/{meeting_id}/messages",
        json={"content": "既有主席紀錄"},
    ).status_code == 200
    before = client.get(f"/meetings/{meeting_id}").json()["events"]

    start = client.post(f"/meetings/{meeting_id}/start", json={})
    sequence = client.post(
        f"/meetings/{meeting_id}/sequences",
        json={"roles": ["Prosecutor", "Defense"]},
    )
    final = client.post(f"/meetings/{meeting_id}/courtroom/final-verdict")

    assert (start.status_code, sequence.status_code, final.status_code) == (409, 409, 409)
    assert client.get(f"/meetings/{meeting_id}").json()["events"] == before


def test_unconfirmed_courtroom_goal_change_after_ai_output_appends_audit_event(
    tmp_path: Path,
) -> None:
    client = create_client(tmp_path)
    meeting_id = create_courtroom(client)
    client.post(
        f"/meetings/{meeting_id}/roles/Prosecutor/respond",
        json={"instruction": "先整理卷宗"},
    )
    before = client.get(f"/meetings/{meeting_id}").json()["events"]

    changed = client.put(
        f"/meetings/{meeting_id}/details",
        json={"title": "土地糾紛案", "goal": "被告是否應返還土地及孳息？"},
    )

    assert changed.status_code == 200
    after = client.get(f"/meetings/{meeting_id}").json()["events"]
    assert after[:-1] == before
    assert after[-1]["interaction_type"] == "meeting-goal-changed"
    assert after[-1]["previous_goal"] == "被告是否應返還土地？"
    assert after[-1]["goal"] == "被告是否應返還土地及孳息？"
