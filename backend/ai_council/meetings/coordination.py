from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import wraps
from inspect import signature
from typing import Any


class MeetingTransitionCoordinator:
    """Serializes validation, mutation, and job reservation per meeting."""

    def __init__(self) -> None:
        self._locks: dict[str, threading.RLock] = {}
        self._locks_guard = threading.Lock()

    @contextmanager
    def guard(self, meeting_id: str) -> Iterator[None]:
        with self._locks_guard:
            lock = self._locks.setdefault(meeting_id, threading.RLock())
        with lock:
            yield

    def synchronized(self, function: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(function)
        def guarded(meeting_id: str, *args: Any, **kwargs: Any) -> Any:
            with self.guard(meeting_id):
                return function(meeting_id, *args, **kwargs)

        # FastAPI inspects the wrapper in this module. Resolve postponed annotations
        # against the endpoint's module before exposing its signature.
        guarded.__signature__ = signature(function, eval_str=True)  # type: ignore[attr-defined]
        return guarded
