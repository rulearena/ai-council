from __future__ import annotations

from ai_council.meetings.transcript import TranscriptProjector


def test_projector_skips_attachment_tombstone_events() -> None:
    events = [
        {
            "event_id": "meeting-1:attachment-added:aaa",
            "step_id": "attachment-added",
            "role": "Human",
            "status": "completed",
            "file_id": "attachment-abc",
            "filename": "note.txt",
        },
        {
            "event_id": "meeting-1:attachment-removed:aaa",
            "step_id": "attachment-removed",
            "role": "Human",
            "status": "completed",
            "file_id": "attachment-abc",
            "filename": "note.txt",
        },
        {
            "event_id": "e1",
            "step_id": "human-message",
            "role": "Human",
            "status": "completed",
            "content": "會後決議",
        },
    ]

    markdown = TranscriptProjector().project(events, title="議事紀錄")

    assert "attachment-removed" not in markdown
    assert "note.txt" not in markdown
    assert "會後決議" in markdown


def test_projector_uses_presentation_labels_and_chinese_fixed_fields() -> None:
    events = [
        {
            "step_id": "courtroom-verdict",
            "role": "Judge",
            "status": "completed",
            "output_schema_id": "structured-verdict/v1",
            "parsed_output": {
                "summary": "證據足以支持判決。",
                "decision": "approve-with-conditions",
                "findings": [],
                "risks": [],
                "recommendation": "補充鑑定。",
                "conditions": [],
                "unresolved_questions": [],
            },
        }
    ]

    markdown = TranscriptProjector().project(
        events,
        title="土地糾紛案",
        role_labels={"Judge": "法官"},
        step_labels={"courtroom-verdict": "法官判決"},
    )

    assert "# 土地糾紛案" in markdown
    assert "## 法官 - 法官判決" in markdown
    assert "**狀態：** 已完成" in markdown
    assert "### 角色回應" in markdown
    assert "### 裁決\n\n有條件核准" in markdown
    assert "### 判定事項" in markdown
    assert "### 風險" in markdown
    assert "### 建議處置" in markdown
    assert "### 附帶條件" in markdown
    assert "### 待釐清事項" in markdown
    assert "courtroom-verdict" not in markdown


def test_projector_renders_completed_role_outputs() -> None:
    events = [
        {
            "step_id": "blue-propose",
            "role": "Blue",
            "status": "completed",
            "parsed_output": {
                "summary": "提出初始方案",
                "arguments": [{"title": "清楚切分", "detail": "先做後端核心。"}],
                "risks": [{"title": "範圍膨脹", "detail": "避免一開始做 UI。"}],
                "recommendation": "先完成 event log。",
            },
        },
        {
            "step_id": "red-critique",
            "role": "Red",
            "status": "completed",
            "parsed_output": {
                "summary": "指出測試不足",
                "arguments": [],
                "risks": [],
                "recommendation": "補 retry 測試。",
            },
        },
    ]

    markdown = TranscriptProjector().project(events, title="架構評審")

    assert markdown == (
        "# 架構評審\n"
        "\n"
        "## Blue - blue-propose\n"
        "\n"
        "**狀態：** 已完成\n"
        "\n"
        "### 角色回應\n"
        "\n"
        "提出初始方案\n"
        "\n"
        "### 論點\n"
        "\n"
        "- **清楚切分:** 先做後端核心。\n"
        "\n"
        "### 風險\n"
        "\n"
        "- **範圍膨脹:** 避免一開始做 UI。\n"
        "\n"
        "### 建議處置\n"
        "\n"
        "先完成 event log。\n"
        "\n"
        "## Red - red-critique\n"
        "\n"
        "**狀態：** 已完成\n"
        "\n"
        "### 角色回應\n"
        "\n"
        "指出測試不足\n"
        "\n"
        "### 論點\n"
        "\n"
        "_無_\n"
        "\n"
        "### 風險\n"
        "\n"
        "_無_\n"
        "\n"
        "### 建議處置\n"
        "\n"
        "補 retry 測試。\n"
    )


def test_projector_renders_rich_verdict_with_evidence_and_follow_up() -> None:
    events = [
        {
            "step_id": "judge-decide",
            "role": "Judge",
            "status": "completed",
            "output_schema_id": "structured-verdict/v1",
            "parsed_output": {
                "summary": "有條件核准上線",
                "decision": "approve-with-conditions",
                "findings": [
                    {
                        "title": "驗收完成",
                        "detail": "測試紀錄完整。",
                        "evidence_refs": ["[證物一]", "[證物二]"],
                    }
                ],
                "risks": [
                    {
                        "title": "回滾風險",
                        "detail": "演練尚未完成。",
                        "evidence_refs": ["[證物二]"],
                    }
                ],
                "recommendation": "完成演練後上線。",
                "conditions": ["完成回滾演練"],
                "unresolved_questions": ["尖峰容量是否足夠？"],
            },
        }
    ]

    markdown = TranscriptProjector().project(events, title="上線審查")

    assert markdown == (
        "# 上線審查\n"
        "\n"
        "## Judge - judge-decide\n"
        "\n"
        "**狀態：** 已完成\n"
        "\n"
        "### 角色回應\n"
        "\n"
        "有條件核准上線\n"
        "\n"
        "### 裁決\n"
        "\n"
        "有條件核准\n"
        "\n"
        "### 判定事項\n"
        "\n"
        "- **驗收完成:** 測試紀錄完整。\n"
        "  - 證據：[證物一], [證物二]\n"
        "\n"
        "### 風險\n"
        "\n"
        "- **回滾風險:** 演練尚未完成。\n"
        "  - 證據：[證物二]\n"
        "\n"
        "### 建議處置\n"
        "\n"
        "完成演練後上線。\n"
        "\n"
        "### 附帶條件\n"
        "\n"
        "- 完成回滾演練\n"
        "\n"
        "### 待釐清事項\n"
        "\n"
        "- 尖峰容量是否足夠？\n"
    )


def test_projector_renders_failed_and_cancelled_status_entries() -> None:
    events = [
        {
            "step_id": "red-critique",
            "role": "Red",
            "status": "failed",
            "error": "invalid JSON",
        },
        {
            "step_id": "judge-decide",
            "role": "Judge",
            "status": "cancelled",
        },
    ]

    markdown = TranscriptProjector().project(events, title="失敗案例")

    assert markdown == (
        "# 失敗案例\n"
        "\n"
        "## Red - red-critique\n"
        "\n"
        "**狀態：** 失敗\n"
        "\n"
        "**錯誤：** invalid JSON\n"
        "\n"
        "## Judge - judge-decide\n"
        "\n"
        "**狀態：** 已取消\n"
    )


def test_projector_renders_human_chair_messages() -> None:
    events = [
        {
            "step_id": "human-message",
            "role": "Human",
            "status": "completed",
            "content": "我覺得方案太大，先聚焦在可以一週內完成的版本。",
        }
    ]

    markdown = TranscriptProjector().project(events, title="主席回饋")

    assert markdown == (
        "# 主席回饋\n"
        "\n"
        "## 主席 - 主席發言\n"
        "\n"
        "**狀態：** 已完成\n"
        "\n"
        "我覺得方案太大，先聚焦在可以一週內完成的版本。\n"
    )


def test_projector_output_is_deterministic() -> None:
    events = [
        {
            "step_id": "judge-decide",
            "role": "Judge",
            "status": "completed",
            "parsed_output": {
                "summary": "結論",
                "arguments": [],
                "risks": [],
                "recommendation": "採用。",
            },
        }
    ]
    projector = TranscriptProjector()

    assert projector.project(events, title="同一場會議") == projector.project(
        events,
        title="同一場會議",
    )
