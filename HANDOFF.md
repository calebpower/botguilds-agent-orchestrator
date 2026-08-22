# HANDOFF — steemer bot improvement loop

_Written 2026-08-21 for a fresh Claude session (model updated mid-project). This is the
on-ramp; the durable detail lives in `decisions.log`, `findings.jsonl`, and the memory
files under `~/.claude/projects/.../memory/` (loaded each session as `MEMORY.md`)._

## TL;DR — where things stand right now

- **Live:** `explorer/0.66.0` on **run #144**, repo HEAD `e791a9d`, branch `main` (pushed).
  Bot writing frames ~12/s, staleness <1s. **FOUR services up: bot / web / dash / watch** —
  `watch` is the always-on supervisor (`tools/healthcheck.py --watch 60 --fix`).
- **What this project is:** a persistent improvement loop for a bot ("Stanley_Steemer" guild)
  playing the BotGuilds multiplayer game (`bot.willmorrison.net`, ZeroMQ wire + HTTPS API).
  The strategy is `steemer/strategy/explorer.py`. Each loop pass: measure → diagnose → ship
  ONE lever → mutation-checked tests → gate → self-deploy → record → schedule next.
- **Operator** = Caleb (running it) / **Will** = the game's dev, but mostly letting his own AI
  add game content, so treat the game as an evolving target — mechanics appear without notice.
- **Current focus (operator direction, late Aug 2026):** *master every game mechanic + LEVEL
  characters while the map-progression window is open.* Gold is a FLOOR (gather only when low),
  not the goal. Also: reverse-engineer rivals.
- **The M3a CRAFTING CHAIN IS CLOSED** (0.52.0 forge + 0.53.0 equip-upgrade): harvest → smelt →
  forge → wear. Recipes learned from the server's own rejections: **spear = 1 ingot + 1 lumber,
  dagger = 1 + 1, shield_iron = 3 ingots + 1 lumber**. The server ACCEPTS equipping into an
  OCCUPIED slot (confirmed live, run #130, club → dagger in place), so gear displaces worse gear
  ranked on the shop's own `buy_price`.
- **THE MAP IS NOW PERSISTENT** (0.55.0): `bot.known` is hydrated from `tiles_seen` at startup
  (26,467 tiles, 0.55s). Before this the bot started map-blind every run and `tiles_seen` had no
  reader at all. **This broke things and the repairs matter more than the feature** — read the
  two entries below before touching navigation.
- **⚠ TWO RULES THE HYDRATION REGRESSION BOUGHT (iter 69, runs #131–#134):**
  1. **Field errands are BOUNDED** to `FIELD_GOAL_RANGE=20` (0.57.0). Every goal search used to
     be unbounded, which was safe only because the old map was small. With a full map,
     chest-beelining became a cross-map pilgrimage and move failures went 5.2% → 19.4%.
     Bounding took them to **1.5%**, below the original baseline.
  2. **`_retreat` is EXPLICITLY UNBOUNDED and must stay so.** It walks home via the same helper
     (goal `y == 0`) and characters range to y=199. Bounding it strands hurt characters on
     `rest` — the stuck-death of 0.42/0.50. The full suite passed with that bug in; a test now
     walks a character home from 100 tiles out.
  3. **Remembered TERRAIN is durable; remembered CONTENTS are not** (0.56.0). Chests are scoped
     to tiles seen THIS run, because a chest gets opened and refills on the band's schedule.
- **🔎 THE BOT NOW CHECKS ITS OWN BELIEFS (0.61.0, `steemer/expectation.py`).** It derives a
  checkable claim from every action it sends and resolves it against later frames as
  confirmed / violated / **expired**. `expired` is not `violated` — frames are stale and
  "not yet" must never read as "did not" (that inference killed two characters). Alarms are
  PER ACTION FAMILY and print + persist as `bot_anomaly` rows.
- **⚠ OWNERSHIP-FILTER EVERY EVENT-DERIVED METRIC — IT IS THE FIRST STEP, NOT A REMINDER.**
  The `forged`/`death`/`sale` streams are WORLD-WIDE. I reported 0.64.0 confirmed on a forge
  success rate of 35%→68%; both figures counted rival forges (run #141's `forged` items
  included pickaxe ×5 and sickle ×3, which we never attempted). Filtered to our own eids the
  real series is 33% / 26% / 21% / 17% across #129/#140/#141/#143 — **flat, no gain.**
- **⚠ ASK OF ANYTHING THE STRATEGY LEARNS: DOES IT SURVIVE A DEPLOY?** A fresh process looks
  identical to a knowledgeable one for the first few minutes, which is why this hid. Run #143:
  one character spent 20 of 23 forge attempts re-walking a ladder run #129 had already solved.
  **0.66.0 persists PROVEN recipes** (`learned` table, hydrated once per process) and sends
  only the proven quantity for a product. Only POSITIVE facts are stored — a persisted failure
  would carry a wrong belief forever, since `wrong_materials` is non-deterministic.
  Still in-memory-only: `slot_wrong`, `wont_fit`, `_tome_failed`, `_swap_failed`, `price`.
- **⚠ A LEARN-BY-REJECTION LOOP NEEDS POSITIVE EVIDENCE, OR IT RATCHETS SHUT (0.64.0).** The
  forge blacklisted a recipe on its FIRST `wrong_materials`. That refusal is NOT deterministic
  in what we keyed on — identical product, material kinds and quantities both succeed and fail
  within one run — so refusals only ever removed options and had condemned **all five spear
  recipes and all five shield_iron recipes**, including `(spear,1,1)`, which we had watched
  work twice. Now: a `forged` event PROVES the recipe that character last attempted; proven
  recipes are never blacklisted; unproven ones need 3 refusals; proof clears a wrongful ban.
  **AUDIT NOW COMPLETE (0.65.0/0.65.1).** Released: `wont_fit` and `_tome_failed` — both
  gated on STATS, which we deliberately raise (`spend_xp` x2,151; str 2→6, level 6→18), so a
  refusal at str 2 stood at str 6 forever. Each now records the stat TOTAL refused: out-grow
  it and retry; a second refusal raises the bar; a weaker one cannot lower it. `wont_fit` was
  also global (one weak character condemned a kind for everyone) and is now per-character.
  Left alone with reasons: `slot_wrong` and `_swap_failed` (a fixed property of the kind, not
  a moving threshold), `STUCK_BLOCK` (already a TTL), `price` (learned upward).
  (Cause of the non-determinism is still unknown — `tier` is the suspect, we ignore it.)
- **⚠ COMPARE STATEFUL THINGS STATEFULLY.** A replay with a FRESH strategy per frame claimed
  97% of forge opportunities were missed; one stateful instance over the same run reproduced
  the live counts exactly (forge 18 vs 18) and found the real cause. Cousin of the iter-71
  rule about replaying the same frames through both versions.
- **Depth chain status:** brewing throughput is the gate — only **1.4%** of village
  char-frames can brew at all and **0.34%** can brew a vigor (`potion_red`) batch, though 32%
  carry a bottle. `potion_red` carried is 4.1%, up from 0% before 0.58. The inputs are there;
  the batch is the missing half.
- **📡 RIVALS TAB (dashboard) — cross-guild comparison, `/api/recon`.** Reads the `spectate`
  and `track` intel feeds that had been written for months and never read back. Two findings
  from the first look, both about us:
  **(1)** We field the **only fully-armed roster on the server** (10/10 vs WillMorr 9/30,
  Fable 2/9) and the highest median level (8 vs 3 and 2). Their max is 29 to our 16 — one
  veteran in front of a large unarmed bench.
  **(2)** **Rivals work at depth 29–43 (max 57); our characters sit at median depth 2.** That
  is `POISON_SAFE_DEPTH` seen from the OUTSIDE, on live data, with no knowledge of our code —
  independent confirmation that DEPTH, not seeking, is the ore bottleneck.
  Also: nobody is outfitted (us 0/10), and `smith_apron` is a kind a rival fields and we never
  have.
- **⚠ CHECK WHAT WE SELL BEFORE BELIEVING A CHAIN IS BLOCKED. Four for four.** `_should_sell`
  has a catch-all branch — "nothing recognised -> bank it" — and every mechanic we unlock adds
  an item it silently misfiles. It has now eaten lumber+ingots (fixed 0.46), `bone` and raw
  `ore` (0.59), and **74 TOMES** (0.63): ring 22, step 16, field 14, veil 13, bolt 9, sold for
  36-44 gold each against a 120-150 shop price, most recently runs #130/#135/#137 — while
  "magic is unaffordable" sat at the top of the wishlist for fifty passes and we had never
  learned a single spell. 0.63.0 keeps tomes under `spell_cap` and `use`s them before the sell
  step. **Casting is still unbuilt** — a form in a head is not a spell thrown.
- **⚠ THE SERVER REFUSES THROUGH TWO CHANNELS — action_errors AND EVENTS.** We watched only
  one for the whole project. `overburdened` is an EVENT, so 1,164 refused pickups were
  invisible to every action_error query while a character burned hundreds of ticks. **When an
  action fails silently, check the event stream too.**
  Fixed in 0.62.0 by trusting the refusal (TTL, scoped to our eids): a refused character reads
  as full AND sheds. The underlying gap was a UNITS MISMATCH — our fullness test counts SLOTS
  (`used >= cap - 1`) while capacity is spent in BULK, so carry (19, 21) could not take a
  bulk-3 item, was not "full" (needs 20) and was not shedding (needs 21).
  **BAND-DEPENDENT and currently dormant:** #137 (rich) lost 1,164 pickups; #138 (starved) had
  103 pickups, 71 successes, 0 overburdened. Do not read the absence of a delta on a starved
  run as failure — measure when loot returns.
- **BANDS REFRESH — now DETECTED (0.60.0), and the rule it bought.** Each field frame carries
  `next_refresh: {band, in_ticks}`; a refresh is a change in the band NUMBER **or** a JUMP UP in
  `in_ticks` (a countdown only falls). Per world; ~10 boundaries per 14,000 ticks. Loot swings
  **~900x within a single run** (0.052 → 1.839 → 0.002 visible items/frame), which idles the whole
  economy in the trough: no loot → nothing carried → nothing sold → gold under the arm floor.
  **NEVER attribute an economy metric across a refresh boundary** — that cost iter 71 its
  measurement and nearly caused a false rollback of a good change. And before blaming a code
  change, replay the SAME frames through BOTH versions; doing that gave byte-identical output and
  refuted my own diagnosis.
  0.60.0's first use: a refresh REFILLS chests, so emptied ones become targets again (the guess is
  kept OUT of `known`, which records only what we observed). **Modest, and I overstated it in the
  commit message** — 22 distinct emptied chests in the whole map, not the thousands the sighting
  count implied. **The bigger half is unbuilt: timing GATHERING to the cycle.**
- **⛓ THE ORE CHAIN, and why three passes of it did nothing (iter 70).** Vein-seek was never
  the problem. On run #134 it fired 751 times and NO CHARACTER WAS EVER ADJACENT TO A VEIN:
  characters sit at **median depth y=2** while the shallowest vein is y=26. `POISON_SAFE_DEPTH=12`
  caps any character without a `potion_red`, and **0.0% carried one** — because brewing needs a
  `bottle_empty` and there was NO PATH TO ACQUIRE ONE (it appeared only in KEEP and the brew
  gate's counter). That silently invalidated v0.35.0's `POTION_RESERVE=600`, which was
  explicitly premised on heals being 99.6% free-brewed. **0.58.0 buys bottles (2 gold).**
  Verified: 2 bottles → 2 brews on #135, against 0 brews in the previous 31,011 frames.
  **STILL OPEN — measure in this order:** `potion_red` carried > 0% → mines depth p90 above 12
  → veins broken above 0. Neither brewing character happened to hold a VIGOR batch; `embercap`
  is vigor (high confidence) and widely carried, so heals should follow. If it stalls, the next
  link is to prefer/keep embercap for vigor batches.
- **Other open gaps:** (1) `nav.frontier` treats OUT-OF-BOUNDS as unexplored, so every map-edge
  tile is a permanent false frontier (201 off-map moves on #132) — needs the frame's `bounds`
  plumbed into nav; (2) `shield_iron` has no shop price so it cannot be ranked for a swap, only
  worn into an empty offhand.
- **Next pass takes the expectation/reality mismatch detector** (wishlist, 0.534, qualified two
  passes running). Iters 69 and 70 are its argument: a lever that shipped INERT, a regression
  that shipped GREEN, and a premise that stopped being true with nothing watching.
- **⚠ INFRA: `reaper up` HANGS INDEFINITELY after printing its success line.** Cost ~45 min this
  session. `reaper test` against the already-up session works fine (~2 min). Once `reaper list`
  shows the session up, stop waiting on `up` and run `reaper test` directly. Killing `up` also
  kills its `heartbeat` child and marks the session DEAD — see `/home/cal/reaper_bugs.md`.
- **Do NOT rebuild the async storage mirror.** 0.51.0 tried and segfaulted the live bot; 0.51.1's
  reorder alone gave run #128 **0 gaps and 0.0% frame loss** over 85,319 frames.
- **Resuming:** just run a loop pass. Start with `uv run python tools/healthcheck.py`.

## How to operate

**The loop:** `orchestrator/loop.md` is the process. Each pass: health check → measure the last
deploy against prior runs → diagnose → implement ONE lever → mutation-checked tests → gate
(pytest + bounded replay + `reaper test`) → commit → self-deploy → record (decisions.log +
findings.jsonl) → update memory → schedule next wakeup with the loop prompt.

**Services** (`./svc.sh {up|down|restart|status|pgid} {bot|web|dash|watch}`, runs directly — NOT
via make, NOT run_in_background):
- `bot` = the live player (`run-live.sh` supervises `steemer.runner`).
- `web` = sidecar (`tools/web_sidecar.py`): map-color rotation @1s + rival intel/spectate +
  rival position tracking (writes `intel` table, kind='track').
- `dash` = dashboard (`ui/server.py`, port 8800).
- `watch` = the supervisor (`tools/healthcheck.py --watch 60 --fix`): restarts a dead bot/web/dash
  and repairs an ABI-broken venv. Logs to `healthcheck.log`, and ONLY when something is wrong.

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

**Verification tools (use them; they exist because green tests were not enough):**
- `uv run python -m steemer.shadow --run <id> --limit 3000` — would the candidate actually
  WIN any ticks? Read the INERT list first. It refuses to rule on a short sample.
- `tools/mutate.py` — the mutation harness. **Never re-roll it in a scratch script**: the
  ad-hoc versions restored sources in a way that made CPython serve the MUTANT's stale
  bytecode, so mutants reported each other's results (see `memory/verification-traps.md`).

**Gate:** if `reaper up` fails with `unable to create VM NNNN: config file already exists`, the
previous session EXPIRED and `down` forgot it without reclaiming the VM. Recover with
`reaper down --all && reaper up` — no hypervisor access needed (logged in `/home/cal/reaper_bugs.md`).
Sessions expire in ~2h, so expect this after any long gap.
`reaper test` runs the full pytest incl. Playwright frontend in a Linux container;
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
- ✅ **Slice 2 (0.46) — feedstock reserve.** The yield question redirected this slice. Harvest was
  fine; run #113 chopped 282 trees and then SOLD 189 lumber, 4 ore and 2 INGOTS, because
  `_should_sell` banks anything without recognised `uses`. Now reserved (4 per KIND per char,
  surplus still sells — bounded so it cannot re-create the v0.19.0 carry clog). `drop` events
  UNDER-REPORT; measure material STOCK from inventories, never drop counts.
- ⏳ **Slice 2b — seek + tool** (deferred, and no longer urgent): path toward resources when idle,
  prefer the axe/pickaxe. Only worth it once stock is proven to hold a floor on #114.
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
3. **Measure 0.48.1 on a matured #117.** Falsification stated before deploy: mean pairwise
   distance must FALL in dangerous worlds and stay flat in safe ones; our-char deaths must
   not rise; damage taken per kill should fall; `move_failed` must not rise (the oscillation
   tell); safe-world gathering per 1k unchanged.
   **Do not judge liveness from the first minutes** — a redeploy resets learned state, so a
   gated branch cannot fire until it is re-learned. v0.48.0 was wrongly called inert this
   way. Use `uv run python -m steemer.shadow --run <id> --limit 3000`.

4. **NEXT LEVER: the GOLD SINK.** 14-31 clubs bought per run at 15g for bare recruits, while
   gold peaks ~165 against ARMOR_BUY_FLOOR=200 — so that single sink starves BOTH the armor
   buy (which has never once fired) and the forge chain. It is a village-economy change, so
   it will not collide with 0.48.1's field-behaviour window.
   **Run it through the shadow gate before deploying** (`steemer/shadow.py`); that tool
   exists because two changes shipped green and did nothing this session.
   After that: M3a forging still tops the wishlist at 0.571, its product name is known, and
   we now hold INGOTS — the remaining blocker is ORE.

5. Show the wishlist table; record; commit + push; schedule the next wakeup.
