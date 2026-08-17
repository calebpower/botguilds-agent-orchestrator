# `map_viewer.py` — visualizing what your guild has scouted

A one-file, stdlib-only local webserver over your bot's `guild_log.db`.
Source: `reference_starter_kit/map_viewer.py`.

## Running it

```bash
python map_viewer.py [--db guild_log.db] [--port 8777] [--game http://<server>]
```

Then open `http://127.0.0.1:8777/`. Pick a world from the dropdown; the
canvas draws:

- **Every tile your guild has ever seen** (`tiles_seen`), rendered with the
  real tile art — not a placeholder grid.
- **Live entities and loot from the latest frame** for that world (the most
  recent row in `frames`), overlaid on top of the historical tile map.
- Your own characters get a highlighted outline (`faction == "guild"`) so
  you can spot them among rival-guild characters and monsters.
- Auto-refreshes every 2 seconds while "auto-refresh" is checked.

## Where the art comes from

`Art.__init__` tries two sources, in order:

1. **Inside the game repo** (i.e. you're running this alongside the actual
   server source): imports `botguilds.assets`, `botguilds.entities.BESTIARY`,
   and `botguilds.items.{BARE_TILE, ITEMS, LOOKS}` directly, reading the
   atlas PNGs and sprite-index tables straight from disk.
2. **Outside the repo** (the normal case for a bot-only checkout): pass
   `--game http://<server>` and it fetches `/assets/atlas.png`,
   `/assets/atlas_gen.png`, and `/api/tiles` (columns, tile size, sprite
   indices, `bare_tile`, `looks`) from the live server's public endpoints
   instead.

Sprite indices at or past `meta["count"]` live on the *generated* atlas sheet
(`atlas_gen.png`) rather than the base one — this is how the client tells the
two apart when drawing (`drawSprite` in the page's inline JS subtracts
`meta.count` and switches images).

## Endpoints it serves

| path | returns |
|---|---|
| `/` | the viewer page (inline HTML/JS, no build step) |
| `/atlas.png`, `/atlas_gen.png` | the two sprite sheets |
| `/api/meta` | `{columns, tile_size, count}` for sprite-index math |
| `/api/worlds` | distinct `world` values seen in `tiles_seen` |
| `/api/map?world=<id>` | `{bounds, tiles, entities, items, tick}` — see below |

`/api/map` combines **everything ever seen** (`tiles_seen`, all history) with
**only the latest frame's** entities/items (current truth) — this is exactly
the same "accumulate tiles, trust only the current frame for what's moving"
split that `farmer_bot.py`/`ranger_bot.py` use in their own pathing logic
(see [10-example-bots.md](10-example-bots.md)).

Row `0` is drawn at the **bottom** of the canvas (`py(y) = h - 1 - y`),
matching the game's own bottom-to-top map convention (see
[08-world-and-economy.md](08-world-and-economy.md)).

## Why it's one file

The module docstring is explicit about this: it's deliberately kept as a
single stdlib-only file specifically so you can **fork it into your own
tooling** — overlay your bot's pathfinding decisions, mark loot priority,
draw heatmaps of where you've died, etc. There's no framework or build step
standing between you and modifying the `PAGE` HTML/JS string or the
`Viewer` request handler directly.

## Practical uses

- **Sanity-check pathing bugs**: if a bot's BFS keeps failing to find a
  route, load the same world here and visually confirm what `tiles_seen`
  actually contains vs. what you assumed was explored.
- **Spot map structure you haven't coded for**: portals, gates between
  bands, chokepoints — easier to see at a glance than to infer from raw
  `(x, y, kind)` tuples.
- **Watch live play** without touching the game server's own Player tab —
  useful when iterating on a bot locally against a dev/test server.
