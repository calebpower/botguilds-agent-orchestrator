# HANDOFF — steemer bot improvement loop

_Written 2026-08-21 for a fresh Claude session (model updated mid-project). This is the
on-ramp; the durable detail lives in `decisions.log`, `findings.jsonl`, and the memory
files under `~/.claude/projects/.../memory/` (loaded each session as `MEMORY.md`)._

## TL;DR — where things stand right now

- **DIRECTION (operator, 2026-08-23): FOCUS ON ARMING + LEVELING; DEPRIORITISE ML.** The
  ML pipeline is a spectator — 6 models deployed, ZERO modulate behaviour, and all predict
  survival/economy while the real bottleneck is ARMING (logistics/mechanics, no model
  touches it). Next levers target the arm rate + leveling, NOT ML Pass 4/5. Smith pipeline
  (0.98.0) is the live thread; slice 2 = ingot scarcity. Return to ML only when a model
  is load-bearing (recruit-quality / XP-rate feeding leveling), not the ones we have.

- **Live:** `explorer/0.103.0` (pending self-deploy; #195 is the last measured run).
- **LINE DANCE FIX (0.103.0)**: un-healed chars oscillated N/S at the POISON_SAFE_DEPTH=12
  boundary (run #195 c19457 at y12/13) — the gather block pulled them past the cap for loot
  (4.0) while the retreat pushed them home (2.5), and the two alternated forever. FIX: a
  `deep_ok(step)` guard suppresses a gather step that would carry an un-healed char past
  POISON_SAFE_DEPTH (the same threshold the retreat uses), so the rules agree about the cap
  instead of fighting. 2 tests, mutation-checked from both sides. NEXT: measure #196.
- **WIZARD RECALL HYSTERESIS (0.102.0)**: #194's return spam (2711 returns/17k ticks) was
  the arch-wizard (INT 8) oscillating home 222x — an observation-staleness thrash (a
  wizard only knows a world is dangerous while IN it; home it expires, the embark reads it
  safe and re-dispatches into the same band). FIX: a band-danger fallback stamps a recall;
  the embark holds the wizard home WIZARD_RECALL_COOLDOWN=200 ticks (~a band cycle) so it
  waits the band out. WATCH #195: returns/1k down, arch-wizard stint length up.
- **STILL OWED (the tome/magic)**: gold surplus lever — scale BREWING (safe) so cheap
  brewed potions replace 20g shop potions and free 150g for the tome (2 wizards tome-ready,
  arch INT 8). Do NOT ship the risky heal-throttle without operator go.
- **TOME BLOCKED ON GOLD SURPLUS (measured #194)**: the tome fund's armour suppression
  works but armour was NOT the drain — 0 tome buys, 0 learned, gold pinned ~30. 2 wizards
  now tome-ready (arch INT 8). Real block: income ~590/run ~= spend, sink is 22 potions
  (~440g); POTION_KEEP=1 (no stockpile to cut), vault potions HALF-PHANTOM (16/31 fail).
  THE KNOT: we SELL brewable herbs as junk (sales 1.4g each) instead of brewing them into
  2g potions — herbs-as-junk -> forced 20g potions -> no surplus -> no tome. NEXT LEVER
  (operator tradeoff, recommend A): (A) SAFE scale BREWING; (B) RISKY throttle shop
  potions while saving (death risk); (C) income. Tome fund stays (harmless; helps once
  arming hits 30/30). Do NOT ship (B) without operator go.
- **THE TOME FUND (0.101.0)**: #193 arming fully compounded (2/30 -> 27/30) and the
  arch-wizard hit INT 6 (past the INT-4 tome gate) — ONE tome (150g) from the first spell
  ever learned on this server (0 `learned` in 340k+ obs). Gold was pinned at ~30 because
  armour buys (40-70g) drained it below the tome line. FIX: while a tome-ready seat exists
  and no tome bought, SUPPRESS the armour buy so gold climbs to 150; releases on purchase.
  (Caught a note-first bug: seats were read before the frame's chars were ledgered.) WATCH
  #194: gold -> 150, tome bought, the FIRST `learned` event = GLASS CEILING BROKEN.
- **ARMING UNBLOCKED (0.100.0 measured on #193)**: armed share 2-3/30 -> 9/30 (11 clubs
  bought vs 0 weapon-buys for entire prior runs), 1 death, chars LEVELING (35 xp, 9
  stat_ups, levels 2-8). The arm->fight->level cycle is finally turning. NO new lever this
  pass on purpose — the recalibration needs runway to compound. EMERGING constraints for
  next pass: gold pinned at ~35 (arming spends to the floor, so the tome@150 waits on
  income); top INT still 3 (int-gifted wizard 1 from the INT-4 tome gate, needs fight-XP
  which arming now enables). NEXT: measure #194+ — armed past ~15/30? wizard reaching INT
  4? gold trending up? then the next lever (income / combat-leveling / the tome itself).
- **THE ARM RATE WAS A STALE GOLD FLOOR (0.100.0)**: WEAPON_BUY_FLOOR was 150 while gold
  sits chronically at ~85 — ALL THREE treasury floors (POTION 100/WEAPON 150/ARMOR 200)
  were above our gold, so the guild bought NOTHING while 15g clubs sat in the shop. The
  entire forge saga (0.95-0.99.1) was routing around a frozen reserve. FIX: recalibrate to
  coin-dry reality (POTION_RESERVE 30/WEAPON 45/ARMOR 70). A bare char now arms with a club
  at 85 gold. BONUS: tome-buy line 220->150 (magic reachable sooner). WATCH #193: armed
  share FINALLY climbs off 2-3/30; then fight->level->the ceiling. Forge still matters for
  tier-2 gear the shop lacks.
- **ORE-DISPATCH MINE-WORTHY GATE (0.99.1)**: #191's "only one char deployed" = a
  revolving door (205 embarks/15 chars, one 58x, median 38-tick stints; 15 never field) —
  bare chars can't hold the field. v0.99.0's ore bias worsened it (sent BARE foragers to
  the mines to churn). Now the ore dispatch only routes MINE-WORTHY chars (fodder or
  armed) to the mines; bare foragers stay on the surface. WIZARDS double-protected (own
  escort/band gate runs first — never ore-dispatched; explicit test). WATCH #192:
  fodder/armed mining, smelts/ingots up, no bare-forager churn into the mines.
- **ORE-HUNGRY FIELDING (0.99.0)**: #190 measured the smith pipeline — thrash GONE (forge
  418 shield/7 spear -> 2 spear/0 shield, wrong_materials 421->0) but armed still 2/30
  because INGOTS are absent (4 smelts; nobody mines — 1 char in the mines, dispatcher
  sends gatherers to the surface for lumber not the mines for ore). LEVER: ingot-poor
  guild (<=3 stash ingots) biases forager/fodder embark to the ORE world (derived from
  seen veins), inside the green-gate, self-correcting. WATCH #191: mines headcount up,
  smelts/ingots up, Fix B (lumber withdrawal) starts firing, armed share climbs off 2/30.
- **SMITH PIPELINE slice 1 (0.98.0)**: fixed the arm-rate bottleneck (0/28 forge-ready on
  #189). Root cause was material CONVERGENCE, not the deep forge (all forging is
  village-based — the mines forge tiles were a red herring). (A) a TOOL in hand
  (FORGE_HAND_TOOLS) no longer reads as armed, so the lone pickaxe-miner forges a spear
  not shield_iron x418; (B) a village char with an ingot but no lumber withdraws a lumber
  from the stash (19 sat unused; ingots are the scarce half), vault-dead-guarded. 6 tests,
  6/6 mutants. WATCH #190: armed share off 2/30, spear forges up, shield wrong_materials
  down. SLICE 2 deferred: ingot SCARCITY (only from mines ore) is the remaining limit.
- **HINTS + SIDECAR HEARTBEAT (0.97.0, operator)**: the nuisance never fired because (a)
  the sidecar's track recorder was crash-looping on a dead DB connection (its any-intel
  heartbeat was masked by spectate/color on the healthy main conn — restart revived it)
  and (b) the nuisance used only LOCAL vision. FIX A: the bot reads the sidecar's track
  feed into bot.rival_hints every 8 ticks (a general 'hints from the feed-watcher'
  capability); the nuisance detects Will map-wide and routes to his hint centroid when
  unseen. FIX B: the recorder writes kind='track_beat' each loop on its OWN connection;
  health.web_heartbeat_at() uses it so the watchdog restarts web when the TRACK feed
  alone goes stale. WATCH #189: does the nuisance designate + route to Will now?
  (Will IS live in the vale as of this pass — track feed flowing.)
- **THE NUISANCE (0.96.0, operator FUN)**: a YELLOW role that shadows rival WillMorr
  (guild g_63837f) in the vale when >=3 of his chars are there — hangs in his party's
  centre, helps kill, says ':(' when he hits it, loots his fallen, and cackles
  'mwahahahaha' as it runs the spoils home (banked by the village economy). Dynamic
  designation: reclassifies when Will leaves/dies, re-designates on return. Will is NOT
  currently fielded (stale track feed) so it's a 'when Will shows up' feature — verified
  by 15 unit tests, 8/8 mutants killed; inert until he appears. A one-off, not a scored
  lever. Survival outranks all nuisance offers (try-not-to-die holds).
- **FORGE-TO-ARM WEAPON-FIRST (0.95.0)**: still measuring on #187/#188 — armed share
  should climb (spear recipe proven: 1 lumber + 1 ingot_copper).
- **FORGE-TO-ARM UNBLOCKED + WEAPON-FIRST (0.95.0)**: the arm rate is the root cause of
  BOTH the idle village (death-latch benches the 28/30 bare-handed) and the passive char
  (bare hands can't fight, stamina-shuffle-dodge). Forge chain is further along than
  thought: #186 forged a SPEAR — recipe PROVEN spear = 1 lumber + 1 ingot_copper (both
  we make). Chain works end-to-end (chop/smelt -> forge -> equip). GAP was PRIORITY:
  led with shield_iron (armour). 0.95.0: an EMPTY HAND forges a WEAPON first
  (FORGE_WEAPON_FIRST), armed chars still forge the shield. WATCH #187: armed-share
  climbs, fewer bare-handed benched, deaths stay low.
- **QUEUED follow-ups**: band-local death-latch (latch only the death's y-strip, not the
  whole world — un-benches shallow foragers); dodge-when-healthy (keep moving vs rest
  adjacent to a weak threat). Both proposed to operator, not yet greenlit.
- **ARCH-WIZARD LOOP BROKEN (0.94.0, operator go)**: the #184 arch-wizard died because
  its role OSCILLATED (43 wizard / 49 forager decisions) — wizard_rank_key ranked LEVEL
  above the int-gift, so the protected (slow-leveling) int-gifted char kept losing its
  seat to bold higher-level peers, and demotion stripped its protection -> deep -> dead.
  FIX (1): int-GIFT now outranks level in the rank key. FIX (2): light hysteresis — an
  incumbent within HYSTERESIS_SLACK=2 of the cutoff reclaims its seat (rank-gap rule,
  never blocks a superior newcomer); strategy holds last-tick seats, empty on restart.
  Dashboard shows pure top-6 (transient boundary divergence, self-heals). WATCH #186:
  wizard-role STABILITY (oscillation gone), arch-wizard survives, INT climbs.
- **RIDE PROBE MADE REACHABLE (0.93.1)**: #184 logged 0 ride sends — slice 1 waited for
  a char to already stand on a rail (never happened; armed chars field shallow, rails at
  mines y12-82). Slice 2 routes a qualified prober (armed/healthy/calm/not-probed, shared
  _ride_prober_ready) to the nearest known RIDEABLE rail (_is_rideable_rail = track with a
  track neighbour), seek score 3.1, range 24. WATCH #185 steemer-live.log for `[ride]
  probe:` + the event/error — minecart hypothesis (operator) vs clean slide vs ram damage.
- **PARTY-TAB GEAR FIXED (ab078bd)**: equipment slots are objects; reduced to .kind
  server-side. Submodule is CURRENT (588702a == origin/HEAD) — was never an API change.
- **ROSTER-CAP (corrected)**: server enforces roster_cap via a recruit error, but counts
  VILLAGE-PRESENT chars, so village+fielded can exceed 30 (we sit at 31). Not exploited —
  more chars worsens the arm-rate constraint. server_bugs.md logged.
- **ZERO-DEATH RUN (#183, 0.92.2)**: 23.7k mature frames, 0 our-deaths (22 -> 0),
  recruits 88 -> 13, embarks 497 (fielding never froze). The three-slice arc — portal
  SOLID -> death latch -> green = bare hands — closed a 60+ corpse bleed. Claims at close.
- **RIDE PROBE LIVE (0.93.0)**: once per run, a healthy ARMED char standing on a rail
  issues the server's first-ever `ride` (guards: no predator in FLEE_RADIUS, hp>=70%,
  adjacent rail tile for direction; score 4.5). WATCH steemer-live.log for `[ride]
  probe:` + the resulting event/error — minecart hypothesis (operator) vs clean slide;
  docs promise flat-cost slide to rail's end + RAM damage to blockers. Slice 2 designs
  itself from the first result.
- **GREEN = BARE HANDS (0.92.2)**: #182 proved the death latch WORKS (hot at 21/22
  victims' embarks) but the classifier leaked twice: cheap spend_xp promotes recruits
  past level<=1 in minutes, and role_of calls a bare-handed level-5 a "guardian" who
  shipped through the un-gated guardian branch. Green is now bare-hands + not-fodder at
  ANY level/title; guardian branch requires not-green. ⚠ 5/30 armed at gold 115 → the
  ARM RATE is the binding constraint on fielding breadth now (forge-to-arm/M3a or income
  un-gates the roster). MEASURE #183: deaths finally down? fielding not frozen?
- **RAILS COMMITMENT**: ride-the-rails (0.523, top qualifier 4 passes running) SHIPS
  next pass if #183 is clean — no further measurement-isolation deferrals.
- **DEATH LATCH (0.92.1)**: #181 proved the 0.92.0 green gate NEVER FIRED — median
  embark->death gap 38 ticks; the census predicate (>=2 predators in one view) can't see
  a spread-out chaser band that kills serially. Now one of OUR corpses latches its world
  dangerous for DEATH_GATE_TTL=900 (ledger-uid only; village/rival deaths latch nothing);
  wizards share the predicate. PROCESS: gates must emit an observable when they SUPPRESS
  (the silent `continue` cost an archaeology session). MEASURE on #182: embark->death
  gaps lengthen, recruit deaths in hot bands drop, gate latches visible after deaths.
- **ML PASS 4 progress**: parity CLEAN on #179 (44/44) + #180 (19/19); stint shadow
  ~11k rows on #181 alone (decisions floor met). REMAINING: extend check_shadow_parity
  to replay stint scores; shadow.py zero-diff; live calibration (>=30 deaths); tick p95.
- **GREEN-RECRUIT BAND GATE (0.92.0)**: #180's first hours: 16 our-deaths, ALL fresh
  recruits, ALL shallow — vale band 0 rolled a chaser pit (lava_ant/spider_brown/delver,
  chaser ~0.93) and level-1 bare-handed replacements were run down fleeing (11/16); 0/16
  were fodder-by-choice. BANDS ARE NUMBERED Y-STRIPS (payload band: 0..3) — the spawn
  strip is band 0 with its own roll. Gate: green (lvl<=1 + bare hands + not fodder)
  embark only into non-dangerous worlds, else wait like gated wizards; fodder + armed
  exempt. MEASURE on #181: recruit deaths in hot bands ~0, recruit rate down.
- **ML BATCH 2 RULED — ALL FIVE ACCEPTED + DEPLOYED**: stint_survival AUC 0.956 (honest
  baseline 0.847 — the coded age-only baseline's sign was BACKWARDS at 0.153:
  survivorship, fresh stints die young), move_fail 0.844 vs 0.750, income_spot 0.906 vs
  0.830, dph_profile (18 kinds), terrain_regrowth (hazard DECAYS 9e-6 -> 3.6% by gap —
  flat STALE_COST=3 is mispriced both ways: future lever). death_risk/mob_move v2
  rejected AGAIN (constants win). stint_survival shadow ACTIVE from this restart (intel
  kind='model_score', model='stint_survival'). Pass 4 shadow acceptance: >=3 runs with
  stint scores + parity + zero-diff. Eval snapshot: models/evals/eval-2026-08-23.json.
- **PORTAL VANISH SPIRAL KILLED (0.91.0)**: run #179 ate itself from tick ~2170k — a
  WALKABLE portal at vale (63,0) on the spawn strip teleported commuting chars deep
  ((57,44)); they died or VANISHED rosterless with no death event while the server kept
  RENDERING them in frames (frame ghosts — server_bugs.md), so the bot commanded ghosts
  (1,481 unknown_character + 4,548 not_in_village) and the recruit gate replaced real
  losses into the same portal (119 recruits, 18 our-deaths). Fix: `portal` in nav.SOLID
  (deliberate use stays open to a future action). MEASURE on #180: vanish-without-death
  ~0, recruits single-digit, scope errors ~0. Wishlisted: scope-error quarantine (the
  containment for the class). Claims from CLOSED #179 still owed.
- **ML BATCH 2 IN FLIGHT** (operator-picked, commit 9880083): five new models built +
  tested — stint_survival (shadow-wired), move_fail, income_spot (GBMs w/ fighting
  baselines) + dph_profile / terrain_regrowth (aggregation tables). Training session
  in reaper (re-extracts all runs — cache marker now requires the .aggr file); verdicts
  land in out/eval.json. 22 remaining model candidates wishlisted (9 ceiling-ineligible).
- **THE ML PIPELINE IS LIVE (passes 1-3 of 5)**: band_forecast (Brier 0.296 vs climatology
  0.715) shadow-forecasts every refresh into intel kind='model_score' — inert by test.
  death_risk/mob_move were REJECTED by their own gates (constants out-rank the GBM at AUC
  0.937 vs 0.897; the honest mob rule baseline is 0.744/0.187, not the leaked 0.81/0.892).
  Pass 4 = shadow acceptance after >=3 runs (tools/check_shadow_parity.py). Retrain via
  `reaper test --manifest .reaper-train.toml`; artifacts land in out/models/.
- **GHOST COMMANDS KILLED** (0.89.0): #177 sent 17k commands to returned/dead chars
  (move_failed 304/10k was never terrain); dead uids never act, returned get 4-tick grace.
  PICKER FIXED: wizards found behind the queue (3 pair-embarks/54k -> ~20x rate).
  #177 also proved the protection stack: wizard deaths ZERO (61 corpses all non-seats).
- **THE CHOSEN SIX** (0.88.0): wizardhood = a SEAT — pure top-6 ranking (INT, level, gift,
  stats, uid) over a sightings ledger, NO stored state; WIZARD_MIN_POOL=12 guards restart
  paralysis; death = instant re-rank promotion; lowest-stat recall makes room; seats bank
  EVERY XP into INT uncapped. Watch: INT climb, tome at INT>=4 + gold>=220, the learned
  event = glass ceiling broken.
- **DOCTRINE ERA** (0.87.x): roster filled to cap (gift lottery: ~9 wizards rolled), fodder
  class (bottom rolls, zero spend, max bold), pair-embark, >=2 guardians/world, wizard
  cluster on the arch-wizard. #175 taught the hard lesson: NINE wizard deaths in an undead
  band — 0.87.1 makes wizards SIT OUT dangerous bands entirely. Watch: wizard deaths in
  calm bands, move_failed composition (210/10k churn watch), INT grind in first calm cycle.
- **THE PARTY IS THE UNIT** (0.86.0, operator architecture): self._party pairs wizard->
  guardian persistently; the party square = the wizard's tile (one fixed point for all);
  partied chars SKIP cohesion; cohesion's centroid now INCLUDES SELF for everyone else.
  Never compute a formation target per-character from other members — that is the jitter.
- **THE ESCORT PACT** (0.85.x, operator directive): wizards only field alongside guardians
  (embark gate via sighting-built roles ledger), fall back home if unescorted (>10 gap),
  guardians close formation inside ESCORT_MAX_GAP=20 at 4.2. Watch: wizard deaths -> 0,
  INT climb continuing, escort winning vs loot.
- **THE PLANNED ESCAPE** (0.84.0): danger priced (nav AVOID_COST=8), not walled, in the
  hurt+cornered branch only — built from two wizard corpses that rested/bounced to death
  in mob boxes on #170. Watch: boxed-death mode ~0, deaths/10k not rising from crossings.
- **THE WIZARD PROJECT IS ON (operator directive)**: int-gifted chars pre-bank INT (first
  ever spend_xp int landed on #168); designate is a protected GUARDIAN at any level, never
  trades hits; tome_veil bought at gold>=220 AND designate INT>=4. Tomes only consumed on
  SUCCESSFUL learning — refusals are free retries. Watch: INT climb, then the `learned` event.
- **WE ARE THE SERVER'S FIRST MERCHANT** (0.82.0): one lumber listed at 3g/run on a market
  that had been empty all project. Listing shape now known (listing_id 'L393559', per-viewer
  `mine` flag). Watch: does any rival ever `buy_listing`? Stale probes auto-unlist next run.
- **ESSENCE MAP IS 9 KINDS** (taste engine): bitterroot=aether, frostmoss=ember,
  glimmerweed=clarity, sungrass=frost this run alone — none vigor, heal supply unchanged.
- **FRESHNESS BIAS CONFIRMED** (mature #165): move_failed 231→53.9/10k, treadmill held,
  looted-out 25.6%. Claim in ledger.
- **TASTE FINALLY EXISTS** (0.81.0): undecoded stranded herbs are tasted (once/kind/run)
  instead of sold. The result event has NEVER been observed — watch steemer-live.log for
  `[taste] raw event:` and wire the exact shape next. First-write-wins protects the poles.
- **⚠ REMEMBERED TERRAIN IS ONLY MOSTLY DURABLE** (mature #164): deep trekkers' walks home
  bounced off regrown bush/rock/water 524 times (move_failed 31→231/10k). 0.80.1 charges
  nav.STALE_COST=3 on tiles not seen this run (ctx.fresh); retreat+trek biased, never
  walled — only-stale routes still taken. Watch #165 mature: move_failed → ~31?
- **TREADMILL IMPROVING**: returned/10k 900 → 556 on #164; one char crossed y=199.
- **BREWING IS A TRICKLE**: 2 bottles/2 brews on #164 vs 16 shop buys — the constraint is
  now bottle+herb logistics per villager, not the floor.
- **OPERATOR DIRECTION (2026-08-22): "chess, not checkers"** — lateral multi-step reasoning.
  Shipped: 0.80.0 chop-through pathing (nav.weighted_step, BREAK_COST=5). Queued: danger as
  COST not wall (mob-box escapes). See memory: operator-direction-lateral-reasoning.
- **0.79.0 BREWING RESTARTED** (bottle floor 150 -> potion floor 100): first bottle ever
  bought -> brewed potion_red. Mature measurement owed on the 0.80.0 run.
- **SERVER CONFIG NOW CAPTURED** per-key into learned(topic=server_config) — NB prod
  truncates learned.fact at varchar(255); never store blobs there. ride_max_tiles is NOT
  in the live config; the ride cap must be discovered empirically.
- **TREK CONFIRMED** (mature #159): healed chars median y 4→21 max 125, deaths FELL to 2.5/10k,
  xp 3.5x — but only 4.8% of char-frames are healed, so POTION THROUGHPUT now binds.
- **⚠ THE VAULT IS A MIRAGE**: frame `guild.inventory` lists 202 potions/404 bottles that the
  server rejects `no_such_item` on withdrawal (>=8 distinct ids; gold in the SAME dict is
  live). Logged in server_bugs.md. 0.78.1 fails closed after 8 phantoms (_vault_dead). Do
  NOT trust guild.inventory as a manifest.
- **⚠ "HARMLESS TO RETRY" NEEDS A PROOF FOR THE PERMANENT CASE** — a dead id is not a stale
  frame. 1,181-error storm in 1,083 frames on #160 from nine chars on a 6-tick cooldown.
- **THE ROSTER IS PINNED TO THE SPAWN STRIP, AND THE CHAIN IS NOW KNOWN** (iters 89-90):
  un-healed chars are capped at `POISON_SAFE_DEPTH=12` (0.76.0 buys the heal FIRST, floor
  100 < arm floor); and since 0.70.0 removed the false frontiers, the nearest TRUE frontier
  is 64-192 tiles out — beyond `FIELD_GOAL_RANGE=20` — so nothing pulled north until
  0.77.0's TREK (unbounded bfs to frontier, heal-gated, `TREK_SCORE=2.2`). Watch #159+:
  healed median y, looted-out share (29%), deaths/10k (6.9), and whether treks fire at all
  (fuel = a 120g potion buy; gold was coin-dry flat at 109 at deploy).
  Bot writing frames ~12/s, staleness <1s. **DEPLOY NOTE: restart dash too when a change touches anything ui/server.py imports (role_of etc.) — the dash imports at startup and ran 2-day-old code once.** **FOUR services up: bot / web / dash / watch** —
  `watch` is the always-on supervisor (`tools/healthcheck.py --watch 60 --fix`).
- **THE GUILD TALKS NOW** (0.74.0–0.75.2): `say` posts ≤40-char flavour text in-world, keyed to
  events the server actually sent us. It is the first thing the bot does for the OPERATOR
  rather than for itself. `steemer/chatter.py`; scored `SAY_SCORE=2.1`, above the idle fillers
  and below anything load-bearing; gated on full hp+stamina; fails closed on three rejections
  inside three cooldowns.
- **⚠ "SCORE IT BELOW EVERYTHING SO IT CANNOT COST ANYTHING" MEANS "IT WILL NEVER HAPPEN."**
  Learned twice in one pass, from opposite directions. Cohesion rallied forever and finished
  never; flavour text was placed under the ladder four times and fired zero times in 1,545
  frames. **Rest is not the floor — `scout` (1.0) is offered on nearly every idle tick**, and
  the looted-out walk home (1.5) and frontier steps (2.0/2.5) are almost always there too.
  State the cost plainly instead: one say is <0.1% of the actions we issue.
- **⚠ AN ERRAND MUST BE SIZED AGAINST UNINTERRUPTED TIME, NOT AGAINST DISTANCE.** A field stint
  is **median 10–12 ticks** (`tools/field_stints.py`); only 3–13% reach 60. `COHESION_RANGE=8`
  comes from that. `VEIN_SEEK_RANGE=14` and the healed 32 have NOT been re-derived and are the
  obvious next candidates.
- **⚠ `decisions.reasoning` STORES THE WHOLE TRACE.** A `LIKE` against it answers "was this
  behaviour OFFERED", never "was it TAKEN" — and it also matches behaviours the stamina gate
  suppressed before they were weighed. Use `attribution.decision_share(..., chosen=True|False)`,
  which reads the `chosen` flag out of `alternatives_json`. This is what made 0.72.0's "cohesion
  was 25% of all decisions" wrong: chosen was 11.6%.
- **⚠ CHECK THE SCOPE COLUMN IN `docs/03-actions.md` BEFORE BUILDING ON AN ACTION.** `say` is
  scoped **map**, meaning where it is LEGAL, not "map-visible". Three rejected actions and two
  deploys went to learning that; the table had it all along.
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
- **🔮 THE MAGIC CHAIN IS ONE STAT FROM WORKING (0.67.0).** Run #145 dropped two tomes — the
  first since 0.63 — and every link held: kept (zero sold, against 74 historically), `use`
  issued on exactly those item_ids, and the server replied **`stat_requirement` five times**.
  `XP_PRIORITY` was `("vit","end","str")` — **INT was not in it at all**, and INT gates which
  tomes you may use, `max_mana`, `spell_cap` and `essence_cap`. Magic was locked out by our
  own XP policy, not by the game. 0.67.0 raises INT **only** for a character carrying a tome
  it has already been refused (an untried tome is a guess, and survival stats are the cost).
  **0.68.0 then found the link above it:** the tome holder never went to the village
  (10,933 tome-carrying frames, all in vale) and the learn step lived only in `village()`, so
  it never learned AND never earned the refusal 0.67.0 keys on. Learning is now offered in the
  FIELD too. Verified live on #147: 2 learn decisions → 2 `use` → 2 refusals EARNED.
  **Watch for: INT rising on that character, then a `learned` event, then casting.**
- **🕳 THE MAP EDGE WAS A FAKE FRONTIER (0.70.0) — CONFIRMED A CLEAR WIN.** `nav.frontier`
  counted any neighbour absent from `known` as unexplored, and beyond the map edge nothing
  ever is: **58 of the mines' 126 "frontier" tiles sat at y=0**, and `bfs_step` takes the
  NEAREST goal, so characters at depth 2 chased the rim while the real frontier (89–126) and
  the veins (median 88) went untouched. 572 false frontiers removed.
  **Measured at comparable loot density:** XP +27%, sale gold +103%, terrain broken 4x, deaths
  6→3, and the rest share **fell** 53.9%→47.0% (I had warned it might rise). Removing the fake
  attractor let v0.36's depletion-aware world-hopping win — embarks/returns doubled, attacks
  nearly tripled. Depth p90 6→12.
- **🌀 COHESION WAS 25% OF ALL DECISIONS AND CONVERGED NEVER (0.72.0).** Closing on the
  NEAREST ALLY is mutual pursuit — everyone chasing a target that is itself chasing someone.
  Run #150: 31,540 of 125,971 decisions; one character logged **482 consecutive** cohesion
  decisions with the ally distance reading 13,9,8,7,6,8,8,6,8; at one tick four characters
  were all "closing" at distance 7, two north and two south. With rest at ~47%, **~72% of
  decisions produced no progress** — and cohesion (2.8) outranks vein-seek (2.7), so a
  "dangerous" world suppressed ore-seeking entirely. Now rallies to the group's **centre**, a
  fixed point, so the spread shrinks monotonically.
  **Rule: any "move toward the nearest X" where X also moves is a chase, not a convergence.**
- **⚠ SIZE AN ERRAND AGAINST THE UNINTERRUPTED TIME AVAILABLE, NOT THE DISTANCE TO THE
  TARGET.** Field stints have a **median of 9–10 ticks**; only 1.6–3.4% last the ~60 ticks a
  30-tile walk needs. This indicts `VEIN_SEEK_RANGE=14` (~28 ticks) as well as the healed 32,
  and is why vein-seek has never converted in ANY version. Next thing to fix.
- **🪨 THE ORE ERRAND WAS SIZED NEVER TO REACH THE ORE (0.71.0).** Veins: median depth 88,
  shallowest 24. Median character-to-vein distance: **30**. `VEIN_SEEK_RANGE` was **14**, so
  only 4.72% of mines char-frames were ever in reach — 3 veins broken against 193 trees. A
  **healed** character now ranges **32** (clears the measured median; pinned to that
  measurement by a test). Gated on the heal because veins are deep and depth is where poison
  kills. Move-failure budget measured first: 0.24–0.33% against a 5.2% baseline.
- **0.69.0 worked:** `potion_red` coverage 4.1% → **27.34%**, depth-retreat decisions
  10.2% → 7.3%. Depth itself did not move, which is what exposed the frontier trap.
- **NEGATIVE RESULT — do not re-litigate `MOVE_STAMINA_SAFETY`.** 55% of decisions are `rest`
  and the traces read "wanted move but stamina 18 < ~30", which looks wasteful. It is not:
  moves still fail at shown-stamina up to 29–30 (median 26–28), a move costs ~15, resting
  regenerates 10–12/tick. Resting most ticks is inherent to the stamina economy.
- **⚠ A CONSTANT'S JUSTIFICATION IS A CLAIM ABOUT THE WORLD, AND CLAIMS EXPIRE.** Twice now a
  well-reasoned constant has outlived its evidence: `POTION_RESERVE=600` (set in v0.35.0
  because heals were "99.6% free-brewed" — we now brew **seven** `potion_red` per ~180k
  frames, and the 600 floor made the buy unreachable at our 156–200 gold), and v0.8.0's
  stranded-singleton sell rule (right for abundant items, wrong for scarce chain inputs;
  fixed in 0.59.0). Both read persuasively in their comments years later. Nothing watched
  either. **0.69.0 ranks the heal with arming** — an un-healed character is capped at
  `POISON_SAFE_DEPTH`, which gates ore, deeper content and XP.
- **Magic is SOUND and short of XP, not broken.** Run #147 earned the field refusals 0.68.0
  was built for; the holder reaches the village; its XP climbed 5 → 25 against the 16 INT
  costs. `c16038`/`c16060` carry the **`int` gift** (half cost) if we ever pick a caster
  deliberately rather than accepting whoever picks up a tome.
- **⚠⚠ "IT IS IMPLEMENTED" IS NOT AN ANSWER TO "WHY IS NOTHING HAPPENING". Ask WHERE it runs
  and FOR WHOM.** Four links in one chain have now been correct and unreachable: 0.54.0
  vein-seek (validated against a map the process did not have), 0.64.0 proof rule (events
  parsed only on frames it never saw), 0.67.0 INT buy (keyed on state that dies at deploy),
  0.68.0 learn step (running where the character never goes). Before shipping a behaviour,
  name the frame it fires on and the character it fires for, and check that character gets
  there.
- **⚠ A RUN YOUNGER THAN ~20k FRAMES CANNOT SUPPORT "SOMETHING STOPPED".** I raised two false
  alarms in one pass ("forging has stopped entirely", "terrain_hit collapsed 519→8") from
  minutes-old samples; full-run figures were unremarkable (terrain_hit 114.6→101.3/10k).
  `shadow.MIN_DECISIONS` exists for exactly this — apply it to ad-hoc queries too.
- **⚠⚠ WHEN A FIX SHOWS NO EFFECT, FIRST ASK WHETHER IT EXECUTED.** v0.64.0's proof rule
  never ran live for TWO versions: event parsing sat inside `_field()`, village frames route
  straight to `strategy.village()`, and **every `forged` event arrives on a village frame**.
  Fixed in 0.66.1 (parse events for every frame, one place).
  **The suite passed before and after** — 752 tests, none asserting that a village frame's
  events are read, because every test drove the strategy or the monitor directly and never
  the ROUTING between them. The chain was broken in the MIDDLE, where both ends test clean.
  **Third inert shipment** (0.48 misread, 0.54 genuinely inert, 0.64 now) and all three were
  correct code that was never reached. Green tests measure the code you call, not the code
  the bot runs.
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
