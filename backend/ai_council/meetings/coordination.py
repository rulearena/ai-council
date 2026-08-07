from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager, contextmanager
from dataclasses import dataclass, field
from functools import wraps
from inspect import iscoroutinefunction, signature
from typing import Any


@dataclass
class _LockEntry:
    lock: threading.Lock = field(default_factory=threading.Lock)
    users: int = 0
    owner_thread_id: int | None = None
    sync_depth: int = 0


class MeetingTransitionCoordinator:
    """Serializes validation, mutation, and job reservation per meeting."""

    def __init__(self) -> None:
        self._locks: dict[str, _LockEntry] = {}
        self._locks_guard = threading.Lock()
        self._before_transition: Callable[[str, str | None], None] | None = None

    def set_before_transition(
        self, callback: Callable[[str, str | None], None]
    ) -> None:
        self._before_transition = callback

    @property
    def registry_size(self) -> int:
        with self._locks_guard:
            return len(self._locks)

    @contextmanager
    def guard(self, meeting_id: str, *, operation: str | None = None) -> Iterator[None]:
        entry = self._register(meeting_id)
        thread_id = threading.get_ident()
        with self._locks_guard:
            nested = entry.owner_thread_id == thread_id
            if nested:
                entry.sync_depth += 1
        acquired = nested
        try:
            if not nested:
                entry.lock.acquire()
                with self._locks_guard:
                    entry.owner_thread_id = thread_id
                    entry.sync_depth = 1
                acquired = True
            self._run_before_transition(meeting_id, operation)
            yield
        finally:
            self._release_sync(entry, thread_id, acquired)
            self._unregister(meeting_id, entry)

    @asynccontextmanager
    async def _async_guard(
        self, meeting_id: str, *, operation: str | None = None
    ) -> AsyncIterator[None]:
        entry = self._register(meeting_id)
        acquired = False
        try:
            acquired = await self._acquire_async(entry)
            self._run_before_transition(meeting_id, operation)
            yield
        finally:
            if acquired:
                entry.lock.release()
            self._unregister(meeting_id, entry)

    def _register(self, meeting_id: str) -> _LockEntry:
        with self._locks_guard:
            entry = self._locks.setdefault(meeting_id, _LockEntry())
            entry.users += 1
            return entry

    def _unregister(self, meeting_id: str, entry: _LockEntry) -> None:
        with self._locks_guard:
            entry.users -= 1
            if entry.users == 0 and self._locks.get(meeting_id) is entry:
                self._locks.pop(meeting_id)

    def _run_before_transition(self, meeting_id: str, operation: str | None) -> None:
        if self._before_transition is not None:
            self._before_transition(meeting_id, operation)

    def _release_sync(
        self, entry: _LockEntry, thread_id: int, acquired: bool
    ) -> None:
        if not acquired:
            return
        release_lock = False
        with self._locks_guard:
            if entry.owner_thread_id == thread_id:
                entry.sync_depth -= 1
                if entry.sync_depth == 0:
                    entry.owner_thread_id = None
                    release_lock = True
        if release_lock:
            entry.lock.release()

    async def _acquire_async(self, entry: _LockEntry) -> bool:
        """Acquire the shared lock without blocking the event loop.

        Each worker call is non-blocking. If cancellation arrives while the
        worker reports acquisition, await its result and release immediately so
        a cancelled request cannot leave the shared lock held.
        """
        while True:
            acquire_task = asyncio.create_task(
                asyncio.to_thread(entry.lock.acquire, False)
            )
            try:
                acquired = await asyncio.shield(acquire_task)
            except asyncio.CancelledError:
                acquired = await acquire_task
                if acquired:
                    entry.lock.release()
                raise
            if acquired:
                return True
            await asyncio.sleep(0)

    def synchronized(self, function: Callable[..., Any]) -> Callable[..., Any]:
        if iscoroutinefunction(function):
            @wraps(function)
            async def guarded(meeting_id: str, *args: Any, **kwargs: Any) -> Any:
                async with self._async_guard(meeting_id, operation=function.__name__):
                    return await function(meeting_id, *args, **kwargs)
        else:
            @wraps(function)
            def guarded(meeting_id: str, *args: Any, **kwargs: Any) -> Any:
                with self.guard(meeting_id, operation=function.__name__):
                    return function(meeting_id, *args, **kwargs)

        # FastAPI inspects the wrapper in this module. Resolve postponed annotations
        # against the endpoint's module before exposing its signature.
        guarded.__signature__ = signature(function, eval_str=True)  # type: ignore[attr-defined]
        return guarded
