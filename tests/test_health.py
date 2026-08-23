"""Tests for the service-plane supervisor decisions (steemer.health).

Written against the 2026-08-21 outage: every service down, then the bot crash-looping on
a pyzmq built for a different CPython prerelease while `svc.sh status` said "up". The
oracle here decides whether to restart, hold, or repair — so, like the frame watchdog, it
is self-tested from BOTH sides: fed a healthy world it must do nothing, and fed each
broken world it must choose the specific action that world calls for. An oracle only ever
observed staying quiet is indistinguishable from one that cannot fire.
"""
import subprocess

from steemer import health


ALIVE = {"ok": True, "level": "ok", "status": "alive", "age_s": 1.0}
STALE = {"ok": False, "level": "warn", "status": "stale", "age_s": 200.0}
DEAD = {"ok": False, "level": "critical", "status": "dead", "age_s": 900.0}
NO_DATA = {"ok": False, "level": "critical", "status": "no_data", "age_s": None}


# ---- pure planner: every branch, both directions ---------------------------

def test_healthy_service_is_left_alone():
    a = health.plan_action("bot", ALIVE, now=1000.0)
    assert a["action"] == "none"


def test_a_stale_gap_is_reported_but_NOT_restarted():
    # The distinction that keeps this supervisor from doing harm: a gap under the dead
    # threshold is a hiccup (reconnect, slow query, band refresh). Restarting on it would
    # close a run window for nothing.
    a = health.plan_action("bot", STALE, now=1000.0)
    assert a["action"] == "hold" and "not acting" in a["reason"]


def test_a_dead_service_is_restarted():
    a = health.plan_action("bot", DEAD, now=1000.0)
    assert a["action"] == "restart"


def test_no_data_at_all_is_restarted():
    a = health.plan_action("web", NO_DATA, now=1000.0)
    assert a["action"] == "restart"


def test_a_broken_venv_is_repaired_NOT_restarted():
    # THE regression this file exists for. With a segfaulting extension, restarting is
    # precisely what run-live.sh already does forever, to no effect — so `repair_venv`
    # must outrank `restart`, even though the service is dead and off cooldown.
    a = health.plan_action("bot", DEAD, now=1000.0, venv_ok=False)
    assert a["action"] == "repair_venv"


def test_a_broken_venv_outranks_the_cooldown_too():
    a = health.plan_action("bot", DEAD, now=1000.0, last_restart_at=999.0, venv_ok=False)
    assert a["action"] == "repair_venv"


def test_a_recent_restart_holds_instead_of_storming():
    # 60s after a restart, still dead: the cause is not one a restart fixes (server
    # unreachable, say). Hold rather than restart every pass.
    a = health.plan_action("bot", DEAD, now=1000.0, last_restart_at=940.0)
    assert a["action"] == "hold" and "cooldown" in a["reason"]


def test_the_cooldown_expires():
    a = health.plan_action("bot", DEAD, now=1000.0,
                           last_restart_at=1000.0 - health.RESTART_COOLDOWN_S - 1)
    assert a["action"] == "restart"


def test_plan_covers_every_service_in_a_stable_order():
    reports = {"bot": DEAD, "web": ALIVE, "dash": STALE}
    acts = health.plan(reports, now=1000.0)
    assert [a["service"] for a in acts] == ["bot", "dash", "web"]
    assert [a["action"] for a in acts] == ["restart", "hold", "none"]


def test_overall_level_reports_the_WORST_service_not_the_first():
    assert health.overall_level({"bot": ALIVE, "web": ALIVE}) == "ok"
    assert health.overall_level({"bot": ALIVE, "web": STALE}) == "warn"
    assert health.overall_level({"bot": STALE, "web": DEAD}) == "critical"
    # order must not matter — a healthy first entry cannot mask a dead later one
    assert health.overall_level({"bot": DEAD, "web": ALIVE}) == "critical"


# ---- port check -------------------------------------------------------------

def test_a_closed_port_is_immediately_critical():
    # Unlike a frame gap there is no benign transient reading of "nothing is listening".
    assert health.port_report(False, now=1.0)["level"] == "critical"
    assert health.port_report(True, now=1.0)["level"] == "ok"


def test_tcp_alive_is_false_for_a_port_nobody_listens_on():
    assert health.tcp_alive("127.0.0.1", 1, timeout_s=0.5) is False


def test_tcp_alive_is_true_for_a_socket_we_open():
    import socket as _s
    srv = _s.socket(); srv.bind(("127.0.0.1", 0)); srv.listen(1)
    try:
        assert health.tcp_alive("127.0.0.1", srv.getsockname()[1], timeout_s=2.0) is True
    finally:
        srv.close()


# ---- the venv smoke test: the oracle for the actual crash ------------------

def _fake(returncode, stdout=b""):
    def _runner(cmd, **kw):
        return subprocess.CompletedProcess(cmd, returncode, stdout, b"")
    return _runner


def test_smoke_venv_passes_only_on_the_real_marker():
    r = health.smoke_venv(_runner=_fake(0, b"smoke-ok\n"))
    assert r["ok"] is True


def test_smoke_venv_fails_when_the_marker_is_missing_despite_exit_0():
    # Two oracles for the same claim: exit status AND the marker the child prints. An
    # exit-0 that never reached the print is not a working socket.
    r = health.smoke_venv(_runner=_fake(0, b""))
    assert r["ok"] is False


def test_smoke_venv_names_a_segfault_as_an_ABI_mismatch():
    # This is the exact signature of the outage: SIGSEGV constructing a zmq socket.
    r = health.smoke_venv(_runner=_fake(-11))
    assert r["ok"] is False and "SIGSEGV" in r["detail"]
    r139 = health.smoke_venv(_runner=_fake(139))
    assert r139["ok"] is False and "SIGSEGV" in r139["detail"]


def test_smoke_venv_really_runs_out_of_process():
    # The check must survive the crash it is checking for, so it must not be an in-process
    # import. Prove it by running it for real against this interpreter.
    r = health.smoke_venv()
    assert r["ok"] is True, f"live venv smoke test failed: {r}"


def test_repair_venv_builds_from_source_bypassing_the_cache():
    seen = {}

    def _runner(cmd, **kw):
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, b"", b"")

    r = health.repair_venv(cwd=".", _runner=_runner)
    assert r["ok"] is True
    # The cause-fix is specifically a fresh COMPILE: a cached wheel is the defect, so
    # both flags must be present or the repair reinstalls the broken binary.
    assert "--no-cache" in seen["cmd"] and "--no-binary" in seen["cmd"]
    assert "pyzmq" in seen["cmd"]


# ---- collect() wiring -------------------------------------------------------

class _FakeConn:
    def __init__(self, frame_at, intel_at):
        self._frame_at, self._intel_at = frame_at, intel_at

    def execute(self, sql):
        val = self._frame_at if "frames" in sql else self._intel_at
        class _C:
            def fetchone(self_inner):
                return None if val is None else (val,)
        return _C()


def test_collect_reads_each_service_from_its_own_source():
    reports = health.collect(_FakeConn(frame_at=999.0, intel_at=900.0), now=1000.0,
                             _tcp=lambda h, p, timeout_s=2.0: True)
    assert reports["bot"]["status"] == "alive"      # 1s old
    assert reports["web"]["status"] == "alive"      # 100s old, under the 180s web stale
    assert reports["dash"]["status"] == "listening"


def test_collect_uses_the_web_thresholds_for_the_sidecar_not_the_bot_ones():
    # The sidecar writes ~every 30s, the bot many times a second: a 150s intel gap is
    # normal-ish for web but long dead for the bot. Sharing one threshold would either
    # cry wolf on web or go blind on bot.
    reports = health.collect(_FakeConn(frame_at=850.0, intel_at=850.0), now=1000.0,
                             _tcp=lambda h, p, timeout_s=2.0: False)
    assert reports["bot"]["level"] == "warn"        # 150s > BOT_STALE_S (120)
    assert reports["web"]["level"] == "ok"          # 150s < WEB_STALE_S (180)
    assert reports["dash"]["level"] == "critical"


# --- v0.97.0: the TRACK-thread heartbeat (the masked-staleness fix) -------------------
import sqlite3


def _intel_db(rows):
    """rows: list of (kind, observed_at) inserted in order (seq ascending)."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE intel(seq INTEGER PRIMARY KEY AUTOINCREMENT, "
              "observed_at REAL, tick INTEGER, kind TEXT, payload_json TEXT)")
    for kind, at in rows:
        c.execute("INSERT INTO intel(observed_at, tick, kind, payload_json) "
                  "VALUES (?,0,?,'{}')", (at, kind))
    c.commit()
    return c


def test_track_beat_is_read_independently_of_other_intel():
    conn = _intel_db([("spectate", 100.0), ("track_beat", 90.0), ("color", 101.0)])
    assert health.latest_track_beat_at(conn) == 90.0
    assert health.latest_intel_at(conn) == 101.0     # any-intel is the newest row


def test_web_heartbeat_PREFERS_the_track_beat_over_fresh_spectate():
    """THE REGRESSION: the track feed is dead (beat old) but spectate/color keep writing
    on the healthy main connection. The any-intel heartbeat reads fresh and hides it; the
    web heartbeat must follow the track_beat and report the sidecar stale."""
    conn = _intel_db([("track_beat", 50.0), ("spectate", 500.0), ("color", 501.0)])
    assert health.web_heartbeat_at(conn) == 50.0, "web heartbeat masked a dead track feed"
    # and the classifier turns that beat age into a restart-worthy state (the watchdog
    # feeds web_heartbeat_at into exactly this call inside collect)
    from steemer import watchdog
    rep = watchdog.classify_liveness(50.0 + health.WEB_DEAD_S + 1,
                                     health.web_heartbeat_at(conn),
                                     health.WEB_STALE_S, health.WEB_DEAD_S)
    assert rep["level"] == "critical", rep


def test_web_heartbeat_FALLS_BACK_to_any_intel_before_the_first_beat():
    """A sidecar predating the beat (or fresh, before its first beat) must not be falsely
    restarted — fall back to the coarse any-intel heartbeat."""
    conn = _intel_db([("spectate", 300.0), ("color", 305.0)])   # no track_beat yet
    assert health.web_heartbeat_at(conn) == 305.0
