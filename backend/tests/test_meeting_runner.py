from __future__ import annotations

import hashlib
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from threading import Event, Lock, Thread

import pytest

from ai_council.meetings.modes import ModeCatalogRepository, relay_plan
from ai_council.meetings.deliberation import DeliberationEpochs, RestartCommand
from ai_council.meetings.repository import MeetingRepository
from ai_council.meetings.runner import (
    MeetingRunner,
    ParallelMemberStep,
    ParallelPlan,
    RelayPlan,
    RunnerAdapters,
    StepDefinition,
)
from ai_council.models.adapters import (
    AdapterError,
    ModelRequest,
    ModelResponse,
    SubscriptionCLIAdapter,
)
from ai_council.models.config import ModelConfig
from ai_council.prompting.renderer import PromptRenderer
from ai_council.prompting.schemas import (
    STRUCTURED_VERDICT_V1_SCHEMA,
    OutputSchemaCodec,
    OutputSchemaRegistry,
)


VALID_OUTPUT = json.dumps(
    {
        "summary": "OK",
        "arguments": [],
        "risks": [],
        "recommendation": "Continue",
    }
)
VALID_STRUCTURED_VERDICT = json.dumps(
    {
        "summary": "有條件核准",
        "decision": "approve-with-conditions",
        "findings": [
            {
                "title": "驗收完成",
                "detail": "測試紀錄完整。",
                "evidence_refs": ["[證物一]"],
            }
        ],
        "risks": [],
        "recommendation": "完成回滾演練後上線。",
        "conditions": ["完成回滾演練"],
        "unresolved_questions": ["尖峰容量是否足夠？"],
    },
    ensure_ascii=False,
)
TEST_PROMPT_TEMPLATE_HASHES = {
    "blue_propose": "e7d46f095166a1501d42f5376af61e82d8773d48a960ce8ec81331f5dc45351d",
    "red_critique": "0705ea3dafccdd8ce99db2616e291a7cb394a664b22b1164ba52090ce3beb462",
    "blue_revise": "cf63dcc57d7a55c8bfb95892b78d87febe08a6ab807dbac82f8974ccce752dea",
    "judge_decide": "a206142cb8fcffced199d9d7facc39b6fd9ace7e2595a76c49241f2d82dd50f3",
    "directed_role_response": "b94bdc0fcbb48d37650e9e1751a70c0d556dda0eaababff5fcaa2bc144f37643",
}
TEST_OUTPUT_SCHEMA_HASH = "15a45919652be5c70d3fd1690a10d37f876f19a14b2a76cc0f21765def281377"
TEST_ONLY_SCHEMA = '{"value":"string"}'
TEST_ONLY_SCHEMA_HASH = hashlib.sha256(TEST_ONLY_SCHEMA.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StubOutput:
    value: str


class TestOnlyParser:
    def parse(self, raw_output: str) -> StubOutput:
        return StubOutput(value=json.loads(raw_output)["value"])


class DictOutputParser:
    def parse(self, raw_output: str) -> dict[str, str]:
        return json.loads(raw_output)


RED_BLUE_PLAN = RelayPlan(
    steps=[
        StepDefinition("blue-propose", "Blue", "blue_propose"),
        StepDefinition("red-critique", "Red", "red_critique"),
        StepDefinition("blue-revise", "Blue", "blue_revise"),
        StepDefinition("judge-decide", "Judge", "judge_decide"),
    ],
    directed_steps={
        "Blue": StepDefinition("blue-response", "Blue", "blue_revise"),
        "Red": StepDefinition("red-response", "Red", "red_critique"),
        "Judge": StepDefinition("judge-response", "Judge", "judge_decide"),
    },
)

COURTROOM_PLAN = RelayPlan(
    steps=[
        StepDefinition("courtroom-charge", "Prosecutor", "courtroom_charge"),
        StepDefinition("courtroom-defense", "Defense", "courtroom_defense"),
        StepDefinition("courtroom-rebuttal", "Prosecutor", "courtroom_rebuttal"),
        StepDefinition("courtroom-verdict", "Judge", "courtroom_verdict"),
    ],
    directed_steps={
        "Prosecutor": StepDefinition("prosecutor-response", "Prosecutor", "courtroom_rebuttal"),
        "Defense": StepDefinition("defense-response", "Defense", "courtroom_defense"),
        "Judge": StepDefinition("judge-response", "Judge", "courtroom_verdict"),
    },
)

PARALLEL_PLAN = ParallelPlan(
    members=[
        ParallelMemberStep(
            step_id="member-1",
            role="Member-1",
            template_name="brainstorm_member",
            display_name="委員 1",
            instance_prompt="成本視角",
            index=1,
        ),
        ParallelMemberStep(
            step_id="member-2",
            role="Member-2",
            template_name="brainstorm_member",
            display_name="委員 2",
            instance_prompt="使用者視角",
            index=2,
        ),
        ParallelMemberStep(
            step_id="member-3",
            role="Member-3",
            template_name="brainstorm_member",
            display_name="委員 3",
            instance_prompt="營運視角",
            index=3,
        ),
    ],
    synthesis=StepDefinition("synthesis", "Moderator", "brainstorm_synthesis"),
)


ANONYMIZED_PARALLEL_PLAN = ParallelPlan(
    members=PARALLEL_PLAN.members,
    synthesis=PARALLEL_PLAN.synthesis,
    anonymize_synthesis_inputs=True,
)


def test_runner_completes_fixed_red_blue_judge_flow(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, adapter=FakeAdapter([VALID_OUTPUT] * 4))

    runner.start(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        goal="先做後端？",
        model_assignments={
            "Blue": ModelConfig(id="mock-blue", adapter="mock"),
            "Red": ModelConfig(id="mock-red", adapter="mock"),
            "Judge": ModelConfig(id="mock-judge", adapter="mock"),
        },
    )

    events = runner.repository.read_events("meeting-1")
    completed_steps = [event for event in events if event["status"] == "completed"]
    assert [event["step_id"] for event in completed_steps] == [
        "blue-propose",
        "red-critique",
        "blue-revise",
        "judge-decide",
    ]
    assert [event["attempt"] for event in completed_steps] == [1, 1, 1, 1]
    assert completed_steps[0]["parsed_output"]["summary"] == "OK"


def test_runner_prompt_contains_goal_without_human_facing_title(tmp_path: Path) -> None:
    adapter = FakeAdapter([VALID_OUTPUT] * 4)
    runner = build_runner(tmp_path, adapter=adapter)

    runner.start(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-goal-only",
        goal="判斷被告是否構成無權占有",
        model_assignments={
            "Blue": ModelConfig(id="mock-blue", adapter="mock"),
            "Red": ModelConfig(id="mock-red", adapter="mock"),
            "Judge": ModelConfig(id="mock-judge", adapter="mock"),
        },
        inputs={"title": "土地糾紛案", "topic": "舊主題不得使用"},
    )

    assert adapter.requests
    assert all("判斷被告是否構成無權占有" in request.prompt for request in adapter.requests)
    assert all("土地糾紛案" not in request.prompt for request in adapter.requests)
    assert all("舊主題不得使用" not in request.prompt for request in adapter.requests)


def test_runner_persists_model_token_usage_on_completed_events(tmp_path: Path) -> None:
    runner = build_runner(
        tmp_path,
        adapter=FakeAdapter(
            [VALID_OUTPUT],
            token_usage={"prompt_tokens": 12, "completion_tokens": 8, "total_tokens": 20},
        ),
    )

    runner.respond_as_role(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        goal="先做後端？",
        role="Blue",
        role_display_name="藍軍",
        instruction="提出最小可行方案",
        model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
    )

    event = runner.repository.read_events("meeting-1")[-1]
    assert event["token_usage"] == {
        "prompt_tokens": 12,
        "completion_tokens": 8,
        "total_tokens": 20,
    }
    assert event["model_config_id"] == "mock-blue"
    assert event["adapter"] == "mock"
    assert event["prompt_messages"][0]["role"] == "user"
    assert event["raw_output"] == VALID_OUTPUT
    assert event["parsed_output"]["summary"] == "OK"
    assert event["started_at"] <= event["completed_at"]
    assert event["duration_ms"] >= 0


def test_runner_persists_prompt_metadata_on_completed_events(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, adapter=FakeAdapter([VALID_OUTPUT]))

    runner.respond_as_role(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        goal="先做後端？",
        role="Blue",
        role_display_name="藍軍",
        instruction="提出最小可行方案",
        model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
    )

    event = runner.repository.read_events("meeting-1")[-1]
    assert event["prompt_template_name"] == "directed_role_response"
    assert event["prompt_template_hash"] == TEST_PROMPT_TEMPLATE_HASHES["directed_role_response"]
    assert event["output_schema_id"] == "role-output/v1"
    assert event["output_schema_hash"] == TEST_OUTPUT_SCHEMA_HASH


def test_directed_response_uses_step_output_schema_for_prompt_parser_and_event(
    tmp_path: Path,
) -> None:
    custom_schema_id = "test-output/v1"
    plan = RelayPlan(
        steps=[StepDefinition("blue-propose", "Blue", "blue_propose")],
        directed_steps={
            "Blue": StepDefinition(
                "blue-response",
                "Blue",
                "blue_revise",
                custom_schema_id,
            )
        },
    )
    registry = OutputSchemaRegistry(
        [OutputSchemaCodec(custom_schema_id, TEST_ONLY_SCHEMA, TestOnlyParser())]
    )
    adapter = FakeAdapter(['{"value":"custom parsed"}'])
    runner = build_runner(tmp_path, adapter=adapter, output_schemas=registry)

    runner.respond_as_role(
        plan=plan,
        meeting_id="meeting-1",
        goal="schema selection",
        role="Blue",
        role_display_name="藍軍",
        instruction="使用指定 schema 回答",
        model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
    )

    event = runner.repository.read_events("meeting-1")[-1]
    assert TEST_ONLY_SCHEMA in adapter.requests[0].prompt
    assert adapter.requests[0].output_schema_id == custom_schema_id
    assert event["output_schema_id"] == custom_schema_id
    assert event["output_schema_hash"] == TEST_ONLY_SCHEMA_HASH
    assert event["parsed_output"] == {"value": "custom parsed"}


def test_output_schema_codec_accepts_a_dict_returning_parser(tmp_path: Path) -> None:
    custom_schema_id = "test-output/v1"
    plan = RelayPlan(
        steps=[StepDefinition("blue-propose", "Blue", "blue_propose")],
        directed_steps={
            "Blue": StepDefinition(
                "blue-response",
                "Blue",
                "blue_revise",
                custom_schema_id,
            )
        },
    )
    registry = OutputSchemaRegistry(
        [OutputSchemaCodec(custom_schema_id, TEST_ONLY_SCHEMA, DictOutputParser())]
    )
    runner = build_runner(
        tmp_path,
        adapter=FakeAdapter(['{"value":"dict parsed"}']),
        output_schemas=registry,
    )

    runner.respond_as_role(
        plan=plan,
        meeting_id="meeting-1",
        goal="schema selection",
        role="Blue",
        role_display_name="藍軍",
        instruction="使用指定 schema 回答",
        model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
    )

    event = runner.repository.read_events("meeting-1")[-1]
    assert event["status"] == "completed"
    assert event["parsed_output"] == {"value": "dict parsed"}


def test_codec_decode_error_auto_retries_once_then_allows_manual_retry(
    tmp_path: Path,
) -> None:
    custom_schema_id = "test-output/v1"
    plan = RelayPlan(
        steps=[
            StepDefinition(
                "blue-propose",
                "Blue",
                "blue_propose",
                custom_schema_id,
            )
        ],
        directed_steps={},
    )
    registry = OutputSchemaRegistry(
        [OutputSchemaCodec(custom_schema_id, TEST_ONLY_SCHEMA, DictOutputParser())]
    )
    runner = build_runner(
        tmp_path,
        adapter=FakeAdapter(["not json", "still not json", '{"value":"recovered"}']),
        output_schemas=registry,
    )

    runner.start(
        plan=plan,
        meeting_id="meeting-1",
        goal="schema selection",
        model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
    )

    failed_events = runner.repository.read_events("meeting-1")
    assert [(event["attempt"], event["status"]) for event in failed_events] == [
        (1, "failed"),
        (2, "failed"),
    ]
    assert {event["output_schema_id"] for event in failed_events} == {custom_schema_id}

    runner.retry_failed_step(
        plan=plan,
        meeting_id="meeting-1",
        step_id="blue-propose",
        goal="schema selection",
        model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
    )

    recovered = runner.repository.read_events("meeting-1")[-1]
    assert recovered["status"] == "completed"
    assert recovered["attempt"] == 3
    assert recovered["parsed_output"] == {"value": "recovered"}


def test_rich_parse_failure_is_recorded_then_automatically_retried_once(
    tmp_path: Path,
) -> None:
    plan = RelayPlan(
        steps=[
            StepDefinition(
                "judge-decide",
                "Judge",
                "judge_decide",
                "structured-verdict/v1",
            )
        ],
        directed_steps={},
    )
    adapter = FakeAdapter(["not a verdict", VALID_STRUCTURED_VERDICT])
    runner = build_runner(tmp_path, adapter=adapter)

    runner.start(
        plan=plan,
        meeting_id="meeting-1",
        goal="是否核准上線？",
        model_assignments={"Judge": ModelConfig(id="mock-judge", adapter="mock")},
    )

    events = runner.repository.read_events("meeting-1")
    assert [(event["attempt"], event["status"]) for event in events] == [
        (1, "failed"),
        (2, "completed"),
    ]
    assert {event["step_id"] for event in events} == {"judge-decide"}
    assert {event["round"] for event in events} == {1}
    assert {event["output_schema_id"] for event in events} == {
        "structured-verdict/v1"
    }
    assert len({event["output_schema_hash"] for event in events}) == 1
    assert len(adapter.requests) == 2
    assert all(STRUCTURED_VERDICT_V1_SCHEMA in request.prompt for request in adapter.requests)
    assert events[-1]["parsed_output"]["decision"] == "approve-with-conditions"


def test_non_string_model_output_uses_parse_failure_retry_flow(tmp_path: Path) -> None:
    class NonStringThenValidAdapter:
        calls = 0

        def complete(self, request: ModelRequest) -> ModelResponse:
            self.calls += 1
            if self.calls == 1:
                return ModelResponse(raw_output=None)  # type: ignore[arg-type]
            return ModelResponse(raw_output=VALID_OUTPUT)

    adapter = NonStringThenValidAdapter()
    runner = build_runner(tmp_path, adapter=adapter)

    runner.respond_as_role(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        goal="非字串輸出",
        role="Blue",
        role_display_name="藍軍",
        instruction="回答問題",
        model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
    )

    events = runner.repository.read_events("meeting-1")
    assert adapter.calls == 2
    response_events = [event for event in events if event["role"] == "Blue"]
    assert [(event["attempt"], event["status"]) for event in response_events] == [
        (1, "failed"),
        (2, "completed"),
    ]
    assert "Model output must be a string" in response_events[0]["error"]


def test_parse_failure_attempt_persists_complete_diagnostics_before_retry(
    tmp_path: Path,
) -> None:
    malformed = '{"summary":"missing delimiter" "arguments":[]}'
    runner = build_runner(
        tmp_path,
        adapter=FakeAdapter(
            [malformed, VALID_OUTPUT],
            token_usage={"prompt_tokens": 21, "completion_tokens": 7, "total_tokens": 28},
        ),
    )

    runner.respond_as_role(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        goal="診斷格式錯誤",
        role="Blue",
        role_display_name="藍軍",
        instruction="回答問題",
        model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
    )

    _, failed, completed = runner.repository.read_events("meeting-1")
    assert (failed["attempt"], failed["status"], failed["retry_scheduled"]) == (
        1,
        "failed",
        True,
    )
    assert (completed["attempt"], completed["status"]) == (2, "completed")
    assert failed["failure_kind"] == "parse_error"
    assert failed["model_config_id"] == "mock-blue"
    assert failed["adapter"] == "mock"
    assert failed["prompt_messages"][0]["role"] == "user"
    assert "診斷格式錯誤" in failed["prompt_messages"][0]["content"]
    assert failed["raw_output"] == malformed
    assert failed["token_usage"] == {
        "prompt_tokens": 21,
        "completion_tokens": 7,
        "total_tokens": 28,
    }
    assert failed["started_at"] <= failed["completed_at"]
    assert isinstance(failed["duration_ms"], int)
    assert failed["duration_ms"] >= 0


def test_parallel_parse_failure_diagnostics_preserve_attempt_semantics(
    tmp_path: Path,
) -> None:
    runner = build_runner(
        tmp_path,
        adapter=FakeAdapter(
            ["not json", '{"value":"member 1 recovered"}', '{"value":"synthesized"}'],
            token_usage={"prompt_tokens": 5, "completion_tokens": 2, "total_tokens": 7},
        ),
        output_schemas=OutputSchemaRegistry(
            [OutputSchemaCodec("test-output/v1", TEST_ONLY_SCHEMA, DictOutputParser())]
        ),
        templates=("brainstorm_member", "brainstorm_synthesis"),
    )
    member = ParallelMemberStep(
        step_id="member-1",
        role="Member-1",
        template_name="brainstorm_member",
        display_name="委員 1",
        instance_prompt="診斷",
        index=1,
        output_schema_id="test-output/v1",
    )

    runner.start_parallel(
        meeting_id="meeting-1",
        goal="平行診斷",
        model_assignments={
            "Member-1": ModelConfig(id="mock-member", adapter="mock"),
            "Moderator": ModelConfig(id="mock-moderator", adapter="mock"),
        },
        plan=ParallelPlan(
            members=[member],
            synthesis=StepDefinition(
                "synthesis",
                "Moderator",
                "brainstorm_synthesis",
                output_schema_id="test-output/v1",
            ),
        ),
        inputs=None,
    )

    failed, completed, _synthesis = runner.repository.read_events("meeting-1")
    assert (failed["step_id"], failed["attempt"], failed["retry_scheduled"]) == (
        "fanout-1-member-1",
        1,
        True,
    )
    assert (completed["step_id"], completed["attempt"], completed["status"]) == (
        "fanout-1-member-1",
        2,
        "completed",
    )
    assert failed["failure_kind"] == "parse_error"
    assert failed["raw_output"] == "not json"
    assert failed["model_config_id"] == "mock-member"
    assert failed["adapter"] == "mock"
    assert failed["token_usage"]["total_tokens"] == 7


def test_injected_registry_is_shared_from_catalog_through_plan_and_runner(
    tmp_path: Path,
) -> None:
    custom_schema_id = "test-output/v1"
    registry = OutputSchemaRegistry(
        [OutputSchemaCodec(custom_schema_id, TEST_ONLY_SCHEMA, DictOutputParser())]
    )
    modes_path = tmp_path / "modes.yaml"
    modes_path.write_text(
        """
modes:
  - id: custom
    name: Custom
    category: relay
    tagline: t
    when_to_use: w
    sop: []
    default_scene: meeting-room
    inputs: []
    roles:
      - { id: Blue, name: Blue, color: "#4d8dff", kind: member, output_schema: test-output/v1 }
    steps:
      - { role: Blue, template: blue_propose, label: Blue }
""".strip(),
        encoding="utf-8",
    )
    mode = ModeCatalogRepository(modes_path, output_schemas=registry).get_mode("custom")
    assert mode is not None
    plan = relay_plan(mode)
    runner = build_runner(
        tmp_path,
        adapter=FakeAdapter(['{"value":"catalog selected"}']),
        output_schemas=registry,
    )

    runner.start(
        plan=plan,
        meeting_id="meeting-1",
        goal="schema selection",
        model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
    )

    event = runner.repository.read_events("meeting-1")[-1]
    assert plan.steps[0].output_schema_id == custom_schema_id
    assert TEST_ONLY_SCHEMA in event["prompt_messages"][0]["content"]
    assert event["output_schema_id"] == custom_schema_id
    assert event["parsed_output"] == {"value": "catalog selected"}


def test_runner_persists_prompt_metadata_on_failed_events(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, adapter=FailingAdapter())

    runner.respond_as_role(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        goal="先做後端？",
        role="Red",
        role_display_name="紅軍",
        instruction="指出主要風險",
        model_assignments={"Red": ModelConfig(id="mock-red", adapter="mock")},
    )

    event = runner.repository.read_events("meeting-1")[-1]
    assert event["status"] == "failed"
    assert event["prompt_template_name"] == "directed_role_response"
    assert event["prompt_template_hash"] == TEST_PROMPT_TEMPLATE_HASHES["directed_role_response"]
    assert event["output_schema_id"] == "role-output/v1"
    assert event["output_schema_hash"] == TEST_OUTPUT_SCHEMA_HASH


def test_runner_persists_prompt_template_names_for_fixed_flow(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, adapter=FakeAdapter([VALID_OUTPUT] * 4))

    runner.start(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        goal="先做後端？",
        model_assignments={
            "Blue": ModelConfig(id="mock-blue", adapter="mock"),
            "Red": ModelConfig(id="mock-red", adapter="mock"),
            "Judge": ModelConfig(id="mock-judge", adapter="mock"),
        },
    )

    events = runner.repository.read_events("meeting-1")
    assert [event["prompt_template_name"] for event in events] == [
        "blue_propose",
        "red_critique",
        "blue_revise",
        "judge_decide",
    ]
    assert [event["prompt_template_hash"] for event in events] == [
        TEST_PROMPT_TEMPLATE_HASHES["blue_propose"],
        TEST_PROMPT_TEMPLATE_HASHES["red_critique"],
        TEST_PROMPT_TEMPLATE_HASHES["blue_revise"],
        TEST_PROMPT_TEMPLATE_HASHES["judge_decide"],
    ]
    assert {event["output_schema_hash"] for event in events} == {TEST_OUTPUT_SCHEMA_HASH}
    assert {event["output_schema_id"] for event in events} == {"role-output/v1"}


def test_runner_start_resumes_from_first_incomplete_step_after_restart(tmp_path: Path) -> None:
    adapter = FakeAdapter([VALID_OUTPUT] * 3)
    runner = build_runner(tmp_path, adapter=adapter)
    runner.repository.append_event(
        "meeting-1",
        {
            "event_id": "meeting-1:blue-propose:attempt-1:completed",
            "meeting_id": "meeting-1",
            "step_id": "blue-propose",
            "base_step_id": "blue-propose",
            "round": 1,
            "role": "Blue",
            "attempt": 1,
            "model_config_id": "mock-blue",
            "parsed_output": json.loads(VALID_OUTPUT),
            "status": "completed",
        },
    )

    runner.start(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        goal="先做後端？",
        model_assignments={
            "Blue": ModelConfig(id="mock-blue", adapter="mock"),
            "Red": ModelConfig(id="mock-red", adapter="mock"),
            "Judge": ModelConfig(id="mock-judge", adapter="mock"),
        },
    )

    events = runner.repository.read_events("meeting-1")
    completed_steps = [event for event in events if event["status"] == "completed"]
    assert [event["step_id"] for event in completed_steps] == [
        "blue-propose",
        "red-critique",
        "blue-revise",
        "judge-decide",
    ]
    assert [request.model_config.id for request in adapter.requests] == [
        "mock-red",
        "mock-blue",
        "mock-judge",
    ]


def test_runner_start_defers_to_explicit_retry_when_a_step_already_failed(
    tmp_path: Path,
) -> None:
    adapter = FakeAdapter([VALID_OUTPUT] * 4)
    runner = build_runner(tmp_path, adapter=adapter)
    runner.repository.append_event(
        "meeting-1",
        {
            "event_id": "meeting-1:blue-propose:attempt-1:completed",
            "meeting_id": "meeting-1",
            "step_id": "blue-propose",
            "base_step_id": "blue-propose",
            "round": 1,
            "role": "Blue",
            "attempt": 1,
            "model_config_id": "mock-blue",
            "parsed_output": json.loads(VALID_OUTPUT),
            "status": "completed",
        },
    )
    runner.repository.append_event(
        "meeting-1",
        {
            "event_id": "meeting-1:red-critique:attempt-1:failed",
            "meeting_id": "meeting-1",
            "step_id": "red-critique",
            "base_step_id": "red-critique",
            "round": 1,
            "role": "Red",
            "attempt": 1,
            "status": "failed",
            "error": "adapter boom",
        },
    )

    runner.start(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        goal="先做後端？",
        model_assignments={
            "Blue": ModelConfig(id="mock-blue", adapter="mock"),
            "Red": ModelConfig(id="mock-red", adapter="mock"),
            "Judge": ModelConfig(id="mock-judge", adapter="mock"),
        },
    )

    assert adapter.requests == []
    events = runner.repository.read_events("meeting-1")
    assert len(events) == 2


def test_runner_starts_follow_up_round_after_human_feedback(tmp_path: Path) -> None:
    adapter = FakeAdapter([VALID_OUTPUT] * 8)
    runner = build_runner(tmp_path, adapter=adapter)
    model_assignments = {
        "Blue": ModelConfig(id="mock-blue", adapter="mock"),
        "Red": ModelConfig(id="mock-red", adapter="mock"),
        "Judge": ModelConfig(id="mock-judge", adapter="mock"),
    }
    runner.start(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        goal="先做後端？",
        model_assignments=model_assignments,
    )
    runner.repository.append_event(
        "meeting-1",
        {
            "event_id": "human-feedback",
            "meeting_id": "meeting-1",
            "step_id": "human-message",
            "role": "Human",
            "attempt": 1,
            "status": "completed",
            "content": "主席補充：第二輪要限制在一週內完成。",
        },
    )

    runner.start(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        goal="先做後端？",
        model_assignments=model_assignments,
    )

    events = runner.repository.read_events("meeting-1")
    completed_steps = [
        event["step_id"]
        for event in events
        if event["status"] == "completed" and event["role"] != "Human"
    ]
    assert completed_steps == [
        "blue-propose",
        "red-critique",
        "blue-revise",
        "judge-decide",
        "round-2-blue-propose",
        "round-2-red-critique",
        "round-2-blue-revise",
        "round-2-judge-decide",
    ]
    assert "主席補充：第二輪要限制在一週內完成。" in adapter.requests[4].prompt


def test_runner_answers_explicit_directed_instruction_with_linked_events_and_generic_prompt(
    tmp_path: Path,
) -> None:
    adapter = FakeAdapter([VALID_OUTPUT])
    runner = build_runner(
        tmp_path,
        adapter=adapter,
        templates=("courtroom_defense", "directed_role_response"),
    )
    prompt_dir = tmp_path / "prompts"
    (prompt_dir / "courtroom_defense.md").write_text(
        "PHASE-ONLY: Answer every charge raised by the Prosecutor.",
        encoding="utf-8",
    )
    (prompt_dir / "directed_role_response.md").write_text(
        "Role: {{ role_display_name }}\nGoal: {{ goal }}\n"
        "Case files: {{ case_files }}\nPrior transcript: {{ prior_transcript }}\n"
        "Instruction: {{ instruction }}\nSchema: {{ required_json_schema }}",
        encoding="utf-8",
    )

    runner.respond_as_role(
        plan=COURTROOM_PLAN,
        meeting_id="meeting-1",
        goal="判斷被告是否構成無權占有",
        role="Defense",
        role_display_name="辯護律師",
        instruction="請針對遺產稅因果關係補充答辯",
        model_assignments={
            "Defense": ModelConfig(id="mock-defense", adapter="mock"),
        },
        inputs={
            "__case_files_by_role": {
                "Defense": "[證物二] 遺產稅繳納紀錄",
            }
        },
    )

    events = runner.repository.read_events("meeting-1")
    instruction_event, response_event = events
    assert instruction_event["step_id"] == "human-directed-message"
    assert instruction_event["role"] == "Human"
    assert instruction_event["interaction_type"] == "directed-role-instruction"
    assert instruction_event["target_role_id"] == "Defense"
    assert instruction_event["content"] == "請針對遺產稅因果關係補充答辯"
    assert response_event["step_id"] == "directed-1-defense-response"
    assert response_event["base_step_id"] == "defense-response"
    assert response_event["interaction_type"] == "directed-role-response"
    assert response_event["directed_sequence"] == 1
    assert response_event["role"] == "Defense"
    assert response_event["in_response_to_event_id"] == instruction_event["event_id"]
    prompt = adapter.requests[0].prompt
    assert "辯護律師" in prompt
    assert "判斷被告是否構成無權占有" in prompt
    assert "[證物二] 遺產稅繳納紀錄" in prompt
    assert "請針對遺產稅因果關係補充答辯" in prompt
    assert "PHASE-ONLY" not in prompt


def test_directed_parse_retry_reuses_sequence_number_for_the_next_response(
    tmp_path: Path,
) -> None:
    adapter = FakeAdapter(["not json", VALID_OUTPUT, VALID_OUTPUT])
    runner = build_runner(tmp_path, adapter=adapter)
    assignments = {"Blue": ModelConfig(id="mock-blue", adapter="mock")}

    runner.respond_as_role(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        goal="先做後端？",
        role="Blue",
        role_display_name="藍軍",
        instruction="第一次追問",
        model_assignments=assignments,
    )
    runner.respond_as_role(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        goal="先做後端？",
        role="Blue",
        role_display_name="藍軍",
        instruction="第二次追問",
        model_assignments=assignments,
    )

    events = runner.repository.read_events("meeting-1")
    response_events = [event for event in events if event["role"] == "Blue"]
    assert [event["directed_sequence"] for event in response_events] == [1, 1, 2]
    assert [event["step_id"] for event in response_events] == [
        "directed-1-blue-response",
        "directed-1-blue-response",
        "directed-2-blue-response",
    ]


def test_retry_failed_directed_response_reuses_instruction_linkage_and_generic_prompt(
    tmp_path: Path,
) -> None:
    adapter = FakeAdapter(["not json", "still not json", VALID_OUTPUT])
    runner = build_runner(
        tmp_path,
        adapter=adapter,
        templates=("courtroom_defense", "directed_role_response"),
    )
    prompt_dir = tmp_path / "prompts"
    (prompt_dir / "courtroom_defense.md").write_text(
        "PHASE-ONLY: Answer every charge raised by the Prosecutor.",
        encoding="utf-8",
    )
    (prompt_dir / "directed_role_response.md").write_text(
        "Role: {{ role_display_name }}\nGoal: {{ goal }}\n"
        "Case files: {{ case_files }}\nInstruction: {{ instruction }}\n"
        "Schema: {{ required_json_schema }}",
        encoding="utf-8",
    )
    assignments = {"Defense": ModelConfig(id="mock-defense", adapter="mock")}
    inputs = {
        "__case_files_by_role": {
            "Defense": "[證物二] 遺產稅繳納紀錄",
        },
        "__case_evidence_by_role": {
            "Defense": [{
                "id": "internal-envelope-only",
                "citation_anchor": "[證物二]",
                "version": 3,
                "content": "遺產稅繳納紀錄",
            }],
        },
        "__materials_revision": 7,
        "__materials_refs": [
            {
                "kind": "evidence",
                "id": "case-file-2",
                "version": 3,
                "status": "active",
                "visible_roles": ["Defense"],
            }
        ],
    }

    runner.respond_as_role(
        plan=COURTROOM_PLAN,
        meeting_id="meeting-1",
        goal="判斷遺產稅損失是否具有因果關係",
        role="Defense",
        role_display_name="辯護律師",
        instruction="請針對遺產稅因果關係補充答辯",
        model_assignments=assignments,
        inputs=inputs,
    )
    failed = runner.repository.read_events("meeting-1")[-1]

    runner.retry_failed_step(
        plan=COURTROOM_PLAN,
        meeting_id="meeting-1",
        step_id=failed["step_id"],
        goal="判斷遺產稅損失是否具有因果關係",
        model_assignments=assignments,
        role_display_names={"Defense": "辯護律師"},
        inputs=inputs,
    )

    events = runner.repository.read_events("meeting-1")
    instructions = [
        event
        for event in events
        if event.get("interaction_type") == "directed-role-instruction"
    ]
    responses = [
        event
        for event in events
        if event.get("interaction_type") == "directed-role-response"
    ]
    assert len(instructions) == 1
    assert [event["attempt"] for event in responses] == [1, 2, 3]
    assert [event["status"] for event in responses] == ["failed", "failed", "completed"]
    assert {event["in_response_to_event_id"] for event in responses} == {
        instructions[0]["event_id"]
    }
    assert instructions[0]["materials_revision"] == 7
    assert {event["materials_revision"] for event in responses} == {7}
    assert {event["materials_refs"][0]["version"] for event in responses} == {3}
    assert responses[-1]["step_id"] == "directed-1-defense-response"
    assert responses[-1]["base_step_id"] == "defense-response"
    retry_prompt = adapter.requests[-1].prompt
    assert "辯護律師" in retry_prompt
    assert "[證物二] 遺產稅繳納紀錄" in retry_prompt
    assert "請針對遺產稅因果關係補充答辯" in retry_prompt
    assert "PHASE-ONLY" not in retry_prompt
    assert "__case_evidence_by_role" not in json.dumps(events, ensure_ascii=False)
    assert "internal-envelope-only" not in json.dumps(events, ensure_ascii=False)


@pytest.mark.parametrize("failure_kind", ["timeout", "interrupted"])
def test_retry_timeout_or_interrupted_directed_response_reuses_instruction(
    tmp_path: Path,
    failure_kind: str,
) -> None:
    runner = build_runner(tmp_path, adapter=FakeAdapter([VALID_OUTPUT]))
    instruction_event_id = "meeting-1:human-directed-message:original"
    runner.repository.append_event(
        "meeting-1",
        {
            "event_id": instruction_event_id,
            "meeting_id": "meeting-1",
            "step_id": "human-directed-message",
            "role": "Human",
            "attempt": 1,
            "status": "completed",
            "interaction_type": "directed-role-instruction",
            "target_role_id": "Blue",
            "content": "請補充回答 timeout 後的原問題",
        },
    )
    runner.repository.append_event(
        "meeting-1",
        {
            "event_id": f"meeting-1:directed-1-blue-response:attempt-1:{failure_kind}",
            "meeting_id": "meeting-1",
            "step_id": "directed-1-blue-response",
            "base_step_id": "blue-response",
            "round": 1,
            "role": "Blue",
            "attempt": 1,
            "status": "failed",
            "failure_kind": failure_kind,
            "interaction_type": "directed-role-response",
            "directed_sequence": 1,
            "in_response_to_event_id": instruction_event_id,
            "output_schema_id": "role-output/v1",
            "error": "execution failed",
        },
    )

    runner.retry_failed_step(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        step_id="directed-1-blue-response",
        goal="回答原追問",
        model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
        role_display_names={"Blue": "藍軍"},
    )

    events = runner.repository.read_events("meeting-1")
    assert len([event for event in events if event["role"] == "Human"]) == 1
    completed = events[-1]
    assert completed["status"] == "completed"
    assert completed["attempt"] == 2
    assert completed["in_response_to_event_id"] == instruction_event_id
    assert "請補充回答 timeout 後的原問題" in completed["prompt_messages"][0]["content"]


def test_runner_runs_chair_directed_role_sequence(tmp_path: Path) -> None:
    adapter = FakeAdapter([VALID_OUTPUT] * 3)
    runner = build_runner(tmp_path, adapter=adapter)
    runner.repository.append_event(
        "meeting-1",
        {
            "event_id": "human-feedback",
            "meeting_id": "meeting-1",
            "step_id": "human-message",
            "role": "Human",
            "attempt": 1,
            "status": "completed",
            "content": "主席要求：Red 先挑戰，再由 Blue 修正，最後 Judge 裁決。",
        },
    )

    runner.respond_as_sequence(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        goal="先做後端？",
        roles=["Red", "Blue", "Judge"],
        model_assignments={
            "Blue": ModelConfig(id="mock-blue", adapter="mock"),
            "Red": ModelConfig(id="mock-red", adapter="mock"),
            "Judge": ModelConfig(id="mock-judge", adapter="mock"),
        },
    )

    completed = [
        event for event in runner.repository.read_events("meeting-1")
        if event["status"] == "completed" and event["role"] != "Human"
    ]
    assert [event["step_id"] for event in completed] == [
        "sequence-1-red-response",
        "sequence-1-blue-response",
        "sequence-1-judge-response",
    ]
    assert [event["role"] for event in completed] == ["Red", "Blue", "Judge"]
    assert {event["interaction_type"] for event in completed} == {"role-sequence-response"}
    assert {event["sequence"] for event in completed} == {1}
    assert [event["sequence_index"] for event in completed] == [1, 2, 3]
    assert "主席要求：Red 先挑戰" in adapter.requests[0].prompt


def test_role_sequence_uses_each_step_output_schema(tmp_path: Path) -> None:
    custom_schema_id = "test-output/v1"
    plan = RelayPlan(
        steps=[StepDefinition("blue-propose", "Blue", "blue_propose")],
        directed_steps={
            "Blue": StepDefinition(
                "blue-response",
                "Blue",
                "blue_revise",
                custom_schema_id,
            )
        },
    )
    registry = OutputSchemaRegistry(
        [OutputSchemaCodec(custom_schema_id, TEST_ONLY_SCHEMA, TestOnlyParser())]
    )
    runner = build_runner(
        tmp_path,
        adapter=FakeAdapter(['{"value":"sequence parsed"}']),
        output_schemas=registry,
    )

    runner.respond_as_sequence(
        plan=plan,
        meeting_id="meeting-1",
        goal="schema selection",
        roles=["Blue"],
        model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
    )

    event = runner.repository.read_events("meeting-1")[-1]
    assert event["interaction_type"] == "role-sequence-response"
    assert event["output_schema_id"] == custom_schema_id
    assert event["parsed_output"] == {"value": "sequence parsed"}


def test_runner_marks_step_failed_when_adapter_raises(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, adapter=FailingAdapter())

    runner.start(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        goal="先做後端？",
        model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
    )

    events = runner.repository.read_events("meeting-1")
    assert events[-1]["step_id"] == "blue-propose"
    assert events[-1]["status"] == "failed"
    assert "adapter boom" in events[-1]["error"]


def test_runner_marks_step_failed_when_output_cannot_be_parsed(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, adapter=FakeAdapter(["not json", "still not json"]))

    runner.start(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        goal="先做後端？",
        model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
    )

    events = runner.repository.read_events("meeting-1")
    assert [(event["attempt"], event["status"]) for event in events] == [
        (1, "failed"),
        (2, "failed"),
    ]
    assert events[-1]["step_id"] == "blue-propose"
    assert events[-1]["status"] == "failed"
    assert events[-1]["error"]


def test_runner_retry_failed_step_creates_second_attempt_and_continues(
    tmp_path: Path,
) -> None:
    runner = build_runner(tmp_path, adapter=FakeAdapter([VALID_OUTPUT] * 4))
    runner.repository.append_event(
        "meeting-1",
        {
            "event_id": "old-failure",
            "meeting_id": "meeting-1",
            "step_id": "blue-propose",
            "role": "Blue",
            "attempt": 1,
            "status": "failed",
            "error": "bad JSON",
        },
    )

    runner.retry_failed_step(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        step_id="blue-propose",
        goal="先做後端？",
        model_assignments={
            "Blue": ModelConfig(id="mock-blue", adapter="mock"),
            "Red": ModelConfig(id="mock-red", adapter="mock"),
            "Judge": ModelConfig(id="mock-judge", adapter="mock"),
        },
    )

    events = runner.repository.read_events("meeting-1")
    completed = [event for event in events if event["status"] == "completed"]
    assert completed[0]["step_id"] == "blue-propose"
    assert completed[0]["attempt"] == 2
    assert [event["step_id"] for event in completed] == [
        "blue-propose",
        "red-critique",
        "blue-revise",
        "judge-decide",
    ]


def test_retry_uses_the_failed_step_role_output_schema(tmp_path: Path) -> None:
    custom_schema_id = "test-output/v1"
    plan = RelayPlan(
        steps=[StepDefinition("blue-propose", "Blue", "blue_propose", custom_schema_id)],
        directed_steps={},
    )
    registry = OutputSchemaRegistry(
        [OutputSchemaCodec(custom_schema_id, TEST_ONLY_SCHEMA, TestOnlyParser())]
    )
    runner = build_runner(
        tmp_path,
        adapter=FakeAdapter(['{"value":"retry parsed"}']),
        output_schemas=registry,
    )
    runner.repository.append_event(
        "meeting-1",
        {
            "event_id": "old-failure",
            "meeting_id": "meeting-1",
            "step_id": "blue-propose",
            "role": "Blue",
            "attempt": 1,
            "status": "failed",
            "error": "bad JSON",
        },
    )

    runner.retry_failed_step(
        plan=plan,
        meeting_id="meeting-1",
        step_id="blue-propose",
        goal="schema selection",
        model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
    )

    event = runner.repository.read_events("meeting-1")[-1]
    assert event["attempt"] == 2
    assert event["output_schema_id"] == custom_schema_id
    assert event["output_schema_hash"] == TEST_ONLY_SCHEMA_HASH
    assert event["parsed_output"] == {"value": "retry parsed"}


def test_runner_retries_round_scoped_failed_step(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, adapter=FakeAdapter([VALID_OUTPUT] * 3))
    runner.repository.append_event(
        "meeting-1",
        {
            "event_id": "round-2-failure",
            "meeting_id": "meeting-1",
            "step_id": "round-2-red-critique",
            "base_step_id": "red-critique",
            "round": 2,
            "role": "Red",
            "attempt": 1,
            "status": "failed",
            "error": "bad JSON",
        },
    )

    runner.retry_failed_step(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        step_id="round-2-red-critique",
        goal="先做後端？",
        model_assignments={
            "Red": ModelConfig(id="mock-red", adapter="mock"),
            "Blue": ModelConfig(id="mock-blue", adapter="mock"),
            "Judge": ModelConfig(id="mock-judge", adapter="mock"),
        },
    )

    events = runner.repository.read_events("meeting-1")
    completed = [event for event in events if event["status"] == "completed"]
    assert [event["step_id"] for event in completed] == [
        "round-2-red-critique",
        "round-2-blue-revise",
        "round-2-judge-decide",
    ]
    assert completed[0]["attempt"] == 2


def test_runner_rejects_retry_when_step_is_not_failed(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, adapter=FakeAdapter([VALID_OUTPUT] * 4))
    runner.start(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        goal="先做後端？",
        model_assignments={
            "Blue": ModelConfig(id="mock-blue", adapter="mock"),
            "Red": ModelConfig(id="mock-red", adapter="mock"),
            "Judge": ModelConfig(id="mock-judge", adapter="mock"),
        },
    )

    with pytest.raises(ValueError):
        runner.retry_failed_step(
            plan=RED_BLUE_PLAN,
            meeting_id="meeting-1",
            step_id="blue-propose",
            goal="先做後端？",
            model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
        )


def test_runner_rejects_retry_for_unknown_step(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, adapter=FakeAdapter([VALID_OUTPUT]))

    with pytest.raises(ValueError):
        runner.retry_failed_step(
            plan=RED_BLUE_PLAN,
            meeting_id="meeting-1",
            step_id="unknown-step",
            goal="先做後端？",
            model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
        )


def test_runner_cancel_records_cancellation_and_start_does_not_run_steps(
    tmp_path: Path,
) -> None:
    runner = build_runner(tmp_path, adapter=FakeAdapter([VALID_OUTPUT] * 4))

    runner.cancel("meeting-1")
    runner.start(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        goal="先做後端？",
        model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
    )

    events = runner.repository.read_events("meeting-1")
    assert strip_created_at(events) == [
        {
            "event_id": "meeting-1:cancelled",
            "meeting_id": "meeting-1",
            "step_id": "meeting",
            "role": "System",
            "attempt": 1,
            "status": "cancelled",
        }
    ]


def test_runner_start_tags_adapter_requests_with_meeting_id(tmp_path: Path) -> None:
    adapter = FakeAdapter([VALID_OUTPUT] * 4)
    runner = build_runner(tmp_path, adapter=adapter)

    runner.start(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        goal="先做後端？",
        model_assignments={
            "Blue": ModelConfig(id="mock-blue", adapter="mock"),
            "Red": ModelConfig(id="mock-red", adapter="mock"),
            "Judge": ModelConfig(id="mock-judge", adapter="mock"),
        },
    )

    assert [request.meeting_id for request in adapter.requests] == ["meeting-1"] * 4


def test_runner_cancel_notifies_adapters_that_support_cancellation(tmp_path: Path) -> None:
    adapter = CancellableFakeAdapter([VALID_OUTPUT] * 4)
    runner = build_runner(tmp_path, adapter=adapter)

    runner.cancel("meeting-1")

    assert adapter.cancelled_meeting_ids == ["meeting-1"]


def test_runner_records_cancelled_subscription_cli_attempt_without_transcript_output(
    tmp_path: Path,
) -> None:
    started_marker = tmp_path / "cli-started"
    cli = tmp_path / "slow_cli.py"
    cli.write_text(
        "import pathlib, time\n"
        f"pathlib.Path({str(started_marker)!r}).write_text('started')\n"
        "print('partial subscription output', flush=True)\n"
        "time.sleep(30)\n",
        encoding="utf-8",
    )
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "directed_role_response.md").write_text(
        "{{ role }} {{ goal }} {{ prior_transcript }} {{ required_json_schema }} "
        "{{ role_display_name }} {{ instruction }}",
        encoding="utf-8",
    )
    runner = MeetingRunner(
        repository=MeetingRepository(tmp_path / "data"),
        prompt_renderer=PromptRenderer(prompt_dir),
        adapters=RunnerAdapters(by_name={"subscription-cli": SubscriptionCLIAdapter()}),
    )
    model = ModelConfig(
        id="cli-blue",
        adapter="subscription-cli",
        command=[sys.executable, str(cli), "{prompt}"],
        timeout_seconds=60,
    )
    thread = Thread(
        target=lambda: runner.respond_as_role(
            plan=RED_BLUE_PLAN,
            meeting_id="meeting-1",
            goal="取消 CLI",
            role="Blue",
            role_display_name="藍軍",
            instruction="回答取消測試",
            model_assignments={"Blue": model},
        )
    )
    thread.start()
    deadline = time.monotonic() + 3
    while not started_marker.exists() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert started_marker.exists(), "subscription CLI did not start"

    runner.cancel("meeting-1")
    thread.join(timeout=3)

    assert not thread.is_alive()
    instruction, lifecycle, diagnostic = runner.repository.read_events("meeting-1")
    assert instruction["interaction_type"] == "directed-role-instruction"
    assert lifecycle["status"] == "cancelled"
    assert diagnostic["status"] == "failed"
    assert diagnostic["failure_kind"] == "interrupted"
    assert diagnostic["in_response_to_event_id"] == instruction["event_id"]
    assert diagnostic["retry_scheduled"] is False
    assert diagnostic["result_discarded"] is True
    assert diagnostic["adapter"] == "subscription-cli"
    assert diagnostic["adapter_stdout_excerpt"] == "partial subscription output"
    serialized = json.dumps(diagnostic)
    assert str(cli) not in serialized
    assert "command" not in diagnostic
    assert "env" not in diagnostic
    transcript = runner.transcript_projector.project(
        runner.repository.read_events("meeting-1"), title="取消 CLI"
    )
    assert diagnostic["step_id"] not in transcript
    assert "partial subscription output" not in transcript


@pytest.mark.parametrize("raw_output", [VALID_OUTPUT, "not json"])
def test_sequential_terminal_result_is_recorded_as_discarded_without_parse_retry(
    tmp_path: Path,
    raw_output: str,
) -> None:
    repository = MeetingRepository(tmp_path / "data")

    class CancelThenRespondAdapter:
        calls = 0

        def complete(self, request: ModelRequest) -> ModelResponse:
            self.calls += 1
            assert request.meeting_id is not None
            repository.append_event(
                request.meeting_id,
                {
                    "event_id": f"{request.meeting_id}:cancelled",
                    "meeting_id": request.meeting_id,
                    "step_id": "meeting",
                    "role": "System",
                    "attempt": 1,
                    "status": "cancelled",
                },
            )
            return ModelResponse(
                raw_output=raw_output,
                token_usage={"prompt_tokens": 4, "completion_tokens": 1, "total_tokens": 5},
            )

    adapter = CancelThenRespondAdapter()
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "directed_role_response.md").write_text(
        "{{ role }} {{ goal }} {{ prior_transcript }} {{ required_json_schema }} "
        "{{ role_display_name }} {{ instruction }}",
        encoding="utf-8",
    )
    runner = MeetingRunner(
        repository=repository,
        prompt_renderer=PromptRenderer(prompt_dir),
        adapters=RunnerAdapters(by_name={"mock": adapter}),
    )

    runner.respond_as_role(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        goal="terminal response",
        role="Blue",
        role_display_name="藍軍",
        instruction="回答終止測試",
        model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
    )

    instruction, lifecycle, diagnostic = repository.read_events("meeting-1")
    assert instruction["interaction_type"] == "directed-role-instruction"
    assert lifecycle["status"] == "cancelled"
    assert adapter.calls == 1
    assert diagnostic["status"] == "failed"
    assert diagnostic["failure_kind"] == "interrupted"
    assert diagnostic["result_discarded"] is True
    assert diagnostic["retry_scheduled"] is False
    assert diagnostic["raw_output"] == raw_output
    assert diagnostic["token_usage"]["total_tokens"] == 5
    if raw_output == VALID_OUTPUT:
        assert diagnostic["parsed_output"]["summary"] == "OK"
    else:
        assert "parsed_output" not in diagnostic
    assert diagnostic["step_id"] not in runner.transcript_projector.project(
        [lifecycle, diagnostic], title="terminal response"
    )


def test_relay_cancel_after_parse_failure_does_not_start_scheduled_retry(
    tmp_path: Path,
) -> None:
    class CancellingParseRepository(MeetingRepository):
        cancelled = False

        def append_event(self, meeting_id: str, event: dict[str, object]) -> None:
            super().append_event(meeting_id, event)
            if event.get("failure_kind") == "parse_error" and not self.cancelled:
                self.cancelled = True
                super().append_event(
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

    repository = CancellingParseRepository(tmp_path / "data")
    adapter = FakeAdapter(["not json", VALID_OUTPUT])
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    (prompt_dir / "directed_role_response.md").write_text(
        "{{ role }} {{ goal }} {{ prior_transcript }} {{ required_json_schema }} "
        "{{ role_display_name }} {{ instruction }}",
        encoding="utf-8",
    )
    runner = MeetingRunner(
        repository=repository,
        prompt_renderer=PromptRenderer(prompt_dir),
        adapters=RunnerAdapters(by_name={"mock": adapter}),
    )

    runner.respond_as_role(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        goal="retry dispatch 前取消",
        role="Blue",
        role_display_name="藍軍",
        instruction="回答重試取消測試",
        model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
    )

    events = repository.read_events("meeting-1")
    assert len(adapter.requests) == 1
    response_events = [event for event in events if event["role"] != "Human"]
    assert [(event["status"], event.get("failure_kind")) for event in response_events] == [
        ("failed", "parse_error"),
        ("cancelled", None),
    ]
    assert response_events[0]["retry_scheduled"] is True


def test_parallel_cancel_after_members_complete_does_not_start_synthesis(
    tmp_path: Path,
) -> None:
    class CancellingAfterFanoutRepository(MeetingRepository):
        completed_members = 0

        def append_event(self, meeting_id: str, event: dict[str, object]) -> None:
            super().append_event(meeting_id, event)
            if event.get("status") != "completed" or not str(event.get("step_id", "")).startswith(
                "fanout-"
            ):
                return
            self.completed_members += 1
            if self.completed_members == 3:
                super().append_event(
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

    repository = CancellingAfterFanoutRepository(tmp_path / "data")
    adapter = FakeAdapter([VALID_OUTPUT] * 4)
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    for template in ("brainstorm_member", "brainstorm_synthesis"):
        (prompt_dir / f"{template}.md").write_text(
            "{{ role }} {{ goal }} {{ prior_transcript }} "
            "{{ required_json_schema }} {{ fanout_outputs }}",
            encoding="utf-8",
        )
    runner = MeetingRunner(
        repository=repository,
        prompt_renderer=PromptRenderer(prompt_dir),
        adapters=RunnerAdapters(by_name={"mock": adapter}),
    )

    runner.start_parallel(
        plan=PARALLEL_PLAN,
        meeting_id="meeting-1",
        goal="synthesis dispatch 前取消",
        model_assignments=parallel_model_assignments(),
    )

    events = repository.read_events("meeting-1")
    assert len(adapter.requests) == 3
    assert {event["step_id"] for event in events[:-1]} == {
        "fanout-1-member-1",
        "fanout-1-member-2",
        "fanout-1-member-3",
    }
    assert events[-1]["step_id"] == "meeting"
    assert all(event["step_id"] != "synthesis-1" for event in events)


def test_parallel_terminal_at_publish_boundary_discards_completed_member_groups_in_member_order(
    tmp_path: Path,
) -> None:
    all_groups_built = Event()
    release_publish = Event()
    built_lock = Lock()
    built_count = 0

    class PublishBoundaryRunner(MeetingRunner):
        def _build_parallel_member_events(self, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal built_count
            events = super()._build_parallel_member_events(**kwargs)
            with built_lock:
                built_count += 1
                if built_count == len(PARALLEL_PLAN.members):
                    all_groups_built.set()
            assert release_publish.wait(timeout=5)
            return events

    repository = MeetingRepository(tmp_path / "data")
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    for template in ("brainstorm_member", "brainstorm_synthesis"):
        (prompt_dir / f"{template}.md").write_text(
            "{{ role }} {{ goal }} {{ prior_transcript }} "
            "{{ required_json_schema }} {{ fanout_outputs }}",
            encoding="utf-8",
        )
    runner = PublishBoundaryRunner(
        repository=repository,
        prompt_renderer=PromptRenderer(prompt_dir),
        adapters=RunnerAdapters(by_name={"mock": FakeAdapter([VALID_OUTPUT] * 3)}),
    )
    run_error: list[BaseException] = []

    def run_parallel() -> None:
        try:
            runner.start_parallel(
                plan=PARALLEL_PLAN,
                meeting_id="meeting-1",
                goal="publish boundary cancellation",
                model_assignments=parallel_model_assignments(),
            )
        except BaseException as error:  # pragma: no cover - asserted below
            run_error.append(error)

    worker = Thread(target=run_parallel)
    worker.start()
    assert all_groups_built.wait(timeout=5)
    repository.append_event(
        "meeting-1",
        {
            "event_id": "meeting-1:cancelled",
            "meeting_id": "meeting-1",
            "step_id": "meeting",
            "role": "System",
            "attempt": 1,
            "status": "cancelled",
        },
    )
    release_publish.set()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert run_error == []
    events = repository.read_events("meeting-1")
    assert events[0]["status"] == "cancelled"
    diagnostics = events[1:]
    assert [event["base_step_id"] for event in diagnostics] == [
        "member-1",
        "member-2",
        "member-3",
    ]
    assert all(event["status"] == "failed" for event in diagnostics)
    assert all(event["failure_kind"] == "interrupted" for event in diagnostics)
    assert all(event["result_discarded"] is True for event in diagnostics)
    assert all(event["retry_scheduled"] is False for event in diagnostics)

def test_parallel_cancel_records_each_started_member_in_deterministic_order(
    tmp_path: Path,
) -> None:
    class BlockingAdapter:
        def __init__(self, expected_calls: int) -> None:
            self.expected_calls = expected_calls
            self.calls = 0
            self.lock = Lock()
            self.all_started = Event()
            self.release = Event()

        def complete(self, request: ModelRequest) -> ModelResponse:
            with self.lock:
                self.calls += 1
                if self.calls == self.expected_calls:
                    self.all_started.set()
            assert self.release.wait(timeout=3)
            return ModelResponse(
                raw_output=VALID_OUTPUT,
                token_usage={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
            )

        def cancel(self, meeting_id: str) -> None:
            self.release.set()

    adapter = BlockingAdapter(expected_calls=3)
    runner = build_runner(
        tmp_path,
        adapter=adapter,
        templates=("brainstorm_member", "brainstorm_synthesis"),
    )
    thread = Thread(
        target=lambda: runner.start_parallel(
            plan=PARALLEL_PLAN,
            meeting_id="meeting-1",
            goal="取消平行執行",
            model_assignments=parallel_model_assignments(),
        )
    )
    thread.start()
    assert adapter.all_started.wait(timeout=3)

    runner.cancel("meeting-1")
    thread.join(timeout=3)

    assert not thread.is_alive()
    events = runner.repository.read_events("meeting-1")
    assert events[0]["status"] == "cancelled"
    diagnostics = events[1:]
    assert [event["step_id"] for event in diagnostics] == [
        "fanout-1-member-1",
        "fanout-1-member-2",
        "fanout-1-member-3",
    ]
    assert all(event["status"] == "failed" for event in diagnostics)
    assert all(event["failure_kind"] == "interrupted" for event in diagnostics)
    assert all(event["retry_scheduled"] is False for event in diagnostics)
    assert all(event["result_discarded"] is True for event in diagnostics)
    assert all(event["raw_output"] == VALID_OUTPUT for event in diagnostics)
    assert all(event["token_usage"]["total_tokens"] == 5 for event in diagnostics)
    transcript = runner.transcript_projector.project(events, title="取消平行執行")
    assert "fanout-1-member" not in transcript


def test_runner_close_records_closure_and_blocks_future_ai_steps(tmp_path: Path) -> None:
    adapter = FakeAdapter([VALID_OUTPUT] * 2)
    runner = build_runner(tmp_path, adapter=adapter)

    runner.close("meeting-1")
    runner.start(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        goal="先做後端？",
        model_assignments={
            "Blue": ModelConfig(id="mock-blue", adapter="mock"),
            "Red": ModelConfig(id="mock-red", adapter="mock"),
            "Judge": ModelConfig(id="mock-judge", adapter="mock"),
        },
    )
    runner.respond_as_role(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        goal="先做後端？",
        role="Blue",
        role_display_name="藍軍",
        instruction="回答問題",
        model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
    )
    runner.respond_as_sequence(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        goal="先做後端？",
        roles=["Red", "Judge"],
        model_assignments={
            "Red": ModelConfig(id="mock-red", adapter="mock"),
            "Judge": ModelConfig(id="mock-judge", adapter="mock"),
        },
    )

    events = runner.repository.read_events("meeting-1")
    assert strip_created_at(events) == [
        {
            "event_id": "meeting-1:closed",
            "meeting_id": "meeting-1",
            "step_id": "meeting",
            "role": "System",
            "attempt": 1,
            "status": "closed",
        }
    ]
    assert adapter.requests == []


def test_runner_terminal_events_are_idempotent(tmp_path: Path) -> None:
    runner = build_runner(tmp_path, adapter=FakeAdapter([]))

    runner.close("meeting-1")
    runner.close("meeting-1")
    runner.cancel("meeting-1")

    events = runner.repository.read_events("meeting-1")
    assert strip_created_at(events) == [
        {
            "event_id": "meeting-1:closed",
            "meeting_id": "meeting-1",
            "step_id": "meeting",
            "role": "System",
            "attempt": 1,
            "status": "closed",
        }
    ]


def test_runner_allows_steps_after_reopened_terminal_event(tmp_path: Path) -> None:
    adapter = FakeAdapter([VALID_OUTPUT] * 4)
    runner = build_runner(tmp_path, adapter=adapter)
    runner.repository.append_event(
        "meeting-1",
        {
            "event_id": "meeting-1:closed",
            "meeting_id": "meeting-1",
            "step_id": "meeting",
            "role": "System",
            "attempt": 1,
            "status": "closed",
        },
    )
    runner.repository.append_event(
        "meeting-1",
        {
            "event_id": "meeting-1:reopened:1",
            "meeting_id": "meeting-1",
            "step_id": "meeting",
            "role": "System",
            "attempt": 1,
            "status": "reopened",
        },
    )

    runner.start(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        goal="先做後端？",
        model_assignments={
            "Blue": ModelConfig(id="mock-blue", adapter="mock"),
            "Red": ModelConfig(id="mock-red", adapter="mock"),
            "Judge": ModelConfig(id="mock-judge", adapter="mock"),
        },
    )

    events = strip_created_at(runner.repository.read_events("meeting-1"))
    assert [event["status"] for event in events] == [
        "closed",
        "reopened",
        "completed",
        "completed",
        "completed",
        "completed",
    ]


def test_runner_completes_courtroom_flow(tmp_path: Path) -> None:
    runner = build_runner(
        tmp_path,
        adapter=FakeAdapter([VALID_OUTPUT] * 8),
        templates=(
            "courtroom_charge",
            "courtroom_defense",
            "courtroom_rebuttal",
            "courtroom_verdict",
        ),
    )
    model_assignments = {
        "Prosecutor": ModelConfig(id="mock-prosecutor", adapter="mock"),
        "Defense": ModelConfig(id="mock-defense", adapter="mock"),
        "Judge": ModelConfig(id="mock-judge", adapter="mock"),
    }

    runner.start(
        plan=COURTROOM_PLAN,
        meeting_id="meeting-1",
        goal="被告是否有罪？",
        model_assignments=model_assignments,
    )

    events = runner.repository.read_events("meeting-1")
    completed_steps = [event for event in events if event["status"] == "completed"]
    assert [event["step_id"] for event in completed_steps] == [
        "courtroom-charge",
        "courtroom-defense",
        "courtroom-rebuttal",
        "courtroom-verdict",
    ]

    runner.start(
        plan=COURTROOM_PLAN,
        meeting_id="meeting-1",
        goal="被告是否有罪？",
        model_assignments=model_assignments,
    )

    events = runner.repository.read_events("meeting-1")
    completed_steps = [event for event in events if event["status"] == "completed"]
    assert [event["step_id"] for event in completed_steps] == [
        "courtroom-charge",
        "courtroom-defense",
        "courtroom-rebuttal",
        "courtroom-verdict",
        "round-2-courtroom-charge",
        "round-2-courtroom-defense",
        "round-2-courtroom-rebuttal",
        "round-2-courtroom-verdict",
    ]


def test_runner_renders_mode_inputs_into_prompt(tmp_path: Path) -> None:
    runner = build_runner(
        tmp_path,
        adapter=FakeAdapter([VALID_OUTPUT]),
        extra_placeholders=" {{ position_a }}",
    )

    runner.respond_as_role(
        plan=RED_BLUE_PLAN,
        meeting_id="meeting-1",
        goal="先做後端？",
        role="Blue",
        role_display_name="藍軍",
        instruction="比較兩個立場",
        model_assignments={"Blue": ModelConfig(id="mock-blue", adapter="mock")},
        inputs={"position_a": "先做後端"},
    )

    events = runner.repository.read_events("meeting-1")
    completed_event = events[-1]
    assert completed_event["status"] == "completed"
    assert "先做後端" in completed_event["prompt_messages"][0]["content"]


def test_parallel_runner_completes_fanout_then_synthesis(tmp_path: Path) -> None:
    runner = build_runner(
        tmp_path,
        adapter=FakeAdapter([VALID_OUTPUT] * 4),
        templates=("brainstorm_member", "brainstorm_synthesis"),
        extra_placeholders=" {{ instance_prompt }} {{ fanout_outputs }}",
    )

    runner.start_parallel(
        plan=PARALLEL_PLAN,
        meeting_id="meeting-1",
        goal="如何改善 onboarding？",
        model_assignments=parallel_model_assignments(),
    )

    events = runner.repository.read_events("meeting-1")
    completed = [event for event in events if event["status"] == "completed"]
    assert {event["step_id"] for event in completed[:-1]} == {
        "fanout-1-member-1",
        "fanout-1-member-2",
        "fanout-1-member-3",
    }
    assert completed[-1]["step_id"] == "synthesis-1"
    assert {event["base_step_id"] for event in completed[:-1]} == {
        "member-1",
        "member-2",
        "member-3",
    }
    assert completed[-1]["base_step_id"] == "synthesis"
    synthesis_prompt = completed[-1]["prompt_messages"][0]["content"]
    assert "Member-1" in synthesis_prompt
    assert "Continue" in synthesis_prompt
    assert {event["output_schema_id"] for event in completed} == {"role-output/v1"}


def test_parallel_runner_publishes_members_in_arrival_order_from_one_round_start_context(
    tmp_path: Path,
) -> None:
    class SignallingRepository(MeetingRepository):
        def __init__(self, root: Path) -> None:
            super().__init__(root)
            self.appended = {
                "fanout-1-member-1": Event(),
                "fanout-1-member-2": Event(),
                "fanout-1-member-3": Event(),
            }

        def append_event(self, meeting_id: str, event: dict[str, object]) -> None:
            super().append_event(meeting_id, event)
            signal = self.appended.get(str(event.get("step_id")))
            if signal is not None:
                signal.set()

    class ControlledArrivalAdapter:
        def __init__(self) -> None:
            self.lock = Lock()
            self.member_requests: dict[str, ModelRequest] = {}
            self.member_started = {role: Event() for role in ("Member-1", "Member-2", "Member-3")}
            self.release = {role: Event() for role in ("Member-1", "Member-2", "Member-3")}
            self.synthesis_started = Event()

        def complete(self, request: ModelRequest) -> ModelResponse:
            role = request.model_config.id.removeprefix("mock-").title()
            if role == "Moderator":
                self.synthesis_started.set()
                return ModelResponse(raw_output=VALID_OUTPUT)
            with self.lock:
                self.member_requests[role] = request
            self.member_started[role].set()
            assert self.release[role].wait(timeout=10)
            return ModelResponse(
                raw_output=json.dumps(
                    {
                        "summary": f"{role} completed",
                        "arguments": [],
                        "risks": [],
                        "recommendation": "Continue",
                    }
                )
            )

    repository = SignallingRepository(tmp_path / "data")
    repository.append_event(
        "meeting-1",
        {
            "event_id": "prior-event",
            "meeting_id": "meeting-1",
            "step_id": "prior-step",
            "role": "Human",
            "attempt": 1,
            "status": "completed",
            "raw_output": "ROUND_START_CONTEXT",
        },
    )
    adapter = ControlledArrivalAdapter()
    runner = build_runner(
        tmp_path,
        adapter=adapter,
        templates=("brainstorm_member", "brainstorm_synthesis"),
        extra_placeholders=" {{ instance_prompt }} {{ fanout_outputs }}",
        repository=repository,
    )
    thread = Thread(
        target=lambda: runner.start_parallel(
            plan=PARALLEL_PLAN,
            meeting_id="meeting-1",
            goal="如何改善 onboarding？",
            model_assignments=parallel_model_assignments(),
        )
    )
    thread.start()
    for started in adapter.member_started.values():
        assert started.wait(timeout=3)

    try:
        adapter.release["Member-3"].set()
        member_three_visible_while_running = repository.appended[
            "fanout-1-member-3"
        ].wait(timeout=1)
        partial_steps = [
            event["step_id"]
            for event in repository.read_events("meeting-1")
            if str(event["step_id"]).startswith("fanout-")
        ]
        synthesis_started_early = adapter.synthesis_started.is_set()

        adapter.release["Member-1"].set()
        assert repository.appended["fanout-1-member-1"].wait(timeout=3)
        adapter.release["Member-2"].set()
    finally:
        for release in adapter.release.values():
            release.set()
        thread.join(timeout=3)

    assert not thread.is_alive()
    assert member_three_visible_while_running is True
    assert partial_steps == ["fanout-1-member-3"]
    assert synthesis_started_early is False
    events = repository.read_events("meeting-1")
    assert [
        event["step_id"]
        for event in events
        if str(event["step_id"]).startswith(("fanout-", "synthesis-"))
    ] == [
        "fanout-1-member-3",
        "fanout-1-member-1",
        "fanout-1-member-2",
        "synthesis-1",
    ]

    schema = runner.output_schemas.get("role-output/v1").schema
    prior_transcripts = {
        request.prompt.split("如何改善 onboarding？", maxsplit=1)[1]
        .split(schema, maxsplit=1)[0]
        .strip()
        for request in adapter.member_requests.values()
    }
    assert len(prior_transcripts) == 1
    assert "prior-step" in prior_transcripts.pop()


def test_parallel_restart_synthesis_uses_only_active_epoch_members(tmp_path: Path) -> None:
    old_output = json.dumps(
        {"summary": "ARCHIVED_MEMBER", "arguments": [], "risks": [], "recommendation": "old"}
    )
    new_output = json.dumps(
        {"summary": "ACTIVE_MEMBER", "arguments": [], "risks": [], "recommendation": "new"}
    )
    runner = build_runner(
        tmp_path,
        adapter=FakeAdapter([old_output] * 4 + [new_output] * 4),
        templates=("brainstorm_member", "brainstorm_synthesis"),
        extra_placeholders=" {{ instance_prompt }} {{ fanout_outputs }}",
    )
    assignments = parallel_model_assignments()
    runner.start_parallel(
        plan=PARALLEL_PLAN,
        meeting_id="meeting-1",
        goal="first",
        model_assignments=assignments,
    )
    raw = runner.repository.read_events("meeting-1")
    runner.repository.append_event(
        "meeting-1",
        DeliberationEpochs.restart_marker(
            meeting_id="meeting-1",
            events=raw,
            command=RestartCommand(scope="all_deliberation", reason="fresh synthesis"),
        ),
    )

    runner.start_parallel(
        plan=PARALLEL_PLAN,
        meeting_id="meeting-1",
        goal="second",
        model_assignments=assignments,
    )

    active = DeliberationEpochs.view(
        runner.repository.read_events("meeting-1")
    ).active_events
    synthesis_prompt = active[-1]["prompt_messages"][0]["content"]
    assert active[-1]["step_id"] == "synthesis-1"
    assert "ACTIVE_MEMBER" in synthesis_prompt
    assert "ARCHIVED_MEMBER" not in synthesis_prompt


def test_parallel_fanout_and_synthesis_use_their_step_output_schemas(tmp_path: Path) -> None:
    custom_schema_id = "test-output/v1"
    plan = ParallelPlan(
        members=[
            ParallelMemberStep(
                step_id="member-1",
                role="Member-1",
                template_name="brainstorm_member",
                display_name="委員 1",
                instance_prompt="",
                index=1,
                output_schema_id=custom_schema_id,
            )
        ],
        synthesis=StepDefinition(
            "synthesis",
            "Moderator",
            "brainstorm_synthesis",
            custom_schema_id,
        ),
    )
    registry = OutputSchemaRegistry(
        [OutputSchemaCodec(custom_schema_id, TEST_ONLY_SCHEMA, TestOnlyParser())]
    )
    adapter = FakeAdapter(['{"value":"member"}', '{"value":"synthesis"}'])
    runner = build_runner(
        tmp_path,
        adapter=adapter,
        templates=("brainstorm_member", "brainstorm_synthesis"),
        extra_placeholders=" {{ fanout_outputs }}",
        output_schemas=registry,
    )

    runner.start_parallel(
        plan=plan,
        meeting_id="meeting-1",
        goal="schema selection",
        model_assignments={
            "Member-1": ModelConfig(id="mock-member", adapter="mock"),
            "Moderator": ModelConfig(id="mock-moderator", adapter="mock"),
        },
    )

    events = runner.repository.read_events("meeting-1")
    assert [event["output_schema_id"] for event in events] == [
        custom_schema_id,
        custom_schema_id,
    ]
    assert [event["parsed_output"] for event in events] == [
        {"value": "member"},
        {"value": "synthesis"},
    ]
    assert [request.output_schema_id for request in adapter.requests] == [
        custom_schema_id,
        custom_schema_id,
    ]


def test_parallel_member_parse_failure_is_recorded_then_auto_retried(
    tmp_path: Path,
) -> None:
    class RetryFirstMemberAdapter:
        first_member_calls = 0

        def complete(self, request: ModelRequest) -> ModelResponse:
            if request.model_config.id == "mock-member-1":
                self.first_member_calls += 1
                if self.first_member_calls == 1:
                    return ModelResponse(raw_output="not json")
                return ModelResponse(raw_output='{"value":"member 1 recovered"}')
            if request.model_config.id == "mock-member-2":
                return ModelResponse(raw_output='{"value":"member 2"}')
            return ModelResponse(raw_output='{"value":"synthesis"}')

    custom_schema_id = "test-output/v1"
    plan = ParallelPlan(
        members=[
            ParallelMemberStep(
                step_id="member-1",
                role="Member-1",
                template_name="brainstorm_member",
                display_name="委員 1",
                instance_prompt="",
                index=1,
                output_schema_id=custom_schema_id,
            ),
            ParallelMemberStep(
                step_id="member-2",
                role="Member-2",
                template_name="brainstorm_member",
                display_name="委員 2",
                instance_prompt="",
                index=2,
                output_schema_id=custom_schema_id,
            ),
        ],
        synthesis=StepDefinition(
            "synthesis",
            "Moderator",
            "brainstorm_synthesis",
            custom_schema_id,
        ),
    )
    registry = OutputSchemaRegistry(
        [OutputSchemaCodec(custom_schema_id, TEST_ONLY_SCHEMA, TestOnlyParser())]
    )
    runner = build_runner(
        tmp_path,
        adapter=RetryFirstMemberAdapter(),
        templates=("brainstorm_member", "brainstorm_synthesis"),
        extra_placeholders=" {{ fanout_outputs }}",
        output_schemas=registry,
    )

    runner.start_parallel(
        plan=plan,
        meeting_id="meeting-1",
        goal="schema retry",
        model_assignments={
            "Member-1": ModelConfig(id="mock-member-1", adapter="mock"),
            "Member-2": ModelConfig(id="mock-member-2", adapter="mock"),
            "Moderator": ModelConfig(id="mock-moderator", adapter="mock"),
        },
    )

    events = runner.repository.read_events("meeting-1")
    assert {
        (event["step_id"], event["attempt"], event["status"])
        for event in events[:-1]
    } == {
        ("fanout-1-member-1", 1, "failed"),
        ("fanout-1-member-1", 2, "completed"),
        ("fanout-1-member-2", 1, "completed"),
    }
    assert (events[-1]["step_id"], events[-1]["attempt"], events[-1]["status"]) == (
        "synthesis-1",
        1,
        "completed",
    )
    assert {event["output_schema_id"] for event in events} == {custom_schema_id}
    assert len({event["output_schema_hash"] for event in events}) == 1


def test_parallel_member_two_parse_failures_wait_for_manual_attempt_three(
    tmp_path: Path,
) -> None:
    custom_schema_id = "test-output/v1"
    member = ParallelMemberStep(
        step_id="member-1",
        role="Member-1",
        template_name="brainstorm_member",
        display_name="委員 1",
        instance_prompt="",
        index=1,
        output_schema_id=custom_schema_id,
    )
    plan = ParallelPlan(
        members=[member],
        synthesis=StepDefinition(
            "synthesis",
            "Moderator",
            "brainstorm_synthesis",
            custom_schema_id,
        ),
    )
    registry = OutputSchemaRegistry(
        [OutputSchemaCodec(custom_schema_id, TEST_ONLY_SCHEMA, TestOnlyParser())]
    )
    runner = build_runner(
        tmp_path,
        adapter=FakeAdapter(
            [
                "not json",
                "still not json",
                '{"value":"member recovered"}',
                '{"value":"synthesis"}',
            ]
        ),
        templates=("brainstorm_member", "brainstorm_synthesis"),
        extra_placeholders=" {{ fanout_outputs }}",
        output_schemas=registry,
    )
    assignments = {
        "Member-1": ModelConfig(id="mock-member", adapter="mock"),
        "Moderator": ModelConfig(id="mock-moderator", adapter="mock"),
    }

    runner.start_parallel(
        plan=plan,
        meeting_id="meeting-1",
        goal="schema retry",
        model_assignments=assignments,
    )

    events = runner.repository.read_events("meeting-1")
    assert [(event["attempt"], event["status"]) for event in events] == [
        (1, "failed"),
        (2, "failed"),
    ]

    runner.retry_failed_parallel_step(
        plan=plan,
        meeting_id="meeting-1",
        step_id="fanout-1-member-1",
        goal="schema retry",
        model_assignments=assignments,
    )

    events = runner.repository.read_events("meeting-1")
    assert [
        (event["step_id"], event["attempt"], event["status"])
        for event in events
    ] == [
        ("fanout-1-member-1", 1, "failed"),
        ("fanout-1-member-1", 2, "failed"),
        ("fanout-1-member-1", 3, "completed"),
        ("synthesis-1", 1, "completed"),
    ]


def test_parallel_parse_retry_stops_before_second_call_when_meeting_is_cancelled(
    tmp_path: Path,
) -> None:
    class CancellingInvalidAdapter:
        def __init__(self, repository: MeetingRepository) -> None:
            self.repository = repository
            self.calls = 0

        def complete(self, request: ModelRequest) -> ModelResponse:
            self.calls += 1
            assert request.meeting_id is not None
            self.repository.append_event(
                request.meeting_id,
                {
                    "event_id": f"{request.meeting_id}:cancelled",
                    "meeting_id": request.meeting_id,
                    "step_id": "meeting-cancelled",
                    "role": "System",
                    "attempt": 1,
                    "status": "cancelled",
                },
            )
            return ModelResponse(raw_output="not json")

    custom_schema_id = "test-output/v1"
    member = ParallelMemberStep(
        step_id="member-1",
        role="Member-1",
        template_name="brainstorm_member",
        display_name="委員 1",
        instance_prompt="",
        index=1,
        output_schema_id=custom_schema_id,
    )
    plan = ParallelPlan(
        members=[member],
        synthesis=StepDefinition(
            "synthesis",
            "Moderator",
            "brainstorm_synthesis",
            custom_schema_id,
        ),
    )
    registry = OutputSchemaRegistry(
        [OutputSchemaCodec(custom_schema_id, TEST_ONLY_SCHEMA, TestOnlyParser())]
    )
    repository = MeetingRepository(tmp_path / "data")
    adapter = CancellingInvalidAdapter(repository)
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    for template in ("brainstorm_member", "brainstorm_synthesis"):
        (prompt_dir / f"{template}.md").write_text(
            "{{ required_json_schema }} {{ fanout_outputs }}",
            encoding="utf-8",
        )
    runner = MeetingRunner(
        repository=repository,
        prompt_renderer=PromptRenderer(prompt_dir),
        adapters=RunnerAdapters(by_name={"mock": adapter}),
        output_schemas=registry,
    )

    runner.start_parallel(
        plan=plan,
        meeting_id="meeting-1",
        goal="取消 retry",
        model_assignments={
            "Member-1": ModelConfig(id="mock-member", adapter="mock"),
            "Moderator": ModelConfig(id="mock-moderator", adapter="mock"),
        },
    )

    assert adapter.calls == 1
    events = repository.read_events("meeting-1")
    assert strip_created_at(events)[0] == {
        "event_id": "meeting-1:cancelled",
        "meeting_id": "meeting-1",
        "step_id": "meeting-cancelled",
        "role": "System",
        "attempt": 1,
        "status": "cancelled",
    }
    diagnostic = events[1]
    assert diagnostic["status"] == "failed"
    assert diagnostic["failure_kind"] == "interrupted"
    assert diagnostic["retry_scheduled"] is False
    assert diagnostic["result_discarded"] is True
    assert diagnostic["raw_output"] == "not json"
    assert "fanout-1-member-1" not in runner.transcript_projector.project(
        events, title="取消 retry"
    )


def test_parallel_cancel_during_parse_retry_preserves_the_finished_first_attempt(
    tmp_path: Path,
) -> None:
    class RetryBlockingAdapter:
        def __init__(self) -> None:
            self.calls = 0
            self.second_started = Event()
            self.release = Event()

        def complete(self, request: ModelRequest) -> ModelResponse:
            self.calls += 1
            if self.calls == 1:
                return ModelResponse(raw_output="not json")
            self.second_started.set()
            assert self.release.wait(timeout=3)
            return ModelResponse(raw_output='{"value":"discard me"}')

        def cancel(self, meeting_id: str) -> None:
            self.release.set()

    schema_id = "test-output/v1"
    plan = ParallelPlan(
        members=[
            ParallelMemberStep(
                step_id="member-1",
                role="Member-1",
                template_name="brainstorm_member",
                display_name="委員 1",
                instance_prompt="",
                index=1,
                output_schema_id=schema_id,
            )
        ],
        synthesis=StepDefinition(
            "synthesis", "Moderator", "brainstorm_synthesis", schema_id
        ),
    )
    adapter = RetryBlockingAdapter()
    runner = build_runner(
        tmp_path,
        adapter=adapter,
        templates=("brainstorm_member", "brainstorm_synthesis"),
        output_schemas=OutputSchemaRegistry(
            [OutputSchemaCodec(schema_id, TEST_ONLY_SCHEMA, TestOnlyParser())]
        ),
    )
    thread = Thread(
        target=lambda: runner.start_parallel(
            plan=plan,
            meeting_id="meeting-1",
            goal="retry 期間取消",
            model_assignments={
                "Member-1": ModelConfig(id="mock-member", adapter="mock"),
                "Moderator": ModelConfig(id="mock-moderator", adapter="mock"),
            },
        )
    )
    thread.start()
    assert adapter.second_started.wait(timeout=3)

    runner.cancel("meeting-1")
    thread.join(timeout=3)

    assert not thread.is_alive()
    lifecycle, first_attempt, second_attempt = runner.repository.read_events("meeting-1")
    assert lifecycle["status"] == "cancelled"
    assert (first_attempt["attempt"], first_attempt["failure_kind"]) == (1, "parse_error")
    assert first_attempt["retry_scheduled"] is True
    assert "result_discarded" not in first_attempt
    assert (second_attempt["attempt"], second_attempt["failure_kind"]) == (2, "interrupted")
    assert second_attempt["retry_scheduled"] is False
    assert second_attempt["result_discarded"] is True


def test_parallel_runner_can_anonymize_synthesis_inputs(tmp_path: Path) -> None:
    outputs = [
        json.dumps(
            {
                "summary": "身為 ChatGPT，我建議先做低成本 onboarding。",
                "arguments": [],
                "risks": [],
                "recommendation": "Use a checklist.",
            }
        ),
        json.dumps(
            {
                "summary": "As ChatGPT, I would simplify the first run.",
                "arguments": [],
                "risks": [],
                "recommendation": "Trim setup steps.",
            }
        ),
        json.dumps(
            {
                "summary": "營運上先控制客服量。",
                "arguments": [],
                "risks": [],
                "recommendation": "Add staged rollout.",
            }
        ),
        VALID_OUTPUT,
    ]
    runner = build_runner(
        tmp_path,
        adapter=FakeAdapter(outputs),
        templates=("brainstorm_member", "brainstorm_synthesis"),
        extra_placeholders=" {{ fanout_outputs }}",
    )

    runner.start_parallel(
        plan=ANONYMIZED_PARALLEL_PLAN,
        meeting_id="meeting-1",
        goal="如何改善 onboarding？",
        model_assignments=parallel_model_assignments(),
    )

    synthesis_event = runner.repository.read_events("meeting-1")[-1]
    synthesis_prompt = synthesis_event["prompt_messages"][0]["content"]
    assert "委員A" in synthesis_prompt
    assert "委員B" in synthesis_prompt
    assert "委員C" in synthesis_prompt
    assert "Member-1" not in synthesis_prompt
    assert "委員 1" not in synthesis_prompt
    assert "身為 ChatGPT" not in synthesis_prompt
    assert "As ChatGPT" not in synthesis_prompt
    assert "低成本 onboarding" in synthesis_prompt
    assert "Trim setup steps." in synthesis_prompt


def test_parallel_runner_records_individual_failures_without_stopping_other_members(
    tmp_path: Path,
) -> None:
    runner = build_runner(
        tmp_path,
        adapter=SelectiveFailingAdapter(failing_model_ids={"mock-member-2"}),
        templates=("brainstorm_member", "brainstorm_synthesis"),
    )

    runner.start_parallel(
        plan=PARALLEL_PLAN,
        meeting_id="meeting-1",
        goal="如何改善 onboarding？",
        model_assignments=parallel_model_assignments(),
    )

    events = runner.repository.read_events("meeting-1")
    assert {(event["step_id"], event["status"]) for event in events} == {
        ("fanout-1-member-1", "completed"),
        ("fanout-1-member-2", "failed"),
        ("fanout-1-member-3", "completed"),
    }
    assert all(event["step_id"] != "synthesis-1" for event in events)


def test_parallel_runner_retry_failed_member_runs_only_that_member_then_synthesizes(
    tmp_path: Path,
) -> None:
    adapter = SelectiveFailingAdapter(failing_model_ids={"mock-member-2"})
    runner = build_runner(
        tmp_path,
        adapter=adapter,
        templates=("brainstorm_member", "brainstorm_synthesis"),
    )
    model_assignments = parallel_model_assignments()
    runner.start_parallel(
        plan=PARALLEL_PLAN,
        meeting_id="meeting-1",
        goal="如何改善 onboarding？",
        model_assignments=model_assignments,
    )
    adapter.failing_model_ids.clear()

    runner.retry_failed_parallel_step(
        plan=PARALLEL_PLAN,
        meeting_id="meeting-1",
        step_id="fanout-1-member-2",
        goal="如何改善 onboarding？",
        model_assignments=model_assignments,
    )

    events = runner.repository.read_events("meeting-1")
    assert {
        (event["step_id"], event["attempt"], event["status"])
        for event in events[:3]
    } == {
        ("fanout-1-member-1", 1, "completed"),
        ("fanout-1-member-2", 1, "failed"),
        ("fanout-1-member-3", 1, "completed"),
    }
    assert [
        (event["step_id"], event["attempt"], event["status"])
        for event in events[3:]
    ] == [
        ("fanout-1-member-2", 2, "completed"),
        ("synthesis-1", 1, "completed"),
    ]
    assert [event["output_schema_id"] for event in events] == ["role-output/v1"] * 5


def test_parallel_runner_starts_next_round_after_synthesis_complete(tmp_path: Path) -> None:
    runner = build_runner(
        tmp_path,
        adapter=FakeAdapter([VALID_OUTPUT] * 8),
        templates=("brainstorm_member", "brainstorm_synthesis"),
    )
    model_assignments = parallel_model_assignments()

    runner.start_parallel(
        plan=PARALLEL_PLAN,
        meeting_id="meeting-1",
        goal="如何改善 onboarding？",
        model_assignments=model_assignments,
    )
    runner.start_parallel(
        plan=PARALLEL_PLAN,
        meeting_id="meeting-1",
        goal="如何改善 onboarding？",
        model_assignments=model_assignments,
    )

    completed_step_ids = [
        event["step_id"]
        for event in runner.repository.read_events("meeting-1")
        if event["status"] == "completed"
    ]
    assert set(completed_step_ids[:3]) == {
        "fanout-1-member-1",
        "fanout-1-member-2",
        "fanout-1-member-3",
    }
    assert completed_step_ids[3] == "synthesis-1"
    assert set(completed_step_ids[4:7]) == {
        "fanout-2-member-1",
        "fanout-2-member-2",
        "fanout-2-member-3",
    }
    assert completed_step_ids[7] == "synthesis-2"


def parallel_model_assignments() -> dict[str, ModelConfig]:
    return {
        "Member-1": ModelConfig(id="mock-member-1", adapter="mock"),
        "Member-2": ModelConfig(id="mock-member-2", adapter="mock"),
        "Member-3": ModelConfig(id="mock-member-3", adapter="mock"),
        "Moderator": ModelConfig(id="mock-moderator", adapter="mock"),
    }


def build_runner(
    tmp_path: Path,
    *,
    adapter: object,
    templates: tuple[str, ...] = ("blue_propose", "red_critique", "blue_revise", "judge_decide"),
    extra_placeholders: str = "",
    output_schemas: OutputSchemaRegistry | None = None,
    repository: MeetingRepository | None = None,
) -> MeetingRunner:
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    for template in templates:
        (prompt_dir / f"{template}.md").write_text(
            f"{template} {{{{ role }}}} {{{{ goal }}}} "
            "{{ prior_transcript }} {{ required_json_schema }}" + extra_placeholders,
            encoding="utf-8",
        )
    if "directed_role_response" not in templates:
        (prompt_dir / "directed_role_response.md").write_text(
            "directed_role_response {{ role }} {{ goal }} "
            "{{ prior_transcript }} {{ required_json_schema }} "
            "{{ role_display_name }} {{ instruction }}",
            encoding="utf-8",
        )

    repository = repository or MeetingRepository(tmp_path / "data")
    return MeetingRunner(
        repository=repository,
        prompt_renderer=PromptRenderer(prompt_dir),
        adapters=RunnerAdapters(
            by_name={
                "mock": adapter,
            }
        ),
        output_schemas=output_schemas,
    )


def strip_created_at(events: list[dict[str, object]]) -> list[dict[str, object]]:
    return [
        {key: value for key, value in event.items() if key != "created_at"}
        for event in events
    ]


class FakeAdapter:
    def __init__(
        self,
        outputs: list[str],
        token_usage: dict[str, int] | None = None,
    ) -> None:
        self.outputs = outputs
        self.token_usage = token_usage
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        return ModelResponse(raw_output=self.outputs.pop(0), token_usage=self.token_usage)


class FailingAdapter:
    def complete(self, request: ModelRequest) -> ModelResponse:
        raise AdapterError("adapter boom")


class SelectiveFailingAdapter:
    def __init__(self, failing_model_ids: set[str]) -> None:
        self.failing_model_ids = failing_model_ids
        self.requests: list[ModelRequest] = []

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if request.model_config.id in self.failing_model_ids:
            raise AdapterError("adapter boom")
        return ModelResponse(raw_output=VALID_OUTPUT)


class CancellableFakeAdapter(FakeAdapter):
    def __init__(self, outputs: list[str]) -> None:
        super().__init__(outputs)
        self.cancelled_meeting_ids: list[str] = []

    def cancel(self, meeting_id: str) -> None:
        self.cancelled_meeting_ids.append(meeting_id)
