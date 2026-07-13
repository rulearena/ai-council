from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

ModelStatus = Literal["unknown", "available", "unavailable"]
SUPPORTED_ADAPTERS = {
    "mock",
    "openai-compatible-http",
    "anthropic-http",
    "gemini-http",
    "subscription-cli",
}


class ModelConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ModelPricing:
    currency: str
    input_per_1m_tokens: float
    output_per_1m_tokens: float


@dataclass(frozen=True)
class ModelConfig:
    id: str
    adapter: str
    base_url: str | None = None
    model: str | None = None
    api_key_env: str | None = None
    supports_json_mode: bool = False
    extra_body: dict[str, Any] = field(default_factory=dict)
    pricing: ModelPricing | None = None
    command: list[str] | None = None
    timeout_seconds: float = 120
    status: ModelStatus = "unknown"


class ModelConfigRepository:
    def __init__(self, config_path: Path | str) -> None:
        self.config_path = Path(config_path)

    def list_models(self) -> list[ModelConfig]:
        if not self.config_path.exists():
            return []

        raw_config = self._read_config()
        raw_models = raw_config.get("models", [])
        if not isinstance(raw_models, list):
            raise ModelConfigError("models must be a list")
        return [_model_from_yaml_item(raw_model) for raw_model in raw_models]

    def save_model(self, model: ModelConfig) -> ModelConfig:
        validate_model_config(model)
        raw_config = self._read_config()
        raw_models = [
            _model_to_yaml_item(existing)
            for existing in self.list_models()
        ]
        next_item = _model_to_yaml_item(model)
        for index, existing in enumerate(raw_models):
            if existing["id"] == model.id:
                raw_models[index] = next_item
                break
        else:
            raw_models.append(next_item)
        raw_config["models"] = raw_models
        self._write_config(raw_config)
        return model

    def delete_model(self, model_id: str) -> bool:
        raw_config = self._read_config()
        raw_models = raw_config.get("models", [])
        next_models = [
            raw_model
            for raw_model in raw_models
            if raw_model.get("id") != model_id
        ]
        if len(next_models) == len(raw_models):
            return False
        raw_config["models"] = next_models
        self._write_config(raw_config)
        return True

    def _read_config(self) -> dict[str, Any]:
        if not self.config_path.exists():
            return {}
        return yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}

    def _write_config(self, raw_config: dict[str, Any]) -> None:
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        serialized = yaml.safe_dump(raw_config, sort_keys=False, allow_unicode=True)
        temp_path = self.config_path.with_name(f".{self.config_path.name}.tmp")
        try:
            temp_path.write_text(serialized, encoding="utf-8")
            os.replace(temp_path, self.config_path)
        finally:
            temp_path.unlink(missing_ok=True)


def validate_model_config(model: ModelConfig) -> None:
    if not model.id.strip():
        raise ModelConfigError("Model id is required")
    if model.adapter not in SUPPORTED_ADAPTERS:
        raise ModelConfigError(f"Unknown adapter: {model.adapter}")
    if model.adapter in {"openai-compatible-http", "anthropic-http", "gemini-http"}:
        if not model.base_url or not model.model:
            raise ModelConfigError(f"{model.adapter} requires base_url and model")
    if model.adapter == "subscription-cli":
        if not model.command:
            raise ModelConfigError("subscription-cli requires command")
        if not any("{prompt}" in argument for argument in model.command):
            raise ModelConfigError("subscription-cli command requires a {prompt} placeholder")
    if model.pricing is not None:
        if not model.pricing.currency.strip():
            raise ModelConfigError("pricing.currency is required")
        if model.pricing.input_per_1m_tokens < 0:
            raise ModelConfigError("pricing.input_per_1m_tokens must be non-negative")
        if model.pricing.output_per_1m_tokens < 0:
            raise ModelConfigError("pricing.output_per_1m_tokens must be non-negative")


def _model_to_yaml_item(model: ModelConfig) -> dict[str, Any]:
    item: dict[str, Any] = {
        "id": model.id,
        "adapter": model.adapter,
    }
    if model.base_url is not None:
        item["base_url"] = model.base_url
    if model.model is not None:
        item["model"] = model.model
    if model.api_key_env is not None:
        item["api_key_env"] = model.api_key_env
    if model.supports_json_mode:
        item["supports_json_mode"] = model.supports_json_mode
    if model.extra_body:
        item["extra_body"] = model.extra_body
    if model.pricing is not None:
        item["pricing"] = {
            "currency": model.pricing.currency,
            "input_per_1m_tokens": model.pricing.input_per_1m_tokens,
            "output_per_1m_tokens": model.pricing.output_per_1m_tokens,
        }
    if model.command is not None:
        item["command"] = model.command
    if model.timeout_seconds != 120:
        item["timeout_seconds"] = model.timeout_seconds
    return item


def _model_from_yaml_item(raw_model: Any) -> ModelConfig:
    if not isinstance(raw_model, dict):
        raise ModelConfigError("Model entry must be a mapping")
    if "id" not in raw_model or "adapter" not in raw_model:
        raise ModelConfigError("Model entry requires id and adapter")
    model = ModelConfig(
        id=str(raw_model["id"]),
        adapter=str(raw_model["adapter"]),
        base_url=raw_model.get("base_url"),
        model=raw_model.get("model"),
        api_key_env=raw_model.get("api_key_env"),
        supports_json_mode=raw_model.get("supports_json_mode", False),
        extra_body=raw_model.get("extra_body") or {},
        pricing=_pricing_from_yaml(raw_model.get("pricing")),
        command=raw_model.get("command"),
        timeout_seconds=float(raw_model.get("timeout_seconds", 120)),
    )
    return model


def _pricing_from_yaml(raw_pricing: Any) -> ModelPricing | None:
    if raw_pricing is None:
        return None
    if not isinstance(raw_pricing, dict):
        raise ModelConfigError("pricing must be a mapping")
    try:
        currency = raw_pricing["currency"]
        input_rate = raw_pricing["input_per_1m_tokens"]
        output_rate = raw_pricing["output_per_1m_tokens"]
    except KeyError as error:
        raise ModelConfigError(f"pricing.{error.args[0]} is required") from error
    if not isinstance(currency, str):
        raise ModelConfigError("pricing.currency must be a string")
    try:
        pricing = ModelPricing(
            currency=currency,
            input_per_1m_tokens=float(input_rate),
            output_per_1m_tokens=float(output_rate),
        )
    except (TypeError, ValueError) as error:
        raise ModelConfigError("pricing token rates must be numbers") from error
    if not pricing.currency.strip():
        raise ModelConfigError("pricing.currency is required")
    if pricing.input_per_1m_tokens < 0:
        raise ModelConfigError("pricing.input_per_1m_tokens must be non-negative")
    if pricing.output_per_1m_tokens < 0:
        raise ModelConfigError("pricing.output_per_1m_tokens must be non-negative")
    return pricing
