"""Authoritative roster via the server's public spectate HTTP endpoint.

The ZeroMQ village frame's guild snapshot (``chars_here`` + ``chars_by_world``)
is a lagged, PARTIAL view of a large persistent roster (see findings.jsonl — the
server shows characters intermittently), so gating recruit/embark on it
over-recruits (``roster_cap``) and over-embarks. The web dashboard's public
``GET /api/spectate/guilds`` endpoint returns the TRUE per-guild roster —
``characters`` (total) plus each roster entry's current ``world`` — which is
exactly the count the gates need.

We poll it on a background daemon thread (the roster changes slowly, so ~45 s is
ample) and expose the latest good value via a lock-guarded cache. The fetch is
best-effort with a short timeout: any failure keeps the last good value and lets
it age out; a caller that finds no fresh value falls back to the frame snapshot.
The game loop never blocks on the network. Attached to the bot only by the live
runner — tests and offline replay never touch the network.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request
from collections import Counter
from typing import Any, Callable
from urllib.parse import urlparse

DEFAULT_POLL_SECONDS = 45.0
FETCH_TIMEOUT = 5.0
STALE_MULTIPLE = 3        # data older than this × poll interval is "unavailable"
VILLAGE = "village"


def http_base_from_server(server: str | None) -> str:
    """Derive the dashboard HTTPS base from the ZeroMQ server URL
    (``tcp://host:port`` -> ``https://host``); fall back to the known host."""
    host = None
    if server:
        try:
            host = urlparse(server).hostname
        except ValueError:
            host = None
    return f"https://{host}" if host else "https://bot.willmorrison.net"


class SpectateRoster:
    """Polls ``/api/spectate/guilds`` in the background; exposes the latest
    authoritative ``(total, {field_world: n}, home)`` for our guild."""

    def __init__(self, guild_id: str, http_base: str | None = None, *,
                 server: str | None = None,
                 poll_seconds: float = DEFAULT_POLL_SECONDS,
                 opener: Callable[[str], Any] | None = None) -> None:
        self.guild_id = guild_id
        base = (http_base or http_base_from_server(server)).rstrip("/")
        self.url = f"{base}/api/spectate/guilds"
        self.poll_seconds = poll_seconds
        self._opener = opener or (
            lambda url: urllib.request.urlopen(url, timeout=FETCH_TIMEOUT))
        self._lock = threading.Lock()
        self._counts: tuple[int, dict[str, int], int] | None = None
        self._last_ok: float | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def fetch_once(self) -> bool:
        """Fetch + parse once and update the cache. True on success, False on any
        network/parse error or if our guild is absent (cache left untouched)."""
        try:
            with self._opener(self.url) as resp:
                data = json.loads(resp.read())
        except Exception:
            return False
        counts = self._parse(data)
        if counts is None:
            return False
        with self._lock:
            self._counts = counts
            self._last_ok = time.monotonic()
        return True

    def _parse(self, data: dict[str, Any]) -> tuple[int, dict[str, int], int] | None:
        for g in data.get("guilds", []) or []:
            if g.get("guild_id") != self.guild_id:
                continue
            roster = g.get("roster", []) or []
            by_world = Counter(c.get("world") for c in roster if c.get("world"))
            field = {w: n for w, n in by_world.items() if w != VILLAGE}
            fielded = sum(field.values())
            # `characters` is authoritative for the total; derive home as the
            # remainder so total stays consistent even if the roster list lags.
            total = g.get("characters")
            if not isinstance(total, int):
                total = sum(by_world.values())
            home = max(0, total - fielded)
            return total, field, home
        return None                          # our guild not in the response

    def counts(self) -> tuple[int, dict[str, int], int] | None:
        """Latest authoritative ``(total, {field_world: n}, home)``, or ``None`` if
        we have never fetched or the last good value is too stale to trust."""
        with self._lock:
            if self._counts is None or self._last_ok is None:
                return None
            if time.monotonic() - self._last_ok > self.poll_seconds * STALE_MULTIPLE:
                return None
            return self._counts

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="spectate-roster", daemon=True)
        self._thread.start()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.fetch_once()
            self._stop.wait(self.poll_seconds)

    def stop(self) -> None:
        self._stop.set()
