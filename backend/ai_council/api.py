from __future__ import annotations

import asyncio
import json
import os
import threading
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from ai_council.meetings.execution_state import (
    ActiveExecutionState,
    MeetingExecutionStateStore,
    interrupted_execution_event,
)
from ai_council.meetings.modes import (
    DEFAULT_MODE_ID,
    ModeCatalogRepository,
    ModeConfigError,
    ModeDefinition,
    parallel_plan,
    relay_plan,
)
from ai_council.meetings.repository import MeetingRepository
from ai_council.meetings.runner import MeetingRunner, RunnerAdapters, TokenStreamEvent
from ai_council.meetings.transcript import TranscriptProjector
from ai_council.models.adapters import (
    AdapterError,
    AnthropicHTTPAdapter,
    GeminiHTTPAdapter,
    MockModelAdapter,
    ModelRequest,
    OpenAICompatibleHTTPAdapter,
    SubscriptionCLIAdapter,
    TokenUsage,
)
from ai_council.models.config import (
    ModelConfig,
    ModelConfigError,
    ModelConfigRepository,
    validate_model_config_fields,
)
from ai_council.models.config import ModelPricing as ConfigModelPricing
from ai_council.prompting.renderer import PromptRenderer

MODEL_TEST_PROMPT = 'Return {"summary":"OK","arguments":[],"risks":[],"recommendation":"OK"}'


class MeetingParticipantRequest(BaseModel):
    role_id: str
    model_config_id: str | None = None
    display_name: str | None = None
    instance_prompt: str | None = None


class CreateMeetingRequest(BaseModel):
    topic: str
    mode_id: str = DEFAULT_MODE_ID
    participants: list[MeetingParticipantRequest] = Field(default_factory=list)
    inputs: dict[str, str] = Field(default_factory=dict)


class StartMeetingRequest(BaseModel):
    models: dict[str, str]


class RunRoleSequenceRequest(BaseModel):
    roles: list[str]
    models: dict[str, str]


class CorrectMeetingMessageRequest(BaseModel):
    content: str


class UpdateMeetingTagsRequest(BaseModel):
    tags: list[str]


class UpdateMeetingPinnedRequest(BaseModel):
    pinned: bool


class AddMeetingMessageRequest(BaseModel):
    content: str


class UpsertModelConfigRequest(BaseModel):
    adapter: str
    base_url: str | None = None
    model: str | None = None
    api_key_env: str | None = None
    supports_json_mode: bool = False
    extra_body: dict[str, Any] = Field(default_factory=dict)
    pricing: ModelPricingRequest | None = None
    command: list[str] | None = None
    timeout_seconds: float = 120


class CreateModelConfigRequest(UpsertModelConfigRequest):
    id: str


class ModelPricingRequest(BaseModel):
    currency: str
    input_per_1m_tokens: float = Field(ge=0)
    output_per_1m_tokens: float = Field(ge=0)


def create_app(
    *,
    data_dir: Path | str,
    model_config_path: Path | str,
    modes_config_path: Path | str,
    prompt_dir: Path | str,
    start_model_health_checks: bool = True,
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

    @app.exception_handler(RequestValidationError)
    async def request_validation_error_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        if (request.method == "POST" and request.url.path == "/models") or (
            request.method == "PUT" and request.url.path.startswith("/models/")
        ):
            detail = [
                {
                    "field": ".".join(str(part) for part in error["loc"] if part != "body"),
                    "message": error["msg"],
                }
                for error in exc.errors()
            ]
            return JSONResponse(status_code=422, content={"detail": detail})
        return JSONResponse(status_code=422, content={"detail": exc.errors()})

    data_path = Path(data_dir)
    metadata_store = MeetingMetadataStore(data_path)
    repository = MeetingRepository(data_path)
    execution_state_store = MeetingExecutionStateStore(data_path)
    model_repository = ModelConfigRepository(model_config_path)
    mode_catalog = ModeCatalogRepository(modes_config_path)
    stream_bus = MeetingStreamBus()
    model_adapters = {
        "mock": MockModelAdapter(),
        "openai-compatible-http": OpenAICompatibleHTTPAdapter(),
        "anthropic-http": AnthropicHTTPAdapter(),
        "gemini-http": GeminiHTTPAdapter(),
        "subscription-cli": SubscriptionCLIAdapter(),
    }
    runner = MeetingRunner(
        repository=repository,
        prompt_renderer=PromptRenderer(prompt_dir),
        adapters=RunnerAdapters(
            by_name=model_adapters,
        ),
        stream_sink=stream_bus.publish,
        execution_state_store=execution_state_store,
    )
    recover_interrupted_executions(repository, execution_state_store)
    projector = TranscriptProjector()
    jobs = MeetingJobManager()
    model_health = ModelHealthCheckStore()
    model_health_checker = ModelHealthChecker(model_repository, model_adapters, model_health)
    model_write_lock = threading.Lock()
    if start_model_health_checks:
        model_health_checker.start()

    @app.get("/models")
    def list_models() -> list[dict[str, Any]]:
        try:
            models = model_repository.list_models()
        except ModelConfigError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return [project_model_config(model, model_health.get(model.id)) for model in models]

    @app.post("/models", status_code=201)
    def create_model(request: CreateModelConfigRequest) -> dict[str, Any]:
        model = ModelConfig(
            id=request.id,
            adapter=request.adapter,
            base_url=request.base_url,
            model=request.model,
            api_key_env=request.api_key_env,
            supports_json_mode=request.supports_json_mode,
            extra_body=request.extra_body,
            pricing=project_model_pricing_request(request.pricing),
            command=request.command,
            timeout_seconds=request.timeout_seconds,
        )
        return save_model_or_422(
            model_repository,
            model_health,
            model,
            expect_existing=False,
            write_lock=model_write_lock,
        )

    @app.put("/models/{model_config_id}")
    def update_model(model_config_id: str, request: UpsertModelConfigRequest) -> dict[str, Any]:
        model = ModelConfig(
            id=model_config_id,
            adapter=request.adapter,
            base_url=request.base_url,
            model=request.model,
            api_key_env=request.api_key_env,
            supports_json_mode=request.supports_json_mode,
            extra_body=request.extra_body,
            pricing=project_model_pricing_request(request.pricing),
            command=request.command,
            timeout_seconds=request.timeout_seconds,
        )
        return save_model_or_422(
            model_repository,
            model_health,
            model,
            expect_existing=True,
            write_lock=model_write_lock,
        )

    @app.delete("/models/{model_config_id}")
    def delete_model(model_config_id: str) -> dict[str, Any]:
        with model_write_lock:
            if not model_repository.delete_model(model_config_id):
                raise HTTPException(status_code=404, detail=f"Unknown model: {model_config_id}")
            model_health.clear(model_config_id)
        referencing = open_meetings_referencing_model(
            metadata_store, repository, model_config_id
        )
        warning = None
        if referencing:
            warning = (
                f"Model is the latest selection in {len(referencing)} open meeting(s): "
                + ", ".join(referencing[:5])
            )
        return {"id": model_config_id, "warning": warning}

    @app.post("/models/{model_config_id}/test")
    def test_model(model_config_id: str) -> dict[str, str]:
        generation = model_health.generation(model_config_id)
        model = get_model(model_repository, model_config_id)
        result = check_model_health(model, model_adapters.get(model.adapter))
        model_health.record(model_config_id, result, generation)
        response = {"status": result.status, "tested_at": result.checked_at}
        if result.error is not None:
            response["error"] = result.error
        return response

    @app.get("/models/{model_config_id}/available-models")
    def discover_available_models(model_config_id: str) -> dict[str, list[str]]:
        model = get_model(model_repository, model_config_id)
        adapter = model_adapters.get(model.adapter)
        if not isinstance(adapter, OpenAICompatibleHTTPAdapter):
            raise HTTPException(
                status_code=400,
                detail=f"Model discovery is not supported for adapter: {model.adapter}",
            )
        try:
            return {"models": adapter.discover_models(model)}
        except AdapterError as error:
            raise HTTPException(status_code=502, detail=str(error)) from error

    @app.get("/modes")
    def list_modes_catalog() -> list[dict[str, Any]]:
        try:
            modes = mode_catalog.list_modes()
        except ModeConfigError as error:
            raise HTTPException(status_code=500, detail=str(error)) from error
        return [project_mode(mode) for mode in modes]

    @app.post("/meetings")
    def create_meeting(request: CreateMeetingRequest) -> dict[str, Any]:
        mode = get_mode_or_400(mode_catalog, request.mode_id)
        if not mode.available:
            raise HTTPException(
                status_code=400,
                detail=f"Mode is not yet supported: {mode.id}",
            )
        participants = normalize_participants(mode, request.participants, model_repository)

        declared_input_ids = {item.id for item in mode.inputs}
        unknown_inputs = sorted(set(request.inputs.keys()) - declared_input_ids)
        if unknown_inputs:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown input for mode {mode.id}: {', '.join(unknown_inputs)}",
            )
        for item in mode.inputs:
            if item.kind == "text" and not request.inputs.get(item.id, "").strip():
                raise HTTPException(
                    status_code=400,
                    detail=f"Missing required input: {item.id}",
                )

        meeting_id = f"meeting-{uuid.uuid4().hex}"
        created_at = now_iso()
        metadata = {
            "meeting_id": meeting_id,
            "topic": request.topic,
            "created_at": created_at,
            "tags": [],
            "pinned": False,
            "mode_id": mode.id,
            "participants": participants,
            "inputs": request.inputs,
        }
        metadata_store.save(metadata)
        return project_meeting_summary(metadata, [], mode=mode, model_pricing={})

    @app.get("/meetings")
    def list_meetings(q: str | None = None) -> list[dict[str, Any]]:
        query = (q or "").strip().lower()
        summaries: list[dict[str, Any]] = []
        pricing = model_pricing_by_id(model_repository)
        try:
            modes_by_id = {mode.id: mode for mode in mode_catalog.list_modes()}
        except ModeConfigError as error:
            raise HTTPException(status_code=500, detail=str(error)) from error
        for metadata in metadata_store.list():
            meeting_id = metadata["meeting_id"]
            events = repository.read_events(meeting_id)
            if query and not _meeting_matches_query(projector, metadata, events, query):
                continue
            mode_id = str(metadata.get("mode_id", DEFAULT_MODE_ID))
            mode = modes_by_id.get(mode_id) or modes_by_id.get(DEFAULT_MODE_ID)
            if mode is None:
                raise HTTPException(status_code=500, detail=f"Missing default mode: {DEFAULT_MODE_ID}")
            summaries.append(
                project_meeting_summary(
                    metadata,
                    events,
                    mode=mode,
                    model_pricing=pricing,
                    activity_status=live_activity_status(events, jobs.is_running(meeting_id), mode),
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
                mode=meeting_mode(mode_catalog, metadata),
                model_pricing=model_pricing_by_id(model_repository),
                activity_status=live_activity_status(
                    events,
                    jobs.is_running(meeting_id),
                    meeting_mode(mode_catalog, metadata),
                ),
            ),
            "events": events,
        }

    @app.put("/meetings/{meeting_id}/tags")
    def update_meeting_tags(meeting_id: str, request: UpdateMeetingTagsRequest) -> dict[str, Any]:
        metadata = metadata_store.get(meeting_id)
        metadata["tags"] = request.tags
        metadata_store.save(metadata)
        events = repository.read_events(meeting_id)
        return project_meeting_summary(
            metadata,
            events,
            mode=meeting_mode(mode_catalog, metadata),
            model_pricing=model_pricing_by_id(model_repository),
            activity_status=live_activity_status(
                events,
                jobs.is_running(meeting_id),
                meeting_mode(mode_catalog, metadata),
            ),
        )

    @app.put("/meetings/{meeting_id}/pinned")
    def update_meeting_pinned(
        meeting_id: str,
        request: UpdateMeetingPinnedRequest,
    ) -> dict[str, Any]:
        metadata = metadata_store.get(meeting_id)
        metadata["pinned"] = request.pinned
        metadata_store.save(metadata)
        events = repository.read_events(meeting_id)
        return project_meeting_summary(
            metadata,
            events,
            mode=meeting_mode(mode_catalog, metadata),
            model_pricing=model_pricing_by_id(model_repository),
            activity_status=live_activity_status(
                events,
                jobs.is_running(meeting_id),
                meeting_mode(mode_catalog, metadata),
            ),
        )

    @app.post("/meetings/{meeting_id}/start", status_code=202)
    def start_meeting(meeting_id: str, request: StartMeetingRequest) -> dict[str, str]:
        metadata = metadata_store.get(meeting_id)
        reject_terminal_meeting(repository, meeting_id)
        mode = meeting_mode(mode_catalog, metadata)
        participant_roles = {item["role_id"] for item in project_participants(mode, metadata)}
        missing_roles = sorted(participant_roles - request.models.keys())
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
            lambda: start_runner_for_mode(
                runner=runner,
                mode=mode,
                metadata=metadata,
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
        mode = meeting_mode(mode_catalog, metadata)
        if mode.category != "relay":
            raise HTTPException(status_code=400, detail=f"Mode does not support directed responses: {mode.id}")
        try:
            runner.respond_as_role(
                meeting_id=meeting_id,
                topic=metadata["topic"],
                role=role,
                model_assignments={
                    role_name: get_model(model_repository, model_id)
                    for role_name, model_id in request.models.items()
                },
                plan=relay_plan(mode),
                inputs=metadata.get("inputs") or {},
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
        mode = meeting_mode(mode_catalog, metadata)
        if mode.category != "relay":
            raise HTTPException(status_code=400, detail=f"Mode does not support role sequences: {mode.id}")
        try:
            runner.respond_as_sequence(
                meeting_id=meeting_id,
                topic=metadata["topic"],
                roles=request.roles,
                model_assignments={
                    role_name: get_model(model_repository, model_id)
                    for role_name, model_id in request.models.items()
                },
                plan=relay_plan(mode),
                inputs=metadata.get("inputs") or {},
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
        mode = meeting_mode(mode_catalog, metadata)
        model_assignments = {
            role: get_model(model_repository, model_id)
            for role, model_id in request.models.items()
        }
        try:
            if mode.category == "relay":
                runner.retry_failed_step(
                    meeting_id=meeting_id,
                    step_id=step_id,
                    topic=metadata["topic"],
                    model_assignments=model_assignments,
                    plan=relay_plan(mode),
                    inputs=metadata.get("inputs") or {},
                )
            else:
                runner.retry_failed_parallel_step(
                    meeting_id=meeting_id,
                    step_id=step_id,
                    topic=metadata["topic"],
                    model_assignments=model_assignments,
                    plan=parallel_plan(mode, project_participants(mode, metadata)),
                    inputs=metadata.get("inputs") or {},
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
        metadata = metadata_store.get(meeting_id)
        mode = meeting_mode(mode_catalog, metadata)
        await websocket.accept()
        events = repository.read_events(meeting_id)
        activity_status = live_activity_status(events, jobs.is_running(meeting_id), mode)
        try:
            await websocket.send_json(
                {
                    "type": "snapshot",
                    "events": events,
                    "stream_events": [],
                    "activity_status": activity_status,
                }
            )
            event_count = len(events)
            stream_cursor = stream_bus.cursor(meeting_id)
            while True:
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
                except TimeoutError:
                    pass
                events = repository.read_events(meeting_id)
                stream_events = stream_bus.events_since(meeting_id, stream_cursor)
                next_activity_status = live_activity_status(events, jobs.is_running(meeting_id), mode)
                if (
                    len(events) != event_count
                    or stream_events
                    or next_activity_status != activity_status
                ):
                    await websocket.send_json(
                        {
                            "type": "update",
                            "events": events[event_count:],
                            "stream_events": stream_events,
                            "activity_status": next_activity_status,
                        }
                    )
                    event_count = len(events)
                    stream_cursor += len(stream_events)
                    activity_status = next_activity_status
        except (WebSocketDisconnect, RuntimeError):
            return

    return app


def get_mode_or_400(catalog: ModeCatalogRepository, mode_id: str) -> ModeDefinition:
    try:
        mode = catalog.get_mode(mode_id)
    except ModeConfigError as error:
        raise HTTPException(status_code=500, detail=str(error)) from error
    if mode is None:
        raise HTTPException(status_code=404, detail=f"Unknown mode: {mode_id}")
    return mode


def meeting_mode(catalog: ModeCatalogRepository, metadata: dict[str, Any]) -> ModeDefinition:
    return get_mode_or_400(catalog, str(metadata.get("mode_id", DEFAULT_MODE_ID)))


def project_mode(mode: ModeDefinition) -> dict[str, Any]:
    result: dict[str, Any] = {
        "id": mode.id,
        "name": mode.name,
        "category": mode.category,
        "tagline": mode.tagline,
        "when_to_use": mode.when_to_use,
        "sop": list(mode.sop),
        "default_scene": mode.default_scene,
        "available": mode.available,
        "inputs": [
            {"id": item.id, "label": item.label, "kind": item.kind} for item in mode.inputs
        ],
        "roles": [
            {
                "id": role.id,
                "name": role.name,
                "color": role.color,
                "kind": role.kind,
                "portrait": role.portrait,
            }
            for role in mode.roles
        ],
    }
    if mode.steps:
        result["steps"] = [
            {"role": step.role, "template": step.template, "label": step.label}
            for step in mode.steps
        ]
    if mode.fanout is not None:
        result["fanout"] = {
            "role": mode.fanout.role,
            "template": mode.fanout.template,
            "label": mode.fanout.label,
            "min_instances": mode.fanout.min_instances,
            "max_instances": mode.fanout.max_instances,
            "instance_prompt": mode.fanout.instance_prompt,
        }
    if mode.synthesis is not None:
        result["synthesis"] = {
            "role": mode.synthesis.role,
            "template": mode.synthesis.template,
            "label": mode.synthesis.label,
        }
    return result


def normalize_participants(
    mode: ModeDefinition,
    requested: list[MeetingParticipantRequest],
    model_repository: ModelConfigRepository,
) -> list[dict[str, Any]]:
    if mode.category == "relay":
        participants = [participant.model_dump() for participant in requested]
        role_ids = set(mode.role_ids())
        validate_participant_ids(
            mode=mode,
            participants=participants,
            allowed_role_ids=role_ids,
            model_repository=model_repository,
        )
        return participants

    if mode.fanout is None or mode.synthesis is None:
        raise HTTPException(status_code=500, detail=f"Parallel mode is incomplete: {mode.id}")

    participants = [participant.model_dump() for participant in requested]
    if not participants:
        participants = [
            {"role_id": f"{mode.fanout.role}-{index}", "model_config_id": None}
            for index in range(1, mode.fanout.min_instances + 1)
        ]
        participants.append({"role_id": mode.synthesis.role, "model_config_id": None})

    validate_participant_ids(
        mode=mode,
        participants=participants,
        allowed_role_ids=parallel_allowed_role_ids(mode, participants),
        model_repository=model_repository,
    )
    member_ids = parallel_member_role_ids(mode, participants)
    if not (mode.fanout.min_instances <= len(member_ids) <= mode.fanout.max_instances):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Mode {mode.id} requires {mode.fanout.min_instances}-"
                f"{mode.fanout.max_instances} fanout members"
            ),
        )
    if mode.synthesis.role not in {str(item.get("role_id")) for item in participants}:
        participants.append({"role_id": mode.synthesis.role, "model_config_id": None})
    return participants


def validate_participant_ids(
    *,
    mode: ModeDefinition,
    participants: list[dict[str, Any]],
    allowed_role_ids: set[str],
    model_repository: ModelConfigRepository,
) -> None:
    seen_role_ids: set[str] = set()
    for participant in participants:
        role_id = str(participant.get("role_id"))
        if role_id not in allowed_role_ids:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown role for mode {mode.id}: {role_id}",
            )
        if role_id in seen_role_ids:
            raise HTTPException(
                status_code=400,
                detail=f"Duplicate participant role: {role_id}",
            )
        seen_role_ids.add(role_id)
        model_config_id = participant.get("model_config_id")
        if model_config_id is not None:
            get_model(model_repository, str(model_config_id))


def parallel_allowed_role_ids(
    mode: ModeDefinition,
    participants: list[dict[str, Any]],
) -> set[str]:
    if mode.fanout is None or mode.synthesis is None:
        return set()
    fixed_member_ids = {role.id for role in mode.roles if role.kind == "member"}
    allowed = {mode.synthesis.role, *fixed_member_ids}
    if fixed_member_ids:
        return allowed
    for participant in participants:
        role_id = str(participant.get("role_id"))
        if is_fanout_instance_role(mode.fanout.role, role_id):
            allowed.add(role_id)
    return allowed


def parallel_member_role_ids(mode: ModeDefinition, participants: list[dict[str, Any]]) -> list[str]:
    if mode.fanout is None:
        return []
    fixed_member_ids = {role.id for role in mode.roles if role.kind == "member"}
    member_ids: list[str] = []
    for participant in participants:
        role_id = str(participant.get("role_id"))
        if fixed_member_ids:
            if role_id in fixed_member_ids:
                member_ids.append(role_id)
        elif is_fanout_instance_role(mode.fanout.role, role_id):
            member_ids.append(role_id)
    return member_ids


def is_fanout_instance_role(prototype_role: str, role_id: str) -> bool:
    prefix = f"{prototype_role}-"
    return role_id.startswith(prefix) and role_id[len(prefix) :].isdigit()


def fanout_instance_index(role_id: str) -> int:
    suffix = role_id.rsplit("-", 1)[-1]
    return int(suffix) if suffix.isdigit() else 0


def project_participants(mode: ModeDefinition, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    if mode.category == "parallel":
        return project_parallel_participants(mode, metadata)

    stored = {
        str(item.get("role_id")): item
        for item in (metadata.get("participants") or [])
        if isinstance(item, dict)
    }
    projected = []
    for role in mode.roles:
        entry = stored.get(role.id, {})
        projected.append(
            {
                "role_id": role.id,
                "name": role.name,
                "color": role.color,
                "kind": role.kind,
                "portrait": role.portrait,
                "model_config_id": entry.get("model_config_id"),
                "display_name": entry.get("display_name") or role.name,
                "instance_prompt": entry.get("instance_prompt"),
            }
        )
    return projected


def project_parallel_participants(mode: ModeDefinition, metadata: dict[str, Any]) -> list[dict[str, Any]]:
    role_defs = {role.id: role for role in mode.roles}
    stored = [
        item
        for item in (metadata.get("participants") or [])
        if isinstance(item, dict) and isinstance(item.get("role_id"), str)
    ]
    stored.sort(key=lambda item: parallel_participant_sort_key(mode, str(item["role_id"])))
    projected: list[dict[str, Any]] = []
    for entry in stored:
        role_id = str(entry["role_id"])
        role_def = role_defs.get(role_id)
        is_member_instance = (
            mode.fanout is not None and is_fanout_instance_role(mode.fanout.role, role_id)
        )
        if role_def is None and not is_member_instance:
            continue
        index = fanout_instance_index(role_id)
        default_name = (
            role_def.name
            if role_def is not None
            else f"{mode.fanout.label} {index}" if mode.fanout is not None else role_id
        )
        projected.append(
            {
                "role_id": role_id,
                "name": default_name,
                "color": role_def.color if role_def is not None else "#4d8dff",
                "kind": role_def.kind if role_def is not None else "member",
                "portrait": role_def.portrait if role_def is not None else None,
                "model_config_id": entry.get("model_config_id"),
                "display_name": entry.get("display_name") or default_name,
                "instance_prompt": entry.get("instance_prompt"),
            }
        )
    return projected


def parallel_participant_sort_key(mode: ModeDefinition, role_id: str) -> tuple[int, int, str]:
    if mode.fanout is not None and is_fanout_instance_role(mode.fanout.role, role_id):
        return (0, fanout_instance_index(role_id), role_id)
    role_def = next((role for role in mode.roles if role.id == role_id), None)
    if role_def is not None and role_def.kind == "member":
        return (0, mode.role_ids().index(role_id), role_id)
    return (1, 0, role_id)


def start_runner_for_mode(
    *,
    runner: MeetingRunner,
    mode: ModeDefinition,
    metadata: dict[str, Any],
    model_assignments: dict[str, ModelConfig],
) -> None:
    if mode.category == "relay":
        runner.start(
            meeting_id=metadata["meeting_id"],
            topic=metadata["topic"],
            model_assignments=model_assignments,
            plan=relay_plan(mode),
            inputs=metadata.get("inputs") or {},
        )
        return
    runner.start_parallel(
        meeting_id=metadata["meeting_id"],
        topic=metadata["topic"],
        model_assignments=model_assignments,
        plan=parallel_plan(mode, project_participants(mode, metadata)),
        inputs=metadata.get("inputs") or {},
    )


def get_model(repository: ModelConfigRepository, model_id: str) -> ModelConfig:
    try:
        models = repository.list_models()
    except ModelConfigError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    for model in models:
        if model.id == model_id:
            return model
    raise HTTPException(status_code=404, detail=f"Unknown model: {model_id}")


def save_model_or_422(
    model_repository: ModelConfigRepository,
    model_health: ModelHealthCheckStore,
    model: ModelConfig,
    *,
    expect_existing: bool,
    write_lock: threading.Lock,
) -> dict[str, Any]:
    errors = validate_model_config_fields(model)
    if errors:
        raise HTTPException(status_code=422, detail=errors)
    with write_lock:
        try:
            existing_models = model_repository.list_models()
        except ModelConfigError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        already_exists = any(existing.id == model.id for existing in existing_models)
        if expect_existing and not already_exists:
            raise HTTPException(status_code=404, detail=f"Unknown model: {model.id}")
        if not expect_existing and already_exists:
            raise HTTPException(
                status_code=422,
                detail=[{"field": "id", "message": "Model id already exists"}],
            )
        try:
            saved = model_repository.save_model(model)
        except ModelConfigError as error:
            raise HTTPException(
                status_code=422,
                detail=[{"field": "", "message": str(error)}],
            ) from error
        model_health.clear(saved.id)
    return project_model_config(saved, model_health.get(saved.id))


def project_model_config(
    model: ModelConfig,
    health: ModelHealthCheckResult | None = None,
) -> dict[str, Any]:
    return {
        **model.__dict__,
        "pricing": project_model_pricing(model.pricing),
        "status": health.status if health is not None else model.status,
        "health_checked_at": health.checked_at if health is not None else None,
        "health_error": health.error if health is not None else None,
        "credential": project_model_credential(model),
    }


def project_model_credential(model: ModelConfig) -> dict[str, Any] | None:
    if not model.api_key_env:
        return None
    return {
        "type": "env",
        "env_var": model.api_key_env,
        "configured": bool(os.environ.get(model.api_key_env)),
    }


def project_model_pricing_request(
    pricing: ModelPricingRequest | None,
) -> ConfigModelPricing | None:
    if pricing is None:
        return None
    return ConfigModelPricing(
        currency=pricing.currency,
        input_per_1m_tokens=pricing.input_per_1m_tokens,
        output_per_1m_tokens=pricing.output_per_1m_tokens,
    )


def project_model_pricing(pricing: ConfigModelPricing | None) -> dict[str, Any] | None:
    if pricing is None:
        return None
    return {
        "currency": pricing.currency,
        "input_per_1m_tokens": pricing.input_per_1m_tokens,
        "output_per_1m_tokens": pricing.output_per_1m_tokens,
    }


def model_pricing_by_id(repository: ModelConfigRepository) -> dict[str, ConfigModelPricing | None]:
    try:
        return {model.id: model.pricing for model in repository.list_models()}
    except ModelConfigError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def _meeting_matches_query(
    projector: TranscriptProjector,
    metadata: dict[str, Any],
    events: list[dict[str, Any]],
    query: str,
) -> bool:
    transcript = projector.project(events, title=str(metadata.get("topic", "")))
    tags = " ".join(metadata.get("tags") or [])
    haystack = f"{transcript}\n{metadata.get('meeting_id', '')}\n{tags}".lower()
    return query in haystack


def reject_terminal_meeting(repository: MeetingRepository, meeting_id: str) -> None:
    for event in repository.read_events(meeting_id):
        status = event.get("status")
        if status in {"closed", "cancelled"}:
            raise HTTPException(status_code=409, detail=f"Meeting is terminal: {status}")


def recover_interrupted_executions(
    repository: MeetingRepository,
    execution_state_store: MeetingExecutionStateStore,
) -> None:
    for state in execution_state_store.list_active():
        meeting_id = state["meeting_id"]
        if not _step_has_finished(repository.read_events(meeting_id), state):
            repository.append_event(meeting_id, interrupted_execution_event(state))
        execution_state_store.clear_active(meeting_id)


def _step_has_finished(
    events: list[dict[str, Any]],
    state: ActiveExecutionState,
) -> bool:
    matching_events = [
        event
        for event in events
        if event.get("step_id") == state["step_id"]
        and event.get("attempt") == state["attempt"]
        and event.get("status") in {"completed", "failed"}
    ]
    return bool(matching_events)


def project_meeting_status(events: list[dict[str, Any]]) -> str:
    for event in events:
        status = event.get("status")
        if status in {"closed", "cancelled"}:
            return str(status)
    return "open"


def open_meetings_referencing_model(
    metadata_store: MeetingMetadataStore,
    repository: MeetingRepository,
    model_config_id: str,
) -> list[str]:
    """Open meetings whose latest per-role model selection is `model_config_id`.

    "Latest selection" means either the model recorded on a role's most
    recent event that carries a model_config_id, or the model stored on the
    meeting's participants metadata (covers roles that haven't run a step
    yet, e.g. right after meeting creation but before start).
    """
    referencing: list[str] = []
    for metadata in metadata_store.list():
        meeting_id = metadata["meeting_id"]
        events = repository.read_events(meeting_id)
        if project_meeting_status(events) != "open":
            continue
        stored = {
            item.get("model_config_id")
            for item in (metadata.get("participants") or [])
            if isinstance(item, dict)
        }
        latest_by_role: dict[str, Any] = {}
        for event in events:
            if isinstance(event.get("model_config_id"), str):
                latest_by_role[str(event.get("role"))] = event["model_config_id"]
        if model_config_id in stored or model_config_id in latest_by_role.values():
            referencing.append(meeting_id)
    return referencing


def project_activity_status(events: list[dict[str, Any]]) -> str:
    if not events:
        return "idle"
    terminal_status = project_meeting_status(events)
    if terminal_status in {"closed", "cancelled"}:
        return terminal_status
    latest_event = events[-1]
    if latest_event.get("status") == "failed":
        base_step_id = str(latest_event.get("base_step_id", latest_event.get("step_id", "")))
        if base_step_id.startswith("member-"):
            return "waiting"
        return "failed"
    if latest_event.get("role") == "Human":
        return "waiting"
    return "completed"


def live_activity_status(
    events: list[dict[str, Any]],
    is_running: bool,
    mode: ModeDefinition | None = None,
) -> str:
    projected = project_activity_status_for_mode(events, mode)
    if projected in {"closed", "cancelled"}:
        return projected
    return "running" if is_running else projected


def project_activity_status_for_mode(
    events: list[dict[str, Any]],
    mode: ModeDefinition | None,
) -> str:
    projected = project_activity_status(events)
    if mode is None or projected != "completed":
        return projected
    latest_event = events[-1]
    if latest_event.get("interaction_type") in {"directed-role-response", "role-sequence-response"}:
        return "completed"
    if mode.category == "parallel":
        base_step_id = str(latest_event.get("base_step_id", latest_event.get("step_id", "")))
        return "completed" if base_step_id == "synthesis" else "running"
    if not mode.steps:
        return projected
    final_step_id = mode.steps[-1].template.replace("_", "-")
    base_step_id = str(latest_event.get("base_step_id", latest_event.get("step_id", "")))
    return "completed" if base_step_id == final_step_id else "running"


def project_meeting_summary(
    metadata: dict[str, str],
    events: list[dict[str, Any]],
    *,
    mode: ModeDefinition,
    model_pricing: dict[str, ConfigModelPricing | None] | None = None,
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
        "token_usage": project_token_usage(events),
        "estimated_cost": project_estimated_cost(events, model_pricing or {}),
        "tags": metadata.get("tags") or [],
        "pinned": bool(metadata.get("pinned", False)),
        "mode_id": mode.id,
        "participants": project_participants(mode, metadata),
    }


def project_token_usage(events: list[dict[str, Any]]) -> TokenUsage:
    totals: TokenUsage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for event in events:
        usage = event.get("token_usage")
        if not isinstance(usage, dict):
            continue
        for key in totals:
            value = usage.get(key)
            if isinstance(value, int):
                totals[key] += value
    return totals


def project_estimated_cost(
    events: list[dict[str, Any]],
    model_pricing: dict[str, ConfigModelPricing | None],
) -> dict[str, Any] | None:
    amount = Decimal("0")
    currency: str | None = None
    saw_usage = False
    for event in events:
        usage = event.get("token_usage")
        if not isinstance(usage, dict):
            continue
        model_id = event.get("model_config_id")
        if not isinstance(model_id, str):
            return None
        pricing = model_pricing.get(model_id)
        if not pricing:
            return None
        event_currency = pricing.currency
        if not event_currency:
            return None
        if currency is None:
            currency = event_currency
        elif currency != event_currency:
            return None
        input_rate = _decimal_pricing_value(pricing.input_per_1m_tokens)
        output_rate = _decimal_pricing_value(pricing.output_per_1m_tokens)
        prompt_tokens = usage.get("prompt_tokens")
        completion_tokens = usage.get("completion_tokens")
        if (
            input_rate is None
            or output_rate is None
            or not isinstance(prompt_tokens, int)
            or not isinstance(completion_tokens, int)
        ):
            return None
        amount += (Decimal(prompt_tokens) * input_rate) / Decimal(1_000_000)
        amount += (Decimal(completion_tokens) * output_rate) / Decimal(1_000_000)
        saw_usage = True
    if not saw_usage or currency is None:
        return None
    return {"currency": currency, "amount": float(amount)}


def _decimal_pricing_value(value: Any) -> Decimal | None:
    if not isinstance(value, int | float | str):
        return None
    try:
        decimal_value = Decimal(str(value))
    except InvalidOperation:
        return None
    if decimal_value < 0:
        return None
    return decimal_value


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class ModelHealthCheckResult:
    status: str
    checked_at: str
    error: str | None = None


def check_model_health(model: ModelConfig, adapter: Any | None) -> ModelHealthCheckResult:
    checked_at = now_iso()
    if adapter is None or not hasattr(adapter, "complete"):
        return ModelHealthCheckResult(
            status="unavailable",
            checked_at=checked_at,
            error=f"Unknown adapter: {model.adapter}",
        )
    try:
        adapter.complete(ModelRequest(prompt=MODEL_TEST_PROMPT, model_config=model))
    except AdapterError as error:
        return ModelHealthCheckResult(
            status="unavailable",
            checked_at=checked_at,
            error=str(error),
        )
    except Exception as error:
        return ModelHealthCheckResult(
            status="unavailable",
            checked_at=checked_at,
            error=str(error),
        )
    return ModelHealthCheckResult(status="available", checked_at=checked_at)


class ModelHealthCheckStore:
    """Tracks health-check results per model id.

    Each id has a generation counter that `clear()` bumps whenever the model
    is (re)saved. `record()` only writes if the generation it was given still
    matches, so a health check that was already in flight when a save
    happened can't clobber the freshly-reset "unknown" status with a stale
    result once it finishes.
    """

    def __init__(self) -> None:
        self._checks: dict[str, ModelHealthCheckResult] = {}
        self._generations: dict[str, int] = {}
        self._lock = threading.Lock()

    def record(self, model_id: str, result: ModelHealthCheckResult, generation: int) -> None:
        with self._lock:
            if generation != self._generations.get(model_id, 0):
                return
            self._checks[model_id] = result

    def get(self, model_id: str) -> ModelHealthCheckResult | None:
        with self._lock:
            return self._checks.get(model_id)

    def generation(self, model_id: str) -> int:
        with self._lock:
            return self._generations.get(model_id, 0)

    def clear(self, model_id: str) -> None:
        with self._lock:
            self._checks.pop(model_id, None)
            self._generations[model_id] = self._generations.get(model_id, 0) + 1


class ModelHealthChecker:
    def __init__(
        self,
        repository: ModelConfigRepository,
        adapters: dict[str, object],
        store: ModelHealthCheckStore,
    ) -> None:
        self.repository = repository
        self.adapters = adapters
        self.store = store
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="ai-council-health")

    def start(self) -> None:
        self._executor.submit(self._check_all)

    def _check_all(self) -> None:
        try:
            models = self.repository.list_models()
        except ModelConfigError:
            return
        for model in models:
            self._check_model(model.id)

    def _check_model(self, model_id: str) -> None:
        # Capture the generation before re-reading the config, so a save
        # that races in between is guaranteed to be caught: either it lands
        # before this read (we'd then check the fresh config, but that's
        # fine) or after (its clear() bumps the generation past what we
        # captured, so our record() below is correctly dropped as stale).
        generation = self.store.generation(model_id)
        model = self._find_model(model_id)
        if model is None:
            return
        result = check_model_health(model, self.adapters.get(model.adapter))
        self.store.record(model_id, result, generation)

    def _find_model(self, model_id: str) -> ModelConfig | None:
        try:
            models = self.repository.list_models()
        except ModelConfigError:
            return None
        for model in models:
            if model.id == model_id:
                return model
        return None


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


class MeetingStreamBus:
    def __init__(self) -> None:
        self._events: dict[str, list[TokenStreamEvent]] = {}
        self._lock = threading.Lock()

    def publish(self, meeting_id: str, event: TokenStreamEvent) -> None:
        with self._lock:
            self._events.setdefault(meeting_id, []).append(event)

    def cursor(self, meeting_id: str) -> int:
        with self._lock:
            return len(self._events.get(meeting_id, []))

    def events_since(self, meeting_id: str, index: int) -> list[TokenStreamEvent]:
        with self._lock:
            return list(self._events.get(meeting_id, [])[index:])


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
