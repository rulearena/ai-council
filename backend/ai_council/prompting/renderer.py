from __future__ import annotations

from pathlib import Path


class PromptRenderer:
    def __init__(self, prompt_dir: Path | str) -> None:
        self.prompt_dir = Path(prompt_dir)

    def render(
        self,
        *,
        template_name: str,
        role: str,
        topic: str,
        prior_transcript: str,
        required_json_schema: str,
    ) -> str:
        template = (self.prompt_dir / f"{template_name}.md").read_text(encoding="utf-8")
        values = {
            "role": role,
            "topic": topic,
            "prior_transcript": prior_transcript,
            "required_json_schema": required_json_schema,
        }
        rendered = template
        for key, value in values.items():
            rendered = rendered.replace("{{ " + key + " }}", value)
            rendered = rendered.replace("{{" + key + "}}", value)
        return rendered
