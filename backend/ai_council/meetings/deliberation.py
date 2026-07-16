from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal


EPOCH_MARKER_INTERACTION = "deliberation-epoch-start"
EPOCH_SCHEMA_VERSION = 1
RestartScope = Literal["current_issue", "all_deliberation", "rebuild_issues"]


@dataclass(frozen=True)
class RestartCommand:
    scope: RestartScope
    reason: str
    issue_id: str | None = None

    def __post_init__(self) -> None:
        reason = self.reason.strip()
        if not reason:
            raise ValueError("Restart reason must not be blank")
        object.__setattr__(self, "reason", reason)
        if self.scope == "current_issue" and not self.issue_id:
            raise ValueError("Current issue restart requires issue_id")
        if self.scope != "current_issue" and self.issue_id is not None:
            raise ValueError("issue_id is only valid for current issue restart")


@dataclass(frozen=True)
class DeliberationEpoch:
    id: str
    number: int
    reason: str | None
    scope: RestartScope | None
    issue_id: str | None
    implicit: bool
    marker: dict[str, Any] | None
    events: list[dict[str, Any]]


@dataclass(frozen=True)
class DeliberationView:
    all_events: list[dict[str, Any]]
    active_events: list[dict[str, Any]]
    workflow_events: list[dict[str, Any]]
    epochs: list[DeliberationEpoch]
    active_epoch: DeliberationEpoch

    def event_id(self, legacy_event_id: str) -> str:
        if self.active_epoch.number == 1:
            return legacy_event_id
        prefix = f"{self.active_epoch.id}:"
        return legacy_event_id if legacy_event_id.startswith(prefix) else prefix + legacy_event_id

    @staticmethod
    def event_step_id(step_id: str) -> str:
        return step_id


class DeliberationEpochs:
    """Projects an append-only event journal into live and historical deliberations."""

    @staticmethod
    def view(events: list[dict[str, Any]]) -> DeliberationView:
        epochs: list[DeliberationEpoch] = []
        current_events: list[dict[str, Any]] = []
        current_marker: dict[str, Any] | None = None

        def finish_epoch() -> None:
            nonlocal current_events, current_marker
            number = len(epochs) + 1
            if current_marker is None:
                epoch_id = "epoch-1"
                reason = None
                scope = None
                issue_id = None
                implicit = True
            else:
                epoch_id = str(current_marker["epoch_id"])
                reason = str(current_marker.get("restart_reason") or "") or None
                scope = current_marker.get("restart_scope")
                issue_id = current_marker.get("issue_id")
                implicit = False
            epochs.append(
                DeliberationEpoch(
                    id=epoch_id,
                    number=number,
                    reason=reason,
                    scope=scope,
                    issue_id=str(issue_id) if issue_id is not None else None,
                    implicit=implicit,
                    marker=current_marker,
                    events=current_events,
                )
            )
            current_events = []

        for event in events:
            if event.get("interaction_type") == EPOCH_MARKER_INTERACTION:
                finish_epoch()
                current_marker = event
            else:
                current_events.append(event)
        finish_epoch()
        active = epochs[-1]
        carried = []
        if active.marker is not None and isinstance(active.marker.get("carry_forward"), list):
            carried = [
                dict(event)
                for event in active.marker["carry_forward"]
                if isinstance(event, dict)
            ]
        return DeliberationView(
            all_events=list(events),
            active_events=list(active.events),
            workflow_events=carried + list(active.events),
            epochs=epochs,
            active_epoch=active,
        )

    @classmethod
    def restart_marker(
        cls,
        *,
        meeting_id: str,
        events: list[dict[str, Any]],
        command: RestartCommand,
        snapshot: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        view = cls.view(events)
        epoch_id = f"epoch-{uuid.uuid4().hex}"
        carry_forward = (
            cls._current_issue_carry_forward(view.workflow_events, command.issue_id)
            if command.scope == "current_issue"
            else []
        )
        return {
            "event_id": f"{meeting_id}:deliberation:{epoch_id}:start",
            "meeting_id": meeting_id,
            "step_id": "deliberation-restart",
            "role": "System",
            "attempt": 1,
            "status": "completed",
            "interaction_type": EPOCH_MARKER_INTERACTION,
            "schema_version": EPOCH_SCHEMA_VERSION,
            "epoch_id": epoch_id,
            "epoch_number": view.active_epoch.number + 1,
            "previous_epoch_id": view.active_epoch.id,
            "restart_scope": command.scope,
            "restart_reason": command.reason,
            "issue_id": command.issue_id,
            "carry_forward": carry_forward,
            "snapshot": dict(snapshot or {}),
        }

    @staticmethod
    def _current_issue_carry_forward(
        events: list[dict[str, Any]], target_issue_id: str | None
    ) -> list[dict[str, Any]]:
        latest_by_issue: dict[str, dict[str, Any]] = {}
        for event in events:
            if (
                event.get("interaction_type") == "courtroom-issue-phase"
                and event.get("issue_phase") == "ruling"
                and event.get("status") == "completed"
                and event.get("issue_id") != target_issue_id
            ):
                latest_by_issue[str(event.get("issue_id"))] = event
        allowed = {
            "event_id",
            "meeting_id",
            "step_id",
            "base_step_id",
            "role",
            "attempt",
            "status",
            "interaction_type",
            "docket_revision",
            "issue_id",
            "issue_phase",
            "parsed_output",
            "output_schema_id",
            "created_at",
            "materials_revision",
            "materials_refs",
        }
        return [
            {key: value for key, value in event.items() if key in allowed}
            for event in latest_by_issue.values()
        ]
