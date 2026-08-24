"""v0.108.2 — the dashboard's fielded counts come from OUR frames, not the guild view.

The server's `chars_by_world` lags departures by whole minutes; on 2026-08-24 it read
`{}` twice while three sentinels were demonstrably fielded, and both times the operator
concluded the field was empty. The snapshot now carries `current.fielded_live`, derived
from the latest frame of each field world — the same stream the bot itself acts on.
"""
from steemer import metrics
from steemer.storage import Storage


def test_fielded_live_reports_frame_truth_over_the_lagging_guild_view(tmp_path):
    s = Storage(str(tmp_path / "f.db"), commit_every=1)
    s.begin_run("sha", "test/ft")
    # the LYING village frame: guild view says nobody is fielded
    s.record_frame({"world": "village", "tick": 100,
                    "guild": {"guild_id": "g_us", "gold": 5,
                              "chars_here": ["h1"], "chars_by_world": {}},
                    "chars": []})
    # the TRUTH: two chars in vale, one in mines, per our own frame stream
    def ch(uid):
        return {"char_uid": uid, "pos": [1, 1], "hp": 30, "max_hp": 30}
    s.record_frame({"world": "vale", "tick": 101, "chars": [ch("a"), ch("b")],
                    "visible": {"tiles": [], "entities": [], "items": [], "gold": []}})
    s.record_frame({"world": "mines", "tick": 102, "chars": [ch("c")],
                    "visible": {"tiles": [], "entities": [], "items": [], "gold": []}})
    s.flush()
    snap = metrics.snapshot(str(tmp_path / "f.db"))
    live = snap["current"]["fielded_live"]
    assert live["vale"]["n"] == 2 and live["mines"]["n"] == 1, live
    assert live["vale"]["at_tick"] == 101
    # the lagging view is preserved unchanged (the UI falls back to it for old snaps)
    assert snap["current"]["chars_by_world"] == {}


def test_an_emptied_world_reports_zero_not_its_last_crowd(tmp_path):
    # the latest frame wins: a world whose newest frame shows no chars is EMPTY even
    # though an older frame of the same world was crowded — no stale-max lying.
    s = Storage(str(tmp_path / "f.db"), commit_every=1)
    s.begin_run("sha", "test/ft")
    s.record_frame({"world": "village", "tick": 100,
                    "guild": {"guild_id": "g_us", "gold": 5,
                              "chars_here": [], "chars_by_world": {}}, "chars": []})
    ch = {"char_uid": "a", "pos": [1, 1], "hp": 30, "max_hp": 30}
    s.record_frame({"world": "vale", "tick": 101, "chars": [ch],
                    "visible": {"tiles": [], "entities": [], "items": [], "gold": []}})
    s.record_frame({"world": "vale", "tick": 150, "chars": [],
                    "visible": {"tiles": [], "entities": [], "items": [], "gold": []}})
    s.flush()
    snap = metrics.snapshot(str(tmp_path / "f.db"))
    assert snap["current"]["fielded_live"]["vale"]["n"] == 0
