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


def test_run_summary_reports_gold_delta(tmp_path):
    db, rid = _build(tmp_path)
    snap = snapshot(db)
    run = next(r for r in snap["runs"] if r["run_id"] == rid)
    assert run["strategy_version"] == "explorer/0.1.0"
    assert run["gold_delta"] == 75               # 175 - 100 within the run
    assert run["action_error_rate"] == 0.5
