from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from ai_council.models.config import ModelConfig


class AdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelRequest:
    prompt: str
    model_config: ModelConfig


@dataclass(frozen=True)
class ModelResponse:
    raw_output: str


class MockModelAdapter:
    def complete(self, request: ModelRequest) -> ModelResponse:
        return ModelResponse(
            raw_output=json.dumps(
                {
                    "summary": "Mock response",
                    "arguments": [
                        {
                            "title": "Mock argument",
                            "detail": "Deterministic detail",
                        }
                    ],
                    "risks": [],
                    "recommendation": "Use this response for tests.",
                },
                ensure_ascii=False,
            )
        )


class OpenAICompatibleHTTPAdapter:
    def complete(self, request: ModelRequest) -> ModelResponse:
        config = request.model_config
        if not config.base_url or not config.model:
            raise AdapterError("HTTP model config requires base_url and model")

        payload: dict[str, object] = {
            "model": config.model,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if config.supports_json_mode:
            payload["response_format"] = {"type": "json_object"}
        payload.update(config.extra_body)

        http_request = urllib.request.Request(
            f"{config.base_url.rstrip('/')}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(http_request, timeout=120) as response:
                body = json.loads(response.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
            raise AdapterError(str(error)) from error

        try:
            return ModelResponse(raw_output=body["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as error:
            raise AdapterError("Malformed chat completion response") from error
