"""Emit a KPI snapshot as JSON — the input the improvement loop's analysis
subagent reads.

Run inside the project env (it imports steemer):

    uv run tools/analyze.py [--db guild_log.db] [--compact]

Read-only; safe against a live database (WAL).
"""

from __future__ import annotations

import argparse
import json
import sys

from steemer.metrics import snapshot


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default="guild_log.db", help="path to guild_log.db")
    ap.add_argument("--compact", action="store_true",
                    help="single-line JSON instead of indented")
    args = ap.parse_args(argv)

    try:
        snap = snapshot(args.db)
    except Exception as e:  # a missing/locked DB should say so, not traceback
        print(json.dumps({"error": str(e), "db": args.db}), file=sys.stderr)
        return 1

    print(json.dumps(snap, separators=(",", ":") if args.compact else None,
                     indent=None if args.compact else 2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
