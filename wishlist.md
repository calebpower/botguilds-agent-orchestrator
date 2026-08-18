# Wishlist

Things the operator would like me to **consider** implementing — candidates, not
commitments. I keep this list, tick items off as they ship (noting the version or
commit), and the operator adds new ones. Anything here is fair game to weigh
during the improvement loop, but nothing here is obligatory.

Format: `- [ ]` open · `- [x]` done (with where it shipped). Newest ideas at the
top of **Open**.

## Open

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
