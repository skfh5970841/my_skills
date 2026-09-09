"""Minimal deterministic command-line modes for the optimizer loop."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from .promote import _audit_tree, _load_manifest, next_action, promote
from .research_prompt import ResearchPromptRequest, build_research_prompt
from .registry import load_registry


def _experiment_dir(registry, identifier: str) -> Path:
    if (
        not identifier
        or identifier in {".", ".."}
        or "/" in identifier
        or "\\" in identifier
    ):
        raise ValueError("experiment must be one safe identifier")
    return registry.root / registry.generated["experiments"] / identifier


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[3]
    )
    commands = parser.add_subparsers(dest="mode", required=True)

    bootstrap = commands.add_parser("bootstrap")
    bootstrap.add_argument("--experiment", required=True)
    bootstrap.add_argument("--model", required=True)
    bootstrap.add_argument("--reasoning", required=True)

    research_prompt = commands.add_parser("research-prompt")
    research_prompt.add_argument("--target", required=True)
    research_prompt.add_argument("--problem", required=True)
    research_prompt.add_argument(
        "--local-evidence", action="append", required=True, dest="local_evidence"
    )
    research_prompt.add_argument(
        "--scope", choices=("initial", "delta", "full-refresh"), required=True
    )
    research_prompt.add_argument("--checked-at", required=True)
    research_prompt.add_argument("--since")
    research_prompt.add_argument(
        "--refresh-reason",
        choices=(
            "runtime-change",
            "evidence-conflict",
            "corpus-expansion",
            "user-request",
        ),
    )

    cycle = commands.add_parser("cycle")
    cycle.add_argument("--experiment", required=True)
    cycle.add_argument("--claims", type=Path)
    cycle.add_argument("--hypothesis", type=Path)
    cycle.add_argument("--cases", type=Path)
    cycle.add_argument("--ratings", type=Path)
    cycle.add_argument("--timeout", type=int)

    resume = commands.add_parser("resume")
    resume.add_argument("--experiment", required=True)
    resume.add_argument("--timeout", type=int)

    report = commands.add_parser("report")
    report.add_argument("--experiment", required=True)

    promotion = commands.add_parser("promote")
    promotion.add_argument("--experiment", required=True)
    promotion.add_argument("--approved-by-user", action="store_true", required=True)
    promotion.add_argument("--install-root", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Validate, read, and print deterministic state; only promote may write."""
    args = _parser().parse_args(argv)
    registry = load_registry(args.root)
    if args.mode == "research-prompt":
        prompt = build_research_prompt(
            ResearchPromptRequest(
                target=args.target,
                problem=args.problem,
                local_evidence=tuple(args.local_evidence),
                scope=args.scope,
                checked_at=args.checked_at,
                since=args.since,
                refresh_reason=args.refresh_reason,
            )
        )
        print(prompt, end="")
        return 0
    experiment = _experiment_dir(registry, args.experiment)
    if args.mode == "bootstrap":
        print(
            json.dumps(
                {
                    "mode": args.mode,
                    "experiment_id": args.experiment,
                    "model": args.model,
                    "reasoning": args.reasoning,
                    "managed_skills": len(registry.skills),
                },
                sort_keys=True,
            )
        )
        return 0
    if args.mode == "promote":
        result = promote(
            experiment,
            registry,
            approved_by_user=args.approved_by_user,
            install_root=args.install_root,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    _audit_tree(
        registry.root / registry.generated["experiments"],
        experiment,
        "experiment directory",
    )
    manifest = _load_manifest(experiment)
    if args.mode == "report":
        report_path = experiment / "report.md"
        if not report_path.is_file():
            raise ValueError("report.md is missing")
        print(report_path.read_text(encoding="utf-8"), end="")
        return 0
    print(
        json.dumps(
            {
                "mode": args.mode,
                "experiment_id": manifest.experiment_id,
                "status": manifest.status.value,
                "next_action": next_action(manifest),
            },
            sort_keys=True,
        )
    )
    return 0
