# The world, terrain, carrying, and economy

## The three maps

You choose which map to `embark` on. All three run bottom-to-top: you spawn
at the bottom of whatever band you're in, the exit is the bottom edge
(`move S` from row 0 returns you to the village), and enemies, loot and
containers get better the further north you push. Every band on every map has
**several independent routes up**, so no rival guild can plug the only path —
expect company, and expect a way around it.

| map | id | size | theme | danger | crafting pillar |
|---|---|---|---|---|---|
| The Vale | `vale` | 72×200 | Gentle overworld — meadows, forests, lakes, farmland | easiest | Brewing (cauldrons out in the field) |
| The Embermines | `mines` | 64×176 | Dug galleries, ore veins, minecart rails, magma vents | medium | Forging (something big guards the great forge at the top) |
| The Hollow Spire | `spire` | 56×208 | Haunted tower — libraries, crypts, three parallel spines | hardest | Magic (nothing here is a starter monster; what holds the top sanctum won't fall to a lone party) |

The village frame lists embarkable maps under `maps` (id + `bounds`). Beyond
terrain, every map holds themed encounters, rare special places, and things
that roam — a `wanderers` event names a roaming band when one shows up near
you. What and where these are is content, discovered in play, not documented
here.

## Terrain

| tile kind | effect |
|---|---|
| `track` / `path` | Cuts move cost. Standing on `track`, you can `ride {dir}` — a flat-cost slide to the rail's end (capped at `ride_max_tiles`); whatever blocks the rail gets rammed for damage. |
| `web` | Doubles move cost. |
| `rime` (frost surface) | Doubles move cost, same as `web`. |
| `tall_grass` (Vale only) | Conceals a character who **holds still**. Moving through it *rustles* — you become visible, and so does any monster moving through it. |
| `water`, `tree`, `bush`, `fence`, `rock`, `vein`, `cauldron`, `forge` | Solid — blocks movement. Some solid tiles (trees, bushes, fences) break after a few attacks, faster with the right tool. `vein` drops ore when broken. |
| `herb` | Walkable; `open` it to harvest (a sickle helps). |
| `crop` | Yields food via `open`. |
| `portal` | Stepping on one teleports you to its linked twin. |
| `cauldron` / `forge` | Crafting stations — worked from an adjacent tile, not by standing on them (they're solid). |

`starter_bot.py`/`farmer_bot.py`/`ranger_bot.py` all treat this set as
impassable when pathing: `{"wall", "chest", "chest_open", "safe", "trap",
"water", "tree", "bush", "fence", "rock", "vein", "cauldron", "forge"}` —
note `chest`/`safe`/`trap` are containers/hazards, also solid until opened.

## Bands refresh

Each map regenerates **one horizontal band at a time** on a schedule:

- Every map frame carries `next_refresh: {band, in_ticks}` so you can see a
  refresh coming.
- A `band_refresh_warning` event fires roughly 60 seconds ahead of the actual
  refresh.
- **A band with your characters still in it defers its refresh — but only
  for a while**, not indefinitely; eventually it refreshes regardless.
- **Loot left behind in a refreshed band is gone.**
- **Band boundaries themselves drift slightly with each refresh** — trust
  the live `next_refresh`/frame data over any row number you've memorized
  from a previous session.

Practical implication: don't stash valuable loot in a band and plan to
retrieve it later — either carry it out or accept the risk it despawns on
the next refresh.

## Carrying: bulk, not slots

There's no inventory slot count — capacity is **bulk-based**:

- Every item has a `bulk` (an egg is 1, a maul is 5).
- Carry cap is `18 + 3·B(STR)`.
- Your char frame shows `carry: {used, cap}`.
- Picking up past your cap leaves the excess on the ground (a pickup that
  would exceed cap errors rather than partially succeeding — check `carry`
  before issuing `pickup` for anything bulky).
- **Gold weighs nothing** — it goes straight to guild-level gold, not a
  character's inventory.

## Economy

Gold is **guild-level**, shared across all characters, not per-character.

- The **shop** sells a small stock of basics at list price (`buy_price`) —
  the docs manual names `dagger, club, shortsword, spear, shield_wood, bow,
  bomb, pickaxe, sickle, bottle_empty, potion_red, potion_blue, vial_green`
  as the baseline stock, exposed at runtime via the village frame's
  `shop.stock`.
- The shop **buys back anything at 20% of list, scaled by quality tier** —
  deliberately bad, so that:
- The **player market** is where real value changes hands: `list {item_id,
  price}` posts an item, any guild can `buy_listing {listing_id}` at your
  price, and **you keep every coin** (no shop cut). Listings are visible to
  every guild in every village frame (`guild.market_listings`).
- `unlist {listing_id}` pulls your own listing back.

Sell to players when you can; only use the shop's buyback as a last resort or
for junk nobody's listing demand exists for.

## What isn't written down

The server's manual is explicit that it documents the **interaction
surface** completely, and just as deliberately does **not** document the
world's *content*:

- Items, outfits, enemies, recipes
- Each world's ingredient-to-essence and metal-to-flux vocabulary
- Containers, traps, special places
- What roams, and boss mechanics

This is intentional design, not a gap in these docs — see the manual's own
section 14, "What isn't written down." Your bot's local `guild_log.db` is
where this knowledge accumulates: it's your guild's actual map knowledge,
drop tables, and bestiary, since the server offers no database export. See
[09-client-library.md](09-client-library.md#the-local-database) for the
schema and example queries, and treat every session's log as compounding
institutional knowledge for the next bot iteration — never hardcode
item/enemy numbers you haven't personally observed, since they're content and
may change.
