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
    status: Literal["running"]
    started_at: NotRequired[str]
    interaction_type: NotRequired[str]
    directed_sequence: NotRequired[int]
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
        "error": "Model execution was interrupted before completion. Retry this failed step manually.",
    }
    for key in ["interaction_type", "directed_sequence", "sequence", "sequence_index"]:
        if key in state:
            event[key] = state[key]
    return event
