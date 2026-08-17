# Combat and damage

## Tick order (why you can't dodge)

Within a tick, all non-move actions resolve first (fastest `speed` first),
then all moves resolve (again fastest first). `speed` is rolled per tick from
AGI (`AGI×5 + d4`); ties break randomly. Practically:

- **An attack hits whoever is standing on the target tile when it resolves.**
  Since moves resolve *after* attacks, you cannot escape a already-declared
  attack by moving away on the same tick.
- Two characters can trade killing blows in the same tick if both attacked
  each other.
- Moving into a solid or occupied tile fails and still costs stamina — plan
  paths around bodies (see the example bots' `blocked` sets in
  [10-example-bots.md](10-example-bots.md)).

## The damage formula

Damage is **fully deterministic** — there is no to-hit roll, so a bot can plan
exactly, not just estimate:

```
damage = (weapon_base + weapon's own stat scaling using B(stat)) × tier_multiplier − target_armor
damage = max(damage, 1)     # a hit that connects always does at least 1
```

- Every weapon scales off its **own** stat: daggers off DEX, mauls off STR,
  wands/scepters off INT. Which stat, and the weapon's niche (reach, cleave,
  throwability, stun chance, ambush bonus), shows up in its `uses` and `desc`
  fields — the actual numbers are discovered by using it, not published.
- **Tier multiplier** comes from crafting quality (see
  [07-crafting.md](07-crafting.md)): weapon tiers 0–3 multiply damage
  ×0.8/×1.0/×1.2/×1.5 (forged) — found/worn gear never exceeds the low
  tiers.
- **Armor** is flat reduction, taken straight off the computed damage before
  the floor-of-1 clamp.
- **Magic ignores half of target armor** (rounded up) — casts and implement
  bolts are meaningfully better against heavily armored targets than
  equivalent physical damage. Some creatures/gear resist further, and a few
  are fully immune.
- **Wards** (from certain brews and at least one spell) soak damage before it
  touches HP at all.

## Friendly fire and PvP

Friendly fire is **on** — attacks and area spells hit whatever occupies the
tile, including your own guildmates and other guilds' characters. There is no
separate PvP mode or flag: **PvP is simply attacking (or area-casting on) an
occupied tile that happens to hold a rival guild's character.** Rings and
fields (see [06-magic.md](06-magic.md)) hit everyone in their footprint,
friend or rival, so positioning matters even for support casts.

## Position and force

- **Concealment multiplies damage.** Striking from concealment (standing
  still in tall grass, on the Vale) lands a savage bonus with the right
  weapon — see [08-world-and-economy.md](08-world-and-economy.md) for how
  `tall_grass` works (it only hides you while you hold still; moving through
  it rustles and reveals you and any monster moving in it).
- **Heavy blows can stun or stagger** — a staggered character doesn't regen
  while staggered.
- **Some attacks and spells apply force** — shoving a target back, or
  dragging it adjacent to the caster. Walls stop all forced movement.

## Charge attacks

`charge {target}` is only usable with weapons that have a run-up attack. It
rushes an open straight line toward a target at least 2 tiles away and lands
a multiplied, shoving blow when it connects — see [03-actions.md](03-actions.md)
for the action shape and stamina cost.

## Statuses

Status effects exist (poison, burn, chill, sleep, haste, regen, and more —
not an exhaustive list; what inflicts each is discovered in play). Visibility
differs by whose character it is:

- **Your own characters** carry a full `statuses` list with `kind`,
  `ticks_left`, and `power` for every active effect (see the char frame shape
  in [02-protocol.md](02-protocol.md#map-frame)).
- **Visible monsters** show only the *kind strings* of their active statuses
  — no remaining duration.
- **Other guilds' characters** show no status information at all.

What causes each status (which weapon, which essence, which terrain) is part
of the content the server deliberately doesn't publish — log outcomes in your
`guild_log.db` and correlate. See
[08-world-and-economy.md](08-world-and-economy.md#what-isnt-written-down).

## Practical patterns

- Prefer attacking the *weakest* adjacent enemy (by `hp_frac`) to secure
  kills faster — `farmer_bot.py` and `ranger_bot.py` both do
  `min(adjacent, key=lambda p: enemies[p]["hp_frac"])`.
- Treat both monster **and** other-guild character tiles as blocked when
  pathing (a bounced move still costs stamina) — but keep monster tiles
  walkable in your *targeting* logic since you attack by walking adjacent and
  striking, not by "attacking through" a tile.
- Watch `char["stamina"]` before committing to an attack; idling a
  low-stamina character to rest is usually better than sending an action that
  will be rejected as unaffordable.
