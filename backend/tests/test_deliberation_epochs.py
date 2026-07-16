from __future__ import annotations

from ai_council.meetings.deliberation import DeliberationEpochs, RestartCommand


def completed(event_id: str, *, issue_id: str | None = None, phase: str | None = None):
    event = {
        "event_id": event_id,
        "step_id": event_id,
        "role": "Judge",
        "status": "completed",
        "parsed_output": {"summary": event_id},
    }
    if issue_id is not None:
        event.update(
            {
                "interaction_type": "courtroom-issue-phase",
                "docket_revision": 2,
                "issue_id": issue_id,
                "issue_phase": phase,
            }
        )
    return event


def test_legacy_events_form_an_implicit_first_epoch_without_backfill() -> None:
    raw = [completed("legacy-one"), completed("legacy-two")]

    view = DeliberationEpochs.view(raw)

    assert view.active_epoch.number == 1
    assert view.active_epoch.implicit is True
    assert view.active_events == raw
    assert len(view.epochs) == 1


def test_blank_restart_reason_is_rejected() -> None:
    try:
        RestartCommand(scope="all_deliberation", reason="  ")
    except ValueError as error:
        assert str(error) == "Restart reason must not be blank"
    else:
        raise AssertionError("blank restart reason was accepted")


def test_all_deliberation_archives_every_prior_discussion_event() -> None:
    marker = DeliberationEpochs.restart_marker(
        meeting_id="meeting-1",
        events=[completed("old")],
        command=RestartCommand(scope="all_deliberation", reason="改用新模型"),
    )
    new_event = completed("new")

    view = DeliberationEpochs.view([completed("old"), marker, new_event])

    assert [event["event_id"] for event in view.active_events] == ["new"]
    assert [epoch.reason for epoch in view.epochs] == [None, "改用新模型"]
    assert view.active_epoch.number == 2


def test_current_issue_restart_carries_only_other_completed_issue_rulings() -> None:
    issue_one = completed("issue-one-ruling", issue_id="issue-1", phase="ruling")
    issue_two = completed("issue-two-ruling", issue_id="issue-2", phase="ruling")
    final = {
        **completed("final"),
        "interaction_type": "courtroom-final-verdict",
        "docket_revision": 2,
    }
    marker = DeliberationEpochs.restart_marker(
        meeting_id="meeting-1",
        events=[issue_one, issue_two, final],
        command=RestartCommand(
            scope="current_issue", reason="補充答辯", issue_id="issue-2"
        ),
    )

    view = DeliberationEpochs.view([issue_one, issue_two, final, marker])

    assert view.active_events == []
    assert [event["event_id"] for event in view.workflow_events] == [
        "issue-one-ruling"
    ]
    assert marker["carry_forward"][0]["issue_id"] == "issue-1"


def test_new_epoch_event_identity_namespaces_attempts_without_changing_step_id() -> None:
    marker = DeliberationEpochs.restart_marker(
        meeting_id="meeting-1",
        events=[completed("old")],
        command=RestartCommand(scope="all_deliberation", reason="重跑"),
    )
    view = DeliberationEpochs.view([completed("old"), marker])

    assert view.event_id("meeting-1:blue-propose:attempt-1:completed").startswith(
        f"{view.active_epoch.id}:"
    )
    assert view.event_step_id("blue-propose") == "blue-propose"
