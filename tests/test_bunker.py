"""v0.117.0 — the server-health BUNKER (operator-directed): watch for server trouble
client-side (sustained frame lag via the hello anchor, or a poison-rejection storm),
recall the field to the village, hold embarks, and resume dynamically once the server
is clean for a full window. Grace both ways: a lag SPIKE never benches the guild and
a brief lull never un-benches it."""
from steemer.bot import (GuildBot, HEALTH_LAG_S, HEALTH_ENTER_TICKS,
                         HEALTH_POISON_N, HEALTH_POISON_WINDOW, HEALTH_EXIT_TICKS)


def test_pinned_literals():
    assert (HEALTH_LAG_S, HEALTH_ENTER_TICKS, HEALTH_POISON_N,
            HEALTH_POISON_WINDOW, HEALTH_EXIT_TICKS) == (8.0, 120, 10, 300, 2000)


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
    # SPIKE: 60 ticks of 10s delay (under the 120-tick entry grace), then a PHYSICAL
    # recovery — the delayed queue flushes in a burst; the arrival clock must stay
    # MONOTONIC (the first draft ran time backwards at the boundary, corrupting the
    # measured slope — a fixture bug, not a sensor bug).
    for t in range(1001, 1061):
        b._health_step(t, now=true_wall(t) + 10.0)
    assert b.server_health() == "ok", "a lag spike under the grace benched the guild"
    burst_floor = true_wall(1060) + 10.0
    for t in range(1061, 1200):
        b._health_step(t, now=max(true_wall(t), burst_floor + 0.001 * (t - 1060)))
    assert b.server_health() == "ok"
    # SUSTAINED: 121 ticks of 10s lag (over the 8s threshold)
    for t in range(1200, 1322):
        b._health_step(t, now=true_wall(t) + 10.0)
    assert b.server_health() == "bunker", "sustained lag never bunkered"


def test_bunker_exits_only_after_a_full_clean_window():
    b = _bot()
    b._hello_anchor = (1000, 100.0)
    for t in range(1000, 1130):
        b._health_step(t, now=100.0 + (t - 1000) * 0.25 + 10.0)
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
    # feed 30 frames at the TRUE 0.25 cadence, each arriving 10s late
    for t in range(1001, 1031):
        b._health_step(t, now=100.0 + (t - 1000) * 0.25 + 10.0)
    lag = b._lag_estimate(1030, now=100.0 + 30 * 0.25 + 10.0)
    assert lag is not None and lag > 9.5, \
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


def test_frozen_debt_requests_a_rehello_and_storms_do_not():
    """v0.117.7: bunkered + poison-quiet + standing sub-threshold lag = the frozen-debt
    deadlock (observed live at 7s vs the 8s arm) -> request a curative re-hello. A
    poison STORM must NOT use this path (the poison self-heal owns storms)."""
    b = _bot()
    b._hello_anchor = (1000, 100.0)
    b._health = "bunker"
    # frozen debt: constant 5s lag, no poison
    for t in range(1001, 1030):
        b._health_step(t, now=100.0 + (t - 1000) * 0.25 + 5.0)
    assert getattr(b, "request_rehello", False), "the frozen-debt cure never fired"
    b.request_rehello = False
    # spacing: no second request inside HEALTH_EXIT_TICKS
    for t in range(1030, 1200):
        b._health_step(t, now=100.0 + (t - 1000) * 0.25 + 5.0)
    assert not getattr(b, "request_rehello", False), "debt-heal flapped inside spacing"
    # storm: poison present -> the debt path stays quiet (poison heal owns it)
    b2 = _bot()
    b2._hello_anchor = (1000, 100.0)
    b2._health = "bunker"
    b2._poison_ticks = list(range(990, 1002))
    b2._health_step(1002, now=100.0 + 2 * 0.25 + 5.0)
    assert not getattr(b2, "request_rehello", False), \
        "debt-heal fired during a poison storm"


def test_the_client_honors_the_rehello_request_with_spacing():
    from steemer.client import Client
    from steemer import protocol as p

    class _T:
        def __init__(self, frames):
            self.queued = list(frames)
            self.sent = []
            self.connects = 0

        def poll(self, timeout_ms=0):
            return self.queued.pop(0) if self.queued else None

        def send(self, m):
            self.sent.append(m)

    c = Client.__new__(Client)
    frames = [{"type": p.FRAME, "tick": 5000 + i, "world": "village", "seq": i + 1,
               "visible": {"tiles": []}, "chars": []} for i in range(2)]
    c.transport = _T(frames)
    c.verbose = False
    c.storage = None
    c.running = True
    c.connected = True
    c.tick = 0
    c._last_seq = None
    c._refresh_at = 0.0
    c._tiles_mem = {}
    c._visible = {}
    c._pending = None
    connects = []
    c._connect = lambda: connects.append(c.tick)

    class _B:
        request_rehello = True
        config = {}

        def on_frame(self, f):
            return []
    c.bot = _B()
    c._loop(max_ticks=1)
    # the drain batches both queued frames, so tick reads 5001 at honor time
    assert connects == [5001], f"request not honored exactly once: {connects}"
    # second request inside HEAL_MIN_SPACING is refused
    c.bot.request_rehello = True
    c.transport.queued = [{"type": p.FRAME, "tick": 5002, "world": "village",
                           "seq": 3, "visible": {"tiles": []}, "chars": []}]
    c.running = True
    c._loop(max_ticks=1)
    assert connects == [5001], f"honored inside the spacing guard: {connects}"


# ---------------------------------------------------------------------------
# v0.118.0 forward-stamp probe: stale_order_ticks=0 x standing session debt kills
# every bunker exit within ticks (six-for-six, 2026-08-28). Measure whether a say
# stamped at the ESTIMATED CURRENT server tick renders while a normal-stamped one
# is rejected — different chars, same batch, so the per-char order rule can't
# confound the reading.

def test_fwd_probe_pins_its_literal():
    from steemer.bot import FWD_PROBE_MIN_TICKS
    assert FWD_PROBE_MIN_TICKS == 4


def _debt_bot(debt_s):
    import time
    b = _bot()
    b.on_hello({"config": b.config, "guild": {}, "tick": 1000})
    b._health = "bunker"
    b._health_bad_at = 1000       # keep the exit clock from firing mid-frame
    b._hello_anchor = (1000, time.monotonic() - debt_s)
    return b


def _fwd_says(acts):
    return [a for a in acts if str(a.get("text", "")).startswith("fwd")]


def test_fwd_probe_fires_bunkered_normal_plus_forward_on_DIFFERENT_chars():
    b = _debt_bot(5.0)
    acts = b.on_frame(_probe_village(1000, ["c1", "c2"]))
    pair = _fwd_says(acts)
    assert len(pair) == 2, f"fwd pair missing: {acts}"
    normal, fwd = pair
    assert "_probe_age" not in normal and normal["char_uid"] == "c1"
    assert fwd["char_uid"] == "c2", "pair on ONE char — the order rule confounds it"
    assert fwd["_probe_age"] == -20, \
        f"5.0s debt at 0.25s/tick must stamp +20 ticks: {fwd}"


def test_fwd_probe_fires_at_the_exact_noise_floor():
    b = _debt_bot(1.0)            # 4 ticks — the FWD_PROBE_MIN_TICKS boundary
    pair = _fwd_says(b.on_frame(_probe_village(1000, ["c1", "c2"])))
    assert len(pair) == 2 and pair[1]["_probe_age"] == -4, f"boundary held out: {pair}"


def test_fwd_probe_holds_healthy_shallow_alone_and_on_cadence():
    import time
    # healthy: nothing to measure (the regular probe may fire; it says 'sync')
    b = _bot()
    b.on_hello({"config": b.config, "guild": {}, "tick": 1000})
    b._hello_anchor = (1000, time.monotonic() - 5.0)
    assert not _fwd_says(b.on_frame(_probe_village(1000, ["c1", "c2"]))), \
        "fwd probe fired while healthy"
    # shallow: 0.75s = 3 ticks, under the noise floor
    b = _debt_bot(0.75)
    assert not _fwd_says(b.on_frame(_probe_village(1000, ["c1", "c2"]))), \
        "fwd probe fired inside the estimator's noise"
    # alone: the discriminator needs two chars
    b = _debt_bot(5.0)
    assert not _fwd_says(b.on_frame(_probe_village(1000, ["c1"]))), \
        "fwd probe fired with one char — order rule confounds"
    # cadence: a second pair inside PROBE_EVERY is retry pressure, not measurement
    b = _debt_bot(5.0)
    assert len(_fwd_says(b.on_frame(_probe_village(1000, ["c1", "c2"])))) == 2
    b._hello_anchor = (1300, b._hello_anchor[1] + 75.0)   # keep the debt standing
    assert not _fwd_says(b.on_frame(_probe_village(1300, ["c1", "c2"]))), \
        "fwd probe ignored its cadence"


def test_a_negative_probe_age_rides_a_FORWARD_envelope():
    """The client's aged-envelope path is the transport: age -20 must stamp
    tick+20, and the marker must never reach the wire."""
    from steemer.client import Client

    class _T:
        def __init__(self):
            self.sent = []

        def send(self, m):
            self.sent.append(m)

    c = Client.__new__(Client)
    c.transport = _T()
    c.verbose = False
    c.tick = 1000
    c.storage = None
    c.send_actions([{"char_uid": "c1", "action": "say", "text": "fwd-a"},
                    {"char_uid": "c2", "action": "say", "text": "fwd-b",
                     "_probe_age": -20}])
    envs = c.transport.sent
    assert len(envs) == 2
    fwd_env = next(m for m in envs if m["actions"][0].get("text") == "fwd-b")
    norm_env = next(m for m in envs if m["actions"][0].get("text") == "fwd-a")
    assert fwd_env["tick"] == 1020, f"forward stamp missing: {fwd_env}"
    assert norm_env["tick"] == 1000
    assert "_probe_age" not in fwd_env["actions"][0], "marker leaked to the wire"


# ---------------------------------------------------------------------------
# v0.118.1 differential debt sensor: the anchor INTEGRAL read a phantom 649s while
# the true debt was 6 ticks (2026-08-28, server tick rate oscillating 3.4-6.1 t/s)
# — it fired a spurious debt-heal and fed the FWD probe a +73 stamp. The sidecar's
# track rows carry the public server tick: (track_tick - our_tick) is a direct
# differential measurement, trusted only while the feed is AHEAD of our stream.

def _phantom_bot(track_tick):
    """A REAL-storage bot whose anchor integral would read minutes of phantom
    lag, with one genuine intel track row at the given public tick."""
    import time
    from steemer.storage import Storage
    from steemer import intel
    st = Storage(":memory:", commit_every=1)
    st.begin_run("sha", "test/bunker")
    intel.record(st.conn, "track", track_tick, 1000.0,
                 {"map": "vale", "rivals": []})
    st.flush()
    b = _bot()
    b.on_hello({"config": b.config, "guild": {}, "tick": 1000})
    b.storage = st
    b._health = "bunker"
    b._health_bad_at = 1000
    b._hello_anchor = (1000, time.monotonic() - 600.0)     # 600s of phantom
    return b


def test_the_differential_sample_overrides_the_phantom_integral():
    b = _phantom_bot(1020)   # true debt: 20 ticks
    b.on_frame(_probe_village(1000, ["c1", "c2"]))              # refreshes hints
    lag = b._lag_estimate(1000)
    assert lag is not None and abs(lag - 5.0) < 0.01, \
        f"20-tick true debt at 0.25 s/t must read 5.0s, not the integral: {lag}"


def test_a_track_feed_BEHIND_our_stream_disqualifies_itself():
    b = _phantom_bot(995)    # sidecar is stale
    b.on_frame(_probe_village(1000, ["c1", "c2"]))
    assert getattr(b, "_offset_sample", None) is None, \
        "a behind-the-stream track row must never become a debt sample"
    lag = b._lag_estimate(1000)
    assert lag is not None and lag > 400, "fallback to the anchor integral missing"


def test_the_sample_expires_at_its_TTL_boundary():
    from steemer.bot import OFFSET_SAMPLE_TTL
    assert OFFSET_SAMPLE_TTL == 400
    b = _phantom_bot(1020)
    b.on_frame(_probe_village(1000, ["c1", "c2"]))
    at_ttl = b._lag_estimate(1400)          # exactly the 400-tick TTL
    assert at_ttl is not None and abs(at_ttl - 5.0) < 0.01, \
        f"the sample must hold AT the TTL boundary: {at_ttl}"
    past_ttl = b._lag_estimate(1401)        # one past it
    assert past_ttl is not None and past_ttl > 400, \
        f"one past the TTL must fall back to the integral: {past_ttl}"


def test_the_fwd_probe_stamps_from_the_differential_not_the_phantom():
    b = _phantom_bot(1020)
    acts = b.on_frame(_probe_village(1000, ["c1", "c2"]))
    pair = _fwd_says(acts)
    assert len(pair) == 2 and pair[1]["_probe_age"] == -20, \
        f"the probe must stamp the TRUE 20-tick debt, not the 600s phantom: {pair}"
