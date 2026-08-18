"""Persisting and summarising web-API intel (see steemer/web.py).

The ``intel`` table is a time series of HTTP-API observations the ZeroMQ frames
don't carry: ``kind='spectate'`` rows are the whole-world roster (our allies and
the rival guilds), ``kind='tiles'`` is the world's tile vocabulary. The web
sidecar writes them; the analysis loop reads the latest via
:func:`summarize_spectate`, which turns a raw response into the compact,
comparison-ready shape the analyst actually reasons over (our size vs rivals,
level distributions, gear adoption)."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any

from . import db as _db


def record(conn: "_db.Connection", kind: str, tick: int | None,
           observed_at: float, obj: Any) -> None:
    """Append one observation. ``obj`` is stored as JSON text."""
    conn.execute(
        "INSERT INTO intel(observed_at, tick, kind, payload_json) VALUES(?,?,?,?)",
        (observed_at, tick, kind, json.dumps(obj)))
    conn.commit()


def latest(conn: "_db.Connection", kind: str) -> dict[str, Any] | None:
    """The most recent observation of ``kind`` as ``{observed_at, tick, data}``,
    or ``None`` if there is none yet."""
    row = conn.execute(
        "SELECT observed_at, tick, payload_json FROM intel WHERE kind=? "
        "ORDER BY seq DESC LIMIT 1", (kind,)).fetchone()
    if not row:
        return None
    try:
        data = json.loads(row[2])
    except (ValueError, TypeError):
        return None
    return {"observed_at": row[0], "tick": row[1], "data": data}


def _guild_summary(guild: dict[str, Any]) -> dict[str, Any]:
    roster = guild.get("roster", []) or []
    by_world = Counter(c.get("world") for c in roster if c.get("world"))
    levels = [c.get("level") for c in roster if isinstance(c.get("level"), int)]
    armed = sum(1 for c in roster if (c.get("equipment") or {}).get("hand"))
    armored = sum(1 for c in roster if (c.get("equipment") or {}).get("outfit"))
    total = guild.get("characters")
    if not isinstance(total, int):
        total = len(roster)
    return {
        "guild_id": guild.get("guild_id"),
        "name": guild.get("name"),
        "characters": total,
        "by_world": dict(by_world),
        "levels": ({"min": min(levels), "max": max(levels),
                    "mean": round(sum(levels) / len(levels), 1)} if levels else None),
        "level_hist": dict(sorted(Counter(levels).items())),
        "armed": armed, "armored": armored,
    }


def summarize_spectate(data: dict[str, Any],
                       our_guild_id: str | None = None) -> dict[str, Any]:
    """Turn a raw ``/api/spectate/guilds`` response into a compact comparison:
    per-guild size / world spread / level distribution / gear, split into ``us``
    and ``rivals``, with a couple of head-to-head deltas the analyst can act on."""
    guilds = data.get("guilds", []) or []
    summaries = [_guild_summary(g) for g in guilds]
    us = next((s for s in summaries if s["guild_id"] == our_guild_id), None)
    rivals = [s for s in summaries if s is not us]
    out: dict[str, Any] = {
        "tick": data.get("tick"),
        "maps": [{"id": m.get("id"), "name": m.get("name"),
                  "size": [m.get("width"), m.get("height")]}
                 for m in (data.get("maps", []) or [])],
        "guild_count": len(summaries),
        "us": us, "rivals": rivals,
    }
    if us and rivals:
        biggest = max(rivals, key=lambda r: r["characters"])
        out["vs_biggest_rival"] = {
            "rival": biggest["name"],
            "roster_delta": us["characters"] - biggest["characters"],
            "max_level_delta": ((us["levels"] or {}).get("max", 0)
                                - (biggest["levels"] or {}).get("max", 0)),
        }
    return out
