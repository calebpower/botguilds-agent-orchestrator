"""Transport and run loop: connect to BotGuilds, play, reconnect, mirror.

The library owns everything that is *not* strategy: authentication, the ZeroMQ
DEALER socket, reconnect/backoff, the silence-timeout re-hello, and mirroring
frames/actions/errors into :mod:`steemer.storage`. A bot is just an object with
``on_frame`` (and optionally ``on_hello`` / ``on_action_error``).

Written fresh. The message shapes it speaks are the server's (see
:mod:`steemer.protocol` and ``docs/02-protocol.md``).

Zero-downtime handoff: a :class:`Client` does all of its setup in ``__init__``
(open the DB, warm the bot/strategy) and only sends ``hello`` in :meth:`run`.
Because a new ``hello`` supersedes the guild's previous session, a freshly
started, fully-initialized process takes over the instant it connects — the old
one exits on the ``kick``. So the supervisor can start the new version, let it
initialize, and the cutover costs roughly one handshake.
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Protocol

import zmq

from . import protocol as p
from .storage import Storage

# A connected bot gets a frame every tick (~0.25 s). A long silence means the
# server restarted under us: DEALER reconnects the TCP session without raising,
# and the new server has never seen our HELLO, so we must re-send it.
SILENCE_TIMEOUT = 10.0
_MAX_BACKOFF = 30.0
REFRESH_THROTTLE = 2.0   # v0.44.0: at most one full-frame refresh request per this many
#   seconds — a burst of dropped frames should trigger ONE resync, not a REFRESH storm.


class Bot(Protocol):
    """What the client needs from a bot. Only ``on_frame`` is required."""

    def on_frame(self, frame: dict[str, Any]) -> list[dict[str, Any]]: ...


def load_token(path: str) -> dict[str, Any]:
    """Read ``guild_token.json`` (``guild_id``, ``token``, ``server``)."""
    try:
        with open(path) as fh:
            data = json.load(fh)
    except FileNotFoundError as e:
        raise SystemExit(
            f"no {path} — register a guild on the server's /docs page and save "
            "the token file next to the bot."
        ) from e
    if "guild_id" not in data or "token" not in data:
        raise ValueError(f"{path} needs 'guild_id' and 'token'")
    return data


class _Transport:
    """A DEALER socket to the server's ROUTER; re-created on each (re)connect."""

    def __init__(self, server: str, creds: dict[str, Any]):
        self.server = server
        self.creds = creds
        self.socket: zmq.Socket | None = None

    def connect(self) -> None:
        self.close()
        sock = zmq.Context.instance().socket(zmq.DEALER)
        sock.setsockopt(zmq.LINGER, 0)
        sock.connect(self.server)
        self.socket = sock
        self.send(p.msg(p.HELLO, guild_id=self.creds["guild_id"],
                        token=self.creds["token"], client_version="steemer/0"))

    def poll(self, timeout_ms: int = 1000) -> dict[str, Any] | None:
        assert self.socket is not None
        if not self.socket.poll(timeout_ms):
            return None
        return p.decode(self.socket.recv())

    def send(self, message: dict[str, Any]) -> None:
        assert self.socket is not None
        self.socket.send(p.encode(message))

    def close(self) -> None:
        if self.socket is not None:
            self.socket.close(linger=0)
            self.socket = None


class Client:
    """Owns the run loop. Construct fully, then :meth:`run` to connect+play."""

    def __init__(
        self,
        bot: Bot,
        *,
        server: str | None = None,
        token_file: str = "guild_token.json",
        storage: Storage | None = None,
        verbose: bool = True,
    ):
        self.bot = bot
        self.creds = load_token(token_file)
        self.server = server or self.creds.get("server", "tcp://localhost:5570")
        self.storage = storage
        self.verbose = verbose
        self.transport = _Transport(self.server, self.creds)
        self.running = False
        self.connected = False
        self.tick = 0
        self.config: dict[str, Any] = {}
        self.guild: dict[str, Any] = {}
        self.dropped_sends = 0
        # v0.44.0 delta-frame handling: per-session seq to detect dropped frames, and
        # per-world tile caches to rebuild a delta frame's full visible tile set.
        self._last_seq: int | None = None
        self._refresh_at = 0.0
        self._tiles_mem: dict[Any, dict] = {}   # world -> {(x,y): tile row} ever seen
        self._visible: dict[Any, set] = {}      # world -> {(x,y)} currently in view
        # let the bot reach back for config/tick if it wants
        setattr(self.bot, "client", self)

    # -- logging helpers ------------------------------------------------------

    def _say(self, *a: Any) -> None:
        if self.verbose:
            print(*a, flush=True)

    def _mirror(self, method: str, *args: Any) -> None:
        if self.storage is None:
            return
        try:
            getattr(self.storage, method)(*args)
        except Exception as e:  # logging must never stop the bot playing
            self._say(f"storage {method} failed ({e}) — continuing")

    # -- connection -----------------------------------------------------------

    def _connect(self) -> None:
        self.connected = False
        backoff = 1.0
        while self.running:
            try:
                self.transport.connect()
                return
            except (zmq.ZMQError, OSError, ValueError) as e:
                self._say(f"connect failed ({e}) — retry in {backoff:.0f}s")
                time.sleep(backoff)
                backoff = min(_MAX_BACKOFF, backoff * 2)

    def send_actions(self, actions: list[dict[str, Any]]) -> None:
        clean: list[dict[str, Any]] = []
        for a in actions:
            if not a:
                continue
            reason = p.check_action(a)
            if reason is not None:
                self._say(f"dropping malformed action ({reason}): {a}")
                continue
            clean.append(a)
        if not clean:
            return
        try:
            self.transport.send(p.msg(p.ACTIONS, tick=self.tick, actions=clean))
        except (zmq.ZMQError, OSError) as e:
            # A hiccup on the way up costs one tick; the next frame is a tick
            # away and unsent actions cost nothing. The read path notices if the
            # connection is really gone.
            self.dropped_sends += 1
            self._say(f"send failed ({e}) — dropping this tick's actions")
            return
        self._mirror("record_actions", self.tick, clean)

    def _maybe_refresh(self, frame: dict[str, Any]) -> None:
        """v0.44.0: a jump in the per-session ``seq`` means frames were dropped, so
        the cumulative tile deltas we missed are gone — ask the server for full frames
        to resync. Throttled so a burst of drops triggers one REFRESH, not a storm. A
        failed send is ignored: the read path notices a genuinely dead connection."""
        seq = frame.get("seq")
        if p.is_seq_gap(self._last_seq, seq) and \
                time.monotonic() - self._refresh_at > REFRESH_THROTTLE:
            self._refresh_at = time.monotonic()
            try:
                self.transport.send(p.msg(p.REFRESH))
                self._say(f"seq gap ({self._last_seq}->{seq}) — requested full-frame refresh")
            except (zmq.ZMQError, OSError):
                pass
        if seq is not None:
            self._last_seq = seq

    # -- main loop ------------------------------------------------------------

    def run(self, max_ticks: int | None = None) -> None:
        self.running = True
        self._connect()
        try:
            self._loop(max_ticks)
        finally:
            self.close()

    def _loop(self, max_ticks: int | None) -> None:
        backoff = 1.0
        seen = 0
        last_seen = time.monotonic()
        while self.running:
            try:
                message = self.transport.poll(1000)
                if message is None:
                    if time.monotonic() - last_seen > SILENCE_TIMEOUT:
                        self._say(f"silent {SILENCE_TIMEOUT:.0f}s — re-hello")
                        self._connect()
                        last_seen = time.monotonic()
                    continue
                last_seen = time.monotonic()
            except (zmq.ZMQError, OSError):
                time.sleep(backoff)
                self._connect()
                last_seen = time.monotonic()
                continue

            mtype = message.get("type")
            if mtype == p.HELLO_OK:
                self.connected = True
                backoff = 1.0
                self.config = message.get("config", {})
                self.guild = message.get("guild", {})
                self.tick = message.get("tick", 0)
                # New server-side session: seq restarts from scratch and the first
                # frame per world is full, so forget the old seq/visible state (else
                # the seq restart looks like a giant gap and the stale visible set
                # would leak into the first delta frame's reassembly).
                self._last_seq = None
                self._visible = {}
                self._call(self.bot, "on_hello", message)
                self._say(f"connected as {self.guild.get('name')} at tick {self.tick}")
            elif mtype == p.HELLO_ERR:
                self._say(f"auth failed: {message.get('reason')}")
                self.running = False
            elif mtype == p.FRAME:
                self.tick = message.get("tick", self.tick)
                # v0.44.0: resync on a dropped-frame gap, then expand the delta tile
                # layer back to the full visible set BEFORE logging or acting, so the
                # stored frame and on_frame see the pre-delta shape.
                self._maybe_refresh(message)
                p.reassemble_tiles(message, self._tiles_mem, self._visible)
                self._mirror("record_frame", message)
                actions = self.bot.on_frame(message) or []
                self.send_actions(actions)
                seen += 1
                if max_ticks is not None and seen >= max_ticks:
                    self.running = False
            elif mtype == p.ACTION_ERR:
                self._mirror("record_error", message)
                self._call(self.bot, "on_action_error", message)
            elif mtype == p.KICK and message.get("reason") == "superseded":
                self._say("kicked: another session hello'd as this guild — exiting")
                self.running = False
            elif mtype in (p.SERVER_PAUSE, p.KICK):
                self._say(f"{mtype}: {message.get('reason')} — reconnecting")
                time.sleep(backoff)
                backoff = min(_MAX_BACKOFF, backoff * 2)
                self._connect()

    @staticmethod
    def _call(obj: Any, method: str, *args: Any) -> None:
        fn = getattr(obj, method, None)
        if callable(fn):
            fn(*args)

    def close(self) -> None:
        self.running = False
        try:
            self.transport.send(p.msg(p.BYE))
        except (zmq.ZMQError, OSError, AssertionError):
            pass
        self.transport.close()
        if self.storage is not None:
            self._mirror("flush")
