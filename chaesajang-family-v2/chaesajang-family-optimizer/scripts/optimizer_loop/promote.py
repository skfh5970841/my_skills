"""Approval-gated, failure-atomic promotion of one verified candidate."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import shutil
import tempfile
import uuid
import warnings
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from . import blind, evals, report
from .artifacts import read_jsonl, validate_artifacts
from .candidate import (
    _baseline_bytes,
    _candidate_bytes,
    _text_lines,
    changed_canonical_files,
)
from .contracts import ExperimentManifest, ExperimentStatus, transition
from .hypothesis import Hypothesis
from .registry import FamilyRegistry
from .render import render_all
from .snapshot import snapshot_registry
from .static_gate import run_static_gate


_REPARSE_POINT = 0x400
_NEXT_ACTION = {
    ExperimentStatus.RESEARCHING: "research",
    ExperimentStatus.HYPOTHESIS_READY: "baseline",
    ExperimentStatus.BASELINE_CAPTURED: "candidate",
    ExperimentStatus.CANDIDATE_READY: "auto_evaluation",
    ExperimentStatus.AUTO_EVALUATED: "readiness",
    ExperimentStatus.AWAITING_HUMAN: "human_ratings",
    ExperimentStatus.READY_FOR_APPROVAL: "promote",
    ExperimentStatus.PROMOTED: "complete",
    ExperimentStatus.REJECTED: "stop",
    ExperimentStatus.INVALID: "stop",
}


def next_action(manifest: ExperimentManifest) -> str:
    """Return the first incomplete stage from an explicit status mapping."""
    if not isinstance(manifest, ExperimentManifest):
        raise TypeError("manifest must be an ExperimentManifest")
    status = manifest.status
    if status is ExperimentStatus.BLOCKED_EXTERNAL:
        if manifest.last_successful_status is None:
            raise ValueError("blocked_external requires last_successful_status")
        status = manifest.last_successful_status
    return _NEXT_ACTION[status]


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON constant: {value}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _read_json(path: Path, label: str) -> dict:
    try:
        value = json.loads(
            Path(path).read_text(encoding="utf-8"),
            parse_constant=_reject_constant,
            object_pairs_hook=_unique_object,
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"invalid {label}: {error}") from error
    if not isinstance(value, dict):
        raise ValueError(f"invalid {label}: expected one JSON object")
    return value


def _json_bytes(value: object) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_path(path: Path) -> str:
    return _sha256_bytes(Path(path).read_bytes())


def _is_reparse(path: Path) -> bool:
    try:
        metadata = os.lstat(path)
    except OSError:
        return False
    return Path(path).is_symlink() or bool(
        getattr(metadata, "st_file_attributes", 0) & _REPARSE_POINT
    )


def _lexically_contained(boundary: Path, target: Path, label: str) -> None:
    try:
        Path(target).absolute().relative_to(Path(boundary).absolute())
    except ValueError as error:
        raise ValueError(f"{label} is outside its named root") from error


def _audit_path(
    boundary: Path, target: Path, label: str, *, require_exists: bool = True
) -> Path:
    boundary, target = Path(boundary), Path(target)
    _lexically_contained(boundary, target, label)
    if not boundary.exists() or not boundary.is_dir():
        raise ValueError(f"{label} root is missing")
    relative = target.absolute().relative_to(boundary.absolute())
    current = boundary
    if _is_reparse(current):
        raise ValueError(f"{label} uses a symlink, junction, or reparse point")
    for part in relative.parts:
        current = current / part
        if current.exists() or current.is_symlink():
            if _is_reparse(current):
                raise ValueError(
                    f"{label} uses a symlink, junction, or reparse point"
                )
    if require_exists and not target.exists():
        raise ValueError(f"{label} is missing")
    resolved_boundary = boundary.resolve(strict=True)
    resolved_target = target.resolve(strict=require_exists)
    try:
        resolved_target.relative_to(resolved_boundary)
    except ValueError as error:
        raise ValueError(f"{label} resolves outside its named root") from error
    return resolved_target


def _audit_tree(boundary: Path, root: Path, label: str) -> None:
    checked = _audit_path(boundary, root, label)
    if not checked.is_dir():
        raise ValueError(f"{label} must be a directory")
    for path in root.rglob("*"):
        _audit_path(boundary, path, label)


def _load_manifest(experiment: Path) -> ExperimentManifest:
    try:
        return ExperimentManifest.from_dict(
            _read_json(experiment / "manifest.json", "manifest.json")
        )
    except (TypeError, ValueError) as error:
        raise ValueError(f"invalid manifest.json: {error}") from error


def _validate_experiment(
    experiment_dir: Path, registry: FamilyRegistry
) -> tuple[Path, ExperimentManifest]:
    if not isinstance(registry, FamilyRegistry):
        raise TypeError("registry must be a FamilyRegistry")
    experiments = registry.root.resolve() / registry.generated["experiments"]
    experiment = Path(experiment_dir)
    if experiment.parent.absolute() != experiments.absolute():
        raise ValueError("experiment directory must be an exact direct child")
    _audit_tree(experiments, experiment, "experiment directory")
    manifest = _load_manifest(experiment)
    if experiment.name != manifest.experiment_id:
        raise ValueError("experiment directory name must match experiment_id")
    if manifest.status is not ExperimentStatus.READY_FOR_APPROVAL:
        raise ValueError("promotion requires exact ready_for_approval state")
    return experiment.resolve(strict=True), manifest


def _expected_patch(registry: FamilyRegistry, candidate_root: Path) -> str:
    original = _baseline_bytes(registry)
    candidate = _candidate_bytes(registry, candidate_root)
    fragments: list[str] = []
    for relative in sorted(set(original) | set(candidate)):
        before, after = original.get(relative), candidate.get(relative)
        if before == after:
            continue
        fragments.extend(
            difflib.unified_diff(
                _text_lines(b"" if before is None else before, relative),
                _text_lines(b"" if after is None else after, relative),
                fromfile=f"a/{relative}",
                tofile=f"b/{relative}",
                lineterm="\n",
            )
        )
    return "".join(fragments)


def _read_candidate_patch(experiment: Path, expected: str) -> str:
    try:
        supplied = (experiment / "candidate.patch").read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ValueError("candidate patch is unreadable") from error
    if supplied != expected:
        raise ValueError("candidate patch does not bind the exact candidate bytes")
    return supplied


@dataclass(frozen=True)
class _PromotionEvidence:
    verification_manifest: ExperimentManifest
    score_evidence: object
    review: object
    change: object
    research: object


def _selected_skill_hashes(
    source_hashes: dict[str, str], target_skill: str
) -> dict[str, str]:
    prefix = f"{target_skill}/"
    selected = {
        path[len(prefix) :]: digest
        for path, digest in source_hashes.items()
        if path.startswith(prefix)
    }
    if not selected:
        raise ValueError(f"target_skill has no canonical source files: {target_skill}")
    return dict(sorted(selected.items()))


def _canonical_eval_cases(registry: FamilyRegistry) -> dict[tuple[str, str, str], object]:
    """Reload canonical EvalCases from the audited repository root fail-closed."""

    root = registry.root.resolve()
    evaluation_root = root / "evals"
    _audit_tree(root, evaluation_root, "canonical evaluation root")
    cases: dict[tuple[str, str, str], object] = {}
    seen_case_ids: set[str] = set()
    for split in sorted(evals.SPLITS):
        split_root = evaluation_root / split
        if not split_root.exists():
            continue
        _audit_tree(root, split_root, f"canonical {split} evaluation root")
        for path in sorted(split_root.glob("*.jsonl"), key=lambda item: item.name):
            _audit_path(root, path, "canonical evaluation record")
            if path.relative_to(evaluation_root).as_posix() == "dev/optimizer_smoke.jsonl":
                continue
            for case in evals.load_cases(path, split):
                if case.case_id in seen_case_ids:
                    raise ValueError(
                        f"duplicate canonical case_id: {case.case_id}"
                    )
                identity = (case.case_id, case.target_skill, case.split)
                if identity in cases:
                    raise ValueError(f"conflicting canonical case identity: {identity}")
                seen_case_ids.add(case.case_id)
                cases[identity] = case
    if not cases:
        raise ValueError("canonical evaluation root has no JSONL cases")
    return cases


def _trusted_expected_pairs(
    registry: FamilyRegistry, supplied_pairs: object
) -> list[dict[str, object]]:
    """Bind persisted selections to exact canonical EvalCase digests."""

    if isinstance(supplied_pairs, (str, bytes, bytearray, dict)):
        raise ValueError("canonical case evidence requires an expected-pair sequence")
    try:
        pairs = list(supplied_pairs)
    except TypeError as error:
        raise ValueError(
            "canonical case evidence requires an expected-pair sequence"
        ) from error
    canonical = _canonical_eval_cases(registry)
    trusted: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, int]] = set()
    required = {
        "case_id",
        "target_skill",
        "split",
        "repeat",
        "case_evidence_sha256",
    }
    for index, pair in enumerate(pairs):
        if not isinstance(pair, dict) or set(pair) != required:
            raise ValueError(
                f"canonical case evidence expected pair {index + 1} has invalid schema"
            )
        case_id = pair["case_id"]
        target_skill = pair["target_skill"]
        split = pair["split"]
        repeat = pair["repeat"]
        if (
            not isinstance(case_id, str)
            or not isinstance(target_skill, str)
            or not isinstance(split, str)
            or type(repeat) is not int
            or repeat < 0
        ):
            raise ValueError(
                f"canonical case evidence expected pair {index + 1} has invalid identity"
            )
        identity = (case_id, target_skill, split, repeat)
        if identity in seen:
            raise ValueError(f"duplicate canonical case selection: {identity}")
        seen.add(identity)
        case = canonical.get((case_id, target_skill, split))
        if case is None:
            raise ValueError(f"canonical case evidence has unknown identity: {identity}")
        expected = evals.expected_pair(case, repeat)
        if pair != expected:
            raise ValueError(
                "canonical case evidence does not match the persisted expected pair"
            )
        trusted.append(expected)
    if not trusted:
        raise ValueError("canonical case evidence requires at least one expected pair")
    return trusted


def _verify_task8_evidence(
    experiment: Path,
    registry: FamilyRegistry,
    manifest: ExperimentManifest,
    hypothesis: Hypothesis,
    patch: str,
    gate: object,
    candidate_hashes: dict[str, str],
) -> _PromotionEvidence:
    baseline_rows = read_jsonl(experiment / "baseline.jsonl")
    candidate_rows = read_jsonl(experiment / "candidate.jsonl")
    claims = read_jsonl(experiment / "research.jsonl")
    try:
        change = report.verify_change_assessment(hypothesis, patch)
        research = report.verify_research_evidence(
            manifest.experiment_id, hypothesis, claims
        )
    except (TypeError, ValueError) as error:
        raise ValueError(f"Task 8 evidence binding failed: {error}") from error
    scores = _read_json(experiment / "scores.json", "scores.json")
    if set(scores) != {"aggregate", "evaluation_rows", "expected_pairs"}:
        raise ValueError("score evidence must use the exact resumable schema")
    try:
        trusted_expected_pairs = _trusted_expected_pairs(
            registry, scores["expected_pairs"]
        )
        score_evidence = evals.verify_score_evidence(
            scores["aggregate"],
            scores["evaluation_rows"],
            baseline_rows,
            candidate_rows,
            expected_pairs=trusted_expected_pairs,
        )
    except (TypeError, ValueError, KeyError) as error:
        raise ValueError(f"score evidence verification failed: {error}") from error
    for label, rows, source_hashes in (
        ("baseline", baseline_rows, manifest.source_hashes),
        ("candidate", candidate_rows, candidate_hashes),
    ):
        for index, row in enumerate(rows):
            expected = _selected_skill_hashes(source_hashes, row["target_skill"])
            if (
                row.get("source_stable") is not True
                or row.get("source_snapshot") != expected
                or row.get("source_snapshot_after") != expected
            ):
                raise ValueError(
                    f"{label} source snapshot does not match canonical bytes "
                    f"for generation row {index + 1}"
                )
    review = None
    if change.human_required:
        try:
            review = blind.verify_blind_review(
                manifest.experiment_id,
                baseline_rows,
                candidate_rows,
                read_jsonl(experiment / "blind_pairs.jsonl"),
                _read_json(
                    experiment / "blind_key.private.json",
                    "blind_key.private.json",
                ),
                read_jsonl(experiment / "human_ratings.jsonl"),
                expected_receipt=_read_json(
                    experiment / "blind_review.private.json",
                    "blind_review.private.json",
                ),
            )
        except (TypeError, ValueError, KeyError) as error:
            raise ValueError(f"Task 8 blind evidence binding failed: {error}") from error
    verification_data = manifest.to_dict()
    verification_data["status"] = (
        ExperimentStatus.AWAITING_HUMAN.value
        if change.human_required
        else ExperimentStatus.AUTO_EVALUATED.value
    )
    verification_manifest = ExperimentManifest.from_dict(verification_data)
    readiness = report.evaluate_readiness(
        verification_manifest,
        hypothesis,
        gate,
        score_evidence,
        review,
        change,
        research,
    )
    if readiness.status != ExperimentStatus.READY_FOR_APPROVAL.value:
        reasons = ", ".join(readiness.reasons) or "unknown"
        raise ValueError(f"Task 8 evidence is not ready_for_approval: {reasons}")
    return _PromotionEvidence(
        verification_manifest=verification_manifest,
        score_evidence=score_evidence,
        review=review,
        change=change,
        research=research,
    )


_REPORT_ARTIFACTS = (
    "research.jsonl",
    "hypothesis.md",
    "baseline.jsonl",
    "candidate.patch",
    "candidate.jsonl",
    "scores.json",
)
_BLIND_REPORT_ARTIFACTS = (
    "blind_pairs.jsonl",
    "human_ratings.jsonl",
)


def _rebuild_approval_report(
    experiment: Path,
    registry: FamilyRegistry,
    hypothesis: Hypothesis,
    gate: object,
    evidence: _PromotionEvidence,
    changed: tuple[str, ...],
) -> str:
    aggregate = evals.verified_score_aggregate(evidence.score_evidence)
    regressions = []
    for axis, conditions in aggregate["axes"].items():
        baseline_failed = conditions["baseline"]["failed"]
        candidate_failed = conditions["candidate"]["failed"]
        delta = candidate_failed - baseline_failed
        regressions.append(
            {
                "axis": axis,
                "baseline_failed": baseline_failed,
                "candidate_failed": candidate_failed,
                "delta": delta,
                "status": (
                    "regressed"
                    if delta > 0
                    else "improved"
                    if delta < 0
                    else "unchanged"
                ),
            }
        )
    experiment_relative = experiment.relative_to(registry.root.resolve())
    artifact_names = _REPORT_ARTIFACTS
    if evidence.change.human_required:
        artifact_names += _BLIND_REPORT_ARTIFACTS
    raw_artifacts = [
        {
            "relative_path": (experiment_relative / name).as_posix(),
            "sha256": _sha256_path(experiment / name),
            "argv": list(evidence.verification_manifest.command),
        }
        for name in artifact_names
    ]
    return report.build_report(
        manifest=evidence.verification_manifest,
        hypothesis=hypothesis,
        gate=gate,
        scores=evidence.score_evidence,
        review=evidence.review,
        change_assessment=evidence.change,
        research_evidence=evidence.research,
        raw_artifacts=raw_artifacts,
        regressions=regressions,
        promotion_files=changed,
        limitations=(
            (
                "one_person_blind_review"
                if evidence.change.human_required
                else "deterministic_static_gates_only"
            ),
        ),
    )


def _validate_approval_report(experiment: Path, expected: str) -> None:
    try:
        supplied = (experiment / "report.md").read_bytes()
    except OSError as error:
        raise ValueError("report.md is unreadable") from error
    if supplied != expected.encode("utf-8"):
        raise ValueError("report.md does not match the exact verified evidence")


def _tree_files(root: Path) -> dict[str, Path]:
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): path
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file()
    }


@dataclass(frozen=True)
class _Replacement:
    target: Path
    source: Path | None
    expected: bytes | None
    boundary: Path
    label: str


def _append_if_changed(
    replacements: list[_Replacement],
    *,
    target: Path,
    source: Path | None,
    expected: bytes | None,
    boundary: Path,
    label: str,
) -> None:
    desired = None if source is None else source.read_bytes()
    if desired != expected:
        replacements.append(_Replacement(target, source, expected, boundary, label))


def _repository_replacements(
    registry: FamilyRegistry,
    candidate_root: Path,
    staged_source: Path,
    staged_dist: Path,
    changed: tuple[str, ...],
) -> list[_Replacement]:
    replacements: list[_Replacement] = []
    root = registry.root.resolve()
    baseline, candidate = _baseline_bytes(registry), _candidate_bytes(registry, candidate_root)
    for relative in changed:
        _append_if_changed(
            replacements,
            target=root / PurePosixPath(relative),
            source=staged_source / PurePosixPath(relative) if relative in candidate else None,
            expected=baseline.get(relative),
            boundary=root,
            label="canonical target",
        )
    current_dist = root / registry.generated["dist"]
    for runtime in registry.adapters:
        for skill in registry.skills:
            old_root, new_root = current_dist / runtime / skill.name, staged_dist / runtime / skill.name
            old_files, new_files = _tree_files(old_root), _tree_files(new_root)
            for relative in sorted(set(old_files) | set(new_files)):
                _append_if_changed(
                    replacements,
                    target=old_root / PurePosixPath(relative),
                    source=new_files.get(relative),
                    expected=old_files[relative].read_bytes() if relative in old_files else None,
                    boundary=root,
                    label="generated adapter target",
                )
    extension = registry.generated["package_extension"]
    for skill in registry.skills:
        old_package = current_dist / "packages" / f"{skill.name}{extension}"
        new_package = staged_dist / "packages" / f"{skill.name}{extension}"
        _append_if_changed(
            replacements,
            target=old_package,
            source=new_package,
            expected=old_package.read_bytes() if old_package.is_file() else None,
            boundary=root,
            label="generated package target",
        )
        old_snapshot = root / registry.generated["compatibility_snapshots"] / f"{skill.name}.SKILL.md"
        new_snapshot = staged_source / registry.generated["compatibility_snapshots"] / f"{skill.name}.SKILL.md"
        _append_if_changed(
            replacements,
            target=old_snapshot,
            source=new_snapshot,
            expected=old_snapshot.read_bytes() if old_snapshot.is_file() else None,
            boundary=root,
            label="compatibility snapshot target",
        )
    return replacements


def _validated_install_root(raw_root: Path, registry: FamilyRegistry) -> Path:
    supplied = Path(raw_root)
    if not supplied.is_absolute() or ".." in supplied.parts:
        raise ValueError("install_root must be one explicit absolute normalized path")
    current = Path(supplied.anchor)
    for part in supplied.parts[1:]:
        current = current / part
        if (current.exists() or current.is_symlink()) and _is_reparse(current):
            raise ValueError(
                "install_root uses a symlink, junction, or reparse point"
            )
    try:
        root = supplied.resolve(strict=True)
    except OSError as error:
        raise ValueError("install_root must be an existing directory") from error
    if not root.is_dir():
        raise ValueError("install_root must be an existing directory")
    drive_root, repository, home = Path(root.anchor).resolve(), registry.root.resolve(), Path.home().resolve()
    root_depth = len(root.relative_to(drive_root).parts)
    if (
        root_depth < 2
        or root == home
        or root == repository
        or repository.is_relative_to(root)
    ):
        raise ValueError("install_root is too broad")
    _audit_tree(root, root, "install_root")
    for skill in registry.skills:
        target = root / skill.name
        _audit_tree(root, target, "expected target skill directory")
        if target.parent.resolve() != root:
            raise ValueError("expected target skill directory must be a direct child")
    return root


def _install_replacements(
    registry: FamilyRegistry, install_root: Path, staged_dist: Path
) -> list[_Replacement]:
    replacements: list[_Replacement] = []
    current_dist = registry.root.resolve() / registry.generated["dist"] / "codex"
    for skill in registry.skills:
        old_files = _tree_files(current_dist / skill.name)
        new_files = _tree_files(staged_dist / "codex" / skill.name)
        target_root = install_root / skill.name
        for relative in sorted(set(old_files) | set(new_files)):
            target = target_root / PurePosixPath(relative)
            _audit_path(install_root, target, "installed target", require_exists=False)
            expected = old_files[relative].read_bytes() if relative in old_files else None
            if expected is None:
                if target.exists():
                    raise ValueError(f"installed target is unowned and would be overwritten: {target}")
            elif not target.is_file() or target.read_bytes() != expected:
                raise ValueError(f"installed target does not match the owned baseline: {target}")
            _append_if_changed(
                replacements,
                target=target,
                source=new_files.get(relative),
                expected=expected,
                boundary=install_root,
                label="installed target",
            )
    return replacements


def _validate_replacements(replacements: list[_Replacement]) -> None:
    targets: set[Path] = set()
    for item in replacements:
        target = item.target.absolute()
        if target in targets:
            raise ValueError(f"duplicate promotion target: {item.target}")
        targets.add(target)
        _audit_path(item.boundary, item.target, item.label, require_exists=False)
        if item.expected is None:
            if item.target.exists() or item.target.is_symlink():
                raise ValueError(f"unowned promotion target already exists: {item.target}")
        elif not item.target.is_file() or item.target.read_bytes() != item.expected:
            raise ValueError(f"promotion target changed before commit: {item.target}")
        if item.source is not None and (not item.source.is_file() or _is_reparse(item.source)):
            raise ValueError(f"staged promotion source is unsafe: {item.source}")


@dataclass
class _Committed:
    item: _Replacement
    backup: Path | None


def _ensure_parent(path: Path, boundary: Path, created: list[Path]) -> None:
    missing: list[Path] = []
    current = path
    while not current.exists():
        _lexically_contained(boundary, current, "promotion target parent")
        missing.append(current)
        current = current.parent
    _audit_path(boundary, current, "promotion target parent")
    for directory in reversed(missing):
        directory.mkdir()
        created.append(directory)


def _commit_replacements(
    replacements: list[_Replacement], recovery_root: Path
) -> None:
    committed: list[_Committed] = []
    adjacent_stages: list[Path] = []
    created_directories: list[Path] = []
    try:
        for item in replacements:
            _ensure_parent(item.target.parent, item.boundary, created_directories)
            staged = None
            if item.source is not None:
                staged = item.target.with_name(f".{item.target.name}.promotion-stage-{uuid.uuid4().hex}")
                adjacent_stages.append(staged)
                shutil.copy2(item.source, staged)
            backup = None
            if item.target.exists():
                backup = item.target.with_name(f".{item.target.name}.promotion-backup-{uuid.uuid4().hex}")
                os.replace(item.target, backup)
            committed.append(_Committed(item, backup))
            if staged is not None:
                os.replace(staged, item.target)
                adjacent_stages.remove(staged)
        for committed_item in committed:
            item = committed_item.item
            if item.source is None:
                if item.target.exists():
                    raise OSError(f"post-write hash failure for deleted target: {item.target}")
            elif not item.target.is_file() or _sha256_path(item.target) != _sha256_path(item.source):
                raise OSError(f"post-write hash failure for target: {item.target}")
    except Exception as error:
        rollback_errors: list[str] = []
        for committed_item in reversed(committed):
            item, backup = committed_item.item, committed_item.backup
            try:
                if item.target.exists() or item.target.is_symlink():
                    item.target.unlink()
                if backup is not None and backup.exists():
                    os.replace(backup, item.target)
            except OSError as rollback_error:
                rollback_errors.append(f"{item.target}: {rollback_error}")
        for staged in adjacent_stages:
            staged.unlink(missing_ok=True)
        for directory in reversed(created_directories):
            try:
                directory.rmdir()
            except OSError:
                pass
        if rollback_errors:
            raise RuntimeError(
                f"promotion failed ({error}); rollback failed: " + "; ".join(rollback_errors)
            ) from error
        raise
    for committed_item in committed:
        if committed_item.backup is not None:
            try:
                committed_item.backup.unlink(missing_ok=True)
            except OSError as error:
                retained = committed_item.backup
                try:
                    recovery_root.mkdir(exist_ok=True)
                    recovery = recovery_root / (
                        f"{uuid.uuid4().hex}-{committed_item.item.target.name}.backup"
                    )
                    os.replace(committed_item.backup, recovery)
                    retained = recovery
                except OSError:
                    pass
                warnings.warn(
                    f"retained promotion backup after commit: "
                    f"{retained} ({error})",
                    RuntimeWarning,
                    stacklevel=2,
                )


def _mark_invalid(experiment: Path, manifest: ExperimentManifest) -> None:
    invalid = transition(manifest, ExperimentStatus.INVALID)
    temporary = experiment / f".manifest.invalid-{uuid.uuid4().hex}"
    temporary.write_bytes(_json_bytes(invalid.to_dict()))
    try:
        os.replace(temporary, experiment / "manifest.json")
    finally:
        temporary.unlink(missing_ok=True)


def promote(
    experiment_dir: Path,
    registry: FamilyRegistry,
    approved_by_user: bool,
    install_root: Path | None = None,
) -> dict:
    """Promote one candidate after re-verifying every persisted trust boundary."""
    if approved_by_user is not True:
        raise PermissionError("promotion requires explicit user approval")
    experiment, manifest = _validate_experiment(experiment_dir, registry)
    hypothesis = Hypothesis.from_markdown(experiment / "hypothesis.md")
    missing = validate_artifacts(
        experiment,
        manifest,
        hypothesis.risk,
        blind_required=hypothesis.blind_required,
    )
    if missing:
        raise ValueError(f"required promotion artifacts are missing: {missing}")
    current_hashes = snapshot_registry(registry)
    if current_hashes != manifest.source_hashes:
        raise ValueError("current source hashes do not match manifest source hashes")
    current_gate = run_static_gate(
        registry, registry.root, registry.root / registry.generated["dist"]
    )
    if not current_gate.passed:
        raise ValueError("current generated outputs fail static validation")
    candidate_root = experiment / "candidate" / "source"
    _audit_tree(experiment, candidate_root, "candidate source")
    changed = changed_canonical_files(registry, candidate_root, manifest.source_hashes)
    if not changed:
        raise ValueError("candidate must change at least one canonical file")
    patch = _read_candidate_patch(experiment, _expected_patch(registry, candidate_root))
    candidate_bytes = _candidate_bytes(registry, candidate_root)
    post_hashes = {path: _sha256_bytes(value) for path, value in sorted(candidate_bytes.items())}
    with tempfile.TemporaryDirectory(
        prefix=f".{manifest.experiment_id}.promotion-", dir=experiment.parent
    ) as scratch_name:
        scratch = Path(scratch_name)
        staged_source = scratch / "source"
        shutil.copytree(candidate_root, staged_source, copy_function=shutil.copy2)
        staged_dist = scratch / "dist"
        render_all(registry, staged_source, staged_dist)
        candidate_gate = run_static_gate(registry, staged_source, staged_dist)
        if not candidate_gate.passed:
            raise ValueError("candidate static gate failed: " + "; ".join(candidate_gate.errors))
        evidence = _verify_task8_evidence(
            experiment,
            registry,
            manifest,
            hypothesis,
            patch,
            candidate_gate,
            post_hashes,
        )
        _validate_approval_report(
            experiment,
            _rebuild_approval_report(
                experiment,
                registry,
                hypothesis,
                candidate_gate,
                evidence,
                changed,
            ),
        )
        replacements = _repository_replacements(
            registry, candidate_root, staged_source, staged_dist, changed
        )
        resolved_install_root = None
        if install_root is not None:
            resolved_install_root = _validated_install_root(install_root, registry)
            replacements.extend(_install_replacements(registry, resolved_install_root, staged_dist))
        result = {
            "schema_version": 1,
            "experiment_id": manifest.experiment_id,
            "changed_paths": list(changed),
            "installed": resolved_install_root is not None,
            "installed_skills": [skill.name for skill in registry.skills] if resolved_install_root is not None else [],
            "pre_source_hashes": dict(sorted(current_hashes.items())),
            "post_source_hashes": post_hashes,
        }
        promoted_data = manifest.to_dict()
        promoted_data["status"] = ExperimentStatus.PROMOTED.value
        promoted_data["source_hashes"] = post_hashes
        promoted_manifest = ExperimentManifest.from_dict(promoted_data)
        staged_record = scratch / "promotion.json"
        staged_record.write_bytes(_json_bytes(result))
        staged_manifest = scratch / "manifest.json"
        staged_manifest.write_bytes(_json_bytes(promoted_manifest.to_dict()))
        replacements.extend(
            [
                _Replacement(experiment / "promotion.json", staged_record, None, experiment, "promotion record"),
                _Replacement(
                    experiment / "manifest.json",
                    staged_manifest,
                    (experiment / "manifest.json").read_bytes(),
                    experiment,
                    "promotion manifest",
                ),
            ]
        )
        _validate_replacements(replacements)
        try:
            _commit_replacements(
                replacements, experiment / "promotion-recovery"
            )
        except Exception:
            _mark_invalid(experiment, manifest)
            raise
    return result
