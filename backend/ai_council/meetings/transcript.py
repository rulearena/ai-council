from __future__ import annotations

from typing import Any


class TranscriptProjector:
    def project(self, events: list[dict[str, Any]], *, title: str) -> str:
        lines = [f"# {title}", ""]

        for index, event in enumerate(events):
            if index:
                lines.append("")
            lines.extend(self._render_event(event))

        return "\n".join(lines) + "\n"

    def _render_event(self, event: dict[str, Any]) -> list[str]:
        role = event.get("role", "Unknown")
        step_id = event.get("step_id", "unknown-step")
        status = event.get("status", "unknown")
        heading = f"## {role} - {step_id}"
        if event.get("corrects_event_id"):
            heading += "（訂正）"
        lines = [
            heading,
            "",
            f"**Status:** {status}",
        ]

        if status != "completed":
            error = event.get("error")
            if error:
                lines.extend(["", f"**Error:** {error}"])
            return lines

        if role == "Human":
            lines.extend(["", str(event.get("content", ""))])
            return lines

        parsed_output = event.get("parsed_output") or {}
        if event.get("output_schema_id") == "structured-verdict/v1":
            lines.extend(self._render_structured_verdict(parsed_output))
            return lines
        lines.extend(
            [
                "",
                "### Summary",
                "",
                str(parsed_output.get("summary", "")),
                "",
                "### Arguments",
                "",
                *self._render_items(parsed_output.get("arguments") or []),
                "",
                "### Risks",
                "",
                *self._render_items(parsed_output.get("risks") or []),
                "",
                "### Recommendation",
                "",
                str(parsed_output.get("recommendation", "")),
            ]
        )
        return lines

    def _render_structured_verdict(self, parsed_output: dict[str, Any]) -> list[str]:
        return [
            "",
            "### Summary",
            "",
            str(parsed_output.get("summary", "")),
            "",
            "### Decision",
            "",
            str(parsed_output.get("decision", "")),
            "",
            "### Findings",
            "",
            *self._render_verdict_items(parsed_output.get("findings") or []),
            "",
            "### Risks",
            "",
            *self._render_verdict_items(parsed_output.get("risks") or []),
            "",
            "### Recommendation",
            "",
            str(parsed_output.get("recommendation", "")),
            "",
            "### Conditions",
            "",
            *self._render_strings(parsed_output.get("conditions") or []),
            "",
            "### Unresolved Questions",
            "",
            *self._render_strings(parsed_output.get("unresolved_questions") or []),
        ]

    @staticmethod
    def _render_items(items: list[dict[str, Any]]) -> list[str]:
        if not items:
            return ["_None_"]
        return [
            f"- **{item.get('title', '')}:** {item.get('detail', '')}"
            for item in items
        ]

    @staticmethod
    def _render_verdict_items(items: list[dict[str, Any]]) -> list[str]:
        if not items:
            return ["_None_"]
        lines: list[str] = []
        for item in items:
            lines.append(f"- **{item.get('title', '')}:** {item.get('detail', '')}")
            evidence_refs = item.get("evidence_refs") or []
            if evidence_refs:
                lines.append(f"  - Evidence: {', '.join(str(ref) for ref in evidence_refs)}")
        return lines

    @staticmethod
    def _render_strings(items: list[str]) -> list[str]:
        if not items:
            return ["_None_"]
        return [f"- {item}" for item in items]
