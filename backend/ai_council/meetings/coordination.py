from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from functools import wraps
from inspect import signature
from typing import Any


@dataclass
class _LockEntry:
    lock: threading.RLock = field(default_factory=threading.RLock)
    users: int = 0


class MeetingTransitionCoordinator:
    """Serializes validation, mutation, and job reservation per meeting."""

    def __init__(self) -> None:
        self._locks: dict[str, _LockEntry] = {}
        self._locks_guard = threading.Lock()

    @property
    def registry_size(self) -> int:
        with self._locks_guard:
            return len(self._locks)

    @contextmanager
    def guard(self, meeting_id: str) -> Iterator[None]:
        with self._locks_guard:
            entry = self._locks.setdefault(meeting_id, _LockEntry())
            entry.users += 1
        try:
            with entry.lock:
                yield
        finally:
            with self._locks_guard:
                entry.users -= 1
                if entry.users == 0 and self._locks.get(meeting_id) is entry:
                    self._locks.pop(meeting_id)

    def synchronized(self, function: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(function)
        def guarded(meeting_id: str, *args: Any, **kwargs: Any) -> Any:
            with self.guard(meeting_id):
                return function(meeting_id, *args, **kwargs)

        # FastAPI inspects the wrapper in this module. Resolve postponed annotations
        # against the endpoint's module before exposing its signature.
        guarded.__signature__ = signature(function, eval_str=True)  # type: ignore[attr-defined]
        return guarded
