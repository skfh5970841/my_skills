import hashlib
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


def test_claude_adapter_excludes_agents_directory(tmp_path, real_registry, loop_modules):
    _, _, render_all, _, _ = loop_modules
    render_all(real_registry, real_registry.root, tmp_path / "dist")
    assert (tmp_path / "dist" / "codex" / "chaesajang-write-teacher" / "agents").is_dir()
    assert not (tmp_path / "dist" / "claude" / "chaesajang-write-teacher" / "agents").exists()


def test_renderer_overwrites_core_and_injects_exact_gaze_block(tmp_path, registry_factory, loop_modules):
    registry = registry_factory()
    _, _, _, render_skill, _ = loop_modules
    alpha = next(skill for skill in registry.skills if skill.name == "alpha")
    hashes = render_skill(registry, alpha, registry.root, tmp_path / "alpha", "codex")

    assert (tmp_path / "alpha" / "references" / "persona_core.md").read_text(encoding="utf-8") == "canonical persona\n"
    assert (tmp_path / "alpha" / "SKILL.md").read_text(encoding="utf-8").count("canonical gaze") == 1
    assert hashes["SKILL.md"] == hashlib.sha256((tmp_path / "alpha" / "SKILL.md").read_bytes()).hexdigest()


@pytest.mark.parametrize("body", ["# alpha\n", "<!-- CORE:gaze BEGIN -->\na\n<!-- CORE:gaze END -->\n<!-- CORE:gaze BEGIN -->\nb\n<!-- CORE:gaze END -->\n"])
def test_renderer_rejects_missing_or_duplicate_gaze_markers(tmp_path, registry_factory, loop_modules, body):
    registry = registry_factory()
    _, _, _, render_skill, _ = loop_modules
    alpha = next(skill for skill in registry.skills if skill.name == "alpha")
    (registry.root / "alpha" / "SKILL.md").write_text(
        "---\nname: alpha\ndescription: test\n---\n" + body, encoding="utf-8"
    )
    with pytest.raises(ValueError, match="CORE:gaze"):
        render_skill(registry, alpha, registry.root, tmp_path / "alpha", "codex")


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
        "---\nname: wrong-name\ndescription: test\n---\nRead `references/missing.md`.\n", encoding="utf-8"
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
