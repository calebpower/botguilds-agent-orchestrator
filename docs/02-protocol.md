# The tick, the wire protocol, and frames

## The tick

The server runs one persistent simulation, ticking at a fixed rate (default
0.25s), forever. Each tick it collects at most one action per character,
resolves them in a fixed order, and sends every connected guild one `frame`
per world it has characters in.

**Resolution order within a tick:**

1. All **non-move** actions resolve first, in descending `speed` order.
   `speed` is rolled fresh every tick from AGI (`AGI×5 + d4`); ties break
   randomly.
2. All **moves** resolve next, also in descending speed order.

Because attacks resolve *before* moves, **you cannot dodge by moving away** —
an attack hits whoever occupies the target tile at the moment it resolves.
Two characters can kill each other in the same tick. Moving into a solid or
occupied tile fails and still costs stamina.

If your bot is offline or slow, you simply miss ticks — a slow bot doesn't
crash the world or get penalized beyond the ticks it missed. See
[Connection lifecycle](#connection-lifecycle) for what happens on a longer
silence.

## Connection lifecycle

Transport is **ZeroMQ DEALER** to the server's ROUTER bot port, one JSON
object per message (no framing beyond that — `botguilds.protocol.encode`/
`decode` just do `json.dumps`/`json.loads`). The client library
(`botguilds.client`) does all of this for you; this section is for anyone
writing a raw client or debugging the wire.

```
-> {"type": "hello", "guild_id": "g_ab12", "token": "…"}
<- {"type": "hello_ok", "tick": 10411, "config": {...}, "guild": {...}}
<- {"type": "hello_err", "reason": "bad_token"}      # check guild_token.json
<- {"type": "frame", ...}                            # one per world per tick
-> {"type": "actions", "tick": 10412, "actions": [...]}
<- {"type": "action_err", "char_uid": "…", "reason": "out_of_range"}
<- {"type": "server_pause"}                          # live restart — reconnect shortly
<- {"type": "kick", "reason": "superseded"}           # another session hello'd as you
-> {"type": "bye"}                                    # polite hangup, optional
```

Message type constants live in `botguilds/protocol.py`:
`HELLO`/`ACTIONS`/`BYE` (client→server), `HELLO_OK`/`HELLO_ERR`/`FRAME`/
`ACTION_ERR`/`SERVER_PAUSE`/`KICK` (server→client).

Behavior worth knowing:

- **A new `hello` for your guild retires the previous session.** You cannot
  accidentally run two bot processes against the same guild — the second
  `hello` wins and the first gets `kick {reason: "superseded"}`.
- **Auth failure** (`hello_err`) means your `guild_token.json` is wrong —
  re-register or re-check the file; the client library gives up and exits
  rather than retry-looping against bad credentials.
- **`server_pause`** means a live server restart; reconnect after a short
  backoff (the client library does this automatically with exponential
  backoff capped at 30s).
- **Silence detection:** a connected bot gets a frame every tick. The client
  library treats 10 seconds of silence (`SILENCE_TIMEOUT` in `client.py`) as
  evidence the server restarted under it — DEALER sockets reconnect the TCP
  session transparently without raising an error, but the new server process
  has never seen your `hello`, so the library proactively re-sends it.
- **`hello_ok.config`** carries server-wide constants your bot should read
  rather than hardcode: `party_cap`, `world_cap`, `roster_cap`,
  `field_heal_mult`, `ride_stamina`, `ride_max_tiles`, the list of `maps`
  (with their `id`/size), etc. `run_bot`/`GuildClient` stash this on
  `bot.config` automatically — see the example bots reading
  `self.config.get("party_cap", 5)`.
- **`hello_ok.guild`** is your guild snapshot at connect time (gold,
  inventory, characters, listings) — also stashed, on `bot.guild`.

## Frames

You get **one frame per tick per world your characters are in** (so a party
split across the village and two maps gets three frames a tick, each handled
independently — this is exactly what `ranger_bot.py` relies on for per-map
memory).

### Map frame

```json
{"type": "frame", "tick": 10412, "world": "vale", "bounds": [72, 200],
 "next_refresh": {"band": 2, "in_ticks": 1180},
 "chars": [{"char_uid": "g_ab12_c1", "eid": 311, "pos": [14, 87], "hp": 22,
            "max_hp": 35, "stamina": 40, "max_stamina": 60, "mana": 10,
            "max_mana": 14,
            "stats": {"str": 2, "dex": 1, "int": 1, "vit": 3, "end": 2, "agi": 1},
            "gifts": ["str", "agi"], "spells": [], "spell_cap": 1,
            "essences": [], "essence_cap": 2, "thread": null,
            "level": 4, "xp": 45, "speed": 8, "vision": 6, "armor": 0,
            "carry": {"used": 6, "cap": 24}, "field_healed": 0, "craft": null,
            "statuses": [{"kind": "poison", "ticks_left": 6, "power": 1}],
            "inventory": [{"item_id": "i_9a", "kind": "…", "tier": 1, "bulk": 2,
                           "uses": ["equip", "attack"], "desc": "…"}],
            "equipment": {"hand": {"item_id": "…", "kind": "…"},
                          "offhand": null, "outfit": "…", "trinket": null},
            "held": "…", "look": "…", "world": "vale"}],
 "visible": {"tiles": [[14, 85, "floor", 210], "…"],
             "entities": ["…"], "items": [{"eid": "…", "kind": "…",
             "pos": [14, 85]}], "gold": [{"pos": [14, 85], "gold": 12}],
             "surfaces": [{"pos": [14, 85], "kind": "fire"}]},
 "events": [{"kind": "attack", "attacker": 311, "target": 902, "dmg": 5}]}
```

Field notes:

- **`chars`** is your own characters, in full — every stat, status, and
  inventory item, no matter where they stand.
- **`visible`** is the *union* of every character's vision, where vision is a
  Chebyshev-radius square **and walls block line of sight**: a tile is
  visible only if no solid tile lies on the line to it, so corners hide
  things and corridors tunnel your view narrowly. Vision radius per character
  is in `char["vision"]`.
- **`visible.entities`** — other guilds' characters and monsters. A monster
  entry carries `eid`, `kind`, `pos`, `hp_frac` (fraction, not raw HP),
  `faction: "monster"`, a `statuses` list of *kind strings only* (no tick
  counts — that detail is private), and `elite`/`dormant` flags. A character
  entity (yours or a rival guild's) carries `eid`, `kind: "char"`,
  `faction: "guild"`, `guild_id`, `name`, `pos`, `hp_frac`, `look`, `outfit`,
  and `held` (what it last had in hand) — **never** its stats, statuses, or
  inventory. Only your own `chars` array carries that private detail.
- **`visible.items`**, **`visible.gold`**, **`visible.surfaces`** — ground
  loot, gold piles, and transient tile effects (e.g. `{"kind": "fire"}` from
  spreading ember damage) currently in view.
- **`events`** — things that happened where you could see them this tick
  (attacks, casts, crafts finishing, refresh warnings, recalls, etc.). Events
  are how you learn *tells* from crafting and *miscast* essence names — see
  [07-crafting.md](07-crafting.md) and [06-magic.md](06-magic.md).
- **`next_refresh`** — when this map band regenerates next; see
  [08-world-and-economy.md](08-world-and-economy.md#bands-refresh).
- **Every item** (in inventory, equipped, or on the ground) carries `tier`
  (0–3), `bulk`, a `uses` list (the verbs it answers to — this is how you
  discover a book is `use`-able or a mushroom is `brew`-able), and a `desc`
  flavor hint that never gives numbers. Stats and effects are for you to
  observe in play, not read off the item.

### Village frame

The village frame has **no `visible` and no `next_refresh`**. Instead:

```json
{"type": "frame", "tick": 10412, "world": "village",
 "chars": ["… characters currently standing in the village, full detail …"],
 "guild": {"gold": 340, "inventory": ["…"], "market_listings": ["…"],
           "chars_here": ["g_ab12_c1", "…"], "chars_by_world": {"vale": ["…"]}},
 "maps": [{"id": "vale", "name": "The Vale", "bounds": [72, 200]}, "…"],
 "shop": {"stock": [{"kind": "dagger", "buy_price": 30, "sell_price": 6}, "…"]}}
```

- `guild.chars_by_world` is how the example bots compute how many characters
  are currently fielded, per map, to respect `party_cap`/`world_cap` (see
  [10-example-bots.md](10-example-bots.md)).
- `shop.stock` lists what the shop sells at `buy_price` and buys back at
  `sell_price` (20% of list, scaled by quality tier) — see
  [08-world-and-economy.md](08-world-and-economy.md#economy).
- `guild.market_listings` is the full player market, visible to every guild.

### Idle worlds

When no guild has anyone fielded anywhere, the server stops simulating and
only ticks briefly in response to a request — your bot doesn't need to detect
or handle this specially; it keeps receiving village frames, and anything it
sends wakes the world back up.

## Actions you send

```json
{"type": "actions", "tick": 10412, "actions": [
  {"char_uid": "g_ab12_c1", "action": "move", "dir": "N"},
  {"action": "recruit"}
]}
```

- Send **at most one action per character per tick**; if you send two for the
  same character, the later one wins.
- Guild-level actions (`recruit`, `embark`, `buy`, `list`, `unlist`,
  `buy_listing`) omit `char_uid` entirely.
- Every other action requires `char_uid`.
- Malformed actions are rejected client-side-shape-checked by
  `botguilds.protocol.check_action` before they're even sent in the reference
  client, and rule-checked (stamina, range, capability) by the server — either
  way, a rejected action costs nothing and comes back as `action_err` with a
  `reason`.

See [03-actions.md](03-actions.md) for the full action reference.
