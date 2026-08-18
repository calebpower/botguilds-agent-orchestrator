# steemer

An autonomous bot and self-improvement harness for **BotGuilds**
(`bot.willmorrison.net`), playing the persistent world as guild
**Stanley_Steemer**.

A bot plays the game and logs verbose per-decision reasoning plus metrics; a
Claude Code loop reads those metrics, learns what the game rewards, improves the
bot, verifies the change in a `reaper` ephemeral-VM session, hot-redeploys with
(near) zero downtime, and repeats. The bot also runs standalone without Claude.

> **Secrets:** `guild_token.json` authenticates as the guild and is **never**
> committed — it is in `.gitignore`, mode `0600`, and a `.githooks/pre-commit`
> hook hard-blocks it (even against `git add -f`). Keep it that way.

## Layout

| Path | What |
|---|---|
| `steemer/` | the bot: client, protocol, decision engine, storage, metrics, runner, replay |
| `steemer/strategy/` | versioned, pluggable strategy modules |
| `ui/` | read-only web dashboard (verbose "thinking", KPIs, map, version timeline) |
| `tools/` | `analyze.py` (metrics snapshot for the improvement loop), `check_submodule.py` |
| `tests/` | unit + frame-replay suites (the pre-redeploy battery) |
| `orchestrator/` | the improvement-loop runbook |
| `docs/` | BotGuilds reference manual (game mechanics, protocol, client) |
| `Makefile` | portable shortcuts for every command below (`make help`) |
| `config.example.toml` | committed template for the git-ignored `config.toml` |
| `decisions.log` | every improvement decision + rationale + expected/actual effect |
| `server_bugs.md` | game-server bugs to report to the server developer |
| `reference_starter_kit/` | upstream starter kit (git submodule) — **inspiration only, never imported** |

## Configuration

Runtime configuration lives in `config.toml` at the repo root — the one place
that decides **where the guild's accumulated memory lives**. It is read by the
bot (writer), the dashboard (reader), and the analysis/retention tools, all via
`steemer.db.load_db_config()`.

The config is resolved in this order, first hit wins:

1. an explicit `--config <path>` flag,
2. the `STEEMER_CONFIG` environment variable,
3. `config.toml` at the repo root,
4. the built-in default — **SQLite at `./guild_log.db`**.

So a fresh checkout with **no `config.toml` runs immediately on SQLite, zero
setup**. Add a `config.toml` only when you want MariaDB (or a non-default
SQLite path):

```sh
cp config.example.toml config.toml    # or: make config
```

[`config.example.toml`](config.example.toml) is a committed template with
placeholder values; your real `config.toml` is the copy you edit.

> **Secret:** `config.toml` carries the MariaDB password (it authenticates as
> the guild's data store), so like `guild_token.json` it is **git-ignored and
> never committed** — only the placeholder `config.example.toml` is tracked.
> Create `config.toml` locally on each host.

### SQLite (default)

Nothing to do — omit `config.toml` and the bot uses `./guild_log.db`. To pin an
explicit path, write:

```toml
[database]
type = "sqlite"
path = "guild_log.db"
```

### MariaDB

For a shared/durable backend, create `config.toml` with the `mariadb` block:

```toml
[database]
type     = "mariadb"
host     = "127.0.0.1"
port     = 3306
user     = "botguilds"
password = "<your-db-password>"   # secret — this file is git-ignored
db_name  = "botguilds"
```

Provision the database and user once (adjust to taste):

```sh
sudo mariadb -e "CREATE DATABASE botguilds CHARACTER SET utf8mb4;
  CREATE USER 'botguilds'@'127.0.0.1' IDENTIFIED BY '<your-db-password>';
  GRANT ALL PRIVILEGES ON botguilds.* TO 'botguilds'@'127.0.0.1';
  FLUSH PRIVILEGES;"
```

The schema is created automatically by the bot on first connect. Every command
below (runner, dashboard, `tools/analyze.py`, replay, retention) then reads the
same `config.toml`, so they all share one backend with no extra flags. To point
a single command elsewhere without editing the file, use
`--config /path/to/other.toml` or `STEEMER_CONFIG=/path/to/other.toml`.

## Running it (without Claude)

Requires [`uv`](https://docs.astral.sh/uv/) and Python ≥ 3.15. All dependencies
are managed by uv; `uv run` keeps the environment in sync automatically.

> Every command below has a `make` shortcut (`make sync`, `make run`,
> `make test`, …). Run `make help` for the full list; the raw commands are
> shown here so it's clear what each shim does.

```sh
uv sync                                   # set up the environment

# Play live (reads guild_token.json for server + credentials):
uv run python -m steemer.runner

# Keep it always-on (auto-restart on crash; POSIX, no systemd needed):
./run-live.sh

# Hot-redeploy the running bot with ~zero downtime (after committing + reaper test):
./redeploy.sh --note "what changed"

# Replay recorded history through the current decision engine:
uv run python -m steemer.replay --db guild_log.db --world vale -v

# Web dashboard (LAN-accessible, read-only):
uv run python ui/server.py --host 0.0.0.0 --port 8800
```

## The improvement loop (with Claude)

`reaper` is the pre-redeploy gate: `reaper test` runs the battery in a
digest-pinned container. Fast tiers also run locally:

```sh
uv run pytest -q          # unit + frame-replay battery
reaper test               # same battery, pinned reproducible environment
```

The loop — analyze metrics → improve → verify (local, then reaper) →
commit/push → hot-redeploy → log — is documented in
[`orchestrator/loop.md`](orchestrator/loop.md).

### One-shotting a single iteration (both scripts)

The fully-autonomous loop self-paces with `ScheduleWakeup`. When you'd rather
drive **one** iteration by hand and supervise it, run the two split-phase
scripts. They read whatever backend `config.toml` selects, so no DB flags are
needed.

```sh
# 1. ANALYZE — "look, don't touch" (loop.md steps 1-4).
#    Computes the KPI snapshot from the configured backend, then a headless
#    Claude pass reads the docs + gameplan and writes the ranked path forward
#    to orchestrator/advice.md. Edits no strategy code; safe to re-run.
./analyze-iteration.sh

#    Review orchestrator/advice.md before applying.

# 2. APPLY — "build it" (loop.md steps 5-11).
#    Reads advice.md and launches a SUPERVISED (interactive) Claude session that
#    implements the change, bumps the strategy version, adds tests, verifies
#    (pytest → replay → reaper gate), commits, hot-redeploys, and logs.
#    Optionally pass one-off operator guidance that overrides advice.md:
./apply-iteration.sh
./apply-iteration.sh "prefer fixing the curdle action-error class first"
```

Each script does **exactly one pass and never re-arms** — neither schedules a
wakeup. `analyze-iteration.sh` runs headless (`claude -p`, `acceptEdits`) so it
only writes `advice.md`; `apply-iteration.sh` is interactive on purpose, since
it edits code, commits, and redeploys the live bot under your watch.

## License

Not yet determined. This project builds on the BotGuilds reference starter kit
(vendored as a submodule); its licensing is unresolved, so no license is
declared here for now.
