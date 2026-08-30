"""Deterministic runtime adapters and atomically published skill packages."""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import uuid
import zipfile
from pathlib import Path

from .registry import FamilyRegistry, SkillSpec


_GAZE_BEGIN = "<!-- CORE:gaze BEGIN -->"
_GAZE_END = "<!-- CORE:gaze END -->"
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_ZIP_MODE = 0o100644 << 16


def _path_from_source_root(registry: FamilyRegistry, source_root: Path, canonical: Path) -> Path:
    try:
        relative = canonical.resolve().relative_to(registry.root.resolve())
    except ValueError as error:
        raise ValueError(f"registry path is outside family root: {canonical}") from error
    return Path(source_root).resolve() / relative


def _gaze_block(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    begins, ends = text.count(_GAZE_BEGIN), text.count(_GAZE_END)
    if begins != 1 or ends != 1:
        state = "missing" if begins == 0 or ends == 0 else "duplicate"
        raise ValueError(f"{state} CORE:gaze marker block in {path}")
    start = text.index(_GAZE_BEGIN)
    end = text.index(_GAZE_END, start) + len(_GAZE_END)
    return text[start:end]


def _replace_gaze(text: str, block: str, path: Path) -> str:
    begins, ends = text.count(_GAZE_BEGIN), text.count(_GAZE_END)
    if begins != 1 or ends != 1:
        state = "missing" if begins == 0 or ends == 0 else "duplicate"
        raise ValueError(f"{state} CORE:gaze marker block in {path}")
    start = text.index(_GAZE_BEGIN)
    end = text.index(_GAZE_END, start) + len(_GAZE_END)
    return text[:start] + block + text[end:]


def _tree_hashes(root: Path) -> dict[str, str]:
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file()
    }


def _validate_publish_destination(registry: FamilyRegistry, source_root: Path, destination: Path) -> None:
    """Refuse a publication target that could replace family or canonical source."""
    destination = destination.resolve()
    root = Path(source_root).resolve()
    if destination == root or destination.parent == destination:
        raise ValueError(f"unsafe publication destination: {destination}")
    canonical = [_path_from_source_root(registry, root, registry.core)]
    canonical.extend(_path_from_source_root(registry, root, skill.source) for skill in registry.skills)
    for source in canonical:
        source = source.resolve()
        if destination == source or destination in source.parents or source in destination.parents:
            raise ValueError(f"publication destination overlaps canonical source: {destination}")


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
    if runtime == "claude":
        for excluded in registry.adapters["claude"]["exclude"]:
            target = destination / excluded
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
    return _tree_hashes(destination)


def _publish_directories(replacements: list[tuple[Path, Path]]) -> None:
    """Publish sibling staging directories, restoring every destination on failure."""
    backups: list[tuple[Path, Path]] = []
    published: list[tuple[Path, Path]] = []
    try:
        for staged, destination in replacements:
            destination.parent.mkdir(parents=True, exist_ok=True)
            backup = destination.with_name(f".{destination.name}.backup-{uuid.uuid4().hex}")
            if destination.exists():
                os.replace(destination, backup)
                backups.append((destination, backup))
            os.replace(staged, destination)
            published.append((staged, destination))
    except Exception:
        for staged, destination in reversed(published):
            if destination.exists():
                os.replace(destination, staged)
        for destination, backup in reversed(backups):
            if backup.exists():
                os.replace(backup, destination)
        raise
    for _, backup in backups:
        if backup.exists():
            shutil.rmtree(backup)


def render_skill(
    registry: FamilyRegistry,
    skill: SkillSpec,
    source_root: Path,
    destination: Path,
    runtime: str,
) -> dict[str, str]:
    """Render one registry skill for *runtime* without partial publication."""
    destination = Path(destination)
    _validate_publish_destination(registry, Path(source_root), destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{skill.name}-", dir=destination.parent) as temp:
        staged = Path(temp) / skill.name
        hashes = _render_tree(registry, skill, Path(source_root), staged, runtime)
        _publish_directories([(staged, destination)])
    return hashes


def _zip_entries(skill_dir: Path) -> list[tuple[str, bytes]]:
    return [
        (f"{skill_dir.name}/{path.relative_to(skill_dir).as_posix()}", path.read_bytes())
        for path in sorted(skill_dir.rglob("*"), key=lambda item: item.as_posix())
        if path.is_file()
    ]


def _write_package(skill_dir: Path, output: Path) -> None:
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, payload in _zip_entries(skill_dir):
            info = zipfile.ZipInfo(name, _ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = _ZIP_MODE
            archive.writestr(info, payload, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def package_skill(skill_dir: Path, output: Path) -> str:
    """Create a byte-stable .skill ZIP with one exact top-level directory."""
    skill_dir, output = Path(skill_dir), Path(output)
    if not skill_dir.is_dir():
        raise ValueError(f"skill directory is missing: {skill_dir}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix=f".{output.name}-", dir=output.parent, delete=False) as temp:
        staged = Path(temp.name)
    try:
        _write_package(skill_dir, staged)
        os.replace(staged, output)
    finally:
        if staged.exists():
            staged.unlink()
    return hashlib.sha256(output.read_bytes()).hexdigest()


def _generated_path(registry: FamilyRegistry, source_root: Path, key: str) -> Path:
    configured = registry.generated[key]
    return Path(source_root).resolve() / configured


def render_all(registry: FamilyRegistry, source_root: Path, dist_root: Path) -> dict[str, dict[str, str]]:
    """Render all adapters/packages/snapshots to staging, then publish as one transaction."""
    source_root, dist_root = Path(source_root), Path(dist_root)
    snapshot_root = _generated_path(registry, source_root, "compatibility_snapshots")
    extension = registry.generated["package_extension"]
    _validate_publish_destination(registry, source_root, dist_root)
    _validate_publish_destination(registry, source_root, snapshot_root)
    results: dict[str, dict[str, str]] = {runtime: {} for runtime in registry.adapters}
    results["packages"] = {}
    dist_root.parent.mkdir(parents=True, exist_ok=True)
    snapshot_root.parent.mkdir(parents=True, exist_ok=True)
    with (
        tempfile.TemporaryDirectory(prefix=".render-", dir=dist_root.parent) as dist_temp,
        tempfile.TemporaryDirectory(prefix=".render-", dir=snapshot_root.parent) as snapshots_temp,
    ):
        staged_dist = Path(dist_temp) / "dist"
        staged_snapshots = Path(snapshots_temp) / "snapshots"
        for runtime in registry.adapters:
            for skill in registry.skills:
                rendered = staged_dist / runtime / skill.name
                hashes = _render_tree(registry, skill, source_root, rendered, runtime)
                results[runtime].update({f"{skill.name}/{path}": digest for path, digest in hashes.items()})
        for skill in registry.skills:
            entrypoint = staged_dist / "codex" / skill.name / "SKILL.md"
            snapshot = staged_snapshots / f"{skill.name}.SKILL.md"
            snapshot.parent.mkdir(parents=True, exist_ok=True)
            snapshot.write_bytes(entrypoint.read_bytes())
            package = staged_dist / "packages" / f"{skill.name}{extension}"
            results["packages"][package.name] = package_skill(staged_dist / "codex" / skill.name, package)
        _publish_directories([(staged_dist, dist_root), (staged_snapshots, snapshot_root)])
    return results
