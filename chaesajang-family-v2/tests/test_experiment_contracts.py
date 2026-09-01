import json
import os
import sys
from pathlib import Path

import pytest


@pytest.fixture
def loop_modules():
    scripts = Path(__file__).resolve().parents[1] / "chaesajang-family-optimizer" / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        from optimizer_loop import artifacts, contracts

        yield artifacts, contracts
    finally:
        sys.path.remove(str(scripts))


def make_manifest(contracts, *, status="researching"):
    return contracts.ExperimentManifest.from_dict(
        {
            "experiment_id": "2026-08-29-001",
            "status": status,
            "source_hashes": {"chaesajang-core/persona_core.md": "abc"},
            "model": "gpt-5.6",
            "runtime": "codex",
            "reasoning": "high",
            "dataset_versions": {"dev": "v1", "golden": "v1", "holdout": "v1"},
            "command": ["codex", "exec"],
            "created_at": "2026-08-29T22:00:00+09:00",
        }
    )


def test_manifest_round_trips_provenance(loop_modules):
    _, contracts = loop_modules
    manifest = make_manifest(contracts)
    assert contracts.ExperimentManifest.from_dict(manifest.to_dict()) == manifest


@pytest.mark.parametrize("field", ["experiment_id", "source_hashes", "command", "created_at"])
def test_manifest_rejects_missing_required_fields(loop_modules, field):
    _, contracts = loop_modules
    data = make_manifest(contracts).to_dict()
    data.pop(field)
    with pytest.raises(ValueError, match="missing manifest fields"):
        contracts.ExperimentManifest.from_dict(data)


def test_manifest_rejects_unknown_fields_and_path_traversal(loop_modules):
    _, contracts = loop_modules
    data = make_manifest(contracts).to_dict()
    data["unexpected"] = True
    with pytest.raises(ValueError, match="unknown manifest fields"):
        contracts.ExperimentManifest.from_dict(data)

    data = make_manifest(contracts).to_dict()
    data["experiment_id"] = "../outside"
    with pytest.raises(ValueError, match="experiment_id"):
        contracts.ExperimentManifest.from_dict(data)


def test_transition_allows_only_declared_next_states(loop_modules):
    _, contracts = loop_modules
    manifest = make_manifest(contracts, status="researching")
    advanced = contracts.transition(manifest, contracts.ExperimentStatus.HYPOTHESIS_READY)
    assert advanced.status is contracts.ExperimentStatus.HYPOTHESIS_READY

    with pytest.raises(ValueError, match="invalid transition"):
        contracts.transition(manifest, contracts.ExperimentStatus.BASELINE_CAPTURED)


@pytest.mark.parametrize(
    "source_status",
    ["baseline_captured", "candidate_ready"],
)
def test_blocked_external_preserves_completed_stage_artifacts(
    tmp_path, loop_modules, source_status
):
    artifacts, contracts = loop_modules
    manifest = make_manifest(contracts, status=source_status)
    blocked = contracts.transition(manifest, contracts.ExperimentStatus.BLOCKED_EXTERNAL)

    assert blocked.last_successful_status is manifest.status
    assert artifacts.validate_artifacts(tmp_path, blocked, risk="behavior") == list(
        artifacts.required_artifacts(manifest.status, "behavior")
    )


@pytest.mark.parametrize("terminal_status", ["blocked_external", "rejected", "invalid"])
def test_terminal_manifest_requires_nonterminal_completed_stage_context(
    loop_modules, terminal_status
):
    _, contracts = loop_modules
    data = make_manifest(contracts).to_dict()
    data["status"] = terminal_status
    with pytest.raises(ValueError, match="last_successful_status"):
        contracts.ExperimentManifest.from_dict(data)

    data["last_successful_status"] = "invalid"
    with pytest.raises(ValueError, match="last_successful_status"):
        contracts.ExperimentManifest.from_dict(data)


@pytest.mark.parametrize(
    ("source_status", "terminal_status"),
    [
        ("hypothesis_ready", "rejected"),
        ("auto_evaluated", "invalid"),
    ],
)
def test_other_contextual_terminal_states_require_source_stage_artifacts(
    tmp_path, loop_modules, source_status, terminal_status
):
    artifacts, contracts = loop_modules
    manifest = make_manifest(contracts, status=source_status)
    terminal = contracts.transition(
        manifest, contracts.ExperimentStatus(terminal_status)
    )

    assert terminal.last_successful_status is manifest.status
    assert artifacts.validate_artifacts(tmp_path, terminal, risk="behavior") == list(
        artifacts.required_artifacts(manifest.status, "behavior")
    )


def test_resume_from_blocked_external_returns_only_to_recorded_stage(loop_modules):
    _, contracts = loop_modules
    manifest = make_manifest(contracts, status="candidate_ready")
    blocked = contracts.transition(manifest, contracts.ExperimentStatus.BLOCKED_EXTERNAL)

    resumed = contracts.transition(blocked, contracts.ExperimentStatus.CANDIDATE_READY)
    assert resumed.status is contracts.ExperimentStatus.CANDIDATE_READY
    assert resumed.last_successful_status is None
    with pytest.raises(ValueError, match="recorded successful state"):
        contracts.transition(blocked, contracts.ExperimentStatus.BASELINE_CAPTURED)


def test_completed_stages_require_only_completed_artifacts(loop_modules):
    artifacts, contracts = loop_modules
    assert artifacts.required_artifacts(
        contracts.ExperimentStatus.RESEARCHING, "low", blind_required=False
    ) == (
        "manifest.json",
    )
    assert artifacts.required_artifacts(
        contracts.ExperimentStatus.CANDIDATE_READY, "low", blind_required=False
    ) == (
        "manifest.json",
        "research.jsonl",
        "hypothesis.md",
        "baseline.jsonl",
        "candidate.patch",
    )
    assert "candidate.jsonl" not in artifacts.required_artifacts(
        contracts.ExperimentStatus.CANDIDATE_READY, "low", blind_required=False
    )
    assert "scores.json" not in artifacts.required_artifacts(
        contracts.ExperimentStatus.CANDIDATE_READY, "low", blind_required=False
    )


def test_ready_for_approval_requires_human_files_for_risky_change(tmp_path, loop_modules):
    artifacts, contracts = loop_modules
    manifest = make_manifest(contracts, status="ready_for_approval")
    missing = artifacts.validate_artifacts(tmp_path, manifest, risk="behavior")
    assert "blind_pairs.jsonl" in missing
    assert "human_ratings.jsonl" in missing


def test_human_review_artifacts_preserve_private_reverification_chain(loop_modules):
    artifacts, contracts = loop_modules
    awaiting = artifacts.required_artifacts(
        contracts.ExperimentStatus.AWAITING_HUMAN, "behavior"
    )
    ready = artifacts.required_artifacts(
        contracts.ExperimentStatus.READY_FOR_APPROVAL, "behavior"
    )

    assert "blind_pairs.jsonl" in awaiting
    assert "blind_key.private.json" in awaiting
    assert "human_ratings.jsonl" not in awaiting
    assert "blind_review.private.json" not in awaiting
    assert {
        "blind_pairs.jsonl",
        "blind_key.private.json",
        "human_ratings.jsonl",
        "blind_review.private.json",
    }.issubset(ready)


def test_explicit_blind_requirement_overrides_low_risk_artifact_shortcut(loop_modules):
    artifacts, contracts = loop_modules
    required = artifacts.required_artifacts(
        contracts.ExperimentStatus.READY_FOR_APPROVAL,
        "low",
        blind_required=True,
    )

    assert "blind_key.private.json" in required
    assert "blind_review.private.json" in required


def test_terminal_context_keeps_private_artifacts_from_last_successful_stage(
    tmp_path, loop_modules
):
    artifacts, contracts = loop_modules
    awaiting = make_manifest(contracts, status="awaiting_human")
    invalid = contracts.transition(awaiting, contracts.ExperimentStatus.INVALID)

    missing = artifacts.validate_artifacts(
        tmp_path, invalid, risk="low", blind_required=True
    )

    assert "blind_pairs.jsonl" in missing
    assert "blind_key.private.json" in missing


def test_omitted_blind_requirement_is_conservative_and_static_skip_is_explicit(
    tmp_path, loop_modules
):
    artifacts, contracts = loop_modules
    manifest = make_manifest(contracts, status="ready_for_approval")
    conservative = artifacts.required_artifacts(manifest.status, "low")
    explicit_static = artifacts.required_artifacts(
        manifest.status, "low", blind_required=False
    )

    assert "blind_pairs.jsonl" in conservative
    assert "human_ratings.jsonl" in conservative
    assert "blind_pairs.jsonl" not in explicit_static
    assert "human_ratings.jsonl" not in explicit_static
    assert artifacts.validate_artifacts(tmp_path, manifest, risk="low") == list(
        conservative
    )
    assert artifacts.validate_artifacts(
        tmp_path, manifest, risk="low", blind_required=False
    ) == list(explicit_static)


def test_write_jsonl_uses_replace_after_writing_a_sibling(tmp_path, loop_modules, monkeypatch):
    artifacts, _ = loop_modules
    destination = tmp_path / "rows.jsonl"
    seen = []
    original_replace = os.replace

    def checked_replace(source, target):
        source_path = Path(source)
        target_path = Path(target)
        seen.append((source_path, target_path, source_path.read_text(encoding="utf-8")))
        assert source_path.parent == destination.parent
        assert target_path == destination
        return original_replace(source, target)

    monkeypatch.setattr(artifacts.os, "replace", checked_replace)
    artifacts.write_jsonl(destination, [{"case_id": "one"}, {"case_id": "two"}])

    assert len(seen) == 1
    temporary, replaced_target, contents = seen[0]
    assert temporary.name.startswith(".rows.jsonl.")
    assert replaced_target == destination
    assert contents == '{"case_id": "one"}\n{"case_id": "two"}\n'
    assert artifacts.read_jsonl(destination) == [{"case_id": "one"}, {"case_id": "two"}]


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_write_jsonl_rejects_nonstandard_numeric_values(tmp_path, loop_modules, value):
    artifacts, _ = loop_modules
    with pytest.raises(ValueError):
        artifacts.write_jsonl(tmp_path / "rows.jsonl", [{"score": value}])


@pytest.mark.parametrize(
    ("contents", "message"),
    [
        ('{"ok": true}\nnot-json\n', "invalid JSONL"),
        ('["not-a-row"]\n', "JSON object"),
        ('{"score": NaN}\n', "invalid JSONL"),
        ('{"score": Infinity}\n', "invalid JSONL"),
    ],
)
def test_read_jsonl_rejects_malformed_rows(tmp_path, loop_modules, contents, message):
    artifacts, _ = loop_modules
    path = tmp_path / "malformed.jsonl"
    path.write_text(contents, encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        artifacts.read_jsonl(path)
