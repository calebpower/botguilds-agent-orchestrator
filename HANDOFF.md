# HANDOFF — steemer bot improvement loop

_Written 2026-08-21 for a fresh Claude session (model updated mid-project). This is the
on-ramp; the durable detail lives in `decisions.log`, `findings.jsonl`, and the memory
files under `~/.claude/projects/.../memory/` (loaded each session as `MEMORY.md`)._

## TL;DR — where things stand right now

- **Live:** `explorer/0.45.0` on **run #113**, repo HEAD `5f9e0ef`, branch `main` (pushed).
  Bot writing frames ~12/s, staleness <1s. **FOUR services up: bot / web / dash / watch** —
  `watch` is the new always-on supervisor (`tools/healthcheck.py --watch 60 --fix`), which
  restarts a dead service and repairs a broken venv. Start it with `./svc.sh up watch`.
- **What this project is:** a persistent improvement loop for a bot ("Stanley_Steemer" guild)
  playing the BotGuilds multiplayer game (`bot.willmorrison.net`, ZeroMQ wire + HTTPS API).
  The strategy is `steemer/strategy/explorer.py`. Each loop pass: measure → diagnose → ship
  ONE lever → mutation-checked tests → gate → self-deploy → record → schedule next.
- **Operator** = Caleb (running it) / **Will** = the game's dev, but mostly letting his own AI
  add game content, so treat the game as an evolving target — mechanics appear without notice.
- **Current focus (operator direction, late Aug 2026):** *master every game mechanic + LEVEL
  characters while the map-progression window is open.* Gold is a FLOOR (gather only when low),
  not the goal. Also: reverse-engineer rivals.
- **Active work:** the **FORGE-TO-ARM probe** — Slice 1 (harvest) just shipped & confirmed live.
  See "In progress" below.
- **Next scheduled loop wakeup:** ~01:39 (a ScheduleWakeup is pending; its prompt measures
  0.44+0.45 and continues the forge probe). If you're resuming manually, just run a loop pass.

## How to operate

**The loop:** `orchestrator/loop.md` is the process. Each pass: health check → measure the last
deploy against prior runs → diagnose → implement ONE lever → mutation-checked tests → gate
(pytest + bounded replay + `reaper test`) → commit → self-deploy → record (decisions.log +
findings.jsonl) → update memory → schedule next wakeup with the loop prompt.

**Services** (`./svc.sh {up|down|restart|status} {bot|web|dash}`, runs directly — NOT via make,
NOT run_in_background):
- `bot` = the live player (`run-live.sh` supervises `steemer.runner`).
- `web` = sidecar (`tools/web_sidecar.py`): map-color rotation @1s + rival intel/spectate +
  rival position tracking (writes `intel` table, kind='track').
- `dash` = dashboard (`ui/server.py`, port 8800).

**✅ DEPLOY GOTCHA — FIXED 2026-08-21, the manual dance below is no longer needed.**
`./svc.sh down bot` used to leave the old `steemer.runner` alive because daemon(8) records
the CHILD pid while the process-group LEADER is daemon itself, so `kill -TERM -$pid` hit a
group that does not exist (proof: bot pid 2510, pgid 2508). `svc.sh` now resolves the real
pgid, kills the descendant tree, and REPORTS any survivor instead of swallowing it — so
`./svc.sh restart bot` is enough. (Historical workaround, kept only for context:
`OLD=$(pgrep -f steemer.runner); ./svc.sh down bot; kill $OLD; pgrep -f run-live.sh`.)
Then VERIFY liveness via the DB with a FRESH MariaDB connection (reused conns give a stale
`MAX(received_at)`): check `runs.strategy_version`/`git_sha` for the newest run and frame
staleness. A `kicked: another session hello'd — exiting` log line at redeploy is GRACEFUL
supersession of the old session, NOT a kick-war — confirm via DB freshness, not the log.

**Gate:** `reaper test` runs the full pytest incl. Playwright frontend in a Linux container;
result is in `out/pytest.log` (not stdout). Local `uv run python -m pytest -q` for fast checks.
Bounded replay over real frames: `uv run python -m steemer.replay --limit N` (set the Bash tool
timeout > the inner one; default Bash timeout is 120s). **This workstation is FreeBSD** — use
`uv run python` (no `python3`); Playwright frontend tests only run in the reaper Linux container.

## Operator standing rules (persist these — they're in memory too)

1. **NEVER hang on an operator answer.** No reply in ~10 min → act on best judgment (REVERSIBLE
   things only) + lead with a status update. Identify a process by PPID before treating it as rogue.
2. **Wishlist scoring EVERY pass** (`wishlist.md`): `final = good_idea × risk_to_bot × (0.75 − 1/tc)`,
   tc = current_minor − add_minor. RECALC + SHOW THE TABLE. Implement the top item if CLEARLY >0.5
   alongside any bot change. `good_idea` CREDITS operator enjoyment/visibility (they play too) —
   don't dock for "aesthetic"; risk_to_bot handles harm. DO dock for genuine quality limits (stale
   data, fragility). Don't inflate to clear the bar. (e.g. rival-recon is docked for ~45s-stale
   spectate / no live mobs → ~0.47.)
3. **Standing push authorization:** `git push` origin/main at your leisure once the gate is green —
   do NOT ask each time. Still NO force-push / tags / PRs / remote changes without asking.
4. **Commits:** NEVER a Claude trailer / Co-Authored-By. Commit as the repo's configured user
   (Caleb L. Power), never `--author`. Use `git commit -F <file>` for multi-line messages (avoid
   backticks in `-m`). config.toml (MariaDB creds) and guild_token.json are git-ignored — never commit.
5. **Run the submodule check EVERY pass** (`uv run tools/check_submodule.py`) — this had lapsed and
   the reference kit drifted 3 commits (see 0.44 below). Reinstated as a per-pass step.
6. Security: only test our own guild with authorization; the `say`-injection probe stays in
   `scratchpad/` (never commit to `tools/`). Server bugs → `server_bugs.md`; reaper-framework bugs
   → `/home/cal/reaper_bugs.md`; never modify `/home/cal/reaper`.

## Recent version arc (what shipped, most recent first)

- **0.45.0 — FORGE-TO-ARM probe slice 1 (harvest).** A safe, non-homing char ADJACENT to a tree/vein
  attacks the tile to harvest (`HARVEST_KINDS={tree,vein}`). Adjacent-only (zero pathing risk),
  no weapon needed, scored 3.3. **CONFIRMED LIVE:** new events `terrain_hit`/`terrain_destroyed`
  (~4 hits/tree) + `drop` item=`lumber` → pickup; 0 deaths.
- **0.44.0 — delta-frame handling port.** Reference kit was 3 commits ahead (submodule check had
  lapsed). Upstream = transport only (no new actions): zlib (our `decode` already handled) + delta
  TILE frames + a REFRESH/seq-gap resync. Verified live only TILES are delta'd (entities/items/gold
  full every frame). Ported (`steemer/protocol.py`+`client.py`, hand-ported NOT merged):
  `is_seq_gap`→client sends REFRESH on a dropped-frame gap; `reassemble_tiles` rebuilds a delta
  frame's `visible.tiles` to the full set before log/on_frame. Pin advanced to reviewed `588702a`.
- **0.43.0 — recruit-burst fix.** The recruit gate trusted `bot.spectate.counts()` (public spectate
  total), which LAGGED our post-deploy roster (froze at 9 for ~176 ticks while real was ~30) → it
  recruited a ~21-char bare bench each deploy. Fix: `roster = max(auth, fresh snapshot) + in-flight
  recruits`. Verified: 0 recruits/235 ticks vs 21.
- **0.42.0 — stuck-death ROOT fix.** The dominant "hurt char rests and bleeds out cornered" deaths:
  the `STUCK_BLOCK` learned-block blacklisted ANY tile a move failed to land on, but ~all move
  failures were `not_enough_stamina` (frame-stale margin), so it poisoned walkable tiles and walled
  chars in. Fix (bot.py): record per-char move-fail reason via `on_action_error`, DON'T learn-block
  on `not_enough_stamina`. Plus a desperation-escape net (hurt+cornered → step onto any clear
  non-wall tile even unseen). Verified: our-deaths 0.14→0.0/1k, move_failed halved.
- **0.41.0 — combat-seek.** Armed + healthy (hp≥70%, sta≥15) chars FIGHT beatable mobs for XP:
  (A) a lone adjacent melee predator (override the dodge), (B) seek benign wildlife. Never
  undead/swarm. Verified clean win: XP/1k +30-44%, avg level climbing, 0 combat deaths.
- **0.40 arm-up** (unfroze weapon-buy, gold-floor 150) · **0.37-0.39.1** survival arc (predator
  spacing → mode-gating → per-char roles guardian/forager → value-gated forager boldness).

## In progress — FORGE-TO-ARM probe (the active thread)

**Why:** leveling is throttled by ARMING. Gold sits ~140, just below the 150 arm-floor, in
coin-dry bands → 15-24 of ~30 roster chars are BARE → can't combat-seek → can't level. If we can
CRAFT weapons from harvested materials we stop depending on scarce gold.

**The blind spot we're fixing:** trees/bush/rock/vein/forge/cauldron were all in `nav.SOLID`
(inherited from the reference starter bots), so we pathfound AROUND them and never touched them;
our `attack` only ever targeted monsters (`ctx.enemies`). So the entire terrain-harvest layer went
unmined — we got lumber/ore only PASSIVELY as loot. docs/08 documented it ("trees break after a few
attacks; vein drops ore"). We DO already brew (herbs→potions, ~87%) and smelt (2 ore→ingot) and
forage herbs; forging was DEFERRED (docs/07: "forge needs an unpublished product name").

**Chain:** tree → chop → lumber · vein → break → ore → smelt → ingot · forge (worked from adjacent,
mines pillar) with ingot + lumber (+ flux) → a hafted weapon.

**Slices:**
- ✅ **Slice 1 (0.45) — harvest.** Done & confirmed live (lumber flowing, 0 deaths).
- ⏳ **Slice 2 — seek + tool.** Path toward nearby resources when idle; prefer the axe/pickaxe
  (a `pickaxe` already shows in inventories). **Measure the YIELD question FIRST:** on run #103,
  133 terrain_destroyed produced only 8 lumber `drop` events (~6%). Measure material STOCK, not
  destroy counts — a tool may be exactly what changes the conversion.
- ⏳ **Slice 3 — forge + product-name discovery.** Probe the forge event's `product`/`tells` to
  learn the hafted-weapon product name (the piece deferred long ago), then craft ingot+lumber→weapon.
- ⏳ **Slice 4 — wire to arming.** Prefer forging a weapon over the gold-gated buy → breaks the throttle.

**Measure between slices:** material stock accumulating? deaths STILL ~0 (harvest must not strand
chars)? any char PINNED chopping a tree that won't break (terrain_hit without terrain_destroyed for
one eid/tile over many ticks → add a per-tile give-up)? move_failed not worse?

## Open flags / next candidates (not yet built)

- **~~Watchdog-cron gap~~ — CLOSED 2026-08-21** without needing the operator's crontab: the
  supervisor is a 4th *service* (`./svc.sh up watch`), covering bot frames, sidecar `intel`
  freshness and the dash port. It survives a reboot only if the operator starts it, though —
  **if you find `watch` down, start it first.**
- **venv ABI break after an OS update (WILL recur):** a FreeBSD/python update makes `uv` rebuild
  `.venv` and reinstall a CACHED locally-compiled pyzmq built for the previous interpreter →
  SIGSEGV (exit 139) on every start. Repair:
  `uv pip install --no-cache --no-binary pyzmq --force-reinstall pyzmq` then
  `uv cache clean pyzmq --force`. The supervisor now smoke-tests and repairs this itself.
- **rival-recon dashboard** (operator's reverse-engineering priority): ~0.47 on the wishlist after
  honest stale-data dock. The rival position-tracking data IS flowing (`intel` kind='track'). Worth
  an explicit operator greenlight (like the codex got).
- **how-nav** dashboard guide: hovering right at the 0.50 wishlist boundary.
- **move-prediction (b) for rivals:** `steemer/mob_predict.py` does mobs (rule-based, 89% chaser
  dir); the rivals half is open.

## Key gotchas & diagnostics learned (save yourself the pain)

- **Attribute OUR deaths carefully:** the `death` event fires for MOBS too. Count our-char deaths by
  eid-in-our-roster AND death payload `kind_name=='char'` (raw counts include mobs; our true rate
  ~0.4/1k historically, ~0 since 0.42). fast-SQL death counts also include RIVAL deaths.
- **Check coins-available per field frame BEFORE any income/gold delta** — a coin-dry band (0
  gold-tiles/frame) voids gold-trend reads (we've had run windows at 0.00 tiles/frame).
- **`kpi.compute_run_kpis` TIMES OUT** on big runs — use FAST SQL / event-count queries.
- **Frames:** stored zlib-compressed JSON; decode with `zlib.decompress` then `json.loads` (on
  MariaDB the col may come back str → `.encode('latin-1')` first). `visible.tiles` was SPARSE under
  deltas; since 0.44 the client reassembles to full before storing.
- **ONE global server `tick`** shared by all data sources — join cross-source data on tick, never
  wall-clock.
- **Verify a schema before writing SQL against it.** Event payloads live in `events.payload_json`.
- Meaningful event kinds: `death, xp, stat_up, attack, move, move_failed, recruit, foraged, drop,
  terrain_hit, terrain_destroyed, smelt_started, sale, gold, band_refresh*`.

## Where the detail lives

- `decisions.log` — the running narrative, one ITER block per pass (currently through iter 57).
- `findings.jsonl` — structured findings/measurements (one JSON per line).
- `wishlist.md` — candidate features + what's shipped.
- `docs/` — the game reference (02-protocol, 03-actions, 07-crafting, 08-world-and-economy, …).
- `reference_starter_kit/` — the upstream submodule (pinned at reviewed `588702a`; check for drift
  each pass with `tools/check_submodule.py`).
- Memory files (auto-loaded): `MEMORY.md` index + `resume-state-2026-08-18.md` (topic file),
  `wishlist-scoring.md`, `push-authorization.md`, `never-hang-the-loop.md`,
  `deploy-and-backend-gotchas.md`.

## Immediate next action for the new session

1. Health check — now one command: `uv run python tools/healthcheck.py` (exit 0/1/2, JSON).
   Confirm all FOUR services incl. `watch`; run the submodule check.
2. 0.44 + 0.45 are MEASURED (iter 58): harvest is entirely ours, 4.1 hits/destroy, no pinning,
   and #103's deaths were the outage window, not the mechanic. **Beware the attribution trap:**
   `eid` (numeric) and `char_uid` (string) are different namespaces — see `decisions.log` iter 58.
3. Forge-to-arm Slice 2 — but answer the YIELD question first (does material STOCK accumulate?).
   Then Slice 3 (forge + product-name discovery).
4. Show the wishlist table; record; commit + push; schedule the next wakeup.
