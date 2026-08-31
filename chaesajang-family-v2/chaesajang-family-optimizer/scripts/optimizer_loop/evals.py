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
MIN_PARTIAL_LEAK_CHARACTERS = 16
# Exact shortest-common-superstring DP is exponential after containment pruning.
MAX_SCS_LITERALS = 12
GENERATOR_VISIBLE_FIELDS = frozenset(
    {
        "prompt",
        "input",
        "loaded_references",
        "loaded_reference_paths",
        "loaded_reference_content",
        "reference_material",
        "reference_materials",
        "reference_text",
        "references",
        "research_card",
        "research_cards",
    }
)

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
_TARGET_SKILL_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_CASE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_CHECK_AXES = {
    "output_present": "request_fulfillment",
    "required_terms": "request_fulfillment",
    "forbidden_terms": "request_fulfillment",
    "checklist_items": "request_fulfillment",
    "exact_facts": "meaning_and_facts",
    "min_characters": "structure_and_information",
    "max_characters": "structure_and_information",
    "max_source_overlap_characters": "over_imitation",
}
_GENERATION_PARITY_FIELDS = (
    "case_id",
    "target_skill",
    "repeat",
    "model",
    "reasoning",
    "runtime",
    "input",
    "prompt",
)


def _has_control_characters(value: str, *, allow_narrative_layout: bool) -> bool:
    allowed = {"\t", "\n", "\r"} if allow_narrative_layout else set()
    return any(
        character not in allowed
        and unicodedata.category(character).startswith("C")
        for character in value
    )


def _required_text(
    value: object,
    field: str,
    *,
    identifier: bool = False,
    narrative: bool = False,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    if _has_control_characters(value, allow_narrative_layout=narrative):
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


def _shortest_common_superstring_length(values: Iterable[str]) -> int:
    """Return the exact minimum length of text containing every literal."""

    unique = list(dict.fromkeys(values))
    literals = [
        value
        for index, value in enumerate(unique)
        if not any(
            index != other_index and value in other
            for other_index, other in enumerate(unique)
        )
    ]
    if len(literals) > MAX_SCS_LITERALS:
        raise ValueError(
            "shortest common superstring accepts at most "
            f"{MAX_SCS_LITERALS} non-contained required literals"
        )
    if not literals:
        return 0
    if len(literals) == 1:
        return len(literals[0])

    count = len(literals)
    overlaps = [[0] * count for _ in range(count)]
    for left_index, left in enumerate(literals):
        for right_index, right in enumerate(literals):
            if left_index == right_index:
                continue
            maximum = min(len(left), len(right))
            overlaps[left_index][right_index] = max(
                (
                    size
                    for size in range(1, maximum + 1)
                    if left.endswith(right[:size])
                ),
                default=0,
            )

    full_mask = (1 << count) - 1
    infinity = sum(len(literal) for literal in literals) + 1
    lengths = [[infinity] * count for _ in range(full_mask + 1)]
    for index, literal in enumerate(literals):
        lengths[1 << index][index] = len(literal)

    for mask in range(1, full_mask + 1):
        for last in range(count):
            current = lengths[mask][last]
            if current == infinity:
                continue
            for following in range(count):
                bit = 1 << following
                if mask & bit:
                    continue
                candidate = (
                    current
                    + len(literals[following])
                    - overlaps[last][following]
                )
                next_mask = mask | bit
                if candidate < lengths[next_mask][following]:
                    lengths[next_mask][following] = candidate

    return min(lengths[full_mask])


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
    if not value:
        raise ValueError(f"{field} must not be empty")
    normalized = tuple(_required_text(item, field) for item in value)
    comparison_values = tuple(_normalize_text(item) for item in normalized)
    if any(not item for item in comparison_values):
        raise ValueError(f"{field} values must contain normalized text")
    if len(set(comparison_values)) != len(comparison_values):
        raise ValueError(f"{field} contains duplicate values")
    return normalized


def _normalize_checks(value: object) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise TypeError("deterministic_checks must be an object")

    unknown = set(value) - _CHECK_KEYS
    if unknown:
        raise ValueError(f"unknown deterministic check(s): {', '.join(sorted(unknown))}")
    if not value:
        raise ValueError("deterministic_checks must not be empty")

    checks: dict[str, object] = {}
    for key, raw_value in value.items():
        if key in _SEQUENCE_CHECKS:
            checks[key] = _normalize_string_sequence(raw_value, key)
        elif key in _INTEGER_CHECKS:
            if isinstance(raw_value, bool) or not isinstance(raw_value, int):
                raise TypeError(f"{key} must be an integer")
            if raw_value <= 0:
                raise ValueError(f"{key} must be a positive non-vacuous threshold")
            checks[key] = raw_value
        elif key == "output_present":
            if raw_value is not True:
                raise ValueError("output_present must be exactly true")
            checks[key] = True

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
        if _CASE_ID_RE.fullmatch(case_id) is None or case_id in {".", ".."}:
            raise ValueError("case_id must be a safe non-path identifier")
        target_skill = _required_text(
            data["target_skill"], "target_skill", identifier=True
        )
        if not 1 <= len(target_skill) <= 64 or not _TARGET_SKILL_RE.fullmatch(
            target_skill
        ):
            raise ValueError(
                "target_skill must be 1..64 lowercase alphanumeric characters "
                "in single-hyphen-separated segments"
            )
        source_group = _required_text(data["source_group"], "source_group")
        generator_brief = _required_text(
            data["generator_brief"], "generator_brief", narrative=True
        )
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
            else _required_text(
                raw_reference, "evaluator_reference", narrative=True
            )
        )
        if "max_source_overlap_characters" in checks and evaluator_reference is None:
            raise ValueError(
                "evaluator_reference is required for max_source_overlap_characters"
            )
        if evaluator_reference is not None and "max_source_overlap_characters" in checks:
            normalized_reference_length = len(_normalize_text(evaluator_reference))
            if checks["max_source_overlap_characters"] >= normalized_reference_length:
                raise ValueError(
                    "max_source_overlap_characters must be below the normalized "
                    "evaluator_reference length to avoid a vacuous overlap gate"
                )

        for check in checks:
            required_axis = _CHECK_AXES[check]
            if required_axis not in axes:
                raise ValueError(
                    f"deterministic check {check} requires axis {required_axis}"
                )

        forbidden = {
            _normalize_text(term) for term in checks.get("forbidden_terms", ())
        }
        positive_literals = tuple(
            term
            for key in ("required_terms", "exact_facts", "checklist_items")
            for term in checks.get(key, ())
        )
        positive = {_normalize_text(term) for term in positive_literals}
        contradictions = {
            (positive_term, forbidden_term)
            for positive_term in positive
            for forbidden_term in forbidden
            if forbidden_term in positive_term
        }
        if contradictions:
            raise ValueError(
                "deterministic check contradiction: a normalized positive "
                "literal contains a forbidden term"
            )
        maximum_characters = checks.get("max_characters")
        if maximum_characters is not None:
            required_superstring_length = _shortest_common_superstring_length(
                positive_literals
            )
            if required_superstring_length > maximum_characters:
                raise ValueError(
                    "max_characters creates an impossible required-literal "
                    f"superstring length ({required_superstring_length})"
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


def _edit_similarity(left: str, right: str) -> float:
    """Return deterministic normalized Levenshtein similarity."""

    if left == right:
        return 1.0
    if not left or not right:
        return 0.0
    previous = list(range(len(right) + 1))
    for left_index, left_character in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_character in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1]
                    + (left_character != right_character),
                )
            )
        previous = current
    return 1.0 - previous[-1] / max(len(left), len(right))


def validate_split_isolation(
    splits: Mapping[str, Sequence[EvalCase]],
) -> list[str]:
    """Collect dataset duplicates and cross-split source/content leakage errors."""

    errors: list[str] = []
    records: list[tuple[str, EvalCase]] = []
    for split, cases in splits.items():
        if split not in SPLITS:
            errors.append(f"unknown split key: {split!r}")
        for case in cases:
            records.append((split, case))
            if case.split != split:
                errors.append(
                    f"case {case.case_id} records split {case.split!r} but is in {split!r}"
                )

    def report_duplicates(field: str) -> None:
        occurrences: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for split, case in records:
            occurrences[getattr(case, field)].append((split, case.case_id))
        for value, locations in occurrences.items():
            if len(locations) > 1:
                errors.append(
                    f"duplicate {field} in dataset: {value} at "
                    + ", ".join(f"{split}/{case_id}" for split, case_id in locations)
                )

    report_duplicates("case_id")

    source_occurrences: dict[str, set[str]] = defaultdict(set)
    for split, case in records:
        source_occurrences[case.source_group].add(split)
    for source_group, source_splits in source_occurrences.items():
        if len(source_splits) > 1:
            errors.append(
                f"source_group spans splits: {source_group} in "
                + ", ".join(sorted(source_splits))
            )

    for field in ("generator_brief", "evaluator_reference"):
        values: list[tuple[str, EvalCase, str]] = []
        for split, case in records:
            raw_value = getattr(case, field)
            if raw_value is not None:
                values.append((split, case, _normalize_text(raw_value)))

        for (left_split, left_case, left), (right_split, right_case, right) in combinations(
            values, 2
        ):
            if left == right:
                errors.append(
                    f"duplicate normalized {field} in dataset: "
                    f"{left_case.case_id} ({left_split}) and "
                    f"{right_case.case_id} ({right_split})"
                )
            if left_split == right_split:
                continue

            left_ngrams = _character_ngrams(left)
            right_ngrams = _character_ngrams(right)
            similarity = _jaccard(left_ngrams, right_ngrams)
            if left_ngrams and right_ngrams and similarity >= 0.85:
                errors.append(
                    f"8-gram {field} similarity {similarity:.3f} in dataset: "
                    f"{left_case.case_id} ({left_split}) and "
                    f"{right_case.case_id} ({right_split})"
                )
            elif min(len(left), len(right)) >= 4 and (
                not left_ngrams or not right_ngrams
            ):
                short_similarity = _edit_similarity(left, right)
                if short_similarity >= 0.85:
                    errors.append(
                        f"short-text {field} similarity {short_similarity:.3f} in dataset: "
                        f"{left_case.case_id} ({left_split}) and "
                        f"{right_case.case_id} ({right_split})"
                    )

    return errors


def validate_case_targets(cases: Iterable[EvalCase], registry: object) -> list[str]:
    """Validate that every case targets a skill declared by a family registry."""

    skills = getattr(registry, "skills", None)
    if not isinstance(skills, (list, tuple)):
        raise TypeError("registry must expose a skills sequence")
    names: set[str] = set()
    for skill in skills:
        name = getattr(skill, "name", None)
        if not isinstance(name, str) or not name:
            raise TypeError("registry skills must expose non-empty names")
        names.add(name)

    errors: list[str] = []
    for case in cases:
        if not isinstance(case, EvalCase):
            raise TypeError("cases must contain EvalCase values")
        if case.target_skill not in names:
            errors.append(
                f"case {case.case_id} target_skill is not in family registry: "
                f"{case.target_skill}"
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


def _maximum_reference_window_jaccard(reference: str, visible: str) -> float:
    reference_ngrams = _character_ngrams(reference)
    if not reference_ngrams or len(visible) < 8:
        return 0.0
    if len(visible) <= len(reference):
        return _jaccard(reference_ngrams, _character_ngrams(visible))

    window_size = len(reference)
    return max(
        _jaccard(
            reference_ngrams,
            _character_ngrams(visible[start : start + window_size]),
        )
        for start in range(len(visible) - window_size + 1)
    )


def validate_holdout_leakage(
    holdout_cases: Sequence[EvalCase], generation_rows: Iterable[dict]
) -> list[str]:
    """Scan only explicitly generator-visible fields for holdout reference leaks."""

    references = [
        (case.case_id, _normalize_text(case.evaluator_reference))
        for case in holdout_cases
        if case.split == "holdout" and case.evaluator_reference
    ]
    errors: list[str] = []
    for row_number, row in enumerate(generation_rows, start=1):
        if not isinstance(row, Mapping):
            errors.append(f"row {row_number} must be a generation mapping")
            continue
        visible_values = [
            (field, _normalize_text(value))
            for field in GENERATOR_VISIBLE_FIELDS
            if field in row
            for value in _iter_string_values(row[field])
        ]
        for case_id, reference in references:
            if not reference:
                continue
            finding: tuple[str, str] | None = None
            for field, visible in visible_values:
                if reference in visible:
                    finding = (field, "full normalized")
                    break
                similarity = _maximum_reference_window_jaccard(reference, visible)
                if similarity >= 0.85:
                    finding = (field, f"8-gram similarity {similarity:.3f}")
                    break
                longest = _longest_common_substring_length(reference, visible)
                if longest >= MIN_PARTIAL_LEAK_CHARACTERS:
                    finding = (
                        field,
                        f"partial contiguous excerpt of {longest} normalized characters",
                    )
                    break
            if finding is not None:
                field, reason = finding
                errors.append(
                    f"row {row_number} {field} leaks evaluator_reference for holdout "
                    f"case {case_id}: {reason}"
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


def _stable_hash(value: Mapping[str, object]) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_generation_row(
    case: EvalCase, row: Mapping[str, object], label: str = "generation"
) -> None:
    """Validate one completed, source-stable generation record."""

    if not isinstance(row, Mapping):
        raise TypeError(f"{label} row must be a mapping")
    if row.get("status") != "completed":
        raise ValueError(f"{label} status must be completed")
    if row.get("source_stable") is not True:
        raise ValueError(f"{label} source must be stable")
    if row.get("case_id") != case.case_id:
        raise ValueError(f"{label} case_id must match EvalCase")
    if row.get("target_skill") != case.target_skill:
        raise ValueError(f"{label} target_skill must match EvalCase")

    repeat = row.get("repeat")
    if isinstance(repeat, bool) or not isinstance(repeat, int) or repeat < 0:
        raise ValueError(f"{label} repeat must be a non-negative integer")
    if row.get("input") != case.generator_brief:
        raise ValueError(f"{label} input must match EvalCase generator_brief")
    for field in ("prompt", "output", "stderr", "cwd", "model", "reasoning", "runtime"):
        value = row.get(field)
        if not isinstance(value, str):
            raise TypeError(f"{label} {field} must be a string")
        if field not in {"stderr"} and not value.strip():
            raise ValueError(f"{label} {field} must be non-empty")

    command = row.get("command")
    if not isinstance(command, (list, tuple)) or not command or not all(
        isinstance(part, str) and part for part in command
    ):
        raise ValueError(f"{label} command must be a non-empty string sequence")
    timeout_seconds = row.get("timeout_seconds")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or timeout_seconds <= 0
    ):
        raise ValueError(f"{label} timeout_seconds must be a positive integer")
    elapsed_ms = row.get("elapsed_ms")
    if isinstance(elapsed_ms, bool) or not isinstance(elapsed_ms, int) or elapsed_ms < 0:
        raise ValueError(f"{label} elapsed_ms must be a non-negative integer")
    returncode = row.get("returncode")
    if isinstance(returncode, bool) or not isinstance(returncode, int) or returncode != 0:
        raise ValueError(f"{label} returncode must be zero")


def generation_parity_signature(case: EvalCase, row: Mapping[str, object]) -> str:
    validate_generation_row(case, row)
    return _stable_hash({field: row[field] for field in _GENERATION_PARITY_FIELDS})


def _pair_id_from_fields(
    case_id: str,
    target_skill: str,
    split: str,
    repeat: int,
    parity_signature: str,
) -> str:
    return _stable_hash(
        {
            "case_id": case_id,
            "target_skill": target_skill,
            "split": split,
            "repeat": repeat,
            "parity_signature": parity_signature,
        }
    )


def generation_pair_id(
    case: EvalCase, repeat: int, parity_signature: str
) -> str:
    if isinstance(repeat, bool) or not isinstance(repeat, int) or repeat < 0:
        raise ValueError("repeat must be a non-negative integer")
    if not isinstance(parity_signature, str) or _SHA256_RE.fullmatch(
        parity_signature
    ) is None:
        raise ValueError("parity_signature must be a SHA-256 hex digest")
    return _pair_id_from_fields(
        case.case_id,
        case.target_skill,
        case.split,
        repeat,
        parity_signature,
    )


def make_deterministic_row(
    case: EvalCase, generation_row: Mapping[str, object], condition: str
) -> dict:
    """Create one typed deterministic gate row from an auditable generation row."""

    if condition not in {"baseline", "candidate"}:
        raise ValueError("condition must be baseline or candidate")
    validate_generation_row(case, generation_row, condition)
    parity_signature = generation_parity_signature(case, generation_row)
    repeat = generation_row["repeat"]
    return {
        "row_type": "deterministic",
        "case_id": case.case_id,
        "target_skill": case.target_skill,
        "split": case.split,
        "condition": condition,
        "repeat": repeat,
        "pair_id": generation_pair_id(case, repeat, parity_signature),
        "parity_signature": parity_signature,
        "scores": score_deterministic(case, generation_row["output"]),
    }


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
    common_required = {
        "row_type",
        "case_id",
        "target_skill",
        "split",
        "repeat",
        "pair_id",
        "parity_signature",
        "rubric_version",
        "order",
        "role",
        "status",
        "baseline_length",
        "candidate_length",
        "model",
        "reasoning",
        "runtime",
        "command",
        "cwd",
        "timeout_seconds",
        "returncode",
        "elapsed_ms",
        "prompt_sha256",
        "raw_output",
        "stderr",
        "label_map",
    }
    valid_required = {
        "axis_results",
        "overall_explanation",
    }
    allowed = common_required | valid_required | {"validation_errors"}

    for index, row in enumerate(rows):
        prefix = f"row {index + 1}"
        if not isinstance(row, Mapping):
            errors.append(f"{prefix} must be an object")
            continue
        errors.extend(_nonfinite_paths(row, prefix))

        status = row.get("status")
        required = common_required | (valid_required if status == "valid" else set())
        missing = required - set(row)
        if missing:
            errors.append(f"{prefix} missing values: {', '.join(sorted(missing))}")
        unknown = set(row) - allowed
        if unknown:
            errors.append(f"{prefix} has unknown values: {', '.join(sorted(unknown))}")

        for key in (
            "case_id",
            "target_skill",
            "rubric_version",
            "model",
            "reasoning",
            "runtime",
            "cwd",
        ):
            if not isinstance(row.get(key), str) or not row[key].strip():
                errors.append(f"{prefix}.{key} must be a non-empty string")
        if row.get("row_type") != "judge":
            errors.append(f"{prefix}.row_type must be judge")
        if row.get("split") not in SPLITS:
            errors.append(f"{prefix}.split is invalid")
        for key in ("repeat", "baseline_length", "candidate_length", "elapsed_ms"):
            value = row.get(key)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                errors.append(f"{prefix}.{key} must be a non-negative integer")
        timeout = row.get("timeout_seconds")
        if isinstance(timeout, bool) or not isinstance(timeout, int) or timeout <= 0:
            errors.append(f"{prefix}.timeout_seconds must be a positive integer")
        returncode = row.get("returncode")
        if returncode is not None and (
            isinstance(returncode, bool) or not isinstance(returncode, int)
        ):
            errors.append(f"{prefix}.returncode must be an integer or null")
        if status == "valid" and returncode != 0:
            errors.append(f"{prefix}.returncode must be zero for a valid row")
        command = row.get("command")
        if not isinstance(command, (list, tuple)) or not command or not all(
            isinstance(part, str) and part for part in command
        ):
            errors.append(f"{prefix}.command must be a non-empty string sequence")
        if not isinstance(row.get("stderr"), str):
            errors.append(f"{prefix}.stderr must be a string")
        if not isinstance(row.get("raw_output"), str):
            errors.append(f"{prefix}.raw_output must be a string")
        elif status == "valid" and not row["raw_output"].strip():
            errors.append(f"{prefix}.raw_output must be non-empty for a valid row")
        for key in ("pair_id", "parity_signature", "prompt_sha256"):
            value = row.get(key)
            if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
                errors.append(f"{prefix}.{key} must be a SHA-256 hex digest")
        if (
            isinstance(row.get("case_id"), str)
            and isinstance(row.get("target_skill"), str)
            and row.get("split") in SPLITS
            and isinstance(row.get("repeat"), int)
            and not isinstance(row.get("repeat"), bool)
            and isinstance(row.get("parity_signature"), str)
            and _SHA256_RE.fullmatch(row["parity_signature"]) is not None
            and isinstance(row.get("pair_id"), str)
            and row["pair_id"]
            != _pair_id_from_fields(
                row["case_id"],
                row["target_skill"],
                row["split"],
                row["repeat"],
                row["parity_signature"],
            )
        ):
            errors.append(f"{prefix}.pair_id does not match pair identity")
        if row.get("runtime") != "codex":
            errors.append(f"{prefix}.runtime must be codex")
        if row.get("role") != "supporting_only":
            errors.append(f"{prefix}.role must be supporting_only")
        order = row.get("order")
        if order not in {"AB", "BA"}:
            errors.append(f"{prefix}.order must be AB or BA")

        expected_label_map = (
            {"A": "baseline", "B": "candidate"}
            if order == "AB"
            else {"A": "candidate", "B": "baseline"}
        )
        if order in {"AB", "BA"} and row.get("label_map") != expected_label_map:
            errors.append(f"{prefix}.label_map does not match order {order}")

        if "validation_errors" in row:
            validation_errors = row["validation_errors"]
            if status == "valid":
                errors.append(f"{prefix}.validation_errors is forbidden on valid rows")
            if not isinstance(validation_errors, list) or not validation_errors or not all(
                isinstance(error, str) and error.strip() for error in validation_errors
            ):
                errors.append(
                    f"{prefix}.validation_errors must be a non-empty string list"
                )

        if status != "valid":
            errors.append(f"{prefix} has invalid external score status: {status!r}")
            continue

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


def _validate_deterministic_row(row: Mapping[str, object], index: int) -> list[str]:
    prefix = f"deterministic row {index + 1}"
    required = {
        "row_type",
        "case_id",
        "target_skill",
        "split",
        "condition",
        "repeat",
        "pair_id",
        "parity_signature",
        "scores",
    }
    errors = _nonfinite_paths(row, prefix)
    missing = required - set(row)
    unknown = set(row) - required
    if missing:
        errors.append(f"{prefix} missing values: {', '.join(sorted(missing))}")
    if unknown:
        errors.append(f"{prefix} has unknown values: {', '.join(sorted(unknown))}")
    if row.get("row_type") != "deterministic":
        errors.append(f"{prefix}.row_type must be deterministic")
    for key in ("case_id", "target_skill"):
        if not isinstance(row.get(key), str) or not row[key].strip():
            errors.append(f"{prefix}.{key} must be a non-empty string")
    if row.get("split") not in SPLITS:
        errors.append(f"{prefix}.split is invalid")
    if row.get("condition") not in {"baseline", "candidate"}:
        errors.append(f"{prefix}.condition is invalid")
    repeat = row.get("repeat")
    if isinstance(repeat, bool) or not isinstance(repeat, int) or repeat < 0:
        errors.append(f"{prefix}.repeat must be a non-negative integer")
    for key in ("pair_id", "parity_signature"):
        value = row.get(key)
        if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
            errors.append(f"{prefix}.{key} must be a SHA-256 hex digest")
    if (
        isinstance(row.get("case_id"), str)
        and isinstance(row.get("target_skill"), str)
        and row.get("split") in SPLITS
        and isinstance(repeat, int)
        and not isinstance(repeat, bool)
        and isinstance(row.get("parity_signature"), str)
        and _SHA256_RE.fullmatch(row["parity_signature"]) is not None
        and isinstance(row.get("pair_id"), str)
        and row["pair_id"]
        != _pair_id_from_fields(
            row["case_id"],
            row["target_skill"],
            row["split"],
            repeat,
            row["parity_signature"],
        )
    ):
        errors.append(f"{prefix}.pair_id does not match pair identity")

    scores = row.get("scores")
    if not isinstance(scores, Mapping) or set(scores) != set(AXES):
        errors.append(f"{prefix}.scores must contain exactly six axes")
    else:
        for axis in AXES:
            result = scores[axis]
            if not isinstance(result, Mapping) or set(result) != {
                "passed",
                "status",
                "evidence",
            }:
                errors.append(f"{prefix}.scores.{axis} has an invalid schema")
                continue
            passed = result["passed"]
            status = result["status"]
            if status == "scored" and not isinstance(passed, bool):
                errors.append(f"{prefix}.scores.{axis}.passed must be boolean")
            elif status == "not_scored" and passed is not None:
                errors.append(f"{prefix}.scores.{axis}.passed must be null")
            elif status not in {"scored", "not_scored"}:
                errors.append(f"{prefix}.scores.{axis}.status is invalid")
            if not isinstance(result["evidence"], Mapping):
                errors.append(f"{prefix}.scores.{axis}.evidence must be an object")
    return errors


def _empty_judge_aggregate() -> dict:
    return {
        "role": "supporting_only",
        "row_count": 0,
        "pair_count": 0,
        "axes": {
            axis: {"baseline": 0, "candidate": 0, "tie": 0, "count": 0}
            for axis in AXES
        },
        "ab_ba_disagreement": {
            axis: {"compared_pairs": 0, "disagreements": 0} for axis in AXES
        },
    }


def _aggregate_judge_rows(rows: list[dict], deterministic_pairs: Mapping[str, dict]) -> dict:
    if not rows:
        return _empty_judge_aggregate()
    validation_errors = validate_external_scores(rows)
    if validation_errors:
        raise ValueError("invalid external score: " + "; ".join(validation_errors))

    grouped: dict[str, dict[str, list[dict]]] = defaultdict(
        lambda: {"AB": [], "BA": []}
    )
    for row in rows:
        pair_id = row["pair_id"]
        if pair_id not in deterministic_pairs:
            raise ValueError(
                f"invalid external score: judge pair_id has no deterministic pair: {pair_id}"
            )
        deterministic = deterministic_pairs[pair_id]
        for field in (
            "case_id",
            "target_skill",
            "split",
            "repeat",
            "parity_signature",
        ):
            if row[field] != deterministic[field]:
                raise ValueError(
                    f"invalid external score: judge {field} does not match deterministic pair"
                )
        grouped[pair_id][row["order"]].append(row)

    summary = _empty_judge_aggregate()
    summary["row_count"] = len(rows)
    summary["pair_count"] = len(grouped)
    for pair_id, orders in grouped.items():
        if len(orders["AB"]) != 1 or len(orders["BA"]) != 1:
            raise ValueError(
                f"invalid external score: pair_id {pair_id} requires exactly one AB and BA row"
            )
        ab_row, ba_row = orders["AB"][0], orders["BA"][0]
        for field in (
            "case_id",
            "target_skill",
            "split",
            "repeat",
            "pair_id",
            "parity_signature",
            "rubric_version",
            "model",
            "reasoning",
            "runtime",
            "command",
            "cwd",
            "timeout_seconds",
        ):
            if ab_row[field] != ba_row[field]:
                raise ValueError(
                    f"invalid external score: AB/BA provenance mismatch for {field}"
                )
        for axis in AXES:
            for row in (ab_row, ba_row):
                winner = row["axis_results"][axis]["winner"]
                summary["axes"][axis][winner] += 1
                summary["axes"][axis]["count"] += 1
            summary["ab_ba_disagreement"][axis]["compared_pairs"] += 1
            if (
                ab_row["axis_results"][axis]["winner"]
                != ba_row["axis_results"][axis]["winner"]
            ):
                summary["ab_ba_disagreement"][axis]["disagreements"] += 1
    return summary


def _validate_expected_pair_inventory(
    expected_pairs: Iterable[Mapping[str, object]],
) -> frozenset[tuple[str, str, str, int]]:
    """Validate the complete case/skill/split/repeat inventory for an eval run."""

    if isinstance(expected_pairs, (str, bytes, Mapping)):
        raise ValueError("expected_pairs must be an iterable of mappings")
    try:
        materialized = list(expected_pairs)
    except TypeError as exc:
        raise ValueError("expected_pairs must be an iterable of mappings") from exc

    required_keys = frozenset({"case_id", "target_skill", "split", "repeat"})
    inventory: set[tuple[str, str, str, int]] = set()
    executions: set[tuple[str, int]] = set()
    for index, pair in enumerate(materialized):
        if not isinstance(pair, Mapping):
            raise ValueError(f"expected_pairs[{index}] must be a mapping")
        keys = frozenset(pair)
        if keys != required_keys:
            missing = sorted(required_keys - keys)
            unknown = sorted(keys - required_keys)
            details = []
            if missing:
                details.append(f"missing keys {missing}")
            if unknown:
                details.append(f"unknown keys {unknown}")
            raise ValueError(
                f"invalid expected deterministic pair at index {index}: "
                + "; ".join(details)
            )

        case_id = pair["case_id"]
        if (
            not isinstance(case_id, str)
            or not _CASE_ID_RE.fullmatch(case_id)
            or _has_control_characters(case_id, allow_narrative_layout=False)
        ):
            raise ValueError(
                f"invalid expected deterministic pair at index {index}: case_id"
            )
        target_skill = pair["target_skill"]
        if (
            not isinstance(target_skill, str)
            or len(target_skill) > 64
            or not _TARGET_SKILL_RE.fullmatch(target_skill)
        ):
            raise ValueError(
                f"invalid expected deterministic pair at index {index}: target_skill"
            )
        split = pair["split"]
        if not isinstance(split, str) or split not in SPLITS:
            raise ValueError(
                f"invalid expected deterministic pair at index {index}: split"
            )
        repeat = pair["repeat"]
        if type(repeat) is not int or repeat < 0:
            raise ValueError(
                f"invalid expected deterministic pair at index {index}: repeat"
            )

        identity = (case_id, target_skill, split, repeat)
        execution = (case_id, repeat)
        if identity in inventory or execution in executions:
            raise ValueError(
                "duplicate expected deterministic pair for "
                f"{case_id} repeat {repeat}"
            )
        inventory.add(identity)
        executions.add(execution)
    return frozenset(inventory)


def aggregate_scores(
    rows: Iterable[dict],
    *,
    expected_pairs: Iterable[Mapping[str, object]] | None = None,
) -> dict:
    """Aggregate gates, verifying complete coverage when inventory is supplied.

    Passing approval booleans are reported only when ``expected_pairs`` proves
    that every planned case/repeat is present and no unplanned pair was scored.
    A detected failure remains ``False`` even without an inventory.
    """

    materialized = list(rows)
    if not materialized:
        raise ValueError(
            "at least one complete baseline and candidate deterministic pair is required"
        )
    deterministic_rows: list[dict] = []
    judge_rows: list[dict] = []
    for row in materialized:
        if not isinstance(row, Mapping):
            raise ValueError("invalid external score row type")
        if row.get("row_type") == "deterministic":
            deterministic_rows.append(dict(row))
        elif row.get("row_type") == "judge":
            judge_rows.append(dict(row))
        else:
            raise ValueError("invalid external score row type")

    if not deterministic_rows:
        raise ValueError(
            "at least one complete baseline and candidate deterministic pair is required"
        )
    deterministic_errors = [
        error
        for index, row in enumerate(deterministic_rows)
        for error in _validate_deterministic_row(row, index)
    ]
    if deterministic_errors:
        raise ValueError("invalid deterministic score: " + "; ".join(deterministic_errors))

    grouped: dict[tuple[str, int], dict[str, dict]] = defaultdict(dict)
    for row in deterministic_rows:
        key = (row["case_id"], row["repeat"])
        condition = row["condition"]
        if condition in grouped[key]:
            raise ValueError(
                f"duplicate deterministic {condition} row for {key[0]} repeat {key[1]}"
            )
        grouped[key][condition] = row

    deterministic_pairs: dict[str, dict] = {}
    for (case_id, repeat), conditions in grouped.items():
        if set(conditions) != {"baseline", "candidate"}:
            raise ValueError(
                "complete baseline and candidate deterministic pair required for "
                f"{case_id} repeat {repeat}"
            )
        baseline = conditions["baseline"]
        candidate = conditions["candidate"]
        for field in ("target_skill", "split", "parity_signature", "pair_id"):
            if baseline[field] != candidate[field]:
                raise ValueError(
                    f"deterministic pair parity mismatch for {case_id} repeat {repeat}: {field}"
                )
        pair_id = baseline["pair_id"]
        if pair_id in deterministic_pairs:
            raise ValueError(f"duplicate deterministic pair_id: {pair_id}")
        deterministic_pairs[pair_id] = baseline

    expected_inventory = (
        None
        if expected_pairs is None
        else _validate_expected_pair_inventory(expected_pairs)
    )
    observed_inventory = frozenset(
        (
            row["case_id"],
            row["target_skill"],
            row["split"],
            row["repeat"],
        )
        for row in deterministic_pairs.values()
    )
    if expected_inventory is not None:
        missing_pairs = expected_inventory - observed_inventory
        unexpected_pairs = observed_inventory - expected_inventory
        coverage_errors = []
        if missing_pairs:
            coverage_errors.append(
                "missing expected deterministic pair(s): "
                + ", ".join(repr(pair) for pair in sorted(missing_pairs))
            )
        if unexpected_pairs:
            coverage_errors.append(
                "unexpected deterministic pair(s): "
                + ", ".join(repr(pair) for pair in sorted(unexpected_pairs))
            )
        if coverage_errors:
            raise ValueError("; ".join(coverage_errors))

    axes = {
        axis: {
            condition: {"passed": 0, "failed": 0, "not_scored": 0, "count": 0}
            for condition in ("baseline", "candidate")
        }
        for axis in AXES
    }
    hard_gate_failures: list[dict] = []
    golden_failures: list[dict] = []
    hard_gate_axes = ("request_fulfillment", "meaning_and_facts")
    for row in deterministic_rows:
        condition = row["condition"]
        for axis in AXES:
            passed = row["scores"][axis]["passed"]
            bucket = "passed" if passed is True else "failed" if passed is False else "not_scored"
            axes[axis][condition][bucket] += 1
            axes[axis][condition]["count"] += 1
        if condition != "candidate":
            continue
        for axis in hard_gate_axes:
            if row["scores"][axis]["passed"] is not True:
                hard_gate_failures.append(
                    {
                        "case_id": row["case_id"],
                        "split": row["split"],
                        "repeat": row["repeat"],
                        "axis": axis,
                    }
                )
        if row["split"] == "golden":
            for axis in AXES:
                if row["scores"][axis]["passed"] is False:
                    golden_failures.append(
                        {
                            "case_id": row["case_id"],
                            "split": row["split"],
                            "repeat": row["repeat"],
                            "axis": axis,
                        }
                    )

    coverage_verified = expected_inventory is not None
    expected_golden_pair_count = (
        None
        if expected_inventory is None
        else sum(1 for _, _, split, _ in expected_inventory if split == "golden")
    )
    hard_gates_passed = (
        False
        if hard_gate_failures
        else True
        if coverage_verified
        else None
    )
    golden_passed = (
        False
        if golden_failures
        else True
        if coverage_verified and expected_golden_pair_count
        else None
    )

    judge = _aggregate_judge_rows(judge_rows, deterministic_pairs)
    return {
        "row_count": len(materialized),
        "deterministic_row_count": len(deterministic_rows),
        "deterministic_pair_count": len(deterministic_pairs),
        "observed_pair_count": len(observed_inventory),
        "coverage_verified": coverage_verified,
        "expected_pair_count": (
            None if expected_inventory is None else len(expected_inventory)
        ),
        "expected_golden_pair_count": expected_golden_pair_count,
        "axes": axes,
        "hard_gate_failures": hard_gate_failures,
        "golden_failures": golden_failures,
        "hard_gates_passed": hard_gates_passed,
        "golden_passed": golden_passed,
        "judge": judge,
    }
