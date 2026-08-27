"""v0.117.0 — the server-health BUNKER (operator-directed): watch for server trouble
client-side (sustained frame lag via the hello anchor, or a poison-rejection storm),
recall the field to the village, hold embarks, and resume dynamically once the server
is clean for a full window. Grace both ways: a lag SPIKE never benches the guild and
a brief lull never un-benches it."""
from steemer.bot import (GuildBot, HEALTH_LAG_S, HEALTH_ENTER_TICKS,
                         HEALTH_POISON_N, HEALTH_POISON_WINDOW, HEALTH_EXIT_TICKS)


def test_pinned_literals():
    assert (HEALTH_LAG_S, HEALTH_ENTER_TICKS, HEALTH_POISON_N,
            HEALTH_POISON_WINDOW, HEALTH_EXIT_TICKS) == (2.5, 120, 10, 300, 2000)


def _bot():
    b = GuildBot(strategy="explorer")
    b.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 10, "tick_seconds": 0.25,
                "maps": [{"id": "vale"}]}
    return b


def test_sustained_lag_bunkers_but_a_spike_does_not():
    b = _bot()
    b._hello_anchor = (1000, 100.0)          # tick 1000 anchored at wall 100.0
    # SPIKE: 60 ticks of 4s lag (under the 120-tick entry grace) then clean again
    for t in range(1001, 1061):
        b._health_step(t, now=100.0 + (t - 1000) * 0.25 + 4.0)
    assert b.server_health() == "ok", "a lag spike under the grace benched the guild"
    for t in range(1061, 1200):
        b._health_step(t, now=100.0 + (t - 1000) * 0.25)     # clean
    assert b.server_health() == "ok"
    # SUSTAINED: 121 ticks of 4s lag
    for t in range(1200, 1322):
        b._health_step(t, now=100.0 + (t - 1000) * 0.25 + 4.0)
    assert b.server_health() == "bunker", "sustained lag never bunkered"


def test_bunker_exits_only_after_a_full_clean_window():
    b = _bot()
    b._hello_anchor = (1000, 100.0)
    for t in range(1000, 1130):
        b._health_step(t, now=100.0 + (t - 1000) * 0.25 + 4.0)
    assert b.server_health() == "bunker"
    # clean, but re-poisoned midway: the exit clock restarts
    for t in range(1130, 2000):
        b._health_step(t, now=100.0 + (t - 1000) * 0.25)
    b._poison_ticks.extend(range(2000, 2012))
    b._health_step(2012, now=100.0 + 1012 * 0.25)
    # the poison entries stay inside their 300t window until ~t2311, so the clean
    # clock starts THERE; exit lands at ~4311, and 4300 must still be bunkered.
    for t in range(2013, 4300):
        b._health_step(t, now=100.0 + (t - 1000) * 0.25)
    assert b.server_health() == "bunker", "exited before a FULL clean window post-storm"
    for t in range(4300, 4330):
        b._health_step(t, now=100.0 + (t - 1000) * 0.25)
    assert b.server_health() == "ok", "never exited after the clean window"


def test_a_new_hello_reanchors_the_lag_clock():
    """Reconnects reset the lag baseline — the fresh session's debt is measured from
    its own hello, not the dead session's."""
    b = _bot()
    b.on_hello({"config": b.config, "guild": {}, "tick": 5000})
    a_tick, a_wall = b._hello_anchor
    assert a_tick == 5000
    lag = b._lag_estimate(5008, now=a_wall + 8 * 0.25 + 0.1)
    assert lag is not None and abs(lag - 0.1) < 1e-6


def _field_frame(tick, char):
    w, h = 24, 24
    tiles = [[x, y, "floor", 0, 0] for x in range(w) for y in range(h)]
    return {"type": "frame", "world": "vale", "tick": tick, "events": [],
            "bounds": [w, 200], "chars": [char],
            "visible": {"tiles": tiles, "entities": [], "items": [], "gold": []}}


def test_a_fielded_char_walks_home_under_bunker_and_gathers_otherwise():
    """Two-oracle wiring test: same char, same world, loot to the NORTH. Healthy ->
    it walks N to the loot. Bunkered (poison storm) -> it walks S toward the village
    instead: the 6.0 bunker retreat outranks the 5.0 beeline."""
    char = {"char_uid": "c1", "eid": 7, "pos": [12, 8], "hp": 30, "max_hp": 30,
            "stamina": 48, "max_stamina": 56, "level": 3, "stats": {}, "gifts": [],
            "statuses": [], "spells": [], "spell_cap": 1,
            "carry": {"used": 0, "cap": 20}, "inventory": [],
            "equipment": {"hand": {"kind": "club"}}}
    frame = _field_frame(3000, dict(char))
    frame["visible"]["gold"] = [{"pos": [12, 10], "amount": 2}]   # NORTH (y+), inside
                                                                  # the unhealed depth cap
    healthy = _bot()
    acts = healthy.on_frame(frame)
    mv = [a for a in acts if a.get("action") == "move"]
    assert mv and mv[0]["dir"] == "N", f"healthy char did not chase the coin: {acts}"

    bunkered = _bot()
    for i in range(12):
        bunkered.on_action_error({"tick": 2990 + i, "reason": "stale_frame"})
    frame2 = _field_frame(3000, dict(char))
    frame2["visible"]["gold"] = [{"pos": [12, 10], "amount": 2}]
    acts2 = bunkered.on_frame(frame2)
    mv2 = [a for a in acts2 if a.get("action") == "move"]
    assert mv2 and mv2[0]["dir"] == "S", \
        f"bunkered char did not turn for the village: {acts2}"


def test_every_hello_prints_the_timing_critical_config(capsys):
    """v0.117.2: the insert-only config archive hid whether tick_seconds=0.4 was
    still advertised during the incident. Every hello must print the current
    values so the log carries a timestamped series."""
    b = _bot()
    b.on_hello({"config": {"tick_seconds": 0.4, "stale_order_ticks": 0},
                "guild": {}, "tick": 100})
    out = capsys.readouterr().out
    assert "[config] tick_seconds=0.4 stale_order_ticks=0" in out, out
