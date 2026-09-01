"""Fail-closed readiness decisions and deterministic approval reports."""

from __future__ import annotations

import hashlib
import html
import json
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import PurePosixPath, PureWindowsPath
from typing import Any

from .blind import MAX_EVIDENCE_CHARACTERS, UNBLINDED_RATING_FIELDS
from .contracts import ExperimentManifest, ExperimentStatus
from .evals import AXES, SPLITS
from .hypothesis import Hypothesis, canonical_relative_path
from .research import normalize_claim
from .static_gate import GateResult


DECISIONS = frozenset(
    {"invalid", "rejected", "awaiting_human", "ready_for_approval"}
)
ONE_PERSON_DISCLAIMER = (
    "이 결과는 사용자 1인의 선호이며, 통계적 우월성을 의미하지 않습니다."
)
MAX_REPORT_EXCERPT_CHARACTERS = 1_000
MAX_DIFF_CHARACTERS = 12_000

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_TARGET_SKILL_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_WINDOWS_ABSOLUTE_RE = re.compile(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]")
_POSIX_ABSOLUTE_RE = re.compile(
    r"(?<![A-Za-z0-9:/])/(?!/)(?:[^/\s<>\"']+/)+[^/\s<>\"']*"
)
_PREFERENCES = frozenset({"candidate", "baseline", "tie"})
_ISSUE_SEVERITIES = frozenset({"none", "minor", "critical"})
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
_AXIS_BUCKET_FIELDS = frozenset({"passed", "failed", "not_scored", "count"})
_FAILURE_FIELDS = frozenset({"case_id", "split", "repeat", "axis"})
_BLIND_SUMMARY_FIELDS = frozenset(
    {"source_pair_count", "presentation_count", "seed", "private_key_digest"}
)
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
    if (
        _WINDOWS_ABSOLUTE_RE.search(value)
        or _POSIX_ABSOLUTE_RE.search(value)
        or "file://" in value.casefold()
    ):
        return True
    for line in value.splitlines():
        stripped = line.strip()
        if stripped.startswith(("--- /", "+++ /")):
            return True
    return False


def _ensure_no_private_mapping(value: object, label: str) -> None:
    if isinstance(value, Mapping):
        forbidden = _PRIVATE_MAPPING_KEYS & set(value)
        if forbidden:
            raise ValueError(f"{label} contains private blind mapping keys: {sorted(forbidden)}")
        for key, nested in value.items():
            _ensure_no_private_mapping(nested, f"{label}.{key}")
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            _ensure_no_private_mapping(nested, f"{label}[{index}]")


def _normalized_claim(claim: object) -> dict:
    if not isinstance(claim, Mapping):
        raise TypeError("research claim must be a mapping")
    data = dict(claim)
    stored_status = data.pop("status", None)
    normalized = normalize_claim(data)
    if stored_status is not None and stored_status != normalized["status"]:
        raise ValueError("research claim status is inconsistent with its evidence")
    for local in normalized["local_evidence"]:
        if _has_absolute_workspace_path(local):
            raise ValueError("research local_evidence must not contain absolute workspace paths")
    return normalized


def research_claim_id(claim: Mapping[str, object]) -> str:
    """Return a stable ID from canonical normalized claim JSON."""

    normalized = _normalized_claim(claim)
    return hashlib.sha256(_canonical_json(normalized).encode("utf-8")).hexdigest()


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
    if set(scores) != _SCORE_FIELDS:
        raise ValueError(
            "scores must use the exact Task 7 aggregate schema; "
            f"missing={sorted(_SCORE_FIELDS - set(scores))}; "
            f"unknown={sorted(set(scores) - _SCORE_FIELDS)}"
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
    }
    return normalized, (
        scores["hard_gates_passed"] is False or scores["golden_passed"] is False
    )


def _validated_rating(row: object, index: int) -> dict:
    label = f"ratings[{index}]"
    if not isinstance(row, Mapping) or set(row) != set(UNBLINDED_RATING_FIELDS):
        raise ValueError(f"{label} must use the exact unblinded rating schema")
    pair_id = _sha256(row["pair_id"], f"{label}.pair_id")
    source_pair_id = _sha256(row["source_pair_id"], f"{label}.source_pair_id")
    case_id = _nonempty_text(row["case_id"], f"{label}.case_id")
    target_skill = _target_skill(row["target_skill"], f"{label}.target_skill")
    repeat = _nonnegative_int(row["repeat"], f"{label}.repeat")
    order = row["order"]
    if order not in {"AB", "BA"}:
        raise ValueError(f"{label}.order must be AB or BA")
    for field in ("quality_preference", "style_preference", "overall_preference"):
        if row[field] not in _PREFERENCES:
            raise ValueError(f"{label}.{field} must be candidate, baseline, or tie")
    for field in ("candidate_over_imitation", "baseline_over_imitation"):
        if type(row[field]) is not bool:
            raise ValueError(f"{label}.{field} must be boolean")
    for field in (
        "candidate_meaning_or_fact_issue",
        "baseline_meaning_or_fact_issue",
    ):
        if row[field] not in _ISSUE_SEVERITIES:
            raise ValueError(f"{label}.{field} has invalid severity")
    evidence = _nonempty_text(row["evidence_excerpt"], f"{label}.evidence_excerpt")
    if len(evidence) > MAX_EVIDENCE_CHARACTERS:
        raise ValueError(
            f"{label}.evidence_excerpt must be at most {MAX_EVIDENCE_CHARACTERS} characters"
        )
    if _has_absolute_workspace_path(evidence):
        raise ValueError(f"{label}.evidence_excerpt must not expose workspace paths")
    return {
        "pair_id": pair_id,
        "source_pair_id": source_pair_id,
        "case_id": case_id,
        "target_skill": target_skill,
        "repeat": repeat,
        "order": order,
        "quality_preference": row["quality_preference"],
        "style_preference": row["style_preference"],
        "overall_preference": row["overall_preference"],
        "candidate_over_imitation": row["candidate_over_imitation"],
        "baseline_over_imitation": row["baseline_over_imitation"],
        "candidate_meaning_or_fact_issue": row[
            "candidate_meaning_or_fact_issue"
        ],
        "baseline_meaning_or_fact_issue": row["baseline_meaning_or_fact_issue"],
        "evidence_excerpt": evidence,
    }


def _validated_ratings(ratings: object, expected_pairs: int) -> tuple[list[dict], bool]:
    rows = _sequence(ratings, "ratings")
    normalized: list[dict] = []
    pair_ids: set[str] = set()
    source_identity: dict[str, tuple[str, str, int]] = {}
    identity_source: dict[tuple[str, str, int], str] = {}
    groups: dict[str, list[dict]] = defaultdict(list)
    for index, raw in enumerate(rows):
        row = _validated_rating(raw, index)
        if row["pair_id"] in pair_ids:
            raise ValueError(f"duplicate rating pair_id: {row['pair_id']}")
        pair_ids.add(row["pair_id"])
        identity = (row["case_id"], row["target_skill"], row["repeat"])
        prior_identity = source_identity.setdefault(row["source_pair_id"], identity)
        if prior_identity != identity:
            raise ValueError("mirrored ratings disagree on source-pair metadata")
        prior_source = identity_source.setdefault(identity, row["source_pair_id"])
        if prior_source != row["source_pair_id"]:
            raise ValueError("one source identity maps to multiple source_pair_ids")
        groups[row["source_pair_id"]].append(row)
        normalized.append(row)

    if len(groups) > expected_pairs or len(rows) > expected_pairs * 2:
        raise ValueError("ratings contain more presentations than expected score pairs")
    for source_pair_id, group in groups.items():
        if len(group) > 2:
            raise ValueError(f"source pair {source_pair_id} has more than two ratings")
        orders = [row["order"] for row in group]
        if len(set(orders)) != len(orders):
            raise ValueError(f"source pair {source_pair_id} repeats an order")
        if len(group) == 2 and set(orders) != {"AB", "BA"}:
            raise ValueError(f"source pair {source_pair_id} must contain AB and BA")
    complete = (
        len(groups) == expected_pairs
        and len(rows) == expected_pairs * 2
        and all(len(group) == 2 for group in groups.values())
    )
    order_rank = {"AB": 0, "BA": 1}
    return sorted(
        normalized,
        key=lambda row: (row["source_pair_id"], order_rank[row["order"]], row["pair_id"]),
    ), complete


def _analyze_readiness(
    manifest: object,
    hypothesis: object,
    gate: object,
    scores: object,
    ratings: object,
) -> tuple[str, dict, list[dict]]:
    _validate_manifest(manifest)
    checked_hypothesis = _validate_hypothesis(hypothesis)
    static_rejected = _gate_rejected(gate)
    checked_scores, aggregate_rejected = _validated_scores(scores)
    expected_pairs = checked_scores["expected_pair_count"]
    checked_ratings, ratings_complete = _validated_ratings(ratings, expected_pairs)

    protected = checked_hypothesis.protected_axes
    candidate_required = {checked_hypothesis.primary_axis, *protected}
    if any(
        checked_scores["axes"][axis]["candidate"]["not_scored"] > 0
        for axis in candidate_required
    ):
        raise ValueError("candidate primary and protected axes must all be scored")
    if static_rejected or aggregate_rejected:
        return "rejected", checked_scores, checked_ratings
    if any(
        checked_scores["axes"][axis]["candidate"]["failed"]
        > checked_scores["axes"][axis]["baseline"]["failed"]
        for axis in protected
    ):
        return "rejected", checked_scores, checked_ratings

    has_candidate_harm = any(
        row["candidate_over_imitation"]
        or row["candidate_meaning_or_fact_issue"] == "critical"
        for row in checked_ratings
    )
    if has_candidate_harm:
        return "rejected", checked_scores, checked_ratings

    human_required = checked_hypothesis.risk != "low" or checked_hypothesis.blind_required
    if not human_required:
        return "ready_for_approval", checked_scores, checked_ratings
    if not ratings_complete:
        return "awaiting_human", checked_scores, checked_ratings

    source_votes = {"candidate": 0, "baseline": 0, "tie": 0}
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in checked_ratings:
        grouped[row["source_pair_id"]].append(row)
    for group in grouped.values():
        votes = [row["overall_preference"] for row in group]
        if votes == ["candidate", "candidate"]:
            source_votes["candidate"] += 1
        elif votes == ["baseline", "baseline"]:
            source_votes["baseline"] += 1
        else:
            source_votes["tie"] += 1
    if (
        source_votes["candidate"] > source_votes["baseline"]
        and source_votes["candidate"] > 0
    ):
        return "ready_for_approval", checked_scores, checked_ratings
    return "rejected", checked_scores, checked_ratings


def decide_readiness(
    manifest: ExperimentManifest,
    hypothesis: Hypothesis,
    gate: GateResult,
    scores: dict,
    ratings: Sequence[dict],
) -> str:
    """Return a pure fail-closed promotion-readiness decision."""

    try:
        decision, _checked_scores, _checked_ratings = _analyze_readiness(
            manifest, hypothesis, gate, scores, ratings
        )
    except (TypeError, ValueError, AttributeError):
        return "invalid"
    return decision


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
        is_absolute = (
            PurePosixPath(token).is_absolute()
            or PureWindowsPath(token).is_absolute()
            or bool(PureWindowsPath(token).drive)
            or _has_absolute_workspace_path(token)
        )
        if not is_absolute:
            normalized.append(token)
            continue
        if index > 0 and parts[index - 1] == "--cd":
            normalized.append(".")
            continue
        raise ValueError(
            f"{label}[{index}] must not contain an absolute workspace path"
        )
    digest = hashlib.sha256(_canonical_json(original).encode("utf-8")).hexdigest()
    return tuple(normalized), digest


def _validated_raw_artifacts(raw_artifacts: object) -> list[dict]:
    rows = _sequence(raw_artifacts, "raw_artifacts", allow_empty=False)
    normalized: list[dict] = []
    seen_paths: set[str] = set()
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping) or set(raw) != _RAW_ARTIFACT_FIELDS:
            raise ValueError(f"raw_artifacts[{index}] has invalid schema")
        path = _safe_relative_path(raw["relative_path"], "raw artifact relative_path")
        if path in seen_paths:
            raise ValueError(f"duplicate raw artifact path: {path}")
        seen_paths.add(path)
        argv, argv_sha256 = _argv(raw["argv"], "raw artifact argv")
        normalized.append(
            {
                "relative_path": path,
                "sha256": _sha256(raw["sha256"], "raw artifact sha256"),
                "argv": argv,
                "argv_sha256": argv_sha256,
            }
        )
    return sorted(normalized, key=lambda row: row["relative_path"])


def _validated_blind_summary(
    blind_summary: object, *, expected_pairs: int, human_required: bool
) -> dict:
    if not isinstance(blind_summary, Mapping) or set(blind_summary) != _BLIND_SUMMARY_FIELDS:
        raise ValueError("blind_summary must contain counts, seed, and private-key digest only")
    source_pairs = _nonnegative_int(
        blind_summary["source_pair_count"], "blind_summary.source_pair_count"
    )
    presentations = _nonnegative_int(
        blind_summary["presentation_count"], "blind_summary.presentation_count"
    )
    seed = blind_summary["seed"]
    if type(seed) is not int:
        raise ValueError("blind_summary.seed must be an integer")
    digest = _sha256(
        blind_summary["private_key_digest"], "blind_summary.private_key_digest"
    )
    if presentations != source_pairs * 2:
        raise ValueError("blind_summary must record two presentations per source pair")
    if human_required and source_pairs != expected_pairs:
        raise ValueError("blind_summary source count must match expected score pairs")
    if not human_required and source_pairs not in {0, expected_pairs}:
        raise ValueError("optional blind_summary must be empty or cover all score pairs")
    return {
        "source_pair_count": source_pairs,
        "presentation_count": presentations,
        "seed": seed,
        "private_key_digest": digest,
    }


def _text_items(value: object, label: str, *, allow_empty: bool) -> list[str]:
    rows = _sequence(value, label, allow_empty=allow_empty)
    normalized: list[str] = []
    for index, item in enumerate(rows):
        text = _nonempty_text(item, f"{label}[{index}]")
        if _has_absolute_workspace_path(text):
            raise ValueError(f"{label}[{index}] must not expose an absolute workspace path")
        normalized.append(text)
    return normalized


def _regression_items(value: object) -> list[str]:
    rows = _sequence(value, "regressions")
    normalized: list[str] = []
    for index, item in enumerate(rows):
        _ensure_no_private_mapping(item, f"regressions[{index}]")
        if isinstance(item, str):
            text = _nonempty_text(item, f"regressions[{index}]")
        elif isinstance(item, Mapping):
            text = _canonical_json(item)
        else:
            raise TypeError("regressions entries must be text or JSON mappings")
        if _has_absolute_workspace_path(text):
            raise ValueError("regressions must not expose absolute workspace paths")
        normalized.append(text)
    return sorted(normalized)


def _excerpt(value: str, limit: int = MAX_REPORT_EXCERPT_CHARACTERS) -> str:
    bounded = value if len(value) <= limit else value[:limit] + "… [truncated]"
    return html.escape(bounded, quote=True)


def _inline(value: object) -> str:
    return _excerpt(str(value)).replace("|", "&#124;").replace("\r\n", "<br>").replace(
        "\n", "<br>"
    )


def build_report(
    *,
    manifest: ExperimentManifest,
    hypothesis: Hypothesis,
    gate: GateResult,
    scores: dict,
    ratings: Sequence[dict],
    research_claims: Sequence[Mapping[str, object]],
    one_change_diff: str,
    raw_artifacts: Sequence[Mapping[str, object]],
    regressions: Sequence[object],
    blind_summary: Mapping[str, object],
    promotion_files: Sequence[str],
    limitations: Sequence[str],
    decision: str,
) -> str:
    """Return one deterministic, escaped report; never read or write hidden state."""

    if decision not in DECISIONS:
        raise ValueError("decision must be a readiness decision")
    expected_decision, checked_scores, checked_ratings = _analyze_readiness(
        manifest, hypothesis, gate, scores, ratings
    )
    if decision != expected_decision:
        raise ValueError(
            f"decision does not match validated readiness: {decision} != {expected_decision}"
        )
    checked_manifest = _validate_manifest(manifest)
    checked_hypothesis = _validate_hypothesis(hypothesis)
    claims = _sequence(research_claims, "research_claims", allow_empty=False)
    normalized_claims: dict[str, dict] = {}
    for claim in claims:
        normalized = _normalized_claim(claim)
        claim_id = research_claim_id(normalized)
        if claim_id in normalized_claims:
            raise ValueError(f"duplicate research claim: {claim_id}")
        normalized_claims[claim_id] = normalized
    unresolved = set(checked_hypothesis.claim_ids) - set(normalized_claims)
    if unresolved:
        raise ValueError(f"hypothesis claim IDs do not resolve: {sorted(unresolved)}")

    diff = _nonempty_text(one_change_diff, "one_change_diff")
    if _has_absolute_workspace_path(diff):
        raise ValueError("one_change_diff must not expose absolute workspace paths")
    artifacts = _validated_raw_artifacts(raw_artifacts)
    regression_rows = _regression_items(regressions)
    human_required = checked_hypothesis.risk != "low" or checked_hypothesis.blind_required
    summary = _validated_blind_summary(
        blind_summary,
        expected_pairs=checked_scores["expected_pair_count"],
        human_required=human_required,
    )
    promotion = sorted(
        set(_text_items(promotion_files, "promotion_files", allow_empty=False))
    )
    promotion = [
        _safe_relative_path(path, "promotion_files path") for path in promotion
    ]
    limitation_rows = _text_items(limitations, "limitations", allow_empty=False)
    static_errors = _text_items(gate.errors, "gate.errors", allow_empty=True)
    _ensure_no_private_mapping(blind_summary, "blind_summary")
    _ensure_no_private_mapping(checked_ratings, "ratings")

    source_hashes = []
    for path, digest in sorted(checked_manifest.source_hashes.items()):
        source_hashes.append(
            (
                _safe_relative_path(path, "manifest source hash path"),
                _sha256(digest, "manifest source hash"),
            )
        )
    manifest_argv, manifest_argv_sha256 = _argv(
        checked_manifest.command, "manifest.command"
    )

    lines: list[str] = [
        "# Decision",
        "",
        f"- Decision: `{decision}`",
        f"- Static gate passed: `{str(gate.passed).lower()}`",
        f"- Experiment: `{_inline(checked_manifest.experiment_id)}`",
        "",
        "## Hypothesis",
        "",
        f"- Change group: `{_inline(checked_hypothesis.change_group)}`",
        f"- Risk: `{_inline(checked_hypothesis.risk)}`",
        f"- Blind required: `{str(checked_hypothesis.blind_required).lower()}`",
        f"- Primary axis: `{_inline(checked_hypothesis.primary_axis)}`",
        "- Protected axes: "
        + ", ".join(f"`{_inline(axis)}`" for axis in checked_hypothesis.protected_axes),
        "- Allowed paths: "
        + ", ".join(f"`{_inline(path)}`" for path in checked_hypothesis.allowed_paths),
        f"- Stop rule: {_inline(checked_hypothesis.stop_rule)}",
        "",
        _excerpt(checked_hypothesis.body),
        "",
        "## Research Claims and Local Evidence",
        "",
    ]
    for claim_id in sorted(normalized_claims):
        claim = normalized_claims[claim_id]
        lines.extend(
            [
                f"### `{claim_id}`",
                "",
                f"- Claim: {_inline(claim['claim'])}",
                f"- Source: [{_inline(claim['source_url'])}]({_inline(claim['source_url'])})",
                f"- Source date / checked: `{_inline(claim['source_date'])}` / `{_inline(claim['checked_at'])}`",
                f"- Type / confidence / status: `{_inline(claim['source_type'])}` / `{_inline(claim['confidence'])}` / `{_inline(claim['status'])}`",
                f"- Evidence: {_inline(claim['evidence'])}",
                "- Local evidence: "
                + ", ".join(f"`{_inline(item)}`" for item in claim["local_evidence"]),
                f"- Decision impact: {_inline(claim['decision_impact'])}",
                f"- Proposed test: {_inline(claim['proposed_test'])}",
                "",
            ]
        )

    lines.extend(
        [
            "## One-Change Diff",
            "",
            "<pre>",
            _excerpt(diff, MAX_DIFF_CHARACTERS),
            "</pre>",
            "",
            "## Artifact Paths",
            "",
            "| Relative path | SHA-256 |",
            "|---|---|",
        ]
    )
    for artifact in artifacts:
        lines.append(
            f"| `{_inline(artifact['relative_path'])}` | `{artifact['sha256']}` |"
        )

    lines.extend(
        [
            "",
            "## Per-Axis Results",
            "",
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
            "",
            "### Static Gate Failures",
            "",
        ]
    )
    if static_errors:
        lines.extend(f"- {_inline(error)}" for error in static_errors)
    else:
        lines.append("- None.")
    for heading, failures in (
        ("Hard Gate Failures", checked_scores["hard_gate_failures"]),
        ("Golden Failures", checked_scores["golden_failures"]),
    ):
        lines.extend(["", f"### {heading}", ""])
        if failures:
            lines.extend(
                "- "
                f"case `{_inline(failure['case_id'])}`, "
                f"split `{failure['split']}`, repeat `{failure['repeat']}`, "
                f"axis `{failure['axis']}`"
                for failure in failures
            )
        else:
            lines.append("- None.")
    lines.extend(
        [
            "",
            "## Regressions",
            "",
        ]
    )
    if regression_rows:
        lines.extend(f"- {_inline(item)}" for item in regression_rows)
    else:
        lines.append("- None reported.")

    lines.extend(
        [
            "",
            "## Human Ratings",
            "",
            ONE_PERSON_DISCLAIMER,
            "",
            f"- Blind source pairs / presentations: `{summary['source_pair_count']}` / `{summary['presentation_count']}`",
            f"- Blind seed: `{summary['seed']}`",
            f"- Private-key digest: `{summary['private_key_digest']}`",
            "",
        ]
    )
    if checked_ratings:
        lines.extend(
            [
                "| Source pair | Order | Quality | Style | Overall | Candidate over-imitation | Candidate meaning/fact issue | Evidence excerpt |",
                "|---|---|---|---|---|---|---|---|",
            ]
        )
        for rating in checked_ratings:
            lines.append(
                f"| `{rating['source_pair_id']}` | `{rating['order']}` | `{rating['quality_preference']}` | "
                f"`{rating['style_preference']}` | `{rating['overall_preference']}` | "
                f"`{str(rating['candidate_over_imitation']).lower()}` | "
                f"`{rating['candidate_meaning_or_fact_issue']}` | {_inline(rating['evidence_excerpt'])} |"
            )
    else:
        lines.append("- No human ratings supplied.")

    lines.extend(
        [
            "",
            "## Reproducibility",
            "",
            f"- Model / reasoning / runtime: `{_inline(checked_manifest.model)}` / `{_inline(checked_manifest.reasoning)}` / `{_inline(checked_manifest.runtime)}`",
            "- Dataset versions: `" + _inline(_canonical_json(checked_manifest.dataset_versions)) + "`",
            "- Manifest argv (portable; absolute `--cd` roots normalized to `.`): `"
            + _inline(_canonical_json(list(manifest_argv)))
            + "`",
            f"- Manifest argv SHA-256: `{manifest_argv_sha256}`",
            "",
            "### Canonical source hashes",
            "",
        ]
    )
    for path, digest in source_hashes:
        lines.append(f"- `{_inline(path)}`: `{digest}`")
    lines.extend(["", "### Tokenized artifact commands", ""])
    for artifact in artifacts:
        lines.append(
            f"- `{_inline(artifact['relative_path'])}`: `"
            + _inline(_canonical_json(list(artifact["argv"])))
            + f"` (exact argv SHA-256: `{artifact['argv_sha256']}`)"
        )

    lines.extend(["", "## Promotion Files", ""])
    lines.extend(f"- `{_inline(path)}`" for path in promotion)
    lines.extend(["", "## Limitations", ""])
    lines.extend(f"- {_inline(item)}" for item in limitation_rows)
    return "\n".join(lines) + "\n"
