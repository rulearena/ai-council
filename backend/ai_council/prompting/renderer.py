from __future__ import annotations

import hashlib
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
        inputs: dict[str, str] | None = None,
    ) -> str:
        template = self._read_template(template_name)
        values = {
            **{key: str(value) for key, value in (inputs or {}).items()},
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

    def template_hash(self, template_name: str) -> str:
        return hashlib.sha256(self._read_template(template_name).encode("utf-8")).hexdigest()

    def _read_template(self, template_name: str) -> str:
        return (self.prompt_dir / f"{template_name}.md").read_text(encoding="utf-8")
