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

    def true_wall(t):
        return 100.0 + (t - 1000) * 0.25
    # SPIKE: 60 ticks of 4s delay (under the 120-tick entry grace), then a PHYSICAL
    # recovery — the delayed queue flushes in a burst; the arrival clock must stay
    # MONOTONIC (the first draft ran time backwards at the boundary, corrupting the
    # measured slope — a fixture bug, not a sensor bug).
    for t in range(1001, 1061):
        b._health_step(t, now=true_wall(t) + 4.0)
    assert b.server_health() == "ok", "a lag spike under the grace benched the guild"
    burst_floor = true_wall(1060) + 4.0
    for t in range(1061, 1200):
        b._health_step(t, now=max(true_wall(t), burst_floor + 0.001 * (t - 1060)))
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


def test_probe_actions_ride_their_own_aged_envelope():
    """v0.117.3: an action with _probe_age=K goes out in a separate envelope tagged
    tick-K; the marker never reaches the wire; normal actions are unaffected."""
    from steemer.client import Client
    from steemer import protocol as p

    class _T:
        def __init__(self):
            self.sent = []

        def send(self, m):
            self.sent.append(m)

    c = Client.__new__(Client)
    c.transport = _T()
    c.verbose = False
    c.tick = 1000
    c.storage = None                      # _mirror no-ops (test/replay path)
    c.send_actions([{"char_uid": "c1", "action": "say", "text": "sync",
                     "_probe_age": 5},
                    {"char_uid": "c2", "action": "move", "dir": "N"}])
    assert len(c.transport.sent) == 2
    probe_env = next(m for m in c.transport.sent if len(m["actions"]) == 1
                     and m["actions"][0]["action"] == "say")
    norm_env = next(m for m in c.transport.sent if m["actions"][0]["action"] == "move")
    assert probe_env["tick"] == 995, f"probe not aged: {probe_env}"
    assert norm_env["tick"] == 1000
    assert "_probe_age" not in probe_env["actions"][0], "marker leaked to the wire"


def _probe_village(tick, here):
    return {"type": "frame", "world": "village", "tick": tick, "events": [],
            "guild": {"gold": 5, "chars_here": here, "chars_by_world": {}},
            "shop": {"stock": []}, "chars": []}


def test_the_probe_fires_on_cadence_healthy_only_and_cycles_K():
    from steemer.bot import PROBE_EVERY, PROBE_AGES
    assert (PROBE_EVERY, PROBE_AGES) == (600, (5, 8, 13, 21, 34, 55))
    b = _bot()
    b.on_hello({"config": b.config, "guild": {}, "tick": 400})   # a probe needs a
    # session baseline — bots that never hello'd (every unit fixture) never probe
    acts = b.on_frame(_probe_village(1000, ["c1"]))
    probes = [a for a in acts if a.get("_probe_age") is not None]
    assert len(probes) == 1 and probes[0]["_probe_age"] == 5, f"first probe: {acts}"
    # cadence: still inside the probe interval — nothing may fire
    acts2 = b.on_frame(_probe_village(1300, ["c1"]))
    assert not [a for a in acts2 if a.get("_probe_age") is not None], "cadence ignored"
    # next probe cycles to K=1
    acts3 = b.on_frame(_probe_village(1601, ["c1"]))
    probes3 = [a for a in acts3 if a.get("_probe_age") is not None]
    assert len(probes3) == 1 and probes3[0]["_probe_age"] == 8, f"K did not cycle: {acts3}"


def test_the_probe_never_fires_while_bunkered():
    b = _bot()
    b.on_hello({"config": b.config, "guild": {}, "tick": 400})
    for i in range(12):
        b.on_action_error({"tick": 990 + i, "reason": "stale_frame"})
    acts = b.on_frame(_probe_village(1002, ["c1"]))
    assert not [a for a in acts if a.get("_probe_age") is not None], \
        "probed during a storm — measures nothing, adds pressure"


def test_a_bot_with_no_session_never_probes():
    """The anchor gate: every unit fixture in the suite constructs a bot without a
    hello — none of them may grow probe actions (17 tests broke when they did)."""
    b = _bot()
    acts = b.on_frame(_probe_village(9000, ["c1"]))
    assert not [a for a in acts if a.get("_probe_age") is not None]


def test_the_lag_sensor_trusts_measurement_over_advertisement():
    """v0.117.5: the 08-25 server advertised tick_seconds=0.4 while running 0.25 —
    a detector trusting the advertisement computes real 4-second lag as EARLY and
    never alarms. With measured samples present, the advertisement is ignored."""
    b = _bot()
    b.config["tick_seconds"] = 0.4            # the lie
    b._hello_anchor = (1000, 100.0)
    # feed 30 frames at the TRUE 0.25 cadence, each arriving 4s late
    for t in range(1001, 1031):
        b._health_step(t, now=100.0 + (t - 1000) * 0.25 + 4.0)
    lag = b._lag_estimate(1030, now=100.0 + 30 * 0.25 + 4.0)
    assert lag is not None and lag > 3.5, \
        f"the advertised 0.4 lie blinded the sensor: lag reads {lag}"


def test_the_pair_probe_emits_fresh_then_aged_for_the_same_char():
    """v0.117.5 order discriminator: every 4th probe is (fresh say, K=5 aged say),
    same char, same batch — a time-window validator accepts both, an order
    validator rejects the aged one."""
    b = _bot()
    b.on_hello({"config": b.config, "guild": {}, "tick": 400})
    pair = None
    for i in range(5):
        acts = b.on_frame(_probe_village(1000 + i * 700, ["c1"]))
        says = [a for a in acts if a.get("action") == "say"]
        if len(says) == 2:
            pair = says
            break
    assert pair is not None, "the pair probe never fired in 5 cycles"
    fresh, aged = pair
    assert "_probe_age" not in fresh and aged.get("_probe_age") == 5
    assert fresh["char_uid"] == aged["char_uid"], "pair split across chars"
