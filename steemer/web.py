"""Authenticated client for the BotGuilds web API — the read-only INTEL channel
that complements the ZeroMQ gameplay protocol, plus one cosmetic write.

The frames the bot receives over ZeroMQ only show OUR guild and whatever is in
our characters' vision. The web API (same host, HTTPS) exposes more:

* ``GET  /api/spectate/guilds`` — every guild's roster: our allies AND the rival
  guilds (names, per-char world + level + gear). Public, no auth.
* ``GET  /api/tiles``          — the world's tile/sprite vocabulary. Public.
* ``POST /api/guild/color``    — set our guild's map color. Needs auth.
* ``GET  /api/me``             — our own detailed village state. Needs auth.

Auth is a session cookie: ``POST /api/login {guild_id, token}`` (the same creds
as the ZeroMQ ``hello``) sets it. We hold the cookie and transparently re-login
on a 401, so a caller just makes requests. The HTTP transport is injectable so
the client is unit-testable without a network.
"""

from __future__ import annotations

import colorsys
import http.cookiejar
import json
import urllib.error
import urllib.request
from typing import Any, Callable
from urllib.parse import urlparse

TIMEOUT = 10.0

# A transport is ``(method, url, body: bytes|None, headers: dict) -> (status,
# headers, body: bytes)``. It must NOT raise on an HTTP error status — return it,
# so the client can act on 401.
Transport = Callable[[str, str, bytes | None, dict], tuple[int, dict, bytes]]


def http_base_from_server(server: str | None) -> str:
    """``tcp://host:port`` (the ZeroMQ server) -> ``https://host``; fall back to
    the known host."""
    host = None
    if server:
        try:
            host = urlparse(server).hostname
        except ValueError:
            host = None
    return f"https://{host}" if host else "https://bot.willmorrison.net"


def _urllib_transport(timeout: float = TIMEOUT) -> Transport:
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    def transport(method: str, url: str, body: bytes | None, headers: dict):
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with opener.open(req, timeout=timeout) as r:
                return r.getcode(), dict(r.headers), r.read()
        except urllib.error.HTTPError as e:           # 4xx/5xx: return, don't raise
            return e.code, dict(e.headers), e.read()
    return transport


def rainbow_hex(step: int, cycle_steps: int = 12,
                saturation: float = 1.0, value: float = 1.0) -> str:
    """A hex color that advances one hue slice per ``step``; a full spectrum every
    ``cycle_steps`` steps. ``rainbow_hex(0)`` is red; it walks red→…→violet→red."""
    h = (step % cycle_steps) / cycle_steps
    r, g, b = colorsys.hsv_to_rgb(h, saturation, value)
    return "#%02x%02x%02x" % (round(r * 255), round(g * 255), round(b * 255))


class WebClient:
    """Holds a login session and speaks JSON to the web API."""

    def __init__(self, guild_id: str, token: str, base: str, *,
                 transport: Transport | None = None) -> None:
        self.guild_id = guild_id
        self.token = token
        self.base = base.rstrip("/")
        self._transport = transport or _urllib_transport()
        self._authed = False

    def login(self) -> bool:
        body = json.dumps({"guild_id": self.guild_id, "token": self.token}).encode()
        status, _, _ = self._transport(
            "POST", self.base + "/api/login", body, {"content-type": "application/json"})
        self._authed = status == 200
        return self._authed

    def _request(self, method: str, path: str, data: Any = None,
                 _retry: bool = True) -> tuple[int, Any]:
        body = json.dumps(data).encode() if data is not None else None
        headers = {"content-type": "application/json"} if body is not None else {}
        status, resp_headers, raw = self._transport(method, self.base + path, body, headers)
        if status == 401 and _retry:                  # cookie missing/expired -> re-login once
            if self.login():
                return self._request(method, path, data, _retry=False)
        ctype = (resp_headers.get("Content-Type") or resp_headers.get("content-type") or "")
        parsed: Any = raw
        if raw and "json" in ctype.lower():
            try:
                parsed = json.loads(raw)
            except (ValueError, TypeError):
                parsed = raw
        return status, parsed

    def get_json(self, path: str) -> Any:
        """Parsed JSON body of a GET, or ``None`` on a non-200."""
        status, body = self._request("GET", path)
        return body if status == 200 else None

    def post_json(self, path: str, data: Any) -> int:
        """POST ``data`` as JSON; returns the HTTP status."""
        status, _ = self._request("POST", path, data)
        return status

    # -- convenience wrappers for the endpoints we use ------------------------

    def spectate_guilds(self) -> Any:
        return self.get_json("/api/spectate/guilds")

    def tiles(self) -> Any:
        return self.get_json("/api/tiles")

    def set_color(self, hex_color: str) -> int:
        return self.post_json("/api/guild/color", {"color": hex_color})
