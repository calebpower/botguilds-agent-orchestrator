"""Always-on supervisor for the three services — the CALLER the watchdog never had.

`steemer/watchdog.py` could always tell whether frames were flowing; nothing ever asked
it. On 2026-08-21 all three services were down and the bot then crash-looped on a broken
pyzmq for as long as it took a human to look at a log. This closes that loop:

    uv run python tools/healthcheck.py                # one shot, JSON to stdout
    uv run python tools/healthcheck.py --fix          # ... and repair what is dead
    uv run python tools/healthcheck.py --watch 60 --fix   # the `svc.sh up watch` service

Exit code (one-shot): 0 all ok · 1 something stale (warn) · 2 something dead (critical).
So a bare cron line can alert on `|| ...` without parsing the JSON.

Restarting is deliberately conservative — see `steemer.health.plan_action`: warn never
acts, a broken venv is repaired instead of restarted, and each service has a restart
cooldown so a cause this cannot fix (server unreachable) produces one restart per window
rather than a storm.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from steemer import db, health           # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SVC = os.path.join(ROOT, "svc.sh")


def _log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}", flush=True)


def apply_action(act: dict, *, dry_run: bool) -> dict:
    """Carry out one planned action. Returns the action annotated with the outcome."""
    kind = act["action"]
    if kind in ("none", "hold"):
        return {**act, "applied": False}
    if dry_run:
        return {**act, "applied": False, "outcome": "dry-run"}
    if kind == "restart":
        # timeout, and stdin from /dev/null: svc.sh detaches the new service, and a
        # freshly-detached child can hold the captured pipe open for a moment. An
        # always-on supervisor that can block forever on its own restart is worse than
        # the outage it is fixing, so bound it and treat a timeout as "started, output
        # not collected" rather than as a failure.
        try:
            r = subprocess.run([SVC, "restart", act["service"]], cwd=ROOT,
                               stdin=subprocess.DEVNULL, capture_output=True,
                               text=True, timeout=120)
        except subprocess.TimeoutExpired:
            _log(f"RESTART {act['service']}: {act['reason']} -> timed out collecting "
                 f"output (the service may still have started)")
            return {**act, "applied": True, "outcome": "timeout"}
        ok = r.returncode == 0
        _log(f"RESTART {act['service']}: {act['reason']} -> "
             f"{'ok' if ok else 'FAILED'} {r.stdout.strip()} {r.stderr.strip()}")
        return {**act, "applied": True, "outcome": "ok" if ok else "failed"}
    if kind == "repair_venv":
        _log(f"REPAIR VENV: {act['reason']}")
        rep = health.repair_venv(cwd=ROOT)
        _log(f"REPAIR VENV -> {rep}")
        return {**act, "applied": True, "outcome": rep}
    return {**act, "applied": False, "outcome": f"unknown action {kind}"}


def one_pass(*, fix: bool, dry_run: bool, last_restart_at: dict,
             dash_port: int, cooldown_s: float) -> dict:
    now = time.time()
    conn = db.connect(db.load_db_config(), readonly=True)
    try:
        reports = health.collect(conn, now=now, dash_port=dash_port)
    finally:
        try:
            conn.close()
        except Exception:                            # pragma: no cover - defensive
            pass

    # The smoke test is only worth its subprocess when something is already dead — but
    # then it is decisive, because it is what separates "restart it" from "restarting
    # cannot possibly help".
    venv = {"ok": True, "detail": "not checked (nothing critical)"}
    if any(r["level"] == "critical" for r in reports.values()):
        venv = health.smoke_venv()

    actions = health.plan(reports, now=now, last_restart_at=last_restart_at,
                          venv_ok=venv["ok"], cooldown_s=cooldown_s)
    if fix:
        applied = []
        for act in actions:
            done = apply_action(act, dry_run=dry_run)
            if done.get("applied") and act["action"] == "restart":
                last_restart_at[act["service"]] = now
            applied.append(done)
        actions = applied
    return {"at": now, "level": health.overall_level(reports),
            "reports": reports, "venv": venv, "actions": actions}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fix", action="store_true",
                    help="act on the plan (restart dead services / repair the venv)")
    ap.add_argument("--dry-run", action="store_true",
                    help="with --fix, print what would be done without doing it")
    ap.add_argument("--watch", type=float, default=0.0, metavar="SECONDS",
                    help="loop forever, checking every SECONDS (0 = one shot)")
    ap.add_argument("--dash-port", type=int, default=int(os.environ.get("DASH_PORT", 8800)))
    ap.add_argument("--cooldown-seconds", type=float, default=health.RESTART_COOLDOWN_S)
    args = ap.parse_args()

    last_restart_at: dict = {}
    if args.watch <= 0:
        rep = one_pass(fix=args.fix, dry_run=args.dry_run,
                       last_restart_at=last_restart_at, dash_port=args.dash_port,
                       cooldown_s=args.cooldown_seconds)
        print(json.dumps(rep, default=str))
        return {"ok": 0, "warn": 1}.get(rep["level"], 2)

    _log(f"healthcheck watching every {args.watch}s (fix={args.fix})")
    while True:
        try:
            rep = one_pass(fix=args.fix, dry_run=args.dry_run,
                           last_restart_at=last_restart_at, dash_port=args.dash_port,
                           cooldown_s=args.cooldown_seconds)
            # Log only when something is wrong or something was done: a supervisor that
            # prints every minute buries the one line that matters.
            acted = [a for a in rep["actions"] if a.get("applied")]
            if rep["level"] != "ok" or acted:
                _log(json.dumps({k: v for k, v in rep.items() if k != "at"}, default=str))
        except Exception as exc:                     # keep watching through a bad pass
            _log(f"healthcheck pass failed (continuing): {exc!r}")
        time.sleep(args.watch)


if __name__ == "__main__":
    raise SystemExit(main())
