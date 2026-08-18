"""Intel persistence + summary (steemer/intel.py) and its surfacing into the
analysis snapshot (steemer/metrics.py)."""

from steemer import db as _db
from steemer import intel
from steemer import metrics
from steemer.storage import Storage

SPECT = {
    "tick": 100,
    "maps": [{"id": "vale", "name": "The Vale", "width": 72, "height": 200}],
    "guilds": [
        {"guild_id": "g_us", "name": "Us", "characters": 3,
         "roster": [
             {"char_uid": "a", "world": "village", "level": 2, "equipment": {"hand": "club"}},
             {"char_uid": "b", "world": "vale", "level": 4, "equipment": {"hand": "sword", "outfit": "vest"}},
             {"char_uid": "c", "world": "vale", "level": 4, "equipment": {}}]},
        {"guild_id": "g_them", "name": "Them", "characters": 5,
         "roster": [{"char_uid": f"t{i}", "world": "village", "level": 1, "equipment": {}}
                    for i in range(5)]},
    ],
}


def _conn():
    c = _db.connect(":memory:")
    _db.apply_schema(c)
    return c


def test_record_then_latest_returns_the_newest():
    c = _conn()
    intel.record(c, "spectate", 100, 1000.0, {"guilds": [], "tick": 100})
    intel.record(c, "spectate", 200, 1001.0, {"guilds": [{"guild_id": "x"}], "tick": 200})
    got = intel.latest(c, "spectate")
    assert got["tick"] == 200 and got["observed_at"] == 1001.0
    assert got["data"]["guilds"][0]["guild_id"] == "x"
    assert intel.latest(c, "tiles") is None            # nothing of that kind yet


def test_summarize_splits_us_from_rivals_with_deltas():
    s = intel.summarize_spectate(SPECT, our_guild_id="g_us")
    assert s["guild_count"] == 2
    assert s["us"]["name"] == "Us" and s["us"]["characters"] == 3
    assert s["us"]["by_world"] == {"village": 1, "vale": 2}
    assert s["us"]["levels"] == {"min": 2, "max": 4, "mean": 3.3}
    assert s["us"]["level_hist"] == {2: 1, 4: 2}
    assert s["us"]["armed"] == 2 and s["us"]["armored"] == 1
    assert [r["name"] for r in s["rivals"]] == ["Them"]
    # head-to-head: we have 3 vs their 5 -> -2; top level 4 vs 1 -> +3.
    assert s["vs_biggest_rival"] == {"rival": "Them", "roster_delta": -2, "max_level_delta": 3}


def test_unknown_guild_id_makes_everyone_a_rival():
    s = intel.summarize_spectate(SPECT, our_guild_id="g_nobody")
    assert s["us"] is None and len(s["rivals"]) == 2


def test_snapshot_surfaces_intel_for_the_analysis_loop(tmp_path):
    s = Storage(str(tmp_path / "i.db"), commit_every=1)
    s.begin_run("sha", "test/intel")
    # a village frame carries our guild_id, which the snapshot uses to pick "us".
    s.record_frame({"world": "village", "tick": 100,
                    "guild": {"guild_id": "g_us", "gold": 5,
                              "chars_here": [], "chars_by_world": {}},
                    "chars": []})
    intel.record(s.conn, "spectate", 100, 1000.0, SPECT)
    intel.record(s.conn, "tiles", None, 1001.0, {"count": 714, "surface_tiles": {"fire": 1, "rime": 2}})
    s.flush()
    snap = metrics.snapshot(str(tmp_path / "i.db"))
    assert "intel" in snap
    assert snap["intel"]["spectate"]["us"]["name"] == "Us"       # identified via the frame's guild_id
    assert snap["intel"]["spectate"]["vs_biggest_rival"]["roster_delta"] == -2
    assert snap["intel"]["tiles"]["sprite_count"] == 714
    assert snap["intel"]["tiles"]["categories"] == {"surface_tiles": 2}
    s.close()
