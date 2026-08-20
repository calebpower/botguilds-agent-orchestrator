"""Learned bestiary — behavioral analysis of the mobs we share the worlds with
(wishlist item, "Behavioral analysis of mobs and rival players", part (a)).

Read-only over the frames mirror; never touches the live strategy. It answers the
question the strategy currently hard-codes a guess for — *does this mob chase a
character, or sit still?* — by measuring it from what we already log. Every field
frame carries `visible.entities` where each monster has a STABLE ``eid`` and a
``hit`` flag, so an individual mob can be followed tick-to-tick and its behaviour
inferred without any guesswork about identity.

Per mob-kind it infers:

* **movement cadence** (``move_rate``) — how often it actually moves.
* **chaser vs stationary** (``chaser_score`` + a ``behavior`` label) — of the moves
  it makes with a character in range, what fraction close the distance.
* **aggro range** — the furthest distance at which it was still seen closing in.
* **hit rate** and **damage per hit** — from the entity ``hit`` flag and a
  single-adjacent-mob-blame HP-drop attribution (same clean-attribution rule the
  death post-mortem uses).
* **dormant / elite fractions** and which **statuses** it tends to apply.

Two layers, split so the judgement is unit-testable without a database:

* :func:`build_bestiary` — PURE: given an ordered list of *normalised* frames, return
  ``{kind: profile}``. This is the whole aggregation + classification core.
* :func:`normalize_frame` — turn one decoded game frame into the normalised shape.
* :func:`analyze_run` — stream a run's field frames from the DB through both.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable

from steemer.strategy.explorer import WILDLIFE_SAFE

# Two observations of the same eid more than this many ticks apart are treated as
# "lost sight of and re-seen" — we do NOT infer a move across the gap.
MAX_GAP = 3
# A character must be within this manhattan distance for a mob's move to be scored
# as toward/away (outside it, the mob has no character to react to).
ENGAGE_VIS = 12
# Adjacency for clean HP-drop / status attribution.
ADJ = 1
# Directional samples needed before a chaser/flees label is trusted.
MIN_DIR_SAMPLES = 15
# Below this move_rate a mob reads as stationary/ambusher regardless of direction.
STATIONARY_MOVE_RATE = 0.15
# chaser_score thresholds.
CHASER_SCORE = 0.60
FLEE_SCORE = 0.30


def _manhattan(a, b) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _nearest_char(pos, char_positions):
    """(pos, dist) of the nearest character to ``pos``, or (None, None)."""
    best_p, best_d = None, None
    for cp in char_positions:
        d = _manhattan(pos, cp)
        if best_d is None or d < best_d:
            best_p, best_d = cp, d
    return best_p, best_d


def normalize_frame(decoded: dict[str, Any]) -> dict[str, Any]:
    """Extract the fields the bestiary needs from a decoded game frame. Village frames
    and anything without monsters normalise to empty mob/char lists (harmless)."""
    chars = []
    for c in decoded.get("chars") or []:
        pos = c.get("pos")
        if pos is None:
            continue
        chars.append({
            "id": c.get("char_uid") or c.get("eid"),
            "pos": (pos[0], pos[1]),
            "hp": c.get("hp"),
            "statuses": [s.get("kind") for s in (c.get("statuses") or []) if s.get("kind")],
        })
    mobs = []
    for e in (decoded.get("visible") or {}).get("entities") or []:
        if e.get("faction") != "monster":
            continue
        pos = e.get("pos")
        if pos is None or e.get("eid") is None or not e.get("kind"):
            continue
        mobs.append({
            "eid": e["eid"], "kind": e["kind"], "pos": (pos[0], pos[1]),
            "hp_frac": e.get("hp_frac"), "hit": bool(e.get("hit")),
            "dormant": bool(e.get("dormant")), "elite": bool(e.get("elite")),
            "statuses": [s.get("kind") if isinstance(s, dict) else s
                         for s in (e.get("statuses") or [])],
        })
    return {"world": decoded.get("world"), "tick": decoded.get("tick"),
            "chars": chars, "mobs": mobs}


def _blank():
    return {"sightings": 0, "individuals": set(), "move_pairs": 0, "moves": 0,
            "toward": 0, "away": 0, "lateral": 0, "aggro_max": 0,
            "hits": 0, "dmg_sum": 0, "dmg_n": 0, "dormant": 0, "elite": 0,
            "status_applied": Counter()}


def _classify(move_rate, chaser_score, dir_samples) -> str:
    """Label a mob's movement behaviour from its measured rates."""
    if move_rate is not None and move_rate < STATIONARY_MOVE_RATE:
        return "stationary"        # barely moves — an ambusher / turret
    if dir_samples < MIN_DIR_SAMPLES or chaser_score is None:
        return "insufficient_data"  # it moves, but never near a character enough to tell
    if chaser_score >= CHASER_SCORE:
        return "chaser"            # closes on characters — the dangerous kind
    if chaser_score <= FLEE_SCORE:
        return "skittish"          # moves away from characters
    return "wanderer"              # moves, but not in reaction to characters


def build_bestiary(frames: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """PURE aggregation core. ``frames`` is an ordered iterable of normalised frames
    (see :func:`normalize_frame`). Returns ``{kind: profile}``.

    An individual mob is followed by its ``eid`` across consecutive frames (same world,
    gap <= MAX_GAP); each move is scored toward/away/lateral relative to the character
    that was nearest when the mob was last seen. HP drops and new statuses are blamed
    on a mob only when it is the *sole* hostile adjacent (clean attribution).
    """
    prof: dict[str, dict[str, Any]] = defaultdict(_blank)
    last: dict[Any, dict[str, Any]] = {}          # eid -> prev observation
    chp: dict[Any, dict[str, Any]] = {}           # char id -> prev {tick, hp, statuses}

    for fr in frames:
        world, tick = fr.get("world"), fr.get("tick")
        mobs = fr.get("mobs") or []
        char_positions = [c["pos"] for c in fr.get("chars") or []]

        for m in mobs:
            kind, eid, pos = m["kind"], m["eid"], m["pos"]
            p = prof[kind]
            p["sightings"] += 1
            p["individuals"].add(eid)
            if m["hit"]:
                p["hits"] += 1
            if m["dormant"]:
                p["dormant"] += 1
            if m["elite"]:
                p["elite"] += 1

            ncpos, ncdist = _nearest_char(pos, char_positions)
            prev = last.get(eid)
            if prev is not None and prev["world"] == world \
                    and tick is not None and 0 < (tick - prev["tick"]) <= MAX_GAP:
                p["move_pairs"] += 1
                if pos != prev["pos"]:
                    p["moves"] += 1
                    # score the move against the char the mob was nearest to last time
                    if prev["ncpos"] is not None and prev["ncdist"] is not None \
                            and prev["ncdist"] <= ENGAGE_VIS:
                        newd = _manhattan(pos, prev["ncpos"])
                        if newd < prev["ncdist"]:
                            p["toward"] += 1
                            p["aggro_max"] = max(p["aggro_max"], prev["ncdist"])
                        elif newd > prev["ncdist"]:
                            p["away"] += 1
                        else:
                            p["lateral"] += 1
            last[eid] = {"world": world, "tick": tick, "pos": pos,
                         "ncpos": ncpos, "ncdist": ncdist}

        # HP-drop + new-status attribution: only when exactly one hostile mob is
        # adjacent to the character, so the blame is unambiguous.
        for c in fr.get("chars") or []:
            cid, cpos, hp = c["id"], c["pos"], c.get("hp")
            prevc = chp.get(cid)
            adj = [m for m in mobs
                   if m["kind"] not in WILDLIFE_SAFE and _manhattan(m["pos"], cpos) <= ADJ]
            if prevc is not None and len(adj) == 1:
                only = adj[0]["kind"]
                if hp is not None and prevc.get("hp") is not None and hp < prevc["hp"]:
                    prof[only]["dmg_sum"] += prevc["hp"] - hp
                    prof[only]["dmg_n"] += 1
                new_status = set(c.get("statuses") or []) - set(prevc.get("statuses") or [])
                for s in new_status:
                    prof[only]["status_applied"][s] += 1
            chp[cid] = {"tick": tick, "hp": hp, "statuses": c.get("statuses") or []}

    return {kind: _finalize(p) for kind, p in prof.items()}


def _finalize(p: dict[str, Any]) -> dict[str, Any]:
    dir_samples = p["toward"] + p["away"] + p["lateral"]
    move_rate = (p["moves"] / p["move_pairs"]) if p["move_pairs"] else None
    chaser_score = (p["toward"] / dir_samples) if dir_samples else None
    return {
        "sightings": p["sightings"],
        "individuals": len(p["individuals"]),
        "move_rate": round(move_rate, 3) if move_rate is not None else None,
        "chaser_score": round(chaser_score, 3) if chaser_score is not None else None,
        "dir_samples": dir_samples,
        "aggro_range": p["aggro_max"] or None,
        "hit_rate": round(p["hits"] / p["sightings"], 3) if p["sightings"] else None,
        "est_dmg_per_hit": round(p["dmg_sum"] / p["dmg_n"], 1) if p["dmg_n"] else None,
        "dmg_samples": p["dmg_n"],
        "dormant_frac": round(p["dormant"] / p["sightings"], 3) if p["sightings"] else None,
        "elite_frac": round(p["elite"] / p["sightings"], 3) if p["sightings"] else None,
        "status_applied": dict(p["status_applied"].most_common()),
        "behavior": _classify(move_rate, chaser_score, dir_samples),
    }


def analyze_run(conn, run_id, world=None, limit=None):
    """Build the bestiary for one run from the DB mirror. Streams the field frames in
    order (optionally one ``world``), normalises each, and aggregates. Returns
    ``{run_id, frames, kinds: {kind: profile}}`` sorted by sightings."""
    from steemer import protocol
    q = ("SELECT tick, json FROM frames WHERE run_id=%s AND world<>'village' "
         + ("AND world=%s " if world else "")
         + "ORDER BY seq ASC" + (" LIMIT %s" if limit else ""))
    params = [run_id] + ([world] if world else []) + ([limit] if limit else [])
    normed = []
    for row in conn.execute(q, tuple(params)).fetchall():
        raw = row["json"]
        raw = raw.encode("latin-1") if isinstance(raw, str) else raw
        try:
            normed.append(normalize_frame(protocol.decode(raw)))
        except Exception:
            continue
    kinds = build_bestiary(normed)
    kinds = dict(sorted(kinds.items(), key=lambda kv: kv[1]["sightings"], reverse=True))
    return {"run_id": run_id, "frames": len(normed), "kinds": kinds}


if __name__ == "__main__":       # pragma: no cover - thin CLI wrapper
    import argparse
    import json as _json
    from steemer import db
    ap = argparse.ArgumentParser(description="Learned mob bestiary for a run")
    ap.add_argument("--run", type=int, default=None, help="run_id (default: latest)")
    ap.add_argument("--world", default=None, help="restrict to one world")
    args = ap.parse_args()
    conn = db.connect(db.load_db_config())
    rid = args.run
    if rid is None:
        rid = conn.execute("SELECT MAX(run_id) m FROM frames").fetchone()["m"]
    print(_json.dumps(analyze_run(conn, rid, world=args.world), indent=2, default=str))
