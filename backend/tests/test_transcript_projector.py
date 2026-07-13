from __future__ import annotations

from ai_council.meetings.transcript import TranscriptProjector


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
        "**Status:** completed\n"
        "\n"
        "### Summary\n"
        "\n"
        "提出初始方案\n"
        "\n"
        "### Arguments\n"
        "\n"
        "- **清楚切分:** 先做後端核心。\n"
        "\n"
        "### Risks\n"
        "\n"
        "- **範圍膨脹:** 避免一開始做 UI。\n"
        "\n"
        "### Recommendation\n"
        "\n"
        "先完成 event log。\n"
        "\n"
        "## Red - red-critique\n"
        "\n"
        "**Status:** completed\n"
        "\n"
        "### Summary\n"
        "\n"
        "指出測試不足\n"
        "\n"
        "### Arguments\n"
        "\n"
        "_None_\n"
        "\n"
        "### Risks\n"
        "\n"
        "_None_\n"
        "\n"
        "### Recommendation\n"
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
        "**Status:** completed\n"
        "\n"
        "### Summary\n"
        "\n"
        "有條件核准上線\n"
        "\n"
        "### Decision\n"
        "\n"
        "approve-with-conditions\n"
        "\n"
        "### Findings\n"
        "\n"
        "- **驗收完成:** 測試紀錄完整。\n"
        "  - Evidence: [證物一], [證物二]\n"
        "\n"
        "### Risks\n"
        "\n"
        "- **回滾風險:** 演練尚未完成。\n"
        "  - Evidence: [證物二]\n"
        "\n"
        "### Recommendation\n"
        "\n"
        "完成演練後上線。\n"
        "\n"
        "### Conditions\n"
        "\n"
        "- 完成回滾演練\n"
        "\n"
        "### Unresolved Questions\n"
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
        "**Status:** failed\n"
        "\n"
        "**Error:** invalid JSON\n"
        "\n"
        "## Judge - judge-decide\n"
        "\n"
        "**Status:** cancelled\n"
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
        "## Human - human-message\n"
        "\n"
        "**Status:** completed\n"
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
