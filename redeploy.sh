#!/bin/sh
# Hot-redeploy the live bot with (near) zero downtime.
#
# BotGuilds allows one session per guild: a new `hello` supersedes the old one,
# which then receives a `kick: superseded` and exits cleanly (its supervisor
# steps aside). So redeploying is just: start a fresh supervised runner. It
# fully initializes (opens the DB, warms the strategy) and only then connects —
# the cutover costs about one handshake, and the new run's window opens in the
# `runs` table as the old one's closes.
#
# Use after committing the new code AND after `reaper test` has passed. Args pass
# through to the runner (e.g. --strategy, --note). Rollback: check out a
# known-good sha (see the runs table) and run this again.
#
#   ./redeploy.sh --note "explorer: prefer nearer loot"
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)" || exit 1

sha=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)
log=${STEEMER_LOG:-steemer-live.log}

printf '[redeploy] %s handing off to %s\n' "$(date '+%Y-%m-%dT%H:%M:%S' 2>/dev/null || echo now)" "$sha" >> "$log"
nohup ./run-live.sh "$@" >> "$log" 2>&1 &
printf '[redeploy] new supervised runner started (pid %s) at %s; logging to %s\n' "$!" "$sha" "$log"
