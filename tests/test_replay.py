"""Offline replay reconstructs the current engine's decisions from history."""

from steemer import replay
from steemer.storage import Storage


def _record_field_frame_with_enemy(db_path):
    s = Storage(db_path, commit_every=1)
    s.record_frame({
        "type": "frame", "tick": 42, "world": "vale",
        "chars": [{"char_uid": "c1", "pos": [0, 0], "hp": 30, "max_hp": 30,
                   "stamina": 40, "carry": {"used": 0, "cap": 20},
                   "inventory": [], "stats": {}, "equipment": {}}],
        "visible": {"tiles": [[0, 0, "floor"], [0, 1, "floor"], [1, 0, "floor"]],
                    "entities": [{"pos": [1, 0], "faction": "monster",
                                  "kind": "rat_grey", "hp_frac": 0.5}],
                    "items": [], "gold": []},
    })
    s.close()


def test_replay_reconstructs_actions(tmp_path, capsys):
    db = str(tmp_path / "hist.db")
    _record_field_frame_with_enemy(db)
    rc = replay.main(["--db", db])
    assert rc == 0
    out = capsys.readouterr().out
    assert "tick 42 vale" in out
    assert "attack" in out                 # explorer attacks the adjacent rat
    assert "replayed 1 frame" in out


def test_replay_verbose_prints_reasoning(tmp_path, capsys):
    db = str(tmp_path / "hist.db")
    _record_field_frame_with_enemy(db)
    rc = replay.main(["--db", db, "-v"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "attack adjacent" in out        # the verbose reasoning is shown
