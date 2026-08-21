"""Rival position/movement tracking via the game's public spectate stream.

The web UI's "track a player" feature hits ``GET /events/spectate?char=<uid>&map=<map>``,
a **public (no-auth) Server-Sent Events** stream. Each tick it pushes a full map view
centred on that character: ``{tick, world, view, bounds, tiles, entities, items, gold,
events}``. Crucially ``entities`` lists EVERY char/monster in view (with pos, eid,
guild_id, name, hp_frac, gear) and ``events`` lists the per-tick ``move`` events — so
watching one char on a map captures the positions and MOVEMENTS of every rival near it.
That is the raw material to reverse-engineer a rival guild's nav/combat algorithm.

Split for testability: the parsing/extraction is PURE (:func:`parse_sse_events`,
:func:`rival_entities`, :func:`moves_of`); :func:`consume` is the thin SSE network loop;
:func:`record_rivals` persists a compact per-tick rival snapshot into the ``intel`` table
(kind ``track``), so the existing retention + the rival-recon analysis read it like any
other intel.
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Iterable

from steemer import intel as _intel


def parse_sse_events(text: str) -> list[dict[str, Any]]:
    """Decode the ``data: {...}`` lines of an SSE blob into JSON objects (skipping
    keep-alives / malformed lines). PURE."""
    out: list[dict[str, Any]] = []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("data:"):
            body = line[5:].strip()
            if not body:
                continue
            try:
                out.append(json.loads(body))
            except json.JSONDecodeError:
                continue
    return out


def rival_entities(frame: dict[str, Any], our_prefix: str) -> list[dict[str, Any]]:
    """The RIVAL guild characters in a spectate frame — faction 'guild' chars whose
    guild_id is NOT ours — with position, identity and gear. PURE."""
    out = []
    for e in frame.get("entities") or []:
        if e.get("kind") != "char" or e.get("faction") != "guild":
            continue
        gid = str(e.get("guild_id") or "")
        if not gid or gid.startswith(our_prefix):
            continue
        out.append({"eid": e.get("eid"), "guild_id": gid, "name": e.get("name"),
                    "pos": e.get("pos"), "hp_frac": e.get("hp_frac"),
                    "held": e.get("held"), "outfit": e.get("outfit")})
    return out


def moves_of(frame: dict[str, Any]) -> list[dict[str, Any]]:
    """The per-tick MOVE events (``{eid, from, to}``) — the raw movement signal a nav
    algorithm reveals itself through. PURE."""
    return [{"eid": ev.get("eid"), "from": ev.get("from"), "to": ev.get("to")}
            for ev in (frame.get("events") or []) if ev.get("kind") == "move"]


def spectate_url(base: str, char: str, world: str) -> str:
    return f"{base.rstrip('/')}/events/spectate?char={char}&map={world}"


def consume(url: str, on_frame: Callable[[dict], None],
            should_stop: Callable[[], bool] = lambda: False,
            read_seconds: float | None = None) -> None:
    """Open the SSE stream and hand each decoded frame to ``on_frame`` until ``should_stop``
    or ``read_seconds`` elapses. Uses stdlib urllib (same as steemer.web — no extra dep);
    the response iterates as newline records, and each ``data:`` record is one tick."""
    import urllib.request
    started = time.monotonic()
    req = urllib.request.Request(url, headers={"Accept": "text/event-stream"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        for raw in resp:                      # file-like: yields one line at a time
            if should_stop() or (read_seconds is not None
                                 and time.monotonic() - started >= read_seconds):
                return
            line = raw.decode("utf-8", "replace") if isinstance(raw, (bytes, bytearray)) else raw
            for frame in parse_sse_events(line):
                on_frame(frame)


def rival_targets(roster: dict[str, Any], our_prefix: str) -> list[tuple[str, str]]:
    """From a ``/api/spectate/guilds`` roster, the ``(char_uid, world)`` of every RIVAL
    character currently on a FIELD map (not the village — movement worth tracking happens
    on maps). PURE. Centering a spectate stream on each guarantees we capture that rival."""
    out: list[tuple[str, str]] = []
    for g in roster.get("guilds") or []:
        gid = str(g.get("guild_id") or "")
        if not gid or gid.startswith(our_prefix):
            continue
        for c in g.get("roster") or []:
            uid, world = c.get("char_uid"), c.get("world")
            if uid and world and world != "village":
                out.append((uid, world))
    return out


def run_recorder(roster_fn: Callable[[], dict], base_url: str, conn, our_prefix: str,
                 should_stop: Callable[[], bool] = lambda: False,
                 per_char_seconds: float = 15.0, downsample: int = 4,
                 idle_sleep: float = 30.0, log: Callable[[str], None] = lambda m: None) -> None:
    """Continuously reverse-engineering feed: round-robin over fielded rival characters,
    tracking each for ``per_char_seconds`` and recording a rival snapshot every ``downsample``
    ticks (server ``tick`` is the join key, so it aligns with our own frames regardless of
    wall-clock). Refreshes the target list from the roster when the queue drains.

    RESILIENT to web-portal failures: every network call is wrapped, and CONSECUTIVE
    failures back off exponentially (3,6,12,24 -> capped at idle_sleep) so a down portal is
    retried patiently rather than hammered, then recover instantly on the first success.
    Never raises — the caller may also restart it, but it self-heals in place."""
    queue: list[tuple[str, str]] = []
    fails = 0
    while not should_stop():
        backoff = min(idle_sleep, 3.0 * (2 ** min(fails, 4)))     # 3,6,12,24,48 capped
        if not queue:
            try:
                queue = rival_targets(roster_fn() or {}, our_prefix)
                fails = 0                                          # portal answered
            except Exception as e:
                fails += 1
                log(f"track: roster error ({e}) — backing off {backoff:.0f}s")
                _sleep(backoff, should_stop)
                continue
            if not queue:
                log("track: no fielded rivals — idling")
                _sleep(idle_sleep, should_stop)
                continue
        char, world = queue.pop(0)
        state = {"n": 0, "rows": 0}

        def _on(frame: dict) -> None:
            state["n"] += 1
            if state["n"] % downsample == 0:
                state["rows"] += record_rivals(conn, world, frame, our_prefix)

        try:
            consume(spectate_url(base_url, char, world), _on, should_stop, per_char_seconds)
            fails = 0                                              # a clean stream = portal up
            if state["rows"]:
                log(f"track: {char}@{world} -> {state['rows']} rival-snapshots")
        except Exception as e:
            fails += 1
            queue = []                                             # re-derive targets after a blip
            log(f"track: stream error {char}@{world} ({e}) — backing off {backoff:.0f}s")
            _sleep(backoff, should_stop)


def _sleep(seconds: float, should_stop: Callable[[], bool]) -> None:
    end = time.monotonic() + seconds
    while time.monotonic() < end and not should_stop():
        time.sleep(min(1.0, end - time.monotonic()))


def record_rivals(conn, world: str, frame: dict[str, Any], our_prefix: str) -> int:
    """Persist a compact rival snapshot for one tick into ``intel`` (kind ``track``): the
    rival characters' positions + the tick's moves. Returns the rival count (0 = nothing to
    record, so a barren tick costs no row). Reuses the retained intel table."""
    rivals = rival_entities(frame, our_prefix)
    if not rivals:
        return 0
    _intel.record(conn, "track", frame.get("tick"), time.time(),
                  {"map": world, "tick": frame.get("tick"),
                   "rivals": rivals, "moves": moves_of(frame)})
    return len(rivals)
