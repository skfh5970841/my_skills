"""Stage artifact contracts and atomic JSONL helpers."""

from __future__ import annotations

import json
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

from .contracts import (
    ALLOWED,
    ExperimentManifest,
    ExperimentStatus,
    _CONTEXTUAL_TERMINAL_STATUSES,
    _TERMINAL_STATUSES,
)


_COMPLETED_ARTIFACTS: dict[ExperimentStatus, tuple[str, ...]] = {
    ExperimentStatus.RESEARCHING: ("manifest.json",),
    ExperimentStatus.HYPOTHESIS_READY: (
        "manifest.json",
        "research.jsonl",
        "hypothesis.md",
    ),
    ExperimentStatus.BASELINE_CAPTURED: (
        "manifest.json",
        "research.jsonl",
        "hypothesis.md",
        "baseline.jsonl",
    ),
    ExperimentStatus.CANDIDATE_READY: (
        "manifest.json",
        "research.jsonl",
        "hypothesis.md",
        "baseline.jsonl",
        "candidate.patch",
    ),
    ExperimentStatus.AUTO_EVALUATED: (
        "manifest.json",
        "research.jsonl",
        "hypothesis.md",
        "baseline.jsonl",
        "candidate.patch",
        "candidate.jsonl",
        "scores.json",
    ),
    ExperimentStatus.AWAITING_HUMAN: (
        "manifest.json",
        "research.jsonl",
        "hypothesis.md",
        "baseline.jsonl",
        "candidate.patch",
        "candidate.jsonl",
        "scores.json",
    ),
    ExperimentStatus.READY_FOR_APPROVAL: (
        "manifest.json",
        "research.jsonl",
        "hypothesis.md",
        "baseline.jsonl",
        "candidate.patch",
        "candidate.jsonl",
        "scores.json",
        "report.md",
    ),
    ExperimentStatus.PROMOTED: (
        "manifest.json",
        "research.jsonl",
        "hypothesis.md",
        "baseline.jsonl",
        "candidate.patch",
        "candidate.jsonl",
        "scores.json",
        "report.md",
    ),
    # These states can be entered before any completed work beyond manifest creation.
    ExperimentStatus.REJECTED: ("manifest.json",),
    ExperimentStatus.BLOCKED_EXTERNAL: ("manifest.json",),
    ExperimentStatus.INVALID: ("manifest.json",),
}


def _requires_human_review(risk: str, blind_required: bool) -> bool:
    if not isinstance(risk, str) or not risk:
        raise ValueError("risk must be a non-empty string")
    if type(blind_required) is not bool:
        raise ValueError("blind_required must be boolean")
    return risk != "low" or blind_required


def required_artifacts(
    status: ExperimentStatus, risk: str, *, blind_required: bool = True
) -> tuple[str, ...]:
    """Return artifacts required by work completed at *status*, never later work."""
    if not isinstance(status, ExperimentStatus):
        raise TypeError("status must be an ExperimentStatus")
    if status in _CONTEXTUAL_TERMINAL_STATUSES:
        raise ValueError("terminal status requires manifest context")
    artifacts = _COMPLETED_ARTIFACTS[status]
    if _requires_human_review(risk, blind_required):
        if status is ExperimentStatus.AWAITING_HUMAN:
            return (*artifacts, "blind_pairs.jsonl", "blind_key.private.json")
        if status in {ExperimentStatus.READY_FOR_APPROVAL, ExperimentStatus.PROMOTED}:
            return (
                *artifacts,
                "blind_pairs.jsonl",
                "blind_key.private.json",
                "human_ratings.jsonl",
                "blind_review.private.json",
            )
    return artifacts


def validate_artifacts(
    experiment_dir: Path,
    manifest: ExperimentManifest,
    risk: str,
    *,
    blind_required: bool = True,
) -> list[str]:
    """List absent artifact filenames for the experiment's completed stages."""
    if not isinstance(manifest, ExperimentManifest):
        raise TypeError("manifest must be an ExperimentManifest")
    root = Path(experiment_dir)
    completed_status = manifest.status
    if manifest.status in _CONTEXTUAL_TERMINAL_STATUSES:
        completed_status = manifest.last_successful_status
        if (
            completed_status is None
            or completed_status in _TERMINAL_STATUSES
            or manifest.status not in ALLOWED[completed_status]
        ):
            raise ValueError("terminal manifest has invalid last_successful_status")
    return [
        artifact
        for artifact in required_artifacts(
            completed_status, risk, blind_required=blind_required
        )
        if not (root / artifact).is_file()
    ]


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON numeric constant: {value}")


def read_jsonl(path: Path) -> list[dict]:
    """Read a JSON object per non-empty line, with line-specific errors."""
    target = Path(path)
    try:
        lines = target.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError(f"unable to read JSONL: {target}") from error

    rows: list[dict] = []
    for number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line, parse_constant=_reject_json_constant)
        except (json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"invalid JSONL at line {number}: {error}") from error
        if not isinstance(row, dict):
            raise ValueError(f"JSONL line {number} must be a JSON object")
        rows.append(row)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    """Atomically replace *path* with newline-delimited JSON object rows."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_name = temporary.name
            for row in rows:
                if not isinstance(row, dict):
                    raise ValueError("JSONL rows must be dictionaries")
                temporary.write(
                    json.dumps(row, ensure_ascii=False, sort_keys=True, allow_nan=False)
                )
                temporary.write("\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_name, target)
        temporary_name = None
    finally:
        if temporary_name is not None:
            Path(temporary_name).unlink(missing_ok=True)
