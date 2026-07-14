from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol

from ai_council.meetings.repository import MeetingRepository
from ai_council.models.config import ModelConfig, ModelConfigRepository


class MeetingMetadataStore(Protocol):
    def update(
        self,
        meeting_id: str,
        transform: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]: ...


class AssignmentValidationError(ValueError):
    pass


@dataclass(frozen=True)
class EffectiveAssignment:
    model_config_id: str | None
    source: str
    warning: str | None = None


class MeetingModelAssignments:
    """Resolve and persist the role-to-model contract for one meeting."""

    def __init__(
        self,
        metadata_store: MeetingMetadataStore,
        meeting_repository: MeetingRepository,
        model_repository: ModelConfigRepository,
    ) -> None:
        self._metadata_store = metadata_store
        self._meeting_repository = meeting_repository
        self._model_repository = model_repository

    def project(
        self,
        metadata: dict[str, Any],
        participants: list[dict[str, Any]],
        *,
        events: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        resolved = self._resolve(metadata, participants, events=events)
        return [
            {
                **participant,
                "model_config_id": resolved[str(participant["role_id"])].model_config_id,
                "model_assignment_source": resolved[str(participant["role_id"])].source,
                "model_assignment_warning": resolved[str(participant["role_id"])].warning,
            }
            for participant in participants
        ]

    def resolve_models(
        self,
        metadata: dict[str, Any],
        participants: list[dict[str, Any]],
    ) -> dict[str, ModelConfig]:
        models = {model.id: model for model in self._model_repository.list_models()}
        resolved = self._resolve(metadata, participants, models=models)
        unavailable = [role for role, assignment in resolved.items() if assignment.model_config_id is None]
        if unavailable:
            raise AssignmentValidationError(
                f"No model assignment available for roles: {', '.join(sorted(unavailable))}"
            )
        return {
            role: models[assignment.model_config_id]
            for role, assignment in resolved.items()
            if assignment.model_config_id is not None
        }

    def replace(
        self,
        meeting_id: str,
        role_ids: list[str],
        requested: dict[str, str],
    ) -> dict[str, Any]:
        expected = set(role_ids)
        actual = set(requested)
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        if missing or extra:
            details: list[str] = []
            if missing:
                details.append(f"missing roles: {', '.join(missing)}")
            if extra:
                details.append(f"unknown roles: {', '.join(extra)}")
            raise AssignmentValidationError("Participant model roster mismatch; " + "; ".join(details))

        known_models = {model.id for model in self._model_repository.list_models()}
        unknown_models = sorted(set(requested.values()) - known_models)
        if unknown_models:
            raise AssignmentValidationError(f"Unknown model: {unknown_models[0]}")

        def replace_participants(metadata: dict[str, Any]) -> dict[str, Any]:
            stored = {
                str(item.get("role_id")): item
                for item in (metadata.get("participants") or [])
                if isinstance(item, dict)
            }
            metadata["participants"] = [
                {
                    **stored.get(role_id, {"role_id": role_id}),
                    "model_config_id": requested[role_id],
                }
                for role_id in role_ids
            ]
            return metadata

        return self._metadata_store.update(meeting_id, replace_participants)

    def _resolve(
        self,
        metadata: dict[str, Any],
        participants: list[dict[str, Any]],
        *,
        models: dict[str, ModelConfig] | None = None,
        events: list[dict[str, Any]] | None = None,
    ) -> dict[str, EffectiveAssignment]:
        ordered_models = self._model_repository.list_models() if models is None else list(models.values())
        models_by_id = {model.id: model for model in ordered_models}
        default_model_id = ordered_models[0].id if ordered_models else None
        stored = {
            str(item.get("role_id")): item.get("model_config_id")
            for item in (metadata.get("participants") or [])
            if isinstance(item, dict)
        }
        latest_event_models: dict[str, str] = {}
        meeting_id = str(metadata["meeting_id"])
        meeting_events = (
            self._meeting_repository.read_events(meeting_id)
            if events is None
            else events
        )
        for event in meeting_events:
            role = event.get("role")
            model_id = event.get("model_config_id")
            if isinstance(role, str) and isinstance(model_id, str) and model_id:
                latest_event_models[role] = model_id

        result: dict[str, EffectiveAssignment] = {}
        for participant in participants:
            role_id = str(participant["role_id"])
            stored_model_id = stored.get(role_id)
            if isinstance(stored_model_id, str) and stored_model_id:
                if stored_model_id in models_by_id:
                    result[role_id] = EffectiveAssignment(stored_model_id, "metadata")
                else:
                    result[role_id] = self._fallback(
                        default_model_id,
                        f"Assigned model '{stored_model_id}' is unavailable",
                    )
                continue

            event_model_id = latest_event_models.get(role_id)
            if event_model_id is not None:
                if event_model_id in models_by_id:
                    result[role_id] = EffectiveAssignment(event_model_id, "latest-event")
                else:
                    result[role_id] = self._fallback(
                        default_model_id,
                        f"Recovered model '{event_model_id}' is unavailable",
                    )
                continue

            result[role_id] = self._fallback(default_model_id, "No saved model assignment")
        return result

    @staticmethod
    def _fallback(default_model_id: str | None, reason: str) -> EffectiveAssignment:
        if default_model_id is None:
            return EffectiveAssignment(None, "unavailable", f"{reason}; no models are configured")
        return EffectiveAssignment(
            default_model_id,
            "default",
            f"{reason}; using default model '{default_model_id}'",
        )
