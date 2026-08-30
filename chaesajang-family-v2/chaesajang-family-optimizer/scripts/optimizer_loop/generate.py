"""Leak-resistant, reproducible generation over a selected local skill tree."""

from __future__ import annotations

import hashlib
import os
import re
import stat
from collections.abc import Iterable, Mapping
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from .runner import RunConfig, run_command


_TARGET_SKILL = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_GENERATOR_FIELDS = ("case_id", "target_skill", "generator_brief")


def _non_empty_string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _generator_case(raw: object) -> dict[str, str]:
    if not isinstance(raw, Mapping):
        raise TypeError("each case must be a mapping")
    missing = [field for field in _GENERATOR_FIELDS if field not in raw]
    if missing:
        raise ValueError(f"case is missing generator fields: {missing}")
    case_id = _non_empty_string(raw["case_id"], "case_id")
    target_skill = _non_empty_string(raw["target_skill"], "target_skill")
    generator_brief = _non_empty_string(raw["generator_brief"], "generator_brief")
    if len(target_skill) > 64 or _TARGET_SKILL.fullmatch(target_skill) is None:
        raise ValueError("target_skill must be one safe lowercase hyphenated path segment")
    return {
        "case_id": case_id,
        "target_skill": target_skill,
        "generator_brief": generator_brief,
    }


def _source_root(source_root: Path) -> Path:
    if not isinstance(source_root, Path):
        raise TypeError("source_root must be a Path")
    if source_root.is_symlink():
        raise ValueError("source_root must not be a symlink")
    try:
        resolved = source_root.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"source_root is missing or inaccessible: {source_root}") from error
    if not resolved.is_dir():
        raise ValueError("source_root must be a directory")
    return resolved


def _skill_tree(root: Path, target_skill: str) -> tuple[Path, Path]:
    lexical = root / target_skill
    if lexical.is_symlink():
        raise ValueError(f"selected skill tree must not be a symlink: {target_skill}")
    try:
        skill = lexical.resolve(strict=True)
        skill.relative_to(root)
    except (OSError, ValueError) as error:
        raise ValueError(f"target_skill resolves outside source_root or is missing: {target_skill}") from error
    if not skill.is_dir():
        raise ValueError(f"target_skill must select a directory: {target_skill}")
    entrypoint = skill / "SKILL.md"
    if entrypoint.is_symlink():
        raise ValueError(f"selected SKILL.md must not be a symlink: {target_skill}")
    if not entrypoint.is_file():
        raise ValueError(f"selected skill is missing a regular SKILL.md: {target_skill}")
    return skill, entrypoint


def _skill_snapshot(skill: Path) -> dict[str, str]:
    def fail_walk(error: OSError) -> None:
        raise ValueError(f"selected skill source is inaccessible: {skill}") from error

    files: list[Path] = []
    for current, directories, filenames in os.walk(
        skill, topdown=True, onerror=fail_walk, followlinks=False
    ):
        current_path = Path(current)
        for name in (*directories, *filenames):
            candidate = current_path / name
            if candidate.is_symlink():
                raise ValueError(f"selected skill source contains a symlink: {candidate}")
        for name in filenames:
            candidate = current_path / name
            try:
                mode = candidate.stat(follow_symlinks=False).st_mode
            except OSError as error:
                raise ValueError(f"selected skill source is inaccessible: {candidate}") from error
            if stat.S_ISREG(mode):
                files.append(candidate)

    snapshot: dict[str, str] = {}
    for path in sorted(files, key=lambda item: item.relative_to(skill).as_posix()):
        relative = path.relative_to(skill).as_posix()
        try:
            contents = path.read_bytes()
        except OSError as error:
            raise ValueError(f"selected skill source is inaccessible: {path}") from error
        snapshot[relative] = hashlib.sha256(contents).hexdigest()
    return snapshot


def build_generation_prompt(case: dict, skill_path: Path) -> str:
    """Build a prompt from the generator-facing allowlist only."""
    safe_case = _generator_case(case)
    if not isinstance(skill_path, Path):
        raise TypeError("skill_path must be a Path")
    logical_skill_path = skill_path.as_posix()
    expected_skill_path = f"{safe_case['target_skill']}/SKILL.md"
    if logical_skill_path != expected_skill_path:
        raise ValueError(
            f"skill_path must be the logical target entrypoint: {expected_skill_path}"
        )
    return (
        "Generate one response for a controlled skill evaluation.\n"
        f"Case ID: {safe_case['case_id']}\n"
        f"Target skill: {safe_case['target_skill']}\n"
        f"Selected local SKILL.md: {logical_skill_path}\n\n"
        "Read the selected local SKILL.md before answering. Read only the local references "
        "that SKILL.md requires and no unrelated evaluation material. "
        "Do not make any file changes. Return only the requested response, with no analysis "
        "of the evaluation setup.\n\n"
        "Generator brief:\n"
        f"{safe_case['generator_brief']}"
    )


def _expected_generation_command(root: Path, config: RunConfig) -> tuple[str, ...]:
    return (
        "codex",
        "exec",
        "--ephemeral",
        "--ignore-user-config",
        "--ignore-rules",
        "--sandbox",
        "read-only",
        "--color",
        "never",
        "--model",
        config.model,
        "--config",
        f'model_reasoning_effort="{config.reasoning}"',
        "--cd",
        str(root),
        "-",
    )


def _validate_generation_config(root: Path, config: RunConfig) -> Path:
    if config.runtime != "codex":
        raise ValueError("generation runtime must be codex")
    if config.expect_json:
        raise ValueError("generation expect_json must be false for writing output")
    try:
        cwd = config.cwd.resolve(strict=True)
    except OSError as error:
        raise ValueError(f"generation cwd is missing or inaccessible: {config.cwd}") from error
    if cwd != root:
        raise ValueError("generation cwd must resolve to source_root")
    if config.command != _expected_generation_command(root, config):
        raise ValueError("generation command must exactly match the declared Codex argv")
    return cwd


def generate_cases(
    cases: Iterable[dict], source_root: Path, config: RunConfig, repeats: int
) -> list[dict]:
    """Generate stable case/repeat rows without exposing evaluator-only fields."""
    if not isinstance(config, RunConfig):
        raise TypeError("config must be a RunConfig")
    if not isinstance(repeats, int) or isinstance(repeats, bool):
        raise TypeError("repeats must be a positive integer")
    if repeats <= 0:
        raise ValueError("repeats must be a positive integer")
    if isinstance(cases, (str, bytes, Mapping)):
        raise TypeError("cases must be an iterable of case mappings")
    try:
        raw_cases = list(cases)
    except TypeError as error:
        raise TypeError("cases must be an iterable of case mappings") from error
    if not raw_cases:
        raise ValueError("cases must contain at least one case")

    root = _source_root(source_root)
    cwd = _validate_generation_config(root, config)
    prepared: list[tuple[dict[str, str], Path, Path]] = []
    identifiers: set[str] = set()
    for raw in raw_cases:
        case = _generator_case(raw)
        if case["case_id"] in identifiers:
            raise ValueError(f"duplicate case_id: {case['case_id']}")
        identifiers.add(case["case_id"])
        skill, _entrypoint = _skill_tree(root, case["target_skill"])
        _skill_snapshot(skill)
        logical_entrypoint = Path(case["target_skill"]) / "SKILL.md"
        prepared.append((case, skill, logical_entrypoint))

    rows: list[dict] = []
    for case, skill, logical_entrypoint in prepared:
        prompt = build_generation_prompt(case, logical_entrypoint)
        per_case_config = replace(config, stdin_text=prompt)
        for repeat in range(repeats):
            started_at = datetime.now(timezone.utc).isoformat()
            source_snapshot = _skill_snapshot(skill)
            result = run_command(per_case_config)
            invalid_reason: str | None = None
            try:
                source_snapshot_after: dict[str, str] | None = _skill_snapshot(skill)
            except (OSError, ValueError) as error:
                source_snapshot_after = None
                source_stable = False
                invalid_reason = f"post-run source snapshot failed: {error}"
            else:
                source_stable = source_snapshot_after == source_snapshot
                if not source_stable:
                    invalid_reason = "source snapshot changed during generation"

            row = {
                "case_id": case["case_id"],
                "target_skill": case["target_skill"],
                "repeat": repeat,
                "input": case["generator_brief"],
                "prompt": prompt,
                "output": result.stdout,
                "stderr": result.stderr,
                "command": list(config.command),
                "cwd": str(cwd),
                "source_root": str(root),
                "timeout_seconds": config.timeout_seconds,
                "model": config.model,
                "reasoning": config.reasoning,
                "runtime": config.runtime,
                "started_at": started_at,
                "elapsed_ms": result.elapsed_ms,
                "status": "invalid" if invalid_reason is not None else result.status,
                "returncode": result.returncode,
                "source_snapshot": dict(source_snapshot),
                "source_snapshot_after": (
                    None
                    if source_snapshot_after is None
                    else dict(source_snapshot_after)
                ),
                "source_stable": source_stable,
            }
            if invalid_reason is not None:
                row["invalid_reason"] = invalid_reason
            rows.append(row)
            if invalid_reason is not None:
                return rows
    return rows
