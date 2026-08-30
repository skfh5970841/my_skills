import hashlib
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest


@pytest.fixture
def loop_modules():
    scripts = Path(__file__).resolve().parents[1] / "chaesajang-family-optimizer" / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        from optimizer_loop.registry import load_registry
        from optimizer_loop.render import package_skill, render_all, render_skill
        from optimizer_loop.static_gate import run_static_gate

        yield load_registry, package_skill, render_all, render_skill, run_static_gate
    finally:
        sys.path.remove(str(scripts))


@pytest.fixture
def registry_factory(tmp_path, loop_modules):
    load_registry, *_ = loop_modules

    def make(root: Path = tmp_path):
        (root / "chaesajang-core").mkdir(parents=True, exist_ok=True)
        (root / "chaesajang-core" / "persona_core.md").write_text("canonical persona\n", encoding="utf-8")
        (root / "chaesajang-core" / "gaze_core.md").write_text(
            "<!-- CORE:gaze BEGIN -->\ncanonical gaze\n<!-- CORE:gaze END -->\n",
            encoding="utf-8",
        )
        for name, inject_gaze in (("alpha", True), ("beta", False)):
            skill = root / name
            (skill / "references").mkdir(parents=True, exist_ok=True)
            (skill / "agents").mkdir(exist_ok=True)
            (skill / "agents" / "openai.yaml").write_text("model: test\n", encoding="utf-8")
            gaze = "<!-- CORE:gaze BEGIN -->\nstale gaze\n<!-- CORE:gaze END -->\n" if inject_gaze else ""
            (skill / "SKILL.md").write_text(
                f"---\nname: {name}\ndescription: test skill\n---\n"
                f"# {name}\n\nRead `references/persona_core.md`.\n{gaze}",
                encoding="utf-8",
            )
            (skill / "references" / "persona_core.md").write_text("stale persona\n", encoding="utf-8")
        (root / "family.yaml").write_text(
            "schema_version: 1\n"
            "core: chaesajang-core\n"
            "skills:\n"
            "  - name: alpha\n"
            "    source: alpha\n"
            "    core_files: [persona_core.md]\n"
            "    inject_gaze: true\n"
            "  - name: beta\n"
            "    source: beta\n"
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
            "    exclude: [agents]\n",
            encoding="utf-8",
        )
        return load_registry(root)

    return make


@pytest.fixture
def real_registry(loop_modules):
    load_registry, *_ = loop_modules
    return load_registry(Path(__file__).resolve().parents[1])


def make_static_fixture_valid(registry):
    """Synchronize fixture-derived source copies before expecting a clean gate."""
    (registry.root / "alpha" / "references" / "persona_core.md").write_text(
        "canonical persona\n", encoding="utf-8"
    )
    alpha = registry.root / "alpha" / "SKILL.md"
    alpha.write_text(
        alpha.read_text(encoding="utf-8").replace("stale gaze", "canonical gaze"),
        encoding="utf-8",
    )


def test_claude_adapter_excludes_agents_directory(tmp_path, real_registry, loop_modules):
    _, _, render_all, _, _ = loop_modules
    render_all(real_registry, real_registry.root, tmp_path / "dist")
    assert (tmp_path / "dist" / "codex" / "chaesajang-write-teacher" / "agents").is_dir()
    assert not (tmp_path / "dist" / "claude" / "chaesajang-write-teacher" / "agents").exists()


def test_renderer_overwrites_core_and_injects_exact_gaze_block(tmp_path, registry_factory, loop_modules):
    registry = registry_factory()
    _, _, _, render_skill, _ = loop_modules
    alpha = next(skill for skill in registry.skills if skill.name == "alpha")
    destination = tmp_path / "rendered" / "alpha"
    hashes = render_skill(registry, alpha, registry.root, destination, "codex")

    assert (destination / "references" / "persona_core.md").read_text(encoding="utf-8") == "canonical persona\n"
    assert (destination / "SKILL.md").read_text(encoding="utf-8").count("canonical gaze") == 1
    assert hashes["SKILL.md"] == hashlib.sha256((destination / "SKILL.md").read_bytes()).hexdigest()


@pytest.mark.parametrize("body", ["# alpha\n", "<!-- CORE:gaze BEGIN -->\na\n<!-- CORE:gaze END -->\n<!-- CORE:gaze BEGIN -->\nb\n<!-- CORE:gaze END -->\n"])
def test_renderer_rejects_missing_or_duplicate_gaze_markers(tmp_path, registry_factory, loop_modules, body):
    registry = registry_factory()
    _, _, _, render_skill, _ = loop_modules
    alpha = next(skill for skill in registry.skills if skill.name == "alpha")
    (registry.root / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: test\n---\n" + body, encoding="utf-8"
    )
    with pytest.raises(ValueError, match="CORE:gaze"):
        render_skill(registry, alpha, registry.root, tmp_path / "rendered" / "alpha", "codex")


def test_packages_have_stable_hashes_sorted_top_level_and_timestamps(tmp_path, registry_factory, loop_modules):
    registry = registry_factory()
    _, package_skill, render_all, _, _ = loop_modules
    first = tmp_path / "first"
    second = tmp_path / "second"
    render_all(registry, registry.root, first)
    render_all(registry, registry.root, second)
    one = first / "packages" / "alpha.skill"
    two = second / "packages" / "alpha.skill"

    assert package_skill(first / "codex" / "alpha", one) == package_skill(second / "codex" / "alpha", two)
    assert one.read_bytes() == two.read_bytes()
    with zipfile.ZipFile(one) as archive:
        names = archive.namelist()
        assert names == sorted(names)
        assert all(name.startswith("alpha/") for name in names)
        assert all(entry.date_time == (1980, 1, 1, 0, 0, 0) for entry in archive.infolist())


def test_static_gate_collects_frontmatter_reference_core_snapshot_adapter_and_package_errors(tmp_path, registry_factory, loop_modules):
    registry = registry_factory()
    _, _, render_all, _, run_static_gate = loop_modules
    dist = tmp_path / "dist"
    render_all(registry, registry.root, dist)
    (registry.root / "alpha" / "SKILL.md").write_text(
        "---\nname: [\n---\n# bad\n<!-- CORE:gaze BEGIN -->\nx\n<!-- CORE:gaze END -->\n",
        encoding="utf-8",
    )
    (registry.root / "beta" / "SKILL.md").write_text(
        "---\nname: wrong-name\ndescription: test\n---\n[missing](references/missing.md)\n", encoding="utf-8"
    )
    (registry.root / "alpha" / "references" / "persona_core.md").write_text("drift\n", encoding="utf-8")
    (registry.root / "skills" / "alpha.SKILL.md").write_text("snapshot drift\n", encoding="utf-8")
    (dist / "claude" / "alpha" / "agents").mkdir()
    (dist / "claude" / "alpha" / "agents" / "unexpected.yaml").write_text("x\n", encoding="utf-8")
    with zipfile.ZipFile(dist / "packages" / "alpha.skill", "w") as archive:
        archive.writestr("wrong/SKILL.md", "wrong")

    result = run_static_gate(registry, registry.root, dist)

    assert not result.passed
    joined = "\n".join(result.errors)
    assert "frontmatter" in joined
    assert "name-directory mismatch" in joined
    assert "broken relative reference" in joined
    assert "core drift" in joined
    assert "compatibility snapshot drift" in joined
    assert "adapter drift" in joined
    assert "ZIP layout" in joined
    assert "package hash mismatch" in joined
    assert len(result.errors) >= 8


def test_static_gate_reports_duplicate_marker_drift_without_short_circuiting(tmp_path, registry_factory, loop_modules):
    registry = registry_factory()
    _, _, render_all, _, run_static_gate = loop_modules
    dist = tmp_path / "dist"
    render_all(registry, registry.root, dist)
    path = registry.root / "alpha" / "SKILL.md"
    path.write_text(path.read_text(encoding="utf-8") + "<!-- CORE:gaze BEGIN -->\nx\n<!-- CORE:gaze END -->\n", encoding="utf-8")
    (registry.root / "skills" / "alpha.SKILL.md").write_text("drift\n", encoding="utf-8")

    result = run_static_gate(registry, registry.root, dist)

    assert not result.passed
    assert any("duplicate CORE:gaze" in error for error in result.errors)
    assert any("compatibility snapshot drift" in error for error in result.errors)


def test_render_all_rolls_back_every_destination_when_snapshot_publication_fails(tmp_path, registry_factory, loop_modules, monkeypatch):
    registry = registry_factory()
    _, _, render_all, _, _ = loop_modules
    import optimizer_loop.render as render_module

    dist = tmp_path / "dist"
    snapshots = registry.root / "skills"
    dist.mkdir()
    (dist / "old.txt").write_text("old dist\n", encoding="utf-8")
    snapshots.mkdir()
    (snapshots / "old.SKILL.md").write_text("old snapshots\n", encoding="utf-8")
    original_replace = os.replace

    def fail_snapshot_publish(source, destination):
        if Path(destination) == snapshots and Path(source).name == "snapshots":
            raise OSError("injected snapshot publication failure")
        return original_replace(source, destination)

    monkeypatch.setattr(render_module.os, "replace", fail_snapshot_publish)
    with pytest.raises(OSError, match="injected snapshot"):
        render_all(registry, registry.root, dist)

    assert (dist / "old.txt").read_text(encoding="utf-8") == "old dist\n"
    assert (snapshots / "old.SKILL.md").read_text(encoding="utf-8") == "old snapshots\n"
    assert not list(tmp_path.glob(".render-*"))
    assert not [path for path in tmp_path.iterdir() if ".backup-" in path.name]


def test_static_gate_collects_output_categories_after_missing_entrypoint(tmp_path, registry_factory, loop_modules):
    registry = registry_factory()
    _, _, render_all, _, run_static_gate = loop_modules
    dist = tmp_path / "dist"
    render_all(registry, registry.root, dist)
    (registry.root / "alpha" / "SKILL.md").unlink()
    (dist / "codex" / "alpha" / "SKILL.md").unlink()
    (dist / "packages" / "alpha.skill").write_bytes(b"not a zip")

    result = run_static_gate(registry, registry.root, dist)
    joined = "\n".join(result.errors)

    assert "missing SKILL.md" in joined
    assert "adapter drift" in joined
    assert "ZIP layout" in joined
    assert "package hash mismatch" in joined


def test_static_gate_uses_document_relative_links_without_source_root_fallback(tmp_path, registry_factory, loop_modules):
    registry = registry_factory()
    _, _, render_all, _, run_static_gate = loop_modules
    dist = tmp_path / "dist"
    render_all(registry, registry.root, dist)
    (registry.root / "alpha" / "nested").mkdir()
    (registry.root / "alpha" / "nested" / "nested.md").write_text(
        "[wrong from nested](references/persona_core.md)\n", encoding="utf-8"
    )

    result = run_static_gate(registry, registry.root, dist)

    assert any("broken relative reference references/persona_core.md" in error for error in result.errors)


def test_static_gate_reports_gaze_content_drift_separately_from_marker_count(tmp_path, registry_factory, loop_modules):
    registry = registry_factory()
    _, _, render_all, _, run_static_gate = loop_modules
    dist = tmp_path / "dist"
    render_all(registry, registry.root, dist)
    source = registry.root / "alpha" / "SKILL.md"
    source.write_text(source.read_text(encoding="utf-8").replace("stale gaze", "different gaze"), encoding="utf-8")

    result = run_static_gate(registry, registry.root, dist)

    assert any("gaze content drift" in error for error in result.errors)
    assert not any("duplicate CORE:gaze" in error for error in result.errors)


def test_codex_output_cannot_exclude_canonical_files(tmp_path, registry_factory, loop_modules):
    registry = registry_factory()
    family = registry.root / "family.yaml"
    family.write_text(family.read_text(encoding="utf-8").replace("  codex:\n    exclude: []", "  codex:\n    exclude: [agents]"), encoding="utf-8")
    load_registry, _, render_all, _, run_static_gate = loop_modules

    with pytest.raises(ValueError, match="codex"):
        load_registry(registry.root)

    render_all(registry, registry.root, tmp_path / "dist")
    assert (tmp_path / "dist" / "codex" / "alpha" / "agents").is_dir()
    assert run_static_gate(registry, registry.root, tmp_path / "dist").passed is False


@pytest.mark.filterwarnings("ignore:Duplicate name:UserWarning")
def test_static_gate_rejects_traversal_duplicate_bad_metadata_and_wrong_zip_content(tmp_path, registry_factory, loop_modules):
    registry = registry_factory()
    _, _, render_all, _, run_static_gate = loop_modules
    dist = tmp_path / "dist"
    render_all(registry, registry.root, dist)
    package = dist / "packages" / "alpha.skill"
    with zipfile.ZipFile(package, "w") as archive:
        archive.writestr("alpha/../escape.md", "escape")
        archive.writestr("alpha/SKILL.md", "wrong")
        archive.writestr("alpha/SKILL.md", "duplicate")

    result = run_static_gate(registry, registry.root, dist)
    joined = "\n".join(result.errors)
    assert "ZIP layout" in joined
    assert "ZIP metadata" in joined
    assert "ZIP content" in joined
    assert "package hash mismatch" in joined


def test_static_gate_does_not_self_validate_a_broken_packager(tmp_path, registry_factory, loop_modules, monkeypatch):
    registry = registry_factory()
    _, _, render_all, _, run_static_gate = loop_modules
    import optimizer_loop.static_gate as gate_module

    dist = tmp_path / "dist"
    render_all(registry, registry.root, dist)
    package = dist / "packages" / "alpha.skill"
    package.write_bytes(package.read_bytes() + b"corruption")

    def broken_expected_packager(_skill_dir, output):
        shutil.copyfile(package, output)
        return hashlib.sha256(package.read_bytes()).hexdigest()

    monkeypatch.setattr(gate_module, "package_skill", broken_expected_packager, raising=False)
    result = run_static_gate(registry, registry.root, dist)

    assert any("package hash mismatch" in error for error in result.errors)


def test_publication_cleanup_failure_warns_but_keeps_new_outputs(tmp_path, registry_factory, loop_modules, monkeypatch):
    registry = registry_factory()
    _, _, render_all, _, _ = loop_modules
    import optimizer_loop.render as render_module

    dist = tmp_path / "dist"
    snapshots = registry.root / "skills"
    dist.mkdir()
    snapshots.mkdir()
    (dist / "old.txt").write_text("old\n", encoding="utf-8")
    (snapshots / "old.SKILL.md").write_text("old\n", encoding="utf-8")
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    original_rmtree = shutil.rmtree
    failed = False

    def fail_first_backup(path, *args, **kwargs):
        nonlocal failed
        if ".backup-" in Path(path).name and not failed:
            failed = True
            raise OSError("injected cleanup failure")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(render_module.shutil, "rmtree", fail_first_backup)
    with pytest.warns(RuntimeWarning, match="retained backup"):
        render_all(registry, registry.root, dist)

    assert (dist / "codex" / "alpha" / "SKILL.md").is_file()
    assert (snapshots / "alpha.SKILL.md").is_file()
    assert outside.read_text(encoding="utf-8") == "outside\n"
    assert list(tmp_path.glob(".*.backup-*"))


def test_static_gate_resolves_backtick_same_directory_parent_and_anchor_references(tmp_path, registry_factory, loop_modules):
    registry = registry_factory()
    _, _, render_all, _, run_static_gate = loop_modules
    import optimizer_loop.static_gate as gate_module

    make_static_fixture_valid(registry)
    root = registry.root / "alpha"
    (root / "same.md").write_text("same\n", encoding="utf-8")
    (root / "nested").mkdir()
    (root / "nested" / "nested.md").write_text(
        "`../same.md#part` and [core](../references/persona_core.md#part)\n",
        encoding="utf-8",
    )
    skill = root / "SKILL.md"
    skill.write_text(
        skill.read_text(encoding="utf-8")
        + "\n`references/persona_core.md#anchor` `same.md#anchor` [same](same.md#anchor)"
        + " [web](https://example.com/a.md) [anchor](#local) [other](image.png)\n",
        encoding="utf-8",
    )
    assert "same.md" in gate_module._local_markdown_references(skill, root)
    dist = tmp_path / "dist"
    render_all(registry, registry.root, dist)

    result = run_static_gate(registry, registry.root, dist)

    assert result.passed, result.errors


def test_static_gate_reports_invalid_backtick_and_markdown_relative_references(tmp_path, registry_factory, loop_modules):
    registry = registry_factory()
    _, _, render_all, _, run_static_gate = loop_modules
    make_static_fixture_valid(registry)
    root = registry.root / "alpha"
    (root / "nested").mkdir()
    (root / "nested" / "nested.md").write_text("[missing](../absent.md#x)\n", encoding="utf-8")
    skill = root / "SKILL.md"
    skill.write_text(skill.read_text(encoding="utf-8") + "\n`./missing.md#anchor`\n", encoding="utf-8")
    dist = tmp_path / "dist"
    render_all(registry, registry.root, dist)

    result = run_static_gate(registry, registry.root, dist)

    assert any("./missing.md" in error for error in result.errors)
    assert any("../absent.md" in error for error in result.errors)


def test_static_gate_independently_detects_codex_canonical_file_omission(tmp_path, registry_factory, loop_modules, monkeypatch):
    registry = registry_factory()
    _, _, render_all, _, run_static_gate = loop_modules
    import optimizer_loop.render as render_module

    make_static_fixture_valid(registry)
    dist = tmp_path / "dist"
    render_all(registry, registry.root, dist)
    assert run_static_gate(registry, registry.root, dist).passed
    original_render_tree = render_module._render_tree

    def omit_codex_agent(registry, skill, source_root, destination, runtime):
        result = original_render_tree(registry, skill, source_root, destination, runtime)
        if runtime == "codex" and skill.name == "alpha":
            (destination / "agents" / "openai.yaml").unlink()
        return result

    monkeypatch.setattr(render_module, "_render_tree", omit_codex_agent)
    render_all(registry, registry.root, dist)
    result = run_static_gate(registry, registry.root, dist)

    assert any("Codex contract missing canonical file agents/openai.yaml" in error for error in result.errors)


def test_sync_wrapper_regenerates_only_declared_outputs(real_registry, loop_modules):
    from optimizer_loop.snapshot import snapshot_registry

    before = snapshot_registry(real_registry)
    root = real_registry.root
    wrapper = root / "sync_core.py"

    write = subprocess.run([sys.executable, str(wrapper)], cwd=root, capture_output=True, text=True)
    check = subprocess.run(
        [sys.executable, str(wrapper), "--check"], cwd=root, capture_output=True, text=True
    )

    assert write.returncode == 0, write.stderr
    assert check.returncode == 0, check.stdout + check.stderr
    assert snapshot_registry(real_registry) == before
