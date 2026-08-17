# The improvement loop

This is the runbook the Claude Code loop follows to improve the bot autonomously.
The live bot runs standalone (see the README); this loop *watches and improves*
it. It is self-paced: each strategy version must run long enough to gather signal
before it is judged — think hours per iteration, not minutes.

## Standing directives (from the operator)

- **Check in at strategy pivots**, not tactical changes — but a slow reply must
  never block progress: proceed on best judgment and log it.
- **Reaper runs in a background subagent.** Never block the main thread on a
  multi-minute VM run; keep doing frontrunner work and reconcile if the reaper
  agent touches tracked files (it only writes the gitignored `out/`).
- **`guild_token.json` is never committed.** The pre-commit hook enforces it.
- **Commit + push freely** for this repo; commit as the configured git user, no
  `--author`, **no Claude trailer**.
- **Server bugs → `server_bugs.md`.** Reaper-framework bugs → `/home/cal/reaper_bugs.md`.
  Never modify `/home/cal/reaper`.
- **Testing ethic** (see `~/.claude/CLAUDE.md`): every fix ships with a test that
  would have caught it; mutation-check every new assertion (break it, watch it
  fail); never weaken a check to route around a defect.

## Usage-cap failure mode (read this first each tick)

The loop runs on the operator's Claude usage. If that caps out, **the game must
keep playing** — so protection is layered:

1. **The bot is detached from the Claude session.** `redeploy.sh` launches it via
   `daemon(8)` (FreeBSD) / `setsid` (Linux), reparented to init — it survives the
   Claude session ending. A cap pauses *improvement*, never *play*. (Verify:
   `pgrep -f steemer.runner` chain roots at PID 1.)
2. **Safety invariant so a mid-cap interruption never breaks the running bot:**
   the only irreversible/outward step is the hot-redeploy, and it happens *only
   after* local pytest + the reaper gate + a commit. If a cap interrupts the loop
   at any earlier point, the worst case is an uncommitted improvement — the live
   (previous) version keeps playing, unharmed.
3. **Graceful degradation via `orchestrator/loop_config.json`** (read it at the
   start of every tick; there is no readable usage-% signal, so this is the
   operator's lever and the loop self-adjusts + logs when it has any budget hint):
   - `mode: normal` — full loop at `cadence_seconds`.
   - `mode: conserve` — self-nerf as the cap nears: skip UI upgrades and the
     reaper VM gate (verify locally with pytest + replay only), act only on clear
     high-value wins, and lengthen the wakeup ~2–3×. This is the "slow the
     decision factors during the last 10%" behavior.
   - `mode: pause` — call `ScheduleWakeup(stop: true)` and stop; the detached bot
     plays solo with zero ongoing Claude usage until the operator restarts the
     loop. Log that it paused and why.
   Adjustments to this ladder are themselves fair game during self-improvement —
   just record them in `decisions.log`.

## One iteration

1. **Ensure the bot is live.** Confirm a current open run window:
   `sqlite3 guild_log.db "SELECT run_id,git_sha,strategy_version,started_at,stopped_at FROM runs ORDER BY run_id DESC LIMIT 3"`.
   If none is open (stopped_at NULL), start it: `./run-live.sh` (or `./redeploy.sh`).

2. **Let it accumulate.** Give the current version enough game-time that rate
   metrics are meaningful. Use `ScheduleWakeup` (self-paced) with a long interval;
   don't judge a version on a handful of ticks.

3. **Analyze — in a subagent.** Run `uv run tools/analyze.py --db guild_log.db`
   and hand the JSON to an analysis subagent along with `docs/` for game context.
   Ask it: what is the current KPI state; what changed vs the previous run
   window; what does the game appear to reward; and the top few concrete,
   testable improvements, ranked. Keep the raw data out of the main thread.

4. **Pick a change.** Tactical (tuning scores, fixing an action-error class,
   handling a newly-seen event) → proceed. Strategy pivot (new build direction,
   changing the optimization target, a big rewrite) → notify the operator, then
   proceed on best judgment if no timely reply.

5. **Implement.** Edit `steemer/strategy/` (or add a new strategy module). **Bump
   the strategy `version`** so metrics attribute correctly. Add/adjust tests and
   **mutation-check** them.

6. **Verify.**
   - Fast: `uv run pytest -q` locally.
   - Regression on real history: `uv run python -m steemer.replay --db guild_log.db -v`
     to see how the new engine would have decided on past frames.
   - Gate (subagent): `reaper up` (if no session) → `reaper test` → report →
     `reaper down` when idle. Do not redeploy on a red gate.

7. **Commit + push.** Review `git status` first (never the token). Message says
   what changed and the expected metric effect.

8. **Redeploy.** `./redeploy.sh --note "<what changed>"` — the new runner
   supersedes the old with ~zero downtime; the old run window closes, a new one
   opens. **Rollback:** pick the last known-good `git_sha` from `runs`,
   `git checkout <sha>`, `./redeploy.sh`, then return to the working branch.

9. **Record.** Append to `decisions.log` under a `## YYYY-MM-DD HH:MM — title`
   header (local time): what, why, expected effect, how it would be falsified.
   After the next window, note the actual effect. Also update the **lab
   notebook** (`findings.jsonl`) — see below.

10. **Periodically** run `uv run tools/check_submodule.py`; if upstream moved,
    review and deliberately port relevant protocol/client fixes into `steemer/`
    (never a blind submodule merge). Log it.

11. **Consider a UI upgrade (optional, operator-requested).** Each iteration,
    weigh whether a dashboard improvement is worth it — a graph/analysis view
    that helps read the metrics, a practical panel, or something the operator
    would simply enjoy. Not required every tick; entirely discretionary. Build UI
    changes in a `ui/`-scoped subagent, verify (routes 200, self-contained, no
    CDNs), restart the UI on 8800, and commit. Candidate ideas live in
    `findings.jsonl` as `consideration` entries tagged `ui`.

## Metric attribution

The world is shared, persistent, and noisy, so there is no clean simultaneous
A/B on one guild. Use **sequential before/after windows** on **rate** metrics
(per-hour), each long enough to gather signal. State the uncertainty honestly in
`decisions.log`; a swing inside noise is not a result. `runs` (git sha + strategy
version + window) is the attribution backbone; `analyze.py` surfaces per-run
gold delta and error rate.

## Lab notebook (`findings.jsonl`)

The game hides its content, so building an evidence-backed model of it is a
first-class goal, not a side effect. Maintain `findings.jsonl` (schema and
helpers in `steemer/findings.py`; surfaced on the UI's Findings tab) every
iteration:

- **discovery** — a fact learned about the game. A *confirmed* discovery must
  carry `evidence` (the event/query that shows it).
- **conjecture** — a hypothesis about a hidden mechanic. Must carry a
  `confidence` and a `test` (how it would be **falsified**) — a conjecture
  without a falsification test is noise, the same rule as "every fix ships with a
  test". Move it to `confirmed`/`refuted` when the test resolves.
- **consideration** — an orchestration idea being weighed, before it graduates
  into `decisions.log` as a change.

Append with `steemer.findings.append(...)` (it validates and timestamps).

**Review the notebook every iteration — do not just append.** Before adding new
entries, read the existing ones and *curate*: resolve conjectures whose tests
have run (`open` → `confirmed`/`refuted`), mark shipped considerations `shipped`,
fold duplicates together. Curation is a first-class op: `findings.load()`, edit
the list, `findings.rewrite(rows)` (validates every entry, writes atomically).
Append-only rot — a pile of stale `open` conjectures sitting next to the
discoveries that already resolved them — is the failure mode here; a short review
pass each loop keeps this committed knowledge honest and legible.

## First objective: discover what the game rewards

Start broad (the `explorer` baseline): survive, explore, exercise every mechanic.
Watch which signals move — gold/hr, xp/hr, deaths, exploration depth, craft
outcomes, action-error classes — and let that steer specialization. Don't
hard-code content (items, enemies, recipes); learn it from `guild_log.db` and the
event stream, exactly as the game intends.

### Periodic usage check-in

No readable usage-% signal exists, so the loop **asks the operator** for current
Claude usage every `usage_checkin_every_ticks` ticks (or when `last_usage` is
stale) and maps the answer via `usage_to_mode` (normal <85%, conserve 85-95%,
pause >=95%), recording it in `loop_config.last_usage`. Never block on the answer
- if the operator is away, proceed on the last known mode. When a reset time is
given, schedule the next wake for just after it.
