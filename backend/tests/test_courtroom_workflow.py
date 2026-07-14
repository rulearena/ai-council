from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ai_council.api import create_app
from ai_council.meetings.courtroom import project_courtroom


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
        "available_actions": ["draft-issues", "edit-issues", "confirm-issues"],
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
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        settled_arguments = client.get(f"/meetings/{meeting_id}").json()
        if settled_arguments["activity_status"] != "running":
            break
        time.sleep(0.01)
    assert settled_arguments["activity_status"] == "completed"
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
        lambda courtroom: courtroom["issues"][0]["status"] == "failed",
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
        f"/meetings/{meeting_id}/courtroom/issues/draft",
        json={"revision": 0},
    )
    wait_for_courtroom(
        client,
        meeting_id,
        lambda courtroom: courtroom["status"] == "draft",
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
    assert after[-1]["content"] == (
        "主席修改會議目標\n"
        "舊目標：被告是否應返還土地？\n"
        "新目標：被告是否應返還土地及孳息？"
    )
    transcript = client.get(f"/meetings/{meeting_id}/transcript.md")
    assert transcript.status_code == 200
    assert "## 主席 - 主席修改會議目標" in transcript.text
    assert "舊目標：被告是否應返還土地？" in transcript.text
    assert "新目標：被告是否應返還土地及孳息？" in transcript.text


def test_restart_preserves_issue_linkage_for_an_interrupted_courtroom_attempt(
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
    execution_path = tmp_path / "data" / "meetings" / meeting_id / "execution.json"
    execution_path.write_text(
        json.dumps(
            {
                "meeting_id": meeting_id,
                "step_id": "courtroom-r2-issue-1-charge",
                "base_step_id": "courtroom-issue-charge",
                "round": 1,
                "role": "Prosecutor",
                "attempt": 1,
                "model_config_id": "mock-fast",
                "status": "running",
                "interaction_type": "courtroom-issue-phase",
                "docket_revision": 2,
                "issue_id": "issue-1",
                "issue_phase": "charge",
            }
        ),
        encoding="utf-8",
    )

    restarted = TestClient(
        create_app(
            data_dir=tmp_path / "data",
            model_config_path=tmp_path / "config" / "models.yaml",
            modes_config_path=tmp_path / "config" / "modes.yaml",
            prompt_dir=PROJECT_ROOT / "prompts",
            start_model_health_checks=False,
        )
    )

    event = restarted.get(f"/meetings/{meeting_id}").json()["events"][-1]
    assert event["failure_kind"] == "interrupted"
    assert event["docket_revision"] == 2
    assert event["issue_id"] == "issue-1"
    assert event["issue_phase"] == "charge"


def test_failed_final_verdict_can_only_retry_the_linked_final_flow(tmp_path: Path) -> None:
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
    client.post(f"/meetings/{meeting_id}/courtroom/issues/issue-1/arguments")
    wait_for_courtroom(
        client,
        meeting_id,
        lambda courtroom: courtroom["issues"][0]["status"] == "awaiting-ruling",
    )
    client.post(f"/meetings/{meeting_id}/courtroom/issues/issue-1/ruling")
    wait_for_courtroom(
        client,
        meeting_id,
        lambda courtroom: courtroom["final_status"] == "ready",
    )
    client.put(
        "/models/mock-fast",
        json={"adapter": "mock", "extra_body": {"mock_error": "final failed"}},
    )
    assert client.post(f"/meetings/{meeting_id}/courtroom/final-verdict").status_code == 202
    failed = wait_for_courtroom(
        client,
        meeting_id,
        lambda courtroom: courtroom["final_status"] == "failed",
    )
    failed_final = next(
        event
        for event in failed["events"]
        if event.get("interaction_type") == "courtroom-final-verdict"
        and event["status"] == "failed"
    )
    assert client.post(f"/meetings/{meeting_id}/courtroom/final-verdict").status_code == 409
    client.put("/models/mock-fast", json={"adapter": "mock", "extra_body": {}})
    time.sleep(0.02)

    retry = client.post(
        f"/meetings/{meeting_id}/steps/{failed_final['step_id']}/retry",
        json={},
    )
    assert retry.status_code == 202
    completed = wait_for_courtroom(
        client,
        meeting_id,
        lambda courtroom: courtroom["final_status"] == "completed",
    )
    final_attempts = [
        event
        for event in completed["events"]
        if event.get("interaction_type") == "courtroom-final-verdict"
    ]
    assert [(event["attempt"], event["status"]) for event in final_attempts] == [
        (1, "failed"),
        (2, "completed"),
    ]
    reservations = [
        event
        for event in completed["events"]
        if event.get("courtroom_operation") == "final-verdict"
    ]
    assert len(reservations) == 1


@pytest.mark.parametrize("failed_phase", ["charge", "defense", "rebuttal", "ruling"])
def test_latest_failed_issue_phase_overrides_prior_completed_attempts(
    failed_phase: str,
) -> None:
    metadata = {
        "mode_id": "courtroom",
        "courtroom_docket": {
            "schema_version": 1,
            "revision": 2,
            "confirmed": True,
            "next_issue_number": 2,
            "issues": [{"id": "issue-1", "title": "占有權源"}],
        },
    }
    phases = ["charge", "defense", "rebuttal", "ruling"]
    events = []
    for phase in phases[: phases.index(failed_phase) + 1]:
        events.append(
            {
                "step_id": f"courtroom-r2-issue-1-{phase}",
                "interaction_type": "courtroom-issue-phase",
                "docket_revision": 2,
                "issue_id": "issue-1",
                "issue_phase": phase,
                "attempt": 1,
                "status": "completed",
                "parsed_output": {"outcome": "proponent-wins"} if phase == "ruling" else {},
            }
        )
    events.append(
        {
            "step_id": f"courtroom-r2-issue-1-{failed_phase}",
            "interaction_type": "courtroom-issue-phase",
            "docket_revision": 2,
            "issue_id": "issue-1",
            "issue_phase": failed_phase,
            "attempt": 2,
            "status": "failed",
            "failure_kind": "timeout",
        }
    )

    projected = project_courtroom(metadata, events)

    assert projected is not None
    assert projected["issues"][0]["status"] == "failed"
    assert projected["issues"][0]["failed_step_id"] == (
        f"courtroom-r2-issue-1-{failed_phase}"
    )
    assert projected["issues"][0]["failed_phase"] == failed_phase
    assert projected["available_actions"] == ["retry-failed-step"]


def test_failed_ruling_requires_retry_and_reuses_the_original_step(tmp_path: Path) -> None:
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
    client.post(f"/meetings/{meeting_id}/courtroom/issues/issue-1/arguments")
    wait_for_courtroom(
        client,
        meeting_id,
        lambda courtroom: courtroom["issues"][0]["status"] == "awaiting-ruling",
    )
    client.put(
        "/models/mock-fast",
        json={"adapter": "mock", "extra_body": {"mock_error": "ruling timeout"}},
    )
    assert client.post(
        f"/meetings/{meeting_id}/courtroom/issues/issue-1/ruling"
    ).status_code == 202
    failed = wait_for_courtroom(
        client,
        meeting_id,
        lambda courtroom: courtroom["issues"][0]["status"] == "failed",
    )
    failed_ruling = next(
        event
        for event in failed["events"]
        if event.get("issue_phase") == "ruling" and event["status"] == "failed"
    )
    assert failed["courtroom"]["available_actions"] == ["retry-failed-step"]
    assert client.post(
        f"/meetings/{meeting_id}/courtroom/issues/issue-1/ruling"
    ).status_code == 409

    client.put("/models/mock-fast", json={"adapter": "mock", "extra_body": {}})
    time.sleep(0.02)
    assert client.post(
        f"/meetings/{meeting_id}/steps/{failed_ruling['step_id']}/retry",
        json={},
    ).status_code == 202
    completed = wait_for_courtroom(
        client,
        meeting_id,
        lambda courtroom: courtroom["issues"][0]["status"] == "ruled",
    )
    attempts = [
        event
        for event in completed["events"]
        if event.get("issue_phase") == "ruling"
    ]
    assert [(event["step_id"], event["attempt"], event["status"]) for event in attempts] == [
        (failed_ruling["step_id"], 1, "failed"),
        (failed_ruling["step_id"], 2, "completed"),
    ]


def test_directed_courtroom_response_is_only_available_during_ruling_pause(
    tmp_path: Path,
) -> None:
    client = create_client(tmp_path)
    meeting_id = create_courtroom(client)

    before = client.get(f"/meetings/{meeting_id}").json()["events"]
    unconfigured = client.post(
        f"/meetings/{meeting_id}/roles/Prosecutor/respond",
        json={"instruction": "請釐清占有權源"},
    )
    assert unconfigured.status_code == 409
    assert client.get(f"/meetings/{meeting_id}").json()["events"] == before

    client.put(
        f"/meetings/{meeting_id}/courtroom/issues",
        json={"revision": 0, "issues": [{"title": "占有權源"}]},
    )
    client.post(
        f"/meetings/{meeting_id}/courtroom/issues/confirm",
        json={"revision": 1},
    )
    pending_meeting = client.get(f"/meetings/{meeting_id}").json()
    assert pending_meeting["courtroom"]["available_actions"] == ["start-issue", "add-note"]
    pending_events = pending_meeting["events"]
    pending = client.post(
        f"/meetings/{meeting_id}/roles/Defense/respond",
        json={"instruction": "請先答辯"},
    )
    assert pending.status_code == 409
    assert client.get(f"/meetings/{meeting_id}").json()["events"] == pending_events

    client.post(f"/meetings/{meeting_id}/courtroom/issues/issue-1/arguments")
    paused = wait_for_courtroom(
        client,
        meeting_id,
        lambda courtroom: courtroom["issues"][0]["status"] == "awaiting-ruling",
    )
    assert paused["courtroom"]["available_actions"] == [
        "submit-ruling",
        "add-note",
        "directed-response",
    ]
    directed = client.post(
        f"/meetings/{meeting_id}/roles/Defense/respond",
        json={"instruction": "哪些證據支持辯方？"},
    )
    assert directed.status_code == 202
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        after_directed = client.get(f"/meetings/{meeting_id}").json()
        directed_events = [
            event
            for event in after_directed["events"]
            if event.get("interaction_type") == "directed-role-response"
        ]
        if directed_events and directed_events[-1]["status"] == "completed":
            break
        time.sleep(0.01)
    else:
        raise AssertionError("Directed response did not complete")
    linked = after_directed["events"][-2:]
    assert [event["interaction_type"] for event in linked] == [
        "directed-role-instruction",
        "directed-role-response",
    ]
    assert {event["docket_revision"] for event in linked} == {2}
    assert {event["issue_id"] for event in linked} == {"issue-1"}
    assert after_directed["courtroom"]["issues"][0]["status"] == "awaiting-ruling"

    client.post(f"/meetings/{meeting_id}/courtroom/issues/issue-1/ruling")
    ruled = wait_for_courtroom(
        client,
        meeting_id,
        lambda courtroom: courtroom["issues"][0]["status"] == "ruled",
    )
    assert ruled["courtroom"]["available_actions"] == ["final-verdict"]
    ruled_events = ruled["events"]
    between = client.post(
        f"/meetings/{meeting_id}/roles/Judge/respond",
        json={"instruction": "請再說明"},
    )
    assert between.status_code == 409
    assert client.get(f"/meetings/{meeting_id}").json()["events"] == ruled_events

    client.post(f"/meetings/{meeting_id}/courtroom/final-verdict")
    completed = wait_for_courtroom(
        client,
        meeting_id,
        lambda courtroom: courtroom["final_status"] == "completed",
    )
    final_event = next(
        event
        for event in completed["events"]
        if event.get("interaction_type") == "courtroom-final-verdict"
        and event["status"] == "completed"
    )
    assert "哪些證據支持辯方？" in final_event["prompt_messages"][0]["content"]
    completed_events = completed["events"]
    after_final = client.post(
        f"/meetings/{meeting_id}/roles/Prosecutor/respond",
        json={"instruction": "最終追問"},
    )
    assert after_final.status_code == 409
    assert client.get(f"/meetings/{meeting_id}").json()["events"] == completed_events


def test_slow_directed_response_reserves_the_meeting_against_conflicting_writes(
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
    client.post(f"/meetings/{meeting_id}/courtroom/issues/issue-1/arguments")
    wait_for_courtroom(
        client,
        meeting_id,
        lambda courtroom: courtroom["issues"][0]["status"] == "awaiting-ruling",
    )
    client.put(
        "/models/mock-fast",
        json={"adapter": "mock", "extra_body": {"mock_delay_ms": 200}},
    )

    first = client.post(
        f"/meetings/{meeting_id}/roles/Defense/respond",
        json={"instruction": "請說明辯方證據"},
    )
    second = client.post(
        f"/meetings/{meeting_id}/roles/Prosecutor/respond",
        json={"instruction": "請補充控方主張"},
    )
    ruling = client.post(f"/meetings/{meeting_id}/courtroom/issues/issue-1/ruling")
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
        json={"content": "途中補充"},
    )

    assert first.status_code == 202
    assert (second.status_code, ruling.status_code) == (409, 409)
    assert (details.status_code, assignments.status_code, message.status_code) == (409, 409, 409)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        events = client.get(f"/meetings/{meeting_id}").json()["events"]
        directed = [
            event
            for event in events
            if event.get("interaction_type")
            in {"directed-role-instruction", "directed-role-response"}
        ]
        if len(directed) == 2 and directed[-1]["status"] == "completed":
            break
        time.sleep(0.01)
    else:
        raise AssertionError("Directed response did not complete")
    assert [event["interaction_type"] for event in directed] == [
        "directed-role-instruction",
        "directed-role-response",
    ]
    assert [event["role"] for event in directed] == ["Human", "Defense"]
    assert client.post(
        f"/meetings/{meeting_id}/courtroom/issues/issue-1/ruling"
    ).status_code == 202


def test_failed_courtroom_directed_response_retry_reuses_instruction_and_issue_context(
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
    client.post(f"/meetings/{meeting_id}/courtroom/issues/issue-1/arguments")
    wait_for_courtroom(
        client,
        meeting_id,
        lambda courtroom: courtroom["issues"][0]["status"] == "awaiting-ruling",
    )
    client.put(
        "/models/mock-fast",
        json={"adapter": "mock", "extra_body": {"mock_error": "directed timeout"}},
    )
    assert client.post(
        f"/meetings/{meeting_id}/roles/Defense/respond",
        json={"instruction": "請指出關鍵反證"},
    ).status_code in {200, 202}
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        failed_meeting = client.get(f"/meetings/{meeting_id}").json()
        failed_responses = [
            event
            for event in failed_meeting["events"]
            if event.get("interaction_type") == "directed-role-response"
            and event["status"] == "failed"
        ]
        if failed_responses:
            break
        time.sleep(0.01)
    else:
        raise AssertionError("Directed response did not fail")
    failed = failed_responses[-1]
    instruction_events = [
        event
        for event in failed_meeting["events"]
        if event.get("interaction_type") == "directed-role-instruction"
    ]
    assert len(instruction_events) == 1
    instruction_id = instruction_events[0]["event_id"]
    client.put("/models/mock-fast", json={"adapter": "mock", "extra_body": {}})
    time.sleep(0.02)

    retry = client.post(
        f"/meetings/{meeting_id}/steps/{failed['step_id']}/retry",
        json={},
    )
    assert retry.status_code == 202
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        completed_meeting = client.get(f"/meetings/{meeting_id}").json()
        responses = [
            event
            for event in completed_meeting["events"]
            if event.get("interaction_type") == "directed-role-response"
        ]
        if responses and responses[-1]["status"] == "completed":
            break
        time.sleep(0.01)
    else:
        raise AssertionError("Directed response retry did not complete")
    assert len(
        [
            event
            for event in completed_meeting["events"]
            if event.get("interaction_type") == "directed-role-instruction"
        ]
    ) == 1
    assert [(event["attempt"], event["status"]) for event in responses] == [
        (1, "failed"),
        (2, "completed"),
    ]
    assert {event["in_response_to_event_id"] for event in responses} == {instruction_id}
    assert {event["issue_id"] for event in responses} == {"issue-1"}
    assert {event["docket_revision"] for event in responses} == {2}
