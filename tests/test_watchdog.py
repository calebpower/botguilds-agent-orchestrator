"""Tests for the liveness watchdog (steemer.watchdog).

The oracle exists to fire on SILENCE, so it is self-tested from both sides: fed the age a
LIVE pipeline produces it must stay quiet, and fed the age a DEAD one produces it must
complain. A watchdog only ever observed passing is indistinguishable from one that never
fires — so the stale/dead cases below are the point of the file, not the ok case.
"""
import time
import zlib
import json

from steemer import db as _db
from steemer.watchdog import (classify_liveness, check_db,
                              DEFAULT_STALE_S, DEFAULT_DEAD_S)


# ---- pure classifier: both sides of the claim -------------------------------

def test_a_fresh_frame_is_alive():
    r = classify_liveness(now=1000.0, latest_received_at=995.0)   # 5s old
    assert r["ok"] is True and r["level"] == "ok" and r["status"] == "alive"
    assert r["age_s"] == 5.0


def test_a_stale_gap_warns():
    # no frame for 200s (> the 120s stale threshold) -> warn/stale. This is the alarm that
    # would have caught the kick-war / stopped-bot silence.
    r = classify_liveness(now=1000.0, latest_received_at=800.0)
    assert r["ok"] is False and r["level"] == "warn" and r["status"] == "stale"
    assert r["age_s"] == 200.0


def test_a_long_silence_is_critical_dead():
    # no frame for 900s (> the 600s dead threshold) -> critical/dead (the zlib crash-loop
    # signature: runs that wrote nothing for a long stretch).
    r = classify_liveness(now=2000.0, latest_received_at=1100.0)
    assert r["ok"] is False and r["level"] == "critical" and r["status"] == "dead"


def test_no_frames_at_all_is_critical_no_data():
    r = classify_liveness(now=1000.0, latest_received_at=None)
    assert r["ok"] is False and r["level"] == "critical" and r["status"] == "no_data"
    assert r["age_s"] is None


def test_threshold_boundaries_are_inclusive_at_the_alarm_side():
    # exactly at stale_s alarms (>=), just under stays ok -> proves the boundary isn't
    # off-by-one in the safe direction (which would hide a just-crossed staleness).
    assert classify_liveness(1000.0, 1000.0 - DEFAULT_STALE_S)["level"] == "warn"
    assert classify_liveness(1000.0, 1000.0 - DEFAULT_STALE_S + 0.1)["level"] == "ok"
    assert classify_liveness(1000.0, 1000.0 - DEFAULT_DEAD_S)["level"] == "critical"


def test_custom_thresholds_are_honored():
    r = classify_liveness(now=100.0, latest_received_at=90.0, stale_s=5.0, dead_s=50.0)
    assert r["level"] == "warn"       # 10s old, > custom 5s stale


# ---- DB wrapper: reads the newest frame's age -------------------------------

def _seed_frame(conn, received_at, seq_tick):
    conn.execute(
        "INSERT INTO frames (tick, world, received_at, run_id, json) VALUES (?,?,?,?,?)",
        (seq_tick, "mines", received_at, 1,
         zlib.compress(json.dumps({"world": "mines", "tick": seq_tick}).encode())))
    conn.commit()


def test_check_db_reads_the_NEWEST_frame_and_stays_quiet_when_live(tmp_path):
    conn = _db.connect({"type": "sqlite", "path": str(tmp_path / "d.db")})
    _db.apply_schema(conn)
    now = 10_000.0
    _seed_frame(conn, received_at=now - 5, seq_tick=1)     # fresh
    r = check_db(conn, now=now)
    assert r["ok"] is True and r["status"] == "alive"


def test_check_db_fires_on_a_stale_mirror(tmp_path):
    # the self-test that matters: a DB whose newest frame is old must make the watchdog
    # complain. Model of the real defect (bot down / crash-looped, no new frames).
    conn = _db.connect({"type": "sqlite", "path": str(tmp_path / "d.db")})
    _db.apply_schema(conn)
    now = 10_000.0
    _seed_frame(conn, received_at=now - 50, seq_tick=1)    # older
    _seed_frame(conn, received_at=now - 900, seq_tick=2)   # NEWEST by seq, but ancient ts
    # newest-by-seq is the ancient one -> dead. (Guards against reading MAX(received_at),
    # which would wrongly report the 50s-old row and mask a stalled-then-restarted mirror.)
    r = check_db(conn, now=now)
    assert r["ok"] is False and r["status"] == "dead"


def test_check_db_no_frames_is_no_data(tmp_path):
    conn = _db.connect({"type": "sqlite", "path": str(tmp_path / "d.db")})
    _db.apply_schema(conn)
    r = check_db(conn, now=10_000.0)
    assert r["status"] == "no_data"
