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


def test_registry_rejects_unknown_keys_and_escaped_sources(repo_root, load_registry, tmp_path):
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
        "adapters: {}\n"
        "unexpected: true\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_registry(family)
