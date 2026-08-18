"""Standalone entry point: play BotGuilds live, with no Claude in the loop.

    uv run python -m steemer.runner            # play forever, logging to guild_log.db
    uv run python -m steemer.runner --ticks 50 # bounded run (smoke tests)

Each invocation opens a *run window* in the ``runs`` table stamped with the git
sha and strategy version, so metrics attribute to exactly this release and the
window closes when the process exits (including a clean exit when a redeploy
supersedes it). That table is both the version timeline and the before/after
attribution the improvement loop uses.
"""

from __future__ import annotations

import argparse
import os
import subprocess

from . import db as _db
from .bot import GuildBot
from .client import Client
from .storage import Storage


def git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            text=True, stderr=subprocess.DEVNULL).strip() or "unknown"
    except Exception:
        return "unknown"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Play BotGuilds as Stanley_Steemer.")
    ap.add_argument("--db", default=None,
                    help="SQLite path override; else use --config/config.toml")
    ap.add_argument("--config", default=None, help="path to config.toml")
    ap.add_argument("--strategy", default="explorer")
    ap.add_argument("--server", default=None, help="override guild_token.json's server")
    ap.add_argument("--token", default=os.environ.get("GUILD_TOKEN_FILE", "guild_token.json"))
    ap.add_argument("--ticks", type=int, default=None, help="stop after N frames")
    ap.add_argument("--no-log", action="store_true")
    ap.add_argument("--note", default="", help="note recorded on this run window")
    args = ap.parse_args(argv)

    db_cfg = {"type": "sqlite", "path": args.db} if args.db \
        else _db.load_db_config(args.config)
    storage = None if args.no_log else Storage(db_cfg)
    bot = GuildBot(strategy=args.strategy, storage=storage)
    if storage is not None:
        storage.begin_run(git_sha(), bot.strategy.version, note=args.note)

    client = Client(bot, server=args.server, token_file=args.token, storage=storage)
    try:
        client.run(max_ticks=args.ticks)   # blocks; closes itself in its finally
    except KeyboardInterrupt:
        pass
    finally:
        if storage is not None:
            storage.end_run()
            storage.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
