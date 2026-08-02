from __future__ import annotations

import os
import re
import shutil
import uuid
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any, BinaryIO

from ai_council.meetings.repository import MeetingRepository

ATTACHMENT_EVENT_KIND = "attachment-added"

# file_id must be a plain name: no path separators, no "." / "..", no traversal.
SAFE_FILE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")

# Text file extensions are routed to the existing case-files contract
# (visible to the AI as case materials); everything else is a binary
# attachment that the AI never sees.
TEXT_EXTENSIONS = {".txt", ".md"}

BINARY_MIME_TYPES: dict[str, str] = {
    ".pdf": "application/pdf",
    ".zip": "application/zip",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".doc": "application/msword",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".xls": "application/vnd.ms-excel",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".csv": "text/csv",
}

# Text files mirror into the case-files contract, but still record an attachment
# event so the chat feed shows a downloadable card. These MIME types let the
# frontend render the reader variant instead of a generic binary card.
TEXT_MIME_TYPES: dict[str, str] = {
    ".txt": "text/plain",
    ".md": "text/markdown",
}


@dataclass
class AttachmentLimits:
    per_file_bytes: int = 10 * 1024 * 1024
    per_meeting_bytes: int = 50 * 1024 * 1024

    @classmethod
    def from_environment(cls) -> "AttachmentLimits":
        return cls(
            per_file_bytes=_positive_integer_environment(
                "AI_COUNCIL_MAX_ATTACHMENT_BYTES", 10 * 1024 * 1024
            ),
            per_meeting_bytes=_positive_integer_environment(
                "AI_COUNCIL_MAX_TOTAL_ATTACHMENT_BYTES", 50 * 1024 * 1024
            ),
        )


def _positive_integer_environment(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be a positive integer") from error
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


def classify_extension(extension: str) -> str:
    """Return ``"text"`` for .txt/.md (case-insensitive), ``"binary"`` otherwise."""
    if extension.lower() in TEXT_EXTENSIONS:
        return "text"
    return "binary"


def mime_type_for_extension(extension: str) -> str:
    if extension.lower() in TEXT_EXTENSIONS:
        return TEXT_MIME_TYPES.get(extension.lower(), "text/plain")
    return BINARY_MIME_TYPES.get(extension.lower(), "application/octet-stream")


class MultipartUploadError(Exception):
    pass


def parse_upload_part(body: bytes, content_type: str) -> tuple[str, bytes]:
    """Extract the single ``file`` part from a multipart/form-data body.

    Implemented with the stdlib ``email`` parser so no python-multipart
    dependency is required (the design's non-goal: no new dependencies).
    """
    marker = "boundary="
    if "multipart/form-data" not in content_type or marker not in content_type:
        raise MultipartUploadError("Expected multipart/form-data upload")
    boundary = content_type.split(marker, 1)[1].strip().strip('"')
    if not boundary:
        raise MultipartUploadError("Missing multipart boundary")
    wrapped = (
        f'Content-Type: multipart/form-data; boundary="{boundary}"\r\n'
        "MIME-Version: 1.0\r\n\r\n"
    ).encode("utf-8") + body
    message = BytesParser(policy=policy.default).parsebytes(wrapped)
    if not message.is_multipart():
        raise MultipartUploadError("Malformed multipart body")
    for part in message.iter_parts():
        disposition = part.get("Content-Disposition")
        if not disposition or "form-data" not in disposition:
            continue
        field_name = part.get_param("name", header="content-disposition")
        filename = part.get_param("filename", header="content-disposition")
        if field_name != "file" or not filename:
            continue
        return filename, part.get_payload(decode=True) or b""
    raise MultipartUploadError("Missing file field")


@dataclass
class AttachmentSummary:
    count: int
    total_bytes: int


class AttachmentStore:
    """Immutable blob storage for binary attachments.

    Blobs live at ``<data_dir>/meetings/<meeting_id>/attachments/<file_id>``.
    Metadata is a single ``attachment-added`` event appended to the meeting
    event log; quotas are projected from those events, never from a counter
    file, and there is no delete/deactivate in v1.
    """

    def __init__(self, repository: MeetingRepository) -> None:
        self._repository = repository

    def attachments_dir(self, meeting_id: str) -> Path:
        return self._repository._meeting_dir(meeting_id) / "attachments"

    def blob_path(self, meeting_id: str, file_id: str) -> Path | None:
        _validate_file_id(file_id)
        event = self.attachment_event(meeting_id, file_id)
        if event is None:
            return None
        return self._blob_path_unchecked(meeting_id, file_id)

    def _blob_path_unchecked(self, meeting_id: str, file_id: str) -> Path:
        return self.attachments_dir(meeting_id) / file_id

    def save_blob(self, meeting_id: str, file_id: str, stream: BinaryIO) -> Path:
        """Persist the upload before any metadata event exists for it."""
        _validate_file_id(file_id)
        meeting_dir = self._repository._meeting_dir(meeting_id)
        target = meeting_dir / "attachments" / file_id
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_path = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            with temp_path.open("wb") as out:
                shutil.copyfileobj(stream, out, length=1024 * 1024)
            os.replace(temp_path, target)
        finally:
            temp_path.unlink(missing_ok=True)
        return target

    def record_attachment(
        self,
        meeting_id: str,
        *,
        file_id: str,
        filename: str,
        size: int,
        mime_type: str,
        extension: str,
    ) -> dict[str, Any]:
        """Record attachment metadata as an immutable event and return it."""
        event = {
            "event_id": f"{meeting_id}:attachment-added:{uuid.uuid4().hex}",
            "meeting_id": meeting_id,
            "step_id": ATTACHMENT_EVENT_KIND,
            "role": "Human",
            "attempt": 1,
            "status": "completed",
            "file_id": file_id,
            "filename": filename,
            "size": size,
            "mime_type": mime_type,
            "extension": extension,
        }
        self._repository.append_event(meeting_id, event)
        return event

    def attachment_event(self, meeting_id: str, file_id: str) -> dict[str, Any] | None:
        """Resolve an attachment by ``file_id`` from the event log."""
        for event in self._repository.read_events(meeting_id):
            if event.get("step_id") == ATTACHMENT_EVENT_KIND and event.get("file_id") == file_id:
                return event
        return None

    def attachment_events(self, meeting_id: str) -> list[dict[str, Any]]:
        return [
            event
            for event in self._repository.read_events(meeting_id)
            if event.get("step_id") == ATTACHMENT_EVENT_KIND
        ]

    def summary(self, meeting_id: str) -> AttachmentSummary:
        events = self.attachment_events(meeting_id)
        return AttachmentSummary(
            count=len(events),
            total_bytes=sum(int(event.get("size", 0) or 0) for event in events),
        )


def _validate_file_id(file_id: str) -> None:
    if not SAFE_FILE_ID.fullmatch(file_id):
        raise ValueError(f"Unsafe file_id: {file_id!r}")
