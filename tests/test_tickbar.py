"""v0.108.3 — the tick-participation bar (wishlist, operator 2026-08-23).

For the last `window` server ticks: which landed a frame (green) and which dropped
(red), plus a ticks/min rate computed from the same seq-indexed tail — NEVER from a
received_at range scan (unindexed; 63 SECONDS measured on the live DB). Its two use
cases have both happened: run #120 silently dropped 3.7% of its stream, and on
2026-08-24 the server clock crawled at ~180 ticks/hour for an afternoon with nothing
on the dash to show it.
"""
import sqlite3

import ui.server as srv


def _seed(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE frames(seq INTEGER PRIMARY KEY, run_id INTEGER, "
                 "world TEXT, tick INTEGER, received_at REAL, json TEXT)")
    for i, (world, tick, recv) in enumerate(rows):
        conn.execute("INSERT INTO frames VALUES (?,?,?,?,?,'')", (i + 1, 1, world, tick, recv))
    conn.commit(); conn.close()


def test_missing_ticks_are_reported_and_present_ones_are_not(tmp_path):
    db = str(tmp_path / "t.db")
    # ticks 100..109 with a hole at 105 and 106; two worlds overlap on some ticks
    rows = [("vale", t, 1000.0 + (t - 100)) for t in (100, 101, 102, 103, 104, 107, 108, 109)]
    rows += [("mines", 103, 1003.5), ("mines", 108, 1008.5)]
    _seed(db, rows)
    out = srv.api_tickbar(db, window=10)
    assert out["ok"] and out["max_tick"] == 109
    assert out["missing"] == [105, 106], out
    # rate: 9 ticks over 8.5s of wall -> ~63.5/min; assert the band, not the decimal
    assert out["rate_per_min"] and 50 <= out["rate_per_min"] <= 80, out


def test_a_stalled_clock_reads_as_a_near_zero_rate(tmp_path):
    db = str(tmp_path / "t.db")
    # the 2026-08-24 shape: many frames, the tick barely advancing (3 ticks in 600s)
    rows = [("vale", 100 + (i % 4), 1000.0 + i * 10) for i in range(60)]
    _seed(db, rows)
    out = srv.api_tickbar(db, window=10)
    assert out["ok"]
    assert out["rate_per_min"] is not None and out["rate_per_min"] < 1.0, out


def test_an_empty_db_is_ok_and_empty_not_an_error(tmp_path):
    db = str(tmp_path / "t.db")
    _seed(db, [])
    out = srv.api_tickbar(db, window=10)
    assert out["ok"] and out["max_tick"] is None and out["missing"] == []


def test_a_counter_LEAP_is_clock_skipped_not_dropped(tmp_path):
    # v0.108.4 — during the 08-24 stall the bar read 369/500 "dropped" when most of
    # that was the tick counter LEAPING across restarts/catch-up bursts: ticks that
    # never happened for us are not lost frames. A gap wider than TICK_JUMP_MIN is
    # classified `jumped`; a small gap stays `missing` (the real-drop case, which is
    # the bar's original purpose and must not be diluted).
    from ui.server import TICK_JUMP_MIN
    assert TICK_JUMP_MIN == 50, "the threshold moved; re-read the numbers in this test"
    db = str(tmp_path / "t.db")
    # observed ticks: 300..304, then a 195-tick leap to 500..503 with a REAL 1-tick
    # hole at 502 (the clock ran 500->503 while our 502 frame never landed).
    rows = [("vale", t, 1000.0 + i) for i, t in enumerate(
        [300, 301, 302, 303, 304, 500, 501, 503])]
    _seed(db, rows)
    out = srv.api_tickbar(db, window=210)
    assert 502 in out["missing"], out
    assert 400 in out["jumped"] and 400 not in out["missing"], out
    assert not (set(out["missing"]) & set(out["jumped"])), "a tick in both classes"
