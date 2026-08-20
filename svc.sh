#!/bin/sh
# Service control for the always-on companions — the game bot, the web sidecar,
# and the dashboard — as detached daemons that outlive the shell (and the
# Claude/harness session) that launched them.
#
#   ./svc.sh up      {bot|web|dash}    # start detached if not already running
#   ./svc.sh down    {bot|web|dash}    # stop it (whole process group)
#   ./svc.sh restart {bot|web|dash}    # down, then up (pick up new on-disk code)
#   ./svc.sh status  {bot|web|dash}
#
# daemon(8) (FreeBSD) double-forks the child into its own session reparented to
# init, so it survives the launching shell — verified: a daemon-detached bot keeps
# storing frames across the harness Bash-call boundary that spawned it. The
# recorded PID is the child (process-group leader), so `down` signals the whole
# group and run-live.sh's supervised runner goes too. NOTE: `-f` sets the child's
# std fds to /dev/null (it is NOT a "foreground"/detach flag — the detach is
# daemon(8)'s own doing); `-o` still captures the child's output to the log. Do NOT
# add daemon's -R/-r supervise mode here: on this daemon(8) build the supervisor
# exits the moment its launcher returns, so `make bot-up` dies instantly — the
# plain (non-supervised) form is what actually stays detached. Crash-restarts are
# run-live.sh's job; a single-session KICK still cleanly stops the bot (intended:
# it steps aside for a redeploy). setsid/nohup are the portable fallback.
set -eu
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)" || exit 1

act="${1:-}"; svc="${2:-}"
DASH_HOST="${DASH_HOST:-0.0.0.0}"; DASH_PORT="${DASH_PORT:-8800}"
case "$svc" in
    bot)  cmd="./run-live.sh"                       ; pidf="run/bot.pid"  ; log="${STEEMER_LOG:-steemer-live.log}";;
    web)  cmd="uv run python tools/web_sidecar.py --color-seconds 1"  ; pidf="run/web.pid"  ; log="web-sidecar.log";;
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
