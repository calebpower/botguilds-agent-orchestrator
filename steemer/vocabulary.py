"""The game's OBSERVED vocabularies, harvested from our own history.

Why this exists (2026-08-21): every regression shipped this session lived in an input the
tests never enumerated — v0.46.0 in "lumber with no metal", v0.49.0 in the `not_in_village`
rejection. Both suites were green AND fully mutation-killed.

That is not a gap mutation testing can close. Mutation testing proves a test is SENSITIVE to
changes in the code; it says nothing about whether the tests COVER the input space. A suite
can kill every mutant and still only exercise the cases its author imagined.

So: harvest the real vocabularies from the database and drive property tests over ALL of
them. The database is genuinely independent of our code, so this is the "test against the
source, not a re-export of it" rule applied to inputs rather than to outputs — a test that
enumerated the 17 observed `reason` values would have caught v0.49.0 on the first run.

The harvest is deliberately SEPARATE from the frozen fixture it feeds (see
`tests/fixtures/`): a live query in the test suite would be slow, non-deterministic, and
unavailable in the reaper container. Re-harvest deliberately, review the diff, commit it.
"""
from __future__ import annotations

import json
from typing import Any

# Verbs the protocol exposes. Sourced from docs/03-actions.md rather than from what we
# happen to have SENT — the whole point is to see what we have never tried.
PROTOCOL_VERBS: tuple[str, ...] = (
    "move", "ride", "attack", "charge", "throw", "pickup", "drop", "equip", "unequip",
    "use", "open", "say", "cast", "taste", "brew", "smelt", "forge", "sell", "buy",
    "list", "buy_listing", "recruit", "embark", "spend_xp", "rest", "refresh",
)


def harvest(conn: Any, sample_frames: int = 400) -> dict[str, Any]:
    """Read the observed vocabularies out of recorded history."""
    import collections
    import zlib

    def rows(sql, params=()):
        return conn.execute(sql, params).fetchall()

    def col(r, name, idx):
        return r[name] if hasattr(r, "keys") else r[idx]

    reasons = sorted({col(r, "reason", 0) for r in rows(
        "SELECT DISTINCT reason FROM action_errors") if col(r, "reason", 0)})
    verbs_sent = sorted({col(r, "action", 0) for r in rows(
        "SELECT DISTINCT action FROM actions_sent") if col(r, "action", 0)})
    event_kinds = sorted({col(r, "kind", 0) for r in rows(
        "SELECT DISTINCT kind FROM events") if col(r, "kind", 0)})

    tiles: set[str] = set()
    try:
        tiles = {col(r, "kind", 0) for r in rows("SELECT DISTINCT kind FROM tiles_seen")
                 if col(r, "kind", 0)}
    except Exception:                       # table may not exist on a fresh checkout
        pass

    items: collections.Counter = collections.Counter()
    mobs: collections.Counter = collections.Counter()
    equippable: set[str] = set()
    uses_by_kind: dict[str, list[str]] = {}
    for r in rows(f"SELECT json FROM frames ORDER BY seq DESC LIMIT {int(sample_frames)}"):
        raw = col(r, "json", 0)
        if isinstance(raw, str):
            raw = raw.encode("latin-1")
        try:
            f = json.loads(zlib.decompress(raw))
        except Exception:
            continue
        for ch in f.get("chars") or []:
            for it in ch.get("inventory") or []:
                k = str(it.get("kind"))
                items[k] += 1
                if it.get("uses"):
                    uses_by_kind[k] = sorted(it["uses"])
                if "equip" in (it.get("uses") or []):
                    equippable.add(k)
            for v in (ch.get("equipment") or {}).values():
                if isinstance(v, dict) and v.get("kind"):
                    equippable.add(v["kind"])
                    items[v["kind"]] += 1
        for e in (f.get("visible") or {}).get("entities", []) or []:
            if e.get("faction") == "monster" and e.get("kind"):
                mobs[e["kind"]] += 1
        for st in (f.get("shop") or {}).get("stock", []) or []:
            if st.get("kind"):
                items[st["kind"]] += 1
                equippable.add(st["kind"]) if st.get("req") else None
    return {
        "reasons": reasons,
        "verbs_sent": verbs_sent,
        "verbs_protocol": list(PROTOCOL_VERBS),
        "verbs_never_sent": sorted(set(PROTOCOL_VERBS) - set(verbs_sent)),
        "event_kinds": event_kinds,
        "tiles": sorted(tiles),
        "items": sorted(items),
        "equippable": sorted(equippable),
        "uses_by_kind": uses_by_kind,
        "mobs": sorted(mobs),
    }


if __name__ == "__main__":              # pragma: no cover - harvest CLI
    import argparse
    import sys
    from . import db as _db
    ap = argparse.ArgumentParser(description="Harvest observed vocabularies to a fixture")
    ap.add_argument("--out", default="tests/fixtures/vocabulary.json")
    ap.add_argument("--frames", type=int, default=400)
    a = ap.parse_args()
    voc = harvest(_db.connect(_db.load_db_config(), readonly=True), sample_frames=a.frames)
    with open(a.out, "w") as fh:
        json.dump(voc, fh, indent=2, sort_keys=True)
        fh.write("\n")
    print(f"wrote {a.out}: " + ", ".join(f"{k}={len(v)}" for k, v in voc.items()
                                         if isinstance(v, (list, dict))), file=sys.stderr)
