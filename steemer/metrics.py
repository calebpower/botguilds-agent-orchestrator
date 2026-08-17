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
import sqlite3
import zlib
from typing import Any


def _ro(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _counts(conn: sqlite3.Connection, table: str, group: str, limit: int = 20) -> dict[str, int]:
    rows = conn.execute(
        f"SELECT {group} AS k, COUNT(*) AS n FROM {table} "
        f"GROUP BY {group} ORDER BY n DESC LIMIT {int(limit)}"
    ).fetchall()
    return {("" if r["k"] is None else str(r["k"])): r["n"] for r in rows}


def _scalar(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> Any:
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def _latest_frame(conn: sqlite3.Connection, world: str | None = None) -> dict[str, Any] | None:
    sql = "SELECT json FROM frames"
    params: tuple = ()
    if world:
        sql += " WHERE world=?"
        params = (world,)
    sql += " ORDER BY seq DESC LIMIT 1"
    row = conn.execute(sql, params).fetchone()
    return json.loads(zlib.decompress(row[0])) if row else None


def snapshot(db_path: str) -> dict[str, Any]:
    """A single JSON-serializable KPI snapshot for the analysis loop."""
    conn = _ro(db_path)
    try:
        out: dict[str, Any] = {"db": db_path}

        # -- volume + span ---------------------------------------------------
        tick_min = _scalar(conn, "SELECT MIN(tick) FROM frames")
        tick_max = _scalar(conn, "SELECT MAX(tick) FROM frames")
        t_first = _scalar(conn, "SELECT MIN(received_at) FROM frames")
        t_last = _scalar(conn, "SELECT MAX(received_at) FROM frames")
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

        # -- per-run windows (for before/after attribution) ------------------
        out["runs"] = _run_summaries(conn)
        return out
    finally:
        conn.close()


def _run_summaries(conn: sqlite3.Connection) -> list[dict[str, Any]]:
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


def _run_gold_delta(conn: sqlite3.Connection, run_id: int) -> int | None:
    """First vs last observed guild gold within a run (village frames only)."""
    rows = conn.execute(
        "SELECT json FROM frames WHERE run_id=? AND world='village' "
        "ORDER BY seq", (run_id,)).fetchall()
    golds = []
    for (blob,) in rows:
        g = json.loads(zlib.decompress(blob)).get("guild", {}).get("gold")
        if g is not None:
            golds.append(g)
    if len(golds) < 2:
        return None
    return golds[-1] - golds[0]
