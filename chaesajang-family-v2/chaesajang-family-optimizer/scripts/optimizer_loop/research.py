"""Validation and durable storage for normalized research evidence cards."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date
from pathlib import Path
import re
from urllib.parse import urlparse

from .artifacts import read_jsonl, write_jsonl


_REQUIRED_FIELDS = frozenset(
    {
        "claim",
        "source_url",
        "source_date",
        "checked_at",
        "source_type",
        "evidence",
        "confidence",
        "local_evidence",
        "decision_impact",
        "proposed_test",
    }
)
_SOURCE_TYPES = frozenset({"official", "peer_reviewed", "technical_report", "preprint", "blog"})
_CONFIDENCE = frozenset({"high", "medium", "low"})
_YEAR_MONTH = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _required_text(data: dict, field: str) -> str:
    value = data[field]
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value.strip()


def _iso_date(data: dict, field: str, *, allow_month: bool = False) -> str:
    value = _required_text(data, field)
    if allow_month and _YEAR_MONTH.fullmatch(value):
        return value
    try:
        parsed = date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{field} must be an ISO date") from error
    if parsed.isoformat() != value:
        raise ValueError(f"{field} must be an ISO date")
    return value


def _is_after_since(value: str, since: date) -> bool:
    if _YEAR_MONTH.fullmatch(value):
        year, month = (int(part) for part in value.split("-"))
        return (year, month) >= (since.year, since.month)
    return date.fromisoformat(value) > since


def normalize_claim(data: dict) -> dict:
    """Validate one exact evidence-card payload and add its routing status."""
    if not isinstance(data, dict):
        raise TypeError("claim must be a dictionary")
    missing = _REQUIRED_FIELDS - set(data)
    unknown = set(data) - _REQUIRED_FIELDS
    if missing:
        raise ValueError(f"missing claim fields: {sorted(missing)}")
    if unknown:
        raise ValueError(f"unknown claim fields: {sorted(unknown)}")

    source_url = _required_text(data, "source_url")
    parsed_url = urlparse(source_url)
    if parsed_url.scheme not in {"http", "https"} or not parsed_url.netloc:
        raise ValueError("source_url must be an http:// or https:// URL")
    source_type = _required_text(data, "source_type")
    if source_type not in _SOURCE_TYPES:
        raise ValueError(f"source_type must be one of {sorted(_SOURCE_TYPES)}")
    confidence = _required_text(data, "confidence")
    if confidence not in _CONFIDENCE:
        raise ValueError(f"confidence must be one of {sorted(_CONFIDENCE)}")
    local_evidence = data["local_evidence"]
    if (
        not isinstance(local_evidence, list)
        or not local_evidence
        or not all(isinstance(item, str) and item.strip() for item in local_evidence)
    ):
        raise ValueError("local_evidence must be a non-empty list of strings")

    normalized = {
        "claim": _required_text(data, "claim"),
        "source_url": source_url,
        "source_date": _iso_date(data, "source_date", allow_month=True),
        "checked_at": _iso_date(data, "checked_at"),
        "source_type": source_type,
        "evidence": _required_text(data, "evidence"),
        "confidence": confidence,
        "local_evidence": [item.strip() for item in local_evidence],
        "decision_impact": _required_text(data, "decision_impact"),
        "proposed_test": _required_text(data, "proposed_test"),
    }
    normalized["status"] = (
        "watchlist"
        if confidence == "low" or source_type in {"preprint", "blog"}
        else "actionable"
    )
    return normalized


def append_claim(path: Path, claim: dict) -> None:
    """Append a normalized claim using the shared atomic JSONL writer."""
    target = Path(path)
    existing = read_jsonl(target) if target.exists() else []
    write_jsonl(target, [*existing, normalize_claim(claim)])


def select_delta_claims(
    claims: Iterable[dict], since: date, tags: set[str]
) -> list[dict]:
    """Select newer claims whose stored local evidence is relevant to *tags*."""
    if not isinstance(since, date):
        raise TypeError("since must be a date")
    if not isinstance(tags, set) or not all(isinstance(tag, str) and tag for tag in tags):
        raise TypeError("tags must be a set of non-empty strings")
    normalized_tags = {tag.casefold() for tag in tags}
    selected: list[dict] = []
    for claim in claims:
        normalized = normalize_claim({key: value for key, value in claim.items() if key != "status"})
        if not _is_after_since(normalized["source_date"], since):
            continue
        local_evidence = [item.casefold() for item in normalized["local_evidence"]]
        if not normalized_tags or any(
            tag in item for tag in normalized_tags for item in local_evidence
        ):
            selected.append(normalized)
    return selected
