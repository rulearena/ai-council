from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Literal, Protocol, TypedDict

from ai_council.meetings.execution_state import ActiveExecutionState, MeetingExecutionStateStore
from ai_council.meetings.repository import MeetingRepository
from ai_council.meetings.transcript import TranscriptProjector
from ai_council.models.adapters import AdapterError, ModelRequest, ModelResponse
from ai_council.models.config import ModelConfig
from ai_council.prompting.parser import OutputParseError, RoleOutputParser
from ai_council.prompting.renderer import PromptRenderer

REQUIRED_JSON_SCHEMA = (
    '{"summary":"string","arguments":[{"title":"string","detail":"string"}],'
    '"risks":[{"title":"string","detail":"string"}],"recommendation":"string"}'
)
REQUIRED_JSON_SCHEMA_HASH = hashlib.sha256(REQUIRED_JSON_SCHEMA.encode("utf-8")).hexdigest()
LIFECYCLE_STATUSES = {"cancelled", "closed", "reopened"}
CASE_FILES_BY_ROLE_INPUT = "__case_files_by_role"


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


@dataclass(frozen=True)
class RelayPlan:
    steps: list[StepDefinition]
    directed_steps: dict[str, StepDefinition]


@dataclass(frozen=True)
class ParallelMemberStep:
    step_id: str
    role: str
    template_name: str
    display_name: str
    instance_prompt: str
    index: int


@dataclass(frozen=True)
class ParallelPlan:
    members: list[ParallelMemberStep]
    synthesis: StepDefinition


class MeetingRunner:
    def __init__(
        self,
        *,
        repository: MeetingRepository,
        prompt_renderer: PromptRenderer,
        adapters: RunnerAdapters,
        stream_sink: Callable[[str, TokenStreamEvent], None] | None = None,
        execution_state_store: MeetingExecutionStateStore | None = None,
    ) -> None:
        self.repository = repository
        self.prompt_renderer = prompt_renderer
        self.adapters = adapters
        self.stream_sink = stream_sink
        self.execution_state_store = execution_state_store
        self.output_parser = RoleOutputParser()
        self.transcript_projector = TranscriptProjector()

    def start(
        self,
        *,
        meeting_id: str,
        topic: str,
        model_assignments: dict[str, ModelConfig],
        plan: RelayPlan,
        inputs: dict[str, str] | None = None,
    ) -> None:
        if self._is_terminal(meeting_id):
            return
        round_number = self._next_round_number(meeting_id, plan)
        start_index = self._first_incomplete_step_index(meeting_id, round_number, plan.steps)
        if start_index is None:
            return
        self._run_from_step(
            meeting_id=meeting_id,
            topic=topic,
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
        topic: str,
        model_assignments: dict[str, ModelConfig],
        plan: RelayPlan,
        inputs: dict[str, str] | None = None,
    ) -> None:
        failed_event = self._latest_event_for_step(meeting_id, step_id)
        if not failed_event or failed_event.get("status") != "failed":
            raise ValueError(f"Step is not failed: {step_id}")
        base_step_id = str(failed_event.get("base_step_id", failed_event.get("step_id")))
        try:
            start_index = next(
                index for index, step in enumerate(plan.steps) if step.step_id == base_step_id
            )
        except StopIteration as error:
            raise ValueError(f"Step is not part of this meeting's mode: {base_step_id}") from error
        self._run_from_step(
            meeting_id=meeting_id,
            topic=topic,
            model_assignments=model_assignments,
            steps=plan.steps,
            inputs=inputs,
            start_index=start_index,
            attempt_override=int(failed_event.get("attempt", 1)) + 1,
            round_number=int(failed_event.get("round", 1)),
        )

    def respond_as_role(
        self,
        *,
        meeting_id: str,
        topic: str,
        role: str,
        model_assignments: dict[str, ModelConfig],
        plan: RelayPlan,
        inputs: dict[str, str] | None = None,
    ) -> None:
        if self._is_terminal(meeting_id):
            return
        step = plan.directed_steps.get(role)
        if step is None:
            raise ValueError(f"Unknown role: {role}")
        if role not in model_assignments:
            raise ValueError(f"Missing model assignment for role: {role}")
        directed_sequence = self._next_directed_response_number(meeting_id)
        self._run_step(
            meeting_id=meeting_id,
            topic=topic,
            model_assignments=model_assignments,
            inputs=inputs,
            step=step,
            attempt=1,
            round_number=self._next_round_number(meeting_id, plan),
            event_step_id=f"directed-{directed_sequence}-{role.lower()}-response",
            extra_event_fields={
                "interaction_type": "directed-role-response",
                "directed_sequence": directed_sequence,
            },
        )

    def respond_as_sequence(
        self,
        *,
        meeting_id: str,
        topic: str,
        roles: list[str],
        model_assignments: dict[str, ModelConfig],
        plan: RelayPlan,
        inputs: dict[str, str] | None = None,
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
                topic=topic,
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
            ):
                return

    def start_parallel(
        self,
        *,
        meeting_id: str,
        topic: str,
        model_assignments: dict[str, ModelConfig],
        plan: ParallelPlan,
        inputs: dict[str, str] | None = None,
    ) -> None:
        if self._is_terminal(meeting_id):
            return
        round_number = self._next_parallel_round_number(meeting_id)
        events = self.repository.read_events(meeting_id)
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
                topic=topic,
                model_assignments=model_assignments,
                members=pending_members,
                inputs=inputs,
                round_number=round_number,
                attempt=1,
            )
        self._run_parallel_synthesis_if_ready(
            meeting_id=meeting_id,
            topic=topic,
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
        topic: str,
        model_assignments: dict[str, ModelConfig],
        plan: ParallelPlan,
        inputs: dict[str, str] | None = None,
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
            topic=topic,
            model_assignments=model_assignments,
            members=[member],
            inputs=inputs,
            round_number=round_number,
            attempt=attempt,
        )
        self._run_parallel_synthesis_if_ready(
            meeting_id=meeting_id,
            topic=topic,
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
                "event_id": f"{meeting_id}:cancelled",
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
                "event_id": f"{meeting_id}:closed",
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
        topic: str,
        model_assignments: dict[str, ModelConfig],
        steps: list[StepDefinition],
        inputs: dict[str, str] | None,
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
                topic=topic,
                model_assignments=model_assignments,
                inputs=inputs,
                step=step,
                attempt=attempt,
                round_number=round_number,
                event_step_id=None,
                extra_event_fields=None,
            ):
                return

    def _run_step(
        self,
        *,
        meeting_id: str,
        topic: str,
        model_assignments: dict[str, ModelConfig],
        inputs: dict[str, str] | None,
        step: StepDefinition,
        attempt: int,
        round_number: int,
        event_step_id: str | None,
        extra_event_fields: dict[str, object] | None,
    ) -> bool:
        config = model_assignments[step.role]
        event_step_id = event_step_id or self._event_step_id(step.step_id, round_number)
        extra_event_fields = extra_event_fields or {}
        prompt_metadata = self._prompt_metadata(step.template_name)
        prompt = self.prompt_renderer.render(
            template_name=step.template_name,
            role=step.role,
            topic=topic,
            prior_transcript=self.transcript_projector.project(
                self.repository.read_events(meeting_id),
                title=topic,
            ),
            required_json_schema=REQUIRED_JSON_SCHEMA,
            inputs=self._inputs_for_role(inputs, step.role),
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
            prompt_metadata=prompt_metadata,
            extra_event_fields=extra_event_fields,
        )
        try:
            response = self.adapters.by_name[config.adapter].complete(
                ModelRequest(
                    prompt=prompt,
                    model_config=config,
                    meeting_id=meeting_id,
                    on_token_delta=emit_token_delta,
                )
            )
            parsed = self.output_parser.parse(response.raw_output)
        except (AdapterError, OutputParseError, KeyError) as error:
            self._clear_active_execution(meeting_id)
            if self._is_terminal(meeting_id):
                return False
            self.repository.append_event(
                meeting_id,
                {
                    "event_id": f"{meeting_id}:{event_step_id}:attempt-{attempt}:failed",
                    "meeting_id": meeting_id,
                    "step_id": event_step_id,
                    "base_step_id": step.step_id,
                    "round": round_number,
                    "role": step.role,
                    "attempt": attempt,
                    "status": "failed",
                    "error": str(error),
                    **prompt_metadata,
                    **extra_event_fields,
                },
            )
            return False

        self._clear_active_execution(meeting_id)
        if self._is_terminal(meeting_id):
            return False
        completed_event = {
            "event_id": f"{meeting_id}:{event_step_id}:attempt-{attempt}:completed",
            "meeting_id": meeting_id,
            "step_id": event_step_id,
            "base_step_id": step.step_id,
            "round": round_number,
            "role": step.role,
            "attempt": attempt,
            "model_config_id": config.id,
            **prompt_metadata,
            "prompt_messages": [{"role": "user", "content": prompt}],
            "raw_output": response.raw_output,
            "parsed_output": {
                "summary": parsed.summary,
                "arguments": [item.__dict__ for item in parsed.arguments],
                "risks": [item.__dict__ for item in parsed.risks],
                "recommendation": parsed.recommendation,
            },
            "status": "completed",
            **extra_event_fields,
        }
        if response.token_usage is not None:
            completed_event["token_usage"] = response.token_usage
        self.repository.append_event(
            meeting_id,
            completed_event,
        )
        return True

    def _run_parallel_members(
        self,
        *,
        meeting_id: str,
        topic: str,
        model_assignments: dict[str, ModelConfig],
        members: list[ParallelMemberStep],
        inputs: dict[str, str] | None,
        round_number: int,
        attempt: int,
    ) -> None:
        if not members:
            return
        with ThreadPoolExecutor(max_workers=len(members)) as executor:
            futures = [
                executor.submit(
                    self._build_parallel_member_event,
                    meeting_id=meeting_id,
                    topic=topic,
                    model_assignments=model_assignments,
                    member=member,
                    inputs=inputs,
                    round_number=round_number,
                    attempt=attempt,
                )
                for member in members
            ]
            events = [future.result() for future in futures]
        for event in events:
            if self._is_terminal(meeting_id):
                return
            self.repository.append_event(meeting_id, event)

    def _build_parallel_member_event(
        self,
        *,
        meeting_id: str,
        topic: str,
        model_assignments: dict[str, ModelConfig],
        member: ParallelMemberStep,
        inputs: dict[str, str] | None,
        round_number: int,
        attempt: int,
    ) -> dict[str, object]:
        config = model_assignments[member.role]
        event_step_id = f"fanout-{round_number}-member-{member.index}"
        prompt_metadata = self._prompt_metadata(member.template_name)
        prompt = self.prompt_renderer.render(
            template_name=member.template_name,
            role=member.role,
            topic=topic,
            prior_transcript=self.transcript_projector.project(
                self.repository.read_events(meeting_id),
                title=topic,
            ),
            required_json_schema=REQUIRED_JSON_SCHEMA,
            inputs=self._inputs_for_role(
                inputs,
                member.role,
                extra={
                    "instance_prompt": member.instance_prompt,
                    "display_name": member.display_name,
                },
            ),
        )
        try:
            response = self.adapters.by_name[config.adapter].complete(
                ModelRequest(prompt=prompt, model_config=config, meeting_id=meeting_id)
            )
            parsed = self.output_parser.parse(response.raw_output)
        except (AdapterError, OutputParseError, KeyError) as error:
            return {
                "event_id": f"{meeting_id}:{event_step_id}:attempt-{attempt}:failed",
                "meeting_id": meeting_id,
                "step_id": event_step_id,
                "base_step_id": member.step_id,
                "round": round_number,
                "role": member.role,
                "attempt": attempt,
                "status": "failed",
                "error": str(error),
                **prompt_metadata,
            }

        completed_event: dict[str, object] = {
            "event_id": f"{meeting_id}:{event_step_id}:attempt-{attempt}:completed",
            "meeting_id": meeting_id,
            "step_id": event_step_id,
            "base_step_id": member.step_id,
            "round": round_number,
            "role": member.role,
            "attempt": attempt,
            "model_config_id": config.id,
            **prompt_metadata,
            "prompt_messages": [{"role": "user", "content": prompt}],
            "raw_output": response.raw_output,
            "parsed_output": {
                "summary": parsed.summary,
                "arguments": [item.__dict__ for item in parsed.arguments],
                "risks": [item.__dict__ for item in parsed.risks],
                "recommendation": parsed.recommendation,
            },
            "status": "completed",
        }
        if response.token_usage is not None:
            completed_event["token_usage"] = response.token_usage
        return completed_event

    def _run_parallel_synthesis_if_ready(
        self,
        *,
        meeting_id: str,
        topic: str,
        model_assignments: dict[str, ModelConfig],
        plan: ParallelPlan,
        inputs: dict[str, str] | None,
        round_number: int,
    ) -> None:
        events = self.repository.read_events(meeting_id)
        if self._parallel_synthesis_completed(events, round_number):
            return
        if not all(self._parallel_member_completed(events, member, round_number) for member in plan.members):
            return
        self._run_step(
            meeting_id=meeting_id,
            topic=topic,
            model_assignments=model_assignments,
            inputs={
                **(inputs or {}),
                "fanout_outputs": self._fanout_outputs(events, plan.members, round_number),
            },
            step=plan.synthesis,
            attempt=1,
            round_number=round_number,
            event_step_id=f"synthesis-{round_number}",
            extra_event_fields=None,
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
            "status": "running",
            **prompt_metadata,
        }
        for key in ["interaction_type", "directed_sequence", "sequence", "sequence_index"]:
            value = extra_event_fields.get(key)
            if isinstance(value, (str, int)):
                state[key] = value
        self.execution_state_store.save_active(meeting_id, state)

    def _clear_active_execution(self, meeting_id: str) -> None:
        if self.execution_state_store is not None:
            self.execution_state_store.clear_active(meeting_id)

    def _prompt_metadata(self, template_name: str) -> dict[str, object]:
        return {
            "prompt_template_name": template_name,
            "prompt_template_hash": self.prompt_renderer.template_hash(template_name),
            "output_schema_hash": REQUIRED_JSON_SCHEMA_HASH,
        }

    def _inputs_for_role(
        self,
        inputs: dict[str, Any] | None,
        role: str,
        *,
        extra: dict[str, str] | None = None,
    ) -> dict[str, str]:
        rendered = {
            str(key): str(value)
            for key, value in (inputs or {}).items()
            if key != CASE_FILES_BY_ROLE_INPUT
        }
        case_files_by_role = (inputs or {}).get(CASE_FILES_BY_ROLE_INPUT)
        if isinstance(case_files_by_role, dict):
            rendered["case_files"] = str(case_files_by_role.get(role, ""))
        if extra:
            rendered.update(extra)
        return rendered

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
            for event in self.repository.read_events(meeting_id)
            if event.get("step_id") == step_id or event.get("base_step_id") == step_id
        ]
        return matching_events[-1] if matching_events else None

    def _first_incomplete_step_index(
        self, meeting_id: str, round_number: int, steps: list[StepDefinition]
    ) -> int | None:
        events = self.repository.read_events(meeting_id)
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
            for event in self.repository.read_events(meeting_id)
            if event.get("status") == "completed"
            and event.get("base_step_id", event.get("step_id")) == final_step_id
        ]
        return len(completed_final_step_events) + 1

    def _next_parallel_round_number(self, meeting_id: str) -> int:
        completed_synthesis_events = [
            event
            for event in self.repository.read_events(meeting_id)
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

    def _fanout_outputs(
        self,
        events: list[dict[str, object]],
        members: list[ParallelMemberStep],
        round_number: int,
    ) -> str:
        lines: list[str] = []
        for member in members:
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
            lines.append(
                f"{member.role} ({member.display_name})\n"
                f"Summary: {summary}\n"
                f"Recommendation: {recommendation}"
            )
        return "\n\n".join(lines)

    def _next_directed_response_number(self, meeting_id: str) -> int:
        directed_events = [
            event
            for event in self.repository.read_events(meeting_id)
            if event.get("interaction_type") == "directed-role-response"
        ]
        return len(directed_events) + 1

    def _next_role_sequence_number(self, meeting_id: str) -> int:
        sequence_events = [
            event
            for event in self.repository.read_events(meeting_id)
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
