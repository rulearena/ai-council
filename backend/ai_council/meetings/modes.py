from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ai_council.meetings.runner import RelayPlan, StepDefinition

VALID_CATEGORIES = {"relay", "parallel"}
VALID_ROLE_KINDS = {"member", "adjudicator", "synthesizer"}
VALID_INPUT_KINDS = {"text", "persona-list"}


class ModeConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ModeRole:
    id: str
    name: str
    color: str
    kind: str
    portrait: str | None = None


@dataclass(frozen=True)
class ModeStep:
    role: str
    template: str
    label: str


@dataclass(frozen=True)
class ModeInput:
    id: str
    label: str
    kind: str


@dataclass(frozen=True)
class ModeFanout:
    role: str
    template: str
    label: str
    min_instances: int
    max_instances: int
    instance_prompt: bool


@dataclass(frozen=True)
class ModeSynthesis:
    role: str
    template: str
    label: str


@dataclass(frozen=True)
class ModeDefinition:
    id: str
    name: str
    category: str
    tagline: str
    when_to_use: str
    sop: list[str]
    default_scene: str
    inputs: list[ModeInput]
    roles: list[ModeRole]
    steps: list[ModeStep] = field(default_factory=list)
    fanout: ModeFanout | None = None
    synthesis: ModeSynthesis | None = None

    @property
    def available(self) -> bool:
        # Only the relay executor exists today; parallel modes unlock in slice C.
        return self.category == "relay"

    def role_ids(self) -> list[str]:
        return [role.id for role in self.roles]


def relay_plan(mode: ModeDefinition) -> RelayPlan:
    if mode.category != "relay":
        raise ModeConfigError(f"Mode does not use the relay executor: {mode.id}")
    steps = [
        StepDefinition(step.template.replace("_", "-"), step.role, step.template)
        for step in mode.steps
    ]
    directed_steps = {
        step.role: StepDefinition(f"{step.role.lower()}-response", step.role, step.template)
        for step in mode.steps
    }
    return RelayPlan(steps=steps, directed_steps=directed_steps)


class ModeCatalogRepository:
    def __init__(self, config_path: Path | str) -> None:
        self.config_path = Path(config_path)

    def list_modes(self) -> list[ModeDefinition]:
        if not self.config_path.exists():
            raise ModeConfigError(f"Mode config not found: {self.config_path}")
        raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        raw_modes = raw.get("modes", [])
        if not isinstance(raw_modes, list):
            raise ModeConfigError("modes must be a list")
        modes = [_mode_from_yaml_item(item) for item in raw_modes]
        seen: set[str] = set()
        for mode in modes:
            if mode.id in seen:
                raise ModeConfigError(f"Duplicate mode id: {mode.id}")
            seen.add(mode.id)
        return modes

    def get_mode(self, mode_id: str) -> ModeDefinition | None:
        for mode in self.list_modes():
            if mode.id == mode_id:
                return mode
        return None


def _mode_from_yaml_item(raw_mode: Any) -> ModeDefinition:
    if not isinstance(raw_mode, dict):
        raise ModeConfigError("Mode entry must be a mapping")

    mode_id = raw_mode.get("id")
    name = raw_mode.get("name")
    category = raw_mode.get("category")
    if not mode_id or not isinstance(mode_id, str):
        raise ModeConfigError(f"Mode entry requires id: {raw_mode!r}")
    if not name or not isinstance(name, str):
        raise ModeConfigError(f"Mode {mode_id!r} requires name")
    if category not in VALID_CATEGORIES:
        raise ModeConfigError(f"Mode {mode_id!r} has unknown category: {category!r}")

    roles = [_role_from_yaml_item(mode_id, item) for item in raw_mode.get("roles", [])]
    if not roles:
        raise ModeConfigError(f"Mode {mode_id!r} requires at least one role")
    role_ids = {role.id for role in roles}
    if len(role_ids) != len(roles):
        raise ModeConfigError(f"Mode {mode_id!r} has duplicate role ids")

    inputs = [_input_from_yaml_item(mode_id, item) for item in raw_mode.get("inputs", []) or []]

    steps = [_step_from_yaml_item(mode_id, item) for item in raw_mode.get("steps", []) or []]
    if category == "relay":
        if not steps:
            raise ModeConfigError(f"Mode {mode_id!r} is category relay but has no steps")
        for step in steps:
            if step.role not in role_ids:
                raise ModeConfigError(
                    f"Mode {mode_id!r} step role {step.role!r} is not in roles"
                )
    elif category == "parallel" and steps:
        raise ModeConfigError(f"Mode {mode_id!r} is category parallel but has steps")

    fanout = _fanout_from_yaml(mode_id, raw_mode.get("fanout"))
    synthesis = _synthesis_from_yaml(mode_id, raw_mode.get("synthesis"))

    return ModeDefinition(
        id=mode_id,
        name=name,
        category=category,
        tagline=raw_mode.get("tagline", ""),
        when_to_use=raw_mode.get("when_to_use", ""),
        sop=list(raw_mode.get("sop", []) or []),
        default_scene=raw_mode.get("default_scene", ""),
        inputs=inputs,
        roles=roles,
        steps=steps,
        fanout=fanout,
        synthesis=synthesis,
    )


def _role_from_yaml_item(mode_id: str, raw_role: Any) -> ModeRole:
    if not isinstance(raw_role, dict):
        raise ModeConfigError(f"Mode {mode_id!r} has a role entry that is not a mapping")
    role_id = raw_role.get("id")
    name = raw_role.get("name")
    color = raw_role.get("color")
    kind = raw_role.get("kind")
    if not role_id or not name or not color:
        raise ModeConfigError(f"Mode {mode_id!r} has a role missing id/name/color")
    if kind not in VALID_ROLE_KINDS:
        raise ModeConfigError(f"Mode {mode_id!r} has role {role_id!r} with unknown kind: {kind!r}")
    return ModeRole(
        id=role_id,
        name=name,
        color=color,
        kind=kind,
        portrait=raw_role.get("portrait"),
    )


def _input_from_yaml_item(mode_id: str, raw_input: Any) -> ModeInput:
    if not isinstance(raw_input, dict):
        raise ModeConfigError(f"Mode {mode_id!r} has an input entry that is not a mapping")
    input_id = raw_input.get("id")
    label = raw_input.get("label")
    kind = raw_input.get("kind")
    if not input_id or not label:
        raise ModeConfigError(f"Mode {mode_id!r} has an input missing id/label")
    if kind not in VALID_INPUT_KINDS:
        raise ModeConfigError(f"Mode {mode_id!r} has input {input_id!r} with unknown kind: {kind!r}")
    return ModeInput(id=input_id, label=label, kind=kind)


def _step_from_yaml_item(mode_id: str, raw_step: Any) -> ModeStep:
    if not isinstance(raw_step, dict):
        raise ModeConfigError(f"Mode {mode_id!r} has a step entry that is not a mapping")
    role = raw_step.get("role")
    template = raw_step.get("template")
    label = raw_step.get("label")
    if not role or not template or not label:
        raise ModeConfigError(f"Mode {mode_id!r} has a step missing role/template/label")
    return ModeStep(role=role, template=template, label=label)


def _fanout_from_yaml(mode_id: str, raw_fanout: Any) -> ModeFanout | None:
    if raw_fanout is None:
        return None
    if not isinstance(raw_fanout, dict):
        raise ModeConfigError(f"Mode {mode_id!r} has a fanout entry that is not a mapping")
    role = raw_fanout.get("role")
    template = raw_fanout.get("template")
    label = raw_fanout.get("label")
    if not role or not template or not label:
        raise ModeConfigError(f"Mode {mode_id!r} has a fanout missing role/template/label")
    return ModeFanout(
        role=role,
        template=template,
        label=label,
        min_instances=int(raw_fanout.get("min_instances", 2)),
        max_instances=int(raw_fanout.get("max_instances", 6)),
        instance_prompt=bool(raw_fanout.get("instance_prompt", False)),
    )


def _synthesis_from_yaml(mode_id: str, raw_synthesis: Any) -> ModeSynthesis | None:
    if raw_synthesis is None:
        return None
    if not isinstance(raw_synthesis, dict):
        raise ModeConfigError(f"Mode {mode_id!r} has a synthesis entry that is not a mapping")
    role = raw_synthesis.get("role")
    template = raw_synthesis.get("template")
    label = raw_synthesis.get("label")
    if not role or not template or not label:
        raise ModeConfigError(f"Mode {mode_id!r} has a synthesis missing role/template/label")
    return ModeSynthesis(role=role, template=template, label=label)
