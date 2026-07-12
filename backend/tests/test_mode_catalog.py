from __future__ import annotations

from pathlib import Path

import pytest

from ai_council.meetings.modes import (
    ModeCatalogRepository,
    ModeConfigError,
    relay_plan,
)
from ai_council.meetings.runner import DIRECTED_RESPONSE_STEPS, STEPS, StepDefinition


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
    assert len(mode.steps) == 4
    assert mode.available is True


def test_catalog_marks_parallel_modes_unavailable(tmp_path: Path) -> None:
    config_path = _write_yaml(tmp_path, PARALLEL_MODE_YAML)

    modes = ModeCatalogRepository(config_path).list_modes()

    assert len(modes) == 1
    assert modes[0].category == "parallel"
    assert modes[0].available is False


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


def test_repo_modes_yaml_is_loadable() -> None:
    config_path = Path(__file__).resolve().parents[2] / "config" / "modes.yaml"
    prompts_dir = Path(__file__).resolve().parents[2] / "prompts"

    modes = ModeCatalogRepository(config_path).list_modes()

    assert len(modes) == 6

    red_blue = next(mode for mode in modes if mode.id == "red-blue")
    plan = relay_plan(red_blue)
    assert [step.step_id for step in plan.steps] == [
        "blue-propose",
        "red-critique",
        "blue-revise",
        "judge-decide",
    ]
    # Backward-compat gate: the derived relay plan must reproduce the runner's
    # pre-mode-system STEPS/DIRECTED_RESPONSE_STEPS constants exactly.
    assert plan.steps == STEPS
    assert plan.directed_steps == DIRECTED_RESPONSE_STEPS

    for mode in modes:
        if mode.category != "relay":
            continue
        for step in mode.steps:
            template_path = prompts_dir / f"{step.template}.md"
            assert template_path.exists(), f"missing prompt template: {template_path}"
