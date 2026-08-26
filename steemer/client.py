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
import queue
import threading
import time
from typing import Any, Protocol

import zmq

from . import protocol as p
from .storage import Storage

# A connected bot gets a frame every tick (~0.25 s). A long silence means the
# server restarted under us: DEALER reconnects the TCP session without raising,
# and the new server has never seen our HELLO, so we must re-send it.
SILENCE_TIMEOUT = 10.0

# v0.115.1 SELF-HEAL (operator-directed after the 2026-08-26 outage): the server's
# per-session state degrades over a connection's lifetime — stale_frame rejections
# escalate (run 224: 0.27/frame -> 8.7/frame over ~10k ticks, 100% of moves refused,
# fielding collapsed to 1) and then unknown_character joins in; a fresh hello clears it
# INSTANTLY (proven twice: manual restarts on runs 224/225). So the client now cures
# itself: a sustained storm of session-poison reasons triggers one re-hello. Hysteresis
# (HEAL_MIN_SPACING) stops a flap if the server itself is the problem that day.
HEAL_REASONS = frozenset({"stale_frame", "unknown_character"})
HEAL_WINDOW = 600          # ticks — the anomaly watchdog's own spike window
HEAL_THRESHOLD = 60        # storm errors within HEAL_WINDOW -> re-hello (~0.1/frame,
                           # 3x the calm baseline, well under the 160+/window of a real
                           # storm's opening minutes)
HEAL_MIN_SPACING = 2400    # ticks between self-heals (~10 min) — one cure per storm
_MAX_BACKOFF = 30.0
# v0.51.0 — how many pending storage writes to hold before dropping the oldest. The queue
# exists so the RECEIVE loop never waits on the database; see _AsyncMirror.
MIRROR_QUEUE_MAX = 4000

REFRESH_THROTTLE = 2.0   # v0.44.0: at most one full-frame refresh request per this many
#   seconds — a burst of dropped frames should trigger ONE resync, not a REFRESH storm.


class _AsyncMirror:
    """Storage writes on a background thread, so the receive loop never blocks on the DB.

    WHY (measured on run #120, 2026-08-21): the receive loop used to zlib-compress the whole
    frame and run three INSERTs before it could read the next message. 34% of frames took
    longer than the ~83ms production budget (3 worlds x ~4 ticks/s), 12.3% exceeded 200ms,
    and the worst was 2,972ms. A ZeroMQ DEALER DROPS rather than blocks when its send queue
    fills, so our stalls cost 4.5% of the frame stream — 31 gaps averaging 131 frames — and
    the bot then issued commands for characters that had already moved on
    (`unknown_character` rose from 1.1 to 104 per 1k frames, the error rate from 13% to 43%).
    The give-away that it was us and not the server: across a gap the NEXT frame arrives in a
    median of 9ms. Nothing stalled; messages were discarded.

    Bounded, and DROPS THE OLDEST on overflow: losing a log row is always better than
    stalling the player. Drops are COUNTED and reported, because an unobservable loss is
    exactly how this went unnoticed for so long.

    One worker thread, so writes keep their order and the storage connection still has a
    single owner (the loop hands it over at start-up and never touches it again).
    """

    def __init__(self, storage: Any, say, maxsize: int = MIRROR_QUEUE_MAX):
        self._storage = storage
        self._say = say
        self._q: "queue.Queue[tuple[str, tuple] | None]" = queue.Queue(maxsize=maxsize)
        self.dropped = 0
        self.failed = 0
        self._thread = threading.Thread(target=self._run, name="storage-mirror", daemon=True)
        self._thread.start()

    def submit(self, method: str, *args: Any) -> None:
        try:
            self._q.put_nowait((method, args))
        except queue.Full:
            # Shed the OLDEST pending write, not the newest: recent frames are the ones an
            # analysis actually wants, and the alternative — blocking — is the bug.
            try:
                self._q.get_nowait()
                self.dropped += 1
            except queue.Empty:                       # pragma: no cover - race, harmless
                pass
            try:
                self._q.put_nowait((method, args))
            except queue.Full:                        # pragma: no cover - race, harmless
                self.dropped += 1

    def _run(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                return
            method, args = item
            try:
                getattr(self._storage, method)(*args)
            except Exception as e:      # logging must never stop the bot playing
                self.failed += 1
                if self.failed in (1, 10, 100) or self.failed % 1000 == 0:
                    self._say(f"storage {method} failed ({e}) — continuing "
                              f"[{self.failed} total]")

    def pending(self) -> int:
        return self._q.qsize()

    def close(self, timeout: float = 10.0) -> None:
        """Drain what is queued, then stop. Called on a clean exit only."""
        self._q.put(None)
        self._thread.join(timeout=timeout)


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
                        token=self.creds["token"],
                        client_version=f"steemer/{p.PROTO_VERSION}"))

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
        # v0.51.0: the async storage mirror. Created only by run(), so tests and replay --
        # which drive _loop/on_frame directly and want writes to have landed by the time
        # they assert -- keep the old synchronous behaviour.
        self._async_mirror: _AsyncMirror | None = None
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
        """Queue a storage write off the receive path (v0.51.0). Falls back to a direct
        call when there is no async mirror, which is the case in tests and replay."""
        if self.storage is None:
            return
        if self._async_mirror is not None:
            self._async_mirror.submit(method, *args)
            return
        try:
            getattr(self.storage, method)(*args)
        except Exception as e:  # logging must never stop the bot playing
            self._say(f"storage {method} failed ({e}) — continuing")

    # -- connection -----------------------------------------------------------

    def _drain_frames(self) -> list[dict[str, Any]]:
        """Pull every FRAME already sitting in the socket queue (non-blocking). A
        non-frame message ends the drain and is handled by the caller loop on its
        next poll — heals/kicks must not be skipped, only stale frames may be
        decision-skipped. Bounded so a pathological flood cannot spin forever."""
        out: list[dict[str, Any]] = []
        for _ in range(64):
            try:
                m = self.transport.poll(0)
            except (zmq.ZMQError, OSError):
                break
            if m is None:
                break
            if m.get("type") != p.FRAME:
                self._pending = m           # re-dispatched by _loop before polling
                break
            out.append(m)
        return out

    def _maybe_heal(self, reason: str, tick: int) -> bool:
        """One re-hello per sustained storm of session-poison errors. Pure decision
        (transport-free) so the storm/threshold/hysteresis logic is unit-testable the
        same way _maybe_refresh is; the caller does the actual reconnect on True."""
        if reason not in HEAL_REASONS:
            return False
        errs = self._heal_errs = [t for t in getattr(self, "_heal_errs", [])
                                  if tick - t < HEAL_WINDOW]
        errs.append(tick)
        if len(errs) < HEAL_THRESHOLD:
            return False
        last = getattr(self, "_heal_last", None)
        if last is not None and tick - last < HEAL_MIN_SPACING:
            return False
        self._heal_last = tick
        self._heal_errs = []
        return True

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
        # v0.51.1 DISABLED: _AsyncMirror moved storage writes to a worker thread, but the
        # MariaDB connection is also used from THIS thread by begin_run/end_run/flush, and
        # mysql-connector is not safe for that — the live bot crash-looped with
        # "bytearray index out of range" and wrote zero frames across runs #124-126.
        # The receive-loop REORDERING (decide+send, then record) is kept: it needs no
        # thread and removes the write from the action path. Re-enable only once the writer
        # owns its own connection.
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
                message = getattr(self, "_pending", None)
                self._pending = None
                if message is None:
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
                # v0.110.0 (wire v3 port): the server echoes its wire revision; a
                # mismatch is a LOUD line, not a guess — the 2026-08-25 grouped-
                # inventory change shipped breaking and silent.
                srv_proto = message.get("proto_version", 1)
                if srv_proto != p.PROTO_VERSION:
                    self._say(f"server speaks wire v{srv_proto}, this client speaks "
                              f"v{p.PROTO_VERSION} — port the delta before trusting frames")
            elif mtype == p.HELLO_ERR:
                self._say(f"auth failed: {message.get('reason')}")
                self.running = False
            elif mtype == p.FRAME:
                # v0.115.2 DECIDE-ON-FRESHEST: the 2026-08-26 stale_frame storms were
                # BACKLOG — we consumed ~10.9 frames/s against ~16 produced, the server-
                # side queue grew ~0.09s/s, every frame arrived already ticks old, and
                # every action tagged with its tick was dead on arrival (0 landed moves;
                # reconnects reset the queue, then it re-rotted — the [heal] loop). So:
                # drain everything already queued, INGEST every frame (seq/refresh, tile
                # reassembly and the mirror must see each one — cheap), but run the
                # EXPENSIVE stage (bot.on_frame -> actions) only on the newest frame per
                # world in the batch. Lag is now bounded at ~one frame no matter how slow
                # a decision pass is. Non-frame messages in the drain are re-dispatched
                # by _loop on the next poll (transport.poll(0) only returns FRAMEs past
                # the first — see _drain_frames).
                batch = [message] + self._drain_frames()
                newest: dict[str, dict] = {}
                for m in batch:
                    self.tick = m.get("tick", self.tick)
                    # v0.44.0: resync on a dropped-frame gap, then expand the delta tile
                    # layer to the full visible set BEFORE logging or acting.
                    self._maybe_refresh(m)
                    p.reassemble_tiles(m, self._tiles_mem, self._visible)
                    newest[m.get("world", "")] = m
                for m in newest.values():
                    # v0.51.0: decide and send before ANY storage write — the whole
                    # batch is mirrored only after the answers are on the wire.
                    actions = self.bot.on_frame(m) or []
                    self.send_actions(actions)
                for m in batch:
                    self._mirror("record_frame", m)
                seen += len(batch)
                if max_ticks is not None and seen >= max_ticks:
                    self.running = False
            elif mtype == p.ACTION_ERR:
                self._mirror("record_error", message)
                self._call(self.bot, "on_action_error", message)
                if self._maybe_heal(message.get("reason", ""), self.tick):
                    self._say("[heal] session-poison storm "
                              f"({message.get('reason')}) — re-hello to shed the "
                              "degraded server-side session")
                    self._connect()
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
        am, self._async_mirror = self._async_mirror, None
        if am is not None:
            pending = am.pending()
            am.close()
            if am.dropped or am.failed:
                self._say(f"storage mirror: {am.dropped} write(s) dropped under load, "
                          f"{am.failed} failed (queue held {pending} at close)")
