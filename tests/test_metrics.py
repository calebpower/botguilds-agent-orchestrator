"""KPI derivation from a small synthetic database."""

import json
import zlib

from steemer.metrics import snapshot
from steemer.storage import Storage


def _village_frame(tick, gold, here=("c1",)):
    return {"type": "frame", "tick": tick, "world": "village",
            "guild": {"gold": gold, "chars_here": list(here),
                      "chars_by_world": {"vale": ["c2"]}, "market_listings": []},
            "chars": []}


def _map_frame(tick, y):
    return {"type": "frame", "tick": tick, "world": "vale",
            "chars": [{"char_uid": "c2", "pos": [3, y]}],
            "visible": {"tiles": [[3, y, "grass", 1], [3, y + 1, "wall", 2]],
                        "entities": [], "items": [], "gold": []},
            "events": [{"kind": "attack", "dmg": 3}, {"kind": "kill", "xp": 10}]}


def _build(tmp_path):
    s = Storage(str(tmp_path / "m.db"), commit_every=1)
    rid = s.begin_run("sha1", "explorer/0.1.0", note="test")
    s.record_frame(_village_frame(1, gold=100))
    s.record_frame(_map_frame(2, y=10))
    s.record_frame(_map_frame(3, y=20))
    s.record_actions(2, [{"char_uid": "c2", "action": "move", "dir": "N"},
                         {"char_uid": "c2", "action": "attack", "target": [3, 21]}])
    s.record_error({"tick": 2, "char_uid": "c2", "action": "attack", "reason": "out_of_range"})
    s.record_frame(_village_frame(4, gold=175))     # gold grew over the run
    s.end_run()
    s.close()
    return str(tmp_path / "m.db"), rid


def test_snapshot_volume_and_rates(tmp_path):
    db, _ = _build(tmp_path)
    snap = snapshot(db)
    v = snap["volume"]
    assert v["frames"] == 4
    assert v["actions_sent"] == 2
    assert v["action_errors"] == 1
    # 1 error / 2 sent
    assert snap["action_error_rate"] == 0.5


def test_snapshot_breakdowns_group_by_whatever_occurred(tmp_path):
    db, _ = _build(tmp_path)
    snap = snapshot(db)
    assert snap["events_by_kind"].get("kill") == 2       # two map frames, one kill each
    assert snap["events_by_kind"].get("attack") == 2
    assert snap["actions_by_kind"].get("move") == 1
    assert snap["action_errors_by_reason"].get("out_of_range") == 1


def test_snapshot_exploration_depth(tmp_path):
    db, _ = _build(tmp_path)
    snap = snapshot(db)
    vale = snap["exploration"]["vale"]
    assert vale["max_y_reached"] == 21          # y=20 tile plus its wall at 21
    assert vale["notable_tiles"] >= 1           # grass counts, floor/wall excluded


def test_snapshot_current_state_from_latest_village(tmp_path):
    db, _ = _build(tmp_path)
    snap = snapshot(db)
    cur = snap["current"]
    assert cur["gold"] == 175                    # the *latest* village gold
    assert cur["chars_by_world"] == {"vale": 1}


def test_gold_delta_reads_first_and_last_village_only(tmp_path):
    # A misleading middle value must be ignored — the delta is last minus first
    # village gold, read via the MIN/MAX-seq query (not a scan of every frame).
    s = Storage(str(tmp_path / "g.db"), commit_every=1)
    s.begin_run("sha", "explorer/x")
    s.record_frame(_village_frame(1, gold=100))
    s.record_frame(_village_frame(2, gold=999))   # spike in the middle
    s.record_frame(_map_frame(3, y=5))
    s.record_frame(_village_frame(4, gold=130))
    s.end_run()
    s.close()
    snap = snapshot(str(tmp_path / "g.db"))
    assert snap["runs"][0]["gold_delta"] == 30      # 130 - 100, ignores 999


def test_gold_delta_fetches_by_pk_not_correlated_subquery(tmp_path):
    """Regression guard on query *shape*, not answer.

    The first/last village frames must be fetched by their concrete seq values (a
    two-row PRIMARY KEY lookup). Written as ``seq IN (SELECT MIN(seq) … UNION
    SELECT MAX(seq) …)`` MariaDB plans a *dependent subquery* and full-scans every
    frame blob — minutes per snapshot. A small SQLite test returns the right
    number either way, so only the shape catches this regression."""
    from steemer import db as _db
    from steemer.metrics import _run_gold_delta

    db, rid = _build(tmp_path)                       # first village gold 100, last 175
    conn = _db.connect(db, readonly=True)
    executed = []
    real = conn.execute

    def spy(sql, params=()):
        executed.append(sql)
        return real(sql, params)

    conn.execute = spy
    try:
        assert _run_gold_delta(conn, rid) == 75      # 175 - 100
    finally:
        conn.close()

    json_fetch = [q for q in executed
                  if "json" in q.lower() and "from frames" in q.lower()]
    assert json_fetch, "expected a fetch of frame json"
    for q in json_fetch:
        # exactly one SELECT -> the IN-list holds bound seq values, not a subquery
        assert q.lower().count("select") == 1, f"correlated subquery reintroduced: {q}"


def test_storage_creates_run_id_indexes(tmp_path):
    # These indexes are what keep /api/snapshot from full-scanning the log.
    s = Storage(str(tmp_path / "i.db"))
    idx = {r[0] for r in s.conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index'")}
    assert {"idx_frames_run", "idx_frames_run_world_seq",
            "idx_actions_run", "idx_actionerr_run"} <= idx
    s.close()


def test_run_summary_reports_gold_delta(tmp_path):
    db, rid = _build(tmp_path)
    snap = snapshot(db)
    run = next(r for r in snap["runs"] if r["run_id"] == rid)
    assert run["strategy_version"] == "explorer/0.1.0"
    assert run["gold_delta"] == 75               # 175 - 100 within the run
    assert run["action_error_rate"] == 0.5


def test_snapshot_field_productivity(tmp_path):
    # the KPIs the loop was blind to: move_failed rate, pickups/xp/attacks, the
    # village economy, and sell-waste (sell actions that never became a sale).
    s = Storage(str(tmp_path / "p.db"), commit_every=1)
    s.begin_run("sha", "explorer/0.12.0")

    def mf(tick, events):
        return {"type": "frame", "tick": tick, "world": "vale",
                "chars": [{"char_uid": "c2", "pos": [3, 3]}],
                "visible": {"tiles": [[3, 3, "grass", 1]], "entities": [], "items": [], "gold": []},
                "events": events}

    s.record_frame(mf(1, [{"kind": "move"}, {"kind": "move"}, {"kind": "move"}, {"kind": "move_failed"}]))
    s.record_frame(mf(2, [{"kind": "pickup"}, {"kind": "sale"}, {"kind": "attack"}, {"kind": "xp"}]))
    s.record_actions(1, [{"char_uid": "c2", "action": "sell", "item_id": "i"},
                         {"char_uid": "c2", "action": "sell", "item_id": "j"},
                         {"char_uid": "c2", "action": "buy", "kind": "club"}])
    s.flush()

    fp = snapshot(str(tmp_path / "p.db"))["field_productivity"]
    assert fp["move_failed_rate"] == 0.25          # 1 / (3 moves + 1 failed)
    assert fp["pickups"] == 1 and fp["attacks"] == 1 and fp["xp_events"] == 1
    assert fp["economy_actions"] == 3              # 2 sell + 1 buy
    assert fp["sell_waste"] == 1                    # 2 sell actions - 1 sale event
    # and it's mirrored per-run in the runs timeline
    assert snapshot(str(tmp_path / "p.db"))["runs"][-1]["productivity"]["move_failed_rate"] == 0.25
    s.close()
