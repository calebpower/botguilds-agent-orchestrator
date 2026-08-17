# Gameplan — milestones for Stanley_Steemer

The long arc for the self-improving bot, as a ladder of milestones. Each rung has
a **goal**, **why it matters**, the **work**, a **measurable exit criterion**, and
a **status**. The loop (`loop.md`) picks each iteration to advance the lowest
unmet milestone; `decisions.log` records the moves and `findings.jsonl` the
learned game model.

Guiding principles (unchanged):
- **Discover, don't assume.** The game hides its content (items, enemies,
  recipes, essences, tells, the weave circle, bosses). Every system is learned by
  *experiment + log + infer*, not by hard-coded knowledge.
- **Measure before/after.** Sequential run-window rate metrics; a swing inside
  noise is not a result. `runs` is the attribution backbone.
- **Survival compounds.** A character that lives, levels, crafts, and learns is
  worth far more than a fresh recruit; most value is in keeping them alive.
- **Every change is gated + measured + reversible.** Local pytest → reaper gate →
  hot-redeploy (detached) → measure → log. Rollback is a known-good sha.

Current position: **M2 (survival), largely met; M3 (self-sufficiency) is next.**

---

## M0 — Foundation & liveness  ✅ DONE
**Goal:** a bot that plays the real game continuously and improves itself.
**Have:** fresh Python client (pyzmq), verbose per-decision logging + SQLite
mirror, reaper pre-redeploy gate, read-only web UI, self-paced improvement loop,
detached (cap-resilient) runner, hot-redeploy + rollback.
**Exit:** bot plays without Claude; the loop iterates, gates, and measures. ✔

## M1 — Mechanical competence  ✅ DONE
**Goal:** stop wasting actions; use gear.
**Did:** nav wall-bug fix + monster-tile blocking + destination reservation
(move_failed 55%→0.8%); per-action stamina gating (action-errors 8.5%→3.9%);
equip carried gear (0→41% of fielded chars armed).
**Exit:** move_failed <5%, action-error <5%, weapon-equip climbing. ✔

## M2 — Survival  ◑ LARGELY MET (keep pushing)
**Goal:** characters live long enough to accumulate value.
**Did:** retreat at 60% HP + poison-triggered flee + heal/flee-only; field
potions; spend XP into VIT/END. Result: deaths/1k −28%, poison exposure −48%,
survivor max_hp 30→66.
**Exit:** deaths/1k ≤ ~half the 0.1.0 baseline (met); **median** max_hp trending
above the 30 recruit floor (partial — survivors reach 66 but median still 30 →
recruits still die young).
**Still to do:** cut recruit churn (protect/withdraw low-level chars; don't feed
fresh recruits into the hardest map — the deferred *spire de-funnel*).

## M3 — Self-sufficiency via crafting  ▶ NEXT
The guild makes its own gear and consumables instead of depending on a shop that
sells no armor and on rare loot.
- **M3a Forging** *(do first — fills the armor gap, needs ore not gold)*: mine
  ore veins (pickaxe) → `smelt` 2 ore → ingot → `forge` weapons/armor (+lumber,
  +flux). Learn per-metal flux by experiment (read the `forged` tells).
  **Exit:** armor-equip% > 50%; forged weapon/armor tier > shop tier; a per-world
  metal→flux table with ≥2 confirmed entries.
- **M3b Brewing** *(second)*: stand at a cauldron, `taste`/`brew` 2–4 ingredients
  (calibrate with fixed parts: bone=vigor, ectoplasm=aether, venom_sac=venom),
  log `tells`+products, infer this world's herb→essence map and recipe tiers.
  **Exit:** self-brewed elixirs (tier ≥ potion) carried and used; a herb→essence
  table with ≥4 confirmed entries per world.
- **M3c Foraging** *(fold in)*: eat carried/foraged food (crops) to extend the
  finite field-heal reserve. **Exit:** measurable rise in ticks-alive-per-expedition.

## M4 — Magic (spellweaving)  ○ AFTER M3
**Goal:** unlock the third pillar and the direct poison counter.
**Work:** buy/loot tomes → `use` to learn forms (veil/step/bolt/field/ring);
attune essences via `focus` ingredients from brewing; map the per-world **weave
circle** by reading resound/fray on the cast event. Use **clarity** (purge
poison/workings), **vigor** (heal), **aether** (shove/ward/blink), **bolt/ring**
(ranged/AoE).
**Exit:** poison's contribution to deaths ≈ 0 (clarity in rotation); the weave
circle mapped for ≥1 world; casts used in normal play without stamina/mana errors.

## M5 — Economy & scale  ○ AFTER M3/M4
**Goal:** convert production into wealth and a strong standing roster.
**Work:** sell crafted gear on the **player market** (full price, not 20% shop
buyback); per-map specialization (vale=brew, mines=forge, spire=magic); balanced
deployment that stops overfeeding the hardest map.
**Exit:** sustained gold/hr growth; roster held near cap with rising average
level; net-positive market trades.

## M6 — Deep content & bosses  ○ ENDGAME
**Goal:** reach and beat what the game hides at the top.
**Work:** push through refreshing bands to map tops; handle portals, special
places, roaming `wanderers`, traps; assemble a party strong enough for the
band-top guardians ("something big guards the great forge"; the spire sanctum
"will not fall to a lone party").
**Exit:** deepest-band clears per map; a boss encounter survived, then killed;
the top-of-map content documented in `findings.jsonl` (bestiary/drops/mechanics).

## M7 — Autonomy & knowledge maturity  ⟳ CROSS-CUTTING / ONGOING
**Goal:** the loop and its knowledge stay trustworthy as they grow.
**Work:** honest before/after attribution; `findings.jsonl` as a living,
curated per-world model (reviewed each iteration, not append-only); UI graph +
heatmap + knowledge views; usage-aware throttling (operator check-in ladder);
periodic reference-submodule review; frames-table retention without losing
per-run history.
**Exit:** the operator can walk away for long stretches; a newcomer can read
`decisions.log` + `findings.jsonl` and understand why the guild is the way it is.

---

### Sequencing note
Recommended order is **M3a forging → M3b brewing → M4 magic → M5 economy → M6
bosses**, with M2 tail-work (spire de-funnel) and M7 folded in continuously. This
order is driven by the metrics: armor (M3a) is the top unmet durability lever
(0% armored, unbuyable), and magic's `clarity` (M4) is the direct counter to the
poison that still dominates damage. Adjust freely — it's a plan, not a contract.
