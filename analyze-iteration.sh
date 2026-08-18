#!/bin/sh
# Analyze phase of ONE manual improvement iteration — the "look, don't touch"
# half of orchestrator/loop.md (steps 1-4). It gathers the KPI snapshot for the
# moves made since the last strategy-version bump, hands it (plus the game docs
# and the gameplan backlog) to a headless Claude Code pass, and has that pass
# write the intended path forward to orchestrator/advice.md — which the operator
# reviews, and which apply-iteration.sh then consumes.
#
# Nothing here edits strategy code, commits, redeploys, or schedules a wakeup.
# It is safe to run repeatedly; each run overwrites advice.md.
#
# The KPI JSON is computed by THIS script (via tools/analyze.py) and embedded in
# the prompt, so the headless pass only needs to READ the repo docs and WRITE the
# advice file — no interactive permission prompts to answer.
#
#   ./analyze-iteration.sh
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)" || exit 1

ADVICE="orchestrator/advice.md"

# The backend is whatever config.toml selects (SQLite or MariaDB); analyze.py is
# read-only and safe against the live writer.
printf '[analyze] computing KPI snapshot from the configured backend...\n' >&2
SNAPSHOT=$(uv run tools/analyze.py --compact 2>/dev/null)
if [ -z "$SNAPSHOT" ]; then
    printf '[analyze] ABORT: could not compute a snapshot (is the DB reachable?)\n' >&2
    exit 1
fi

PROMPT=$(cat <<PROMPT_EOF
You are running the ANALYZE phase of one improvement iteration for the steemer
bot. Follow orchestrator/loop.md steps 1-4 ONLY. Do NOT edit strategy code, run
tests, commit, redeploy, or schedule any wakeup — this pass only analyzes and
advises.

Here is the current KPI snapshot (from tools/analyze.py, JSON):

$SNAPSHOT

Your tasks:
1. From the "runs" array, identify the LAST strategy-version boundary — the most
   recent run whose strategy_version differs from the one before it — and treat
   "the moves since then" as the window under review.
2. Read docs/ for game context and orchestrator/gameplan.md for the milestone
   backlog. Determine the lowest unmet milestone.
3. Write orchestrator/advice.md (overwrite it) containing: the current KPI state,
   what changed versus the prior run window, what the game appears to reward, and
   a RANKED list of concrete, testable next changes with the single recommended
   one first (the intended path forward). Keep it tight and skimmable.
4. Print a short summary of that advice to stdout.

advice.md is the handoff to apply-iteration.sh — make the top recommendation
unambiguous and implementable.
PROMPT_EOF
)

printf '[analyze] running headless Claude analysis pass -> %s\n' "$ADVICE" >&2
# acceptEdits lets the pass write advice.md without prompting; reads are allowed
# by default. It runs no destructive tools.
claude -p "$PROMPT" --permission-mode acceptEdits

printf '\n[analyze] done. Review %s, then run: ./apply-iteration.sh ["guidance"]\n' "$ADVICE" >&2
