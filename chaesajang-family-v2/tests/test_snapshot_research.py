import hashlib
import sys
from datetime import date
from pathlib import Path

import pytest


@pytest.fixture
def loop_modules():
    scripts = Path(__file__).resolve().parents[1] / "chaesajang-family-optimizer" / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        from optimizer_loop import research, snapshot
        from optimizer_loop.registry import FamilyRegistry, SkillSpec

        yield snapshot, research, FamilyRegistry, SkillSpec
    finally:
        sys.path.remove(str(scripts))


@pytest.fixture
def registry_factory(loop_modules):
    _, _, FamilyRegistry, SkillSpec = loop_modules

    def factory(root: Path, *, generated: dict | None = None) -> FamilyRegistry:
        core = root / "chaesajang-core"
        skill = root / "chaesajang-style"
        core.mkdir()
        skill.mkdir()
        (core / "persona_core.md").write_text("original", encoding="utf-8")
        (skill / "SKILL.md").write_text("skill", encoding="utf-8")
        return FamilyRegistry(
            root=root,
            core=core,
            skills=(SkillSpec("chaesajang-style", skill, (), False),),
            generated={} if generated is None else generated,
        )

    return factory


def claim_data(**overrides):
    data = {
        "claim": "A bounded instruction change needs a falsifiable evaluation.",
        "source_url": "https://example.test/paper",
        "source_date": "2026-08-20",
        "checked_at": "2026-08-30",
        "source_type": "peer_reviewed",
        "evidence": "A controlled comparison reports a measurable difference.",
        "confidence": "high",
        "local_evidence": ["chaesajang-core/persona_core.md"],
        "decision_impact": "Require one-change hypotheses.",
        "proposed_test": "Compare one-change candidates against the same baseline.",
    }
    data.update(overrides)
    return data


def test_snapshot_changes_when_canonical_text_changes(tmp_path, registry_factory, loop_modules):
    snapshot, _, _, _ = loop_modules
    registry = registry_factory(tmp_path)

    before = snapshot.snapshot_registry(registry)
    (tmp_path / "chaesajang-core" / "persona_core.md").write_text(
        "changed", encoding="utf-8"
    )

    assert snapshot.snapshot_registry(registry) != before


def test_snapshot_uses_only_registry_paths_and_excludes_generated_content(
    tmp_path, registry_factory, loop_modules
):
    snapshot, _, _, _ = loop_modules
    registry = registry_factory(tmp_path)
    (tmp_path / "outside.md").write_text("outside", encoding="utf-8")
    for name in ("dist", "experiments", "skills", ".skill", ".git", "__pycache__"):
        generated = tmp_path / "chaesajang-core" / name
        generated.mkdir()
        (generated / "ignored.md").write_text(name, encoding="utf-8")

    hashes = snapshot.snapshot_registry(registry)

    assert set(hashes) == {
        "chaesajang-core/persona_core.md",
        "chaesajang-style/SKILL.md",
    }
    assert all("\\" not in path for path in hashes)


def test_snapshot_excludes_configured_compatibility_roots_and_cache_files(
    tmp_path, registry_factory, loop_modules
):
    snapshot, _, _, _ = loop_modules
    registry = registry_factory(
        tmp_path,
        generated={
            "compatibility_snapshots": "chaesajang-core/compatibility-output"
        },
    )
    for relative in (
        "chaesajang-core/compatibility-output/copied.md",
        "chaesajang-core/cache/runtime.md",
        "chaesajang-core/compiled.cache",
    ):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("generated", encoding="utf-8")

    hashes = snapshot.snapshot_registry(registry)

    assert set(hashes) == {
        "chaesajang-core/persona_core.md",
        "chaesajang-style/SKILL.md",
    }


def test_combined_snapshot_hash_is_stable_for_mapping_order(loop_modules):
    snapshot, _, _, _ = loop_modules
    first = {"chaesajang-style/SKILL.md": "b", "chaesajang-core/persona_core.md": "a"}
    second = {"chaesajang-core/persona_core.md": "a", "chaesajang-style/SKILL.md": "b"}

    assert snapshot.combined_snapshot_hash(first) == snapshot.combined_snapshot_hash(second)
    assert snapshot.combined_snapshot_hash(first) == hashlib.sha256(
        b"chaesajang-core/persona_core.md\x00a\x00chaesajang-style/SKILL.md\x00b\x00"
    ).hexdigest()


def test_low_confidence_preprint_cannot_be_actionable_alone(loop_modules):
    _, research, _, _ = loop_modules
    claim = research.normalize_claim(
        claim_data(source_type="preprint", confidence="low")
    )

    assert claim["status"] == "watchlist"


@pytest.mark.parametrize(
    "field, value",
    [
        ("source_url", "ftp://example.test/paper"),
        ("source_date", "2026-8-20"),
        ("source_type", "book"),
        ("confidence", "certain"),
        ("local_evidence", []),
        ("decision_impact", ""),
        ("proposed_test", ""),
    ],
)
def test_normalize_claim_rejects_invalid_required_values(loop_modules, field, value):
    _, research, _, _ = loop_modules
    with pytest.raises(ValueError):
        research.normalize_claim(claim_data(**{field: value}))


def test_normalize_claim_rejects_unknown_or_missing_fields(loop_modules):
    _, research, _, _ = loop_modules
    with pytest.raises(ValueError, match="unknown"):
        research.normalize_claim(claim_data(extra="not allowed"))
    missing = claim_data()
    missing.pop("evidence")
    with pytest.raises(ValueError, match="missing"):
        research.normalize_claim(missing)


def test_blog_claim_stays_on_watchlist(loop_modules):
    _, research, _, _ = loop_modules
    assert research.normalize_claim(claim_data(source_type="blog"))["status"] == "watchlist"


def test_append_claim_normalizes_and_appends_jsonl(tmp_path, loop_modules):
    _, research, _, _ = loop_modules
    path = tmp_path / "research.jsonl"

    research.append_claim(path, claim_data())
    research.append_claim(path, claim_data(claim="A distinct claim."))

    assert [row["claim"] for row in research.read_jsonl(path)] == [
        "A bounded instruction change needs a falsifiable evaluation.",
        "A distinct claim.",
    ]


def test_select_delta_claims_filters_source_date_and_relevant_tags(loop_modules):
    _, research, _, _ = loop_modules
    claims = [
        research.normalize_claim(claim_data(source_date="2026-08-20")),
        research.normalize_claim(
            claim_data(
                claim="An unrelated observation.",
                source_date="2026-08-21",
                local_evidence=["chaesajang-style/SKILL.md"],
            )
        ),
        research.normalize_claim(claim_data(source_date="2026-08-01")),
    ]

    assert research.select_delta_claims(
        claims, since=date(2026, 8, 10), tags={"persona_core"}
    ) == [claims[0]]


def test_select_delta_claims_keeps_month_precision_conservatively(loop_modules):
    _, research, _, _ = loop_modules
    month_claim = claim_data(source_date="2026-08")
    full_date_claim = claim_data(source_date="2026-08-01")

    assert research.select_delta_claims(
        [month_claim, full_date_claim], since=date(2026, 8, 15), tags=set()
    ) == [research.normalize_claim(month_claim)]


def test_select_delta_claims_uses_only_local_evidence_tags(loop_modules):
    _, research, _, _ = loop_modules
    narrative_only = claim_data(
        claim="persona_core is mentioned in this narrative but not as local evidence.",
        local_evidence=["chaesajang-style/SKILL.md"],
    )

    assert research.select_delta_claims(
        [narrative_only], since=date(2026, 8, 1), tags={"persona_core"}
    ) == []


def test_select_delta_claims_returns_normalized_records_not_stale_input(loop_modules):
    _, research, _, _ = loop_modules
    stale = {**claim_data(), "status": "watchlist"}

    selected = research.select_delta_claims(
        [stale], since=date(2026, 8, 1), tags={"persona_core"}
    )

    assert selected == [research.normalize_claim(claim_data())]
    assert selected[0] is not stale


def test_normalize_claim_preserves_verified_month_precision(loop_modules):
    _, research, _, _ = loop_modules

    claim = research.normalize_claim(claim_data(source_date="2025-04"))

    assert claim["source_date"] == "2025-04"


def test_seed_index_contains_exactly_the_nine_primary_sources(loop_modules):
    _, research, _, _ = loop_modules
    index = Path(__file__).resolve().parents[1] / "research" / "index.jsonl"
    expected_urls = {
        "https://agentskills.io/specification",
        "https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills",
        "https://developers.openai.com/api/docs/guides/latest-model",
        "https://developers.openai.com/api/docs/guides/evaluation-best-practices",
        "https://developers.openai.com/api/docs/guides/graders",
        "https://aclanthology.org/2025.findings-naacl.326/",
        "https://aclanthology.org/2025.findings-emnlp.532/",
        "https://aclanthology.org/2025.naacl-long.436/",
        "https://aclanthology.org/2025.ijcnlp-long.18/",
    }

    records = research.read_jsonl(index)

    assert {record["source_url"] for record in records} == expected_urls
    assert len(records) == len(expected_urls)
    assert all(
        research.normalize_claim(
            {key: value for key, value in record.items() if key != "status"}
        )
        == record
        for record in records
    )


def test_living_document_cards_keep_version_provenance_distinct_from_checked_at(
    loop_modules,
):
    _, research, _, _ = loop_modules
    index = Path(__file__).resolve().parents[1] / "research" / "index.jsonl"
    records = {record["source_url"]: record for record in research.read_jsonl(index)}
    expected_dates = {
        "https://developers.openai.com/api/docs/guides/latest-model": "2026-06-26",
        "https://developers.openai.com/api/docs/guides/evaluation-best-practices": "2026-08-29",
        "https://developers.openai.com/api/docs/guides/graders": "2026-08-29",
    }

    for source_url, source_date in expected_dates.items():
        record = records[source_url]
        assert record["checked_at"] == "2026-08-30"
        assert record["source_date"] == source_date
        assert record["source_date"] != record["checked_at"]
        assert "version provenance" in record["evidence"]
