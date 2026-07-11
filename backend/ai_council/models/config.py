from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

ModelStatus = Literal["unknown", "available", "unavailable"]


@dataclass(frozen=True)
class ModelConfig:
    id: str
    adapter: str
    base_url: str | None = None
    model: str | None = None
    api_key_env: str | None = None
    supports_json_mode: bool = False
    extra_body: dict[str, Any] = field(default_factory=dict)
    command: list[str] | None = None
    timeout_seconds: float = 120
    status: ModelStatus = "unknown"


class ModelConfigRepository:
    def __init__(self, config_path: Path | str) -> None:
        self.config_path = Path(config_path)

    def list_models(self) -> list[ModelConfig]:
        if not self.config_path.exists():
            return []

        raw_config = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        return [
            ModelConfig(
                id=raw_model["id"],
                adapter=raw_model["adapter"],
                base_url=raw_model.get("base_url"),
                model=raw_model.get("model"),
                api_key_env=raw_model.get("api_key_env"),
                supports_json_mode=raw_model.get("supports_json_mode", False),
                extra_body=raw_model.get("extra_body") or {},
                command=raw_model.get("command"),
                timeout_seconds=float(raw_model.get("timeout_seconds", 120)),
            )
            for raw_model in raw_config.get("models", [])
        ]
