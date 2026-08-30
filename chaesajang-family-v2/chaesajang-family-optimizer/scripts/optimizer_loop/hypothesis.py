"""Strict parsing for a single-change experiment hypothesis."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml


_REQUIRED_FIELDS = frozenset(
    {
        "claim_ids",
        "change_group",
        "allowed_paths",
        "primary_axis",
        "protected_axes",
        "risk",
        "blind_required",
        "stop_rule",
    }
)


def canonical_relative_path(value: object, label: str) -> str:
    """Return a safe POSIX relative path, rejecting absolute and escaped paths."""
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a non-empty POSIX relative path")
    if "\x00" in value:
        raise ValueError(f"{label} must not contain NUL bytes")
    if "\\" in value:
        raise ValueError(f"{label} must use POSIX separators: {value}")
    path = PurePosixPath(value)
    if path.is_absolute() or path.drive or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError(f"{label} must not be absolute or escape its root: {value}")
    # PurePosixPath treats Windows drive-relative paths as normal segments.
    first = path.parts[0] if path.parts else ""
    if len(first) >= 2 and first[1] == ":":
        raise ValueError(f"{label} must not be absolute or escape its root: {value}")
    return path.as_posix()


def _string_list(value: object, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{label} must be a non-empty list of strings")
    if len(set(value)) != len(value):
        raise ValueError(f"{label} must not contain duplicates")
    return tuple(value)


@dataclass(frozen=True)
class Hypothesis:
    claim_ids: tuple[str, ...]
    change_group: str
    allowed_paths: tuple[str, ...]
    primary_axis: str
    protected_axes: tuple[str, ...]
    risk: str
    blind_required: bool
    stop_rule: str
    body: str

    @classmethod
    def from_markdown(cls, path: Path) -> "Hypothesis":
        """Load an experiment hypothesis whose document starts with YAML frontmatter."""
        text = Path(path).read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            raise ValueError("hypothesis.md must start with YAML frontmatter")
        closing = text.find("\n---\n", 4)
        if closing < 0:
            raise ValueError("hypothesis.md frontmatter is not closed")
        try:
            data = yaml.safe_load(text[4:closing])
        except yaml.YAMLError as error:
            raise ValueError(f"invalid hypothesis frontmatter: {error}") from error
        if not isinstance(data, dict):
            raise ValueError("hypothesis frontmatter must be a mapping")
        unknown = set(data) - _REQUIRED_FIELDS
        missing = _REQUIRED_FIELDS - set(data)
        if unknown:
            raise ValueError(f"unknown hypothesis fields: {sorted(unknown)}")
        if missing:
            raise ValueError(f"missing hypothesis fields: {sorted(missing)}")

        claim_ids = _string_list(data["claim_ids"], "claim_ids")
        change_group = data["change_group"]
        if not isinstance(change_group, str) or not change_group:
            raise ValueError("change_group must be exactly one non-empty string")
        raw_allowed_paths = _string_list(data["allowed_paths"], "allowed_paths")
        allowed_paths = tuple(
            canonical_relative_path(item, "allowed_paths") for item in raw_allowed_paths
        )
        if len(set(allowed_paths)) != len(allowed_paths):
            raise ValueError("allowed_paths must not contain duplicates")
        primary_axis = data["primary_axis"]
        if not isinstance(primary_axis, str) or not primary_axis:
            raise ValueError("primary_axis must be a non-empty string")
        protected_axes = _string_list(data["protected_axes"], "protected_axes")
        risk = data["risk"]
        if not isinstance(risk, str) or not risk:
            raise ValueError("risk must be a non-empty string")
        blind_required = data["blind_required"]
        if not isinstance(blind_required, bool):
            raise ValueError("blind_required must be boolean")
        stop_rule = data["stop_rule"]
        if not isinstance(stop_rule, str) or not stop_rule:
            raise ValueError("stop_rule must be a non-empty string")
        return cls(
            claim_ids=claim_ids,
            change_group=change_group,
            allowed_paths=allowed_paths,
            primary_axis=primary_axis,
            protected_axes=protected_axes,
            risk=risk,
            blind_required=blind_required,
            stop_rule=stop_rule,
            body=text[closing + len("\n---\n") :],
        )
