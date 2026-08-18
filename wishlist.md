# Wishlist

Things the operator would like me to **consider** implementing — candidates, not
commitments. I keep this list, tick items off as they ship (noting the version or
commit), and the operator adds new ones. Anything here is fair game to weigh
during the improvement loop, but nothing here is obligatory.

Format: `- [ ]` open · `- [x]` done (with where it shipped). Newest ideas at the
top of **Open**.

## Open

- [ ] **The Campaign Layer — treat characters as individuals, keep a fellowship
  alive** ⭐ (operator idea, flushed out). Overlay a persistent D&D-style
  narrative on the mechanical roster. The event log already records each
  `char_uid`'s whole life (embarks, kills, deaths, xp, close calls, loot), so
  this is an *analysis + presentation* layer, not new game content:
  - **Character sheets** — a persistent record per char: a real name (not
    "Recruit-7679"), an archetype inferred from stats/gifts (the gifted-VIT
    "Tank", the high-STR "Bruiser"), and a running list of deeds.
  - **Relationships** — chars who field together / fight side-by-side / survive a
    scary run together form bonds; a survivor who witnessed a comrade die
    **mourns** them (a grief mood, maybe a `say` eulogy — ties to #7). Track it as
    a small relationship graph (bonded-with, avenged, rivals).
  - **Attitudes, likes/dislikes, preferences from lived events** — a char nearly
    killed by poison on the spire grows to **fear the spire**; one who struck it
    rich in the mines **favors the mines**. These become soft preferences that can
    *gently* bias strategy (a tiny score nudge to embark toward a favored map, or
    beside a friend, or away from where it nearly died) — flavor that must never
    override survival/productivity.
  - **Keep the fellowship alive** — identify a core party of veterans (level,
    deeds) and protect them: don't throw a beloved 6-veteran into a suicide run;
    prioritize *their* continuity as a soft objective. A campaign you're rooting
    for, not just a headcount.
  - **Story mode** — the dashboard renders each life as a short saga ("The Ballad
    of Recruit-7679: 43 ticks, 2 rats, fell poisoned at the spire"). Dovetails
    with the memorial (#6), death post-mortem (#2), and `say` banter (#7).
- [ ] **Cross-run KPI regression alarm** — the loop auto-flags when *any* metric
  regresses vs the prior window. The direct meta-fix for the blindness that let
  `move_failed` rot for 8 runs; never get blind-sided again.
- [ ] **Death post-mortem taxonomy** — for every death, reconstruct the last ~15
  ticks (HP curve, position, killing blow, was flight ever possible?) into a
  structured cause-of-death. Turns deaths into a survival dataset (and feeds the
  campaign layer's char deeds).
- [ ] **Shadow-evaluation deploy gate** — before shipping a candidate strategy,
  replay it AND the incumbent over the last N recorded frames and compare
  predicted KPIs. A "is this actually better?" check that would've caught the
  0.11.0 "fix that didn't fix."
- [ ] **Loot & danger heatmaps per world** — where loot, gold, monsters, and
  deaths cluster on each map; route toward hot zones and see the world we can't
  fully see.
- [ ] **In-world trash talk via `say`** — the bot posts contextual chat using the
  unused `say` verb: taunt a rival parking its roster, celebrate a big haul, mourn
  a death. Free personality (and doubles as campaign-layer eulogies).
- [ ] **Always-on watchdog + push alerts** — ping the operator when something
  actually breaks: bot crash-looping, run window not advancing, bankruptcy, or a
  mass-death spike. Ops safety for a bot that runs unattended.
- [ ] **Version-timeline "story mode"** — the dashboard narrates the bot's
  evolution: each strategy version's hypothesis + its *measured* effect (from
  decisions.log) as a visual timeline. A guided tour of why the bot is the way it
  is.
- [ ] **Band-refresh timing awareness** — the game has periodically-refreshing
  "bands" (we log `band_refresh` events and ignore them); time embarks/retreats
  around them instead of getting caught out.
- [ ] **Behavioral analysis of mobs and rival players** — learn the *patterns* of
  the things we share the world with. Two kinds: (a) **monsters** — the
  game-programmed behavior (aggro range, movement, attack cadence, retreat,
  status application) inferred from the `visible.entities` (faction=monster) we
  already log per field frame; a learned bestiary would let the bot predict and
  exploit them. (b) **rival players** — extrapolate the *algorithms* other guilds
  encoded for their characters (do they park in the village, rush a map, hunt
  loot, avoid us?) from `/events/spectate` + the periodic spectate roster. Both
  feed strategy: counter mob patterns, and anticipate/avoid/outcompete rivals.
  Builds on the existing intel pipeline. (operator request)
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
- [ ] **Dashboard "how navigation works" explainer** — a tab (or a section of the
  Decisions tab) that explains the character navigation algorithm in plain terms:
  why a char rests / retreats / pushes a frontier / routes around a learned-blocked
  tile. Ideally *dynamic* — derived from or versioned with the actual nav/strategy
  code so it stays true every time the nav protocols change, and the operator can
  learn why characters do what they do. (operator request)
- [ ] **Magic / spellweaving (`cast`)** — the direct counter to the poison that
  dominates status-damage; a whole unused mechanic (M4). Needs mana/implement +
  attunement discovery.
- [ ] **M3a forging** — armor is unbuyable; forging is the only route. Blocked on
  learning a per-world `product` name (blind-forge storms `unknown_product`).
  Path: harvest a `forged` event from a rival via `/events/spectate`, or the shop.
- [ ] **Rival tracking via `/events/spectate`** — live enemy positions/gear per
  map (currently we only poll the periodic roster). Would enable avoidance/PvP.
- [ ] **Rival-awareness dashboard panel** — surface the spectate `intel` (us vs
  rivals: size, levels, gear) on the web UI.
- [ ] **Move the storage mirror off the decision hot path** — `record_frame`
  (~11 ms on MariaDB) runs before the decision in `client._loop`; sending actions
  first would shave latency. Low value alone (measured small) — revisit if frame
  staleness ever proves material.
- [ ] **Player market (`list` / `buy_listing`)** — we only use the NPC shop; the
  guild-to-guild market is untouched.

## Done

_(nothing yet — newly created)_
