"""Web sidecar — a small always-on companion to the game bot.

It owns the HTTP-API side of the guild, which is orthogonal to gameplay (that
runs over ZeroMQ in ``steemer.runner``) and so lives in its own process that
survives strategy redeploys:

* **Rotates the guild's map color through the rainbow** every ``--color-seconds``
  (default 2 s) via ``POST /api/guild/color``.
* **Polls intel** the frames don't carry and persists it to the ``intel`` table
  for the analysis loop: the whole-world roster (``/api/spectate/guilds`` — our
  allies and the rival guilds) every ``--spectate-seconds``, and the world's tile
  vocabulary (``/api/tiles``) every ``--tiles-seconds``.

Run it in its own screen window alongside the bot and the dashboard:

    uv run python tools/web_sidecar.py

Best-effort throughout: a failed request is logged and retried next tick; auth is
re-established automatically on a 401. It never touches gameplay.
"""

from __future__ import annotations

import argparse
import sys
import time

# allow `uv run tools/web_sidecar.py` (script dir on path) to import the package
sys.path.insert(0, __import__("pathlib").Path(__file__).resolve().parent.parent.as_posix())

from steemer import db as _db          # noqa: E402
from steemer import intel as _intel    # noqa: E402
from steemer.client import load_token  # noqa: E402
from steemer.web import WebClient, http_base_from_server, rainbow_hex  # noqa: E402


def _say(*a) -> None:
    print("[sidecar]", *a, flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="BotGuilds web sidecar: rainbow color + intel polling.")
    ap.add_argument("--token", default="guild_token.json")
    ap.add_argument("--config", default=None, help="path to config.toml (DB backend)")
    ap.add_argument("--color-seconds", type=float, default=2.0)
    ap.add_argument("--spectate-seconds", type=float, default=30.0)
    ap.add_argument("--tiles-seconds", type=float, default=3600.0)
    ap.add_argument("--no-color", action="store_true", help="don't rotate the color")
    ap.add_argument("--once", action="store_true", help="one pass of every task, then exit (smoke test)")
    args = ap.parse_args(argv)

    creds = load_token(args.token)
    base = http_base_from_server(creds.get("server"))
    client = WebClient(creds["guild_id"], creds["token"], base)
    if client.login():
        _say(f"signed in to {base} as {creds['guild_id']}")
    else:
        _say(f"WARNING: sign-in to {base} failed; public intel still works, color/me will retry on 401")

    conn = _db.connect(_db.load_db_config(args.config))
    _db.apply_schema(conn)             # idempotent — ensures the intel table exists

    tick = 0
    last_spectate = last_tiles = -1e18

    def poll_spectate() -> None:
        data = client.spectate_guilds()
        if isinstance(data, dict) and data.get("guilds"):
            _intel.record(conn, "spectate", data.get("tick"), time.time(), data)
            n = len(data["guilds"])
            _say(f"intel: spectate recorded ({n} guild(s), tick {data.get('tick')})")
        else:
            _say("intel: spectate fetch returned no data")

    def poll_tiles() -> None:
        data = client.tiles()
        if isinstance(data, dict) and "count" in data:
            _intel.record(conn, "tiles", None, time.time(), data)
            cats = {k: len(v) for k, v in data.items() if isinstance(v, dict) and v}
            _say(f"intel: tiles recorded ({data.get('count')} sprites, categories {cats})")
        else:
            _say("intel: tiles fetch returned no data")

    def rotate_color() -> None:
        color = rainbow_hex(tick)
        status = client.set_color(color)
        if status != 200:
            _say(f"color set to {color} -> HTTP {status}")

    try:
        while True:
            now = time.monotonic()
            if not args.no_color:
                try:
                    rotate_color()
                except Exception as e:      # never let one bad request stop the loop
                    _say(f"color error: {e}")
            if now - last_spectate >= args.spectate_seconds:
                try:
                    poll_spectate()
                except Exception as e:
                    _say(f"spectate error: {e}")
                last_spectate = now
            if now - last_tiles >= args.tiles_seconds:
                try:
                    poll_tiles()
                except Exception as e:
                    _say(f"tiles error: {e}")
                last_tiles = now
            tick += 1
            if args.once:
                break
            time.sleep(args.color_seconds)
    except KeyboardInterrupt:
        _say("stopping")
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
