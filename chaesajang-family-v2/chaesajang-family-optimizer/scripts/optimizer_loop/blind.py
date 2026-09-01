"""Anonymous mirrored presentation and strict one-person rating contracts."""

from __future__ import annotations

import hashlib
import json
import random
import re
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any


SCHEMA_VERSION = 1
MAX_EVIDENCE_CHARACTERS = 500
PUBLIC_PAIR_FIELDS = frozenset(
    {
        "pair_id",
        "source_pair_id",
        "order",
        "seed",
        "generator_brief",
        "response_a",
        "response_b",
    }
)
RAW_RATING_FIELDS = frozenset(
    {
        "pair_id",
        "quality_preference",
        "style_preference",
        "overall_preference",
        "over_imitation",
        "meaning_or_fact_issue",
        "evidence_excerpt",
    }
)
UNBLINDED_RATING_FIELDS = frozenset(
    {
        "pair_id",
        "source_pair_id",
        "case_id",
        "target_skill",
        "repeat",
        "order",
        "quality_preference",
        "style_preference",
        "overall_preference",
        "candidate_over_imitation",
        "baseline_over_imitation",
        "candidate_meaning_or_fact_issue",
        "baseline_meaning_or_fact_issue",
        "evidence_excerpt",
    }
)

_PRIVATE_KEY_FIELDS = frozenset({"schema_version", "seed", "presentations"})
_PRIVATE_PRESENTATION_FIELDS = frozenset(
    {
        "source_pair_id",
        "candidate_label",
        "case_id",
        "target_skill",
        "repeat",
        "order",
    }
)
_PARITY_FIELDS = (
    "case_id",
    "target_skill",
    "repeat",
    "model",
    "reasoning",
    "runtime",
    "input",
    "prompt",
)
_GENERATION_REQUIRED_FIELDS = frozenset(
    {
        *_PARITY_FIELDS,
        "output",
        "status",
        "source_snapshot",
        "source_snapshot_after",
        "source_stable",
    }
)
_PREFERENCE_FIELDS = (
    "quality_preference",
    "style_preference",
    "overall_preference",
)
_PREFERENCES = frozenset({"A", "B", "tie"})
_OVER_IMITATION = frozenset({"A", "B", "both", "neither"})
_ISSUE_SEVERITIES = frozenset({"none", "minor", "critical"})
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_TARGET_SKILL_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


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


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _seed(value: object) -> int:
    if type(value) is not int:
        raise TypeError("seed must be an integer")
    return value


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a SHA-256 hex digest")
    return value


def _nonempty_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _target_skill(value: object, label: str) -> str:
    target = _nonempty_text(value, label)
    if len(target) > 64 or _TARGET_SKILL_RE.fullmatch(target) is None:
        raise ValueError(f"{label} must be a safe lowercase hyphenated skill name")
    return target


def _repeat(value: object, label: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _materialize_rows(rows: object, label: str) -> list[Mapping[str, Any]]:
    if isinstance(rows, (str, bytes, bytearray, Mapping)):
        raise TypeError(f"{label} must be a sequence of row mappings")
    if not isinstance(rows, Sequence):
        raise TypeError(f"{label} must be a sequence of row mappings")
    materialized = list(rows)
    if not materialized:
        raise ValueError(f"{label} must not be empty")
    if not all(isinstance(row, Mapping) for row in materialized):
        raise TypeError(f"{label} must contain only row mappings")
    return materialized


def _validate_snapshot(value: object, label: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{label} must be a non-empty source snapshot")
    snapshot: dict[str, str] = {}
    for path, digest in value.items():
        if not isinstance(path, str) or not path:
            raise ValueError(f"{label} paths must be non-empty strings")
        snapshot[path] = _sha256(digest, f"{label}[{path!r}]")
    return snapshot


def _validate_generation_row(row: Mapping[str, Any], label: str) -> dict[str, Any]:
    missing = _GENERATION_REQUIRED_FIELDS - set(row)
    if missing:
        raise ValueError(f"{label} is missing generation fields: {sorted(missing)}")

    case_id = _nonempty_text(row["case_id"], f"{label}.case_id")
    target_skill = _target_skill(row["target_skill"], f"{label}.target_skill")
    repeat = _repeat(row["repeat"], f"{label}.repeat")
    for field in ("model", "reasoning", "runtime", "input", "prompt"):
        _nonempty_text(row[field], f"{label}.{field}")
    if re.search(
        rf"(?<![A-Za-z0-9]){re.escape(case_id)}(?![A-Za-z0-9])",
        row["input"],
        flags=re.IGNORECASE,
    ):
        raise ValueError(f"{label}.generator brief must not expose case_id metadata")
    if row["runtime"] != "codex":
        raise ValueError(f"{label}.runtime must be codex")
    if row["status"] != "completed":
        raise ValueError(f"{label}.status must be completed")
    output = _nonempty_text(row["output"], f"{label}.output")
    if row["source_stable"] is not True:
        raise ValueError(f"{label} source must be stable")
    before = _validate_snapshot(row["source_snapshot"], f"{label}.source_snapshot")
    after = _validate_snapshot(
        row["source_snapshot_after"], f"{label}.source_snapshot_after"
    )
    if before != after:
        raise ValueError(f"{label} source must be stable before and after generation")
    if "generator_brief" in row and row["generator_brief"] != row["input"]:
        raise ValueError(f"{label}.generator_brief must equal input")
    return {
        **{field: row[field] for field in _PARITY_FIELDS},
        "case_id": case_id,
        "target_skill": target_skill,
        "repeat": repeat,
        "output": output,
    }


def _indexed_inventory(rows: list[Mapping[str, Any]], label: str) -> dict[tuple[str, str, int], dict]:
    inventory: dict[tuple[str, str, int], dict] = {}
    executions: set[tuple[str, int]] = set()
    for index, row in enumerate(rows):
        normalized = _validate_generation_row(row, f"{label}[{index}]")
        identity = (
            normalized["case_id"],
            normalized["target_skill"],
            normalized["repeat"],
        )
        execution = (normalized["case_id"], normalized["repeat"])
        if identity in inventory or execution in executions:
            raise ValueError(
                f"duplicate {label} generation row for {normalized['case_id']} "
                f"repeat {normalized['repeat']}"
            )
        inventory[identity] = normalized
        executions.add(execution)
    return inventory


def make_blind_package(
    baseline_rows: Sequence[dict], candidate_rows: Sequence[dict], seed: int
) -> tuple[list[dict], dict]:
    """Build mirrored public presentations and a separate private answer key.

    The public rows contain no condition, case, model, command, timing, path, or
    snapshot metadata.  A local ``random.Random`` instance anonymously chooses
    the first source sample; ``AB`` and ``BA`` only describe presentation
    orientation around that hidden sample choice.
    """

    recorded_seed = _seed(seed)
    baseline = _indexed_inventory(
        _materialize_rows(baseline_rows, "baseline_rows"), "baseline_rows"
    )
    candidate = _indexed_inventory(
        _materialize_rows(candidate_rows, "candidate_rows"), "candidate_rows"
    )
    if set(baseline) != set(candidate):
        missing = sorted(set(baseline) - set(candidate))
        unexpected = sorted(set(candidate) - set(baseline))
        raise ValueError(
            "baseline/candidate inventory mismatch"
            f"; missing candidate rows: {missing}; unexpected candidate rows: {unexpected}"
        )

    identities = sorted(baseline)
    rng = random.Random(recorded_seed)
    public_rows: list[dict] = []
    presentations: dict[str, dict] = {}
    for ordinal, identity in enumerate(identities):
        left = baseline[identity]
        right = candidate[identity]
        mismatched = [field for field in _PARITY_FIELDS if left[field] != right[field]]
        if mismatched:
            raise ValueError(
                "baseline/candidate parity mismatch for "
                f"{identity[0]} repeat {identity[2]}: {', '.join(mismatched)}"
            )

        source_pair_id = _digest(
            {
                "kind": "blind-source-pair",
                "schema_version": SCHEMA_VERSION,
                "ordinal": ordinal,
                "identity": list(identity),
                "parity": {field: left[field] for field in _PARITY_FIELDS},
            }
        )
        candidate_is_first = bool(rng.randrange(2))
        first_response = right["output"] if candidate_is_first else left["output"]
        second_response = left["output"] if candidate_is_first else right["output"]
        candidate_label_ab = "A" if candidate_is_first else "B"

        for order in ("AB", "BA"):
            pair_id = _digest(
                {
                    "kind": "blind-presentation",
                    "schema_version": SCHEMA_VERSION,
                    "source_pair_id": source_pair_id,
                    "order": order,
                    "seed": recorded_seed,
                }
            )
            if order == "AB":
                response_a, response_b = first_response, second_response
                candidate_label = candidate_label_ab
            else:
                response_a, response_b = second_response, first_response
                candidate_label = "B" if candidate_label_ab == "A" else "A"
            public_rows.append(
                {
                    "pair_id": pair_id,
                    "source_pair_id": source_pair_id,
                    "order": order,
                    "seed": recorded_seed,
                    "generator_brief": left["input"],
                    "response_a": response_a,
                    "response_b": response_b,
                }
            )
            presentations[pair_id] = {
                "source_pair_id": source_pair_id,
                "candidate_label": candidate_label,
                "case_id": left["case_id"],
                "target_skill": left["target_skill"],
                "repeat": left["repeat"],
                "order": order,
            }

    errors = validate_order_balance(public_rows)
    if errors:
        raise RuntimeError("generated blind package is invalid: " + "; ".join(errors))
    return public_rows, {
        "schema_version": SCHEMA_VERSION,
        "seed": recorded_seed,
        "presentations": presentations,
    }


def make_blind_pairs(
    baseline_rows: Sequence[dict], candidate_rows: Sequence[dict], seed: int
) -> list[dict]:
    """Return only the public portion of :func:`make_blind_package`."""

    public_rows, _private_key = make_blind_package(baseline_rows, candidate_rows, seed)
    return public_rows


def validate_order_balance(pairs: Sequence[dict]) -> list[str]:
    """Return all public-schema and mirrored-order errors without raising."""

    errors: list[str] = []
    if isinstance(pairs, (str, bytes, bytearray, Mapping)) or not isinstance(
        pairs, Sequence
    ):
        return ["pairs must be a sequence of public pair mappings"]
    materialized = list(pairs)
    if not materialized:
        return ["pairs must not be empty"]

    seen_pair_ids: set[str] = set()
    groups: dict[str, list[dict]] = defaultdict(list)
    order_counts = {"AB": 0, "BA": 0}
    for index, raw in enumerate(materialized):
        label = f"pair[{index}]"
        if not isinstance(raw, Mapping):
            errors.append(f"{label} must be a mapping")
            continue
        fields = set(raw)
        if fields != PUBLIC_PAIR_FIELDS:
            missing = sorted(PUBLIC_PAIR_FIELDS - fields)
            unknown = sorted(fields - PUBLIC_PAIR_FIELDS)
            errors.append(f"{label} has invalid public schema; missing={missing}; unknown={unknown}")
            continue
        try:
            pair_id = _sha256(raw["pair_id"], f"{label}.pair_id")
            source_pair_id = _sha256(raw["source_pair_id"], f"{label}.source_pair_id")
            recorded_seed = _seed(raw["seed"])
            brief = _nonempty_text(raw["generator_brief"], f"{label}.generator_brief")
            response_a = _nonempty_text(raw["response_a"], f"{label}.response_a")
            response_b = _nonempty_text(raw["response_b"], f"{label}.response_b")
            order = raw["order"]
            if order not in {"AB", "BA"}:
                raise ValueError(f"{label}.order must be AB or BA")
        except (TypeError, ValueError) as error:
            errors.append(str(error))
            continue
        if pair_id in seen_pair_ids:
            errors.append(f"duplicate pair_id: {pair_id}")
        seen_pair_ids.add(pair_id)
        order_counts[order] += 1
        groups[source_pair_id].append(
            {
                "pair_id": pair_id,
                "order": order,
                "seed": recorded_seed,
                "generator_brief": brief,
                "response_a": response_a,
                "response_b": response_b,
            }
        )

    for source_pair_id, group in sorted(groups.items()):
        if len(group) != 2:
            errors.append(f"source pair {source_pair_id} must have exactly two presentations")
            continue
        by_order = {row["order"]: row for row in group}
        if set(by_order) != {"AB", "BA"}:
            errors.append(f"source pair {source_pair_id} must have one AB and one BA")
            continue
        ab, ba = by_order["AB"], by_order["BA"]
        if ab["seed"] != ba["seed"]:
            errors.append(f"source pair {source_pair_id} has mismatched seeds")
        if ab["generator_brief"] != ba["generator_brief"]:
            errors.append(f"source pair {source_pair_id} has mismatched generator briefs")
        if ab["response_a"] != ba["response_b"] or ab["response_b"] != ba["response_a"]:
            errors.append(f"source pair {source_pair_id} responses are not mirrored")
    if order_counts["AB"] != order_counts["BA"]:
        errors.append("global AB and BA presentation counts must be equal")
    return errors


def private_key_digest(private_key: Mapping[str, object]) -> str:
    """Return the canonical SHA-256 digest disclosed by reports, never the map."""

    if not isinstance(private_key, Mapping):
        raise TypeError("private_key must be a mapping")
    return _digest(private_key)


def _validated_private_key(private_key: object) -> tuple[int, dict[str, dict]]:
    if not isinstance(private_key, Mapping):
        raise TypeError("private_key must be a mapping")
    fields = set(private_key)
    if fields != _PRIVATE_KEY_FIELDS:
        raise ValueError(
            "private_key has invalid schema; "
            f"missing={sorted(_PRIVATE_KEY_FIELDS - fields)}; "
            f"unknown={sorted(fields - _PRIVATE_KEY_FIELDS)}"
        )
    if private_key["schema_version"] != SCHEMA_VERSION or type(
        private_key["schema_version"]
    ) is not int:
        raise ValueError(f"private_key.schema_version must be {SCHEMA_VERSION}")
    recorded_seed = _seed(private_key["seed"])
    raw_presentations = private_key["presentations"]
    if not isinstance(raw_presentations, Mapping) or not raw_presentations:
        raise ValueError("private_key.presentations must be a non-empty mapping")

    presentations: dict[str, dict] = {}
    groups: dict[str, list[dict]] = defaultdict(list)
    for pair_id_value, raw in raw_presentations.items():
        pair_id = _sha256(pair_id_value, "private presentation pair_id")
        if not isinstance(raw, Mapping) or set(raw) != _PRIVATE_PRESENTATION_FIELDS:
            raise ValueError(f"private presentation {pair_id} has invalid schema")
        source_pair_id = _sha256(raw["source_pair_id"], "private source_pair_id")
        candidate_label = raw["candidate_label"]
        if candidate_label not in {"A", "B"}:
            raise ValueError("private candidate_label must be A or B")
        order = raw["order"]
        if order not in {"AB", "BA"}:
            raise ValueError("private order must be AB or BA")
        presentation = {
            "source_pair_id": source_pair_id,
            "candidate_label": candidate_label,
            "case_id": _nonempty_text(raw["case_id"], "private case_id"),
            "target_skill": _target_skill(raw["target_skill"], "private target_skill"),
            "repeat": _repeat(raw["repeat"], "private repeat"),
            "order": order,
        }
        presentations[pair_id] = presentation
        groups[source_pair_id].append(presentation)

    for source_pair_id, group in groups.items():
        if len(group) != 2 or {row["order"] for row in group} != {"AB", "BA"}:
            raise ValueError(
                f"private source pair {source_pair_id} must have one AB and one BA presentation"
            )
        by_order = {row["order"]: row for row in group}
        ab, ba = by_order["AB"], by_order["BA"]
        if any(ab[field] != ba[field] for field in ("case_id", "target_skill", "repeat")):
            raise ValueError(f"private source pair {source_pair_id} metadata must be mirrored")
        if ab["candidate_label"] == ba["candidate_label"]:
            raise ValueError(f"private source pair {source_pair_id} candidate labels must flip")
    return recorded_seed, presentations


def normalize_human_rating(data: dict, known_pair_ids: set[str]) -> dict:
    """Validate one raw blind response without consulting identity mappings.

    ``evidence_excerpt`` is intentionally capped at 500 Unicode characters and
    preserved byte-for-byte after validation.
    """

    if not isinstance(known_pair_ids, set):
        raise TypeError("known_pair_ids must be a set")
    for pair_id in known_pair_ids:
        _sha256(pair_id, "known pair_id")
    if not isinstance(data, dict):
        raise TypeError("human rating must be a dictionary")
    fields = set(data)
    if fields != RAW_RATING_FIELDS:
        missing = sorted(RAW_RATING_FIELDS - fields)
        unknown = sorted(fields - RAW_RATING_FIELDS)
        raise ValueError(f"human rating has missing fields {missing} and unknown fields {unknown}")
    pair_id = _sha256(data["pair_id"], "pair_id")
    if pair_id not in known_pair_ids:
        raise ValueError(f"unknown pair_id for blind presentation: {pair_id}")
    for field in _PREFERENCE_FIELDS:
        if data[field] not in _PREFERENCES:
            raise ValueError(f"{field} preference must be A, B, or tie")
    if data["over_imitation"] not in _OVER_IMITATION:
        raise ValueError("over_imitation must be A, B, both, or neither")
    issue = data["meaning_or_fact_issue"]
    if (
        not isinstance(issue, dict)
        or set(issue) != {"A", "B"}
        or any(value not in _ISSUE_SEVERITIES for value in issue.values())
    ):
        raise ValueError(
            "meaning_or_fact_issue must map exactly A and B to none, minor, or critical"
        )
    evidence = data["evidence_excerpt"]
    if not isinstance(evidence, str) or not evidence.strip():
        raise ValueError("evidence_excerpt must be non-blank")
    if len(evidence) > MAX_EVIDENCE_CHARACTERS:
        raise ValueError(
            f"evidence_excerpt must be at most {MAX_EVIDENCE_CHARACTERS} characters"
        )
    if "\x00" in evidence or any(
        ord(character) < 32 and character not in "\t\n\r" for character in evidence
    ):
        raise ValueError("evidence_excerpt contains unsafe control characters")
    return {
        "pair_id": pair_id,
        **{field: data[field] for field in _PREFERENCE_FIELDS},
        "over_imitation": data["over_imitation"],
        "meaning_or_fact_issue": {"A": issue["A"], "B": issue["B"]},
        "evidence_excerpt": evidence,
    }


def unblind_human_ratings(ratings: Sequence[dict], private_key: Mapping[str, object]) -> list[dict]:
    """Map a complete raw rating file to condition-oriented, report-safe rows."""

    _recorded_seed, presentations = _validated_private_key(private_key)
    if isinstance(ratings, (str, bytes, bytearray, Mapping)) or not isinstance(
        ratings, Sequence
    ):
        raise TypeError("ratings must be a sequence of raw rating dictionaries")
    known_pair_ids = set(presentations)
    seen: set[str] = set()
    normalized_rows: list[dict] = []
    for raw in ratings:
        normalized = normalize_human_rating(raw, known_pair_ids)
        pair_id = normalized["pair_id"]
        if pair_id in seen:
            raise ValueError(f"duplicate human rating for pair_id: {pair_id}")
        seen.add(pair_id)
        normalized_rows.append(normalized)
    missing = known_pair_ids - seen
    if missing:
        raise ValueError(
            "human rating coverage is missing private-key presentations: "
            + ", ".join(sorted(missing))
        )
    if seen != known_pair_ids:
        raise ValueError("human rating coverage does not match the private key")

    unblinded: list[dict] = []
    for rating in normalized_rows:
        private = presentations[rating["pair_id"]]
        candidate_label = private["candidate_label"]
        baseline_label = "B" if candidate_label == "A" else "A"

        def condition_preference(value: str) -> str:
            if value == "tie":
                return "tie"
            return "candidate" if value == candidate_label else "baseline"

        over_imitation = rating["over_imitation"]
        unblinded.append(
            {
                "pair_id": rating["pair_id"],
                "source_pair_id": private["source_pair_id"],
                "case_id": private["case_id"],
                "target_skill": private["target_skill"],
                "repeat": private["repeat"],
                "order": private["order"],
                **{
                    field: condition_preference(rating[field])
                    for field in _PREFERENCE_FIELDS
                },
                "candidate_over_imitation": over_imitation
                in {candidate_label, "both"},
                "baseline_over_imitation": over_imitation
                in {baseline_label, "both"},
                "candidate_meaning_or_fact_issue": rating[
                    "meaning_or_fact_issue"
                ][candidate_label],
                "baseline_meaning_or_fact_issue": rating[
                    "meaning_or_fact_issue"
                ][baseline_label],
                "evidence_excerpt": rating["evidence_excerpt"],
            }
        )
    order_rank = {"AB": 0, "BA": 1}
    return sorted(
        unblinded,
        key=lambda row: (row["source_pair_id"], order_rank[row["order"]], row["pair_id"]),
    )
