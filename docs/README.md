# BotGuilds documentation

BotGuilds (`bot.willmorrison.net`) is a persistent multiplayer game world that you
play entirely by writing a bot. There are no matches, no rounds, and no client UI
to click through: you register a guild, run a Python process that speaks a small
JSON protocol to the server, and your bot recruits characters, sends them into
dungeons, fights, loots, crafts, trades, and (if you're any good) grows a guild
that survives. If your bot goes offline, your characters simply stand still and
rest — nothing is lost.

The game is explicitly built to be played *through a coding agent*. You describe
strategy in English; the agent turns it into an `on_frame` method. This `docs/`
folder is written for that workflow: it's the reference an agent (or you) needs
to write, debug, and improve a bot without re-deriving mechanics from scratch.

This documentation was assembled from the server's own `/docs` manual, the
`AGENTS.md` wire-level reference shipped in the starter kit, and a read of the
actual starter kit source (`botguilds/client.py`, `botguilds/protocol.py`, and
the three example bots). Where the manual and the code agreed, that's the
ground truth below; nothing here is guessed.

## Start here

If you're setting up a bot for the first time, read these two in order:

1. **[Getting started](01-getting-started.md)** — register a guild, get the
   starter kit, run it, understand `guild_token.json`.
2. **[The client library](09-client-library.md)** — what `GuildBot`,
   `run_bot`, and the local SQLite log actually do for you, so you know what's
   already handled and what you need to write.

## Reference, by topic

| Doc | Covers |
|---|---|
| [01-getting-started.md](01-getting-started.md) | Registration, the starter kit, running your first bot, `on_frame` |
| [02-protocol.md](02-protocol.md) | The tick loop, wire protocol (ZeroMQ/JSON), connection lifecycle, frame shape |
| [03-actions.md](03-actions.md) | Every action: arguments, where it's legal, stamina cost, failure reasons |
| [04-characters-and-stats.md](04-characters-and-stats.md) | The six stats, effective-bonus soft cap, XP/leveling, gifts, recruiting, death, unattended recall |
| [05-combat-and-damage.md](05-combat-and-damage.md) | Damage formula, armor, tick order, positioning, statuses, PvP/friendly fire |
| [06-magic.md](06-magic.md) | Mana, implements, spellweaving (forms + essences), attunement, the weave/thread |
| [07-crafting.md](07-crafting.md) | Brewing and forging, tells, quality tiers, the busy/`craft` state |
| [08-world-and-economy.md](08-world-and-economy.md) | The three maps, bands and refresh, terrain, carrying/bulk, gold and markets |
| [09-client-library.md](09-client-library.md) | `botguilds.client` / `botguilds.protocol`, `GuildBot`, `GuildClient`, the SQLite schema, `read_frames` |
| [10-example-bots.md](10-example-bots.md) | Annotated walkthroughs of `starter_bot.py`, `farmer_bot.py`, `ranger_bot.py` |
| [11-map-viewer.md](11-map-viewer.md) | `map_viewer.py`, the local map/entity visualizer |

## The one-paragraph version

Every 0.25s tick, the server resolves all non-move actions (fastest character
first, by a per-tick roll off AGI), then all moves, and sends you one JSON
`frame` per world your characters occupy. You reply with at most one action
dict per character. Combat is deterministic (no to-hit rolls) and attacks
resolve against whoever is standing on the target tile when they're evaluated
— you cannot dodge by moving. Six stats (STR/DEX/INT/VIT/END/AGI) drive
damage, HP, mana, stamina and speed through a published soft-cap curve; XP
comes from kills and discoveries and is spent one stat point at a time.
Stamina paces you to roughly one action every 4–5 ticks; an idle character
rests (double regen, slow healing) instead of acting. Three maps — Vale
(brewing), Embermines (forging), Spire (magic) — get harder as you push north
through periodically-refreshing bands. Crafting (`brew`/`smelt`/`forge`) is a
single timed command per character; recipes are a public *grammar* over a
per-world-shuffled *vocabulary* you have to infer from `taste` and from the
"tells" every craft reports. Death drops your whole kit on the ground but
costs nothing to replace. None of the game's actual content — items, enemies,
recipes, bosses — is documented anywhere; it's discovered in play and mirrored
into your own `guild_log.db`.

## Source of truth

- Server manual: `https://bot.willmorrison.net/docs`
- Starter kit: `https://bot.willmorrison.net/starter.git` (vendored here as the
  `reference_starter_kit` git submodule at the repo root)
- Wire-level agent reference: `reference_starter_kit/AGENTS.md`
- Client library: `reference_starter_kit/botguilds/client.py`,
  `reference_starter_kit/botguilds/protocol.py`

The server deliberately keeps game *content* (items, enemies, recipes, boss
mechanics, per-world ingredient vocabularies) undocumented — see
[08-world-and-economy.md](08-world-and-economy.md#what-isnt-written-down) and
[07-crafting.md](07-crafting.md). That's by design, not a gap in these docs.
