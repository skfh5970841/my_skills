"""Deterministic runtime adapters and portable skill packages."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import zipfile
from pathlib import Path

from .registry import FamilyRegistry, SkillSpec


_GAZE_BEGIN = "<!-- CORE:gaze BEGIN -->"
_GAZE_END = "<!-- CORE:gaze END -->"
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)


def _path_from_source_root(registry: FamilyRegistry, source_root: Path, canonical: Path) -> Path:
    try:
        relative = canonical.resolve().relative_to(registry.root.resolve())
    except ValueError as error:
        raise ValueError(f"registry path is outside family root: {canonical}") from error
    return Path(source_root).resolve() / relative


def _gaze_block(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    begins = text.count(_GAZE_BEGIN)
    ends = text.count(_GAZE_END)
    if begins != 1 or ends != 1:
        state = "missing" if begins == 0 or ends == 0 else "duplicate"
        raise ValueError(f"{state} CORE:gaze marker block in {path}")
    start = text.index(_GAZE_BEGIN)
    end = text.index(_GAZE_END, start) + len(_GAZE_END)
    return text[start:end]


def _replace_gaze(text: str, block: str, path: Path) -> str:
    begins = text.count(_GAZE_BEGIN)
    ends = text.count(_GAZE_END)
    if begins != 1 or ends != 1:
        state = "missing" if begins == 0 or ends == 0 else "duplicate"
        raise ValueError(f"{state} CORE:gaze marker block in {path}")
    start = text.index(_GAZE_BEGIN)
    end = text.index(_GAZE_END, start) + len(_GAZE_END)
    return text[:start] + block + text[end:]


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file()
    }


def _render_tree(
    registry: FamilyRegistry,
    skill: SkillSpec,
    source_root: Path,
    destination: Path,
    runtime: str,
) -> dict[str, str]:
    if runtime not in registry.adapters:
        raise ValueError(f"unknown runtime adapter: {runtime}")
    source = _path_from_source_root(registry, source_root, skill.source)
    if not source.is_dir():
        raise ValueError(f"missing canonical skill source: {source}")
    shutil.copytree(source, destination)
    core = _path_from_source_root(registry, source_root, registry.core)
    for filename in skill.core_files:
        source_file = core / filename
        if not source_file.is_file():
            raise ValueError(f"missing declared core file: {source_file}")
        target = destination / "references" / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source_file.read_bytes())
    if skill.inject_gaze:
        block = _gaze_block(core / "gaze_core.md")
        entrypoint = destination / "SKILL.md"
        entrypoint.write_text(
            _replace_gaze(entrypoint.read_text(encoding="utf-8"), block, entrypoint),
            encoding="utf-8",
        )
    for excluded in registry.adapters[runtime]["exclude"]:
        target = destination / excluded
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
    return _tree_hashes(destination)


def _replace_directory(staged: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        shutil.rmtree(destination)
    os.replace(staged, destination)


def render_skill(
    registry: FamilyRegistry,
    skill: SkillSpec,
    source_root: Path,
    destination: Path,
    runtime: str,
) -> dict[str, str]:
    """Render one registry skill for *runtime* without leaving partial output."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{skill.name}-", dir=destination.parent) as temp:
        staged = Path(temp) / skill.name
        hashes = _render_tree(registry, skill, Path(source_root), staged, runtime)
        _replace_directory(staged, destination)
    return hashes


def package_skill(skill_dir: Path, output: Path) -> str:
    """Create a byte-stable .skill ZIP with exactly one top-level directory."""
    skill_dir, output = Path(skill_dir), Path(output)
    if not skill_dir.is_dir():
        raise ValueError(f"skill directory is missing: {skill_dir}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=f".{output.name}-", dir=output.parent, delete=False) as temp:
        staged = Path(temp.name)
    try:
        with zipfile.ZipFile(staged, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for file_path in sorted(skill_dir.rglob("*"), key=lambda item: item.as_posix()):
                if not file_path.is_file():
                    continue
                relative = file_path.relative_to(skill_dir).as_posix()
                info = zipfile.ZipInfo(f"{skill_dir.name}/{relative}", _ZIP_TIMESTAMP)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                archive.writestr(info, file_path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        os.replace(staged, output)
    finally:
        if staged.exists():
            staged.unlink()
    return hashlib.sha256(output.read_bytes()).hexdigest()


def _generated_path(registry: FamilyRegistry, source_root: Path, key: str) -> Path:
    configured = registry.generated.get(key)
    if not isinstance(configured, str) or not configured:
        raise ValueError(f"generated.{key} must be a non-empty relative path")
    candidate = Path(configured)
    if candidate.is_absolute() or candidate.anchor or ".." in candidate.parts:
        raise ValueError(f"generated.{key} must be a safe relative path")
    return Path(source_root).resolve() / candidate


def render_all(registry: FamilyRegistry, source_root: Path, dist_root: Path) -> dict[str, dict[str, str]]:
    """Render every runtime adapter, compatibility entrypoint, and .skill package."""
    source_root, dist_root = Path(source_root), Path(dist_root)
    extension = registry.generated.get("package_extension", ".skill")
    if not isinstance(extension, str) or not extension.startswith("."):
        raise ValueError("generated.package_extension must be a file extension")
    snapshot_root = _generated_path(registry, source_root, "compatibility_snapshots")
    results: dict[str, dict[str, str]] = {runtime: {} for runtime in registry.adapters}
    results["packages"] = {}
    dist_root.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".render-", dir=dist_root.parent) as temp:
        staged_root = Path(temp) / "dist"
        staged_snapshots = Path(temp) / "snapshots"
        for runtime in registry.adapters:
            for skill in registry.skills:
                rendered = staged_root / runtime / skill.name
                hashes = _render_tree(registry, skill, source_root, rendered, runtime)
                results[runtime].update({f"{skill.name}/{path}": digest for path, digest in hashes.items()})
        for skill in registry.skills:
            entrypoint = staged_root / "codex" / skill.name / "SKILL.md"
            target = staged_snapshots / f"{skill.name}.SKILL.md"
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(entrypoint.read_bytes())
            package = staged_root / "packages" / f"{skill.name}{extension}"
            results["packages"][package.name] = package_skill(staged_root / "codex" / skill.name, package)
        _replace_directory(staged_root, dist_root)
        snapshot_root.mkdir(parents=True, exist_ok=True)
        for snapshot in staged_snapshots.iterdir():
            os.replace(snapshot, snapshot_root / snapshot.name)
    return results
