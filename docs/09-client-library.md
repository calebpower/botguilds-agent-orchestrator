# The client library (`botguilds`)

The starter kit's `botguilds` package handles every piece of infrastructure a
bot needs so that writing a bot reduces to implementing `on_frame`. Source:
`reference_starter_kit/botguilds/client.py` and
`reference_starter_kit/botguilds/protocol.py`.

## `GuildBot` — the class you subclass

```python
class GuildBot:
    def __init__(self):
        self.config = {}   # server config, filled in on hello_ok
        self.guild = {}    # guild snapshot, filled in on hello_ok
        self.tick = 0

    def on_hello(self, hello):
        """Called once per (re)connection."""

    def on_frame(self, frame):
        """Return a list of action dicts for this frame. Default: do nothing."""
        return []

    def on_action_error(self, message):
        """Called when the server rejects an action."""
```

Only `on_frame` is required. `on_hello` fires once per connection (including
reconnections) with the full `hello_ok` payload — use it to read server
config constants once. `on_action_error` fires per rejected action with
`{char_uid, action, reason, tick}` — `ranger_bot.py` uses this to *learn*
which equipment slot an item wants, rather than guessing (see
[10-example-bots.md](10-example-bots.md)).

`self.config` and `self.guild` are populated automatically by `GuildClient`
before `on_hello`/`on_frame` ever fire — read `self.config.get("party_cap",
5)` etc. rather than hardcoding server-tunable caps.

## `GuildClient` — the connection/run loop

```python
GuildClient(bot, server=None, token_file="guild_token.json",
            db="guild_log.db", log=True, verbose=True)
```

What it does, so you don't have to:

- **Loads and validates** `guild_token.json` (`load_token`) — raises a clear
  `SystemExit` if the file is missing, or a `ValueError` if it's missing
  `guild_id`/`token`.
- **Connects** over a ZeroMQ DEALER socket (`ZmqTransport`), sending `hello`
  immediately with your credentials and a `client_version`.
- **Reconnects with exponential backoff** (capped at 30s) on any connect
  failure, and **keeps retrying indefinitely** through a live server restart
  (`server_pause`) — this is deliberate: a restart is not a fatal error.
- **Detects silent disconnects**: if 10 seconds pass with no frame
  (`SILENCE_TIMEOUT`), it assumes the TCP session survived a server restart
  that the new process never saw a `hello` for, and proactively re-sends
  `hello`.
- **Handles `kick {reason: "superseded"}`** by shutting down cleanly — this
  fires when another session `hello`'d as the same guild, so you never
  accidentally run two bots against one guild fighting over actions.
- **Mirrors every frame, sent-action batch, and action_err to SQLite**
  (`LocalLog`, see below) without ever letting a logging failure block the
  bot from playing — a DB error just drops logging (`self.log = None`) and
  the bot keeps going.
- **Never blocks a network hiccup on send**: if sending actions fails, it
  drops that tick's actions (costs nothing — a missed tick already costs
  nothing) rather than retrying mid-loop and risking desync.
- **Sends `bye`** on clean shutdown (`Ctrl-C` via `run_bot`'s
  `KeyboardInterrupt` handling, or any call to `close()`).

You will rarely construct `GuildClient` directly — use `run_bot` instead.

## `run_bot` — the standard entry point

```python
from botguilds.client import GuildBot, run_bot

class MyBot(GuildBot):
    def on_frame(self, frame):
        ...

if __name__ == "__main__":
    raise SystemExit(run_bot(MyBot()))
```

This wires up `argparse` for you:

| flag | default | effect |
|---|---|---|
| `--server` | `guild_token.json`'s `server`, else `tcp://localhost:5570` | override the server address |
| `--token` | `guild_token.json` (or `$GUILD_TOKEN_FILE`) | run a different guild's credentials |
| `--db` | `guild_log.db` | separate the local SQLite log per run |
| `--no-log` | off | skip local logging entirely |
| `--ticks N` | unbounded | stop after N frames — useful for scripted test runs |

`run_bot` also catches `KeyboardInterrupt` and calls `client.close()` so
`Ctrl-C` always sends a polite `bye` and flushes the SQLite log rather than
leaving a dangling write transaction.

## The local database

`LocalLog` mirrors everything into a SQLite file (default `guild_log.db`,
WAL mode so a concurrent reader like `map_viewer.py` can coexist with your
bot's writes):

```sql
CREATE TABLE frames (
  seq INTEGER PRIMARY KEY, tick INTEGER, world TEXT, received_at REAL, json BLOB);
  -- json is zlib-compressed; a busy party is ~14 KB of raw frame per tick.
  -- Decode with botguilds.client.read_frames(), not raw SQL.
CREATE TABLE events (
  seq INTEGER PRIMARY KEY, tick INTEGER, world TEXT, kind TEXT, payload_json TEXT);
CREATE TABLE actions_sent (
  seq INTEGER PRIMARY KEY, tick INTEGER, char_uid TEXT, action TEXT, payload_json TEXT);
CREATE TABLE action_errors (
  seq INTEGER PRIMARY KEY, tick INTEGER, char_uid TEXT, action TEXT, reason TEXT);
CREATE TABLE tiles_seen (
  world TEXT, x INTEGER, y INTEGER, kind TEXT, sprite INTEGER, last_tick INTEGER,
  base INTEGER DEFAULT 0,   -- ground under a transparent sprite (web, chest, ...);
                            -- a JSON list when stacked (e.g. grass under a lilypad)
  PRIMARY KEY (world, x, y));
CREATE INDEX idx_events_tick ON events(tick);
```

Because the server offers no database export, **this local mirror is the
entirety of your guild's discovered knowledge** — map layout, drop tables,
craft outcomes and tells, everything. Treat it as durable state to carry
between bot iterations, not throwaway logging.

Useful queries (from the shipped README/AGENTS.md):

```sql
-- what kinds of events have I actually seen, and how often?
SELECT kind, COUNT(*) FROM events GROUP BY kind ORDER BY 2 DESC;

-- everything I've scouted in the Vale, minus plain floor/wall
SELECT x, y, kind FROM tiles_seen WHERE world='vale' AND kind NOT IN ('floor','wall');

-- why do my actions keep failing?
SELECT action, reason, COUNT(*) FROM action_errors GROUP BY 1, 2 ORDER BY 3 DESC;
```

### Reading frames back

`frames.json` is zlib-compressed JSON — don't decode it by hand:

```python
from botguilds.client import read_frames

for frame in read_frames("guild_log.db", world="vale", limit=10):
    print(frame["tick"], [c["pos"] for c in frame["chars"]])
```

`read_frames(db_path, world=None, limit=None)` returns frames oldest-first
(`ORDER BY seq`), optionally filtered to one world and/or capped.

## `botguilds.protocol`

The wire-level constants and pure functions, with no I/O:

- Message type strings: `HELLO`, `ACTIONS`, `BYE` (client→server);
  `HELLO_OK`, `HELLO_ERR`, `FRAME`, `ACTION_ERR`, `SERVER_PAUSE`, `KICK`
  (server→client).
- `DIRS` / `DIAGONALS` / `DIRS_ALL` — the direction-name-to-vector maps used
  by `move`/`ride`.
- `MAP_ACTIONS`, `VILLAGE_ACTIONS`, `ALL_ACTIONS`, `GUILD_ACTIONS` — which
  actions are legal where, and which need no `char_uid`. This is the
  authoritative list backing [03-actions.md](03-actions.md).
- `msg(type_, **fields)` — build a message dict.
- `encode(message)` / `decode(raw)` — compact JSON (de)serialization for the
  wire.
- `check_action(action)` — shape-validate one action dict client-side before
  sending; returns `None` if fine, else a reason string identical in spirit
  to what the server itself would return in `action_err`. Useful if you're
  building actions programmatically and want to fail fast without a round
  trip.

You will not usually call `protocol` functions directly — `GuildClient`
already does — but reading it is the fastest way to get the exact,
executable list of every action name and its required argument keys.
