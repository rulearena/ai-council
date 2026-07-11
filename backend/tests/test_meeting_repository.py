from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_council.meetings.repository import MeetingRepository


@pytest.fixture
def repository(tmp_path: Path) -> MeetingRepository:
    return MeetingRepository(data_dir=tmp_path)


def test_append_event_creates_meeting_directory_and_event_log(
    repository: MeetingRepository,
    tmp_path: Path,
) -> None:
    event = {"event_id": "evt-1", "meeting_id": "meeting-1", "role": "Blue"}

    repository.append_event("meeting-1", event)

    event_log = tmp_path / "meetings" / "meeting-1" / "events.jsonl"
    assert event_log.exists()
    stored_event = json.loads(event_log.read_text(encoding="utf-8").strip())
    assert stored_event["created_at"]
    assert {key: value for key, value in stored_event.items() if key != "created_at"} == event


def test_read_events_returns_empty_list_when_event_log_is_missing(
    repository: MeetingRepository,
) -> None:
    assert repository.read_events("missing-meeting") == []


def test_appended_events_round_trip_in_order(repository: MeetingRepository) -> None:
    events = [
        {"event_id": "evt-1", "meeting_id": "meeting-1", "role": "Blue"},
        {"event_id": "evt-2", "meeting_id": "meeting-1", "role": "Red"},
        {"event_id": "evt-3", "meeting_id": "meeting-1", "role": "Judge"},
    ]

    for event in events:
        repository.append_event("meeting-1", event)

    stored_events = repository.read_events("meeting-1")
    assert [event["event_id"] for event in stored_events] == ["evt-1", "evt-2", "evt-3"]
    assert all(event["created_at"] for event in stored_events)


def test_repository_data_dir_can_be_injected(tmp_path: Path) -> None:
    data_dir = tmp_path / "custom-data"
    repository = MeetingRepository(data_dir=data_dir)

    repository.append_event("meeting-1", {"event_id": "evt-1"})

    assert (data_dir / "meetings" / "meeting-1" / "events.jsonl").exists()


def test_read_events_returns_empty_list_for_existing_empty_event_log(
    repository: MeetingRepository,
    tmp_path: Path,
) -> None:
    event_log = tmp_path / "meetings" / "meeting-1" / "events.jsonl"
    event_log.parent.mkdir(parents=True)
    event_log.write_text("", encoding="utf-8")

    assert repository.read_events("meeting-1") == []


@pytest.mark.parametrize("meeting_id", ["../outside", "nested/path", "", "."])
def test_repository_rejects_unsafe_meeting_ids(
    repository: MeetingRepository,
    meeting_id: str,
) -> None:
    with pytest.raises(ValueError):
        repository.append_event(meeting_id, {"event_id": "evt-1"})

    with pytest.raises(ValueError):
        repository.read_events(meeting_id)
