"""The authenticated web client (steemer/web.py): login-gated writes with
transparent re-login on 401, public reads without auth, and the rainbow color.
A fake transport stands in for the network."""

import json

from steemer.web import WebClient, http_base_from_server, rainbow_hex


class _FakeServer:
    """Simulates the web API: /api/login sets a session, guarded endpoints 401
    until then. Records calls so a test can assert a re-login happened."""
    JSON = {"content-type": "application/json"}

    def __init__(self, spectate=None, tiles=None):
        self.authed = False
        self.color = None
        self.calls = []
        self.spectate = spectate or {"guilds": [], "tick": 1}
        self.tiles = tiles or {"count": 1}

    def __call__(self, method, url, body, headers):
        self.calls.append((method, url.rsplit("/", 2)[-1] if "/api/" not in url else url.split("/api/")[-1]))
        if url.endswith("/api/login"):
            self.authed = True
            return 200, {}, b""
        if url.endswith("/api/spectate/guilds"):
            return 200, self.JSON, json.dumps(self.spectate).encode()
        if url.endswith("/api/tiles"):
            return 200, self.JSON, json.dumps(self.tiles).encode()
        if url.endswith("/api/guild/color"):
            if not self.authed:
                return 401, {}, b""
            self.color = json.loads(body)["color"]
            return 200, {}, b""
        return 404, {}, b""


def _client(server):
    return WebClient("g_me", "tok", "https://x", transport=server)


def test_public_read_needs_no_login():
    srv = _FakeServer(spectate={"guilds": [{"guild_id": "g_me"}], "tick": 7})
    c = _client(srv)
    data = c.spectate_guilds()
    assert data["tick"] == 7
    assert not any(name == "login" for _, name in srv.calls)   # never logged in


def test_color_write_relogs_in_on_401_then_succeeds():
    srv = _FakeServer()
    c = _client(srv)                       # starts unauthenticated
    status = c.set_color("#ff8800")
    assert status == 200
    assert srv.color == "#ff8800"
    # the first color POST 401'd, then a login, then a successful retry.
    assert srv.calls[0] == ("POST", "guild/color")
    assert srv.calls[1][0] == "POST" and srv.calls[1][1] == "login"
    assert srv.calls[2] == ("POST", "guild/color")


def test_get_json_returns_none_on_error_status():
    class Boom(_FakeServer):
        def __call__(self, *a):
            return 500, {}, b"nope"
    assert _client(Boom()).spectate_guilds() is None


def test_rainbow_walks_the_spectrum_and_wraps():
    assert rainbow_hex(0) == "#ff0000"                 # step 0 is red
    assert rainbow_hex(12) == rainbow_hex(0)           # full cycle wraps
    assert rainbow_hex(6) == "#00ffff"                 # halfway round is cyan
    # every step in a cycle is a distinct color
    assert len({rainbow_hex(i) for i in range(12)}) == 12


def test_http_base_derives_from_zeromq_server():
    assert http_base_from_server("tcp://bot.willmorrison.net:5570") == "https://bot.willmorrison.net"
    assert http_base_from_server(None) == "https://bot.willmorrison.net"
