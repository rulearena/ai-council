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
        lines = [
            f"## {role} - {step_id}",
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

    @staticmethod
    def _render_items(items: list[dict[str, Any]]) -> list[str]:
        if not items:
            return ["_None_"]
        return [
            f"- **{item.get('title', '')}:** {item.get('detail', '')}"
            for item in items
        ]
