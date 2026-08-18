"""The live anomaly monitor (steemer/anomaly.py) and its wiring into GuildBot:
an action-error family that spikes within a rolling window is flagged once (with
cooldown), a quiet stream produces nothing, and the bot persists the flag."""

from steemer.anomaly import AnomalyMonitor
from steemer.bot import GuildBot
from steemer.storage import Storage


def test_flags_a_spiking_family_and_stays_quiet_below_threshold():
    m = AnomalyMonitor(window_ticks=100, spike_count=5, cooldown_ticks=50)
    # 4 in the window -> below threshold, nothing.
    out = [m.record(t, "no_such_character") for t in range(1, 5)]
    assert out == [None, None, None, None]
    # the 5th within the window trips the spike.
    a = m.record(5, "no_such_character")
    assert a is not None and a["subtype"] == "error_spike:no_such_character"
    assert a["count"] == 5 and a["reason"] == "no_such_character"


def test_a_different_family_does_not_borrow_anothers_count():
    # counts are per-family: 4 of A + 4 of B (each below 5) must NOT flag.
    m = AnomalyMonitor(window_ticks=100, spike_count=5, cooldown_ticks=50)
    outs = []
    for t in range(1, 5):
        outs.append(m.record(t, "no_such_character"))
        outs.append(m.record(t, "not_in_village"))
    assert all(o is None for o in outs)


def test_old_errors_evict_so_a_slow_trickle_never_spikes():
    m = AnomalyMonitor(window_ticks=100, spike_count=5, cooldown_ticks=1)
    # one error every 100 ticks: the window only ever holds ~1, never 5.
    assert all(m.record(t, "roster_cap") is None for t in range(0, 2000, 100))


def test_spike_is_reported_once_per_cooldown():
    m = AnomalyMonitor(window_ticks=1000, spike_count=3, cooldown_ticks=500)
    assert m.record(1, "x") is None
    assert m.record(2, "x") is None
    assert m.record(3, "x") is not None          # first spike
    assert m.record(4, "x") is None              # still spiking, but on cooldown
    assert m.record(600, "x") is not None        # cooldown elapsed -> re-report


def test_bot_records_bot_anomaly_event_on_a_spike(tmp_path):
    s = Storage(str(tmp_path / "an.db"), commit_every=1)
    bot = GuildBot(strategy="explorer", storage=s)
    bot.anomaly = AnomalyMonitor(window_ticks=100, spike_count=5, cooldown_ticks=50)
    for t in range(1, 6):
        bot.tick = t
        bot.on_action_error({"tick": t, "char_uid": "c1",
                             "action": "embark", "reason": "no_such_character"})
    n = s.conn.execute(
        "SELECT COUNT(*) FROM events WHERE kind='bot_anomaly' "
        "AND world='error_spike:no_such_character'").fetchone()[0]
    assert n == 1, "expected the spike to be persisted as a bot_anomaly event"
    s.close()


def test_bot_stays_quiet_on_a_healthy_error_stream(tmp_path):
    s = Storage(str(tmp_path / "an2.db"), commit_every=1)
    bot = GuildBot(strategy="explorer", storage=s)
    bot.anomaly = AnomalyMonitor(window_ticks=100, spike_count=5, cooldown_ticks=50)
    # errors spread far apart (one per 100 ticks) never fill the window.
    for t in range(0, 1000, 100):
        bot.tick = t
        bot.on_action_error({"tick": t, "char_uid": "c1",
                             "action": "move", "reason": "not_in_village"})
    n = s.conn.execute("SELECT COUNT(*) FROM events WHERE kind='bot_anomaly'").fetchone()[0]
    assert n == 0, "a healthy, spread-out error stream must not flag"
    s.close()
