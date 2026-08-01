from __future__ import annotations

import json
from pathlib import Path

import pytest

from ai_council.api import (
    active_case_evidence_projection,
    active_case_material_prompt_items,
    case_evidence_by_role,
    case_file_manifest,
    case_files_by_role,
    evidence_anchor_label,
    localize_evidence_anchor,
    material_inputs_for_runner,
    meeting_inputs_for_runner,
    project_case_files,
    project_case_materials,
)
from ai_council.meetings.case_materials import (
    CaseMaterialsView,
    CaseNote,
    EvidenceMaterial,
    MaterialRevision,
    MaterialVersion,
)
from ai_council.meetings.input_envelope import CASE_EVIDENCE_BY_ROLE_INPUT
from ai_council.meetings.runner import CASE_FILES_BY_ROLE_INPUT
from ai_council.meetings.repository import MeetingRepository
from ai_council.models.adapters import MockModelAdapter, ModelRequest, ModelResponse
from ai_council.models.config import ModelConfig
from ai_council.prompting.parser import EVIDENCE_REF_PATTERN
from ai_council.prompting.schemas import DEFAULT_OUTPUT_SCHEMA_REGISTRY


def evidence_item() -> dict[str, object]:
    return {
        "kind": "evidence",
        "id": "evidence-1",
        "evidence_index": 1,
        "citation_anchor": "[證物一]",
        "version": 1,
        "title": "檢方事故時間線",
        "content": "10:05 error rate spike",
        "visible_roles": ["Judge"],
        "size": 20,
    }


def material_view() -> CaseMaterialsView:
    version = MaterialVersion(
        version=1,
        title="檢方事故時間線",
        content="10:05 error rate spike",
        visible_roles=["Judge"],
        size=20,
        created_at="2026-01-01T00:00:00+00:00",
        source_event_id="evt-1",
    )
    return CaseMaterialsView(
        schema_version=2,
        revision=1,
        evidence=[
            EvidenceMaterial(
                id="evidence-1",
                evidence_index=1,
                citation_anchor="[證物一]",
                status="active",
                active_version=1,
                versions=[version],
            )
        ],
        notes=[],
        pending_impact=None,
        revision_history=[
            MaterialRevision(
                revision=1,
                parent_revision=None,
                transition="create",
                created_at="2026-01-01T00:00:00+00:00",
                evidence=[
                    {
                        "id": "evidence-1",
                        "evidence_index": 1,
                        "citation_anchor": "[證物一]",
                        "status": "active",
                        "version": 1,
                        "visible_roles": ["Judge"],
                    }
                ],
                notes=[],
            )
        ],
    )


@pytest.mark.parametrize(
    ("mode_id", "label"),
    [
        ("courtroom", "證物"),
        ("chatroom", "附件"),
        ("red-blue", "附件"),
        ("relay", "附件"),
        ("parallel", "附件"),
        (None, "證物"),
    ],
)
def test_evidence_anchor_label(mode_id: str | None, label: str) -> None:
    assert evidence_anchor_label(mode_id) == label


@pytest.mark.parametrize(
    ("anchor", "mode_id", "expected"),
    [
        ("[證物一]", "courtroom", "[證物一]"),
        ("[證物一]", "chatroom", "[附件一]"),
        ("[證物一]", None, "[證物一]"),
        ("[附件一]", "chatroom", "[附件一]"),
        ("[附件一]", "courtroom", "[附件一]"),
    ],
)
def test_localize_evidence_anchor_is_mode_aware_and_idempotent(
    anchor: str, mode_id: str | None, expected: str
) -> None:
    assert localize_evidence_anchor(anchor, mode_id) == expected


def test_case_files_by_role_localizes_block_header_and_instruction_for_chatroom() -> None:
    rendered = case_files_by_role([evidence_item()], mode_id="chatroom")
    block = rendered["Judge"]
    assert "### [附件一] 檢方事故時間線" in block
    assert "引用案卷中的事實或主張時，必須附上對應的 [附件…] 引用錨點" in block
    assert "不可假造不存在的附件錨點" in block
    assert "證物" not in block


def test_case_files_by_role_keeps_courtroom_wording() -> None:
    rendered = case_files_by_role([evidence_item()], mode_id="courtroom")
    block = rendered["Judge"]
    assert "### [證物一] 檢方事故時間線" in block
    assert "引用案卷中的事實或主張時，必須附上對應的 [證物…] 引用錨點" in block
    assert "不可假造不存在的證物錨點" in block


def test_case_evidence_by_role_localizes_citation_anchor() -> None:
    chatroom = case_evidence_by_role([evidence_item()], mode_id="chatroom")
    assert chatroom["Judge"][0]["citation_anchor"] == "[附件一]"
    courtroom = case_evidence_by_role([evidence_item()], mode_id="courtroom")
    assert courtroom["Judge"][0]["citation_anchor"] == "[證物一]"


def test_active_case_material_prompt_items_localizes_citation_anchor() -> None:
    chatroom = active_case_material_prompt_items(material_view(), mode_id="chatroom")
    assert chatroom[0]["citation_anchor"] == "[附件一]"
    courtroom = active_case_material_prompt_items(material_view(), mode_id="courtroom")
    assert courtroom[0]["citation_anchor"] == "[證物一]"


def test_active_case_evidence_projection_localizes_citation_anchor() -> None:
    chatroom = active_case_evidence_projection(material_view(), mode_id="chatroom")
    assert chatroom[0]["citation_anchor"] == "[附件一]"
    courtroom = active_case_evidence_projection(material_view(), mode_id="courtroom")
    assert courtroom[0]["citation_anchor"] == "[證物一]"


def test_project_case_materials_localizes_active_evidence_anchor() -> None:
    chatroom = project_case_materials(
        material_view(), active_epoch_id="epoch-1", mode_id="chatroom"
    )
    assert chatroom["evidence"][0]["citation_anchor"] == "[附件一]"
    courtroom = project_case_materials(
        material_view(), active_epoch_id="epoch-1", mode_id="courtroom"
    )
    assert courtroom["evidence"][0]["citation_anchor"] == "[證物一]"


def test_project_case_files_localizes_citation_anchor() -> None:
    chatroom = project_case_files([evidence_item()], mode_id="chatroom")
    assert chatroom[0]["citation_anchor"] == "[附件一]"
    courtroom = project_case_files([evidence_item()], mode_id="courtroom")
    assert courtroom[0]["citation_anchor"] == "[證物一]"


def test_case_file_manifest_localizes_citation_anchor() -> None:
    chatroom = case_file_manifest([evidence_item()], mode_id="chatroom")
    assert chatroom[0]["citation_anchor"] == "[附件一]"
    courtroom = case_file_manifest([evidence_item()], mode_id="courtroom")
    assert courtroom[0]["citation_anchor"] == "[證物一]"


def test_meeting_inputs_for_runner_localizes_from_metadata_mode() -> None:
    inputs = meeting_inputs_for_runner({"mode_id": "chatroom"}, [evidence_item()])
    assert "引用案卷中的事實或主張時，必須附上對應的 [附件…] 引用錨點" in inputs[CASE_FILES_BY_ROLE_INPUT]["Judge"]
    assert inputs[CASE_EVIDENCE_BY_ROLE_INPUT]["Judge"][0]["citation_anchor"] == "[附件一]"


def test_meeting_inputs_for_runner_is_idempotent_over_localized_case_files() -> None:
    localized = [dict(evidence_item(), citation_anchor="[附件一]")]
    inputs = meeting_inputs_for_runner({"mode_id": "chatroom"}, localized)
    assert "### [附件一] 檢方事故時間線" in inputs[CASE_FILES_BY_ROLE_INPUT]["Judge"]
    assert inputs[CASE_EVIDENCE_BY_ROLE_INPUT]["Judge"][0]["citation_anchor"] == "[附件一]"


def test_meeting_inputs_for_runner_keeps_legacy_courtroom_wording() -> None:
    inputs = meeting_inputs_for_runner({}, [evidence_item()])
    assert "引用案卷中的事實或主張時，必須附上對應的 [證物…] 引用錨點" in inputs[CASE_FILES_BY_ROLE_INPUT]["Judge"]


def test_material_inputs_for_runner_localizes_from_metadata_mode() -> None:
    inputs = material_inputs_for_runner({"mode_id": "chatroom"}, material_view())
    assert inputs[CASE_FILES_BY_ROLE_INPUT]["Judge"] == (
        "引用案卷中的事實或主張時，必須附上對應的 [附件…] 引用錨點；"
        "不可假造不存在的附件錨點。\n\n"
        "### [附件一] 檢方事故時間線\n10:05 error rate spike"
    )
    assert inputs[CASE_EVIDENCE_BY_ROLE_INPUT]["Judge"][0]["citation_anchor"] == "[附件一]"


@pytest.mark.parametrize("anchor", ["[附件一]", "[附件十]", "[附件一百零一]"])
def test_parser_accepts_attachment_anchors(anchor: str) -> None:
    assert EVIDENCE_REF_PATTERN.fullmatch(anchor) is not None


@pytest.mark.parametrize("anchor", ["[證物一]", "[證物十]", "[證物一百零一]"])
def test_parser_still_accepts_evidence_anchors(anchor: str) -> None:
    assert EVIDENCE_REF_PATTERN.fullmatch(anchor) is not None


@pytest.mark.parametrize("anchor", ["[證物]", "[附件]", "[證物A]", "[附件一"])
def test_parser_rejects_anchor_shapes_without_a_chinese_numeral(anchor: str) -> None:
    assert EVIDENCE_REF_PATTERN.fullmatch(anchor) is None


def test_mock_adapter_backfills_attachment_anchor_from_visible_case_files_block() -> None:
    codec = DEFAULT_OUTPUT_SCHEMA_REGISTRY.get("structured-verdict/v1")
    prompt = (
        "Case files visible to you:\n"
        "### [附件二] 上線檢查表\n驗收完成。\n\n"
        "Prior transcript:\n尚未發言\n\n"
        f"Return exactly one JSON object matching this schema:\n{codec.schema}"
    )

    response: ModelResponse = MockModelAdapter().complete(
        ModelRequest(
            prompt=prompt,
            model_config=ModelConfig(id="mock-fast", adapter="mock"),
            output_schema_id="structured-verdict/v1",
        )
    )

    assert codec.parse(response.raw_output)["findings"][0]["evidence_refs"] == ["[附件二]"]
