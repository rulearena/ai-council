from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ai_council.meetings.runner import ParallelMemberStep, ParallelPlan, RelayPlan, StepDefinition
from ai_council.prompting.schemas import (
    DEFAULT_OUTPUT_SCHEMA_ID,
    DEFAULT_OUTPUT_SCHEMA_REGISTRY,
    OutputSchemaRegistry,
)

VALID_CATEGORIES = {"relay", "parallel"}
VALID_ROLE_KINDS = {"member", "adjudicator", "synthesizer"}
VALID_INPUT_KINDS = {"text", "persona-list"}
DEFAULT_MODE_ID = "red-blue"


class ModeConfigError(ValueError):
    pass


@dataclass(frozen=True)
class ModeRole:
    id: str
    name: str
    color: str
    kind: str
    portrait: str | None = None
    output_schema: str = DEFAULT_OUTPUT_SCHEMA_ID


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
    templates_by_role: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ModeSynthesis:
    role: str
    template: str
    label: str
    anonymize_inputs: bool = False


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
        return True

    def role_ids(self) -> list[str]:
        return [role.id for role in self.roles]


def relay_plan(mode: ModeDefinition) -> RelayPlan:
    if mode.category != "relay":
        raise ModeConfigError(f"Mode does not use the relay executor: {mode.id}")
    schemas_by_role = {role.id: role.output_schema for role in mode.roles}
    steps = [
        StepDefinition(
            step.template.replace("_", "-"),
            step.role,
            step.template,
            schemas_by_role[step.role],
        )
        for step in mode.steps
    ]
    directed_steps = {
        step.role: StepDefinition(
            f"{step.role.lower()}-response",
            step.role,
            step.template,
            schemas_by_role[step.role],
        )
        for step in mode.steps
    }
    return RelayPlan(steps=steps, directed_steps=directed_steps)


def parallel_plan(mode: ModeDefinition, participants: list[dict[str, Any]]) -> ParallelPlan:
    if mode.category != "parallel":
        raise ModeConfigError(f"Mode does not use the parallel executor: {mode.id}")
    if mode.fanout is None or mode.synthesis is None:
        raise ModeConfigError(f"Mode {mode.id!r} requires fanout and synthesis")

    schemas_by_role = {role.id: role.output_schema for role in mode.roles}
    synthesizer_role = mode.synthesis.role
    fixed_member_roles = {role.id for role in mode.roles if role.kind == "member"}
    member_items: list[dict[str, Any]] = []
    for participant in participants:
        role_id = str(participant.get("role_id", ""))
        if role_id == synthesizer_role:
            continue
        if fixed_member_roles:
            if role_id in fixed_member_roles:
                member_items.append(participant)
        elif _is_fanout_instance_role(mode.fanout.role, role_id):
            member_items.append(participant)

    member_items.sort(key=lambda item: _fanout_instance_index(mode.fanout.role, str(item["role_id"])))
    members = [
        ParallelMemberStep(
            step_id=f"member-{index}",
            role=str(item["role_id"]),
            template_name=mode.fanout.templates_by_role.get(
                str(item["role_id"]),
                mode.fanout.template,
            ),
            display_name=str(item.get("display_name") or item["role_id"]),
            instance_prompt=str(item.get("instance_prompt") or ""),
            index=index,
            output_schema_id=schemas_by_role.get(str(item["role_id"]), DEFAULT_OUTPUT_SCHEMA_ID),
        )
        for index, item in enumerate(member_items, start=1)
    ]
    if not (mode.fanout.min_instances <= len(members) <= mode.fanout.max_instances):
        raise ModeConfigError(
            f"Mode {mode.id!r} requires {mode.fanout.min_instances}-"
            f"{mode.fanout.max_instances} fanout members"
        )
    return ParallelPlan(
        members=members,
        synthesis=StepDefinition(
            "synthesis",
            synthesizer_role,
            mode.synthesis.template,
            schemas_by_role[synthesizer_role],
        ),
        anonymize_synthesis_inputs=mode.synthesis.anonymize_inputs,
    )


class ModeCatalogRepository:
    def __init__(
        self,
        config_path: Path | str,
        *,
        output_schemas: OutputSchemaRegistry | None = None,
    ) -> None:
        self.config_path = Path(config_path)
        self.output_schemas = output_schemas or DEFAULT_OUTPUT_SCHEMA_REGISTRY

    def list_modes(self) -> list[ModeDefinition]:
        if not self.config_path.exists():
            raise ModeConfigError(f"Mode config not found: {self.config_path}")
        raw = yaml.safe_load(self.config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ModeConfigError("modes.yaml root must be a mapping")
        raw_modes = raw.get("modes", [])
        if not isinstance(raw_modes, list):
            raise ModeConfigError("modes must be a list")
        modes = [
            _mode_from_yaml_item(item, output_schemas=self.output_schemas)
            for item in raw_modes
        ]
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


def _require_list(mode_id: str, value: Any, field_name: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ModeConfigError(f"Mode {mode_id!r} {field_name} must be a list")
    return value


def _mode_from_yaml_item(
    raw_mode: Any,
    *,
    output_schemas: OutputSchemaRegistry,
) -> ModeDefinition:
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

    raw_roles = _require_list(mode_id, raw_mode.get("roles"), "roles")
    roles = [
        _role_from_yaml_item(mode_id, item, output_schemas=output_schemas)
        for item in raw_roles
    ]
    if not roles:
        raise ModeConfigError(f"Mode {mode_id!r} requires at least one role")
    role_ids = {role.id for role in roles}
    if len(role_ids) != len(roles):
        raise ModeConfigError(f"Mode {mode_id!r} has duplicate role ids")

    raw_inputs = _require_list(mode_id, raw_mode.get("inputs"), "inputs")
    inputs = [_input_from_yaml_item(mode_id, item) for item in raw_inputs]

    raw_steps = _require_list(mode_id, raw_mode.get("steps"), "steps")
    steps = [_step_from_yaml_item(mode_id, item) for item in raw_steps]
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
    if category == "parallel":
        if fanout is None or synthesis is None:
            raise ModeConfigError(f"Mode {mode_id!r} is category parallel but lacks fanout/synthesis")
        if synthesis.role not in role_ids:
            raise ModeConfigError(
                f"Mode {mode_id!r} synthesis role {synthesis.role!r} is not in roles"
            )
        fixed_member_roles = {role.id for role in roles if role.kind == "member"}
        unknown_template_roles = set(fanout.templates_by_role) - fixed_member_roles
        if unknown_template_roles:
            raise ModeConfigError(
                f"Mode {mode_id!r} fanout templates reference unknown roles: "
                f"{', '.join(sorted(unknown_template_roles))}"
            )

    sop = _require_list(mode_id, raw_mode.get("sop"), "sop")

    return ModeDefinition(
        id=mode_id,
        name=name,
        category=category,
        tagline=raw_mode.get("tagline", ""),
        when_to_use=raw_mode.get("when_to_use", ""),
        sop=list(sop),
        default_scene=raw_mode.get("default_scene", ""),
        inputs=inputs,
        roles=roles,
        steps=steps,
        fanout=fanout,
        synthesis=synthesis,
    )


def _role_from_yaml_item(
    mode_id: str,
    raw_role: Any,
    *,
    output_schemas: OutputSchemaRegistry,
) -> ModeRole:
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
    output_schema = raw_role.get("output_schema", DEFAULT_OUTPUT_SCHEMA_ID)
    if not isinstance(output_schema, str) or not output_schemas.contains(output_schema):
        raise ModeConfigError(
            f"Mode {mode_id!r} role {role_id!r} references unknown output schema: "
            f"{output_schema!r}"
        )
    return ModeRole(
        id=role_id,
        name=name,
        color=color,
        kind=kind,
        portrait=raw_role.get("portrait"),
        output_schema=output_schema,
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
    try:
        min_instances = int(raw_fanout.get("min_instances", 2))
        max_instances = int(raw_fanout.get("max_instances", 6))
    except (TypeError, ValueError) as error:
        raise ModeConfigError(
            f"Mode {mode_id!r} fanout min_instances/max_instances must be integers"
        ) from error
    return ModeFanout(
        role=role,
        template=template,
        label=label,
        min_instances=min_instances,
        max_instances=max_instances,
        instance_prompt=bool(raw_fanout.get("instance_prompt", False)),
        templates_by_role=_string_map_from_yaml(
            mode_id,
            raw_fanout.get("templates_by_role", {}),
            "fanout.templates_by_role",
        ),
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
    return ModeSynthesis(
        role=role,
        template=template,
        label=label,
        anonymize_inputs=bool(raw_synthesis.get("anonymize_inputs", False)),
    )


def _string_map_from_yaml(mode_id: str, raw_map: Any, field_name: str) -> dict[str, str]:
    if raw_map is None:
        return {}
    if not isinstance(raw_map, dict):
        raise ModeConfigError(f"Mode {mode_id!r} {field_name} must be a mapping")
    result: dict[str, str] = {}
    for key, value in raw_map.items():
        if not isinstance(key, str) or not isinstance(value, str):
            raise ModeConfigError(f"Mode {mode_id!r} {field_name} must map strings to strings")
        result[key] = value
    return result


def _is_fanout_instance_role(prototype_role: str, role_id: str) -> bool:
    prefix = f"{prototype_role}-"
    return role_id.startswith(prefix) and role_id[len(prefix) :].isdigit()


def _fanout_instance_index(prototype_role: str, role_id: str) -> int:
    if _is_fanout_instance_role(prototype_role, role_id):
        return int(role_id.rsplit("-", 1)[1])
    return 10_000
