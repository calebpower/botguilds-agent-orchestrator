"""The BotGuilds wire protocol: message types, action grammar, and validation.

Written fresh for this project. The *string constants* here (``"hello"``,
``"move"``, direction ``"N"`` …) are the on-the-wire interface the server
defines — they must match the server exactly or nothing connects — but the
structure, typing, and validation below are our own.

Transport is one JSON object per ZeroMQ message; see ``steemer.client``. The
game reference lives in ``docs/02-protocol.md`` and ``docs/03-actions.md``.
"""

from __future__ import annotations

import json
import zlib
from typing import Any

# --- message types ----------------------------------------------------------

# client -> server
HELLO = "hello"
ACTIONS = "actions"
BYE = "bye"
REFRESH = "refresh"     # ask the server for full (non-delta) frames after a detected gap

# server -> client
HELLO_OK = "hello_ok"
HELLO_ERR = "hello_err"
FRAME = "frame"
ACTION_ERR = "action_err"
SERVER_PAUSE = "server_pause"
KICK = "kick"

# --- movement ---------------------------------------------------------------

# Cardinal steps. y increases north; row 0 is the map's south (village) edge.
DIRS: dict[str, tuple[int, int]] = {
    "N": (0, 1),
    "S": (0, -1),
    "E": (1, 0),
    "W": (-1, 0),
}

# Diagonals exist in the protocol but are gear-gated; the server rejects them
# with ``no_diagonal_step`` unless a character's gear grants them.
DIAGONALS: dict[str, tuple[int, int]] = {
    "NE": (1, 1),
    "NW": (-1, 1),
    "SE": (1, -1),
    "SW": (-1, -1),
}

DIRS_ALL: dict[str, tuple[int, int]] = {**DIRS, **DIAGONALS}

# --- action grammar ---------------------------------------------------------
#
# action name -> tuple of argument keys the server requires. ``char_uid`` is
# handled separately (see GUILD_ACTIONS). Crafting verbs are legal both on a
# map and in the village.

_CRAFT_ARGS: dict[str, tuple[str, ...]] = {
    "taste": ("item_id",),
    "brew": ("item_ids",),
    "smelt": ("item_ids",),
    "forge": ("product", "item_ids"),
}

MAP_ACTIONS: dict[str, tuple[str, ...]] = {
    "move": ("dir",),
    "ride": ("dir",),
    "attack": ("target",),
    "charge": ("target",),
    "cast": ("spell",),          # essence/target/focus are optional
    "throw": ("item_id", "target"),
    "use": ("item_id",),         # optional target
    "pickup": (),                # optional item_id
    "drop": ("item_id",),
    "equip": ("slot",),          # optional item_id; bare slot unequips
    "open": ("target",),
    "spend_xp": ("stat",),
    "say": ("text",),
    **_CRAFT_ARGS,
}

VILLAGE_ACTIONS: dict[str, tuple[str, ...]] = {
    "buy": ("kind",),
    "sell": ("item_id",),
    "list": ("item_id", "price"),
    "unlist": ("listing_id",),
    "buy_listing": ("listing_id",),
    "recruit": (),               # optional name
    "rename": ("name",),
    "embark": ("map", "char_uids"),
    "use": ("item_id",),
    "drop": ("item_id",),
    "pickup": (),
    "equip": ("slot",),
    "spend_xp": ("stat",),
    **_CRAFT_ARGS,
}

ALL_ACTIONS: dict[str, tuple[str, ...]] = {**MAP_ACTIONS, **VILLAGE_ACTIONS}

# Guild-level actions carry no char_uid.
GUILD_ACTIONS: frozenset[str] = frozenset(
    {"recruit", "embark", "buy", "list", "unlist", "buy_listing"}
)

# Fields that must be strings when present.
_STRING_FIELDS: frozenset[str] = frozenset(
    {"map", "product", "listing_id", "kind", "slot", "stat", "spell"}
)


# --- (de)serialization ------------------------------------------------------


def msg(type_: str, **fields: Any) -> dict[str, Any]:
    """Build a message dict with its ``type`` set."""
    fields["type"] = type_
    return fields


def encode(message: dict[str, Any]) -> bytes:
    """Compact JSON bytes for the wire."""
    return json.dumps(message, separators=(",", ":")).encode("utf-8")


def decode(raw: bytes) -> dict[str, Any]:
    """Parse a wire message. The server may zlib-compress messages (frames in
    particular) — a zlib stream starts with 0x78 — so decompress those
    transparently and fall back to plain JSON for uncompressed messages. (Added
    when the server began compressing the ZeroMQ wire mid-run; without it every
    frame raised UnicodeDecodeError on json.loads and the bot crash-looped.)"""
    if raw[:1] == b"\x78":
        try:
            raw = zlib.decompress(raw)
        except zlib.error:
            pass                      # not actually zlib — try as plain JSON
    return json.loads(raw)


# --- delta frames (v0.44.0) -------------------------------------------------
#
# The server compresses the FRAME's terrain layer: a `delta` frame carries only
# the tiles that CHANGED plus a `gone` list of tile positions that left vision,
# rather than the whole visible tile set. (Entities, items and gold stay FULL in
# every frame — verified live on run #101: their counts hold frame-to-frame while
# `tiles`/`gone` churn.) Two consequences the client must handle:
#   * a jump in the per-session `seq` means frames were DROPPED, so the deltas we
#     missed are lost — ask for a full refresh to resync (is_seq_gap + REFRESH);
#   * a delta frame's `visible.tiles` is incomplete on its own — rebuild it to the
#     full currently-visible set so on_frame/logging/replay see the same shape they
#     did before the server switched to deltas (reassemble_tiles).


def is_seq_gap(last_seq: int | None, seq: int | None) -> bool:
    """True when `seq` skips past `last_seq` — i.e. one or more frames were dropped
    and their (cumulative) tile deltas are gone. A repeat or step-of-one is fine; a
    missing/None seq is treated as no gap (nothing to resync against)."""
    return last_seq is not None and seq is not None and seq > last_seq + 1


def reassemble_tiles(frame: dict[str, Any],
                     tiles_mem: dict[Any, dict[tuple[int, int], Any]],
                     visible: dict[Any, set[tuple[int, int]]]) -> None:
    """Expand a delta tile-frame IN PLACE so ``frame['visible']['tiles']`` is again
    the full currently-visible tile set (the pre-delta shape everything downstream
    was written against). Maintains two per-world caches passed in by the client:
    ``tiles_mem`` (world -> {(x,y): tile row} — every tile ever seen) and ``visible``
    (world -> {(x,y)} currently in view). Only the tile layer is delta-compressed;
    entities/items/gold are left untouched (they are full every frame). Never raises
    on a malformed frame — a garbled reassembly must not stop the bot playing."""
    try:
        vis = frame.get("visible")
        if not isinstance(vis, dict):
            return
        world = frame.get("world")
        mem = tiles_mem.setdefault(world, {})
        for t in vis.get("tiles") or ():
            mem[(t[0], t[1])] = t
        if frame.get("delta"):
            shown = visible.setdefault(world, set())
            shown.difference_update((g[0], g[1]) for g in vis.pop("gone", ()) or ())
            shown.update((t[0], t[1]) for t in vis.get("tiles") or ())
            vis["tiles"] = [mem[pos] for pos in sorted(shown) if pos in mem]
        else:
            # a full frame reseeds the currently-visible set for this world
            visible[world] = {(t[0], t[1]) for t in vis.get("tiles") or ()}
            vis.pop("gone", None)
    except (KeyError, TypeError, IndexError):
        return


# --- validation -------------------------------------------------------------


def is_guild_action(name: str) -> bool:
    return name in GUILD_ACTIONS


def check_action(action: Any) -> str | None:
    """Shape-check one action dict before we send it.

    Returns ``None`` if the shape is acceptable, else a short reason string in
    the same spirit as the server's ``action_err`` reasons. Game-rule checks
    (stamina, range, capability) are the server's job; this only catches
    malformed calls so we never spend a tick on one.
    """
    if not isinstance(action, dict):
        return "not_an_object"

    name = action.get("action")
    if name not in ALL_ACTIONS:
        return "unknown_action"

    if action.get("char_uid") is None and name not in GUILD_ACTIONS:
        return "missing_char_uid"
    if action.get("char_uid") is not None and not isinstance(action["char_uid"], str):
        return "bad_char_uid"

    required = ALL_ACTIONS[name]
    for key in required:
        if key not in action:
            return f"missing_{key}"

    if name == "move" and action["dir"] not in DIRS_ALL:
        return "bad_dir"
    if name == "ride" and action["dir"] not in DIRS:
        return "bad_dir"  # rails run straight — no diagonal riding

    if "target" in action:
        target = action["target"]
        if (
            not isinstance(target, (list, tuple))
            or len(target) != 2
            or not all(isinstance(v, int) for v in target)
        ):
            return "bad_target"

    for key in _STRING_FIELDS:
        if key in required and not isinstance(action.get(key), str):
            return f"bad_{key}"

    if "essence" in action and not isinstance(action["essence"], str):
        return "bad_essence"

    if name == "embark":
        uids = action.get("char_uids")
        if not isinstance(uids, list) or not all(isinstance(u, str) for u in uids):
            return "bad_char_uids"

    if "item_ids" in required and not isinstance(action.get("item_ids"), list):
        return "bad_item_ids"

    return None
