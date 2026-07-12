from __future__ import annotations

from pathlib import Path

import pytest

from ai_council.models.config import (
    ModelConfig,
    ModelConfigError,
    ModelConfigRepository,
    ModelPricing,
)


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


def test_repository_loads_model_pricing_metadata(tmp_path: Path) -> None:
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        """
models:
  - id: priced-model
    adapter: mock
    pricing:
      currency: USD
      input_per_1m_tokens: 1.25
      output_per_1m_tokens: 10.0
""".strip(),
        encoding="utf-8",
    )

    model = ModelConfigRepository(config_path).list_models()[0]

    assert model.pricing is not None
    assert model.pricing.currency == "USD"
    assert model.pricing.input_per_1m_tokens == 1.25
    assert model.pricing.output_per_1m_tokens == 10.0


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


def test_repository_loads_subscription_cli_command_and_timeout(tmp_path: Path) -> None:
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        """
models:
  - id: claude-subscription
    adapter: subscription-cli
    command: [claude, -p, "{prompt}"]
    timeout_seconds: 300
""".strip(),
        encoding="utf-8",
    )

    model = ModelConfigRepository(config_path).list_models()[0]

    assert model.command == ["claude", "-p", "{prompt}"]
    assert model.timeout_seconds == 300


def test_repository_saves_new_model_to_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "models.yaml"
    config_path.write_text("models: []\n", encoding="utf-8")
    repository = ModelConfigRepository(config_path)

    repository.save_model(
        ModelConfig(
            id="qwen27",
            adapter="openai-compatible-http",
            base_url="http://192.168.50.80:8487/v1",
            model="bartowski/Qwen_Qwen3.6-27B-GGUF",
            supports_json_mode=True,
            extra_body={"chat_template_kwargs": {"enable_thinking": False}},
            pricing=ModelPricing(
                currency="USD",
                input_per_1m_tokens=1.25,
                output_per_1m_tokens=10.0,
            ),
        )
    )

    reloaded = ModelConfigRepository(config_path).list_models()
    assert [model.id for model in reloaded] == ["qwen27"]
    assert reloaded[0].base_url == "http://192.168.50.80:8487/v1"
    assert reloaded[0].extra_body == {"chat_template_kwargs": {"enable_thinking": False}}
    assert reloaded[0].pricing is not None
    assert reloaded[0].pricing.currency == "USD"
    assert reloaded[0].pricing.input_per_1m_tokens == 1.25
    assert reloaded[0].pricing.output_per_1m_tokens == 10.0


def test_repository_updates_existing_model_without_reordering(tmp_path: Path) -> None:
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        """
models:
  - id: mock-fast
    adapter: mock
  - id: qwen27
    adapter: openai-compatible-http
    base_url: http://old.example/v1
    model: old-model
""".strip(),
        encoding="utf-8",
    )
    repository = ModelConfigRepository(config_path)

    repository.save_model(
        ModelConfig(
            id="qwen27",
            adapter="openai-compatible-http",
            base_url="http://new.example/v1",
            model="new-model",
            supports_json_mode=True,
        )
    )

    models = repository.list_models()
    assert [model.id for model in models] == ["mock-fast", "qwen27"]
    assert models[1].base_url == "http://new.example/v1"
    assert models[1].model == "new-model"
    assert models[1].supports_json_mode is True


def test_repository_deletes_model_from_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        """
models:
  - id: mock-fast
    adapter: mock
  - id: qwen27
    adapter: openai-compatible-http
    base_url: http://example.test/v1
    model: qwen
""".strip(),
        encoding="utf-8",
    )
    repository = ModelConfigRepository(config_path)

    assert repository.delete_model("qwen27") is True
    assert repository.delete_model("missing") is False

    assert [model.id for model in repository.list_models()] == ["mock-fast"]


def test_repository_rejects_invalid_model_config(tmp_path: Path) -> None:
    repository = ModelConfigRepository(tmp_path / "models.yaml")

    with pytest.raises(ModelConfigError, match="base_url and model"):
        repository.save_model(ModelConfig(id="broken-http", adapter="openai-compatible-http"))

    with pytest.raises(ModelConfigError, match="command"):
        repository.save_model(ModelConfig(id="broken-cli", adapter="subscription-cli"))

    with pytest.raises(ModelConfigError, match="Unknown adapter"):
        repository.save_model(ModelConfig(id="broken-adapter", adapter="unknown"))


def test_repository_rejects_incomplete_pricing_metadata(tmp_path: Path) -> None:
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        """
models:
  - id: broken-pricing
    adapter: mock
    pricing:
      input_per_1m_tokens: 1.25
      output_per_1m_tokens: 10.0
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ModelConfigError, match="pricing.currency"):
        ModelConfigRepository(config_path).list_models()


def test_repository_reports_invalid_existing_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "models.yaml"
    config_path.write_text(
        """
models:
  - adapter: mock
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ModelConfigError, match="Model entry requires id and adapter"):
        ModelConfigRepository(config_path).list_models()
