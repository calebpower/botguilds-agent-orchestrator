# Wishlist

Things the operator would like me to **consider** implementing — candidates, not
commitments. I keep this list, tick items off as they ship (noting the version or
commit), and the operator adds new ones. Anything here is fair game to weigh
during the improvement loop, but nothing here is obligatory.

Format: `- [ ]` open · `- [x]` done (with where it shipped). Newest ideas at the
top of **Open**.

## Open

- [ ] **Log-scale the overview-page bar charts (QoL)** — on the dashboard overview
  page, the bars at the bottom span values of wildly different magnitude (e.g. moves
  in the tens-of-thousands vs deaths in the tens), so the small bars are unreadable
  next to the huge ones. Apply a logarithm to the bar lengths (log10 or log1p,
  keeping the true value in the label/tooltip) so cross-metric comparisons are
  actually useful. Guard log(0) (use log1p or a floor). (operator request)

- [ ] **The Campaign Layer — characters as individuals who actually *play*
  differently** ⭐⭐ (operator idea). Not just a narrative overlay — a layer that
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
  mass-death spike. Ops safety for a bot that runs unattended. **NOW HIGH VALUE:**
  a "latest frame older than N seconds" alarm would have instantly caught BOTH the
  zlib crash-loop (runs #39-#51, empty) and the 2026-08-18 deploy kick-war (guild
  single-session collision between the svc.sh bot and the screen host). A companion
  "single authoritative host" guard (refuse to `bot-up` if a session is already
  live, or detect the 'kicked' log line and back off) would prevent the kick-war
  outright — see the `svc.sh collides with screen host` finding.
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
