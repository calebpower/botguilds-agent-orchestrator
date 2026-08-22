"""Local persistence: the bot's own mirror of everything it saw and did.

One SQLite file (default ``guild_log.db``) holds four kinds of thing:

* the **raw mirror** — every frame (zlib-compressed JSON), plus flattened
  ``events`` / ``actions_sent`` / ``action_errors`` / ``tiles_seen`` for cheap
  SQL — so no query needs to decompress a frame;
* **decisions** — the verbose per-character reasoning behind each action (the
  "thinking" the UI surfaces and the analysis loop mines);
* **runs** — one row per bot version (git sha + strategy version) with a
  start/stop window, so metrics attribute to the version that produced them.

WAL mode + a generous busy timeout let the live writer coexist with read-only
readers (the web UI, the analysis subagent, ad-hoc queries). The server offers
no history export, so this file *is* the guild's accumulated knowledge.
"""

from __future__ import annotations

import json
import time
import zlib
from typing import Any, Iterable, Iterator

from . import db as _db
from .db import DEFAULT_DB  # re-exported: ui/server.py imports it from here

# The authoritative schema (both dialects) lives in steemer.db; Storage applies
# it via _db.apply_schema. The SQLite text is also exposed there as SCHEMA_SQLITE.


def _base_cell(base: Any) -> Any:
    """tiles_seen.base is an int for a single under-layer, or JSON for a stack."""
    return json.dumps(base) if isinstance(base, list) else base


class Storage:
    """The bot's SQLite mirror. One instance per process owns the connection."""

    def __init__(self, db: Any = None, *, commit_every: int = 20):
        # ``db`` is a config dict, a SQLite path string (e.g. ":memory:"), or
        # None to resolve from config.toml. The writer connection keeps default
        # (tuple) rows; read paths use their own read-only Row connections.
        self.conn = _db.connect(db)
        if self.conn.dialect == "sqlite":
            # WAL + NORMAL let the live writer coexist with read-only readers.
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.execute("PRAGMA synchronous=NORMAL")
        _db.apply_schema(self.conn)
        self.run_id: int | None = None
        self._commit_every = commit_every
        self._since_commit = 0

    # -- run/version windows --------------------------------------------------

    def begin_run(self, git_sha: str, strategy_version: str, note: str = "") -> int:
        now = time.time()
        # Defensive close: a prior runner that was hard-killed (e.g. superseded
        # during a hot-redeploy, before it could call end_run) leaves its window
        # open. Close any such dangling window so there is always exactly one
        # open run — otherwise per-run metric attribution silently double-counts.
        self.conn.execute(
            "UPDATE runs SET stopped_at=? WHERE stopped_at IS NULL", (now,))
        cur = self.conn.execute(
            "INSERT INTO runs(git_sha, strategy_version, started_at, note) "
            "VALUES(?,?,?,?)",
            (git_sha, strategy_version, now, note),
        )
        self.conn.commit()
        self.run_id = cur.lastrowid
        return self.run_id

    def end_run(self) -> None:
        if self.run_id is not None:
            self.conn.execute(
                "UPDATE runs SET stopped_at=? WHERE run_id=?",
                (time.time(), self.run_id),
            )
            self.conn.commit()

    # -- raw mirror -----------------------------------------------------------

    def record_frame(self, frame: dict[str, Any]) -> None:
        world = frame.get("world")
        tick = frame.get("tick")
        self.conn.execute(
            "INSERT INTO frames(tick, world, received_at, run_id, json) VALUES(?,?,?,?,?)",
            (tick, world, time.time(), self.run_id,
             zlib.compress(json.dumps(frame).encode("utf-8"))),
        )
        events = frame.get("events") or []
        if events:
            self.conn.executemany(
                "INSERT INTO events(tick, world, kind, payload_json, run_id) "
                "VALUES(?,?,?,?,?)",
                [(tick, world, e.get("kind"), json.dumps(e), self.run_id)
                 for e in events],
            )
        tiles = (frame.get("visible") or {}).get("tiles") or []
        if tiles:
            self.conn.executemany(
                _db.tiles_seen_upsert(self.conn.dialect),
                [(world, t[0], t[1], t[2],
                  t[3] if len(t) > 3 else 0, tick,
                  _base_cell(t[4]) if len(t) > 4 else 0) for t in tiles],
            )
        self._tick_commit()

    def load_known_tiles(self) -> dict[str, dict[tuple[int, int], str]]:
        """Every tile we have ever seen, as ``{world: {(x, y): kind}}``.

        The counterpart to the ``tiles_seen`` upsert above, which had no reader: the map
        was written on every frame and never once read back, so each redeploy started
        map-blind and re-learned ground it already knew. We redeploy several times a day.

        Deliberately returns kinds only, with no recency filter. The map is a HINT, not an
        authority — a live frame overwrites any tile the moment a character sees it, and a
        remembered tile that has since changed costs at most one bounced move, which
        v0.50.0's server-driven learned-block already absorbs. Filtering by ``last_tick``
        would trade that bounded, self-correcting cost for the unbounded one of not knowing
        the map at all.
        """
        out: dict[str, dict[tuple[int, int], str]] = {}
        cur = self.conn.execute("SELECT world, x, y, kind FROM tiles_seen")
        for world, x, y, kind in cur.fetchall():
            out.setdefault(world, {})[(int(x), int(y))] = kind
        return out

    def record_learned(self, topic: str, fact: str) -> None:
        """Persist one PROVEN fact the strategy worked out in play.

        Idempotent by primary key, so re-proving costs nothing. Positive facts only -- see
        the note on the `learned` table: a persisted FAILURE would carry a wrong belief
        across every future run, and `wrong_materials` has already been shown to be
        unreliable."""
        sql = ("INSERT INTO learned(topic, fact, proved_at) VALUES(?,?,?) "
               "ON CONFLICT(topic, fact) DO NOTHING" if self.conn.dialect == "sqlite"
               else "INSERT IGNORE INTO learned(topic, fact, proved_at) VALUES(?,?,?)")
        self.conn.execute(sql, (topic, fact, time.time()))
        self._tick_commit()

    def load_learned(self, topic: str) -> set[str]:
        """Every fact proven for a topic, across all previous runs."""
        cur = self.conn.execute("SELECT fact FROM learned WHERE topic=?", (topic,))
        return {r[0] for r in cur.fetchall()}

    def record_actions(self, tick: int, actions: Iterable[dict[str, Any]]) -> None:
        rows = [(tick, a.get("char_uid"), a.get("action"), json.dumps(a), self.run_id)
                for a in actions]
        if rows:
            self.conn.executemany(
                "INSERT INTO actions_sent(tick, char_uid, action, payload_json, run_id) "
                "VALUES(?,?,?,?,?)", rows)
            self._tick_commit()

    def record_error(self, message: dict[str, Any]) -> None:
        self.conn.execute(
            "INSERT INTO action_errors(tick, char_uid, action, reason, run_id) "
            "VALUES(?,?,?,?,?)",
            (message.get("tick"), message.get("char_uid"),
             message.get("action"), message.get("reason"), self.run_id))
        self._tick_commit()

    def record_anomaly(self, tick: int, subtype: str, detail: dict[str, Any]) -> None:
        """Persist a bot-detected anomaly as an ``events`` row with a distinct
        ``bot_anomaly`` kind (so it is queryable/analysable and never confused
        with a server-emitted game event). ``world`` carries the subtype for a
        cheap GROUP BY; the full payload is in ``payload_json``."""
        payload = {"kind": "bot_anomaly", "subtype": subtype, **detail}
        self.conn.execute(
            "INSERT INTO events(tick, world, kind, payload_json, run_id) "
            "VALUES(?,?,?,?,?)",
            (tick, subtype, "bot_anomaly", json.dumps(payload), self.run_id))
        self._tick_commit()

    # -- verbose decisions ----------------------------------------------------

    def record_decision(
        self,
        *,
        tick: int,
        world: str | None,
        char_uid: str | None,
        chosen: dict[str, Any] | None,
        alternatives: Any,
        reasoning: str,
        strategy_version: str,
    ) -> None:
        self.conn.execute(
            "INSERT INTO decisions(tick, world, char_uid, action, chosen_json, "
            "alternatives_json, reasoning, strategy_version, run_id) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            (tick, world, char_uid,
             (chosen or {}).get("action") if chosen else None,
             json.dumps(chosen) if chosen is not None else None,
             json.dumps(alternatives),
             reasoning, strategy_version, self.run_id))
        self._tick_commit()

    # -- retention ------------------------------------------------------------

    def prune_frames(self, keep_last: int) -> int:
        """Drop all but the most recent ``keep_last`` frames (raw JSON is the
        bulk of the file — ~14 KB/tick). events/decisions/tiles are kept, since
        they are the mined signal and are cheap. Returns rows removed.

        Delegated to :func:`steemer.db.prune_frames` for a portable form (the old
        ``DELETE ... WHERE seq NOT IN (SELECT ... LIMIT ?)`` is SQLite-only)."""
        return _db.prune_frames(self.conn, keep_last)

    # -- lifecycle ------------------------------------------------------------

    def _tick_commit(self) -> None:
        self._since_commit += 1
        if self._since_commit >= self._commit_every:
            self.conn.commit()
            self._since_commit = 0

    def flush(self) -> None:
        self.conn.commit()
        self._since_commit = 0

    def close(self) -> None:
        self.flush()
        self.conn.close()


def read_frames(
    db: Any = None, world: str | None = None, limit: int | None = None
) -> Iterator[dict[str, Any]]:
    """Yield decompressed frames oldest-first, optionally filtered by world.

    Opens its own read-only connection (SQLite ``mode=ro`` / a fresh MariaDB
    connection), so it is safe to call from the UI or an analysis process while
    the bot is writing. ``db`` is a config dict, a SQLite path, or None->config.
    """
    conn = _db.connect(db, readonly=True)
    try:
        sql = "SELECT json FROM frames"
        params: tuple[Any, ...] = ()
        if world:
            sql += " WHERE world=?"
            params = (world,)
        sql += " ORDER BY seq"
        if limit:
            sql += f" LIMIT {int(limit)}"
        for (blob,) in conn.execute(sql, params):
            yield json.loads(zlib.decompress(blob))
    finally:
        conn.close()
