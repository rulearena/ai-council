from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable

from ai_council.meetings.repository import MeetingRepository


CASE_MATERIALS_SCHEMA_VERSION = 2


class CaseMaterialConflict(ValueError):
    pass


class CaseMaterialValidationError(ValueError):
    pass


@dataclass(frozen=True)
class CaseMaterialLimits:
    per_item_chars: int
    total_chars: int


@dataclass(frozen=True)
class MaterialVersion:
    version: int
    title: str
    content: str
    visible_roles: list[str]
    size: int
    created_at: str | None
    source_event_id: str | None
    host_acl_explicit: bool | None = None
    host_acl_explicit_present: bool = False


@dataclass(frozen=True)
class EvidenceMaterial:
    id: str
    evidence_index: int
    citation_anchor: str
    status: str
    active_version: int
    versions: list[MaterialVersion]


@dataclass(frozen=True)
class CaseNote:
    id: str
    status: str
    active_version: int
    versions: list[MaterialVersion]


@dataclass(frozen=True)
class MaterialRevision:
    revision: int
    parent_revision: int | None
    transition: str
    created_at: str | None
    evidence: list[dict[str, Any]]
    notes: list[dict[str, Any]]


@dataclass(frozen=True)
class CaseMaterialsView:
    schema_version: int
    revision: int
    evidence: list[EvidenceMaterial]
    notes: list[CaseNote]
    pending_impact: dict[str, Any] | None
    revision_history: list[MaterialRevision]


@dataclass(frozen=True)
class CaseMaterialsSummary:
    revision: int
    active_evidence_count: int
    active_note_count: int
    pending_impact: dict[str, Any] | None


class CaseMaterials:
    """Owns versioned prompt materials in the meeting's single case-file store."""

    def __init__(self, repository: MeetingRepository) -> None:
        self.repository = repository

    def view(self, meeting_id: str) -> CaseMaterialsView:
        raw = self.repository.read_case_materials_raw(meeting_id)
        document, schema_version = self._document(raw)
        return self._view(document, schema_version=schema_version)

    def summary(self, meeting_id: str) -> CaseMaterialsSummary:
        """Project counts and revision without copying versions or revision history."""
        raw = self.repository.read_case_materials_raw(meeting_id)
        if raw is None:
            return CaseMaterialsSummary(0, 0, 0, None)
        if isinstance(raw, list):
            return CaseMaterialsSummary(0, len(raw), 0, None)
        if raw.get("schema_version") != CASE_MATERIALS_SCHEMA_VERSION:
            raise CaseMaterialValidationError(
                f"Unsupported case materials schema: {raw.get('schema_version')!r}"
            )
        return CaseMaterialsSummary(
            revision=int(raw.get("revision", 0)),
            active_evidence_count=sum(
                item.get("status") == "active" for item in raw.get("evidence", [])
            ),
            active_note_count=sum(
                item.get("status") == "active" for item in raw.get("notes", [])
            ),
            pending_impact=raw.get("pending_impact"),
        )

    def view_at_revision(self, meeting_id: str, revision: int) -> CaseMaterialsView:
        raw = self.repository.read_case_materials_raw(meeting_id)
        document, schema_version = self._document(raw)
        entry = next(
            (
                candidate
                for candidate in document["revision_history"]
                if int(candidate["revision"]) == revision
            ),
            None,
        )
        if entry is None:
            raise CaseMaterialValidationError(
                f"Unknown case materials revision: {revision}"
            )
        restored = self._restore_revision(document, entry)
        return self._view(restored, schema_version=schema_version)

    def add_evidence(
        self,
        meeting_id: str,
        *,
        expected_revision: int,
        title: str,
        content: str,
        visible_roles: list[str],
        limits: CaseMaterialLimits,
        impact: dict[str, Any] | None = None,
    ) -> CaseMaterialsView:
        def mutate(document: dict[str, Any]) -> None:
            index = int(document["next_evidence_index"])
            document["next_evidence_index"] = index + 1
            document["evidence"].append(
                {
                    "id": f"case-file-{index}",
                    "evidence_index": index,
                    "citation_anchor": citation_anchor(index),
                    "status": "active",
                    "active_version": 1,
                    "versions": [
                        self._version(
                            1,
                            title=title,
                            content=content,
                            visible_roles=visible_roles,
                        )
                    ],
                }
            )

        return self._mutate(
            meeting_id,
            expected_revision=expected_revision,
            mutate=mutate,
            limits=limits,
            impact=impact,
            transition="add-evidence",
        )

    def add_evidence_version(
        self,
        meeting_id: str,
        evidence_id: str,
        *,
        expected_revision: int,
        title: str,
        content: str,
        visible_roles: list[str],
        limits: CaseMaterialLimits,
        impact: dict[str, Any] | None = None,
    ) -> CaseMaterialsView:
        def mutate(document: dict[str, Any]) -> None:
            evidence = self._find(document["evidence"], evidence_id, "evidence")
            version = int(evidence["active_version"]) + 1
            evidence["versions"].append(
                self._version(
                    version,
                    title=title,
                    content=content,
                    visible_roles=visible_roles,
                )
            )
            evidence["active_version"] = version

        return self._mutate(
            meeting_id,
            expected_revision=expected_revision,
            mutate=mutate,
            limits=limits,
            impact=impact,
            transition="version-evidence",
        )

    def set_evidence_active(
        self,
        meeting_id: str,
        evidence_id: str,
        *,
        active: bool,
        expected_revision: int,
        limits: CaseMaterialLimits,
        impact: dict[str, Any] | None = None,
    ) -> CaseMaterialsView:
        return self._mutate(
            meeting_id,
            expected_revision=expected_revision,
            mutate=lambda document: self._set_status(
                document["evidence"], evidence_id, active, "evidence"
            ),
            limits=limits,
            impact=impact,
            transition="reactivate-evidence" if active else "deactivate-evidence",
        )

    def add_note(
        self,
        meeting_id: str,
        *,
        expected_revision: int,
        title: str,
        content: str,
        visible_roles: list[str],
        limits: CaseMaterialLimits,
        source_event_id: str | None = None,
        impact: dict[str, Any] | None = None,
    ) -> CaseMaterialsView:
        def mutate(document: dict[str, Any]) -> None:
            number = int(document["next_note_number"])
            document["next_note_number"] = number + 1
            document["notes"].append(
                {
                    "id": f"case-note-{number}",
                    "status": "active",
                    "active_version": 1,
                    "versions": [
                        self._version(
                            1,
                            title=title,
                            content=content,
                            visible_roles=visible_roles,
                            source_event_id=source_event_id,
                        )
                    ],
                }
            )

        return self._mutate(
            meeting_id,
            expected_revision=expected_revision,
            mutate=mutate,
            limits=limits,
            impact=impact,
            transition="add-note",
        )

    def add_note_version(
        self,
        meeting_id: str,
        note_id: str,
        *,
        expected_revision: int,
        title: str,
        content: str,
        visible_roles: list[str],
        limits: CaseMaterialLimits,
        impact: dict[str, Any] | None = None,
    ) -> CaseMaterialsView:
        def mutate(document: dict[str, Any]) -> None:
            note = self._find(document["notes"], note_id, "case note")
            version = int(note["active_version"]) + 1
            note["versions"].append(
                self._version(
                    version,
                    title=title,
                    content=content,
                    visible_roles=visible_roles,
                )
            )
            note["active_version"] = version

        return self._mutate(
            meeting_id,
            expected_revision=expected_revision,
            mutate=mutate,
            limits=limits,
            impact=impact,
            transition="version-note",
        )

    def set_note_active(
        self,
        meeting_id: str,
        note_id: str,
        *,
        active: bool,
        expected_revision: int,
        limits: CaseMaterialLimits,
        impact: dict[str, Any] | None = None,
    ) -> CaseMaterialsView:
        return self._mutate(
            meeting_id,
            expected_revision=expected_revision,
            mutate=lambda document: self._set_status(
                document["notes"], note_id, active, "case note"
            ),
            limits=limits,
            impact=impact,
            transition="reactivate-note" if active else "deactivate-note",
        )

    def remove_evidence(
        self,
        meeting_id: str,
        evidence_id: str,
        *,
        expected_revision: int,
        limits: CaseMaterialLimits | None = None,
        impact: dict[str, Any] | None = None,
    ) -> CaseMaterialsView:
        def mutate(document: dict[str, Any]) -> None:
            removed = next(
                (
                    item
                    for item in document["evidence"]
                    if item.get("id") == evidence_id
                ),
                None,
            )
            if removed is None:
                raise CaseMaterialValidationError(f"Unknown evidence: {evidence_id}")
            document["evidence"] = [
                item
                for item in document["evidence"]
                if item.get("id") != evidence_id
            ]

        return self._mutate(
            meeting_id,
            expected_revision=expected_revision,
            mutate=mutate,
            limits=limits,
            impact=impact,
            transition="remove-evidence",
        )

    def _mutate(
        self,
        meeting_id: str,
        *,
        expected_revision: int,
        mutate: Callable[[dict[str, Any]], None],
        limits: CaseMaterialLimits | None,
        impact: dict[str, Any] | None,
        transition: str,
    ) -> CaseMaterialsView:
        raw = self.repository.read_case_materials_raw(meeting_id)
        document, _ = self._document(raw)
        actual_revision = int(document["revision"])
        if expected_revision != actual_revision:
            raise CaseMaterialConflict(
                f"Stale case materials revision: expected {actual_revision}, got {expected_revision}"
            )
        updated = deepcopy(document)
        mutate(updated)
        if limits is not None:
            self._validate_new_versions(document, updated, limits)
            self._validate_active_total(updated, limits)
        updated["revision"] = actual_revision + 1
        if (
            impact is not None
            and self._active_prompt_refs(document) != self._active_prompt_refs(updated)
        ):
            updated["pending_impact"] = deepcopy(impact)
        updated["revision_history"].append(
            self._revision_entry(
                updated,
                revision=actual_revision + 1,
                parent_revision=actual_revision,
                transition=transition,
            )
        )
        self.repository.save_case_materials(meeting_id, updated)
        return self._view(updated, schema_version=CASE_MATERIALS_SCHEMA_VERSION)

    @classmethod
    def _document(
        cls, raw: list[dict[str, Any]] | dict[str, Any] | None
    ) -> tuple[dict[str, Any], int]:
        if isinstance(raw, dict) and raw.get("schema_version") == CASE_MATERIALS_SCHEMA_VERSION:
            document = deepcopy(raw)
            if "revision_history" not in document:
                document["revision_history"] = [
                    cls._revision_entry(
                        document,
                        revision=int(document["revision"]),
                        parent_revision=(
                            int(document["revision"]) - 1
                            if int(document["revision"]) > 0
                            else None
                        ),
                        transition="legacy-versioned-snapshot",
                    )
                ]
            return document, CASE_MATERIALS_SCHEMA_VERSION
        if isinstance(raw, dict):
            raise CaseMaterialValidationError(
                f"Unsupported case materials schema: {raw.get('schema_version')!r}"
            )
        if isinstance(raw, list):
            evidence = []
            for position, item in enumerate(raw, start=1):
                index = int(item.get("evidence_index", position))
                evidence.append(
                    {
                        "id": str(item.get("id") or f"case-file-{index}"),
                        "evidence_index": index,
                        "citation_anchor": str(
                            item.get("citation_anchor") or citation_anchor(index)
                        ),
                        "status": "active",
                        "active_version": 1,
                        "versions": [
                            cls._version(
                                1,
                                title=str(item.get("title", "")),
                                content=str(item.get("content", "")),
                                visible_roles=[
                                    str(role)
                                    for role in item.get("visible_roles") or []
                                ],
                                created_at=item.get("created_at"),
                            )
                        ],
                    }
                )
            next_index = max((item["evidence_index"] for item in evidence), default=0) + 1
            return cls._empty_document(evidence=evidence, next_index=next_index), 1
        return cls._empty_document(), CASE_MATERIALS_SCHEMA_VERSION

    @classmethod
    def _empty_document(
        cls, *, evidence: list[dict[str, Any]] | None = None, next_index: int = 1
    ) -> dict[str, Any]:
        document = {
            "schema_version": CASE_MATERIALS_SCHEMA_VERSION,
            "revision": 0,
            "next_evidence_index": next_index,
            "next_note_number": 1,
            "evidence": evidence or [],
            "notes": [],
            "pending_impact": None,
        }
        document["revision_history"] = [
            cls._revision_entry(
                document,
                revision=0,
                parent_revision=None,
                transition="initial",
            )
        ]
        return document

    @staticmethod
    def _version(
        version: int,
        *,
        title: str,
        content: str,
        visible_roles: list[str],
        source_event_id: str | None = None,
        created_at: str | None = None,
    ) -> dict[str, Any]:
        title = title.strip()
        roles = list(dict.fromkeys(role.strip() for role in visible_roles if role.strip()))
        if not title:
            raise CaseMaterialValidationError("Material title must not be blank")
        if not content.strip():
            raise CaseMaterialValidationError("Material content must not be blank")
        if not roles:
            raise CaseMaterialValidationError("Material requires at least one visible role")
        return {
            "version": version,
            "title": title,
            "content": content,
            "visible_roles": roles,
            "size": len(content),
            "created_at": created_at or datetime.now(UTC).isoformat(),
            "source_event_id": source_event_id,
            "host_acl_explicit": True,
        }

    @staticmethod
    def _find(items: list[dict[str, Any]], item_id: str, kind: str) -> dict[str, Any]:
        item = next((candidate for candidate in items if candidate.get("id") == item_id), None)
        if item is None:
            raise CaseMaterialValidationError(f"Unknown {kind}: {item_id}")
        return item

    @classmethod
    def _set_status(
        cls, items: list[dict[str, Any]], item_id: str, active: bool, kind: str
    ) -> None:
        item = cls._find(items, item_id, kind)
        requested = "active" if active else "inactive"
        if item.get("status") == requested:
            raise CaseMaterialValidationError(f"{kind.title()} is already {requested}: {item_id}")
        item["status"] = requested

    @classmethod
    def _validate_new_versions(
        cls,
        before: dict[str, Any],
        after: dict[str, Any],
        limits: CaseMaterialLimits,
    ) -> None:
        before_counts = {
            (kind, str(item["id"])): len(item["versions"])
            for kind, collection in (("evidence", before["evidence"]), ("note", before["notes"]))
            for item in collection
        }
        for kind, collection in (("evidence", after["evidence"]), ("note", after["notes"])):
            for item in collection:
                start = before_counts.get((kind, str(item["id"])), 0)
                for version in item["versions"][start:]:
                    if int(version["size"]) > limits.per_item_chars:
                        raise CaseMaterialValidationError(
                            f"Material content exceeds {limits.per_item_chars} characters"
                        )

    @classmethod
    def _validate_active_total(
        cls, document: dict[str, Any], limits: CaseMaterialLimits
    ) -> None:
        total = 0
        for collection in (document["evidence"], document["notes"]):
            for item in collection:
                if item.get("status") != "active":
                    continue
                version = cls._active_version(item)
                size = int(version["size"])
                total += size
        if total > limits.total_chars:
            raise CaseMaterialValidationError(
                f"Active materials exceed {limits.total_chars} total characters"
            )

    @classmethod
    def _view(cls, document: dict[str, Any], *, schema_version: int) -> CaseMaterialsView:
        return CaseMaterialsView(
            schema_version=schema_version,
            revision=int(document["revision"]),
            evidence=[cls._evidence_view(item) for item in document["evidence"]],
            notes=[cls._note_view(item) for item in document["notes"]],
            pending_impact=deepcopy(document.get("pending_impact")),
            revision_history=[
                cls._revision_view(entry) for entry in document["revision_history"]
            ],
        )

    @classmethod
    def _revision_entry(
        cls,
        document: dict[str, Any],
        *,
        revision: int,
        parent_revision: int | None,
        transition: str,
    ) -> dict[str, Any]:
        references = cls._material_refs(document)
        return {
            "revision": revision,
            "parent_revision": parent_revision,
            "transition": transition,
            "created_at": datetime.now(UTC).isoformat(),
            **references,
        }

    @classmethod
    def _material_refs(cls, document: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
        def reference(kind: str, item: dict[str, Any]) -> dict[str, Any]:
            version = cls._active_version(item)
            result = {
                "kind": kind,
                "id": str(item["id"]),
                "status": str(item["status"]),
                "version": int(item["active_version"]),
                "visible_roles": [str(role) for role in version["visible_roles"]],
            }
            if kind == "evidence":
                result.update(
                    {
                        "evidence_index": int(item["evidence_index"]),
                        "citation_anchor": str(item["citation_anchor"]),
                    }
                )
            return result

        return {
            "evidence": [reference("evidence", item) for item in document["evidence"]],
            "notes": [reference("note", item) for item in document["notes"]],
        }

    @staticmethod
    def _revision_view(entry: dict[str, Any]) -> MaterialRevision:
        return MaterialRevision(
            revision=int(entry["revision"]),
            parent_revision=(
                int(entry["parent_revision"])
                if entry.get("parent_revision") is not None
                else None
            ),
            transition=str(entry["transition"]),
            created_at=entry.get("created_at"),
            evidence=deepcopy(entry["evidence"]),
            notes=deepcopy(entry["notes"]),
        )

    @classmethod
    def _restore_revision(
        cls, document: dict[str, Any], entry: dict[str, Any]
    ) -> dict[str, Any]:
        def restore(
            collection: str, references: list[dict[str, Any]]
        ) -> list[dict[str, Any]]:
            current_by_id = {str(item["id"]): item for item in document[collection]}
            restored = []
            for reference in references:
                current = deepcopy(current_by_id[str(reference["id"])])
                version = int(reference["version"])
                current["status"] = reference["status"]
                current["active_version"] = version
                current["versions"] = [
                    item
                    for item in current["versions"]
                    if int(item["version"]) <= version
                ]
                restored.append(current)
            return restored

        restored = deepcopy(document)
        restored["revision"] = int(entry["revision"])
        restored["evidence"] = restore("evidence", entry["evidence"])
        restored["notes"] = restore("notes", entry["notes"])
        restored["pending_impact"] = None
        return restored

    @classmethod
    def _active_prompt_refs(cls, document: dict[str, Any]) -> list[dict[str, Any]]:
        references = cls._material_refs(document)
        return [
            reference
            for reference in [*references["evidence"], *references["notes"]]
            if reference["status"] == "active"
        ]

    @classmethod
    def _evidence_view(cls, item: dict[str, Any]) -> EvidenceMaterial:
        return EvidenceMaterial(
            id=str(item["id"]),
            evidence_index=int(item["evidence_index"]),
            citation_anchor=str(item["citation_anchor"]),
            status=str(item["status"]),
            active_version=int(item["active_version"]),
            versions=[cls._version_view(version) for version in item["versions"]],
        )

    @classmethod
    def _note_view(cls, item: dict[str, Any]) -> CaseNote:
        return CaseNote(
            id=str(item["id"]),
            status=str(item["status"]),
            active_version=int(item["active_version"]),
            versions=[cls._version_view(version) for version in item["versions"]],
        )

    @staticmethod
    def _version_view(version: dict[str, Any]) -> MaterialVersion:
        return MaterialVersion(
            version=int(version["version"]),
            title=str(version["title"]),
            content=str(version["content"]),
            visible_roles=[str(role) for role in version["visible_roles"]],
            size=int(version["size"]),
            created_at=version.get("created_at"),
            source_event_id=version.get("source_event_id"),
            host_acl_explicit=version.get("host_acl_explicit"),
            host_acl_explicit_present="host_acl_explicit" in version,
        )

    @staticmethod
    def _active_version(item: dict[str, Any]) -> dict[str, Any]:
        number = int(item["active_version"])
        return next(version for version in item["versions"] if int(version["version"]) == number)


CHINESE_DIGITS = "零一二三四五六七八九"
def citation_anchor(value: int) -> str:
    def section(number: int) -> str:
        result = ""
        pending_zero = False
        for divisor, unit in ((1000, "千"), (100, "百"), (10, "十"), (1, "")):
            digit, number = divmod(number, divisor)
            if digit:
                if pending_zero and result:
                    result += CHINESE_DIGITS[0]
                if not (divisor == 10 and digit == 1 and not result):
                    result += CHINESE_DIGITS[digit]
                result += unit
                pending_zero = False
            elif result and number:
                pending_zero = True
        return result

    if value <= 0:
        raise ValueError("Evidence index must be positive")
    high, low = divmod(value, 10_000)
    if not high:
        text = section(low)
    elif high >= 10_000:
        text = "".join(CHINESE_DIGITS[int(digit)] for digit in str(value))
    else:
        separator = CHINESE_DIGITS[0] if low and low < 1000 else ""
        text = f"{section(high)}萬{separator}{section(low) if low else ''}"
    return f"[證物{text}]"
