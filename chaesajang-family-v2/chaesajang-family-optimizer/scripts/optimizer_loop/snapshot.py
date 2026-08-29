"""Stable content hashes for registry-declared canonical source files."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

from .registry import FamilyRegistry


_EXCLUDED_PARTS = frozenset(
    {
        ".cache",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".skill",
        "__pycache__",
        "cache",
        "dist",
        "experiments",
        "skills",
    }
)


def _compatibility_snapshot_roots(registry: FamilyRegistry) -> tuple[Path, ...]:
    configured = registry.generated.get("compatibility_snapshots")
    values = (configured,) if isinstance(configured, str) else configured
    if not isinstance(values, (tuple, list)):
        return ()
    roots: list[Path] = []
    for value in values:
        if not isinstance(value, str):
            continue
        candidate = Path(value)
        if candidate.is_absolute() or ".." in candidate.parts:
            continue
        roots.append(candidate)
    return tuple(roots)


def _is_included(path: Path, compatibility_roots: tuple[Path, ...]) -> bool:
    if any(part in _EXCLUDED_PARTS for part in path.parts):
        return False
    if path.name.casefold().endswith(".cache"):
        return False
    return not any(path == root or root in path.parents for root in compatibility_roots)


def _canonical_files(registry: FamilyRegistry) -> list[Path]:
    root = registry.root.resolve()
    compatibility_roots = _compatibility_snapshot_roots(registry)
    files: list[Path] = []
    for declared in registry.canonical_paths():
        source = Path(declared)
        try:
            source.resolve().relative_to(root)
        except ValueError as error:
            raise ValueError(f"canonical path resolves outside family root: {source}") from error
        if source.is_symlink():
            continue
        if source.is_file():
            candidates = (source,)
        elif source.is_dir():
            candidates = source.rglob("*")
        else:
            raise ValueError(f"missing canonical path: {source}")
        for candidate in candidates:
            if candidate.is_symlink() or not candidate.is_file():
                continue
            relative = candidate.relative_to(root)
            if _is_included(relative, compatibility_roots):
                files.append(candidate)
    return files


def snapshot_registry(registry: FamilyRegistry) -> dict[str, str]:
    """Return SHA-256 hashes of only the registry-declared canonical files."""
    if not isinstance(registry, FamilyRegistry):
        raise TypeError("registry must be a FamilyRegistry")
    root = registry.root.resolve()
    snapshot: dict[str, str] = {}
    for path in _canonical_files(registry):
        relative = path.relative_to(root).as_posix()
        snapshot[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return dict(sorted(snapshot.items()))


def combined_snapshot_hash(snapshot: Mapping[str, str]) -> str:
    """Hash a snapshot's path/hash pairs in stable POSIX-path order."""
    digest = hashlib.sha256()
    for path, file_hash in sorted(snapshot.items()):
        if not isinstance(path, str) or not isinstance(file_hash, str):
            raise TypeError("snapshot paths and hashes must be strings")
        digest.update(path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()
