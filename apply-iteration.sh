#!/bin/sh
# Apply phase of ONE manual improvement iteration — the "build it" half of
# orchestrator/loop.md (steps 5-11). It reads the advice analyze-iteration.sh
# produced (orchestrator/advice.md), takes optional operator guidance on the
# command line, and launches a SUPERVISED (interactive) Claude Code session that
# implements the change, verifies it, commits, redeploys, updates the notes and
# UI docs, and prints a summary — then stops WITHOUT scheduling a wakeup.
#
# Interactive on purpose: this half edits code, commits, and hot-redeploys the
# live bot, so you watch and approve each step on your own terms. Contrast with
# the fully-autonomous loop in orchestrator/loop.md, which self-paces via
# ScheduleWakeup; this one does exactly one pass and never re-arms.
#
#   ./apply-iteration.sh
#   ./apply-iteration.sh "prefer fixing the curdle action-error class first"
cd "$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)" || exit 1

ADVICE="orchestrator/advice.md"
GUIDANCE="$*"

if [ ! -f "$ADVICE" ]; then
    printf '[apply] no %s found — run ./analyze-iteration.sh first.\n' "$ADVICE" >&2
    exit 1
fi

if [ -n "$GUIDANCE" ]; then
    GUIDANCE_BLOCK="Operator guidance for THIS iteration (takes precedence over the
advice file where they conflict):
$GUIDANCE"
else
    GUIDANCE_BLOCK="No extra operator guidance was given; follow the advice file's top recommendation."
fi

PROMPT=$(cat <<PROMPT_EOF
You are running the APPLY phase of exactly ONE improvement iteration for the
steemer bot. Follow orchestrator/loop.md steps 5-11.

First read orchestrator/advice.md (the analyze phase wrote it) for the intended
path forward and the ranked recommendations.

$GUIDANCE_BLOCK

Then, for this single iteration:
- Implement the chosen change in steemer/strategy/ (or add a strategy module),
  bump the strategy version, and add tests — mutation-check every new assertion.
- Verify: uv run pytest -q, then uv run python -m steemer.replay, then the reaper
  gate per loop.md step 6. Do not redeploy on a red gate.
- Commit AND PUSH (loop.md step 7 — configured git user, no --author, no Claude
  trailer; the standing directive is "commit + push freely"), then
  ./redeploy.sh --note "...".
- Record (loop.md step 9): append the decision to decisions.log; and REVIEW +
  CURATE findings.jsonl — this is NOT append-only. Before adding entries, load
  the notebook and curate: resolve conjectures whose tests have now run
  (open -> confirmed/refuted), mark shipped considerations, fold duplicates
  together (findings.load() -> edit -> findings.rewrite(rows)). Then add any new
  discovery/conjecture/consideration for this change. Also update any UI
  doc/README affected by a dashboard change.
- Submodule check (loop.md step 10): run uv run tools/check_submodule.py; if
  upstream has moved, review and DELIBERATELY port the relevant protocol/client
  fixes into steemer/ (never a blind submodule merge), and log it. If nothing
  moved, say so and move on.
- Print a concise SUMMARY of what changed and the expected metric effect.

Do exactly one pass. Do NOT call ScheduleWakeup and do NOT schedule any
follow-up — this is a manually-triggered single iteration.
PROMPT_EOF
)

SYS_GUARD="This is a single manually-triggered iteration. Run exactly one pass and then stop. Never call ScheduleWakeup or arrange any follow-up wakeup/cron."

printf '[apply] launching supervised Claude session for one iteration...\n' >&2
# Interactive (no -p): the operator supervises and approves each action.
exec claude "$PROMPT" --append-system-prompt "$SYS_GUARD"
