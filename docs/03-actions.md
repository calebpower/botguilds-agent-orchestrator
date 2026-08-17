# Actions reference

Send a list of action dicts each tick (see
[02-protocol.md](02-protocol.md#actions-you-send)). Every `target` is a tile
`[x, y]` — attacks and casts hit whatever occupies the tile when they
resolve, never an entity id. One action per character per tick; a second
action for the same character in the same tick replaces the first. Rejected
actions cost nothing and come back as `action_err {char_uid, action, reason,
tick}`.

## Guild-level actions (no `char_uid`)

| action | args | notes |
|---|---|---|
| `recruit` | `[name]` | Free level-0 character, up to `roster_cap` (server config). Rolls 1–2 in each stat and two `gifts` (see [04](04-characters-and-stats.md)). |
| `embark` | `map`, `char_uids` | Sends a party from the village to a map. Capped per map (`party_cap`) and across all maps at once (`world_cap`); exceeding either errors `party_cap`/`world_cap`. |
| `buy` | `kind` | Village shop purchase. |
| `list` | `item_id`, `price` | Post an item to the player market. |
| `unlist` | `listing_id` | Pull your own listing. |
| `buy_listing` | `listing_id` | Buy another guild's listing at their price — they keep every coin (no shop cut). |

## Per-character actions (`char_uid` required)

| action | args | where | notes |
|---|---|---|---|
| `move` | `dir: N\|S\|E\|W` | map | Single axis. Walking `S` off row 0 exits to the village. Diagonals (`NE`/`NW`/`SE`/`SW`) exist in the protocol but error `no_diagonal_step` unless your gear grants them (then ×1.5 stamina). |
| `ride` | `dir: N\|S\|E\|W` | map | Only from a `track` tile: slides along the rail to its end (up to `ride_max_tiles`) for a flat cost — fast and cheap, no stopping early. Whatever blocks the rail gets rammed for damage. Diagonal riding always errors `bad_dir` — rails run straight. |
| `attack` | `target: [x,y]` | map | Your equipped weapon decides the shape: a melee swing/punch in reach, or — for bows and implements — a shot down a straight rank/file/true-diagonal that stops at the first wall (implements also cost mana). |
| `charge` | `target: [x,y]` | map | Only for weapons with a run-up attack: rushes an open straight line (target ≥2 away) for a multiplied, shoving blow. |
| `cast` | `spell` `[, essence, target, focus]` | map | Weaves a learned form with an essence. See [06-magic.md](06-magic.md). Costs mana and stamina. |
| `throw` | `item_id`, `target` | map | Throwable items only; the item lands where it's thrown (unless it bursts). |
| `use` | `item_id` `[, target]` | anywhere | Consumables. Using a tome reads/learns it. A few items target a tile (blasts, teleports). |
| `pickup` | `[item_id]` | anywhere | No `item_id`: take everything on the tile. With one: just that item. In the village, moves an item *into* the free/infinite guild inventory. |
| `drop` | `item_id` | anywhere | Drop on your own tile. In the village, moves an item *out of* guild inventory onto the character. |
| `equip` | `slot` `[, item_id]` | anywhere | Slots: `hand`, `offhand`, `outfit`, `trinket`, `boots`. A bare slot (no `item_id`) unequips into your pack, bulk permitting. Gear with stat requirements errors `stat_requirement` if you don't meet them. |
| `open` | `target` | map | Adjacent containers, crop tiles, herb plants. Some containers need several consecutive opens (interrupting resets progress). |
| `spend_xp` | `stat` | anywhere | +1 to a stat. Cost: `8 × v × 2^(v//10)` XP where `v` is the stat's *current* value — half that if the stat is one of the character's two `gifts`. Stats cap at 24. |
| `say` | `text` (≤40 chars) | map | Visible flavor text only. |
| `rename` | `name` (≤32 chars, trimmed) | village | Rename a character. |
| `taste` | `item_id` | anywhere | Destructively consumes a component to learn what it brews (its essence). |
| `brew` | `item_ids` (2–4) | anywhere | One command starts and occupies the character for the whole brew. See [07-crafting.md](07-crafting.md). |
| `smelt` | `item_ids` | anywhere | Two matching ore → one ingot. Same timed-command mechanics as `brew`. |
| `forge` | `product`, `item_ids` | anywhere | Ingots (+ lumber, + optional flux) → a finished item. Timed command. |
| `sell` | `item_id` | village | Sell to the shop at 20% of list, scaled by tier. |

Crafting actions (`taste`/`brew`/`smelt`/`forge`) work both on a map — next to
the right station (`cauldron` for brewing, `forge` for forging) — and in the
village, where they're capped at quality tier 2; the top tier needs a real
station tile out on a map.

## Where an action is legal

- **"anywhere"** truly means both village and any map.
- **"map"**-only actions error if sent while the character is in the village
  (and vice versa for `sell`, `list`, `unlist`, `buy_listing`, `embark`,
  `recruit`, `buy`, which are village/guild-only).

## Validation

`botguilds/protocol.py`'s `check_action` shape-checks an action *before* it's
sent (this is what the reference client does client-side; the server
independently validates and additionally enforces game rules like stamina,
range and capability):

- `action` must name one of the known actions (`ALL_ACTIONS`).
- Must carry `char_uid` unless it's one of `GUILD_ACTIONS` (`recruit`,
  `embark`, `buy`, `list`, `unlist`, `buy_listing`).
- Must carry every argument key that action requires (`missing_<key>`).
- `move`/`ride` must use a known direction (`bad_dir`).
- `target`, when present, must be a 2-element list/tuple of ints
  (`bad_target`).
- `char_uid`, `map`, `product`, `listing_id`, `kind`, `slot`, `stat`, `spell`,
  `essence` (optional), `char_uids`, `item_ids` are all type-checked
  (`bad_<field>`).

A shape failure and a game-rule failure look identical from the bot's side:
both come back as `action_err` with a `reason` string and no state change.
Always read `on_action_error` rather than assuming your action shape was
correct — see `ranger_bot.py`'s equip-slot learning in
[10-example-bots.md](10-example-bots.md) for a bot that treats `action_err`
as information, not just a log line.

## Rest: the action you don't send

There is no explicit "rest" action. **A character you send nothing for rests
automatically**: stamina and mana regen at double rate, and once it has gone
unhit for a few ticks it heals a little (more with VIT) — see
[04-characters-and-stats.md](04-characters-and-stats.md#stamina-and-resting).
Idling in the village heals faster still (10% max HP per tick) and restores
stamina fully. Doing nothing is a real, deliberate move, not something to
avoid — every example bot idles low-stamina characters on purpose rather than
sending a doomed action.

One caveat: **resting counts as "unattended"** for the 2000-tick recall timer
— see [04-characters-and-stats.md](04-characters-and-stats.md#unattended-recall).
If you want a party to hold position in the field indefinitely, send some
action (even `say`) periodically.
