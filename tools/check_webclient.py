# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Check whether the server's vendored web client (``app.js``) has changed.

    uv run tools/check_webclient.py           # report drift vs the vendored copy
    uv run tools/check_webclient.py --update   # re-fetch and overwrite the copy

The BotGuilds web UI at ``https://bot.willmorrison.net/web/app.js`` is the
richest public description of the server's HTTP/SSE surface — the endpoints it
calls (``/api/spectate/guilds``, ``/events/spectate``, ``/api/tiles``, ...) and
the event vocabulary it knows are things the wire protocol does not document.
We vendor a copy at ``reference_web/app.js`` and periodically re-diff it, exactly
as we do the reference starter kit: the server owner updates the client when the
API changes, and a diff is where a new useful endpoint first shows up. Never
imported or executed — reference only.

Stdlib only (PEP 723, no deps). Fetches from the network. Always exits 0; the
report is the point.
"""

from __future__ import annotations

import hashlib
import pathlib
import sys
import urllib.request

URL = "https://bot.willmorrison.net/web/app.js"
VENDORED = "reference_web/app.js"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    repo = pathlib.Path(__file__).resolve().parent.parent
    local = repo / VENDORED
    update = "--update" in sys.argv[1:]

    try:
        with urllib.request.urlopen(URL, timeout=30) as resp:
            remote = resp.read()
    except Exception as e:  # network/HTTP error — report, never crash the loop
        print(f"could not fetch {URL}: {e}")
        return 0

    remote_sha = _sha(remote)
    if not local.exists():
        print(f"no vendored copy at {VENDORED} (remote sha {remote_sha[:12]}).")
        if update:
            local.parent.mkdir(parents=True, exist_ok=True)
            local.write_bytes(remote)
            print(f"  wrote {VENDORED} ({len(remote)} bytes).")
        else:
            print("  run with --update to vendor it.")
        return 0

    local_sha = _sha(local.read_bytes())
    if local_sha == remote_sha:
        print(f"{VENDORED} is up to date (sha {local_sha[:12]}).")
        return 0

    print(f"{VENDORED} DRIFTED from upstream:")
    print(f"  local  {local_sha[:12]}")
    print(f"  remote {remote_sha[:12]}")
    if update:
        local.write_bytes(remote)
        print(f"  updated {VENDORED} ({len(remote)} bytes). "
              "Review `git diff` for new/changed endpoints, then deliberately "
              "wire any useful ones into the bot — log the decision.")
    else:
        print("  run with --update to refresh, then `git diff` for new endpoints "
              "and deliberately port anything useful (never a blind adoption).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
