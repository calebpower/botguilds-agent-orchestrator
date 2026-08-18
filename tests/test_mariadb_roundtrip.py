"""Real round-trip against a live MariaDB — proves the write seam (placeholder
translation, the tiles_seen ON DUPLICATE KEY upsert, BLOB fidelity, Row access)
on the actual backend, not just the dialect-string level.

Env-gated: set ``STEEMER_TEST_MARIADB=1`` to run it against the backend named by
config.toml (or point ``STEEMER_CONFIG`` at another config). When the var is
unset it SKIPS with a stated reason — mirroring this repo's existing
``pytest.skip("no POSIX sh on PATH")`` precedent in test_scripts.py, so a
SQLite-only environment (e.g. the reaper container) stays green without silently
dropping coverage.

Safety: it never calls prune_frames (that would delete real frames), never uses
begin_run (which would close other runs' windows), and cleans up every row it
writes — tagged with a unique world + its own run row — so live data is
untouched. The suite assumes the live writer is stopped (a maintenance window)."""

import json
import os
import zlib

import pytest

from steemer import db as _db

pytestmark = pytest.mark.skipif(
    not os.environ.get("STEEMER_TEST_MARIADB"),
    reason="STEEMER_TEST_MARIADB not set — skipping live MariaDB round-trip "
           "(runs only in an environment with the configured MariaDB reachable)")

TEST_WORLD = "pytest_roundtrip_world"          # unique -> cleanable, never real data


def _cfg():
    cfg = _db.load_db_config()
    if cfg.get("type") != "mariadb":
        pytest.skip(f"configured backend is {cfg.get('type')}, not mariadb")
    return cfg


def _make_test_run(conn):
    """Insert an isolated run row directly (NOT begin_run, which would touch other
    runs' windows) and return its run_id."""
    cur = conn.execute(
        "INSERT INTO runs(git_sha, strategy_version, started_at, stopped_at, note) "
        "VALUES(?,?,?,?,?)",
        ("pytestsha", "test/roundtrip", 1.0, 2.0, "pytest roundtrip — auto-cleaned"))
    conn.commit()
    return cur.lastrowid


def _cleanup(conn, run_id):
    for t in ("frames", "events", "actions_sent", "action_errors", "decisions"):
        conn.execute(f"DELETE FROM {t} WHERE run_id=?", (run_id,))
    conn.execute("DELETE FROM tiles_seen WHERE world=?", (TEST_WORLD,))
    conn.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
    conn.commit()


def test_mariadb_write_read_roundtrip():
    from steemer.storage import Storage, read_frames
    cfg = _cfg()

    # Verify placeholder translation actually reached MariaDB (dialect detected).
    probe = _db.connect(cfg)
    assert probe.dialect == "mariadb" and probe.placeholder == "%s"
    probe.close()

    s = Storage(cfg, commit_every=1)
    run_id = _make_test_run(s.conn)
    s.run_id = run_id
    frame = {
        "type": "frame", "tick": 424242, "world": TEST_WORLD,
        "chars": [{"char_uid": "rt1", "pos": [2, 3]}],
        "visible": {"tiles": [[2, 3, "grass", 7], [2, 4, "wall", 8]],
                    "entities": [], "items": [], "gold": []},
        "events": [{"kind": "roundtrip_probe", "n": 1}],
    }
    try:
        s.record_frame(frame)                        # exercises tiles ON DUPLICATE KEY
        s.record_actions(424242, [{"char_uid": "rt1", "action": "move", "dir": "N"}])
        s.record_error({"tick": 424242, "char_uid": "rt1",
                        "action": "move", "reason": "roundtrip_reason"})
        s.record_decision(tick=424242, world=TEST_WORLD, char_uid="rt1",
                          chosen={"action": "move", "dir": "N"},
                          alternatives=[{"action": "rest", "score": 0.5}],
                          reasoning="roundtrip reasoning", strategy_version="test/roundtrip")
        s.flush()

        # Two oracles for the frame: (1) it decompresses back to the same dict via
        # read_frames, and (2) the stored BLOB is byte-identical to what we'd store.
        got = [f for f in read_frames(cfg, world=TEST_WORLD) if f.get("tick") == 424242]
        assert got and got[0]["events"][0]["kind"] == "roundtrip_probe"

        blob = s.conn.execute(
            "SELECT json FROM frames WHERE run_id=? AND tick=424242",
            (run_id,)).fetchone()[0]
        assert bytes(blob) == zlib.compress(json.dumps(frame).encode("utf-8"))

        # Flattened rows + name-access rows survived the seam.
        assert s.conn.execute(
            "SELECT reason FROM action_errors WHERE run_id=?", (run_id,)
        ).fetchone()["reason"] == "roundtrip_reason"
        assert s.conn.execute(
            "SELECT action FROM actions_sent WHERE run_id=?", (run_id,)
        ).fetchone()[0] == "move"

        # tiles upsert landed and updates-in-place on a second sighting.
        frame2 = dict(frame)
        frame2["visible"] = {"tiles": [[2, 3, "lava", 9]], "entities": [],
                             "items": [], "gold": []}
        s.record_frame(frame2)
        s.flush()
        kind = s.conn.execute(
            "SELECT kind FROM tiles_seen WHERE world=? AND x=2 AND y=3",
            (TEST_WORLD,)).fetchone()[0]
        assert kind == "lava"          # ON DUPLICATE KEY UPDATE, not a duplicate row
        assert s.conn.execute(
            "SELECT COUNT(*) FROM tiles_seen WHERE world=? AND x=2 AND y=3",
            (TEST_WORLD,)).fetchone()[0] == 1

        # export_run must STREAM the run's frames off MariaDB (unbuffered cursor)
        # and produce a faithful archive — the retention path that made cutover
        # to MariaDB unsafe until now. Export to a temp file, read it back, and
        # confirm the blob decompresses to exactly the frame we wrote.
        import tempfile
        from steemer import archive
        out = tempfile.mktemp(suffix=".jsonl.gz")
        try:
            res = archive.export_run(s.conn, run_id, out)
            assert res["rows"] >= 1
            back = list(archive.read_archive(out))
            blobs = [bytes(r["blob"]) for r in back
                     if r["run_id"] == run_id and r["tick"] == 424242]
            assert blobs, "export_run yielded no frame for the test run"
            assert json.loads(zlib.decompress(blobs[0]))["world"] == TEST_WORLD
        finally:
            if os.path.exists(out):
                os.remove(out)
    finally:
        _cleanup(s.conn, run_id)
        s.close()


def test_readonly_connection_sees_writes_committed_after_its_first_read():
    """A ``readonly=True`` MariaDB connection must see rows committed by another
    connection AFTER it has already issued a read. Before the fix, readonly
    connections were opened ``autocommit=False`` under InnoDB's default
    REPEATABLE READ, so the first SELECT froze an MVCC snapshot for the
    connection's whole life — a reused reader (a monitor, the analysis tool held
    open across samples) never advanced past the data as of its first query,
    which read as the DB being "stalled"/"gated". This is the code-level fix for
    the artifact that decisions.log/findings.jsonl previously only worked around
    by habit ("use a fresh connection per sample")."""
    cfg = _cfg()
    writer = _db.connect(cfg)                       # autocommit=False writer
    run_id = _make_test_run(writer)
    reader = _db.connect(cfg, readonly=True)
    try:
        # The reader takes its FIRST snapshot here (0 rows for our isolated run).
        before = reader.execute(
            "SELECT COUNT(*) FROM action_errors WHERE run_id=?", (run_id,)).fetchone()[0]
        assert before == 0
        # A different connection commits a new row.
        writer.execute(
            "INSERT INTO action_errors(tick, char_uid, action, reason, run_id) "
            "VALUES(?,?,?,?,?)", (1, "rt", "move", "snapshot_probe", run_id))
        writer.commit()
        # A fresh read on the SAME reader must now see it. Under the old frozen
        # REPEATABLE READ snapshot this stayed 0 — the regression this guards.
        after = reader.execute(
            "SELECT COUNT(*) FROM action_errors WHERE run_id=?", (run_id,)).fetchone()[0]
        assert after == 1, "read-only connection is pinned to a stale snapshot"
    finally:
        reader.close()
        _cleanup(writer, run_id)
        writer.close()
