from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, Protocol, TypedDict

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


STEPS = [
    StepDefinition("blue-propose", "Blue", "blue_propose"),
    StepDefinition("red-critique", "Red", "red"),
    StepDefinition("blue-revise", "Blue", "blue_revise"),
    StepDefinition("judge-decide", "Judge", "judge"),
]

DIRECTED_RESPONSE_STEPS = {
    "Blue": StepDefinition("blue-response", "Blue", "blue_revise"),
    "Red": StepDefinition("red-response", "Red", "red"),
    "Judge": StepDefinition("judge-response", "Judge", "judge"),
}


class MeetingRunner:
    def __init__(
        self,
        *,
        repository: MeetingRepository,
        prompt_renderer: PromptRenderer,
        adapters: RunnerAdapters,
        stream_sink: Callable[[str, TokenStreamEvent], None] | None = None,
    ) -> None:
        self.repository = repository
        self.prompt_renderer = prompt_renderer
        self.adapters = adapters
        self.stream_sink = stream_sink
        self.output_parser = RoleOutputParser()
        self.transcript_projector = TranscriptProjector()

    def start(
        self,
        *,
        meeting_id: str,
        topic: str,
        model_assignments: dict[str, ModelConfig],
    ) -> None:
        if self._is_terminal(meeting_id):
            return
        round_number = self._next_round_number(meeting_id)
        start_index = self._first_incomplete_step_index(meeting_id, round_number)
        if start_index is None:
            return
        self._run_from_step(
            meeting_id=meeting_id,
            topic=topic,
            model_assignments=model_assignments,
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
    ) -> None:
        failed_event = self._latest_event_for_step(meeting_id, step_id)
        if not failed_event or failed_event.get("status") != "failed":
            raise ValueError(f"Step is not failed: {step_id}")
        base_step_id = str(failed_event.get("base_step_id", failed_event.get("step_id")))
        start_index = next(index for index, step in enumerate(STEPS) if step.step_id == base_step_id)
        self._run_from_step(
            meeting_id=meeting_id,
            topic=topic,
            model_assignments=model_assignments,
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
    ) -> None:
        if self._is_terminal(meeting_id):
            return
        step = DIRECTED_RESPONSE_STEPS.get(role)
        if step is None:
            raise ValueError(f"Unknown role: {role}")
        if role not in model_assignments:
            raise ValueError(f"Missing model assignment for role: {role}")
        directed_sequence = self._next_directed_response_number(meeting_id)
        self._run_step(
            meeting_id=meeting_id,
            topic=topic,
            model_assignments=model_assignments,
            step=step,
            attempt=1,
            round_number=self._next_round_number(meeting_id),
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
    ) -> None:
        if self._is_terminal(meeting_id):
            return
        if not roles:
            raise ValueError("Role sequence cannot be empty")
        if len(set(roles)) != len(roles):
            raise ValueError("Role sequence cannot contain duplicate roles")

        steps: list[StepDefinition] = []
        for role in roles:
            step = DIRECTED_RESPONSE_STEPS.get(role)
            if step is None:
                raise ValueError(f"Unknown role: {role}")
            if role not in model_assignments:
                raise ValueError(f"Missing model assignment for role: {role}")
            steps.append(step)

        sequence_number = self._next_role_sequence_number(meeting_id)
        round_number = self._next_round_number(meeting_id)
        for index, step in enumerate(steps, start=1):
            if self._is_terminal(meeting_id):
                return
            if not self._run_step(
                meeting_id=meeting_id,
                topic=topic,
                model_assignments=model_assignments,
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
        start_index: int,
        attempt_override: int | None,
        round_number: int,
    ) -> None:
        for index, step in enumerate(STEPS[start_index:], start=start_index):
            if self._is_terminal(meeting_id):
                return
            attempt = attempt_override if index == start_index and attempt_override else 1
            if not self._run_step(
                meeting_id=meeting_id,
                topic=topic,
                model_assignments=model_assignments,
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
        step: StepDefinition,
        attempt: int,
        round_number: int,
        event_step_id: str | None,
        extra_event_fields: dict[str, object] | None,
    ) -> bool:
        config = model_assignments[step.role]
        event_step_id = event_step_id or self._event_step_id(step.step_id, round_number)
        extra_event_fields = extra_event_fields or {}
        prompt = self.prompt_renderer.render(
            template_name=step.template_name,
            role=step.role,
            topic=topic,
            prior_transcript=self.transcript_projector.project(
                self.repository.read_events(meeting_id),
                title=topic,
            ),
            required_json_schema=REQUIRED_JSON_SCHEMA,
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
                    **extra_event_fields,
                },
            )
            return False

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

    def _is_terminal(self, meeting_id: str) -> bool:
        return any(
            event.get("status") in {"cancelled", "closed"}
            for event in self.repository.read_events(meeting_id)
        )

    def _latest_event_for_step(self, meeting_id: str, step_id: str) -> dict[str, object] | None:
        matching_events = [
            event
            for event in self.repository.read_events(meeting_id)
            if event.get("step_id") == step_id or event.get("base_step_id") == step_id
        ]
        return matching_events[-1] if matching_events else None

    def _first_incomplete_step_index(self, meeting_id: str, round_number: int) -> int | None:
        events = self.repository.read_events(meeting_id)
        for index, step in enumerate(STEPS):
            event_step_id = self._event_step_id(step.step_id, round_number)
            matching_events = [event for event in events if event.get("step_id") == event_step_id]
            if not matching_events:
                return index
            if matching_events[-1].get("status") != "completed":
                return None
        return None

    def _next_round_number(self, meeting_id: str) -> int:
        completed_judge_events = [
            event
            for event in self.repository.read_events(meeting_id)
            if event.get("status") == "completed"
            and event.get("base_step_id", event.get("step_id")) == "judge-decide"
        ]
        return len(completed_judge_events) + 1

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
