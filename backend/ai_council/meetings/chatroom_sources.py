from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Iterable

from ai_council.meetings.attachments import TEXT_EXTENSIONS


SOURCE_CONTEXT_VERSION = "chatroom-source-context/v1"


def _active_version(item: dict[str, Any]) -> dict[str, Any] | None:
    versions = item.get("versions")
    if not isinstance(versions, list):
        return None
    active = item.get("active_version")
    return next(
        (
            version
            for version in versions
            if isinstance(version, dict) and version.get("version") == active
        ),
        None,
    )


def _host_acl_is_valid(version: dict[str, Any]) -> bool:
    marker = version.get("host_acl_explicit")
    return marker is None or marker is True


def _evidence_visible(version: dict[str, Any], role_id: str) -> bool:
    if not _host_acl_is_valid(version):
        return False
    roles = version.get("visible_roles")
    if not isinstance(roles, list):
        return False
    if role_id in roles:
        return True
    # Only an absent marker is legacy data. New evidence with an explicit marker
    # follows visible_roles exactly, including an explicit Host denial.
    return role_id == "host" and "host_acl_explicit" not in version


def _source_entry(
    *,
    source_ref: str,
    label: str,
    kind: str,
    reader_ref: str,
    active: bool,
    readable: bool,
    visible_roles: list[str],
    size: int | None = None,
    created_at: str | None = None,
    content: str | None = None,
    content_identity: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "source_ref": source_ref,
        "label": label,
        "kind": kind,
        "active": active,
        "readable": readable,
        "reader_ref": reader_ref,
        "available_segment_refs": ["full"] if readable else [],
        "visible_roles": list(visible_roles),
        **({"size": size} if size is not None else {}),
        **({"created_at": created_at} if created_at else {}),
        **({"content": content} if content is not None else {}),
        **({"content_identity": content_identity} if content_identity else {}),
    }


def project_chatroom_sources(
    *,
    meeting_id: str,
    materials: dict[str, Any],
    attachment_events: Iterable[dict[str, Any]],
    active_role_ids: list[str],
    readable_attachment_ids: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Project selectable chatroom sources without opening attachment bodies."""
    readable_attachment_ids = readable_attachment_ids or set()
    evidence_by_id = {
        str(item.get("id")): item
        for item in materials.get("evidence", [])
        if isinstance(item, dict)
    }
    linked_evidence_ids = {
        str(event.get("evidence_id"))
        for event in attachment_events
        if event.get("evidence_id")
    }
    result: list[dict[str, Any]] = []
    for event in attachment_events:
        file_id = str(event.get("file_id", ""))
        if not file_id:
            continue
        evidence = evidence_by_id.get(str(event.get("evidence_id"))) if event.get("evidence_id") else None
        version = _active_version(evidence) if evidence else None
        extension = str(event.get("extension") or Path(str(event.get("filename", ""))).suffix).lower()
        readable = extension in TEXT_EXTENSIONS and file_id in readable_attachment_ids
        visible_roles = list(active_role_ids)
        if version is not None:
            visible_roles = [
                role_id for role_id in active_role_ids if _evidence_visible(version, role_id)
            ]
            readable = (
                readable
                and _host_acl_is_valid(version)
                and isinstance(version.get("content"), str)
                and bool(version.get("content"))
            )
        result.append(
            _source_entry(
                source_ref=f"attachment:{file_id}",
                label=str(event.get("filename") or file_id),
                kind="attachment",
                reader_ref=f"attachment:{file_id}",
                active=True,
                readable=readable,
                visible_roles=visible_roles,
                size=int(event.get("size", 0) or 0),
                created_at=str(event.get("created_at")) if event.get("created_at") else None,
            )
        )

    for evidence_id, evidence in evidence_by_id.items():
        if evidence_id in linked_evidence_ids or evidence.get("status") != "active":
            continue
        version = _active_version(evidence)
        if version is None:
            continue
        content = version.get("content")
        readable = _host_acl_is_valid(version) and isinstance(content, str) and bool(content)
        visible_roles = [
            role_id for role_id in active_role_ids if _evidence_visible(version, role_id)
        ]
        result.append(
            _source_entry(
                source_ref=f"evidence:{evidence_id}",
                label=str(version.get("title") or evidence_id),
                kind="evidence",
                reader_ref=f"evidence:{evidence_id}",
                active=True,
                readable=readable,
                visible_roles=visible_roles,
                size=int(version.get("size", len(content) if isinstance(content, str) else 0) or 0),
                created_at=str(version.get("created_at")) if version.get("created_at") else None,
            )
        )
    return result


def validate_chatroom_sources(
    sources: list[dict[str, Any]],
    source_refs: list[str],
    target_role_ids: list[str],
) -> tuple[bool, str | None, str | None, str | None]:
    by_ref = {str(item.get("source_ref")): item for item in sources}
    for source_ref in source_refs:
        source = by_ref.get(source_ref)
        if source is None or not source.get("active"):
            return False, "INVALID_SOURCE_REF", source_ref, None
        if not source.get("readable"):
            return False, "SOURCE_NOT_READABLE", source_ref, None
        for role_id in target_role_ids:
            if role_id not in source.get("visible_roles", []):
                return False, "SOURCE_NOT_VISIBLE_TO_TARGET", source_ref, role_id
    return True, None, None, None


def make_attachment_identity(event: dict[str, Any], content: bytes) -> dict[str, Any]:
    return {
        "attachment_event_id": event.get("event_id"),
        "file_id": event.get("file_id"),
        "byte_size": len(content),
        "sha256": hashlib.sha256(content).hexdigest(),
    }


def make_evidence_identity(evidence_id: str, version: dict[str, Any]) -> dict[str, Any]:
    return {"evidence_id": evidence_id, "version": version.get("version")}
