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
import sqlite3
import time
import zlib
from typing import Any, Iterable, Iterator

DEFAULT_DB = "guild_log.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS frames (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    tick INTEGER, world TEXT, received_at REAL, run_id INTEGER,
    json BLOB                                   -- zlib-compressed frame JSON
);
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    tick INTEGER, world TEXT, kind TEXT, payload_json TEXT, run_id INTEGER
);
CREATE TABLE IF NOT EXISTS actions_sent (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    tick INTEGER, char_uid TEXT, action TEXT, payload_json TEXT, run_id INTEGER
);
CREATE TABLE IF NOT EXISTS action_errors (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    tick INTEGER, char_uid TEXT, action TEXT, reason TEXT, run_id INTEGER
);
CREATE TABLE IF NOT EXISTS tiles_seen (
    world TEXT, x INTEGER, y INTEGER, kind TEXT, sprite INTEGER,
    last_tick INTEGER, base TEXT,
    PRIMARY KEY (world, x, y)
);
CREATE TABLE IF NOT EXISTS decisions (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    tick INTEGER, world TEXT, char_uid TEXT,
    action TEXT,                 -- the action name chosen (or NULL for "rest")
    chosen_json TEXT,            -- the full action dict we sent
    alternatives_json TEXT,      -- ranked candidates + scores we considered
    reasoning TEXT,              -- human-readable "why" — the verbose thinking
    strategy_version TEXT, run_id INTEGER
);
CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    git_sha TEXT, strategy_version TEXT,
    started_at REAL, stopped_at REAL, note TEXT
);
CREATE INDEX IF NOT EXISTS idx_frames_tick ON frames(tick);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind);
CREATE INDEX IF NOT EXISTS idx_events_tick ON events(tick);
CREATE INDEX IF NOT EXISTS idx_decisions_tick ON decisions(tick);
CREATE INDEX IF NOT EXISTS idx_actionerr_reason ON action_errors(reason);
-- run_id / grouping indexes: the metrics snapshot does per-run COUNT(*) and a
-- first/last-village-frame gold lookup; without these it full-scans the largest
-- tables on every poll (the /api/snapshot slowness). run_id is low-cardinality
-- so the write-path cost is negligible.
CREATE INDEX IF NOT EXISTS idx_frames_run ON frames(run_id);
CREATE INDEX IF NOT EXISTS idx_frames_run_world_seq ON frames(run_id, world, seq);
CREATE INDEX IF NOT EXISTS idx_actions_run ON actions_sent(run_id);
CREATE INDEX IF NOT EXISTS idx_actionerr_run ON action_errors(run_id);
CREATE INDEX IF NOT EXISTS idx_actions_action ON actions_sent(action);
CREATE INDEX IF NOT EXISTS idx_decisions_action ON decisions(action);
"""


def _base_cell(base: Any) -> Any:
    """tiles_seen.base is an int for a single under-layer, or JSON for a stack."""
    return json.dumps(base) if isinstance(base, list) else base


class Storage:
    """The bot's SQLite mirror. One instance per process owns the connection."""

    def __init__(self, path: str = DEFAULT_DB, *, commit_every: int = 20):
        # check_same_thread=False so the client loop and a heartbeat/flush timer
        # may share it; only one thread actually writes.
        self.conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA busy_timeout=30000")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()
        self.run_id: int | None = None
        self._commit_every = commit_every
        self._since_commit = 0

    # -- run/version windows --------------------------------------------------

    def begin_run(self, git_sha: str, strategy_version: str, note: str = "") -> int:
        cur = self.conn.execute(
            "INSERT INTO runs(git_sha, strategy_version, started_at, note) "
            "VALUES(?,?,?,?)",
            (git_sha, strategy_version, time.time(), note),
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
                "INSERT INTO tiles_seen(world, x, y, kind, sprite, last_tick, base) "
                "VALUES(?,?,?,?,?,?,?) ON CONFLICT(world, x, y) DO UPDATE SET "
                "kind=excluded.kind, sprite=excluded.sprite, "
                "last_tick=excluded.last_tick, base=excluded.base",
                [(world, t[0], t[1], t[2],
                  t[3] if len(t) > 3 else 0, tick,
                  _base_cell(t[4]) if len(t) > 4 else 0) for t in tiles],
            )
        self._tick_commit()

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
        they are the mined signal and are cheap. Returns rows removed."""
        cur = self.conn.execute(
            "DELETE FROM frames WHERE seq NOT IN "
            "(SELECT seq FROM frames ORDER BY seq DESC LIMIT ?)", (keep_last,))
        self.conn.commit()
        return cur.rowcount

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
    db_path: str = DEFAULT_DB, world: str | None = None, limit: int | None = None
) -> Iterator[dict[str, Any]]:
    """Yield decompressed frames oldest-first, optionally filtered by world.

    Opens its own read-only connection, so it is safe to call from the UI or an
    analysis process while the bot is writing (WAL).
    """
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
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
