"""Fail-closed readiness decisions and deterministic approval reports."""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from types import MappingProxyType
from typing import Any
from weakref import WeakKeyDictionary

from .blind import (
    MAX_EVIDENCE_CHARACTERS,
    VerifiedBlindReview,
    is_verified_blind_review,
)
from .contracts import ExperimentManifest, ExperimentStatus
from .evals import AXES, SPLITS
from .hypothesis import Hypothesis, canonical_relative_path
from .research import normalize_claim
from .static_gate import GateResult


DECISIONS = frozenset(
    {
        "invalid",
        "blocked_external",
        "rejected",
        "awaiting_human",
        "ready_for_approval",
    }
)
ONE_PERSON_DISCLAIMER = (
    "이 결과는 사용자 1인의 선호이며, 통계적 우월성을 의미하지 않습니다."
)
MAX_REPORT_EXCERPT_CHARACTERS = 1_000
MAX_DIFF_CHARACTERS = 12_000

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_TARGET_SKILL_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_PATH_REDACTION_TOKEN = "CODEXREDACTEDPATHTOKEN"
_PATH_PATTERNS = (
    re.compile(r"file://[^\s<>\"'`]*", re.IGNORECASE),
    re.compile(r"\\\\[^\s<>\"'`]+"),
    re.compile(r"(?<!:)//[^\s<>\"'`]+"),
    re.compile(r"~[\\/][^\s<>\"'`]*"),
    re.compile(
        r"(?<![A-Za-z0-9])[A-Za-z]:(?:[\\/][^\s<>\"'`]*|[^\s/\\:][^\s<>\"'`]*)"
    ),
    re.compile(r"(?<![A-Za-z0-9:/])/(?!/)[^\s<>\"'`]+"),
)
_SCORE_FIELDS = frozenset(
    {
        "row_count",
        "deterministic_row_count",
        "deterministic_pair_count",
        "observed_pair_count",
        "coverage_verified",
        "expected_pair_count",
        "expected_golden_pair_count",
        "axes",
        "hard_gate_failures",
        "golden_failures",
        "hard_gates_passed",
        "golden_passed",
        "judge",
    }
)
_SCORE_EVIDENCE_FIELD = "generation_evidence_digest"
_AXIS_BUCKET_FIELDS = frozenset({"passed", "failed", "not_scored", "count"})
_FAILURE_FIELDS = frozenset({"case_id", "split", "repeat", "axis"})
_RAW_ARTIFACT_FIELDS = frozenset({"relative_path", "sha256", "argv"})
_PRIVATE_MAPPING_KEYS = frozenset(
    {
        "candidate_label",
        "presentations",
        "private_key",
        "label_map",
        "raw_output",
        "stdout",
        "stderr",
        "response_a",
        "response_b",
    }
)
_REGRESSION_AGGREGATE_FIELDS = frozenset(
    {
        "axis",
        "baseline_failed",
        "candidate_failed",
        "delta",
        "status",
        "summary",
    }
)
_PRIVATE_REGRESSION_KEYS = frozenset(
    {
        "pair_id",
        "source_id",
        "package_id",
        "private_key",
        "candidate_label",
        "label_map",
        "mapping",
        "mappings",
        "order",
        "seed",
        "secret",
        "receipt",
        "mac",
        "rating",
        "ratings",
        "raw_rating",
        "raw_ratings",
        "human_ratings",
        "quality_preference",
        "style_preference",
        "overall_preference",
        "evidence_excerpt",
        "meaning_or_fact_issue",
        "over_imitation",
        "raw_output",
        "response_a",
        "response_b",
        "relative_path",
        "path",
        "argv",
        "stdout",
        "stderr",
    }
)
_SHA256_TOKEN_RE = re.compile(r"(?<![0-9a-f])[0-9a-f]{64}(?![0-9a-f])", re.I)


def _canonical_json(value: object) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as error:
        raise ValueError("value is not canonical JSON data") from error


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a SHA-256 hex digest")
    return value


def _nonempty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    if "\x00" in value or any(
        ord(character) < 32 and character not in "\t\n\r" for character in value
    ):
        raise ValueError(f"{label} contains unsafe control characters")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _positive_int(value: object, label: str) -> int:
    number = _nonnegative_int(value, label)
    if number == 0:
        raise ValueError(f"{label} must be positive")
    return number


def _sequence(value: object, label: str, *, allow_empty: bool = True) -> list:
    if isinstance(value, (str, bytes, bytearray, Mapping)) or not isinstance(
        value, Sequence
    ):
        raise TypeError(f"{label} must be a sequence")
    result = list(value)
    if not allow_empty and not result:
        raise ValueError(f"{label} must not be empty")
    return result


def _target_skill(value: object, label: str) -> str:
    target = _nonempty_text(value, label)
    if len(target) > 64 or _TARGET_SKILL_RE.fullmatch(target) is None:
        raise ValueError(f"{label} must be a safe lowercase hyphenated skill name")
    return target


def _has_absolute_workspace_path(value: str) -> bool:
    return _redact_paths(value) != value


def _redact_paths(value: str) -> str:
    redacted = value
    for pattern in _PATH_PATTERNS:
        redacted = pattern.sub(_PATH_REDACTION_TOKEN, redacted)
    return redacted


def _ensure_safe_regression_value(value: object, label: str) -> None:
    if isinstance(value, Mapping):
        non_text_keys = [key for key in value if not isinstance(key, str)]
        if non_text_keys:
            raise ValueError(f"{label} contains non-text regression keys")
        forbidden = _PRIVATE_REGRESSION_KEYS & {key.casefold() for key in value}
        if forbidden:
            raise ValueError(f"{label} contains private regression fields: {sorted(forbidden)}")
        for key, nested in value.items():
            _ensure_safe_regression_value(nested, f"{label}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _ensure_safe_regression_value(nested, f"{label}[{index}]")
    elif isinstance(value, str):
        if _has_absolute_workspace_path(value):
            raise ValueError(f"{label} contains a private path")
        if _SHA256_TOKEN_RE.search(value):
            raise ValueError(f"{label} contains private identifier or secret material")


def _normalized_claim(claim: object) -> dict:
    if not isinstance(claim, Mapping):
        raise TypeError("research claim must be a mapping")
    data = dict(claim)
    stored_status = data.pop("status", None)
    normalized = normalize_claim(data)
    if stored_status is not None and stored_status != normalized["status"]:
        raise ValueError(
            "research claim actionable/watchlist status is inconsistent with its evidence"
        )
    for local in normalized["local_evidence"]:
        if _has_absolute_workspace_path(local):
            raise ValueError("research local_evidence must not contain absolute workspace paths")
    return normalized


def research_claim_id(claim: Mapping[str, object]) -> str:
    """Return a stable ID from canonical normalized claim JSON."""

    normalized = _normalized_claim(claim)
    return hashlib.sha256(_canonical_json(normalized).encode("utf-8")).hexdigest()


def _hypothesis_payload(hypothesis: Hypothesis) -> dict:
    checked = _validate_hypothesis(hypothesis)
    return {
        "claim_ids": list(checked.claim_ids),
        "change_group": checked.change_group,
        "allowed_paths": list(checked.allowed_paths),
        "primary_axis": checked.primary_axis,
        "protected_axes": list(checked.protected_axes),
        "risk": checked.risk,
        "blind_required": checked.blind_required,
        "stop_rule": checked.stop_rule,
        "body": checked.body,
    }


def _hypothesis_digest(hypothesis: Hypothesis) -> str:
    return hashlib.sha256(
        _canonical_json(_hypothesis_payload(hypothesis)).encode("utf-8")
    ).hexdigest()


_EVIDENCE_SEAL = object()


@dataclass(frozen=True, slots=True, weakref_slot=True, eq=False)
class VerifiedChangeAssessment:
    hypothesis_digest: str
    patch_digest: str
    changed_paths: tuple[str, ...]
    human_required: bool
    classification: str
    patch_text: str
    _seal: object


@dataclass(frozen=True, slots=True, weakref_slot=True, eq=False)
class VerifiedResearchEvidence:
    experiment_id: str
    hypothesis_digest: str
    claims: tuple[Mapping[str, object], ...]
    claim_ids: tuple[str, ...]
    _seal: object


def _change_fingerprint(value: VerifiedChangeAssessment) -> str:
    return hashlib.sha256(
        _canonical_json(
            {
                "hypothesis_digest": value.hypothesis_digest,
                "patch_digest": value.patch_digest,
                "changed_paths": value.changed_paths,
                "human_required": value.human_required,
                "classification": value.classification,
                "patch_text": value.patch_text,
            }
        ).encode("utf-8")
    ).hexdigest()


def _research_fingerprint(value: VerifiedResearchEvidence) -> str:
    return hashlib.sha256(
        _canonical_json(
            {
                "experiment_id": value.experiment_id,
                "hypothesis_digest": value.hypothesis_digest,
                "claims": [dict(claim) for claim in value.claims],
                "claim_ids": value.claim_ids,
            }
        ).encode("utf-8")
    ).hexdigest()


_ISSUED_CHANGES: WeakKeyDictionary[VerifiedChangeAssessment, str] = WeakKeyDictionary()
_ISSUED_RESEARCH: WeakKeyDictionary[VerifiedResearchEvidence, str] = WeakKeyDictionary()


def _is_verified_change(value: object) -> bool:
    if type(value) is not VerifiedChangeAssessment or value._seal is not _EVIDENCE_SEAL:
        return False
    try:
        return _ISSUED_CHANGES.get(value) == _change_fingerprint(value)
    except (AttributeError, TypeError, ValueError):
        return False


def _is_verified_research(value: object) -> bool:
    if type(value) is not VerifiedResearchEvidence or value._seal is not _EVIDENCE_SEAL:
        return False
    try:
        return _ISSUED_RESEARCH.get(value) == _research_fingerprint(value)
    except (AttributeError, TypeError, ValueError):
        return False


def _diff_paths(patch: str) -> tuple[str, ...]:
    lines = patch.splitlines()
    paths: set[str] = set()
    git_header_paths: set[str] = set()
    saw_pair = False
    index = 0
    while index < len(lines):
        line = lines[index]
        if line == "GIT binary patch" or line.startswith("Binary files "):
            raise ValueError("binary patch sections cannot be verified as a text-only change")
        if line.startswith(("rename from ", "rename to ", "copy from ", "copy to ")):
            raise ValueError("rename/copy patch sections are outside exact change scope")
        if line.startswith("diff --git "):
            match = re.fullmatch(r"diff --git a/(\S+) b/(\S+)", line)
            if match is None or match.group(1) != match.group(2):
                raise ValueError("patch has an unsupported or renamed git file section")
            git_header_paths.add(
                canonical_relative_path(match.group(1), "patch git header path")
            )
            index += 1
            continue
        if not line.startswith("--- "):
            index += 1
            continue
        if index + 1 >= len(lines) or not lines[index + 1].startswith("+++ "):
            raise ValueError("patch has an incomplete unified-diff header")
        old_raw = line[4:].split("\t", 1)[0]
        new_raw = lines[index + 1][4:].split("\t", 1)[0]
        old_path = None if old_raw == "/dev/null" else old_raw.removeprefix("a/")
        new_path = None if new_raw == "/dev/null" else new_raw.removeprefix("b/")
        if old_path is None and new_path is None:
            raise ValueError("patch cannot compare /dev/null to itself")
        normalized_old = (
            canonical_relative_path(old_path, "patch old path")
            if old_path is not None
            else None
        )
        normalized_new = (
            canonical_relative_path(new_path, "patch new path")
            if new_path is not None
            else None
        )
        if (
            normalized_old is not None
            and normalized_new is not None
            and normalized_old != normalized_new
        ):
            raise ValueError("patch renames are outside a single exact change scope")
        paths.add(normalized_new or normalized_old)  # type: ignore[arg-type]
        saw_pair = True
        index += 2
    if not saw_pair or not paths:
        raise ValueError("patch must contain at least one unified-diff file header")
    if git_header_paths and git_header_paths != paths:
        raise ValueError("git patch sections disagree with unified-diff scope")
    return tuple(sorted(paths))


def verify_change_assessment(
    hypothesis: Hypothesis, one_change_diff: str
) -> VerifiedChangeAssessment:
    """Bind an exact unified diff to its hypothesis and classify review risk."""

    checked = _validate_hypothesis(hypothesis)
    patch = _nonempty_text(one_change_diff, "one_change_diff")
    changed_paths = _diff_paths(patch)
    if set(changed_paths) != set(checked.allowed_paths):
        raise ValueError("patch scope must exactly match hypothesis.allowed_paths")
    static_sync = (
        checked.change_group == "packaging/static-sync"
        and checked.risk == "low"
        and checked.blind_required is False
        and changed_paths == ("sync_core.py",)
    )
    assessment = VerifiedChangeAssessment(
        hypothesis_digest=_hypothesis_digest(checked),
        patch_digest=hashlib.sha256(patch.encode("utf-8")).hexdigest(),
        changed_paths=changed_paths,
        human_required=not static_sync,
        classification="packaging_static_sync" if static_sync else "human_review_required",
        patch_text=patch,
        _seal=_EVIDENCE_SEAL,
    )
    _ISSUED_CHANGES[assessment] = _change_fingerprint(assessment)
    return assessment


def verify_research_evidence(
    experiment_id: str,
    hypothesis: Hypothesis,
    claims: Sequence[Mapping[str, object]],
) -> VerifiedResearchEvidence:
    """Bind every hypothesis claim to actionable normalized research evidence."""

    checked = _validate_hypothesis(hypothesis)
    identifier = _nonempty_text(experiment_id, "experiment_id")
    if "/" in identifier or "\\" in identifier or identifier in {".", ".."}:
        raise ValueError("experiment_id must be a safe identifier")
    raw_claims = _sequence(claims, "claims", allow_empty=False)
    normalized_by_id: dict[str, dict] = {}
    for raw in raw_claims:
        normalized = _normalized_claim(raw)
        claim_id = research_claim_id(normalized)
        if claim_id in normalized_by_id:
            raise ValueError(f"duplicate research claim: {claim_id}")
        if normalized["status"] != "actionable":
            raise ValueError(f"research claim {claim_id} must be actionable")
        normalized_by_id[claim_id] = normalized
    if set(normalized_by_id) != set(checked.claim_ids):
        unresolved = sorted(set(checked.claim_ids) - set(normalized_by_id))
        extra = sorted(set(normalized_by_id) - set(checked.claim_ids))
        raise ValueError(
            f"research claims do not exactly resolve hypothesis; unresolved={unresolved}; extra={extra}"
        )
    frozen_claims = tuple(
        MappingProxyType(
            {
                **normalized_by_id[claim_id],
                "local_evidence": tuple(normalized_by_id[claim_id]["local_evidence"]),
            }
        )
        for claim_id in sorted(normalized_by_id)
    )
    evidence = VerifiedResearchEvidence(
        experiment_id=identifier,
        hypothesis_digest=_hypothesis_digest(checked),
        claims=frozen_claims,
        claim_ids=tuple(sorted(normalized_by_id)),
        _seal=_EVIDENCE_SEAL,
    )
    _ISSUED_RESEARCH[evidence] = _research_fingerprint(evidence)
    return evidence


def _validate_manifest(manifest: object) -> ExperimentManifest:
    if not isinstance(manifest, ExperimentManifest):
        raise TypeError("manifest must be an ExperimentManifest")
    reparsed = ExperimentManifest.from_dict(manifest.to_dict())
    if reparsed != manifest:
        raise ValueError("manifest does not round-trip through its declared schema")
    if manifest.status not in {
        ExperimentStatus.AUTO_EVALUATED,
        ExperimentStatus.AWAITING_HUMAN,
    }:
        raise ValueError(
            "readiness requires an auto_evaluated or awaiting_human manifest"
        )
    if manifest.runtime != "codex":
        raise ValueError("manifest.runtime must be codex for behavioral readiness")
    if not manifest.source_hashes:
        raise ValueError("manifest.source_hashes provenance must not be empty")
    if not manifest.dataset_versions:
        raise ValueError("manifest.dataset_versions provenance must not be empty")
    for path, digest in manifest.source_hashes.items():
        canonical_relative_path(path, "manifest.source_hashes path")
        _sha256(digest, "manifest.source_hashes digest")
    return manifest


def _validate_hypothesis(hypothesis: object) -> Hypothesis:
    if not isinstance(hypothesis, Hypothesis):
        raise TypeError("hypothesis must be a Hypothesis")
    if (
        not hypothesis.claim_ids
        or not all(isinstance(item, str) and item for item in hypothesis.claim_ids)
        or len(set(hypothesis.claim_ids)) != len(hypothesis.claim_ids)
    ):
        raise ValueError("hypothesis.claim_ids must be unique non-empty strings")
    _nonempty_text(hypothesis.change_group, "hypothesis.change_group")
    if not hypothesis.allowed_paths or len(set(hypothesis.allowed_paths)) != len(
        hypothesis.allowed_paths
    ):
        raise ValueError("hypothesis.allowed_paths must be unique and non-empty")
    for path in hypothesis.allowed_paths:
        canonical_relative_path(path, "hypothesis.allowed_paths")
    if hypothesis.primary_axis not in AXES:
        raise ValueError("hypothesis.primary_axis must be one of the six evaluation axes")
    if (
        not hypothesis.protected_axes
        or len(set(hypothesis.protected_axes)) != len(hypothesis.protected_axes)
        or any(axis not in AXES for axis in hypothesis.protected_axes)
    ):
        raise ValueError("hypothesis.protected_axes must be unique known axes")
    _nonempty_text(hypothesis.risk, "hypothesis.risk")
    if type(hypothesis.blind_required) is not bool:
        raise ValueError("hypothesis.blind_required must be boolean")
    _nonempty_text(hypothesis.stop_rule, "hypothesis.stop_rule")
    if not isinstance(hypothesis.body, str):
        raise ValueError("hypothesis.body must be a string")
    return hypothesis


def _gate_rejected(gate: object) -> bool:
    if not isinstance(gate, GateResult):
        raise TypeError("gate must be a GateResult")
    if type(gate.passed) is not bool:
        raise ValueError("gate.passed must be boolean")
    if not isinstance(gate.errors, tuple) or not all(
        isinstance(error, str) and error.strip() for error in gate.errors
    ):
        raise ValueError("gate.errors must be a tuple of non-empty strings")
    if not isinstance(gate.details, dict):
        raise ValueError("gate.details must be a dictionary")
    if gate.passed and gate.errors:
        raise ValueError("a passing gate cannot contain errors")
    if not gate.passed and not gate.errors:
        raise ValueError("a failed gate must contain explicit errors")
    return not gate.passed


def _validate_failure_list(value: object, label: str, *, golden_only: bool) -> list[dict]:
    rows = _sequence(value, label)
    normalized: list[dict] = []
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping) or set(raw) != _FAILURE_FIELDS:
            raise ValueError(f"{label}[{index}] must use the exact Task 7 failure schema")
        case_id = _nonempty_text(raw["case_id"], f"{label}[{index}].case_id")
        split = raw["split"]
        if split not in SPLITS:
            raise ValueError(f"{label}[{index}].split is invalid")
        if golden_only and split != "golden":
            raise ValueError(f"{label}[{index}] must refer to the golden split")
        repeat = _nonnegative_int(raw["repeat"], f"{label}[{index}].repeat")
        axis = raw["axis"]
        if axis not in AXES:
            raise ValueError(f"{label}[{index}].axis is invalid")
        normalized.append(
            {"case_id": case_id, "split": split, "repeat": repeat, "axis": axis}
        )
    return normalized


def _validated_scores(scores: object) -> tuple[dict, bool]:
    if not isinstance(scores, dict):
        raise TypeError("scores must be a dictionary")
    score_fields = set(scores)
    if score_fields not in {_SCORE_FIELDS, _SCORE_FIELDS | {_SCORE_EVIDENCE_FIELD}}:
        raise ValueError(
            "scores must use the exact Task 7 aggregate schema; "
            f"missing={sorted(_SCORE_FIELDS - set(scores))}; "
            f"unknown={sorted(set(scores) - _SCORE_FIELDS - {_SCORE_EVIDENCE_FIELD})}"
        )
    evidence_digest = (
        _sha256(scores[_SCORE_EVIDENCE_FIELD], f"scores.{_SCORE_EVIDENCE_FIELD}")
        if _SCORE_EVIDENCE_FIELD in scores
        else None
    )
    # Deliberately do not inspect scores["judge"]. It is supporting-only and
    # cannot affect readiness, even when malformed or adversarial.
    if scores["coverage_verified"] is not True:
        raise ValueError("scores.coverage_verified must be exactly true")
    expected = _positive_int(scores["expected_pair_count"], "expected_pair_count")
    observed = _positive_int(scores["observed_pair_count"], "observed_pair_count")
    deterministic_pairs = _positive_int(
        scores["deterministic_pair_count"], "deterministic_pair_count"
    )
    if expected != observed or expected != deterministic_pairs:
        raise ValueError("expected, observed, and deterministic pair counts must match")
    deterministic_rows = _positive_int(
        scores["deterministic_row_count"], "deterministic_row_count"
    )
    if deterministic_rows != 2 * deterministic_pairs:
        raise ValueError("deterministic_row_count must equal two rows per pair")
    row_count = _positive_int(scores["row_count"], "row_count")
    if row_count < deterministic_rows:
        raise ValueError("row_count cannot be smaller than deterministic_row_count")
    golden_pairs = _positive_int(
        scores["expected_golden_pair_count"], "expected_golden_pair_count"
    )
    if golden_pairs > expected:
        raise ValueError("expected_golden_pair_count cannot exceed expected_pair_count")

    axes = scores["axes"]
    if not isinstance(axes, dict) or set(axes) != set(AXES):
        raise ValueError("scores.axes must contain exactly the six evaluation axes")
    normalized_axes: dict[str, dict] = {}
    for axis in AXES:
        conditions = axes[axis]
        if not isinstance(conditions, dict) or set(conditions) != {"baseline", "candidate"}:
            raise ValueError(f"scores.axes.{axis} must contain baseline and candidate")
        normalized_axes[axis] = {}
        for condition in ("baseline", "candidate"):
            bucket = conditions[condition]
            if not isinstance(bucket, dict) or set(bucket) != _AXIS_BUCKET_FIELDS:
                raise ValueError(f"scores.axes.{axis}.{condition} has invalid schema")
            values = {
                key: _nonnegative_int(
                    bucket[key], f"scores.axes.{axis}.{condition}.{key}"
                )
                for key in _AXIS_BUCKET_FIELDS
            }
            if values["count"] != deterministic_pairs:
                raise ValueError(
                    f"scores.axes.{axis}.{condition}.count must equal pair count"
                )
            if (
                values["passed"] + values["failed"] + values["not_scored"]
                != values["count"]
            ):
                raise ValueError(
                    f"scores.axes.{axis}.{condition} buckets must sum to count"
                )
            normalized_axes[axis][condition] = values

    hard_failures = _validate_failure_list(
        scores["hard_gate_failures"], "hard_gate_failures", golden_only=False
    )
    if any(
        failure["axis"] not in {"request_fulfillment", "meaning_and_facts"}
        for failure in hard_failures
    ):
        raise ValueError("hard_gate_failures may contain only hard-gate axes")
    hard_failure_counts: dict[str, int] = defaultdict(int)
    for failure in hard_failures:
        hard_failure_counts[failure["axis"]] += 1
    for axis in ("request_fulfillment", "meaning_and_facts"):
        candidate = normalized_axes[axis]["candidate"]
        observed_not_passing = candidate["failed"] + candidate["not_scored"]
        if hard_failure_counts[axis] != observed_not_passing:
            raise ValueError(
                f"hard_gate_failures conflicts with candidate {axis} buckets"
            )
    golden_failures = _validate_failure_list(
        scores["golden_failures"], "golden_failures", golden_only=True
    )
    for flag_name, failures in (
        ("hard_gates_passed", hard_failures),
        ("golden_passed", golden_failures),
    ):
        flag = scores[flag_name]
        if type(flag) is not bool:
            raise ValueError(f"scores.{flag_name} must be strictly boolean")
        if flag and failures:
            raise ValueError(f"scores.{flag_name} conflicts with recorded failures")
        if not flag and not failures:
            raise ValueError(f"scores.{flag_name}=false requires recorded failures")

    normalized = {
        **{key: scores[key] for key in _SCORE_FIELDS - {"axes", "judge"}},
        "axes": normalized_axes,
        "judge": None,
        _SCORE_EVIDENCE_FIELD: evidence_digest,
    }
    return normalized, (
        scores["hard_gates_passed"] is False or scores["golden_passed"] is False
    )


@dataclass(frozen=True, slots=True)
class ReadinessResult:
    status: str
    reasons: tuple[str, ...]


def _result(status: str, *reasons: str) -> ReadinessResult:
    return ReadinessResult(status=status, reasons=tuple(reasons))


def _source_preference_counts(
    rows: Sequence[Mapping[str, object]], field: str
) -> dict[str, int]:
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["source_id"])].append(row)
    counts = {"candidate": 0, "baseline": 0, "tie": 0}
    for group in grouped.values():
        votes = [row[field] for row in group]
        if len(votes) == 2 and all(vote == "candidate" for vote in votes):
            counts["candidate"] += 1
        elif len(votes) == 2 and all(vote == "baseline" for vote in votes):
            counts["baseline"] += 1
        else:
            counts["tie"] += 1
    return counts


def evaluate_readiness(
    manifest: ExperimentManifest,
    hypothesis: Hypothesis,
    gate: GateResult,
    scores: dict,
    review: VerifiedBlindReview | None,
    change_assessment: VerifiedChangeAssessment,
    research_evidence: VerifiedResearchEvidence,
) -> ReadinessResult:
    """Return a structured fail-closed decision from process-local evidence."""

    if not isinstance(manifest, ExperimentManifest):
        return _result("invalid", "invalid_manifest")
    try:
        reparsed = ExperimentManifest.from_dict(manifest.to_dict())
    except (TypeError, ValueError, AttributeError):
        return _result("invalid", "invalid_manifest")
    if reparsed != manifest:
        return _result("invalid", "invalid_manifest")
    if manifest.status is ExperimentStatus.BLOCKED_EXTERNAL:
        return _result("blocked_external", "external_execution_blocked")
    if manifest.status is ExperimentStatus.INVALID:
        return _result("invalid", "manifest_marked_invalid")
    if manifest.status is ExperimentStatus.REJECTED:
        return _result("rejected", "manifest_marked_rejected")
    try:
        checked_manifest = _validate_manifest(manifest)
    except (TypeError, ValueError, AttributeError):
        return _result("invalid", "invalid_manifest")
    try:
        checked_hypothesis = _validate_hypothesis(hypothesis)
        hypothesis_digest = _hypothesis_digest(checked_hypothesis)
    except (TypeError, ValueError, AttributeError):
        return _result("invalid", "invalid_hypothesis")
    try:
        static_rejected = _gate_rejected(gate)
    except (TypeError, ValueError, AttributeError):
        return _result("invalid", "invalid_static_gate")
    try:
        checked_scores, aggregate_rejected = _validated_scores(scores)
    except (TypeError, ValueError, AttributeError):
        return _result("invalid", "invalid_scores")

    if (
        not _is_verified_change(change_assessment)
        or change_assessment.hypothesis_digest != hypothesis_digest
        or set(change_assessment.changed_paths) != set(checked_hypothesis.allowed_paths)
    ):
        return _result("invalid", "invalid_change_assessment")
    if (
        not _is_verified_research(research_evidence)
        or research_evidence.experiment_id != checked_manifest.experiment_id
        or research_evidence.hypothesis_digest != hypothesis_digest
        or set(research_evidence.claim_ids) != set(checked_hypothesis.claim_ids)
    ):
        return _result("invalid", "invalid_research_evidence")
    if review is not None and not is_verified_blind_review(review):
        return _result("invalid", "invalid_blind_review")

    expected_pairs = checked_scores["expected_pair_count"]
    if review is not None and (
        review.experiment_id != checked_manifest.experiment_id
        or review.expected_count != expected_pairs * 2
        or review.coverage_count > review.expected_count
    ):
        return _result("invalid", "invalid_blind_review")

    if change_assessment.human_required and review is not None and (
        checked_scores[_SCORE_EVIDENCE_FIELD] is None
        or review.generation_evidence_digest
        != checked_scores[_SCORE_EVIDENCE_FIELD]
    ):
        return _result("invalid", "blind_review_evidence_mismatch")

    candidate_required = {
        checked_hypothesis.primary_axis,
        *checked_hypothesis.protected_axes,
    }
    if any(
        checked_scores["axes"][axis]["candidate"]["not_scored"] > 0
        for axis in candidate_required
    ):
        return _result("invalid", "candidate_axis_not_scored")
    rejection_reasons: list[str] = []
    if static_rejected:
        rejection_reasons.append("static_gate_failed")
    if aggregate_rejected:
        if checked_scores["hard_gates_passed"] is False:
            rejection_reasons.append("hard_gate_failed")
        if checked_scores["golden_passed"] is False:
            rejection_reasons.append("golden_gate_failed")
    if any(
        checked_scores["axes"][axis]["candidate"]["failed"]
        > checked_scores["axes"][axis]["baseline"]["failed"]
        for axis in checked_hypothesis.protected_axes
    ):
        rejection_reasons.append("protected_axis_regression")
    if rejection_reasons:
        return _result("rejected", *rejection_reasons)

    if not change_assessment.human_required:
        return _result("ready_for_approval", "automatic_requirements_satisfied")
    if review is None or not review.complete:
        return _result("awaiting_human", "human_review_partial")

    rows = review.condition_ratings
    grouped: dict[str, list[Mapping[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["source_id"])].append(row)
    if (
        len(rows) != expected_pairs * 2
        or len(grouped) != expected_pairs
        or any(len(group) != 2 for group in grouped.values())
    ):
        return _result("invalid", "invalid_blind_review")

    human_rejections: list[str] = []
    if any(
        row["candidate_over_imitation"] is True
        and row["baseline_over_imitation"] is False
        for row in rows
    ):
        human_rejections.append("candidate_over_imitation_regression")
    if any(
        row["candidate_meaning_or_fact_issue"] == "critical" for row in rows
    ):
        human_rejections.append("candidate_critical_meaning_or_fact_issue")
    overall = _source_preference_counts(rows, "overall_preference")
    primary_field = (
        "style_preference"
        if checked_hypothesis.primary_axis == "style_behavior"
        else "quality_preference"
    )
    primary = _source_preference_counts(rows, primary_field)
    if overall["candidate"] <= expected_pairs / 2:
        human_rejections.append("overall_candidate_majority_missing")
    if primary["candidate"] <= expected_pairs / 2:
        human_rejections.append("primary_candidate_majority_missing")
    if human_rejections:
        return _result("rejected", *human_rejections)
    return _result("ready_for_approval", "human_requirements_satisfied")


def decide_readiness(
    manifest: ExperimentManifest,
    hypothesis: Hypothesis,
    gate: GateResult,
    scores: dict,
    review: VerifiedBlindReview | None,
    change_assessment: VerifiedChangeAssessment,
    research_evidence: VerifiedResearchEvidence,
) -> str:
    """Return the readiness status while preserving structured reasons separately."""

    try:
        return evaluate_readiness(
            manifest,
            hypothesis,
            gate,
            scores,
            review,
            change_assessment,
            research_evidence,
        ).status
    except Exception:
        return "invalid"


def _safe_relative_path(value: object, label: str) -> str:
    path = canonical_relative_path(value, label)
    if _has_absolute_workspace_path(path):
        raise ValueError(f"{label} must not be absolute")
    return path


def _argv(value: object, label: str) -> tuple[tuple[str, ...], str]:
    parts = _sequence(value, label, allow_empty=False)
    original: list[str] = []
    normalized: list[str] = []
    for index, part in enumerate(parts):
        token = _nonempty_text(part, f"{label}[{index}]")
        original.append(token)
        normalized.append(_redact_paths(token))
    digest = hashlib.sha256(_canonical_json(original).encode("utf-8")).hexdigest()
    return tuple(normalized), digest


def _validated_raw_artifacts(raw_artifacts: object) -> tuple[list[dict], int]:
    rows = _sequence(raw_artifacts, "raw_artifacts", allow_empty=False)
    normalized: list[dict] = []
    seen_paths: set[str] = set()
    private_exclusions = 0
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping) or set(raw) != _RAW_ARTIFACT_FIELDS:
            raise ValueError(f"raw_artifacts[{index}] has invalid schema")
        path = _safe_relative_path(raw["relative_path"], "raw artifact relative_path")
        if path in seen_paths:
            raise ValueError(f"duplicate raw artifact path: {path}")
        seen_paths.add(path)
        filename = PurePosixPath(path).name.casefold()
        if filename in {
            "blind_key.private.json",
            "blind_review.private.json",
        } or (filename.startswith("blind_") and ".private." in filename):
            private_exclusions += 1
            continue
        argv, argv_sha256 = _argv(raw["argv"], "raw artifact argv")
        normalized.append(
            {
                "relative_path": path,
                "sha256": _sha256(raw["sha256"], "raw artifact sha256"),
                "argv": argv,
                "argv_sha256": argv_sha256,
            }
        )
    return sorted(normalized, key=lambda row: row["relative_path"]), private_exclusions


def _text_items(value: object, label: str, *, allow_empty: bool) -> list[str]:
    rows = _sequence(value, label, allow_empty=allow_empty)
    normalized: list[str] = []
    for index, item in enumerate(rows):
        text = _nonempty_text(item, f"{label}[{index}]")
        normalized.append(text)
    return normalized


def _regression_items(value: object) -> list[str]:
    rows = _sequence(value, "regressions")
    normalized: list[str] = []
    for index, item in enumerate(rows):
        if isinstance(item, str):
            _ensure_safe_regression_value(item, f"regressions[{index}]")
            text = _nonempty_text(item, f"regressions[{index}]")
        elif isinstance(item, Mapping):
            label = f"regressions[{index}]"
            _ensure_safe_regression_value(item, label)
            if set(item) != _REGRESSION_AGGREGATE_FIELDS:
                raise ValueError(
                    f"{label} must use the exact aggregate regression schema"
                )
            axis = item["axis"]
            if axis not in AXES:
                raise ValueError(f"{label}.axis is invalid")
            baseline_failed = _nonnegative_int(
                item["baseline_failed"], f"{label}.baseline_failed"
            )
            candidate_failed = _nonnegative_int(
                item["candidate_failed"], f"{label}.candidate_failed"
            )
            delta = item["delta"]
            if type(delta) is not int or delta != candidate_failed - baseline_failed:
                raise ValueError(f"{label}.delta must equal candidate minus baseline")
            expected_status = (
                "regressed" if delta > 0 else "improved" if delta < 0 else "unchanged"
            )
            if item["status"] != expected_status:
                raise ValueError(f"{label}.status conflicts with aggregate counts")
            summary = _nonempty_text(item["summary"], f"{label}.summary")
            text = _canonical_json(
                {
                    "axis": axis,
                    "baseline_failed": baseline_failed,
                    "candidate_failed": candidate_failed,
                    "delta": delta,
                    "status": expected_status,
                    "summary": summary,
                }
            )
        else:
            raise TypeError("regressions entries must be text or aggregate mappings")
        normalized.append(text)
    return sorted(normalized)


def _excerpt(value: str, limit: int = MAX_REPORT_EXCERPT_CHARACTERS) -> str:
    redacted = _redact_paths(value)
    bounded = redacted if len(redacted) <= limit else redacted[:limit] + "… [truncated]"
    escaped = html.escape(bounded, quote=True)
    escaped = escaped.translate(
        {
            ord(character): f"&#{ord(character)};"
            for character in "`[]()!*_\\:"
        }
    )
    return escaped.replace(_PATH_REDACTION_TOKEN, "[REDACTED_PATH]")


def _inline(value: object) -> str:
    return _excerpt(str(value)).replace("|", "&#124;").replace("\r\n", "<br>").replace(
        "\n", "<br>"
    )


def _terminal_diagnostic_report(
    readiness: ReadinessResult, manifest: object
) -> str:
    experiment_id = (
        manifest.experiment_id
        if type(manifest) is ExperimentManifest
        and isinstance(manifest.experiment_id, str)
        else "unavailable"
    )
    return "\n".join(
        [
            "# Decision",
            "",
            f"- Decision: `{readiness.status}`",
            "- Reason codes: "
            + ", ".join(f"`{code}`" for code in readiness.reasons),
            f"- Experiment: `{_inline(experiment_id)}`",
            "- Evidence withheld: terminal-safe diagnostics do not render unverified evidence.",
            "",
        ]
    )


def build_report(
    *,
    manifest: ExperimentManifest,
    hypothesis: Hypothesis,
    gate: GateResult,
    scores: dict,
    review: VerifiedBlindReview | None,
    change_assessment: VerifiedChangeAssessment,
    research_evidence: VerifiedResearchEvidence,
    raw_artifacts: Sequence[Mapping[str, object]],
    regressions: Sequence[object],
    promotion_files: Sequence[str],
    limitations: Sequence[str],
) -> str:
    """Render a deterministic public report from verified, aggregate-only evidence."""

    readiness = evaluate_readiness(
        manifest,
        hypothesis,
        gate,
        scores,
        review,
        change_assessment,
        research_evidence,
    )
    if readiness.status in {"invalid", "blocked_external"}:
        return _terminal_diagnostic_report(readiness, manifest)
    try:
        checked_hypothesis = _validate_hypothesis(hypothesis)
    except (TypeError, ValueError, AttributeError):
        checked_hypothesis = None
    try:
        checked_scores, _aggregate_rejected = _validated_scores(scores)
    except (TypeError, ValueError, AttributeError):
        checked_scores = None
    artifacts, private_exclusions = _validated_raw_artifacts(raw_artifacts)
    regression_rows = _regression_items(regressions)
    promotion = sorted(
        {
            _safe_relative_path(path, "promotion_files path")
            for path in _text_items(
                promotion_files, "promotion_files", allow_empty=False
            )
        }
    )
    limitation_rows = _text_items(limitations, "limitations", allow_empty=False)
    static_errors = (
        _text_items(gate.errors, "gate.errors", allow_empty=True)
        if isinstance(gate, GateResult)
        else []
    )
    reason_codes = list(readiness.reasons)
    if private_exclusions:
        reason_codes.append("private_artifact_excluded")

    source_hashes: list[tuple[str, str]] = []
    manifest_argv: tuple[str, ...] = ()
    manifest_argv_sha256 = "unavailable"
    if isinstance(manifest, ExperimentManifest):
        for path, digest in sorted(manifest.source_hashes.items()):
            source_hashes.append(
                (
                    _safe_relative_path(path, "manifest source hash path"),
                    _sha256(digest, "manifest source hash"),
                )
            )
        manifest_argv, manifest_argv_sha256 = _argv(
            manifest.command, "manifest.command"
        )

    lines: list[str] = [
        "# Decision",
        "",
        f"- Decision: `{readiness.status}`",
        "- Reason codes: "
        + ", ".join(f"`{code}`" for code in reason_codes),
        f"- Static gate passed: `{str(getattr(gate, 'passed', False)).lower()}`",
        "- Experiment: `"
        + _inline(getattr(manifest, "experiment_id", "unavailable"))
        + "`",
        "",
        "## Hypothesis",
        "",
    ]
    if checked_hypothesis is None:
        lines.append("- Unavailable because the hypothesis is invalid.")
    else:
        lines.extend(
            [
                f"- Change group: `{_inline(checked_hypothesis.change_group)}`",
                f"- Declared risk: `{_inline(checked_hypothesis.risk)}`",
                "- Verified change classification: `"
                + _inline(
                    change_assessment.classification
                    if _is_verified_change(change_assessment)
                    else "unverified"
                )
                + "`",
                "- Human review required: `"
                + str(
                    change_assessment.human_required
                    if _is_verified_change(change_assessment)
                    else True
                ).lower()
                + "`",
                f"- Primary axis: `{checked_hypothesis.primary_axis}`",
                "- Protected axes: "
                + ", ".join(f"`{axis}`" for axis in checked_hypothesis.protected_axes),
                "- Allowed paths: "
                + ", ".join(
                    f"`{_inline(path)}`" for path in checked_hypothesis.allowed_paths
                ),
                f"- Stop rule: {_inline(checked_hypothesis.stop_rule)}",
                "",
                _excerpt(checked_hypothesis.body),
            ]
        )

    lines.extend(["", "## Research Claims and Local Evidence", ""])
    if _is_verified_research(research_evidence):
        for claim_id, claim in zip(
            research_evidence.claim_ids, research_evidence.claims, strict=True
        ):
            lines.extend(
                [
                    f"### `{claim_id}`",
                    "",
                    f"- Claim: {_inline(claim['claim'])}",
                    f"- Source: {_inline(claim['source_url'])}",
                    "- Source date / checked: `"
                    + _inline(claim["source_date"])
                    + "` / `"
                    + _inline(claim["checked_at"])
                    + "`",
                    "- Type / confidence / status: `"
                    + _inline(claim["source_type"])
                    + "` / `"
                    + _inline(claim["confidence"])
                    + "` / `actionable`",
                    f"- Evidence: {_inline(claim['evidence'])}",
                    "- Local evidence: "
                    + ", ".join(
                        f"`{_inline(item)}`" for item in claim["local_evidence"]
                    ),
                    f"- Decision impact: {_inline(claim['decision_impact'])}",
                    f"- Proposed test: {_inline(claim['proposed_test'])}",
                    "",
                ]
            )
    else:
        lines.append("- Unavailable because research evidence is unverified.")

    lines.extend(["", "## One-Change Diff", ""])
    if _is_verified_change(change_assessment):
        lines.extend(
            [
                f"- Patch SHA-256: `{change_assessment.patch_digest}`",
                "<pre>",
                _excerpt(change_assessment.patch_text, MAX_DIFF_CHARACTERS),
                "</pre>",
            ]
        )
    else:
        lines.append("- Unavailable because the change assessment is unverified.")

    lines.extend(
        [
            "",
            "## Artifact Paths",
            "",
            "| Relative path | SHA-256 |",
            "|---|---|",
        ]
    )
    if artifacts:
        for artifact in artifacts:
            lines.append(
                f"| `{_inline(artifact['relative_path'])}` | `{artifact['sha256']}` |"
            )
    else:
        lines.append("| None public | unavailable |")

    lines.extend(["", "## Per-Axis Results", ""])
    if checked_scores is None:
        lines.append("- Unavailable: `invalid_scores`.")
    else:
        lines.extend(
            [
                "| Axis | Baseline passed | Baseline failed | Baseline not_scored | Candidate passed | Candidate failed | Candidate not_scored |",
                "|---|---:|---:|---:|---:|---:|---:|",
            ]
        )
        for axis in AXES:
            baseline = checked_scores["axes"][axis]["baseline"]
            candidate = checked_scores["axes"][axis]["candidate"]
            lines.append(
                f"| `{axis}` | {baseline['passed']} | {baseline['failed']} | {baseline['not_scored']} | "
                f"{candidate['passed']} | {candidate['failed']} | {candidate['not_scored']} |"
            )
        lines.extend(
            [
                "",
                f"- Coverage: expected `{checked_scores['expected_pair_count']}`, observed `{checked_scores['observed_pair_count']}`, deterministic `{checked_scores['deterministic_pair_count']}` pairs / `{checked_scores['deterministic_row_count']}` rows.",
                f"- Expected golden pairs: `{checked_scores['expected_golden_pair_count']}`",
                f"- Hard gates passed: `{str(checked_scores['hard_gates_passed']).lower()}`",
                f"- Golden passed: `{str(checked_scores['golden_passed']).lower()}`",
                "- LLM judge: supporting-only and excluded from readiness.",
            ]
        )

    lines.extend(["", "### Static Gate Failures", ""])
    lines.extend(f"- {_inline(error)}" for error in static_errors)
    if not static_errors:
        lines.append("- None.")
    for heading, key in (
        ("Hard Gate Failures", "hard_gate_failures"),
        ("Golden Failures", "golden_failures"),
    ):
        lines.extend(["", f"### {heading}", ""])
        failures = checked_scores[key] if checked_scores is not None else []
        if failures:
            for failure in failures:
                lines.append(
                    "- case `"
                    + _inline(failure["case_id"])
                    + f"`, split `{failure['split']}`, repeat `{failure['repeat']}`, axis `{failure['axis']}`"
                )
        else:
            lines.append("- None.")

    lines.extend(["", "## Regressions", ""])
    lines.extend(f"- {_inline(item)}" for item in regression_rows)
    if not regression_rows:
        lines.append("- None reported.")

    lines.extend(["", "## Human Blind Review", "", ONE_PERSON_DISCLAIMER, ""])
    if review is not None and is_verified_blind_review(review):
        lines.extend(
            [
                f"- Public bundle digest: `{review.public_bundle_digest}`",
                f"- Coverage: `{review.coverage_count}` / `{review.expected_count}` presentations",
            ]
        )
        if review.complete:
            overall = _source_preference_counts(
                review.condition_ratings, "overall_preference"
            )
            lines.append(
                "- Aggregate preference: candidate `"
                + str(overall["candidate"])
                + "`, baseline `"
                + str(overall["baseline"])
                + "`, tie `"
                + str(overall["tie"])
                + "` source pairs."
            )
        else:
            lines.append("- Aggregate preference: withheld until coverage is complete.")
    else:
        expected_presentations = (
            checked_scores["expected_pair_count"] * 2
            if checked_scores is not None
            else 0
        )
        lines.extend(
            [
                "- Public bundle digest: `not supplied`",
                f"- Coverage: `0` / `{expected_presentations}` presentations",
                "- Aggregate preference: withheld until a verified complete review exists.",
            ]
        )

    lines.extend(["", "## Reproducibility", ""])
    if isinstance(manifest, ExperimentManifest):
        lines.extend(
            [
                "- Model / reasoning / runtime: `"
                + _inline(manifest.model)
                + "` / `"
                + _inline(manifest.reasoning)
                + "` / `"
                + _inline(manifest.runtime)
                + "`",
                "- Dataset versions: `"
                + _inline(_canonical_json(manifest.dataset_versions))
                + "`",
                "- Manifest argv (token boundaries preserved; private paths redacted): `"
                + _inline(_canonical_json(list(manifest_argv)))
                + "`",
                f"- Manifest argv SHA-256: `{manifest_argv_sha256}`",
            ]
        )
    else:
        lines.append("- Manifest provenance unavailable.")
    lines.extend(["", "### Canonical source hashes", ""])
    for path, digest in source_hashes:
        lines.append(f"- `{_inline(path)}`: `{digest}`")
    if not source_hashes:
        lines.append("- None.")
    lines.extend(["", "### Tokenized artifact commands", ""])
    for artifact in artifacts:
        lines.append(
            f"- `{_inline(artifact['relative_path'])}`: `"
            + _inline(_canonical_json(list(artifact["argv"])))
            + f"` (exact original argv SHA-256: `{artifact['argv_sha256']}`)"
        )
    if not artifacts:
        lines.append("- None public.")

    lines.extend(["", "## Promotion Files", ""])
    lines.extend(f"- `{_inline(path)}`" for path in promotion)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {_inline(item)}" for item in limitation_rows)
    return "\n".join(lines) + "\n"
