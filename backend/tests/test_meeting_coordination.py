from __future__ import annotations

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
