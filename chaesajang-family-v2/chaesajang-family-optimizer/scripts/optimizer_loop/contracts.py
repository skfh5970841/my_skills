"""Experiment manifest and state-transition contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any, Mapping


class ExperimentStatus(str, Enum):
    RESEARCHING = "researching"
    HYPOTHESIS_READY = "hypothesis_ready"
    BASELINE_CAPTURED = "baseline_captured"
    CANDIDATE_READY = "candidate_ready"
    AUTO_EVALUATED = "auto_evaluated"
    AWAITING_HUMAN = "awaiting_human"
    READY_FOR_APPROVAL = "ready_for_approval"
    PROMOTED = "promoted"
    REJECTED = "rejected"
    BLOCKED_EXTERNAL = "blocked_external"
    INVALID = "invalid"


ALLOWED: dict[ExperimentStatus, set[ExperimentStatus]] = {
    ExperimentStatus.RESEARCHING: {
        ExperimentStatus.HYPOTHESIS_READY,
        ExperimentStatus.BLOCKED_EXTERNAL,
        ExperimentStatus.INVALID,
    },
    ExperimentStatus.HYPOTHESIS_READY: {
        ExperimentStatus.BASELINE_CAPTURED,
        ExperimentStatus.REJECTED,
        ExperimentStatus.INVALID,
    },
    ExperimentStatus.BASELINE_CAPTURED: {
        ExperimentStatus.CANDIDATE_READY,
        ExperimentStatus.REJECTED,
        ExperimentStatus.BLOCKED_EXTERNAL,
        ExperimentStatus.INVALID,
    },
    ExperimentStatus.CANDIDATE_READY: {
        ExperimentStatus.AUTO_EVALUATED,
        ExperimentStatus.REJECTED,
        ExperimentStatus.BLOCKED_EXTERNAL,
        ExperimentStatus.INVALID,
    },
    ExperimentStatus.AUTO_EVALUATED: {
        ExperimentStatus.AWAITING_HUMAN,
        ExperimentStatus.READY_FOR_APPROVAL,
        ExperimentStatus.REJECTED,
        ExperimentStatus.INVALID,
    },
    ExperimentStatus.AWAITING_HUMAN: {
        ExperimentStatus.READY_FOR_APPROVAL,
        ExperimentStatus.REJECTED,
        ExperimentStatus.INVALID,
    },
    ExperimentStatus.READY_FOR_APPROVAL: {
        ExperimentStatus.PROMOTED,
        ExperimentStatus.REJECTED,
        ExperimentStatus.INVALID,
    },
    ExperimentStatus.PROMOTED: set(),
    ExperimentStatus.REJECTED: set(),
    ExperimentStatus.BLOCKED_EXTERNAL: {
        ExperimentStatus.RESEARCHING,
        ExperimentStatus.HYPOTHESIS_READY,
        ExperimentStatus.BASELINE_CAPTURED,
        ExperimentStatus.CANDIDATE_READY,
    },
    ExperimentStatus.INVALID: set(),
}


_MANIFEST_FIELDS = {
    "experiment_id",
    "status",
    "source_hashes",
    "model",
    "runtime",
    "reasoning",
    "dataset_versions",
    "command",
    "created_at",
}


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _string_mapping(value: object, field: str) -> dict[str, str]:
    if not isinstance(value, dict) or not all(
        isinstance(key, str) and key and isinstance(item, str) and item
        for key, item in value.items()
    ):
        raise ValueError(f"{field} must be a mapping of non-empty strings")
    return dict(value)


def _experiment_id(value: object) -> str:
    identifier = _non_empty_string(value, "experiment_id")
    posix = PurePosixPath(identifier)
    windows = PureWindowsPath(identifier)
    if (
        identifier in {".", ".."}
        or "/" in identifier
        or "\\" in identifier
        or posix.is_absolute()
        or windows.is_absolute()
        or ".." in posix.parts
        or ".." in windows.parts
    ):
        raise ValueError("experiment_id must not contain path traversal")
    return identifier


@dataclass(frozen=True)
class ExperimentManifest:
    experiment_id: str
    status: ExperimentStatus
    source_hashes: dict[str, str]
    model: str
    runtime: str
    reasoning: str
    dataset_versions: dict[str, str]
    command: tuple[str, ...]
    created_at: str

    @classmethod
    def from_dict(cls, data: dict) -> "ExperimentManifest":
        if not isinstance(data, dict):
            raise ValueError("manifest must be a mapping")
        unknown = set(data) - _MANIFEST_FIELDS
        missing = _MANIFEST_FIELDS - set(data)
        if unknown:
            raise ValueError(f"unknown manifest fields: {sorted(unknown)}")
        if missing:
            raise ValueError(f"missing manifest fields: {sorted(missing)}")
        try:
            status = ExperimentStatus(data["status"])
        except (TypeError, ValueError) as error:
            raise ValueError(f"unknown experiment status: {data['status']!r}") from error

        command = data["command"]
        if not isinstance(command, list) or not command or not all(
            isinstance(part, str) and part for part in command
        ):
            raise ValueError("command must be a non-empty list of strings")
        created_at = _non_empty_string(data["created_at"], "created_at")
        try:
            datetime.fromisoformat(created_at)
        except ValueError as error:
            raise ValueError("created_at must be an ISO-8601 timestamp") from error

        return cls(
            experiment_id=_experiment_id(data["experiment_id"]),
            status=status,
            source_hashes=_string_mapping(data["source_hashes"], "source_hashes"),
            model=_non_empty_string(data["model"], "model"),
            runtime=_non_empty_string(data["runtime"], "runtime"),
            reasoning=_non_empty_string(data["reasoning"], "reasoning"),
            dataset_versions=_string_mapping(data["dataset_versions"], "dataset_versions"),
            command=tuple(command),
            created_at=created_at,
        )

    def to_dict(self) -> dict:
        return {
            "experiment_id": self.experiment_id,
            "status": self.status.value,
            "source_hashes": dict(self.source_hashes),
            "model": self.model,
            "runtime": self.runtime,
            "reasoning": self.reasoning,
            "dataset_versions": dict(self.dataset_versions),
            "command": list(self.command),
            "created_at": self.created_at,
        }


def transition(manifest: ExperimentManifest, target: ExperimentStatus) -> ExperimentManifest:
    """Return *manifest* in an explicitly permitted next state."""
    if not isinstance(manifest, ExperimentManifest):
        raise TypeError("manifest must be an ExperimentManifest")
    if not isinstance(target, ExperimentStatus):
        raise TypeError("target must be an ExperimentStatus")
    if target not in ALLOWED[manifest.status]:
        raise ValueError(
            f"invalid transition: {manifest.status.value} -> {target.value}"
        )
    return ExperimentManifest(
        experiment_id=manifest.experiment_id,
        status=target,
        source_hashes=dict(manifest.source_hashes),
        model=manifest.model,
        runtime=manifest.runtime,
        reasoning=manifest.reasoning,
        dataset_versions=dict(manifest.dataset_versions),
        command=tuple(manifest.command),
        created_at=manifest.created_at,
    )
