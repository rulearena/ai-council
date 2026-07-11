from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest

from ai_council.models.adapters import (
    AdapterError,
    ModelRequest,
    MockModelAdapter,
    OpenAICompatibleHTTPAdapter,
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

    def __enter__(self) -> RecordingServer:
        self._thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)
