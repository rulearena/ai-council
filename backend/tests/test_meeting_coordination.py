from __future__ import annotations

import asyncio
import threading

import pytest

from ai_council.meetings.coordination import MeetingTransitionCoordinator


def test_coordinator_releases_registry_entry_after_success_and_exception() -> None:
    coordinator = MeetingTransitionCoordinator()

    with coordinator.guard("meeting-success"):
        assert coordinator.registry_size == 1
    assert coordinator.registry_size == 0

    with pytest.raises(RuntimeError):
        with coordinator.guard("meeting-error"):
            assert coordinator.registry_size == 1
            raise RuntimeError("expected")
    assert coordinator.registry_size == 0


def test_coordinator_keeps_entry_until_waiter_finishes() -> None:
    coordinator = MeetingTransitionCoordinator()
    waiter_started = threading.Event()
    waiter_finished = threading.Event()

    def wait_for_guard() -> None:
        waiter_started.set()
        with coordinator.guard("meeting-race"):
            pass
        waiter_finished.set()

    with coordinator.guard("meeting-race"):
        waiter = threading.Thread(target=wait_for_guard)
        waiter.start()
        assert waiter_started.wait(timeout=2)
        assert coordinator.registry_size == 1
        assert not waiter_finished.is_set()

    assert waiter_finished.wait(timeout=2)
    waiter.join(timeout=2)
    assert coordinator.registry_size == 0


def test_synchronized_async_function_holds_meeting_lock_until_await_completes() -> None:
    coordinator = MeetingTransitionCoordinator()
    observed_registry_sizes: list[int] = []

    @coordinator.synchronized
    async def transition(meeting_id: str) -> str:
        observed_registry_sizes.append(coordinator.registry_size)
        await asyncio.sleep(0)
        observed_registry_sizes.append(coordinator.registry_size)
        return meeting_id

    result = asyncio.run(transition("meeting-async"))

    assert result == "meeting-async"
    assert observed_registry_sizes == [1, 1]
    assert coordinator.registry_size == 0
