from __future__ import annotations

import re
import time
import uuid
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Callable, Literal, Protocol, TypedDict

from ai_council.meetings.execution_state import ActiveExecutionState, MeetingExecutionStateStore
from ai_council.meetings.deliberation import DeliberationEpochs
from ai_council.meetings.repository import MeetingRepository
from ai_council.meetings.transcript import TranscriptProjector
from ai_council.models.adapters import AdapterError, ModelRequest, ModelResponse
from ai_council.models.config import ModelConfig
from ai_council.prompting.parser import OutputParseError
from ai_council.prompting.renderer import PromptRenderer
from ai_council.prompting.schemas import (
    DEFAULT_OUTPUT_SCHEMA_ID,
    DEFAULT_OUTPUT_SCHEMA_REGISTRY,
    ROLE_OUTPUT_V1_SCHEMA,
    OutputSchemaCodec,
    OutputSchemaRegistry,
)

REQUIRED_JSON_SCHEMA = ROLE_OUTPUT_V1_SCHEMA
REQUIRED_JSON_SCHEMA_HASH = DEFAULT_OUTPUT_SCHEMA_REGISTRY.get(DEFAULT_OUTPUT_SCHEMA_ID).hash
LIFECYCLE_STATUSES = {"cancelled", "closed", "reopened"}
CASE_FILES_BY_ROLE_INPUT = "__case_files_by_role"
CASE_FILES_DEFAULT_ROLE = "__default__"
MATERIALS_REVISION_INPUT = "__materials_revision"
MATERIALS_REFS_INPUT = "__materials_refs"


class ModelAdapter(Protocol):
    def complete(self, request: ModelRequest) -> ModelResponse:
        ...


class TokenStreamEvent(TypedDict):
    type: Literal["token_delta"]
    meeting_id: str
    step_id: str
    base_step_id: str
    round: int
    role: str
    attempt: int
    content: str


@dataclass(frozen=True)
class RunnerAdapters:
    by_name: dict[str, ModelAdapter]


@dataclass(frozen=True)
class StepDefinition:
    step_id: str
    role: str
    template_name: str
    output_schema_id: str = DEFAULT_OUTPUT_SCHEMA_ID


@dataclass(frozen=True)
class RelayPlan:
    steps: list[StepDefinition]
    directed_steps: dict[str, StepDefinition]


def latest_unresolved_fixed_relay_failure(
    events: list[dict[str, object]],
    plan: RelayPlan,
) -> dict[str, object] | None:
    step_ids = {step.step_id for step in plan.steps}
    fixed_events = [
        event
        for event in events
        if not event.get("interaction_type")
        and str(event.get("base_step_id") or event.get("step_id")) in step_ids
    ]
    if not fixed_events:
        return None
    latest_round = max(int(event.get("round", 1)) for event in fixed_events)
    latest_by_step: dict[str, dict[str, object]] = {}
    for event in fixed_events:
        if int(event.get("round", 1)) != latest_round:
            continue
        step_id = str(event.get("base_step_id") or event.get("step_id"))
        previous = latest_by_step.get(step_id)
        if previous is None or int(event.get("attempt", 1)) >= int(previous.get("attempt", 1)):
            latest_by_step[step_id] = event
    for step in plan.steps:
        event = latest_by_step.get(step.step_id)
        if event is not None and event.get("status") == "failed":
            return event
    return None


@dataclass(frozen=True)
class ParallelMemberStep:
    step_id: str
    role: str
    template_name: str
    display_name: str
    instance_prompt: str
    index: int
    output_schema_id: str = DEFAULT_OUTPUT_SCHEMA_ID


@dataclass(frozen=True)
class ParallelPlan:
    members: list[ParallelMemberStep]
    synthesis: StepDefinition
    anonymize_synthesis_inputs: bool = False


class MeetingRunner:
    def __init__(
        self,
        *,
        repository: MeetingRepository,
        prompt_renderer: PromptRenderer,
        adapters: RunnerAdapters,
        stream_sink: Callable[[str, TokenStreamEvent], None] | None = None,
        execution_state_store: MeetingExecutionStateStore | None = None,
        output_schemas: OutputSchemaRegistry | None = None,
    ) -> None:
        self.repository = repository
        self.prompt_renderer = prompt_renderer
        self.adapters = adapters
        self.stream_sink = stream_sink
        self.execution_state_store = execution_state_store
        self.output_schemas = output_schemas or DEFAULT_OUTPUT_SCHEMA_REGISTRY
        self.transcript_projector = TranscriptProjector()

    def run_workflow_step(
        self,
        *,
        meeting_id: str,
        goal: str,
        model_assignments: dict[str, ModelConfig],
        step: StepDefinition,
        event_step_id: str,
        inputs: dict[str, Any] | None = None,
        extra_event_fields: dict[str, object] | None = None,
        attempt: int = 1,
    ) -> bool:
        """Run one explicitly identified domain-workflow step.

        The caller owns transition legality; the runner owns prompt, attempt,
        diagnostics, execution reservation, parsing, and append-only output.
        """
        return self._run_step(
            meeting_id=meeting_id,
            goal=goal,
            model_assignments=model_assignments,
            inputs=inputs,
            step=step,
            attempt=attempt,
            round_number=1,
            event_step_id=event_step_id,
            extra_event_fields=extra_event_fields,
            prior_transcript_override=None,
        )

    def start(
        self,
        *,
        meeting_id: str,
        goal: str,
        model_assignments: dict[str, ModelConfig],
        plan: RelayPlan,
        inputs: dict[str, Any] | None = None,
    ) -> None:
        if self._is_terminal(meeting_id):
            return
        round_number = self._next_round_number(meeting_id, plan)
        start_index = self._first_incomplete_step_index(meeting_id, round_number, plan.steps)
        if start_index is None:
            return
        self._run_from_step(
            meeting_id=meeting_id,
            goal=goal,
            model_assignments=model_assignments,
            steps=plan.steps,
            inputs=inputs,
            start_index=start_index,
            attempt_override=None,
            round_number=round_number,
        )

    def retry_failed_step(
        self,
        *,
        meeting_id: str,
        step_id: str,
        goal: str,
        model_assignments: dict[str, ModelConfig],
        plan: RelayPlan,
        inputs: dict[str, Any] | None = None,
        role_display_names: dict[str, str] | None = None,
    ) -> None:
        failed_event = self._latest_event_for_step(meeting_id, step_id)
        if not failed_event or failed_event.get("status") != "failed":
            raise ValueError(f"Step is not failed: {step_id}")
        if failed_event.get("interaction_type") == "directed-role-response":
            self._retry_failed_directed_response(
                meeting_id=meeting_id,
                failed_event=failed_event,
                goal=goal,
                model_assignments=model_assignments,
                inputs=inputs,
                role_display_names=role_display_names or {},
            )
            return
        base_step_id = str(failed_event.get("base_step_id", failed_event.get("step_id")))
        try:
            start_index = next(
                index for index, step in enumerate(plan.steps) if step.step_id == base_step_id
            )
        except StopIteration as error:
            raise ValueError(f"Step is not part of this meeting's mode: {base_step_id}") from error
        self._run_from_step(
            meeting_id=meeting_id,
            goal=goal,
            model_assignments=model_assignments,
            steps=plan.steps,
            inputs=inputs,
            start_index=start_index,
            attempt_override=int(failed_event.get("attempt", 1)) + 1,
            round_number=int(failed_event.get("round", 1)),
        )

    def _retry_failed_directed_response(
        self,
        *,
        meeting_id: str,
        failed_event: dict[str, object],
        goal: str,
        model_assignments: dict[str, ModelConfig],
        inputs: dict[str, Any] | None,
        role_display_names: dict[str, str],
    ) -> None:
        role = str(failed_event.get("role", ""))
        if role not in model_assignments:
            raise ValueError(f"Missing model assignment for role: {role}")
        instruction_event_id = str(failed_event.get("in_response_to_event_id", ""))
        instruction_event = next(
            (
                event
                for event in self._active_events(meeting_id)
                if event.get("event_id") == instruction_event_id
            ),
            None,
        )
        if (
            not instruction_event
            or instruction_event.get("interaction_type") != "directed-role-instruction"
        ):
            raise ValueError("Directed response instruction is unavailable for retry")
        instruction = str(instruction_event.get("content", "")).strip()
        if not instruction:
            raise ValueError("Directed response instruction is unavailable for retry")
        base_step_id = str(failed_event.get("base_step_id", failed_event.get("step_id")))
        step = StepDefinition(
            step_id=base_step_id,
            role=role,
            template_name="directed_role_response",
            output_schema_id=str(
                failed_event.get("output_schema_id") or DEFAULT_OUTPUT_SCHEMA_ID
            ),
        )
        self._run_step(
            meeting_id=meeting_id,
            goal=goal,
            model_assignments=model_assignments,
            inputs=inputs,
            step=step,
            attempt=int(failed_event.get("attempt", 1)) + 1,
            round_number=int(failed_event.get("round", 1)),
            event_step_id=str(failed_event["step_id"]),
            extra_event_fields={
                "interaction_type": "directed-role-response",
                "directed_sequence": int(failed_event.get("directed_sequence", 1)),
                "in_response_to_event_id": instruction_event_id,
                **{
                    key: failed_event[key]
                    for key in ("docket_revision", "issue_id")
                    if key in failed_event
                },
            },
            prior_transcript_override=None,
            prompt_input_overrides={
                "instruction": instruction,
                "role_display_name": role_display_names.get(role, role),
            },
        )

    def respond_as_role(
        self,
        *,
        meeting_id: str,
        goal: str,
        role: str,
        role_display_name: str,
        instruction: str,
        model_assignments: dict[str, ModelConfig],
        plan: RelayPlan,
        inputs: dict[str, Any] | None = None,
        context_fields: dict[str, object] | None = None,
    ) -> None:
        if self._is_terminal(meeting_id):
            return
        instruction = instruction.strip()
        if not instruction:
            raise ValueError("Directed role instruction cannot be blank")
        step = plan.directed_steps.get(role)
        if step is None:
            raise ValueError(f"Unknown role: {role}")
        if role not in model_assignments:
            raise ValueError(f"Missing model assignment for role: {role}")
        directed_sequence = self._next_directed_response_number(meeting_id)
        context_fields = context_fields or {}
        instruction_event_id = f"{meeting_id}:human-directed-message:{uuid.uuid4().hex}"
        self.repository.append_event(
            meeting_id,
            {
                "event_id": instruction_event_id,
                "meeting_id": meeting_id,
                "step_id": "human-directed-message",
                "role": "Human",
                "attempt": 1,
                "status": "completed",
                "interaction_type": "directed-role-instruction",
                "target_role_id": role,
                "content": instruction,
                **self._audit_event_fields(inputs),
                **context_fields,
            },
        )
        directed_step = StepDefinition(
            step_id=step.step_id,
            role=step.role,
            template_name="directed_role_response",
            output_schema_id=step.output_schema_id,
        )
        self._run_step(
            meeting_id=meeting_id,
            goal=goal,
            model_assignments=model_assignments,
            inputs=inputs,
            step=directed_step,
            attempt=1,
            round_number=self._next_round_number(meeting_id, plan),
            event_step_id=f"directed-{directed_sequence}-{role.lower()}-response",
            extra_event_fields={
                "interaction_type": "directed-role-response",
                "directed_sequence": directed_sequence,
                "in_response_to_event_id": instruction_event_id,
                **context_fields,
            },
            prior_transcript_override=None,
            prompt_input_overrides={
                "instruction": instruction,
                "role_display_name": role_display_name,
            },
        )

    def respond_as_sequence(
        self,
        *,
        meeting_id: str,
        goal: str,
        roles: list[str],
        model_assignments: dict[str, ModelConfig],
        plan: RelayPlan,
        inputs: dict[str, Any] | None = None,
    ) -> None:
        if self._is_terminal(meeting_id):
            return
        if not roles:
            raise ValueError("Role sequence cannot be empty")
        if len(set(roles)) != len(roles):
            raise ValueError("Role sequence cannot contain duplicate roles")

        steps: list[StepDefinition] = []
        for role in roles:
            step = plan.directed_steps.get(role)
            if step is None:
                raise ValueError(f"Unknown role: {role}")
            if role not in model_assignments:
                raise ValueError(f"Missing model assignment for role: {role}")
            steps.append(step)

        sequence_number = self._next_role_sequence_number(meeting_id)
        round_number = self._next_round_number(meeting_id, plan)
        for index, step in enumerate(steps, start=1):
            if self._is_terminal(meeting_id):
                return
            if not self._run_step(
                meeting_id=meeting_id,
                goal=goal,
                model_assignments=model_assignments,
                inputs=inputs,
                step=step,
                attempt=1,
                round_number=round_number,
                event_step_id=f"sequence-{sequence_number}-{step.role.lower()}-response",
                extra_event_fields={
                    "interaction_type": "role-sequence-response",
                    "sequence": sequence_number,
                    "sequence_index": index,
                },
                prior_transcript_override=None,
            ):
                return

    def start_parallel(
        self,
        *,
        meeting_id: str,
        goal: str,
        model_assignments: dict[str, ModelConfig],
        plan: ParallelPlan,
        inputs: dict[str, Any] | None = None,
    ) -> None:
        if self._is_terminal(meeting_id):
            return
        round_number = self._next_parallel_round_number(meeting_id)
        events = self._active_events(meeting_id)
        if self._parallel_synthesis_completed(events, round_number):
            return
        if self._parallel_has_failed_member(events, round_number):
            return

        pending_members = [
            member
            for member in plan.members
            if not self._parallel_member_completed(events, member, round_number)
        ]
        if pending_members:
            self._run_parallel_members(
                meeting_id=meeting_id,
                goal=goal,
                model_assignments=model_assignments,
                members=pending_members,
                inputs=inputs,
                round_number=round_number,
                attempt=1,
            )
        self._run_parallel_synthesis_if_ready(
            meeting_id=meeting_id,
            goal=goal,
            model_assignments=model_assignments,
            plan=plan,
            inputs=inputs,
            round_number=round_number,
        )

    def retry_failed_parallel_step(
        self,
        *,
        meeting_id: str,
        step_id: str,
        goal: str,
        model_assignments: dict[str, ModelConfig],
        plan: ParallelPlan,
        inputs: dict[str, Any] | None = None,
    ) -> None:
        failed_event = self._latest_event_for_step(meeting_id, step_id)
        if not failed_event or failed_event.get("status") != "failed":
            raise ValueError(f"Step is not failed: {step_id}")
        base_step_id = str(failed_event.get("base_step_id", failed_event.get("step_id")))
        member = next((candidate for candidate in plan.members if candidate.step_id == base_step_id), None)
        if member is None:
            raise ValueError(f"Step is not part of this meeting's parallel fanout: {base_step_id}")
        round_number = int(failed_event.get("round", 1))
        attempt = int(failed_event.get("attempt", 1)) + 1
        self._run_parallel_members(
            meeting_id=meeting_id,
            goal=goal,
            model_assignments=model_assignments,
            members=[member],
            inputs=inputs,
            round_number=round_number,
            attempt=attempt,
        )
        self._run_parallel_synthesis_if_ready(
            meeting_id=meeting_id,
            goal=goal,
            model_assignments=model_assignments,
            plan=plan,
            inputs=inputs,
            round_number=round_number,
        )

    def cancel(self, meeting_id: str) -> None:
        if self._is_terminal(meeting_id):
            return
        self.repository.append_event(
            meeting_id,
            {
                "event_id": self._event_id(meeting_id, f"{meeting_id}:cancelled"),
                "meeting_id": meeting_id,
                "step_id": "meeting",
                "role": "System",
                "attempt": 1,
                "status": "cancelled",
            },
        )
        for adapter in self.adapters.by_name.values():
            cancel_active_call = getattr(adapter, "cancel", None)
            if callable(cancel_active_call):
                cancel_active_call(meeting_id)

    def close(self, meeting_id: str) -> None:
        if self._is_terminal(meeting_id):
            return
        self.repository.append_event(
            meeting_id,
            {
                "event_id": self._event_id(meeting_id, f"{meeting_id}:closed"),
                "meeting_id": meeting_id,
                "step_id": "meeting",
                "role": "System",
                "attempt": 1,
                "status": "closed",
            },
        )

    def _run_from_step(
        self,
        *,
        meeting_id: str,
        goal: str,
        model_assignments: dict[str, ModelConfig],
        steps: list[StepDefinition],
        inputs: dict[str, Any] | None,
        start_index: int,
        attempt_override: int | None,
        round_number: int,
    ) -> None:
        for index, step in enumerate(steps[start_index:], start=start_index):
            if self._is_terminal(meeting_id):
                return
            attempt = attempt_override if index == start_index and attempt_override else 1
            if not self._run_step(
                meeting_id=meeting_id,
                goal=goal,
                model_assignments=model_assignments,
                inputs=inputs,
                step=step,
                attempt=attempt,
                round_number=round_number,
                event_step_id=None,
                extra_event_fields=None,
                prior_transcript_override=None,
            ):
                return

    def _run_step(
        self,
        *,
        meeting_id: str,
        goal: str,
        model_assignments: dict[str, ModelConfig],
        inputs: dict[str, Any] | None,
        step: StepDefinition,
        attempt: int,
        round_number: int,
        event_step_id: str | None,
        extra_event_fields: dict[str, object] | None,
        prior_transcript_override: str | None,
        prompt_input_overrides: dict[str, str] | None = None,
        parse_retries_remaining: int = 1,
    ) -> bool:
        if self._is_terminal(meeting_id):
            return False
        config = model_assignments[step.role]
        event_step_id = event_step_id or self._event_step_id(step.step_id, round_number)
        extra_event_fields = extra_event_fields or {}
        extra_event_fields = {
            **extra_event_fields,
            **self._audit_event_fields(inputs),
        }
        output_schema = self.output_schemas.get(step.output_schema_id)
        prompt_metadata = self._prompt_metadata(step.template_name, output_schema)
        prompt = self.prompt_renderer.render(
            template_name=step.template_name,
            role=step.role,
            goal=goal,
            prior_transcript=(
                prior_transcript_override
                if prior_transcript_override is not None
                else self.transcript_projector.project(
                    self._active_events(meeting_id),
                    title=goal,
                )
            ),
            required_json_schema=output_schema.schema,
            inputs=self._prompt_inputs_for_role(
                inputs, step.role, extra=prompt_input_overrides
            ),
        )

        def emit_token_delta(content: str) -> None:
            if self.stream_sink is None:
                return
            self.stream_sink(
                meeting_id,
                {
                    "type": "token_delta",
                    "meeting_id": meeting_id,
                    "step_id": event_step_id,
                    "base_step_id": step.step_id,
                    "round": round_number,
                    "role": step.role,
                    "attempt": attempt,
                    "content": content,
                },
            )

        self._save_active_execution(
            meeting_id=meeting_id,
            step=step,
            event_step_id=event_step_id,
            attempt=attempt,
            round_number=round_number,
            model_config_id=config.id,
            adapter=config.adapter,
            prompt=prompt,
            prompt_metadata=prompt_metadata,
            extra_event_fields=extra_event_fields,
        )
        started_at = datetime.now(UTC).isoformat()
        started_clock = time.monotonic()
        response: ModelResponse | None = None
        try:
            response = self.adapters.by_name[config.adapter].complete(
                ModelRequest(
                    prompt=prompt,
                    model_config=config,
                    output_schema_id=output_schema.id,
                    meeting_id=meeting_id,
                    on_token_delta=emit_token_delta,
                )
            )
            parsed_output = output_schema.parse(response.raw_output)
        except OutputParseError as error:
            self._clear_active_execution(meeting_id)
            failed_event: dict[str, object] = {
                "event_id": self._event_id(
                    meeting_id, f"{meeting_id}:{event_step_id}:attempt-{attempt}:failed"
                ),
                "meeting_id": meeting_id,
                "step_id": event_step_id,
                "base_step_id": step.step_id,
                "round": round_number,
                "role": step.role,
                "attempt": attempt,
                "model_config_id": config.id,
                "adapter": config.adapter,
                "prompt_messages": [{"role": "user", "content": prompt}],
                "raw_output": error.raw_output,
                "status": "failed",
                "failure_kind": "parse_error",
                "error": str(error),
                "retry_scheduled": bool(parse_retries_remaining),
                **self._timing_fields(started_at, started_clock),
                **prompt_metadata,
                **extra_event_fields,
            }
            if response is not None and response.token_usage is not None:
                failed_event["token_usage"] = response.token_usage
            if self._is_terminal(meeting_id):
                self.repository.append_event(
                    meeting_id, self._discarded_terminal_attempt(failed_event)
                )
                return False
            self.repository.append_event(meeting_id, failed_event)
            if parse_retries_remaining:
                return self._run_step(
                    meeting_id=meeting_id,
                    goal=goal,
                    model_assignments=model_assignments,
                    inputs=inputs,
                    step=step,
                    attempt=attempt + 1,
                    round_number=round_number,
                    event_step_id=event_step_id,
                    extra_event_fields=extra_event_fields,
                    prior_transcript_override=prior_transcript_override,
                    prompt_input_overrides=prompt_input_overrides,
                    parse_retries_remaining=parse_retries_remaining - 1,
                )
            return False
        except (AdapterError, KeyError) as error:
            self._clear_active_execution(meeting_id)
            failed_event = {
                "event_id": self._event_id(
                    meeting_id, f"{meeting_id}:{event_step_id}:attempt-{attempt}:failed"
                ),
                "meeting_id": meeting_id,
                "step_id": event_step_id,
                "base_step_id": step.step_id,
                "round": round_number,
                "role": step.role,
                "attempt": attempt,
                "model_config_id": config.id,
                "adapter": config.adapter,
                "prompt_messages": [{"role": "user", "content": prompt}],
                "status": "failed",
                "failure_kind": self._failure_kind(error),
                "error": str(error),
                "retry_scheduled": False,
                **self._timing_fields(started_at, started_clock),
                **prompt_metadata,
                **extra_event_fields,
            }
            self._add_adapter_excerpts(failed_event, error)
            if self._is_terminal(meeting_id):
                self.repository.append_event(
                    meeting_id, self._discarded_terminal_attempt(failed_event)
                )
                return False
            self.repository.append_event(meeting_id, failed_event)
            return False

        self._clear_active_execution(meeting_id)
        completed_event = {
            "event_id": self._event_id(
                meeting_id, f"{meeting_id}:{event_step_id}:attempt-{attempt}:completed"
            ),
            "meeting_id": meeting_id,
            "step_id": event_step_id,
            "base_step_id": step.step_id,
            "round": round_number,
            "role": step.role,
            "attempt": attempt,
            "model_config_id": config.id,
            "adapter": config.adapter,
            **prompt_metadata,
            "prompt_messages": [{"role": "user", "content": prompt}],
            "raw_output": response.raw_output,
            "parsed_output": parsed_output,
            "status": "completed",
            **self._timing_fields(started_at, started_clock),
            **extra_event_fields,
        }
        if response.token_usage is not None:
            completed_event["token_usage"] = response.token_usage
        if self._is_terminal(meeting_id):
            self.repository.append_event(
                meeting_id, self._discarded_terminal_attempt(completed_event)
            )
            return False
        self.repository.append_event(
            meeting_id,
            completed_event,
        )
        return True

    def _run_parallel_members(
        self,
        *,
        meeting_id: str,
        goal: str,
        model_assignments: dict[str, ModelConfig],
        members: list[ParallelMemberStep],
        inputs: dict[str, Any] | None,
        round_number: int,
        attempt: int,
    ) -> None:
        if not members:
            return
        with ThreadPoolExecutor(max_workers=len(members)) as executor:
            futures = [
                executor.submit(
                    self._build_parallel_member_events,
                    meeting_id=meeting_id,
                    goal=goal,
                    model_assignments=model_assignments,
                    member=member,
                    inputs=inputs,
                    round_number=round_number,
                    attempt=attempt,
                )
                for member in members
            ]
            event_groups = [future.result() for future in futures]
        for events in event_groups:
            for event in events:
                self.repository.append_event(meeting_id, event)

    def _build_parallel_member_events(
        self,
        *,
        meeting_id: str,
        goal: str,
        model_assignments: dict[str, ModelConfig],
        member: ParallelMemberStep,
        inputs: dict[str, Any] | None,
        round_number: int,
        attempt: int,
    ) -> list[dict[str, object]]:
        config = model_assignments[member.role]
        event_step_id = f"fanout-{round_number}-member-{member.index}"
        output_schema = self.output_schemas.get(member.output_schema_id)
        prompt_metadata = self._prompt_metadata(member.template_name, output_schema)
        prompt = self.prompt_renderer.render(
            template_name=member.template_name,
            role=member.role,
            goal=goal,
            prior_transcript=self.transcript_projector.project(
                self._active_events(meeting_id),
                title=goal,
            ),
            required_json_schema=output_schema.schema,
            inputs=self._prompt_inputs_for_role(
                inputs,
                member.role,
                extra={
                    "instance_prompt": member.instance_prompt,
                    "display_name": member.display_name,
                },
            ),
        )
        events: list[dict[str, object]] = []
        audit_event_fields = self._audit_event_fields(inputs)
        for current_attempt in (attempt, attempt + 1):
            if current_attempt != attempt and self._is_terminal(meeting_id):
                return events
            started_at = datetime.now(UTC).isoformat()
            started_clock = time.monotonic()
            response: ModelResponse | None = None
            try:
                response = self.adapters.by_name[config.adapter].complete(
                    ModelRequest(
                        prompt=prompt,
                        model_config=config,
                        output_schema_id=output_schema.id,
                        meeting_id=meeting_id,
                    )
                )
                parsed_output = output_schema.parse(response.raw_output)
            except OutputParseError as error:
                failure_event = self._parallel_member_failure_event(
                        meeting_id=meeting_id,
                        event_step_id=event_step_id,
                        member=member,
                        round_number=round_number,
                        attempt=current_attempt,
                        error=error,
                        config=config,
                        prompt=prompt,
                        response=response,
                        retry_scheduled=current_attempt == attempt,
                        started_at=started_at,
                        started_clock=started_clock,
                        prompt_metadata=prompt_metadata,
                    )
                failure_event.update(audit_event_fields)
                if self._is_terminal(meeting_id):
                    events.append(self._discarded_terminal_attempt(failure_event))
                    return events
                events.append(failure_event)
                continue
            except (AdapterError, KeyError) as error:
                failure_event = self._parallel_member_failure_event(
                        meeting_id=meeting_id,
                        event_step_id=event_step_id,
                        member=member,
                        round_number=round_number,
                        attempt=current_attempt,
                        error=error,
                        config=config,
                        prompt=prompt,
                        response=None,
                        retry_scheduled=False,
                        started_at=started_at,
                        started_clock=started_clock,
                        prompt_metadata=prompt_metadata,
                    )
                failure_event.update(audit_event_fields)
                if self._is_terminal(meeting_id):
                    failure_event = self._discarded_terminal_attempt(failure_event)
                events.append(failure_event)
                return events

            completed_event: dict[str, object] = {
                "event_id": self._event_id(
                    meeting_id,
                    f"{meeting_id}:{event_step_id}:attempt-{current_attempt}:completed",
                ),
                "meeting_id": meeting_id,
                "step_id": event_step_id,
                "base_step_id": member.step_id,
                "round": round_number,
                "role": member.role,
                "attempt": current_attempt,
                "model_config_id": config.id,
                "adapter": config.adapter,
                **prompt_metadata,
                "prompt_messages": [{"role": "user", "content": prompt}],
                "raw_output": response.raw_output,
                "parsed_output": parsed_output,
                "status": "completed",
                **self._timing_fields(started_at, started_clock),
            }
            completed_event.update(audit_event_fields)
            if response.token_usage is not None:
                completed_event["token_usage"] = response.token_usage
            if self._is_terminal(meeting_id):
                completed_event = self._discarded_terminal_attempt(completed_event)
            events.append(completed_event)
            return events
        return events

    def _parallel_member_failure_event(
        self,
        *,
        meeting_id: str,
        event_step_id: str,
        member: ParallelMemberStep,
        round_number: int,
        attempt: int,
        error: Exception,
        config: ModelConfig,
        prompt: str,
        response: ModelResponse | None,
        retry_scheduled: bool,
        started_at: str,
        started_clock: float,
        prompt_metadata: dict[str, object],
    ) -> dict[str, object]:
        event: dict[str, object] = {
            "event_id": self._event_id(
                meeting_id, f"{meeting_id}:{event_step_id}:attempt-{attempt}:failed"
            ),
            "meeting_id": meeting_id,
            "step_id": event_step_id,
            "base_step_id": member.step_id,
            "round": round_number,
            "role": member.role,
            "attempt": attempt,
            "model_config_id": config.id,
            "adapter": config.adapter,
            "prompt_messages": [{"role": "user", "content": prompt}],
            "status": "failed",
            "failure_kind": self._failure_kind(error),
            "error": str(error),
            "retry_scheduled": retry_scheduled,
            **self._timing_fields(started_at, started_clock),
            **prompt_metadata,
        }
        if isinstance(error, OutputParseError):
            event["raw_output"] = error.raw_output
        if response is not None and response.token_usage is not None:
            event["token_usage"] = response.token_usage
        self._add_adapter_excerpts(event, error)
        return event

    @staticmethod
    def _timing_fields(started_at: str, started_clock: float) -> dict[str, object]:
        return {
            "started_at": started_at,
            "completed_at": datetime.now(UTC).isoformat(),
            "duration_ms": max(0, round((time.monotonic() - started_clock) * 1000)),
        }

    @staticmethod
    def _failure_kind(error: Exception) -> str:
        if isinstance(error, OutputParseError):
            return "parse_error"
        if isinstance(error, AdapterError):
            return error.failure_kind
        return "configuration_error"

    @staticmethod
    def _add_adapter_excerpts(event: dict[str, object], error: Exception) -> None:
        if not isinstance(error, AdapterError):
            return
        if error.stdout_excerpt is not None:
            event["adapter_stdout_excerpt"] = error.stdout_excerpt
        if error.stderr_excerpt is not None:
            event["adapter_stderr_excerpt"] = error.stderr_excerpt

    @staticmethod
    def _discarded_terminal_attempt(event: dict[str, object]) -> dict[str, object]:
        discarded = dict(event)
        original_error = discarded.get("error")
        event_id = str(discarded["event_id"])
        discarded.update(
            {
                "event_id": f"{event_id.rsplit(':', 1)[0]}:interrupted",
                "status": "failed",
                "failure_kind": "interrupted",
                "retry_scheduled": False,
                "result_discarded": True,
                "error": "Model attempt was interrupted because the meeting became terminal; result discarded.",
            }
        )
        if original_error:
            discarded["error"] = f"{discarded['error']} Original error: {original_error}"
        return discarded

    def _run_parallel_synthesis_if_ready(
        self,
        *,
        meeting_id: str,
        goal: str,
        model_assignments: dict[str, ModelConfig],
        plan: ParallelPlan,
        inputs: dict[str, Any] | None,
        round_number: int,
    ) -> None:
        events = self._active_events(meeting_id)
        if self._parallel_synthesis_completed(events, round_number):
            return
        if not all(self._parallel_member_completed(events, member, round_number) for member in plan.members):
            return
        self._run_step(
            meeting_id=meeting_id,
            goal=goal,
            model_assignments=model_assignments,
            inputs=self._synthesis_inputs(
                inputs,
                events,
                plan,
                round_number,
            ),
            step=plan.synthesis,
            attempt=1,
            round_number=round_number,
            event_step_id=f"synthesis-{round_number}",
            extra_event_fields=None,
            prior_transcript_override="" if plan.anonymize_synthesis_inputs else None,
        )

    def _save_active_execution(
        self,
        *,
        meeting_id: str,
        step: StepDefinition,
        event_step_id: str,
        attempt: int,
        round_number: int,
        model_config_id: str,
        adapter: str,
        prompt: str,
        prompt_metadata: dict[str, object],
        extra_event_fields: dict[str, object],
    ) -> None:
        if self.execution_state_store is None:
            return
        state: ActiveExecutionState = {
            "meeting_id": meeting_id,
            "step_id": event_step_id,
            "base_step_id": step.step_id,
            "round": round_number,
            "role": step.role,
            "attempt": attempt,
            "model_config_id": model_config_id,
            "adapter": adapter,
            "prompt_messages": [{"role": "user", "content": prompt}],
            "status": "running",
            "deliberation_epoch_id": DeliberationEpochs.view(
                self.repository.read_events(meeting_id)
            ).active_epoch.id,
            **prompt_metadata,
        }
        for key in [
            "interaction_type",
            "directed_sequence",
            "in_response_to_event_id",
            "sequence",
            "sequence_index",
            "docket_revision",
            "issue_id",
            "issue_phase",
            "courtroom_operation",
            "materials_revision",
            "materials_refs",
        ]:
            value = extra_event_fields.get(key)
            if isinstance(value, (str, int, list)):
                state[key] = value
        self.execution_state_store.save_active(meeting_id, state)

    def _clear_active_execution(self, meeting_id: str) -> None:
        if self.execution_state_store is not None:
            self.execution_state_store.clear_active(meeting_id)

    def _prompt_metadata(
        self,
        template_name: str,
        output_schema: OutputSchemaCodec,
    ) -> dict[str, object]:
        return {
            "prompt_template_name": template_name,
            "prompt_template_hash": self.prompt_renderer.template_hash(template_name),
            "output_schema_id": output_schema.id,
            "output_schema_hash": output_schema.hash,
        }

    def _prompt_inputs_for_role(
        self,
        inputs: dict[str, Any] | None,
        role: str,
        *,
        extra: dict[str, str] | None = None,
    ) -> dict[str, str]:
        rendered = {
            str(key): str(value)
            for key, value in (inputs or {}).items()
            if key
            not in {
                CASE_FILES_BY_ROLE_INPUT,
                MATERIALS_REVISION_INPUT,
                MATERIALS_REFS_INPUT,
            }
        }
        case_files_by_role = (inputs or {}).get(CASE_FILES_BY_ROLE_INPUT)
        if isinstance(case_files_by_role, dict):
            rendered["case_files"] = str(
                case_files_by_role.get(role, case_files_by_role.get(CASE_FILES_DEFAULT_ROLE, ""))
            )
        if extra:
            rendered.update(extra)
        return rendered

    @staticmethod
    def _audit_event_fields(inputs: dict[str, Any] | None) -> dict[str, object]:
        audit: dict[str, object] = {}
        revision = (inputs or {}).get(MATERIALS_REVISION_INPUT)
        if isinstance(revision, int):
            audit["materials_revision"] = revision
        references = (inputs or {}).get(MATERIALS_REFS_INPUT)
        if isinstance(references, list):
            audit["materials_refs"] = deepcopy(references)
        return audit

    def _active_events(self, meeting_id: str) -> list[dict[str, Any]]:
        return DeliberationEpochs.view(
            self.repository.read_events(meeting_id)
        ).active_events

    def _event_id(self, meeting_id: str, legacy_event_id: str) -> str:
        return DeliberationEpochs.view(
            self.repository.read_events(meeting_id)
        ).event_id(legacy_event_id)

    def _is_terminal(self, meeting_id: str) -> bool:
        latest_lifecycle_status = None
        for event in self.repository.read_events(meeting_id):
            status = event.get("status")
            if status in LIFECYCLE_STATUSES:
                latest_lifecycle_status = status
        return latest_lifecycle_status in {"cancelled", "closed"}

    def _latest_event_for_step(self, meeting_id: str, step_id: str) -> dict[str, object] | None:
        matching_events = [
            event
            for event in self._active_events(meeting_id)
            if event.get("step_id") == step_id or event.get("base_step_id") == step_id
        ]
        return matching_events[-1] if matching_events else None

    def _first_incomplete_step_index(
        self, meeting_id: str, round_number: int, steps: list[StepDefinition]
    ) -> int | None:
        events = self._active_events(meeting_id)
        for index, step in enumerate(steps):
            event_step_id = self._event_step_id(step.step_id, round_number)
            matching_events = [event for event in events if event.get("step_id") == event_step_id]
            if not matching_events:
                return index
            if matching_events[-1].get("status") != "completed":
                return None
        return None

    def _next_round_number(self, meeting_id: str, plan: RelayPlan) -> int:
        final_step_id = plan.steps[-1].step_id
        completed_final_step_events = [
            event
            for event in self._active_events(meeting_id)
            if event.get("status") == "completed"
            and event.get("base_step_id", event.get("step_id")) == final_step_id
        ]
        return len(completed_final_step_events) + 1

    def _next_parallel_round_number(self, meeting_id: str) -> int:
        completed_synthesis_events = [
            event
            for event in self._active_events(meeting_id)
            if event.get("status") == "completed"
            and event.get("base_step_id", event.get("step_id")) == "synthesis"
        ]
        return len(completed_synthesis_events) + 1

    def _parallel_member_completed(
        self,
        events: list[dict[str, object]],
        member: ParallelMemberStep,
        round_number: int,
    ) -> bool:
        matching = [
            event
            for event in events
            if event.get("round") == round_number
            and event.get("base_step_id", event.get("step_id")) == member.step_id
        ]
        return bool(matching) and matching[-1].get("status") == "completed"

    def _parallel_has_failed_member(
        self,
        events: list[dict[str, object]],
        round_number: int,
    ) -> bool:
        latest_by_step: dict[str, dict[str, object]] = {}
        for event in events:
            if event.get("round") != round_number:
                continue
            base_step_id = str(event.get("base_step_id", event.get("step_id")))
            if not base_step_id.startswith("member-"):
                continue
            latest_by_step[base_step_id] = event
        return any(event.get("status") == "failed" for event in latest_by_step.values())

    def _parallel_synthesis_completed(
        self,
        events: list[dict[str, object]],
        round_number: int,
    ) -> bool:
        return any(
            event.get("round") == round_number
            and event.get("base_step_id", event.get("step_id")) == "synthesis"
            and event.get("status") == "completed"
            for event in events
        )

    def _synthesis_inputs(
        self,
        inputs: dict[str, Any] | None,
        events: list[dict[str, object]],
        plan: ParallelPlan,
        round_number: int,
    ) -> dict[str, str]:
        return {
            **(inputs or {}),
            "fanout_outputs": self._fanout_outputs(
                events,
                plan.members,
                round_number,
                anonymize=plan.anonymize_synthesis_inputs,
            ),
        }

    def _fanout_outputs(
        self,
        events: list[dict[str, object]],
        members: list[ParallelMemberStep],
        round_number: int,
        *,
        anonymize: bool = False,
    ) -> str:
        lines: list[str] = []
        for label_index, member in enumerate(members, start=1):
            matching = [
                event
                for event in events
                if event.get("round") == round_number
                and event.get("base_step_id", event.get("step_id")) == member.step_id
                and event.get("status") == "completed"
            ]
            if not matching:
                continue
            parsed = matching[-1].get("parsed_output")
            summary = parsed.get("summary") if isinstance(parsed, dict) else ""
            recommendation = parsed.get("recommendation") if isinstance(parsed, dict) else ""
            if anonymize:
                label = self._anonymous_member_label(label_index)
                summary = self._strip_self_identification(str(summary))
                recommendation = self._strip_self_identification(str(recommendation))
                lines.append(
                    f"{label}\n"
                    f"Summary: {summary}\n"
                    f"Recommendation: {recommendation}"
                )
                continue
            lines.append(
                f"{member.role} ({member.display_name})\n"
                f"Summary: {summary}\n"
                f"Recommendation: {recommendation}"
            )
        return "\n\n".join(lines)

    @staticmethod
    def _anonymous_member_label(index: int) -> str:
        alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        if 1 <= index <= len(alphabet):
            return f"委員{alphabet[index - 1]}"
        return f"委員{index}"

    @staticmethod
    def _strip_self_identification(value: str) -> str:
        patterns = [
            r"\bAs\s+ChatGPT,?\s*",
            r"\bAs\s+an\s+AI\s+language\s+model,?\s*",
            r"身為\s*ChatGPT[，,]?\s*",
            r"作為\s*ChatGPT[，,]?\s*",
            r"身為\s*AI\s*語言模型[，,]?\s*",
            r"作為\s*AI\s*語言模型[，,]?\s*",
        ]
        result = value
        for pattern in patterns:
            result = re.sub(pattern, "", result, flags=re.IGNORECASE)
        return result.strip()

    def _next_directed_response_number(self, meeting_id: str) -> int:
        directed_events = [
            event
            for event in self._active_events(meeting_id)
            if event.get("interaction_type") == "directed-role-response"
        ]
        existing_sequences = {
            int(event["directed_sequence"])
            for event in directed_events
            if "directed_sequence" in event
        }
        return (max(existing_sequences) if existing_sequences else 0) + 1

    def _next_role_sequence_number(self, meeting_id: str) -> int:
        sequence_events = [
            event
            for event in self._active_events(meeting_id)
            if event.get("interaction_type") == "role-sequence-response"
        ]
        existing_sequences = {
            int(event["sequence"])
            for event in sequence_events
            if "sequence" in event
        }
        return (max(existing_sequences) if existing_sequences else 0) + 1

    @staticmethod
    def _event_step_id(base_step_id: str, round_number: int) -> str:
        if round_number == 1:
            return base_step_id
        return f"round-{round_number}-{base_step_id}"
