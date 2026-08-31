"""Strict, split-isolated evaluation data and scoring contracts."""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from itertools import combinations
from pathlib import Path
from types import MappingProxyType
from typing import Any, Iterable, Mapping, Sequence


AXES = (
    "request_fulfillment",
    "meaning_and_facts",
    "structure_and_information",
    "style_behavior",
    "over_imitation",
    "resource_use",
)

SPLITS = frozenset({"dev", "golden", "holdout"})

_REQUIRED_FIELDS = frozenset(
    {
        "case_id",
        "target_skill",
        "source_group",
        "generator_brief",
        "axes",
        "risk",
        "deterministic_checks",
    }
)
_OPTIONAL_FIELDS = frozenset({"evaluator_reference"})
_CHECK_KEYS = frozenset(
    {
        "output_present",
        "required_terms",
        "forbidden_terms",
        "min_characters",
        "max_characters",
        "exact_facts",
        "checklist_items",
        "max_source_overlap_characters",
    }
)
_SEQUENCE_CHECKS = frozenset(
    {"required_terms", "forbidden_terms", "exact_facts", "checklist_items"}
)
_INTEGER_CHECKS = frozenset(
    {"min_characters", "max_characters", "max_source_overlap_characters"}
)
_TARGET_SKILL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _has_control_characters(value: str) -> bool:
    return any(unicodedata.category(character).startswith("C") for character in value)


def _required_text(value: object, field: str, *, identifier: bool = False) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    if _has_control_characters(value):
        raise ValueError(f"{field} contains a control character")
    if identifier and (value != value.strip() or any(character.isspace() for character in value)):
        raise ValueError(f"{field} must be a safe identifier")
    return value


def _normalize_text(value: str) -> str:
    """Normalize text for leakage and split comparisons.

    Whitespace and Unicode punctuation are deliberately discarded so cosmetic
    formatting cannot disguise copied evaluation material.
    """

    normalized = unicodedata.normalize("NFKC", value).casefold()
    return "".join(
        character
        for character in normalized
        if not character.isspace()
        and not unicodedata.category(character).startswith("P")
    )


def _strict_json_loads(text: str) -> object:
    def reject_constant(value: str) -> None:
        raise ValueError(f"non-finite JSON constant: {value}")

    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    return json.loads(
        text,
        parse_constant=reject_constant,
        object_pairs_hook=reject_duplicate_keys,
    )


def _normalize_string_sequence(value: object, field: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise TypeError(f"{field} must be a list of strings")
    normalized = tuple(_required_text(item, field) for item in value)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field} contains duplicate values")
    return normalized


def _normalize_checks(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("deterministic_checks must be an object")

    unknown = set(value) - _CHECK_KEYS
    if unknown:
        raise ValueError(f"unknown deterministic check(s): {', '.join(sorted(unknown))}")

    checks: dict[str, object] = {}
    for key, raw_value in value.items():
        if key in _SEQUENCE_CHECKS:
            checks[key] = _normalize_string_sequence(raw_value, key)
        elif key in _INTEGER_CHECKS:
            if isinstance(raw_value, bool) or not isinstance(raw_value, int):
                raise TypeError(f"{key} must be an integer")
            if raw_value < 0:
                raise ValueError(f"{key} must be non-negative")
            checks[key] = raw_value
        elif key == "output_present":
            if not isinstance(raw_value, bool):
                raise TypeError("output_present must be a boolean")
            checks[key] = raw_value

    minimum = checks.get("min_characters")
    maximum = checks.get("max_characters")
    if minimum is not None and maximum is not None and minimum > maximum:
        raise ValueError("invalid character range: min_characters exceeds max_characters")

    return MappingProxyType(checks)


@dataclass(frozen=True, slots=True)
class EvalCase:
    """An immutable evaluation case with evaluator-only material separated."""

    case_id: str
    target_skill: str
    source_group: str
    generator_brief: str
    axes: tuple[str, ...]
    risk: str
    deterministic_checks: Mapping[str, object]
    evaluator_reference: str | None
    split: str

    @classmethod
    def from_dict(cls, data: dict, split: str) -> "EvalCase":
        if not isinstance(data, Mapping):
            raise TypeError("evaluation case must be an object")
        if split not in SPLITS:
            raise ValueError(f"invalid split: {split!r}")

        keys = set(data)
        missing = _REQUIRED_FIELDS - keys
        if missing:
            raise ValueError(f"missing required field(s): {', '.join(sorted(missing))}")
        unknown = keys - _REQUIRED_FIELDS - _OPTIONAL_FIELDS
        if unknown:
            raise ValueError(f"unknown evaluation field(s): {', '.join(sorted(unknown))}")

        case_id = _required_text(data["case_id"], "case_id", identifier=True)
        target_skill = _required_text(
            data["target_skill"], "target_skill", identifier=True
        )
        if not _TARGET_SKILL_RE.fullmatch(target_skill):
            raise ValueError("target_skill must be a safe skill name, not a path")
        source_group = _required_text(data["source_group"], "source_group")
        generator_brief = _required_text(data["generator_brief"], "generator_brief")
        risk = _required_text(data["risk"], "risk")

        raw_axes = data["axes"]
        if not isinstance(raw_axes, (list, tuple)) or not raw_axes:
            raise TypeError("axes must be a non-empty list")
        axes = tuple(raw_axes)
        if not all(isinstance(axis, str) for axis in axes):
            raise TypeError("axes must contain strings")
        if len(set(axes)) != len(axes):
            raise ValueError("axes contains duplicate values")
        unknown_axes = set(axes) - set(AXES)
        if unknown_axes:
            raise ValueError(f"unknown axes: {', '.join(sorted(unknown_axes))}")

        checks = _normalize_checks(data["deterministic_checks"])
        raw_reference = data.get("evaluator_reference")
        evaluator_reference = (
            None
            if raw_reference is None
            else _required_text(raw_reference, "evaluator_reference")
        )
        if "max_source_overlap_characters" in checks and evaluator_reference is None:
            raise ValueError(
                "evaluator_reference is required for max_source_overlap_characters"
            )

        return cls(
            case_id=case_id,
            target_skill=target_skill,
            source_group=source_group,
            generator_brief=generator_brief,
            axes=axes,
            risk=risk,
            deterministic_checks=checks,
            evaluator_reference=evaluator_reference,
            split=split,
        )


def _content_hash(value: str) -> str:
    return hashlib.sha256(_normalize_text(value).encode("utf-8")).hexdigest()


def load_cases(path: Path, split: str) -> list[EvalCase]:
    """Load strict JSONL cases and reject duplicate IDs or generator content."""

    cases: list[EvalCase] = []
    seen_ids: set[str] = set()
    seen_briefs: dict[str, str] = {}

    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ValueError(f"could not read evaluation cases: {path}") from error

    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise ValueError(f"invalid blank JSONL record at line {line_number}")
        try:
            raw = _strict_json_loads(line)
        except (json.JSONDecodeError, ValueError) as error:
            raise ValueError(f"invalid JSON at line {line_number}: {error}") from error
        if not isinstance(raw, dict):
            raise ValueError(f"evaluation record at line {line_number} must be an object")

        try:
            case = EvalCase.from_dict(raw, split)
        except (TypeError, ValueError) as error:
            raise type(error)(f"line {line_number}: {error}") from error

        if case.case_id in seen_ids:
            raise ValueError(f"duplicate case_id at line {line_number}: {case.case_id}")
        brief_hash = _content_hash(case.generator_brief)
        if brief_hash in seen_briefs:
            raise ValueError(
                "duplicate normalized generator_brief at line "
                f"{line_number}: matches {seen_briefs[brief_hash]}"
            )
        seen_ids.add(case.case_id)
        seen_briefs[brief_hash] = case.case_id
        cases.append(case)

    return cases


def _character_ngrams(value: str, size: int = 8) -> set[str]:
    if len(value) < size:
        return set()
    return {value[index : index + size] for index in range(len(value) - size + 1)}


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return len(left & right) / len(left | right)


def validate_split_isolation(
    splits: Mapping[str, Sequence[EvalCase]],
) -> list[str]:
    """Collect all cross-split identity, source, and content leakage errors."""

    errors: list[str] = []
    records: list[tuple[str, EvalCase]] = []
    for split, cases in splits.items():
        for case in cases:
            records.append((split, case))
            if case.split != split:
                errors.append(
                    f"case {case.case_id} records split {case.split!r} but is in {split!r}"
                )

    def report_spanning(field: str) -> None:
        occurrences: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for split, case in records:
            occurrences[getattr(case, field)].append((split, case.case_id))
        for value, locations in occurrences.items():
            distinct_splits = {split for split, _ in locations}
            if len(distinct_splits) > 1:
                if field == "case_id":
                    errors.append(
                        f"duplicate case_id across splits: {value} in "
                        + ", ".join(sorted(distinct_splits))
                    )
                else:
                    errors.append(
                        f"{field} spans splits: {value} in "
                        + ", ".join(sorted(distinct_splits))
                    )

    report_spanning("case_id")
    report_spanning("source_group")

    for field in ("generator_brief", "evaluator_reference"):
        values: list[tuple[str, EvalCase, str]] = []
        for split, case in records:
            raw_value = getattr(case, field)
            if raw_value is not None:
                values.append((split, case, _normalize_text(raw_value)))

        for (left_split, left_case, left), (right_split, right_case, right) in combinations(
            values, 2
        ):
            if left_split == right_split:
                continue
            if left == right:
                errors.append(
                    f"duplicate normalized {field} across splits: "
                    f"{left_case.case_id} ({left_split}) and "
                    f"{right_case.case_id} ({right_split})"
                )

            similarity = _jaccard(_character_ngrams(left), _character_ngrams(right))
            if similarity >= 0.85:
                errors.append(
                    f"8-gram {field} similarity {similarity:.3f} across splits: "
                    f"{left_case.case_id} ({left_split}) and "
                    f"{right_case.case_id} ({right_split})"
                )

    return errors


def _iter_string_values(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for nested in value.values():
            yield from _iter_string_values(nested)
    elif isinstance(value, (list, tuple)):
        for nested in value:
            yield from _iter_string_values(nested)


def validate_holdout_leakage(
    holdout_cases: Sequence[EvalCase], generation_rows: Iterable[dict]
) -> list[str]:
    """Find evaluator-only holdout references embedded in generation records."""

    references = [
        (case.case_id, _normalize_text(case.evaluator_reference))
        for case in holdout_cases
        if case.split == "holdout" and case.evaluator_reference
    ]
    errors: list[str] = []
    for row_number, row in enumerate(generation_rows, start=1):
        normalized_values = [_normalize_text(value) for value in _iter_string_values(row)]
        for case_id, reference in references:
            if reference and any(reference in value for value in normalized_values):
                errors.append(
                    f"row {row_number} leaks evaluator_reference for holdout case {case_id}"
                )
                break
    return errors


def _not_scored() -> dict[str, object]:
    return {"passed": None, "status": "not_scored", "evidence": {}}


def _scored(passed: bool, evidence: dict[str, object]) -> dict[str, object]:
    return {"passed": passed, "status": "scored", "evidence": evidence}


def _longest_common_substring_length(left: str, right: str) -> int:
    if not left or not right:
        return 0
    if len(left) < len(right):
        left, right = right, left

    previous = [0] * (len(right) + 1)
    longest = 0
    for left_character in left:
        current = [0] * (len(right) + 1)
        for index, right_character in enumerate(right, start=1):
            if left_character == right_character:
                current[index] = previous[index - 1] + 1
                longest = max(longest, current[index])
        previous = current
    return longest


def score_deterministic(case: EvalCase, output: str) -> dict[str, dict]:
    """Score only measurable checks without collapsing the six evaluation axes."""

    text = output if isinstance(output, str) else ""
    output_present = bool(text.strip())
    checks = case.deterministic_checks
    scores: dict[str, dict] = {axis: _not_scored() for axis in AXES}

    request_keys = {
        "output_present",
        "required_terms",
        "forbidden_terms",
        "checklist_items",
    }
    if request_keys & checks.keys():
        required_terms = {
            term: output_present and term in text
            for term in checks.get("required_terms", ())
        }
        forbidden_terms = {
            term: output_present and term in text
            for term in checks.get("forbidden_terms", ())
        }
        checklist_items = {
            item: output_present and item in text
            for item in checks.get("checklist_items", ())
        }
        conditions: list[bool] = []
        if "output_present" in checks:
            conditions.append(output_present is checks["output_present"])
        if "required_terms" in checks:
            conditions.append(all(required_terms.values()))
        if "forbidden_terms" in checks:
            conditions.append(not any(forbidden_terms.values()))
        if "checklist_items" in checks:
            conditions.append(all(checklist_items.values()))
        scores["request_fulfillment"] = _scored(
            output_present and all(conditions),
            {
                "output_present": output_present,
                "required_terms": required_terms,
                "forbidden_terms": forbidden_terms,
                "checklist_items": checklist_items,
            },
        )

    if "exact_facts" in checks:
        exact_facts = {
            fact: output_present and fact in text for fact in checks["exact_facts"]
        }
        scores["meaning_and_facts"] = _scored(
            output_present and all(exact_facts.values()),
            {"exact_facts": exact_facts},
        )

    if {"min_characters", "max_characters"} & checks.keys():
        character_count = len(text)
        minimum = checks.get("min_characters")
        maximum = checks.get("max_characters")
        within_minimum = minimum is None or character_count >= minimum
        within_maximum = maximum is None or character_count <= maximum
        evidence = {
            "character_count": character_count,
            "min_characters": minimum,
            "max_characters": maximum,
        }
        scores["structure_and_information"] = _scored(
            output_present and within_minimum and within_maximum,
            evidence,
        )

    if "max_source_overlap_characters" in checks:
        normalized_output = _normalize_text(text)
        normalized_reference = _normalize_text(case.evaluator_reference or "")
        longest = _longest_common_substring_length(
            normalized_output, normalized_reference
        )
        maximum_overlap = checks["max_source_overlap_characters"]
        scores["over_imitation"] = _scored(
            output_present and longest <= maximum_overlap,
            {
                "longest_normalized_source_overlap_characters": longest,
                "max_source_overlap_characters": maximum_overlap,
            },
        )

    return scores


def _nonfinite_paths(value: object, path: str = "row") -> list[str]:
    errors: list[str] = []
    if isinstance(value, float) and not math.isfinite(value):
        errors.append(f"{path} contains a non-finite number")
    elif isinstance(value, Mapping):
        for key, nested in value.items():
            errors.extend(_nonfinite_paths(nested, f"{path}.{key}"))
    elif isinstance(value, (list, tuple)):
        for index, nested in enumerate(value):
            errors.extend(_nonfinite_paths(nested, f"{path}[{index}]"))
    return errors


def validate_external_scores(rows: Iterable[dict]) -> list[str]:
    """Validate judge rows; invalid or incomplete results are never numeric zeros."""

    errors: list[str] = []
    required = {
        "case_id",
        "rubric_version",
        "order",
        "role",
        "status",
        "baseline_length",
        "candidate_length",
        "model",
        "reasoning",
        "raw_output",
        "label_map",
        "axis_results",
        "overall_explanation",
    }
    allowed = required | {"stderr", "validation_errors"}

    for index, row in enumerate(rows):
        prefix = f"row {index + 1}"
        if not isinstance(row, Mapping):
            errors.append(f"{prefix} must be an object")
            continue
        errors.extend(_nonfinite_paths(row, prefix))

        status = row.get("status")
        if status != "valid":
            errors.append(f"{prefix} has invalid external score status: {status!r}")
            continue

        missing = required - set(row)
        if missing:
            errors.append(f"{prefix} missing values: {', '.join(sorted(missing))}")
        unknown = set(row) - allowed
        if unknown:
            errors.append(f"{prefix} has unknown values: {', '.join(sorted(unknown))}")

        for key in ("case_id", "rubric_version", "model", "reasoning", "raw_output"):
            if not isinstance(row.get(key), str) or not row[key].strip():
                errors.append(f"{prefix}.{key} must be a non-empty string")
        if row.get("role") != "supporting_only":
            errors.append(f"{prefix}.role must be supporting_only")
        order = row.get("order")
        if order not in {"AB", "BA"}:
            errors.append(f"{prefix}.order must be AB or BA")
        for key in ("baseline_length", "candidate_length"):
            value = row.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                errors.append(f"{prefix}.{key} must be a non-negative integer")

        expected_label_map = (
            {"A": "baseline", "B": "candidate"}
            if order == "AB"
            else {"A": "candidate", "B": "baseline"}
        )
        if order in {"AB", "BA"} and row.get("label_map") != expected_label_map:
            errors.append(f"{prefix}.label_map does not match order {order}")

        axis_results = row.get("axis_results")
        if not isinstance(axis_results, Mapping):
            errors.append(f"{prefix}.axis_results must be an object")
        else:
            if set(axis_results) != set(AXES):
                errors.append(f"{prefix}.axis_results must contain exactly six axes")
            for axis in AXES:
                result = axis_results.get(axis)
                if not isinstance(result, Mapping):
                    errors.append(f"{prefix}.axis_results.{axis} must be an object")
                    continue
                if set(result) != {"winner", "explanation"}:
                    errors.append(
                        f"{prefix}.axis_results.{axis} must contain winner and explanation"
                    )
                if result.get("winner") not in {"baseline", "candidate", "tie"}:
                    errors.append(f"{prefix}.axis_results.{axis}.winner is invalid")
                explanation = result.get("explanation")
                if not isinstance(explanation, str) or not explanation.strip():
                    errors.append(
                        f"{prefix}.axis_results.{axis}.explanation must be non-empty"
                    )

        overall = row.get("overall_explanation")
        if not isinstance(overall, str) or not overall.strip():
            errors.append(f"{prefix}.overall_explanation must be non-empty")

    return errors


def aggregate_scores(rows: Iterable[dict]) -> dict:
    """Aggregate valid supporting judge rows while exposing order disagreement."""

    materialized = list(rows)
    validation_errors = validate_external_scores(materialized)
    if validation_errors:
        raise ValueError("invalid external score: " + "; ".join(validation_errors))

    axes = {
        axis: {"baseline": 0, "candidate": 0, "tie": 0, "count": 0}
        for axis in AXES
    }
    by_case: dict[str, dict[str, list[dict]]] = defaultdict(
        lambda: {"AB": [], "BA": []}
    )
    for row in materialized:
        by_case[row["case_id"]][row["order"]].append(row)
        for axis in AXES:
            winner = row["axis_results"][axis]["winner"]
            axes[axis][winner] += 1
            axes[axis]["count"] += 1

    disagreement = {
        axis: {"compared_pairs": 0, "disagreements": 0} for axis in AXES
    }
    for orders in by_case.values():
        for ab_row, ba_row in zip(orders["AB"], orders["BA"]):
            for axis in AXES:
                disagreement[axis]["compared_pairs"] += 1
                if (
                    ab_row["axis_results"][axis]["winner"]
                    != ba_row["axis_results"][axis]["winner"]
                ):
                    disagreement[axis]["disagreements"] += 1

    return {
        "role": "supporting_only",
        "row_count": len(materialized),
        "axes": axes,
        "ab_ba_disagreement": disagreement,
    }
