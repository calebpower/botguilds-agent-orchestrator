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
| `decisions.log` | every improvement decision + rationale + expected/actual effect |
| `server_bugs.md` | game-server bugs to report to the server developer |
| `reference_starter_kit/` | upstream starter kit (git submodule) — **inspiration only, never imported** |

## Running it (without Claude)

Requires [`uv`](https://docs.astral.sh/uv/) and Python ≥ 3.15. All dependencies
are managed by uv; `uv run` keeps the environment in sync automatically.

```sh
uv sync                                   # set up the environment

# Play live (reads guild_token.json for server + credentials):
uv run python -m steemer.runner

# Keep it always-on (auto-restart; POSIX, no systemd needed):
./steemer/runner.sh

# Replay recorded history through the current decision engine:
uv run python -m steemer.replay --db guild_log.db --world vale

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

## License

Not yet determined. This project builds on the BotGuilds reference starter kit
(vendored as a submodule); its licensing is unresolved, so no license is
declared here for now.
