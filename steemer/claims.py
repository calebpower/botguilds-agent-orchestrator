"""A ledger of numbers reported to the operator, and a way to re-check them.

v0.61.0 gave the BOT a detector that asks "did what we predicted actually happen?". This is
the same instrument turned on the loop itself, because the loop's own error rate is currently
larger than the bot's.

The case that motivated it: a forge success rate of "35% -> 68%" was reported as confirming
v0.64.0. Both numbers counted rival forges. It survived a full pass and was caught only by
accident, while chasing something else. A ledger would have caught it on the next tick, because
re-running the SAME question through `steemer.attribution` (where ownership filtering is the
default) yields 4 of 19, not 13 of 19.

The design point is that a claim records the QUESTION, not just the answer. A number in prose
cannot be re-checked; a metrics call with its arguments can be re-run against a database that
is immutable history. If the stored answer and the re-run disagree, the original was wrong —
the underlying frames have not changed.

Deliberately narrow: this checks claims that are FUNCTIONS OF RECORDED DATA. It cannot check
"the fix is structurally right" or "this is worth building", and pretending otherwise would be
the unfalsifiable-claim mistake the expectation detector already refuses to make.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any

import steemer.attribution as metrics

LEDGER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "claims.jsonl")

# How far a re-run may drift before the original claim is called wrong. Zero would be wrong
# in the other direction: `rate_per` divides by a frame count that grows while a run is live,
# so a claim recorded mid-run legitimately moves a little.
TOLERANCE = 0.02

# Only these may be recorded as checks. A ledger that could call anything would be a way to
# re-run the same bad ad-hoc query and get the same bad answer twice.
CHECKS = {
    "rate_per": metrics.rate_per,
    "distinct_entities": metrics.distinct_entities,
    "event_count": lambda conn, **kw: len(metrics.events(conn, **kw)),
    "frame_count": metrics.frame_count,
}


def record(claim: str, check: str, kwargs: dict[str, Any], value: float,
           iteration: str | None = None, path: str = LEDGER) -> dict[str, Any]:
    """Log a number that was REPORTED, with the question that produced it."""
    if check not in CHECKS:
        raise ValueError(f"unknown check {check!r}; allowed: {sorted(CHECKS)}")
    row = {"at": time.time(), "iteration": iteration, "claim": claim,
           "check": check, "kwargs": kwargs, "value": value}
    with open(path, "a") as fh:
        fh.write(json.dumps(row) + "\n")
    return row


def load(path: str = LEDGER) -> list[dict[str, Any]]:
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path):
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


def recheck(conn, path: str = LEDGER, tolerance: float = TOLERANCE) -> list[dict[str, Any]]:
    """Re-run every recorded claim. Returns one verdict per claim.

    Verdicts are three-valued for the same reason the expectation detector's are: an
    `unavailable` claim (a pruned run, a changed schema) is NOT a wrong one, and folding
    the two together would turn housekeeping into false alarms.
    """
    results = []
    for row in load(path):
        verdict = {"claim": row["claim"], "iteration": row.get("iteration"),
                   "recorded": row["value"]}
        fn = CHECKS.get(row["check"])
        if fn is None:
            verdict.update(status="unavailable", detail=f"unknown check {row['check']!r}")
            results.append(verdict)
            continue
        rid = row.get("kwargs", {}).get("run_id")
        if rid is not None and not metrics.run_exists(conn, rid):
            # A pruned or never-existent run is housekeeping, not a wrong number. Checked
            # explicitly because `frame_count` would answer 0 and that reads as a 100% drift.
            verdict.update(status="unavailable", detail=f"run {rid} is not in this database")
            results.append(verdict)
            continue
        try:
            now = fn(conn, **row["kwargs"])
        except Exception as e:
            verdict.update(status="unavailable", detail=f"{type(e).__name__}: {e}")
            results.append(verdict)
            continue
        verdict["recomputed"] = now
        denom = max(abs(row["value"]), 1e-9)
        drift = abs(now - row["value"]) / denom
        verdict["drift"] = drift
        verdict["status"] = "confirmed" if drift <= tolerance else "contradicted"
        results.append(verdict)
    return results


def summarise(results: list[dict[str, Any]]) -> str:
    counts: dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    lines = [f"claims: {len(results)} " + ", ".join(f"{k} {v}" for k, v in sorted(counts.items()))]
    for r in results:
        if r["status"] == "contradicted":
            lines.append(f"  CONTRADICTED [{r.get('iteration') or '?'}] {r['claim']}"
                         f"\n     reported {r['recorded']}, recomputed {r['recomputed']}"
                         f" ({r['drift']:.0%} drift)")
    return "\n".join(lines)
