from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable, TypedDict

from ai_council.models.config import ModelConfig

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class AdapterError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelRequest:
    prompt: str
    model_config: ModelConfig
    meeting_id: str | None = None
    on_token_delta: Callable[[str], None] | None = None


class TokenUsage(TypedDict):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class ModelResponse:
    raw_output: str
    token_usage: TokenUsage | None = None


class MockModelAdapter:
    def complete(self, request: ModelRequest) -> ModelResponse:
        chunks = request.model_config.extra_body.get("mock_stream_chunks", [])
        if request.on_token_delta is not None and isinstance(chunks, list):
            for chunk in chunks:
                if isinstance(chunk, str):
                    request.on_token_delta(chunk)
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
        normalized_stdout = normalize_cli_output(stdout, config)
        if not normalized_stdout:
            raise AdapterError("Subscription CLI returned empty output")
        return ModelResponse(raw_output=normalized_stdout)

    def cancel(self, meeting_id: str) -> None:
        with self._lock:
            process = self._active_processes.get(meeting_id)
        if process is not None:
            process.kill()


def normalize_cli_output(stdout: str, config: ModelConfig | None = None) -> str:
    output = ANSI_ESCAPE_RE.sub("", stdout).strip()
    provider = _cli_provider(config)
    if provider == "codex":
        return _normalize_codex_cli_output(output)
    return output


def _cli_provider(config: ModelConfig | None) -> str:
    if config is None:
        return ""
    provider = config.extra_body.get("cli_provider")
    if isinstance(provider, str):
        return provider.strip().lower()
    return ""


def _normalize_codex_cli_output(stdout: str) -> str:
    start_marker = "<codex-output>"
    end_marker = "</codex-output>"
    if start_marker not in stdout or end_marker not in stdout:
        return stdout
    return stdout.split(start_marker, 1)[1].split(end_marker, 1)[0].strip()


def _resolve_api_key(api_key_env: str | None) -> str | None:
    if not api_key_env:
        return None
    api_key = os.environ.get(api_key_env)
    if not api_key:
        raise AdapterError(f"Environment variable {api_key_env} is not set for API key")
    return api_key


def _request_json(
    url: str,
    *,
    method: str,
    headers: dict[str, str],
    payload: dict[str, object] | None = None,
) -> dict[str, object]:
    http_request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(http_request, timeout=120) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise AdapterError(str(error)) from error


def _post_json(url: str, payload: dict[str, object], headers: dict[str, str]) -> dict[str, object]:
    return _request_json(url, method="POST", payload=payload, headers=headers)


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
            return ModelResponse(
                raw_output=body["choices"][0]["message"]["content"],
                token_usage=_openai_token_usage(body),
            )
        except (KeyError, IndexError, TypeError) as error:
            raise AdapterError("Malformed chat completion response") from error

    def discover_models(self, config: ModelConfig) -> list[str]:
        if not config.base_url:
            raise AdapterError("HTTP model config requires base_url")
        headers = {"Content-Type": "application/json"}
        api_key = _resolve_api_key(config.api_key_env)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        body = _request_json(
            f"{config.base_url.rstrip('/')}/models",
            method="GET",
            headers=headers,
        )
        try:
            return [str(model["id"]) for model in body["data"]]
        except (KeyError, TypeError) as error:
            raise AdapterError("Malformed models response") from error


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
            return ModelResponse(
                raw_output=body["content"][0]["text"],
                token_usage=_anthropic_token_usage(body),
            )
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
            return ModelResponse(
                raw_output=body["candidates"][0]["content"]["parts"][0]["text"],
                token_usage=_gemini_token_usage(body),
            )
        except (KeyError, IndexError, TypeError) as error:
            raise AdapterError("Malformed Gemini response") from error


def _openai_token_usage(body: dict[str, object]) -> TokenUsage | None:
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return None
    return _token_usage(
        prompt_tokens=usage.get("prompt_tokens"),
        completion_tokens=usage.get("completion_tokens"),
        total_tokens=usage.get("total_tokens"),
    )


def _anthropic_token_usage(body: dict[str, object]) -> TokenUsage | None:
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return None
    prompt_tokens = usage.get("input_tokens")
    completion_tokens = usage.get("output_tokens")
    return _token_usage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=_sum_tokens(prompt_tokens, completion_tokens),
    )


def _gemini_token_usage(body: dict[str, object]) -> TokenUsage | None:
    usage = body.get("usageMetadata")
    if not isinstance(usage, dict):
        return None
    return _token_usage(
        prompt_tokens=usage.get("promptTokenCount"),
        completion_tokens=usage.get("candidatesTokenCount"),
        total_tokens=usage.get("totalTokenCount"),
    )


def _token_usage(
    *,
    prompt_tokens: object,
    completion_tokens: object,
    total_tokens: object,
) -> TokenUsage | None:
    if not all(isinstance(value, int) for value in [prompt_tokens, completion_tokens, total_tokens]):
        return None
    return {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
    }


def _sum_tokens(left: object, right: object) -> int | None:
    if isinstance(left, int) and isinstance(right, int):
        return left + right
    return None
