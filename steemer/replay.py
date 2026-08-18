"""Offline replay: run recorded frames back through the *current* decision engine.

    uv run python -m steemer.replay --db guild_log.db --world vale --limit 200
    uv run python -m steemer.replay --db guild_log.db --strategy explorer -v

No network and no game side effects — it reads history and shows what the current
strategy *would* do, which is how you eyeball a change against real past frames
or regression-check a new strategy version. Decisions are computed into an
in-memory DB so the verbose reasoning is available without touching your log.
"""

from __future__ import annotations

import argparse

from . import db as _db
from .bot import GuildBot
from .storage import Storage, read_frames


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--db", default=None,
                    help="SQLite history override; else use --config/config.toml")
    ap.add_argument("--config", default=None, help="path to config.toml")
    ap.add_argument("--world", default=None, help="only frames from this world")
    ap.add_argument("--limit", type=int, default=None, help="cap frames replayed")
    ap.add_argument("--strategy", default="explorer")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="print each decision's reasoning, not just the action")
    args = ap.parse_args(argv)

    src = {"type": "sqlite", "path": args.db} if args.db \
        else _db.load_db_config(args.config)
    mem = Storage(":memory:", commit_every=1)     # capture reasoning, touch no file
    bot = GuildBot(strategy=args.strategy, storage=mem)

    frames = replayed = 0
    for frame in read_frames(src, world=args.world, limit=args.limit):
        frames += 1
        # feed config through the first village/any frame if present
        bot.tick = frame.get("tick", bot.tick)
        actions = bot.on_frame(frame)
        replayed += 1
        summary = ", ".join(
            f"{a.get('char_uid','-')}:{a.get('action')}" for a in actions) or "(no actions)"
        print(f"tick {frame.get('tick')} {frame.get('world')}: {summary}")
        if args.verbose:
            rows = mem.conn.execute(
                "SELECT char_uid, reasoning FROM decisions WHERE tick=? ORDER BY seq",
                (frame.get("tick"),)).fetchall()
            for uid, reasoning in rows:
                head = f"  [{uid}] " if uid else "  "
                print(head + (reasoning or "").replace("\n", "\n    "))

    print(f"\nreplayed {replayed} frame(s) with strategy {bot.strategy.version}")
    mem.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
