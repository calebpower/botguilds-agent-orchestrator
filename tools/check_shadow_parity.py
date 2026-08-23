"""Shadow parity: recompute every logged model score offline and demand agreement.

The classic failure of a train/serve split is silent feature drift — live code and
extraction code computing "the same" features differently. mlfeat makes that hard by
construction (one implementation); this makes it PROVEN by measurement: for each
`model_score` intel row of a run, rebuild the band history from the run's frames alone,
recompute the forecast with the committed artifacts, and compare to what the live bot
logged, to 1e-6.

Usage: uv run python tools/check_shadow_parity.py [--db config] [--run N]
Exit 0 = parity holds; 1 = divergence (print the first few); 2 = nothing to check.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from steemer import db, mlfeat, models, protocol  # noqa: E402
from steemer.strategy.explorer import THREAT_KINDS, WILDLIFE_SAFE  # noqa: E402

TOL = 1e-6


def replay_band_scores(conn, run_id: int) -> list[dict]:
    """Re-derive the per-refresh forecasts from frames only (no intel)."""
    hist: dict[str, list[str]] = {}
    acc: dict[str, list[float]] = {}
    last_nr: dict[str, float | None] = {}
    out = []
    for row in conn.execute_stream(
            "SELECT tick, world, json FROM frames WHERE run_id=? AND world<>'village' "
            "ORDER BY seq ASC", (run_id,)):
        raw = row["json"]
        raw = raw.encode("latin-1") if isinstance(raw, str) else raw
        try:
            f = protocol.decode(raw)
        except Exception:
            continue
        world = row["world"]
        nf = mlfeat.normalize_frame(f)
        mobs = nf["mobs"]
        undead = sum(1 for m in mobs if m["kind"] in THREAT_KINDS)
        melee = sum(1 for m in mobs
                    if m["kind"] not in THREAT_KINDS and m["kind"] not in WILDLIFE_SAFE)
        nr = (f.get("next_refresh") or {}).get("in_ticks")
        a = acc.setdefault(world, [0.0, 0.0, 0.0])
        prev_nr = last_nr.get(world)
        if prev_nr is not None and nr is not None and nr > prev_nr + 1:
            # refresh boundary: classify the ended window, roll history, forecast
            if a[2]:
                cls = mlfeat.band_danger_class(a[0] / a[2], a[1] / a[2])
                h = hist.setdefault(world, [])
                h.insert(0, cls)
                del h[4:]
            acc[world] = [0.0, 0.0, 0.0]
            fc = models.score_band(
                mlfeat.band_features(world, hist.get(world, []), 0))
            if fc is not None:
                out.append({"tick": row["tick"], "world": world,
                            "history": list(hist.get(world, [])),
                            "forecast": {k: round(v, 4) for k, v in fc.items()}})
        a = acc[world]
        a[0] += (undead / len(mobs)) if mobs else 0.0
        a[1] += float(melee)
        a[2] += 1
        last_nr[world] = nr
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None)
    ap.add_argument("--run", type=int, default=None)
    a = ap.parse_args(argv)
    conn = db.connect(db.load_db_config(a.db), readonly=True)
    rid = a.run or conn.execute(
        "SELECT MAX(run_id) FROM runs WHERE stopped_at IS NOT NULL").fetchone()[0]
    logged = []
    for row in conn.execute(
            "SELECT tick, payload_json FROM intel WHERE kind='model_score' "
            "ORDER BY seq ASC").fetchall():
        d = json.loads(row["payload_json"])
        if d.get("model") == "band_forecast":
            logged.append({"tick": row["tick"], **d})
    # scope logged rows to this run's tick range
    lo, hi = conn.execute(
        "SELECT MIN(tick), MAX(tick) FROM frames WHERE run_id=?", (rid,)).fetchone()
    logged = [l for l in logged if lo <= l["tick"] <= hi]
    if not logged:
        print(f"[parity] run {rid}: no logged forecasts in range — nothing to check")
        return 2
    recomputed = {(r["tick"], r["world"]): r for r in replay_band_scores(conn, rid)}
    bad = 0
    matched = 0
    for l in logged:
        key = (l["tick"], l["world"])
        r = recomputed.get(key)
        if r is None:
            # live boundary detection and replay boundary detection can differ by the
            # frame-arrival tick; accept a neighbour within 2 ticks
            near = [v for (t, w), v in recomputed.items()
                    if w == l["world"] and abs(t - l["tick"]) <= 2]
            r = near[0] if near else None
        if r is None:
            bad += 1
            if bad <= 3:
                print(f"[parity] MISSING recompute for {key}")
            continue
        diffs = [abs(r["forecast"].get(k, 0) - v) for k, v in l["forecast"].items()]
        if max(diffs) > TOL or r["history"] != l["history"]:
            bad += 1
            if bad <= 3:
                print(f"[parity] DIVERGED at {key}: live={l['forecast']} "
                      f"replay={r['forecast']} hist {l['history']} vs {r['history']}")
        else:
            matched += 1
    print(f"[parity] run {rid}: {matched} matched, {bad} diverged/missing "
          f"of {len(logged)} logged")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
