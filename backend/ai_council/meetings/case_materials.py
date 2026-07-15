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
class CaseMaterialsView:
    schema_version: int
    revision: int
    evidence: list[EvidenceMaterial]
    notes: list[CaseNote]
    pending_impact: dict[str, Any] | None


class CaseMaterials:
    """Owns versioned prompt materials in the meeting's single case-file store."""

    def __init__(self, repository: MeetingRepository) -> None:
        self.repository = repository

    def view(self, meeting_id: str) -> CaseMaterialsView:
        raw = self.repository.read_case_materials_raw(meeting_id)
        document, schema_version = self._document(raw)
        return self._view(document, schema_version=schema_version)

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
        )

    def _mutate(
        self,
        meeting_id: str,
        *,
        expected_revision: int,
        mutate: Callable[[dict[str, Any]], None],
        limits: CaseMaterialLimits | None,
        impact: dict[str, Any] | None,
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
            self._validate_limits(updated, limits)
        updated["revision"] = actual_revision + 1
        if impact is not None:
            updated["pending_impact"] = deepcopy(impact)
        self.repository.save_case_materials(meeting_id, updated)
        return self._view(updated, schema_version=CASE_MATERIALS_SCHEMA_VERSION)

    @classmethod
    def _document(
        cls, raw: list[dict[str, Any]] | dict[str, Any] | None
    ) -> tuple[dict[str, Any], int]:
        if isinstance(raw, dict) and raw.get("schema_version") == CASE_MATERIALS_SCHEMA_VERSION:
            return deepcopy(raw), CASE_MATERIALS_SCHEMA_VERSION
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
                                visible_roles=[str(role) for role in item.get("visible_roles") or []],
                                created_at=item.get("created_at"),
                            )
                        ],
                    }
                )
            next_index = max((item["evidence_index"] for item in evidence), default=0) + 1
            return cls._empty_document(evidence=evidence, next_index=next_index), 1
        return cls._empty_document(), CASE_MATERIALS_SCHEMA_VERSION

    @staticmethod
    def _empty_document(
        *, evidence: list[dict[str, Any]] | None = None, next_index: int = 1
    ) -> dict[str, Any]:
        return {
            "schema_version": CASE_MATERIALS_SCHEMA_VERSION,
            "revision": 0,
            "next_evidence_index": next_index,
            "next_note_number": 1,
            "evidence": evidence or [],
            "notes": [],
            "pending_impact": None,
        }

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
    def _validate_limits(cls, document: dict[str, Any], limits: CaseMaterialLimits) -> None:
        total = 0
        for collection in (document["evidence"], document["notes"]):
            for item in collection:
                if item.get("status") != "active":
                    continue
                version = cls._active_version(item)
                size = int(version["size"])
                if size > limits.per_item_chars:
                    raise CaseMaterialValidationError(
                        f"Material content exceeds {limits.per_item_chars} characters"
                    )
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
        )

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
