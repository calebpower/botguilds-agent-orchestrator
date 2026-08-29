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




def _sustained_storm(b, t0=1000, n=12, step=20):
    """Errors SPREAD over n*step ticks (> SQUALL_HOLD): a storm the squall
    shelter must NOT absorb — the fixtures' road into the full bunker."""
    for i in range(n):
        b.on_action_error({"tick": t0 + i * step, "reason": "stale_frame"})

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
    b._poison_ticks.extend(range(2000, 2240, 20))   # v0.121.0: SPREAD past the
    b._health_step(2012, now=100.0 + 1012 * 0.25)   # squall hold -> a true storm
    # the spread entries stay storm-strength until ~t2359, so the clean clock
    # starts THERE; exit lands at ~4359, and 4300 must still be bunkered.
    for t in range(2013, 4300):
        b._health_step(t, now=100.0 + (t - 1000) * 0.25)
    assert b.server_health() == "bunker", "exited before a FULL clean window post-storm"
    for t in range(4300, 4360):
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
    _sustained_storm(bunkered, 2770)      # spread 220 > SQUALL_HOLD: a real storm
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
    _sustained_storm(b, 760)
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
    b._health_bad_at = 1000
    b._poison_bad_at = 1000       # keep the exit clock from firing mid-frame
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
    b._poison_bad_at = 1000
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


# ---------------------------------------------------------------------------
# v0.119.0 staged exit: a full-bench release re-blows the delivery debt (8/8
# exits on 2026-08-28 stormed within ~65 ticks, offset 236). After an EXIT the
# afield budget ramps 2 -> 4 -> 8 -> all; unhealthy = 0; a session that never
# bunkered is unlimited.

def test_embark_stages_pin_their_literals():
    from steemer.bot import EMBARK_STAGES
    assert EMBARK_STAGES == ((300, 2), (600, 4), (900, 8))


def test_embark_budget_ramps_from_the_exit_with_exact_boundaries():
    b = _bot()
    b._health = "ok"
    b._exit_at = 1000
    for tick, want in ((1000, 2), (1299, 2), (1300, 4), (1599, 4),
                       (1600, 8), (1899, 8), (1900, 10**9)):
        b.tick = tick
        assert b.embark_budget() == want, f"t{tick}: {b.embark_budget()} != {want}"


def test_embark_budget_is_zero_unhealthy_and_unlimited_before_any_exit():
    b = _bot()
    b._health = "bunker"
    b._exit_at = 1000
    b.tick = 5000
    assert b.embark_budget() == 0, "bunkered but budget granted"
    b2 = _bot()
    b2._health = "ok"
    b2.tick = 5000
    assert b2.embark_budget() == 10**9, "a never-bunkered session was staged"


def test_the_exit_transition_stamps_the_ramp_anchor():
    b = _bot()
    b._hello_anchor = (1000, 100.0)
    _sustained_storm(b, 780)
    b._health_step(1012, now=100.0 + 12 * 0.25)
    assert b.server_health() == "bunker"
    for t in range(1013, 3400):
        b._health_step(t, now=100.0 + (t - 1000) * 0.25)
    assert b.server_health() == "ok", "never exited in the fixture"
    assert getattr(b, "_exit_at", None) is not None and 3100 <= b._exit_at <= 3200, \
        f"EXIT did not stamp the ramp anchor: {getattr(b, '_exit_at', None)}"


def test_the_spectate_feed_covers_a_quiet_track_feed():
    """v0.119.1: rivals going quiet stalls the track feed; the phantom integral
    then re-arms the bunker clock and starves the exit (observed live: probe read
    the true ~4t while the debt-heal read 41s, t3607630). The spectate poll ticks
    every second regardless — the sample must come from the freshest of BOTH."""
    import time
    from steemer.storage import Storage
    from steemer import intel
    st = Storage(":memory:", commit_every=1)
    st.begin_run("sha", "test/bunker")
    intel.record(st.conn, "track", 995, 999.0, {"map": "vale", "rivals": []})
    intel.record(st.conn, "spectate", 1020, 1000.0, {"guild_count": 2})
    st.flush()
    b = _bot()
    b.on_hello({"config": b.config, "guild": {}, "tick": 1000})
    b.storage = st
    b._health = "bunker"
    b._health_bad_at = 1000
    b._poison_bad_at = 1000
    b._hello_anchor = (1000, time.monotonic() - 600.0)
    b.on_frame(_probe_village(1000, ["c1", "c2"]))
    lag = b._lag_estimate(1000)
    assert lag is not None and abs(lag - 5.0) < 0.01, \
        f"a quiet track feed must not blind the sensor to the spectate clock: {lag}"


def test_exit_runs_on_poison_alone_while_lag_breathes():
    """v0.119.2: the server's delivery BREATHES (true offset 10<->271 in minutes),
    so a lag-windowed exit clock starves the bunker forever with zero rejections.
    Exit = poison clean for the window AND lag small NOW. Driven via the
    differential sample so every lag value is exact."""
    b = _bot()
    b._hello_anchor = (1000, 100.0)
    _sustained_storm(b, 780)

    def step(t, offset_ticks):
        b._offset_sample = (t, offset_ticks)
        b._health_step(t, now=100.0 + (t - 1000) * 0.25)
    step(1012, 2)
    assert b.server_health() == "bunker"
    # poison-clean, lag breathing 2 <-> 240 ticks (0.5s <-> 60s): the spikes must
    # not re-arm the exit clock. The storm entries stay inside their 300t window
    # until ~t1301, so the poison stamp refreshes until then -> earliest exit
    # ~3301. A calm moment at t3300 must still be held by the POISON clock.
    for t in range(1013, 3100):
        step(t, 240 if (t // 200) % 2 else 2)
    step(3100, 2)
    assert b.server_health() == "bunker", "exited before the poison window elapsed"
    # past the window (storm stamps end ~1119 -> eligible ~3119): a spiking step
    # must not exit, and (v0.121.2) neither may the first calm step — the exit
    # needs EXIT_LAG_CALM_TICKS of calm so a one-frame dip can't flap the bunker
    step(3118, 240)
    assert b.server_health() == "bunker", "exited INTO a 60s breath-in"
    for t in range(3120, 3178):
        step(t, 2)
    assert b.server_health() == "bunker", \
        "exited before the lag-calm window elapsed (one-tick flap returns)"
    step(3178, 2)
    assert b.server_health() == "ok", "poison-clean window + calm water never exited"


def test_exit_holds_while_lag_is_bad_right_now():
    b = _bot()
    b._hello_anchor = (1000, 100.0)
    _sustained_storm(b, 780)

    def step(t, offset_ticks):
        b._offset_sample = (t, offset_ticks)
        b._health_step(t, now=100.0 + (t - 1000) * 0.25)
    step(1012, 2)
    assert b.server_health() == "bunker"
    for t in range(1013, 3119):
        step(t, 240)          # poison clean but lag CURRENTLY deep
    # t3119 is the FIRST poison-eligible tick (last stamp ~1119 + 2000). Probe
    # health exactly here: a missing instantaneous gate exits on this very step
    # (the immediate lag-sustained re-entry one step later would mask it from an
    # end-state assertion).
    step(3119, 240)
    assert b.server_health() == "bunker", \
        "exited into deep standing lag — the instantaneous gate is dead"
    for t in range(3302, 3413):
        step(t, 240)
    assert b.server_health() == "bunker"


# ---------------------------------------------------------------------------
# v0.120.0 lag-corrected action stamps: even a 4-char staged release stormed in
# 94 ticks — burst size was never the trigger; the FRAME-tick stamp was. The
# client adds the differential offset to outgoing envelopes.

def test_stamp_offset_pins_fresh_stale_negative_and_the_cap():
    from steemer.bot import STAMP_OFFSET_MAX
    assert STAMP_OFFSET_MAX == 300
    b = _bot()
    b.tick = 1000
    b._offset_sample = (1000, 20)
    assert b.stamp_offset() == 20
    b._offset_sample = (599, 20)            # 401 ticks old: one past the TTL
    assert b.stamp_offset() == 0, "a stale sample still corrected the stamp"
    b._offset_sample = (600, 20)            # exactly the TTL: still authoritative
    assert b.stamp_offset() == 20
    b._offset_sample = (1000, -5)
    assert b.stamp_offset() == 0, "a negative sample must never stamp BACKWARD"
    b._offset_sample = (1000, 999)
    assert b.stamp_offset() == 300, "a suspect huge sample must be capped, not obeyed"
    b2 = _bot()
    b2.tick = 1000
    assert b2.stamp_offset() == 0, "no sample must mean no correction"


def test_the_clean_envelope_carries_the_corrected_stamp_and_probes_do_not():
    from steemer.client import Client

    class _T:
        def __init__(self):
            self.sent = []

        def send(self, m):
            self.sent.append(m)

    b = _bot()
    b.tick = 1000
    b._offset_sample = (1000, 20)
    c = Client.__new__(Client)
    c.transport = _T()
    c.verbose = False
    c.tick = 1000
    c.storage = None
    c.bot = b
    c.send_actions([{"char_uid": "c1", "action": "move", "dir": "N"},
                    {"char_uid": "c2", "action": "say", "text": "sync",
                     "_probe_age": 5}])
    envs = c.transport.sent
    clean = next(m for m in envs if m["actions"][0].get("action") == "move")
    probe = next(m for m in envs if m["actions"][0].get("action") == "say")
    assert clean["tick"] == 1020, f"clean envelope not lag-corrected: {clean}"
    assert probe["tick"] == 995, \
        f"the probe's deliberate aging must stay UNcorrected: {probe}"


def test_a_botless_client_stamps_raw():
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
    c.send_actions([{"char_uid": "c1", "action": "move", "dir": "N"}])
    assert c.transport.sent[0]["tick"] == 1000


def test_envelope_ticks_are_monotonic_when_the_correction_recedes():
    """v0.120.1: run 294 — three chars locked out at ~1 stale_frame/tick after
    the differential correction receded below an earlier slightly-ahead stamp
    (the per-char order rule ratchets). Envelope ticks never go backward."""
    from steemer.client import Client

    class _T:
        def __init__(self):
            self.sent = []

        def send(self, m):
            self.sent.append(m)

    b = _bot()
    b.tick = 1000
    b._offset_sample = (1000, 20)
    c = Client.__new__(Client)
    c.transport = _T()
    c.verbose = False
    c.tick = 1000
    c.storage = None
    c.bot = b
    c.send_actions([{"char_uid": "c1", "action": "move", "dir": "N"}])
    assert c.transport.sent[-1]["tick"] == 1020
    # the sample expires; our tick has only advanced 5 — a raw stamp of 1005
    # would be BELOW the char's last-accepted 1020 and ratchet the lockout
    b.tick = c.tick = 1005
    b._offset_sample = None
    c.send_actions([{"char_uid": "c1", "action": "move", "dir": "N"}])
    assert c.transport.sent[-1]["tick"] == 1020, \
        f"envelope tick went backward: {c.transport.sent[-1]}"
    # once the raw clock passes the high-water mark, stamps track it again
    b.tick = c.tick = 1030
    c.send_actions([{"char_uid": "c1", "action": "move", "dir": "N"}])
    assert c.transport.sent[-1]["tick"] == 1030


# ---------------------------------------------------------------------------
# v0.121.0 squall shelter: run 295 measured 4 rejection bursts of width 0-72t
# with gaps 871-3900t — each cost a full recall + 2000t exit. A sharp burst now
# gets a stand-still hold; the bunker is reserved for weather that PERSISTS
# (spread > SQUALL_HOLD or squalls clustering).

def test_squall_literals_are_pinned():
    from steemer.bot import (SQUALL_TRIGGER_N, SQUALL_TRIGGER_WINDOW, SQUALL_HOLD,
                             SQUALL_ESCALATE_N, SQUALL_ESCALATE_WINDOW)
    assert (SQUALL_TRIGGER_N, SQUALL_TRIGGER_WINDOW, SQUALL_HOLD,
            SQUALL_ESCALATE_N, SQUALL_ESCALATE_WINDOW) == (6, 50, 150, 3, 1000)


def test_a_tight_burst_squalls_and_passes_without_the_bunker_tax():
    """The run-295 shape: 60 rejections 16 ticks wide. Squall, hold, resume after
    150 quiet ticks — no recall, no 2000t exit window."""
    b = _bot()
    for i in range(60):
        b.on_action_error({"tick": 1000 + (i % 16), "reason": "stale_frame"})
    b._health_step(1016, now=100.0)
    assert b.server_health() == "squall", \
        f"a 16t burst must squall, not {b.server_health()}"
    assert b.embark_budget() == 0, "embarks flowed during a squall"
    for t in range(1017, 1166):
        b._health_step(t, now=100.0 + (t - 1016) * 0.25)
    assert b.server_health() == "squall", "resumed before the quiet hold elapsed"
    b._health_step(1170, now=100.0 + 154 * 0.25)
    assert b.server_health() == "ok", "the squall never passed"


def test_a_storm_spanning_past_the_hold_still_bunkers():
    b = _bot()
    _sustained_storm(b, 780)                      # spread 220 > SQUALL_HOLD
    b._health_step(1012, now=100.0)
    assert b.server_health() == "bunker", \
        f"a 220t-spread storm must bunker, not {b.server_health()}"


def test_three_squalls_inside_the_window_escalate_to_the_bunker():
    b = _bot()
    t0 = 1000
    for n in range(3):
        for i in range(8):
            b.on_action_error({"tick": t0 + i, "reason": "stale_frame"})
        b._health_step(t0 + 8, now=100.0 + n)
        if n < 2:
            assert b.server_health() == "squall", f"squall {n+1} did not hold"
            # let it pass before the next one
            for t in range(t0 + 9, t0 + 8 + 155):
                b._health_step(t, now=100.0 + n + (t - t0) * 0.01)
            assert b.server_health() == "ok"
            t0 += 300
    assert b.server_health() == "bunker", \
        "the third squall in 1000t did not escalate to the bunker"


def test_field_chars_stand_still_through_a_squall_and_retreat_in_a_bunker():
    """Two oracles on the field branch: a squall issues NO actions for a fielded
    char; a bunker still offers the retreat."""
    from tests.test_decision_engine import _bot as _debot, _world_field_frame
    bot = _debot()
    corridor = [[0, y, "floor"] for y in range(0, 8)]
    frame = _world_field_frame("vale", corridor, [])
    bot.on_frame(frame)                     # baseline: sees the world
    bot._health = "squall"
    bot._squall_until = frame["tick"] + 150   # mid-squall, not yet passed
    held = bot.on_frame(frame)
    assert not held, f"a fielded char acted through a squall: {held}"
    bot._health = "bunker"
    bot._poison_bad_at = frame["tick"]        # standing storm: the exit clock holds
    acts = bot.on_frame(frame)
    assert any(a.get("action") == "move" for a in acts), \
        f"the bunker retreat vanished: {acts}"


def test_resume_stragglers_do_not_merge_with_the_spent_burst():
    """v0.121.1 (observed live t3646930): a few rejections at squall-resume merged
    with the original burst still inside the 300t window and read as a >150t
    "sustained" storm — bunkering four ticks after the squall passed. A passed
    squall clears the ledger; stragglers start fresh."""
    b = _bot()
    for i in range(60):
        b.on_action_error({"tick": 1000 + (i % 16), "reason": "stale_frame"})
    b._health_step(1016, now=100.0)
    assert b.server_health() == "squall"
    for t in range(1017, 1167):
        b._health_step(t, now=100.0 + (t - 1016) * 0.25)
    b._health_step(1170, now=100.0 + 154 * 0.25)
    assert b.server_health() == "ok", "fixture: the squall never passed"
    for t in (1171, 1173, 1175):              # stragglers at resume
        b.on_action_error({"tick": t, "reason": "stale_frame"})
    b._health_step(1176, now=100.0 + 160 * 0.25)
    assert b.server_health() == "ok", \
        f"three stragglers after a passed squall escalated to {b.server_health()}"


def test_a_lag_dip_cannot_flap_a_one_tick_bunker_cycle(capsys):
    """v0.121.2 (live t3655454->56): enter needs 120 SUSTAINED bad ticks, but exit
    was instantaneous — one breathing dip flapped ENTER->EXIT in a tick. Exit now
    needs EXIT_LAG_CALM_TICKS of calm. Also pins the escalation why-string."""
    from steemer.bot import EXIT_LAG_CALM_TICKS
    assert EXIT_LAG_CALM_TICKS == 60
    b = _bot()
    b._hello_anchor = (1000, 100.0)

    def step(t, off):
        b._offset_sample = (t, off)
        b._health_step(t, now=100.0 + (t - 1000) * 0.25)
    for t in range(1000, 1125):
        step(t, 240)                     # sustained deep lag -> bunker
    assert b.server_health() == "bunker"
    step(1125, 2)                        # one-frame dip
    assert b.server_health() == "bunker", "a single calm frame flapped the exit"
    for t in range(1126, 1184):
        step(t, 2)
    assert b.server_health() == "bunker", "exited inside the calm window"
    step(1184, 2)                        # last bad frame was 1124: exactly 60 calm
    assert b.server_health() == "ok", "never exited after 60 calm ticks"


def test_the_escalation_names_itself_not_a_poison_storm(capsys):
    b = _bot()
    t0 = 1000
    for n in range(3):
        for i in range(8):
            b.on_action_error({"tick": t0 + i, "reason": "stale_frame"})
        b._health_step(t0 + 8, now=100.0 + n)
        if n < 2:
            for t in range(t0 + 9, t0 + 8 + 155):
                b._health_step(t, now=100.0 + n + (t - t0) * 0.01)
            t0 += 300
    out = capsys.readouterr().out
    assert "squalls/1000t — persistent weather" in out, \
        f"the escalation still blames a poison storm: {out[-200:]}"


# ---------------------------------------------------------------------------
# v0.122.0 scope quarantine: a LONE sick char (the dead c20054 solo-spammed 95
# rejections; per-char niv divergence does the same) must not bench the guild.
# A global burst (others also rejecting) is squall weather and never quarantines.

def _perr(b, tick, uid):
    b.on_action_error({"tick": tick, "reason": "stale_frame", "char_uid": uid})


def test_a_lone_spammer_is_quarantined_at_exactly_the_threshold(capsys):
    from steemer.bot import CHAR_QUAR_N, CHAR_QUAR_WINDOW, CHAR_QUAR_TTL
    assert (CHAR_QUAR_N, CHAR_QUAR_WINDOW, CHAR_QUAR_TTL) == (5, 200, 600)
    b = _bot()
    for i in range(4):
        _perr(b, 1000 + i * 20, "sick")
    assert "sick" not in getattr(b, "_quarantine", {}), "quarantined below threshold"
    _perr(b, 1080, "sick")                    # the 5th within 200t
    assert getattr(b, "_quarantine", {}).get("sick") == 1080 + CHAR_QUAR_TTL, \
        "the 5th lone rejection did not quarantine"
    assert b._poison_ticks == [], "the spammer's ticks were not scrubbed"
    # two oracles: further spam neither counts nor re-prints
    for i in range(30):
        _perr(b, 1100 + i, "sick")
    assert b._poison_ticks == [], "quarantined errors still fed the guild signal"
    b._health_step(1140, now=100.0)
    assert b.server_health() == "ok", \
        f"a lone quarantined spammer benched the guild: {b.server_health()}"
    assert b._quarantine["sick"] == 1080 + CHAR_QUAR_TTL, \
        "quarantined errors re-entered the ledger (the TTL advanced)"
    out = capsys.readouterr().out
    assert out.count("[quarantine] sick") == 1, \
        f"re-quarantine churn: {out.count('[quarantine] sick')} prints"


def test_a_global_burst_never_quarantines():
    b = _bot()
    # one char crosses 5 while THREE others are also bursting inside 50t
    for i, uid in enumerate(["a", "b", "c"] * 3):
        _perr(b, 1000 + i, uid)
    for i in range(5):
        _perr(b, 1010 + i, "x")
    assert "x" not in getattr(b, "_quarantine", {}), \
        "quarantined during a global burst — squall weather misattributed"
    assert len(b._poison_ticks) == 14, \
        f"global-burst errors must all count: {len(b._poison_ticks)}"


def test_quarantine_expires_and_uidless_errors_still_count():
    from steemer.bot import CHAR_QUAR_TTL
    b = _bot()
    for i in range(5):
        _perr(b, 1000 + i, "sick")
    until = b._quarantine["sick"]
    _perr(b, until + 1, "sick")               # past the TTL: counts again
    assert b._poison_ticks == [until + 1], \
        f"post-TTL error did not count: {b._poison_ticks}"
    b2 = _bot()
    b2.on_action_error({"tick": 500, "reason": "stale_frame"})   # no char_uid
    assert b2._poison_ticks == [500], "uidless poison must still count"
