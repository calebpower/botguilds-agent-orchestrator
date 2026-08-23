"""Service-plane health — is each always-on service actually WORKING, and what to do.

Context (2026-08-21): all three services (bot, web sidecar, dashboard) were found DOWN,
and when the bot was restarted it CRASH-LOOPED — `uv` had rebuilt `.venv` against a newer
CPython 3.15 prerelease and reinstalled a CACHED pyzmq wheel built against the older one,
so `zmq_getsockopt` SEGFAULTED (exit 139) on every start. Nothing noticed either
condition, because nothing here could:

* `steemer.watchdog` answers the right question ("are frames flowing?") but nothing ever
  RAN it — it was a CLI with no caller, so its coverage was illusory.
* `svc.sh status` answers "is a pid alive?", which a crash-loop satisfies just as well as
  a healthy run: `run-live.sh` respawns forever, so the supervisor looks up while the
  runner dies every few seconds and not one frame is written.

This module is the *decision* half of an always-on supervisor. The split mirrors
`watchdog.py`: PURE classification/planning driven by an explicit clock (so the oracle is
deterministic and can be self-tested from both sides), plus thin IO that gathers inputs.

What it deliberately does NOT claim: a listening TCP port proves the dashboard is
*accepting connections*, not that its handlers work; and frame freshness proves the data
plane is moving, not that the strategy is playing WELL. Those are other oracles' jobs.
"""
from __future__ import annotations

import socket
import subprocess
import sys
import time
from typing import Any

from steemer import watchdog

# The bot writes many frames a second; the sidecar writes an `intel` row every
# ~30s (its --spectate-seconds default), so it needs its own, looser thresholds.
BOT_STALE_S = watchdog.DEFAULT_STALE_S      # 120
BOT_DEAD_S = watchdog.DEFAULT_DEAD_S        # 600
WEB_STALE_S = 180.0
WEB_DEAD_S = 600.0

# Never restart the same service more often than this. A restart that does not fix
# the cause (server unreachable, broken venv) would otherwise become a restart STORM,
# which is worse than the outage: each bot restart closes a run window and re-hellos.
RESTART_COOLDOWN_S = 900.0

SERVICES = ("bot", "web", "dash")


# --------------------------------------------------------------------------- #
# PURE: what to do about one service's report
# --------------------------------------------------------------------------- #

def plan_action(service: str, report: dict[str, Any], *, now: float,
                last_restart_at: float | None = None, venv_ok: bool = True,
                cooldown_s: float = RESTART_COOLDOWN_S) -> dict[str, Any]:
    """Decide the single action for ``service`` given its liveness ``report``. PURE.

    Rules, in precedence order — the order is the point, so each is stated:

    1. ``level == "ok"``  -> ``none``. Nothing to do.
    2. ``level == "warn"`` (stale) -> ``hold``. A gap under the dead threshold is a
       hiccup (a band refresh, a slow query, a reconnect). Restarting on a hiccup costs
       a run window and proves nothing, so warn is reported but never acted on.
    3. ``venv_ok`` False -> ``repair_venv``, and this OUTRANKS restart: when the
       interpreter/extension ABI is broken, restarting is exactly what `run-live.sh`
       already does forever, to no effect. Only rebuilding the extension helps.
    4. within ``cooldown_s`` of the last restart -> ``hold``. Storm guard (see above).
    5. otherwise -> ``restart``.
    """
    level = report.get("level")
    if level == "ok":
        return {"service": service, "action": "none", "level": level,
                "reason": f"{service} {report.get('status')}"}
    if level == "warn":
        return {"service": service, "action": "hold", "level": level,
                "reason": f"{service} {report.get('status')} (age {report.get('age_s')}s) "
                          "— under the dead threshold, not acting"}
    if not venv_ok:
        return {"service": service, "action": "repair_venv", "level": level,
                "reason": f"{service} {report.get('status')} AND the venv smoke test "
                          "fails — a restart cannot fix a broken extension"}
    if last_restart_at is not None and (now - last_restart_at) < cooldown_s:
        waited = round(now - last_restart_at, 1)
        return {"service": service, "action": "hold", "level": level,
                "reason": f"{service} {report.get('status')} but restarted {waited}s ago "
                          f"(< {cooldown_s}s cooldown) — not storming"}
    age = report.get("age_s")
    age_txt = f" (age {age}s)" if age is not None else ""
    return {"service": service, "action": "restart", "level": level,
            "reason": f"{service} {report.get('status')}{age_txt} — restarting"}


def plan(reports: dict[str, dict[str, Any]], *, now: float,
         last_restart_at: dict[str, float] | None = None, venv_ok: bool = True,
         cooldown_s: float = RESTART_COOLDOWN_S) -> list[dict[str, Any]]:
    """``plan_action`` over every reported service, in a stable order. PURE."""
    last = last_restart_at or {}
    return [plan_action(svc, reports[svc], now=now, last_restart_at=last.get(svc),
                        venv_ok=venv_ok, cooldown_s=cooldown_s)
            for svc in sorted(reports)]


def overall_level(reports: dict[str, dict[str, Any]]) -> str:
    """Worst level across the reports — what a cron's exit code should reflect."""
    order = {"ok": 0, "warn": 1, "critical": 2}
    worst = "ok"
    for r in reports.values():
        if order.get(r.get("level"), 2) > order[worst]:
            worst = r.get("level", "critical")
    return worst


# --------------------------------------------------------------------------- #
# IO: gather the inputs
# --------------------------------------------------------------------------- #

def latest_intel_at(conn: Any) -> float | None:
    """Newest `intel` row's ``observed_at`` — a coarse sidecar heartbeat, via the seq PK."""
    row = conn.execute(
        "SELECT observed_at FROM intel ORDER BY seq DESC LIMIT 1").fetchone()
    if row is None:
        return None
    return row["observed_at"] if hasattr(row, "keys") else row[0]


def latest_track_beat_at(conn: Any) -> float | None:
    """Newest `track_beat` observed_at — the TRACK THREAD's own liveness (v0.97.0). This
    is the heartbeat that matters: it beats on the recorder's own db connection, so it
    goes stale exactly when that connection dies — the failure the any-intel heartbeat
    masks because spectate/color keep writing on the healthy main connection."""
    row = conn.execute(
        "SELECT observed_at FROM intel WHERE kind='track_beat' "
        "ORDER BY seq DESC LIMIT 1").fetchone()
    if row is None:
        return None
    return row["observed_at"] if hasattr(row, "keys") else row[0]


def web_heartbeat_at(conn: Any) -> float | None:
    """The sidecar's heartbeat for liveness: the track_beat when the new sidecar is
    running, else the coarse any-intel (back-compat for a sidecar predating the beat, so
    a fresh deploy is not falsely restarted before the first beat lands)."""
    beat = latest_track_beat_at(conn)
    return beat if beat is not None else latest_intel_at(conn)


def tcp_alive(host: str, port: int, timeout_s: float = 2.0) -> bool:
    """Is something accepting connections on host:port? Proves LISTENING, not healthy."""
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            return True
    except OSError:
        return False


def port_report(alive: bool, *, now: float) -> dict[str, Any]:
    """Shape a port check like a ``classify_liveness`` report so ``plan`` treats it the
    same way. There is no age here, so a closed port is immediately critical: unlike a
    frame gap, "not listening" has no benign transient reading."""
    if alive:
        return {"ok": True, "level": "ok", "status": "listening", "age_s": None}
    return {"ok": False, "level": "critical", "status": "not_listening", "age_s": None}


# The failure this exists to catch is a SEGFAULT, so the check must run OUT OF PROCESS —
# an in-process import/socket test would take the supervisor down with the thing it is
# supposed to be reporting on. That is not hypothetical: it is exactly how the pyzmq ABI
# break stayed invisible behind `run-live.sh`'s respawn loop.
_SMOKE_SRC = (
    "import zmq\n"
    "c = zmq.Context()\n"
    "s = c.socket(zmq.DEALER)\n"      # constructing a socket calls getsockopt(TYPE)
    "s.close(); c.term()\n"
    "print('smoke-ok')\n"
)


def smoke_venv(python_exe: str | None = None, timeout_s: float = 60.0,
               _runner=subprocess.run) -> dict[str, Any]:
    """Can this interpreter actually build a ZeroMQ socket? Returns ``{ok, detail}``.

    A negative ``returncode`` is a signal: -11 (SIGSEGV) is the ABI-mismatch signature.
    """
    exe = python_exe or sys.executable
    try:
        r = _runner([exe, "-c", _SMOKE_SRC], capture_output=True, timeout=timeout_s)
    except Exception as exc:                        # pragma: no cover - defensive
        return {"ok": False, "returncode": None, "detail": f"smoke test not runnable: {exc}"}
    out = r.stdout.decode(errors="replace") if isinstance(r.stdout, bytes) else (r.stdout or "")
    if r.returncode == 0 and "smoke-ok" in out:
        return {"ok": True, "returncode": 0, "detail": "zmq socket constructed"}
    detail = f"exit {r.returncode}"
    if r.returncode == -11 or r.returncode == 139:
        detail += " (SIGSEGV — compiled extension vs interpreter/libzmq ABI mismatch)"
    return {"ok": False, "returncode": r.returncode, "detail": detail}


def repair_venv(cwd: str | None = None, timeout_s: float = 1800.0,
                _runner=subprocess.run) -> dict[str, Any]:
    """Rebuild pyzmq FROM SOURCE against the current interpreter, bypassing the cache.

    This is the cause-fix for the ABI break, not a workaround: the cached wheel is a
    binary built for a different CPython prerelease, and ``--no-cache --no-binary`` is
    what forces a fresh compile against the interpreter that is actually installed.
    """
    cmd = ["uv", "pip", "install", "--no-cache", "--no-binary", "pyzmq",
           "--force-reinstall", "pyzmq"]
    try:
        r = _runner(cmd, cwd=cwd, capture_output=True, timeout=timeout_s)
    except Exception as exc:                        # pragma: no cover - defensive
        return {"ok": False, "detail": f"repair not runnable: {exc}", "cmd": cmd}
    return {"ok": r.returncode == 0, "detail": f"exit {r.returncode}", "cmd": cmd}


def collect(conn: Any, *, now: float | None = None, dash_host: str = "127.0.0.1",
            dash_port: int = 8800, _tcp=tcp_alive) -> dict[str, dict[str, Any]]:
    """Liveness reports for every service, keyed by name."""
    now = time.time() if now is None else now
    return {
        "bot": watchdog.classify_liveness(now, watchdog.latest_received_at(conn),
                                          BOT_STALE_S, BOT_DEAD_S),
        "web": watchdog.classify_liveness(now, web_heartbeat_at(conn),
                                          WEB_STALE_S, WEB_DEAD_S),
        "dash": port_report(_tcp(dash_host, dash_port), now=now),
    }
