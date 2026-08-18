"""The SQLite/MariaDB seam (steemer.db): dialect SQL, row shim, config, prune.

These are backend-agnostic unit tests — no live MariaDB needed. The real
round-trip against MariaDB lives in test_mariadb_roundtrip.py (env-gated). Each
assertion here was mutation-checked (broken, watched fail, restored)."""

import re

import pytest

from steemer import db as _db
from steemer.storage import Storage


# --- placeholder translation ------------------------------------------------ #

def test_xlate_translates_qmark_for_mariadb_only():
    sqlite = _db.Connection(raw=None, dialect="sqlite")
    maria = _db.Connection(raw=None, dialect="mariadb")
    sql = "INSERT INTO t(a,b) VALUES(?,?) WHERE c=?"
    assert sqlite._xlate(sql) == sql                       # untouched on sqlite
    assert maria._xlate(sql) == "INSERT INTO t(a,b) VALUES(%s,%s) WHERE c=%s"
    assert maria.placeholder == "%s" and sqlite.placeholder == "?"


def test_no_sql_string_would_break_percent_paramstyle():
    """The ?->%s translation is only safe because no query the code issues holds
    a literal ``%`` (mysql.connector's paramstyle would treat it as a format
    char). Guard the seam-touched modules: any line that looks like SQL must not
    contain a bare ``%``. Excludes steemer/db.py itself (it defines the ``%s``
    placeholder and documents the rule in prose), and stops at ui/server.py's
    inline HTML/CSS blob (which legitimately contains ``%`` widths)."""
    from steemer import storage, metrics, archive
    import ui.server as srv
    sql_kw = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|VALUES|FROM|WHERE)\b")
    offenders = []
    for mod in (storage, metrics, archive, srv):
        with open(mod.__file__, encoding="utf-8") as fh:
            for i, line in enumerate(fh, 1):
                if line.startswith("PAGE = "):         # ui: stop before the HTML/CSS
                    break
                code = line.split("#", 1)[0]           # ignore trailing comments
                if sql_kw.search(code) and "%" in code:
                    offenders.append(f"{mod.__name__}:{i}: {line.strip()}")
    assert not offenders, "literal % in SQL breaks the ?->%s seam:\n" + "\n".join(offenders)


# --- dialect-divergent statements ------------------------------------------- #

def test_tiles_seen_upsert_dialect_forms():
    s = _db.tiles_seen_upsert("sqlite")
    m = _db.tiles_seen_upsert("mariadb")
    assert "ON CONFLICT(world, x, y) DO UPDATE" in s and "excluded." in s
    assert "ON DUPLICATE KEY UPDATE" in m and "VALUES(kind)" in m
    assert "%" not in s and "%" not in m               # translation-safe


def test_archive_upsert_backticks_reserved_rows_word():
    for d in ("sqlite", "mariadb"):
        assert "`rows`" in _db.archive_upsert(d)       # reserved word, both dialects
    assert "ON CONFLICT(run_id)" in _db.archive_upsert("sqlite")
    assert "ON DUPLICATE KEY UPDATE" in _db.archive_upsert("mariadb")


# --- prune cutoff (the SQLite-only NOT IN (... LIMIT) rewrite) --------------- #

def _frame(tick):
    return {"tick": tick, "world": "vale", "visible": {"tiles": []}, "events": []}


def test_prune_keeps_last_n_via_offset_cutoff():
    s = Storage(":memory:", commit_every=1)
    for t in range(10):
        s.record_frame(_frame(t))
    removed = _db.prune_frames(s.conn, keep_last=3)
    assert removed == 7
    ticks = [r[0] for r in s.conn.execute("SELECT tick FROM frames ORDER BY tick")]
    assert ticks == [7, 8, 9]
    s.close()


def test_prune_noop_when_fewer_than_keep_last():
    s = Storage(":memory:", commit_every=1)
    for t in range(3):
        s.record_frame(_frame(t))
    assert _db.prune_frames(s.conn, keep_last=10) == 0     # nothing to drop
    assert s.conn.execute("SELECT COUNT(*) FROM frames").fetchone()[0] == 3
    s.close()


def test_prune_zero_keep_deletes_all():
    s = Storage(":memory:", commit_every=1)
    for t in range(4):
        s.record_frame(_frame(t))
    assert _db.prune_frames(s.conn, keep_last=0) == 4
    assert s.conn.execute("SELECT COUNT(*) FROM frames").fetchone()[0] == 0
    s.close()


# --- Row shim: dual (name + position) access -------------------------------- #

def test_row_supports_name_position_iter_len():
    r = _db.Row(["gold", "tick"], (14, 284137))
    assert r["gold"] == 14 and r["tick"] == 284137        # by name
    assert r[0] == 14 and r[1] == 284137                  # by position
    assert len(r) == 2 and list(r) == [14, 284137]        # iterable
    g, t = r                                              # tuple-unpacking
    assert (g, t) == (14, 284137)
    assert r.keys() == ["gold", "tick"]


# --- config loader ---------------------------------------------------------- #

def test_load_config_reads_toml(tmp_path):
    p = tmp_path / "c.toml"
    p.write_text('[database]\ntype = "mariadb"\nhost = "h"\nport = 3307\n'
                 'user = "u"\npassword = "pw"\ndb_name = "d"\n')
    cfg = _db.load_db_config(str(p))
    assert cfg == {"type": "mariadb", "host": "h", "port": 3307,
                   "user": "u", "password": "pw", "db_name": "d"}


def test_load_config_env_and_arg_precedence(tmp_path, monkeypatch):
    envp = tmp_path / "env.toml"
    envp.write_text('[database]\ntype = "sqlite"\npath = "env.db"\n')
    argp = tmp_path / "arg.toml"
    argp.write_text('[database]\ntype = "sqlite"\npath = "arg.db"\n')
    monkeypatch.setenv("STEEMER_CONFIG", str(envp))
    assert _db.load_db_config()["path"] == "env.db"            # env used
    assert _db.load_db_config(str(argp))["path"] == "arg.db"   # explicit arg wins


def test_load_config_falls_back_to_sqlite_when_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("STEEMER_CONFIG", str(tmp_path / "nope.toml"))
    assert _db.load_db_config() == {"type": "sqlite", "path": _db.DEFAULT_DB}


def test_load_config_rejects_malformed(tmp_path):
    p = tmp_path / "bad.toml"
    p.write_text('[database]\nhost = "h"\n')      # no `type`
    with pytest.raises(ValueError):
        _db.load_db_config(str(p))


# --- normalize / cfg_key ---------------------------------------------------- #

def test_normalize_str_dict_and_bad():
    assert _db.normalize("g.db") == {"type": "sqlite", "path": "g.db"}
    d = {"type": "mariadb", "user": "u"}
    assert _db.normalize(d) is d
    with pytest.raises(TypeError):
        _db.normalize(123)


def test_cfg_key_is_stable_and_secretfree():
    assert _db.cfg_key({"type": "sqlite", "path": "g.db"}) == "sqlite:g.db"
    k = _db.cfg_key({"type": "mariadb", "host": "127.0.0.1", "port": 3306,
                     "db_name": "botguilds", "password": "secret"})
    assert k == "mariadb:127.0.0.1:3306/botguilds"
    assert "secret" not in k


# --- statement splitter (MariaDB executescript) ----------------------------- #

def test_split_ignores_semicolons_inside_line_comments():
    # A `;` inside a `--` comment is prose, not a separator. The MariaDB path
    # sends one statement per execute(), so splitting mid-statement hands the
    # driver a truncated fragment (1064). This is exactly the shape of the
    # `decisions` DDL bug: a comment ending in ';' between two KEY clauses.
    script = (
        "CREATE TABLE t (\n"
        "    a INT,\n"
        "    -- keep a and b; they feed the dropdowns\n"
        "    KEY ka (a),\n"
        "    KEY kb (b)\n"
        ");\n"
        "CREATE TABLE u (c INT);"
    )
    stmts = _db._split_statements(script)
    assert len(stmts) == 2                         # the comment's ';' did NOT split
    assert stmts[0].startswith("CREATE TABLE t")
    assert "KEY ka (a)" in stmts[0] and "KEY kb (b)" in stmts[0]   # not truncated
    assert stmts[0].rstrip().endswith(")")         # closing paren survived
    assert stmts[1].startswith("CREATE TABLE u")


def test_schema_mariadb_splits_into_whole_create_statements():
    # Guard the real DDL: every split piece must be a complete CREATE TABLE, and
    # the `decisions` table (whose comment contains a ';') must keep the KEY
    # clauses that follow the comment. Under the old naive split(';') the
    # decisions statement truncated and a bare-comment fragment appeared -> both
    # of these assertions fail (the mutation check).
    stmts = _db._split_statements(_db.SCHEMA_MARIADB)
    assert stmts, "schema produced no statements"
    assert all(s.upper().startswith("CREATE TABLE") for s in stmts), \
        [s[:40] for s in stmts if not s.upper().startswith("CREATE TABLE")]
    decisions = [s for s in stmts if "decisions" in s]
    assert len(decisions) == 1                     # one whole statement, not two halves
    d = decisions[0]
    assert "idx_decisions_world" in d and "idx_decisions_char" in d   # tail survived
    assert d.rstrip().endswith(")")


# --- streaming cursor for large reads (archive export) ---------------------- #

class _FakeCur:
    def __init__(self, buffered): self.buffered = buffered; self.description = [("x",)]
    def execute(self, sql, params=None): self.sql = sql
    @property
    def with_rows(self): return True
    def __iter__(self): return iter(())
    def close(self): pass

class _FakeRaw:
    def __init__(self): self.buffered_flags = []
    def cursor(self, buffered=False):
        self.buffered_flags.append(buffered)
        return _FakeCur(buffered)

def test_execute_streams_unbuffered_while_execute_buffers_on_mariadb():
    # export_run reads a whole run's frames; on MariaDB that MUST be an unbuffered
    # cursor or a multi-GB run is materialised in memory (OOM). execute() stays
    # buffered (safe for the nested-query read paths). Break either flag -> fail.
    raw = _FakeRaw()
    conn = _db.Connection(raw, "mariadb")
    conn.execute("SELECT 1")
    assert raw.buffered_flags[-1] is True         # normal reads buffer
    conn.execute_stream("SELECT json FROM frames WHERE run_id=?", (1,))
    assert raw.buffered_flags[-1] is False        # export streams (no OOM)

def test_execute_stream_on_sqlite_delegates_and_streams(tmp_path):
    p = tmp_path / "s.db"
    conn = _db.connect({"type": "sqlite", "path": str(p)})
    conn.execute("CREATE TABLE t(a INT)")
    conn.executemany("INSERT INTO t(a) VALUES(?)", [(1,), (2,), (3,)])
    conn.commit()
    got = sorted(r[0] for r in conn.execute_stream("SELECT a FROM t"))
    assert got == [1, 2, 3]
    conn.close()
