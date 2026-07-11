from __future__ import annotations

import json
import subprocess
import threading
import time
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
