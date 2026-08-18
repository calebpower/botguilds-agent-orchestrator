#!/bin/sh
# Analyze phase of ONE manual improvement iteration — the "look, don't touch"
# half of orchestrator/loop.md (steps 1-4). It gathers the KPI snapshot for the
# moves made since the last strategy-version bump, hands it (plus the game docs,
# the gameplan backlog, AND the decision history + lab notebook) to a headless
# Claude Code pass, and has that pass write the intended path forward to
# orchestrator/advice.md — which the operator reviews, and which apply-iteration.sh
# then consumes.
#
# Nothing here edits strategy code, commits, redeploys, or schedules a wakeup.
#
# NOT freely repeatable: it REFUSES to re-analyze the same strategy-version window
# with no new signal (that just re-decides the same thing). Ship a change with
# `make apply` (which bumps the version), let it accumulate, then analyze — or
# override with `--force` / `FORCE=1`. Tunables: MIN_NEW_DECISIONS (default 200),
# MIN_WINDOW_FRAMES (default 500).
#
# The KPI JSON is computed by THIS script (via tools/analyze.py) and embedded in
# the prompt; the headless pass READS the repo docs + history and WRITES advice.
#
#   ./analyze-iteration.sh [--force]
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)" || exit 1

ADVICE="orchestrator/advice.md"
STATE="orchestrator/.analyze-window"           # local cursor: the last window advised on
MIN_NEW_DECISIONS=${MIN_NEW_DECISIONS:-200}
MIN_WINDOW_FRAMES=${MIN_WINDOW_FRAMES:-500}

FORCE=${FORCE:-0}
for a in "$@"; do
    case "$a" in
        --force|-f) FORCE=1 ;;
    esac
done

# The backend is whatever config.toml selects (SQLite or MariaDB); analyze.py is
# read-only and safe against the live writer.
printf '[analyze] computing KPI snapshot from the configured backend...\n' >&2
SNAPSHOT=$(uv run tools/analyze.py --compact 2>/dev/null)
if [ -z "$SNAPSHOT" ]; then
    printf '[analyze] ABORT: could not compute a snapshot (is the DB reachable?)\n' >&2
    exit 1
fi

# Window signature = "<strategy_version>#<boundary_run_id>" (the run where the
# current strategy version began), plus total decisions and the frames
# accumulated in this window. Version bump -> new boundary -> new signature.
WIN=$(SNAP="$SNAPSHOT" uv run python -c '
import os, json
s = json.loads(os.environ["SNAP"])
runs = s.get("runs") or []
dec = int((s.get("volume") or {}).get("decisions") or 0)
b = 0
for i in range(1, len(runs)):
    if runs[i].get("strategy_version") != runs[i-1].get("strategy_version"):
        b = i
br = runs[b] if runs else {}
frames = sum(int(r.get("frames") or 0) for r in runs[b:])
print("%s#%s\t%s\t%s" % (br.get("strategy_version"), br.get("run_id"), dec, frames))
' 2>/dev/null)
SIG=$(printf '%s' "$WIN" | cut -f1)
DEC=$(printf '%s' "$WIN" | cut -f2); : "${DEC:=0}"
FRAMES=$(printf '%s' "$WIN" | cut -f3); : "${FRAMES:=0}"

# Guard against re-deciding the same window (b-1/b-3 from the review).
if [ -n "$SIG" ] && [ -f "$STATE" ]; then
    PRIOR_SIG=$(cut -f1 "$STATE"); PRIOR_DEC=$(cut -f2 "$STATE"); : "${PRIOR_DEC:=0}"
    DELTA=$(( DEC - PRIOR_DEC ))
    if [ "$SIG" = "$PRIOR_SIG" ] && [ "$DELTA" -lt "$MIN_NEW_DECISIONS" ]; then
        printf '[analyze] REFUSE: same strategy-version window (%s) as the last analysis, only %s new decisions since (< %s).\n' "$SIG" "$DELTA" "$MIN_NEW_DECISIONS" >&2
        printf '          Re-running would re-decide the same window. Ship a change with `make apply` (it bumps the\n' >&2
        printf '          version), let it accumulate, then analyze — or override: ./analyze-iteration.sh --force\n' >&2
        if [ "$FORCE" != "1" ]; then
            exit 2
        fi
        printf '[analyze] --force set; proceeding anyway.\n' >&2
    elif [ "$SIG" = "$PRIOR_SIG" ]; then
        printf '[analyze] note: same window (%s) as last analysis, +%s decisions of new signal — re-analyzing with more data.\n' "$SIG" "$DELTA" >&2
    fi
fi
if [ "$FRAMES" -lt "$MIN_WINDOW_FRAMES" ]; then
    printf '[analyze] WARN: window is young (%s frames since the last version bump; < %s). Metrics may be noisy —\n' "$FRAMES" "$MIN_WINDOW_FRAMES" >&2
    printf '          loop.md step 2 says let a version accumulate before judging.\n' >&2
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
3. Read decisions.log (the full decision history: what has already been tried,
   why, its expected vs actual effect) and findings.jsonl (the lab notebook of
   discoveries / conjectures / considerations). Use them as MEMORY:
   - Do NOT re-propose a change that decisions.log shows was already shipped and
     reverted, or already tried, UNLESS you name the specific NEW evidence in
     this window that justifies retrying it.
   - Prefer advancing an open conjecture/consideration in findings.jsonl or the
     lowest unmet gameplan milestone over rehashing settled ground.
4. Write orchestrator/advice.md (overwrite it) containing: the current KPI state,
   what changed versus the prior run window, what the game appears to reward, a
   one-line note on what history rules OUT (already-tried / rejected), and a
   RANKED list of concrete, testable next changes with the single recommended one
   first (the intended path forward). Keep it tight and skimmable.
5. Print a short summary of that advice to stdout.

advice.md is the handoff to apply-iteration.sh — make the top recommendation
unambiguous and implementable.
PROMPT_EOF
)

printf '[analyze] running headless Claude analysis pass -> %s\n' "$ADVICE" >&2
# acceptEdits lets the pass write advice.md without prompting; reads are allowed
# by default. It runs no destructive tools.
claude -p "$PROMPT" --permission-mode acceptEdits

# Record the window we just advised on, so the next run can refuse a no-op re-run.
printf '%s\t%s\t%s\n' "$SIG" "$DEC" "$FRAMES" > "$STATE"

printf '\n[analyze] done. Review %s, then run: ./apply-iteration.sh ["guidance"]\n' "$ADVICE" >&2
