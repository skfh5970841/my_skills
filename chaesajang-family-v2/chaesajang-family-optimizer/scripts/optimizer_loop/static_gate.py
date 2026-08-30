"""Collected static validation for canonical sources and generated adapters."""

from __future__ import annotations

import hashlib
import io
import os
import re
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml

from .registry import FamilyRegistry, SkillSpec
from .render import _gaze_block, _path_from_source_root, _render_tree, _tree_hashes


_MARKDOWN_REFERENCE_RE = re.compile(r"\]\(([^\s)]+)\)")
_BACKTICK_REFERENCE_RE = re.compile(r"`([^`\s]+)`")
_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_ZIP_MODE = 0o100644 << 16


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


def _single_marker_block(text: str) -> str | None:
    begin, end = "<!-- CORE:gaze BEGIN -->", "<!-- CORE:gaze END -->"
    if text.count(begin) != 1 or text.count(end) != 1:
        return None
    start = text.index(begin)
    return text[start : text.index(end, start) + len(end)]


def _local_markdown_references(markdown: Path, source: Path) -> tuple[str, ...]:
    """Find local .md links/backticks and keep their document-relative spelling."""
    text = markdown.read_text(encoding="utf-8")
    local: list[str] = []

    def normalized(candidate: str) -> str | None:
        path = candidate.split("#", 1)[0]
        if not path or path.startswith(("http://", "https://")) or not path.endswith(".md"):
            return None
        return path

    for candidate in _MARKDOWN_REFERENCE_RE.findall(text):
        if path := normalized(candidate):
            local.append(path)
    for candidate in _BACKTICK_REFERENCE_RE.findall(text):
        if not (path := normalized(candidate)):
            continue
        target = markdown.parent / path
        # Bare code spans are often filename terminology rather than link syntax.
        # Treat unambiguous paths and existing same-directory files as references.
        if path.startswith(("./", "../")) or "/" in path or target.is_file():
            local.append(path)
    return tuple(local)


def _replace_gaze_contract(text: str, block: str) -> str:
    begin, end = "<!-- CORE:gaze BEGIN -->", "<!-- CORE:gaze END -->"
    if text.count(begin) != 1 or text.count(end) != 1:
        raise ValueError("SKILL.md does not contain one CORE:gaze marker block")
    start = text.index(begin)
    finish = text.index(end, start) + len(end)
    return text[:start] + block + text[finish:]


def _codex_contract(registry: FamilyRegistry, source_root: Path, skill: SkillSpec) -> dict[str, bytes]:
    """Build Codex bytes directly from canonical sources, never via renderer code."""
    source = _source_skill(registry, source_root, skill)
    if not source.is_dir():
        raise ValueError("canonical skill source is missing")
    contract = {
        path.relative_to(source).as_posix(): path.read_bytes()
        for path in source.rglob("*")
        if path.is_file()
    }
    core = _path_from_source_root(registry, source_root, registry.core)
    for filename in skill.core_files:
        source_file = core / filename
        if not source_file.is_file():
            raise ValueError(f"declared core file is missing: {filename}")
        contract[f"references/{filename}"] = source_file.read_bytes()
    if skill.inject_gaze:
        entrypoint = contract.get("SKILL.md")
        if entrypoint is None:
            raise ValueError("SKILL.md is missing")
        entrypoint_text = entrypoint.decode("utf-8").replace("\r\n", "\n")
        rendered = _replace_gaze_contract(entrypoint_text, _gaze_block(core / "gaze_core.md"))
        contract["SKILL.md"] = rendered.replace("\n", os.linesep).encode("utf-8")
    return contract


def _check_codex_contract(
    registry: FamilyRegistry, source_root: Path, skill: SkillSpec, actual: Path, errors: list[str]
) -> None:
    try:
        expected = _codex_contract(registry, source_root, skill)
    except (OSError, UnicodeDecodeError, ValueError) as error:
        errors.append(f"{skill.name}: Codex contract cannot build: {error}")
        return
    actual_files = {
        path.relative_to(actual).as_posix(): path.read_bytes()
        for path in actual.rglob("*")
        if path.is_file()
    } if actual.is_dir() else {}
    for relative in sorted(set(expected) - set(actual_files)):
        errors.append(f"{skill.name}: Codex contract missing canonical file {relative}")
    for relative in sorted(set(actual_files) - set(expected)):
        errors.append(f"{skill.name}: Codex contract has unexpected file {relative}")
    for relative in sorted(set(expected) & set(actual_files)):
        if expected[relative] != actual_files[relative]:
            errors.append(f"{skill.name}: Codex contract content drift {relative}")


def _check_source(registry: FamilyRegistry, source_root: Path, skill: SkillSpec, errors: list[str]) -> None:
    source = _source_skill(registry, source_root, skill)
    entrypoint = source / "SKILL.md"
    entrypoint_text: str | None = None
    if not entrypoint.is_file():
        errors.append(f"{skill.name}: missing SKILL.md")
    else:
        entrypoint_text = entrypoint.read_text(encoding="utf-8")
        frontmatter, failure = _frontmatter(entrypoint)
        if failure:
            errors.append(f"{skill.name}: frontmatter: {failure}")
        elif frontmatter.get("name") != skill.name:
            errors.append(f"{skill.name}: name-directory mismatch")
    for markdown in source.rglob("*.md") if source.is_dir() else ():
        if markdown.relative_to(source).parts[:1] == ("references",):
            continue
        for reference in _local_markdown_references(markdown, source):
            target = (markdown.parent / reference).resolve()
            try:
                target.relative_to(source.resolve())
            except ValueError:
                errors.append(f"{skill.name}: broken relative reference {reference} in {markdown.name}")
                continue
            if not target.is_file():
                errors.append(f"{skill.name}: broken relative reference {reference} in {markdown.name}")
    core = _path_from_source_root(registry, source_root, registry.core)
    for filename in skill.core_files:
        expected, actual = core / filename, source / "references" / filename
        if not expected.is_file() or not actual.is_file() or expected.read_bytes() != actual.read_bytes():
            errors.append(f"{skill.name}: core drift for {filename}")
    if skill.inject_gaze:
        text = entrypoint_text or ""
        begins, ends = text.count("<!-- CORE:gaze BEGIN -->"), text.count("<!-- CORE:gaze END -->")
        if begins > 1 or ends > 1:
            errors.append(f"{skill.name}: duplicate CORE:gaze marker")
        elif begins != 1 or ends != 1:
            errors.append(f"{skill.name}: missing CORE:gaze marker")
        try:
            expected_block = _gaze_block(core / "gaze_core.md")
        except (OSError, ValueError) as error:
            errors.append(f"{skill.name}: canonical gaze block is invalid: {error}")
        else:
            actual_block = _single_marker_block(text)
            if actual_block is not None and actual_block != expected_block:
                errors.append(f"{skill.name}: gaze content drift")


def _expected_zip_bytes(skill_dir: Path) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file_path in sorted(skill_dir.rglob("*"), key=lambda item: item.as_posix()):
            if not file_path.is_file():
                continue
            name = f"{skill_dir.name}/{file_path.relative_to(skill_dir).as_posix()}"
            info = zipfile.ZipInfo(name, _ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = _ZIP_MODE
            archive.writestr(info, file_path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
    return buffer.getvalue()


def _validate_package(package: Path, skill: SkillSpec, expected: Path | None, errors: list[str]) -> None:
    try:
        with zipfile.ZipFile(package) as archive:
            entries = archive.infolist()
            names = [entry.filename for entry in entries]
            expected_files = _tree_hashes(expected) if expected is not None else None
            actual_files: dict[str, bytes] = {}
            layout_valid = bool(entries)
            metadata_valid = True
            for entry in entries:
                name = entry.filename
                posix = PurePosixPath(name)
                parts = posix.parts
                raw_parts = name.split("/")
                if (
                    "\\" in name
                    or name.startswith("/")
                    or name.endswith("/")
                    or posix.is_absolute()
                    or len(parts) < 2
                    or parts[0] != skill.name
                    or any(part in {"", ".", ".."} for part in raw_parts)
                ):
                    layout_valid = False
                if entry.date_time != _ZIP_TIMESTAMP or entry.compress_type != zipfile.ZIP_DEFLATED or entry.create_system != 3 or entry.external_attr != _ZIP_MODE:
                    metadata_valid = False
                if name in actual_files:
                    layout_valid = False
                else:
                    actual_files[name] = archive.read(entry)
            if names != sorted(names):
                layout_valid = False
    except (OSError, zipfile.BadZipFile):
        errors.append(f"{skill.name}: ZIP layout is invalid")
        errors.append(f"{skill.name}: ZIP metadata is invalid")
        errors.append(f"{skill.name}: ZIP content is invalid")
        errors.append(f"{skill.name}: package hash mismatch")
        return
    if not layout_valid:
        errors.append(f"{skill.name}: ZIP layout is invalid")
    if not metadata_valid:
        errors.append(f"{skill.name}: ZIP metadata is invalid")
    if expected_files is None:
        errors.append(f"{skill.name}: ZIP content cannot be compared without expected adapter")
        errors.append(f"{skill.name}: package hash mismatch")
        return
    expected_payloads = {
        f"{skill.name}/{relative}": (expected / relative).read_bytes()
        for relative in expected_files
    }
    if actual_files != expected_payloads:
        errors.append(f"{skill.name}: ZIP content is invalid")
    if package.read_bytes() != _expected_zip_bytes(expected):
        errors.append(f"{skill.name}: package hash mismatch")


def run_static_gate(registry: FamilyRegistry, source_root: Path, dist_root: Path) -> GateResult:
    """Return all independent static errors without short-circuiting."""
    source_root, dist_root = Path(source_root), Path(dist_root)
    errors: list[str] = []
    details: dict[str, object] = {"source_root": str(source_root), "dist_root": str(dist_root), "checked": []}
    for skill in registry.skills:
        _check_source(registry, source_root, skill, errors)
    snapshot_root = source_root.resolve() / registry.generated["compatibility_snapshots"]
    extension = registry.generated["package_extension"]
    with tempfile.TemporaryDirectory(prefix=".static-gate-") as temp:
        expected_root = Path(temp)
        for runtime in registry.adapters:
            for skill in registry.skills:
                expected = expected_root / runtime / skill.name
                render_failed = False
                try:
                    _render_tree(registry, skill, source_root, expected, runtime)
                except (OSError, ValueError) as error:
                    render_failed = True
                    errors.append(f"{runtime}/{skill.name}: cannot render expected adapter: {error}")
                actual = dist_root / runtime / skill.name
                if render_failed or not actual.is_dir() or _tree_hashes(expected) != _tree_hashes(actual):
                    errors.append(f"{runtime}/{skill.name}: adapter drift")
                if runtime == "codex":
                    _check_codex_contract(registry, source_root, skill, actual, errors)
                    snapshot = snapshot_root / f"{skill.name}.SKILL.md"
                    if render_failed or not snapshot.is_file() or not (expected / "SKILL.md").is_file():
                        errors.append(f"{skill.name}: compatibility snapshot drift")
                    elif snapshot.read_bytes() != (expected / "SKILL.md").read_bytes():
                        errors.append(f"{skill.name}: compatibility snapshot drift")
                    package = dist_root / "packages" / f"{skill.name}{extension}"
                    _validate_package(package, skill, expected if not render_failed else None, errors)
                details["checked"].append(f"{runtime}/{skill.name}")
    return GateResult(not errors, tuple(errors), details)
