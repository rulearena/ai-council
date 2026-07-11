from __future__ import annotations

import json
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest

from ai_council.models.adapters import (
    AdapterError,
    ModelRequest,
    MockModelAdapter,
    OpenAICompatibleHTTPAdapter,
    SubscriptionCLIAdapter,
)
from ai_council.models.config import ModelConfig


def test_mock_adapter_returns_deterministic_valid_json() -> None:
    adapter = MockModelAdapter()

    response = adapter.complete(
        ModelRequest(
            prompt="請提出方案",
            model_config=ModelConfig(id="mock-fast", adapter="mock"),
        )
    )

    assert json.loads(response.raw_output) == {
        "summary": "Mock response",
        "arguments": [{"title": "Mock argument", "detail": "Deterministic detail"}],
        "risks": [],
        "recommendation": "Use this response for tests.",
    }


def test_mock_adapter_supports_configurable_delay(monkeypatch) -> None:
    delays: list[float] = []
    monkeypatch.setattr("ai_council.models.adapters.time.sleep", delays.append)

    MockModelAdapter().complete(
        ModelRequest(
            prompt="slow test",
            model_config=ModelConfig(
                id="mock-slow",
                adapter="mock",
                extra_body={"mock_delay_ms": 250},
            ),
        )
    )

    assert delays == [0.25]


def test_subscription_cli_adapter_passes_prompt_and_returns_stdout(tmp_path) -> None:
    fake_cli = tmp_path / "fake_cli.py"
    fake_cli.write_text(
        "import json, sys\n"
        "print(json.dumps({\"summary\": sys.argv[1], \"arguments\": [], "
        "\"risks\": [], \"recommendation\": \"OK\"}))\n",
        encoding="utf-8",
    )

    response = SubscriptionCLIAdapter().complete(
        ModelRequest(
            prompt="請用訂閱額度回答",
            model_config=ModelConfig(
                id="fake-subscription",
                adapter="subscription-cli",
                command=[sys.executable, str(fake_cli), "{prompt}"],
                timeout_seconds=5,
            ),
        )
    )

    assert json.loads(response.raw_output)["summary"] == "請用訂閱額度回答"


def test_subscription_cli_adapter_reports_nonzero_exit(tmp_path) -> None:
    fake_cli = tmp_path / "failing_cli.py"
    fake_cli.write_text(
        "import sys\nprint('login required', file=sys.stderr)\nraise SystemExit(7)\n",
        encoding="utf-8",
    )

    with pytest.raises(AdapterError, match="exited with code 7: login required"):
        SubscriptionCLIAdapter().complete(
            ModelRequest(
                prompt="test",
                model_config=ModelConfig(
                    id="failing",
                    adapter="subscription-cli",
                    command=[sys.executable, str(fake_cli), "{prompt}"],
                ),
            )
        )


def test_subscription_cli_adapter_reports_timeout(tmp_path) -> None:
    hanging_cli = tmp_path / "hanging_cli.py"
    hanging_cli.write_text("import time\ntime.sleep(5)\n", encoding="utf-8")

    with pytest.raises(AdapterError, match="timed out after 0.1 seconds"):
        SubscriptionCLIAdapter().complete(
            ModelRequest(
                prompt="test",
                model_config=ModelConfig(
                    id="slow",
                    adapter="subscription-cli",
                    command=[sys.executable, str(hanging_cli), "{prompt}"],
                    timeout_seconds=0.1,
                ),
            )
        )


def test_subscription_cli_adapter_cancel_kills_running_process(tmp_path) -> None:
    started_marker = tmp_path / "started"
    completed_marker = tmp_path / "completed"
    slow_cli = tmp_path / "slow_cli.py"
    slow_cli.write_text(
        "import pathlib, time\n"
        f"pathlib.Path({str(started_marker)!r}).write_text('started')\n"
        "time.sleep(10)\n"
        f"pathlib.Path({str(completed_marker)!r}).write_text('completed')\n",
        encoding="utf-8",
    )

    adapter = SubscriptionCLIAdapter()
    request = ModelRequest(
        prompt="test",
        model_config=ModelConfig(
            id="slow-subscription",
            adapter="subscription-cli",
            command=[sys.executable, str(slow_cli), "{prompt}"],
            timeout_seconds=30,
        ),
        meeting_id="meeting-1",
    )
    outcome: dict[str, object] = {}

    def run() -> None:
        try:
            outcome["response"] = adapter.complete(request)
        except AdapterError as error:
            outcome["error"] = error

    thread = Thread(target=run)
    thread.start()

    deadline = time.monotonic() + 2
    while not started_marker.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert started_marker.exists(), "subprocess never started"

    adapter.cancel("meeting-1")
    thread.join(timeout=3)

    assert not thread.is_alive(), "complete() did not return after cancel"
    assert "error" in outcome, "cancel should surface as an AdapterError"
    assert not completed_marker.exists(), "subprocess kept running after cancel"


def test_http_adapter_posts_chat_completion_request() -> None:
    server = RecordingServer(
        response={
            "choices": [
                {
                    "message": {
                        "content": '{"summary":"OK","arguments":[],"risks":[],"recommendation":"Go"}'
                    }
                }
            ]
        }
    )
    with server:
        adapter = OpenAICompatibleHTTPAdapter()
        response = adapter.complete(
            ModelRequest(
                prompt="Hello",
                model_config=ModelConfig(
                    id="local",
                    adapter="openai-compatible-http",
                    base_url=server.base_url,
                    model="test-model",
                    supports_json_mode=True,
                    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
                ),
            )
        )

    assert response.raw_output == '{"summary":"OK","arguments":[],"risks":[],"recommendation":"Go"}'
    assert server.request_path == "/v1/chat/completions"
    assert server.request_body["model"] == "test-model"
    assert server.request_body["messages"] == [{"role": "user", "content": "Hello"}]
    assert server.request_body["response_format"] == {"type": "json_object"}
    assert server.request_body["chat_template_kwargs"] == {"enable_thinking": False}


def test_http_adapter_adds_authorization_header_from_api_key_env(monkeypatch) -> None:
    monkeypatch.setenv("TEST_API_KEY", "secret-key-123")
    server = RecordingServer(
        response={
            "choices": [
                {
                    "message": {
                        "content": '{"summary":"OK","arguments":[],"risks":[],"recommendation":"Go"}'
                    }
                }
            ]
        }
    )
    with server:
        adapter = OpenAICompatibleHTTPAdapter()
        adapter.complete(
            ModelRequest(
                prompt="Hello",
                model_config=ModelConfig(
                    id="cloud",
                    adapter="openai-compatible-http",
                    base_url=server.base_url,
                    model="test-model",
                    api_key_env="TEST_API_KEY",
                ),
            )
        )

    assert server.request_headers["Authorization"] == "Bearer secret-key-123"


def test_http_adapter_omits_authorization_header_when_api_key_env_not_configured() -> None:
    server = RecordingServer(
        response={
            "choices": [
                {
                    "message": {
                        "content": '{"summary":"OK","arguments":[],"risks":[],"recommendation":"Go"}'
                    }
                }
            ]
        }
    )
    with server:
        adapter = OpenAICompatibleHTTPAdapter()
        adapter.complete(
            ModelRequest(
                prompt="Hello",
                model_config=ModelConfig(
                    id="local",
                    adapter="openai-compatible-http",
                    base_url=server.base_url,
                    model="test-model",
                ),
            )
        )

    assert "Authorization" not in server.request_headers


def test_http_adapter_raises_when_api_key_env_variable_is_unset(monkeypatch) -> None:
    monkeypatch.delenv("MISSING_API_KEY", raising=False)

    with pytest.raises(AdapterError, match="MISSING_API_KEY"):
        OpenAICompatibleHTTPAdapter().complete(
            ModelRequest(
                prompt="Hello",
                model_config=ModelConfig(
                    id="cloud",
                    adapter="openai-compatible-http",
                    base_url="http://127.0.0.1:1/v1",
                    model="test-model",
                    api_key_env="MISSING_API_KEY",
                ),
            )
        )


def test_http_adapter_surfaces_http_errors_as_adapter_error() -> None:
    server = RecordingServer(status=500, response={"error": "boom"})
    with server:
        adapter = OpenAICompatibleHTTPAdapter()
        with pytest.raises(AdapterError):
            adapter.complete(
                ModelRequest(
                    prompt="Hello",
                    model_config=ModelConfig(
                        id="bad",
                        adapter="openai-compatible-http",
                        base_url=server.base_url,
                        model="test-model",
                    ),
                )
            )


class RecordingHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.server.request_path = self.path  # type: ignore[attr-defined]
        self.server.request_body = json.loads(body.decode("utf-8"))  # type: ignore[attr-defined]
        self.server.request_headers = dict(self.headers)  # type: ignore[attr-defined]
        self.send_response(self.server.status)  # type: ignore[attr-defined]
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(self.server.response).encode("utf-8"))  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: object) -> None:
        return


class RecordingServer:
    def __init__(self, *, response: dict[str, object], status: int = 200) -> None:
        self._server = HTTPServer(("127.0.0.1", 0), RecordingHandler)
        self._server.response = response  # type: ignore[attr-defined]
        self._server.status = status  # type: ignore[attr-defined]
        self._thread = Thread(target=self._server.serve_forever)
        self._thread.daemon = True

    @property
    def base_url(self) -> str:
        host, port = self._server.server_address
        return f"http://{host}:{port}/v1"

    @property
    def request_path(self) -> str:
        return self._server.request_path  # type: ignore[attr-defined]

    @property
    def request_body(self) -> dict[str, object]:
        return self._server.request_body  # type: ignore[attr-defined]

    @property
    def request_headers(self) -> dict[str, str]:
        return self._server.request_headers  # type: ignore[attr-defined]

    def __enter__(self) -> RecordingServer:
        self._thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)
