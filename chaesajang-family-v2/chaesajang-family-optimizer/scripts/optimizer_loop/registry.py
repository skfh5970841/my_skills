"""Canonical family registry loading and boundary validation."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping

import yaml


_TOP_LEVEL_KEYS = {"schema_version", "core", "skills", "generated", "adapters"}
_SKILL_KEYS = {"name", "source", "core_files", "inject_gaze"}
_ADAPTER_KEYS = {"exclude"}
_GENERATED_KEYS = {"compatibility_snapshots", "dist", "experiments", "package_extension"}
_RUNTIME_ADAPTERS = ("codex", "claude")
_SKILL_NAME_RE = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*\Z")


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
    generated: Mapping[str, Any]
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


def _safe_posix_relative(raw: object, label: str) -> str:
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"{label} must be a non-empty relative POSIX path")
    if "\\" in raw or ":" in raw:
        raise ValueError(f"{label} must use POSIX separators")
    path = PurePosixPath(raw)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} must be a normalized relative POSIX path")
    normalized = path.as_posix()
    if normalized != raw:
        raise ValueError(f"{label} must be normalized")
    return normalized


def _skill_spec(root: Path, core: Path, raw: object, names: set[str]) -> SkillSpec:
    if not isinstance(raw, dict):
        raise ValueError("each skills entry must be a mapping")
    unknown = set(raw) - _SKILL_KEYS
    if unknown:
        raise ValueError(f"unknown skills keys: {sorted(unknown)}")

    name = raw.get("name")
    if (
        not isinstance(name, str)
        or not 1 <= len(name) <= 64
        or _SKILL_NAME_RE.fullmatch(name) is None
    ):
        raise ValueError(
            "skill name must be 1..64 lowercase ASCII letters/digits in single-hyphen-separated segments"
        )
    if name in names:
        raise ValueError(f"duplicate skill name: {name}")
    names.add(name)

    source = _contained_directory(root, raw.get("source"), f"skill {name} source")
    raw_core_files = raw.get("core_files")
    if not isinstance(raw_core_files, list):
        raise ValueError(f"skill {name} core_files must be a list of strings")
    core_files: list[str] = []
    for item in raw_core_files:
        relative = _safe_posix_relative(item, f"skill {name} core_files entry")
        candidate = (core / relative).resolve()
        try:
            candidate.relative_to(core)
        except ValueError as error:
            raise ValueError(f"skill {name} core file resolves outside core: {relative}") from error
        if not candidate.is_file():
            raise ValueError(f"skill {name} declares missing core file: {relative}")
        core_files.append(relative)
    if len(set(core_files)) != len(core_files):
        raise ValueError(f"skill {name} core_files contains duplicates")
    inject_gaze = raw.get("inject_gaze")
    if not isinstance(inject_gaze, bool):
        raise ValueError(f"skill {name} inject_gaze must be boolean")
    return SkillSpec(name, source, tuple(core_files), inject_gaze)


def _adapters(raw: object) -> Mapping[str, Mapping[str, tuple[str, ...]]]:
    """Validate runtime adapter configuration and make it immutable."""
    if not isinstance(raw, dict):
        raise ValueError("adapters must be a mapping")
    if set(raw) != set(_RUNTIME_ADAPTERS):
        raise ValueError("adapters must contain exactly codex and claude")
    validated: dict[str, Mapping[str, tuple[str, ...]]] = {}
    for runtime in _RUNTIME_ADAPTERS:
        config = raw[runtime]
        if not isinstance(config, dict):
            raise ValueError(f"adapters.{runtime} must be a mapping")
        if set(config) != _ADAPTER_KEYS:
            raise ValueError(f"adapters.{runtime} must contain exactly {_ADAPTER_KEYS}")
        excluded = config["exclude"]
        if not isinstance(excluded, list) or not all(
            isinstance(item, str) and item for item in excluded
        ):
            raise ValueError(f"adapters.{runtime}.exclude must be a list of strings")
        normalized: list[str] = []
        for item in excluded:
            normalized.append(_safe_posix_relative(item, f"adapters.{runtime} exclusion"))
        if len(set(normalized)) != len(normalized):
            raise ValueError(f"adapters.{runtime}.exclude contains duplicates")
        if runtime == "codex" and normalized:
            raise ValueError("adapters.codex.exclude must be exactly empty")
        validated[runtime] = MappingProxyType({"exclude": tuple(normalized)})
    return MappingProxyType(validated)


def _paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def _generated(root: Path, raw: object, canonical: tuple[Path, ...]) -> Mapping[str, str]:
    if not isinstance(raw, dict):
        raise ValueError("generated must be a mapping")
    if set(raw) != _GENERATED_KEYS:
        missing = _GENERATED_KEYS - set(raw)
        unknown = set(raw) - _GENERATED_KEYS
        raise ValueError(f"generated must contain exactly {_GENERATED_KEYS}; missing={sorted(missing)}, unknown={sorted(unknown)}")
    directories: dict[str, Path] = {}
    values: dict[str, str] = {}
    for key in ("compatibility_snapshots", "dist", "experiments"):
        relative = _safe_posix_relative(raw[key], f"generated.{key}")
        resolved = (root / relative).resolve()
        try:
            resolved.relative_to(root)
        except ValueError as error:
            raise ValueError(f"generated.{key} resolves outside family root") from error
        if resolved == root:
            raise ValueError(f"generated.{key} must not equal family root")
        directories[key] = resolved
        values[key] = relative
    for name, directory in directories.items():
        for canonical_path in canonical:
            if _paths_overlap(directory, canonical_path.resolve()):
                raise ValueError(f"generated.{name} overlaps a canonical directory")
    directory_values = tuple(directories.items())
    for index, (name, directory) in enumerate(directory_values):
        for other_name, other in directory_values[index + 1 :]:
            if _paths_overlap(directory, other):
                raise ValueError(f"generated.{name} overlaps generated.{other_name}")
    extension = raw["package_extension"]
    if (
        not isinstance(extension, str)
        or not extension.startswith(".")
        or extension.count(".") != 1
        or len(extension) == 1
        or "/" in extension
        or "\\" in extension
        or ":" in extension
        or ".." in extension
    ):
        raise ValueError("generated.package_extension must be one safe dot-prefixed extension")
    values["package_extension"] = extension
    return MappingProxyType(values)


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
    skills = tuple(_skill_spec(family_root, core, raw, names) for raw in raw_skills)
    generated = _generated(family_root, data.get("generated"), (core, *(skill.source for skill in skills)))
    adapters = _adapters(data.get("adapters"))
    return FamilyRegistry(family_root, core, skills, generated, adapters)
