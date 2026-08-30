"""Create and verify isolated copies of registry-declared canonical sources."""

from __future__ import annotations

import difflib
import hashlib
from collections.abc import Iterable, Mapping
from pathlib import Path, PurePosixPath

from .hypothesis import Hypothesis, canonical_relative_path
from .registry import FamilyRegistry
from .snapshot import _compatibility_snapshot_roots, _is_included, snapshot_registry


def _contained(root: Path, path: Path, label: str) -> Path:
    resolved = Path(path).resolve(strict=False)
    try:
        resolved.relative_to(root.resolve())
    except ValueError as error:
        raise ValueError(f"{label} resolves outside its permitted root: {path}") from error
    return resolved


def _declared_relatives(registry: FamilyRegistry) -> tuple[str, ...]:
    root = registry.root.resolve()
    relatives: list[str] = []
    for declared in registry.canonical_paths():
        resolved = _contained(root, Path(declared), "canonical path")
        relatives.append(resolved.relative_to(root).as_posix())
    return tuple(relatives)


def _audit_source_symlinks(registry: FamilyRegistry) -> None:
    root = registry.root.resolve()
    for declared in registry.canonical_paths():
        source = Path(declared)
        resolved = _contained(root, source, "canonical path")
        if source.is_symlink() and resolved != source.resolve():
            # The containment check above is the security boundary; in-root links are skipped
            # by snapshot_registry and therefore never become candidate source files.
            pass
        if source.is_file() or source.is_symlink():
            paths = (source,)
        elif source.is_dir():
            paths = source.rglob("*")
        else:
            raise ValueError(f"missing canonical path: {source}")
        for path in paths:
            if path.is_symlink():
                try:
                    path.resolve().relative_to(root)
                except ValueError as error:
                    raise ValueError(f"canonical symlink resolves outside family root: {path}") from error


def _candidate_root(registry: FamilyRegistry, candidate_root: Path) -> Path:
    candidate = Path(candidate_root)
    if candidate.name != "source" or candidate.parent.name != "candidate":
        raise ValueError("candidate root must end in candidate/source")
    if candidate.is_symlink() or candidate.parent.is_symlink():
        raise ValueError("candidate root must not be a symlink")
    resolved = candidate.resolve(strict=False)
    if not resolved.is_dir():
        raise ValueError(f"candidate root is missing: {candidate}")
    for declared in registry.canonical_paths():
        declared_resolved = Path(declared).resolve()
        try:
            resolved.relative_to(declared_resolved)
        except ValueError:
            continue
        raise ValueError("candidate root must not be inside canonical source")
    return resolved


def _belongs_to_declared_source(relative: str, declared: tuple[str, ...]) -> bool:
    path = PurePosixPath(relative)
    for root in declared:
        source = PurePosixPath(root)
        if path == source or source in path.parents:
            return True
    return False


def _candidate_bytes(registry: FamilyRegistry, candidate_root: Path) -> dict[str, bytes]:
    root = _candidate_root(registry, candidate_root)
    declared = _declared_relatives(registry)
    compatibility_roots = _compatibility_snapshot_roots(registry)
    copied: dict[str, bytes] = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            _contained(root, path, "candidate symlink")
            raise ValueError(f"candidate source must not contain symlinks: {path}")
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if not _belongs_to_declared_source(relative, declared) or not _is_included(
            Path(relative), compatibility_roots
        ):
            raise ValueError(f"candidate contains a non-canonical file: {relative}")
        copied[relative] = path.read_bytes()
    return copied


def _reject_file_to_directory_replacement(
    registry: FamilyRegistry, candidate_root: Path, baseline: Mapping[str, str]
) -> None:
    """Reject a candidate directory that occupies a baseline file's path."""
    root = _candidate_root(registry, candidate_root)
    for path in root.rglob("*"):
        if path.is_symlink() or not path.is_dir():
            continue
        relative = path.relative_to(root).as_posix()
        if relative in baseline:
            raise ValueError(f"candidate file-to-directory replacement: {relative}")


def _baseline_bytes(registry: FamilyRegistry) -> dict[str, bytes]:
    root = registry.root.resolve()
    return {relative: (root / relative).read_bytes() for relative in snapshot_registry(registry)}


def _validate_baseline(registry: FamilyRegistry, baseline: Mapping[str, str]) -> None:
    if not isinstance(baseline, Mapping):
        raise TypeError("baseline must be a mapping of canonical paths to SHA-256 hashes")
    _audit_source_symlinks(registry)
    declared = _declared_relatives(registry)
    for path, digest in baseline.items():
        relative = canonical_relative_path(path, "baseline path")
        if relative != path or not _belongs_to_declared_source(relative, declared):
            raise ValueError(f"baseline path is not canonical: {path}")
        if (
            not isinstance(digest, str)
            or len(digest) != hashlib.sha256().digest_size * 2
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError(f"baseline hash must be a string: {path}")
    expected = snapshot_registry(registry)
    if set(baseline) != set(expected):
        raise ValueError("baseline must exactly match the current canonical snapshot paths")
    if any(baseline[path] != expected[path] for path in expected):
        raise ValueError("baseline hashes must exactly match the current canonical snapshot")


def create_candidate(registry: FamilyRegistry, experiment_dir: Path) -> Path:
    """Copy snapshot-visible canonical bytes to ``experiment/candidate/source``."""
    if not isinstance(registry, FamilyRegistry):
        raise TypeError("registry must be a FamilyRegistry")
    _audit_source_symlinks(registry)
    experiment = Path(experiment_dir)
    candidate = experiment / "candidate" / "source"
    experiment.mkdir(parents=True, exist_ok=True)
    _contained(experiment, candidate, "candidate root")
    if candidate.exists() or candidate.is_symlink():
        raise ValueError(f"candidate root already exists: {candidate}")
    for declared in registry.canonical_paths():
        try:
            candidate.resolve(strict=False).relative_to(Path(declared).resolve())
        except ValueError:
            continue
        raise ValueError("candidate root must not be inside canonical source")
    candidate.mkdir(parents=True)
    root = registry.root.resolve()
    for relative in snapshot_registry(registry):
        source = root / relative
        destination = candidate / PurePosixPath(relative)
        _contained(candidate, destination, "candidate destination")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())
    return candidate


def changed_canonical_files(
    registry: FamilyRegistry, candidate_root: Path, baseline: Mapping[str, str]
) -> tuple[str, ...]:
    """Return sorted canonical paths changed, deleted, or added in a candidate."""
    _validate_baseline(registry, baseline)
    _reject_file_to_directory_replacement(registry, candidate_root, baseline)
    current = _candidate_bytes(registry, candidate_root)
    for path in current:
        if any(str(ancestor) in baseline for ancestor in PurePosixPath(path).parents):
            raise ValueError(f"candidate file-to-directory replacement: {path}")
    changed = {
        path
        for path in set(baseline) | set(current)
        if path not in baseline
        or path not in current
        or hashlib.sha256(current[path]).hexdigest() != baseline[path]
    }
    return tuple(sorted(changed))


def validate_change_scope(hypothesis: Hypothesis, changed: Iterable[str]) -> list[str]:
    """Return scope errors when actual changes exceed a single hypothesis group."""
    if not isinstance(hypothesis, Hypothesis):
        raise TypeError("hypothesis must be a Hypothesis")
    errors: list[str] = []
    for raw_path in changed:
        try:
            relative = canonical_relative_path(raw_path, "changed path")
        except ValueError as error:
            errors.append(str(error))
            continue
        if relative not in hypothesis.allowed_paths:
            errors.append(
                f"changed path is outside change_group {hypothesis.change_group}: {relative}"
            )
    return errors


def _text_lines(value: bytes, path: str) -> list[str]:
    if b"\0" in value:
        raise ValueError(f"binary changes are invalid: {path}")
    try:
        return value.decode("utf-8").splitlines(keepends=True)
    except UnicodeDecodeError as error:
        raise ValueError(f"binary changes are invalid: {path}") from error


def write_candidate_patch(registry: FamilyRegistry, candidate_root: Path, output: Path) -> None:
    """Write a deterministic UTF-8 unified diff of canonical source and candidate."""
    baseline = snapshot_registry(registry)
    changed_canonical_files(registry, candidate_root, baseline)
    original = _baseline_bytes(registry)
    candidate = _candidate_bytes(registry, candidate_root)
    fragments: list[str] = []
    for relative in sorted(set(original) | set(candidate)):
        before = original.get(relative)
        after = candidate.get(relative)
        if before == after:
            continue
        fragments.extend(
            difflib.unified_diff(
                _text_lines(b"" if before is None else before, relative),
                _text_lines(b"" if after is None else after, relative),
                fromfile=f"a/{relative}",
                tofile=f"b/{relative}",
                lineterm="\n",
            )
        )
    destination = Path(output)
    root = registry.root.resolve()
    for declared in registry.canonical_paths():
        try:
            destination.resolve(strict=False).relative_to(Path(declared).resolve())
        except ValueError:
            continue
        raise ValueError("candidate patch output must not overwrite canonical source")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("".join(fragments), encoding="utf-8", newline="")
