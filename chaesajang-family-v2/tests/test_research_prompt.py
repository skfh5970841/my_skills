import sys
from pathlib import Path

import pytest


SCRIPTS = (
    Path(__file__).resolve().parents[1]
    / "chaesajang-family-optimizer"
    / "scripts"
)
sys.path.insert(0, str(SCRIPTS))

from optimizer_loop import cli
from optimizer_loop.research_prompt import ResearchPromptRequest, build_research_prompt


def request(**overrides):
    values = {
        "target": "chaesajang-advisor",
        "problem": "Long answers repeat the same explanation.",
        "local_evidence": ("chaesajang-advisor/SKILL.md",),
        "scope": "delta",
        "checked_at": "2026-09-05",
        "since": "2026-08-30",
    }
    values.update(overrides)
    return ResearchPromptRequest(**values)


def test_delta_prompt_is_deterministic_paste_ready_and_matches_evidence_contract():
    first = build_research_prompt(request())
    second = build_research_prompt(request())

    assert first == second
    assert "material published after 2026-08-30" in first
    assert '"local_evidence": [' in first
    assert '"chaesajang-advisor/SKILL.md"' in first
    assert "Return only newline-delimited JSON (JSONL)" in first
    assert "claim, source_url, source_date, checked_at, source_type" in first
    assert "Do not add a status field" in first
    assert "Do not imitate or role-play" in first


def test_initial_prompt_covers_full_protocol_topics():
    prompt = build_research_prompt(
        request(scope="initial", since=None)
    )

    assert "Agent Skill design" in prompt
    assert "judge bias" in prompt
    assert "memorization and overfitting prevention" in prompt


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"since": None}, "requires since"),
        ({"since": "2026-9-5"}, "ISO date"),
        (
            {"scope": "initial", "since": "2026-08-30"},
            "does not accept",
        ),
        (
            {"scope": "full-refresh", "since": None},
            "requires one documented",
        ),
        (
            {
                "scope": "full-refresh",
                "since": None,
                "refresh_reason": "because-I-want-to",
            },
            "requires one documented",
        ),
        (
            {"local_evidence": ("../outside.md",)},
            "local_evidence",
        ),
    ],
)
def test_prompt_request_rejects_ambiguous_or_unsafe_scope(overrides, message):
    with pytest.raises(ValueError, match=message):
        build_research_prompt(request(**overrides))


def test_cli_prints_prompt_without_creating_files(tmp_path, capsys):
    family = tmp_path / "family"
    core = family / "core"
    skill = family / "skill"
    core.mkdir(parents=True)
    skill.mkdir()
    (family / "family.yaml").write_text(
        """schema_version: 1
core: core
skills:
  - name: demo
    source: skill
    core_files: []
    inject_gaze: false
generated:
  compatibility_snapshots: skills
  dist: dist
  experiments: experiments
  package_extension: .skill
adapters:
  codex:
    exclude: []
  claude:
    exclude: [agents]
""",
        encoding="utf-8",
    )
    before = sorted(path.relative_to(family) for path in family.rglob("*"))

    result = cli.main(
        [
            "--root",
            str(family),
            "research-prompt",
            "--target",
            "demo",
            "--problem",
            "The output repeats itself.",
            "--local-evidence",
            "skill/SKILL.md",
            "--scope",
            "full-refresh",
            "--refresh-reason",
            "user-request",
            "--checked-at",
            "2026-09-05",
        ]
    )

    after = sorted(path.relative_to(family) for path in family.rglob("*"))
    assert result == 0
    assert "user-request" in capsys.readouterr().out
    assert after == before
