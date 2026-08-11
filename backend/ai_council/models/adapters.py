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
from ai_council.prompting.schemas import (
    CHAT_MESSAGE_V1_ID,
    COURTROOM_ISSUE_DRAFT_V1_ID,
    COURTROOM_CIVIL_FINAL_V1_ID,
    COURTROOM_CRIMINAL_FINAL_V1_ID,
    COURTROOM_RULING_V1_ID,
    DEFAULT_OUTPUT_SCHEMA_ID,
    STRUCTURED_VERDICT_V1_ID,
)

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
BEARER_TOKEN_RE = re.compile(r"(?i)\bBearer\s+\S+")
DIAGNOSTIC_EXCERPT_LIMIT = 8192


class AdapterError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        failure_kind: str = "adapter_error",
        stdout_excerpt: str | None = None,
        stderr_excerpt: str | None = None,
    ) -> None:
        super().__init__(message)
        self.failure_kind = failure_kind
        self.stdout_excerpt = stdout_excerpt
        self.stderr_excerpt = stderr_excerpt


@dataclass(frozen=True)
class ModelRequest:
    prompt: str
    model_config: ModelConfig
    meeting_id: str | None = None
    on_token_delta: Callable[[str], None] | None = None
    output_schema_id: str = DEFAULT_OUTPUT_SCHEMA_ID
    # Canonical chatroom layers.  None is the compatibility signal for all
    # formal-mode callers and preserves their legacy single prompt payload.
    messages: list[dict[str, str]] | None = None


class TokenUsage(TypedDict):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


@dataclass(frozen=True)
class ModelResponse:
    raw_output: str
    token_usage: TokenUsage | None = None


class MockModelAdapter:
    last_request: ModelRequest | None = None

    def __init__(self) -> None:
        self.last_request = None
        self._chat_response_offsets: dict[tuple[str | None, str], int] = {}
        self._chat_response_lock = threading.Lock()

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.last_request = request
        chunks = request.model_config.extra_body.get("mock_stream_chunks", [])
        if request.on_token_delta is not None and isinstance(chunks, list):
            for chunk in chunks:
                if isinstance(chunk, str):
                    request.on_token_delta(chunk)
        delay_ms = request.model_config.extra_body.get("mock_delay_ms", 0)
        if isinstance(delay_ms, (int, float)) and delay_ms > 0:
            time.sleep(delay_ms / 1000)
        mock_error = request.model_config.extra_body.get("mock_error")
        if isinstance(mock_error, str) and mock_error:
            raise AdapterError(mock_error)
        if request.output_schema_id == CHAT_MESSAGE_V1_ID:
            sequence = request.model_config.extra_body.get(
                "mock_chat_response_sequence"
            )
            payload: dict[str, object] | None = None
            if isinstance(sequence, list) and sequence:
                key = (request.meeting_id, request.model_config.id)
                with self._chat_response_lock:
                    offset = self._chat_response_offsets.get(key, 0)
                    self._chat_response_offsets[key] = offset + 1
                candidate = sequence[min(offset, len(sequence) - 1)]
                if isinstance(candidate, dict):
                    payload = candidate
            if payload is None:
                payload = {
                    "message": "Mock chat response.",
                }
        elif request.output_schema_id == COURTROOM_ISSUE_DRAFT_V1_ID:
            payload = {"issues": [{"title": "Mock generated issue"}]}
        elif request.output_schema_id == COURTROOM_RULING_V1_ID:
            payload = {
                "outcome": "partially-upheld",
                "reasoning": "Mock issue ruling",
                "evidence_refs": _visible_case_file_anchors(request.prompt)[:1],
                "unresolved_questions": [],
            }
        elif request.output_schema_id == COURTROOM_CIVIL_FINAL_V1_ID:
            payload = {
                "summary": "Mock verdict",
                "claims": [{
                    "claim": "Mock claim",
                    "outcome": "upheld",
                    "reasoning": "Mock civil reasoning",
                    "evidence_refs": _visible_case_file_anchors(request.prompt)[:1],
                    "relief": {
                        "obligation": "Mock obligation",
                        "monetary_amount": None,
                        "calculation_basis": None,
                    },
                }],
                "unresolved_questions": [],
            }
        elif request.output_schema_id == COURTROOM_CRIMINAL_FINAL_V1_ID:
            payload = {
                "summary": "Mock verdict",
                "charges": [{
                    "charge": "Mock charge",
                    "decision": "guilty",
                    "reasoning": "Mock criminal reasoning",
                    "evidence_refs": _visible_case_file_anchors(request.prompt)[:1],
                }],
                "sentencing_factors": ["Mock factor"],
                "unresolved_questions": [],
            }
        else:
            payload = (
            {
                "summary": "Mock verdict",
                "decision": "approve-with-conditions",
                "findings": [
                    {
                        "title": "Mock finding",
                        "detail": "Deterministic finding",
                        "evidence_refs": _visible_case_file_anchors(request.prompt)[:1],
                    }
                ],
                "risks": [],
                "recommendation": "Use this verdict for tests.",
                "conditions": ["Verify the result."],
                "unresolved_questions": ["Is more evidence available?"],
            }
            if request.output_schema_id == STRUCTURED_VERDICT_V1_ID
            else {
                "summary": "Mock response",
                "arguments": [
                    {
                        "title": "Mock argument",
                        "detail": "Deterministic detail",
                    }
                ],
                "risks": [],
                "recommendation": "Use this response for tests.",
            }
            )
        return ModelResponse(raw_output=json.dumps(payload, ensure_ascii=False))


def _visible_case_file_anchors(prompt: str) -> list[str]:
    heading = "Case files visible to you:"
    start = prompt.find(heading)
    if start == -1:
        return []
    start += len(heading)
    end = prompt.find("\n\nPrior transcript:", start)
    case_files_block = prompt[start:] if end == -1 else prompt[start:end]
    anchors = re.findall(r"^### (\[(?:證物|附件)[^\[\]\n]+\])", case_files_block, re.MULTILINE)
    return list(dict.fromkeys(anchors))


class SubscriptionCLIAdapter:
    def __init__(self) -> None:
        self._active_processes: dict[str, subprocess.Popen[str]] = {}
        self._lock = threading.Lock()

    def complete(self, request: ModelRequest) -> ModelResponse:
        config = request.model_config
        if not config.command:
            raise AdapterError(
                "Subscription CLI config requires command", failure_kind="configuration_error"
            )
        if not any("{prompt}" in argument for argument in config.command):
            raise AdapterError(
                "Subscription CLI command requires a {prompt} placeholder",
                failure_kind="configuration_error",
            )

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
                stdout, stderr = process.communicate()
                stdout_excerpt, stderr_excerpt = _safe_cli_excerpts(stdout, stderr, config)
                raise AdapterError(
                    f"Subscription CLI timed out after {config.timeout_seconds:g} seconds",
                    failure_kind="timeout",
                    stdout_excerpt=stdout_excerpt,
                    stderr_excerpt=stderr_excerpt,
                ) from error
        finally:
            if request.meeting_id is not None:
                with self._lock:
                    if self._active_processes.get(request.meeting_id) is process:
                        del self._active_processes[request.meeting_id]

        if process.returncode is not None and process.returncode < 0:
            stdout_excerpt, stderr_excerpt = _safe_cli_excerpts(stdout, stderr, config)
            raise AdapterError(
                "Subscription CLI was cancelled",
                failure_kind="interrupted",
                stdout_excerpt=stdout_excerpt,
                stderr_excerpt=stderr_excerpt,
            )
        if process.returncode != 0:
            stdout_excerpt, stderr_excerpt = _safe_cli_excerpts(stdout, stderr, config)
            detail = stderr_excerpt or stdout_excerpt or "no output"
            raise AdapterError(
                f"Subscription CLI exited with code {process.returncode}: {detail}",
                stdout_excerpt=stdout_excerpt,
                stderr_excerpt=stderr_excerpt,
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


def _safe_cli_excerpts(
    stdout: str | None,
    stderr: str | None,
    config: ModelConfig,
) -> tuple[str | None, str | None]:
    return (
        _safe_cli_excerpt(stdout, config),
        _safe_cli_excerpt(stderr, config),
    )


def _safe_cli_excerpt(output: str | None, config: ModelConfig) -> str | None:
    if not output:
        return None
    redacted = output
    if config.api_key_env:
        api_key = os.environ.get(config.api_key_env)
        if api_key:
            redacted = redacted.replace(api_key, "[REDACTED]")
    redacted = BEARER_TOKEN_RE.sub("Bearer [REDACTED]", redacted)
    return redacted[-DIAGNOSTIC_EXCERPT_LIMIT:].strip()


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
        raise AdapterError(
            f"Environment variable {api_key_env} is not set for API key",
            failure_kind="configuration_error",
        )
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
        is_timeout = isinstance(error, TimeoutError) or (
            isinstance(error, urllib.error.URLError)
            and isinstance(error.reason, TimeoutError)
        )
        raise AdapterError(
            _safe_http_error_detail(error, url),
            failure_kind="timeout" if is_timeout else "adapter_error",
        ) from error


def _safe_http_error_detail(error: BaseException, request_url: str) -> str:
    detail = str(error)
    parsed_url = urllib.parse.urlsplit(request_url)
    if parsed_url.query:
        queryless_url = urllib.parse.urlunsplit(parsed_url._replace(query=""))
        detail = detail.replace(request_url, f"{queryless_url}?[REDACTED]")
    return detail


def _post_json(url: str, payload: dict[str, object], headers: dict[str, str]) -> dict[str, object]:
    return _request_json(url, method="POST", payload=payload, headers=headers)


def _messages_by_role(request: ModelRequest) -> dict[str, str]:
    return {
        str(message["role"]): str(message["content"])
        for message in (request.messages or [])
        if isinstance(message, dict) and "role" in message and "content" in message
    }


def _merged_system_developer(messages: list[dict[str, str]]) -> str:
    by_role = _messages_by_role(ModelRequest(prompt="", model_config=ModelConfig(id="_", adapter="mock"), messages=messages))
    return "\n\n".join(
        value for value in (by_role.get("system", ""), by_role.get("developer", "")) if value
    )


def _user_message(messages: list[dict[str, str]]) -> str:
    by_role = _messages_by_role(ModelRequest(prompt="", model_config=ModelConfig(id="_", adapter="mock"), messages=messages))
    return by_role.get("user", "")


def _openai_messages(request: ModelRequest, supports_developer_role: bool) -> list[dict[str, str]]:
    if request.messages is None:
        return [{"role": "user", "content": request.prompt}]
    if supports_developer_role:
        return [dict(message) for message in request.messages]
    return [
        {"role": "system", "content": _merged_system_developer(request.messages)},
        {"role": "user", "content": _user_message(request.messages)},
    ]


def _anthropic_messages(request: ModelRequest) -> list[dict[str, str]]:
    if request.messages is None:
        return [{"role": "user", "content": request.prompt}]
    return [{"role": "user", "content": _user_message(request.messages)}]


class OpenAICompatibleHTTPAdapter:
    def __init__(self, *, supports_developer_role: bool = False) -> None:
        self.supports_developer_role = supports_developer_role

    def complete(self, request: ModelRequest) -> ModelResponse:
        config = request.model_config
        if not config.base_url or not config.model:
            raise AdapterError(
                "HTTP model config requires base_url and model",
                failure_kind="configuration_error",
            )

        payload: dict[str, object] = {"model": config.model, "messages": _openai_messages(request, self.supports_developer_role)}
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
            raise AdapterError(
                "HTTP model config requires base_url", failure_kind="configuration_error"
            )
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
            raise AdapterError(
                "HTTP model config requires base_url and model",
                failure_kind="configuration_error",
            )

        payload: dict[str, object] = {
            "model": config.model,
            "max_tokens": 4096,
            "messages": _anthropic_messages(request),
        }
        if request.messages is not None:
            payload["system"] = _merged_system_developer(request.messages)
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

    def discover_models(self, config: ModelConfig) -> list[str]:
        if not config.base_url:
            raise AdapterError(
                "HTTP model config requires base_url", failure_kind="configuration_error"
            )
        headers = {"anthropic-version": "2023-06-01"}
        api_key = _resolve_api_key(config.api_key_env)
        if api_key:
            headers["x-api-key"] = api_key
        url = f"{config.base_url.rstrip('/')}/models"
        model_ids: set[str] = set()
        seen_cursors: set[str] = set()
        while True:
            body = _request_json(url, method="GET", headers=headers)
            try:
                model_ids.update(str(model["id"]) for model in body["data"])
                has_more = body.get("has_more", False)
                if not has_more:
                    return sorted(model_ids)
                cursor = str(body["last_id"])
            except (KeyError, TypeError) as error:
                raise AdapterError("Malformed Anthropic models response") from error
            if not cursor or cursor in seen_cursors:
                raise AdapterError("Malformed Anthropic models pagination")
            seen_cursors.add(cursor)
            url = (
                f"{config.base_url.rstrip('/')}/models?"
                f"{urllib.parse.urlencode({'after_id': cursor})}"
            )


class GeminiHTTPAdapter:
    def __init__(self, *, supports_system_instruction: bool = True) -> None:
        self.supports_system_instruction = supports_system_instruction

    def complete(self, request: ModelRequest) -> ModelResponse:
        config = request.model_config
        if not config.base_url or not config.model:
            raise AdapterError(
                "HTTP model config requires base_url and model",
                failure_kind="configuration_error",
            )

        if request.messages is not None and self.supports_system_instruction:
            payload: dict[str, object] = {
                "systemInstruction": {"parts": [{"text": _merged_system_developer(request.messages)}]},
                "contents": [{"role": "user", "parts": [{"text": _user_message(request.messages)}]}],
            }
        else:
            payload = {
                "contents": [
                    {
                        **({"role": "user"} if request.messages is not None else {}),
                        "parts": [{"text": request.prompt}],
                    }
                ]
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

    def discover_models(self, config: ModelConfig) -> list[str]:
        if not config.base_url:
            raise AdapterError(
                "HTTP model config requires base_url", failure_kind="configuration_error"
            )
        api_key = _resolve_api_key(config.api_key_env)
        model_ids: set[str] = set()
        page_token: str | None = None
        seen_page_tokens: set[str] = set()
        while True:
            query: dict[str, str] = {}
            if api_key:
                query["key"] = api_key
            if page_token:
                query["pageToken"] = page_token
            url = f"{config.base_url.rstrip('/')}/models"
            if query:
                url = f"{url}?{urllib.parse.urlencode(query)}"
            body = _request_json(url, method="GET", headers={})
            try:
                for model in body["models"]:
                    name = str(model["name"])
                    if not name.startswith("models/") or name == "models/":
                        raise KeyError("name")
                    supported_methods = model.get("supportedGenerationMethods")
                    if supported_methods is not None:
                        if not isinstance(supported_methods, list):
                            raise TypeError("supportedGenerationMethods")
                        if "generateContent" not in supported_methods:
                            continue
                    model_ids.add(name.removeprefix("models/"))
            except (KeyError, TypeError) as error:
                raise AdapterError("Malformed Gemini models response") from error
            next_page_token = body.get("nextPageToken")
            if not next_page_token:
                return sorted(model_ids)
            page_token = str(next_page_token)
            if page_token in seen_page_tokens:
                raise AdapterError("Malformed Gemini models pagination")
            seen_page_tokens.add(page_token)


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
