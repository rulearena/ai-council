from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_council.meetings.case_materials import (
    CaseMaterialConflict,
    CaseMaterialLimits,
    CaseMaterials,
)
from ai_council.meetings.repository import MeetingRepository


def legacy_files() -> list[dict[str, object]]:
    return [
        {
            "id": "case-file-1",
            "evidence_index": 1,
            "citation_anchor": "[證物一]",
            "title": "舊證物",
            "content": "legacy body",
            "visible_roles": ["Judge"],
            "size": 11,
        }
    ]


def test_legacy_materials_project_without_writing_or_upgrading(tmp_path: Path) -> None:
    repository = MeetingRepository(tmp_path)
    repository.save_case_files("meeting-1", legacy_files())
    path = tmp_path / "meetings" / "meeting-1" / "case_files.json"
    before = path.read_bytes()

    view = CaseMaterials(repository).view("meeting-1")

    assert view.schema_version == 1
    assert view.revision == 0
    assert view.evidence[0].id == "case-file-1"
    assert view.evidence[0].active_version == 1
    assert path.read_bytes() == before
    assert isinstance(json.loads(path.read_text(encoding="utf-8")), list)


def test_first_explicit_mutation_atomically_upgrades_and_never_reuses_anchor(
    tmp_path: Path,
) -> None:
    repository = MeetingRepository(tmp_path)
    repository.save_case_files("meeting-1", legacy_files())
    materials = CaseMaterials(repository)

    upgraded = materials.add_evidence(
        "meeting-1",
        expected_revision=0,
        title="新證物",
        content="new body",
        visible_roles=["Judge", "Defense"],
        limits=CaseMaterialLimits(per_item_chars=100, total_chars=1000),
    )
    deactivated = materials.set_evidence_active(
        "meeting-1",
        "case-file-1",
        active=False,
        expected_revision=1,
        limits=CaseMaterialLimits(per_item_chars=100, total_chars=1000),
    )
    third = materials.add_evidence(
        "meeting-1",
        expected_revision=2,
        title="第三份",
        content="third",
        visible_roles=["Judge"],
        limits=CaseMaterialLimits(per_item_chars=100, total_chars=1000),
    )

    assert upgraded.schema_version == 2
    assert upgraded.evidence[1].id == "case-file-2"
    assert upgraded.evidence[1].citation_anchor == "[證物二]"
    assert deactivated.evidence[0].status == "inactive"
    assert third.evidence[2].id == "case-file-3"
    assert third.evidence[2].citation_anchor == "[證物三]"
    stored = json.loads(
        (tmp_path / "meetings" / "meeting-1" / "case_files.json").read_text(
            encoding="utf-8"
        )
    )
    assert stored["schema_version"] == 2
    assert stored["revision"] == 3


def test_versions_keep_role_visibility_and_optimistic_revision(tmp_path: Path) -> None:
    repository = MeetingRepository(tmp_path)
    materials = CaseMaterials(repository)
    created = materials.add_evidence(
        "meeting-1",
        expected_revision=0,
        title="版本一",
        content="v1",
        visible_roles=["Judge"],
        limits=CaseMaterialLimits(per_item_chars=10, total_chars=20),
    )

    updated = materials.add_evidence_version(
        "meeting-1",
        created.evidence[0].id,
        expected_revision=1,
        title="版本二",
        content="v2 body",
        visible_roles=["Defense"],
        limits=CaseMaterialLimits(per_item_chars=10, total_chars=20),
    )

    evidence = updated.evidence[0]
    assert evidence.active_version == 2
    assert evidence.versions[0].visible_roles == ["Judge"]
    assert evidence.versions[1].visible_roles == ["Defense"]
    with pytest.raises(CaseMaterialConflict, match="expected 2, got 1"):
        materials.set_evidence_active(
            "meeting-1",
            evidence.id,
            active=False,
            expected_revision=1,
            limits=CaseMaterialLimits(per_item_chars=10, total_chars=20),
        )


def test_case_notes_are_versioned_prompt_materials(tmp_path: Path) -> None:
    materials = CaseMaterials(MeetingRepository(tmp_path))

    created = materials.add_note(
        "meeting-1",
        expected_revision=0,
        title="法院已確認",
        content="基地位置無爭議",
        visible_roles=["Judge", "Defense"],
        source_event_id="human-1",
        limits=CaseMaterialLimits(per_item_chars=100, total_chars=1000),
    )
    updated = materials.add_note_version(
        "meeting-1",
        created.notes[0].id,
        expected_revision=1,
        title="法院已確認",
        content="基地位置與面積無爭議",
        visible_roles=["Judge"],
        limits=CaseMaterialLimits(per_item_chars=100, total_chars=1000),
    )

    note = updated.notes[0]
    assert note.id == "case-note-1"
    assert note.active_version == 2
    assert note.versions[0].source_event_id == "human-1"
    assert note.versions[1].source_event_id is None
