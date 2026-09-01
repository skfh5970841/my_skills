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
    "source_id",
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
    return private_key["mapping"]


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


def _passing_scores(pair_count=2, *, generation_evidence_digest=None):
    scores = {
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
    if generation_evidence_digest is not None:
        scores["generation_evidence_digest"] = generation_evidence_digest
    return scores


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


def _static_hypothesis(hypothesis_module, *, claim_ids=("claim",)):
    return hypothesis_module.Hypothesis(
        claim_ids=tuple(claim_ids),
        change_group="packaging/static-sync",
        allowed_paths=("sync_core.py",),
        primary_axis="resource_use",
        protected_axes=(
            "request_fulfillment",
            "meaning_and_facts",
            "structure_and_information",
        ),
        risk="low",
        blind_required=False,
        stop_rule="reject protected regressions",
        body="Synchronize a static package manifest.",
    )


def _bind_v2_evidence(report, manifest, hypothesis):
    claim = _research_claim()
    claim_id = report.research_claim_id(claim)
    bound_hypothesis = dataclasses.replace(hypothesis, claim_ids=(claim_id,))
    patch = "".join(
        f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-old\n+new\n"
        for path in bound_hypothesis.allowed_paths
    )
    change = report.verify_change_assessment(bound_hypothesis, patch)
    research = report.verify_research_evidence(
        manifest.experiment_id, bound_hypothesis, [claim]
    )
    return bound_hypothesis, change, research


def _decide_v2(
    loop_modules,
    *,
    manifest=None,
    hypothesis=None,
    gate=None,
    scores=None,
    review=None,
):
    _, contracts, hypothesis_module, report, static_gate = loop_modules
    checked_manifest = manifest if manifest is not None else _manifest(contracts)
    checked_hypothesis = (
        hypothesis if hypothesis is not None else _static_hypothesis(hypothesis_module)
    )
    checked_hypothesis, change, research = _bind_v2_evidence(
        report, checked_manifest, checked_hypothesis
    )
    return report.decide_readiness(
        checked_manifest,
        checked_hypothesis,
        gate if gate is not None else _gate(static_gate),
        scores if scores is not None else _passing_scores(),
        review,
        change,
        research,
    )


def test_blind_package_is_public_only_balanced_mirrored_and_opaque(
    loop_modules, baseline_rows, candidate_rows
):
    blind, _, _, _, _ = loop_modules
    pairs, private_key = blind.make_blind_package(
        "2026-08-30-001", baseline_rows, candidate_rows, seed=7
    )

    assert len(pairs) == len(baseline_rows) * 2
    assert all(set(pair) == PUBLIC_PAIR_FIELDS for pair in pairs)
    assert blind.validate_order_balance(pairs) == []
    assert all(re.fullmatch(r"[0-9a-f]{64}", pair["pair_id"]) for pair in pairs)
    assert all(
        case_id not in pair["pair_id"]
        for pair in pairs
        for case_id in ("case-alpha", "case-beta")
    )
    assert set(_presentation_map(private_key)) == {pair["pair_id"] for pair in pairs}
    assert set(private_key) == V2_PRIVATE_KEY_FIELDS


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
    first_pairs, first_key = blind.make_blind_package(
        "2026-08-30-001", baseline_rows, candidate_rows, seed=19
    )
    after = random.getstate()
    rebuilt = blind.rebuild_blind_package(
        "2026-08-30-001",
        list(reversed(baseline_rows)),
        list(reversed(candidate_rows)),
        first_key,
    )
    second_pairs, _second_key = blind.make_blind_package(
        "2026-08-30-001", baseline_rows, candidate_rows, seed=19
    )

    assert before == after
    assert json.dumps(first_pairs, sort_keys=True, ensure_ascii=False).encode() == json.dumps(
        rebuilt, sort_keys=True, ensure_ascii=False
    ).encode()
    assert {row["pair_id"] for row in first_pairs}.isdisjoint(
        {row["pair_id"] for row in second_pairs}
    )


def test_private_key_digest_is_canonical_and_changes_with_mapping(
    loop_modules, baseline_rows, candidate_rows
):
    blind, _, _, _, _ = loop_modules
    _, key = blind.make_blind_package(
        "2026-08-30-001", baseline_rows, candidate_rows, seed=3
    )
    reordered = dict(reversed(list(key.items())))
    mutated = copy.deepcopy(key)
    first_id = next(iter(mutated["mapping"]))
    mutated["mapping"][first_id]["candidate_label"] = (
        "B" if mutated["mapping"][first_id]["candidate_label"] == "A" else "A"
    )

    assert re.fullmatch(r"[0-9a-f]{64}", blind.private_key_digest(key))
    assert blind.private_key_digest(key) == blind.private_key_digest(reordered)
    with pytest.raises(ValueError):
        blind.private_key_digest(mutated)


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
        blind.make_blind_package("2026-08-30-001", baseline, candidate, seed=7)


def test_blind_package_rejects_case_id_leaked_by_generator_brief(loop_modules):
    blind, _, _, _, _ = loop_modules
    baseline = [_generation_row("case-secret", 0, "old", brief="Discuss case-secret")]
    candidate = [_generation_row("case-secret", 0, "new", brief="Discuss case-secret")]

    with pytest.raises(ValueError, match="generator brief|case_id"):
        blind.make_blind_package("2026-08-30-001", baseline, candidate, seed=7)


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
    pairs, private_key = blind.make_blind_package(
        "2026-08-30-001", baseline_rows[:1], candidate_rows[2:], seed=7
    )
    ratings = []
    for pair in pairs:
        candidate_label = private_key["mapping"][pair["pair_id"]]["candidate_label"]
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
    pairs, private_key = blind.make_blind_package(
        "2026-08-30-001", baseline_rows[:1], candidate_rows[2:], seed=11
    )
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
    _, _, _, _, static_gate = loop_modules
    scores = _passing_scores()

    assert _decide_v2(
        loop_modules,
        gate=_gate(static_gate, passed=False, errors=("drift",)),
        scores=scores,
    ) == "rejected"
    assert _decide_v2(
        loop_modules,
        gate=_gate(static_gate, passed=True, errors=("drift",)),
        scores=scores,
    ) == "invalid"
    assert _decide_v2(
        loop_modules,
        gate=_gate(static_gate, passed=False, errors=()),
        scores=scores,
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
    scores = _passing_scores()
    mutation(scores)

    assert _decide_v2(loop_modules, scores=scores) == "invalid"


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
    scores = _passing_scores()
    scores[flag] = False
    scores[failures_key] = [failure]
    scores["axes"][failure["axis"]]["candidate"] = _axis_bucket(failed=1)

    assert _decide_v2(loop_modules, scores=scores) == "rejected"


def test_readiness_ignores_judge_content_entirely(loop_modules):
    first = _passing_scores()
    second = copy.deepcopy(first)
    first["judge"] = {"winner": "baseline", "malformed": [object()]}
    second["judge"] = "candidate wins every judge row"

    first_decision = _decide_v2(loop_modules, scores=first)
    second_decision = _decide_v2(loop_modules, scores=second)
    assert first_decision == second_decision == "ready_for_approval"


def test_readiness_invalidates_unscored_primary_or_protected_candidate_axis(loop_modules):
    _, _, hypothesis_module, _, _ = loop_modules
    for axis in ("style_behavior", "meaning_and_facts"):
        scores = _passing_scores()
        scores["axes"][axis]["candidate"] = _axis_bucket(not_scored=1)
        assert _decide_v2(
            loop_modules,
            hypothesis=_hypothesis(
                hypothesis_module, risk="low", blind_required=False
            ),
            scores=scores,
        ) == "invalid"


def test_task7_hard_gate_not_scored_stays_invalid_not_rejected(loop_modules):
    _, _, hypothesis_module, _, _ = loop_modules
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

    assert _decide_v2(
        loop_modules,
        hypothesis=_hypothesis(
            hypothesis_module, risk="low", blind_required=False
        ),
        scores=scores,
    ) == "invalid"


@pytest.mark.parametrize("bucket", ["failed", "not_scored"])
def test_readiness_invalidates_passing_hard_gate_flag_that_contradicts_axis_buckets(
    loop_modules, bucket
):
    _, _, hypothesis_module, _, _ = loop_modules
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

    assert _decide_v2(
        loop_modules, hypothesis=hypothesis, scores=scores
    ) == "invalid"


def test_readiness_invalidates_malformed_manifest_source_hash(loop_modules):
    _, contracts, _, _, _ = loop_modules
    manifest = dataclasses.replace(
        _manifest(contracts),
        source_hashes={"chaesajang-core/persona_core.md": "not-a-sha256"},
    )

    assert _decide_v2(loop_modules, manifest=manifest) == "invalid"


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
    _, contracts, _, _, _ = loop_modules
    manifest = dataclasses.replace(
        _manifest(contracts), status=contracts.ExperimentStatus(status)
    )

    assert _decide_v2(loop_modules, manifest=manifest) == "invalid"


def test_readiness_rejects_candidate_failure_regression_on_protected_axis(loop_modules):
    _, _, hypothesis_module, _, _ = loop_modules
    scores = _passing_scores()
    scores["axes"]["structure_and_information"]["candidate"] = _axis_bucket(failed=1)

    assert _decide_v2(
        loop_modules,
        hypothesis=_hypothesis(
            hypothesis_module, risk="low", blind_required=False
        ),
        scores=scores,
    ) == "rejected"


def test_low_static_change_can_be_ready_but_any_nonlow_or_explicit_blind_waits(loop_modules):
    _, _, hypothesis_module, _, _ = loop_modules

    assert _decide_v2(loop_modules) == "ready_for_approval"
    assert _decide_v2(
        loop_modules,
        hypothesis=_hypothesis(
            hypothesis_module, risk="behavior", blind_required=False
        ),
    ) == "awaiting_human"
    assert _decide_v2(
        loop_modules,
        hypothesis=_hypothesis(
            hypothesis_module, risk="low", blind_required=True
        ),
    ) == "awaiting_human"


def test_raw_unblinded_ratings_cannot_authorize_readiness(loop_modules):
    _, contracts, hypothesis_module, report, static_gate = loop_modules
    manifest = _manifest(contracts)
    hypothesis, change, research = _bind_v2_evidence(
        report, manifest, _hypothesis(hypothesis_module)
    )

    assert report.decide_readiness(
        manifest,
        hypothesis,
        _gate(static_gate),
        _passing_scores(),
        _complete_unblinded_ratings(),
        change,
        research,
    ) == "invalid"


def _report_inputs(loop_modules):
    baseline = [
        _generation_row("case-one", 0, "old one"),
        _generation_row("case-two", 0, "old two"),
    ]
    candidate = [
        _generation_row("case-two", 0, "new two"),
        _generation_row("case-one", 0, "new one"),
    ]
    inputs = _v2_report_inputs(loop_modules, baseline, candidate)
    inputs["limitations"] = ["<script>alert('one user')</script>"]
    return inputs


def test_build_report_is_pure_deterministic_escaped_and_complete(loop_modules, tmp_path):
    _, _, _, report, _ = loop_modules
    inputs = _report_inputs(loop_modules)
    before = set(tmp_path.iterdir())

    first = report.build_report(**inputs)
    second = report.build_report(**inputs)

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
        "## Human Blind Review",
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
    assert "candidate_label" not in first
    assert "Blind seed" not in first
    assert "Private-key digest" not in first
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
    assert "[REDACTED_PATH]" in rendered
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
    rendered = report.build_report(**inputs)

    assert "### Static Gate Failures" in rendered
    assert "chaesajang-style" in rendered
    assert "adapter drift" in rendered
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


def test_build_report_marks_unverified_research_invalid(loop_modules):
    _, _, _, report, _ = loop_modules
    inputs = _report_inputs(loop_modules)
    inputs["research_evidence"] = []

    rendered = report.build_report(**inputs)

    assert "invalid" in rendered
    assert "invalid_research_evidence" in rendered


# Task 8 security review regressions (blind protocol/readiness/report v2).

V2_PUBLIC_PAIR_FIELDS = {
    "pair_id",
    "generator_brief",
    "response_a",
    "response_b",
}
V2_PRIVATE_KEY_FIELDS = {
    "schema_version",
    "experiment_id",
    "seed",
    "secret",
    "baseline_row_digests",
    "candidate_row_digests",
    "public_bundle_digest",
    "public_row_digests",
    "mapping",
    "package_id",
}


def _v2_hypothesis(
    hypothesis_module,
    claim_id,
    *,
    path="chaesajang-core/persona_core.md",
    change_group="persona-layering",
    risk="low",
    blind_required=False,
    primary_axis="style_behavior",
):
    return hypothesis_module.Hypothesis(
        claim_ids=(claim_id,),
        change_group=change_group,
        allowed_paths=(path,),
        primary_axis=primary_axis,
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


def _v2_patch(path="chaesajang-core/persona_core.md"):
    return (
        f"--- a/{path}\n"
        f"+++ b/{path}\n"
        "@@ -1 +1 @@\n"
        "-old rule\n"
        "+new rule\n"
    )


def _v2_claim(**overrides):
    claim = _research_claim()
    claim.update(overrides)
    return claim


def _v2_raw_ratings(private_key, *, choice="candidate"):
    rows = []
    for pair_id, private in private_key["mapping"].items():
        candidate_label = private["candidate_label"]
        baseline_label = "B" if candidate_label == "A" else "A"
        selected = {
            "candidate": candidate_label,
            "baseline": baseline_label,
            "tie": "tie",
        }[choice]
        rows.append(
            {
                "pair_id": pair_id,
                "quality_preference": selected,
                "style_preference": selected,
                "overall_preference": selected,
                "over_imitation": "neither",
                "meaning_or_fact_issue": {"A": "none", "B": "none"},
                "evidence_excerpt": "The candidate is clearer without changing the meaning.",
            }
        )
    return rows


def _v2_context(loop_modules, baseline_rows, candidate_rows, *, complete=True):
    blind, contracts, hypothesis_module, report, static_gate = loop_modules
    manifest = _manifest(contracts)
    claim = _v2_claim()
    claim_id = report.research_claim_id(claim)
    hypothesis = _v2_hypothesis(hypothesis_module, claim_id)
    change = report.verify_change_assessment(hypothesis, _v2_patch())
    research = report.verify_research_evidence(
        manifest.experiment_id, hypothesis, [claim]
    )
    pairs, key = blind.make_blind_package(
        manifest.experiment_id, baseline_rows, candidate_rows, seed=7
    )
    ratings = _v2_raw_ratings(key)
    if not complete:
        ratings = ratings[:1]
    review = blind.verify_blind_review(
        manifest.experiment_id,
        baseline_rows,
        candidate_rows,
        pairs,
        key,
        ratings,
    )
    return {
        "manifest": manifest,
        "hypothesis": hypothesis,
        "gate": _gate(static_gate),
        "scores": _passing_scores(
            pair_count=len(baseline_rows),
            generation_evidence_digest=blind.generation_evidence_digest(
                baseline_rows, candidate_rows
            ),
        ),
        "review": review,
        "change_assessment": change,
        "research_evidence": research,
        "pairs": pairs,
        "key": key,
        "raw_ratings": ratings,
    }


def test_v2_public_rows_have_exact_anonymous_schema_and_preserve_response_bytes(
    loop_modules, baseline_rows, candidate_rows
):
    blind, _, _, _, _ = loop_modules
    pairs, key = blind.make_blind_package(
        "2026-08-30-001", baseline_rows, candidate_rows, seed=7
    )

    assert all(set(row) == V2_PUBLIC_PAIR_FIELDS for row in pairs)
    assert set(key) == V2_PRIVATE_KEY_FIELDS
    assert key["schema_version"] == 2
    assert len(bytes.fromhex(key["secret"])) == 32
    encoded_metadata = json.dumps(
        [{key: value for key, value in row.items() if key not in {"response_a", "response_b"}}
         for row in pairs],
        ensure_ascii=False,
    )
    for forbidden in ("seed", "source_pair", "order", "mapping", "package"):
        assert forbidden not in encoded_metadata.casefold()
    outputs = [row["output"] for row in baseline_rows + candidate_rows]
    displayed = [value for pair in pairs for value in (pair["response_a"], pair["response_b"])]
    assert sorted(displayed) == sorted(outputs * 2)
    assert any("baseline word retained" in value for value in displayed)
    assert any("candidate word retained" in value for value in displayed)


def test_v2_same_seed_uses_fresh_secret_but_persisted_key_rebuilds_byte_identically(
    loop_modules, baseline_rows, candidate_rows
):
    blind, _, _, _, _ = loop_modules
    first, first_key = blind.make_blind_package(
        "2026-08-30-001", baseline_rows, candidate_rows, seed=19
    )
    second, second_key = blind.make_blind_package(
        "2026-08-30-001", baseline_rows, candidate_rows, seed=19
    )
    rebuilt = blind.rebuild_blind_package(
        "2026-08-30-001", baseline_rows, candidate_rows, first_key
    )

    assert first_key["secret"] != second_key["secret"]
    assert {row["pair_id"] for row in first}.isdisjoint(
        {row["pair_id"] for row in second}
    )
    assert json.dumps(rebuilt, ensure_ascii=False, separators=(",", ":")) == json.dumps(
        first, ensure_ascii=False, separators=(",", ":")
    )
    assert blind.verify_blind_package(
        "2026-08-30-001", baseline_rows, candidate_rows, first, first_key
    ).public_bundle_digest == first_key["public_bundle_digest"]


def test_v2_public_wrapper_never_exposes_replay_seed(loop_modules, baseline_rows, candidate_rows):
    blind, _, _, _, _ = loop_modules
    first = blind.make_blind_pairs(baseline_rows, candidate_rows, seed=23)
    second = blind.make_blind_pairs(baseline_rows, candidate_rows, seed=23)

    assert all(set(row) == V2_PUBLIC_PAIR_FIELDS for row in first)
    assert {row["pair_id"] for row in first}.isdisjoint(
        {row["pair_id"] for row in second}
    )
    assert blind.validate_order_balance(first) == []


@pytest.mark.parametrize(
    "axis",
    [
        "baseline",
        "candidate",
        "public_response",
        "public_brief",
        "public_id",
        "key_secret",
        "key_seed",
        "key_experiment",
        "key_baseline_digest",
        "key_candidate_digest",
        "key_public_digest",
        "key_row_digest",
        "key_mapping",
        "key_package_id",
    ],
)
def test_v2_exact_package_verifier_rejects_every_tamper_axis(
    loop_modules, baseline_rows, candidate_rows, axis
):
    blind, _, _, _, _ = loop_modules
    experiment_id = "2026-08-30-001"
    pairs, key = blind.make_blind_package(
        experiment_id, baseline_rows, candidate_rows, seed=7
    )
    baseline = copy.deepcopy(baseline_rows)
    candidate = copy.deepcopy(candidate_rows)
    public = copy.deepcopy(pairs)
    private = copy.deepcopy(key)
    if axis == "baseline":
        baseline[0]["output"] += " tampered"
    elif axis == "candidate":
        candidate[0]["model"] = "other-model"
    elif axis == "public_response":
        public[0]["response_a"] += " tampered"
    elif axis == "public_brief":
        public[0]["generator_brief"] += " tampered"
    elif axis == "public_id":
        public[0]["pair_id"] = "f" * 64
    elif axis == "key_secret":
        private["secret"] = "00" * 32
    elif axis == "key_seed":
        private["seed"] += 1
    elif axis == "key_experiment":
        private["experiment_id"] = "other-experiment"
    elif axis == "key_baseline_digest":
        private["baseline_row_digests"][0]["sha256"] = "0" * 64
    elif axis == "key_candidate_digest":
        private["candidate_row_digests"][0]["sha256"] = "0" * 64
    elif axis == "key_public_digest":
        private["public_bundle_digest"] = "0" * 64
    elif axis == "key_row_digest":
        first_id = next(iter(private["public_row_digests"]))
        private["public_row_digests"][first_id] = "0" * 64
    elif axis == "key_mapping":
        first_id = next(iter(private["mapping"]))
        current = private["mapping"][first_id]["candidate_label"]
        private["mapping"][first_id]["candidate_label"] = "B" if current == "A" else "A"
    else:
        private["package_id"] = "0" * 64

    with pytest.raises((TypeError, ValueError)):
        blind.verify_blind_package(
            experiment_id, baseline, candidate, public, private
        )


def test_v2_package_and_review_reject_cross_experiment_replay(
    loop_modules, baseline_rows, candidate_rows
):
    blind, _, _, _, _ = loop_modules
    pairs, key = blind.make_blind_package(
        "2026-08-30-001", baseline_rows, candidate_rows, seed=7
    )
    ratings = _v2_raw_ratings(key)

    with pytest.raises(ValueError, match="experiment"):
        blind.verify_blind_package(
            "2026-08-30-002", baseline_rows, candidate_rows, pairs, key
        )
    with pytest.raises(ValueError, match="experiment"):
        blind.verify_blind_review(
            "2026-08-30-002",
            baseline_rows,
            candidate_rows,
            pairs,
            key,
            ratings,
        )


def test_v2_readiness_rejects_review_from_substituted_generation_rows(
    loop_modules, baseline_rows, candidate_rows
):
    blind, _, _, report, _ = loop_modules
    context = _v2_context(loop_modules, baseline_rows, candidate_rows)
    substituted_baseline = copy.deepcopy(baseline_rows)
    substituted_candidate = copy.deepcopy(candidate_rows)
    for row in substituted_baseline:
        row["output"] = f"substituted baseline for {row['case_id']} repeat {row['repeat']}"
    for row in substituted_candidate:
        row["output"] = f"substituted candidate for {row['case_id']} repeat {row['repeat']}"
    pairs, key = blind.make_blind_package(
        context["manifest"].experiment_id,
        substituted_baseline,
        substituted_candidate,
        seed=7,
    )
    substituted_review = blind.verify_blind_review(
        context["manifest"].experiment_id,
        substituted_baseline,
        substituted_candidate,
        pairs,
        key,
        _v2_raw_ratings(key),
    )

    assert report.decide_readiness(
        context["manifest"],
        context["hypothesis"],
        context["gate"],
        context["scores"],
        substituted_review,
        context["change_assessment"],
        context["research_evidence"],
    ) == "invalid"


def test_v2_partial_review_is_coverage_only_and_complete_review_is_sealed_and_immutable(
    loop_modules, baseline_rows, candidate_rows
):
    blind, _, _, _, _ = loop_modules
    pairs, key = blind.make_blind_package(
        "2026-08-30-001", baseline_rows, candidate_rows, seed=7
    )
    ratings = _v2_raw_ratings(key)
    partial = blind.verify_blind_review(
        "2026-08-30-001", baseline_rows, candidate_rows, pairs, key, ratings[:1]
    )
    complete = blind.verify_blind_review(
        "2026-08-30-001", baseline_rows, candidate_rows, pairs, key, ratings
    )

    assert partial.coverage_count == 1
    assert partial.complete is False
    assert partial.condition_ratings == ()
    assert partial.receipt is None
    assert complete.complete is True
    assert len(complete.condition_ratings) == len(ratings)
    assert complete.receipt is not None
    with pytest.raises(TypeError):
        complete.condition_ratings[0]["overall_preference"] = "baseline"
    with pytest.raises(TypeError):
        blind.VerifiedBlindReview()


def test_v2_complete_review_receipt_must_be_reverified_against_raw_ratings(
    loop_modules, baseline_rows, candidate_rows
):
    blind, _, _, _, _ = loop_modules
    experiment_id = "2026-08-30-001"
    pairs, key = blind.make_blind_package(
        experiment_id, baseline_rows, candidate_rows, seed=7
    )
    ratings = _v2_raw_ratings(key)
    first = blind.verify_blind_review(
        experiment_id, baseline_rows, candidate_rows, pairs, key, ratings
    )
    replayed = blind.verify_blind_review(
        experiment_id,
        baseline_rows,
        candidate_rows,
        pairs,
        key,
        ratings,
        expected_receipt=dict(first.receipt),
    )
    assert replayed.receipt == first.receipt

    tampered_ratings = copy.deepcopy(ratings)
    tampered_ratings[0]["overall_preference"] = "tie"
    with pytest.raises(ValueError, match="receipt"):
        blind.verify_blind_review(
            experiment_id,
            baseline_rows,
            candidate_rows,
            pairs,
            key,
            tampered_ratings,
            expected_receipt=dict(first.receipt),
        )
    tampered_receipt = dict(first.receipt)
    tampered_receipt["mac"] = "0" * 64
    with pytest.raises(ValueError, match="receipt"):
        blind.verify_blind_review(
            experiment_id,
            baseline_rows,
            candidate_rows,
            pairs,
            key,
            ratings,
            expected_receipt=tampered_receipt,
        )


def test_v2_readiness_rejects_forged_unblinded_rows_and_serialized_receipts(
    loop_modules, baseline_rows, candidate_rows
):
    _, _, _, report, _ = loop_modules
    context = _v2_context(loop_modules, baseline_rows, candidate_rows)
    common = (
        context["manifest"],
        context["hypothesis"],
        context["gate"],
        context["scores"],
    )
    forged = _complete_unblinded_ratings(("candidate", "candidate", "candidate"))

    assert report.decide_readiness(
        *common,
        forged,
        context["change_assessment"],
        context["research_evidence"],
    ) == "invalid"
    assert report.decide_readiness(
        *common,
        dict(context["review"].receipt),
        context["change_assessment"],
        context["research_evidence"],
    ) == "invalid"


@pytest.mark.parametrize(
    ("artifact_name", "field", "tampered_value"),
    [
        ("review", "complete", False),
        ("change_assessment", "human_required", False),
        ("research_evidence", "claims", ()),
    ],
)
def test_v2_readiness_rejects_post_issuance_object_setattr_mutation(
    loop_modules,
    baseline_rows,
    candidate_rows,
    artifact_name,
    field,
    tampered_value,
):
    _, _, _, report, _ = loop_modules
    context = _v2_context(loop_modules, baseline_rows, candidate_rows)
    object.__setattr__(context[artifact_name], field, tampered_value)

    assert report.decide_readiness(
        context["manifest"],
        context["hypothesis"],
        context["gate"],
        context["scores"],
        context["review"],
        context["change_assessment"],
        context["research_evidence"],
    ) == "invalid"


def test_v2_readiness_rejects_copies_of_issued_verification_objects(
    loop_modules, baseline_rows, candidate_rows
):
    _, _, _, report, _ = loop_modules
    context = _v2_context(loop_modules, baseline_rows, candidate_rows)

    with pytest.raises(TypeError):
        copy.copy(context["review"])

    for artifact_name in ("change_assessment", "research_evidence"):
        copied = copy.copy(context[artifact_name])
        inputs = {
            key: context[key]
            for key in (
                "review",
                "change_assessment",
                "research_evidence",
            )
        }
        inputs[artifact_name] = copied
        assert report.decide_readiness(
            context["manifest"],
            context["hypothesis"],
            context["gate"],
            context["scores"],
            inputs["review"],
            inputs["change_assessment"],
            inputs["research_evidence"],
        ) == "invalid"


def test_v2_persona_markdown_cannot_skip_human_review_by_self_labeling_low(
    loop_modules, baseline_rows, candidate_rows
):
    _, _, _, report, _ = loop_modules
    context = _v2_context(loop_modules, baseline_rows, candidate_rows, complete=False)

    assert context["change_assessment"].human_required is True
    assert report.decide_readiness(
        context["manifest"],
        context["hypothesis"],
        context["gate"],
        context["scores"],
        None,
        context["change_assessment"],
        context["research_evidence"],
    ) == "awaiting_human"


def test_v2_only_verified_packaging_static_sync_patch_can_skip_human(
    loop_modules, baseline_rows, candidate_rows
):
    _, contracts, hypothesis_module, report, static_gate = loop_modules
    manifest = _manifest(contracts)
    claim = _v2_claim()
    claim_id = report.research_claim_id(claim)
    hypothesis = _v2_hypothesis(
        hypothesis_module,
        claim_id,
        path="sync_core.py",
        change_group="packaging/static-sync",
        risk="low",
        blind_required=False,
        primary_axis="resource_use",
    )
    change = report.verify_change_assessment(hypothesis, _v2_patch("sync_core.py"))
    research = report.verify_research_evidence(
        manifest.experiment_id, hypothesis, [claim]
    )

    assert change.human_required is False
    assert report.decide_readiness(
        manifest,
        hypothesis,
        _gate(static_gate),
        _passing_scores(pair_count=len(baseline_rows)),
        None,
        change,
        research,
    ) == "ready_for_approval"
    assert report.decide_readiness(
        manifest,
        hypothesis,
        _gate(static_gate),
        _passing_scores(pair_count=len(baseline_rows)),
        None,
        {"human_required": False},
        research,
    ) == "invalid"


@pytest.mark.parametrize(
    "paths",
    [
        ("nested/sync_core.py",),
        ("package.py",),
        ("attacker/render.py",),
        ("sync_core.py", "package.py"),
    ],
)
def test_v2_static_only_exemption_requires_exact_single_sync_core_path(
    loop_modules, paths
):
    _, _, hypothesis_module, report, _ = loop_modules
    hypothesis = dataclasses.replace(
        _v2_hypothesis(
            hypothesis_module,
            "a" * 64,
            path=paths[0],
            change_group="packaging/static-sync",
            risk="low",
            blind_required=False,
            primary_axis="resource_use",
        ),
        allowed_paths=paths,
    )
    patch = "".join(_v2_patch(path) for path in paths)

    assessment = report.verify_change_assessment(hypothesis, patch)

    assert assessment.human_required is True
    assert assessment.classification == "human_review_required"


@pytest.mark.parametrize(
    "unsafe_path",
    [
        " sync_core.py",
        "sync_core.py ",
        "sync_core.py.",
        "nested./sync_core.py",
        "nested /sync_core.py",
    ],
)
def test_v2_ambiguous_path_spellings_cannot_be_classified_as_trusted(
    loop_modules, unsafe_path
):
    _, _, hypothesis_module, report, _ = loop_modules
    hypothesis = _v2_hypothesis(
        hypothesis_module,
        "a" * 64,
        path=unsafe_path,
        change_group="packaging/static-sync",
        risk="low",
        blind_required=False,
        primary_axis="resource_use",
    )

    with pytest.raises(ValueError, match="path|whitespace|space|dot"):
        report.verify_change_assessment(hypothesis, _v2_patch(unsafe_path))


def test_v2_change_assessment_binds_patch_hypothesis_and_exact_scope(loop_modules):
    _, _, hypothesis_module, report, _ = loop_modules
    claim_id = "a" * 64
    hypothesis = _v2_hypothesis(hypothesis_module, claim_id)
    assessment = report.verify_change_assessment(hypothesis, _v2_patch())
    altered_hypothesis = dataclasses.replace(
        hypothesis, allowed_paths=("chaesajang-core/handoff_core.md",)
    )

    assert re.fullmatch(r"[0-9a-f]{64}", assessment.patch_digest)
    assert assessment.changed_paths == ("chaesajang-core/persona_core.md",)
    with pytest.raises(ValueError, match="scope|hypothesis"):
        report.verify_change_assessment(altered_hypothesis, _v2_patch())


def test_v2_change_assessment_rejects_hidden_or_binary_file_sections(loop_modules):
    _, _, hypothesis_module, report, _ = loop_modules
    hypothesis = _v2_hypothesis(hypothesis_module, "a" * 64)
    hidden = (
        _v2_patch()
        + "diff --git a/sync_core.py b/sync_core.py\n"
        + "GIT binary patch\n"
        + "literal 1\nX\n"
    )

    with pytest.raises(ValueError, match="binary|patch|scope"):
        report.verify_change_assessment(hypothesis, hidden)


def test_v2_readiness_requires_actionable_resolved_research_and_experiment_binding(
    loop_modules, baseline_rows, candidate_rows
):
    _, _, _, report, _ = loop_modules
    context = _v2_context(loop_modules, baseline_rows, candidate_rows)
    common = (
        context["manifest"],
        context["hypothesis"],
        context["gate"],
        context["scores"],
        context["review"],
        context["change_assessment"],
    )

    watchlist = _v2_claim(source_type="preprint", confidence="low")
    with pytest.raises(ValueError, match="actionable"):
        report.verify_research_evidence(
            context["manifest"].experiment_id,
            dataclasses.replace(
                context["hypothesis"],
                claim_ids=(report.research_claim_id(watchlist),),
            ),
            [watchlist],
        )
    assert report.decide_readiness(*common, []) == "invalid"
    other_experiment = report.verify_research_evidence(
        "other-experiment", context["hypothesis"], [_v2_claim()]
    )
    assert report.decide_readiness(*common, other_experiment) == "invalid"


def _mutate_v2_ratings_for_source(private_key, ratings, source_index, **changes):
    source_ids = sorted({item["source_id"] for item in private_key["mapping"].values()})
    source_id = source_ids[source_index]
    for row in ratings:
        if private_key["mapping"][row["pair_id"]]["source_id"] in {source_id}:
            for field, condition_value in changes.items():
                candidate_label = private_key["mapping"][row["pair_id"]]["candidate_label"]
                baseline_label = "B" if candidate_label == "A" else "A"
                if field in {"overall_preference", "quality_preference", "style_preference"}:
                    row[field] = {
                        "candidate": candidate_label,
                        "baseline": baseline_label,
                        "tie": "tie",
                    }[condition_value]
                elif field == "candidate_critical":
                    row["meaning_or_fact_issue"][candidate_label] = "critical"
                elif field == "over_imitation":
                    row["over_imitation"] = (
                        candidate_label if condition_value == "candidate_only" else condition_value
                    )


def test_v2_human_readiness_requires_strict_overall_and_primary_preference_majorities(
    loop_modules, baseline_rows, candidate_rows
):
    blind, _, _, report, _ = loop_modules
    context = _v2_context(loop_modules, baseline_rows, candidate_rows)
    ratings = _v2_raw_ratings(context["key"])
    _mutate_v2_ratings_for_source(
        context["key"], ratings, 1, style_preference="tie"
    )
    _mutate_v2_ratings_for_source(
        context["key"], ratings, 2, style_preference="baseline"
    )
    review = blind.verify_blind_review(
        context["manifest"].experiment_id,
        baseline_rows,
        candidate_rows,
        context["pairs"],
        context["key"],
        ratings,
    )
    result = report.evaluate_readiness(
        context["manifest"],
        context["hypothesis"],
        context["gate"],
        context["scores"],
        review,
        context["change_assessment"],
        context["research_evidence"],
    )
    assert result.status == "rejected"
    assert "primary_candidate_majority_missing" in result.reasons


def test_v2_human_readiness_uses_quality_preference_for_nonstyle_primary_axis(
    loop_modules, baseline_rows, candidate_rows
):
    blind, _, _, report, _ = loop_modules
    context = _v2_context(loop_modules, baseline_rows, candidate_rows)
    hypothesis = dataclasses.replace(
        context["hypothesis"], primary_axis="structure_and_information"
    )
    change = report.verify_change_assessment(hypothesis, _v2_patch())
    research = report.verify_research_evidence(
        context["manifest"].experiment_id, hypothesis, [_v2_claim()]
    )
    ratings = _v2_raw_ratings(context["key"])
    _mutate_v2_ratings_for_source(
        context["key"], ratings, 1, quality_preference="tie"
    )
    _mutate_v2_ratings_for_source(
        context["key"], ratings, 2, quality_preference="baseline"
    )
    review = blind.verify_blind_review(
        context["manifest"].experiment_id,
        baseline_rows,
        candidate_rows,
        context["pairs"],
        context["key"],
        ratings,
    )

    assert report.decide_readiness(
        context["manifest"],
        hypothesis,
        context["gate"],
        context["scores"],
        review,
        change,
        research,
    ) == "rejected"


@pytest.mark.parametrize(
    ("over_imitation", "expected"),
    [("both", "ready_for_approval"), ("candidate_only", "rejected")],
)
def test_v2_over_imitation_is_candidate_only_regression_not_absolute_prohibition(
    loop_modules, baseline_rows, candidate_rows, over_imitation, expected
):
    blind, _, _, report, _ = loop_modules
    context = _v2_context(loop_modules, baseline_rows, candidate_rows)
    ratings = _v2_raw_ratings(context["key"])
    _mutate_v2_ratings_for_source(
        context["key"], ratings, 0, over_imitation=over_imitation
    )
    review = blind.verify_blind_review(
        context["manifest"].experiment_id,
        baseline_rows,
        candidate_rows,
        context["pairs"],
        context["key"],
        ratings,
    )

    assert report.decide_readiness(
        context["manifest"],
        context["hypothesis"],
        context["gate"],
        context["scores"],
        review,
        context["change_assessment"],
        context["research_evidence"],
    ) == expected


def test_v2_partial_review_never_interprets_votes_or_harm(
    loop_modules, baseline_rows, candidate_rows
):
    blind, _, _, report, _ = loop_modules
    context = _v2_context(loop_modules, baseline_rows, candidate_rows, complete=False)
    ratings = _v2_raw_ratings(context["key"])
    first = ratings[:1]
    candidate_label = context["key"]["mapping"][first[0]["pair_id"]]["candidate_label"]
    first[0]["overall_preference"] = (
        "B" if candidate_label == "A" else "A"
    )
    first[0]["meaning_or_fact_issue"][candidate_label] = "critical"
    partial = blind.verify_blind_review(
        context["manifest"].experiment_id,
        baseline_rows,
        candidate_rows,
        context["pairs"],
        context["key"],
        first,
    )
    result = report.evaluate_readiness(
        context["manifest"],
        context["hypothesis"],
        context["gate"],
        context["scores"],
        partial,
        context["change_assessment"],
        context["research_evidence"],
    )

    assert result.status == "awaiting_human"
    assert result.reasons == ("human_review_partial",)


def _v2_report_inputs(loop_modules, baseline_rows, candidate_rows):
    context = _v2_context(loop_modules, baseline_rows, candidate_rows)
    return {
        key: context[key]
        for key in (
            "manifest",
            "hypothesis",
            "gate",
            "scores",
            "review",
            "change_assessment",
            "research_evidence",
        )
    } | {
        "raw_artifacts": [
            {
                "relative_path": "experiments/2026-08-30-001/baseline.jsonl",
                "sha256": "d" * 64,
                "argv": ["python", "scripts/loop.py", "report"],
            }
        ],
        "regressions": ["No protected regression observed."],
        "promotion_files": ["chaesajang-core/persona_core.md"],
        "limitations": ["One evaluator."],
    }


def test_v2_report_derives_safe_aggregate_blind_summary_without_private_metadata(
    loop_modules, baseline_rows, candidate_rows
):
    _, _, _, report, _ = loop_modules
    inputs = _v2_report_inputs(loop_modules, baseline_rows, candidate_rows)
    rendered = report.build_report(**inputs)

    assert "ready_for_approval" in rendered
    assert inputs["review"].public_bundle_digest in rendered
    assert "Coverage" in rendered
    assert "Aggregate preference" in rendered
    for forbidden in (
        inputs["review"].package_id,
        inputs["review"].receipt["mac"],
        inputs["review"].condition_ratings[0]["pair_id"],
        inputs["review"].condition_ratings[0]["source_id"],
        inputs["review"].condition_ratings[0]["order"],
        inputs["review"].condition_ratings[0]["response_a"]
        if "response_a" in inputs["review"].condition_ratings[0]
        else "__no_raw_response__",
        inputs["review"]._secret_for_test if hasattr(inputs["review"], "_secret_for_test") else "__no_secret__",
    ):
        assert forbidden not in rendered
    assert "Blind seed" not in rendered
    assert "Private-key digest" not in rendered


def test_v2_report_renders_markdown_injection_inert_and_redacts_every_private_path_form(
    loop_modules, baseline_rows, candidate_rows
):
    _, _, _, report, _ = loop_modules
    inputs = _v2_report_inputs(loop_modules, baseline_rows, candidate_rows)
    claim = _v2_claim(
        claim="`break` ![pixel](https://tracker.test/pixel)",
        evidence="](file:///secret)",
        decision_impact="[click](https://tracker.test)",
    )
    claim_id = report.research_claim_id(claim)
    inputs["hypothesis"] = dataclasses.replace(
        inputs["hypothesis"],
        claim_ids=(claim_id,),
        body="`body` ![x](https://tracker.test/body)",
    )
    inputs["change_assessment"] = report.verify_change_assessment(
        inputs["hypothesis"], _v2_patch()
    )
    inputs["research_evidence"] = report.verify_research_evidence(
        inputs["manifest"].experiment_id, inputs["hypothesis"], [claim]
    )
    inputs["limitations"] = [
        "/secret",
        "C:\\secret\\file",
        "C:relative-secret",
        "\\\\server\\share\\secret",
        "//server/share/secret",
        "file:///secret",
        "~/secret",
    ]
    rendered = report.build_report(**inputs)

    assert "](file:///secret)" not in rendered
    assert "![pixel](" not in rendered
    assert "[click](" not in rendered
    for leaked in (
        "/secret",
        "C:\\secret",
        "C:relative-secret",
        "\\\\server\\share",
        "//server/share",
        "file:///secret",
        "~/secret",
    ):
        assert leaked not in rendered
    assert "[REDACTED_PATH]" in rendered


def test_v2_report_preserves_argv_token_boundaries_with_redaction_and_original_digest(
    loop_modules, baseline_rows, candidate_rows
):
    _, _, _, report, _ = loop_modules
    inputs = _v2_report_inputs(loop_modules, baseline_rows, candidate_rows)
    argv = ["codex", "exec", "--cd", "C:\\private\\source", "--flag=C:relative"]
    inputs["raw_artifacts"][0]["argv"] = argv
    digest = hashlib.sha256(
        json.dumps(
            argv,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    rendered = report.build_report(**inputs)

    assert "C:\\private\\source" not in rendered
    assert "C:relative" not in rendered
    assert rendered.count("[REDACTED_PATH]") >= 2
    assert digest in rendered


@pytest.mark.parametrize("field", ["raw_artifacts", "promotion_files"])
def test_v2_report_rejects_ambiguous_suffix_paths(
    loop_modules, baseline_rows, candidate_rows, field
):
    _, _, _, report, _ = loop_modules
    inputs = _v2_report_inputs(loop_modules, baseline_rows, candidate_rows)
    if field == "raw_artifacts":
        inputs[field][0]["relative_path"] = "experiments/scores.json."
    else:
        inputs[field] = ["sync_core.py "]

    with pytest.raises(ValueError, match="path|space|dot"):
        report.build_report(**inputs)


def test_v2_paths_preserve_legitimate_internal_spaces(
    loop_modules, baseline_rows, candidate_rows
):
    _, _, hypothesis_module, report, _ = loop_modules
    assert (
        hypothesis_module.canonical_relative_path(
            "experiments/run one/scores.json", "artifact"
        )
        == "experiments/run one/scores.json"
    )
    inputs = _v2_report_inputs(loop_modules, baseline_rows, candidate_rows)
    inputs["raw_artifacts"][0]["relative_path"] = (
        "experiments/run one/baseline.jsonl"
    )
    inputs["promotion_files"] = ["docs/release notes.md"]

    rendered = report.build_report(**inputs)

    assert "experiments/run one/baseline.jsonl" in rendered
    assert "docs/release notes.md" in rendered


def test_v2_invalid_and_blocked_external_reports_render_stable_reason_codes(
    loop_modules, baseline_rows, candidate_rows
):
    _, contracts, _, report, _ = loop_modules
    inputs = _v2_report_inputs(loop_modules, baseline_rows, candidate_rows)
    inputs["scores"] = {"malformed": True}
    invalid = report.build_report(**inputs)
    assert "invalid" in invalid
    assert "invalid_scores" in invalid

    valid_inputs = _v2_report_inputs(loop_modules, baseline_rows, candidate_rows)
    candidate_ready = dataclasses.replace(
        valid_inputs["manifest"], status=contracts.ExperimentStatus.CANDIDATE_READY
    )
    blocked = contracts.transition(candidate_ready, contracts.ExperimentStatus.BLOCKED_EXTERNAL)
    valid_inputs["manifest"] = blocked
    blocked_report = report.build_report(**valid_inputs)
    assert "blocked_external" in blocked_report
    assert "external_execution_blocked" in blocked_report


@pytest.mark.parametrize("terminal_status", ["invalid", "blocked_external"])
def test_v2_terminal_reports_withhold_poisoned_unrelated_evidence(
    loop_modules, baseline_rows, candidate_rows, terminal_status
):
    _, contracts, _, report, _ = loop_modules
    inputs = _v2_report_inputs(loop_modules, baseline_rows, candidate_rows)
    manifest = dataclasses.replace(
        inputs["manifest"],
        status=contracts.ExperimentStatus.CANDIDATE_READY,
        experiment_id="exp<img src=x>",
    )
    inputs["manifest"] = contracts.transition(
        manifest, contracts.ExperimentStatus(terminal_status)
    )
    secret = "TOP_SECRET_BLIND_PAYLOAD"
    inputs.update(
        {
            "hypothesis": object(),
            "gate": object(),
            "scores": {"secret": secret},
            "review": {"secret": secret},
            "change_assessment": object(),
            "research_evidence": {"claims": [secret]},
            "raw_artifacts": [{"secret": secret}],
            "regressions": [{"secret": secret}],
            "promotion_files": ["../private-promotion"],
            "limitations": [secret],
        }
    )

    first = report.build_report(**inputs)
    second = report.build_report(**inputs)

    assert first == second
    assert f"Decision: `{terminal_status}`" in first
    assert "Evidence withheld" in first
    assert "exp&lt;img src=x&gt;" in first
    assert "<img src=x>" not in first
    assert secret not in first
    assert "## Hypothesis" not in first


def test_v2_invalid_evidence_report_does_not_validate_or_leak_later_poison(
    loop_modules, baseline_rows, candidate_rows
):
    _, _, _, report, _ = loop_modules
    inputs = _v2_report_inputs(loop_modules, baseline_rows, candidate_rows)
    secret = "UNVALIDATED_PRIVATE_PAYLOAD"
    inputs.update(
        {
            "scores": {"malformed": True},
            "review": {"secret": secret},
            "change_assessment": object(),
            "research_evidence": {"claims": [secret]},
            "raw_artifacts": object(),
            "regressions": [{"secret": secret}],
            "promotion_files": ["../private-promotion"],
            "limitations": [secret],
        }
    )

    rendered = report.build_report(**inputs)

    assert "Decision: `invalid`" in rendered
    assert "`invalid_scores`" in rendered
    assert "Evidence withheld" in rendered
    assert secret not in rendered
    assert "## Per-Axis Results" not in rendered


def test_v2_report_never_lists_private_blind_artifacts(
    loop_modules, baseline_rows, candidate_rows
):
    _, _, _, report, _ = loop_modules
    inputs = _v2_report_inputs(loop_modules, baseline_rows, candidate_rows)
    inputs["raw_artifacts"].extend(
        [
            {
                "relative_path": "experiments/x/blind_key.private.json",
                "sha256": "e" * 64,
                "argv": ["python", "loop.py"],
            },
            {
                "relative_path": "experiments/x/blind_review.private.json",
                "sha256": "f" * 64,
                "argv": ["python", "loop.py"],
            },
        ]
    )
    rendered = report.build_report(**inputs)

    assert "blind_key.private.json" not in rendered
    assert "blind_review.private.json" not in rendered
    assert "private_artifact_excluded" in rendered


def test_v2_report_accepts_only_strict_aggregate_regression_records(
    loop_modules, baseline_rows, candidate_rows
):
    _, _, _, report, _ = loop_modules
    inputs = _v2_report_inputs(loop_modules, baseline_rows, candidate_rows)
    inputs["regressions"] = [
        {
            "axis": "style_behavior",
            "baseline_failed": 1,
            "candidate_failed": 2,
            "delta": 1,
            "status": "regressed",
            "summary": "Aggregate style failures increased; `markup` stays inert.",
        }
    ]

    rendered = report.build_report(**inputs)

    assert "style_behavior" in rendered
    assert "Aggregate style failures increased" in rendered
    assert "`markup`" not in rendered


@pytest.mark.parametrize(
    "unsafe_regression",
    [
        "receipt mac " + "0" * 64,
        "private receipt path C:\\private\\blind_review.private.json",
        {"pair_id": "a" * 64},
        {"source_id": "b" * 64},
        {"package_id": "c" * 64},
        {"receipt": {"mac": "d" * 64}},
        {"ratings": [{"overall_preference": "A", "evidence_excerpt": "raw"}]},
        {"mapping": {"A": "candidate", "B": "baseline"}},
        {"secret": "e" * 64},
        {"seed": 7},
        {
            "axis": "style_behavior",
            "baseline_failed": 1,
            "candidate_failed": 2,
            "delta": 1,
            "status": "regressed",
            "summary": "C:\\private\\blind_review.private.json",
        },
        {
            "axis": "style_behavior",
            "baseline_failed": 1,
            "candidate_failed": 2,
            "delta": 1,
            "status": "regressed",
            "summary": "f" * 64,
        },
    ],
)
def test_v2_report_rejects_private_material_in_regression_records(
    loop_modules, baseline_rows, candidate_rows, unsafe_regression
):
    _, _, _, report, _ = loop_modules
    inputs = _v2_report_inputs(loop_modules, baseline_rows, candidate_rows)
    inputs["regressions"] = [unsafe_regression]

    with pytest.raises((TypeError, ValueError), match="regression|private|aggregate"):
        report.build_report(**inputs)
