# Crafting

Crafting has a public **grammar** (the rules below) and a per-world-shuffled
**vocabulary** (which specific herb carries which essence, which flux favors
which metal, what each "tell" means). Identification is meant to be an
inference puzzle you solve by playing and logging results, not something you
look up.

## The shared mechanic: one timed command

`brew`, `smelt`, and `forge` are each a **single command**:

- Inputs are **consumed immediately** when you send the command.
- The character becomes **busy** for some number of ticks (bigger jobs take
  longer) — visible on the character as `craft: {kind, ticks_left, ...}`.
- **Until `craft.ticks_left` reaches 0, every other action for that character
  — including moves — is rejected with reason `crafting`.** You cannot
  cancel a craft by trying to act; you can only wait it out.
- **Walking home (or embarking) abandons the in-progress craft.** Don't send
  a character on a multi-tick craft and then also plan to relocate it before
  the timer runs out.
- The result — or the failure, which always says why — arrives when the
  timer hits 0.
- Both success and failure report **`tells`**: a short list of what the pot
  or anvil noticed about the ingredients (see below). Read these even on
  failure; they're free information.

Stamina cost is paid once, up front, not per tick: `brew`/`forge` cost 15,
`smelt` costs 10 (see [03-actions.md](03-actions.md)). Crafting works both on
a map (next to the right station) and in the village (capped at quality
tier 2 — the top tier needs a real station tile out in the world).

## Brewing

Stand next to a `cauldron` (or be in the village) and `brew {item_ids}` with
**2–4 ingredients**; you also need an empty bottle (`bottle_empty`, sold by
the shop) in inventory — it's consumed too.

- Every ingredient carries one of the **six essences** (ember, frost, venom,
  vigor, clarity, aether — the same six used in spellweaving, see
  [06-magic.md](06-magic.md)).
- **The majority essence in the pot decides the product.**
  - An exact **two-way tie** can combine into something better than either
    alone.
  - **Opposed essences curdle** (a wasted brew).
  - A pot with no clear agreement comes out **murky** (also wasted).
- **Which herb carries which essence is shuffled per world** — this is the
  core identification puzzle. Two ways to learn it:
  - `taste {item_id}` an ingredient: destructive, but tells you its essence
    directly.
  - Brew and **read the result** (and the `tells` — see below).
- **Monster parts are fixed, universal freebies** that don't shuffle:
  `venom_sac` = venom, `ectoplasm` = aether, `bone` = vigor. Use these as
  known reference points when you don't yet know your world's herb mapping.
- **Quality** (tier 0–3: draught / potion / elixir / grand, scaling effect
  ×0.6 / ×1.0 / ×1.6 / ×2.4) comes from what goes in: stronger ingredients
  raise the ceiling, and ingredients that *agree* with each other (same or
  adjacent essence) help further.
- Finished potions can themselves go back into a later brew as ingredients.
- Found/worn potions (picked up off the ground) are never better than the
  low tiers — good potions are crafted, not found.

## Forging

By a `forge` tile (or in the village): `smelt {item_ids}` **two matching
ore** into an ingot, then `forge {product, item_ids}` with ingots (plus
lumber for hafted weapons) and optionally **one extra ingredient as flux**.

- **Quality** (tier 0–3: crude / sound / fine / masterwork, multiplying
  weapon damage ×0.8 / ×1.0 / ×1.2 / ×1.5) comes from:
  - **The metal** — better metal raises the achievable ceiling; the metal
    itself *caps* the tier (copper only goes so far; rarer metals go
    further).
  - **The flux** — each metal favors a different flux, shuffled per world:
    the right flux perfects the piece, the wrong one mars it.
- A **masterwork** item bears its maker's name.
- A forged item can be **smelted back down** for part of its metal — found
  gear is legitimate feedstock for forging, not just something to sell.

## Tells

Every finished craft — success **or** failure — reports a short list of
`tells`: things the pot or anvil noticed about what went in. Examples:
`acrid_smoke`, `sweet_mist`, `pale_crust`, `dark_sheen`. **Which ingredient
produces which tell is hidden per world** — the way to learn it is to
correlate tells with outcomes across many crafts. This is exactly the kind of
signal you should be logging to `guild_log.db`'s `events` table (every craft
completion is an event) and mining later — see
[09-client-library.md](09-client-library.md#the-local-database).

## Quick reference

| | brew | forge |
|---|---|---|
| Station | `cauldron` (or village) | `forge` tile (or village) |
| Inputs | 2–4 ingredients + `bottle_empty` | ingots + lumber + optional flux |
| Quality axis | ingredient essence agreement | metal + flux match |
| Quality tiers | draught/potion/elixir/grand (×0.6/1.0/1.6/2.4) | crude/sound/fine/masterwork (×0.8/1.0/1.2/1.5) |
| Failure modes | curdled (opposed), murky (no agreement) | mismatched flux mars the piece |
| Village cap | tier 2 | tier 2 |
| Reversible? | potions can be re-brewed as ingredients | forged items can be smelted back down |

## Practical patterns

- Don't send a character into a craft and then plan to move it — the walk
  abandons the craft and wastes the consumed inputs.
- Check `char["craft"]` before issuing any other action for that character;
  if `craft is not None`, the only sane action is none (let it finish) or
  accept the `crafting` rejection.
- Keep monster-part freebies (`venom_sac`, `ectoplasm`, `bone`) as calibration
  points — brewing with a known-essence ingredient tells you what the
  *other* ingredients in the pot must be, by comparing to a solo-ingredient
  baseline brew.
- Log every `brewed`/`forged`/`curdled`/`murky` event's `tells` field
  alongside the `item_ids` that went in — that's the dataset the essence/flux
  puzzle is solved from.
