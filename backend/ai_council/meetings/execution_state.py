from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, NotRequired, TypedDict

SAFE_MEETING_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class ActiveExecutionState(TypedDict):
    meeting_id: str
    step_id: str
    base_step_id: str
    round: int
    role: str
    attempt: int
    model_config_id: str
    adapter: NotRequired[str]
    prompt_messages: NotRequired[list[dict[str, str]]]
    status: Literal["running"]
    started_at: NotRequired[str]
    prompt_template_name: NotRequired[str]
    prompt_template_hash: NotRequired[str]
    output_schema_id: NotRequired[str]
    output_schema_hash: NotRequired[str]
    interaction_type: NotRequired[str]
    directed_sequence: NotRequired[int]
    in_response_to_event_id: NotRequired[str]
    sequence: NotRequired[int]
    sequence_index: NotRequired[int]


class MeetingExecutionStateStore:
    def __init__(self, data_dir: Path | str) -> None:
        self.data_dir = Path(data_dir)

    def save_active(self, meeting_id: str, state: ActiveExecutionState) -> None:
        path = self._state_path(meeting_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        stored_state = {
            "started_at": datetime.now(UTC).isoformat(),
            **state,
        }
        path.write_text(json.dumps(stored_state, ensure_ascii=False), encoding="utf-8")

    def read_active(self, meeting_id: str) -> ActiveExecutionState | None:
        path = self._state_path(meeting_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def clear_active(self, meeting_id: str) -> None:
        path = self._state_path(meeting_id)
        if path.exists():
            path.unlink()

    def list_active(self) -> list[ActiveExecutionState]:
        meeting_root = self.data_dir / "meetings"
        if not meeting_root.exists():
            return []
        states = []
        for path in sorted(meeting_root.glob("*/execution.json")):
            states.append(json.loads(path.read_text(encoding="utf-8")))
        return states

    def _state_path(self, meeting_id: str) -> Path:
        if not SAFE_MEETING_ID.fullmatch(meeting_id):
            raise ValueError(f"Unsafe meeting_id: {meeting_id!r}")
        return self.data_dir / "meetings" / meeting_id / "execution.json"


def interrupted_execution_event(state: ActiveExecutionState) -> dict[str, object]:
    completed_at = datetime.now(UTC)
    started_at = state.get("started_at")
    duration_ms = 0
    if started_at:
        try:
            duration_ms = max(
                0,
                round((completed_at - datetime.fromisoformat(started_at)).total_seconds() * 1000),
            )
        except ValueError:
            duration_ms = 0
    event: dict[str, object] = {
        "event_id": (
            f"{state['meeting_id']}:{state['step_id']}:"
            f"attempt-{state['attempt']}:interrupted"
        ),
        "meeting_id": state["meeting_id"],
        "step_id": state["step_id"],
        "base_step_id": state["base_step_id"],
        "round": state["round"],
        "role": state["role"],
        "attempt": state["attempt"],
        "model_config_id": state["model_config_id"],
        "status": "failed",
        "failure_kind": "interrupted",
        "error": "Model execution was interrupted before completion. Retry this failed step manually.",
        "retry_scheduled": False,
        "completed_at": completed_at.isoformat(),
        "duration_ms": duration_ms,
    }
    for key in [
        "prompt_template_name",
        "prompt_template_hash",
        "output_schema_id",
        "output_schema_hash",
        "interaction_type",
        "directed_sequence",
        "in_response_to_event_id",
        "sequence",
        "sequence_index",
        "adapter",
        "prompt_messages",
        "started_at",
    ]:
        if key in state:
            event[key] = state[key]
    return event
