from __future__ import annotations

from ai_council.meetings.chatroom_sources import (
    project_chatroom_sources,
    validate_chatroom_sources,
)


def _materials() -> dict:
    return {
        "evidence": [
            {
                "id": "evidence-mirror",
                "status": "active",
                "active_version": 1,
                "versions": [{
                    "version": 1,
                    "title": "待辦總覽.md",
                    "content": "mirror body",
                    "visible_roles": ["Advisor"],
                    "host_acl_explicit": True,
                    "size": 11,
                }],
            },
            {
                "id": "evidence-independent",
                "status": "active",
                "active_version": 1,
                "versions": [{
                    "version": 1,
                    "title": "待辦總覽.md",
                    "content": "independent body",
                    "visible_roles": ["Critic"],
                    "host_acl_explicit": True,
                    "size": 17,
                }],
            },
        ],
        "notes": [{
            "id": "note-1",
            "status": "active",
            "active_version": 1,
            "versions": [{"version": 1, "title": "待辦總覽.md", "content": "secret"}],
        }],
    }


def test_projection_suppresses_only_exact_mirror_and_keeps_same_label_evidence() -> None:
    sources = project_chatroom_sources(
        meeting_id="meeting-1",
        materials=_materials(),
        attachment_events=[{
            "event_id": "meeting-1:attachment-added:1",
            "file_id": "file-1",
            "filename": "待辦總覽.md",
            "extension": ".md",
            "size": 11,
            "evidence_id": "evidence-mirror",
        }],
        active_role_ids=["host", "Advisor", "Critic"],
        readable_attachment_ids={"file-1"},
    )

    assert [item["source_ref"] for item in sources] == [
        "attachment:file-1",
        "evidence:evidence-independent",
    ]
    assert sources[0]["visible_roles"] == ["Advisor"]
    assert sources[1]["visible_roles"] == ["Critic"]
    assert all(item["kind"] != "note" for item in sources)


def test_legacy_unlinked_attachment_is_visible_to_frozen_roster() -> None:
    sources = project_chatroom_sources(
        meeting_id="meeting-1",
        materials={"evidence": [], "notes": []},
        attachment_events=[{
            "event_id": "meeting-1:attachment-added:1",
            "file_id": "file-1",
            "filename": "legacy.txt",
            "extension": ".txt",
            "size": 3,
        }],
        active_role_ids=["host", "Advisor"],
        readable_attachment_ids={"file-1"},
    )
    assert sources[0]["visible_roles"] == ["host", "Advisor"]


def test_source_validation_is_atomic_and_uses_kind_specific_readability() -> None:
    sources = [
        {
            "source_ref": "attachment:pdf-1",
            "active": True,
            "readable": False,
            "visible_roles": ["host", "Advisor"],
        },
        {
            "source_ref": "evidence:no-extension",
            "active": True,
            "readable": True,
            "visible_roles": ["host", "Advisor"],
        },
    ]
    assert validate_chatroom_sources(
        sources, ["attachment:pdf-1"], ["Advisor"]
    ) == (False, "SOURCE_NOT_READABLE", "attachment:pdf-1", None)
    assert validate_chatroom_sources(
        sources, ["evidence:no-extension"], ["Advisor"]
    )[0] is True
