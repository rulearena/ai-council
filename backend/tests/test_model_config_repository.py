from __future__ import annotations

from pathlib import Path

from ai_council.models.config import ModelConfigRepository


def test_repository_loads_models_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        """
models:
  - id: qwen27
    adapter: openai-compatible-http
    base_url: http://192.168.50.80:8487/v1
    model: bartowski/Qwen_Qwen3.6-27B-GGUF
    api_key_env: null
    supports_json_mode: true
    extra_body:
      chat_template_kwargs:
        enable_thinking: false
""".strip(),
        encoding="utf-8",
    )

    models = ModelConfigRepository(config_path).list_models()

    assert len(models) == 1
    model = models[0]
    assert model.id == "qwen27"
    assert model.adapter == "openai-compatible-http"
    assert model.base_url == "http://192.168.50.80:8487/v1"
    assert model.model == "bartowski/Qwen_Qwen3.6-27B-GGUF"
    assert model.api_key_env is None
    assert model.supports_json_mode is True
    assert model.extra_body == {"chat_template_kwargs": {"enable_thinking": False}}
    assert model.status == "unknown"


def test_repository_returns_empty_list_when_config_is_missing(tmp_path: Path) -> None:
    models = ModelConfigRepository(tmp_path / "missing.yaml").list_models()

    assert models == []


def test_repository_loads_multiple_models_with_default_fields(tmp_path: Path) -> None:
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        """
models:
  - id: mock-fast
    adapter: mock
  - id: ornith
    adapter: openai-compatible-http
    base_url: http://192.168.50.81:8488/v1
    model: deepreinforce-ai/Ornith-1.0-35B-GGUF
    supports_json_mode: true
""".strip(),
        encoding="utf-8",
    )

    models = ModelConfigRepository(config_path).list_models()

    assert [model.id for model in models] == ["mock-fast", "ornith"]
    assert models[0].base_url is None
    assert models[0].model is None
    assert models[0].supports_json_mode is False
    assert models[0].status == "unknown"
    assert models[1].api_key_env is None
