# Wishlist

Things the operator would like me to **consider** implementing — candidates, not
commitments. I keep this list, tick items off as they ship (noting the version or
commit), and the operator adds new ones. Anything here is fair game to weigh
during the improvement loop, but nothing here is obligatory.

Format: `- [ ]` open · `- [x]` done (with where it shipped). Newest ideas at the
top of **Open**.

## Scoring

`final = good_idea × risk_to_bot × (0.75 − 1/tc)`, where `tc` = **deploys** since the item was
added (a pass that ships no deploy does not advance it; the first deploy after an add still
leaves `tc=1`, so a new item scores negative twice).

**The age factor saturates at 0.75, so `ceiling = good_idea × risk_to_bot × 0.75`.** An item
whose ceiling is under 0.5 can *never* qualify at any age — it is INELIGIBLE, not "almost". Say
so plainly rather than reporting it as "just under 0.5" pass after pass. At a typical
`risk_to_bot` of 0.97 this means **`good_idea` must exceed 0.687** for an item to ever be built.

**`good_idea` anchors** (added 2026-08-21 after the operator asked why their ideas kept scoring
low — the honest answer was that 7 of 10 items sat inside a 0.07-wide band straddling the
eligibility line, which is a coin flip with a decimal point, and that visibility/enjoyment items
were being parked at the bottom of it despite the rule below):

| band | meaning |
|---|---|
| **0.90–1.00** | unlocks a whole mechanic or capability we do not have, or serves the operator's stated direction directly |
| **0.70–0.89** | real, evidenced value on a known bottleneck — but narrower: one subsystem, or visibility that materially changes decisions |
| **0.50–0.69** | speculative, or substantially redundant with something we already have |
| **below 0.50** | cosmetic, or superseded |

`good_idea` **CREDITS operator enjoyment and visibility** — the operator plays this too. Do NOT
dock for "aesthetic, doesn't help the bot"; `risk_to_bot` is what handles harm. DO dock for
genuine quality limits: stale data, fragility, speculation, or **bundling slices of different
risk under one score** (that lets the risky half hold the safe half hostage — split instead).
Do not inflate to clear the bar; recalibration should move items DOWN as often as up.

`risk_to_bot` is risk to **the bot**, not to the platform or the verification effort.

## Current scores

**Bookkeeping rules** (normalised 2026-08-21 after the operator noticed ticked items sitting
inside `## Open` alongside a separate `## Done` section — two conventions that had drifted,
with `## Done` unmaintained since 2026-08-20):
- A shipped item moves to `## Done` with its full text. `## Open` contains ONLY open items.
- **The table below must have exactly one row per open item.** Counting them is the cheap
  mechanical check, and it exists because the Campaign Layer was silently absent from 16 of
  20 score tables — an omission is worse than a wrong number and far harder to notice.


Recalculated fresh each pass. `tc` at deploy-minor **93.1** (`explorer/0.93.1`), counting
DEPLOYS since an item was added — a pass that ships no deploy does not advance it.

| item | good | risk | tc | final | ceiling | status |
|---|---|---|---|---|---|---|
| Investigate the mines forge (special/great forge?) | 0.80 | 0.85 | 0 | — | 0.510 | just added (tc=0) — ELIGIBLE |
| Hints: rival-avoidance for wizards | 0.82 | 0.95 | 0 | — | 0.584 | just added (tc=0) — ELIGIBLE |
| Hints: any-rival death-loot vulture | 0.80 | 0.92 | 0 | — | 0.552 | just added (tc=0) — ELIGIBLE |
| Hints: map-wide danger early-warning | 0.80 | 0.95 | 0 | — | 0.570 | just added (tc=0) — ELIGIBLE |
| Hints: least-contested world routing | 0.75 | 0.93 | 0 | — | 0.523 | just added (tc=0) — ELIGIBLE |
| Hints: rival-position dashboard overlay | 0.68 | 1.00 | 0 | — | 0.510 | just added (tc=0) — ELIGIBLE |
| Deterministic party-card order | 0.68 | 1.00 | 1 | **-0.170** | 0.510 | below 0.5 — ages toward ceiling 0.510 |
| Scope-error quarantine | 0.82 | 0.96 | 4 | **0.394** | 0.590 | below 0.5 — ages toward ceiling 0.590 |
| Model: XP-rate per placement | 0.85 | 0.95 | 4 | **0.404** | 0.606 | below 0.5 — ages toward ceiling 0.606 |
| Model: death-cause classifier | 0.77 | 0.99 | 4 | **0.381** | 0.572 | below 0.5 — ages toward ceiling 0.572 |
| Model: aggro/leash radius | 0.78 | 0.96 | 4 | **0.374** | 0.562 | below 0.5 — ages toward ceiling 0.562 |
| Model: time-to-kill | 0.76 | 0.95 | 4 | **0.361** | 0.541 | below 0.5 — ages toward ceiling 0.541 |
| Model: refresh-clock inference | 0.74 | 0.99 | 4 | **0.366** | 0.549 | below 0.5 — ages toward ceiling 0.549 |
| Model: combat outcome | 0.75 | 0.95 | 4 | **0.356** | 0.534 | below 0.5 — ages toward ceiling 0.534 |
| Model: server-patch change detection | 0.72 | 0.99 | 4 | **0.356** | 0.535 | below 0.5 — ages toward ceiling 0.535 |
| Model: swarm formation | 0.74 | 0.96 | 4 | **0.355** | 0.533 | below 0.5 — ages toward ceiling 0.533 |
| Model: forge success hidden-variable | 0.72 | 0.98 | 4 | **0.353** | 0.529 | below 0.5 — ages toward ceiling 0.529 |
| Model: frame staleness | 0.73 | 0.96 | 4 | **0.350** | 0.526 | below 0.5 — ages toward ceiling 0.526 |
| Model: anomaly detection (own KPIs) | 0.70 | 0.99 | 4 | **0.346** | 0.520 | below 0.5 — ages toward ceiling 0.520 |
| Model: recruit quality projection | 0.70 | 0.97 | 4 | **0.339** | 0.509 | below 0.5 — ages toward ceiling 0.509 |
| Model: wizard-pipeline ETA | 0.68 | 0.99 | 4 | **0.337** | 0.505 | below 0.5 — ages toward ceiling 0.505 |
| Model: spawn composition | 0.68 | 0.97 | 4 | **0.330** | 0.495 | **INELIGIBLE FOREVER (ceiling < 0.5)** |
| Model: chest-refill clock | 0.66 | 0.98 | 4 | **0.323** | 0.485 | **INELIGIBLE FOREVER (ceiling < 0.5)** |
| Model: loot-value maps | 0.65 | 0.97 | 4 | **0.315** | 0.473 | **INELIGIBLE FOREVER (ceiling < 0.5)** |
| Model: seat-selection value | 0.62 | 0.96 | 4 | **0.298** | 0.446 | **INELIGIBLE FOREVER (ceiling < 0.5)** |
| Model: rival behaviour | 0.60 | 0.98 | 4 | **0.294** | 0.441 | **INELIGIBLE FOREVER (ceiling < 0.5)** |
| Model: portal-destination safety | 0.55 | 0.96 | 4 | **0.264** | 0.396 | **INELIGIBLE FOREVER (ceiling < 0.5)** |
| Model: brew-output priors | 0.55 | 0.97 | 4 | **0.267** | 0.400 | **INELIGIBLE FOREVER (ceiling < 0.5)** |
| Model: market price | 0.55 | 0.97 | 4 | **0.267** | 0.400 | **INELIGIBLE FOREVER (ceiling < 0.5)** |
| Model: test selection for the loop | 0.52 | 1.00 | 4 | **0.260** | 0.390 | **INELIGIBLE FOREVER (ceiling < 0.5)** |
| Magic — CASTING (chain sound; INT+tome slice unblocks) | 0.90 | 0.85 | 45 | **0.557** | 0.574 | **qualifies — BLOCKED: treasury (gold 113 vs ~220 for a tome)** |
| Move-prediction (b) rivals | 0.72 | 0.98 | 81 | **0.520** | 0.529 | **qualifies — UNBLOCKED 2026-08-23: WillMorr is live in the vale + the hint channel (0.97.0) feeds his positions/moves; the subject finally exists** |
| RIDE the rails (slices 2+: nav integration, ram tactics — awaits probe result) | 0.82 | 0.90 | 26 | **0.525** | 0.553 | **slice 1 SHIPPED 0.93.0** — re-scope after the first ride lands |
| Errand-budget audit (size every errand vs stint length) | 0.80 | 0.85 | 32 | **0.489** | 0.510 | below 0.5 — ages toward ceiling 0.510 |
| Portal-aware routing (portal tile = edge to its twin; graph from our own events) | 0.90 | 0.80 | 14 | **0.489** | 0.540 | below 0.5 — ages toward ceiling 0.540 |
| Tick-participation bar (operator: block-explorer style, last 500 ticks green/red) | 0.72 | 1.00 | 14 | **0.489** | 0.540 | below 0.5 — ages toward ceiling 0.540 |
| Stale-ground SWEEP (revisit map instead of walking home) | 0.88 | 0.80 | 26 | **0.501** | 0.528 | **qualifies** |
| Exploration matrix (B) experiment arm | 0.92 | 0.70 | 61 | **0.472** | 0.483 | INELIGIBLE — ceiling<0.5 |
| Rival-awareness dashboard panel | 0.62 | 0.97 | 92 | **0.445** | 0.451 | INELIGIBLE — ceiling<0.5 |
| Impassable-tile analysis | 0.60 | 1.00 | 94 | **0.444** | 0.450 | INELIGIBLE — ceiling<0.5 |
| Short-TTL predator memory | 0.60 | 0.90 | 66 | **0.397** | 0.405 | INELIGIBLE — ceiling<0.5 |
| Log-scale overview bars | 0.45 | 1.00 | 76 | **0.332** | 0.338 | INELIGIBLE — ceiling<0.5 |
| Campaign layer remainder (narrative+A/B) | 0.80 | 0.55 | 93 | **0.325** | 0.330 | INELIGIBLE — ceiling<0.5 |

**Danger-as-cost RE-DERIVED (2026-08-23, promised iter 95):** risk raised 0.75 → 0.90 with
the scope narrowed to make that honest: the change applies ONLY to the desperation branch
(hurt + cornered + no known-walkable escape), which today has NO plan to break — a single
clear-tile step re-decided every tick. A planned route through the least-dangerous corridor
(predator-adjacency as high COST in `weighted_step`, not a wall) can only replace no-plan
with plan in a branch whose current common outcome is the stuck-death. Ceiling 0.594 is
ELIGIBLE; the tc term gates it until ~2 more deploys. Not gamed: the old 0.75 priced a
global blocked-set change, which this is no longer.

**`ride` IS AN ACTION WE HAVE NEVER ISSUED** (found 2026-08-22 while answering "is there a
`read` action?" — there isn't; a tome is read with `use`). From a `track` tile, `ride {dir}`
slides to the rail's end for a FLAT cost, capped at `ride_max_tiles`. CORRECTED after a
proper survey (operator pushed back on "they're just horizontal", rightly): the 60 mines
track tiles are 19 SEPARATE rails — two horizontals at y=8 (13 + 8 tiles) and one at y=10,
a 2-D junction/curve at x51-53/y76-80, and the deep fragments are mostly VERTICAL but only
2-3 tiles each. All 78 rail ends terminate on MAPPED ground (zero on unmapped), so they are
genuinely short, not glimpses of longer lines. The longest ride available is 12 tiles west
along y=8 AND IT ENDS AT A CHEST; 30 of 78 rides are >=5 tiles; chest density beside track
is 5.0% vs 2.0% on ordinary floor. Value: a flat-cost one-action traverse of the stripped
spawn strip (an errand that fits a 10-12 tick stint), plus the chest run — NOT a route
north. `_cost` already reads `ride_stamina`; nothing offers the action. Build order:
(1) log `ride_max_tiles` from the hello config; (2) check the rail line for entities (a
blocker "gets rammed" — collision, not commute); (3) offer the ride.

Also never issued: `throw`, `charge` (weapon run-up attack), `cast`, `list`/`unlist`/
`buy_listing`.

**OPERATOR DIRECTION (2026-08-22, screenshots): "chess, not checkers"** — lateral,
multi-step reasoning. Item 1 (tree-as-dead-end) SHIPPED as 0.80.0 chop-through pathing.
Item 2 queued below.

*(Item 2 SHIPPED as 0.84.0 planned escape — nav.AVOID_COST=8 prices strike range in the hurt+cornered branch; see Done.)*

**Tick-participation bar (added 2026-08-23, operator):** a div of 500 blocks, one per
tick, green if we received/handled that tick's frame, red if skipped — crypto-block-
explorer style. Data source exists already: `frames.tick` per world plus the seq-gap
machinery (0.44.0); a skipped tick is a tick with no frame landed. Real diagnostic value
beyond the aesthetics: we have had silent drops (run #120 lost 3.7% of its stream) and a
22h-dead track feed nobody noticed — this makes stream health visible at a glance.
good=0.72 credits operator visibility per the scoring rules; risk 1.0 (pure read-only UI).
Ceiling 0.540 — ELIGIBLE, qualifies on the tc term in ~2 deploys.

**SHIPPED this cycle:** in-world trash talk (`say`) — 0.74.0–0.75.2, `steemer/chatter.py`.

**MAGIC IS BLOCKED, not deprioritised.** It has topped the table for many passes and cannot
be built: on run #157, every character holds **0 spells**, there are **0 `learned` events**,
INT is **1–2** across the roster and nothing referenced a tome all run. There is no spell in
existence to cast, so any casting code would be written against an unobserved mechanic — the
shape that shipped inert four times (0.54.0, 0.64.0, 0.67.0, 0.68.0). The unblock is a
concrete, separable slice: get one tome-holder's INT high enough that `use` on a tome is not
refused, and watch for the `learned` event. That slice, not casting, is what to build first.

_Scored 2026-08-22 (iter 85). `tc` +1 (0.72.0 deployed). Lever from measurement again — and this
one was found by TRACING ONE CHARACTER'S CONSECUTIVE DECISIONS, which no aggregate would have shown:
cohesion looked like a normal 25% slice until you watched it fail to converge. Worth repeating as a
technique when a metric is flat despite activity._

**Seven items qualify.** Exploration matrix (A) shipped this pass, one deploy after it crossed at tc=5 exactly as projected when it was split out of the campaign layer. `ceiling = good_idea x risk_to_bot x 0.75`; anything with a
ceiling under 0.5 is INELIGIBLE at any age and is reported that way, never as "almost".

**Scored 2026-08-24 (iter 94, deploy 0.108.1).** ~45 deploys since the 08-22 scoring, ~10
today alone (the 0.103-0.108 bug arc), so every pre-existing item's age factor sits near its
0.75 saturation: score ~= ceiling. Sweep notes: two items SHIPPED-BY-ARC without being named
— **band-refresh** (the 0.106.0 replenishment clocks + refresh-gated re-embark ARE the
band-refresh-aware routing this item described) and most of **M3a forging** (the 0.98.0
smith pipeline forges spears from ingot+lumber; the un-shipped remainder is only the
exotic-product discovery). Both moved to Done rather than kept as zombie line items.

| item | good | risk | ceiling | tc | score | verdict |
|---|---|---|---|---|---|---|
| shadow-eval (ML Pass 4 acceptance) | 0.75 | 1.00 | 0.563 | ~45 | **0.56** | qualifies — but ML is DEPRIORITISED by operator direction; parked, stated openly |
| danger-as-cost corridor (desperation branch) | 0.88 | 0.90 | 0.594 | ~15 | **0.54** | QUALIFIES — top *actionable* item |
| rival-recon dashboard (track feed) | 0.73 | 1.00 | 0.548 | ~45 | **0.54** | qualifies; WillMorr active, other rivals field ~0 |
| magic / cast | 0.75 | 0.98 | 0.551 | ~45 | 0.55 | **BLOCKED** (0 spells learned ever; arch-wizard INT 8 died on #201 — the INT ladder lost its top; tome 150g vs gold 20) |
| adaptive-cohesion remainder | 0.72 | 1.00 | 0.540 | ~34 | 0.52 | qualifies, thin remainder (cohesion+escort shipped) |
| tick-participation bar | 0.72 | 1.00 | 0.540 | ~15 | 0.49 | eligible, crosses in ~2 deploys |
| dashboard FIELD TRUTH (chars_by_world lag) — NEW | 0.75 | 1.00 | 0.563 | 0 | — | added 2026-08-24: the lagging counter told the operator "0 in worlds" twice TODAY while sentinels were out; frames are the truth source the dash should read |
| player market | 0.68 | 0.99 | 0.505 | ~45 | 0.50 | marginal; market dead server-wide (one listing ever) |
| forge-in-mines investigation (operator) | 0.70 | 1.00 | 0.525 | ~12 | 0.46 | crosses in ~3 deploys; cheap investigation slice |
| hints: wizard rival-avoidance | 0.70 | 1.00 | 0.525 | ~10 | 0.46 | crosses in ~4 deploys |
| hints: vulture / early-warning / routing / overlay | 0.55-0.65 | 1.0 | <0.49 | — | — | INELIGIBLE (ceilings under 0.5) |
| ML model ideas (11 parked) | — | — | <0.5 | — | — | INELIGIBLE or data-starved; unchanged |

**This pass's bot change was 0.108.1** (arm-budget fix), so the implement-top-alongside rule
is satisfied by the active brewing/economy thread; **danger-as-cost corridor is the queued
next lever** once the post-deploy watch (new standing rule) is clean and the heal-economy
thread reaches a stable point.

**Scored 2026-08-25 (iter 111, deploy 0.110.3 — ~20 deploys since the 08-24 table).**
SWEEP: four items SHIPPED since last scoring and move to Done — **tick-participation
bar** (0.108.3/0.108.4), **dashboard field truth** (0.108.2), **scope-error
quarantine** (shipped as the ghost quarantine + render distrust, 0.107.1/0.110.3 — a
BETTER version of the item as written), and danger-as-cost (0.84.0, swept last pass).
Old items sit near their ceilings (tc factor ~0.73).

| item | good | risk | ceiling | tc | score | verdict |
|---|---|---|---|---|---|---|
| **LEVELING lever (combat scale-up)** — NEW | 0.90 | 0.85 | 0.574 | 0 | — | THE standing-direction item (arming 24/30, gate 25); ships on direction, not age; PRECONDITION: sim pass 2 (mobs) |
| sim pass 2: mobs in the test bed — NEW | 0.85 | 1.00 | 0.638 | 0 | — | process-mandated by the testing directive (combat levers must soak pre-deploy); builds next pass |
| shadow-eval (ML Pass 4) | 0.75 | 1.00 | 0.563 | ~65 | **0.55** | qualifies; parked by the operator's ML deprioritisation (stated, not hidden) |
| magic / cast | 0.75 | 0.98 | 0.551 | ~65 | 0.54 | **BLOCKED** (0 spells ever; tome 150g vs gold ~7; the INT ladder rebuilt to lvl-9 after the arch-wizard loss) |
| rival-recon dashboard | 0.73 | 1.00 | 0.548 | ~65 | **0.54** | qualifies — and value FIRMED: WillMorr is actively fielding again (subjects exist; nuisance 1-0) |
| adaptive-cohesion remainder | 0.72 | 1.00 | 0.540 | ~55 | 0.53 | qualifies; thin remainder (cohesion/escort/party shipped) |
| forge-in-mines investigation (operator) | 0.70 | 1.00 | 0.525 | ~27 | **0.499** | crosses at the NEXT deploy — the top operator-added item |
| hints: wizard rival-avoidance | 0.70 | 1.00 | 0.525 | ~22 | 0.49 | crosses in ~3 deploys |
| player market | 0.68 | 0.99 | 0.505 | ~65 | 0.49 | perpetually marginal (market dead server-wide; one listing ever) |
| deterministic party-card order (operator) | 0.62 | 1.00 | 0.465 | — | — | INELIGIBLE (ceiling < 0.5) unless re-scoped |
| hints: vulture / early-warning / routing / overlay | 0.55-0.65 | 1.0 | <0.49 | — | — | INELIGIBLE |
| zombie-char detector (input-paralysis counter) — NEW | 0.55 | 1.00 | 0.41 | — | — | INELIGIBLE: no mitigation exists (the char is doomed); the server_bugs entry IS the action |
| ML model ideas (11 parked) | — | — | <0.5 | — | — | unchanged; rival-behaviour's data-starvation is EASING (rivals active) but ML stays parked per direction |

**Queue implied by the table + direction:** sim pass 2 (mobs) -> leveling lever (both
direction/process-mandated), with forge-in-mines investigation as the interleave item
the moment it crosses (next deploy), then rival-recon.

## Open


- [x] **Investigate the forge in the mines (operator, 2026-08-23)** — INVESTIGATED
  2026-08-25 (iter 114): three forge tiles confirmed at mines y105-117 (mapped to y126
  by old healed treks). What makes them special is DOCUMENTED, not mysterious: docs/07
  caps village crafting at quality tier 2 — the top tier (masterwork, x1.5 effect)
  requires a real station tile in the world. The mines forge is therefore the
  MASTERWORK forge. Nobody on the server has ever used one (0 forge events in the
  mines, ours or rivals'). Exploitation cost today: y105+ needs ~6 potions of depth
  budget (16 rows/potion past cap 12) + the ingot/lumber cargo hauled there — a
  full expedition design. Filed as a FUTURE lever ("masterwork expedition") gated on
  the heal economy maturing; the investigation itself is complete. Original text: — the mines forge tiles
  (y105-117) may be a SPECIAL forge, not equivalent to the village forge we use. docs/08
  explicitly flags the Embermines: "Forging (something big guards **the great forge at the
  top**)." We have only ever forged at the VILLAGE forge, producing tier-0/1 items
  (shield_iron t0, spear/dagger t0, pickaxe t1). A guarded deep forge is the classic
  higher-tier / unique-recipe unlock — it could yield tier-2+ weapons or armour the shop
  and village forge cannot, which bears directly on the arm rate (better weapons per
  scarce ingot) AND the wizard program (a forged caster item?). INVESTIGATION first, not
  engagement: (1) confirm the mines forge accepts our known recipes and compare the
  product tier/`tells` to the village forge's; (2) map what "guards the great forge at the
  top" is (a boss? a gate?) from the tile/entity data BEFORE risking a char; (3) only then
  decide whether a forged-armament trek to the deep forge pays. Ties into the smith
  pipeline (0.98.0) and the deferred slice-2 ingot-scarcity work.


### Hints-system ideas (2026-08-23, operator asked for 20; the good ones added below + to the table)

The hint channel (0.97.0) = the bot acting on anything the sidecar sees MAP-WIDE (rival
positions/moves from the track feed, guild rosters/levels/equipment/world-counts from
spectate). The nuisance is the first consumer; these are the rest. **Good (added to the
score table):**

- [ ] **Hints: rival-avoidance for wizards** — keep our protected wizards (the compounding
  INT investment) away from rival war-bands the hints reveal — WillMorr fields a lvl-29
  wizard that would one-shot ours. Route wizards to rival-free worlds/bands; a guardian
  escort holds/reroutes if a rival party approaches. Serves the wizard directive directly.
- [ ] **Hints: any-rival death-loot vulture** — generalise the nuisance's loot phase to ANY
  rival death (not just Will): when a rival char dies within reach, a nearby forager grabs
  the drop. Free gear/gold — feeds the arm rate. The loot->deliver code already exists.
- [ ] **Hints: map-wide danger early-warning** — rival deaths and mob swarms the sidecar
  sees in worlds/bands our chars haven't reached yet = a free danger signal. Feed it into
  the death-latch / band-forecast so we gate fielding into a hot world BEFORE we lose a
  char discovering it ourselves.
- [ ] **Hints: least-contested world routing** — spectate world-counts show where rivals
  are crowding; field our gatherers into the LEAST contested world (more loot/char). Ties
  into the income-dispatcher idea.
- [ ] **Hints: rival-position dashboard overlay** — plot rival positions on the map viewer
  / a rival heatmap (operator plays too; visibility). Cheap, dashboard-only.

**Considered but NOT added (weaker):** loot-density heatmap from rival clustering
(speculative — assumes rivals loot where they cluster; ceiling ~0.50); portal-network
mapping via rival transits (portal-block already solved our need); "follow the leader"
exploration shadowing a rival's best char (fun but redundant with the nuisance); rival
forge/craft espionage (we already know the spear recipe); recruit-tempo matching (weak
signal); market intelligence (market is dead); own-roster cross-world coordination (the
bot already sees all our positions per-frame); rival-tier combat-seek targeting (folds
into combat-outcome model); chokepoint/ambush avoidance (subsumed by rival-avoidance);
rival-death mechanics postmortem (subsumed by map-wide danger warning). The rival
MOVE-PREDICTION model itself is already a table item — now UNBLOCKED by the live feed.


- [ ] **Deterministic party-card order (operator, 2026-08-23)** — the Party tab maps cards
  in raw `/api/roster` order and re-renders every 2s, so cards JUMP on each update when the
  server's order shifts. Sort by a stable key before render — e.g. world, then role
  (guardian/wizard/forager/fodder), then level desc, then a stat tiebreak, then char_uid as
  the final stable tiebreak so equal cards never swap. Pure dashboard/JS (renderParty in
  ui/server.py); no bot risk, no data change. Cheap and it's the operator watching the
  screen, so `good_idea` credits the annoyance it removes.


- [x] **Scope-error quarantine** — SHIPPED as the ghost quarantine + render distrust (0.107.1 / 0.110.3), a stronger form than written. Original text: — stop issuing actions for a char uid after K consecutive
  scope errors (`unknown_character` / `not_in_village` / `no_such_character`) with no
  intervening successful event; release on any fresh authoritative signal (own event, xp,
  successful action). Born from run #179's portal vanish spiral: the server renders
  roster-lost chars as frame ghosts (server_bugs.md), so a bot that trusts frames commands
  them forever — 1,481 unknown_character errors. This is the 0.62.0 "harmless to retry
  needs a proof for the permanent case" lesson generalised into a circuit breaker. The
  portal-block (0.91.0) removed the known cause; this contains the CLASS. (added 2026-08-23)

- [ ] **RIDE the rails — probe notes (2026-08-23):** docs say `ride {dir}` works straight
  from a `track` tile — flat cost, slides to the rail's end (`ride_max_tiles` cap absent
  from live config = empirical), no stopping early, and whatever blocks the rail is
  RAMMED for damage (a weapon-free damage source — interesting for our unarmed era).
  **Operator hypothesis to test in slice 1: does riding need a minecart, found or
  crafted?** Zero cart/wagon/trolley item kinds in 8.7M+ recorded events says no, but
  docs have under-described mechanics before — the first probe's error taxonomy
  (`missing_item`? clean slide?) settles it for one tick. If a cart IS required, a
  find-or-craft-minecart item enters this list with evidence.

### Model backlog (operator-directed add, 2026-08-23)

The 30-candidate model survey minus the three already tried (death-risk, band forecast,
mob next-move) and the five picked for immediate build (stint survival, move-fail,
income spot, dph distributions, terrain-regrowth clock). Each is one line: what it
predicts, and the decision it informs. All inherit the ML pipeline's rules — a baseline
that fights back, refuse-to-rule floors, shadow-first. Initial good/risk in the table;
ceiling-ineligible items are named as such per the ceiling rule.

- [ ] **Model: spawn composition** — P(kind mix of next band | world, history); informs pre-positioning. Largely redundant with band_forecast.
- [ ] **Model: combat outcome** — P(win | our stats/weapon vs kind/hp); informs engage/decline in combat-seek.
- [ ] **Model: market price** — expected sale price per item tier; informs listing strategy. Market is dead on this server (one listing ever: ours).
- [ ] **Model: rival behaviour** — next-move/strategy model of rival guilds from the track feed; no subjects (rivals fielding 0 chars).
- [ ] **Model: anomaly detection (own KPIs)** — flags metric drift the watchdogs don't name; informs loop attention.
- [ ] **Model: server-patch change detection** — distribution-shift alarm on mechanics constants; informs re-measurement after upstream changes.
- [ ] **Model: portal-destination safety** — P(survive far side | pair, band, state); 11 own transits = data-starved until we ride portals deliberately.
- [ ] **Model: chest-refill clock** — refill timing per band cycle; informs routing the chest run.
- [ ] **Model: aggro/leash radius** — per-kind acquire/abandon distance distributions; informs spacing + escort geometry.
- [ ] **Model: swarm formation** — P(lone mob becomes N within k ticks | band, region); informs early disengage.
- [ ] **Model: time-to-kill** — ticks to finish a target given weapon/stats vs kind/hp; composes with stint survival for "is this fight affordable".
- [ ] **Model: loot-value maps** — expected value of unidentified drops; informs what fodder sheds when overburdened.
- [ ] **Model: brew-output priors** — essence effects from name morphology before a taste; "just taste it" probably wins (bitterroot broke the name heuristic).
- [ ] **Model: forge success hidden-variable** — why identical recipes pass and fail (run #140); a model finding the variable OR proving randomness both pay.
- [ ] **Model: recruit quality projection** — rolled stats/gifts -> expected level-10 value per role; sharper than the stat-sum<=7 fodder rule.
- [ ] **Model: XP-rate per placement** — where a char grinds a stat fastest at acceptable risk; serves the INT glass-ceiling directive directly.
- [ ] **Model: wizard-pipeline ETA** — predicted date INT>=4 + 220g converge; visibility item, operator plays too.
- [ ] **Model: seat-selection value** — survival-weighted chosen-six scoring vs the lexicographic rule; the simple rule probably wins.
- [ ] **Model: frame staleness** — P(action bounces from lag | seq gaps, jitter); would generalise RETURN_GRACE and the stamina margin into one uncertainty estimate.
- [ ] **Model: refresh-clock inference** — the exact generator behind next_refresh; if it's regular, we get the calendar and every forecast upgrades.
- [ ] **Model: test selection for the loop** — which suites catch which diffs; gate is ~50s today, so this is meta-tooling with weak payoff.
- [ ] **Model: death-cause classifier** — learned postmortem over traces to name the residual `unknown` death modes; each named mode has historically become a lever.


- [ ] **Exploration matrix (B) — the experiment arm** *(OVERRIDE-ONLY; touches live play)* —
  exploring-role characters spend a budgeted fraction of idle ticks probing the top untried cells
  from (A), turning the frontier into confirmed mechanics. **Depends on (A).** (operator request
  2026-08-21)

  **Gates, all of them required:** healthy character in an exploring role; no predator within the
  spacing radius; not carrying anything scarce; one experiment per character per N ticks with a
  per-run global budget; and a strict verb allowlist that grows only as each verb proves harmless.

  **An `action_error` is information, not failure.** `unknown_action` vs `out_of_range` vs
  `wrong_slot` vs `nothing_to_open` tells us whether the verb exists at all, which is most of what
  we want to learn. (`open` is already live at 2,948 sends and `nothing_to_open` is a real error
  reason, so the game clearly models openable things — whether a *word* opens one is exactly an
  unknown cell.) Every experiment logs as a first-class record so the cube updates itself.

  **`say` is in scope** (operator: *"you never know if there's a door with a magic word"*). A
  `safe` has a combination, a `grave` is a thing you speak at, a `portal` is the canonical
  speak-friend-and-enter. `say` also looks cheap — likely no turn cost — which makes it the best
  value experiment surface in the cube. **The boundary is intent, not the verb:** in-world
  utterances aimed at discovering a mechanic are in scope; anything crafted to manipulate another
  *agent* or a parser — prompt-injection payloads, impersonating the server or the dev,
  instructions aimed at rival bots — stays in `scratchpad/` as a separately-authorised security
  probe. Chat is public and social, so utterances are hard rate-limited and kept short and
  obviously in-world; a bot chanting XYZZY at 12 ticks a second invites a throttle.

  **Excluded outright:** no experiment may sell, drop or consume an item that is not junk.
  Destructive-to-us verbs are the one place a wrong prior costs real progress rather than one
  wasted tick.

  **Scoring:** good_idea 0.88; risk_to_bot **0.70** (issues novel actions on live characters —
  wasted turns, possible item loss, possible aggro). Ceiling 0.462 — **it never clears 0.5 at any
  age, by design.** That is the formula stating the right thing: an arm that puts untried actions
  on live characters should always need an explicit operator override, not age its way in.

  **Graduation:** a confirmed mechanic feeds the strategy, exactly as harvest did in 0.45.

- [ ] **Move-prediction model — mobs AND rival players** — (a) MOBS: SHIPPED 2026-08-20
  (steemer/mob_predict.py — rule-based predict()/evaluate(), validated live #97: exact 0.81,
  chaser toward-when-moved 0.892; NOT yet wired into the strategy — 0.41 combat-seek uses simple
  adjacency, not the predictor yet). (b) RIVALS still OPEN (needs accumulated spectate-track data).
  turn the behaviour data we log into
  a *predictor* of the next tick's positions. (a) **Mobs** (build FIRST — practical + feasible):
  extend the bestiary from a behaviour CLASS to a next-tile predictor (a chaser steps toward the
  nearest char at ~move_rate; stationary don't; wanderers ~random). Feeds survival AND the leveling
  goal — predict a predator's next tile to dodge into the gap, or to attack it safely for XP.
  (b) **Rival guilds** (build SECOND — needs the new spectate-track data to accumulate): learn each
  guild's policy from recorded moves — behavioural class (parker/rusher/hunter/avoids-us) then a
  local next-move predictor. Start READ-ONLY and MEASURE accuracy (an accurate predictor *proves* we
  understand the mechanic — a mastery meter); integrate mob-prediction into the strategy only once
  validated. Data: bestiary + spectate-track (intel kind='track') + our frames. (operator request)


- [ ] **Short-TTL memory of recently-seen predator tiles** — char sight is partly
  line-of-sight-occluded (~18% of mobs first appear at distance 0, i.e. a predator
  hidden behind a wall/corner until rounded — see the spectate/LOS finding). Keep a
  small per-world map of *where a predator was last seen* with a short expiry (a few
  ticks), and treat those tiles as danger for pathing/dodging even after the mob drops
  out of sight — so a char keeps steering clear of the spot a golem just slipped
  behind a wall, instead of forgetting it instantly. Mirrors the existing
  `STUCK_BLOCK` learned-blocked mechanism. Must expire fast because mobs move (stale
  positions would mislead). Directly targets the occlusion gap the dodge/allowlist
  can't cover. (surfaced answering the operator's LOS/spectate question) (operator request)

- [ ] **Log-scale the overview-page bar charts (QoL)** — on the dashboard overview
  page, the bars at the bottom span values of wildly different magnitude (e.g. moves
  in the tens-of-thousands vs deaths in the tens), so the small bars are unreadable
  next to the huge ones. Apply a logarithm to the bar lengths (log10 or log1p,
  keeping the true value in the label/tooltip) so cross-metric comparisons are
  actually useful. Guard log(0) (use log1p or a floor). (operator request)

- [ ] **The Campaign Layer (remainder: narrative + the per-char A/B harness)** ⭐⭐
  (operator idea). **NOTE: step 4 "coordinated raids" was SPLIT OUT 2026-08-21 as its own
  item, "Adaptive cohesion / raids" (0.539, qualifies) — see above.** What remains scores
  good_idea 0.80 x risk_to_bot 0.55 = ceiling 0.330, INELIGIBLE: the risk is real and
  belongs here, since the A/B half runs divergent experimental policies on live characters.
  Original text follows. Not just a narrative overlay — a layer that
  **shapes play**. Each character is a persistent individual with a role and
  preferences that drive its own in-game behavior, and the roster becomes a live
  experimentation platform. The event log already records each `char_uid`'s whole
  life, so the narrative is cheap; the new part is letting it feed back into
  decisions.
  - **Characters as A/B test beds** ⭐ (the strategically valuable part) — the
    game is one-guild-per-session, so we can't A/B two guilds; but we CAN run
    different nav/combat policies on different characters in the SAME world at the
    SAME time and compare their productivity head-to-head. A *real simultaneous
    experiment* that fixes the loop's core attribution weakness (today: noisy
    sequential windows). Try a new idea on one char, measure, promote it if it
    beats its siblings. Needs **per-character productivity KPIs** (a natural
    extension of the per-run ones just shipped).
  - **Per-character roles / division of labor** — instead of one policy for all,
    chars specialize: a Forager works safe loot/gold, an Explorer pushes
    frontiers, a **Miner breaks veins for ore** (feeds the stalled M3a smelt/forge
    chain!), a Hunter seeks monsters for xp, a Homebody tends the economy.
    Specialization likely beats everyone-generalist — and some just *like fishing*.
  - **Adaptive preferences from lived experience** — a char grows to favor what's
    worked FOR IT (struck it rich in the mines → prefers mines) and avoid what hurt
    it (nearly died on the spire → fears it). Preferences reinforce from outcomes:
    D&D-charming AND a sound "do more of what works for you" heuristic that biases
    (never overrides) its scored decisions.
  - **Occasional group raids** — chars mostly spread out, but every so often a
    party bands up and coordinates on something a lone char can't take (a tough
    zone, the boss guarding the great forge). Coordinated multi-char tactics vs.
    the current thin one-per-map spread.
  - **The narrative that makes it legible** — character sheets (real names,
    stat/gift archetypes, deeds), relationships (bonds from fighting together;
    **mourning** a fallen friend, maybe via a `say` eulogy — ties to trash-talk),
    "keep the fellowship alive" (protect veterans from suicide runs), and
    story-mode on the dashboard ("The Ballad of Recruit-7679") so you can *see* and
    root for why each character does what it does. Dovetails with the memorial and
    death post-mortem items.
  - **Path** — incremental: (1) per-char role tags that softly bias existing
    decisions → (2) adaptive preferences from outcomes → (3) the A/B harness +
    per-char KPIs → (4) coordinated raids. Guardrail: an experimental per-char
    policy risks that one char underperforming — bounded (one char, not the guild),
    and that's the point (measure, keep winners).
- [ ] **In-world trash talk via `say`** — the bot posts contextual chat using the
  unused `say` verb: taunt a rival parking its roster, celebrate a big haul, mourn
  a death. Free personality (and doubles as campaign-layer eulogies).

- [ ] **Analyze *why* a tile was impassable → hidden-opportunity discovery** — the
  0.12.0 nav fix now records per-world "learned-blocked" tiles (things chars
  bounced off). Feed those into the analysis loop with a two-layer read: a
  "dummy" first pass that discards the obvious (literal rock/wall/water), leaving
  the *interesting* blockers for interpretation — a `fence`/`bush`/`tree` that
  **breaks after a few attacks** (docs 08), a `vein` that **drops ore when
  broken** (feeds M3a!), or a tile that looks solid but might be a secret door.
  Cross-reference the blocked tile's `kind` (from `tiles_seen`) against what's
  known to be breakable, and surface "maybe break this?" candidates. Could drive
  active game discovery (attack-the-obstacle probes) rather than just routing
  around. (operator request)
- [ ] **Magic — CASTING** *(the acquisition half SHIPPED as 0.63.0; this is what remains)* —
  `cast {spell: form, essence, target[, focus]}`. **Aether is FREE** — no attunement, no
  focus, and it is the default if no essence is named — so an aether cast of a learned form
  needs nothing but mana and stamina. Not every form x essence exists (`no_such_working`),
  which is a learn-by-rejection grid exactly like the forge recipes.
  **Prerequisite is now satisfiable:** 0.63.0 stops us selling tomes and `use`s them to learn
  a form. Wait until a character actually holds a form before building this, or it ships inert
  the way v0.54.0 did.
  Scoring: good_idea 0.90 (a whole mechanic we have never used, and ranged damage is the
  levelling lever the operator's direction asks for); risk_to_bot 0.85 (touches live combat
  and spends mana/stamina; `no_such_working` and friendly fire are real — rings and fields hit
  our own characters too).


- [ ] **Rival-awareness dashboard panel** — surface the spectate `intel` (us vs
  rivals: size, levels, gear) on the web UI.
- [ ] **Player market (`list` / `buy_listing`)** — we only use the NPC shop; the
  guild-to-guild market is untouched.

## Done

Shipped items live HERE, not in Open — an "Open" section that is 40% closed items
is misleading to scan, and the every-pass check that the score table covers every open
item is only checkable when the two are separated. Entries below keep their full
original text; the short `-> module (date, @ run)` lines are the older ledger format
and are kept as-is rather than rewritten.

- [x] **Danger as COST, not wall** — SHIPPED 2026-08-22 as **0.84.0 planned escape**:
  strike-range tiles cost `nav.AVOID_COST=8` (one eaten hit) instead of being walls, in the
  hurt+cornered branch only; built from the operator's mob-box screenshot (two wizard
  corpses on #170). The desperation-branch scoping kept the risk term honest.
- [x] **Portal hazard-mask** — SHIPPED 2026-08-23 as **0.91.0**, widened from "bare chars"
  to the WHOLE roster: `portal` joined `nav.SOLID` after run #179's vanish spiral (a
  spawn-strip portal at vale (63,0) fed an 18-death / 119-recruit loop, plus server-side
  frame ghosts — server_bugs.md). Deliberate portal use stays open via the separate
  "Portal-aware routing" item.
- [x] **Rival-recon dashboard tab** — SHIPPED 2026-08-21 as the **Rivals** tab
  (`ui/server.py` `api_recon` + `/api/recon`, Playwright-tested). Reads the `spectate` and
  `track` intel feeds that had been written for months and never read back. Cross-guild, not
  rival-only, because every number here is a ratio. 7 unit tests + 1 Playwright, 10 mutants
  killed; 0.140s on the live DB.
  **It paid for itself on the first look:** we field the ONLY fully-armed roster on the
  server (10/10 vs 9/30 and 2/9) and the highest median level (8 vs 3 and 2) — and rivals
  work at depth 29–43 while ours sit at median depth 2, which is POISON_SAFE_DEPTH seen from
  the outside and independent confirmation that DEPTH is the ore bottleneck.

- [x] **Magic — ACQUIRING FORMS (tomes)** — SHIPPED `explorer/0.63.0`, 2026-08-21, run #140.
  The block was never cost. **We had sold 74 tomes** (ring 22, step 16, field 14, veil 13,
  bolt 9) for 36-44 gold apiece against a 120-150 shop price, most recently on runs #130,
  #135 and #137, and had never learned a single spell. A tome carries `use`, not `equip`, so
  `_should_sell` filed it under "pure loot -> bank it" — the fourth scarce chain input lost to
  that same default. Now kept while under `spell_cap` and `use`d before the sell step, with
  (character, tome_kind) learn-by-rejection. 12 tests, 10 mutants killed.
  **Casting remains unbuilt** and is back on the Open list at tc=1.

- [x] **Expectation/reality mismatch detector** — SHIPPED `steemer/expectation.py` +
  `explorer/0.61.0`, 2026-08-21, run #138. The bot derives a checkable claim from each action
  it sends (move/pickup/buy/equip/sell) and resolves it against later frames as
  confirmed / violated / **expired** — the third value being the whole design, since frames are
  stale and "not yet" must never read as "did not". Alarms are PER ACTION FAMILY (a rare broken
  family hides under a common healthy one in any pooled rate) and refuse to rule on a small
  sample. They print live and persist as `bot_anomaly` rows the dashboard already surfaces.
  22 tests, 19 mutants killed.
  **It earned its place on its first run over real data:** across 20,000 frames it found that
  `pickup` confirms 90 times against 811 violations — 90% of our pickups fail silently, because
  `overburdened` (1,164 events) is reported as an EVENT rather than an action_error and nothing
  ever learned from it. That is now the next lever.

- [x] **Band-refresh timing awareness** — SHIPPED `explorer/0.60.0`, 2026-08-21, run #137.
  Each field frame carries `next_refresh: {band, in_ticks}` and we had ignored it entirely.
  Detection uses two independent tells (the band NUMBER changes, or `in_ticks` JUMPS UP — a
  countdown only falls, so a rise is a new cycle); per world, ten boundaries in ~14,000 ticks.
  First use: a refresh REFILLS chests, so emptied ones become targets again, with the
  hypothesis kept OUT of the observed map. 13 tests, 12 mutants killed.
  **Value stated honestly:** the commit message oversold it by quoting SIGHTINGS
  (2,500–4,600/bucket) as if they were distinct chests. There are **22** distinct emptied
  chests in the whole map. Correct and cheap, but a modest lever — see decisions.log iter 72.
  **The bigger half is unbuilt:** timing GATHERING to the cycle. Loot swings ~900x within a
  single run (0.052 → 1.839 → 0.002 items/frame), and we still spend the trough hunting loot
  that is not there. Re-add as its own item if it outranks the leaders.

- [x] **M3a forging** — SHIPPED `explorer/0.52.0` (forge) + `0.53.0` (equip-upgrade),
  2026-08-21, runs #129/#130. The blocker was never real: the `product` name was in our own
  event stream all along — 189 rival `forged`/`forge_started` events name it outright
  (`{"kind": "forge_started", "product": "shield_iron"}`). Recipe QUANTITIES are still
  undocumented, so the design is learn-by-rejection, and run #129 duly LEARNED them from the
  server's `wrong_materials` replies: **spear = 1 ingot + 1 lumber**, **dagger = 1 + 1**,
  **shield_iron = 3 ingots + 1 lumber** (2+2 and every cheaper combination were refused).
  All five `forged` events on #129 were ours. **Then 0.53.0, because #129 also showed the
  forge output being SOLD** — the slot search learned outfit/trinket/boots were wrong for a
  spear, `hand` held a club, and the sell rule concluded no slot remained. Gear may now
  displace strictly dearer same-class gear, ranked on the shop's own prices.
  **Known gap, stated rather than faked:** `shield_iron` is sold at no price, so it cannot be
  ranked and can only be worn into an offhand that is still empty. Valuing the unbuyable is
  the next slice.

- [x] **Move the storage mirror off the decision hot path** — RESOLVED 2026-08-21 by
  measurement, and NOT by building the thing. `0.51.0` built the worker thread and
  SEGFAULTED the live bot (shared MariaDB connection, zero frames across #124–126); `0.51.1`
  reverted it and kept only the free half — decide and send *before* recording. That alone
  was the whole fix: run #128 took **85,319 frames with 0 gaps and 0.0% loss**, against
  #120's 3.7% over 31 gaps, with >200ms stalls down 11.6% → 2.1%. There is no remaining
  latency problem for a thread to solve, so the mirror should NOT be rebuilt. A test pins
  `run()` against constructing one.

- [x] **Cross-run KPI regression alarm** → `steemer/kpi_watch.py` (2026-08-20, @ run #88,
  bot on explorer/0.32.0). Read-only DB analysis; `flag_regressions` is mutation-checked.
  Selected by the operator's wishlist-scoring formula (final 0.537 > 0.5). Later fixed to
  flag per-1k RATES not cumulative totals (run-length confound).
- [x] **Death post-mortem taxonomy** → `steemer/postmortem.py` (2026-08-20, @ run #91, bot
  on explorer/0.35.0). Read-only; `classify_death` is pure + mutation-checked. Shares the
  bestiary (WILDLIFE_SAFE/THREAT_KINDS) with the strategy. Boundary wishlist pick (~0.49,
  zero-risk). First run: most deaths are `stuck` chars pinned by wolf/delver.
- [x] **Behavioral mob analysis (part a: monsters)** → `steemer/bestiary.py` +
  `tests/test_bestiary.py` (2026-08-20, @ run #92, bot on explorer/0.36.0). Read-only;
  `build_bestiary` is pure + mutation-checked (3 mutations caught). Tracks each mob by its
  stable `eid` to measure chaser-vs-stationary behaviour, aggro range, and damage/hit.
  Wishlist-scoring winner @ 0.578. Independently validated the strategy's predator allowlist
  on live run #92. Part (b: rival players) folds into the Rival-recon dashboard tab item.
- [x] **Always-on watchdog (detection half)** → `steemer/watchdog.py` +
  `tests/test_watchdog.py` (2026-08-20, @ run #93, bot on explorer/0.36.0). Read-only frame-
  liveness alarm; `classify_liveness` is pure + mutation-checked + self-tested both sides.
  Wishlist-scoring winner @ 0.538. Push-alert transport + single-host guard remain open.
- [x] **"Codex" tab — an auto-populated wiki (lands / items / monsters / mechanics)** — SHIPPED 2026-08-20 (ui/server.py api_codex + /api/codex + Codex tab, Playwright-tested). Built as a one-off on operator request (score -0.21 by the formula: just-added tc=1, but operator-directed). Reuses the bestiary (monsters), tiles_seen+events (lands), frame item-sightings (items), docs/*.md + confirmed findings (mechanics); regenerated every load. — a
  dashboard tab that consolidates everything we've learned into one browsable reference,
  regenerated after each run so it stays current. Most of the data already exists — this is
  largely presentation + consolidation, not new analysis:
  - **Monsters** — reuse `steemer/bestiary.py` (per-mob chaser/stationary behaviour, aggro
    range, hit-rate, est damage/hit, benign-vs-predator-vs-undead classification). One page
    per mob kind.
  - **Lands (worlds)** — per world: terrain vocabulary (`tiles_seen` kinds), size/bounds,
    live undead/threat level (`_world_threat`), band-refresh cadence, and the survivor-bias-
    corrected **danger** (from the heatmap `danger` layer, deaths/time-in-tile), plus which
    mobs rotate in.
  - **Items** — kinds seen (from frames' `visible.items` + character inventories), their slot/
    type (weapon/outfit/potion/tome), and gold value where known (shop prices / sale events).
  - **Mechanics** — the game rules we've learned, drawn from `docs/*.md` + the findings
    notebook (band refreshes, poison/DoT, coins bank instantly, forge blocked on product
    discovery, stamina gating, etc.).
  A build step regenerates the codex snapshot from the DB (bestiary, tiles_seen, item
  sightings, danger) + docs + findings after each run; the tab renders it. High operator-
  reference/enjoyment value; read-only (dashboard sidecar, zero bot risk). Dovetails with the
  behavioural-mob work, the heatmap, and rival-recon. (operator request 2026-08-20)

- [x] **Extend the watchdog to cover the web SIDECAR** — SHIPPED 2026-08-21 as the wider
  **always-on supervisor** (`steemer/health.py` + `tools/healthcheck.py` + `svc.sh up watch`):
  covers bot (frame freshness), web sidecar (`intel` freshness) AND dash (port), restarts what
  is dead with a per-service cooldown, and repairs a broken venv instead of restarting into it.
  Prompted by the 2026-08-21 outage, where all three services were down and the bot then
  crash-looped on an ABI-broken pyzmq while `svc.sh status` reported "up". Original text:
  `steemer/watchdog.py` only checks the
  BOT's frame-liveness. The `web` sidecar (`tools/web_sidecar.py`: rainbow map-color rotation +
  rival intel/spectate + tiles) died externally on 2026-08-19 and sat dead ~1.5 days UNNOTICED
  (stuck color, paused intel recording) — the frame-watchdog can't see it. Add a sibling
  liveness check: `intel` table freshness (newest spectate row age) or `run/web.pid` process
  liveness, classified like `classify_liveness`. Read-only. (surfaced fixing the stuck-color
  report 2026-08-20; operator asked whether to build it)

- [x] **Comprehensive per-character stats panel on the dashboard** — SHIPPED 2026-08-20
  (ui/server.py `/api/roster` + the "Party" tab; verified by a Playwright test in the
  reaper gate). Per-char cards: colour-coded live HP bar + stamina bar, stats with gifts
  flagged, level/xp, equipment slots, individual inventory, status chips (poison etc.),
  world+pos, and the latest decision. Wishlist-scoring winner at 0.53 once risk_to_bot
  was corrected (dashboard = separate sidecar, can't hurt the bot). Original text: — a live roster
  view where each character is a card/row showing everything about it in real time:
  a **live HP bar** (hp/max_hp, colour-coded, + any status like poison/burn), level
  & XP, the six stats (str/dex/int/vit/end/agi) with gifts flagged, stamina/mana
  bars, equipment slots (hand/offhand/outfit/trinket/boots), **the character's live
  individual inventory** (carry used/cap + item list), current world & position, and
  what it's doing (its latest decision/trace). Basically turn the roster into a
  proper "party sheet" that updates as the frames stream in — the foundation the
  Campaign-Layer idea wants, and just good visibility into who's alive/hurt/rich.
  Data is all in the frames (`chars[].hp/max_hp/stats/equipment/inventory/carry/
  statuses/level/xp`), streamed via the spectate/events feed. (operator request)

- [x] **Cross-run KPI regression alarm** — the loop auto-flags when *any* metric
  regresses vs the prior window. The direct meta-fix for the blindness that let
  `move_failed` rot for 8 runs; never get blind-sided again. **SHIPPED 2026-08-20
  (`steemer/kpi_watch.py`, surfaced by the wishlist-scoring formula @ 0.537).** On
  its first live run (#87→#88) it flagged income −53% / chest_opens −69% and, via a
  frame-proportional `undead_frac` context KPI, showed the undead level was ~constant
  (5.3→5.6%) — i.e. 0.32.0 traded income for survival, a finding I'd otherwise have
  mis-attributed to the world.
- [x] **Death post-mortem taxonomy** — for every death, reconstruct the last ~15
  ticks (HP curve, position, killing blow, was flight ever possible?) into a
  structured cause-of-death. Turns deaths into a survival dataset (and feeds the
  campaign layer's char deeds). **SHIPPED 2026-08-20 (`steemer/postmortem.py`,
  wishlist-scoring boundary call ~0.49, zero-risk read-only).** On run #91 it
  immediately showed most deaths are `stuck` (pinned in place, not fleeing) by
  wolf/delver — auto-characterizing the chaser residual.
- [x] **Loot & danger heatmaps per world** — SHIPPED 2026-08-20 (ui/server.py `api_heatmap`
  + `/api/heatmap` + the "Heatmap" tab; Playwright test in the reaper gate). Per-tile density
  canvas with a layer selector: Danger (all-run deaths from events), Monsters/Gold/Loot
  (sampled from recent frames). Wishlist-scoring winner @ 0.551 once enjoyment/visibility was
  credited to good_idea (operator: don't dock for "aesthetic but doesn't help the bot").
  Original: where loot, gold, monsters, and deaths cluster on each map; route toward hot zones.
- [x] **Always-on watchdog** — DETECTION HALF SHIPPED 2026-08-20 (`steemer/watchdog.py`
  + `tests/test_watchdog.py`; read-only, pure oracle mutation-checked + self-tested both
  sides). `classify_liveness(now, latest_received_at)` → ok/warn/critical from the age of
  the newest frame; `check_db` reads it via the `seq` PK (instant); CLI exits 0/1/2 for a
  cron. Catches the silence the KPI/post-mortem tools can't (they read completed runs): the
  zlib crash-loop (#39-51 empty), the kick-war, a stopped bot. Wishlist-scoring winner @
  0.538. STILL OPEN (smaller follow-ons): the external PUSH-alert transport, and a "single
  authoritative host" guard (refuse `bot-up` if a session is already live, or detect the
  'kicked' log line and back off) to prevent the kick-war outright — see the `svc.sh
  collides with screen host` finding. Original: ping the operator when something
  actually breaks: bot crash-looping, run window not advancing, bankruptcy, or a
  mass-death spike. Ops safety for a bot that runs unattended.
- [x] **Version-timeline "story mode"** — SHIPPED 2026-08-20 (ui/server.py `api_story` +
  `/api/story` + a "Story mode" card in the Timeline tab; Playwright test in the reaper gate).
  Groups the findings notebook by `explorer/X.Y.Z` version (newest first); each version shows
  its shipped HYPOTHESIS (consideration) + MEASURED effect (measurement/discovery/correction)
  with colour-coded shipped/measured tags. Wishlist-scoring winner @ 0.537 once enjoyment was
  credited to good_idea. Original: the dashboard narrates the bot's evolution: each strategy
  version's hypothesis + its measured effect as a visual timeline.
- [x] **Behavioral analysis of mobs and rival players** — part (a) **monsters SHIPPED
  2026-08-20** (`steemer/bestiary.py` + `tests/test_bestiary.py`; read-only, pure core
  mutation-checked). Follows each mob by its stable `eid` across frames to infer per-kind
  `move_rate` (cadence), `chaser_score` + a `behavior` label (chaser/stationary/skittish/
  wanderer), `aggro_range`, `hit_rate`, and clean single-adjacent-blame `est_dmg_per_hit`.
  Wishlist-scoring winner @ 0.578. First live run (#92) independently confirmed the
  strategy's `_is_melee_predator` allowlist: the chasers-that-hurt (wolf/boar/crab_green/
  cultist, dmg 4–6) are exactly what it flees, and the benign allowlist members that chase
  (skunk/bat_brown/rat_grey) deal ZERO measured damage. Part (b) **rival players** remains
  open — it folds into the dedicated "Rival-recon dashboard tab" item below.
  Original: learn the *patterns* of
  the things we share the world with. Two kinds: (a) **monsters** — the
  game-programmed behavior (aggro range, movement, attack cadence, retreat,
  status application) inferred from the `visible.entities` (faction=monster) we
  already log per field frame; a learned bestiary would let the bot predict and
  exploit them. (b) **rival players** — extrapolate the *algorithms* other guilds
  encoded for their characters (do they park in the village, rush a map, hunt
  loot, avoid us?) from `/events/spectate` + the periodic spectate roster. Both
  feed strategy: counter mob patterns, and anticipate/avoid/outcompete rivals.
  Builds on the existing intel pipeline. (operator request)
- [x] **Dashboard "how navigation works" explainer** — SHIPPED 2026-08-21 (`ui/server.py`
  `api_nav` + `/api/nav` + the "How nav works" tab; unit + Playwright tested). Derived, not
  written down: rules from `steemer/nav.py` via inspect at request time, priority ladder from
  the bot's own recorded decision traces. Original: — a tab (or a section of the
  Decisions tab) that explains the character navigation algorithm in plain terms:
  why a char rests / retreats / pushes a frontier / routes around a learned-blocked
  tile. Ideally *dynamic* — derived from or versioned with the actual nav/strategy
  code so it stays true every time the nav protocols change, and the operator can
  learn why characters do what they do. (operator request)
- [x] **Rival tracking via `/events/spectate`** — SHIPPED 2026-08-20
  (`steemer/spectate_track.py`; SSE -> `intel` table kind='track', tick-keyed, portal-resilient).
  Original: — live enemy positions/gear per
  map (currently we only poll the periodic roster). Would enable avoidance/PvP.
- [x] **Adaptive cohesion / raids** — SHIPPED 2026-08-21 as explorer 0.48.0/0.48.1. A
  STANDING leash in dangerous worlds (score 2.8, above frontier, strictly below spacing),
  gated on a max-over-TTL per-world danger reading. 0.48.0 competed with gathering and lost
  every tick, so 0.48.1 BIASES it instead: out of position, prefer loot near an ally — same
  action, same score, same income, formation closes while we work. Verified on real frames
  (loot-near-ally 220 offered/84 chosen; standalone 238/43). Original: — characters draw TOGETHER where it pays and spread
  where it doesn't, gated on how dangerous the world/band is. **Split out of the Campaign
  Layer 2026-08-21** (it was step 4 there, "occasional group raids"), because the campaign
  layer's `risk_to_bot` 0.50 — earned by its per-character A/B harness — had been pricing
  this too, and it is a far cheaper change. Inherits the campaign layer's `add_minor` (13):
  splitting must not reset the clock on an idea that has genuinely been waiting since then.
  **This was the operator's idea from the original entry, down to "the boss guarding the
  great forge".**

  **The mechanism, MEASURED (2026-08-21)** — unusually for this list, this is not a guess:
  | participants | DPS on the mob | party dmg taken/tick | per-MEMBER dmg taken/tick |
  |---|---|---|---|
  | 1 | 2.36 | 0.51 | 0.51 |
  | 2 | 4.80 | 0.49 | 0.24 |
  Damage output roughly doubles (holds within mob kind: rat_grey 1.86→6.07, wolf
  3.78→10.42, skunk 2.59→5.97, mole 0.99→2.23). The party's total intake per tick is FLAT
  because a mob can only swing at one target per tick — so per-member intake halves. That
  second row is pure geometry and cannot be confounded by rivals' better gear, unlike the
  DPS column. Net: **~2x kill speed at ~half the personal damage — roughly 4x less damage
  taken per member per kill.**

  **XP is SPLIT, and that is fine.** Measured the same day, two oracles agreeing: total XP
  per kill is flat in participant count (5.70 at 1p, 5.87 at 2p, where per-participant
  would predict 11.40), and a within-character control gives a shared/solo ratio of 0.545
  against a split prediction of 0.47. So grouping does not MULTIPLY xp — but with kill
  speed roughly doubling, XP per character per unit time is ~unchanged. The case for
  cohesion was never XP; it is survivability, and survivability is what buys access to
  content worth more XP. (Nuance: there is a floor of ~1 xp per participant, so on
  near-worthless mobs — chicken, turtle, sheep — grouping pays slightly MORE in total.)

  **The constraint that kills the naive version: REACTIVE COHESION CANNOT WORK.** Median
  solo time-to-kill is **6 ticks**; our mean pairwise distance is **22-25 steps** and
  movement is a tile per tick. "Gang up, a mob is near" arrives ~16 ticks after the fight
  ended. The coming-together must be **STANDING** — a leash held *while in* a dangerous
  world or band, so the second attacker is already a step or two away when anything starts.
  The spreading-out half works fine reactively; only the gathering cannot.

  **Where to apply it** — per-world threat over 400k ticks:
  | world | frames | char deaths/1k | dmg/swing | contents |
  |---|---|---|---|---|
  | vale | 46,493 | 4.93 | 3.91 | skunk/chicken/wolf/frog — wildlife: SPREAD, gather |
  | mines | 46,489 | 5.06 | 4.00 | bat/rat/mole + delver/lava_ant: RAID — and it holds the veins |
  | spire | **3,917** | **6.64** | **5.25** | vampire_bat/ghoul/cultist/zombie — all undead |
  (Char deaths include rivals; read comparatively.) Spire is the real frontier: 35% deadlier
  per frame, the hardest hitters, and we spend 8% as much time there as in the other two —
  yet it is the northern content docs/04 says we must reach to keep levelling. We flee it.
  **A mines raid is simultaneously the ore run and the levelling run**, which is the same
  place the M3a forge chain is currently stuck.

  **We already own every piece:** v0.38 gates behaviour on band severity (the switch);
  v0.37/0.38 spacing pushes AWAY from predators (cohesion is its mirror term on the same
  ladder); v0.39 per-char roles already separate guardian from forager; and the danger
  heatmap already computes per-tile deaths/time, survivor-bias corrected. This is a
  cohesion score, not a new subsystem.

  **Known hazard:** cohesion-toward-allies and spacing-from-predators can fight each other
  and oscillate a character between them. The scores must be ordered deliberately rather
  than left to tie — the v0.37 anti-stuck work is the precedent for how that goes wrong.

  **Cost:** coverage. Five characters in one place gather about one character's worth of
  tiles, and dispersal is our whole gathering/frontier economy. That is the real trade, and
  it is what the per-band gate exists to manage.

  **Scoring:** good_idea 0.88 (one of the few MEASURED items, and it unlocks content we
  currently cannot touch at all); risk_to_bot 0.85 (a movement/scoring change to the core
  loop, bounded and reversible, but it can conflict with spacing and it costs coverage).
  **0.539 at tc=34 — QUALIFIES.**

- [x] **Shadow-evaluation deploy gate** — SHIPPED 2026-08-21 (`steemer/shadow.py`, 13 tests).
  Replays the working tree's strategy over recorded frames and diffs it against what the
  incumbent ACTUALLY chose (from the `decisions` table — no git gymnastics). Headline output
  is the INERT list. Refuses to rule below MIN_DECISIONS, because v0.48.0 was wrongly called
  inert from a sample taken inside a warm-up. Honest limit recorded in the module: TRUST THE
  STRUCTURE, NOT THE COUNTS — replay cannot reproduce live counts. Original: — before shipping a candidate strategy,
  replay it AND the incumbent over the last N recorded frames and compare
  predicted KPIs. A "is this actually better?" check that would've caught the
  0.11.0 "fix that didn't fix."
- [x] **Exploration matrix (A) — the cube + the frontier** — SHIPPED 2026-08-21
  (`steemer/matrix.py` + `steemer/vocabulary.py`, 16 + 101 tests). Read-only, issues no
  actions. Live over 9,100 cells it reports SIX frontier cells: `lumber x forge` at 0.95
  (the item declares `uses:["forge"]` and `forge` is one of 12 protocol verbs we have never
  sent) and `say` at chest/grave/portal/safe/wall at 0.70. It independently surfaced the M3a
  blocker AND the operator's magic-word intuition from a standing rule. Two first-run flaws
  fixed: the equip axis expanded for verbs it cannot affect (7x duplicate noise), and the
  tested layer used a row window so `brew` (474 lifetime sends) read as never tried.
  Original: *(READ-ONLY; no bot risk)* —
  build the noun × verb × equipped cube, score its cells, and populate what we have already
  tried. Ships an artifact, touches nothing the bot does. (operator request 2026-08-21; split
  out of the original single item 2026-08-21 because bundling two very different risk profiles
  under one score is the "bundled" dock the scoring rule warns about)

  **The cube.** Columns = every noun we have ever encountered (the 23 observed tile kinds —
  floor, wall, path, water, tall_grass, tree, bush, lily, rock, crop, herb, fence, vein, web,
  track, chest, chest_open, portal, trap, cauldron, forge, safe, grave — plus item kinds from
  frames/inventories/drops and mob kinds from the bestiary). Rows = every action verb
  (`docs/03-actions` plus any inferred). Depth = every equippable item **including `none`**, so
  `tree × attack × none` is a real cell beside `tree × attack × axe`.

  **The score.** Each cell carries a `prior` in 0..1: *is there something one could plausibly do
  here — a mechanic that exists in real life or in other games?* `tree × attack × axe` high;
  `grass × consume × sword` low. Per-cell scoring does not scale to thousands of cells, so
  priors derive from auditable **rule families** ("chopping verb × woody target × bladed tool =
  high"), with per-cell overrides where a family gets it wrong. The families are the reasoning;
  a noun the game invents tomorrow is scored the moment it appears.

  **`say` gets a different depth axis.** Equipment barely varies the outcome of speaking — the
  variable is the WORD. So `say` cells expand over a curated wordlist instead: folklore/game
  conventions (open, sesame, friend, mellon, xyzzy, plugh) and, **ranked higher, words the world
  itself hands us** — grave and sign text, item names, `docs/` strings, `tells`/flavour fields.
  A word found in-world is a far better prior than one imported from Tolkien.

  **The tested layer comes free and retroactive.** `actions_sent` × `action_errors` × `events`
  already records what we sent, whether it bounced and with which `reason`, and what happened.
  Joining those yields **the frontier: high-prior cells we have never once tried** — with no new
  action issued. Dashboard tab; pairs naturally with the Codex.

  **Why the frontier is large.** Across **4.3M actions sent we have only ever used 14 verbs**:
  move, embark, attack, pickup, recruit, drop, sell, buy, equip, open, use, spend_xp, brew,
  smelt. Never sent: `say`, `cast`, `forge`, `list`, `buy_listing`, `unequip`, `rest`, `refresh`.
  And nouns like `safe`, `grave`, `portal`, `web`, `track` have almost certainly never been acted
  on — the same blind spot as trees sitting in `nav.SOLID` as scenery. The frontier is not a few
  odd corners of the cube; it is most of the verb axis.

  **Scoring:** good_idea 0.85 (produces the map, not the discoveries — the discoveries are (B));
  risk_to_bot **1.00** (pure analysis over stored data; it cannot touch the running bot).
  Ceiling 0.6375; **clears 0.5 at tc=7**.

