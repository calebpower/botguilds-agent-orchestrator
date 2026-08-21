#!/bin/sh
# Keep the live bot running. Restart on a crash (non-zero exit) with capped
# backoff; step aside on a clean exit (exit 0) — which happens when a bounded
# --ticks run finishes, or when a redeploy's new session supersedes this one.
# POSIX sh; runs on FreeBSD (no systemd needed). Args pass through to the runner.
#
#   ./run-live.sh                 # play forever, logging to guild_log.db
#   ./run-live.sh --strategy explorer --note "baseline"
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)" || exit 1

# Crash-LOOP detection. Respawning forever is right for a transient crash and WRONG to do
# silently: on 2026-08-21 a stale cached pyzmq wheel (built against an older CPython 3.15
# prerelease) made the runner SEGFAULT (exit 139) on every start, and this loop restarted
# it every 30s for as long as it took a human to read the log — while `svc.sh status`
# cheerfully reported "bot up", because the supervisor WAS up. So: keep restarting (the
# game must keep playing), but leave a machine-readable marker that `svc.sh status` and
# tools/healthcheck.py can see. A run that survives FAST_FAIL_S counts as a real start and
# clears both the marker and the backoff.
CRASHLOOP_N="${STEEMER_CRASHLOOP_N:-3}"
FAST_FAIL_S="${STEEMER_FAST_FAIL_S:-20}"
MARKER="run/bot.crashloop"
mkdir -p run

backoff=1
fastfails=0
while :; do
    started=$(date +%s)
    uv run python -m steemer.runner "$@"
    code=$?
    lived=$(( $(date +%s) - started ))
    if [ "$code" -eq 0 ]; then
        rm -f "$MARKER"
        echo "[run-live] runner exited cleanly (0) — supervisor stopping"
        exit 0
    fi
    if [ "$lived" -lt "$FAST_FAIL_S" ]; then
        fastfails=$((fastfails + 1))
    else
        # It ran long enough to have really been playing: not a loop. Reset BOTH, so a
        # single bad patch does not leave the backoff pinned at 30s for the rest of the
        # process's life.
        fastfails=0; backoff=1; rm -f "$MARKER"
    fi
    if [ "$fastfails" -ge "$CRASHLOOP_N" ]; then
        echo "$(date '+%Y-%m-%d %H:%M:%S') exit=$code consecutive_fast_failures=$fastfails lived=${lived}s" > "$MARKER"
        echo "[run-live] CRASH-LOOP: $fastfails consecutive failures under ${FAST_FAIL_S}s (exit $code) — see $MARKER"
    fi
    echo "[run-live] runner exited $code after ${lived}s — restarting in ${backoff}s"
    sleep "$backoff"
    if [ "$backoff" -lt 30 ]; then
        backoff=$((backoff * 2))
    fi
done
