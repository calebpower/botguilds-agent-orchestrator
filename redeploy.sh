#!/bin/sh
# Hot-redeploy the live bot with (near) zero downtime, DETACHED from whatever
# launched it (a terminal, or a Claude session that might hit a usage cap).
#
# BotGuilds allows one session per guild: a new `hello` supersedes the old one,
# which receives `kick: superseded` and exits cleanly (its supervisor steps
# aside). So redeploying is just: start a fresh, fully-detached supervised
# runner. The cutover costs ~one handshake; the new run's window opens in the
# `runs` table as the old one's closes.
#
# Detachment matters for the failure mode where the operator's Claude usage caps
# out: the game bot must keep playing on its own. `daemon -f` (FreeBSD) reparents
# to init; setsid/nohup are portability fallbacks.
#
# Use after committing new code AND after `reaper test` passes. Args pass through
# to the runner. Rollback: check out a known-good sha (see the runs table) and
# run this again.
#
#   ./redeploy.sh --note "explorer: prefer nearer loot"
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)" || exit 1

sha=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
log=${STEEMER_LOG:-steemer-live.log}

printf '[redeploy] %s handing off to %s (detached)\n' \
    "$(date '+%Y-%m-%dT%H:%M:%S' 2>/dev/null || echo now)" "$sha" >> "$log"

if command -v daemon >/dev/null 2>&1; then          # FreeBSD: fully detach + log
    daemon -f -o "$log" ./run-live.sh "$@"
elif command -v setsid >/dev/null 2>&1; then        # Linux
    setsid nohup ./run-live.sh "$@" </dev/null >> "$log" 2>&1 &
else                                                # last resort
    nohup ./run-live.sh "$@" </dev/null >> "$log" 2>&1 &
fi

printf '[redeploy] detached supervised runner started at %s; logging to %s\n' "$sha" "$log"
