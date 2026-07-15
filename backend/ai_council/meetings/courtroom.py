from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from ai_council.meetings.repository import MeetingRepository
from ai_council.meetings.case_profiles import (
    CourtroomCaseProfile,
    CourtroomCaseProfileError,
    CourtroomStepProfile,
)
from ai_council.meetings.deliberation import DeliberationEpochs
from ai_council.meetings.runner import MeetingRunner, StepDefinition
from ai_council.models.config import ModelConfig


DOCKET_SCHEMA_VERSION = 1


def project_courtroom(
    metadata: dict[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if metadata.get("mode_id") != "courtroom":
        return None
    try:
        profile = CourtroomCaseProfile.for_metadata(metadata)
    except CourtroomCaseProfileError:
        profile = None
    docket = metadata.get("courtroom_docket")
    if not isinstance(docket, dict):
        return {
            "schema_version": DOCKET_SCHEMA_VERSION,
            "revision": 0,
            "status": "not-configured",
            "issues": [],
            "current_issue_id": None,
            "final_status": "not-ready",
            "available_actions": ["draft-issues", "edit-issues"],
            "case_type": profile.case_type if profile else None,
            "requires_case_type": profile is None,
        }
    confirmed = bool(docket.get("confirmed"))
    revision = int(docket.get("revision", 0))
    issues = []
    current_issue_id = None
    for position, issue in enumerate(docket.get("issues") or [], start=1):
        issue_id = str(issue["id"])
        phase_events = {
            phase: _latest_phase_event(events, revision, issue_id, phase)
            for phase in ("charge", "defense", "rebuttal", "ruling")
        }
        latest_failed = next(
            (
                event
                for event in reversed(list(phase_events.values()))
                if event is not None and event.get("status") == "failed"
            ),
            None,
        )
        if latest_failed is not None:
            status = "failed"
            current_issue_id = issue_id
        elif (phase_events["ruling"] or {}).get("status") == "completed":
            status = "ruled"
        elif (phase_events["rebuttal"] or {}).get("status") == "completed":
            status = "awaiting-ruling"
            current_issue_id = issue_id
        elif any(value is not None for value in phase_events.values()):
            status = "arguments-in-progress"
            current_issue_id = issue_id
        else:
            status = "pending"
        projected_issue: dict[str, Any] = {
            "id": issue_id,
            "title": str(issue["title"]),
            "position": position,
            "status": status,
        }
        if latest_failed is not None:
            projected_issue.update(
                {
                    "failed_step_id": str(latest_failed.get("step_id", "")),
                    "failed_phase": str(latest_failed.get("issue_phase", "")),
                    "failure_kind": latest_failed.get("failure_kind"),
                }
            )
        ruling = phase_events["ruling"]
        if ruling is not None and ruling.get("status") == "completed":
            projected_issue["ruling"] = ruling.get("parsed_output")
        issues.append(projected_issue)
    all_ruled = bool(issues) and all(issue["status"] == "ruled" for issue in issues)
    final_event = _latest_final_event(events, revision)
    final_status = (
        "completed"
        if final_event is not None and final_event.get("status") == "completed"
        else "failed"
        if final_event is not None and final_event.get("status") == "failed"
        else "ready"
        if confirmed and all_ruled
        else "not-ready"
    )
    if not confirmed:
        available_actions = ["draft-issues", "edit-issues", "confirm-issues"]
    elif final_status == "ready":
        available_actions = ["final-verdict"]
    elif final_status == "failed":
        available_actions = ["retry-failed-step"]
    elif current_issue_id is not None:
        current = next(issue for issue in issues if issue["id"] == current_issue_id)
        available_actions = (
            ["submit-ruling", "add-note", "directed-response"]
            if current["status"] == "awaiting-ruling"
            else ["retry-failed-step"]
        )
    elif any(issue["status"] == "pending" for issue in issues):
        available_actions = ["start-issue", "add-note"]
    else:
        available_actions = []
    projection = {
        "schema_version": DOCKET_SCHEMA_VERSION,
        "revision": revision,
        "status": "confirmed" if confirmed else "draft",
        "issues": issues,
        "current_issue_id": current_issue_id,
        "final_status": final_status,
        "available_actions": available_actions,
        "case_type": profile.case_type if profile else None,
        "requires_case_type": profile is None,
    }
    if final_status == "failed" and final_event is not None:
        projection["failed_step_id"] = str(final_event.get("step_id", ""))
    return projection


def _latest_phase_event(
    events: list[dict[str, Any]], revision: int, issue_id: str, phase: str
) -> dict[str, Any] | None:
    matching = [
        event
        for event in events
        if event.get("interaction_type") == "courtroom-issue-phase"
        and event.get("docket_revision") == revision
        and event.get("issue_id") == issue_id
        and event.get("issue_phase") == phase
    ]
    return matching[-1] if matching else None


def _latest_final_event(
    events: list[dict[str, Any]], revision: int
) -> dict[str, Any] | None:
    matching = [
        event
        for event in events
        if event.get("interaction_type") == "courtroom-final-verdict"
        and event.get("docket_revision") == revision
    ]
    return matching[-1] if matching else None


class MetadataStore(Protocol):
    def get(self, meeting_id: str) -> dict[str, Any]: ...

    def update(
        self,
        meeting_id: str,
        transform: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class CourtroomWorkflowError(ValueError):
    detail: str
    status_code: int = 409

    def __str__(self) -> str:
        return self.detail


class CourtroomWorkflowService:
    """Owns the persistent courtroom docket and its legal transitions."""

    def __init__(self, metadata_store: MetadataStore, repository: MeetingRepository) -> None:
        self.metadata_store = metadata_store
        self.repository = repository
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()

    def project(self, metadata: dict[str, Any], events: list[dict[str, Any]]) -> dict[str, Any] | None:
        return project_courtroom(metadata, events)

    def replace_issues(
        self,
        meeting_id: str,
        *,
        expected_revision: int,
        requested_issues: list[dict[str, Any]],
    ) -> dict[str, Any]:
        with self._meeting_lock(meeting_id):
            metadata = self._require_courtroom(meeting_id)
            docket = self._docket(metadata)
            if bool(docket.get("confirmed")):
                raise CourtroomWorkflowError("Confirmed courtroom issues are read-only")
            self._require_revision(docket, expected_revision)
            existing = {
                str(issue["id"]): issue
                for issue in docket.get("issues") or []
                if isinstance(issue, dict) and issue.get("id")
            }
            next_number = int(docket.get("next_issue_number", 1))
            normalized: list[dict[str, str]] = []
            seen_ids: set[str] = set()
            seen_titles: set[str] = set()
            for requested in requested_issues:
                title = str(requested.get("title", "")).strip()
                if not title:
                    raise CourtroomWorkflowError("Courtroom issue title must not be blank", 422)
                if title in seen_titles:
                    raise CourtroomWorkflowError("Courtroom issue titles must be unique", 422)
                issue_id = requested.get("id")
                if issue_id is None:
                    issue_id = f"issue-{next_number}"
                    next_number += 1
                issue_id = str(issue_id)
                if issue_id not in existing and requested.get("id") is not None:
                    raise CourtroomWorkflowError(f"Unknown courtroom issue: {issue_id}", 400)
                if issue_id in seen_ids:
                    raise CourtroomWorkflowError(f"Duplicate courtroom issue: {issue_id}", 422)
                seen_ids.add(issue_id)
                seen_titles.add(title)
                normalized.append({"id": issue_id, "title": title})
            if not normalized:
                raise CourtroomWorkflowError("Courtroom docket requires at least one issue", 422)
            updated_docket = {
                "schema_version": DOCKET_SCHEMA_VERSION,
                "revision": expected_revision + 1,
                "confirmed": False,
                "next_issue_number": next_number,
                "issues": normalized,
            }
            return self.metadata_store.update(
                meeting_id,
                lambda current: {**current, "courtroom_docket": updated_docket},
            )

    def confirm_issues(self, meeting_id: str, *, expected_revision: int) -> dict[str, Any]:
        with self._meeting_lock(meeting_id):
            metadata = self._require_courtroom(meeting_id)
            docket = self._docket(metadata)
            if bool(docket.get("confirmed")):
                raise CourtroomWorkflowError("Courtroom issues are already confirmed")
            self._require_revision(docket, expected_revision)
            if not docket.get("issues"):
                raise CourtroomWorkflowError("Courtroom docket requires at least one issue", 422)
            updated_docket = {
                **docket,
                "revision": expected_revision + 1,
                "confirmed": True,
            }
            return self.metadata_store.update(
                meeting_id,
                lambda current: {**current, "courtroom_docket": updated_docket},
            )

    def require_confirmed(self, metadata: dict[str, Any]) -> dict[str, Any]:
        docket = self._docket(metadata)
        if not bool(docket.get("confirmed")):
            raise CourtroomWorkflowError(
                "Courtroom issues must be confirmed before execution"
            )
        return docket

    def validate_draft(self, metadata: dict[str, Any], expected_revision: int) -> None:
        docket = self._docket(metadata)
        self._require_revision(docket, expected_revision)
        if docket.get("confirmed"):
            raise CourtroomWorkflowError("Confirmed courtroom issues are read-only")

    def validate_arguments(
        self,
        metadata: dict[str, Any],
        events: list[dict[str, Any]],
        issue_id: str,
    ) -> None:
        docket = self.require_confirmed(metadata)
        self._require_issue(docket, issue_id)
        projection = project_courtroom(metadata, events)
        assert projection is not None
        issue = next(item for item in projection["issues"] if item["id"] == issue_id)
        if issue["status"] != "pending" or projection["current_issue_id"] is not None:
            raise CourtroomWorkflowError("Complete the current courtroom issue first")

    def validate_ruling(
        self,
        metadata: dict[str, Any],
        events: list[dict[str, Any]],
        issue_id: str,
    ) -> None:
        docket = self.require_confirmed(metadata)
        self._require_issue(docket, issue_id)
        projection = project_courtroom(metadata, events)
        assert projection is not None
        issue = next(item for item in projection["issues"] if item["id"] == issue_id)
        if issue["status"] != "awaiting-ruling":
            raise CourtroomWorkflowError("Issue arguments must complete before ruling")

    def validate_final(self, metadata: dict[str, Any], events: list[dict[str, Any]]) -> None:
        projection = project_courtroom(metadata, events)
        if projection is None or projection["final_status"] != "ready":
            raise CourtroomWorkflowError(
                "Every confirmed issue requires a completed ruling"
            )

    def generate_draft(
        self,
        meeting_id: str,
        *,
        expected_revision: int,
        goal: str,
        model_assignments: dict[str, ModelConfig],
        inputs: dict[str, Any],
        runner: MeetingRunner,
    ) -> None:
        with self._meeting_lock(meeting_id):
            metadata = self._require_courtroom(meeting_id)
            profile = self._profile(metadata)
            self.validate_draft(metadata, expected_revision)
            event_step_id = f"courtroom-draft-r{expected_revision + 1}"
            self._append_reservation(meeting_id, "draft", expected_revision)
            completed = runner.run_workflow_step(
                meeting_id=meeting_id,
                goal=goal,
                model_assignments=model_assignments,
                step=StepDefinition(
                    "courtroom-issue-draft",
                    profile.draft.role_id,
                    profile.draft.prompt_template,
                    profile.draft.output_schema_id,
                ),
                event_step_id=event_step_id,
                inputs=inputs,
                extra_event_fields={**self._event_snapshot(profile, profile.draft),
                    "interaction_type": "courtroom-issue-draft",
                    "docket_revision": expected_revision,
                },
            )
            if not completed:
                return
            event = self._workflow_events(meeting_id)[-1]
            parsed = event.get("parsed_output")
            issues = parsed.get("issues") if isinstance(parsed, dict) else None
            if not isinstance(issues, list):
                return
            self.replace_issues(
                meeting_id,
                expected_revision=expected_revision,
                requested_issues=issues,
            )

    def run_arguments(
        self,
        meeting_id: str,
        *,
        issue_id: str,
        goal: str,
        model_assignments: dict[str, ModelConfig],
        inputs: dict[str, Any],
        runner: MeetingRunner,
    ) -> None:
        with self._meeting_lock(meeting_id):
            metadata = self._require_courtroom(meeting_id)
            profile = self._profile(metadata)
            docket = self.require_confirmed(metadata)
            revision = int(docket["revision"])
            issue = self._require_issue(docket, issue_id)
            self.validate_arguments(metadata, self._workflow_events(meeting_id), issue_id)
            self._append_reservation(meeting_id, "arguments", revision, issue_id)
            for phase in profile.argument_phases:
                completed = runner.run_workflow_step(
                    meeting_id=meeting_id,
                    goal=goal,
                    model_assignments=model_assignments,
                    step=StepDefinition(
                        f"courtroom-issue-{phase.id}",
                        phase.role_id,
                        phase.prompt_template,
                        phase.output_schema_id,
                    ),
                    event_step_id=f"courtroom-r{revision}-{issue_id}-{phase.id}",
                    inputs={**inputs, "current_issue": issue["title"]},
                    extra_event_fields={**self._event_snapshot(profile, phase),
                        "interaction_type": "courtroom-issue-phase",
                        "docket_revision": revision,
                        "issue_id": issue_id,
                        "issue_phase": phase.id,
                    },
                )
                if not completed:
                    return

    def run_ruling(
        self,
        meeting_id: str,
        *,
        issue_id: str,
        goal: str,
        model_assignments: dict[str, ModelConfig],
        inputs: dict[str, Any],
        runner: MeetingRunner,
    ) -> None:
        with self._meeting_lock(meeting_id):
            metadata = self._require_courtroom(meeting_id)
            profile = self._profile(metadata)
            docket = self.require_confirmed(metadata)
            revision = int(docket["revision"])
            issue = self._require_issue(docket, issue_id)
            self.validate_ruling(metadata, self._workflow_events(meeting_id), issue_id)
            self._append_reservation(meeting_id, "ruling", revision, issue_id)
            runner.run_workflow_step(
                meeting_id=meeting_id,
                goal=goal,
                model_assignments=model_assignments,
                step=StepDefinition(
                    "courtroom-issue-ruling",
                    profile.ruling.role_id,
                    profile.ruling.prompt_template,
                    profile.ruling.output_schema_id,
                ),
                event_step_id=f"courtroom-r{revision}-{issue_id}-ruling",
                inputs={**inputs, "current_issue": issue["title"]},
                extra_event_fields={**self._event_snapshot(profile, profile.ruling),
                    "interaction_type": "courtroom-issue-phase",
                    "docket_revision": revision,
                    "issue_id": issue_id,
                    "issue_phase": "ruling",
                },
            )

    def run_final_verdict(
        self,
        meeting_id: str,
        *,
        goal: str,
        model_assignments: dict[str, ModelConfig],
        inputs: dict[str, Any],
        runner: MeetingRunner,
    ) -> None:
        with self._meeting_lock(meeting_id):
            metadata = self._require_courtroom(meeting_id)
            profile = self._profile(metadata)
            docket = self.require_confirmed(metadata)
            revision = int(docket["revision"])
            events = self._workflow_events(meeting_id)
            self.validate_final(metadata, events)
            projection = project_courtroom(metadata, events)
            assert projection is not None
            issue_rulings = []
            for issue in projection["issues"]:
                issue_rulings.append(
                    f"- {issue['id']}: {issue['title']}\n  {issue['ruling']}"
                )
            self._append_reservation(meeting_id, "final-verdict", revision)
            runner.run_workflow_step(
                meeting_id=meeting_id,
                goal=goal,
                model_assignments=model_assignments,
                step=StepDefinition(
                    "courtroom-final-verdict",
                    profile.final.role_id,
                    profile.final.prompt_template,
                    profile.final.output_schema_id,
                ),
                event_step_id=f"courtroom-r{revision}-final-verdict",
                inputs={**inputs, "issue_rulings": "\n".join(issue_rulings)},
                extra_event_fields={**self._event_snapshot(profile, profile.final),
                    "interaction_type": "courtroom-final-verdict",
                    "docket_revision": revision,
                },
            )

    def retry_failed_step(
        self,
        meeting_id: str,
        *,
        step_id: str,
        goal: str,
        model_assignments: dict[str, ModelConfig],
        inputs: dict[str, Any],
        runner: MeetingRunner,
    ) -> None:
        with self._meeting_lock(meeting_id):
            metadata = self._require_courtroom(meeting_id)
            profile = self._profile(metadata)
            docket = self._docket(metadata)
            events = self._workflow_events(meeting_id)
            matching = [event for event in events if event.get("step_id") == step_id]
            failed = matching[-1] if matching else None
            if failed is None or failed.get("status") != "failed":
                raise CourtroomWorkflowError(f"Step is not failed: {step_id}", 400)
            revision = int(failed.get("docket_revision", -1))
            if revision != int(docket.get("revision", 0)):
                raise CourtroomWorkflowError("Failed step belongs to an inactive docket revision")
            attempt = int(failed.get("attempt", 1)) + 1
            interaction = failed.get("interaction_type")
            if interaction == "courtroom-issue-draft":
                self.validate_draft(metadata, revision)
                completed = runner.run_workflow_step(
                    meeting_id=meeting_id,
                    goal=goal,
                    model_assignments=model_assignments,
                    step=StepDefinition(
                        "courtroom-issue-draft",
                        profile.draft.role_id,
                        profile.draft.prompt_template,
                        profile.draft.output_schema_id,
                    ),
                    event_step_id=step_id,
                    inputs=inputs,
                    extra_event_fields={**self._event_snapshot(profile, profile.draft),
                        "interaction_type": "courtroom-issue-draft",
                        "docket_revision": revision,
                    },
                    attempt=attempt,
                )
                if completed:
                    completed_event = self._workflow_events(meeting_id)[-1]
                    parsed = completed_event.get("parsed_output")
                    issues = parsed.get("issues") if isinstance(parsed, dict) else None
                    if isinstance(issues, list):
                        self.replace_issues(
                            meeting_id,
                            expected_revision=revision,
                            requested_issues=issues,
                        )
                return
            if interaction == "courtroom-final-verdict":
                runner.run_workflow_step(
                    meeting_id=meeting_id,
                    goal=goal,
                    model_assignments=model_assignments,
                    step=StepDefinition(
                        "courtroom-final-verdict",
                        profile.final.role_id,
                        profile.final.prompt_template,
                        profile.final.output_schema_id,
                    ),
                    event_step_id=step_id,
                    inputs={**inputs, "issue_rulings": self._issue_rulings_text(metadata, events)},
                    extra_event_fields={**self._event_snapshot(profile, profile.final),
                        "interaction_type": "courtroom-final-verdict",
                        "docket_revision": revision,
                    },
                    attempt=attempt,
                )
                return
            if interaction != "courtroom-issue-phase":
                raise CourtroomWorkflowError("Step is not part of the courtroom workflow", 400)
            issue_id = str(failed.get("issue_id", ""))
            issue = self._require_issue(docket, issue_id)
            phase = str(failed.get("issue_phase", ""))
            definitions = [*profile.argument_phases, profile.ruling]
            try:
                start_index = next(
                    index for index, definition in enumerate(definitions) if definition.id == phase
                )
            except StopIteration as error:
                raise CourtroomWorkflowError("Unknown courtroom issue phase", 400) from error
            end_index = 3 if phase != "ruling" else start_index + 1
            for index, definition in enumerate(
                definitions[start_index:end_index], start=start_index
            ):
                next_phase = definition.id
                completed = runner.run_workflow_step(
                    meeting_id=meeting_id,
                    goal=goal,
                    model_assignments=model_assignments,
                    step=StepDefinition(
                        f"courtroom-issue-{next_phase}",
                        definition.role_id,
                        definition.prompt_template,
                        definition.output_schema_id,
                    ),
                    event_step_id=(
                        step_id
                        if index == start_index
                        else f"courtroom-r{revision}-{issue_id}-{next_phase}"
                    ),
                    inputs={**inputs, "current_issue": issue["title"]},
                    extra_event_fields={**self._event_snapshot(profile, definition),
                        "interaction_type": "courtroom-issue-phase",
                        "docket_revision": revision,
                        "issue_id": issue_id,
                        "issue_phase": next_phase,
                    },
                    attempt=attempt if index == start_index else 1,
                )
                if not completed:
                    return

    @staticmethod
    def _issue_rulings_text(metadata: dict[str, Any], events: list[dict[str, Any]]) -> str:
        projection = project_courtroom(metadata, events)
        if projection is None:
            return ""
        return "\n".join(
            f"- {issue['id']}: {issue['title']}\n  {issue.get('ruling')}"
            for issue in projection["issues"]
        )

    def _append_reservation(
        self,
        meeting_id: str,
        operation: str,
        revision: int,
        issue_id: str | None = None,
    ) -> None:
        event: dict[str, Any] = {
            "event_id": DeliberationEpochs.view(
                self.repository.read_events(meeting_id)
            ).event_id(
                f"{meeting_id}:courtroom-operation:{operation}:{revision}:{issue_id or 'docket'}"
            ),
            "meeting_id": meeting_id,
            "step_id": "courtroom-operation",
            "role": "System",
            "attempt": 1,
            "status": "started",
            "interaction_type": "courtroom-operation-reservation",
            "courtroom_operation": operation,
            "docket_revision": revision,
        }
        if issue_id is not None:
            event["issue_id"] = issue_id
        self.repository.append_event(meeting_id, event)

    def _workflow_events(self, meeting_id: str) -> list[dict[str, Any]]:
        return DeliberationEpochs.view(
            self.repository.read_events(meeting_id)
        ).workflow_events

    @staticmethod
    def _require_issue(docket: dict[str, Any], issue_id: str) -> dict[str, Any]:
        issue = next(
            (issue for issue in docket.get("issues") or [] if issue.get("id") == issue_id),
            None,
        )
        if issue is None:
            raise CourtroomWorkflowError(f"Unknown courtroom issue: {issue_id}", 404)
        return issue

    def _require_courtroom(self, meeting_id: str) -> dict[str, Any]:
        metadata = self.metadata_store.get(meeting_id)
        if metadata.get("mode_id") != "courtroom":
            raise CourtroomWorkflowError(
                "Courtroom workflow is only available for courtroom meetings",
                400,
            )
        return metadata

    @staticmethod
    def _profile(metadata: dict[str, Any]) -> CourtroomCaseProfile:
        try:
            return CourtroomCaseProfile.for_metadata(metadata)
        except CourtroomCaseProfileError as error:
            raise CourtroomWorkflowError(str(error)) from error

    @staticmethod
    def _event_snapshot(
        profile: CourtroomCaseProfile,
        step: CourtroomStepProfile,
    ) -> dict[str, str]:
        return {
            "case_type": profile.case_type,
            "role_display": profile.role_display(step.role_id),
            "phase_display": step.display,
        }

    @staticmethod
    def _docket(metadata: dict[str, Any]) -> dict[str, Any]:
        docket = metadata.get("courtroom_docket")
        if isinstance(docket, dict):
            return docket
        return {
            "schema_version": DOCKET_SCHEMA_VERSION,
            "revision": 0,
            "confirmed": False,
            "next_issue_number": 1,
            "issues": [],
        }

    @staticmethod
    def _require_revision(docket: dict[str, Any], expected_revision: int) -> None:
        actual = int(docket.get("revision", 0))
        if expected_revision != actual:
            raise CourtroomWorkflowError(
                f"Stale courtroom docket revision: expected {actual}, got {expected_revision}"
            )

    def _meeting_lock(self, meeting_id: str) -> threading.RLock:
        with self._locks_guard:
            return self._locks.setdefault(meeting_id, threading.RLock())
