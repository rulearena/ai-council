from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

SAFE_MEETING_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


class MeetingRepository:
    def __init__(self, data_dir: Path | str) -> None:
        self.data_dir = Path(data_dir)

    def append_event(self, meeting_id: str, event: dict[str, Any]) -> None:
        event_log = self._event_log_path(meeting_id)
        event_log.parent.mkdir(parents=True, exist_ok=True)
        with event_log.open("a", encoding="utf-8") as file:
            file.write(json.dumps(event, ensure_ascii=False) + "\n")

    def read_events(self, meeting_id: str) -> list[dict[str, Any]]:
        event_log = self._event_log_path(meeting_id)
        if not event_log.exists():
            return []

        events: list[dict[str, Any]] = []
        with event_log.open("r", encoding="utf-8") as file:
            for line in file:
                stripped = line.strip()
                if stripped:
                    events.append(json.loads(stripped))
        return events

    def _event_log_path(self, meeting_id: str) -> Path:
        if not SAFE_MEETING_ID.fullmatch(meeting_id):
            raise ValueError(f"Unsafe meeting_id: {meeting_id!r}")
        return self.data_dir / "meetings" / meeting_id / "events.jsonl"
