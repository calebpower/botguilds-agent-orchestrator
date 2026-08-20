"""Death post-mortem taxonomy (wishlist item, shipped 2026-08-20).

Turns every character death into a structured cause-of-death record — the thing the
improvement loop reconstructs BY HAND on every measurement pass (HP-drop blame, death
traces). Read-only over the frames/events mirror; never touches the live strategy.

Two layers, split so the judgement is unit-testable without a database:

* :func:`classify_death` — PURE: given a reconstructed per-tick trace of a dying char,
  return {killer, cause, mobility, killing_blow}. This is the core taxonomy.
* :func:`reconstruct_trace` — read a death's last ~N ticks from the DB.
* :func:`analyze_run` — every death in a run, classified, plus a summary breakdown.

The predator classification is shared with the live bot (WILDLIFE_SAFE / THREAT_KINDS
imported from the strategy) so the post-mortem blames a death the same way the bot
decides to flee it — one source of truth for the bestiary.
"""
from __future__ import annotations

from collections import Counter
from typing import Any

from steemer.strategy.explorer import WILDLIFE_SAFE, THREAT_KINDS

# A "big" single-tick HP drop — a melee burst rather than DoT chip.
BURST_DROP = 8
# How many ticks of no movement at the end reads as "stuck" (couldn't flee).
STUCK_TICKS = 3


def _nearest_hostile(pos, ents):
    """(kind, manhattan_dist) of the nearest non-benign monster to ``pos`` within the
    entity list, or None. Benign wildlife is ignored — it doesn't kill."""
    best = None
    for kind, epos in ents:
        if not kind or kind in WILDLIFE_SAFE or not epos:
            continue
        d = abs(epos[0] - pos[0]) + abs(epos[1] - pos[1])
        if best is None or d < best[1]:
            best = (kind, d)
    return best


def classify_death(trace: list[dict[str, Any]]) -> dict[str, Any]:
    """Classify one death from its per-tick trace (oldest first). Each tick is
    ``{"tick": int, "hp": int|None, "pos": (x, y)|None, "ents": [(kind, (x, y)), ...]}``.

    Returns ``{killer, killer_dist, cause, mobility, killing_blow, hp_from, hp_to}``:
    * ``cause``: ``melee_burst`` (a big single-tick drop with a hostile adjacent),
      ``undead_dot`` (an undead was the nearest hostile — poison/burn chip),
      ``dot_bleed`` (steady HP loss with NO hostile adjacent — environmental/poison),
      or ``unknown``.
    * ``mobility``: ``stuck`` (no movement over the last STUCK_TICKS) or ``fleeing``.
    * ``killer``: the nearest hostile kind at the killing blow (or None).
    """
    hp_pts = [(i, t) for i, t in enumerate(trace) if t.get("hp") is not None]
    out: dict[str, Any] = {"killer": None, "killer_dist": None, "cause": "unknown",
                           "mobility": "unknown", "killing_blow": 0,
                           "hp_from": None, "hp_to": None}
    if len(hp_pts) < 2:
        return out

    # killing blow = the largest single-step HP drop across the trace.
    worst_i, worst_drop = None, 0
    for (ai, a), (bi, b) in zip(hp_pts, hp_pts[1:]):
        drop = (a["hp"] or 0) - (b["hp"] or 0)
        if drop > worst_drop:
            worst_drop, worst_i = drop, bi
    if worst_i is None:
        return out
    out["killing_blow"] = worst_drop
    out["hp_from"] = trace[worst_i - 1].get("hp") if worst_i > 0 else None
    out["hp_to"] = trace[worst_i].get("hp")

    # who was nearest at the blow (use the tick BEFORE the drop registered — that's
    # where the attacker stood when it hit).
    blow_tick = trace[max(0, worst_i - 1)]
    near = _nearest_hostile(blow_tick.get("pos") or (0, 0), blow_tick.get("ents") or [])
    if near:
        out["killer"], out["killer_dist"] = near[0], near[1]

    # cause taxonomy
    adjacent_hostile = near is not None and near[1] <= 1
    if adjacent_hostile and worst_drop >= BURST_DROP:
        out["cause"] = "melee_burst"
    elif near is not None and near[0] in THREAT_KINDS:
        out["cause"] = "undead_dot"
    elif near is None or near[1] > 2:
        out["cause"] = "dot_bleed"      # steady loss, nothing hostile close = DoT
    else:
        out["cause"] = "unknown"

    # mobility: did the char move in the last STUCK_TICKS positioned ticks?
    poss = [t["pos"] for t in trace if t.get("pos")]
    tail = poss[-STUCK_TICKS:]
    out["mobility"] = "stuck" if len(tail) >= 2 and len(set(map(tuple, tail))) == 1 else "fleeing"
    return out


def reconstruct_trace(conn, run_id, char_uid, death_tick, window=15):
    """Read a dying char's last ``window`` ticks of field frames from the DB into the
    per-tick trace :func:`classify_death` expects (oldest first)."""
    from steemer import protocol
    trace: list[dict[str, Any]] = []
    rows = conn.execute(
        "SELECT tick, json FROM frames WHERE run_id=%s AND world<>'village' "
        "AND tick BETWEEN %s AND %s ORDER BY tick ASC", (run_id, death_tick - window, death_tick)
    ).fetchall()
    for row in rows:
        raw = row["json"]
        raw = raw.encode("latin-1") if isinstance(raw, str) else raw
        try:
            f = protocol.decode(raw)
        except Exception:
            continue
        me = next((c for c in f.get("chars", []) if c.get("char_uid") == char_uid), None)
        if not me:
            continue
        ents = [(e.get("kind"), e.get("pos"))
                for e in (f.get("visible") or {}).get("entities") or []
                if e.get("pos") and e.get("kind") != "char"
                and not str(e.get("kind")).startswith("g_")]
        trace.append({"tick": row["tick"], "hp": me.get("hp"),
                      "pos": tuple(me["pos"]) if me.get("pos") else None, "ents": ents})
    return trace


def analyze_run(conn, run_id, our_guild_id="g_cd0e2a", limit=None):
    """Classify every death in a run. Returns ``{deaths: [...], summary: {...}}`` with
    breakdowns by cause / killer / world / mobility."""
    import json as _json
    q = ("SELECT tick, payload_json FROM events WHERE run_id=%s AND kind='death' "
         "ORDER BY tick ASC")
    rows = conn.execute(q, (run_id,)).fetchall()
    deaths: list[dict[str, Any]] = []
    for row in (rows[:limit] if limit else rows):
        p = row["payload_json"]
        p = _json.loads(p) if isinstance(p, str) else p
        uid = p.get("char_uid")
        if not uid or (p.get("guild_id") and p.get("guild_id") != our_guild_id):
            continue
        trace = reconstruct_trace(conn, run_id, uid, row["tick"])
        rec = classify_death(trace)
        rec.update({"char_uid": uid, "tick": row["tick"], "pos": p.get("pos")})
        deaths.append(rec)
    summary = {
        "total": len(deaths),
        "by_cause": dict(Counter(d["cause"] for d in deaths).most_common()),
        "by_killer": dict(Counter(d["killer"] for d in deaths if d["killer"]).most_common()),
        "by_mobility": dict(Counter(d["mobility"] for d in deaths).most_common()),
    }
    return {"deaths": deaths, "summary": summary}
