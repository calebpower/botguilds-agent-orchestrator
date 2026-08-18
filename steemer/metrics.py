"""Derive KPIs from the raw mirror — the signal the improvement loop reads.

Everything here is read-only and opens its own connection, so it is safe to run
against a live ``guild_log.db`` while the bot is writing (WAL). It leans on SQL
aggregates for the cheap flattened tables and only decompresses the most recent
village/map frames for point-in-time state (gold, roster, depth).

Deliberately content-agnostic: event kinds, item kinds and enemies are things
the game does not document, so KPIs are computed by *grouping over whatever
occurred* rather than by hard-coding names. The analysis loop interprets them.
"""

from __future__ import annotations

import json
import time
import zlib
from typing import Any

from . import db as _db


def _ro(db: Any) -> _db.Connection:
    """Read-only connection to either backend (Row-style name access)."""
    return _db.connect(db, readonly=True)


def _counts(conn: _db.Connection, table: str, group: str, limit: int = 20) -> dict[str, int]:
    rows = conn.execute(
        f"SELECT {group} AS k, COUNT(*) AS n FROM {table} "
        f"GROUP BY {group} ORDER BY n DESC LIMIT {int(limit)}"
    ).fetchall()
    return {("" if r["k"] is None else str(r["k"])): r["n"] for r in rows}


def _scalar(conn: _db.Connection, sql: str, params: tuple = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def _latest_frame(conn: _db.Connection, world: str | None = None) -> dict[str, Any] | None:
    sql = "SELECT json FROM frames"
    params: tuple = ()
    if world:
        sql += " WHERE world=?"
        params = (world,)
    sql += " ORDER BY seq DESC LIMIT 1"
    row = conn.execute(sql, params).fetchone()
    return json.loads(zlib.decompress(row[0])) if row else None


def _roster_inventory(conn: _db.Connection, recent_village: int = 40) -> dict[str, Any] | None:
    """Roster detail + recent swing range + aggregate inventory, from the latest
    village frames. The single-frame roster (``chars_here`` + ``chars_by_world``)
    is a PARTIAL, swinging view of a large persistent roster — the server shows
    chars intermittently (see findings.jsonl) — so alongside the current numbers
    we return the recent min/max range and the frame's age, so the dashboard can
    show a dip as a transient partial view rather than a bare, misleading count.
    Inventory is aggregated across every home char in the latest village frame."""
    rows = conn.execute(
        "SELECT json, received_at FROM frames WHERE world='village' "
        "ORDER BY seq DESC LIMIT ?", (int(recent_village),)).fetchall()
    if not rows:
        return None
    latest = json.loads(zlib.decompress(rows[0][0]))
    g = latest.get("guild", {}) or {}
    here = len(g.get("chars_here", []) or [])
    by_world = {k: len(v) for k, v in (g.get("chars_by_world", {}) or {}).items()}
    total = here + sum(by_world.values())

    totals = []
    for row in rows:
        gg = json.loads(zlib.decompress(row[0])).get("guild", {}) or {}
        totals.append(len(gg.get("chars_here", []) or [])
                      + sum(len(v) for v in (gg.get("chars_by_world", {}) or {}).values()))

    inv: dict[str, int] = {}
    for ch in latest.get("chars", []) or []:
        for it in ch.get("inventory", []) or []:
            k = it.get("kind")
            if k:
                inv[k] = inv.get(k, 0) + 1

    age = None
    try:
        age = round(time.time() - float(rows[0]["received_at"]), 1)
    except (TypeError, ValueError, KeyError):
        pass
    return {
        "home": here, "by_world": by_world, "total": total,
        "range": {"min": min(totals), "max": max(totals), "samples": len(totals)},
        "frame_age_s": age, "at_tick": latest.get("tick"),
        "inventory": dict(sorted(inv.items(), key=lambda kv: -kv[1])),
        "note": "server shows chars intermittently; this is a partial view of a "
                "larger persistent roster (see range).",
    }


def snapshot(db: Any = None) -> dict[str, Any]:
    """A single JSON-serializable KPI snapshot for the analysis loop.

    ``db`` is a config dict, a SQLite path, or None to resolve from config."""
    cfg = _db.normalize(db)
    conn = _ro(cfg)
    try:
        out: dict[str, Any] = {"db": _db.cfg_key(cfg)}

        # -- volume + span ---------------------------------------------------
        tick_min = _scalar(conn, "SELECT MIN(tick) FROM frames")
        tick_max = _scalar(conn, "SELECT MAX(tick) FROM frames")
        # wall span = first vs last frame's received_at. `received_at` is unindexed,
        # so MIN()/MAX() over it FULL-SCAN the frames table (~19 s each = ~38 s, the
        # bulk of a live-MariaDB snapshot). It is written monotonically with the
        # autoincrement `seq` PK, so the earliest/latest frame are the min/max seq —
        # fetch received_at by seq order (an index-only PK lookup, instant).
        t_first = _scalar(conn, "SELECT received_at FROM frames ORDER BY seq ASC LIMIT 1")
        t_last = _scalar(conn, "SELECT received_at FROM frames ORDER BY seq DESC LIMIT 1")
        wall_s = (t_last - t_first) if (t_first and t_last) else 0.0
        out["volume"] = {
            "frames": _scalar(conn, "SELECT COUNT(*) FROM frames") or 0,
            "events": _scalar(conn, "SELECT COUNT(*) FROM events") or 0,
            "actions_sent": _scalar(conn, "SELECT COUNT(*) FROM actions_sent") or 0,
            "action_errors": _scalar(conn, "SELECT COUNT(*) FROM action_errors") or 0,
            "decisions": _scalar(conn, "SELECT COUNT(*) FROM decisions") or 0,
            "tick_span": [tick_min, tick_max],
            "wall_seconds": round(wall_s, 1),
        }

        # -- behaviour breakdowns -------------------------------------------
        out["events_by_kind"] = _counts(conn, "events", "kind")
        out["actions_by_kind"] = _counts(conn, "actions_sent", "action")
        out["decisions_by_action"] = _counts(conn, "decisions", "action")
        out["action_errors_by_reason"] = _counts(conn, "action_errors", "reason")

        # error rate: a rising rate usually means the strategy is asking for
        # things it can't afford / reach — a cheap, content-free health signal.
        sent = out["volume"]["actions_sent"]
        errs = out["volume"]["action_errors"]
        out["action_error_rate"] = round(errs / sent, 3) if sent else None

        # -- exploration (a first-objective KPI) -----------------------------
        expl = {}
        for (world,) in conn.execute("SELECT DISTINCT world FROM tiles_seen"):
            tiles = _scalar(conn, "SELECT COUNT(*) FROM tiles_seen WHERE world=?", (world,))
            max_y = _scalar(conn, "SELECT MAX(y) FROM tiles_seen WHERE world=?", (world,))
            non_floor = _scalar(
                conn,
                "SELECT COUNT(*) FROM tiles_seen WHERE world=? AND kind NOT IN ('floor','wall')",
                (world,))
            expl[world] = {"tiles_seen": tiles, "max_y_reached": max_y,
                           "notable_tiles": non_floor}
        out["exploration"] = expl

        # -- current state (latest frames) ----------------------------------
        village = _latest_frame(conn, "village")
        if village:
            g = village.get("guild", {})
            out["current"] = {
                "gold": g.get("gold"),
                "chars_here": len(g.get("chars_here", [])),
                "chars_by_world": {k: len(v) for k, v in g.get("chars_by_world", {}).items()},
                "market_listings": len(g.get("market_listings", [])),
                "at_tick": village.get("tick"),
            }

        # Roster detail + swing range + aggregate inventory (dashboard panel).
        out["roster"] = _roster_inventory(conn)

        # Recent bot-detected anomalies (self-reported error-family spikes etc.).
        out["anomalies_recent"] = [
            {"tick": r["tick"], "subtype": r["k"], "n": r["n"]}
            for r in conn.execute(
                "SELECT tick, world AS k, COUNT(*) AS n FROM events "
                "WHERE kind='bot_anomaly' GROUP BY world ORDER BY MAX(tick) DESC LIMIT 8"
            ).fetchall()
        ]

        # -- per-run windows (for before/after attribution) ------------------
        out["runs"] = _run_summaries(conn)
        return out
    finally:
        conn.close()


def _run_summaries(conn: _db.Connection) -> list[dict[str, Any]]:
    runs = conn.execute(
        "SELECT run_id, git_sha, strategy_version, started_at, stopped_at, note "
        "FROM runs ORDER BY run_id"
    ).fetchall()
    summaries = []
    for r in runs:
        rid = r["run_id"]
        frames = _scalar(conn, "SELECT COUNT(*) FROM frames WHERE run_id=?", (rid,)) or 0
        sent = _scalar(conn, "SELECT COUNT(*) FROM actions_sent WHERE run_id=?", (rid,)) or 0
        errs = _scalar(conn, "SELECT COUNT(*) FROM action_errors WHERE run_id=?", (rid,)) or 0
        # gold delta across the run, read from village frames tagged to it.
        gold = _run_gold_delta(conn, rid)
        summaries.append({
            "run_id": rid,
            "git_sha": r["git_sha"],
            "strategy_version": r["strategy_version"],
            "started_at": r["started_at"],
            "stopped_at": r["stopped_at"],
            "note": r["note"],
            "frames": frames,
            "actions_sent": sent,
            "action_error_rate": round(errs / sent, 3) if sent else None,
            "gold_delta": gold,
        })
    return summaries


def _run_gold_delta(conn: _db.Connection, run_id: int) -> int | None:
    """First vs last observed guild gold within a run (village frames only).

    Two steps, each genuinely O(1): first find the min/max village-frame ``seq``
    for the run (an index-only lookup on idx_frames_run_world_seq — "tables
    optimized away"), then fetch exactly those 1-2 rows by PRIMARY KEY.

    This must NOT be written as ``WHERE seq IN (SELECT MIN(seq) … UNION SELECT
    MAX(seq) …)``: MariaDB plans that as a *dependent* subquery re-checked per
    row, so the outer query degrades to a full index scan of every frame that
    decompresses each ~2.4 GB of blobs — minutes per snapshot, and it was the
    real bulk of the /api/snapshot cost. Computing the two seq values first and
    binding them as literals keeps the outer fetch a two-row PK lookup.
    """
    bounds = conn.execute(
        "SELECT MIN(seq), MAX(seq) FROM frames WHERE run_id=? AND world='village'",
        (run_id,)).fetchone()
    if not bounds or bounds[0] is None:
        return None
    lo, hi = bounds[0], bounds[1]
    seqs = (lo,) if lo == hi else (lo, hi)
    placeholders = ",".join(["?"] * len(seqs))
    rows = conn.execute(
        f"SELECT json FROM frames WHERE seq IN ({placeholders}) ORDER BY seq",
        seqs).fetchall()
    golds = []
    for (blob,) in rows:
        g = json.loads(zlib.decompress(blob)).get("guild", {}).get("gold")
        if g is not None:
            golds.append(g)
    if len(golds) < 2:
        return None
    return golds[-1] - golds[0]
