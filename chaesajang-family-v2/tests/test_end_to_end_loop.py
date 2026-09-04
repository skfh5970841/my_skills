import json
import re
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "chaesajang-family-optimizer" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from optimizer_loop import blind, evals, generate, report, runner
from optimizer_loop.candidate import (
    changed_canonical_files,
    create_candidate,
    validate_change_scope,
    write_candidate_patch,
)
from optimizer_loop.contracts import ExperimentManifest
from optimizer_loop.hypothesis import Hypothesis
from optimizer_loop.promote import promote
from optimizer_loop.registry import load_registry
from optimizer_loop.render import render_all
from optimizer_loop.research import normalize_claim
from optimizer_loop.snapshot import snapshot_registry
from optimizer_loop.static_gate import run_static_gate


def _write_fixture_family(root: Path) -> None:
    (root / "demo-core").mkdir(parents=True)
    skill = root / "demo-skill"
    skill.mkdir()
    (skill / "SKILL.md").write_text(
        "---\nname: demo-skill\ndescription: Use when a deterministic fixture is requested.\n---\n\n"
        "# Demo skill\n\nState the core fact.\n",
        encoding="utf-8",
    )
    (root / "family.yaml").write_text(
        "schema_version: 1\n"
        "core: demo-core\n"
        "skills:\n"
        "  - name: demo-skill\n"
        "    source: demo-skill\n"
        "    core_files: []\n"
        "    inject_gaze: false\n"
        "generated:\n"
        "  compatibility_snapshots: skills\n"
        "  dist: dist\n"
        "  experiments: experiments\n"
        "  package_extension: .skill\n"
        "adapters:\n"
        "  codex:\n"
        "    exclude: []\n"
        "  claude:\n"
        "    exclude: []\n",
        encoding="utf-8",
    )


def _generation_config(source_root: Path) -> runner.RunConfig:
    root = source_root.resolve(strict=True)
    model = "fixture-model"
    reasoning = "high"
    return runner.RunConfig(
        command=(
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
            model,
            "--config",
            f'model_reasoning_effort="{reasoning}"',
            "--cd",
            str(root),
            "-",
        ),
        cwd=root,
        timeout_seconds=5,
        stdin_text="replaced by generate_cases",
        model=model,
        reasoning=reasoning,
        runtime="codex",
        expect_json=False,
    )


def _claim() -> dict:
    return normalize_claim(
        {
            "claim": "A scoped instruction change can be evaluated with fixed cases.",
            "source_url": "https://example.test/deterministic-fixture",
            "source_date": "2026-08-01",
            "checked_at": "2026-09-02",
            "source_type": "technical_report",
            "evidence": "The fixture records one scoped comparison.",
            "confidence": "high",
            "local_evidence": ["demo-skill/SKILL.md"],
            "decision_impact": "Change only the declared demo instruction.",
            "proposed_test": "Require fixed hard gates and a blind preference.",
        }
    )


def _hypothesis(claim_id: str) -> Hypothesis:
    return Hypothesis(
        claim_ids=(claim_id,),
        change_group="demo-guidance",
        allowed_paths=("demo-skill/SKILL.md",),
        primary_axis="request_fulfillment",
        protected_axes=("meaning_and_facts", "structure_and_information"),
        risk="behavior",
        blind_required=True,
        stop_rule="reject protected regressions",
        body="Change only the declared demo instruction.\n",
    )


def _case() -> evals.EvalCase:
    return evals.EvalCase.from_dict(
        {
            "case_id": "fixture-golden",
            "target_skill": "demo-skill",
            "source_group": "fixture/end-to-end",
            "generator_brief": "핵심 사실을 한 문장으로 쓰세요.",
            "axes": [
                "request_fulfillment",
                "meaning_and_facts",
                "structure_and_information",
            ],
            "risk": "behavior",
            "deterministic_checks": {
                "output_present": True,
                "exact_facts": ["핵심 사실"],
                "min_characters": 5,
            },
        },
        "golden",
    )


def _candidate_ratings(pairs: list[dict], private_key: dict) -> list[dict]:
    rows = []
    for pair in pairs:
        candidate = private_key["mapping"][pair["pair_id"]]["candidate_label"]
        rows.append(
            {
                "pair_id": pair["pair_id"],
                "quality_preference": candidate,
                "style_preference": candidate,
                "overall_preference": candidate,
                "over_imitation": "neither",
                "meaning_or_fact_issue": {"A": "none", "B": "none"},
                "evidence_excerpt": "The candidate is clearer and preserves the fact.",
            }
        )
    return rows


def test_dry_run_reaches_ready_without_touching_canonical(tmp_path, monkeypatch):
    family = tmp_path / "family"
    _write_fixture_family(family)
    registry = load_registry(family)
    before = snapshot_registry(registry)
    experiment = tmp_path / "experiment"

    claim = _claim()
    claim_id = report.research_claim_id(claim)
    hypothesis = _hypothesis(claim_id)
    research_evidence = report.verify_research_evidence(
        "fixture-run", hypothesis, [claim]
    )

    candidate_root = create_candidate(registry, experiment)
    candidate_entrypoint = candidate_root / "demo-skill" / "SKILL.md"
    candidate_entrypoint.write_text(
        candidate_entrypoint.read_text(encoding="utf-8")
        + "Make the requested fact explicit and concise.\n",
        encoding="utf-8",
    )
    changed = changed_canonical_files(registry, candidate_root, before)
    assert changed == ("demo-skill/SKILL.md",)
    assert validate_change_scope(hypothesis, changed) == []
    patch_path = experiment / "candidate.patch"
    write_candidate_patch(registry, candidate_root, patch_path)
    change_evidence = report.verify_change_assessment(
        hypothesis, patch_path.read_text(encoding="utf-8")
    )

    candidate_dist = tmp_path / "candidate-dist"
    render_all(registry, candidate_root, candidate_dist)
    gate = run_static_gate(registry, candidate_root, candidate_dist)
    assert gate.passed, gate.errors

    outputs = iter(("핵심 사실.", "더 명확한 핵심 사실."))
    monkeypatch.setattr(
        generate,
        "run_command",
        lambda _config: runner.RunResult("completed", 0, next(outputs), "", 1),
    )
    case = _case()
    public_case = {
        "case_id": case.case_id,
        "target_skill": case.target_skill,
        "generator_brief": case.generator_brief,
    }
    baseline_rows = generate.generate_cases(
        [public_case], family, _generation_config(family), repeats=1
    )
    candidate_rows = generate.generate_cases(
        [public_case], candidate_root, _generation_config(candidate_root), repeats=1
    )
    evaluation_rows = [
        evals.make_deterministic_row(case, baseline_rows[0], "baseline"),
        evals.make_deterministic_row(case, candidate_rows[0], "candidate"),
    ]
    expected_pairs = [evals.expected_pair(case, repeat=0)]
    aggregate = evals.aggregate_scores(
        evaluation_rows, expected_pairs=expected_pairs
    )
    score_evidence = evals.verify_score_evidence(
        aggregate,
        evaluation_rows,
        baseline_rows,
        candidate_rows,
        expected_pairs=expected_pairs,
    )
    pairs, private_key = blind.make_blind_package(
        "fixture-run", baseline_rows, candidate_rows, seed=7
    )
    review = blind.verify_blind_review(
        "fixture-run",
        baseline_rows,
        candidate_rows,
        pairs,
        private_key,
        _candidate_ratings(pairs, private_key),
    )
    manifest = ExperimentManifest.from_dict(
        {
            "experiment_id": "fixture-run",
            "status": "auto_evaluated",
            "source_hashes": before,
            "model": "fixture-model",
            "runtime": "codex",
            "reasoning": "high",
            "dataset_versions": {"golden": "fixture-v1"},
            "command": ["codex", "exec"],
            "created_at": "2026-09-02T00:00:00+09:00",
        }
    )

    result = report.evaluate_readiness(
        manifest,
        hypothesis,
        gate,
        score_evidence,
        review,
        change_evidence,
        research_evidence,
    )

    assert result.status == "ready_for_approval", result.reasons
    assert snapshot_registry(registry) == before


def _interaction_records() -> list[dict]:
    path = ROOT / "evals" / "golden" / "interaction_cases.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_interaction_smoke_explicit_invocation_is_explicit_only():
    records = _interaction_records()
    assert len(records) == 2
    case = next(row for row in records if row["case_id"] == "interaction-explicit-invocation")
    parsed = evals.EvalCase.from_dict(case, "golden")
    prompt = generate.build_generation_prompt(case, Path("chaesajang-style/SKILL.md"))

    assert "$chaesajang-style" in parsed.generator_brief
    assert "$chaesajang-style" in prompt


def test_interaction_smoke_carries_only_explicit_handoff_input():
    records = _interaction_records()
    assert len(records) == 2
    case = next(
        row for row in records if row["case_id"] == "interaction-handoff-context-carryover"
    )
    parsed = evals.EvalCase.from_dict(case, "golden")
    prompt = generate.build_generation_prompt(case, Path("chaesajang-style/SKILL.md"))

    assert "명시적 핸드오프 입력" in parsed.generator_brief
    assert "핵심 질문=" in prompt
    assert "지속된 세션" not in prompt


def _policy_hypothesis(*, static: bool) -> Hypothesis:
    return Hypothesis(
        claim_ids=("claim",),
        change_group="packaging/static-sync" if static else "persona-layering",
        allowed_paths=("sync_core.py",) if static else ("chaesajang-core/persona_core.md",),
        primary_axis="resource_use" if static else "style_behavior",
        protected_axes=("request_fulfillment",),
        risk="low" if static else "behavior",
        blind_required=False if static else True,
        stop_rule="reject protected regressions",
        body="One deterministic policy fixture.",
    )


def test_optimizer_policy_smoke_fixtures_use_real_fail_closed_apis(tmp_path):
    path = ROOT / "evals" / "dev" / "optimizer_smoke.jsonl"
    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 5
    assert {row["policy"] for row in records} == {
        "no_evidence_no_candidate",
        "low_risk_packaging_skips_human_blind",
        "persona_change_requires_human_blind",
        "failed_command_is_blocked_external",
        "unapproved_promotion_is_denied",
    }

    for row in records:
        policy = row["policy"]
        if policy == "no_evidence_no_candidate":
            with pytest.raises(ValueError, match=re.escape(row["expected_error"])):
                report.verify_research_evidence(
                    "smoke", _policy_hypothesis(static=False), []
                )
            assert not (tmp_path / "candidate").exists()
        elif policy == "low_risk_packaging_skips_human_blind":
            evidence = report.verify_change_assessment(
                _policy_hypothesis(static=True),
                "--- a/sync_core.py\n+++ b/sync_core.py\n@@ -1 +1 @@\n-old\n+new\n",
            )
            assert evidence.human_required is row["expected_human_required"]
        elif policy == "persona_change_requires_human_blind":
            evidence = report.verify_change_assessment(
                _policy_hypothesis(static=False),
                "--- a/chaesajang-core/persona_core.md\n"
                "+++ b/chaesajang-core/persona_core.md\n@@ -1 +1 @@\n-old\n+new\n",
            )
            assert evidence.human_required is row["expected_human_required"]
        elif policy == "failed_command_is_blocked_external":
            result = runner.run_command(
                runner.RunConfig(
                    command=(sys.executable, "-c", "raise SystemExit(3)"),
                    cwd=tmp_path,
                    timeout_seconds=5,
                    stdin_text="",
                    model="fixture-model",
                    reasoning="high",
                    runtime="codex",
                )
            )
            assert result.status == row["expected_status"]
        else:
            with pytest.raises(PermissionError, match=re.escape(row["expected_error"])):
                promote(tmp_path / "missing", object(), approved_by_user=False)
