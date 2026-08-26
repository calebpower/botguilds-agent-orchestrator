"""v0.116.0 — capability-KPI anomalies (operator-directed after the 2026-08-26 outage:
"wake me on a deviation in normal behavior — e.g. a drastic change in kpis, or a ML
model that fails"). Fielded-collapse is the detector that would have flagged that
outage at minute ~2.5 instead of minute 90; xp-stall flags the leveling engine dying;
the models runtime-failure line is proven to EMIT (it existed but was never tested)."""
import json

from steemer.anomaly import (KpiMonitor, FIELDED_COLLAPSE_TICKS,
                             FIELDED_COLLAPSE_MAX, FIELDED_BENCH_MIN,
                             XP_STALL_WINDOW)
from steemer.bot import GuildBot


def test_pinned_literals():
    assert (FIELDED_COLLAPSE_TICKS, FIELDED_COLLAPSE_MAX, FIELDED_BENCH_MIN,
            XP_STALL_WINDOW) == (600, 1, 5, 3000), \
        "KPI tuning moved; re-read the literals in these tests"


def test_a_sustained_fielded_collapse_flags_once_then_cools():
    m = KpiMonitor()
    flags = []
    for t in range(1000, 1000 + 2000, 10):
        flags += m.observe(t, fielded=1, bench=8)
    subs = [a["subtype"] for a in flags]
    assert subs.count("kpi:fielded_collapse") == 2, \
        (f"expected flag at ~601 ticks and one cooldown re-flag at ~1200 later, got "
         f"{len(subs)}: {subs}")


def test_recovery_resets_the_collapse_clock():
    m = KpiMonitor()
    for t in range(1000, 1500, 10):                # 500 ticks collapsed (below 600)
        assert not m.observe(t, fielded=1, bench=8)
    assert not m.observe(1510, fielded=6, bench=3)  # recovery
    for t in range(1520, 2100, 10):                # collapsed again, clock restarted
        flags = m.observe(t, fielded=0, bench=8)
        assert not [a for a in flags if t - 1520 < 600], \
            "the collapse clock survived a recovery"


def test_a_tiny_roster_fielding_nobody_is_not_a_collapse():
    m = KpiMonitor()
    for t in range(1000, 3000, 10):
        assert not m.observe(t, fielded=0, bench=4), \
            "flagged a roster too small to owe anyone to the field"


def test_xp_stall_needs_a_transition_not_a_cold_start():
    m = KpiMonitor()
    # cold start: never any xp -> never a stall
    assert not m.observe(10_000, fielded=5, bench=5)
    # activity, then silence
    m2 = KpiMonitor()
    for t in range(10_000, 10_050, 10):
        m2.note_xp(t, 1)
    flags = m2.observe(10_040 + 3000 + 10, fielded=5, bench=5)
    assert [a["subtype"] for a in flags] == ["kpi:xp_stall"], f"got {flags}"
    # continuing activity -> no stall
    m3 = KpiMonitor()
    for t in range(10_000, 16_000, 500):
        m3.note_xp(t, 1)
        assert not [a for a in m3.observe(t, fielded=5, bench=5)
                    if a["subtype"] == "kpi:xp_stall"]


def _village(tick, by_world, here_n):
    return {"type": "frame", "world": "village", "tick": tick, "events": [],
            "guild": {"gold": 5, "chars_here": [f"h{i}" for i in range(here_n)],
                      "chars_by_world": by_world},
            "shop": {"stock": []}, "chars": []}


def test_the_collapse_reaches_the_anomaly_channel_through_the_real_bot(capsys):
    """Wiring: 700 ticks of village frames showing 8 benched / 0 fielded must print
    the [anomaly] kpi:fielded_collapse line — the exact line the wake-up monitor
    greps. Through GuildBot.on_frame, not the monitor class."""
    bot = GuildBot(strategy="explorer")
    bot.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 10,
                  "maps": [{"id": "vale"}]}
    for t in range(5000, 5700, 10):
        bot.on_frame(_village(t, {}, 8))
    out = capsys.readouterr().out
    assert "[anomaly] kpi:fielded_collapse" in out, \
        f"the collapse never reached the channel: {out[-400:]}"


def test_a_models_runtime_failure_emits_the_disabled_line(capsys):
    """The [models] line existed for LOAD failures; this pins the RUNTIME fail-closed
    path emitting too (a poisoned artifact that explodes mid-scoring)."""
    from steemer import models
    models._cache["death_risk"] = {"feature_names": ["a"], "base_score": "boom",
                                   "trees": [], "schema_version": None}
    models._warned.discard("death_risk")
    try:
        assert models.score_death_risk({"a": 1.0}) is None
        out = capsys.readouterr().out
        assert "[models] death_risk disabled: scoring failed" in out, \
            f"runtime failure was silent: {out!r}"
    finally:
        models._cache.pop("death_risk", None)
        models._warned.discard("death_risk")


def test_sheltering_suppresses_kpis_and_restarts_the_collapse_clock():
    """v0.116.2: a shelter-held bench (deliberate fielded=0) must not flag —
    and on release the 600-tick collapse measurement starts FRESH, so a healthy
    post-release embark wave has time to land before anyone cries collapse."""
    m = KpiMonitor()
    # the collapse clock is ALREADY RUNNING when the shelter engages (fielded had
    # collapsed for 400 ticks first) — the reset must wipe that epoch, else the
    # post-release flag fires instantly off the stale clock.
    for t in range(600, 1000, 10):
        m.observe(t, fielded=0, bench=10)
    for t in range(1000, 4000, 10):
        assert not m.observe(t, fielded=0, bench=10, sheltering=True), \
            "flagged the intentional shelter bench-down"
    # released at t=4000; collapse conditions persist (a REAL problem now) — the
    # flag must come only after a fresh full window, not instantly.
    flags = []
    for t in range(4000, 4600, 10):
        flags += m.observe(t, fielded=0, bench=10)
    assert not flags, f"flagged before a fresh post-release window elapsed: {flags}"
    flags = m.observe(4610, fielded=0, bench=10)
    assert [a["subtype"] for a in flags] == ["kpi:fielded_collapse"], \
        "a real post-release collapse never flagged"


def test_the_shelter_flag_reaches_the_kpi_monitor_through_the_real_bot(capsys):
    """Wiring: a poison error stamps bot._storm_last; the village frames that follow
    must NOT print kpi:fielded_collapse even after 700 sheltered ticks."""
    bot = GuildBot(strategy="explorer")
    bot.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 10,
                  "maps": [{"id": "vale"}]}
    for i in range(12):                       # v0.117.0: a STORM bunkers, not a stray
        bot.on_action_error({"tick": 4980 + i, "reason": "stale_frame"})
    for t in range(5000, 5700, 10):
        bot.on_frame(_village(t, {}, 8))
    out = capsys.readouterr().out
    assert "kpi:fielded_collapse" not in out, \
        f"the sheltered bench-down still flagged: {out[-300:]}"
