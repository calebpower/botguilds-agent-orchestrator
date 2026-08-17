#!/bin/sh
# Keep the live bot running. Restart on a crash (non-zero exit) with capped
# backoff; step aside on a clean exit (exit 0) — which happens when a bounded
# --ticks run finishes, or when a redeploy's new session supersedes this one.
# POSIX sh; runs on FreeBSD (no systemd needed). Args pass through to the runner.
#
#   ./run-live.sh                 # play forever, logging to guild_log.db
#   ./run-live.sh --strategy explorer --note "baseline"
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)" || exit 1

backoff=1
while :; do
    uv run python -m steemer.runner "$@"
    code=$?
    if [ "$code" -eq 0 ]; then
        echo "[run-live] runner exited cleanly (0) — supervisor stopping"
        exit 0
    fi
    echo "[run-live] runner exited $code — restarting in ${backoff}s"
    sleep "$backoff"
    if [ "$backoff" -lt 30 ]; then
        backoff=$((backoff * 2))
    fi
done
