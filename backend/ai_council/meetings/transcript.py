from __future__ import annotations

from typing import Any

from ai_council.meetings.attachments import ATTACHMENT_REMOVED_KIND
from ai_council.meetings.case_profiles import CourtroomCaseProfile, CourtroomCaseProfileError


class TranscriptProjector:
    def project(
        self,
        events: list[dict[str, Any]],
        *,
        title: str,
        role_labels: dict[str, str] | None = None,
        step_labels: dict[str, str] | None = None,
    ) -> str:
        lines = [f"# {title}", ""]

        for index, event in enumerate(events):
            if event.get("result_discarded"):
                continue
            if event.get("step_id") == ATTACHMENT_REMOVED_KIND:
                continue
            if index:
                lines.append("")
            lines.extend(
                self._render_event(
                    event,
                    role_labels=role_labels or {},
                    step_labels=step_labels or {},
                )
            )

        return "\n".join(lines) + "\n"

    def _render_event(
        self,
        event: dict[str, Any],
        *,
        role_labels: dict[str, str],
        step_labels: dict[str, str],
    ) -> list[str]:
        role = event.get("role", "Unknown")
        step_id = event.get("step_id", "unknown-step")
        status = event.get("status", "unknown")
        base_step_id = str(event.get("base_step_id") or step_id)
        role_label = str(
            event.get("role_display")
            or role_labels.get(str(role), "主席" if role == "Human" else str(role))
        )
        built_in_step_labels = {
            "human-message": "主席發言",
            "human-directed-message": "主席追問",
            "human-correction": "主席訂正",
            "meeting-goal-changed": "主席修改會議目標",
            "meeting-closed": "會議結案",
            "meeting-cancelled": "會議取消",
            "meeting-reopened": "重新開啟會議",
        }
        if base_step_id == "meeting":
            built_in_step_labels["meeting"] = {
                "closed": "會議結案",
                "cancelled": "會議取消",
                "reopened": "重新開啟會議",
            }.get(str(status), "會議狀態更新")
        step_label = str(event.get("phase_display") or step_labels.get(
            str(event.get("event_id", "")),
            step_labels.get(
                str(step_id),
                step_labels.get(base_step_id, built_in_step_labels.get(base_step_id, str(step_id))),
            ),
        ))
        heading = f"## {role_label} - {step_label}"
        if event.get("corrects_event_id"):
            heading += "（訂正）"
        lines = [
            heading,
            "",
            f"**狀態：** {self._status_label(str(status))}",
        ]

        if status != "completed":
            error = event.get("error")
            if error:
                lines.extend(["", f"**錯誤：** {error}"])
            return lines

        if role == "Human":
            lines.extend(["", str(event.get("content", ""))])
            return lines

        parsed_output = event.get("parsed_output") or {}
        if event.get("output_schema_id") == "structured-verdict/v1":
            lines.extend(self._render_structured_verdict(parsed_output))
            return lines
        if event.get("output_schema_id") in {
            "courtroom-civil-final/v1",
            "courtroom-criminal-final/v1",
        }:
            try:
                rendered = CourtroomCaseProfile.for_type(str(event.get("case_type"))).render_final(
                    parsed_output
                )
            except CourtroomCaseProfileError:
                rendered = str(parsed_output)
            lines.extend(["", "### 全案最終判決", "", rendered])
            return lines
        lines.extend(
            [
                "",
                "### 角色回應",
                "",
                str(parsed_output.get("summary", "")),
                "",
                "### 論點",
                "",
                *self._render_items(parsed_output.get("arguments") or []),
                "",
                "### 風險",
                "",
                *self._render_items(parsed_output.get("risks") or []),
                "",
                "### 建議處置",
                "",
                str(parsed_output.get("recommendation", "")),
            ]
        )
        return lines

    def _render_structured_verdict(self, parsed_output: dict[str, Any]) -> list[str]:
        return [
            "",
            "### 角色回應",
            "",
            str(parsed_output.get("summary", "")),
            "",
            "### 裁決",
            "",
            self._decision_label(str(parsed_output.get("decision", ""))),
            "",
            "### 判定事項",
            "",
            *self._render_verdict_items(parsed_output.get("findings") or []),
            "",
            "### 風險",
            "",
            *self._render_verdict_items(parsed_output.get("risks") or []),
            "",
            "### 建議處置",
            "",
            str(parsed_output.get("recommendation", "")),
            "",
            "### 附帶條件",
            "",
            *self._render_strings(parsed_output.get("conditions") or []),
            "",
            "### 待釐清事項",
            "",
            *self._render_strings(parsed_output.get("unresolved_questions") or []),
        ]

    @staticmethod
    def _render_items(items: list[dict[str, Any]]) -> list[str]:
        if not items:
            return ["_無_"]
        return [
            f"- **{item.get('title', '')}:** {item.get('detail', '')}"
            for item in items
        ]

    @staticmethod
    def _render_verdict_items(items: list[dict[str, Any]]) -> list[str]:
        if not items:
            return ["_無_"]
        lines: list[str] = []
        for item in items:
            lines.append(f"- **{item.get('title', '')}:** {item.get('detail', '')}")
            evidence_refs = item.get("evidence_refs") or []
            if evidence_refs:
                lines.append(f"  - 證據：{', '.join(str(ref) for ref in evidence_refs)}")
        return lines

    @staticmethod
    def _render_strings(items: list[str]) -> list[str]:
        if not items:
            return ["_無_"]
        return [f"- {item}" for item in items]

    @staticmethod
    def _status_label(status: str) -> str:
        return {
            "completed": "已完成",
            "failed": "失敗",
            "cancelled": "已取消",
            "closed": "已結案",
            "reopened": "已重新開啟",
        }.get(status, status)

    @staticmethod
    def _decision_label(decision: str) -> str:
        return {
            "approve": "核准",
            "approve-with-conditions": "有條件核准",
            "reject": "否決",
            "insufficient-evidence": "證據不足",
        }.get(decision, decision)
