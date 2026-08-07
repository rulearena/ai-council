from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import threading
import urllib.parse
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable, Literal

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, field_validator, model_validator

from ai_council.meetings.execution_state import (
    ActiveExecutionState,
    MeetingExecutionStateStore,
    interrupted_execution_event,
)
from ai_council.meetings.case_materials import (
    CaseMaterialConflict,
    CaseMaterialLimits as VersionedCaseMaterialLimits,
    CaseMaterials,
    CaseMaterialsView,
    CaseMaterialValidationError,
)
from ai_council.meetings.attachments import (
    ATTACHMENT_EVENT_KIND,
    ATTACHMENT_REMOVED_KIND,
    AttachmentLimits,
    AttachmentStore,
    MultipartUploadError,
    classify_extension,
    mime_type_for_extension,
    parse_upload_part,
)
from ai_council.meetings.deliberation import (
    DeliberationEpochs,
    RestartCommand,
)
from ai_council.meetings.courtroom import (
    CourtroomWorkflowError,
    CourtroomWorkflowService,
    project_courtroom,
)
from ai_council.meetings.case_profiles import (
    CourtroomCaseProfile,
    CourtroomCaseProfileError,
)
from ai_council.meetings.coordination import MeetingTransitionCoordinator
from ai_council.meetings.assignments import (
    AssignmentValidationError,
    MeetingModelAssignments,
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
from ai_council.meetings.chatroom_routing import (
    ChatroomMentionToken,
    ChatroomSourceToken,
    rejected,
    validate_chatroom_routing,
    ValidatedChatroomRouting,
)
from ai_council.meetings.input_envelope import CASE_EVIDENCE_BY_ROLE_INPUT
from ai_council.meetings.runner import (
    CASE_FILES_BY_ROLE_INPUT,
    CASE_FILES_DEFAULT_ROLE,
    MATERIALS_REVISION_INPUT,
    MATERIALS_REFS_INPUT,
    latest_unresolved_fixed_relay_failure,
    MeetingRunner,
    RunnerAdapters,
    TokenStreamEvent,
)
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
from ai_council.prompting.schemas import (
    DEFAULT_OUTPUT_SCHEMA_ID,
    DEFAULT_OUTPUT_SCHEMA_REGISTRY,
)

MODEL_TEST_PROMPT = 'Return {"summary":"OK","arguments":[],"risks":[],"recommendation":"OK"}'
CHINESE_DIGITS = "零一二三四五六七八九"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CaseFileLimits:
    per_file_chars: int = 50_000
    total_chars: int = 120_000

    def __post_init__(self) -> None:
        if self.per_file_chars <= 0:
            raise ValueError("AI_COUNCIL_MAX_CASE_FILE_CHARS must be a positive integer")
        if self.total_chars <= 0:
            raise ValueError("AI_COUNCIL_MAX_TOTAL_CASE_FILE_CHARS must be a positive integer")
        if self.total_chars < self.per_file_chars:
            raise ValueError(
                "AI_COUNCIL_MAX_TOTAL_CASE_FILE_CHARS must be greater than or equal to "
                "AI_COUNCIL_MAX_CASE_FILE_CHARS"
            )

    @classmethod
    def from_environment(cls) -> CaseFileLimits:
        return cls(
            per_file_chars=_positive_integer_environment(
                "AI_COUNCIL_MAX_CASE_FILE_CHARS", 50_000
            ),
            total_chars=_positive_integer_environment(
                "AI_COUNCIL_MAX_TOTAL_CASE_FILE_CHARS", 120_000
            ),
        )


def _positive_integer_environment(name: str, default: int) -> int:
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as error:
        raise ValueError(f"{name} must be a positive integer") from error
    if value <= 0:
        raise ValueError(f"{name} must be a positive integer")
    return value


# A multipart request body carries boundary + part headers on top of the file
# bytes themselves, so a declared Content-Length is always a little above the
# file size.  This slack lets the per-file limit be enforced against the parsed
# file while still bounding how much of the request is ever buffered.
_MULTIPART_OVERHEAD_BYTES = 64 * 1024


async def _read_upload_body(request: Request, file_limit_bytes: int) -> bytes:
    """Read a multipart upload body without buffering beyond the per-file limit.

    A declared ``Content-Length`` well over the limit is rejected before any
    body bytes are read; otherwise the body is streamed and the same bound is
    enforced as chunks arrive.  The exact per-file check still runs against the
    parsed file content, so the contract (over-limit writes no blob/event)
    is unchanged.
    """
    bound = file_limit_bytes + _MULTIPART_OVERHEAD_BYTES
    declared = request.headers.get("content-length")
    if declared:
        try:
            if int(declared) > bound:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"File exceeds the per-file attachment limit "
                        f"of {file_limit_bytes} bytes"
                    ),
                )
        except ValueError:
            pass
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > bound:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"File exceeds the per-file attachment limit "
                    f"of {file_limit_bytes} bytes"
                ),
            )
        chunks.append(chunk)
    return b"".join(chunks)


class MeetingParticipantRequest(BaseModel):
    role_id: str
    model_config_id: str | None = None
    display_name: str | None = None
    instance_prompt: str | None = None


class CaseFileRequest(BaseModel):
    title: str
    content: str
    visible_roles: list[str]


class CreateMeetingRequest(BaseModel):
    title: str
    goal: str = ""
    mode_id: str = DEFAULT_MODE_ID
    participants: list[MeetingParticipantRequest] = Field(default_factory=list)
    inputs: dict[str, str] = Field(default_factory=dict)
    case_files: list[CaseFileRequest] = Field(default_factory=list)
    case_type: Literal["civil", "criminal"] | None = None

    @field_validator("title")
    @classmethod
    def require_non_blank_title(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @model_validator(mode="after")
    def normalize_goal(self) -> "CreateMeetingRequest":
        stripped = self.goal.strip()
        if self.mode_id != "chatroom" and not stripped:
            raise ValueError("goal must not be blank")
        self.goal = stripped
        return self


class UpdateMeetingDetailsRequest(BaseModel):
    title: str
    goal: str

    @field_validator("title", "goal")
    @classmethod
    def require_non_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class UpdateMeetingSettingsRequest(BaseModel):
    expected_revision: int = Field(ge=0)
    title: str
    goal: str
    case_type: Literal["civil", "criminal"] | None = None
    scene: Literal["meeting-room", "courtroom", "default-chamber"]
    participant_models: dict[str, str]

    # `goal` is deliberately absent here: chatroom meetings are created without one
    # (see CreateMeetingRequest.normalize_goal), so a blanket non-blank rule made every
    # chatroom settings save 422 and — because update_participant_models reuses this
    # model internally — every chatroom model switch a 500. Whether a blank goal is
    # acceptable depends on the meeting's mode, which this request cannot see, so the
    # check lives in the endpoint.
    @field_validator("title")
    @classmethod
    def require_non_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped

    @field_validator("goal")
    @classmethod
    def normalize_goal(cls, value: str) -> str:
        return value.strip()


class CourtroomIssueRequest(BaseModel):
    id: str | None = None
    title: str


class ReplaceCourtroomIssuesRequest(BaseModel):
    revision: int = Field(ge=0)
    issues: list[CourtroomIssueRequest]


class CourtroomRevisionRequest(BaseModel):
    revision: int = Field(ge=0)


class CourtroomCaseTypeRequest(BaseModel):
    case_type: Literal["civil", "criminal"]


class RestartDeliberationRequest(BaseModel):
    scope: Literal["current_issue", "all_deliberation", "rebuild_issues"]
    reason: str
    issue_id: str | None = None

    @field_validator("reason")
    @classmethod
    def require_restart_reason(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class CaseMaterialContentRequest(BaseModel):
    revision: int = Field(ge=0)
    title: str
    content: str
    visible_roles: list[str]


class CaseMaterialStatusRequest(BaseModel):
    revision: int = Field(ge=0)


class PromoteCaseNoteRequest(BaseModel):
    revision: int = Field(ge=0)
    title: str
    visible_roles: list[str]


class StartMeetingRequest(BaseModel):
    models: dict[str, str] = Field(default_factory=dict)


class DirectedRoleResponseRequest(BaseModel):
    instruction: str

    @field_validator("instruction")
    @classmethod
    def require_non_blank(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class RunRoleSequenceRequest(BaseModel):
    roles: list[str]
    models: dict[str, str] = Field(default_factory=dict)


class UpdateParticipantModelsRequest(BaseModel):
    models: dict[str, str]


class CorrectMeetingMessageRequest(BaseModel):
    content: str


class UpdateMeetingTagsRequest(BaseModel):
    tags: list[str]


class UpdateMeetingPinnedRequest(BaseModel):
    pinned: bool


class AddMeetingMessageRequest(BaseModel):
    content: str
    quoted_event_id: str | None = None


class ChatroomMentionTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token_id: StrictStr
    role_id: StrictStr
    display_text: StrictStr
    start: StrictInt
    end: StrictInt


class ChatroomSourceTokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    token_id: StrictStr
    source_ref: StrictStr
    display_text: StrictStr
    start: StrictInt
    end: StrictInt


class AddChatMentionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: StrictStr
    mentions: list[ChatroomMentionTokenRequest]
    source_tokens: list[ChatroomSourceTokenRequest]
    source_refs: list[StrictStr]
    quoted_event_id: StrictStr | None = None


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


class ModelDiscoveryPreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    adapter: str
    base_url: str | None = None
    api_key_env: str | None = None


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
    case_file_limits: CaseFileLimits | None = None,
    attachment_limits: AttachmentLimits | None = None,
) -> FastAPI:
    limits = case_file_limits or CaseFileLimits.from_environment()
    attachment_limits = attachment_limits or AttachmentLimits.from_environment()
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
        if request.method == "POST" and request.url.path.endswith("/chat/mention"):
            locations = [str(part) for part in exc.errors()[0].get("loc", []) if part != "body"]
            field = locations[0] if locations else None
            return JSONResponse(
                status_code=400,
                content=rejected("INVALID_REQUEST_SCHEMA", field),
            )
        if (
            request.method == "POST"
            and request.url.path in {"/models", "/models/available-models"}
        ) or (
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
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {key: value for key, value in error.items() if key != "ctx"}
                    for error in exc.errors()
                ]
            },
        )

    @app.exception_handler(HTTPException)
    async def chatroom_http_exception_handler(
        request: Request,
        exc: HTTPException,
    ) -> JSONResponse:
        if request.method == "POST" and request.url.path.endswith("/chat/mention"):
            if exc.status_code == 404:
                return JSONResponse(
                    status_code=404,
                    content=rejected("MEETING_NOT_FOUND", None),
                )
            if exc.status_code == 409:
                return JSONResponse(
                    status_code=409,
                    content=rejected("CHATROOM_NOT_ACCEPTING_INPUT", None),
                )
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    data_path = Path(data_dir)
    metadata_store = MeetingMetadataStore(data_path)
    repository = MeetingRepository(data_path)
    case_materials = CaseMaterials(repository)
    attachments = AttachmentStore(repository)
    courtroom_workflow = CourtroomWorkflowService(metadata_store, repository)
    execution_state_store = MeetingExecutionStateStore(data_path)
    model_repository = ModelConfigRepository(model_config_path)
    meeting_assignments = MeetingModelAssignments(
        metadata_store,
        repository,
        model_repository,
    )
    output_schemas = DEFAULT_OUTPUT_SCHEMA_REGISTRY
    mode_catalog = ModeCatalogRepository(
        modes_config_path,
        output_schemas=output_schemas,
    )
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
        output_schemas=output_schemas,
    )
    recover_interrupted_executions(repository, execution_state_store)
    projector = TranscriptProjector()
    jobs = MeetingJobManager()
    meeting_transitions = MeetingTransitionCoordinator()

    def reconcile_pending_restart(meeting_id: str, operation: str | None) -> None:
        metadata = metadata_store.get(meeting_id)
        pending_settings = metadata.get("pending_meeting_settings")
        if isinstance(pending_settings, dict):
            if operation in {
                "update_meeting_settings",
                "update_meeting_details",
                "update_courtroom_case_type",
            }:
                return
            event_ids = {
                str(event.get("event_id"))
                for event in repository.read_events(meeting_id)
            }
            required = {
                str(event.get("event_id"))
                for event in pending_settings.get("events", [])
                if isinstance(event, dict)
            }
            if not required.issubset(event_ids):
                raise HTTPException(
                    status_code=409,
                    detail="Meeting settings update must be retried before changing the meeting",
                )
            try:
                metadata_store.update(
                    meeting_id,
                    finalize_pending_meeting_settings,
                )
            except OSError as error:
                raise HTTPException(
                    status_code=409,
                    detail="Meeting settings metadata is pending recovery",
                ) from error
            metadata = metadata_store.get(meeting_id)
        pending = metadata.get("pending_deliberation_restart")
        if not isinstance(pending, dict) or operation in {
            "restart_deliberation",
            "update_courtroom_case_type",
        }:
            return
        marker = next(
            (
                event
                for event in reversed(repository.read_events(meeting_id))
                if event.get("interaction_type") == "deliberation-epoch-start"
                and event.get("epoch_id") == pending.get("epoch_id")
            ),
            None,
        )
        if marker is None:
            raise HTTPException(
                status_code=409,
                detail="Deliberation restart must be retried before changing the meeting",
            )

        try:
            metadata_store.update(
                meeting_id,
                lambda current: finalize_deliberation_restart_metadata(current, marker),
            )
        except OSError as error:
            raise HTTPException(
                status_code=409,
                detail="Deliberation restart metadata is pending recovery",
            ) from error

    meeting_transitions.set_before_transition(reconcile_pending_restart)
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
        check_token = model_health.begin(model_config_id)
        model = get_model(model_repository, model_config_id)
        result = check_model_health(model, model_adapters.get(model.adapter))
        model_health.record(model_config_id, result, check_token)
        response = {"status": result.status, "tested_at": result.checked_at}
        if result.error is not None:
            response["error"] = result.error
        return response

    @app.get("/models/{model_config_id}/available-models")
    def discover_available_models(model_config_id: str) -> dict[str, list[str]]:
        model = get_model(model_repository, model_config_id)
        adapter = model_adapters.get(model.adapter)
        discover_models = getattr(adapter, "discover_models", None)
        if not callable(discover_models):
            raise HTTPException(
                status_code=400,
                detail=f"Model discovery is not supported for adapter: {model.adapter}",
            )
        try:
            return {"models": discover_models(model)}
        except AdapterError as error:
            raise HTTPException(
                status_code=502,
                detail=model_discovery_error_detail(error, model),
            ) from error

    @app.post("/models/available-models")
    def preview_available_models(
        request: ModelDiscoveryPreviewRequest,
    ) -> dict[str, list[str]]:
        adapter = model_adapters.get(request.adapter)
        discover_models = getattr(adapter, "discover_models", None)
        if not callable(discover_models):
            raise HTTPException(
                status_code=400,
                detail=f"Model discovery is not supported for adapter: {request.adapter}",
            )
        model = ModelConfig(
            id="discovery-preview",
            adapter=request.adapter,
            base_url=request.base_url,
            api_key_env=request.api_key_env,
        )
        try:
            return {"models": discover_models(model)}
        except AdapterError as error:
            raise HTTPException(
                status_code=502,
                detail=model_discovery_error_detail(error, model),
            ) from error

    @app.get("/modes")
    def list_modes_catalog() -> list[dict[str, Any]]:
        try:
            modes = mode_catalog.list_modes()
        except ModeConfigError as error:
            raise HTTPException(status_code=500, detail=str(error)) from error
        return [project_mode(mode) for mode in modes]

    @app.get("/case-file-limits")
    def get_case_file_limits() -> dict[str, int]:
        return {
            "per_file_chars": limits.per_file_chars,
            "total_chars": limits.total_chars,
        }

    @app.post("/meetings")
    def create_meeting(request: CreateMeetingRequest) -> dict[str, Any]:
        mode = get_mode_or_400(mode_catalog, request.mode_id)
        if not mode.available:
            raise HTTPException(
                status_code=400,
                detail=f"Mode is not yet supported: {mode.id}",
            )
        if mode.id == "courtroom" and request.case_type is None:
            raise HTTPException(
                status_code=422,
                detail="Courtroom case type must be explicitly selected",
            )
        if mode.id != "courtroom" and request.case_type is not None:
            raise HTTPException(
                status_code=400,
                detail="Case type is only available for courtroom meetings",
            )
        participants = normalize_participants(mode, request.participants, model_repository)
        case_files = normalize_case_files(mode, participants, request.case_files, limits)

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
            "title": request.title,
            "goal": request.goal,
            "created_at": created_at,
            "tags": [],
            "pinned": False,
            "mode_id": mode.id,
            "participants": participants,
            "inputs": request.inputs,
            "settings_revision": 0,
            "scene": mode.default_scene,
        }
        if request.case_type is not None:
            metadata["case_type"] = request.case_type
        metadata_store.save(metadata)
        if case_files:
            repository.save_case_files(meeting_id, case_files)
        return {
            **project_meeting_summary(
                metadata,
                [],
                mode=mode,
                model_pricing={},
                meeting_assignments=meeting_assignments,
            ),
            "case_files": case_file_manifest(case_files, mode_id=mode.id),
            "materials_revision": 0,
        }

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
            material_summary = case_materials.summary(meeting_id)
            attachment_summary = attachments.summary(meeting_id)
            summaries.append(
                {
                    **project_meeting_summary(
                        metadata,
                        events,
                        mode=mode,
                        model_pricing=pricing,
                        meeting_assignments=meeting_assignments,
                        activity_status=live_activity_status(
                            DeliberationEpochs.view(events).active_events,
                            jobs.is_running(meeting_id),
                            mode,
                        ),
                    ),
                    "case_materials_summary": {
                        "revision": material_summary.revision,
                        "active_evidence_count": material_summary.active_evidence_count,
                        "active_note_count": material_summary.active_note_count,
                        "pending_impact": (
                            None
                            if mode.category == "chatroom"
                            else material_summary.pending_impact
                        ),
                    },
                    "attachments_summary": {
                        "count": attachment_summary.count,
                        "total_bytes": attachment_summary.total_bytes,
                    },
                    "materials_revision": material_summary.revision,
                }
            )
        return summaries

    @app.get("/meetings/{meeting_id}")
    def get_meeting(meeting_id: str) -> dict[str, Any]:
        metadata = metadata_store.get(meeting_id)
        mode = meeting_mode(mode_catalog, metadata)
        all_events, activity_status = live_meeting_snapshot(
            repository,
            jobs,
            meeting_id,
            mode,
        )
        deliberation = DeliberationEpochs.view(all_events)
        events = deliberation.active_events
        workflow_events = deliberation.workflow_events
        material_view = case_materials.view(meeting_id)
        attachment_summary = attachments.summary(meeting_id)
        return {
            **project_meeting_summary(
                metadata,
                all_events,
                mode=mode,
                model_pricing=model_pricing_by_id(model_repository),
                meeting_assignments=meeting_assignments,
                activity_status=activity_status,
                live_events=events,
                workflow_events=workflow_events,
            ),
            "events": project_events(
                events,
                removed_attachment_ids=attachments.removed_file_ids(meeting_id),
            ),
            "case_files": active_case_evidence_projection(
                material_view, mode_id=metadata.get("mode_id")
            ),
            "case_materials": project_case_materials(
                material_view,
                active_epoch_id=deliberation.active_epoch.id,
                mode_id=metadata.get("mode_id"),
                category=mode.category,
            ),
            "attachments_summary": {
                "count": attachment_summary.count,
                "total_bytes": attachment_summary.total_bytes,
            },
        }

    def validate_material_roles(
        metadata: dict[str, Any], visible_roles: list[str]
    ) -> None:
        mode = meeting_mode(mode_catalog, metadata)
        allowed = {
            str(participant["role_id"])
            for participant in project_participants(mode, metadata)
        }
        requested = [role.strip() for role in visible_roles if role.strip()]
        if not requested:
            raise HTTPException(
                status_code=400,
                detail="Material requires at least one visible role",
            )
        unknown = sorted(set(requested) - allowed)
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown material visible role: {', '.join(unknown)}",
            )

    def material_change_impact(meeting_id: str) -> dict[str, Any] | None:
        deliberation = DeliberationEpochs.view(repository.read_events(meeting_id))
        has_ai_output = any(
            event.get("role") not in {"Human", "System"}
            and event.get("status") == "completed"
            for event in deliberation.workflow_events
        )
        if not has_ai_output:
            return None
        return {
            "deliberation_epoch_id": deliberation.active_epoch.id,
            "reason": "prompt_material_changed_after_ai_output",
        }

    def versioned_limits() -> VersionedCaseMaterialLimits:
        return VersionedCaseMaterialLimits(
            per_item_chars=limits.per_file_chars,
            total_chars=limits.total_chars,
        )

    def perform_material_mutation(
        meeting_id: str,
        operation: Callable[[dict[str, Any], dict[str, Any] | None], CaseMaterialsView],
    ) -> dict[str, Any]:
        reject_running_meeting(jobs, meeting_id)
        metadata = metadata_store.get(meeting_id)
        try:
            impact = (
                None
                if meeting_mode(mode_catalog, metadata).category == "chatroom"
                else material_change_impact(meeting_id)
            )
            view = operation(metadata, impact)
        except CaseMaterialConflict as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except CaseMaterialValidationError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        active_epoch_id = DeliberationEpochs.view(
            repository.read_events(meeting_id)
        ).active_epoch.id
        return project_case_materials(
            view,
            active_epoch_id=active_epoch_id,
            mode_id=metadata.get("mode_id"),
            category=meeting_mode(mode_catalog, metadata).category,
        )

    @app.get("/meetings/{meeting_id}/materials")
    def get_case_materials(
        meeting_id: str, revision: int | None = None
    ) -> dict[str, Any]:
        metadata = metadata_store.get(meeting_id)
        active_epoch_id = DeliberationEpochs.view(
            repository.read_events(meeting_id)
        ).active_epoch.id
        try:
            view = (
                case_materials.view(meeting_id)
                if revision is None
                else case_materials.view_at_revision(meeting_id, revision)
            )
        except CaseMaterialValidationError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return project_case_materials(
            view,
            active_epoch_id=active_epoch_id,
            mode_id=metadata.get("mode_id"),
            category=meeting_mode(mode_catalog, metadata).category,
        )

    @app.post("/meetings/{meeting_id}/materials/evidence")
    @meeting_transitions.synchronized
    def add_case_evidence(
        meeting_id: str, request: CaseMaterialContentRequest
    ) -> dict[str, Any]:
        def operation(metadata: dict[str, Any], impact: dict[str, Any] | None) -> CaseMaterialsView:
            validate_material_roles(metadata, request.visible_roles)
            return case_materials.add_evidence(
                meeting_id,
                expected_revision=request.revision,
                title=request.title,
                content=request.content,
                visible_roles=request.visible_roles,
                limits=versioned_limits(),
                impact=impact,
            )

        return perform_material_mutation(meeting_id, operation)

    @app.post("/meetings/{meeting_id}/materials/evidence/{evidence_id}/versions")
    @meeting_transitions.synchronized
    def add_case_evidence_version(
        meeting_id: str,
        evidence_id: str,
        request: CaseMaterialContentRequest,
    ) -> dict[str, Any]:
        def operation(metadata: dict[str, Any], impact: dict[str, Any] | None) -> CaseMaterialsView:
            validate_material_roles(metadata, request.visible_roles)
            return case_materials.add_evidence_version(
                meeting_id,
                evidence_id,
                expected_revision=request.revision,
                title=request.title,
                content=request.content,
                visible_roles=request.visible_roles,
                limits=versioned_limits(),
                impact=impact,
            )

        return perform_material_mutation(meeting_id, operation)

    def set_case_evidence_status(
        meeting_id: str,
        evidence_id: str,
        request: CaseMaterialStatusRequest,
        *,
        active: bool,
    ) -> dict[str, Any]:
        return perform_material_mutation(
            meeting_id,
            lambda _metadata, impact: case_materials.set_evidence_active(
                meeting_id,
                evidence_id,
                active=active,
                expected_revision=request.revision,
                limits=versioned_limits(),
                impact=impact,
            ),
        )

    @app.post("/meetings/{meeting_id}/materials/evidence/{evidence_id}/deactivate")
    @meeting_transitions.synchronized
    def deactivate_case_evidence(
        meeting_id: str, evidence_id: str, request: CaseMaterialStatusRequest
    ) -> dict[str, Any]:
        return set_case_evidence_status(
            meeting_id, evidence_id, request, active=False
        )

    @app.post("/meetings/{meeting_id}/materials/evidence/{evidence_id}/reactivate")
    @meeting_transitions.synchronized
    def reactivate_case_evidence(
        meeting_id: str, evidence_id: str, request: CaseMaterialStatusRequest
    ) -> dict[str, Any]:
        return set_case_evidence_status(
            meeting_id, evidence_id, request, active=True
        )

    @app.post("/meetings/{meeting_id}/materials/notes")
    @meeting_transitions.synchronized
    def add_case_note(
        meeting_id: str, request: CaseMaterialContentRequest
    ) -> dict[str, Any]:
        def operation(metadata: dict[str, Any], impact: dict[str, Any] | None) -> CaseMaterialsView:
            validate_material_roles(metadata, request.visible_roles)
            return case_materials.add_note(
                meeting_id,
                expected_revision=request.revision,
                title=request.title,
                content=request.content,
                visible_roles=request.visible_roles,
                limits=versioned_limits(),
                impact=impact,
            )

        return perform_material_mutation(meeting_id, operation)

    @app.post("/meetings/{meeting_id}/materials/notes/{note_id}/versions")
    @meeting_transitions.synchronized
    def add_case_note_version(
        meeting_id: str,
        note_id: str,
        request: CaseMaterialContentRequest,
    ) -> dict[str, Any]:
        def operation(metadata: dict[str, Any], impact: dict[str, Any] | None) -> CaseMaterialsView:
            validate_material_roles(metadata, request.visible_roles)
            return case_materials.add_note_version(
                meeting_id,
                note_id,
                expected_revision=request.revision,
                title=request.title,
                content=request.content,
                visible_roles=request.visible_roles,
                limits=versioned_limits(),
                impact=impact,
            )

        return perform_material_mutation(meeting_id, operation)

    def set_case_note_status(
        meeting_id: str,
        note_id: str,
        request: CaseMaterialStatusRequest,
        *,
        active: bool,
    ) -> dict[str, Any]:
        return perform_material_mutation(
            meeting_id,
            lambda _metadata, impact: case_materials.set_note_active(
                meeting_id,
                note_id,
                active=active,
                expected_revision=request.revision,
                limits=versioned_limits(),
                impact=impact,
            ),
        )

    @app.post("/meetings/{meeting_id}/materials/notes/{note_id}/deactivate")
    @meeting_transitions.synchronized
    def deactivate_case_note(
        meeting_id: str, note_id: str, request: CaseMaterialStatusRequest
    ) -> dict[str, Any]:
        return set_case_note_status(meeting_id, note_id, request, active=False)

    @app.post("/meetings/{meeting_id}/materials/notes/{note_id}/reactivate")
    @meeting_transitions.synchronized
    def reactivate_case_note(
        meeting_id: str, note_id: str, request: CaseMaterialStatusRequest
    ) -> dict[str, Any]:
        return set_case_note_status(meeting_id, note_id, request, active=True)

    @app.post("/meetings/{meeting_id}/messages/{event_id}/promote-to-note")
    @meeting_transitions.synchronized
    def promote_message_to_case_note(
        meeting_id: str,
        event_id: str,
        request: PromoteCaseNoteRequest,
    ) -> dict[str, Any]:
        metadata = metadata_store.get(meeting_id)
        validate_material_roles(metadata, request.visible_roles)
        source = next(
            (
                event
                for event in active_meeting_events(repository, meeting_id)
                if event.get("event_id") == event_id
            ),
            None,
        )
        if (
            source is None
            or source.get("role") != "Human"
            or source.get("status") != "completed"
            or not str(source.get("content", "")).strip()
        ):
            raise HTTPException(
                status_code=400,
                detail="Only an active completed chairman message can become a case note",
            )
        return perform_material_mutation(
            meeting_id,
            lambda _metadata, impact: case_materials.add_note(
                meeting_id,
                expected_revision=request.revision,
                title=request.title,
                content=str(source["content"]),
                visible_roles=request.visible_roles,
                source_event_id=event_id,
                limits=versioned_limits(),
                impact=impact,
            ),
        )

    @app.get("/meetings/{meeting_id}/deliberations")
    def get_deliberations(meeting_id: str) -> dict[str, Any]:
        metadata_store.get(meeting_id)
        view = DeliberationEpochs.view(repository.read_events(meeting_id))
        return {
            "active_epoch_id": view.active_epoch.id,
            "active_epoch_number": view.active_epoch.number,
            "epochs": [
                {
                    "id": epoch.id,
                    "number": epoch.number,
                    "reason": epoch.reason,
                    "scope": epoch.scope,
                    "issue_id": epoch.issue_id,
                    "implicit": epoch.implicit,
                    "event_count": len(epoch.events),
                    "materials_revision": epoch_materials_revision(epoch),
                }
                for epoch in view.epochs
            ],
        }

    @app.post("/meetings/{meeting_id}/deliberations/restart")
    @meeting_transitions.synchronized
    def restart_deliberation(
        meeting_id: str,
        request: RestartDeliberationRequest,
    ) -> dict[str, Any]:
        reject_running_meeting(jobs, meeting_id)
        metadata = metadata_store.get(meeting_id)
        pending_restart = metadata.get("pending_deliberation_restart")
        if isinstance(pending_restart, dict):
            raw_events = repository.read_events(meeting_id)
            completed_marker = next(
                (
                    event
                    for event in reversed(raw_events)
                    if event.get("interaction_type") == "deliberation-epoch-start"
                    and event.get("epoch_id") == pending_restart.get("epoch_id")
                ),
                None,
            )
            if completed_marker is not None:
                metadata_store.update(
                    meeting_id,
                    lambda current: finalize_deliberation_restart_metadata(
                        current, completed_marker
                    ),
                )
                return get_meeting(meeting_id)
            metadata = metadata_store.update(
                meeting_id,
                lambda current: {
                    key: value
                    for key, value in current.items()
                    if key != "pending_deliberation_restart"
                },
            )
        lifecycle = latest_lifecycle_status(repository.read_events(meeting_id))
        if lifecycle in {"closed", "cancelled"}:
            raise HTTPException(
                status_code=409,
                detail="Reopen the terminal meeting before restarting deliberation",
            )
        mode = meeting_mode(mode_catalog, metadata)
        try:
            command = RestartCommand(
                scope=request.scope,
                reason=request.reason,
                issue_id=request.issue_id,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        all_events = repository.read_events(meeting_id)
        deliberation = DeliberationEpochs.view(all_events)
        if mode.id != "courtroom" and command.scope != "all_deliberation":
            raise HTTPException(
                status_code=400,
                detail="This restart scope is only available for courtroom meetings",
            )
        if mode.id == "courtroom" and command.scope == "current_issue":
            docket = metadata.get("courtroom_docket")
            known_issue_ids = {
                str(issue.get("id"))
                for issue in (docket or {}).get("issues", [])
                if isinstance(issue, dict)
            }
            if not isinstance(docket, dict) or not docket.get("confirmed"):
                raise HTTPException(status_code=409, detail="Courtroom issues must be confirmed")
            if command.issue_id not in known_issue_ids:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown courtroom issue: {command.issue_id}",
                )
            courtroom = project_courtroom(
                metadata, deliberation.workflow_events
            )
            active_issue_id = courtroom.get("current_issue_id") if courtroom else None
            if active_issue_id is not None and command.issue_id != active_issue_id:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Restart target must match the active courtroom issue: "
                        f"{active_issue_id}"
                    ),
                )
        snapshot = {
            "goal": metadata.get("goal"),
            "mode_id": mode.id,
            "participants": metadata.get("participants") or [],
            "courtroom_docket": metadata.get("courtroom_docket"),
            "materials_revision": case_materials.view(meeting_id).revision,
        }
        marker = DeliberationEpochs.restart_marker(
            meeting_id=meeting_id,
            events=all_events,
            command=command,
            snapshot=snapshot,
        )
        pending = {
            "epoch_id": marker["epoch_id"],
            "scope": command.scope,
            "reason": command.reason,
        }
        metadata_store.update(
            meeting_id,
            lambda current: {**current, "pending_deliberation_restart": pending},
        )
        repository.append_event(meeting_id, marker)

        metadata_store.update(
            meeting_id,
            lambda current: finalize_deliberation_restart_metadata(current, marker),
        )
        return get_meeting(meeting_id)

    @app.put("/meetings/{meeting_id}/courtroom/case-type")
    @meeting_transitions.synchronized
    def update_courtroom_case_type(
        meeting_id: str,
        request: CourtroomCaseTypeRequest,
    ) -> dict[str, Any]:
        reject_running_meeting(jobs, meeting_id)
        reject_terminal_meeting(repository, meeting_id)
        metadata = metadata_store.get(meeting_id)
        if metadata.get("mode_id") != "courtroom":
            raise HTTPException(
                status_code=400,
                detail="Case type is only available for courtroom meetings",
            )
        mode = meeting_mode(mode_catalog, metadata)
        participants = meeting_assignments.project(
            metadata,
            project_participants(mode, metadata),
        )
        return update_meeting_settings(
            meeting_id,
            UpdateMeetingSettingsRequest(
                expected_revision=int(metadata.get("settings_revision", 0)),
                title=meeting_title(metadata),
                goal=str(metadata.get("goal") or ""),
                case_type=request.case_type,
                scene=metadata.get("scene", mode.default_scene),
                participant_models={
                    str(item["role_id"]): str(item["model_config_id"])
                    for item in participants
                },
            ),
        )

    @app.put("/meetings/{meeting_id}/courtroom/issues")
    @meeting_transitions.synchronized
    def replace_courtroom_issues(
        meeting_id: str,
        request: ReplaceCourtroomIssuesRequest,
    ) -> dict[str, Any]:
        reject_running_meeting(jobs, meeting_id)
        reject_terminal_meeting(repository, meeting_id)
        try:
            metadata = courtroom_workflow.replace_issues(
                meeting_id,
                expected_revision=request.revision,
                requested_issues=[issue.model_dump() for issue in request.issues],
            )
        except CourtroomWorkflowError as error:
            raise HTTPException(status_code=error.status_code, detail=error.detail) from error
        return project_meeting_summary(
            metadata,
            repository.read_events(meeting_id),
            mode=meeting_mode(mode_catalog, metadata),
            model_pricing=model_pricing_by_id(model_repository),
            meeting_assignments=meeting_assignments,
        )

    @app.post("/meetings/{meeting_id}/courtroom/issues/confirm")
    @meeting_transitions.synchronized
    def confirm_courtroom_issues(
        meeting_id: str,
        request: CourtroomRevisionRequest,
    ) -> dict[str, Any]:
        reject_running_meeting(jobs, meeting_id)
        reject_terminal_meeting(repository, meeting_id)
        try:
            metadata = courtroom_workflow.confirm_issues(
                meeting_id,
                expected_revision=request.revision,
            )
        except CourtroomWorkflowError as error:
            raise HTTPException(status_code=error.status_code, detail=error.detail) from error
        return project_meeting_summary(
            metadata,
            repository.read_events(meeting_id),
            mode=meeting_mode(mode_catalog, metadata),
            model_pricing=model_pricing_by_id(model_repository),
            meeting_assignments=meeting_assignments,
        )

    @app.post("/meetings/{meeting_id}/courtroom/issues/draft", status_code=202)
    @meeting_transitions.synchronized
    def draft_courtroom_issues(
        meeting_id: str,
        request: CourtroomRevisionRequest,
    ) -> dict[str, str]:
        metadata, mode, models, inputs = courtroom_operation_context(
            meeting_id,
            metadata_store=metadata_store,
            repository=repository,
            case_materials=case_materials,
            mode_catalog=mode_catalog,
            meeting_assignments=meeting_assignments,
        )
        try:
            courtroom_workflow.validate_draft(metadata, request.revision)
        except CourtroomWorkflowError as error:
            raise HTTPException(status_code=error.status_code, detail=error.detail) from error
        if not jobs.start(
            meeting_id,
            lambda: courtroom_workflow.generate_draft(
                meeting_id,
                expected_revision=request.revision,
                goal=str(metadata["goal"]),
                model_assignments=models,
                inputs=inputs,
                runner=runner,
            ),
        ):
            raise HTTPException(status_code=409, detail="Meeting is already running")
        return {"status": "running"}

    @app.post(
        "/meetings/{meeting_id}/courtroom/issues/{issue_id}/arguments",
        status_code=202,
    )
    @meeting_transitions.synchronized
    def run_courtroom_issue_arguments(meeting_id: str, issue_id: str) -> dict[str, str]:
        metadata, mode, models, inputs = courtroom_operation_context(
            meeting_id,
            metadata_store=metadata_store,
            repository=repository,
            case_materials=case_materials,
            mode_catalog=mode_catalog,
            meeting_assignments=meeting_assignments,
        )
        try:
            courtroom_workflow.validate_arguments(
                metadata, workflow_meeting_events(repository, meeting_id), issue_id
            )
        except CourtroomWorkflowError as error:
            raise HTTPException(status_code=error.status_code, detail=error.detail) from error
        if not jobs.start(
            meeting_id,
            lambda: courtroom_workflow.run_arguments(
                meeting_id,
                issue_id=issue_id,
                goal=str(metadata["goal"]),
                model_assignments=models,
                inputs=inputs,
                runner=runner,
            ),
        ):
            raise HTTPException(status_code=409, detail="Meeting is already running")
        return {"status": "running"}

    @app.post(
        "/meetings/{meeting_id}/courtroom/issues/{issue_id}/ruling",
        status_code=202,
    )
    @meeting_transitions.synchronized
    def run_courtroom_issue_ruling(meeting_id: str, issue_id: str) -> dict[str, str]:
        metadata, mode, models, inputs = courtroom_operation_context(
            meeting_id,
            metadata_store=metadata_store,
            repository=repository,
            case_materials=case_materials,
            mode_catalog=mode_catalog,
            meeting_assignments=meeting_assignments,
        )
        try:
            courtroom_workflow.validate_ruling(
                metadata, workflow_meeting_events(repository, meeting_id), issue_id
            )
        except CourtroomWorkflowError as error:
            raise HTTPException(status_code=error.status_code, detail=error.detail) from error
        if not jobs.start(
            meeting_id,
            lambda: courtroom_workflow.run_ruling(
                meeting_id,
                issue_id=issue_id,
                goal=str(metadata["goal"]),
                model_assignments=models,
                inputs=inputs,
                runner=runner,
            ),
        ):
            raise HTTPException(status_code=409, detail="Meeting is already running")
        return {"status": "running"}

    @app.post("/meetings/{meeting_id}/courtroom/final-verdict", status_code=202)
    @meeting_transitions.synchronized
    def run_courtroom_final_verdict(meeting_id: str) -> dict[str, str]:
        metadata, mode, models, inputs = courtroom_operation_context(
            meeting_id,
            metadata_store=metadata_store,
            repository=repository,
            case_materials=case_materials,
            mode_catalog=mode_catalog,
            meeting_assignments=meeting_assignments,
        )
        try:
            courtroom_workflow.validate_final(
                metadata, workflow_meeting_events(repository, meeting_id)
            )
        except CourtroomWorkflowError as error:
            raise HTTPException(status_code=error.status_code, detail=error.detail) from error
        if not jobs.start(
            meeting_id,
            lambda: courtroom_workflow.run_final_verdict(
                meeting_id,
                goal=str(metadata["goal"]),
                model_assignments=models,
                inputs=inputs,
                runner=runner,
            ),
        ):
            raise HTTPException(status_code=409, detail="Meeting is already running")
        return {"status": "running"}

    @app.put("/meetings/{meeting_id}/details")
    @meeting_transitions.synchronized
    def update_meeting_details(
        meeting_id: str,
        request: UpdateMeetingDetailsRequest,
    ) -> dict[str, Any]:
        reject_running_meeting(jobs, meeting_id)
        current_metadata = metadata_store.get(meeting_id)
        mode = meeting_mode(mode_catalog, current_metadata)
        participants = meeting_assignments.project(
            current_metadata,
            project_participants(mode, current_metadata),
        )
        return update_meeting_settings(
            meeting_id,
            UpdateMeetingSettingsRequest(
                expected_revision=int(current_metadata.get("settings_revision", 0)),
                title=request.title,
                goal=request.goal,
                case_type=current_metadata.get("case_type"),
                scene=current_metadata.get("scene", mode.default_scene),
                participant_models={
                    str(item["role_id"]): str(item["model_config_id"])
                    for item in participants
                },
            ),
        )

    @app.put("/meetings/{meeting_id}/settings")
    @meeting_transitions.synchronized
    def update_meeting_settings(
        meeting_id: str,
        request: UpdateMeetingSettingsRequest,
    ) -> dict[str, Any]:
        """Replace meeting settings through a recoverable metadata/event commit."""
        reject_running_meeting(jobs, meeting_id)
        current = metadata_store.get(meeting_id)
        # Mirrors CreateMeetingRequest.normalize_goal: every mode but chatroom requires a
        # goal. Enforced here rather than on the request model because only the stored
        # metadata knows the mode.
        if str(current.get("mode_id") or DEFAULT_MODE_ID) != "chatroom" and not request.goal:
            raise HTTPException(
                status_code=422,
                detail="Meeting goal must not be blank",
            )
        pending = current.get("pending_meeting_settings")
        recovered_pending = False
        if isinstance(pending, dict):
            target = pending.get("target")
            requested_target = {
                "title": request.title,
                "goal": request.goal,
                "scene": request.scene,
                "case_type": request.case_type,
                "settings_revision": request.expected_revision + 1,
            }
            pending_models = {
                str(item.get("role_id")): item.get("model_config_id")
                for item in (target or {}).get("participants", [])
                if isinstance(item, dict)
            }
            if not isinstance(target, dict) or any(
                target.get(key) != value for key, value in requested_target.items()
            ) or pending_models != request.participant_models:
                raise HTTPException(
                    status_code=409,
                    detail="Retry the same pending meeting settings update",
                )
            existing_event_ids = {
                str(event.get("event_id"))
                for event in repository.read_events(meeting_id)
            }
            try:
                for event in pending.get("events", []):
                    if (
                        isinstance(event, dict)
                        and str(event.get("event_id")) not in existing_event_ids
                    ):
                        repository.append_event(meeting_id, event)
                current = metadata_store.update(
                    meeting_id, finalize_pending_meeting_settings
                )
                recovered_pending = True
            except OSError as error:
                raise HTTPException(
                    status_code=409,
                    detail="Meeting settings update is pending recovery; retry the same save",
                ) from error

        mode = meeting_mode(mode_catalog, current)
        if recovered_pending:
            recovered_events = repository.read_events(meeting_id)
            return project_meeting_summary(
                current,
                recovered_events,
                mode=mode,
                model_pricing=model_pricing_by_id(model_repository),
                meeting_assignments=meeting_assignments,
                activity_status=live_activity_status(
                    DeliberationEpochs.view(recovered_events).active_events,
                    jobs.is_running(meeting_id),
                    mode,
                ),
            )
        role_ids = [
            str(participant["role_id"])
            for participant in project_participants(mode, current)
        ]
        requested_roles = set(request.participant_models)
        expected_roles = set(role_ids)
        if requested_roles != expected_roles:
            missing = sorted(expected_roles - requested_roles)
            extra = sorted(requested_roles - expected_roles)
            details = []
            if missing:
                details.append(f"missing roles: {', '.join(missing)}")
            if extra:
                details.append(f"unknown roles: {', '.join(extra)}")
            raise HTTPException(
                status_code=400,
                detail="Participant model roster mismatch; " + "; ".join(details),
            )
        known_models = {model.id for model in model_repository.list_models()}
        unknown_models = sorted(set(request.participant_models.values()) - known_models)
        if unknown_models:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown model: {unknown_models[0]}",
            )
        if mode.id == "courtroom" and request.case_type is None:
            raise HTTPException(
                status_code=400,
                detail="Courtroom case type must be explicitly selected",
            )
        if mode.id != "courtroom" and request.case_type is not None:
            raise HTTPException(
                status_code=400,
                detail="Case type is only available for courtroom meetings",
            )
        docket = current.get("courtroom_docket")
        confirmed = isinstance(docket, dict) and bool(docket.get("confirmed"))
        if confirmed and request.goal != current.get("goal"):
            raise HTTPException(
                status_code=409,
                detail="Courtroom goal is read-only after issues are confirmed",
            )
        if (
            confirmed
            and current.get("case_type") is not None
            and request.case_type != current.get("case_type")
        ):
            raise HTTPException(
                status_code=409,
                detail="Confirmed courtroom case type is read-only",
            )

        revision = int(current.get("settings_revision", 0))
        if revision != request.expected_revision:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Stale meeting settings revision: "
                    f"expected {revision}, got {request.expected_revision}"
                ),
            )
        stored = {
            str(item.get("role_id")): item
            for item in (current.get("participants") or [])
            if isinstance(item, dict)
        }
        target: dict[str, Any] = {
            "title": request.title,
            "goal": request.goal,
            "scene": request.scene,
            "participants": [
                {
                    **stored.get(role_id, {"role_id": role_id}),
                    "model_config_id": request.participant_models[role_id],
                }
                for role_id in role_ids
            ],
            "settings_revision": revision + 1,
        }
        remove = ["topic"]
        if mode.id == "courtroom":
            target["case_type"] = request.case_type
        else:
            remove.append("case_type")

        events_to_append: list[dict[str, Any]] = []
        all_events = repository.read_events(meeting_id)
        case_type_changed = (
            mode.id == "courtroom"
            and not confirmed
            and current.get("case_type") != request.case_type
        )
        if case_type_changed and DeliberationEpochs.view(all_events).active_events:
            marker = DeliberationEpochs.restart_marker(
                meeting_id=meeting_id,
                events=all_events,
                command=RestartCommand(
                    scope="all_deliberation",
                    reason="case_type_changed",
                ),
                snapshot={
                    "goal": current.get("goal"),
                    "courtroom_docket": current.get("courtroom_docket"),
                    "models": current.get("participants") or [],
                    "materials_revision": case_materials.view(meeting_id).revision,
                    "from_case_type": current.get("case_type"),
                    "to_case_type": request.case_type,
                },
            )
            events_to_append.append(marker)
            target["deliberation_epoch_id"] = marker["epoch_id"]
            target["deliberation_epoch_number"] = marker["epoch_number"]
            remove.append("courtroom_docket")
        elif case_type_changed and isinstance(current.get("courtroom_docket"), dict):
            remove.append("courtroom_docket")

        if request.goal != current.get("goal") and any(
            event.get("role") not in {"Human", "System"}
            and event.get("status") == "completed"
            for event in DeliberationEpochs.view(all_events).active_events
        ):
            events_to_append.append(
                {
                    "event_id": f"{meeting_id}:goal-changed:{uuid.uuid4().hex}",
                    "meeting_id": meeting_id,
                    "step_id": "meeting-goal-changed",
                    "role": "Human",
                    "attempt": 1,
                    "status": "completed",
                    "interaction_type": "meeting-goal-changed",
                    "previous_goal": current.get("goal"),
                    "goal": request.goal,
                    "content": (
                        "主席修改會議目標\n"
                        f"舊目標：{current.get('goal')}\n"
                        f"新目標：{request.goal}"
                    ),
                }
            )
        if events_to_append:
            pending_update = {
                "target": target,
                "remove": remove,
                "events": events_to_append,
            }
            try:
                metadata_store.update(
                    meeting_id,
                    lambda metadata: {
                        **metadata,
                        "pending_meeting_settings": pending_update,
                    },
                )
                for event in events_to_append:
                    repository.append_event(meeting_id, event)
                metadata = metadata_store.update(
                    meeting_id, finalize_pending_meeting_settings
                )
            except OSError as error:
                raise HTTPException(
                    status_code=409,
                    detail="Meeting settings update is pending recovery; retry the same save",
                ) from error
        else:
            metadata = metadata_store.update(
                meeting_id,
                lambda existing: finalize_pending_meeting_settings(
                    {
                        **existing,
                        "pending_meeting_settings": {
                            "target": target,
                            "remove": remove,
                            "events": [],
                        },
                    }
                ),
            )
        events = repository.read_events(meeting_id)
        return project_meeting_summary(
            metadata,
            events,
            mode=mode,
            model_pricing=model_pricing_by_id(model_repository),
            meeting_assignments=meeting_assignments,
            activity_status=live_activity_status(
                DeliberationEpochs.view(events).active_events,
                jobs.is_running(meeting_id),
                mode,
            ),
        )

    @app.put("/meetings/{meeting_id}/tags")
    @meeting_transitions.synchronized
    def update_meeting_tags(meeting_id: str, request: UpdateMeetingTagsRequest) -> dict[str, Any]:
        reject_running_meeting(jobs, meeting_id)
        metadata = metadata_store.update(
            meeting_id,
            lambda current: {**current, "tags": request.tags},
        )
        events = repository.read_events(meeting_id)
        return project_meeting_summary(
            metadata,
            events,
            mode=meeting_mode(mode_catalog, metadata),
            model_pricing=model_pricing_by_id(model_repository),
            meeting_assignments=meeting_assignments,
            activity_status=live_activity_status(
                DeliberationEpochs.view(events).active_events,
                jobs.is_running(meeting_id),
                meeting_mode(mode_catalog, metadata),
            ),
        )

    @app.put("/meetings/{meeting_id}/pinned")
    @meeting_transitions.synchronized
    def update_meeting_pinned(
        meeting_id: str,
        request: UpdateMeetingPinnedRequest,
    ) -> dict[str, Any]:
        reject_running_meeting(jobs, meeting_id)
        metadata = metadata_store.update(
            meeting_id,
            lambda current: {**current, "pinned": request.pinned},
        )
        events = repository.read_events(meeting_id)
        return project_meeting_summary(
            metadata,
            events,
            mode=meeting_mode(mode_catalog, metadata),
            model_pricing=model_pricing_by_id(model_repository),
            meeting_assignments=meeting_assignments,
            activity_status=live_activity_status(
                DeliberationEpochs.view(events).active_events,
                jobs.is_running(meeting_id),
                meeting_mode(mode_catalog, metadata),
            ),
        )

    @app.put("/meetings/{meeting_id}/participant-models")
    @meeting_transitions.synchronized
    def update_participant_models(
        meeting_id: str,
        request: UpdateParticipantModelsRequest,
    ) -> dict[str, Any]:
        reject_running_meeting(jobs, meeting_id)
        metadata = metadata_store.get(meeting_id)
        mode = meeting_mode(mode_catalog, metadata)
        role_ids = [
            str(participant["role_id"])
            for participant in project_participants(mode, metadata)
        ]
        expected_roles = set(role_ids)
        requested_roles = set(request.models)
        if requested_roles != expected_roles:
            missing = sorted(expected_roles - requested_roles)
            extra = sorted(requested_roles - expected_roles)
            details = []
            if missing:
                details.append(f"missing roles: {', '.join(missing)}")
            if extra:
                details.append(f"unknown roles: {', '.join(extra)}")
            raise HTTPException(
                status_code=400,
                detail="Participant model roster mismatch; " + "; ".join(details),
            )
        known_models = {model.id for model in model_repository.list_models()}
        unknown_models = sorted(set(request.models.values()) - known_models)
        if unknown_models:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown model: {unknown_models[0]}",
            )
        return update_meeting_settings(
            meeting_id,
            UpdateMeetingSettingsRequest(
                expected_revision=int(metadata.get("settings_revision", 0)),
                title=meeting_title(metadata),
                goal=str(metadata.get("goal") or ""),
                case_type=metadata.get("case_type"),
                scene=metadata.get("scene", mode.default_scene),
                participant_models=request.models,
            ),
        )

    @app.post("/meetings/{meeting_id}/start", status_code=202)
    @meeting_transitions.synchronized
    def start_meeting(meeting_id: str, request: StartMeetingRequest) -> dict[str, str]:
        metadata = metadata_store.get(meeting_id)
        require_meeting_goal(metadata)
        reject_terminal_meeting(repository, meeting_id)
        material_view = require_case_materials_ready(
            repository, case_materials, meeting_id
        )
        mode = meeting_mode(mode_catalog, metadata)
        if mode.id == "courtroom":
            try:
                CourtroomCaseProfile.for_metadata(metadata)
            except CourtroomCaseProfileError as error:
                raise HTTPException(status_code=409, detail=str(error)) from error
            raise HTTPException(
                status_code=409,
                detail="Use the courtroom issue workflow to start arguments",
            )
        model_assignments = resolved_meeting_models(
            meeting_assignments,
            metadata,
            mode,
        )
        if not jobs.start(
            meeting_id,
            lambda: start_runner_for_mode(
                runner=runner,
                mode=mode,
                metadata=metadata,
                model_assignments=model_assignments,
                inputs=material_inputs_for_runner(metadata, material_view),
            ),
        ):
            raise HTTPException(status_code=409, detail="Meeting is already running")
        return {"status": "running"}

    @app.post("/meetings/{meeting_id}/cancel")
    @meeting_transitions.synchronized
    def cancel_meeting(meeting_id: str) -> dict[str, str]:
        metadata_store.get(meeting_id)
        runner.cancel(meeting_id)
        return {"status": "cancelled"}

    @app.post("/meetings/{meeting_id}/close")
    @meeting_transitions.synchronized
    def close_meeting(meeting_id: str) -> dict[str, str]:
        metadata_store.get(meeting_id)
        runner.close(meeting_id)
        return {"status": "closed"}

    @app.post("/meetings/{meeting_id}/reopen")
    @meeting_transitions.synchronized
    def reopen_meeting(meeting_id: str) -> dict[str, str]:
        metadata_store.get(meeting_id)
        if jobs.is_running(meeting_id):
            raise HTTPException(
                status_code=409,
                detail="Meeting is still finishing its background job",
            )
        event = {
            "event_id": f"{meeting_id}:reopened:{uuid.uuid4().hex}",
            "meeting_id": meeting_id,
            "step_id": "meeting",
            "role": "System",
            "attempt": 1,
            "status": "reopened",
        }
        repository.append_event(meeting_id, event)
        return {"status": "open"}

    @app.delete("/meetings/{meeting_id}", status_code=204)
    @meeting_transitions.synchronized
    def delete_meeting(meeting_id: str) -> Response:
        metadata_store.get(meeting_id)
        if jobs.is_running(meeting_id):
            raise HTTPException(status_code=409, detail="Cannot delete a running meeting")
        repository.delete(meeting_id)
        return Response(status_code=204)

    def _resolve_quoted_event_id(
        meeting_id: str, quoted_event_id: str | None
    ) -> str | None:
        if not quoted_event_id:
            return None
        exists = any(
            e.get("event_id") == quoted_event_id
            for e in repository.read_events(meeting_id)
        )
        return quoted_event_id if exists else None

    @app.post("/meetings/{meeting_id}/messages")
    @meeting_transitions.synchronized
    def add_meeting_message(
        meeting_id: str,
        request: AddMeetingMessageRequest,
    ) -> dict[str, Any]:
        reject_running_meeting(jobs, meeting_id)
        metadata_store.get(meeting_id)
        reject_terminal_meeting(repository, meeting_id)
        resolved_quote = _resolve_quoted_event_id(meeting_id, request.quoted_event_id)
        event = {
            "event_id": f"{meeting_id}:human-message:{uuid.uuid4().hex}",
            "meeting_id": meeting_id,
            "step_id": "human-message",
            "role": "Human",
            "attempt": 1,
            "status": "completed",
            "content": request.content,
        }
        if resolved_quote:
            event["quoted_event_id"] = resolved_quote
        repository.append_event(meeting_id, event)
        return event

    @app.post("/meetings/{meeting_id}/attachments")
    @meeting_transitions.synchronized
    async def upload_meeting_attachment(
        meeting_id: str,
        request: Request,
    ) -> dict[str, Any]:
        reject_running_meeting(jobs, meeting_id)
        metadata = metadata_store.get(meeting_id)
        reject_terminal_meeting(repository, meeting_id)
        content_type = request.headers.get("content-type", "")
        body = await _read_upload_body(request, attachment_limits.per_file_bytes)
        try:
            filename, content = parse_upload_part(body, content_type)
        except MultipartUploadError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        extension = Path(filename).suffix.lower()
        mode = meeting_mode(mode_catalog, metadata)
        is_text = classify_extension(extension) == "text"
        if is_text and mode.category != "chatroom":
            raise HTTPException(
                status_code=400,
                detail="Text files (.txt/.md) must be ingested via the case-files flow",
            )
        size = len(content)
        if size > attachment_limits.per_file_bytes:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"File exceeds the per-file attachment limit "
                    f"of {attachment_limits.per_file_bytes} bytes"
                ),
            )
        if attachments.summary(meeting_id).total_bytes + size > attachment_limits.per_meeting_bytes:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Meeting exceeds the total attachment quota "
                    f"of {attachment_limits.per_meeting_bytes} bytes"
                ),
            )
        if is_text:
            # Chatroom text files mirror into the AI-visible case-files contract
            # before anything is persisted, so a rejected mirror never leaves a
            # half-written blob/attachment event behind. The mirror reuses the
            # write-side mutation helper, which disables pending-impact gating
            # for chatroom mode.
            text_content = content.decode("utf-8", errors="replace")
            material_limits = versioned_limits()
            if len(text_content) > material_limits.per_item_chars:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"文字檔超過 case-files 單份字元上限 "
                        f"（{material_limits.per_item_chars} 字元）"
                    ),
                )
            current = case_materials.view(meeting_id)
            existing_chars = 0
            for item in [*current.evidence, *current.notes]:
                if item.status != "active":
                    continue
                active = next(
                    version
                    for version in item.versions
                    if version.version == item.active_version
                )
                existing_chars += active.size
            if existing_chars + len(text_content) > material_limits.total_chars:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"文字檔超過 case-files 總量字元上限 "
                        f"（{material_limits.total_chars} 字元）"
                    ),
                )
            visible_roles = [
                str(participant["role_id"])
                for participant in project_participants(mode, metadata)
            ]
            validate_material_roles(metadata, visible_roles)
            holder: dict[str, str] = {}

            def capture_evidence_id(view: CaseMaterialsView) -> CaseMaterialsView:
                holder["evidence_id"] = view.evidence[-1].id
                return view

            perform_material_mutation(
                meeting_id,
                lambda metadata, impact: capture_evidence_id(
                    case_materials.add_evidence(
                        meeting_id,
                        expected_revision=current.revision,
                        title=Path(filename).stem,
                        content=text_content,
                        visible_roles=visible_roles,
                        limits=material_limits,
                        impact=impact,
                    )
                ),
            )
        file_id = f"attachment-{uuid.uuid4().hex}"
        attachments.save_blob(meeting_id, file_id, io.BytesIO(content))
        return attachments.record_attachment(
            meeting_id,
            file_id=file_id,
            filename=filename,
            size=size,
            mime_type=mime_type_for_extension(extension),
            extension=extension,
            evidence_id=holder.get("evidence_id") if is_text else None,
        )

    @app.delete("/meetings/{meeting_id}/attachments/{file_id}")
    @meeting_transitions.synchronized
    def delete_meeting_attachment(meeting_id: str, file_id: str) -> dict[str, Any]:
        reject_running_meeting(jobs, meeting_id)
        metadata = metadata_store.get(meeting_id)
        reject_terminal_meeting(repository, meeting_id)
        event = attachments.attachment_event(meeting_id, file_id)
        if event is None:
            raise HTTPException(status_code=404, detail=f"Unknown attachment: {file_id}")
        mime_type = str(event.get("mime_type") or "")
        if mime_type in {"text/plain", "text/markdown"}:
            if meeting_mode(mode_catalog, metadata).category != "chatroom":
                raise HTTPException(
                    status_code=404, detail=f"Unknown attachment: {file_id}"
                )
            view = case_materials.view(meeting_id)
            target: str | None = None
            evidence_id = event.get("evidence_id")
            if evidence_id is not None:
                if any(
                    item.status == "active" and item.id == evidence_id
                    for item in view.evidence
                ):
                    target = str(evidence_id)
            else:
                stem = Path(str(event.get("filename") or "")).stem
                candidates = [
                    item
                    for item in view.evidence
                    if item.status == "active"
                    and item.versions[-1].title == stem
                ]
                if len(candidates) > 1:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            f"Attachment title matches multiple evidence items: {stem}"
                        ),
                    )
                if len(candidates) == 1:
                    target = candidates[0].id
            if target is not None:
                perform_material_mutation(
                    meeting_id,
                    lambda metadata, impact: case_materials.remove_evidence(
                        meeting_id,
                        target,
                        expected_revision=case_materials.view(meeting_id).revision,
                        impact=impact,
                    ),
                )
        removed_event = attachments.remove_attachment(meeting_id, file_id)
        if removed_event is None:
            raise HTTPException(status_code=404, detail=f"Unknown attachment: {file_id}")
        return removed_event

    @app.get("/meetings/{meeting_id}/attachments/{file_id}")
    def download_meeting_attachment(meeting_id: str, file_id: str) -> FileResponse:
        metadata_store.get(meeting_id)
        event = attachments.attachment_event(meeting_id, file_id)
        if event is None:
            raise HTTPException(status_code=404, detail=f"Unknown attachment: {file_id}")
        try:
            blob = attachments.blob_path(meeting_id, file_id)
        except ValueError:
            raise HTTPException(
                status_code=404, detail=f"Unknown attachment: {file_id}"
            ) from None
        mime_type = str(event.get("mime_type") or "application/octet-stream")
        filename = str(event.get("filename") or file_id)
        disposition = "inline" if mime_type.startswith("image/") else "attachment"
        return FileResponse(
            blob,
            media_type=mime_type,
            filename=filename,
            content_disposition_type=disposition,
        )

    @app.post("/meetings/{meeting_id}/messages/{event_id}/correct")
    @meeting_transitions.synchronized
    def correct_meeting_message(
        meeting_id: str,
        event_id: str,
        request: CorrectMeetingMessageRequest,
    ) -> dict[str, Any]:
        reject_running_meeting(jobs, meeting_id)
        metadata_store.get(meeting_id)
        reject_terminal_meeting(repository, meeting_id)
        original_event = next(
            (
                event
                for event in active_meeting_events(repository, meeting_id)
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

    def directed_response_context(
        meeting_id: str,
        role: str,
    ) -> tuple[
        dict[str, Any],
        ModeDefinition,
        list[Any],
        str,
        dict[str, ModelConfig],
        dict[str, Any],
        dict[str, object],
    ]:
        metadata = metadata_store.get(meeting_id)
        require_meeting_goal(metadata)
        reject_terminal_meeting(repository, meeting_id)
        material_view = require_case_materials_ready(
            repository, case_materials, meeting_id
        )
        mode = meeting_mode(mode_catalog, metadata)
        if mode.category != "relay":
            raise HTTPException(
                status_code=400,
                detail=f"Mode does not support directed responses: {mode.id}",
            )
        plan = relay_plan(mode)
        events = workflow_meeting_events(repository, meeting_id)
        directed_context: dict[str, object] = {}
        if mode.id == "courtroom":
            try:
                profile = CourtroomCaseProfile.for_metadata(metadata)
            except CourtroomCaseProfileError as error:
                raise HTTPException(status_code=409, detail=str(error)) from error
            courtroom = courtroom_workflow.project(metadata, events)
            if (
                courtroom is None
                or courtroom.get("status") != "confirmed"
                or "directed-response" not in courtroom.get("available_actions", [])
                or not courtroom.get("current_issue_id")
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "Directed courtroom responses are only available after the current "
                        "issue arguments complete and before its ruling"
                    ),
                )
            if role != "Defense":
                raise HTTPException(
                    status_code=400,
                    detail=f"Directed courtroom supplements are only available for {profile.role_display('Defense')}",
                )
            directed_context = {
                "docket_revision": int(courtroom["revision"]),
                "issue_id": str(courtroom["current_issue_id"]),
                "case_type": profile.case_type,
                "role_display": profile.role_display(role),
                "phase_display": "答辯方補充",
            }
        else:
            failed = latest_unresolved_fixed_relay_failure(events, plan)
            if failed is not None:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        f"Retry failed relay step before requesting a directed response: "
                        f"{failed.get('step_id')}"
                    ),
                )
        participants = project_participants(mode, metadata)
        participant = next(
            (item for item in participants if item["role_id"] == role),
            None,
        )
        if participant is None:
            raise HTTPException(status_code=400, detail=f"Unknown role: {role}")
        role_definition = next((item for item in mode.roles if item.id == role), None)
        role_display_name = str(
            participant.get("display_name")
            or participant.get("name")
            or (role_definition.name if role_definition is not None else role)
        )
        return (
            metadata,
            mode,
            plan,
            role_display_name,
            resolved_meeting_models(meeting_assignments, metadata, mode),
            material_inputs_for_runner(metadata, material_view),
            directed_context,
        )

    def record_stale_courtroom_operation(
        meeting_id: str,
        *,
        operation: str,
        error: Exception,
    ) -> None:
        repository.append_event(
            meeting_id,
            {
                "event_id": f"{meeting_id}:courtroom-operation:{uuid.uuid4().hex}",
                "meeting_id": meeting_id,
                "step_id": "courtroom-operation",
                "role": "System",
                "attempt": 1,
                "status": "failed",
                "interaction_type": "courtroom-operation-failure",
                "courtroom_operation": operation,
                "failure_kind": "stale_transition",
                "error": str(error),
            },
        )

    def perform_role_response(
        meeting_id: str,
        role: str,
        request: DirectedRoleResponseRequest,
    ) -> Any:
        reject_running_meeting(jobs, meeting_id)
        metadata, mode, plan, role_display_name, model_assignments, inputs, directed_context = (
            directed_response_context(meeting_id, role)
        )

        def run_directed_response() -> None:
            if mode.id == "courtroom":
                try:
                    with meeting_transitions.guard(meeting_id):
                        (
                            fresh_metadata,
                            _fresh_mode,
                            fresh_plan,
                            fresh_role_display_name,
                            fresh_model_assignments,
                            fresh_inputs,
                            fresh_directed_context,
                        ) = directed_response_context(meeting_id, role)
                except Exception as error:
                    record_stale_courtroom_operation(
                        meeting_id,
                        operation="directed-response",
                        error=error,
                    )
                    return
                runner.respond_as_role(
                    meeting_id=meeting_id,
                    goal=fresh_metadata["goal"],
                    role=role,
                    role_display_name=fresh_role_display_name,
                    instruction=request.instruction,
                    model_assignments=fresh_model_assignments,
                    plan=fresh_plan,
                    inputs=fresh_inputs,
                    context_fields=fresh_directed_context,
                )
                return
            runner.respond_as_role(
                meeting_id=meeting_id,
                goal=metadata["goal"],
                role=role,
                role_display_name=role_display_name,
                instruction=request.instruction,
                model_assignments=model_assignments,
                plan=plan,
                inputs=inputs,
                context_fields=directed_context,
            )

        if not jobs.start(meeting_id, run_directed_response):
            raise HTTPException(status_code=409, detail="Meeting is already running")
        return JSONResponse(status_code=202, content={"status": "running"})

    @app.post("/meetings/{meeting_id}/roles/{role}/respond", status_code=202)
    def respond_as_role(
        meeting_id: str,
        role: str,
        request: DirectedRoleResponseRequest,
    ) -> Any:
        with meeting_transitions.guard(meeting_id):
            return perform_role_response(meeting_id, role, request)

    def chatroom_mention_context(
        meeting_id: str,
    ) -> tuple[
        dict[str, Any],
        ModeDefinition,
        dict[str, ModelConfig],
        dict[str, Any],
        list[dict[str, Any]],
    ]:
        metadata = metadata_store.get(meeting_id)
        reject_terminal_meeting(repository, meeting_id)
        material_view = require_case_materials_ready(
            repository, case_materials, meeting_id, ignore_pending_impact=True
        )
        mode = meeting_mode(mode_catalog, metadata)
        if mode.category != "chatroom":
            raise HTTPException(status_code=409, detail="Mode does not support chat mentions")
        participants = project_participants(mode, metadata)
        model_assignments = resolved_meeting_models(meeting_assignments, metadata, mode)
        inputs = material_inputs_for_runner(metadata, material_view)
        return metadata, mode, model_assignments, inputs, participants

    @app.post("/meetings/{meeting_id}/chat/mention")
    def chat_mention(
        meeting_id: str,
        request: AddChatMentionRequest,
    ) -> Any:
        with meeting_transitions.guard(meeting_id):
            reject_running_meeting(jobs, meeting_id)
            metadata, mode, model_assignments, inputs, participants = (
                chatroom_mention_context(meeting_id)
            )
            role_display_names = _build_role_display_names(mode, participants)
            stored_role_ids = {
                str(item.get("role_id"))
                for item in (metadata.get("participants") or [])
                if isinstance(item, dict) and item.get("role_id")
            }
            active_role_ids = [
                role.id
                for role in mode.roles
                if role.id == "host" or role.id in stored_role_ids
            ]
            if request.quoted_event_id and not request.quoted_event_id.startswith(f"{meeting_id}:"):
                return JSONResponse(
                    status_code=400,
                    content=rejected("INVALID_REQUEST_SCHEMA", "quoted_event_id"),
                )
            human_event_fields: dict[str, object] = {}
            try:
                routing = validate_chatroom_routing(
                    content=request.content,
                    mentions=[
                        ChatroomMentionToken(
                            token_id=token.token_id,
                            role_id=token.role_id,
                            display_text=token.display_text,
                            start=token.start,
                            end=token.end,
                        )
                        for token in request.mentions
                    ],
                    source_tokens=[
                        ChatroomSourceToken(
                            token_id=token.token_id,
                            source_ref=token.source_ref,
                            display_text=token.display_text,
                            start=token.start,
                            end=token.end,
                        )
                        for token in request.source_tokens
                    ],
                    source_refs=list(request.source_refs),
                    active_role_ids=active_role_ids,
                    role_display_names=role_display_names,
                )
            except ValueError as error:
                payload = error.args[0]
                if isinstance(payload, dict) and payload.get("status") == "rejected":
                    return JSONResponse(status_code=400, content=payload)
                return JSONResponse(status_code=400, content=rejected("INVALID_REQUEST_SCHEMA", None))
            target_role_ids = routing.target_role_ids
            human_event_fields = {
                "mentions": [token.model_dump() for token in request.mentions],
                "source_tokens": [token.model_dump() for token in request.source_tokens],
                "source_refs": list(request.source_refs),
            }

            # Source authorization is intentionally only a structural seam in this slice;
            # the source registry and readable-body projection belong to Slice 3.
            if request.source_tokens or request.source_refs:
                return JSONResponse(
                    status_code=400,
                    content=rejected("INVALID_SOURCE_REF", "source_refs"),
                )

            def run_mention() -> None:
                if target_role_ids == active_role_ids:
                    runner.fanout_chatroom_all(
                        meeting_id=meeting_id,
                        goal=metadata.get("goal", ""),
                        instruction=routing.instruction,
                        role_display_names=role_display_names,
                        model_assignments=model_assignments,
                        inputs=inputs,
                        quoted_event_id=request.quoted_event_id,
                        human_content=request.content,
                        human_event_fields=human_event_fields,
                    )
                elif len(target_role_ids) == 1:
                    single_role = target_role_ids[0]
                    participant = next(
                        (p for p in participants if p["role_id"] == single_role),
                        None,
                    )
                    role_definition = next(
                        (r for r in mode.roles if r.id == single_role), None
                    )
                    role_display_name = str(
                        participant.get("display_name")
                        or participant.get("name")
                        or (role_definition.name if role_definition is not None else single_role)
                    )
                    runner.chat_respond_as_role(
                        meeting_id=meeting_id,
                        goal=metadata.get("goal", ""),
                        role=single_role,
                        role_display_name=role_display_name,
                        instruction=routing.instruction,
                        model_assignments=model_assignments,
                        inputs=inputs,
                        quoted_event_id=request.quoted_event_id,
                        human_content=request.content,
                        human_event_fields=human_event_fields,
                    )
                else:
                    filtered_assignments = {
                        r: model_assignments[r] for r in target_role_ids if r in model_assignments
                    }
                    filtered_display_names = {
                        r: role_display_names[r]
                        for r in filtered_assignments
                    }
                    runner.fanout_chatroom_all(
                        meeting_id=meeting_id,
                        goal=metadata.get("goal", ""),
                        instruction=routing.instruction,
                        role_display_names=filtered_display_names,
                        model_assignments=filtered_assignments,
                        inputs=inputs,
                        quoted_event_id=request.quoted_event_id,
                        human_content=request.content,
                        human_event_fields=human_event_fields,
                    )

            if not jobs.start(meeting_id, run_mention):
                raise HTTPException(status_code=409, detail="Meeting is already running")
            return JSONResponse(
                status_code=202,
                content={
                    "status": "accepted",
                    "meeting_id": meeting_id,
                    "target_role_ids": target_role_ids,
                    "source_refs": list(request.source_refs or []),
                    "warnings": routing.warnings,
                },
            )

    def _build_role_display_names(
        mode: ModeDefinition,
        participants: list[dict[str, Any]],
    ) -> dict[str, str]:
        names: dict[str, str] = {}
        for p in participants:
            rid = p["role_id"]
            rd = next((r for r in mode.roles if r.id == rid), None)
            names[rid] = str(
                p.get("display_name") or p.get("name")
                or (rd.name if rd is not None else rid)
            )
        return names

    @app.post("/meetings/{meeting_id}/sequences", status_code=202)
    @meeting_transitions.synchronized
    def respond_as_sequence(
        meeting_id: str,
        request: RunRoleSequenceRequest,
    ) -> dict[str, str]:
        reject_running_meeting(jobs, meeting_id)
        metadata = metadata_store.get(meeting_id)
        require_meeting_goal(metadata)
        reject_terminal_meeting(repository, meeting_id)
        material_view = require_case_materials_ready(
            repository, case_materials, meeting_id
        )
        mode = meeting_mode(mode_catalog, metadata)
        if mode.id == "courtroom":
            try:
                CourtroomCaseProfile.for_metadata(metadata)
            except CourtroomCaseProfileError as error:
                raise HTTPException(status_code=409, detail=str(error)) from error
            raise HTTPException(
                status_code=409,
                detail="Role sequences cannot bypass the courtroom issue workflow",
            )
        if mode.category != "relay":
            raise HTTPException(status_code=400, detail=f"Mode does not support role sequences: {mode.id}")
        plan = relay_plan(mode)
        failed = latest_unresolved_fixed_relay_failure(
            active_meeting_events(repository, meeting_id),
            plan,
        )
        if failed is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Retry failed relay step before running a role sequence: "
                    f"{failed.get('step_id')}"
                ),
            )
        if not request.roles:
            raise HTTPException(status_code=400, detail="Role sequence cannot be empty")
        if len(set(request.roles)) != len(request.roles):
            raise HTTPException(
                status_code=400,
                detail="Role sequence cannot contain duplicate roles",
            )
        model_assignments = resolved_meeting_models(
            meeting_assignments,
            metadata,
            mode,
        )
        for role in request.roles:
            if role not in plan.directed_steps:
                raise HTTPException(status_code=400, detail=f"Unknown role: {role}")
            if role not in model_assignments:
                raise HTTPException(
                    status_code=400,
                    detail=f"Missing model assignment for role: {role}",
                )
        inputs = material_inputs_for_runner(metadata, material_view)
        if not jobs.start(
            meeting_id,
            lambda: runner.respond_as_sequence(
                meeting_id=meeting_id,
                goal=metadata["goal"],
                roles=request.roles,
                model_assignments=model_assignments,
                plan=plan,
                inputs=inputs,
            ),
        ):
            raise HTTPException(status_code=409, detail="Meeting is already running")
        return {"status": "running"}

    def perform_step_retry(
        meeting_id: str,
        step_id: str,
        request: StartMeetingRequest,
    ) -> Any:
        reject_running_meeting(jobs, meeting_id)
        metadata = metadata_store.get(meeting_id)
        require_meeting_goal(metadata)
        reject_terminal_meeting(repository, meeting_id)
        material_view = require_case_materials_ready(
            repository, case_materials, meeting_id
        )
        mode = meeting_mode(mode_catalog, metadata)
        model_assignments = resolved_meeting_models(
            meeting_assignments,
            metadata,
            mode,
        )
        participants = project_participants(mode, metadata)
        role_display_names = {
            str(participant["role_id"]): str(
                participant.get("display_name")
                or participant.get("name")
                or participant["role_id"]
            )
            for participant in participants
        }
        if mode.id != "courtroom":
            retry_events = active_meeting_events(repository, meeting_id)
            retry_matching = [
                event for event in retry_events if event.get("step_id") == step_id
            ]
            retry_failed = retry_matching[-1] if retry_matching else None
            if retry_failed is None or retry_failed.get("status") != "failed":
                raise HTTPException(status_code=400, detail=f"Step is not failed: {step_id}")
            retry_base_step_id = str(
                retry_failed.get("base_step_id", retry_failed.get("step_id"))
            )
            if mode.category == "relay":
                plan = relay_plan(mode)
                if (
                    retry_failed.get("interaction_type") != "directed-role-response"
                    and retry_base_step_id not in {step.step_id for step in plan.steps}
                ):
                    raise HTTPException(
                        status_code=400,
                        detail=f"Step is not part of this meeting's mode: {retry_base_step_id}",
                    )
            else:
                plan = parallel_plan(mode, project_participants(mode, metadata))
                if retry_base_step_id not in {member.step_id for member in plan.members}:
                    raise HTTPException(
                        status_code=400,
                        detail=(
                            "Step is not part of this meeting's parallel fanout: "
                            f"{retry_base_step_id}"
                        ),
                    )
        retry_events = active_meeting_events(repository, meeting_id)
        retry_matching = [event for event in retry_events if event.get("step_id") == step_id]
        retry_failed = retry_matching[-1] if retry_matching else None
        if (
            retry_failed is not None
            and retry_failed.get("interaction_type") == "directed-role-response"
        ):
            retry_role = str(retry_failed.get("role", ""))
            if retry_role not in model_assignments:
                raise HTTPException(
                    status_code=400,
                    detail=f"Missing model assignment for role: {retry_role}",
                )
            instruction_event_id = str(
                retry_failed.get("in_response_to_event_id", "")
            )
            instruction_event = next(
                (
                    event
                    for event in retry_events
                    if event.get("event_id") == instruction_event_id
                ),
                None,
            )
            if (
                not instruction_event_id
                or instruction_event is None
                or instruction_event.get("interaction_type")
                != "directed-role-instruction"
                or instruction_event.get("role") != "Human"
                or instruction_event.get("status") != "completed"
                or instruction_event.get("target_role_id") != retry_role
                or not str(instruction_event.get("content", "")).strip()
            ):
                raise HTTPException(
                    status_code=400,
                    detail="Directed response instruction is unavailable for retry",
                )
        try:
            if mode.id == "courtroom":
                try:
                    CourtroomCaseProfile.for_metadata(metadata)
                except CourtroomCaseProfileError as error:
                    raise CourtroomWorkflowError(str(error)) from error
                events = workflow_meeting_events(repository, meeting_id)
                matching = [event for event in events if event.get("step_id") == step_id]
                failed = matching[-1] if matching else None
                if failed is None or failed.get("status") != "failed":
                    raise CourtroomWorkflowError(f"Step is not failed: {step_id}", 400)
                interaction_type = failed.get("interaction_type")
                retry_inputs = material_inputs_for_runner(metadata, material_view)
                if interaction_type in {
                    "courtroom-issue-draft",
                    "courtroom-issue-phase",
                    "courtroom-final-verdict",
                }:
                    def operation() -> None:
                        courtroom_workflow.retry_failed_step(
                            meeting_id,
                            step_id=step_id,
                            goal=metadata["goal"],
                            model_assignments=model_assignments,
                            inputs=retry_inputs,
                            runner=runner,
                        )
                elif interaction_type == "directed-role-response":
                    courtroom = courtroom_workflow.project(metadata, events)
                    if (
                        courtroom is None
                        or courtroom.get("status") != "confirmed"
                        or "directed-response" not in courtroom.get("available_actions", [])
                        or failed.get("docket_revision") != courtroom.get("revision")
                        or failed.get("issue_id") != courtroom.get("current_issue_id")
                    ):
                        raise CourtroomWorkflowError(
                            "Directed response retry does not belong to the current courtroom issue"
                        )
                    def operation() -> None:
                        try:
                            with meeting_transitions.guard(meeting_id):
                                fresh_metadata = metadata_store.get(meeting_id)
                                require_meeting_goal(fresh_metadata)
                                reject_terminal_meeting(repository, meeting_id)
                                fresh_material_view = require_case_materials_ready(
                                    repository, case_materials, meeting_id
                                )
                                fresh_mode = meeting_mode(mode_catalog, fresh_metadata)
                                if fresh_mode.id != "courtroom":
                                    raise CourtroomWorkflowError(
                                        "Directed response retry is only available in courtroom mode"
                                    )
                                fresh_events = workflow_meeting_events(repository, meeting_id)
                                fresh_matching = [
                                    event
                                    for event in fresh_events
                                    if event.get("step_id") == step_id
                                ]
                                fresh_failed = fresh_matching[-1] if fresh_matching else None
                                fresh_courtroom = courtroom_workflow.project(
                                    fresh_metadata,
                                    fresh_events,
                                )
                                if (
                                    fresh_failed is None
                                    or fresh_failed.get("status") != "failed"
                                    or fresh_failed.get("interaction_type")
                                    != "directed-role-response"
                                    or fresh_courtroom is None
                                    or fresh_courtroom.get("status") != "confirmed"
                                    or "directed-response"
                                    not in fresh_courtroom.get("available_actions", [])
                                    or fresh_failed.get("docket_revision")
                                    != fresh_courtroom.get("revision")
                                    or fresh_failed.get("issue_id")
                                    != fresh_courtroom.get("current_issue_id")
                                ):
                                    raise CourtroomWorkflowError(
                                        "Directed response retry does not belong to the current "
                                        "courtroom issue"
                                    )
                                fresh_participants = project_participants(
                                    fresh_mode,
                                    fresh_metadata,
                                )
                                fresh_role_display_names = {
                                    str(participant["role_id"]): str(
                                        participant.get("display_name")
                                        or participant.get("name")
                                        or participant["role_id"]
                                    )
                                    for participant in fresh_participants
                                }
                                fresh_model_assignments = resolved_meeting_models(
                                    meeting_assignments,
                                    fresh_metadata,
                                    fresh_mode,
                                )
                                fresh_inputs = material_inputs_for_runner(
                                    fresh_metadata, fresh_material_view
                                )
                        except Exception as error:
                            record_stale_courtroom_operation(
                                meeting_id,
                                operation="directed-response-retry",
                                error=error,
                            )
                            return
                        runner.retry_failed_step(
                            meeting_id=meeting_id,
                            step_id=step_id,
                            goal=fresh_metadata["goal"],
                            model_assignments=fresh_model_assignments,
                            plan=relay_plan(fresh_mode),
                            inputs=fresh_inputs,
                            role_display_names=fresh_role_display_names,
                        )
                else:
                    raise CourtroomWorkflowError(f"Step is not failed: {step_id}", 400)
                if not jobs.start(meeting_id, operation):
                    raise CourtroomWorkflowError("Meeting is already running")
                return JSONResponse(status_code=202, content={"status": "running"})
            retry_inputs = material_inputs_for_runner(metadata, material_view)
            if mode.category == "relay":
                operation = lambda: runner.retry_failed_step(
                    meeting_id=meeting_id,
                    step_id=step_id,
                    goal=metadata["goal"],
                    model_assignments=model_assignments,
                    plan=plan,
                    inputs=retry_inputs,
                    role_display_names=role_display_names,
                )
            else:
                operation = lambda: runner.retry_failed_parallel_step(
                    meeting_id=meeting_id,
                    step_id=step_id,
                    goal=metadata["goal"],
                    model_assignments=model_assignments,
                    plan=plan,
                    inputs=retry_inputs,
                )
            if not jobs.start(meeting_id, operation):
                raise HTTPException(status_code=409, detail="Meeting is already running")
            return JSONResponse(status_code=202, content={"status": "running"})
        except CourtroomWorkflowError as error:
            raise HTTPException(status_code=error.status_code, detail=error.detail) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {
            "status": project_activity_status(
                active_meeting_events(repository, meeting_id)
            )
        }

    @app.post("/meetings/{meeting_id}/steps/{step_id}/retry", status_code=202)
    def retry_step(
        meeting_id: str,
        step_id: str,
        request: StartMeetingRequest,
    ) -> Any:
        with meeting_transitions.guard(meeting_id):
            return perform_step_retry(meeting_id, step_id, request)

    @app.get("/meetings/{meeting_id}/transcript.md")
    def get_transcript(meeting_id: str, epoch: str = "current") -> PlainTextResponse:
        metadata = metadata_store.get(meeting_id)
        mode = meeting_mode(mode_catalog, metadata)
        view = DeliberationEpochs.view(repository.read_events(meeting_id))

        def render(events: list[dict[str, Any]], title: str) -> str:
            role_labels, step_labels = transcript_presentation_labels(
                mode,
                project_participants(mode, metadata),
                events,
            )
            return projector.project(
                events,
                title=title,
                role_labels=role_labels,
                step_labels=step_labels,
            )

        if epoch == "current":
            transcript = render(view.active_events, meeting_title(metadata))
        elif epoch == "all":
            sections = [f"# {meeting_title(metadata)} — 完整審議歷史\n"]
            for item in view.epochs:
                sections.append(f"\n## 審議輪次 {item.number}\n")
                if item.reason:
                    sections.append(f"\n**重開原因：** {item.reason}\n")
                sections.append("\n" + render(item.events, f"審議輪次 {item.number}"))
            transcript = "".join(sections)
        else:
            selected = next((item for item in view.epochs if item.id == epoch), None)
            if selected is None:
                raise HTTPException(status_code=404, detail=f"Unknown deliberation epoch: {epoch}")
            transcript = render(selected.events, meeting_title(metadata))
        return PlainTextResponse(transcript, media_type="text/markdown")

    @app.websocket("/meetings/{meeting_id}/events")
    async def meeting_events(websocket: WebSocket, meeting_id: str) -> None:
        metadata = metadata_store.get(meeting_id)
        mode = meeting_mode(mode_catalog, metadata)
        await websocket.accept()
        all_events, activity_status = live_meeting_snapshot(
            repository,
            jobs,
            meeting_id,
            mode,
        )
        view = DeliberationEpochs.view(all_events)
        events = view.active_events
        try:
            await websocket.send_json(
                {
                    "type": "snapshot",
                    "events": project_events(
                        events,
                        removed_attachment_ids=attachments.removed_file_ids(meeting_id),
                    ),
                    "stream_events": [],
                    "activity_status": activity_status,
                }
            )
            event_count = len(events)
            epoch_id = view.active_epoch.id
            stream_cursor = stream_bus.cursor(meeting_id)
            while True:
                try:
                    await asyncio.wait_for(websocket.receive_text(), timeout=0.1)
                except TimeoutError:
                    pass
                all_events, next_activity_status = live_meeting_snapshot(
                    repository,
                    jobs,
                    meeting_id,
                    mode,
                )
                view = DeliberationEpochs.view(all_events)
                events = view.active_events
                stream_events = stream_bus.events_since(meeting_id, stream_cursor)
                epoch_changed = view.active_epoch.id != epoch_id
                if (
                    len(events) != event_count
                    or stream_events
                    or next_activity_status != activity_status
                    or epoch_changed
                ):
                    if epoch_changed:
                        await websocket.send_json(
                            {
                                "type": "snapshot",
                                "events": project_events(
                                    events,
                                    removed_attachment_ids=attachments.removed_file_ids(
                                        meeting_id
                                    ),
                                ),
                                "stream_events": [],
                                "activity_status": next_activity_status,
                            }
                        )
                    else:
                        await websocket.send_json(
                            {
                                "type": "update",
                                "events": project_events(
                                    events[event_count:],
                                    removed_attachment_ids=attachments.removed_file_ids(
                                        meeting_id
                                    ),
                                ),
                                "stream_events": stream_events,
                                "activity_status": next_activity_status,
                            }
                        )
                    event_count = len(events)
                    epoch_id = view.active_epoch.id
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


def project_events(
    events: list[dict[str, Any]],
    *,
    removed_attachment_ids: set[str] = frozenset(),
) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for event in events:
        if event.get("step_id") == ATTACHMENT_REMOVED_KIND:
            continue
        entry: dict[str, Any] = {
            **event,
            **(
                {"output_schema_id": event.get("output_schema_id", DEFAULT_OUTPUT_SCHEMA_ID)}
                if event.get("role") not in {"Human", "System"}
                else {}
            ),
        }
        if (
            event.get("step_id") == ATTACHMENT_EVENT_KIND
            and event.get("file_id") in removed_attachment_ids
        ):
            entry["removed"] = True
        projected.append(entry)
    return projected


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
                "output_schema": role.output_schema,
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
            "anonymize_inputs": mode.synthesis.anonymize_inputs,
        }
    return result


def normalize_participants(
    mode: ModeDefinition,
    requested: list[MeetingParticipantRequest],
    model_repository: ModelConfigRepository,
) -> list[dict[str, Any]]:
    configured_models = model_repository.list_models()
    default_model_id = configured_models[0].id if configured_models else None
    if mode.category == "relay":
        participants = [participant.model_dump() for participant in requested]
        if not participants:
            participants = [
                {"role_id": role_id, "model_config_id": default_model_id}
                for role_id in mode.role_ids()
            ]
        role_ids = set(mode.role_ids())
        validate_participant_ids(
            mode=mode,
            participants=participants,
            allowed_role_ids=role_ids,
            model_repository=model_repository,
        )
        missing_roles = sorted(role_ids - {str(item["role_id"]) for item in participants})
        if missing_roles:
            raise HTTPException(
                status_code=400,
                detail=f"Missing participant roles: {', '.join(missing_roles)}",
            )
        return participants

    if mode.category == "chatroom":
        participants = [participant.model_dump() for participant in requested]
        if not participants:
            participants = [
                {"role_id": role_id, "model_config_id": default_model_id}
                for role_id in mode.role_ids()
            ]
        validate_participant_ids(
            mode=mode,
            participants=participants,
            allowed_role_ids=set(mode.role_ids()),
            model_repository=model_repository,
        )
        return participants

    if mode.fanout is None or mode.synthesis is None:
        raise HTTPException(status_code=500, detail=f"Parallel mode is incomplete: {mode.id}")

    participants = [participant.model_dump() for participant in requested]
    if not participants:
        fixed_member_ids = [role.id for role in mode.roles if role.kind == "member"]
        if fixed_member_ids:
            participants = [
                {"role_id": role.id, "model_config_id": default_model_id}
                for role in mode.roles
            ]
        else:
            participants = [
                {
                    "role_id": f"{mode.fanout.role}-{index}",
                    "model_config_id": default_model_id,
                }
                for index in range(1, mode.fanout.min_instances + 1)
            ]
            participants.append(
                {"role_id": mode.synthesis.role, "model_config_id": default_model_id}
            )
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
        raise HTTPException(
            status_code=400,
            detail=f"Missing participant roles: {mode.synthesis.role}",
        )
    return participants


def normalize_case_files(
    mode: ModeDefinition,
    participants: list[dict[str, Any]],
    requested: list[CaseFileRequest],
    limits: CaseFileLimits,
) -> list[dict[str, Any]]:
    if not requested:
        return []
    allowed_roles = {
        participant["role_id"]
        for participant in project_participants(mode, {"participants": participants})
    }
    case_files: list[dict[str, Any]] = []
    total_size = 0
    for index, item in enumerate(requested, start=1):
        title = item.title.strip()
        content = item.content
        visible_roles = [role.strip() for role in item.visible_roles if role.strip()]
        if not title:
            raise HTTPException(status_code=400, detail="Case file title is required")
        if not content.strip():
            raise HTTPException(status_code=400, detail=f"Case file content is required: {title}")
        if not visible_roles:
            raise HTTPException(status_code=400, detail=f"Case file requires at least one visible role: {title}")
        for role in visible_roles:
            if role not in allowed_roles:
                raise HTTPException(
                    status_code=400,
                    detail=f"Unknown case file visible role for mode {mode.id}: {role}",
                )
        size = len(content)
        if size > limits.per_file_chars:
            raise HTTPException(
                status_code=413,
                detail=f"Case file content exceeds {limits.per_file_chars} characters: {title}",
            )
        total_size += size
        if total_size > limits.total_chars:
            raise HTTPException(
                status_code=413,
                detail=f"Case files exceed {limits.total_chars} total characters",
            )
        case_files.append(
            {
                "id": f"case-file-{index}",
                "evidence_index": index,
                "citation_anchor": citation_anchor(index),
                "title": title,
                "content": content,
                "visible_roles": visible_roles,
                "size": size,
            }
        )
    return case_files


def evidence_anchor_label(mode_id: str | None) -> str:
    return "附件" if mode_id and mode_id != "courtroom" else "證物"


def localize_evidence_anchor(anchor: str, mode_id: str | None) -> str:
    return anchor.replace("證物", "附件") if evidence_anchor_label(mode_id) == "附件" else anchor


def case_file_manifest(
    case_files: list[dict[str, Any]], *, mode_id: str | None
) -> list[dict[str, Any]]:
    return [
        {
            "id": str(item["id"]),
            "evidence_index": int(item["evidence_index"]),
            "citation_anchor": str(item["citation_anchor"]),
            "title": str(item["title"]),
            "visible_roles": list(item["visible_roles"]),
            "size": int(item["size"]),
        }
        for item in project_case_files(case_files, mode_id=mode_id)
    ]


def citation_anchor(index: int) -> str:
    return f"[證物{chinese_integer(index)}]"


def chinese_integer(value: int) -> str:
    def section(number: int) -> str:
        result = ""
        pending_zero = False
        for divisor, unit in ((1000, "千"), (100, "百"), (10, "十"), (1, "")):
            digit, number = divmod(number, divisor)
            if digit:
                if pending_zero and result:
                    result += CHINESE_DIGITS[0]
                if not (divisor == 10 and digit == 1 and not result):
                    result += CHINESE_DIGITS[digit]
                result += unit
                pending_zero = False
            elif result and number:
                pending_zero = True
        return result

    if value <= 0:
        raise ValueError("Evidence index must be positive")
    high, low = divmod(value, 10_000)
    if not high:
        return section(low)
    if high >= 10_000:
        return "".join(CHINESE_DIGITS[int(digit)] for digit in str(value))
    separator = CHINESE_DIGITS[0] if low and low < 1000 else ""
    return f"{section(high)}萬{separator}{section(low) if low else ''}"


def project_case_files(
    case_files: list[dict[str, Any]], *, mode_id: str | None
) -> list[dict[str, Any]]:
    projected: list[dict[str, Any]] = []
    for position, item in enumerate(case_files, start=1):
        evidence_index = int(item.get("evidence_index", position))
        projected.append(
            {
                **item,
                "evidence_index": evidence_index,
                "citation_anchor": localize_evidence_anchor(
                    str(item.get("citation_anchor") or citation_anchor(evidence_index)),
                    mode_id,
                ),
            }
        )
    return projected


def project_case_materials(
    view: CaseMaterialsView,
    *,
    active_epoch_id: str,
    mode_id: str | None,
    category: str | None = None,
) -> dict[str, Any]:
    def project_version(version: Any) -> dict[str, Any]:
        return {
            "version": version.version,
            "title": version.title,
            "content": version.content,
            "visible_roles": list(version.visible_roles),
            "size": version.size,
            "created_at": version.created_at,
            "source_event_id": version.source_event_id,
        }

    impact = view.pending_impact
    effective_impact = (
        None
        if category == "chatroom"
        else (
            impact
            if impact is not None and impact.get("deliberation_epoch_id") == active_epoch_id
            else None
        )
    )
    return {
        "schema_version": view.schema_version,
        "revision": view.revision,
        "pending_impact": effective_impact,
        "evidence": [
            {
                "id": item.id,
                "evidence_index": item.evidence_index,
                "citation_anchor": localize_evidence_anchor(item.citation_anchor, mode_id),
                "status": item.status,
                "active_version": item.active_version,
                "versions": [project_version(version) for version in item.versions],
            }
            for item in view.evidence
        ],
        "notes": [
            {
                "id": item.id,
                "status": item.status,
                "active_version": item.active_version,
                "versions": [project_version(version) for version in item.versions],
            }
            for item in view.notes
        ],
        "revision_history": [
            {
                "revision": item.revision,
                "parent_revision": item.parent_revision,
                "transition": item.transition,
                "created_at": item.created_at,
                "evidence": item.evidence,
                "notes": item.notes,
            }
            for item in view.revision_history
        ],
    }


def active_case_material_prompt_items(
    view: CaseMaterialsView, *, mode_id: str | None
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for evidence in view.evidence:
        if evidence.status != "active":
            continue
        version = next(
            version
            for version in evidence.versions
            if version.version == evidence.active_version
        )
        items.append(
            {
                "kind": "evidence",
                "id": evidence.id,
                "evidence_index": evidence.evidence_index,
                "citation_anchor": localize_evidence_anchor(evidence.citation_anchor, mode_id),
                "version": evidence.active_version,
                "title": version.title,
                "content": version.content,
                "visible_roles": list(version.visible_roles),
                "size": version.size,
            }
        )
    for note in view.notes:
        if note.status != "active":
            continue
        version = next(
            version for version in note.versions if version.version == note.active_version
        )
        items.append(
            {
                "kind": "note",
                "id": note.id,
                "title": version.title,
                "content": version.content,
                "visible_roles": list(version.visible_roles),
                "size": version.size,
            }
        )
    return items


def active_case_evidence_projection(
    view: CaseMaterialsView, *, mode_id: str | None
) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in item.items() if key not in {"kind", "version"}}
        for item in active_case_material_prompt_items(view, mode_id=mode_id)
        if item["kind"] == "evidence"
    ]


def meeting_inputs_for_runner(
    metadata: dict[str, Any],
    case_files: list[dict[str, Any]],
    *,
    materials_revision: int | None = None,
) -> dict[str, Any]:
    mode_id = metadata.get("mode_id")
    inputs: dict[str, Any] = dict(metadata.get("inputs") or {})
    inputs.pop(CASE_FILES_BY_ROLE_INPUT, None)
    inputs[CASE_EVIDENCE_BY_ROLE_INPUT] = case_evidence_by_role(case_files, mode_id=mode_id)
    if case_files:
        inputs[CASE_FILES_BY_ROLE_INPUT] = case_files_by_role(case_files, mode_id=mode_id)
    if materials_revision is not None:
        inputs[MATERIALS_REVISION_INPUT] = materials_revision
    return inputs


def material_inputs_for_runner(
    metadata: dict[str, Any], view: CaseMaterialsView
) -> dict[str, Any]:
    inputs = meeting_inputs_for_runner(
        metadata,
        active_case_material_prompt_items(view, mode_id=metadata.get("mode_id")),
        materials_revision=view.revision,
    )
    latest = view.revision_history[-1]
    inputs[MATERIALS_REFS_INPUT] = [
        reference
        for reference in [*latest.evidence, *latest.notes]
        if reference["status"] == "active"
    ]
    return inputs


def case_files_by_role(
    case_files: list[dict[str, Any]], *, mode_id: str | None
) -> dict[str, str]:
    label = evidence_anchor_label(mode_id)
    grouped: dict[str, list[str]] = {}
    for item in case_files:
        title = str(item.get("title", "")).strip()
        content = str(item.get("content", ""))
        if not title or not content.strip():
            continue
        if item.get("kind") == "note":
            block = f"### 案件備註：{title}\n{content}"
        else:
            anchor = localize_evidence_anchor(str(item["citation_anchor"]), mode_id)
            block = f"### {anchor} {title}\n{content}"
        for role in item.get("visible_roles") or []:
            grouped.setdefault(str(role), []).append(block)
    instruction = (
        f"引用案卷中的事實或主張時，必須附上對應的 [{label}…] 引用錨點；"
        f"不可假造不存在的{label}錨點。"
    )
    rendered = {
        role: instruction + "\n\n" + "\n\n".join(blocks)
        for role, blocks in grouped.items()
    }
    rendered[CASE_FILES_DEFAULT_ROLE] = instruction
    return rendered


def case_evidence_by_role(
    case_files: list[dict[str, Any]], *, mode_id: str | None
) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in case_files:
        if item.get("kind") != "evidence":
            continue
        block = {
            "id": item["id"],
            "citation_anchor": localize_evidence_anchor(str(item["citation_anchor"]), mode_id),
            "version": item["version"],
            "content": item["content"],
        }
        for role in item.get("visible_roles") or []:
            grouped.setdefault(str(role), []).append(block.copy())
    return grouped


def require_case_materials_ready(
    repository: MeetingRepository,
    materials: CaseMaterials,
    meeting_id: str,
    *,
    ignore_pending_impact: bool = False,
) -> CaseMaterialsView:
    view = materials.view(meeting_id)
    impact = view.pending_impact
    active_epoch_id = DeliberationEpochs.view(
        repository.read_events(meeting_id)
    ).active_epoch.id
    if (
        not ignore_pending_impact
        and impact is not None
        and impact.get("deliberation_epoch_id") == active_epoch_id
    ):
        raise HTTPException(
            status_code=409,
            detail="Case materials changed; restart deliberation before AI execution",
        )
    return view


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
        if not isinstance(model_config_id, str) or not model_config_id:
            raise HTTPException(
                status_code=400,
                detail=f"Missing model assignment for participant: {role_id}",
            )
        get_model(model_repository, model_config_id)


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
    courtroom_profile = None
    if mode.id == "courtroom":
        try:
            courtroom_profile = CourtroomCaseProfile.for_metadata(metadata)
        except CourtroomCaseProfileError:
            pass
    for role in mode.roles:
        entry = stored.get(role.id, {})
        role_name = (
            courtroom_profile.role_display(role.id)
            if courtroom_profile is not None
            else role.name
        )
        projected.append(
            {
                "role_id": role.id,
                "name": role_name,
                "color": role.color,
                "kind": role.kind,
                "portrait": role.portrait,
                "model_config_id": entry.get("model_config_id"),
                "display_name": entry.get("display_name") or role_name,
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
    inputs: dict[str, Any],
) -> None:
    if mode.category == "relay":
        runner.start(
            meeting_id=metadata["meeting_id"],
            goal=metadata["goal"],
            model_assignments=model_assignments,
            plan=relay_plan(mode),
            inputs=inputs,
        )
        return
    runner.start_parallel(
        meeting_id=metadata["meeting_id"],
        goal=metadata["goal"],
        model_assignments=model_assignments,
        plan=parallel_plan(mode, project_participants(mode, metadata)),
        inputs=inputs,
    )


def resolved_meeting_models(
    meeting_assignments: MeetingModelAssignments,
    metadata: dict[str, Any],
    mode: ModeDefinition,
) -> dict[str, ModelConfig]:
    try:
        return meeting_assignments.resolve_models(
            metadata,
            project_participants(mode, metadata),
        )
    except AssignmentValidationError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error


def courtroom_operation_context(
    meeting_id: str,
    *,
    metadata_store: MeetingMetadataStore,
    repository: MeetingRepository,
    case_materials: CaseMaterials,
    mode_catalog: ModeCatalogRepository,
    meeting_assignments: MeetingModelAssignments,
) -> tuple[dict[str, Any], ModeDefinition, dict[str, ModelConfig], dict[str, Any]]:
    metadata = metadata_store.get(meeting_id)
    require_meeting_goal(metadata)
    reject_terminal_meeting(repository, meeting_id)
    material_view = require_case_materials_ready(
        repository, case_materials, meeting_id
    )
    mode = meeting_mode(mode_catalog, metadata)
    if mode.id != "courtroom":
        raise HTTPException(
            status_code=400,
            detail="Courtroom workflow is only available for courtroom meetings",
        )
    try:
        CourtroomCaseProfile.for_metadata(metadata)
    except CourtroomCaseProfileError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    return (
        metadata,
        mode,
        resolved_meeting_models(meeting_assignments, metadata, mode),
        material_inputs_for_runner(metadata, material_view),
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


def model_discovery_error_detail(error: AdapterError, model: ModelConfig) -> str:
    detail = str(error)
    if model.api_key_env:
        secret = os.environ.get(model.api_key_env)
        if secret:
            variants = {
                secret,
                urllib.parse.quote(secret),
                urllib.parse.quote(secret, safe=""),
                urllib.parse.quote_plus(secret),
                urllib.parse.urlencode({"key": secret}).partition("=")[2],
            }
            for variant in sorted(variants, key=len, reverse=True):
                detail = detail.replace(variant, "[REDACTED]")
    return detail


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
    transcript = projector.project(events, title=meeting_title(metadata))
    tags = " ".join(metadata.get("tags") or [])
    haystack = f"{transcript}\n{metadata.get('meeting_id', '')}\n{tags}".lower()
    return query in haystack


def reject_terminal_meeting(repository: MeetingRepository, meeting_id: str) -> None:
    status = latest_lifecycle_status(repository.read_events(meeting_id))
    if status in {"closed", "cancelled"}:
        raise HTTPException(status_code=409, detail=f"Meeting is terminal: {status}")


def reject_running_meeting(jobs: MeetingJobManager, meeting_id: str) -> None:
    if jobs.is_running(meeting_id):
        raise HTTPException(status_code=409, detail="Meeting is already running")


def meeting_title(metadata: dict[str, Any]) -> str:
    title = metadata.get("title")
    if isinstance(title, str) and title.strip():
        return title
    legacy_topic = metadata.get("topic")
    return legacy_topic if isinstance(legacy_topic, str) else ""


def transcript_presentation_labels(
    mode: ModeDefinition,
    participants: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> tuple[dict[str, str], dict[str, str]]:
    role_labels = {role.id: role.name for role in mode.roles}
    if mode.id != "courtroom":
        role_labels.update(
            {
                str(participant["role_id"]): str(
                    participant.get("display_name") or role_labels.get(str(participant["role_id"]))
                    or participant["role_id"]
                )
                for participant in participants
            }
        )
    role_labels["Human"] = "主席"
    role_labels["System"] = "系統"

    step_labels = {
        step.template.replace("_", "-"): step.label
        for step in mode.steps
    }
    if mode.synthesis is not None:
        step_labels["synthesis"] = mode.synthesis.label

    human_steps = {
        "human-message": "主席發言",
        "human-correction": "主席訂正",
        "meeting-goal-changed": "主席修改會議目標",
        "meeting-closed": "會議結案",
        "meeting-cancelled": "會議取消",
        "meeting-reopened": "重新開啟會議",
    }
    step_labels.update(human_steps)
    for event in events:
        event_id = str(event.get("event_id", ""))
        step_id = str(event.get("step_id", ""))
        base_step_id = str(event.get("base_step_id") or step_id)
        event_label_key = event_id or step_id
        role_label = role_labels.get(str(event.get("role")), str(event.get("role", "")))
        interaction_type = event.get("interaction_type")
        if interaction_type == "directed-role-instruction":
            target_role = str(event.get("target_role_id", ""))
            step_labels[event_label_key] = f"主席追問{role_labels.get(target_role, target_role)}"
        elif interaction_type == "directed-role-response":
            step_labels[event_label_key] = f"{role_label}回應主席追問"
        elif interaction_type == "role-sequence-response":
            step_labels[event_label_key] = f"{role_label}依序回應"
        elif base_step_id.startswith("member-"):
            step_labels[event_label_key] = f"{role_label}發想"
    return role_labels, step_labels


def require_meeting_goal(metadata: dict[str, Any]) -> str:
    if metadata.get("pending_deliberation_restart"):
        raise HTTPException(
            status_code=409,
            detail="Deliberation restart must recover before execution",
        )
    goal = metadata.get("goal")
    if not isinstance(goal, str) or not goal.strip():
        raise HTTPException(
            status_code=409,
            detail="Meeting goal must be set before execution",
        )
    return goal


def active_meeting_events(
    repository: MeetingRepository, meeting_id: str
) -> list[dict[str, Any]]:
    return DeliberationEpochs.view(repository.read_events(meeting_id)).active_events


def workflow_meeting_events(
    repository: MeetingRepository, meeting_id: str
) -> list[dict[str, Any]]:
    return DeliberationEpochs.view(repository.read_events(meeting_id)).workflow_events


def epoch_materials_revision(epoch: Any) -> int | None:
    if isinstance(epoch.marker, dict):
        snapshot = epoch.marker.get("snapshot")
        if isinstance(snapshot, dict) and isinstance(snapshot.get("materials_revision"), int):
            return snapshot["materials_revision"]
    return next(
        (
            event["materials_revision"]
            for event in reversed(epoch.events)
            if isinstance(event.get("materials_revision"), int)
        ),
        None,
    )


def finalize_deliberation_restart_metadata(
    metadata: dict[str, Any], marker: dict[str, Any]
) -> dict[str, Any]:
    updated = dict(metadata)
    updated.pop("pending_deliberation_restart", None)
    updated["deliberation_epoch_id"] = marker["epoch_id"]
    updated["deliberation_epoch_number"] = marker["epoch_number"]
    snapshot = marker.get("snapshot")
    if (
        marker.get("restart_reason") == "case_type_changed"
        and isinstance(snapshot, dict)
        and snapshot.get("to_case_type") in {"civil", "criminal"}
    ):
        updated["case_type"] = snapshot["to_case_type"]
        updated.pop("courtroom_docket", None)
    if marker.get("restart_scope") == "rebuild_issues":
        updated.pop("courtroom_docket", None)
    return updated


def finalize_pending_meeting_settings(metadata: dict[str, Any]) -> dict[str, Any]:
    """Publish a journal-backed settings update after all audit events exist."""
    pending = metadata.get("pending_meeting_settings")
    if not isinstance(pending, dict) or not isinstance(pending.get("target"), dict):
        return metadata
    updated = {**metadata, **pending["target"]}
    for key in pending.get("remove", []):
        if isinstance(key, str):
            updated.pop(key, None)
    updated.pop("pending_meeting_settings", None)
    return updated


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
    execution_epoch_id = state.get("deliberation_epoch_id")
    if execution_epoch_id:
        view = DeliberationEpochs.view(events)
        execution_epoch = next(
            (epoch for epoch in view.epochs if epoch.id == execution_epoch_id),
            None,
        )
        candidate_events = execution_epoch.events if execution_epoch is not None else []
    else:
        candidate_events = events
    matching_events = [
        event
        for event in candidate_events
        if event.get("step_id") == state["step_id"]
        and event.get("attempt") == state["attempt"]
        and event.get("status") in {"completed", "failed"}
    ]
    return bool(matching_events)


def project_meeting_status(events: list[dict[str, Any]]) -> str:
    status = latest_lifecycle_status(events)
    if status in {"closed", "cancelled"}:
        return status
    return "open"


def latest_lifecycle_status(events: list[dict[str, Any]]) -> str | None:
    latest_status = None
    for event in events:
        status = event.get("status")
        if status in {"closed", "cancelled", "reopened"}:
            latest_status = str(status)
    return latest_status


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
    if latest_event.get("status") == "reopened":
        return "waiting"
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


def live_meeting_snapshot(
    repository: MeetingRepository,
    jobs: MeetingJobManager,
    meeting_id: str,
    mode: ModeDefinition,
) -> tuple[list[dict[str, Any]], str]:
    """Read events and job state without publishing a torn settled projection."""
    was_running, revision_before = jobs.lifecycle_state(meeting_id)
    events = repository.read_events(meeting_id)
    is_running, revision_after = jobs.lifecycle_state(meeting_id)
    if not is_running and (was_running or revision_before != revision_after):
        # The operation may append its final events between the first read and the
        # lifecycle check. The revision also catches a whole fast operation that starts
        # and finishes between two otherwise identical non-running observations. Once
        # the Future is done all operation writes are complete, so one fresh read gives
        # callers the matching settled event snapshot.
        events = repository.read_events(meeting_id)
        verified_running, verified_revision = jobs.lifecycle_state(meeting_id)
        if verified_running or verified_revision != revision_after:
            # A second lifecycle transition overlapped the bounded reread. Publishing
            # that snapshot as settled would repeat the same torn-read bug; mark it
            # running so the frontend performs a fresh poll instead of looping here.
            is_running = True
    active_events = DeliberationEpochs.view(events).active_events
    return events, live_activity_status(active_events, is_running, mode)


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
    if mode.id == "courtroom" and latest_event.get("interaction_type") in {
        "courtroom-issue-draft",
        "courtroom-issue-phase",
        "courtroom-final-verdict",
    }:
        return projected
    if mode.category == "parallel":
        current_round = max(
            (
                int(event.get("round", 0))
                for event in events
                if str(event.get("base_step_id", "")).startswith("member-")
            ),
            default=0,
        )
        latest_members: dict[str, dict[str, Any]] = {}
        for event in events:
            base_step_id = str(event.get("base_step_id", ""))
            if (
                int(event.get("round", 0)) == current_round
                and base_step_id.startswith("member-")
            ):
                latest_members[base_step_id] = event
        if any(event.get("status") == "failed" for event in latest_members.values()):
            return "waiting"
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
    meeting_assignments: MeetingModelAssignments,
    model_pricing: dict[str, ConfigModelPricing | None] | None = None,
    activity_status: str | None = None,
    live_events: list[dict[str, Any]] | None = None,
    workflow_events: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    deliberation = DeliberationEpochs.view(events)
    live_events = deliberation.active_events if live_events is None else live_events
    workflow_events = deliberation.workflow_events if workflow_events is None else workflow_events
    created_at = metadata.get("created_at", "")
    updated_at = str(events[-1].get("created_at", created_at)) if events else created_at
    latest_event = live_events[-1] if live_events else None
    projected_metadata = {key: value for key, value in metadata.items() if key != "topic"}
    goal = metadata.get("goal")
    has_goal = isinstance(goal, str) and bool(goal.strip())
    return {
        **projected_metadata,
        "title": meeting_title(metadata),
        "goal": goal if has_goal else None,
        "requires_goal": not has_goal,
        "settings_revision": int(metadata.get("settings_revision", 0)),
        "scene": str(metadata.get("scene") or mode.default_scene),
        "created_at": created_at,
        "updated_at": updated_at,
        "status": project_meeting_status(events),
        "activity_status": activity_status or project_activity_status(live_events),
        "last_step_id": latest_event.get("step_id") if latest_event else None,
        "token_usage": project_token_usage(events),
        "estimated_cost": project_estimated_cost(events, model_pricing or {}),
        "tags": metadata.get("tags") or [],
        "pinned": bool(metadata.get("pinned", False)),
        "mode_id": mode.id,
        "participants": meeting_assignments.project(
            metadata,
            project_participants(mode, metadata),
            events=events,
        ),
        "case_files": case_file_manifest(
            metadata.get("case_files") or [], mode_id=metadata.get("mode_id")
        ),
        "courtroom": project_courtroom(metadata, workflow_events),
        "deliberation": {
            "active_epoch_id": deliberation.active_epoch.id,
            "active_epoch_number": deliberation.active_epoch.number,
            "epoch_count": len(deliberation.epochs),
        },
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

    Each check begins with a new token. Only the latest token may record, so
    checks that finish out of order cannot overwrite a newer result. Clearing
    a model also advances its token, invalidating every in-flight check after
    a save or delete.
    """

    def __init__(self) -> None:
        self._checks: dict[str, ModelHealthCheckResult] = {}
        self._generations: dict[str, int] = {}
        self._lock = threading.Lock()

    def begin(self, model_id: str) -> int:
        with self._lock:
            token = self._generations.get(model_id, 0) + 1
            self._generations[model_id] = token
            return token

    def record(self, model_id: str, result: ModelHealthCheckResult, token: int) -> None:
        with self._lock:
            if token != self._generations.get(model_id, 0):
                return
            self._checks[model_id] = result

    def get(self, model_id: str) -> ModelHealthCheckResult | None:
        with self._lock:
            return self._checks.get(model_id)

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
        # Begin before re-reading the config, so a save
        # that races in between is guaranteed to be caught: either it lands
        # before this read (we'd then check the fresh config, but that's
        # fine) or after (its clear() bumps the token past what we
        # captured, so our record() below is correctly dropped as stale).
        check_token = self.store.begin(model_id)
        model = self._find_model(model_id)
        if model is None:
            return
        result = check_model_health(model, self.adapters.get(model.adapter))
        self.store.record(model_id, result, check_token)

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
        self._lifecycle_revisions: dict[str, int] = {}
        self._lock = threading.Lock()

    def start(self, meeting_id: str, operation: Callable[[], None]) -> bool:
        with self._lock:
            current = self._running.get(meeting_id)
            if current is not None and not current.done():
                return False
            future = self._executor.submit(operation)
            self._running[meeting_id] = future
            self._lifecycle_revisions[meeting_id] = (
                self._lifecycle_revisions.get(meeting_id, 0) + 1
            )
        future.add_done_callback(lambda completed: self._finish(meeting_id, completed))
        return True

    def is_running(self, meeting_id: str) -> bool:
        return self.lifecycle_state(meeting_id)[0]

    def lifecycle_state(self, meeting_id: str) -> tuple[bool, int]:
        with self._lock:
            future = self._running.get(meeting_id)
            return (
                future is not None and not future.done(),
                self._lifecycle_revisions.get(meeting_id, 0),
            )

    def _finish(self, meeting_id: str, completed: Future[None]) -> None:
        if not completed.cancelled() and completed.exception() is not None:
            logger.error(
                "Background meeting job failed unexpectedly",
                extra={"meeting_id": meeting_id},
            )
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
        self._lock = threading.RLock()

    def save(self, metadata: dict[str, Any]) -> None:
        with self._lock:
            self._save_unlocked(metadata)

    def update(
        self,
        meeting_id: str,
        transform: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        with self._lock:
            metadata = self._get_unlocked(meeting_id)
            updated = transform(metadata)
            self._save_unlocked(updated)
            return updated

    def _save_unlocked(self, metadata: dict[str, Any]) -> None:
        path = self._metadata_path(metadata["meeting_id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            temp_path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
            os.replace(temp_path, path)
        finally:
            temp_path.unlink(missing_ok=True)

    def get(self, meeting_id: str) -> dict[str, Any]:
        with self._lock:
            return self._get_unlocked(meeting_id)

    def _get_unlocked(self, meeting_id: str) -> dict[str, Any]:
        path = self._metadata_path(meeting_id)
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Unknown meeting: {meeting_id}")
        return json.loads(path.read_text(encoding="utf-8"))

    def list(self) -> list[dict[str, Any]]:
        with self._lock:
            meeting_root = self.data_dir / "meetings"
            if not meeting_root.exists():
                return []
            return [
                json.loads(path.read_text(encoding="utf-8"))
                for path in sorted(meeting_root.glob("*/metadata.json"))
            ]

    def _metadata_path(self, meeting_id: str) -> Path:
        return self.data_dir / "meetings" / meeting_id / "metadata.json"
