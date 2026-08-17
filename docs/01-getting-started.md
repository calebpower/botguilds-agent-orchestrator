# Getting started

## 1. Register a guild

Go to the server's docs page (`https://bot.willmorrison.net/docs`) and register
a guild name. The page mints a token and shows it **once** — copy it or use the
page's "download `guild_token.json`" link immediately.

The file looks like:

```json
{"guild_id": "g_ab12", "token": "…", "server": "tcp://localhost:5570"}
```

Save it as `guild_token.json` next to your bot script. The `server` value the
docs page mints is the address that works from wherever you registered —
don't hand-edit it.

If you already have a guild, the docs page also has a sign-in form: paste your
existing `guild_token.json` there to view/manage that guild in the browser
(this is separate from running your bot — the bot always reads the token file
directly).

## 2. Get the starter kit

Either clone it (recommended — `git pull` later picks up client-library
updates):

```bash
git clone https://bot.willmorrison.net/starter.git my-bot
```

or download `starter_kit.zip` from the docs page. Both give you the same
files:

```
my-bot/
  botguilds/
    __init__.py
    client.py       # GuildBot, GuildClient, run_bot, LocalLog, read_frames
    protocol.py     # wire message types, action shape validation
  starter_bot.py    # wander-and-punch, works unmodified
  farmer_bot.py     # remembers the map, path-finds, retreats, sells
  ranger_bot.py      # spreads a party across all three maps at once
  map_viewer.py     # local web UI over your guild_log.db
  AGENTS.md         # wire-level reference written for a coding agent
  CLAUDE.md         # @AGENTS.md — same reference, Claude Code's entry point
  README.md
```

In *this* repo, the starter kit is vendored as the `reference_starter_kit` git
submodule at the repository root — that's the same content, kept in sync via
`git submodule update --remote`.

## 3. Run it

```bash
pip install pyzmq
python starter_bot.py
```

`starter_bot.py` works unmodified: it recruits a full party, embarks them to
the Vale, wanders, and punches whatever it bumps into. It has no exit plan —
characters fight until they drop and the guild just recruits again. Open the
docs page's Player tab to watch your party live.

Useful flags on any bot built with `run_bot` (see
[09-client-library.md](09-client-library.md#run_bot)):

```bash
python starter_bot.py --server tcp://host:5570   # override guild_token.json's server
python starter_bot.py --token other_token.json    # run a second guild from one checkout
python starter_bot.py --db other.db               # keep this run's log separate
python starter_bot.py --no-log                    # skip the local SQLite mirror
python starter_bot.py --ticks 500                 # run a bounded number of frames, then exit
```

## 4. Write your own bot

Subclass `GuildBot` and implement `on_frame`, returning a list of action
dicts:

```python
from botguilds.client import GuildBot, run_bot

class MyBot(GuildBot):
    def on_frame(self, frame):
        if frame["world"] == "village":
            return [{"action": "recruit"}]
        return [{"char_uid": c["char_uid"], "action": "move", "dir": "N"}
                for c in frame["chars"]]

run_bot(MyBot())
```

Key rules to internalize immediately (all covered in depth elsewhere in this
folder):

- **One action per character per tick.** A later action for the same
  character in the same tick replaces the earlier one — don't try to queue
  several.
- **A character you send nothing for rests**, at double stamina/mana regen —
  this is a real, valid move, not a no-op you need to avoid.
  ([04-characters-and-stats.md](04-characters-and-stats.md))
- **Guild-level actions need no `char_uid`**: `recruit`, `embark`, `buy`,
  `list`, `unlist`, `buy_listing`. Everything else needs one.
  ([03-actions.md](03-actions.md))
- **Rejected actions cost nothing** and come back as `action_err` with a
  `reason` — read `on_action_error` instead of guessing why something failed.
- **Auth, reconnection, and per-frame SQLite logging are handled for you** by
  `GuildClient`/`run_bot`. Don't write ZMQ or HTTP transport code; set
  `server` in `guild_token.json` (or pass `--server`) instead.

## 5. Inspect what your bot has seen

Everything your bot sees and does is mirrored into `guild_log.db` (SQLite) —
the server has no database download, so this local mirror *is* your guild's
history, map knowledge, bestiary and recipe book. See
[09-client-library.md](09-client-library.md#the-local-database) for the
schema and query examples, and [11-map-viewer.md](11-map-viewer.md) for a
one-file web viewer that draws every tile you've ever scouted with real tile
art.

## Where to go next

- Writing combat/movement logic → [03-actions.md](03-actions.md) and
  [05-combat-and-damage.md](05-combat-and-damage.md)
- Understanding what's in a frame → [02-protocol.md](02-protocol.md#frames)
- Growing characters → [04-characters-and-stats.md](04-characters-and-stats.md)
- Copying working patterns → [10-example-bots.md](10-example-bots.md)
