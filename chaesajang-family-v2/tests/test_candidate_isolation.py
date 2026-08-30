import sys
from pathlib import Path

import pytest


@pytest.fixture
def loop_modules():
    scripts = Path(__file__).resolve().parents[1] / "chaesajang-family-optimizer" / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        from optimizer_loop import candidate, hypothesis, snapshot
        from optimizer_loop.registry import FamilyRegistry, SkillSpec

        yield candidate, hypothesis, snapshot, FamilyRegistry, SkillSpec
    finally:
        sys.path.remove(str(scripts))


@pytest.fixture
def registry_factory(loop_modules):
    _, _, _, FamilyRegistry, SkillSpec = loop_modules

    def factory(root: Path) -> FamilyRegistry:
        core = root / "chaesajang-core"
        skill = root / "chaesajang-advisor"
        core.mkdir()
        skill.mkdir()
        (core / "persona_core.md").write_text("original\n", encoding="utf-8")
        (skill / "SKILL.md").write_text("skill\n", encoding="utf-8")
        return FamilyRegistry(
            root=root,
            core=core,
            skills=(SkillSpec("chaesajang-advisor", skill, (), False),),
            generated={},
        )

    return factory


@pytest.fixture
def hypothesis_file(tmp_path):
    path = tmp_path / "hypothesis.md"
    path.write_text(
        "---\n"
        "claim_ids: [claim-id]\n"
        "change_group: persona-layering\n"
        "allowed_paths: [chaesajang-core/persona_core.md]\n"
        "primary_axis: over_imitation\n"
        "protected_axes: [request_fulfillment, meaning_and_facts, structure_and_information]\n"
        "risk: behavior\n"
        "blind_required: true\n"
        "stop_rule: reject if a hard gate fails or baseline weakness cannot be reproduced\n"
        "---\n\n"
        "Change only the persona layer.\n",
        encoding="utf-8",
    )
    return path


@pytest.fixture
def hypothesis(loop_modules, hypothesis_file):
    _, hypothesis_module, _, _, _ = loop_modules
    return hypothesis_module.Hypothesis.from_markdown(hypothesis_file)


def test_candidate_edit_does_not_touch_canonical(tmp_path, registry_factory, loop_modules):
    candidate_module, _, snapshot, _, _ = loop_modules
    registry = registry_factory(tmp_path)
    original = snapshot.snapshot_registry(registry)
    experiment = tmp_path / "experiments" / "exp-1"

    candidate = candidate_module.create_candidate(registry, experiment)
    target = candidate / "chaesajang-core" / "persona_core.md"
    target.write_text("candidate\n", encoding="utf-8")

    assert candidate == experiment / "candidate" / "source"
    assert (tmp_path / "chaesajang-core" / "persona_core.md").read_text(encoding="utf-8") == "original\n"
    assert snapshot.snapshot_registry(registry) == original


def test_candidate_copies_only_registry_declared_files(tmp_path, registry_factory, loop_modules):
    candidate_module, _, _, _, _ = loop_modules
    registry = registry_factory(tmp_path)
    (tmp_path / "unmanaged.md").write_text("do not copy", encoding="utf-8")

    candidate = candidate_module.create_candidate(registry, tmp_path / "experiment")

    assert (candidate / "chaesajang-core" / "persona_core.md").is_file()
    assert (candidate / "chaesajang-advisor" / "SKILL.md").is_file()
    assert not (candidate / "unmanaged.md").exists()


def test_candidate_rejects_path_that_is_already_outside_experiment(tmp_path, registry_factory, loop_modules):
    candidate_module, _, _, _, _ = loop_modules
    registry = registry_factory(tmp_path)
    experiment = tmp_path / "experiment"
    (experiment / "candidate").mkdir(parents=True)
    (experiment / "candidate" / "source").symlink_to(tmp_path / "outside", target_is_directory=True)

    with pytest.raises(ValueError, match="candidate root"):
        candidate_module.create_candidate(registry, experiment)


def test_changed_files_rejects_candidate_root_symlink_to_external_tree(
    tmp_path, registry_factory, loop_modules
):
    candidate_module, _, snapshot, _, _ = loop_modules
    registry = registry_factory(tmp_path)
    baseline = snapshot.snapshot_registry(registry)
    outside = tmp_path.parent / "candidate-outside"
    outside.mkdir()
    (outside / "chaesajang-core").mkdir()
    (outside / "chaesajang-core" / "persona_core.md").write_text(
        "escaped\n", encoding="utf-8"
    )
    candidate = tmp_path / "experiment" / "candidate" / "source"
    candidate.parent.mkdir(parents=True)
    candidate.symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="candidate root"):
        candidate_module.changed_canonical_files(registry, candidate, baseline)


def test_changed_files_rejects_nested_candidate_symlink_to_external_tree(
    tmp_path, registry_factory, loop_modules
):
    candidate_module, _, snapshot, _, _ = loop_modules
    registry = registry_factory(tmp_path)
    baseline = snapshot.snapshot_registry(registry)
    candidate = candidate_module.create_candidate(registry, tmp_path / "experiment")
    outside = tmp_path.parent / "nested-candidate-outside"
    outside.mkdir()
    (candidate / "chaesajang-core" / "escaped").symlink_to(
        outside, target_is_directory=True
    )

    with pytest.raises(ValueError, match="candidate symlink"):
        candidate_module.changed_canonical_files(registry, candidate, baseline)


def test_changed_files_rejects_malformed_baseline_hash(tmp_path, registry_factory, loop_modules):
    candidate_module, _, _, _, _ = loop_modules
    registry = registry_factory(tmp_path)
    candidate = candidate_module.create_candidate(registry, tmp_path / "experiment")

    with pytest.raises(ValueError, match="baseline hash"):
        candidate_module.changed_canonical_files(
            registry,
            candidate,
            {"chaesajang-core/persona_core.md": "not-a-sha256"},
        )


def test_candidate_rejects_canonical_symlink_resolving_outside_family(
    tmp_path, registry_factory, loop_modules
):
    candidate_module, _, _, _, _ = loop_modules
    registry = registry_factory(tmp_path)
    outside = tmp_path.parent / "outside-family"
    outside.mkdir()
    (outside / "secret.md").write_text("secret", encoding="utf-8")
    (registry.core / "escaped").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="symlink.*outside"):
        candidate_module.create_candidate(registry, tmp_path / "experiment")


def test_changed_canonical_files_detects_modified_deleted_and_added_files(
    tmp_path, registry_factory, loop_modules
):
    candidate_module, _, snapshot, _, _ = loop_modules
    registry = registry_factory(tmp_path)
    baseline = snapshot.snapshot_registry(registry)
    candidate = candidate_module.create_candidate(registry, tmp_path / "experiment")
    (candidate / "chaesajang-core" / "persona_core.md").write_text("changed\n", encoding="utf-8")
    (candidate / "chaesajang-advisor" / "SKILL.md").unlink()
    (candidate / "chaesajang-core" / "new.md").write_text("new\n", encoding="utf-8")

    assert candidate_module.changed_canonical_files(registry, candidate, baseline) == (
        "chaesajang-advisor/SKILL.md",
        "chaesajang-core/new.md",
        "chaesajang-core/persona_core.md",
    )


def test_changed_files_rejects_file_to_directory_replacement(
    tmp_path, registry_factory, loop_modules
):
    candidate_module, _, snapshot, _, _ = loop_modules
    registry = registry_factory(tmp_path)
    baseline = snapshot.snapshot_registry(registry)
    candidate = candidate_module.create_candidate(registry, tmp_path / "experiment")
    target = candidate / "chaesajang-core" / "persona_core.md"
    target.unlink()
    target.mkdir()
    (target / "nested.md").write_text("hidden change\n", encoding="utf-8")

    with pytest.raises(ValueError, match="file-to-directory"):
        candidate_module.changed_canonical_files(registry, candidate, baseline)


def test_changed_files_rejects_incomplete_baseline(
    tmp_path, registry_factory, loop_modules
):
    candidate_module, _, snapshot, _, _ = loop_modules
    registry = registry_factory(tmp_path)
    baseline = snapshot.snapshot_registry(registry)
    baseline.pop("chaesajang-core/persona_core.md")
    candidate = candidate_module.create_candidate(registry, tmp_path / "experiment")

    with pytest.raises(ValueError, match="baseline"):
        candidate_module.changed_canonical_files(registry, candidate, baseline)


def test_changed_files_rejects_extra_baseline_path(
    tmp_path, registry_factory, loop_modules
):
    candidate_module, _, snapshot, _, _ = loop_modules
    registry = registry_factory(tmp_path)
    baseline = snapshot.snapshot_registry(registry)
    baseline["chaesajang-core/extra.md"] = "0" * 64
    candidate = candidate_module.create_candidate(registry, tmp_path / "experiment")

    with pytest.raises(ValueError, match="baseline"):
        candidate_module.changed_canonical_files(registry, candidate, baseline)


def test_changed_files_rejects_stale_current_canonical_snapshot(
    tmp_path, registry_factory, loop_modules
):
    candidate_module, _, snapshot, _, _ = loop_modules
    registry = registry_factory(tmp_path)
    baseline = snapshot.snapshot_registry(registry)
    candidate = candidate_module.create_candidate(registry, tmp_path / "experiment")
    (registry.core / "persona_core.md").write_text("canonical drift\n", encoding="utf-8")

    with pytest.raises(ValueError, match="baseline"):
        candidate_module.changed_canonical_files(registry, candidate, baseline)


def test_two_change_groups_are_invalid(hypothesis, loop_modules):
    candidate_module, _, _, _, _ = loop_modules

    errors = candidate_module.validate_change_scope(
        hypothesis,
        ["chaesajang-core/persona_core.md", "chaesajang-advisor/SKILL.md"],
    )

    assert errors


@pytest.mark.parametrize("path", ["/outside.md", "../outside.md", "C:/outside.md"])
def test_hypothesis_rejects_absolute_or_escaping_allowed_paths(
    hypothesis_file, loop_modules, path
):
    _, hypothesis_module, _, _, _ = loop_modules
    text = hypothesis_file.read_text(encoding="utf-8").replace(
        "chaesajang-core/persona_core.md", path
    )
    hypothesis_file.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match="allowed_paths"):
        hypothesis_module.Hypothesis.from_markdown(hypothesis_file)


def test_hypothesis_rejects_drive_relative_allowed_paths(hypothesis_file, loop_modules):
    _, hypothesis_module, _, _, _ = loop_modules
    text = hypothesis_file.read_text(encoding="utf-8").replace(
        "chaesajang-core/persona_core.md", "C:outside.md"
    )
    hypothesis_file.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match="allowed_paths"):
        hypothesis_module.Hypothesis.from_markdown(hypothesis_file)


def test_hypothesis_requires_exactly_one_change_group(hypothesis_file, loop_modules):
    _, hypothesis_module, _, _, _ = loop_modules
    hypothesis_file.write_text(
        hypothesis_file.read_text(encoding="utf-8").replace(
            "change_group: persona-layering", "change_group: [persona-layering, advisor]"
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="change_group"):
        hypothesis_module.Hypothesis.from_markdown(hypothesis_file)


def test_validate_change_scope_rejects_noncanonical_and_escaping_changes(
    hypothesis, loop_modules
):
    candidate_module, _, _, _, _ = loop_modules

    errors = candidate_module.validate_change_scope(
        hypothesis, ["../outside.md", "chaesajang-core/not-allowed.md"]
    )

    assert len(errors) == 2


def test_validate_change_scope_requires_exact_allowed_file_paths(
    hypothesis, loop_modules
):
    candidate_module, _, _, _, _ = loop_modules

    assert candidate_module.validate_change_scope(
        hypothesis, ["chaesajang-core/persona_core.md"]
    ) == []
    assert candidate_module.validate_change_scope(
        hypothesis, ["chaesajang-core/persona_core.md/nested.md"]
    )


def test_write_candidate_patch_is_deterministic_utf8_unified_diff(
    tmp_path, registry_factory, loop_modules
):
    candidate_module, _, _, _, _ = loop_modules
    registry = registry_factory(tmp_path)
    candidate = candidate_module.create_candidate(registry, tmp_path / "experiment")
    (candidate / "chaesajang-core" / "persona_core.md").write_text("changed\n", encoding="utf-8")
    output = tmp_path / "experiment" / "candidate.patch"

    candidate_module.write_candidate_patch(registry, candidate, output)

    first = output.read_bytes()
    candidate_module.write_candidate_patch(registry, candidate, output)

    assert output.read_bytes() == first
    assert output.read_text(encoding="utf-8") == (
        "--- a/chaesajang-core/persona_core.md\n"
        "+++ b/chaesajang-core/persona_core.md\n"
        "@@ -1 +1 @@\n"
        "-original\n"
        "+changed\n"
    )


def test_write_candidate_patch_rejects_binary_changes(tmp_path, registry_factory, loop_modules):
    candidate_module, _, _, _, _ = loop_modules
    registry = registry_factory(tmp_path)
    candidate = candidate_module.create_candidate(registry, tmp_path / "experiment")
    (candidate / "chaesajang-core" / "persona_core.md").write_bytes(b"\x00binary")

    with pytest.raises(ValueError, match="binary"):
        candidate_module.write_candidate_patch(
            registry, candidate, tmp_path / "experiment" / "candidate.patch"
        )
