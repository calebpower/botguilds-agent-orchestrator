"""The SQLite mirror: raw frames, flattened rows, decisions, runs, retention."""

from steemer.storage import Storage, read_frames


def _frame(tick, world="vale"):
    return {
        "type": "frame", "tick": tick, "world": world,
        "chars": [{"char_uid": "c1", "pos": [1, 1]}],
        "visible": {
            "tiles": [[1, 1, "floor", 10], [1, 2, "wall", 11]],
            "entities": [], "items": [], "gold": [],
        },
        "events": [{"kind": "attack", "attacker": 1, "target": 2, "dmg": 5}],
    }


def _db(tmp_path):
    return Storage(str(tmp_path / "t.db"), commit_every=1)


def test_frame_fans_out_to_frames_events_tiles(tmp_path):
    s = _db(tmp_path)
    s.record_frame(_frame(100))
    assert s.conn.execute("SELECT COUNT(*) FROM frames").fetchone()[0] == 1
    assert s.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    assert s.conn.execute("SELECT COUNT(*) FROM tiles_seen").fetchone()[0] == 2
    kind = s.conn.execute(
        "SELECT kind FROM tiles_seen WHERE x=1 AND y=2").fetchone()[0]
    assert kind == "wall"
    s.close()


def test_tiles_seen_upserts_latest(tmp_path):
    s = _db(tmp_path)
    s.record_frame(_frame(1))
    f2 = _frame(2)
    f2["visible"]["tiles"] = [[1, 1, "grass", 12]]     # same tile, new kind
    s.record_frame(f2)
    rows = s.conn.execute(
        "SELECT kind, last_tick FROM tiles_seen WHERE x=1 AND y=1").fetchall()
    assert rows == [("grass", 2)]        # upserted, not duplicated
    s.close()


def test_read_frames_roundtrips_compressed_json(tmp_path):
    s = _db(tmp_path)
    s.record_frame(_frame(1))
    s.record_frame(_frame(2, world="mines"))
    s.close()
    got = list(read_frames(str(tmp_path / "t.db")))
    assert [f["tick"] for f in got] == [1, 2]
    vale = list(read_frames(str(tmp_path / "t.db"), world="vale"))
    assert [f["world"] for f in vale] == ["vale"]


def test_actions_errors_and_decisions_recorded(tmp_path):
    s = _db(tmp_path)
    s.record_actions(5, [{"char_uid": "c1", "action": "move", "dir": "N"}])
    s.record_error({"tick": 5, "char_uid": "c1", "action": "move", "reason": "no_stamina"})
    s.record_decision(tick=5, world="vale", char_uid="c1",
                      chosen={"action": "move", "dir": "N"},
                      alternatives=[{"action": "rest", "score": 1.0}],
                      reasoning="stepping north", strategy_version="explorer/0")
    assert s.conn.execute("SELECT action FROM actions_sent").fetchone()[0] == "move"
    assert s.conn.execute("SELECT reason FROM action_errors").fetchone()[0] == "no_stamina"
    row = s.conn.execute("SELECT action, reasoning FROM decisions").fetchone()
    assert row == ("move", "stepping north")
    s.close()


def test_runs_window_recorded(tmp_path):
    s = _db(tmp_path)
    rid = s.begin_run("abc123", "explorer/0.1.0", note="baseline")
    assert rid == s.run_id
    s.record_frame(_frame(1))          # should be tagged with the run id
    s.end_run()
    started, stopped = s.conn.execute(
        "SELECT started_at, stopped_at FROM runs WHERE run_id=?", (rid,)).fetchone()
    assert started is not None and stopped is not None and stopped >= started
    assert s.conn.execute(
        "SELECT run_id FROM frames").fetchone()[0] == rid
    s.close()


def test_begin_run_closes_a_dangling_prior_window(tmp_path):
    # A runner hard-killed during a hot-redeploy never calls end_run, leaving its
    # window open. The next begin_run must close it, or two windows look "open"
    # at once and per-run metrics double-count.
    s = _db(tmp_path)
    old = s.begin_run("aaa", "explorer/0.7.0")     # simulate: no end_run() called
    new = s.begin_run("bbb", "explorer/0.8.0")     # supersedes it
    open_windows = [r[0] for r in s.conn.execute(
        "SELECT run_id FROM runs WHERE stopped_at IS NULL").fetchall()]
    assert open_windows == [new]                   # exactly one open, the newest
    old_stopped = s.conn.execute(
        "SELECT stopped_at FROM runs WHERE run_id=?", (old,)).fetchone()[0]
    assert old_stopped is not None                 # the dangling one got closed
    s.close()


def test_prune_frames_keeps_only_the_last_n(tmp_path):
    s = _db(tmp_path)
    for t in range(10):
        s.record_frame(_frame(t))
    removed = s.prune_frames(keep_last=3)
    assert removed == 7
    ticks = [r[0] for r in s.conn.execute("SELECT tick FROM frames ORDER BY tick")]
    assert ticks == [7, 8, 9]
    # events/tiles are deliberately retained even when frames are pruned
    assert s.conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 10
    s.close()
