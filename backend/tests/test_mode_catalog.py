from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ai_council.meetings.modes import (
    ModeCatalogRepository,
    ModeConfigError,
    parallel_plan,
    relay_plan,
)
from ai_council.meetings.runner import ParallelMemberStep, StepDefinition


def _write_yaml(tmp_path: Path, content: str) -> Path:
    config_path = tmp_path / "modes.yaml"
    config_path.write_text(content.strip(), encoding="utf-8")
    return config_path


RELAY_MODE_YAML = """
modes:
  - id: red-blue
    name: 紅藍對抗
    category: relay
    tagline: 最扎實的方案壓力測試。
    when_to_use: 需要深度攻防時使用。
    sop:
      - 輸入方案主題
      - 挑選模型
    default_scene: meeting-room
    inputs: []
    roles:
      - { id: Blue, name: 藍軍, color: "#4d8dff", portrait: blue, kind: member }
      - { id: Red, name: 紅軍, color: "#ff6b5e", portrait: red, kind: member }
      - { id: Judge, name: 裁判, color: "#e8b44c", portrait: judge, kind: adjudicator }
    steps:
      - { role: Blue, template: blue_propose, label: 藍軍提案 }
      - { role: Red, template: red_critique, label: 紅軍質詢 }
      - { role: Blue, template: blue_revise, label: 藍軍修訂 }
      - { role: Judge, template: judge_decide, label: 裁判裁決 }
"""

PARALLEL_MODE_YAML = """
modes:
  - id: six-hats
    name: 六頂思考帽
    category: parallel
    tagline: 五頂帽子各司其職。
    when_to_use: 需要系統性覆蓋多視角時使用。
    sop:
      - 輸入主題
    default_scene: meeting-room
    inputs: []
    roles:
      - { id: HatWhite, name: 白帽, color: "#e8e8ec", kind: member }
      - { id: HatBlue, name: 藍帽, color: "#4d8dff", kind: synthesizer }
    fanout:
      role: Hat
      template: hat_white
      label: 帽子發言
      min_instances: 1
      max_instances: 5
      templates_by_role:
        HatWhite: hat_white
    synthesis:
      role: HatBlue
      template: hat_blue_synthesis
      label: 藍帽統整
      anonymize_inputs: true
"""

CHATROOM_MODE_YAML = """
modes:
  - id: chatroom
    name: 自由聊天室
    category: chatroom
    tagline: 隨性交流、即問即答。
    when_to_use: 開放式自由對話。
    sop:
      - 選擇委員並挑選模型
      - 用 @ 點名想發言的委員
    default_scene: meeting-room
    inputs: []
    roles:
      - { id: host, name: 主持 AI, color: "#e8b44c", kind: member, persona_summary: 主持, persona_prompt: 主持對話 }
      - { id: Advisor, name: 顧問, color: "#4d8dff", kind: member, persona_summary: 顧問, persona_prompt: 提出建議 }
      - { id: Critic, name: 評論者, color: "#ff6b5e", kind: member, persona_summary: 評論, persona_prompt: 指出風險 }
      - { id: Strategist, name: 策略師, color: "#8b6dd9", kind: member, persona_summary: 策略, persona_prompt: 衡量取捨 }
      - { id: Analyst, name: 分析師, color: "#3dd68c", kind: member, persona_summary: 分析, persona_prompt: 區分證據 }
"""


def test_catalog_parses_relay_mode(tmp_path: Path) -> None:
    config_path = _write_yaml(tmp_path, RELAY_MODE_YAML)

    modes = ModeCatalogRepository(config_path).list_modes()

    assert len(modes) == 1
    mode = modes[0]
    assert mode.id == "red-blue"
    assert mode.name == "紅藍對抗"
    assert mode.category == "relay"
    assert mode.tagline == "最扎實的方案壓力測試。"
    assert mode.when_to_use == "需要深度攻防時使用。"
    assert mode.sop == ["輸入方案主題", "挑選模型"]
    assert mode.default_scene == "meeting-room"
    assert mode.inputs == []
    assert mode.role_ids() == ["Blue", "Red", "Judge"]
    assert {role.output_schema for role in mode.roles} == {"role-output/v1"}
    assert len(mode.steps) == 4
    assert mode.available is True


def test_catalog_rejects_role_with_unknown_output_schema(tmp_path: Path) -> None:
    config_path = _write_yaml(
        tmp_path,
        """
modes:
  - id: broken-schema
    name: Broken Schema
    category: relay
    tagline: t
    when_to_use: w
    sop: []
    default_scene: meeting-room
    inputs: []
    roles:
      - { id: Judge, name: 裁判, color: "#e8b44c", kind: adjudicator, output_schema: missing/v9 }
    steps:
      - { role: Judge, template: judge_decide, label: 裁判 }
""",
    )

    with pytest.raises(
        ModeConfigError,
        match=r"broken-schema.*Judge.*missing/v9",
    ):
        ModeCatalogRepository(config_path).list_modes()


def test_catalog_marks_parallel_modes_unavailable(tmp_path: Path) -> None:
    config_path = _write_yaml(tmp_path, PARALLEL_MODE_YAML)

    modes = ModeCatalogRepository(config_path).list_modes()

    assert len(modes) == 1
    assert modes[0].category == "parallel"
    assert modes[0].available is True


def test_parallel_plan_derives_member_and_synthesis_steps(tmp_path: Path) -> None:
    config_path = _write_yaml(
        tmp_path,
        """
modes:
  - id: brainstorm
    name: Brainstorm
    category: parallel
    tagline: t
    when_to_use: w
    sop: []
    default_scene: meeting-room
    inputs: []
    roles:
      - { id: Moderator, name: 主持人, color: "#8b6dd9", kind: synthesizer }
    fanout:
      role: Member
      template: brainstorm_member
      label: 委員發想
      min_instances: 2
      max_instances: 6
      instance_prompt: true
    synthesis:
      role: Moderator
      template: brainstorm_synthesis
      label: 主持人彙整
""",
    )
    mode = ModeCatalogRepository(config_path).get_mode("brainstorm")
    assert mode is not None

    plan = parallel_plan(
        mode,
        [
            {"role_id": "Member-1", "display_name": "委員 1", "instance_prompt": "成本視角"},
            {"role_id": "Member-2", "display_name": "委員 2", "instance_prompt": "使用者視角"},
            {"role_id": "Moderator", "display_name": "主持人"},
        ],
    )

    assert plan.members == [
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
    ]
    assert plan.synthesis == StepDefinition("synthesis", "Moderator", "brainstorm_synthesis")


def test_parallel_plan_carries_synthesis_anonymization_flag(tmp_path: Path) -> None:
    config_path = _write_yaml(tmp_path, PARALLEL_MODE_YAML)
    mode = ModeCatalogRepository(config_path).get_mode("six-hats")
    assert mode is not None
    assert mode.synthesis is not None
    assert mode.synthesis.anonymize_inputs is True

    plan = parallel_plan(
        mode,
        [
            {"role_id": "HatWhite", "display_name": "白帽"},
            {"role_id": "HatBlue", "display_name": "藍帽"},
        ],
    )

    assert plan.anonymize_synthesis_inputs is True


def test_catalog_rejects_parallel_mode_without_fanout_or_synthesis(tmp_path: Path) -> None:
    config_path = _write_yaml(
        tmp_path,
        """
modes:
  - id: bad-parallel
    name: Bad Parallel
    category: parallel
    tagline: t
    when_to_use: w
    sop: []
    default_scene: meeting-room
    inputs: []
    roles:
      - { id: Moderator, name: 主持人, color: "#8b6dd9", kind: synthesizer }
""",
    )

    with pytest.raises(ModeConfigError, match="bad-parallel"):
        ModeCatalogRepository(config_path).list_modes()


def test_relay_plan_derives_step_ids_from_templates(tmp_path: Path) -> None:
    config_path = _write_yaml(tmp_path, RELAY_MODE_YAML)
    mode = ModeCatalogRepository(config_path).get_mode("red-blue")
    assert mode is not None

    plan = relay_plan(mode)

    assert plan.steps[1] == StepDefinition("red-critique", "Red", "red_critique")


def test_relay_plan_directed_steps_use_last_template_per_role(tmp_path: Path) -> None:
    config_path = _write_yaml(tmp_path, RELAY_MODE_YAML)
    mode = ModeCatalogRepository(config_path).get_mode("red-blue")
    assert mode is not None

    plan = relay_plan(mode)

    assert plan.directed_steps["Blue"] == StepDefinition("blue-response", "Blue", "blue_revise")


def test_relay_plan_rejects_parallel_mode(tmp_path: Path) -> None:
    config_path = _write_yaml(tmp_path, PARALLEL_MODE_YAML)
    mode = ModeCatalogRepository(config_path).get_mode("six-hats")
    assert mode is not None

    with pytest.raises(ModeConfigError):
        relay_plan(mode)


def test_catalog_rejects_step_role_not_in_roster(tmp_path: Path) -> None:
    config_path = _write_yaml(
        tmp_path,
        """
modes:
  - id: broken
    name: Broken
    category: relay
    tagline: t
    when_to_use: w
    sop: []
    default_scene: meeting-room
    inputs: []
    roles:
      - { id: Blue, name: 藍軍, color: "#4d8dff", kind: member }
    steps:
      - { role: Ghost, template: ghost_step, label: Ghost Step }
""",
    )

    with pytest.raises(ModeConfigError, match="broken"):
        ModeCatalogRepository(config_path).list_modes()


def test_catalog_rejects_duplicate_mode_ids(tmp_path: Path) -> None:
    config_path = _write_yaml(
        tmp_path,
        """
modes:
  - id: dup
    name: Dup One
    category: relay
    tagline: t
    when_to_use: w
    sop: []
    default_scene: meeting-room
    inputs: []
    roles:
      - { id: Blue, name: 藍軍, color: "#4d8dff", kind: member }
    steps:
      - { role: Blue, template: blue_propose, label: Blue Propose }
  - id: dup
    name: Dup Two
    category: relay
    tagline: t
    when_to_use: w
    sop: []
    default_scene: meeting-room
    inputs: []
    roles:
      - { id: Blue, name: 藍軍, color: "#4d8dff", kind: member }
    steps:
      - { role: Blue, template: blue_propose, label: Blue Propose }
""",
    )

    with pytest.raises(ModeConfigError, match="dup"):
        ModeCatalogRepository(config_path).list_modes()


def test_catalog_rejects_unknown_category(tmp_path: Path) -> None:
    config_path = _write_yaml(
        tmp_path,
        """
modes:
  - id: weird
    name: Weird
    category: sequential
    tagline: t
    when_to_use: w
    sop: []
    default_scene: meeting-room
    inputs: []
    roles:
      - { id: Blue, name: 藍軍, color: "#4d8dff", kind: member }
""",
    )

    with pytest.raises(ModeConfigError, match="weird"):
        ModeCatalogRepository(config_path).list_modes()


def test_get_mode_returns_none_for_unknown_id(tmp_path: Path) -> None:
    config_path = _write_yaml(tmp_path, RELAY_MODE_YAML)

    assert ModeCatalogRepository(config_path).get_mode("does-not-exist") is None


def test_catalog_rejects_non_list_roles(tmp_path: Path) -> None:
    config_path = _write_yaml(
        tmp_path,
        """
modes:
  - id: not-a-list
    name: Not A List
    category: relay
    tagline: t
    when_to_use: w
    sop: 5
    default_scene: meeting-room
    inputs: []
    roles: 7
    steps:
      - { role: Blue, template: blue_propose, label: Blue Propose }
""",
    )

    with pytest.raises(ModeConfigError, match="not-a-list"):
        ModeCatalogRepository(config_path).list_modes()


def test_catalog_rejects_non_mapping_root(tmp_path: Path) -> None:
    config_path = _write_yaml(
        tmp_path,
        """
- id: red-blue
- id: courtroom
""",
    )

    with pytest.raises(ModeConfigError):
        ModeCatalogRepository(config_path).list_modes()


def test_catalog_rejects_non_integer_fanout_instances(tmp_path: Path) -> None:
    config_path = _write_yaml(
        tmp_path,
        """
modes:
  - id: bad-fanout
    name: Bad Fanout
    category: parallel
    tagline: t
    when_to_use: w
    sop: []
    default_scene: meeting-room
    inputs: []
    roles:
      - { id: Moderator, name: 主持人, color: "#8b6dd9", kind: synthesizer }
    fanout:
      role: Member
      template: brainstorm_member
      label: 委員發想
      min_instances: abc
      max_instances: 6
      instance_prompt: true
""",
    )

    with pytest.raises(ModeConfigError, match="bad-fanout"):
        ModeCatalogRepository(config_path).list_modes()


def test_catalog_rejects_unknown_role_kind(tmp_path: Path) -> None:
    config_path = _write_yaml(
        tmp_path,
        """
modes:
  - id: bad-role-kind
    name: Bad Role Kind
    category: relay
    tagline: t
    when_to_use: w
    sop: []
    default_scene: meeting-room
    inputs: []
    roles:
      - { id: Blue, name: 藍軍, color: "#4d8dff", kind: overlord }
    steps:
      - { role: Blue, template: blue_propose, label: Blue Propose }
""",
    )

    with pytest.raises(ModeConfigError, match="bad-role-kind"):
        ModeCatalogRepository(config_path).list_modes()


def test_catalog_rejects_unknown_input_kind(tmp_path: Path) -> None:
    config_path = _write_yaml(
        tmp_path,
        """
modes:
  - id: bad-input-kind
    name: Bad Input Kind
    category: relay
    tagline: t
    when_to_use: w
    sop: []
    default_scene: meeting-room
    inputs:
      - { id: position_a, label: 正方立場, kind: audio }
    roles:
      - { id: Blue, name: 藍軍, color: "#4d8dff", kind: member }
    steps:
      - { role: Blue, template: blue_propose, label: Blue Propose }
""",
    )

    with pytest.raises(ModeConfigError, match="bad-input-kind"):
        ModeCatalogRepository(config_path).list_modes()


def test_catalog_rejects_parallel_mode_with_steps(tmp_path: Path) -> None:
    config_path = _write_yaml(
        tmp_path,
        """
modes:
  - id: bad-parallel-steps
    name: Bad Parallel Steps
    category: parallel
    tagline: t
    when_to_use: w
    sop: []
    default_scene: meeting-room
    inputs: []
    roles:
      - { id: Moderator, name: 主持人, color: "#8b6dd9", kind: synthesizer }
    steps:
      - { role: Moderator, template: brainstorm_synthesis, label: 主持人彙整 }
""",
    )

    with pytest.raises(ModeConfigError, match="bad-parallel-steps"):
        ModeCatalogRepository(config_path).list_modes()


def test_chatroom_mode_loads(tmp_path: Path) -> None:
    config_path = _write_yaml(tmp_path, CHATROOM_MODE_YAML)

    modes = ModeCatalogRepository(config_path).list_modes()

    assert len(modes) == 1
    mode = modes[0]
    assert mode.id == "chatroom"
    assert mode.category == "chatroom"
    assert mode.default_scene == "meeting-room"
    assert mode.role_ids() == ["host", "Advisor", "Critic", "Strategist", "Analyst"]
    assert all(role.kind == "member" for role in mode.roles)
    assert mode.steps == []
    assert mode.fanout is None
    assert mode.synthesis is None


@pytest.mark.parametrize(
    "role_id",
    ["host", "Advisor", "Critic", "Strategist", "Analyst"],
)
@pytest.mark.parametrize("field_name", ["persona_summary", "persona_prompt"])
@pytest.mark.parametrize("invalid_value", ["missing", "blank", "non-string"])
def test_chatroom_fixed_role_persona_fields_reject_every_invalid_shape(
    tmp_path: Path,
    role_id: str,
    field_name: str,
    invalid_value: str,
) -> None:
    config = yaml.safe_load(CHATROOM_MODE_YAML)
    role = next(
        candidate
        for candidate in config["modes"][0]["roles"]
        if candidate["id"] == role_id
    )
    if invalid_value == "missing":
        role.pop(field_name)
    elif invalid_value == "blank":
        role[field_name] = "   "
    else:
        role[field_name] = 17
    config_path = _write_yaml(
        tmp_path,
        yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
    )

    with pytest.raises(
        ModeConfigError,
        match=rf"Chatroom role {role_id!r} requires {field_name}",
    ):
        ModeCatalogRepository(config_path).list_modes()


def test_non_chatroom_role_persona_fields_remain_optional(tmp_path: Path) -> None:
    mode = ModeCatalogRepository(_write_yaml(tmp_path, RELAY_MODE_YAML)).get_mode(
        "red-blue"
    )

    assert mode is not None
    assert all(role.persona_summary is None for role in mode.roles)
    assert all(role.persona_prompt is None for role in mode.roles)


def test_chatroom_relay_plan_rejected(tmp_path: Path) -> None:
    config_path = _write_yaml(tmp_path, CHATROOM_MODE_YAML)
    mode = ModeCatalogRepository(config_path).get_mode("chatroom")
    assert mode is not None

    with pytest.raises(ModeConfigError):
        relay_plan(mode)


def test_chatroom_parallel_plan_rejected(tmp_path: Path) -> None:
    config_path = _write_yaml(tmp_path, CHATROOM_MODE_YAML)
    mode = ModeCatalogRepository(config_path).get_mode("chatroom")
    assert mode is not None

    with pytest.raises(ModeConfigError):
        parallel_plan(mode, [])


def test_repo_modes_yaml_is_loadable() -> None:
    config_path = Path(__file__).resolve().parents[2] / "config" / "modes.yaml"
    prompts_dir = Path(__file__).resolve().parents[2] / "prompts"

    modes = ModeCatalogRepository(config_path).list_modes()

    assert len(modes) == 7

    red_blue = next(mode for mode in modes if mode.id == "red-blue")
    plan = relay_plan(red_blue)
    assert [step.step_id for step in plan.steps] == [
        "blue-propose",
        "red-critique",
        "blue-revise",
        "judge-decide",
    ]
    # Backward-compat gate: step, role, and template identities remain frozen;
    # only the adjudicator's versioned output contract may differ from v1.
    assert plan.steps == [
        StepDefinition("blue-propose", "Blue", "blue_propose"),
        StepDefinition("red-critique", "Red", "red_critique"),
        StepDefinition("blue-revise", "Blue", "blue_revise"),
        StepDefinition(
            "judge-decide",
            "Judge",
            "judge_decide",
            "structured-verdict/v1",
        ),
    ]
    assert plan.directed_steps == {
        "Blue": StepDefinition("blue-response", "Blue", "blue_revise"),
        "Red": StepDefinition("red-response", "Red", "red_critique"),
        "Judge": StepDefinition(
            "judge-response",
            "Judge",
            "judge_decide",
            "structured-verdict/v1",
        ),
    }

    for mode in modes:
        if mode.category == "chatroom":
            assert mode.steps == [], f"chatroom mode must not have steps: {mode.id}"
            assert mode.fanout is None, f"chatroom mode must not have fanout: {mode.id}"
            assert mode.synthesis is None, f"chatroom mode must not have synthesis: {mode.id}"
            continue
        if mode.category == "relay":
            templates = [step.template for step in mode.steps]
        else:
            assert mode.fanout is not None, f"parallel mode missing fanout: {mode.id}"
            assert mode.synthesis is not None, f"parallel mode missing synthesis: {mode.id}"
            templates = [mode.fanout.template, mode.synthesis.template]
        for template in templates:
            template_path = prompts_dir / f"{template}.md"
            assert template_path.exists(), f"missing prompt template: {template_path}"


def test_repo_modes_select_rich_verdicts_only_for_adjudicators() -> None:
    config_path = Path(__file__).resolve().parents[2] / "config" / "modes.yaml"

    modes = ModeCatalogRepository(config_path).list_modes()

    adjudicators = [
        (mode.id, role.id, role.output_schema)
        for mode in modes
        for role in mode.roles
        if role.kind == "adjudicator"
    ]
    other_schemas = {
        role.output_schema
        for mode in modes
        for role in mode.roles
        if role.kind != "adjudicator"
    }
    assert adjudicators == [
        ("red-blue", "Judge", "structured-verdict/v1"),
        ("courtroom", "Judge", "structured-verdict/v1"),
        ("debate", "Arbiter", "structured-verdict/v1"),
    ]
    assert other_schemas == {"role-output/v1"}
