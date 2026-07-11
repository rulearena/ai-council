from __future__ import annotations

import json
import os
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from ai_council.models.config import ModelConfig


class AdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelRequest:
    prompt: str
    model_config: ModelConfig
    meeting_id: str | None = None


@dataclass(frozen=True)
class ModelResponse:
    raw_output: str


class MockModelAdapter:
    def complete(self, request: ModelRequest) -> ModelResponse:
        delay_ms = request.model_config.extra_body.get("mock_delay_ms", 0)
        if isinstance(delay_ms, (int, float)) and delay_ms > 0:
            time.sleep(delay_ms / 1000)
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


class SubscriptionCLIAdapter:
    def __init__(self) -> None:
        self._active_processes: dict[str, subprocess.Popen[str]] = {}
        self._lock = threading.Lock()

    def complete(self, request: ModelRequest) -> ModelResponse:
        config = request.model_config
        if not config.command:
            raise AdapterError("Subscription CLI config requires command")
        if not any("{prompt}" in argument for argument in config.command):
            raise AdapterError("Subscription CLI command requires a {prompt} placeholder")

        command = [argument.replace("{prompt}", request.prompt) for argument in config.command]
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
        except OSError as error:
            raise AdapterError(f"Subscription CLI could not start: {error}") from error

        if request.meeting_id is not None:
            with self._lock:
                self._active_processes[request.meeting_id] = process
        try:
            try:
                stdout, stderr = process.communicate(timeout=config.timeout_seconds)
            except subprocess.TimeoutExpired as error:
                process.kill()
                process.communicate()
                raise AdapterError(
                    f"Subscription CLI timed out after {config.timeout_seconds:g} seconds"
                ) from error
        finally:
            if request.meeting_id is not None:
                with self._lock:
                    if self._active_processes.get(request.meeting_id) is process:
                        del self._active_processes[request.meeting_id]

        if process.returncode is not None and process.returncode < 0:
            raise AdapterError("Subscription CLI was cancelled")
        if process.returncode != 0:
            detail = stderr.strip() or stdout.strip() or "no output"
            raise AdapterError(
                f"Subscription CLI exited with code {process.returncode}: {detail}"
            )
        if not stdout.strip():
            raise AdapterError("Subscription CLI returned empty output")
        return ModelResponse(raw_output=stdout.strip())

    def cancel(self, meeting_id: str) -> None:
        with self._lock:
            process = self._active_processes.get(meeting_id)
        if process is not None:
            process.kill()


def _resolve_api_key(api_key_env: str | None) -> str | None:
    if not api_key_env:
        return None
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise AdapterError(f"Environment variable {api_key_env} is not set for API key")
    return api_key


def _post_json(url: str, payload: dict[str, object], headers: dict[str, str]) -> dict[str, object]:
    http_request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(http_request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise AdapterError(str(error)) from error


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

        headers = {"Content-Type": "application/json"}
        api_key = _resolve_api_key(config.api_key_env)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        body = _post_json(f"{config.base_url.rstrip('/')}/chat/completions", payload, headers)

        try:
            return ModelResponse(raw_output=body["choices"][0]["message"]["content"])
        except (KeyError, IndexError, TypeError) as error:
            raise AdapterError("Malformed chat completion response") from error


class AnthropicHTTPAdapter:
    def complete(self, request: ModelRequest) -> ModelResponse:
        config = request.model_config
        if not config.base_url or not config.model:
            raise AdapterError("HTTP model config requires base_url and model")

        payload: dict[str, object] = {
            "model": config.model,
            "max_tokens": 4096,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        payload.update(config.extra_body)

        headers = {"Content-Type": "application/json", "anthropic-version": "2023-06-01"}
        api_key = _resolve_api_key(config.api_key_env)
        if api_key:
            headers["x-api-key"] = api_key

        body = _post_json(f"{config.base_url.rstrip('/')}/messages", payload, headers)

        try:
            return ModelResponse(raw_output=body["content"][0]["text"])
        except (KeyError, IndexError, TypeError) as error:
            raise AdapterError("Malformed Anthropic response") from error


class GeminiHTTPAdapter:
    def complete(self, request: ModelRequest) -> ModelResponse:
        config = request.model_config
        if not config.base_url or not config.model:
            raise AdapterError("HTTP model config requires base_url and model")

        payload: dict[str, object] = {
            "contents": [{"parts": [{"text": request.prompt}]}],
        }
        payload.update(config.extra_body)

        url = f"{config.base_url.rstrip('/')}/models/{config.model}:generateContent"
        api_key = _resolve_api_key(config.api_key_env)
        if api_key:
            url = f"{url}?key={urllib.parse.quote(api_key, safe='')}"

        body = _post_json(url, payload, {"Content-Type": "application/json"})

        try:
            return ModelResponse(raw_output=body["candidates"][0]["content"]["parts"][0]["text"])
        except (KeyError, IndexError, TypeError) as error:
            raise AdapterError("Malformed Gemini response") from error
