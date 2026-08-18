#!/bin/sh
# Service control for the always-on companions — the game bot, the web sidecar,
# and the dashboard — as detached daemons (reparented to init, so they survive
# the shell that launched them).
#
#   ./svc.sh up      {bot|web|dash}    # start detached if not already running
#   ./svc.sh down    {bot|web|dash}    # stop it (whole process group)
#   ./svc.sh restart {bot|web|dash}    # down, then up (pick up new on-disk code)
#   ./svc.sh status  {bot|web|dash}
#
# A PID file under run/ tracks each service. `daemon(8)` (FreeBSD) detaches into
# a new session so the recorded PID is the process-group leader — `down` signals
# the whole group, so run-live.sh's supervised child (and the web loop) go too.
# setsid is the portable fallback.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)" || exit 1

act="${1:-}"; svc="${2:-}"
DASH_HOST="${DASH_HOST:-0.0.0.0}"; DASH_PORT="${DASH_PORT:-8800}"
case "$svc" in
    bot)  cmd="./run-live.sh"                       ; pidf="run/bot.pid"  ; log="${STEEMER_LOG:-steemer-live.log}";;
    web)  cmd="uv run python tools/web_sidecar.py"  ; pidf="run/web.pid"  ; log="web-sidecar.log";;
    dash) cmd="uv run python ui/server.py --host $DASH_HOST --port $DASH_PORT"; pidf="run/dash.pid"; log="ui-server.log";;
    *)    echo "usage: $0 {up|down|restart|status} {bot|web|dash}" >&2; exit 2;;
esac
mkdir -p run

is_up() { [ -f "$pidf" ] && kill -0 "$(cat "$pidf")" 2>/dev/null; }

up() {
    if is_up; then echo "$svc already up (pid $(cat "$pidf"))"; return 0; fi
    rm -f "$pidf"
    if command -v daemon >/dev/null 2>&1; then          # FreeBSD: detach + pidfile
        daemon -f -p "$pidf" -o "$log" sh -c "exec $cmd"
    elif command -v setsid >/dev/null 2>&1; then        # Linux fallback
        setsid sh -c "exec $cmd" >> "$log" 2>&1 &
        echo $! > "$pidf"
    else
        nohup sh -c "exec $cmd" >> "$log" 2>&1 &
        echo $! > "$pidf"
    fi
    sleep 1
    if is_up; then echo "$svc up (pid $(cat "$pidf"), logging to $log)";
    else echo "$svc failed to stay up — see $log" >&2; return 1; fi
}

down() {
    if ! [ -f "$pidf" ]; then echo "$svc not running (no $pidf)"; return 0; fi
    pid="$(cat "$pidf")"
    kill -TERM "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
    # give it a moment, then hard-stop any stragglers in the group
    sleep 1
    kill -KILL "-$pid" 2>/dev/null || true
    rm -f "$pidf"
    echo "$svc down"
}

case "$act" in
    up)      up;;
    down)    down;;
    restart) down; sleep 1; up;;
    status)  if is_up; then echo "$svc up (pid $(cat "$pidf"))"; else echo "$svc down"; fi;;
    *)       echo "usage: $0 {up|down|restart|status} {bot|web|dash}" >&2; exit 2;;
esac
