from __future__ import annotations

import asyncio
import json
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel

from ai_council.meetings.repository import MeetingRepository
from ai_council.meetings.runner import MeetingRunner, RunnerAdapters
from ai_council.meetings.transcript import TranscriptProjector
from ai_council.models.adapters import (
    AdapterError,
    MockModelAdapter,
    ModelRequest,
    OpenAICompatibleHTTPAdapter,
    SubscriptionCLIAdapter,
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


class CorrectMeetingMessageRequest(BaseModel):
    content: str


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
            "http://localhost:3009",
            "http://127.0.0.1:3009",
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
        "subscription-cli": SubscriptionCLIAdapter(),
    }
    runner = MeetingRunner(
        repository=repository,
        prompt_renderer=PromptRenderer(prompt_dir),
        adapters=RunnerAdapters(
            by_name=model_adapters,
        ),
    )
    projector = TranscriptProjector()
    jobs = MeetingJobManager()

    @app.get("/models")
    def list_models() -> list[dict[str, Any]]:
        return [model.__dict__ for model in model_repository.list_models()]

    @app.post("/models/{model_config_id}/test")
    def test_model(model_config_id: str) -> dict[str, str]:
        model = get_model(model_repository, model_config_id)
        adapter = model_adapters.get(model.adapter)
        tested_at = now_iso()
        if adapter is None:
            return {
                "status": "unavailable",
                "tested_at": tested_at,
                "error": f"Unknown adapter: {model.adapter}",
            }
        try:
            adapter.complete(
                ModelRequest(
                    prompt='Return {"summary":"OK","arguments":[],"risks":[],"recommendation":"OK"}',
                    model_config=model,
                )
            )
        except AdapterError as error:
            return {"status": "unavailable", "tested_at": tested_at, "error": str(error)}
        return {"status": "available", "tested_at": tested_at}

    @app.post("/meetings")
    def create_meeting(request: CreateMeetingRequest) -> dict[str, Any]:
        meeting_id = f"meeting-{uuid.uuid4().hex}"
        created_at = now_iso()
        metadata = {
            "meeting_id": meeting_id,
            "topic": request.topic,
            "created_at": created_at,
        }
        metadata_store.save(metadata)
        return project_meeting_summary(metadata, [])

    @app.get("/meetings")
    def list_meetings() -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for metadata in metadata_store.list():
            meeting_id = metadata["meeting_id"]
            events = repository.read_events(meeting_id)
            summaries.append(
                project_meeting_summary(
                    metadata,
                    events,
                    activity_status=live_activity_status(events, jobs.is_running(meeting_id)),
                )
            )
        return summaries

    @app.get("/meetings/{meeting_id}")
    def get_meeting(meeting_id: str) -> dict[str, Any]:
        metadata = metadata_store.get(meeting_id)
        events = repository.read_events(meeting_id)
        return {
            **project_meeting_summary(
                metadata,
                events,
                activity_status=live_activity_status(events, jobs.is_running(meeting_id)),
            ),
            "events": events,
        }

    @app.post("/meetings/{meeting_id}/start", status_code=202)
    def start_meeting(meeting_id: str, request: StartMeetingRequest) -> dict[str, str]:
        metadata = metadata_store.get(meeting_id)
        reject_terminal_meeting(repository, meeting_id)
        missing_roles = sorted({"Blue", "Red", "Judge"} - request.models.keys())
        if missing_roles:
            raise HTTPException(
                status_code=400,
                detail=f"Missing model assignments: {', '.join(missing_roles)}",
            )
        model_assignments = {
            role: get_model(model_repository, model_id)
            for role, model_id in request.models.items()
        }
        if not jobs.start(
            meeting_id,
            lambda: runner.start(
                meeting_id=meeting_id,
                topic=metadata["topic"],
                model_assignments=model_assignments,
            ),
        ):
            raise HTTPException(status_code=409, detail="Meeting is already running")
        return {"status": "running"}

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

    @app.delete("/meetings/{meeting_id}", status_code=204)
    def delete_meeting(meeting_id: str) -> Response:
        metadata_store.get(meeting_id)
        if jobs.is_running(meeting_id):
            raise HTTPException(status_code=409, detail="Cannot delete a running meeting")
        repository.delete(meeting_id)
        return Response(status_code=204)

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

    @app.post("/meetings/{meeting_id}/messages/{event_id}/correct")
    def correct_meeting_message(
        meeting_id: str,
        event_id: str,
        request: CorrectMeetingMessageRequest,
    ) -> dict[str, Any]:
        metadata_store.get(meeting_id)
        reject_terminal_meeting(repository, meeting_id)
        original_event = next(
            (
                event
                for event in repository.read_events(meeting_id)
                if event.get("event_id") == event_id
            ),
            None,
        )
        if original_event is None:
            raise HTTPException(status_code=404, detail=f"Unknown event: {event_id}")
        if original_event.get("role") != "Human" or original_event.get("step_id") != "human-message":
            raise HTTPException(status_code=400, detail="Only human messages can be corrected")
        correction = {
            "event_id": f"{meeting_id}:human-message-correction:{uuid.uuid4().hex}",
            "meeting_id": meeting_id,
            "step_id": "human-message",
            "role": "Human",
            "attempt": 1,
            "status": "completed",
            "content": request.content,
            "corrects_event_id": event_id,
        }
        repository.append_event(meeting_id, correction)
        return correction

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
        return {"status": project_activity_status(repository.read_events(meeting_id))}

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
        return {"status": project_activity_status(repository.read_events(meeting_id))}

    @app.post("/meetings/{meeting_id}/steps/{step_id}/retry")
    def retry_step(
        meeting_id: str,
        step_id: str,
        request: StartMeetingRequest,
    ) -> dict[str, str]:
        metadata = metadata_store.get(meeting_id)
        reject_terminal_meeting(repository, meeting_id)
        try:
            runner.retry_failed_step(
                meeting_id=meeting_id,
                step_id=step_id,
                topic=metadata["topic"],
                model_assignments={
                    role: get_model(model_repository, model_id)
                    for role, model_id in request.models.items()
                },
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"status": project_activity_status(repository.read_events(meeting_id))}

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
        events = repository.read_events(meeting_id)
        activity_status = live_activity_status(events, jobs.is_running(meeting_id))
        try:
            await websocket.send_json(
                {
                    "type": "snapshot",
                    "events": events,
                    "activity_status": activity_status,
                }
            )
            event_count = len(events)
            while True:
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
                except TimeoutError:
                    pass
                events = repository.read_events(meeting_id)
                next_activity_status = live_activity_status(events, jobs.is_running(meeting_id))
                if len(events) != event_count or next_activity_status != activity_status:
                    await websocket.send_json(
                        {
                            "type": "update",
                            "events": events[event_count:],
                            "activity_status": next_activity_status,
                        }
                    )
                    event_count = len(events)
                    activity_status = next_activity_status
        except (WebSocketDisconnect, RuntimeError):
            return

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


def project_activity_status(events: list[dict[str, Any]]) -> str:
    if not events:
        return "idle"
    terminal_status = project_meeting_status(events)
    if terminal_status in {"closed", "cancelled"}:
        return terminal_status
    latest_event = events[-1]
    if latest_event.get("status") == "failed":
        return "failed"
    if latest_event.get("role") == "Human":
        return "waiting"
    return "completed"


def live_activity_status(events: list[dict[str, Any]], is_running: bool) -> str:
    projected = project_activity_status(events)
    if projected in {"closed", "cancelled"}:
        return projected
    return "running" if is_running else projected


def project_meeting_summary(
    metadata: dict[str, str],
    events: list[dict[str, Any]],
    *,
    activity_status: str | None = None,
) -> dict[str, Any]:
    created_at = metadata.get("created_at", "")
    updated_at = str(events[-1].get("created_at", created_at)) if events else created_at
    latest_event = events[-1] if events else None
    return {
        **metadata,
        "created_at": created_at,
        "updated_at": updated_at,
        "status": project_meeting_status(events),
        "activity_status": activity_status or project_activity_status(events),
        "last_step_id": latest_event.get("step_id") if latest_event else None,
    }


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class MeetingJobManager:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ai-council")
        self._running: dict[str, Future[None]] = {}
        self._lock = threading.Lock()

    def start(self, meeting_id: str, operation: Callable[[], None]) -> bool:
        with self._lock:
            current = self._running.get(meeting_id)
            if current is not None and not current.done():
                return False
            future = self._executor.submit(operation)
            self._running[meeting_id] = future
        future.add_done_callback(lambda completed: self._finish(meeting_id, completed))
        return True

    def is_running(self, meeting_id: str) -> bool:
        with self._lock:
            future = self._running.get(meeting_id)
            return future is not None and not future.done()

    def _finish(self, meeting_id: str, completed: Future[None]) -> None:
        with self._lock:
            if self._running.get(meeting_id) is completed:
                self._running.pop(meeting_id, None)


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
