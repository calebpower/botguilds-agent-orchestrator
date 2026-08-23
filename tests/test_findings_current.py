"""The findings notebook must keep pace with the strategy — executable, not aspirational.

On 2026-08-23 the operator caught a fifteen-version lapse ("you've lapsed on findings,
codex, and timeline"): every deploy from 0.73.0 to 0.87.0 shipped without a findings
entry, and since the timeline tab and the codex's learnings both READ findings.jsonl,
three surfaces went quietly stale together. A prose rule ("record findings every pass")
had existed the whole time; this is the failing test the rule never had.
"""
import re

import steemer.findings as findings

_VER = re.compile(r"explorer/(\d+)\.(\d+)")


def _minor(tag):
    m = _VER.search(str(tag))
    return (int(m.group(1)), int(m.group(2))) if m else None


def test_findings_lag_the_strategy_by_at_most_two_minor_versions():
    src = open("steemer/strategy/explorer.py").read()
    m = re.search(r'version = "explorer/(\d+)\.(\d+)', src)
    current = (int(m.group(1)), int(m.group(2)))
    newest = max((v for f in findings.load() for t in (f.get("tags") or [])
                  if (v := _minor(t)) is not None), default=(0, 0))
    lag = (current[0] - newest[0]) * 1000 + (current[1] - newest[1])
    assert lag <= 2, (
        f"strategy is at explorer/{current[0]}.{current[1]} but the newest finding tag is "
        f"explorer/{newest[0]}.{newest[1]} — the timeline and codex go stale together when "
        f"this lapses. Write the findings entries; do not widen this bound.")
