from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel

from ai_council.meetings.repository import MeetingRepository
from ai_council.meetings.runner import MeetingRunner, RunnerAdapters
from ai_council.meetings.transcript import TranscriptProjector
from ai_council.models.adapters import (
    AdapterError,
    MockModelAdapter,
    ModelRequest,
    OpenAICompatibleHTTPAdapter,
)
from ai_council.models.config import ModelConfig, ModelConfigRepository
from ai_council.prompting.renderer import PromptRenderer


class CreateMeetingRequest(BaseModel):
    topic: str


class StartMeetingRequest(BaseModel):
    models: dict[str, str]


class RunRoleSequenceRequest(BaseModel):
    roles: list[str]
    models: dict[str, str]


class AddMeetingMessageRequest(BaseModel):
    content: str


def create_app(
    *,
    data_dir: Path | str,
    model_config_path: Path | str,
    prompt_dir: Path | str,
) -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_origin_regex=r"^http://(localhost|127\.0\.0\.1):\d+$",
        allow_methods=["*"],
        allow_headers=["*"],
    )
    data_path = Path(data_dir)
    metadata_store = MeetingMetadataStore(data_path)
    repository = MeetingRepository(data_path)
    model_repository = ModelConfigRepository(model_config_path)
    model_adapters = {
        "mock": MockModelAdapter(),
        "openai-compatible-http": OpenAICompatibleHTTPAdapter(),
    }
    runner = MeetingRunner(
        repository=repository,
        prompt_renderer=PromptRenderer(prompt_dir),
        adapters=RunnerAdapters(
            by_name=model_adapters,
        ),
    )
    projector = TranscriptProjector()

    @app.get("/models")
    def list_models() -> list[dict[str, Any]]:
        return [model.__dict__ for model in model_repository.list_models()]

    @app.post("/models/{model_config_id}/test")
    def test_model(model_config_id: str) -> dict[str, str]:
        model = get_model(model_repository, model_config_id)
        adapter = model_adapters.get(model.adapter)
        if adapter is None:
            return {"status": "unavailable", "error": f"Unknown adapter: {model.adapter}"}
        try:
            adapter.complete(
                ModelRequest(
                    prompt='Return {"summary":"OK","arguments":[],"risks":[],"recommendation":"OK"}',
                    model_config=model,
                )
            )
        except AdapterError as error:
            return {"status": "unavailable", "error": str(error)}
        return {"status": "available"}

    @app.post("/meetings")
    def create_meeting(request: CreateMeetingRequest) -> dict[str, str]:
        meeting_id = f"meeting-{uuid.uuid4().hex}"
        metadata = {"meeting_id": meeting_id, "topic": request.topic}
        metadata_store.save(metadata)
        return {**metadata, "status": "open"}

    @app.get("/meetings")
    def list_meetings() -> list[dict[str, str]]:
        return [
            {
                **metadata,
                "status": project_meeting_status(repository.read_events(metadata["meeting_id"])),
            }
            for metadata in metadata_store.list()
        ]

    @app.get("/meetings/{meeting_id}")
    def get_meeting(meeting_id: str) -> dict[str, Any]:
        metadata = metadata_store.get(meeting_id)
        events = repository.read_events(meeting_id)
        return {
            **metadata,
            "status": project_meeting_status(events),
            "events": events,
        }

    @app.post("/meetings/{meeting_id}/start")
    def start_meeting(meeting_id: str, request: StartMeetingRequest) -> dict[str, str]:
        metadata = metadata_store.get(meeting_id)
        reject_terminal_meeting(repository, meeting_id)
        runner.start(
            meeting_id=meeting_id,
            topic=metadata["topic"],
            model_assignments={
                role: get_model(model_repository, model_id)
                for role, model_id in request.models.items()
            },
        )
        return {"status": "completed"}

    @app.post("/meetings/{meeting_id}/cancel")
    def cancel_meeting(meeting_id: str) -> dict[str, str]:
        metadata_store.get(meeting_id)
        runner.cancel(meeting_id)
        return {"status": "cancelled"}

    @app.post("/meetings/{meeting_id}/close")
    def close_meeting(meeting_id: str) -> dict[str, str]:
        metadata_store.get(meeting_id)
        runner.close(meeting_id)
        return {"status": "closed"}

    @app.post("/meetings/{meeting_id}/messages")
    def add_meeting_message(
        meeting_id: str,
        request: AddMeetingMessageRequest,
    ) -> dict[str, Any]:
        metadata_store.get(meeting_id)
        reject_terminal_meeting(repository, meeting_id)
        event = {
            "event_id": f"{meeting_id}:human-message:{uuid.uuid4().hex}",
            "meeting_id": meeting_id,
            "step_id": "human-message",
            "role": "Human",
            "attempt": 1,
            "status": "completed",
            "content": request.content,
        }
        repository.append_event(meeting_id, event)
        return event

    @app.post("/meetings/{meeting_id}/roles/{role}/respond")
    def respond_as_role(
        meeting_id: str,
        role: str,
        request: StartMeetingRequest,
    ) -> dict[str, str]:
        metadata = metadata_store.get(meeting_id)
        reject_terminal_meeting(repository, meeting_id)
        try:
            runner.respond_as_role(
                meeting_id=meeting_id,
                topic=metadata["topic"],
                role=role,
                model_assignments={
                    role_name: get_model(model_repository, model_id)
                    for role_name, model_id in request.models.items()
                },
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"status": "completed"}

    @app.post("/meetings/{meeting_id}/sequences")
    def respond_as_sequence(
        meeting_id: str,
        request: RunRoleSequenceRequest,
    ) -> dict[str, str]:
        metadata = metadata_store.get(meeting_id)
        reject_terminal_meeting(repository, meeting_id)
        try:
            runner.respond_as_sequence(
                meeting_id=meeting_id,
                topic=metadata["topic"],
                roles=request.roles,
                model_assignments={
                    role_name: get_model(model_repository, model_id)
                    for role_name, model_id in request.models.items()
                },
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"status": "completed"}

    @app.post("/meetings/{meeting_id}/steps/{step_id}/retry")
    def retry_step(
        meeting_id: str,
        step_id: str,
        request: StartMeetingRequest,
    ) -> dict[str, str]:
        metadata = metadata_store.get(meeting_id)
        reject_terminal_meeting(repository, meeting_id)
        runner.retry_failed_step(
            meeting_id=meeting_id,
            step_id=step_id,
            topic=metadata["topic"],
            model_assignments={
                role: get_model(model_repository, model_id)
                for role, model_id in request.models.items()
            },
        )
        return {"status": "completed"}

    @app.get("/meetings/{meeting_id}/transcript.md")
    def get_transcript(meeting_id: str) -> PlainTextResponse:
        metadata = metadata_store.get(meeting_id)
        transcript = projector.project(
            repository.read_events(meeting_id),
            title=metadata["topic"],
        )
        return PlainTextResponse(transcript, media_type="text/markdown")

    @app.websocket("/meetings/{meeting_id}/events")
    async def meeting_events(websocket: WebSocket, meeting_id: str) -> None:
        metadata_store.get(meeting_id)
        await websocket.accept()
        await websocket.send_json(
            {
                "type": "snapshot",
                "events": repository.read_events(meeting_id),
            }
        )
        await websocket.close()

    return app


def get_model(repository: ModelConfigRepository, model_id: str) -> ModelConfig:
    for model in repository.list_models():
        if model.id == model_id:
            return model
    raise HTTPException(status_code=404, detail=f"Unknown model: {model_id}")


def reject_terminal_meeting(repository: MeetingRepository, meeting_id: str) -> None:
    for event in repository.read_events(meeting_id):
        status = event.get("status")
        if status in {"closed", "cancelled"}:
            raise HTTPException(status_code=409, detail=f"Meeting is terminal: {status}")


def project_meeting_status(events: list[dict[str, Any]]) -> str:
    for event in events:
        status = event.get("status")
        if status in {"closed", "cancelled"}:
            return str(status)
    return "open"


class MeetingMetadataStore:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir

    def save(self, metadata: dict[str, str]) -> None:
        path = self._metadata_path(metadata["meeting_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")

    def get(self, meeting_id: str) -> dict[str, str]:
        path = self._metadata_path(meeting_id)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Unknown meeting: {meeting_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self) -> list[dict[str, str]]:
        meeting_root = self.data_dir / "meetings"
        if not meeting_root.exists():
            return []
        return [
            json.loads(path.read_text(encoding="utf-8"))
            for path in sorted(meeting_root.glob("*/metadata.json"))
        ]

    def _metadata_path(self, meeting_id: str) -> Path:
        return self.data_dir / "meetings" / meeting_id / "metadata.json"
