"""Backend seam: run the guild's mirror on either SQLite or MariaDB.

The rest of the codebase was written against the stdlib ``sqlite3`` API with
hand-written SQL. This module lets the *same* call sites run unchanged against
MariaDB by presenting a thin wrapper that mimics the subset of the
``sqlite3.Connection`` API those call sites use (``execute`` / ``executemany`` /
``executescript`` / ``commit`` / ``close``), plus a small set of dialect-aware
helpers for the handful of statements where the two SQL dialects genuinely differ
(placeholders, upserts, the retention prune, WAL/VACUUM maintenance, schema DDL).

Which backend is used is decided by a config dict::

    {"type": "sqlite",  "path": "guild_log.db"}
    {"type": "mariadb", "host": .., "port": .., "user": .., "password": .., "db_name": ..}

resolved by :func:`load_db_config` (``--config`` flag > ``STEEMER_CONFIG`` env >
repo-root ``config.toml`` > the SQLite default), so a checkout with no config
still runs on SQLite with zero setup.

Design notes / known constraints:

* **Placeholders.** SQLite uses ``?``; MariaDB (mysql.connector) uses ``%s``. We
  translate ``?``->``%s`` for MariaDB. This is only safe because no query in the
  codebase contains a literal ``?`` or ``%`` — ``tests/test_db_seam.py`` guards
  that this stays true. When a statement has no parameters we pass ``None`` so
  the driver skips ``%``-formatting entirely.
* **Rows.** Read paths use column-name access (``row["gold"]``) *and* positional
  access (``row[0]``, ``for (blob,) in ...``). SQLite gets that from
  ``sqlite3.Row`` on read-only connections; MariaDB gets it from :class:`Row`.
  The *writer* SQLite connection deliberately keeps plain-tuple rows (default
  factory) so equality-with-tuple assertions in the storage tests hold.
* **Read-only.** SQLite opens ``file:...?mode=ro`` so a reader can never mutate
  the guild's memory. MariaDB has no per-connection read-only URI and the
  configured user holds write grants, so ``readonly=True`` is a *documented
  no-op* there — read-only-ness for the UI rests on the UI issuing only SELECTs.
* **Buffered cursors.** MariaDB reads use buffered cursors so nested queries
  (e.g. a per-world loop that runs sub-queries mid-iteration) don't trip
  "Unread result found". The one streaming consumer — archive export of a whole
  run — therefore materialises a run client-side; that path is SQLite-only today
  (retention was designed around SQLite WAL) so it is not a concern in practice.
"""

from __future__ import annotations

import os
import sqlite3
import tomllib
from typing import Any, Iterable, Sequence

DEFAULT_DB = "guild_log.db"
DEFAULT_CONFIG = "config.toml"

# mysql.connector is only needed for the MariaDB backend. Import it lazily so a
# SQLite-only checkout (and the reaper container's SQLite tests) runs without it.
try:  # pragma: no cover - import shape, exercised by whichever backend is present
    import mysql.connector as _mysql
    _MYSQL_ERRORS: tuple[type[BaseException], ...] = (_mysql.Error,)
except ImportError:  # pragma: no cover
    _mysql = None
    _MYSQL_ERRORS = ()

# Exception types a caller should catch to mean "the database said no" across
# both backends (used by the UI to degrade to an empty view instead of crashing).
Error: tuple[type[BaseException], ...] = (sqlite3.Error,) + _MYSQL_ERRORS


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

def _repo_root() -> str:
    # steemer/db.py -> steemer/ -> repo root
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_db_config(path: str | None = None) -> dict[str, Any]:
    """Resolve the ``[database]`` config: explicit ``path`` > ``STEEMER_CONFIG``
    env > repo-root ``config.toml`` > SQLite default. Returns a plain dict; the
    SQLite fallback keeps standalone/test usage working with no config present."""
    candidate = path or os.environ.get("STEEMER_CONFIG") \
        or os.path.join(_repo_root(), DEFAULT_CONFIG)
    if candidate and os.path.exists(candidate):
        with open(candidate, "rb") as fh:
            data = tomllib.load(fh)
        db = data.get("database")
        if not isinstance(db, dict) or "type" not in db:
            raise ValueError(
                f"{candidate}: missing a [database] table with a `type` key")
        return db
    return {"type": "sqlite", "path": DEFAULT_DB}


def load_retention_config(path: str | None = None) -> dict[str, Any]:
    """Resolve the optional ``[retention]`` table (same file + resolution order as
    :func:`load_db_config`). Keys are all optional — ``dest`` (NAS archive dir),
    ``stage`` (local staging dir), ``hot_hours`` (retention window), ``mount_root``
    (mount that must be live) — and callers apply their own defaults for any that
    are absent. A missing file or section yields ``{}``, so the archival tool runs
    with built-in defaults and no config is required for a fresh checkout.

    Deliberately config-driven and NOT hardcoded: the destination is an operator's
    private NAS path, which must never live in this (public) source tree.
    """
    candidate = path or os.environ.get("STEEMER_CONFIG") \
        or os.path.join(_repo_root(), DEFAULT_CONFIG)
    if candidate and os.path.exists(candidate):
        with open(candidate, "rb") as fh:
            data = tomllib.load(fh)
        ret = data.get("retention")
        if isinstance(ret, dict):
            return ret
    return {}


def normalize(db: Any) -> dict[str, Any]:
    """Coerce the flexible ``db`` argument the entry points accept into a config
    dict: ``None`` -> load from config; a ``str`` -> a SQLite path; a dict -> as-is."""
    if db is None:
        return load_db_config()
    if isinstance(db, str):
        return {"type": "sqlite", "path": db}
    if isinstance(db, dict):
        return db
    raise TypeError(f"unsupported db config: {db!r}")


def cfg_key(cfg: dict[str, Any]) -> str:
    """A short, stable, secret-free identity for a config — cache key / display."""
    if cfg.get("type") == "sqlite":
        return f"sqlite:{cfg.get('path', DEFAULT_DB)}"
    return f"mariadb:{cfg.get('host')}:{cfg.get('port')}/{cfg.get('db_name')}"


# --------------------------------------------------------------------------- #
# Row + cursor shims (MariaDB) — give mysql.connector rows sqlite3.Row-like
# dual access (by name and by position, iterable for tuple-unpacking).
# --------------------------------------------------------------------------- #

class Row:
    """A result row supporting ``row["col"]``, ``row[0]``, ``len(row)`` and
    iteration (so ``for (blob,) in cursor`` unpacks). Matches how the codebase
    reads SQLite ``sqlite3.Row`` objects, so read code is backend-agnostic."""

    __slots__ = ("_vals", "_idx")

    def __init__(self, cols: Sequence[str], vals: Sequence[Any]):
        self._vals = tuple(vals)
        self._idx = {c: i for i, c in enumerate(cols)}

    def __getitem__(self, key: Any) -> Any:
        if isinstance(key, str):
            return self._vals[self._idx[key]]
        return self._vals[key]

    def __iter__(self):
        return iter(self._vals)

    def __len__(self) -> int:
        return len(self._vals)

    def keys(self):
        return list(self._idx)


class _Result:
    """Return value of a write (INSERT/UPDATE/DELETE/DDL) on MariaDB: exposes the
    ``rowcount``/``lastrowid`` the writer reads, with no result set to fetch."""

    def __init__(self, rowcount: int, lastrowid: int | None):
        self.rowcount = rowcount
        self.lastrowid = lastrowid

    def fetchone(self):
        return None

    def fetchall(self):
        return []

    def __iter__(self):
        return iter(())


class _Cursor:
    """Wraps a buffered mysql.connector cursor so fetched rows are :class:`Row`."""

    def __init__(self, cur):
        self._cur = cur
        self._cols = [d[0] for d in cur.description] if cur.description else []

    def fetchone(self):
        vals = self._cur.fetchone()
        if vals is None:
            self._close()
            return None
        return Row(self._cols, vals)

    def fetchall(self):
        rows = [Row(self._cols, v) for v in self._cur.fetchall()]
        self._close()
        return rows

    def __iter__(self):
        for v in self._cur:
            yield Row(self._cols, v)
        self._close()

    @property
    def rowcount(self) -> int:
        return self._cur.rowcount

    @property
    def lastrowid(self):
        return self._cur.lastrowid

    def _close(self):
        try:
            self._cur.close()
        except Exception:  # pragma: no cover - best-effort cleanup
            pass

    def __del__(self):  # pragma: no cover - GC safety net for unfetched reads
        self._close()


# --------------------------------------------------------------------------- #
# Connection wrapper
# --------------------------------------------------------------------------- #

class Connection:
    """A thin ``sqlite3.Connection``-shaped wrapper over either backend.

    For SQLite it delegates straight to the native connection (fast path, native
    cursors, tuple/``Row`` rows exactly as before). For MariaDB it translates
    placeholders and wraps cursors so the calling code is identical.
    """

    def __init__(self, raw: Any, dialect: str):
        self._raw = raw
        self.dialect = dialect
        self.placeholder = "?" if dialect == "sqlite" else "%s"

    def _xlate(self, sql: str) -> str:
        return sql if self.dialect == "sqlite" else sql.replace("?", "%s")

    def execute(self, sql: str, params: Iterable[Any] = ()):
        if self.dialect == "sqlite":
            return self._raw.execute(sql, tuple(params))
        cur = self._raw.cursor(buffered=True)
        p = tuple(params)
        cur.execute(self._xlate(sql), p if p else None)
        if cur.with_rows:
            return _Cursor(cur)
        res = _Result(cur.rowcount, cur.lastrowid)
        cur.close()
        return res

    def execute_stream(self, sql: str, params: Iterable[Any] = ()):
        """Like :meth:`execute` but for a read whose result set can be arbitrarily
        large (a whole run's frames): it does NOT buffer the rows client-side. On
        MariaDB this uses an UNBUFFERED cursor, so the caller MUST consume the
        returned iterator fully before issuing another statement on this
        connection (no nested query mid-iteration). On SQLite, ``execute`` already
        streams, so this just delegates. Without it, exporting a multi-GB run
        through the buffered cursor would materialise the entire run in memory."""
        if self.dialect == "sqlite":
            return self._raw.execute(sql, tuple(params))
        cur = self._raw.cursor(buffered=False)
        p = tuple(params)
        cur.execute(self._xlate(sql), p if p else None)
        return _Cursor(cur)

    def executemany(self, sql: str, seq_of_params: Iterable[Sequence[Any]]):
        rows = [tuple(p) for p in seq_of_params]
        if self.dialect == "sqlite":
            return self._raw.executemany(sql, rows)
        cur = self._raw.cursor(buffered=True)
        if rows:
            cur.executemany(self._xlate(sql), rows)
        res = _Result(cur.rowcount, cur.lastrowid)
        cur.close()
        return res

    def executescript(self, script: str):
        if self.dialect == "sqlite":
            return self._raw.executescript(script)
        cur = self._raw.cursor()
        for stmt in _split_statements(script):
            cur.execute(stmt)
        cur.close()

    def commit(self):
        self._raw.commit()

    def close(self):
        self._raw.close()

    @property
    def raw(self):
        return self._raw


def _split_statements(script: str) -> list[str]:
    """Split a multi-statement DDL script into individual statements for the
    MariaDB path (mysql.connector executes one statement per ``execute()``).

    ``--`` line comments are stripped FIRST, because a ``;`` inside a comment is
    prose, not a statement separator — the ``decisions`` DDL has exactly that
    (``-- ... via SELECT DISTINCT;``), and a naive ``split(";")`` truncated the
    CREATE TABLE mid-statement (1064 syntax error). SQLite never hit this: its
    ``executescript`` splits natively. Safe because our DDL contains no string
    literal or identifier with ``--`` or ``;`` — only comments and column names."""
    no_comments = "\n".join(line.split("--", 1)[0] for line in script.splitlines())
    return [s.strip() for s in no_comments.split(";") if s.strip()]


# --------------------------------------------------------------------------- #
# connect()
# --------------------------------------------------------------------------- #

def connect(db: Any, *, readonly: bool = False) -> Connection:
    """Open a connection for ``db`` (config dict, path str, or None->config).

    ``readonly`` opens SQLite ``mode=ro`` (real read-only) and applies the
    read-only ``sqlite3.Row`` factory so reads get name access; it is a
    documented no-op for MariaDB. A non-read-only SQLite connection keeps default
    tuple rows (the writer's storage tests assert row==tuple)."""
    cfg = normalize(db)
    kind = cfg.get("type")
    if kind == "sqlite":
        path = cfg.get("path", DEFAULT_DB)
        if readonly:
            raw = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            raw.row_factory = sqlite3.Row
        else:
            # check_same_thread=False: the live writer shares one connection
            # across the client loop and a flush/heartbeat timer (one writer).
            raw = sqlite3.connect(path, check_same_thread=False, timeout=30)
            raw.execute("PRAGMA busy_timeout=30000")
        return Connection(raw, "sqlite")
    if kind == "mariadb":
        if _mysql is None:  # pragma: no cover - only when the driver is absent
            raise RuntimeError(
                "config selects mariadb but mysql-connector-python is not installed")
        raw = _mysql.connect(
            host=cfg.get("host", "127.0.0.1"), port=int(cfg.get("port", 3306)),
            user=cfg["user"], password=cfg["password"], database=cfg["db_name"],
            autocommit=False)
        return Connection(raw, "mariadb")
    raise ValueError(f"unknown database type: {kind!r}")


def db_ready(db: Any) -> bool:
    """True when the backend is reachable/openable — the UI treats False as
    "no data yet" and renders an empty state rather than erroring."""
    cfg = normalize(db)
    if cfg.get("type") == "sqlite":
        path = cfg.get("path", DEFAULT_DB)
        if not os.path.exists(path):
            return False
        try:
            connect(cfg, readonly=True).close()
            return True
        except sqlite3.Error:
            return False
    try:
        conn = connect(cfg, readonly=True)
        conn.execute("SELECT 1").fetchone()
        conn.close()
        return True
    except Error:  # pragma: no cover - depends on a live server
        return False


# --------------------------------------------------------------------------- #
# Schema (dialect-specific DDL)
# --------------------------------------------------------------------------- #

# The SQLite schema is authoritative for column semantics; the MariaDB schema is
# a faithful translation (INTEGER PK AUTOINCREMENT -> INT AUTO_INCREMENT, REAL ->
# DOUBLE, BLOB -> MEDIUMBLOB for headroom, TEXT columns that are keyed/short ->
# VARCHAR(255)). Both use IF NOT EXISTS so applying them to an existing DB (the
# live MariaDB already has these tables) is a no-op. Indexes are declared inline
# as KEY clauses to avoid needing CREATE INDEX IF NOT EXISTS (version-sensitive).

SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS frames (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    tick INTEGER, world TEXT, received_at REAL, run_id INTEGER,
    json BLOB
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
    action TEXT, chosen_json TEXT, alternatives_json TEXT, reasoning TEXT,
    strategy_version TEXT, run_id INTEGER
);
CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    git_sha TEXT, strategy_version TEXT,
    started_at REAL, stopped_at REAL, note TEXT
);
CREATE INDEX IF NOT EXISTS idx_frames_tick ON frames(tick);
-- (kind, tick) composite: serves GROUP BY kind AND lets the dashboard's
-- "first seen per kind" (MIN(tick) per kind) be an index lookup instead of a
-- full-table scan. Supersedes the old single-column events(kind) index.
CREATE INDEX IF NOT EXISTS idx_events_kind_tick ON events(kind, tick);
CREATE INDEX IF NOT EXISTS idx_events_tick ON events(tick);
CREATE INDEX IF NOT EXISTS idx_decisions_tick ON decisions(tick);
CREATE INDEX IF NOT EXISTS idx_actionerr_reason ON action_errors(reason);
CREATE INDEX IF NOT EXISTS idx_frames_run ON frames(run_id);
CREATE INDEX IF NOT EXISTS idx_frames_run_world_seq ON frames(run_id, world, seq);
CREATE INDEX IF NOT EXISTS idx_actions_run ON actions_sent(run_id);
CREATE INDEX IF NOT EXISTS idx_actionerr_run ON action_errors(run_id);
CREATE INDEX IF NOT EXISTS idx_actions_action ON actions_sent(action);
CREATE INDEX IF NOT EXISTS idx_decisions_action ON decisions(action);
-- world/char_uid feed the dashboard's filter dropdowns via SELECT DISTINCT; without
-- these the DISTINCT is a full scan of the (large) decisions table.
CREATE INDEX IF NOT EXISTS idx_decisions_world ON decisions(world);
CREATE INDEX IF NOT EXISTS idx_decisions_char ON decisions(char_uid);
"""

SCHEMA_MARIADB = """
CREATE TABLE IF NOT EXISTS frames (
    seq INT AUTO_INCREMENT PRIMARY KEY,
    tick INT, world VARCHAR(255), received_at DOUBLE, run_id INT,
    json MEDIUMBLOB,
    KEY idx_frames_tick (tick),
    KEY idx_frames_run (run_id),
    KEY idx_frames_run_world_seq (run_id, world, seq)
);
CREATE TABLE IF NOT EXISTS events (
    seq INT AUTO_INCREMENT PRIMARY KEY,
    tick INT, world VARCHAR(255), kind VARCHAR(255), payload_json TEXT, run_id INT,
    -- (kind, tick) composite: serves GROUP BY kind AND makes the dashboard's
    -- MIN(tick)-per-kind "first seen" an index lookup, not a 1.5M-row scan.
    KEY idx_events_kind_tick (kind, tick),
    KEY idx_events_tick (tick)
);
CREATE TABLE IF NOT EXISTS actions_sent (
    seq INT AUTO_INCREMENT PRIMARY KEY,
    tick INT, char_uid VARCHAR(255), action VARCHAR(255), payload_json TEXT, run_id INT,
    KEY idx_actions_run (run_id),
    KEY idx_actions_action (action)
);
CREATE TABLE IF NOT EXISTS action_errors (
    seq INT AUTO_INCREMENT PRIMARY KEY,
    tick INT, char_uid VARCHAR(255), action VARCHAR(255), reason TEXT, run_id INT,
    KEY idx_actionerr_reason (reason(255)),
    KEY idx_actionerr_run (run_id)
);
CREATE TABLE IF NOT EXISTS tiles_seen (
    world VARCHAR(255), x INT, y INT, kind VARCHAR(255), sprite INT,
    last_tick INT, base TEXT,
    PRIMARY KEY (world, x, y)
);
CREATE TABLE IF NOT EXISTS decisions (
    seq INT AUTO_INCREMENT PRIMARY KEY,
    tick INT, world VARCHAR(255), char_uid VARCHAR(255),
    action VARCHAR(255), chosen_json TEXT, alternatives_json TEXT, reasoning TEXT,
    strategy_version VARCHAR(255), run_id INT,
    KEY idx_decisions_tick (tick),
    KEY idx_decisions_action (action),
    -- world/char_uid feed the dashboard's filter dropdowns via SELECT DISTINCT;
    -- without these the DISTINCT is a full scan of the (large) decisions table.
    KEY idx_decisions_world (world),
    KEY idx_decisions_char (char_uid)
);
CREATE TABLE IF NOT EXISTS runs (
    run_id INT AUTO_INCREMENT PRIMARY KEY,
    git_sha VARCHAR(255), strategy_version VARCHAR(255),
    started_at DOUBLE, stopped_at DOUBLE, note TEXT
);
"""


def apply_schema(conn: Connection) -> None:
    """Create the mirror's tables if absent (idempotent on both backends)."""
    if conn.dialect == "sqlite":
        conn.executescript(SCHEMA_SQLITE)
    else:
        conn.executescript(SCHEMA_MARIADB)
    conn.commit()


# The archives retention manifest (steemer.archive). ``rows`` is a MariaDB
# reserved word so it is backtick-quoted; SQLite accepts backticks too.
MANIFEST_SQLITE = """
CREATE TABLE IF NOT EXISTS archives (
    run_id INTEGER PRIMARY KEY,
    path TEXT, remote_uri TEXT, sha256 TEXT,
    `rows` INTEGER, bytes INTEGER,
    run_started REAL, run_stopped REAL, archived_at REAL,
    verified INTEGER DEFAULT 0, pruned INTEGER DEFAULT 0
);
"""

MANIFEST_MARIADB = """
CREATE TABLE IF NOT EXISTS archives (
    run_id INT PRIMARY KEY,
    path TEXT, remote_uri TEXT, sha256 VARCHAR(255),
    `rows` INT, bytes BIGINT,
    run_started DOUBLE, run_stopped DOUBLE, archived_at DOUBLE,
    verified INT DEFAULT 0, pruned INT DEFAULT 0
);
"""


def apply_manifest(conn: Connection) -> None:
    """Create the archives manifest table if absent (idempotent, both backends)."""
    conn.executescript(MANIFEST_SQLITE if conn.dialect == "sqlite" else MANIFEST_MARIADB)
    conn.commit()


# --------------------------------------------------------------------------- #
# Dialect-divergent statements
# --------------------------------------------------------------------------- #

def tiles_seen_upsert(dialect: str) -> str:
    """Upsert one tiles_seen row keyed on (world, x, y). SQLite ON CONFLICT vs
    MariaDB ON DUPLICATE KEY — the only per-row dialect fork in the write path."""
    base = ("INSERT INTO tiles_seen(world, x, y, kind, sprite, last_tick, base) "
            "VALUES(?,?,?,?,?,?,?) ")
    if dialect == "sqlite":
        return base + ("ON CONFLICT(world, x, y) DO UPDATE SET "
                       "kind=excluded.kind, sprite=excluded.sprite, "
                       "last_tick=excluded.last_tick, base=excluded.base")
    return base + ("ON DUPLICATE KEY UPDATE kind=VALUES(kind), "
                   "sprite=VALUES(sprite), last_tick=VALUES(last_tick), "
                   "base=VALUES(base)")


def archive_upsert(dialect: str) -> str:
    """Upsert an archives manifest row keyed on run_id (see steemer.archive)."""
    base = ("INSERT INTO archives(run_id, path, remote_uri, sha256, `rows`, bytes, "
            "run_started, run_stopped, archived_at, verified, pruned) "
            "VALUES(?,?,?,?,?,?,?,?,?,0,0) ")
    if dialect == "sqlite":
        return base + ("ON CONFLICT(run_id) DO UPDATE SET path=excluded.path, "
                       "remote_uri=excluded.remote_uri, sha256=excluded.sha256, "
                       "rows=excluded.rows, bytes=excluded.bytes, "
                       "archived_at=excluded.archived_at")
    return base + ("ON DUPLICATE KEY UPDATE path=VALUES(path), "
                   "remote_uri=VALUES(remote_uri), sha256=VALUES(sha256), "
                   "`rows`=VALUES(`rows`), bytes=VALUES(bytes), "
                   "archived_at=VALUES(archived_at)")


def prune_frames(conn: Connection, keep_last: int) -> int:
    """Drop all but the most recent ``keep_last`` frames; returns rows removed.

    Replaces the SQLite-only ``DELETE ... WHERE seq NOT IN (SELECT ... LIMIT ?)``
    (which MariaDB rejects) with a portable two-step: find the oldest seq we keep,
    then delete everything strictly older. Semantics are identical on both."""
    if keep_last <= 0:
        cur = conn.execute("DELETE FROM frames")
        conn.commit()
        return cur.rowcount
    # The keep_last-th newest row is the oldest one we keep; delete seq < it.
    row = conn.execute(
        "SELECT seq FROM frames ORDER BY seq DESC LIMIT 1 OFFSET ?",
        (keep_last - 1,)).fetchone()
    if row is None:                       # fewer than keep_last frames: nothing to do
        return 0
    cutoff = row[0]
    cur = conn.execute("DELETE FROM frames WHERE seq < ?", (cutoff,))
    conn.commit()
    return cur.rowcount


def checkpoint(conn: Connection) -> None:
    """Fold WAL back into the main file (SQLite). No-op on MariaDB (InnoDB manages
    its own storage; the walk-away disk-bound story is a SQLite concern)."""
    if conn.dialect == "sqlite":
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.commit()


def reclaim_space(conn: Connection) -> None:
    """Physically shrink the file after large prunes (SQLite VACUUM). No-op on
    MariaDB (would be OPTIMIZE TABLE, a separate maintenance-window decision)."""
    if conn.dialect == "sqlite":
        conn.execute("VACUUM")
        conn.commit()
