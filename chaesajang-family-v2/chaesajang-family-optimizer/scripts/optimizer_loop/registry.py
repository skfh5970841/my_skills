"""Canonical family registry loading and boundary validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping

import yaml


_TOP_LEVEL_KEYS = {"schema_version", "core", "skills", "generated", "adapters"}
_SKILL_KEYS = {"name", "source", "core_files", "inject_gaze"}
_ADAPTER_KEYS = {"exclude"}


@dataclass(frozen=True)
class SkillSpec:
    name: str
    source: Path
    core_files: tuple[str, ...]
    inject_gaze: bool


@dataclass(frozen=True)
class FamilyRegistry:
    root: Path
    core: Path
    skills: tuple[SkillSpec, ...]
    generated: dict[str, Any]
    adapters: Mapping[str, Mapping[str, tuple[str, ...]]] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def canonical_paths(self) -> tuple[Path, ...]:
        return (self.core, *(skill.source for skill in self.skills))


def _contained_directory(root: Path, raw_path: object, label: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path:
        raise ValueError(f"{label} must be a non-empty relative path")
    candidate = Path(raw_path)
    if candidate.is_absolute() or candidate.anchor:
        raise ValueError(f"{label} must not be an absolute path: {raw_path}")
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as error:
        raise ValueError(f"{label} resolves outside the family root: {raw_path}") from error
    if not resolved.is_dir():
        raise ValueError(f"missing canonical directory for {label}: {resolved}")
    return resolved


def _skill_spec(root: Path, raw: object, names: set[str]) -> SkillSpec:
    if not isinstance(raw, dict):
        raise ValueError("each skills entry must be a mapping")
    unknown = set(raw) - _SKILL_KEYS
    if unknown:
        raise ValueError(f"unknown skills keys: {sorted(unknown)}")

    name = raw.get("name")
    if not isinstance(name, str) or not name:
        raise ValueError("skill name must be a non-empty string")
    if name in names:
        raise ValueError(f"duplicate skill name: {name}")
    names.add(name)

    source = _contained_directory(root, raw.get("source"), f"skill {name} source")
    core_files = raw.get("core_files")
    if not isinstance(core_files, list) or not all(isinstance(item, str) for item in core_files):
        raise ValueError(f"skill {name} core_files must be a list of strings")
    inject_gaze = raw.get("inject_gaze")
    if not isinstance(inject_gaze, bool):
        raise ValueError(f"skill {name} inject_gaze must be boolean")
    return SkillSpec(name, source, tuple(core_files), inject_gaze)


def _adapters(raw: object) -> Mapping[str, Mapping[str, tuple[str, ...]]]:
    """Validate runtime adapter configuration and make it immutable."""
    if not isinstance(raw, dict):
        raise ValueError("adapters must be a mapping")
    validated: dict[str, Mapping[str, tuple[str, ...]]] = {}
    for runtime, config in raw.items():
        if not isinstance(runtime, str) or not runtime:
            raise ValueError("adapter runtime names must be non-empty strings")
        if not isinstance(config, dict):
            raise ValueError(f"adapters.{runtime} must be a mapping")
        unknown = set(config) - _ADAPTER_KEYS
        if unknown:
            raise ValueError(f"unknown adapters.{runtime} keys: {sorted(unknown)}")
        excluded = config.get("exclude", [])
        if not isinstance(excluded, list) or not all(
            isinstance(item, str) and item for item in excluded
        ):
            raise ValueError(f"adapters.{runtime}.exclude must be a list of strings")
        normalized: list[str] = []
        for item in excluded:
            path = Path(item)
            if path.is_absolute() or path.anchor or ".." in path.parts:
                raise ValueError(f"adapters.{runtime} exclusion must be a safe relative path: {item}")
            normalized.append(path.as_posix())
        if len(set(normalized)) != len(normalized):
            raise ValueError(f"adapters.{runtime}.exclude contains duplicates")
        validated[runtime] = MappingProxyType({"exclude": tuple(normalized)})
    return MappingProxyType(validated)


def load_registry(root: Path) -> FamilyRegistry:
    """Load the canonical family registry rooted at *root*."""
    family_root = Path(root).resolve()
    config_path = family_root / "family.yaml"
    if not config_path.is_file():
        raise ValueError(f"family.yaml is missing: {config_path}")
    try:
        data = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as error:
        raise ValueError(f"invalid family.yaml: {error}") from error
    if not isinstance(data, dict):
        raise ValueError("family.yaml must contain a mapping")
    unknown = set(data) - _TOP_LEVEL_KEYS
    if unknown:
        raise ValueError(f"unknown top-level keys: {sorted(unknown)}")
    if data.get("schema_version") != 1:
        raise ValueError("unsupported schema_version")

    core = _contained_directory(family_root, data.get("core"), "core")
    raw_skills = data.get("skills")
    if not isinstance(raw_skills, list):
        raise ValueError("skills must be a list")
    names: set[str] = set()
    skills = tuple(_skill_spec(family_root, raw, names) for raw in raw_skills)
    generated = data.get("generated")
    if not isinstance(generated, dict):
        raise ValueError("generated must be a mapping")
    adapters = _adapters(data.get("adapters"))
    return FamilyRegistry(family_root, core, skills, generated, adapters)
