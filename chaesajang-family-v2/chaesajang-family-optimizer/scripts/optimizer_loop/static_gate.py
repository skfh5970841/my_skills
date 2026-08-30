"""Collected static validation for canonical sources and generated adapters."""

from __future__ import annotations

import hashlib
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

import yaml

from .registry import FamilyRegistry, SkillSpec
from .render import _generated_path, _path_from_source_root, _render_tree, _tree_hashes, package_skill


_REFERENCE_RE = re.compile(r"(?:\]\(|`)([^`\s)]+/[^`\s)]+\.md)(?:\)|`)")


@dataclass(frozen=True)
class GateResult:
    passed: bool
    errors: tuple[str, ...]
    details: dict


def _frontmatter(path: Path) -> tuple[dict | None, str | None]:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return None, "missing YAML frontmatter"
    closing = text.find("\n---", 4)
    if closing < 0:
        return None, "unterminated YAML frontmatter"
    try:
        data = yaml.safe_load(text[4:closing])
    except yaml.YAMLError as error:
        return None, f"invalid YAML frontmatter: {error}"
    if not isinstance(data, dict):
        return None, "YAML frontmatter must be a mapping"
    return data, None


def _source_skill(registry: FamilyRegistry, source_root: Path, skill: SkillSpec) -> Path:
    return _path_from_source_root(registry, source_root, skill.source)


def _check_source(registry: FamilyRegistry, source_root: Path, skill: SkillSpec, errors: list[str]) -> None:
    source = _source_skill(registry, source_root, skill)
    entrypoint = source / "SKILL.md"
    if not entrypoint.is_file():
        errors.append(f"{skill.name}: missing SKILL.md")
        return
    frontmatter, failure = _frontmatter(entrypoint)
    if failure:
        errors.append(f"{skill.name}: frontmatter: {failure}")
    elif frontmatter.get("name") != skill.name:
        errors.append(f"{skill.name}: name-directory mismatch")
    for markdown in source.rglob("*.md"):
        text = markdown.read_text(encoding="utf-8")
        for reference in _REFERENCE_RE.findall(text):
            targets = ((markdown.parent / reference).resolve(), (source / reference).resolve())
            contained = []
            for target in targets:
                try:
                    target.relative_to(source.resolve())
                except ValueError:
                    continue
                contained.append(target)
            if not contained or not any(target.is_file() for target in contained):
                errors.append(f"{skill.name}: broken relative reference {reference} in {markdown.name}")
    core = _path_from_source_root(registry, source_root, registry.core)
    for filename in skill.core_files:
        expected, actual = core / filename, source / "references" / filename
        if not expected.is_file() or not actual.is_file() or expected.read_bytes() != actual.read_bytes():
            errors.append(f"{skill.name}: core drift for {filename}")
    if skill.inject_gaze:
        text = entrypoint.read_text(encoding="utf-8")
        begins, ends = text.count("<!-- CORE:gaze BEGIN -->"), text.count("<!-- CORE:gaze END -->")
        if begins > 1 or ends > 1:
            errors.append(f"{skill.name}: duplicate CORE:gaze marker")
        elif begins != 1 or ends != 1:
            errors.append(f"{skill.name}: missing CORE:gaze marker")


def _zip_layout_ok(package: Path, skill_name: str) -> bool:
    try:
        with zipfile.ZipFile(package) as archive:
            names = archive.namelist()
    except (OSError, zipfile.BadZipFile):
        return False
    prefix = f"{skill_name}/"
    return bool(names) and names == sorted(names) and all(name.startswith(prefix) and name != prefix for name in names)


def run_static_gate(registry: FamilyRegistry, source_root: Path, dist_root: Path) -> GateResult:
    """Return all detectable static errors; never stop after the first failure."""
    source_root, dist_root = Path(source_root), Path(dist_root)
    errors: list[str] = []
    details: dict[str, object] = {"source_root": str(source_root), "dist_root": str(dist_root), "checked": []}
    for skill in registry.skills:
        _check_source(registry, source_root, skill, errors)
    extension = registry.generated.get("package_extension", ".skill")
    if not isinstance(extension, str):
        errors.append("package extension is invalid")
        extension = ".skill"
    try:
        snapshot_root = _generated_path(registry, source_root, "compatibility_snapshots")
    except ValueError as error:
        errors.append(str(error))
        snapshot_root = source_root / "skills"
    dist_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".static-gate-", dir=dist_root.parent) as temp:
        expected_root = Path(temp)
        for runtime in registry.adapters:
            for skill in registry.skills:
                expected = expected_root / runtime / skill.name
                try:
                    _render_tree(registry, skill, source_root, expected, runtime)
                except (OSError, ValueError) as error:
                    errors.append(f"{runtime}/{skill.name}: cannot render expected adapter: {error}")
                    if runtime == "codex":
                        snapshot = snapshot_root / f"{skill.name}.SKILL.md"
                        entrypoint = _source_skill(registry, source_root, skill) / "SKILL.md"
                        if not snapshot.is_file() or not entrypoint.is_file() or snapshot.read_bytes() != entrypoint.read_bytes():
                            errors.append(f"{skill.name}: compatibility snapshot drift")
                    continue
                actual = dist_root / runtime / skill.name
                if not actual.is_dir() or _tree_hashes(expected) != _tree_hashes(actual):
                    errors.append(f"{runtime}/{skill.name}: adapter drift")
                if runtime == "codex":
                    snapshot = snapshot_root / f"{skill.name}.SKILL.md"
                    if not snapshot.is_file() or snapshot.read_bytes() != (expected / "SKILL.md").read_bytes():
                        errors.append(f"{skill.name}: compatibility snapshot drift")
                    package = dist_root / "packages" / f"{skill.name}{extension}"
                    if not _zip_layout_ok(package, skill.name):
                        errors.append(f"{skill.name}: ZIP layout is invalid")
                    expected_package = expected_root / "packages" / f"{skill.name}{extension}"
                    expected_package.parent.mkdir(parents=True, exist_ok=True)
                    expected_hash = package_skill(expected, expected_package)
                    actual_hash = hashlib.sha256(package.read_bytes()).hexdigest() if package.is_file() else None
                    if actual_hash != expected_hash:
                        errors.append(f"{skill.name}: package hash mismatch")
                details["checked"].append(f"{runtime}/{skill.name}")
    return GateResult(not errors, tuple(errors), details)
