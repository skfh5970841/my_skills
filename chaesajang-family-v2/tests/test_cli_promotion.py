import hashlib
import json
import os
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest


SCRIPTS = (
    Path(__file__).resolve().parents[1]
    / "chaesajang-family-optimizer"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

from optimizer_loop import blind, cli, evals, promote as promote_module, report
from optimizer_loop.artifacts import read_jsonl, write_jsonl
from optimizer_loop.candidate import create_candidate, write_candidate_patch
from optimizer_loop.contracts import ExperimentManifest
from optimizer_loop.hypothesis import Hypothesis
from optimizer_loop.promote import next_action, promote
from optimizer_loop.registry import load_registry
from optimizer_loop.render import render_all
from optimizer_loop.research import normalize_claim
from optimizer_loop.snapshot import snapshot_registry
from optimizer_loop.static_gate import GateResult


AXES = (
    "request_fulfillment",
    "meaning_and_facts",
    "structure_and_information",
    "style_behavior",
    "over_imitation",
    "resource_use",
)


@dataclass
class ReadyFixture:
    family: Path
    experiment: Path
    canonical: Path
    registry: object
    original: bytes
    candidate: bytes


def _json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True), encoding="utf-8"
    )


def _generation_row(
    output: str, source_hashes: dict[str, str], *, target_skill: str = "demo-skill"
) -> dict:
    brief = "인공지능의 한계를 쉬운 한국어로 설명하세요."
    return {
        "case_id": "case-one",
        "target_skill": target_skill,
        "repeat": 0,
        "input": brief,
        "prompt": "stable neutral prompt",
        "output": output,
        "stderr": "",
        "command": ["codex", "exec", "-"],
        "cwd": "C:/fixture/source",
        "source_root": "C:/fixture/source",
        "timeout_seconds": 30,
        "model": "gpt-test",
        "reasoning": "high",
        "runtime": "codex",
        "started_at": "2026-09-02T00:00:00+09:00",
        "elapsed_ms": 1,
        "status": "completed",
        "returncode": 0,
        "source_snapshot": source_hashes,
        "source_snapshot_after": source_hashes,
        "source_stable": True,
    }


def _case(*, target_skill: str = "demo-skill") -> evals.EvalCase:
    return evals.EvalCase.from_dict(
        {
            "case_id": "case-one",
            "target_skill": target_skill,
            "source_group": "fixture/one",
            "generator_brief": "인공지능의 한계를 쉬운 한국어로 설명하세요.",
            "axes": list(AXES),
            "risk": "behavior",
            "deterministic_checks": {
                "output_present": True,
                "required_terms": ["결론"],
                "forbidden_terms": ["허위"],
                "exact_facts": ["사실 하나"],
            },
            "evaluator_reference": "평가 전용 원문은 생성에 노출되지 않습니다.",
        },
        "golden",
    )


def _rating(pair: dict, key: dict) -> dict:
    candidate_label = key["mapping"][pair["pair_id"]]["candidate_label"]
    return {
        "pair_id": pair["pair_id"],
        "quality_preference": candidate_label,
        "style_preference": candidate_label,
        "overall_preference": candidate_label,
        "over_imitation": "neither",
        "meaning_or_fact_issue": {"A": "none", "B": "none"},
        "evidence_excerpt": "The candidate is clearer and preserves the fact.",
    }


def _ready_fixture(
    tmp_path: Path,
    *,
    candidate_uses_baseline_snapshot: bool = False,
    multi_skill: bool = False,
    candidate_uses_other_skill_snapshot: bool = False,
) -> ReadyFixture:
    family = tmp_path / "fixture-repository"
    core = family / "demo-core"
    skill = family / "demo-skill"
    core.mkdir(parents=True)
    skill.mkdir()
    original = b"---\nname: demo-skill\n---\n\nOriginal guidance.\n"
    candidate_bytes = b"---\nname: demo-skill\n---\n\nImproved guidance.\n"
    canonical = skill / "SKILL.md"
    canonical.write_bytes(original)
    other_skill = family / "other-skill"
    if multi_skill:
        other_skill.mkdir()
        (other_skill / "SKILL.md").write_bytes(
            b"---\nname: other-skill\n---\n\nUnrelated guidance.\n"
        )
    skills_yaml = (
        "  - name: demo-skill\n"
        "    source: demo-skill\n"
        "    core_files: []\n"
        "    inject_gaze: false\n"
    )
    if multi_skill:
        skills_yaml += (
            "  - name: other-skill\n"
            "    source: other-skill\n"
            "    core_files: []\n"
            "    inject_gaze: false\n"
        )
    (family / "family.yaml").write_text(
        "schema_version: 1\n"
        "core: demo-core\n"
        "skills:\n"
        + skills_yaml
        +
        "generated: {compatibility_snapshots: skills, dist: dist, experiments: experiments, package_extension: .skill}\n"
        "adapters:\n"
        "  codex:\n"
        "    exclude: []\n"
        "  claude:\n"
        "    exclude: []\n",
        encoding="utf-8",
    )
    registry = load_registry(family)
    render_all(registry, family, family / "dist")
    baseline = snapshot_registry(registry)

    experiment = family / "experiments" / "run-001"
    candidate_root = create_candidate(registry, experiment)
    (candidate_root / "demo-skill" / "SKILL.md").write_bytes(candidate_bytes)
    write_candidate_patch(registry, candidate_root, experiment / "candidate.patch")
    candidate_snapshot = {
        **baseline,
        "demo-skill/SKILL.md": hashlib.sha256(candidate_bytes).hexdigest(),
    }
    baseline_skill_snapshot = {"SKILL.md": baseline["demo-skill/SKILL.md"]}
    candidate_skill_snapshot = {
        "SKILL.md": candidate_snapshot["demo-skill/SKILL.md"]
    }
    if candidate_uses_other_skill_snapshot:
        candidate_skill_snapshot = {
            "SKILL.md": baseline["other-skill/SKILL.md"]
        }

    claim = normalize_claim(
        {
            "claim": "A concise instruction improves request fulfillment.",
            "source_url": "https://example.test/study",
            "source_date": "2026-08-01",
            "checked_at": "2026-09-02",
            "source_type": "peer_reviewed",
            "evidence": "The controlled comparison favored concise instructions.",
            "confidence": "high",
            "local_evidence": ["demo-skill/SKILL.md"],
            "decision_impact": "Change the one declared skill instruction.",
            "proposed_test": "Compare deterministic gates and blind preference.",
        }
    )
    claim_id = report.research_claim_id(claim)
    write_jsonl(experiment / "research.jsonl", [claim])
    (experiment / "hypothesis.md").write_text(
        "---\n"
        f"claim_ids: [{claim_id}]\n"
        "change_group: demo-guidance\n"
        "allowed_paths: [demo-skill/SKILL.md]\n"
        "primary_axis: request_fulfillment\n"
        "protected_axes: [meaning_and_facts]\n"
        "risk: behavior\n"
        "blind_required: true\n"
        "stop_rule: reject protected regressions\n"
        "---\n"
        "Change only the declared guidance.\n",
        encoding="utf-8",
    )

    baseline_rows = [
        _generation_row("핵심 결론과 사실 하나.", baseline_skill_snapshot)
    ]
    candidate_rows = [
        _generation_row(
            "더 명확한 핵심 결론과 사실 하나.",
            baseline_skill_snapshot
            if candidate_uses_baseline_snapshot
            else candidate_skill_snapshot,
        )
    ]
    write_jsonl(experiment / "baseline.jsonl", baseline_rows)
    write_jsonl(experiment / "candidate.jsonl", candidate_rows)
    case = _case()
    canonical_case = {
        "case_id": case.case_id,
        "target_skill": case.target_skill,
        "source_group": case.source_group,
        "generator_brief": case.generator_brief,
        "axes": list(case.axes),
        "risk": case.risk,
        "deterministic_checks": dict(case.deterministic_checks),
        "evaluator_reference": case.evaluator_reference,
    }
    canonical_evals = family / "evals" / "golden"
    canonical_evals.mkdir(parents=True)
    (canonical_evals / "case-one.jsonl").write_text(
        json.dumps(canonical_case, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    evaluations = [
        evals.make_deterministic_row(case, baseline_rows[0], "baseline"),
        evals.make_deterministic_row(case, candidate_rows[0], "candidate"),
    ]
    expected_pairs = [evals.expected_pair(case, repeat=0)]
    aggregate = evals.aggregate_scores(evaluations, expected_pairs=expected_pairs)
    _json(
        experiment / "scores.json",
        {
            "aggregate": aggregate,
            "evaluation_rows": evaluations,
            "expected_pairs": expected_pairs,
        },
    )

    public, private = blind.make_blind_package(
        "run-001", baseline_rows, candidate_rows, seed=7
    )
    ratings = [_rating(pair, private) for pair in public]
    review = blind.verify_blind_review(
        "run-001", baseline_rows, candidate_rows, public, private, ratings
    )
    write_jsonl(experiment / "blind_pairs.jsonl", public)
    _json(experiment / "blind_key.private.json", private)
    write_jsonl(experiment / "human_ratings.jsonl", ratings)
    _json(experiment / "blind_review.private.json", dict(review.receipt))
    manifest = ExperimentManifest.from_dict(
        {
            "experiment_id": "run-001",
            "status": "ready_for_approval",
            "source_hashes": baseline,
            "model": "gpt-test",
            "runtime": "codex",
            "reasoning": "high",
            "dataset_versions": {"golden": "v1"},
            "command": ["codex", "exec"],
            "created_at": "2026-09-02T00:00:00+09:00",
        }
    )
    _json(experiment / "manifest.json", manifest.to_dict())
    hypothesis = Hypothesis.from_markdown(experiment / "hypothesis.md")
    gate = GateResult(True, (), {"fixture": True})
    change = report.verify_change_assessment(
        hypothesis, (experiment / "candidate.patch").read_text(encoding="utf-8")
    )
    research = report.verify_research_evidence("run-001", hypothesis, [claim])
    score_evidence = evals.verify_score_evidence(
        aggregate,
        evaluations,
        baseline_rows,
        candidate_rows,
        expected_pairs=expected_pairs,
    )
    verification_data = manifest.to_dict()
    verification_data["status"] = "awaiting_human"
    evidence = promote_module._PromotionEvidence(
        verification_manifest=ExperimentManifest.from_dict(verification_data),
        score_evidence=score_evidence,
        review=review,
        change=change,
        research=research,
    )
    (experiment / "report.md").write_bytes(
        promote_module._rebuild_approval_report(
            experiment,
            registry,
            hypothesis,
            gate,
            evidence,
            ("demo-skill/SKILL.md",),
        ).encode("utf-8")
    )
    return ReadyFixture(
        family, experiment, canonical, registry, original, candidate_bytes
    )


def _manifest(status: str) -> ExperimentManifest:
    data = {
        "experiment_id": "run-001",
        "status": status,
        "source_hashes": {"demo-skill/SKILL.md": "1" * 64},
        "model": "gpt-test",
        "runtime": "codex",
        "reasoning": "high",
        "dataset_versions": {"golden": "v1"},
        "command": ["codex", "exec"],
        "created_at": "2026-09-02T00:00:00+09:00",
    }
    if status == "blocked_external":
        data["last_successful_status"] = "baseline_captured"
    return ExperimentManifest.from_dict(data)


def test_promote_rejects_missing_explicit_approval_before_inspecting_paths(tmp_path):
    with pytest.raises(PermissionError, match="explicit user approval"):
        promote(tmp_path / "missing", object(), approved_by_user=False)


def test_next_action_is_a_pure_explicit_status_map():
    assert next_action(_manifest("baseline_captured")) == "candidate"
    assert next_action(_manifest("blocked_external")) == "candidate"
    assert next_action(_manifest("ready_for_approval")) == "promote"


def test_repository_only_promotion_reverifies_evidence_and_records_hashes(tmp_path):
    fixture = _ready_fixture(tmp_path)
    outside = tmp_path / "not-an-install-root" / "demo-skill" / "SKILL.md"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"outside sentinel")

    result = promote(
        fixture.experiment, fixture.registry, approved_by_user=True
    )

    assert fixture.canonical.read_bytes() == fixture.candidate
    assert outside.read_bytes() == b"outside sentinel"
    assert result["installed"] is False
    assert result["pre_source_hashes"]["demo-skill/SKILL.md"] == hashlib.sha256(
        fixture.original
    ).hexdigest()
    assert result["post_source_hashes"]["demo-skill/SKILL.md"] == hashlib.sha256(
        fixture.candidate
    ).hexdigest()
    stored = json.loads((fixture.experiment / "promotion.json").read_text("utf-8"))
    manifest = json.loads((fixture.experiment / "manifest.json").read_text("utf-8"))
    assert stored == result
    assert manifest["status"] == "promoted"
    assert manifest["source_hashes"] == result["post_source_hashes"]
    assert (
        fixture.family / "dist" / "codex" / "demo-skill" / "SKILL.md"
    ).read_bytes() == fixture.candidate


@pytest.mark.parametrize(
    "mutate, error",
    [
        (
            lambda fixture: _json(
                fixture.experiment / "manifest.json",
                {
                    **json.loads(
                        (fixture.experiment / "manifest.json").read_text("utf-8")
                    ),
                    "status": "candidate_ready",
                },
            ),
            "ready_for_approval",
        ),
        (
            lambda fixture: (fixture.experiment / "report.md").unlink(),
            "artifacts",
        ),
        (
            lambda fixture: fixture.canonical.write_bytes(b"source drift"),
            "source hashes",
        ),
        (
            lambda fixture: (fixture.experiment / "candidate.patch").write_text(
                "tampered patch", encoding="utf-8"
            ),
            "candidate patch",
        ),
        (
            lambda fixture: _json(
                fixture.experiment / "scores.json",
                {
                    **json.loads(
                        (fixture.experiment / "scores.json").read_text("utf-8")
                    ),
                    "expected_pairs": [],
                },
            ),
            "score evidence",
        ),
    ],
)
def test_promotion_rejects_invalid_state_or_evidence_before_any_write(
    tmp_path, mutate, error
):
    fixture = _ready_fixture(tmp_path)
    mutate(fixture)
    before_manifest = (fixture.experiment / "manifest.json").read_bytes()
    before_canonical = fixture.canonical.read_bytes()

    with pytest.raises((ValueError, PermissionError), match=error):
        promote(fixture.experiment, fixture.registry, approved_by_user=True)

    assert fixture.canonical.read_bytes() == before_canonical
    assert (fixture.experiment / "manifest.json").read_bytes() == before_manifest
    assert not (fixture.experiment / "promotion.json").exists()


def test_promotion_requires_exact_direct_child_experiment_directory(tmp_path):
    fixture = _ready_fixture(tmp_path)
    nested = fixture.experiment / "nested"
    nested.mkdir()

    with pytest.raises(ValueError, match="direct child"):
        promote(nested, fixture.registry, approved_by_user=True)

    assert fixture.canonical.read_bytes() == fixture.original


def test_promotion_rejects_candidate_evidence_bound_to_baseline_snapshot(
    tmp_path,
):
    fixture = _ready_fixture(
        tmp_path, candidate_uses_baseline_snapshot=True
    )
    before_manifest = (fixture.experiment / "manifest.json").read_bytes()

    with pytest.raises(ValueError, match="candidate.*source snapshot"):
        promote(fixture.experiment, fixture.registry, approved_by_user=True)

    assert fixture.canonical.read_bytes() == fixture.original
    assert (fixture.experiment / "manifest.json").read_bytes() == before_manifest
    assert not (fixture.experiment / "promotion.json").exists()


def test_promotion_rejects_same_identity_with_weaker_canonical_case_evidence(tmp_path):
    fixture = _ready_fixture(tmp_path)
    canonical = fixture.family / "evals" / "golden" / "case-one.jsonl"
    weaker = json.loads(canonical.read_text(encoding="utf-8"))
    weaker["deterministic_checks"] = {"output_present": True}
    canonical.write_text(
        json.dumps(weaker, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="canonical.*case.*evidence"):
        promote(fixture.experiment, fixture.registry, approved_by_user=True)

    assert fixture.canonical.read_bytes() == fixture.original
    assert not (fixture.experiment / "promotion.json").exists()


def test_promotion_skips_only_the_known_dev_policy_fixture(tmp_path):
    policy_fixture = (
        '{"case_id":"optimizer-no-evidence","policy":"no_evidence_no_candidate",'
        '"expected_error":"claims must not be empty"}\n'
        '{"case_id":"optimizer-low-risk-packaging",'
        '"policy":"low_risk_packaging_skips_human_blind",'
        '"expected_human_required":false}\n'
        '{"case_id":"optimizer-persona-change",'
        '"policy":"persona_change_requires_human_blind",'
        '"expected_human_required":true}\n'
        '{"case_id":"optimizer-failed-command",'
        '"policy":"failed_command_is_blocked_external",'
        '"expected_status":"blocked_external"}\n'
        '{"case_id":"optimizer-unapproved-promotion",'
        '"policy":"unapproved_promotion_is_denied",'
        '"expected_error":"promotion requires explicit user approval"}\n'
    )
    valid = _ready_fixture(tmp_path / "valid")
    valid_policy = valid.family / "evals" / "dev" / "optimizer_smoke.jsonl"
    valid_policy.parent.mkdir(parents=True)
    valid_policy.write_text(policy_fixture, encoding="utf-8")

    result = promote(valid.experiment, valid.registry, approved_by_user=True)

    assert result["changed_paths"] == ["demo-skill/SKILL.md"]

    malformed = _ready_fixture(tmp_path / "malformed")
    malformed_dev = malformed.family / "evals" / "dev"
    malformed_dev.mkdir(parents=True)
    (malformed_dev / "optimizer_smoke.jsonl").write_text(
        policy_fixture, encoding="utf-8"
    )
    (malformed_dev / "not-an-eval-case.jsonl").write_text(
        '{"case_id":"malformed"}\n', encoding="utf-8"
    )

    with pytest.raises(ValueError, match="score evidence.*missing required"):
        promote(malformed.experiment, malformed.registry, approved_by_user=True)

    assert malformed.canonical.read_bytes() == malformed.original
    assert not (malformed.experiment / "promotion.json").exists()


def test_multi_skill_promotion_accepts_selected_skill_snapshots_and_rejects_wrong_skill(
    tmp_path,
):
    valid = _ready_fixture(tmp_path / "valid", multi_skill=True)
    unrelated = valid.family / "other-skill" / "SKILL.md"
    unrelated_before = unrelated.read_bytes()

    result = promote(valid.experiment, valid.registry, approved_by_user=True)

    assert valid.canonical.read_bytes() == valid.candidate
    assert unrelated.read_bytes() == unrelated_before
    assert result["changed_paths"] == ["demo-skill/SKILL.md"]

    wrong = _ready_fixture(
        tmp_path / "wrong",
        multi_skill=True,
        candidate_uses_other_skill_snapshot=True,
    )
    before_manifest = (wrong.experiment / "manifest.json").read_bytes()

    with pytest.raises(ValueError, match="candidate.*source snapshot"):
        promote(wrong.experiment, wrong.registry, approved_by_user=True)

    assert wrong.canonical.read_bytes() == wrong.original
    assert (wrong.experiment / "manifest.json").read_bytes() == before_manifest
    assert not (wrong.experiment / "promotion.json").exists()


def test_promotion_rejects_tampered_or_stale_report_before_writes(tmp_path):
    fixture = _ready_fixture(tmp_path)
    (fixture.experiment / "report.md").write_text(
        "# stale but plausible approval report\n", encoding="utf-8"
    )
    before_manifest = (fixture.experiment / "manifest.json").read_bytes()

    with pytest.raises(ValueError, match="report.md.*exact.*evidence"):
        promote(fixture.experiment, fixture.registry, approved_by_user=True)

    assert fixture.canonical.read_bytes() == fixture.original
    assert (fixture.experiment / "manifest.json").read_bytes() == before_manifest
    assert not (fixture.experiment / "promotion.json").exists()


def test_promotion_rejects_report_with_byte_different_newlines(tmp_path):
    fixture = _ready_fixture(tmp_path)
    report_path = fixture.experiment / "report.md"
    expected = report_path.read_bytes()
    crlf = expected.replace(b"\n", b"\r\n")
    assert crlf != expected
    report_path.write_bytes(crlf)
    before_manifest = (fixture.experiment / "manifest.json").read_bytes()

    with pytest.raises(ValueError, match="report.md.*exact.*evidence"):
        promote(fixture.experiment, fixture.registry, approved_by_user=True)

    assert fixture.canonical.read_bytes() == fixture.original
    assert (fixture.experiment / "manifest.json").read_bytes() == before_manifest
    assert not (fixture.experiment / "promotion.json").exists()


def test_static_only_report_omits_blind_artifacts_and_rating_claim(tmp_path):
    fixture = _ready_fixture(tmp_path)
    experiment = fixture.experiment
    for name in (
        "blind_pairs.jsonl",
        "blind_key.private.json",
        "human_ratings.jsonl",
        "blind_review.private.json",
    ):
        (experiment / name).unlink()
    claim = normalize_claim(
        {
            "claim": "The deterministic sync wrapper must remain synchronized.",
            "source_url": "https://example.test/static-sync",
            "source_date": "2026-08-01",
            "checked_at": "2026-09-02",
            "source_type": "technical_report",
            "evidence": "The static check verifies synchronized generated outputs.",
            "confidence": "high",
            "local_evidence": ["sync_core.py"],
            "decision_impact": "Update only the static sync wrapper.",
            "proposed_test": "Run the deterministic sync check.",
        }
    )
    claim_id = report.research_claim_id(claim)
    write_jsonl(experiment / "research.jsonl", [claim])
    (experiment / "hypothesis.md").write_text(
        "---\n"
        f"claim_ids: [{claim_id}]\n"
        "change_group: packaging/static-sync\n"
        "allowed_paths: [sync_core.py]\n"
        "primary_axis: resource_use\n"
        "protected_axes: [meaning_and_facts]\n"
        "risk: low\n"
        "blind_required: false\n"
        "stop_rule: reject deterministic regressions\n"
        "---\n"
        "Update only the verified static sync wrapper.\n",
        encoding="utf-8",
    )
    patch = (
        "--- a/sync_core.py\n"
        "+++ b/sync_core.py\n"
        "@@ -1 +1 @@\n"
        "-old\n"
        "+new\n"
    )
    (experiment / "candidate.patch").write_text(patch, encoding="utf-8")
    hypothesis = Hypothesis.from_markdown(experiment / "hypothesis.md")
    manifest = ExperimentManifest.from_dict(
        json.loads((experiment / "manifest.json").read_text("utf-8"))
    )
    verification_data = manifest.to_dict()
    verification_data["status"] = "auto_evaluated"
    baseline_rows = list(read_jsonl(experiment / "baseline.jsonl"))
    candidate_rows = list(read_jsonl(experiment / "candidate.jsonl"))
    scores = json.loads((experiment / "scores.json").read_text("utf-8"))
    for evaluation in scores["evaluation_rows"]:
        for axis in AXES:
            evaluation["scores"][axis] = {
                "passed": True,
                "status": "scored",
                "evidence": {},
            }
    scores["aggregate"] = evals.aggregate_scores(
        scores["evaluation_rows"], expected_pairs=scores["expected_pairs"]
    )
    _json(experiment / "scores.json", scores)
    score_evidence = evals.verify_score_evidence(
        scores["aggregate"],
        scores["evaluation_rows"],
        baseline_rows,
        candidate_rows,
        expected_pairs=scores["expected_pairs"],
    )
    evidence = promote_module._PromotionEvidence(
        verification_manifest=ExperimentManifest.from_dict(verification_data),
        score_evidence=score_evidence,
        review=None,
        change=report.verify_change_assessment(hypothesis, patch),
        research=report.verify_research_evidence("run-001", hypothesis, [claim]),
    )
    gate = GateResult(True, (), {"fixture": True})
    readiness = report.evaluate_readiness(
        evidence.verification_manifest,
        hypothesis,
        gate,
        evidence.score_evidence,
        None,
        evidence.change,
        evidence.research,
    )
    assert readiness.status == "ready_for_approval", readiness.reasons

    rendered = promote_module._rebuild_approval_report(
        experiment,
        fixture.registry,
        hypothesis,
        gate,
        evidence,
        ("sync_core.py",),
    )

    assert "blind_pairs.jsonl" not in rendered
    assert "human_ratings.jsonl" not in rendered
    assert "## Human Blind Review" not in rendered
    assert "사용자 1인의 선호" not in rendered
    assert "Aggregate preference" not in rendered
    (experiment / "report.md").write_bytes(rendered.encode("utf-8"))
    promote_module._validate_approval_report(experiment, rendered)


def test_explicit_install_root_updates_owned_files_and_preserves_extras(tmp_path):
    fixture = _ready_fixture(tmp_path)
    install_root = tmp_path / "named-install-root"
    installed_skill = install_root / "demo-skill"
    installed_skill.mkdir(parents=True)
    baseline_render = fixture.family / "dist" / "codex" / "demo-skill"
    for source in baseline_render.rglob("*"):
        if source.is_file():
            target = installed_skill / source.relative_to(baseline_render)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
    extra = installed_skill / "user-notes.txt"
    extra.write_bytes(b"unowned")

    result = promote(
        fixture.experiment,
        fixture.registry,
        approved_by_user=True,
        install_root=install_root,
    )

    assert (installed_skill / "SKILL.md").read_bytes() == fixture.candidate
    assert extra.read_bytes() == b"unowned"
    assert result["installed"] is True


def test_install_root_is_validated_before_repository_writes(tmp_path):
    fixture = _ready_fixture(tmp_path)
    missing_skill_root = tmp_path / "named-install-root"
    missing_skill_root.mkdir()

    with pytest.raises(ValueError, match="expected target skill"):
        promote(
            fixture.experiment,
            fixture.registry,
            approved_by_user=True,
            install_root=missing_skill_root,
        )

    assert fixture.canonical.read_bytes() == fixture.original


def test_missing_or_broad_install_root_is_rejected_as_value_error(tmp_path):
    missing_fixture = _ready_fixture(tmp_path / "missing-case")
    with pytest.raises(ValueError, match="install_root"):
        promote(
            missing_fixture.experiment,
            missing_fixture.registry,
            approved_by_user=True,
            install_root=tmp_path / "missing-install-root",
        )
    assert missing_fixture.canonical.read_bytes() == missing_fixture.original

    broad_fixture = _ready_fixture(tmp_path / "broad-case")
    with pytest.raises(ValueError, match="broad"):
        promote(
            broad_fixture.experiment,
            broad_fixture.registry,
            approved_by_user=True,
            install_root=broad_fixture.family.parent,
        )
    assert broad_fixture.canonical.read_bytes() == broad_fixture.original


def test_tampered_install_target_is_rejected_as_unowned_before_writes(tmp_path):
    fixture = _ready_fixture(tmp_path)
    install_root = tmp_path / "named-install-root"
    installed_skill = install_root / "demo-skill"
    installed_skill.mkdir(parents=True)
    (installed_skill / "SKILL.md").write_bytes(b"locally modified")

    with pytest.raises(ValueError, match="installed target"):
        promote(
            fixture.experiment,
            fixture.registry,
            approved_by_user=True,
            install_root=install_root,
        )

    assert fixture.canonical.read_bytes() == fixture.original
    assert (installed_skill / "SKILL.md").read_bytes() == b"locally modified"


def test_symlinked_install_root_alias_is_rejected_before_writes(tmp_path):
    fixture = _ready_fixture(tmp_path)
    actual_root = tmp_path / "actual-install-root"
    installed_skill = actual_root / "demo-skill"
    installed_skill.mkdir(parents=True)
    baseline_render = fixture.family / "dist" / "codex" / "demo-skill"
    (installed_skill / "SKILL.md").write_bytes(
        (baseline_render / "SKILL.md").read_bytes()
    )
    alias = tmp_path / "install-root-alias"
    try:
        alias.symlink_to(actual_root, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlinks are unavailable: {error}")

    with pytest.raises(ValueError, match="symlink|junction|reparse"):
        promote(
            fixture.experiment,
            fixture.registry,
            approved_by_user=True,
            install_root=alias,
        )

    assert fixture.canonical.read_bytes() == fixture.original
    assert (installed_skill / "SKILL.md").read_bytes() == fixture.original


def test_replacement_failure_rolls_back_exact_bytes_metadata_and_marks_invalid(
    tmp_path, monkeypatch
):
    fixture = _ready_fixture(tmp_path)
    before_stat = fixture.canonical.stat()
    generated_target = (
        fixture.family / "dist" / "codex" / "demo-skill" / "SKILL.md"
    )
    real_replace = os.replace
    failed = False

    def fail_once(source, destination):
        nonlocal failed
        if Path(destination) == generated_target and not failed:
            failed = True
            raise OSError("injected replacement failure")
        return real_replace(source, destination)

    monkeypatch.setattr(promote_module.os, "replace", fail_once)

    with pytest.raises(OSError, match="injected replacement failure"):
        promote(fixture.experiment, fixture.registry, approved_by_user=True)

    after_stat = fixture.canonical.stat()
    assert fixture.canonical.read_bytes() == fixture.original
    assert stat.S_IMODE(after_stat.st_mode) == stat.S_IMODE(before_stat.st_mode)
    assert after_stat.st_mtime_ns == before_stat.st_mtime_ns
    manifest = json.loads((fixture.experiment / "manifest.json").read_text("utf-8"))
    assert manifest["status"] == "invalid"
    assert not (fixture.experiment / "promotion.json").exists()


def test_post_write_hash_failure_rolls_back_every_target(tmp_path, monkeypatch):
    fixture = _ready_fixture(tmp_path)
    real_replace = os.replace
    corrupted = False

    def corrupt_once(source, destination):
        nonlocal corrupted
        result = real_replace(source, destination)
        if Path(destination) == fixture.canonical and not corrupted:
            corrupted = True
            Path(destination).write_bytes(b"corrupted after replace")
        return result

    monkeypatch.setattr(promote_module.os, "replace", corrupt_once)

    with pytest.raises(OSError, match="post-write hash"):
        promote(fixture.experiment, fixture.registry, approved_by_user=True)

    assert fixture.canonical.read_bytes() == fixture.original
    assert json.loads(
        (fixture.experiment / "manifest.json").read_text("utf-8")
    )["status"] == "invalid"


def test_partial_adjacent_stage_is_removed_when_copy_fails(tmp_path, monkeypatch):
    fixture = _ready_fixture(tmp_path)
    real_copy2 = promote_module.shutil.copy2
    injected = False

    def partial_copy(source, destination, *args, **kwargs):
        nonlocal injected
        destination = Path(destination)
        if ".promotion-stage-" in destination.name and not injected:
            injected = True
            destination.write_bytes(b"partial stage bytes")
            raise OSError("injected partial copy failure")
        return real_copy2(source, destination, *args, **kwargs)

    monkeypatch.setattr(promote_module.shutil, "copy2", partial_copy)

    with pytest.raises(OSError, match="injected partial copy failure"):
        promote(fixture.experiment, fixture.registry, approved_by_user=True)

    assert fixture.canonical.read_bytes() == fixture.original
    assert not list(fixture.family.rglob("*.promotion-stage-*"))
    assert json.loads(
        (fixture.experiment / "manifest.json").read_text("utf-8")
    )["status"] == "invalid"


def test_backup_cleanup_failure_does_not_turn_a_committed_promotion_invalid(
    tmp_path, monkeypatch
):
    fixture = _ready_fixture(tmp_path)
    real_unlink = Path.unlink

    def retain_backups(path, *args, **kwargs):
        if ".promotion-backup-" in path.name:
            raise OSError("injected cleanup failure")
        return real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", retain_backups)

    with pytest.warns(RuntimeWarning, match="retained promotion backup"):
        result = promote(
            fixture.experiment, fixture.registry, approved_by_user=True
        )

    assert result["installed"] is False
    assert fixture.canonical.read_bytes() == fixture.candidate
    assert json.loads(
        (fixture.experiment / "manifest.json").read_text("utf-8")
    )["status"] == "promoted"
    assert snapshot_registry(fixture.registry) == result["post_source_hashes"]


def test_report_mode_rejects_symlinked_artifact_and_remains_read_only(
    tmp_path, capsys
):
    fixture = _ready_fixture(tmp_path)
    report_path = fixture.experiment / "report.md"
    outside = tmp_path / "outside-report.md"
    outside.write_text("secret outside report\n", encoding="utf-8")
    report_path.unlink()
    try:
        report_path.symlink_to(outside)
    except OSError as error:
        pytest.skip(f"file symlinks are unavailable: {error}")
    before = fixture.canonical.read_bytes()

    with pytest.raises(ValueError, match="symlink|junction|reparse"):
        cli.main(
            [
                "--root",
                str(fixture.family),
                "report",
                "--experiment",
                "run-001",
            ]
        )

    assert fixture.canonical.read_bytes() == before
    assert capsys.readouterr().out == ""


def test_cli_help_lists_five_modes_and_promote_requires_approval():
    loop = SCRIPTS / "loop.py"
    help_result = subprocess.run(
        [sys.executable, str(loop), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )
    missing_approval = subprocess.run(
        [sys.executable, str(loop), "promote", "--experiment", "run-001"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert help_result.returncode == 0
    assert all(
        mode in help_result.stdout
        for mode in ("bootstrap", "cycle", "resume", "report", "promote")
    )
    assert missing_approval.returncode != 0
    assert "--approved-by-user" in missing_approval.stderr
