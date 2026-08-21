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
WATCH_SECONDS="${WATCH_SECONDS:-60}"
case "$svc" in
    bot)  cmd="./run-live.sh"                       ; pidf="run/bot.pid"  ; log="${STEEMER_LOG:-steemer-live.log}"; marker="run-live.sh";;
    web)  cmd="uv run python tools/web_sidecar.py --color-seconds 1"  ; pidf="run/web.pid"  ; log="web-sidecar.log"; marker="web_sidecar.py";;
    dash) cmd="uv run python ui/server.py --host $DASH_HOST --port $DASH_PORT"; pidf="run/dash.pid"; log="ui-server.log"; marker="ui/server.py";;
    watch) cmd="uv run python tools/healthcheck.py --watch $WATCH_SECONDS --fix"; pidf="run/watch.pid"; log="healthcheck.log"; marker="healthcheck.py";;
    *)    echo "usage: $0 {up|down|restart|status|pgid} {bot|web|dash|watch}" >&2; exit 2;;
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

# The process-group id of $1 (empty if it is gone). daemon(8) records the CHILD pid in
# the pidfile, but the group LEADER is daemon itself -- so pid != pgid, and the old
# `kill -TERM -$pid` signalled a process group that does not exist. The `|| kill $pid`
# fallback then killed only run-live.sh, orphaning the `uv` and python runner beneath it:
# that is the exact mechanism behind the long-standing "`svc.sh down bot` leaves
# steemer.runner alive" gotcha, and behind the single-session kick-wars that followed a
# redeploy. Resolve the real group instead of assuming one.
pgid_of() { ps -o pgid= -p "$1" 2>/dev/null | tr -d ' '; }

# Existence is POSIX `kill -0`, deliberately NOT ps: on a slim container ps(1) may be
# absent entirely, and asking ps made "no ps installed" indistinguishable from "process
# gone" -- so `down` reported every service stale and stopped NOTHING while claiming
# success. That is a fail-OPEN, the worst kind for a stop command. Caught by the reaper
# gate, whose debian-slim image ships no procps.
alive()   { kill -0 "$1" 2>/dev/null; }
have_ps() { ps -o pid= -p $$ >/dev/null 2>&1; }

# Every descendant of $1 (inclusive), by walking the ps ppid table. Belt-and-braces
# beside the group signal, and precise: it names the pids we are about to kill instead of
# pattern-matching a command line, which could match another checkout's bot.
proc_tree() {
    _frontier="$1"; _all="$1"
    while [ -n "$_frontier" ]; do
        _next=""
        for _p in $_frontier; do
            _next="$_next $(ps -axo pid,ppid | awk -v pp="$_p" '$2==pp {print $1}')"
        done
        _frontier="$(echo $_next)"
        _all="$_all $_frontier"
    done
    echo $_all
}

down() {
    if ! [ -f "$pidf" ]; then echo "$svc not running (no $pidf)"; return 0; fi
    pid="$(cat "$pidf")"
    if ! alive "$pid"; then
        rm -f "$pidf"; echo "$svc not running (stale $pidf, pid $pid gone)"; return 0
    fi
    # The process EXISTS. Everything below -- proving it is ours, and resolving its
    # process group -- needs ps. Without ps we can neither verify ownership nor signal
    # the right group, so refuse LOUDLY rather than kill blindly or lie about success.
    if ! have_ps; then
        echo "$svc NOT stopped: pid $pid is alive but ps(1) is unavailable, so ownership" \
             "and process group cannot be resolved (install procps)" >&2
        return 1
    fi
    # Guard against a STALE pidfile whose pid the OS has recycled: without this, the
    # tree-kill below would take out an unrelated process and its children.
    cmdline="$(ps -o command= -p "$pid" 2>/dev/null || true)"
    case "$cmdline" in
        *"$marker"*) ;;
        *) rm -f "$pidf"
           echo "$svc NOT stopped: $pidf pid $pid is not ours ($cmdline) -- pidfile removed" >&2
           return 1;;
    esac

    tree="$(proc_tree "$pid")"
    pgid="$(pgid_of "$pid")"
    # Never signal our OWN process group. A detached service is always in a session of
    # its own, so this can only trigger on a bad/recycled pidfile -- in which case the
    # group signal below would kill the CALLER (and, when that caller is the test suite
    # or the healthcheck supervisor, take the supervision down with it). Observed for
    # real while mutation-testing the guard above.
    if [ -n "$pgid" ] && [ "$pgid" = "$(pgid_of $$)" ]; then
        echo "$svc NOT stopped: pid $pid shares MY process group ($pgid) -- refusing" >&2
        return 1
    fi
    if [ -n "$pgid" ]; then kill -TERM "-$pgid" 2>/dev/null || true; fi
    kill -TERM $tree 2>/dev/null || true
    sleep 1
    if [ -n "$pgid" ]; then kill -KILL "-$pgid" 2>/dev/null || true; fi
    kill -KILL $tree 2>/dev/null || true
    rm -f "$pidf"
    # Report a survivor rather than swallowing it -- a runner that outlives its `down` is
    # what starts a kick-war with the session that replaces it.
    left=""
    for _p in $tree; do if kill -0 "$_p" 2>/dev/null; then left="$left $_p"; fi; done
    if [ -n "$left" ]; then echo "$svc down (WARNING: survivors:$left)" >&2; return 1; fi
    echo "$svc down"
}

case "$act" in
    up)      up;;
    down)    down;;
    restart) down; sleep 1; up;;
    status)  if is_up; then
                 echo "$svc up (pid $(cat "$pidf"), pgid $(pgid_of "$(cat "$pidf")"))"
                 # A live pid is NOT health: run-live.sh respawns a segfaulting runner
                 # forever and still looks "up". Surface the crash-loop marker it writes.
                 if [ "$svc" = bot ] && [ -f run/bot.crashloop ]; then
                     echo "  !! CRASH-LOOP: $(cat run/bot.crashloop)" >&2
                     exit 1
                 fi
             else echo "$svc down"; exit 1; fi;;
    pgid)    pgid_of "$(cat "$pidf" 2>/dev/null || echo 0)";;
    *)       echo "usage: $0 {up|down|restart|status|pgid} {bot|web|dash|watch}" >&2; exit 2;;
esac
