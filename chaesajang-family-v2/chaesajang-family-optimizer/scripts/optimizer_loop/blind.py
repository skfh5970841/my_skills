"""HMAC-bound blind presentations and process-local verified human reviews."""

from __future__ import annotations

import hashlib
import hmac
import json
import random
import re
import secrets
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any
from weakref import WeakKeyDictionary


SCHEMA_VERSION = 2
MAX_EVIDENCE_CHARACTERS = 500
PUBLIC_PAIR_FIELDS = frozenset(
    {"pair_id", "generator_brief", "response_a", "response_b"}
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
        "pair_id", "source_id", "case_id", "target_skill", "repeat", "order",
        "quality_preference", "style_preference", "overall_preference",
        "candidate_over_imitation", "baseline_over_imitation",
        "candidate_meaning_or_fact_issue", "baseline_meaning_or_fact_issue",
        "evidence_excerpt",
    }
)

_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_TARGET_SKILL_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")
_EXPERIMENT_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SEAL = object()


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


_PRIVATE_KEY_FIELDS = frozenset(
    {
        "schema_version", "experiment_id", "seed", "secret",
        "baseline_row_digests", "candidate_row_digests",
        "public_bundle_digest", "public_row_digests", "mapping", "package_id",
    }
)
_MAPPING_FIELDS = frozenset(
    {"source_id", "candidate_label", "case_id", "target_skill", "repeat", "order"}
)
_PARITY_FIELDS = (
    "case_id", "target_skill", "repeat", "model", "reasoning", "runtime", "input", "prompt",
)
_GENERATION_FIELDS = frozenset(
    {*_PARITY_FIELDS, "output", "status", "source_snapshot", "source_snapshot_after", "source_stable"}
)
_PREFERENCE_FIELDS = ("quality_preference", "style_preference", "overall_preference")
_PREFERENCES = frozenset({"A", "B", "tie"})
_OVER_IMITATION = frozenset({"A", "B", "both", "neither"})
_ISSUE_SEVERITIES = frozenset({"none", "minor", "critical"})


def _canonical_bytes(value: object) -> bytes:
    return _canonical_json(value).encode("utf-8")


def _mac(secret: bytes, domain: str, value: object) -> str:
    payload = b"chaesajang-family-optimizer/blind/v2\0" + domain.encode("ascii") + b"\0" + _canonical_bytes(value)
    return hmac.new(secret, payload, hashlib.sha256).hexdigest()


def _experiment_id(value: object) -> str:
    if not isinstance(value, str) or _EXPERIMENT_ID_RE.fullmatch(value) is None:
        raise ValueError("experiment_id must be a safe non-empty identifier")
    return value


def _seed(value: object) -> int:
    if type(value) is not int:
        raise TypeError("seed must be an integer")
    return value


def _sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a SHA-256 hex digest")
    return value


def _nonempty(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value


def _rows(value: object, label: str, *, empty: bool = False) -> list[Mapping[str, Any]]:
    if isinstance(value, (str, bytes, bytearray, Mapping)) or not isinstance(value, Sequence):
        raise TypeError(f"{label} must be a sequence of row mappings")
    materialized = list(value)
    if not empty and not materialized:
        raise ValueError(f"{label} must not be empty")
    if not all(isinstance(row, Mapping) for row in materialized):
        raise TypeError(f"{label} must contain only row mappings")
    return materialized


def _snapshot(value: object, label: str) -> dict[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise ValueError(f"{label} must be a non-empty source snapshot")
    result: dict[str, str] = {}
    for path, digest in value.items():
        if not isinstance(path, str) or not path:
            raise ValueError(f"{label} paths must be non-empty strings")
        result[path] = _sha256(digest, label)
    return result


def _generation(row: Mapping[str, Any], label: str) -> dict[str, Any]:
    missing = _GENERATION_FIELDS - set(row)
    if missing:
        raise ValueError(f"{label} is missing generation fields: {sorted(missing)}")
    row_digest = _digest(dict(row))
    case_id = _nonempty(row["case_id"], f"{label}.case_id")
    target = _nonempty(row["target_skill"], f"{label}.target_skill")
    if len(target) > 64 or _TARGET_SKILL_RE.fullmatch(target) is None:
        raise ValueError(f"{label}.target_skill must be a safe skill name")
    repeat = row["repeat"]
    if type(repeat) is not int or repeat < 0:
        raise ValueError(f"{label}.repeat must be a non-negative integer")
    for field in ("model", "reasoning", "runtime", "input", "prompt"):
        _nonempty(row[field], f"{label}.{field}")
    if re.search(rf"(?<![A-Za-z0-9]){re.escape(case_id)}(?![A-Za-z0-9])", row["input"], re.I):
        raise ValueError(f"{label}.generator brief must not expose case_id metadata")
    if row["runtime"] != "codex" or row["status"] != "completed":
        raise ValueError(f"{label}.status/runtime must be completed/codex")
    output = _nonempty(row["output"], f"{label}.output")
    if row["source_stable"] is not True:
        raise ValueError(f"{label} source must be stable")
    if _snapshot(row["source_snapshot"], label) != _snapshot(row["source_snapshot_after"], label):
        raise ValueError(f"{label} source must be stable before and after generation")
    if "generator_brief" in row and row["generator_brief"] != row["input"]:
        raise ValueError(f"{label}.generator_brief must equal input")
    return {**{field: row[field] for field in _PARITY_FIELDS}, "output": output, "row_digest": row_digest}


def _inventory(value: object, label: str) -> dict[tuple[str, str, int], dict]:
    result: dict[tuple[str, str, int], dict] = {}
    executions: set[tuple[str, int]] = set()
    for index, raw in enumerate(_rows(value, label)):
        row = _generation(raw, f"{label}[{index}]")
        identity = (row["case_id"], row["target_skill"], row["repeat"])
        execution = (row["case_id"], row["repeat"])
        if identity in result or execution in executions:
            raise ValueError(f"duplicate {label} generation row")
        result[identity] = row
        executions.add(execution)
    return result


def _commitments(inventory: Mapping[tuple[str, str, int], Mapping[str, Any]]) -> list[dict]:
    return [
        {"identity": list(identity), "sha256": inventory[identity]["row_digest"]}
        for identity in sorted(inventory)
    ]


def _evidence_digest(
    baseline_commitments: Sequence[Mapping[str, object]],
    candidate_commitments: Sequence[Mapping[str, object]],
) -> str:
    rows = [
        {"condition": condition, **dict(commitment)}
        for condition, commitments in (
            ("baseline", baseline_commitments),
            ("candidate", candidate_commitments),
        )
        for commitment in commitments
    ]
    return _digest(
        {
            "schema_version": 1,
            "rows": sorted(
                rows,
                key=lambda row: (
                    row["condition"],
                    tuple(row["identity"]),
                    row["sha256"],
                ),
            ),
        }
    )


def generation_evidence_digest(
    baseline_rows: Sequence[dict], candidate_rows: Sequence[dict]
) -> str:
    """Commit to the exact raw generation rows used by both conditions."""

    baseline = _inventory(baseline_rows, "baseline_rows")
    candidate = _inventory(candidate_rows, "candidate_rows")
    if set(baseline) != set(candidate):
        raise ValueError("baseline/candidate inventory mismatch")
    return _evidence_digest(_commitments(baseline), _commitments(candidate))


def validate_order_balance(pairs: Sequence[dict]) -> list[str]:
    """Validate public-only uniqueness and mirrored response multisets."""
    if isinstance(pairs, (str, bytes, bytearray, Mapping)) or not isinstance(pairs, Sequence):
        return ["pairs must be a sequence of public pair mappings"]
    if not pairs:
        return ["pairs must not be empty"]
    errors: list[str] = []
    seen: set[str] = set()
    directed: Counter[tuple[str, str, str]] = Counter()
    for index, raw in enumerate(pairs):
        if not isinstance(raw, Mapping) or set(raw) != PUBLIC_PAIR_FIELDS:
            errors.append(f"pair[{index}] has invalid public schema")
            continue
        try:
            pair_id = _sha256(raw["pair_id"], f"pair[{index}].pair_id")
            brief = _nonempty(raw["generator_brief"], "generator_brief")
            a = _nonempty(raw["response_a"], "response_a")
            b = _nonempty(raw["response_b"], "response_b")
        except (TypeError, ValueError) as error:
            errors.append(str(error))
            continue
        if pair_id in seen:
            errors.append(f"duplicate pair_id: {pair_id}")
        seen.add(pair_id)
        directed[(brief, a, b)] += 1
    for (brief, a, b), count in directed.items():
        if a == b:
            if count % 2:
                errors.append("equal-response presentation multiset must be even")
        elif directed[(brief, b, a)] != count:
            errors.append("public response presentations are not mirrored")
    return sorted(set(errors))


def _build(
    experiment_id: str,
    baseline_rows: object,
    candidate_rows: object,
    seed: int,
    secret: bytes,
) -> tuple[list[dict], dict]:
    experiment_id = _experiment_id(experiment_id)
    seed = _seed(seed)
    if not isinstance(secret, bytes) or len(secret) != 32:
        raise ValueError("blind secret must contain exactly 32 bytes")
    baseline = _inventory(baseline_rows, "baseline_rows")
    candidate = _inventory(candidate_rows, "candidate_rows")
    if set(baseline) != set(candidate):
        raise ValueError("baseline/candidate inventory mismatch")
    baseline_digests = _commitments(baseline)
    candidate_digests = _commitments(candidate)
    context = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "seed": seed,
        "baseline_row_digests": baseline_digests,
        "candidate_row_digests": candidate_digests,
    }
    context_digest = _digest(context)
    rng = random.Random(seed)
    public: list[dict] = []
    mapping: dict[str, dict] = {}
    for ordinal, identity in enumerate(sorted(baseline)):
        old, new = baseline[identity], candidate[identity]
        mismatched = [field for field in _PARITY_FIELDS if old[field] != new[field]]
        if mismatched:
            raise ValueError(f"baseline/candidate parity mismatch: {', '.join(mismatched)}")
        source_id = _mac(secret, "source-id", {
            "context": context_digest, "ordinal": ordinal, "identity": list(identity),
            "baseline": old["row_digest"], "candidate": new["row_digest"],
        })
        candidate_first = bool(rng.randrange(2))
        first = new["output"] if candidate_first else old["output"]
        second = old["output"] if candidate_first else new["output"]
        candidate_ab = "A" if candidate_first else "B"
        for order in ("AB", "BA"):
            a, b = (first, second) if order == "AB" else (second, first)
            candidate_label = candidate_ab if order == "AB" else ("B" if candidate_ab == "A" else "A")
            payload = {"generator_brief": old["input"], "response_a": a, "response_b": b}
            pair_id = _mac(secret, "presentation-id", {
                "context": context_digest, "source_id": source_id, "order": order, "payload": payload,
            })
            public.append({"pair_id": pair_id, **payload})
            mapping[pair_id] = {
                "source_id": source_id, "candidate_label": candidate_label,
                "case_id": old["case_id"], "target_skill": old["target_skill"],
                "repeat": old["repeat"], "order": order,
            }
    errors = validate_order_balance(public)
    if errors:
        raise RuntimeError("generated blind package is invalid: " + "; ".join(errors))
    row_digests = {row["pair_id"]: _digest(row) for row in public}
    bundle_digest = _digest(public)
    package_id = _mac(secret, "package-id", {
        "context": context, "public_bundle_digest": bundle_digest,
        "public_row_digests": row_digests, "mapping_digest": _digest(mapping),
    })
    key = {
        "schema_version": SCHEMA_VERSION, "experiment_id": experiment_id,
        "seed": seed, "secret": secret.hex(),
        "baseline_row_digests": baseline_digests,
        "candidate_row_digests": candidate_digests,
        "public_bundle_digest": bundle_digest,
        "public_row_digests": row_digests, "mapping": mapping, "package_id": package_id,
    }
    return public, key


def make_blind_package(
    experiment_id: str,
    baseline_rows: Sequence[dict],
    candidate_rows: Sequence[dict],
    seed: int,
) -> tuple[list[dict], dict]:
    """Create a manifest-bound package using a fresh 256-bit private key."""
    return _build(experiment_id, baseline_rows, candidate_rows, seed, secrets.token_bytes(32))


def _validated_commitments(value: object, label: str) -> list[dict]:
    rows = _rows(value, label)
    commitments: list[dict] = []
    identities: set[tuple[str, str, int]] = set()
    for index, raw in enumerate(rows):
        if set(raw) != {"identity", "sha256"}:
            raise ValueError(f"{label}[{index}] has invalid schema")
        identity_value = raw["identity"]
        if (
            isinstance(identity_value, (str, bytes, bytearray, Mapping))
            or not isinstance(identity_value, Sequence)
            or len(identity_value) != 3
        ):
            raise ValueError(f"{label}[{index}].identity has invalid schema")
        case_id = _nonempty(identity_value[0], f"{label}[{index}].identity.case_id")
        target_skill = _nonempty(
            identity_value[1], f"{label}[{index}].identity.target_skill"
        )
        repeat = identity_value[2]
        if type(repeat) is not int or repeat < 0:
            raise ValueError(f"{label}[{index}].identity.repeat must be non-negative")
        identity = (case_id, target_skill, repeat)
        if identity in identities:
            raise ValueError(f"{label} contains a duplicate identity")
        identities.add(identity)
        commitments.append(
            {
                "identity": list(identity),
                "sha256": _sha256(raw["sha256"], f"{label}[{index}].sha256"),
            }
        )
    return commitments


def _validated_private_key(
    private_key: object, *, expected_experiment_id: str | None = None
) -> tuple[dict, bytes]:
    if not isinstance(private_key, Mapping):
        raise TypeError("private_key must be a mapping")
    if set(private_key) != _PRIVATE_KEY_FIELDS:
        missing = sorted(_PRIVATE_KEY_FIELDS - set(private_key))
        unknown = sorted(set(private_key) - _PRIVATE_KEY_FIELDS)
        raise ValueError(
            f"private_key has invalid schema; missing={missing}; unknown={unknown}"
        )
    if type(private_key["schema_version"]) is not int or private_key["schema_version"] != SCHEMA_VERSION:
        raise ValueError(f"private_key.schema_version must be {SCHEMA_VERSION}")
    experiment_id = _experiment_id(private_key["experiment_id"])
    if expected_experiment_id is not None:
        expected = _experiment_id(expected_experiment_id)
        if experiment_id != expected:
            raise ValueError("private key belongs to a different experiment")
    seed = _seed(private_key["seed"])
    secret_text = private_key["secret"]
    if not isinstance(secret_text, str) or _SHA256_RE.fullmatch(secret_text) is None:
        raise ValueError("private_key.secret must encode exactly 32 bytes")
    secret = bytes.fromhex(secret_text)

    baseline_digests = _validated_commitments(
        private_key["baseline_row_digests"], "private_key.baseline_row_digests"
    )
    candidate_digests = _validated_commitments(
        private_key["candidate_row_digests"], "private_key.candidate_row_digests"
    )
    public_bundle_digest = _sha256(
        private_key["public_bundle_digest"], "private_key.public_bundle_digest"
    )

    raw_row_digests = private_key["public_row_digests"]
    if not isinstance(raw_row_digests, Mapping) or not raw_row_digests:
        raise ValueError("private_key.public_row_digests must be a non-empty mapping")
    public_row_digests: dict[str, str] = {}
    for raw_pair_id, raw_digest in raw_row_digests.items():
        pair_id = _sha256(raw_pair_id, "private_key.public_row_digests pair_id")
        public_row_digests[pair_id] = _sha256(
            raw_digest, f"private_key.public_row_digests[{pair_id}]"
        )

    raw_mapping = private_key["mapping"]
    if not isinstance(raw_mapping, Mapping) or not raw_mapping:
        raise ValueError("private_key.mapping must be a non-empty mapping")
    mapping: dict[str, dict] = {}
    groups: dict[str, list[dict]] = defaultdict(list)
    for raw_pair_id, raw in raw_mapping.items():
        pair_id = _sha256(raw_pair_id, "private_key.mapping pair_id")
        if not isinstance(raw, Mapping) or set(raw) != _MAPPING_FIELDS:
            raise ValueError(f"private_key.mapping[{pair_id}] has invalid schema")
        source_id = _sha256(raw["source_id"], "private mapping source_id")
        candidate_label = raw["candidate_label"]
        if candidate_label not in {"A", "B"}:
            raise ValueError("private mapping candidate_label must be A or B")
        order = raw["order"]
        if order not in {"AB", "BA"}:
            raise ValueError("private mapping order must be AB or BA")
        case_id = _nonempty(raw["case_id"], "private mapping case_id")
        target_skill = _nonempty(raw["target_skill"], "private mapping target_skill")
        repeat = raw["repeat"]
        if type(repeat) is not int or repeat < 0:
            raise ValueError("private mapping repeat must be a non-negative integer")
        item = {
            "source_id": source_id,
            "candidate_label": candidate_label,
            "case_id": case_id,
            "target_skill": target_skill,
            "repeat": repeat,
            "order": order,
        }
        mapping[pair_id] = item
        groups[source_id].append(item)
    if set(mapping) != set(public_row_digests):
        raise ValueError("private key mapping and public row digests disagree")
    for source_id, group in groups.items():
        if len(group) != 2 or {item["order"] for item in group} != {"AB", "BA"}:
            raise ValueError(f"private source {source_id} lacks mirrored coverage")
        ab, ba = sorted(group, key=lambda item: item["order"])
        if any(
            ab[field] != ba[field]
            for field in ("case_id", "target_skill", "repeat")
        ):
            raise ValueError(f"private source {source_id} metadata is not mirrored")
        if ab["candidate_label"] == ba["candidate_label"]:
            raise ValueError(f"private source {source_id} candidate labels do not flip")

    package_id = _sha256(private_key["package_id"], "private_key.package_id")
    validated = {
        "schema_version": SCHEMA_VERSION,
        "experiment_id": experiment_id,
        "seed": seed,
        "secret": secret_text,
        "baseline_row_digests": baseline_digests,
        "candidate_row_digests": candidate_digests,
        "public_bundle_digest": public_bundle_digest,
        "public_row_digests": public_row_digests,
        "mapping": mapping,
        "package_id": package_id,
    }
    _canonical_json(validated)
    return validated, secret


def rebuild_blind_package(
    experiment_id: str,
    baseline_rows: Sequence[dict],
    candidate_rows: Sequence[dict],
    private_key: Mapping[str, object],
) -> list[dict]:
    """Rebuild a byte-identical public package from its persisted private key."""

    validated, secret = _validated_private_key(
        private_key, expected_experiment_id=experiment_id
    )
    rebuilt, rebuilt_key = _build(
        validated["experiment_id"],
        baseline_rows,
        candidate_rows,
        validated["seed"],
        secret,
    )
    if _canonical_json(rebuilt_key) != _canonical_json(validated):
        raise ValueError("private key does not match the experiment generation inputs")
    return rebuilt


@dataclass(frozen=True, slots=True)
class VerifiedBlindPackage:
    experiment_id: str
    package_id: str
    public_bundle_digest: str
    generation_evidence_digest: str
    pair_ids: tuple[str, ...]


def verify_blind_package(
    experiment_id: str,
    baseline_rows: Sequence[dict],
    candidate_rows: Sequence[dict],
    public_pairs: Sequence[dict],
    private_key: Mapping[str, object],
) -> VerifiedBlindPackage:
    """Verify exact raw inputs, public rows, and private commitments together."""

    expected = rebuild_blind_package(
        experiment_id, baseline_rows, candidate_rows, private_key
    )
    supplied = _rows(public_pairs, "public_pairs")
    supplied_rows = [dict(row) for row in supplied]
    errors = validate_order_balance(supplied_rows)
    if errors:
        raise ValueError("invalid public blind package: " + "; ".join(errors))
    if _canonical_json(supplied_rows) != _canonical_json(expected):
        raise ValueError("public blind package does not match its private key")
    validated, _secret = _validated_private_key(
        private_key, expected_experiment_id=experiment_id
    )
    return VerifiedBlindPackage(
        experiment_id=validated["experiment_id"],
        package_id=validated["package_id"],
        public_bundle_digest=validated["public_bundle_digest"],
        generation_evidence_digest=_evidence_digest(
            validated["baseline_row_digests"],
            validated["candidate_row_digests"],
        ),
        pair_ids=tuple(row["pair_id"] for row in supplied_rows),
    )


def private_key_digest(private_key: Mapping[str, object]) -> str:
    """Return a canonical checksum after validating the complete private schema."""

    validated, _secret = _validated_private_key(private_key)
    return _digest(validated)


def normalize_human_rating(data: dict, known_pair_ids: set[str]) -> dict:
    """Validate one anonymous A/B rating without consulting condition identity."""

    if not isinstance(known_pair_ids, set):
        raise TypeError("known_pair_ids must be a set")
    validated_ids = {
        _sha256(pair_id, "known pair_id") for pair_id in known_pair_ids
    }
    if not isinstance(data, dict):
        raise TypeError("human rating must be a dictionary")
    if set(data) != RAW_RATING_FIELDS:
        missing = sorted(RAW_RATING_FIELDS - set(data))
        unknown = sorted(set(data) - RAW_RATING_FIELDS)
        raise ValueError(
            f"human rating has missing fields {missing} and unknown fields {unknown}"
        )
    pair_id = _sha256(data["pair_id"], "pair_id")
    if pair_id not in validated_ids:
        raise ValueError(f"unknown pair_id for blind presentation: {pair_id}")
    preferences: dict[str, str] = {}
    for field in _PREFERENCE_FIELDS:
        value = data[field]
        if value not in _PREFERENCES:
            raise ValueError(f"{field} preference must be A, B, or tie")
        preferences[field] = value
    over_imitation = data["over_imitation"]
    if over_imitation not in _OVER_IMITATION:
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
        **preferences,
        "over_imitation": over_imitation,
        "meaning_or_fact_issue": {"A": issue["A"], "B": issue["B"]},
        "evidence_excerpt": evidence,
    }


def _normalized_ratings(
    ratings: object, known_pair_ids: set[str]
) -> list[dict]:
    rows = _rows(ratings, "ratings", empty=True)
    normalized: list[dict] = []
    seen: set[str] = set()
    for raw in rows:
        if not isinstance(raw, dict):
            raw = dict(raw)
        rating = normalize_human_rating(raw, known_pair_ids)
        if rating["pair_id"] in seen:
            raise ValueError(f"duplicate human rating for pair_id: {rating['pair_id']}")
        seen.add(rating["pair_id"])
        normalized.append(rating)
    return normalized


def _condition_ratings(normalized: Sequence[dict], mapping: Mapping[str, dict]) -> list[dict]:
    condition_rows: list[dict] = []
    for rating in normalized:
        private = mapping[rating["pair_id"]]
        candidate_label = private["candidate_label"]
        baseline_label = "B" if candidate_label == "A" else "A"

        def condition_preference(value: str) -> str:
            if value == "tie":
                return "tie"
            return "candidate" if value == candidate_label else "baseline"

        over_imitation = rating["over_imitation"]
        condition_rows.append(
            {
                "pair_id": rating["pair_id"],
                "source_id": private["source_id"],
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
                "candidate_meaning_or_fact_issue": rating["meaning_or_fact_issue"][
                    candidate_label
                ],
                "baseline_meaning_or_fact_issue": rating["meaning_or_fact_issue"][
                    baseline_label
                ],
                "evidence_excerpt": rating["evidence_excerpt"],
            }
        )
    order_rank = {"AB": 0, "BA": 1}
    return sorted(
        condition_rows,
        key=lambda row: (row["source_id"], order_rank[row["order"]], row["pair_id"]),
    )


def unblind_human_ratings(
    ratings: Sequence[dict], private_key: Mapping[str, object]
) -> list[dict]:
    """Unblind a complete rating set after validating the v2 private key."""

    validated, _secret = _validated_private_key(private_key)
    known_pair_ids = set(validated["mapping"])
    normalized = _normalized_ratings(ratings, known_pair_ids)
    seen = {row["pair_id"] for row in normalized}
    missing = known_pair_ids - seen
    if missing:
        raise ValueError(
            "human rating coverage is missing private-key presentations: "
            + ", ".join(sorted(missing))
        )
    if seen != known_pair_ids:
        raise ValueError("human rating coverage does not match the private key")
    return _condition_ratings(normalized, validated["mapping"])


class VerifiedBlindReview:
    """An immutable, process-local proof that raw blind evidence was reverified."""

    __slots__ = (
        "experiment_id",
        "package_id",
        "public_bundle_digest",
        "generation_evidence_digest",
        "coverage_count",
        "expected_count",
        "complete",
        "condition_ratings",
        "receipt",
        "_seal",
        "__weakref__",
    )

    def __new__(cls, seal: object, **_values: object):
        if seal is not _SEAL:
            raise TypeError("VerifiedBlindReview instances are issued by verify_blind_review")
        return super().__new__(cls)

    def __init__(
        self,
        seal: object,
        *,
        experiment_id: str,
        package_id: str,
        public_bundle_digest: str,
        generation_evidence_digest: str,
        coverage_count: int,
        expected_count: int,
        complete: bool,
        condition_ratings: tuple[Mapping[str, object], ...],
        receipt: Mapping[str, object] | None,
    ) -> None:
        if seal is not _SEAL:
            raise TypeError("VerifiedBlindReview instances are issued by verify_blind_review")
        object.__setattr__(self, "experiment_id", experiment_id)
        object.__setattr__(self, "package_id", package_id)
        object.__setattr__(self, "public_bundle_digest", public_bundle_digest)
        object.__setattr__(self, "generation_evidence_digest", generation_evidence_digest)
        object.__setattr__(self, "coverage_count", coverage_count)
        object.__setattr__(self, "expected_count", expected_count)
        object.__setattr__(self, "complete", complete)
        object.__setattr__(self, "condition_ratings", condition_ratings)
        object.__setattr__(self, "receipt", receipt)
        object.__setattr__(self, "_seal", seal)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise TypeError("VerifiedBlindReview is immutable")


def _review_fingerprint(review: VerifiedBlindReview) -> str:
    return _digest(
        {
            "experiment_id": review.experiment_id,
            "package_id": review.package_id,
            "public_bundle_digest": review.public_bundle_digest,
            "generation_evidence_digest": review.generation_evidence_digest,
            "coverage_count": review.coverage_count,
            "expected_count": review.expected_count,
            "complete": review.complete,
            "condition_ratings": [dict(row) for row in review.condition_ratings],
            "receipt": None if review.receipt is None else dict(review.receipt),
        }
    )


_ISSUED_REVIEWS: WeakKeyDictionary[VerifiedBlindReview, str] = WeakKeyDictionary()


def is_verified_blind_review(value: object) -> bool:
    """Return whether *value* is an immutable review issued in this process."""

    if type(value) is not VerifiedBlindReview or getattr(value, "_seal", None) is not _SEAL:
        return False
    try:
        return _ISSUED_REVIEWS.get(value) == _review_fingerprint(value)
    except (AttributeError, TypeError, ValueError):
        return False


_RECEIPT_FIELDS = frozenset(
    {
        "schema_version",
        "experiment_id",
        "package_id",
        "public_bundle_digest",
        "ratings_digest",
        "coverage_count",
        "mac",
    }
)


def verify_blind_review(
    experiment_id: str,
    baseline_rows: Sequence[dict],
    candidate_rows: Sequence[dict],
    public_pairs: Sequence[dict],
    private_key: Mapping[str, object],
    ratings: Sequence[dict],
    *,
    expected_receipt: Mapping[str, object] | None = None,
) -> VerifiedBlindReview:
    """Reverify all package inputs and issue a sealed complete/partial review."""

    package = verify_blind_package(
        experiment_id, baseline_rows, candidate_rows, public_pairs, private_key
    )
    validated_key, secret = _validated_private_key(
        private_key, expected_experiment_id=experiment_id
    )
    known_pair_ids = set(validated_key["mapping"])
    normalized = _normalized_ratings(ratings, known_pair_ids)
    complete = len(normalized) == len(known_pair_ids)
    condition_rows: tuple[Mapping[str, object], ...] = ()
    receipt: Mapping[str, object] | None = None
    if complete:
        ordered_normalized = sorted(normalized, key=lambda row: row["pair_id"])
        interpreted = _condition_ratings(
            ordered_normalized, validated_key["mapping"]
        )
        condition_rows = tuple(MappingProxyType(dict(row)) for row in interpreted)
        receipt_payload = {
            "schema_version": SCHEMA_VERSION,
            "experiment_id": package.experiment_id,
            "package_id": package.package_id,
            "public_bundle_digest": package.public_bundle_digest,
            "ratings_digest": _digest(ordered_normalized),
            "coverage_count": len(normalized),
        }
        receipt_dict = {
            **receipt_payload,
            "mac": _mac(secret, "review-receipt", receipt_payload),
        }
        receipt = MappingProxyType(receipt_dict)
    if expected_receipt is not None:
        if (
            receipt is None
            or not isinstance(expected_receipt, Mapping)
            or set(expected_receipt) != _RECEIPT_FIELDS
            or _canonical_json(dict(expected_receipt)) != _canonical_json(dict(receipt))
        ):
            raise ValueError("blind review receipt does not match the raw ratings")
    review = VerifiedBlindReview(
        _SEAL,
        experiment_id=package.experiment_id,
        package_id=package.package_id,
        public_bundle_digest=package.public_bundle_digest,
        generation_evidence_digest=package.generation_evidence_digest,
        coverage_count=len(normalized),
        expected_count=len(known_pair_ids),
        complete=complete,
        condition_ratings=condition_rows,
        receipt=receipt,
    )
    _ISSUED_REVIEWS[review] = _review_fingerprint(review)
    return review


def make_blind_pairs(
    baseline_rows: Sequence[dict], candidate_rows: Sequence[dict], seed: int
) -> list[dict]:
    """Return a fresh public-only wrapper whose discarded key cannot authorize readiness."""
    return make_blind_package("public-wrapper", baseline_rows, candidate_rows, seed)[0]
