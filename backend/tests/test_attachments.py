from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pytest

from ai_council.meetings.attachments import (
    ATTACHMENT_EVENT_KIND,
    AttachmentLimits,
    AttachmentStore,
    classify_extension,
    mime_type_for_extension,
)
from ai_council.meetings.repository import MeetingRepository


def _make_store(tmp_path: Path) -> tuple[MeetingRepository, AttachmentStore]:
    repository = MeetingRepository(tmp_path / "data")
    store = AttachmentStore(repository)
    return repository, store


def _upload(
    store: AttachmentStore,
    meeting_id: str,
    *,
    filename: str,
    content: bytes,
    file_id: str = "attachment-testfile",
) -> tuple[str, dict[str, object], Path]:
    extension = Path(filename).suffix.lower()
    blob_path = store.save_blob(meeting_id, file_id, BytesIO(content))
    event = store.record_attachment(
        meeting_id,
        file_id=file_id,
        filename=filename,
        size=len(content),
        mime_type=mime_type_for_extension(extension),
        extension=extension,
    )
    return file_id, event, blob_path


def test_blob_written_before_metadata_event(tmp_path: Path) -> None:
    repository, store = _make_store(tmp_path)
    meeting_id = "meeting-1"
    file_id = "attachment-blobfirst"
    blob_path = store.save_blob(meeting_id, file_id, BytesIO(b"pdf-bytes"))

    events = repository.read_events(meeting_id)
    assert all(event.get("step_id") != ATTACHMENT_EVENT_KIND for event in events)

    assert blob_path.exists()
    assert blob_path.read_bytes() == b"pdf-bytes"
    assert store.attachment_event(meeting_id, file_id) is None


def test_record_attachment_event_carries_metadata(tmp_path: Path) -> None:
    repository, store = _make_store(tmp_path)
    meeting_id = "meeting-1"
    file_id = "attachment-meta"
    store.save_blob(meeting_id, file_id, BytesIO(b"content"))
    event = store.record_attachment(
        meeting_id,
        file_id=file_id,
        filename="報表.pdf",
        size=7,
        mime_type="application/pdf",
        extension=".pdf",
    )

    assert event["event_id"].startswith(f"{meeting_id}:attachment-added:")
    assert event["step_id"] == ATTACHMENT_EVENT_KIND
    assert event["meeting_id"] == meeting_id
    assert event["role"] == "Human"
    assert event["status"] == "completed"
    assert event["file_id"] == file_id
    assert event["filename"] == "報表.pdf"
    assert event["size"] == 7
    assert event["mime_type"] == "application/pdf"
    assert event["extension"] == ".pdf"

    stored = repository.read_events(meeting_id)[-1]
    assert stored["step_id"] == ATTACHMENT_EVENT_KIND
    assert stored["file_id"] == file_id
    assert stored["filename"] == "報表.pdf"


def test_extension_routing_txt_and_md_are_text() -> None:
    assert classify_extension(".txt") == "text"
    assert classify_extension(".md") == "text"
    assert classify_extension(".TXT") == "text"
    assert classify_extension(".Md") == "text"


def test_extension_routing_other_types_are_binary() -> None:
    assert classify_extension(".zip") == "binary"
    assert classify_extension(".pdf") == "binary"
    assert classify_extension(".png") == "binary"
    assert classify_extension(".docx") == "binary"
    assert classify_extension("") == "binary"
    assert classify_extension("report") == "binary"


def test_mime_type_map_and_fallback() -> None:
    assert mime_type_for_extension(".pdf") == "application/pdf"
    assert mime_type_for_extension(".zip") == "application/zip"
    assert mime_type_for_extension(".png") == "image/png"
    assert mime_type_for_extension(".jpeg") == "image/jpeg"
    assert mime_type_for_extension(".txt") == "text/plain"
    assert mime_type_for_extension(".md") == "text/markdown"
    assert mime_type_for_extension(".unknown-ext") == "application/octet-stream"
    assert mime_type_for_extension(".PNG") == "image/png"


def test_attachment_limits_defaults() -> None:
    limits = AttachmentLimits()
    assert limits.per_file_bytes == 10 * 1024 * 1024
    assert limits.per_meeting_bytes == 50 * 1024 * 1024


def test_attachment_limits_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AI_COUNCIL_MAX_ATTACHMENT_BYTES", "2048")
    monkeypatch.setenv("AI_COUNCIL_MAX_TOTAL_ATTACHMENT_BYTES", "8192")
    limits = AttachmentLimits.from_environment()
    assert limits.per_file_bytes == 2048
    assert limits.per_meeting_bytes == 8192


def test_attachment_limits_rejects_non_positive_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AI_COUNCIL_MAX_ATTACHMENT_BYTES", "0")
    with pytest.raises(ValueError):
        AttachmentLimits.from_environment()
    monkeypatch.setenv("AI_COUNCIL_MAX_ATTACHMENT_BYTES", "abc")
    with pytest.raises(ValueError):
        AttachmentLimits.from_environment()


def test_resolve_attachment_by_file_id(tmp_path: Path) -> None:
    _, store = _make_store(tmp_path)
    meeting_id = "meeting-1"
    file_id, event, _ = _upload(store, meeting_id, filename="report.pdf", content=b"pdf-bytes")

    resolved_event = store.attachment_event(meeting_id, file_id)
    assert resolved_event is not None
    assert resolved_event["event_id"] == event["event_id"]
    assert store.blob_path(meeting_id, file_id) is not None

    assert store.attachment_event(meeting_id, "attachment-unknown") is None
    assert store.blob_path(meeting_id, "attachment-unknown") is None


def test_attachments_summary_counts_and_bytes(tmp_path: Path) -> None:
    _, store = _make_store(tmp_path)
    meeting_id = "meeting-1"
    _upload(store, meeting_id, filename="a.pdf", content=b"a", file_id="attachment-a")
    _upload(store, meeting_id, filename="b.zip", content=b"bb", file_id="attachment-b")

    summary = store.summary(meeting_id)
    assert summary.count == 2
    assert summary.total_bytes == 3

    assert store.summary("other-meeting").count == 0
    assert store.summary("other-meeting").total_bytes == 0


def test_repository_delete_removes_attachment_blobs(tmp_path: Path) -> None:
    repository, store = _make_store(tmp_path)
    meeting_id = "meeting-1"
    _, _, blob_path = _upload(store, meeting_id, filename="a.pdf", content=b"a")
    assert blob_path.exists()

    repository.delete(meeting_id)

    assert not blob_path.exists()
    assert not blob_path.parent.exists()
    assert not blob_path.parent.parent.exists()


def test_unsafe_file_id_rejected(tmp_path: Path) -> None:
    _, store = _make_store(tmp_path)
    with pytest.raises(ValueError):
        store.save_blob("meeting-1", "../escape", BytesIO(b"x"))
    with pytest.raises(ValueError):
        store.save_blob("meeting-1", "attachment/a", BytesIO(b"x"))
