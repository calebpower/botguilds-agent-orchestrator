"""The party tab's [object Object] bug: a frame equipment slot is an OBJECT, and the
roster API must reduce it to a kind string (the frontend renders slots as text).

Two oracles: the reducer in isolation, and the full api_roster over a synthetic frame —
because the bug was that the reducer WASN'T APPLIED at the call site, so a unit test of
_slot_kind alone would have stayed green while the panel showed [object Object].
"""
import json
import sqlite3
import zlib

import ui.server as srv


def test_slot_kind_reduces_object_string_and_null():
    assert srv._slot_kind({"item_id": 1, "kind": "club", "tier": 1}) == "club"
    assert srv._slot_kind("club") == "club"      # legacy bare string tolerated
    assert srv._slot_kind(None) is None
    assert srv._slot_kind({"item_id": 9}) is None  # object with no kind -> None, not {}


def _frame_with_armed_char():
    return {
        "world": "vale", "tick": 100,
        "chars": [{
            "char_uid": "g_us_c1", "eid": 7, "name": "Recruit-1", "pos": [3, 3],
            "hp": 20, "max_hp": 30, "stamina": 40, "max_stamina": 56,
            "level": 2, "xp": 5, "stats": {"str": 2}, "gifts": [],
            "equipment": {"hand": {"item_id": 42, "kind": "club", "tier": 1},
                          "offhand": None, "outfit": None, "trinket": None,
                          "boots": None},
            "inventory": [{"item_id": 9, "kind": "ore_copper"}],
            "carry": {"used": 2, "cap": 20}, "status": [],
        }],
        "guild": {"guild_id": "g_us"},
    }


def _seed_db(path):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE runs(run_id INTEGER, started_at REAL, stopped_at REAL)")
    conn.execute("CREATE TABLE frames(seq INTEGER PRIMARY KEY, run_id INTEGER, "
                 "world TEXT, tick INTEGER, json TEXT)")
    conn.execute("CREATE TABLE decisions(seq INTEGER, run_id INTEGER, char_uid TEXT, "
                 "tick INTEGER, action TEXT, reasoning TEXT)")
    conn.execute("INSERT INTO runs VALUES (1, 0, NULL)")
    conn.execute("INSERT INTO frames VALUES (1, 1, 'vale', 100, ?)",
                 (zlib.compress(json.dumps(_frame_with_armed_char()).encode()),))
    conn.commit()
    conn.close()


def test_api_roster_emits_a_STRING_equipment_slot(tmp_path, monkeypatch):
    """The end-to-end oracle: through api_roster, hand must be 'club', never a dict —
    if the call site drops the reducer (the actual bug), this catches it where a
    _slot_kind unit test cannot."""
    db = str(tmp_path / "r.db")
    _seed_db(db)
    monkeypatch.setattr(srv, "_db_ready", lambda p: True)
    def _connect(p):
        c = sqlite3.connect(db); c.row_factory = sqlite3.Row; return c
    monkeypatch.setattr(srv, "_ro", _connect)
    res = srv.api_roster(db)
    assert res["ok"] and res["chars"], res
    hand = res["chars"][0]["equipment"]["hand"]
    assert hand == "club", f"slot not reduced to a kind string: {hand!r}"
    assert not isinstance(hand, dict), "an equipment object reached the frontend"
    assert res["chars"][0]["equipment"]["offhand"] is None
