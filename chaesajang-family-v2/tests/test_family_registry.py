import sys
from pathlib import Path

import pytest


@pytest.fixture
def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


@pytest.fixture
def load_registry(repo_root):
    scripts = repo_root / "chaesajang-family-v2" / "chaesajang-family-optimizer" / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        from optimizer_loop.registry import load_registry as loader

        return loader
    finally:
        sys.path.remove(str(scripts))


def test_registry_declares_exactly_five_managed_skills(repo_root, load_registry):
    registry = load_registry(repo_root / "chaesajang-family-v2")
    assert {skill.name for skill in registry.skills} == {
        "chaesajang-advisor",
        "chaesajang-style",
        "chaesajang-dialogue",
        "chaesajang-style-youtube-scripter",
        "chaesajang-write-teacher",
    }


def test_registry_exposes_validated_read_only_adapter_mapping(repo_root, load_registry):
    registry = load_registry(repo_root / "chaesajang-family-v2")

    assert registry.adapters["claude"]["exclude"] == ("agents",)
    with pytest.raises(TypeError):
        registry.adapters["claude"] = {"exclude": ()}
    with pytest.raises(TypeError):
        registry.generated["dist"] = "other-dist"


def test_registry_rejects_invalid_adapter_configuration(repo_root, load_registry, tmp_path):
    family = tmp_path / "family"
    family.mkdir()
    (family / "chaesajang-core").mkdir()
    (family / "family.yaml").write_text(
        "schema_version: 1\ncore: chaesajang-core\nskills: []\n"
        "generated: {compatibility_snapshots: skills, dist: dist, experiments: experiments, package_extension: .skill}\n"
        "adapters:\n  claude:\n    exclude: not-a-list\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="adapters"):
        load_registry(family)


@pytest.mark.parametrize(
    "generated, core_files, codex_exclude",
    [
        ("{compatibility_snapshots: ../outside, dist: dist, experiments: experiments, package_extension: .skill}", "[]", "[]"),
        ("{compatibility_snapshots: skills, dist: chaesajang-core/out, experiments: experiments, package_extension: .skill}", "[]", "[]"),
        ("{compatibility_snapshots: skills, dist: dist, experiments: dist/cache, package_extension: .skill}", "[]", "[]"),
        ("{compatibility_snapshots: skills, dist: dist, experiments: experiments, package_extension: ../bad.skill}", "[]", "[]"),
        ("{compatibility_snapshots: skills, dist: dist, experiments: experiments, package_extension: .skill}", "[../escape.md]", "[]"),
        ("{compatibility_snapshots: skills, dist: dist, experiments: experiments, package_extension: .skill}", "[persona_core.md, persona_core.md]", "[]"),
        ("{compatibility_snapshots: skills, dist: dist, experiments: experiments, package_extension: .skill}", "[]", "[agents]"),
    ],
)
def test_registry_rejects_unsafe_generated_core_and_codex_adapter_values(
    load_registry, tmp_path, generated, core_files, codex_exclude
):
    family = tmp_path / "family"
    (family / "chaesajang-core").mkdir(parents=True)
    (family / "chaesajang-core" / "persona_core.md").write_text("core\n", encoding="utf-8")
    (family / "alpha").mkdir()
    (family / "family.yaml").write_text(
        "schema_version: 1\ncore: chaesajang-core\n"
        "skills:\n  - name: alpha\n    source: alpha\n"
        f"    core_files: {core_files}\n    inject_gaze: false\n"
        f"generated: {generated}\n"
        f"adapters:\n  codex:\n    exclude: {codex_exclude}\n  claude:\n    exclude: []\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_registry(family)


def test_optimizer_is_neutral_and_requires_approval(repo_root):
    text = (
        repo_root
        / "chaesajang-family-v2"
        / "chaesajang-family-optimizer"
        / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "중립적인 연구자" in text
    assert "사용자 승인" in text
    assert "채사장 역할극" in text


def test_registry_rejects_duplicate_names(repo_root, load_registry, tmp_path):
    family = tmp_path / "family"
    family.mkdir()
    (family / "chaesajang-core").mkdir()
    (family / "chaesajang-style").mkdir()
    (family / "chaesajang-advisor").mkdir()
    (family / "chaesajang-dialogue").mkdir()
    (family / "chaesajang-style-youtube-scripter").mkdir()
    (family / "chaesajang-write-teacher").mkdir()
    (family / "family.yaml").write_text(
        "schema_version: 1\n"
        "core: chaesajang-core\n"
        "skills:\n"
        "  - name: chaesajang-style\n"
        "    source: chaesajang-advisor\n"
        "    core_files: []\n"
        "    inject_gaze: false\n"
        "  - name: chaesajang-style\n"
        "    source: chaesajang-style\n"
        "    core_files: []\n"
        "    inject_gaze: false\n"
        "generated: {}\n"
        "adapters: {}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_registry(family)


def test_registry_rejects_absolute_sources(repo_root, load_registry, tmp_path):
    family = tmp_path / "family"
    family.mkdir()
    (family / "chaesajang-core").mkdir()
    (family / "family.yaml").write_text(
        "schema_version: 1\n"
        "core: chaesajang-core\n"
        "skills:\n"
        "  - name: absolute\n"
        "    source: /outside-family\n"
        "    core_files: []\n"
        "    inject_gaze: false\n"
        "generated: {}\n"
        "adapters: {}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_registry(family)


def test_registry_rejects_unknown_top_level_keys(repo_root, load_registry, tmp_path):
    family = tmp_path / "family"
    family.mkdir()
    (family / "chaesajang-core").mkdir()
    (family / "family.yaml").write_text(
        "schema_version: 1\n"
        "core: chaesajang-core\n"
        "skills:\n"
        "  - name: known\n"
        "    source: chaesajang-core\n"
        "    core_files: []\n"
        "    inject_gaze: false\n"
        "generated: {}\n"
        "adapters: {}\n"
        "unexpected: true\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_registry(family)


def test_registry_rejects_escaped_sources(repo_root, load_registry, tmp_path):
    family = tmp_path / "family"
    family.mkdir()
    (family / "chaesajang-core").mkdir()
    (family / "family.yaml").write_text(
        "schema_version: 1\n"
        "core: chaesajang-core\n"
        "skills:\n"
        "  - name: escaped\n"
        "    source: ../outside\n"
        "    core_files: []\n"
        "    inject_gaze: false\n"
        "generated: {}\n"
        "adapters: {}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_registry(family)


def test_registry_rejects_missing_canonical_directories(repo_root, load_registry, tmp_path):
    family = tmp_path / "family"
    family.mkdir()
    (family / "chaesajang-core").mkdir()
    (family / "family.yaml").write_text(
        "schema_version: 1\n"
        "core: chaesajang-core\n"
        "skills:\n"
        "  - name: missing\n"
        "    source: missing-skill\n"
        "    core_files: []\n"
        "    inject_gaze: false\n"
        "generated: {}\n"
        "adapters: {}\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_registry(family)
