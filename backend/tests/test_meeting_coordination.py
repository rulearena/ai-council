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


def test_sync_guard_remains_reentrant_for_same_thread_nested_transitions() -> None:
    coordinator = MeetingTransitionCoordinator()

    with coordinator.guard("meeting-nested"):
        with coordinator.guard("meeting-nested"):
            assert coordinator.registry_size == 1

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


def test_async_transitions_are_mutually_exclusive_on_same_event_loop() -> None:
    coordinator = MeetingTransitionCoordinator()
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    second_entered = False

    @coordinator.synchronized
    async def transition(meeting_id: str, number: int) -> None:
        nonlocal second_entered
        if number == 1:
            first_entered.set()
            await release_first.wait()
        else:
            second_entered = True

    async def scenario() -> None:
        first = asyncio.create_task(transition("meeting-async-race", 1))
        await first_entered.wait()
        second = asyncio.create_task(transition("meeting-async-race", 2))
        await asyncio.sleep(0)
        assert not second_entered
        release_first.set()
        await asyncio.gather(first, second)

    asyncio.run(scenario())
    assert second_entered
    assert coordinator.registry_size == 0


def test_async_and_sync_transitions_share_the_same_meeting_lock() -> None:
    coordinator = MeetingTransitionCoordinator()
    async_entered = asyncio.Event()
    release_async = asyncio.Event()
    sync_entered = threading.Event()

    @coordinator.synchronized
    async def async_transition(meeting_id: str) -> None:
        async_entered.set()
        await release_async.wait()

    def sync_transition() -> None:
        with coordinator.guard("meeting-cross-mode"):
            sync_entered.set()

    async def scenario() -> None:
        holder = asyncio.create_task(async_transition("meeting-cross-mode"))
        await async_entered.wait()
        waiter = threading.Thread(target=sync_transition)
        waiter.start()
        assert not sync_entered.wait(timeout=0.05)
        release_async.set()
        await holder
        waiter.join(timeout=2)
        assert not waiter.is_alive()

    asyncio.run(scenario())
    assert sync_entered.is_set()
    assert coordinator.registry_size == 0


def test_synchronized_async_exception_releases_lock_and_registry_entry() -> None:
    coordinator = MeetingTransitionCoordinator()

    @coordinator.synchronized
    async def transition(meeting_id: str) -> None:
        await asyncio.sleep(0)
        raise RuntimeError("expected")

    with pytest.raises(RuntimeError, match="expected"):
        asyncio.run(transition("meeting-async-error"))

    assert coordinator.registry_size == 0


def test_cancelled_async_waiter_does_not_leave_shared_lock_held() -> None:
    coordinator = MeetingTransitionCoordinator()
    holder_entered = asyncio.Event()
    release_holder = asyncio.Event()

    @coordinator.synchronized
    async def transition(meeting_id: str, holder: bool) -> None:
        if holder:
            holder_entered.set()
            await release_holder.wait()

    async def scenario() -> None:
        holder = asyncio.create_task(transition("meeting-cancel", True))
        await holder_entered.wait()
        waiter = asyncio.create_task(transition("meeting-cancel", False))
        await asyncio.sleep(0)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        assert coordinator.registry_size == 1
        release_holder.set()
        await holder

    asyncio.run(scenario())
    assert coordinator.registry_size == 0
    with coordinator.guard("meeting-cancel"):
        pass
