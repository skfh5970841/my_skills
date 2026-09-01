import copy
import dataclasses
import hashlib
import json
import random
import re
import sys
from pathlib import Path

import pytest


AXES = (
    "request_fulfillment",
    "meaning_and_facts",
    "structure_and_information",
    "style_behavior",
    "over_imitation",
    "resource_use",
)
PUBLIC_PAIR_FIELDS = {
    "pair_id",
    "source_pair_id",
    "order",
    "seed",
    "generator_brief",
    "response_a",
    "response_b",
}
RAW_RATING_FIELDS = {
    "pair_id",
    "quality_preference",
    "style_preference",
    "overall_preference",
    "over_imitation",
    "meaning_or_fact_issue",
    "evidence_excerpt",
}
UNBLINDED_RATING_FIELDS = {
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


@pytest.fixture
def loop_modules():
    scripts = Path(__file__).resolve().parents[1] / "chaesajang-family-optimizer" / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        from optimizer_loop import blind, contracts, hypothesis, report, static_gate

        yield blind, contracts, hypothesis, report, static_gate
    finally:
        sys.path.remove(str(scripts))


def _generation_row(
    case_id,
    repeat,
    output,
    *,
    target_skill="chaesajang-style",
    brief=None,
):
    topic = case_id.removeprefix("case-")
    brief = brief or f"Explain the {topic} topic without evaluator metadata."
    prompt = f"stable prompt for {case_id}: {brief}"
    return {
        "case_id": case_id,
        "target_skill": target_skill,
        "repeat": repeat,
        "input": brief,
        "prompt": prompt,
        "output": output,
        "stderr": "",
        "command": ["codex", "exec"],
        "cwd": "C:/private/source",
        "source_root": "C:/private/source",
        "timeout_seconds": 30,
        "model": "gpt-5.6",
        "reasoning": "high",
        "runtime": "codex",
        "started_at": "2026-08-30T00:00:00+00:00",
        "elapsed_ms": 10,
        "status": "completed",
        "returncode": 0,
        "source_snapshot": {"SKILL.md": "1" * 64},
        "source_snapshot_after": {"SKILL.md": "1" * 64},
        "source_stable": True,
    }


@pytest.fixture
def baseline_rows():
    return [
        _generation_row("case-alpha", 1, "baseline word retained: old alpha"),
        _generation_row("case-alpha", 0, "old alpha zero"),
        _generation_row("case-beta", 0, "old beta"),
    ]


@pytest.fixture
def candidate_rows():
    return [
        _generation_row("case-beta", 0, "new beta with candidate word retained"),
        _generation_row("case-alpha", 0, "new alpha zero"),
        _generation_row("case-alpha", 1, "new alpha one"),
    ]


def _presentation_map(private_key):
    return private_key["presentations"]


def _raw_rating(pair_id, *, choice="candidate", private_key=None, **overrides):
    candidate_label = (
        _presentation_map(private_key)[pair_id]["candidate_label"]
        if private_key is not None
        else "A"
    )
    baseline_label = "B" if candidate_label == "A" else "A"
    selected = {
        "candidate": candidate_label,
        "baseline": baseline_label,
        "tie": "tie",
    }[choice]
    data = {
        "pair_id": pair_id,
        "quality_preference": selected,
        "style_preference": selected,
        "overall_preference": selected,
        "over_imitation": "neither",
        "meaning_or_fact_issue": {"A": "none", "B": "none"},
        "evidence_excerpt": "The response is concrete and preserves the requested meaning.",
    }
    data.update(overrides)
    return data


def _manifest(contracts):
    return contracts.ExperimentManifest.from_dict(
        {
            "experiment_id": "2026-08-30-001",
            "status": "auto_evaluated",
            "source_hashes": {"chaesajang-core/persona_core.md": "1" * 64},
            "model": "gpt-5.6",
            "runtime": "codex",
            "reasoning": "high",
            "dataset_versions": {"dev": "v1", "golden": "v1", "holdout": "v1"},
            "command": ["codex", "exec"],
            "created_at": "2026-08-30T12:00:00+09:00",
        }
    )


def _hypothesis(hypothesis_module, *, risk="behavior", blind_required=True, claim_ids=("claim",)):
    return hypothesis_module.Hypothesis(
        claim_ids=tuple(claim_ids),
        change_group="persona-layering",
        allowed_paths=("chaesajang-core/persona_core.md",),
        primary_axis="style_behavior",
        protected_axes=(
            "request_fulfillment",
            "meaning_and_facts",
            "structure_and_information",
        ),
        risk=risk,
        blind_required=blind_required,
        stop_rule="reject protected regressions",
        body="Change one instruction group.",
    )


def _gate(static_gate, *, passed=True, errors=()):
    return static_gate.GateResult(passed=passed, errors=tuple(errors), details={"checks": 5})


def _axis_bucket(pair_count=2, *, failed=0, not_scored=0):
    return {
        "passed": pair_count - failed - not_scored,
        "failed": failed,
        "not_scored": not_scored,
        "count": pair_count,
    }


def _passing_scores(pair_count=2):
    return {
        "row_count": pair_count * 2,
        "deterministic_row_count": pair_count * 2,
        "deterministic_pair_count": pair_count,
        "observed_pair_count": pair_count,
        "coverage_verified": True,
        "expected_pair_count": pair_count,
        "expected_golden_pair_count": 1,
        "axes": {
            axis: {
                "baseline": _axis_bucket(pair_count),
                "candidate": _axis_bucket(pair_count),
            }
            for axis in AXES
        },
        "hard_gate_failures": [],
        "golden_failures": [],
        "hard_gates_passed": True,
        "golden_passed": True,
        "judge": {"role": "supporting_only", "winner": "baseline"},
    }


def _unblinded_rating(source_pair_id, pair_id, order, *, vote="candidate", **overrides):
    row = {
        "pair_id": pair_id,
        "source_pair_id": source_pair_id,
        "case_id": f"case-{source_pair_id[-4:]}",
        "target_skill": "chaesajang-style",
        "repeat": int(source_pair_id[-1], 16) % 3,
        "order": order,
        "quality_preference": vote,
        "style_preference": vote,
        "overall_preference": vote,
        "candidate_over_imitation": False,
        "baseline_over_imitation": False,
        "candidate_meaning_or_fact_issue": "none",
        "baseline_meaning_or_fact_issue": "none",
        "evidence_excerpt": "Candidate keeps the meaning and is more complete.",
    }
    row.update(overrides)
    return row


def _complete_unblinded_ratings(votes=("candidate", "candidate")):
    rows = []
    for index, vote in enumerate(votes):
        source_pair_id = f"{index + 1:064x}"
        rows.extend(
            [
                _unblinded_rating(source_pair_id, f"{index * 2 + 10:064x}", "AB", vote=vote),
                _unblinded_rating(source_pair_id, f"{index * 2 + 11:064x}", "BA", vote=vote),
            ]
        )
    return rows


def _research_claim():
    return {
        "claim": "Progressive disclosure can reduce irrelevant context.",
        "source_url": "https://example.test/research",
        "source_date": "2026-08-01",
        "checked_at": "2026-08-30",
        "source_type": "peer_reviewed",
        "evidence": "A controlled comparison found lower irrelevant context use.",
        "confidence": "high",
        "local_evidence": ["chaesajang-core/persona_core.md"],
        "decision_impact": "Load one instruction group at a time.",
        "proposed_test": "Compare protected axes and blind preference.",
        "status": "actionable",
    }


def test_blind_package_is_public_only_balanced_mirrored_and_opaque(
    loop_modules, baseline_rows, candidate_rows
):
    blind, _, _, _, _ = loop_modules
    pairs, private_key = blind.make_blind_package(baseline_rows, candidate_rows, seed=7)

    assert len(pairs) == len(baseline_rows) * 2
    assert all(set(pair) == PUBLIC_PAIR_FIELDS for pair in pairs)
    assert blind.validate_order_balance(pairs) == []
    assert {pair["order"] for pair in pairs} == {"AB", "BA"}
    assert all(re.fullmatch(r"[0-9a-f]{64}", pair["pair_id"]) for pair in pairs)
    assert all(re.fullmatch(r"[0-9a-f]{64}", pair["source_pair_id"]) for pair in pairs)
    assert all(
        case_id not in pair["pair_id"] and case_id not in pair["source_pair_id"]
        for pair in pairs
        for case_id in ("case-alpha", "case-beta")
    )
    assert set(_presentation_map(private_key)) == {pair["pair_id"] for pair in pairs}
    assert set(private_key) == {"schema_version", "seed", "presentations"}


def test_blind_package_preserves_response_words_but_not_source_metadata(
    loop_modules, baseline_rows, candidate_rows
):
    blind, _, _, _, _ = loop_modules
    pairs = blind.make_blind_pairs(baseline_rows, candidate_rows, seed=7)
    encoded = json.dumps(pairs, ensure_ascii=False)

    assert "baseline word retained" in encoded
    assert "candidate word retained" in encoded
    for forbidden in (
        "case-alpha",
        "case-beta",
        "chaesajang-style",
        "gpt-5.6",
        "codex",
        "C:/private/source",
        "source_snapshot",
        "prompt",
        "command",
        "elapsed_ms",
        "stderr",
    ):
        assert forbidden not in encoded


def test_blind_package_is_byte_stable_for_reversed_inputs_and_does_not_touch_global_rng(
    loop_modules, baseline_rows, candidate_rows
):
    blind, _, _, _, _ = loop_modules
    random.seed(12345)
    before = random.getstate()
    first_pairs, first_key = blind.make_blind_package(baseline_rows, candidate_rows, seed=19)
    after = random.getstate()
    second_pairs, second_key = blind.make_blind_package(
        list(reversed(baseline_rows)), list(reversed(candidate_rows)), seed=19
    )

    assert before == after
    assert json.dumps(first_pairs, sort_keys=True, ensure_ascii=False).encode() == json.dumps(
        second_pairs, sort_keys=True, ensure_ascii=False
    ).encode()
    assert json.dumps(first_key, sort_keys=True, ensure_ascii=False).encode() == json.dumps(
        second_key, sort_keys=True, ensure_ascii=False
    ).encode()
    assert blind.make_blind_pairs(baseline_rows, candidate_rows, 19) == first_pairs


def test_private_key_digest_is_canonical_and_changes_with_mapping(
    loop_modules, baseline_rows, candidate_rows
):
    blind, _, _, _, _ = loop_modules
    _, key = blind.make_blind_package(baseline_rows, candidate_rows, seed=3)
    reordered = {
        "presentations": dict(reversed(list(key["presentations"].items()))),
        "seed": key["seed"],
        "schema_version": key["schema_version"],
    }
    mutated = copy.deepcopy(key)
    first_id = next(iter(mutated["presentations"]))
    mutated["presentations"][first_id]["candidate_label"] = (
        "B" if mutated["presentations"][first_id]["candidate_label"] == "A" else "A"
    )

    assert re.fullmatch(r"[0-9a-f]{64}", blind.private_key_digest(key))
    assert blind.private_key_digest(key) == blind.private_key_digest(reordered)
    assert blind.private_key_digest(key) != blind.private_key_digest(mutated)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda b, c: c.pop(), "inventory"),
        (lambda b, c: b.append(copy.deepcopy(b[0])), "duplicate"),
        (lambda b, c: c[0].update({"status": "blocked_external"}), "completed"),
        (lambda b, c: b[0].update({"source_stable": False}), "stable"),
        (lambda b, c: c[0].update({"output": "   "}), "output"),
        (lambda b, c: c[0].update({"model": "different"}), "parity"),
        (lambda b, c: c[0].update({"prompt": "different"}), "parity"),
        (lambda b, c: c[0].update({"input": "different"}), "parity"),
    ],
)
def test_blind_package_rejects_unmatched_duplicate_invalid_or_nonparity_rows(
    loop_modules, baseline_rows, candidate_rows, mutation, message
):
    blind, _, _, _, _ = loop_modules
    baseline = copy.deepcopy(baseline_rows)
    candidate = copy.deepcopy(candidate_rows)
    mutation(baseline, candidate)

    with pytest.raises((TypeError, ValueError), match=message):
        blind.make_blind_package(baseline, candidate, seed=7)


def test_blind_package_rejects_case_id_leaked_by_generator_brief(loop_modules):
    blind, _, _, _, _ = loop_modules
    baseline = [_generation_row("case-secret", 0, "old", brief="Discuss case-secret")]
    candidate = [_generation_row("case-secret", 0, "new", brief="Discuss case-secret")]

    with pytest.raises(ValueError, match="generator brief|case_id"):
        blind.make_blind_package(baseline, candidate, seed=7)


def test_validate_order_balance_reports_strict_schema_duplicates_and_nonmirrors(
    loop_modules, baseline_rows, candidate_rows
):
    blind, _, _, _, _ = loop_modules
    pairs = blind.make_blind_pairs(baseline_rows, candidate_rows, seed=7)

    unknown = copy.deepcopy(pairs)
    unknown[0]["candidate_label"] = "A"
    duplicate = copy.deepcopy(pairs)
    duplicate[1]["pair_id"] = duplicate[0]["pair_id"]
    nonmirror = copy.deepcopy(pairs)
    nonmirror[1]["response_a"] = "not mirrored"
    missing = copy.deepcopy(pairs[:-1])

    assert blind.validate_order_balance(unknown)
    assert blind.validate_order_balance(duplicate)
    assert blind.validate_order_balance(nonmirror)
    assert blind.validate_order_balance(missing)


def test_normalize_human_rating_is_strict_and_preserves_safe_evidence(loop_modules):
    blind, _, _, _, _ = loop_modules
    pair_id = "a" * 64
    evidence = "  concise evidence\nwith a second line  "
    raw = _raw_rating(pair_id, evidence_excerpt=evidence)

    normalized = blind.normalize_human_rating(raw, {pair_id})

    assert normalized == raw
    assert normalized["evidence_excerpt"] == evidence
    assert set(normalized) == RAW_RATING_FIELDS


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda row: row.pop("overall_preference"), "missing"),
        (lambda row: row.update({"extra": True}), "unknown"),
        (lambda row: row.update({"quality_preference": "candidate"}), "preference"),
        (lambda row: row.update({"over_imitation": "candidate"}), "over_imitation"),
        (lambda row: row.update({"meaning_or_fact_issue": {"A": "none"}}), "meaning_or_fact_issue"),
        (
            lambda row: row.update(
                {"meaning_or_fact_issue": {"A": "none", "B": "severe"}}
            ),
            "meaning_or_fact_issue",
        ),
        (lambda row: row.update({"evidence_excerpt": "  "}), "evidence"),
        (lambda row: row.update({"evidence_excerpt": "x" * 501}), "500"),
        (lambda row: row.update({"pair_id": "b" * 64}), "known"),
    ],
)
def test_normalize_human_rating_rejects_malformed_or_unknown_responses(
    loop_modules, mutation, message
):
    blind, _, _, _, _ = loop_modules
    pair_id = "a" * 64
    raw = _raw_rating(pair_id)
    mutation(raw)

    with pytest.raises((TypeError, ValueError), match=message):
        blind.normalize_human_rating(raw, {pair_id})


def test_unblind_human_ratings_maps_condition_fields_without_exposing_private_map(
    loop_modules, baseline_rows, candidate_rows
):
    blind, _, _, _, _ = loop_modules
    pairs, private_key = blind.make_blind_package(baseline_rows[:1], candidate_rows[2:], seed=7)
    ratings = []
    for pair in pairs:
        candidate_label = private_key["presentations"][pair["pair_id"]]["candidate_label"]
        baseline_label = "B" if candidate_label == "A" else "A"
        ratings.append(
            _raw_rating(
                pair["pair_id"],
                private_key=private_key,
                over_imitation=candidate_label,
                meaning_or_fact_issue={candidate_label: "minor", baseline_label: "critical"},
            )
        )

    unblinded = blind.unblind_human_ratings(ratings, private_key)

    assert len(unblinded) == 2
    assert all(set(row) == UNBLINDED_RATING_FIELDS for row in unblinded)
    assert all(row["quality_preference"] == "candidate" for row in unblinded)
    assert all(row["style_preference"] == "candidate" for row in unblinded)
    assert all(row["overall_preference"] == "candidate" for row in unblinded)
    assert all(row["candidate_over_imitation"] is True for row in unblinded)
    assert all(row["baseline_over_imitation"] is False for row in unblinded)
    assert all(row["candidate_meaning_or_fact_issue"] == "minor" for row in unblinded)
    assert all(row["baseline_meaning_or_fact_issue"] == "critical" for row in unblinded)
    assert "candidate_label" not in json.dumps(unblinded)
    assert "presentations" not in json.dumps(unblinded)


@pytest.mark.parametrize("mode", ["duplicate", "unknown", "missing"])
def test_unblind_human_ratings_requires_exact_private_key_coverage(
    loop_modules, baseline_rows, candidate_rows, mode
):
    blind, _, _, _, _ = loop_modules
    pairs, private_key = blind.make_blind_package(baseline_rows[:1], candidate_rows[2:], seed=11)
    ratings = [_raw_rating(pair["pair_id"], private_key=private_key) for pair in pairs]
    if mode == "duplicate":
        ratings[1] = copy.deepcopy(ratings[0])
    elif mode == "unknown":
        ratings[0]["pair_id"] = "f" * 64
    else:
        ratings.pop()

    with pytest.raises(ValueError, match="duplicate|unknown|missing|coverage"):
        blind.unblind_human_ratings(ratings, private_key)


def test_readiness_rejects_valid_static_gate_failure_and_invalidates_gate_inconsistency(
    loop_modules
):
    _, contracts, hypothesis_module, report, static_gate = loop_modules
    manifest = _manifest(contracts)
    hypothesis = _hypothesis(hypothesis_module, risk="low", blind_required=False)
    scores = _passing_scores()

    assert report.decide_readiness(
        manifest, hypothesis, _gate(static_gate, passed=False, errors=("drift",)), scores, []
    ) == "rejected"
    assert report.decide_readiness(
        manifest, hypothesis, _gate(static_gate, passed=True, errors=("drift",)), scores, []
    ) == "invalid"
    assert report.decide_readiness(
        manifest, hypothesis, _gate(static_gate, passed=False, errors=()), scores, []
    ) == "invalid"


@pytest.mark.parametrize(
    "mutation",
    [
        lambda score: score.pop("coverage_verified"),
        lambda score: score.update({"coverage_verified": False}),
        lambda score: score.update({"expected_pair_count": None}),
        lambda score: score.update({"expected_pair_count": 0}),
        lambda score: score.update({"observed_pair_count": 1}),
        lambda score: score.update({"deterministic_pair_count": 1}),
        lambda score: score.update({"deterministic_row_count": 3}),
        lambda score: score.update({"expected_golden_pair_count": 0}),
        lambda score: score.update({"hard_gates_passed": None}),
        lambda score: score.update({"golden_passed": None}),
        lambda score: score["axes"].pop("resource_use"),
        lambda score: score["axes"]["style_behavior"]["candidate"].update({"count": 1}),
        lambda score: score["axes"]["style_behavior"]["candidate"].update({"passed": 1}),
    ],
)
def test_readiness_is_invalid_for_missing_or_inconsistent_score_provenance(
    loop_modules, mutation
):
    _, contracts, hypothesis_module, report, static_gate = loop_modules
    scores = _passing_scores()
    mutation(scores)

    assert report.decide_readiness(
        _manifest(contracts),
        _hypothesis(hypothesis_module, risk="low", blind_required=False),
        _gate(static_gate),
        scores,
        [],
    ) == "invalid"


@pytest.mark.parametrize(
    ("flag", "failures_key", "failure"),
    [
        (
            "hard_gates_passed",
            "hard_gate_failures",
            {"case_id": "case-a", "split": "golden", "repeat": 0, "axis": "meaning_and_facts"},
        ),
        (
            "golden_passed",
            "golden_failures",
            {"case_id": "case-a", "split": "golden", "repeat": 0, "axis": "style_behavior"},
        ),
    ],
)
def test_readiness_rejects_explicit_task7_hard_or_golden_failures(
    loop_modules, flag, failures_key, failure
):
    _, contracts, hypothesis_module, report, static_gate = loop_modules
    scores = _passing_scores()
    scores[flag] = False
    scores[failures_key] = [failure]
    scores["axes"][failure["axis"]]["candidate"] = _axis_bucket(failed=1)

    assert report.decide_readiness(
        _manifest(contracts),
        _hypothesis(hypothesis_module, risk="low", blind_required=False),
        _gate(static_gate),
        scores,
        [],
    ) == "rejected"


def test_readiness_ignores_judge_content_entirely(loop_modules):
    _, contracts, hypothesis_module, report, static_gate = loop_modules
    manifest = _manifest(contracts)
    hypothesis = _hypothesis(hypothesis_module, risk="low", blind_required=False)
    first = _passing_scores()
    second = copy.deepcopy(first)
    first["judge"] = {"winner": "baseline", "malformed": [object()]}
    second["judge"] = "candidate wins every judge row"

    first_decision = report.decide_readiness(
        manifest, hypothesis, _gate(static_gate), first, []
    )
    second_decision = report.decide_readiness(
        manifest, hypothesis, _gate(static_gate), second, []
    )
    assert first_decision == second_decision == "ready_for_approval"


def test_readiness_invalidates_unscored_primary_or_protected_candidate_axis(loop_modules):
    _, contracts, hypothesis_module, report, static_gate = loop_modules
    for axis in ("style_behavior", "meaning_and_facts"):
        scores = _passing_scores()
        scores["axes"][axis]["candidate"] = _axis_bucket(not_scored=1)
        assert report.decide_readiness(
            _manifest(contracts),
            _hypothesis(hypothesis_module, risk="low", blind_required=False),
            _gate(static_gate),
            scores,
            [],
        ) == "invalid"


def test_task7_hard_gate_not_scored_stays_invalid_not_rejected(loop_modules):
    _, contracts, hypothesis_module, report, static_gate = loop_modules
    scores = _passing_scores()
    scores["axes"]["meaning_and_facts"]["candidate"] = _axis_bucket(not_scored=1)
    scores["hard_gates_passed"] = False
    scores["hard_gate_failures"] = [
        {
            "case_id": "case-a",
            "split": "golden",
            "repeat": 0,
            "axis": "meaning_and_facts",
        }
    ]

    assert report.decide_readiness(
        _manifest(contracts),
        _hypothesis(hypothesis_module, risk="low", blind_required=False),
        _gate(static_gate),
        scores,
        [],
    ) == "invalid"


@pytest.mark.parametrize("bucket", ["failed", "not_scored"])
def test_readiness_invalidates_passing_hard_gate_flag_that_contradicts_axis_buckets(
    loop_modules, bucket
):
    _, contracts, hypothesis_module, report, static_gate = loop_modules
    scores = _passing_scores()
    contradictory = _axis_bucket(**{bucket: 1})
    scores["axes"]["request_fulfillment"]["baseline"] = copy.deepcopy(
        contradictory
    )
    scores["axes"]["request_fulfillment"]["candidate"] = contradictory
    hypothesis = dataclasses.replace(
        _hypothesis(hypothesis_module, risk="low", blind_required=False),
        protected_axes=("structure_and_information",),
    )

    assert report.decide_readiness(
        _manifest(contracts),
        hypothesis,
        _gate(static_gate),
        scores,
        [],
    ) == "invalid"


def test_readiness_invalidates_malformed_manifest_source_hash(loop_modules):
    _, contracts, hypothesis_module, report, static_gate = loop_modules
    manifest = dataclasses.replace(
        _manifest(contracts),
        source_hashes={"chaesajang-core/persona_core.md": "not-a-sha256"},
    )

    assert report.decide_readiness(
        manifest,
        _hypothesis(hypothesis_module, risk="low", blind_required=False),
        _gate(static_gate),
        _passing_scores(),
        [],
    ) == "invalid"


@pytest.mark.parametrize(
    "status",
    [
        "researching",
        "hypothesis_ready",
        "baseline_captured",
        "candidate_ready",
        "ready_for_approval",
        "promoted",
    ],
)
def test_readiness_is_invalid_outside_auto_evaluated_or_awaiting_human(
    loop_modules, status
):
    _, contracts, hypothesis_module, report, static_gate = loop_modules
    manifest = dataclasses.replace(
        _manifest(contracts), status=contracts.ExperimentStatus(status)
    )

    assert report.decide_readiness(
        manifest,
        _hypothesis(hypothesis_module, risk="low", blind_required=False),
        _gate(static_gate),
        _passing_scores(),
        [],
    ) == "invalid"


def test_readiness_rejects_candidate_failure_regression_on_protected_axis(loop_modules):
    _, contracts, hypothesis_module, report, static_gate = loop_modules
    scores = _passing_scores()
    scores["axes"]["structure_and_information"]["candidate"] = _axis_bucket(failed=1)

    assert report.decide_readiness(
        _manifest(contracts),
        _hypothesis(hypothesis_module, risk="low", blind_required=False),
        _gate(static_gate),
        scores,
        [],
    ) == "rejected"


def test_low_static_change_can_be_ready_but_any_nonlow_or_explicit_blind_waits(loop_modules):
    _, contracts, hypothesis_module, report, static_gate = loop_modules
    manifest = _manifest(contracts)
    gate = _gate(static_gate)
    scores = _passing_scores()

    assert report.decide_readiness(
        manifest,
        _hypothesis(hypothesis_module, risk="low", blind_required=False),
        gate,
        scores,
        [],
    ) == "ready_for_approval"
    assert report.decide_readiness(
        manifest,
        _hypothesis(hypothesis_module, risk="behavior", blind_required=False),
        gate,
        scores,
        [],
    ) == "awaiting_human"
    assert report.decide_readiness(
        manifest,
        _hypothesis(hypothesis_module, risk="low", blind_required=True),
        gate,
        scores,
        [],
    ) == "awaiting_human"


def test_human_required_partial_ratings_wait_and_complete_strict_candidate_vote_is_ready(
    loop_modules
):
    _, contracts, hypothesis_module, report, static_gate = loop_modules
    args = (
        _manifest(contracts),
        _hypothesis(hypothesis_module),
        _gate(static_gate),
        _passing_scores(),
    )
    complete = _complete_unblinded_ratings()

    assert report.decide_readiness(*args, complete[:3]) == "awaiting_human"
    assert report.decide_readiness(*args, complete) == "ready_for_approval"


@pytest.mark.parametrize("review_shape", ["baseline", "split", "inconsistent"])
def test_completed_human_review_without_strict_candidate_source_preference_is_rejected(
    loop_modules, review_shape
):
    _, contracts, hypothesis_module, report, static_gate = loop_modules
    if review_shape == "baseline":
        ratings = _complete_unblinded_ratings(("baseline", "baseline"))
    elif review_shape == "split":
        ratings = _complete_unblinded_ratings(("candidate", "baseline"))
    else:
        ratings = _complete_unblinded_ratings(("candidate", "candidate"))
        ratings[1]["overall_preference"] = "baseline"
        ratings[3]["overall_preference"] = "baseline"

    assert report.decide_readiness(
        _manifest(contracts),
        _hypothesis(hypothesis_module),
        _gate(static_gate),
        _passing_scores(),
        ratings,
    ) == "rejected"


@pytest.mark.parametrize(
    "override",
    [
        {"candidate_over_imitation": True},
        {"candidate_meaning_or_fact_issue": "critical"},
    ],
)
def test_human_review_rejects_candidate_over_imitation_or_critical_issue(loop_modules, override):
    _, contracts, hypothesis_module, report, static_gate = loop_modules
    ratings = _complete_unblinded_ratings()
    ratings[0].update(override)

    assert report.decide_readiness(
        _manifest(contracts),
        _hypothesis(hypothesis_module),
        _gate(static_gate),
        _passing_scores(),
        ratings,
    ) == "rejected"


def test_partial_human_review_with_decisive_candidate_harm_is_rejected(loop_modules):
    _, contracts, hypothesis_module, report, static_gate = loop_modules
    ratings = _complete_unblinded_ratings()[:1]
    ratings[0]["candidate_meaning_or_fact_issue"] = "critical"

    assert report.decide_readiness(
        _manifest(contracts),
        _hypothesis(hypothesis_module),
        _gate(static_gate),
        _passing_scores(),
        ratings,
    ) == "rejected"


def _report_inputs(loop_modules):
    blind, contracts, hypothesis_module, report, static_gate = loop_modules
    claim = _research_claim()
    claim_id = report.research_claim_id(claim)
    hypothesis = _hypothesis(hypothesis_module, claim_ids=(claim_id,))
    key = {
        "schema_version": 1,
        "seed": 7,
        "presentations": {
            "a" * 64: {
                "source_pair_id": "1" * 64,
                "candidate_label": "A",
                "case_id": "case-one",
                "target_skill": "chaesajang-style",
                "repeat": 0,
                "order": "AB",
            },
            "b" * 64: {
                "source_pair_id": "1" * 64,
                "candidate_label": "B",
                "case_id": "case-one",
                "target_skill": "chaesajang-style",
                "repeat": 0,
                "order": "BA",
            },
        },
    }
    return {
        "manifest": _manifest(contracts),
        "hypothesis": hypothesis,
        "gate": _gate(static_gate),
        "scores": _passing_scores(),
        "ratings": _complete_unblinded_ratings(),
        "research_claims": [claim],
        "one_change_diff": "--- a/rule.md\n+++ b/rule.md\n-<old>\n+<new>\n",
        "raw_artifacts": [
            {
                "relative_path": "experiments/2026-08-30-001/baseline.jsonl",
                "sha256": "d" * 64,
                "argv": ["python", "scripts/loop.py", "report", "--experiment", "2026-08-30-001"],
            }
        ],
        "regressions": ["No protected regression observed."],
        "blind_summary": {
            "source_pair_count": 2,
            "presentation_count": 4,
            "seed": 7,
            "private_key_digest": blind.private_key_digest(key),
        },
        "promotion_files": ["chaesajang-core/persona_core.md"],
        "limitations": ["<script>alert('one user')</script>"],
        "decision": "ready_for_approval",
    }


def test_build_report_is_pure_deterministic_escaped_and_complete(loop_modules, tmp_path):
    _, _, _, report, _ = loop_modules
    inputs = _report_inputs(loop_modules)
    before = set(tmp_path.iterdir())

    first = report.build_report(**inputs)
    second = report.build_report(**copy.deepcopy(inputs))

    assert first.encode("utf-8") == second.encode("utf-8")
    assert set(tmp_path.iterdir()) == before
    for heading in (
        "# Decision",
        "## Hypothesis",
        "## Research Claims and Local Evidence",
        "## One-Change Diff",
        "## Artifact Paths",
        "## Per-Axis Results",
        "## Regressions",
        "## Human Ratings",
        "## Reproducibility",
        "## Promotion Files",
        "## Limitations",
    ):
        assert heading in first
    for axis in AXES:
        assert axis in first
    assert "not_scored" in first
    assert "0" in first
    assert "이 결과는 사용자 1인의 선호이며, 통계적 우월성을 의미하지 않습니다." in first
    assert "&lt;script&gt;" in first
    assert "<script>" not in first
    assert "&lt;old&gt;" in first
    assert "candidate_label" not in first
    assert '"presentations"' not in first
    assert "C:/private/source" not in first


def test_build_report_normalizes_task6_absolute_cd_and_keeps_exact_argv_digest(
    loop_modules, tmp_path
):
    _, _, _, report, _ = loop_modules
    inputs = _report_inputs(loop_modules)
    source_root = (tmp_path / "candidate-source").resolve()
    command = (
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
        "gpt-5.6",
        "--config",
        'model_reasoning_effort="high"',
        "--cd",
        str(source_root),
        "-",
    )
    inputs["manifest"] = dataclasses.replace(inputs["manifest"], command=command)
    inputs["raw_artifacts"][0]["argv"] = list(command)
    expected_digest = hashlib.sha256(
        json.dumps(
            command,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()

    rendered = report.build_report(**inputs)

    assert str(source_root) not in rendered
    assert "absolute `--cd` roots normalized to `.`" in rendered
    assert expected_digest in rendered


def test_rejected_report_lists_static_hard_and_golden_failure_details(loop_modules):
    _, _, _, report, static_gate = loop_modules
    inputs = _report_inputs(loop_modules)
    failure = {
        "case_id": "case-gate-detail",
        "split": "golden",
        "repeat": 1,
        "axis": "meaning_and_facts",
    }
    inputs["gate"] = _gate(
        static_gate,
        passed=False,
        errors=("chaesajang-style: adapter drift",),
    )
    inputs["scores"]["axes"]["meaning_and_facts"]["candidate"] = (
        _axis_bucket(failed=1)
    )
    inputs["scores"]["hard_gate_failures"] = [failure]
    inputs["scores"]["golden_failures"] = [failure]
    inputs["scores"]["hard_gates_passed"] = False
    inputs["scores"]["golden_passed"] = False
    inputs["decision"] = "rejected"

    rendered = report.build_report(**inputs)

    assert "### Static Gate Failures" in rendered
    assert "chaesajang-style: adapter drift" in rendered
    assert "### Hard Gate Failures" in rendered
    assert "### Golden Failures" in rendered
    assert "case-gate-detail" in rendered


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data["raw_artifacts"][0].update({"relative_path": "C:/private/raw.jsonl"}),
        lambda data: data["raw_artifacts"][0].update({"relative_path": "../raw.jsonl"}),
        lambda data: data.update({"promotion_files": ["/private/canonical.md"]}),
        lambda data: data.update({"promotion_files": ["../canonical.md"]}),
        lambda data: data["raw_artifacts"][0].update({"sha256": "not-a-hash"}),
        lambda data: data["raw_artifacts"][0].update({"argv": "python loop.py"}),
        lambda data: data["raw_artifacts"][0].update({"argv": ["python", "C:/private/loop.py"]}),
        lambda data: data["blind_summary"].update({"presentations": {}}),
        lambda data: data.update({"limitations": ["See /home/user/private/report.json"]}),
        lambda data: data.update({"regressions": [{"raw_output": "private output"}]}),
    ],
)
def test_build_report_rejects_unsafe_paths_hashes_commands_or_private_mapping(
    loop_modules, mutation
):
    _, _, _, report, _ = loop_modules
    inputs = _report_inputs(loop_modules)
    mutation(inputs)

    with pytest.raises((TypeError, ValueError)):
        report.build_report(**inputs)


def test_build_report_rejects_unresolved_claim_and_decision_mismatch(loop_modules):
    _, _, hypothesis_module, report, _ = loop_modules
    inputs = _report_inputs(loop_modules)
    inputs["hypothesis"] = dataclasses.replace(
        inputs["hypothesis"], claim_ids=("f" * 64,)
    )
    with pytest.raises(ValueError, match="claim"):
        report.build_report(**inputs)

    inputs = _report_inputs(loop_modules)
    inputs["decision"] = "rejected"
    with pytest.raises(ValueError, match="decision"):
        report.build_report(**inputs)
