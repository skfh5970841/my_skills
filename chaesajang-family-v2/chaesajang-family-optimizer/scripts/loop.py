"""Command-line entry point for the Chaesajang family optimizer."""

from __future__ import annotations

import argparse
from pathlib import Path

from optimizer_loop.registry import load_registry


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("bootstrap", "cycle", "resume", "report", "promote"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    args = parser.parse_args()
    registry = load_registry(args.root)
    print(f"{args.mode}: {len(registry.skills)} managed skills")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
