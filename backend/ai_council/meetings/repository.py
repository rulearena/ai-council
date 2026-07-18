from __future__ import annotations

import json
import os
import re
import shutil
import threading
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SAFE_MEETING_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


@dataclass
class _EventLockEntry:
    lock: threading.RLock = field(default_factory=threading.RLock)
    users: int = 0


class MeetingRepository:
    def __init__(self, data_dir: Path | str) -> None:
        self.data_dir = Path(data_dir)
        self._event_locks: dict[str, _EventLockEntry] = {}
        self._event_locks_guard = threading.Lock()

    def append_event(self, meeting_id: str, event: dict[str, Any]) -> None:
        with self._event_guard(meeting_id):
            self._append_event_unlocked(meeting_id, event)

    def append_event_if(
        self,
        meeting_id: str,
        event: dict[str, Any],
        predicate: Callable[[list[dict[str, Any]]], bool],
    ) -> bool:
        """Append only when ``predicate`` accepts the locked event snapshot.

        The predicate and append are one per-meeting critical section, so callers
        can publish a result without a terminal marker crossing that boundary.
        """
        with self._event_guard(meeting_id):
            if not predicate(self._read_events_unlocked(meeting_id)):
                return False
            self._append_event_unlocked(meeting_id, event)
            return True

    @property
    def event_lock_registry_size(self) -> int:
        with self._event_locks_guard:
            return len(self._event_locks)

    def _append_event_unlocked(self, meeting_id: str, event: dict[str, Any]) -> None:
        event_log = self._event_log_path(meeting_id)
        event_log.parent.mkdir(parents=True, exist_ok=True)
        stored_event = {
            "created_at": datetime.now(UTC).isoformat(),
            **event,
        }
        with event_log.open("a", encoding="utf-8") as file:
            file.write(json.dumps(stored_event, ensure_ascii=False) + "\n")

    def read_events(self, meeting_id: str) -> list[dict[str, Any]]:
        with self._event_guard(meeting_id):
            return self._read_events_unlocked(meeting_id)

    def _read_events_unlocked(self, meeting_id: str) -> list[dict[str, Any]]:
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

    @contextmanager
    def _event_guard(self, meeting_id: str) -> Iterator[None]:
        # Validate before registering a key so rejected IDs cannot grow the registry.
        self._meeting_dir(meeting_id)
        with self._event_locks_guard:
            entry = self._event_locks.setdefault(meeting_id, _EventLockEntry())
            entry.users += 1
        try:
            with entry.lock:
                yield
        finally:
            with self._event_locks_guard:
                entry.users -= 1
                if entry.users == 0 and self._event_locks.get(meeting_id) is entry:
                    self._event_locks.pop(meeting_id)

    def delete(self, meeting_id: str) -> None:
        meeting_dir = self._meeting_dir(meeting_id)
        if meeting_dir.exists():
            shutil.rmtree(meeting_dir)

    def save_case_files(self, meeting_id: str, case_files: list[dict[str, Any]]) -> None:
        case_files_path = self._case_files_path(meeting_id)
        case_files_path.parent.mkdir(parents=True, exist_ok=True)
        case_files_path.write_text(
            json.dumps(case_files, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def read_case_files(self, meeting_id: str) -> list[dict[str, Any]]:
        case_files_path = self._case_files_path(meeting_id)
        if not case_files_path.exists():
            return []
        return json.loads(case_files_path.read_text(encoding="utf-8"))

    def read_case_materials_raw(
        self, meeting_id: str
    ) -> list[dict[str, Any]] | dict[str, Any] | None:
        path = self._case_files_path(meeting_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def save_case_materials(self, meeting_id: str, materials: dict[str, Any]) -> None:
        path = self._case_files_path(meeting_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temp_path.write_text(
                json.dumps(materials, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(temp_path, path)
        finally:
            temp_path.unlink(missing_ok=True)

    def _event_log_path(self, meeting_id: str) -> Path:
        return self._meeting_dir(meeting_id) / "events.jsonl"

    def _case_files_path(self, meeting_id: str) -> Path:
        return self._meeting_dir(meeting_id) / "case_files.json"

    def _meeting_dir(self, meeting_id: str) -> Path:
        if not SAFE_MEETING_ID.fullmatch(meeting_id):
            raise ValueError(f"Unsafe meeting_id: {meeting_id!r}")
        return self.data_dir / "meetings" / meeting_id
