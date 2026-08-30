#!/usr/bin/env python3
"""Compatibility wrapper for the registry-driven canonical renderer."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", help="family root; defaults to this script's directory")
    parser.add_argument("--check", action="store_true", help="check generated adapters without writing")
    args = parser.parse_args()

    root = Path(args.root).resolve() if args.root else Path(__file__).resolve().parent
    scripts = root / "chaesajang-family-optimizer" / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        from optimizer_loop.registry import load_registry
        from optimizer_loop.render import render_all
        from optimizer_loop.static_gate import run_static_gate

        registry = load_registry(root)
        dist = root / registry.generated["dist"]
        if args.check:
            result = run_static_gate(registry, root, dist)
            if result.passed:
                print("drift-free: canonical adapters, snapshots, and packages are synchronized.")
                return 0
            print("drift detected:")
            for error in result.errors:
                print(f" - {error}")
            return 2
        render_all(registry, root, dist)
        print("generated canonical adapters, compatibility snapshots, and packages.")
        return 0
    except (KeyError, OSError, ValueError) as error:
        print(f"[FAIL] {error}", file=sys.stderr)
        return 1
    finally:
        sys.path.remove(str(scripts))


if __name__ == "__main__":
    raise SystemExit(main())
