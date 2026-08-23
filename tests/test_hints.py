"""v0.97.0 — the HINT channel: the bot consumes the sidecar's map-wide rival positions.

The sidecar sees the whole map (spectate/track intel); our chars see only locally. The
hint reader closes that gap. Fail-closed and cached, so it never burdens the frame loop.
"""
import json
import zlib

from steemer.bot import GuildBot
from steemer.storage import Storage


def _bot_with_track(tmp_path, rivals, world="vale", tick=500):
    st = Storage(str(tmp_path / "s.db"))
    st.begin_run("h", "test/0")
    import time as _t
    from steemer import intel
    intel.record(st.conn, "track", tick, _t.time(),
                 {"map": world, "tick": tick, "rivals": rivals})
    st.conn.commit()
    b = GuildBot(strategy="explorer", storage=st)
    b.tick = 10 ** 6      # far past HINT_REFRESH so the first on-frame refresh fires
    return b


def test_the_bot_reads_rival_positions_from_the_track_feed(tmp_path):
    b = _bot_with_track(tmp_path, [
        {"guild_id": "g_63837f", "pos": [44, 39], "name": "Barbarian_Troy"},
        {"guild_id": "g_63837f", "pos": [45, 35], "name": "Ranger_Harry"},
    ])
    b._refresh_hints()
    hints = b.rival_hints.get("vale") or []
    assert len(hints) == 2
    assert {h["guild_id"] for h in hints} == {"g_63837f"}
    assert (44, 39) in {h["pos"] for h in hints}      # pos is a tuple, ready for math


def test_hints_are_CACHED_between_refresh_windows(tmp_path):
    b = _bot_with_track(tmp_path, [{"guild_id": "g_63837f", "pos": [1, 1]}])
    b._refresh_hints()
    first = b.rival_hints.get("vale")
    # a second call within HINT_REFRESH_TICKS must NOT hit the DB again (advance tick by 1)
    b.tick += 1
    b._refresh_hints()
    assert b.rival_hints.get("vale") is first, "refreshed inside the cache window"


def test_a_missing_feed_leaves_hints_empty_and_never_raises(tmp_path):
    st = Storage(str(tmp_path / "s.db"))
    st.begin_run("h", "test/0")            # no track rows at all
    b = GuildBot(strategy="explorer", storage=st)
    b.tick = 10 ** 6
    b._refresh_hints()                     # must not raise
    assert b.rival_hints == {}


def test_a_storageless_bot_just_skips_hints():
    b = GuildBot(strategy="explorer")      # no storage
    b.tick = 10 ** 6
    b._refresh_hints()
    assert b.rival_hints == {}
