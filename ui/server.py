#!/usr/bin/env python3
"""A read-only operator dashboard for the ``steemer`` BotGuilds bot.

The headline feature is the **decision feed**: the bot writes a verbose,
human-readable reasoning trace for every per-character decision (see
:mod:`steemer.reasoning`), and this dashboard surfaces those newest-first so an
operator can watch the bot "think".

Design constraints (deliberate):

* **Read-only.** Every DB connection is opened ``mode=ro`` so this coexists with
  the live writer under WAL. The dashboard never writes, and never reads the
  guild token.
* **Stdlib + steemer only.** No third-party packages, no external CDNs/fonts —
  the page is fully self-contained (inline CSS/JS). It reuses
  :func:`steemer.metrics.snapshot` for KPIs and :mod:`steemer.storage`'s schema
  rather than recomputing.
* **Robust to no data.** A missing or empty DB renders "no data yet" instead of
  crashing, so it can be launched before the bot has written anything.

Routes: ``/`` serves the single-page app; the ``/api/*`` routes return JSON (or
text, for the log viewers) that the page polls. Bind is LAN-accessible and
unauthenticated by design — the DB holds only read-only game data, no secret.

Run: ``uv run python ui/server.py [--host H] [--port P] [--db PATH]``
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
from collections import Counter
import os
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

# Import from the installed steemer package (works under `uv run`): the storage
# module owns the authoritative schema, metrics owns the KPI snapshot, findings
# owns the authored lab-notebook loader, and db owns the SQLite/MariaDB seam.
from steemer import db as _db
from steemer import findings, metrics
from steemer.strategy.explorer import role_of, select_wizards
from steemer.storage import DEFAULT_DB

# Repo root is the parent of this ui/ directory; the authored notebook and the
# log files the operator wants rendered all live there.
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The lab notebook lives at the repo root; load() already tolerates a missing or
# half-written file (returns [] / skips bad lines) so the tab degrades cleanly.
FINDINGS_PATH = os.path.join(REPO_ROOT, findings.FINDINGS_PATH)

# Files exposed by the log viewer, by short name. Restricted to this allow-list
# so the route can never be coerced into reading arbitrary paths.
LOG_FILES = {
    "decisions": os.path.join(REPO_ROOT, "decisions.log"),
    "bugs": os.path.join(REPO_ROOT, "server_bugs.md"),
}


# --------------------------------------------------------------------------- #
# Read-only DB access
# --------------------------------------------------------------------------- #

def _ro(db_cfg) -> _db.Connection:
    """Open the configured backend read-only (SQLite ``mode=ro`` / a fresh
    MariaDB connection) with row access by name.

    For SQLite, read-only is enforced at the driver level (``mode=ro``) so we
    coexist with the live writer under WAL and can never mutate the guild's
    memory. For MariaDB there is no per-connection read-only mode, so this
    coexists by only ever issuing SELECTs (a documented, code-enforced guarantee).
    """
    return _db.connect(db_cfg, readonly=True)


def _db_ready(db_cfg) -> bool:
    """True when the configured backend is reachable/openable.

    Everything downstream treats a False here as "no data yet" rather than an
    error, so the dashboard is useful before the bot has ever run.
    """
    return _db.db_ready(db_cfg)


# The filter-dropdown lists (distinct worlds / character uids) change only when a
# new world is entered or a new character is fielded — rare — but the query still
# touches large tables (SELECT DISTINCT world FROM frames is a full index scan).
# A short TTL keeps a tab-switch or reconnect storm from re-running them, without
# ever serving a stale-by-more-than-a-few-seconds list.
_LIST_TTL = 15.0
_list_lock = threading.Lock()
_list_cache: dict[str, tuple[float, list]] = {}
# The codex is a heavy decode (a bounded frame sample -> bestiary) that only changes
# meaningfully between runs, so cache it per run_id: compute once, serve instantly after,
# recompute when a new run starts (which is exactly "kept up to date after each run").
_codex_cache: dict = {"run": None, "data": None}
_codex_lock = threading.Lock()
_codex_inflight: set = set()   # run_ids whose codex is being built in a background thread


def _cached_list(key: str, fn) -> list:
    now = time.monotonic()
    with _list_lock:
        hit = _list_cache.get(key)
        if hit is not None and now - hit[0] < _LIST_TTL:
            return hit[1]
    val = fn()
    with _list_lock:
        _list_cache[key] = (now, val)
    return val


# The KPI snapshot is a heavy aggregate over a multi-GB mirror: dozens of
# full-scan COUNT(*)/GROUP BY queries that take tens of seconds on a large
# guild_log. Computing it on the HTTP request thread made /api/snapshot (and
# /api/observed, which reuses it) hang for the whole compute — and because a
# browser caps ~6 connections per host, those hung sockets starved every *other*
# endpoint too, so the whole dashboard appeared dead. Instead a dedicated
# background thread (see _snapshot_worker) recomputes it off the request path and
# publishes it here; request threads only ever read this cache and never block on
# a compute. The read is intentionally non-blocking: a cold cache returns
# "computing" rather than triggering an inline recompute.
_snap_lock = threading.Lock()
# ``version`` is a monotonic counter bumped on every successful publish; it is the
# cursor the live push channel (and the page) use to tell "has the snapshot been
# recomputed since I last saw it?" without comparing snapshot contents.
_snap_state: dict = {"snap": None, "computed_at": 0.0, "error": None, "version": 0}
# One full snapshot is a genuinely heavy aggregate over the multi-GB mirror
# (full COUNT(*)s on frames/decisions/events plus a per-run gold-delta blob read),
# minutes of wall time on a large guild_log. A KPI overview does not need
# sub-minute freshness, and recomputing tightly would keep the DB perpetually
# busy competing with the live writer — so the background worker recomputes at
# most this often, and only when the data has actually advanced (see below).
_SNAP_REFRESH = 300.0


def _publish_snapshot(db_cfg) -> None:
    """Compute the snapshot and publish it. Called only from the background
    worker thread — never from an HTTP request thread."""
    try:
        snap = metrics.snapshot(db_cfg)
    except _db.Error as exc:      # empty/partial DB or a transient hiccup
        with _snap_lock:
            _snap_state["error"] = str(exc)
        return
    with _snap_lock:
        _snap_state["snap"] = snap
        _snap_state["computed_at"] = time.monotonic()
        _snap_state["error"] = None
        _snap_state["version"] += 1


def _read_snapshot() -> tuple[dict | None, str | None]:
    """The latest published snapshot (or None) and the last compute error."""
    with _snap_lock:
        return _snap_state["snap"], _snap_state["error"]


def _snap_version() -> int:
    """The current publish counter — the cursor for snapshot/observed pushes."""
    with _snap_lock:
        return _snap_state["version"]


def api_snapshot(db_path: str) -> dict:
    """KPI overview — served from the background-published cache, never computed
    on the request thread. ``ok:false, reason:"computing"`` until the first
    background compute lands (a few tens of seconds after startup).

    ``version`` is the cursor the page hands back when subscribing to live
    pushes, so the socket only re-sends the snapshot when it has been recomputed.
    """
    if not _db_ready(db_path):
        return {"ok": False, "reason": "no_db"}
    snap, err = _read_snapshot()
    if snap is None:
        return {"ok": False, "reason": err or "computing"}
    out = dict(snap)
    out["ok"] = True
    out["version"] = _snap_version()
    return out


def api_worlds(db_path: str) -> list[str]:
    """Distinct worlds we have any record of (tiles or frames), for dropdowns."""
    if not _db_ready(db_path):
        return []

    def compute() -> list[str]:
        conn = _ro(db_path)
        try:
            worlds: set[str] = set()
            for table in ("tiles_seen", "frames", "decisions"):
                for (w,) in conn.execute(f"SELECT DISTINCT world FROM {table}"):
                    if w:
                        worlds.add(w)
            return sorted(worlds)
        except _db.Error:
            return []
        finally:
            conn.close()

    return _cached_list(f"worlds:{_db.cfg_key(db_path)}", compute)


def api_chars(db_path: str) -> list[str]:
    """Distinct character uids that appear in decisions, for the feed filter."""
    if not _db_ready(db_path):
        return []

    def compute() -> list[str]:
        conn = _ro(db_path)
        try:
            rows = conn.execute(
                "SELECT DISTINCT char_uid FROM decisions WHERE char_uid IS NOT NULL "
                "ORDER BY char_uid"
            ).fetchall()
            return [r[0] for r in rows]
        except _db.Error:
            return []
        finally:
            conn.close()

    return _cached_list(f"chars:{_db.cfg_key(db_path)}", compute)


def _decision_row(r) -> dict:
    """One decision feed row (shared by the REST feed and the live pusher)."""
    try:
        alts = json.loads(r["alternatives_json"]) if r["alternatives_json"] else []
    except (json.JSONDecodeError, TypeError):
        alts = []
    return {
        "seq": r["seq"], "tick": r["tick"], "world": r["world"],
        "char_uid": r["char_uid"], "action": r["action"],
        "reasoning": r["reasoning"] or "", "alternatives": alts,
        "strategy_version": r["strategy_version"], "run_id": r["run_id"],
    }


def _query_decisions(conn, char: str | None, world: str | None,
                     limit: int, since: int = 0) -> list[dict]:
    """Newest-first decision rows matching the filter, with ``seq > since``.

    ``since=0`` (the REST default) returns the latest ``limit``; the live pusher
    passes the client's cursor so it gets only rows written after that point —
    the race-free handoff between the initial REST pull and the push stream.
    """
    sql = ("SELECT seq, tick, world, char_uid, action, alternatives_json, "
           "reasoning, strategy_version, run_id FROM decisions WHERE seq > ?")
    params: list = [since]
    if char:
        sql += " AND char_uid = ?"
        params.append(char)
    if world:
        sql += " AND world = ?"
        params.append(world)
    # seq is monotonic with insert order, so DESC is "most recent first".
    sql += " ORDER BY seq DESC LIMIT ?"
    params.append(max(1, min(limit, 500)))
    return [_decision_row(r) for r in conn.execute(sql, params)]


def api_decisions(db_path: str, char: str | None, world: str | None,
                  limit: int) -> list[dict]:
    """The verbose decision feed, newest-first, optionally filtered.

    ``alternatives_json`` is parsed back into a list so the page can render the
    ranked candidates; ``reasoning`` is returned as-is (multi-line text) and the
    page preserves its line breaks. The page reads the newest row's ``seq`` as
    its live-push cursor, so no separate watermark field is needed here.
    """
    if not _db_ready(db_path):
        return []
    conn = _ro(db_path)
    try:
        return _query_decisions(conn, char, world, limit, since=0)
    except _db.Error:
        return []
    finally:
        conn.close()


def api_map(db_path: str, world: str | None) -> dict:
    """Everything to draw a world: accumulated tiles + the latest frame's
    entities/loot/gold/own-characters.

    Mirrors the "accumulate tiles, trust only the current frame for what's
    moving" split the bot's own pathing uses. Returns bounds so the page can size
    the grid; row 0 is drawn at the bottom (y increases north).
    """
    empty = {"world": world, "tiles": [], "bounds": None, "tick": None,
             "seq": 0, "entities": [], "items": [], "gold": [], "chars": []}
    if not _db_ready(db_path):
        return empty
    conn = _ro(db_path)
    try:
        if not world:  # default to whichever world has the most tiles seen
            row = conn.execute(
                "SELECT world, COUNT(*) n FROM tiles_seen GROUP BY world "
                "ORDER BY n DESC LIMIT 1").fetchone()
            world = row[0] if row else None
        if not world:
            return empty

        tiles = [[r["x"], r["y"], r["kind"]]
                 for r in conn.execute(
                     "SELECT x, y, kind FROM tiles_seen WHERE world = ?", (world,))]

        # Bounds from the tiles we've seen (+1 because coords are 0-based).
        max_x = max((t[0] for t in tiles), default=-1)
        max_y = max((t[1] for t in tiles), default=-1)

        out = dict(empty)
        out["world"] = world
        out["tiles"] = tiles

        # Overlay the latest frame for this world (moving things = current only).
        # ``seq`` (the frame's PK) is the page's live-push cursor for the map.
        frow = conn.execute(
            "SELECT seq, json FROM frames WHERE world = ? ORDER BY seq DESC LIMIT 1",
            (world,)).fetchone()
        if frow:
            out["seq"] = frow["seq"]
            ov = _frame_overlay(frow["json"])
            out.update(ov)
            # If the frame declares bounds, prefer them (whole-map extent).
            b = ov.get("frame_bounds")
            if isinstance(b, (list, tuple)) and len(b) == 2:
                max_x = max(max_x, b[0] - 1)
                max_y = max(max_y, b[1] - 1)
        out.pop("frame_bounds", None)

        out["bounds"] = [max_x + 1, max_y + 1] if max_x >= 0 and max_y >= 0 else None
        return out
    except (*_db.Error, zlib.error, json.JSONDecodeError, KeyError):
        return empty
    finally:
        conn.close()


def _frame_overlay(blob) -> dict:
    """The moving/point-in-time layer of one (compressed) frame: entities, loot,
    gold, our characters, the tick, and the frame's declared bounds. Shared by the
    full map endpoint and the live map pusher so both draw identical overlays."""
    frame = json.loads(zlib.decompress(blob))
    vis = frame.get("visible") or {}
    b = frame.get("bounds")
    return {
        "tick": frame.get("tick"),
        "entities": vis.get("entities") or [],
        "items": vis.get("items") or [],
        "gold": vis.get("gold") or [],
        "chars": [
            {"char_uid": c.get("char_uid"), "pos": c.get("pos"),
             "hp": c.get("hp"), "max_hp": c.get("max_hp")}
            for c in (frame.get("chars") or []) if c.get("pos")
        ],
        "frame_bounds": list(b) if isinstance(b, (list, tuple)) and len(b) == 2 else None,
    }


def api_heatmap(db_path: str, world: str | None, sample: int = 1200) -> dict:
    """Per-tile heatmap layers for a world, drawn as a Map overlay.

    Monster/gold/loot positions and our-character OCCUPANCY (time spent per tile) come from
    a BOUNDED sample of the most recent ``sample`` frames (a full-history decode would hang
    the request); deaths come from the ``events`` table (cheap, indexed by world).

    The key layer is **danger**, which corrects the SURVIVOR BIAS the operator flagged: we
    see more gold and take more deaths near the village simply because we're THERE more, so
    a raw death count reads a well-trodden safe tile as "deadly". ``danger`` normalises each
    tile's death share by its occupancy share — ``(deaths[t]/Σdeaths) / (occ[t]/Σocc)`` — a
    deaths-PER-TIME-THERE multiplier: >1 = deadlier than our presence predicts (genuinely
    dangerous), <1 = safer. Only defined where we have occupancy, so it can't be faked by a
    tile we never visit. Returns ``layers = {danger, death, occupancy, monster, gold, loot}``
    (each ``[x, y, value]``); death/occupancy/monster/gold/loot are raw counts, danger is the
    multiplier ×100 (int) so the client scales it like the others."""
    empty = {"world": world, "bounds": None, "frames_sampled": 0, "deaths": 0, "occ_total": 0,
             "layers": {"danger": [], "death": [], "occupancy": [],
                        "monster": [], "gold": [], "loot": []}}
    if not _db_ready(db_path):
        return empty
    conn = _ro(db_path)
    try:
        if not world:
            row = conn.execute("SELECT world, COUNT(*) n FROM tiles_seen GROUP BY world "
                               "ORDER BY n DESC LIMIT 1").fetchone()
            world = row[0] if row else None
        if not world:
            return empty
        b = conn.execute("SELECT MAX(x) mx, MAX(y) my FROM tiles_seen WHERE world = ?",
                         (world,)).fetchone()
        bounds = ([b["mx"] + 1, b["my"] + 1]
                  if b and b["mx"] is not None and b["my"] is not None else None)

        mon: Counter = Counter()
        gold: Counter = Counter()
        loot: Counter = Counter()
        occ: Counter = Counter()      # our-character time-in-tile (the survivor-bias baseline)
        rows = conn.execute("SELECT json FROM frames WHERE world = ? ORDER BY seq DESC LIMIT ?",
                            (world, sample)).fetchall()
        for r in rows:
            blob = r["json"]
            blob = blob.encode("latin-1") if isinstance(blob, str) else blob
            try:
                frame = json.loads(zlib.decompress(blob))
            except (zlib.error, json.JSONDecodeError):
                continue
            vis = frame.get("visible") or {}
            for e in vis.get("entities") or []:
                p = e.get("pos")
                if p and e.get("faction") == "monster":
                    mon[(p[0], p[1])] += 1
            for g in vis.get("gold") or []:
                p = g.get("pos")
                if p:
                    gold[(p[0], p[1])] += 1
            for it in vis.get("items") or []:
                p = it.get("pos")
                if p:
                    loot[(p[0], p[1])] += 1
            for c in frame.get("chars") or []:      # frame.chars are OUR guild's characters
                p = c.get("pos")
                if p:
                    occ[(p[0], p[1])] += 1

        death: Counter = Counter()
        for r in conn.execute("SELECT payload_json FROM events WHERE kind = 'death' AND world = ?",
                              (world,)).fetchall():
            p = r["payload_json"]
            p = json.loads(p) if isinstance(p, str) else p
            pos = p.get("pos")
            if pos:
                death[(pos[0], pos[1])] += 1

        # danger = deaths-per-time-there, survivor-bias corrected. Normalise both to shares so
        # the all-run deaths and the sampled occupancy are comparable, then divide. Defined
        # only where we have occupancy (elsewhere a per-visit rate is meaningless).
        occ_total = sum(occ.values())
        death_total = sum(death.values())
        danger: list = []
        if occ_total and death_total:
            for tile, d in death.items():
                o = occ.get(tile, 0)
                if o:
                    mult = (d / death_total) / (o / occ_total)
                    danger.append([tile[0], tile[1], round(mult * 100)])

        def flat(c: Counter) -> list:
            return [[x, y, n] for (x, y), n in c.items()]

        return {"world": world, "bounds": bounds, "frames_sampled": len(rows),
                "deaths": death_total, "occ_total": occ_total,
                "layers": {"danger": danger, "death": flat(death), "occupancy": flat(occ),
                           "monster": flat(mon), "gold": flat(gold), "loot": flat(loot)}}
    except (*_db.Error, zlib.error, json.JSONDecodeError, KeyError):
        return empty
    finally:
        conn.close()


def _item_type(kind: str) -> str:
    k = str(kind).lower()
    if k.startswith("potion"):
        return "potion"
    if any(w in k for w in ("tome", "scroll", "book")):
        return "tome"
    if any(w in k for w in ("club", "sword", "axe", "dagger", "spear", "bow", "staff",
                            "wand", "mace", "blade")):
        return "weapon"
    if any(w in k for w in ("outfit", "armor", "robe", "mail", "plate", "boots", "helm",
                            "cloak", "trinket", "ring", "amulet", "shield")):
        return "gear"
    if any(w in k for w in ("ore", "ingot", "gem", "herb", "essence", "vein", "hide", "bone")):
        return "material"
    if any(w in k for w in ("egg", "meat", "fish", "fruit", "bread")):
        return "food"
    return "misc"


def _codex_mechanics() -> dict:
    """The cheap (no-DB) codex section: game-rule docs + our confirmed learnings."""
    docs = []
    docs_dir = os.path.join(REPO_ROOT, "docs")
    try:
        for fn in sorted(os.listdir(docs_dir)):
            if not fn.endswith(".md"):
                continue
            title = fn[:-3].split("-", 1)[-1].replace("-", " ").title()
            summary = ""
            try:
                with open(os.path.join(docs_dir, fn), encoding="utf-8") as fh:
                    for line in fh:
                        s = line.strip().lstrip("# ").strip()
                        if s:
                            summary = s[:160]
                            break
            except OSError:
                pass
            docs.append({"doc": fn, "title": title, "summary": summary})
    except OSError:
        pass
    learnings = []
    try:
        for f in findings.load(FINDINGS_PATH):
            if f.get("kind") in ("discovery", "correction") and f.get("status") == "confirmed":
                learnings.append({"title": f.get("title"), "tags": f.get("tags") or []})
    except OSError:
        pass
    # newest first: the cap used to serve the OLDEST 40, so every fresh discovery fell
    # off the end — the codex looked maintained and showed nothing new (2026-08-23).
    return {"docs": docs, "learnings": list(reversed(learnings))[:40]}


def _codex_build(db_path: str, sample: int = 1200) -> dict:
    """The Codex: an auto-populated wiki of what we've learned, regenerated from current
    data every load. Four sections:
      * monsters  — the learned bestiary (behaviour/aggro/damage/class) over recent frames
      * lands     — per world: terrain vocabulary, size, mobs seen, total deaths
      * items     — item kinds seen (visible items + inventories) with an inferred type
      * mechanics — the game-rule docs (docs/*.md) + our confirmed discoveries (findings)
    Monsters/items share ONE bounded frame decode (positions/kinds live only in frame JSON)."""
    from steemer import bestiary as _best
    from steemer.strategy.explorer import WILDLIFE_SAFE, THREAT_KINDS
    out = {"monsters": [], "lands": [], "items": [], "mechanics": _codex_mechanics(),
           "frames_sampled": 0, "generated_run": None}
    if not _db_ready(db_path):
        return out
    conn = _ro(db_path)
    try:
        run = conn.execute("SELECT MAX(run_id) m FROM frames").fetchone()
        run_id = run["m"] if run else None
        out["generated_run"] = run_id

        # --- lands: cheap SQL over tiles_seen + events ---
        worlds = [r["world"] for r in conn.execute(
            "SELECT DISTINCT world FROM tiles_seen WHERE world <> 'village'").fetchall()]
        for w in worlds:
            terrain = [{"kind": r["kind"], "count": r["c"]} for r in conn.execute(
                "SELECT kind, COUNT(*) c FROM tiles_seen WHERE world = ? GROUP BY kind "
                "ORDER BY c DESC", (w,)).fetchall()]
            b = conn.execute("SELECT MAX(x) mx, MAX(y) my FROM tiles_seen WHERE world = ?",
                             (w,)).fetchone()
            deaths = conn.execute("SELECT COUNT(*) c FROM events WHERE world = ? AND kind='death'",
                                  (w,)).fetchone()["c"]
            out["lands"].append({
                "world": w,
                "size": [b["mx"] + 1, b["my"] + 1] if b and b["mx"] is not None else None,
                "terrain": terrain, "deaths": deaths, "mob_kinds": []})
        lands_by_world = {land["world"]: land for land in out["lands"]}

        # --- one bounded frame decode -> bestiary (monsters) + item kinds + per-world mobs ---
        normed = []
        items: Counter = Counter()
        world_mobs: dict = {}
        for r in conn.execute("SELECT json FROM frames WHERE world <> 'village' "
                              "ORDER BY seq DESC LIMIT ?", (sample,)).fetchall():
            blob = r["json"]
            blob = blob.encode("latin-1") if isinstance(blob, str) else blob
            try:
                frame = json.loads(zlib.decompress(blob))
            except (zlib.error, json.JSONDecodeError):
                continue
            normed.append(_best.normalize_frame(frame))
            w = frame.get("world")
            vis = frame.get("visible") or {}
            for it in vis.get("items") or []:
                if it.get("kind"):
                    items[it["kind"]] += 1
            for c in frame.get("chars") or []:
                for it in c.get("inventory") or []:
                    if it.get("kind"):
                        items[it["kind"]] += 1
            for e in vis.get("entities") or []:
                if e.get("faction") == "monster" and e.get("kind"):
                    world_mobs.setdefault(w, set()).add(e["kind"])
        out["frames_sampled"] = len(normed)
        for w, kinds in world_mobs.items():
            if w in lands_by_world:
                lands_by_world[w]["mob_kinds"] = sorted(kinds)

        def _mob_class(kind: str) -> str:
            if kind in THREAT_KINDS:
                return "undead"
            if kind in WILDLIFE_SAFE:
                return "benign"
            return "predator"

        bez = _best.build_bestiary(normed)
        monsters = []
        for kind, p in bez.items():
            monsters.append({"kind": kind, "class": _mob_class(kind), **p})
        monsters.sort(key=lambda m: m["sightings"], reverse=True)
        out["monsters"] = monsters

        out["items"] = sorted(
            [{"kind": k, "type": _item_type(k), "count": n} for k, n in items.items()],
            key=lambda i: (i["type"], -i["count"]))
        return out
    except (*_db.Error, zlib.error, json.JSONDecodeError, KeyError):
        return out
    finally:
        conn.close()


def _codex_latest_run(db_path: str):
    if not _db_ready(db_path):
        return None
    try:
        conn = _ro(db_path)
        try:
            r = conn.execute("SELECT MAX(run_id) m FROM frames").fetchone()
            return r["m"] if r else None
        finally:
            conn.close()
    except _db.Error:
        return None


# --------------------------------------------------------------------------- #
# "How navigation works" — the explainer, DERIVED rather than written down
# --------------------------------------------------------------------------- #
# The wishlist asked for this to stay true as the nav protocols change, so nothing
# here restates the algorithm in prose that could rot. Both halves are pulled from
# the source of truth at request time:
#
#   * the RULES come from steemer.nav itself — its live DIRS/SOLID values and the
#     docstrings of the functions the planner actually calls (inspect.getdoc). Edit
#     nav.py and this page changes with it; delete a function and it disappears.
#   * the PRIORITY LADDER comes from the bot's own recorded decision traces, not
#     from reading the strategy's literals. Every candidate the strategy `offer`s
#     lands in `decisions.alternatives_json` with its score, its reason and whether
#     it won — so the ladder shown is the one that actually ran, and a re-scored
#     branch shows up here without anyone editing the dashboard.
#
# The cost of that fidelity: the ladder can only show rungs the bot has REACHED in
# the sampled window. A branch that never fired is absent rather than listed at
# zero — which is itself worth seeing, so the sample size is reported alongside.

_NAV_RUNG_SPLIT = re.compile(r"\s+[—–-]\s+|[;:(]")
# character uids first: they are hex+digits, so blanking numbers alone would leave a
# different mangled uid per character and shatter one rung into dozens.
_NAV_UID = re.compile(r"g_[0-9a-f]+_c\d+")
_NAV_NUMS = re.compile(r"\d+(\.\d+)?%?")


def _nav_rung_label(why: str) -> str:
    """Collapse one candidate's reason to the branch it came from.

    Reasons carry specifics ("a wolf is 2 away", "selling meat (tier 1)"); the rung
    is the phrase before the first dash/colon/paren, with numbers blanked, so the
    same branch groups across characters and ticks.
    """
    head = _NAV_RUNG_SPLIT.split(why or "", 1)[0]
    head = _NAV_UID.sub("a char", head)
    return _NAV_NUMS.sub("#", head).strip().rstrip(",") or "(unlabelled)"


def api_recon(db_path: str, track_rows: int = 600) -> dict:
    """RIVAL RECON: us against every other guild, from the two intel feeds we already keep.

    `spectate` carries a full roster per guild (level, world, equipment) and `track` carries
    live rival positions with what each one is holding. Both were being written and only
    ever read back as raw rows; this is the comparison they were collected for.

    Deliberately CROSS-GUILD rather than rival-only: the interesting numbers are ratios, and
    a ratio needs both sides. The first look already paid for itself — we field the highest
    median level and the only fully-armed roster, while the guild with three times our
    headcount has a median of 3 and arms fewer than a third of it.

    Cheap by construction: the newest spectate snapshot is one row, and `track` is bounded
    to the newest `track_rows`. Measured on the live DB at 0.056s for a COUNT over 72k track
    rows and 0.009s for the newest 400 — this endpoint is not a codex-style table scan.
    """
    empty = {"guilds": [], "us": None, "gear_gap": [], "sightings": [], "tick": None}
    if not _db_ready(db_path):
        return empty
    conn = _ro(db_path)
    try:
        row = conn.execute(
            "SELECT payload_json FROM intel WHERE kind='spectate' "
            "ORDER BY seq DESC LIMIT 1").fetchone()
        snap = json.loads(row[0]) if row else {}
        # Which guild is OURS, derived rather than hardcoded: every decision we record
        # names one of our characters, and a char_uid is "<guild_id>_c<n>". Reading it from
        # the data keeps this correct if the guild is ever renamed or re-created, and needs
        # no access to the (git-ignored) token file.
        ours = None
        me = conn.execute(
            "SELECT char_uid FROM decisions ORDER BY seq DESC LIMIT 1").fetchone()
        if me and me[0]:
            parts = str(me[0]).split("_")
            if len(parts) >= 2:
                ours = "_".join(parts[:2])
        guilds = []
        our_kinds: set[str] = set()
        their_kinds: dict[str, int] = {}
        for g in snap.get("guilds") or []:
            roster = g.get("roster") or []
            levels = sorted(r.get("level") or 0 for r in roster)
            eq = [(r.get("equipment") or {}) for r in roster]
            kinds = [v for e in eq for v in e.values() if v]
            mine = g.get("guild_id") == ours
            if mine:
                our_kinds |= set(kinds)
            else:
                for k in kinds:
                    their_kinds[k] = their_kinds.get(k, 0) + 1
            guilds.append({
                "name": g.get("name"), "guild_id": g.get("guild_id"),
                "us": mine, "characters": g.get("characters"),
                "roster": len(roster),
                "level_median": levels[len(levels) // 2] if levels else None,
                "level_max": max(levels) if levels else None,
                "levels": levels,
                "armed": sum(1 for e in eq if e.get("hand")),
                "outfitted": sum(1 for e in eq if e.get("outfit")),
                "worlds": g.get("worlds") or {},
            })
        guilds.sort(key=lambda x: (not x["us"], -(x["level_median"] or 0)))
        # Gear a rival fields that no character of ours does — the concrete "what do they
        # know that we don't" list, which is the whole point of reconnaissance.
        gear_gap = sorted(({"kind": k, "rivals_fielding": n}
                           for k, n in their_kinds.items() if k not in our_kinds),
                          key=lambda x: -x["rivals_fielding"])
        rows = conn.execute(
            "SELECT payload_json FROM intel WHERE kind='track' "
            "ORDER BY seq DESC LIMIT ?", (track_rows,)).fetchall()
        # Where rivals actually are, by world and depth. Latest position per eid only:
        # the feed samples every tick, so counting rows would just weight whoever stood
        # still the longest.
        latest: dict[int, dict] = {}
        tick = None
        for (payload,) in rows:
            t = json.loads(payload)
            tick = tick or t.get("tick")
            for r in t.get("rivals") or []:
                if r.get("eid") not in latest:
                    latest[r["eid"]] = dict(r, map=t.get("map"))
        by_world: dict[str, dict] = {}
        for r in latest.values():
            w = by_world.setdefault(r.get("map") or "?",
                                    {"world": r.get("map"), "seen": 0, "depths": []})
            w["seen"] += 1
            pos = r.get("pos")
            if isinstance(pos, (list, tuple)) and len(pos) == 2:
                w["depths"].append(pos[1])
        sightings = []
        for w in by_world.values():
            d = sorted(w["depths"])
            sightings.append({"world": w["world"], "seen": w["seen"],
                              "depth_median": d[len(d) // 2] if d else None,
                              "depth_max": max(d) if d else None})
        sightings.sort(key=lambda x: -x["seen"])
        return {"guilds": guilds, "us": next((g for g in guilds if g["us"]), None),
                "gear_gap": gear_gap, "sightings": sightings, "tick": tick}
    except (_db.Error, ValueError):
        return empty
    finally:
        conn.close()


def api_nav(db_path: str, sample: int = 4000) -> dict:
    """The nav explainer: live nav rules + the ladder the bot actually weighed."""
    import inspect

    from steemer import nav as _nav

    rules = {
        "dirs": dict(_nav.DIRS),
        "solid": sorted(_nav.SOLID),
        "functions": [
            {"name": fn.__name__, "doc": inspect.getdoc(fn) or ""}
            for fn in (_nav.is_walkable, _nav.bfs_step, _nav.frontier,
                       _nav.step_dir, _nav.neighbors)
        ],
        "module_doc": inspect.getdoc(_nav) or "",
    }

    rungs: dict = {}
    considered = chosen_total = rows = 0
    version = None
    if _db_ready(db_path):
        conn = _ro(db_path)
        try:
            cur = conn.execute(
                "SELECT alternatives_json, strategy_version FROM decisions "
                "ORDER BY seq DESC LIMIT ?", (int(sample),))
            for row in cur.fetchall():
                alts_json = row["alternatives_json"] if hasattr(row, "keys") else row[0]
                version = version or (row["strategy_version"] if hasattr(row, "keys") else row[1])
                try:
                    alts = json.loads(alts_json) if alts_json else []
                except (TypeError, ValueError):
                    continue
                rows += 1
                for alt in alts:
                    score = alt.get("score")
                    if score is None:
                        continue
                    label = _nav_rung_label(alt.get("why", ""))
                    key = (round(float(score), 2), label)
                    r = rungs.setdefault(key, {"score": key[0], "label": label,
                                               "considered": 0, "chosen": 0,
                                               "example": alt.get("why", "")})
                    r["considered"] += 1
                    considered += 1
                    if alt.get("chosen"):
                        r["chosen"] += 1
                        chosen_total += 1
        except _db.Error:
            pass
        finally:
            conn.close()

    ladder = sorted(rungs.values(), key=lambda r: (-r["score"], -r["considered"]))
    for r in ladder:
        r["win_rate"] = round(r["chosen"] / r["considered"], 3) if r["considered"] else 0.0
    return {"rules": rules, "ladder": ladder, "strategy_version": version,
            "sampled_decisions": rows, "sampled_candidates": considered,
            "sampled_chosen": chosen_total}


# The frontier costs ~2-3s against the live DB (a DISTINCT over actions_sent plus a bounded
# scan), so it is cached per run exactly like the codex — the request thread must never own
# that cost. See the api_snapshot comment for why that rule exists.
_matrix_cache: dict = {"run": None, "data": None}


def api_matrix(db_path: str, min_prior: float = 0.5, limit: int = 20000) -> dict:
    """The exploration matrix for the Codex's Frontier pane.

    Returns the verb-coverage headline, the noun x verb grid, and the ranked frontier. The
    frontier is only useful while it is SMALL — six cells is a work queue, three hundred is
    another wall of data — so its size is reported prominently and the UI says so.
    """
    import json as _json
    import os as _os

    from steemer import matrix as _mx

    run_id = _codex_latest_run(db_path)
    if _matrix_cache["run"] == run_id and _matrix_cache["data"]:
        return _matrix_cache["data"]

    fixture = _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                            "tests", "fixtures", "vocabulary.json")
    try:
        with open(fixture) as fh:
            voc = _json.load(fh)
    except OSError:
        return {"ok": False, "reason": "no vocabulary fixture; run "
                                       "`python -m steemer.vocabulary`"}
    # No database is NOT an error here. The vocabulary fixture is committed, so the cube,
    # its priors and the never-sent verb list are all computable without any history —
    # only the TESTED layer needs the DB, and with no history everything is untried, which
    # is exactly right for a fresh checkout. Degrading to an error message would hide the
    # most useful view precisely when there is nothing else to look at.
    tested: dict = {}
    if _db_ready(db_path):
        conn = _ro(db_path)
        try:
            tested = _mx.tested_cells(conn, limit=limit)
        except _db.Error:
            tested = {}
        finally:
            conn.close()

    rep = _mx.build(voc, tested, min_prior=min_prior)
    out = {
        "ok": True,
        "verbs_all": voc.get("verbs_protocol", []),
        "verbs_sent": voc.get("verbs_sent", []),
        "verbs_never": rep["verbs_never_sent"],
        "cells_total": rep["cells_total"],
        "frontier": rep["frontier"],
        "frontier_size": rep["frontier_size"],
        "min_prior": min_prior,
        "say_words": rep["say_words"],
        "grid": _mx.grid(voc, tested, min_prior=min_prior),
    }
    _matrix_cache["run"], _matrix_cache["data"] = run_id, out
    return out


def api_codex(db_path: str) -> dict:
    """Serve the codex WITHOUT blocking the request thread. The heavy frame decode in
    _codex_build (~15s over MariaDB) runs at most once per run in a background thread;
    this returns the cached codex instantly, or a lightweight ``computing`` placeholder
    (with the cheap mechanics section already filled) while the first build for a run runs.
    The client re-fetches on ``computing``. Regenerating once per run IS "kept up to date
    after each run"."""
    run_id = _codex_latest_run(db_path)
    with _codex_lock:
        if _codex_cache["run"] == run_id and _codex_cache["data"]:
            return _codex_cache["data"]
        stale = _codex_cache["data"]
        launch = run_id is not None and run_id not in _codex_inflight
        if launch:
            _codex_inflight.add(run_id)
    if launch:
        threading.Thread(target=_codex_worker, args=(db_path, run_id), daemon=True).start()
    # while it builds, hand back the previous run's codex (flagged) or a mechanics-only stub
    if stale:
        return {**stale, "computing": True}
    return {"computing": True, "generated_run": run_id, "frames_sampled": 0,
            "monsters": [], "lands": [], "items": [], "mechanics": _codex_mechanics()}


def _codex_worker(db_path: str, run_id) -> None:
    try:
        data = _codex_build(db_path)
        data["generated_run"] = run_id
        with _codex_lock:
            _codex_cache["run"], _codex_cache["data"] = run_id, data
    except Exception:
        pass
    finally:
        with _codex_lock:
            _codex_inflight.discard(run_id)


def api_log(name: str) -> tuple[str, str, int]:
    """Return ``(kind, text, size)`` for a whitelisted log file.

    ``size`` is the number of file *bytes* the ``text`` represents (read as raw
    bytes, then decoded) — the page hands it back as the cursor, and the live tail
    pusher seeks from exactly that byte offset, so the append never mis-aligns even
    when the file contains invalid UTF-8. ``kind`` hints rendering."""
    path = LOG_FILES.get(name)
    if not path:
        return ("error", f"unknown log: {name}", 0)
    if not os.path.exists(path):
        return ("missing", f"{os.path.basename(path)} does not exist yet.", 0)
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
        kind = "md" if path.endswith(".md") else "text"
        return (kind, raw.decode("utf-8", "replace"), len(raw))
    except OSError as exc:
        return ("error", str(exc), 0)


def api_findings() -> list[dict]:
    """The authored lab notebook — reuse :func:`steemer.findings.load` verbatim.

    ``load`` already returns ``[]`` for a missing file and skips malformed lines,
    so a half-written notebook never takes the tab down. Sorting (newest-updated
    first) and filtering are left to the page so the raw notebook is served as-is.
    """
    try:
        return findings.load(FINDINGS_PATH)
    except OSError:
        return []


_VERSION_RE = re.compile(r"\b(\d+\.\d+\.\d+)\b")


def api_story() -> list[dict]:
    """Story mode: narrate the bot's evolution by strategy version. Groups the authored
    findings notebook by the ``explorer/X.Y.Z`` version each one is tagged with, so each
    version shows its shipped HYPOTHESIS (kind=consideration) and its MEASURED effect
    (kind=measurement / discovery / correction). Returns newest version first:
    ``[{version, entries:[{kind,status,title,updated}]}]``."""
    try:
        rows = findings.load(FINDINGS_PATH)
    except OSError:
        return []
    by_ver: dict[str, list] = {}
    for f in rows:
        vers = set()
        for t in (f.get("tags") or []):
            m = _VERSION_RE.search(str(t))
            if m:
                vers.add(m.group(1))
        if not vers:                       # fall back to a version named in the title
            m = _VERSION_RE.search(f.get("title") or "")
            if m:
                vers.add(m.group(1))
        for v in vers:
            by_ver.setdefault(v, []).append({
                "kind": f.get("kind"), "status": f.get("status"),
                "title": f.get("title"), "updated": f.get("updated")})

    def vkey(v: str):
        try:
            return tuple(int(x) for x in v.split("."))
        except ValueError:
            return (0,)

    return [{"version": v, "entries": by_ver[v]}
            for v in sorted(by_ver, key=vkey, reverse=True)]


TICK_JUMP_MIN = 50   # a tick gap wider than this is a counter LEAP (restart/catch-up),
                     # not frame loss — the clock cannot genuinely run 50+ ticks between
                     # two frames of a stream that delivers several frames per tick.


PHASE_OFFLINE_S = 15    # no frame this long -> OFFLINE (bot down or server down)

PHASES = ("offline", "bunker", "recall", "fielding", "mustering")


def resolve_phase(frame_age_s, health: str, fielded: int) -> str:
    """PURE: the guild's at-a-glance phase (operator wishlist, 2026-08-26).

    offline   — no frames flowing (bot down, or the server is)
    bunker    — server unhealthy (bot's health machine), roster safe at home
    recall    — server unhealthy and characters are still walking home
    fielding  — normal play, characters in the field
    mustering — normal play, everyone home between stints (rotating/resting)
    """
    if frame_age_s is None or frame_age_s > PHASE_OFFLINE_S:
        return "offline"
    if health == "bunker":
        return "recall" if fielded > 0 else "bunker"
    return "fielding" if fielded > 0 else "mustering"


def api_phase(db_path: str) -> dict:
    """The header chip's data: current phase + the inputs it derives from. Three
    cheap tail queries (seq-indexed), never the snapshot cache — the chip must be
    honest even while the cache computes."""
    if not _db_ready(db_path):
        return {"ok": True, "phase": "offline", "detail": "no db"}
    conn = _ro(db_path)
    try:
        row = conn.execute(
            "SELECT tick, received_at FROM frames ORDER BY seq DESC LIMIT 1"
        ).fetchone()
        age = (time.time() - row["received_at"]) if row and row["received_at"] else None
        # BOTH lookups must stay index-bound: `world`/`kind` are UNINDEXED on the
        # live MariaDB (the tickbar comment's 63-second lesson — the first draft of
        # this endpoint hung the dashboard on exactly that scan). Phase rows ride
        # idx_events_tick; the village frame comes from the seq tail in Python.
        mx = row["tick"] if row else 0
        ph = conn.execute(
            "SELECT world, payload_json FROM events WHERE tick > ? "
            "AND kind='bot_anomaly' AND world LIKE 'phase:%' "
            "ORDER BY seq DESC LIMIT 1", (mx - 200_000,)).fetchone()
        health = ph["world"].split(":", 1)[1] if ph else "ok"
        why = ""
        if ph:
            try:
                why = json.loads(ph["payload_json"]).get("why", "")
            except (ValueError, TypeError):
                pass
        vf = None
        for r in conn.execute(
                "SELECT world, json FROM frames ORDER BY seq DESC LIMIT 60"):
            if r["world"] == "village":
                vf = r
                break
        fielded = 0
        if vf:
            try:
                blob = vf["json"]
                if isinstance(blob, (bytes, bytearray)):
                    blob = zlib.decompress(blob)
                g = json.loads(blob).get("guild", {})
                fielded = sum(len(v) for v in (g.get("chars_by_world") or {}).values())
            except (zlib.error, json.JSONDecodeError, TypeError, KeyError):
                pass
        phase = resolve_phase(age, health, fielded)
        return {"ok": True, "phase": phase, "health": health, "fielded": fielded,
                "frame_age_s": None if age is None else round(age, 1), "why": why}
    except _db.Error:
        return {"ok": True, "phase": "offline", "detail": "db error"}
    finally:
        conn.close()


def api_tickbar(db_path: str, window: int = 500) -> dict:
    """Tick participation, block-explorer style (wishlist item, operator 2026-08-23):
    for the last ``window`` server ticks, which ones did we receive at least one frame
    for? A missing tick is a dropped frame (run #120 silently lost 3.7% of its stream)
    — and the RATE line makes a stalled server clock (2026-08-24: ~180 ticks/hour for
    an afternoon) visible at a glance instead of needing a DB session to diagnose.

    One seq-indexed tail query only. `received_at` is UNINDEXED on this table and a
    range scan measured 63 SECONDS on the live DB — the rate is therefore computed
    from the same tail rows in Python, never from a received_at WHERE clause."""
    if not _db_ready(db_path):
        return {"ok": False, "max_tick": None, "missing": [], "rate_per_min": None}
    conn = _ro(db_path)
    try:
        rows = conn.execute(
            "SELECT tick, received_at FROM frames ORDER BY seq DESC LIMIT 2000"
        ).fetchall()
        if not rows:
            return {"ok": True, "max_tick": None, "window": window,
                    "missing": [], "rate_per_min": None, "frames_seen": 0}
        ticks = [r["tick"] for r in rows if r["tick"] is not None]
        mx = max(ticks)
        lo = mx - window + 1
        present = {t for t in ticks if t >= lo}
        # v0.108.4: distinguish tick JUMPS from genuine drops. Between two
        # successively-observed ticks, a small gap means the clock ran and our
        # frames for those ticks never landed (a real drop, red); a gap wider
        # than TICK_JUMP_MIN means the counter LEAPT (run restart, server
        # catch-up burst) and the intermediate ticks never happened for us —
        # painting them red overstated loss 369/500 during the 08-24 stall.
        missing, jumped = [], []
        seen_sorted = sorted(present | {lo - 1})
        for a, b in zip(seen_sorted, seen_sorted[1:]):
            gap = range(max(a + 1, lo), b)
            (jumped if b - a > TICK_JUMP_MIN else missing).extend(gap)
        recvs = [r["received_at"] for r in rows if r["received_at"] is not None]
        rate = None
        if len(recvs) >= 2:
            wall = max(recvs) - min(recvs)
            span = mx - min(ticks)
            if wall > 1:
                rate = round(60.0 * span / wall, 1)
        return {"ok": True, "max_tick": mx, "window": window, "missing": missing,
                "jumped": jumped, "rate_per_min": rate, "frames_seen": len(rows)}
    except _db.Error:
        return {"ok": False, "max_tick": None, "missing": [], "rate_per_min": None}
    finally:
        conn.close()


def api_observed(db_path: str) -> dict:
    """Auto-derived "observed in play" signals from the read-only guild_log.db.

    Three cheap SQL/aggregate views that keep the Findings tab alive between the
    operator's authored updates: when each event kind was *first* seen, which
    action-error reasons occur (and how often), and how far exploration has
    pushed per world. Robust to an empty/missing DB.
    """
    empty = {"ok": False, "event_first_seen": [], "error_reasons": [],
             "exploration": {}}
    if not _db_ready(db_path):
        return empty
    conn = _ro(db_path)
    try:
        out = {"ok": True}
        # New game events surface here the first tick they ever appear.
        out["event_first_seen"] = [
            {"kind": r["kind"], "first_tick": r["first_tick"], "n": r["n"]}
            for r in conn.execute(
                "SELECT kind, MIN(tick) AS first_tick, COUNT(*) AS n "
                "FROM events GROUP BY kind ORDER BY first_tick")
        ]
        # Action-error reasons, most frequent first — a content-free health tell.
        out["error_reasons"] = [
            {"reason": ("" if r[0] is None else r[0]), "n": r[1]}
            for r in conn.execute(
                "SELECT reason, COUNT(*) FROM action_errors "
                "GROUP BY reason ORDER BY 2 DESC")
        ]
        # Exploration frontier: reuse the background-published snapshot's
        # exploration block (never compute one inline — that reintroduces the
        # request-thread hang this endpoint used to suffer).
        snap, _ = _read_snapshot()
        out["exploration"] = (snap or {}).get("exploration", {})
        # Observed drifts only with the snapshot recompute (exploration) and the
        # slow event/error aggregates; the page carries this back as its cursor so
        # the pusher re-sends it only when it changes, not every tick.
        out["version"] = _snap_version()
        return out
    except _db.Error:
        return empty
    finally:
        conn.close()


def _slot_kind(v):
    """A frame's equipment slot is an OBJECT ({item_id, kind, tier, uses, desc}) —
    always has been (reference AGENTS.md documents it), but the dashboard only started
    rendering non-null slots when the 0.92.x arming finally equipped chars, at which
    point esc(object) printed '[object Object]'. Reduce to the kind string here, the way
    inventory already is; tolerate a legacy bare-string slot and null."""
    if v is None:
        return None
    if isinstance(v, dict):
        return v.get("kind")
    return v


def api_roster(db_path: str) -> dict:
    """The full character roster with per-character detail, unioned from the latest
    frame of EACH world (a char is only ever in one world's frame at a time). For
    each char: live HP + stamina, stats + gifts, equipment slots, individual
    inventory, world + position, status effects, and its latest decision. Robust to
    an empty/missing DB (returns an empty roster, not an error)."""
    if not _db_ready(db_path):
        return {"ok": False, "chars": [], "count": 0}
    conn = _ro(db_path)
    try:
        # Union the latest frame of every world; keep each char's most recent sighting.
        best: dict[str, tuple[int, dict, str]] = {}
        for (world,) in conn.execute("SELECT DISTINCT world FROM frames"):
            row = conn.execute(
                "SELECT json, tick FROM frames WHERE world=? ORDER BY seq DESC LIMIT 1",
                (world,)).fetchone()
            if not row:
                continue
            try:
                frame = json.loads(zlib.decompress(row["json"]))
            except Exception:
                continue
            tick = row["tick"] or frame.get("tick") or 0
            for c in frame.get("chars", []) or []:
                uid = c.get("char_uid")
                if uid and (uid not in best or tick > best[uid][0]):
                    best[uid] = (tick, c, world)

        # v0.88.0: wizardhood is a chosen SEAT — the same pure ranking the bot runs,
        # applied to the same roster snapshot, so the panel and the strategy can never
        # disagree about who the wizards are.
        _seats = select_wizards([c for (_t, c, _w) in best.values()])
        # v0.96.0: the nuisance is a RUNTIME designation (who volunteered against Will),
        # not a pure function — the strategy records it to intel so the panel can show it.
        _nuisance_uid = None
        try:
            nrow = conn.execute("SELECT payload_json FROM intel WHERE kind='nuisance' "
                                "ORDER BY seq DESC LIMIT 1").fetchone()
            if nrow:
                _nuisance_uid = (json.loads(nrow["payload_json"]) or {}).get("uid")
        except _db.Error:
            _nuisance_uid = None
        chars = []
        for uid, (tick, c, world) in best.items():
            eq = c.get("equipment") or {}
            carry = c.get("carry") or {}
            dec = conn.execute(
                "SELECT action, reasoning FROM decisions WHERE char_uid=? "
                "ORDER BY seq DESC LIMIT 1", (uid,)).fetchone()
            latest = None
            if dec:
                # reasoning can be a full multi-line weighed-options trace; keep only
                # its last line (the "chose: …" summary / the single offer's why).
                why = (dec["reasoning"] or "").strip().splitlines()
                latest = why[-1].strip() if why else (dec["action"] or None)
            chars.append({
                "char_uid": uid, "name": c.get("name") or uid,
                "world": world, "pos": c.get("pos"),
                "hp": c.get("hp"), "max_hp": c.get("max_hp"),
                "stamina": c.get("stamina"), "max_stamina": c.get("max_stamina"),
                "level": c.get("level"), "xp": c.get("xp"),
                "role": role_of(c, _seats, _nuisance_uid),   # v0.88.0 seat-aware; v0.96.0 nuisance overlay
                "stats": c.get("stats") or {}, "gifts": list(c.get("gifts") or []),
                "equipment": {k: _slot_kind(eq.get(k)) for k in
                              ("hand", "offhand", "outfit", "trinket", "boots")},
                "inventory": [it.get("kind") for it in (c.get("inventory") or [])
                              if it.get("kind")],
                "carry": {"used": carry.get("used"), "cap": carry.get("cap")},
                "status": [s.get("kind") for s in (c.get("status") or [])
                           if isinstance(s, dict) and s.get("kind")],
                "latest_decision": latest, "at_tick": tick,
            })
        chars.sort(key=lambda x: (x["world"] or "", (x["name"] or "").lower()))
        return {"ok": True, "chars": chars, "count": len(chars)}
    except _db.Error:
        return {"ok": False, "chars": [], "count": 0}
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# WebSocket push (hand-rolled RFC6455, stdlib only)
#
# The socket carries the *data*, not a nudge. Each client subscribes to the view
# it is showing (tab + filters) with a cursor — the seq/version watermark it
# already has from its initial REST load. Once a second a single push thread asks
# each subscription's delta builder "what is new past this cursor?" and sends
# exactly that (new decision rows, the moving map overlay + freshly-seen tiles, a
# recomputed snapshot, an appended log tail) — then advances the cursor. REST is
# used only for the first paint of a view and as the no-socket fallback; nothing
# else pulls. The framing is hand-rolled to keep the dashboard stdlib-only.
#
# Race-freedom: the REST pull and the deltas share one monotonic seq per source,
# so subscribing with "the max seq I just loaded" means the push resumes exactly
# where REST left off — no gap, no duplicate — given the single sequential writer
# (the bot) that the whole mirror already assumes.
# --------------------------------------------------------------------------- #

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"   # RFC6455 magic
_ws_clients: set["WSClient"] = set()
_ws_lock = threading.Lock()


def _ws_accept_key(key: str) -> str:
    """The Sec-WebSocket-Accept value for a client's Sec-WebSocket-Key."""
    return base64.b64encode(
        hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()).decode("ascii")


def _ws_encode(payload: bytes, opcode: int = 0x1) -> bytes:
    """Frame a server->client message (FIN=1, unmasked — servers never mask).
    Notifications are tiny, so only the <126 and 16-bit length forms are needed."""
    b1 = 0x80 | opcode
    n = len(payload)
    if n < 126:
        header = bytes([b1, n])
    elif n < 65536:
        header = bytes([b1, 126]) + n.to_bytes(2, "big")
    else:
        header = bytes([b1, 127]) + n.to_bytes(8, "big")
    return header + payload


def _ws_read_frame(rfile):
    """Read one client->server frame. Returns (opcode, data) or None at EOF.
    Client frames are always masked (RFC6455); we unmask before returning."""
    hdr = rfile.read(2)
    if len(hdr) < 2:
        return None
    b1, b2 = hdr[0], hdr[1]
    opcode = b1 & 0x0F
    masked = b2 & 0x80
    length = b2 & 0x7F
    if length == 126:
        ext = rfile.read(2)
        if len(ext) < 2:
            return None
        length = int.from_bytes(ext, "big")
    elif length == 127:
        ext = rfile.read(8)
        if len(ext) < 8:
            return None
        length = int.from_bytes(ext, "big")
    mask = rfile.read(4) if masked else b""
    data = rfile.read(length) if length else b""
    if len(data) < length:
        return None
    if masked:
        data = bytes(data[i] ^ mask[i % 4] for i in range(len(data)))
    return opcode, data


class WSClient:
    """A connected dashboard socket. Writes are serialized by a per-client lock so
    the push-thread send and a handler-thread pong never interleave.

    Each client also carries a *subscription* — the view it is currently showing
    (``tab``, filter ``params``) and a ``cursor`` (the seq/version watermark it has
    already received). The handler thread updates it from the client's ``sub``
    frames; the push thread reads it to decide what new data to send. A separate
    lock guards it so the two threads never tear the dict."""

    def __init__(self, sock):
        self._sock = sock
        self._wlock = threading.Lock()
        self._slock = threading.Lock()
        self.alive = True
        self.sub: dict | None = None

    def set_sub(self, tab, params, cursor) -> None:
        with self._slock:
            self.sub = {"tab": tab, "params": params or {}, "cursor": cursor}

    def get_sub(self) -> dict | None:
        with self._slock:
            return dict(self.sub) if self.sub is not None else None

    def advance_cursor(self, tab, params, cursor) -> None:
        """Record what the client now has, so the next tick sends only newer data.
        Only applies if the client is still on the same view we pushed for — if it
        re-subscribed (switched tab / changed filter) meanwhile, its fresh cursor
        wins and this is a no-op, so a view change can't be clobbered by a stale
        advance."""
        with self._slock:
            if (self.sub is not None and self.sub["tab"] == tab
                    and self.sub["params"] == params):
                self.sub["cursor"] = cursor

    def send(self, text: str) -> bool:
        """Send a text frame; returns False (and marks dead) if the peer is gone."""
        frame = _ws_encode(text.encode("utf-8"))
        with self._wlock:
            if not self.alive:
                return False
            try:
                self._sock.sendall(frame)
                return True
            except OSError:
                self.alive = False
                return False

    def pong(self, payload: bytes) -> None:
        with self._wlock:
            if not self.alive:
                return
            try:
                self._sock.sendall(_ws_encode(payload, opcode=0xA))
            except OSError:
                self.alive = False


def _apply_sub(client: "WSClient", data: bytes) -> None:
    """Record a client's ``sub`` frame (which view + cursor it wants updates for).
    Malformed frames are ignored so a stray message can't drop the socket."""
    try:
        msg = json.loads(data.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return
    if isinstance(msg, dict) and msg.get("t") == "sub":
        client.set_sub(msg.get("tab"), msg.get("params"), msg.get("cursor"))


# --------------------------------------------------------------------------- #
# Per-view delta builders. Each takes the subscription's ``params`` and
# ``cursor`` (the watermark the client already has) and returns either
# ``(message, new_cursor)`` — the actual data to push and the advanced cursor —
# or ``None`` when nothing has changed. They are the push counterpart of the REST
# endpoints and deliberately return the *data*, never a "go fetch" nudge.
#
# The cursor handoff is race-free because the REST load and these deltas both key
# off the same monotonic ``seq``: the page subscribes with the max seq its REST
# pull returned, and each builder returns strictly-greater rows. This relies on a
# single, sequential writer (the bot) so committed seqs never appear out of order
# — the same assumption the KPI worker's MAX(seq) change-detection already makes.
# --------------------------------------------------------------------------- #

def _delta_decisions(conn, params: dict, cursor) -> tuple[dict, dict] | None:
    since = int((cursor or {}).get("seq") or 0)
    rows = _query_decisions(conn, params.get("char") or None,
                            params.get("world") or None,
                            int(params.get("limit") or 100), since=since)
    if not rows:
        return None
    # rows are newest-first, so rows[0] carries the new high-water seq.
    return {"t": "decisions", "rows": rows}, {"seq": rows[0]["seq"]}


def _delta_map(conn, params: dict, cursor) -> tuple[dict, dict] | None:
    world = params.get("world") or None
    if not world:
        return None                      # the page always names its map world
    cur = cursor or {}
    frame_seq = int(cur.get("seq") or 0)
    tile_tick = -1 if cur.get("tick") is None else int(cur.get("tick"))
    frow = conn.execute(
        "SELECT seq, json FROM frames WHERE world=? ORDER BY seq DESC LIMIT 1",
        (world,)).fetchone()
    new_seq = frow["seq"] if frow else frame_seq
    # Tiles first seen / refreshed since the client's tile watermark (small table).
    tiles = [[r["x"], r["y"], r["kind"]] for r in conn.execute(
        "SELECT x, y, kind FROM tiles_seen WHERE world=? AND last_tick > ?",
        (world, tile_tick))]
    mt = conn.execute("SELECT MAX(last_tick) FROM tiles_seen WHERE world=?",
                      (world,)).fetchone()
    tile_wm = mt[0] if mt and mt[0] is not None else tile_tick
    fresh_frame = frow is not None and new_seq > frame_seq
    if not fresh_frame and not tiles:
        return None                      # nothing new for this world
    # New frame -> push the moving overlay (small); otherwise just new tiles.
    overlay = _frame_overlay(frow["json"]) if fresh_frame else None
    msg = {"t": "map", "world": world, "tiles": tiles, "overlay": overlay}
    return msg, {"seq": new_seq, "tick": max(tile_tick, tile_wm)}


def _delta_snapshot(cursor) -> tuple[dict, dict] | None:
    snap, _ = _read_snapshot()
    if snap is None:
        return None                      # still computing the first one
    ver = _snap_version()
    if isinstance(cursor, dict) and cursor.get("version") == ver:
        return None                      # no recompute since the client's copy
    out = dict(snap)
    out["ok"] = True
    out["version"] = ver
    return {"t": "snapshot", "data": out}, {"version": ver}


def _delta_findings(db_config, cursor) -> tuple[dict, dict] | None:
    """The Findings tab tracks two independent sources: the authored notebook
    file (by mtime) and the auto-derived 'observed' block (by snapshot version).
    Push whichever advanced, carrying both cursors forward."""
    cur = cursor or {}
    msg: dict = {"t": "findings"}
    new_cursor = dict(cur)
    changed = False
    try:
        mtime = os.path.getmtime(FINDINGS_PATH)
    except OSError:
        mtime = 0
    if cur.get("mtime") != mtime:
        msg["rows"] = api_findings()
        new_cursor["mtime"] = mtime
        changed = True
    ver = _snap_version()
    snap, _ = _read_snapshot()
    if snap is not None and cur.get("version") != ver:
        msg["observed"] = api_observed(db_config)
        new_cursor["version"] = ver
        changed = True
    return (msg, new_cursor) if changed else None


def _delta_logs(params: dict, cursor) -> tuple[dict, dict] | None:
    """Stream growth of the selected log file as an appended tail. Switching files
    is handled by a fresh REST load, so here we only follow the same file; a
    truncation/rotation (size shrank) re-sends the whole file."""
    name = params.get("name") or "decisions"
    path = LOG_FILES.get(name)
    if not path or not os.path.exists(path):
        return None
    cur = cursor or {}
    if cur.get("name") != name:
        return None                      # file just changed; REST load owns it
    try:
        size = os.path.getsize(path)
    except OSError:
        return None
    prev = int(cur.get("size") or 0)
    if size == prev:
        return None
    if size < prev:                      # rotated/truncated: full resend
        kind, text, wm = api_log(name)
        return {"t": "log", "name": name, "kind": kind, "full": text}, \
               {"name": name, "size": wm}
    try:
        with open(path, "rb") as fh:
            fh.seek(prev)
            chunk = fh.read(size - prev)
    except OSError:
        return None
    return {"t": "log", "name": name, "append": chunk.decode("utf-8", "replace")}, \
           {"name": name, "size": size}


def _build_delta(conn, db_config, sub: dict) -> tuple[dict, dict] | None:
    """Dispatch a subscription to its delta builder. ``conn`` is a shared
    read-only connection for the DB-backed views; file/cache views ignore it."""
    tab = sub.get("tab")
    params = sub.get("params") or {}
    cursor = sub.get("cursor")
    if tab == "decisions":
        return _delta_decisions(conn, params, cursor)
    if tab == "map":
        return _delta_map(conn, params, cursor)
    if tab in ("overview", "timeline"):
        return _delta_snapshot(cursor)
    if tab == "findings":
        return _delta_findings(db_config, cursor)
    if tab == "logs":
        return _delta_logs(params, cursor)
    return None


def _push_loop(db_config, stop: threading.Event, interval: float = 1.0) -> None:
    """The live-delta pump: once a second, for each subscribed client, compute
    what changed since its cursor for the view it is on and push the *data*.

    One shared read-only connection per tick serves all decision/map subscribers
    (findings/logs/snapshot read files or the cached snapshot and need no DB). A
    dead socket is dropped; a DB hiccup skips this tick, never crashes — the page
    then rides its REST polling fallback until the socket recovers."""
    while not stop.is_set():
        with _ws_lock:
            clients = [c for c in _ws_clients if c.get_sub()]
        if clients:
            need_db = any((c.get_sub() or {}).get("tab") in ("decisions", "map")
                          for c in clients)
            conn = None
            if need_db:
                try:
                    conn = _db.connect(db_config, readonly=True)
                except _db.Error:
                    conn = None
            try:
                for c in clients:
                    sub = c.get_sub()
                    if not sub:
                        continue
                    if sub["tab"] in ("decisions", "map") and conn is None:
                        continue         # DB down this tick; retry next
                    try:
                        result = _build_delta(conn, db_config, sub)
                    except (*_db.Error, zlib.error, json.JSONDecodeError, OSError):
                        result = None
                    if result is None:
                        continue
                    msg, new_cursor = result
                    # Echo the advanced cursor to the client so it mirrors ours and
                    # can resume exactly here after a reconnect / filter change.
                    msg["cursor"] = new_cursor
                    if c.send(json.dumps(msg)):
                        c.advance_cursor(sub["tab"], sub["params"], new_cursor)
                    else:
                        with _ws_lock:
                            _ws_clients.discard(c)
            finally:
                if conn is not None:
                    conn.close()
        stop.wait(interval)


def _data_signature(db_config) -> tuple | None:
    """A cheap "has anything been written?" fingerprint: the PRIMARY-KEY maxima
    of the two hot tables (an instant index lookup on both backends). ``None`` on
    any DB hiccup, which the caller treats as "recompute to be safe"."""
    try:
        conn = _db.connect(db_config, readonly=True)
        try:
            fr = conn.execute("SELECT MAX(seq) FROM frames").fetchone()
            de = conn.execute("SELECT MAX(seq) FROM decisions").fetchone()
        finally:
            conn.close()
        return (fr[0] if fr else None, de[0] if de else None)
    except _db.Error:
        return None


def _snapshot_step(db_config, last_sig):
    """One worker iteration: (re)compute the snapshot iff the data has advanced
    since ``last_sig`` (or nothing has been published yet, or the signature is
    unavailable), and return the ``last_sig`` to carry into the next iteration.

    Extracted from the worker loop so the change-detection guard — the thing that
    stops a static DB from being re-aggregated (minutes of load) every cycle — is
    unit-testable without driving the thread."""
    sig = _data_signature(db_config)
    published, _ = _read_snapshot()
    # Recompute when the data changed, when we've never published, or when the
    # signature is unavailable (a hiccup — recompute rather than serve nothing).
    if sig is None or sig != last_sig or published is None:
        _publish_snapshot(db_config)
        fresh, err = _read_snapshot()
        if fresh is not None and err is None:
            return sig
    return last_sig


def _snapshot_worker(db_config, stop: threading.Event,
                     refresh: float = _SNAP_REFRESH) -> None:
    """Recompute and publish the KPI snapshot off the HTTP request path.

    The snapshot is a heavy multi-GB aggregate (minutes of wall time); running it
    on a request thread hung /api/snapshot and, via the browser's connection cap,
    starved the whole dashboard. This owns that cost on a background thread:
    (re)compute only when the data has advanced, publish, wait ``refresh``
    seconds, repeat. The first compute starts at startup, so Overview/Timeline
    show a "computing…" placeholder until it lands, then update each cycle. A slow
    compute simply defers the next one — never a pile-up, since the next compute
    begins only after this one returns."""
    last_sig = object()          # sentinel: guarantees a compute on the first pass
    while not stop.is_set():
        last_sig = _snapshot_step(db_config, last_sig)
        stop.wait(refresh)


# --------------------------------------------------------------------------- #
# HTTP handler
# --------------------------------------------------------------------------- #

class Handler(BaseHTTPRequestHandler):
    # ``db_config`` (a SQLite/MariaDB config dict) is injected in main().
    db_config = {"type": "sqlite", "path": DEFAULT_DB}

    def log_message(self, *args):  # keep the console quiet; we're read-only
        pass

    def _send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj) -> None:
        self._send(200, json.dumps(obj).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_HEAD(self) -> None:
        self.do_GET()

    def _serve_ws(self) -> None:
        """Upgrade this connection to a WebSocket and serve it until it closes.

        Sends the RFC6455 101 handshake, registers the client, then loops reading
        frames: it answers pings, applies the client's ``sub`` messages (which view
        + cursor it wants live updates for), and exits on close/EOF. The push
        thread does the sending; this loop keeps the socket healthy and the
        client's subscription current."""
        key = self.headers.get("Sec-WebSocket-Key")
        if not key:
            self._send(400, b"missing Sec-WebSocket-Key", "text/plain; charset=utf-8")
            return
        # Emit the 101 as raw HTTP/1.1 — the WebSocket protocol requires 1.1, but
        # BaseHTTPRequestHandler.send_response would stamp the handler's default
        # HTTP/1.0 status line, which strict clients/proxies reject.
        self.wfile.write(
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\n"
            b"Connection: Upgrade\r\n"
            b"Sec-WebSocket-Accept: " + _ws_accept_key(key).encode("ascii") +
            b"\r\n\r\n")
        self.wfile.flush()
        self.close_connection = True     # we own the socket now; no keep-alive reuse

        client = WSClient(self.connection)
        with _ws_lock:
            _ws_clients.add(client)
        try:
            while True:
                frame = _ws_read_frame(self.rfile)
                if frame is None:
                    break                       # EOF / malformed -> peer gone
                opcode, data = frame
                if opcode == 0x8:               # close
                    break
                if opcode == 0x9:               # ping -> pong
                    client.pong(data)
                elif opcode == 0x1:             # text -> a subscription message
                    _apply_sub(client, data)
                # binary/pong from the client are ignored
        except OSError:
            pass
        finally:
            client.alive = False
            with _ws_lock:
                _ws_clients.discard(client)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        q = parse_qs(parsed.query)

        def one(key, default=None):
            v = q.get(key, [default])
            return v[0] if v else default

        try:
            if path == "/ws" and self.headers.get("Upgrade", "").lower() == "websocket":
                self._serve_ws()
                return
            if path in ("/", "/index.html"):
                self._send(200, PAGE.encode("utf-8"), "text/html; charset=utf-8")
            elif path == "/api/snapshot":
                self._json(api_snapshot(self.db_config))
            elif path == "/api/worlds":
                self._json(api_worlds(self.db_config))
            elif path == "/api/chars":
                self._json(api_chars(self.db_config))
            elif path == "/api/decisions":
                self._json(api_decisions(
                    self.db_config, one("char"), one("world"),
                    int(one("limit", "100") or 100)))
            elif path == "/api/map":
                self._json(api_map(self.db_config, one("world")))
            elif path == "/api/heatmap":
                self._json(api_heatmap(self.db_config, one("world")))
            elif path == "/api/story":
                self._json(api_story())
            elif path == "/api/codex":
                self._json(api_codex(self.db_config))
            elif path == "/api/recon":
                self._json(api_recon(self.db_config))
            elif path == "/api/nav":
                self._json(api_nav(self.db_config))
            elif path == "/api/matrix":
                self._json(api_matrix(self.db_config))
            elif path == "/api/log":
                kind, text, size = api_log(one("name", "decisions"))
                # ``size`` is the byte cursor the page subscribes with for the tail.
                self._json({"kind": kind, "text": text, "size": size})
            elif path == "/api/findings":
                # ``mtime`` is the cursor the page subscribes with; the pusher
                # re-sends the notebook only when the file changes.
                try:
                    mtime = os.path.getmtime(FINDINGS_PATH)
                except OSError:
                    mtime = 0
                self._json({"rows": api_findings(), "mtime": mtime})
            elif path == "/api/tickbar":
                self._json(api_tickbar(self.db_config))
            elif path == "/api/phase":
                self._json(api_phase(self.db_config))
            elif path == "/api/observed":
                self._json(api_observed(self.db_config))
            elif path == "/api/roster":
                self._json(api_roster(self.db_config))
            else:
                self._send(404, b"not found", "text/plain; charset=utf-8")
        except BrokenPipeError:
            pass  # client navigated away mid-response; nothing to do
        except Exception as exc:  # never let one bad request kill the handler
            self._send(500, json.dumps({"error": str(exc)}).encode("utf-8"),
                       "application/json; charset=utf-8")


# --------------------------------------------------------------------------- #
# The single-page app (inline HTML/CSS/JS, fully self-contained)
# --------------------------------------------------------------------------- #

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>steemer dashboard</title>
<style>
/* Palette roles from the data-viz reference palette; light + dark are both
   selected steps, not an auto-flip. Only the roles this page uses are defined. */
:root{
  --plane:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e;
  --muted:#898781; --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,.10);
  --s1:#2a78d6; /* blue  */ --s2:#1baf7a; /* aqua */ --s3:#eda100; /* yellow */
  --good:#0ca30c; --warn:#fab219; --serious:#ec835a; --crit:#d03b3b;
  --chosen:#2a78d6;
}
@media (prefers-color-scheme:dark){
  :root{
    --plane:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7;
    --muted:#898781; --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10);
    --s1:#3987e5; --s2:#199e70; --s3:#c98500; --good:#0ca30c; --warn:#fab219;
    --serious:#ec835a; --crit:#d03b3b; --chosen:#3987e5;
  }
}
/* Explicit theme toggle wins in both directions. */
:root[data-theme=light]{
  --plane:#f9f9f7; --surface:#fcfcfb; --ink:#0b0b0b; --ink2:#52514e;
  --grid:#e1e0d9; --axis:#c3c2b7; --border:rgba(11,11,11,.10);
  --s1:#2a78d6; --s2:#1baf7a; --s3:#eda100; --chosen:#2a78d6;
}
:root[data-theme=dark]{
  --plane:#0d0d0d; --surface:#1a1a19; --ink:#fff; --ink2:#c3c2b7;
  --grid:#2c2c2a; --axis:#383835; --border:rgba(255,255,255,.10);
  --s1:#3987e5; --s2:#199e70; --s3:#c98500; --chosen:#3987e5;
}
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);
  font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:14px;
  line-height:1.45}
a{color:var(--s1)}
header{display:flex;align-items:center;gap:16px;padding:10px 16px;
  border-bottom:1px solid var(--border);background:var(--surface);
  position:sticky;top:0;z-index:5;flex-wrap:wrap}
header h1{font-size:15px;margin:0;font-weight:700;letter-spacing:.2px}
header .phasechip{font-size:11px;font-weight:700;letter-spacing:.06em;
  text-transform:uppercase;padding:2px 10px;border-radius:999px;
  background:var(--surface);color:var(--muted);border:1px solid var(--border)}
header .phasechip.fielding{background:#173d24;color:#7fdc9c;border-color:#2e7d4f}
header .phasechip.mustering{background:#1b2f45;color:#8fc1f0;border-color:#2a5f95}
header .phasechip.recall{background:#4a3312;color:#f0c060;border-color:#a07020}
header .phasechip.bunker{background:#5a1d1d;color:#ffb4b4;border-color:#a03030}
header .phasechip.offline{background:var(--surface);color:var(--muted);border-color:var(--border)}
header .grow{flex:1}
nav{display:flex;gap:4px;flex-wrap:wrap}
nav button{background:transparent;border:1px solid transparent;color:var(--ink2);
  padding:6px 12px;border-radius:8px;cursor:pointer;font:inherit}
nav button:hover{background:var(--plane)}
nav button.active{background:var(--plane);color:var(--ink);
  border-color:var(--border);font-weight:600}
.small{color:var(--muted);font-size:12px}
main{padding:16px;max-width:1200px;margin:0 auto}
.tab{display:none}
.tab.active{display:block}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;
  padding:16px;margin-bottom:16px}
.card h2{font-size:13px;text-transform:uppercase;letter-spacing:.6px;
  color:var(--ink2);margin:0 0 12px}
/* stat tiles */
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.tickbar{margin-top:10px;background:var(--surface);border:1px solid var(--border);
  border-radius:12px;padding:10px 12px}
.tickstrip{display:flex;flex-wrap:nowrap;overflow:hidden;gap:0;height:14px}
.tickstrip .tk{flex:1 1 auto;min-width:1px;background:var(--good,#2ea043)}
.tickstrip .tk.miss{background:#d1242f}
.tickstrip .tk.jump{background:var(--border,#6e7681)}
.tickstrip .tk.ok{background:#2ea043}
.tickcap{font-size:12px;color:var(--muted);margin-top:6px}
.tickrate.good{color:#2ea043}.tickrate.warn{color:#d29922}.tickrate.crit{color:#d1242f;font-weight:700}
.stat{background:var(--surface);border:1px solid var(--border);border-radius:12px;
  padding:14px 16px}
.stat .k{font-size:12px;color:var(--muted);text-transform:uppercase;
  letter-spacing:.5px}
.stat .v{font-size:26px;font-weight:700;margin-top:4px}
.stat .sub{font-size:12px;color:var(--ink2);margin-top:2px}
.v.good{color:var(--good)} .v.warn{color:var(--warn)} .v.crit{color:var(--crit)}
/* bar charts (single series -> no legend needed) */
.bars{display:flex;flex-direction:column;gap:6px}
.bar-row{display:grid;grid-template-columns:150px 1fr 48px;align-items:center;gap:8px}
.bar-row .lbl{font-size:12px;color:var(--ink2);white-space:nowrap;overflow:hidden;
  text-overflow:ellipsis}
.bar-track{background:var(--plane);border-radius:6px;height:14px;overflow:hidden}
.bar-fill{height:100%;background:var(--s1);border-radius:4px;min-width:2px}
.bar-row .num{font-size:12px;color:var(--ink2);text-align:right;
  font-variant-numeric:tabular-nums}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media(max-width:760px){.grid2{grid-template-columns:1fr}}
/* decision feed */
.filters{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
select,input[type=text]{background:var(--surface);color:var(--ink);
  border:1px solid var(--border);border-radius:8px;padding:6px 8px;font:inherit}
label.chk{display:flex;align-items:center;gap:6px;color:var(--ink2);font-size:13px}
.decision{background:var(--surface);border:1px solid var(--border);
  border-radius:12px;padding:14px 16px;margin-bottom:12px}
.decision .head{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap;
  margin-bottom:8px}
.badge{font-size:11px;padding:2px 8px;border-radius:999px;background:var(--plane);
  border:1px solid var(--border);color:var(--ink2);
  font-variant-numeric:tabular-nums}
.badge.act{color:var(--ink);border-color:var(--chosen);font-weight:600}
.decision .reasoning{white-space:pre-wrap;font-family:ui-monospace,
  "SF Mono",Menlo,Consolas,monospace;font-size:12.5px;color:var(--ink);
  background:var(--plane);border-radius:8px;padding:10px 12px;overflow-x:auto}
.alts{margin-top:10px;display:flex;flex-direction:column;gap:4px}
.alt{display:grid;grid-template-columns:56px 1fr;gap:8px;align-items:baseline;
  font-size:12.5px;padding:3px 6px;border-radius:6px}
.alt.chosen{background:color-mix(in srgb,var(--chosen) 14%,transparent);
  border:1px solid var(--chosen)}
.alt .score{font-variant-numeric:tabular-nums;font-weight:600;color:var(--ink2)}
.alt.chosen .score{color:var(--chosen)}
.alt .why{color:var(--ink2)}
.alt .aname{color:var(--ink);font-weight:600}
/* map — a pan/zoom canvas viewport (Google-Maps style) */
.map-wrap{position:relative;overflow:hidden;border:1px solid var(--border);
  border-radius:8px;background:var(--plane);height:min(70vh,640px);
  touch-action:none}                 /* touch-action:none -> we own pan/pinch */
#mapCanvas{display:block;width:100%;height:100%;image-rendering:pixelated;
  cursor:grab}
#mapCanvas.grabbing{cursor:grabbing}
.map-controls{position:absolute;top:10px;right:10px;display:flex;
  flex-direction:column;gap:6px;z-index:2}
.map-controls button{width:34px;height:34px;border:1px solid var(--border);
  background:var(--surface);color:var(--ink);border-radius:8px;font-size:18px;
  line-height:1;cursor:pointer;display:flex;align-items:center;
  justify-content:center;padding:0}
.map-controls button:hover{background:var(--plane)}
.map-coords{position:absolute;left:10px;bottom:10px;background:var(--surface);
  border:1px solid var(--border);border-radius:8px;padding:4px 8px;font-size:12px;
  font-variant-numeric:tabular-nums;color:var(--ink2);pointer-events:none;
  z-index:2}
.legend{display:flex;flex-wrap:wrap;gap:8px 14px;margin-top:12px}
.legend .item{display:flex;align-items:center;gap:6px;font-size:12px;color:var(--ink2)}
.legend .sw{width:12px;height:12px;border-radius:3px;border:1px solid var(--border)}
/* timeline */
.run{display:grid;grid-template-columns:12px 1fr;gap:14px;margin-bottom:4px}
.run .line{position:relative}
.run .line::before{content:"";position:absolute;left:5px;top:4px;bottom:-4px;
  width:2px;background:var(--axis)}
.run:last-child .line::before{bottom:auto;height:8px}
.run .node{width:12px;height:12px;border-radius:50%;background:var(--s1);
  border:2px solid var(--surface);position:relative;z-index:1}
.run .body{background:var(--surface);border:1px solid var(--border);
  border-radius:12px;padding:12px 14px;margin-bottom:12px}
.run .body h3{margin:0 0 6px;font-size:14px}
.run .meta{display:flex;flex-wrap:wrap;gap:6px 16px;font-size:12.5px;
  color:var(--ink2)}
.run .meta b{color:var(--ink);font-weight:600;font-variant-numeric:tabular-nums}
.delta.up{color:var(--good)} .delta.down{color:var(--crit)}
/* story mode — version narrative */
.sv{display:grid;grid-template-columns:110px 1fr;gap:12px;padding:8px 0;
  border-top:1px solid var(--border)}
.sv:first-child{border-top:none}
.sv-ver{font-weight:600;font-variant-numeric:tabular-nums;color:var(--s1);font-size:13px}
.sv-items{display:flex;flex-direction:column;gap:6px}
.sv-item{display:flex;gap:8px;align-items:baseline;font-size:13px}
.sv-tag{flex:none;font-size:10px;text-transform:uppercase;letter-spacing:.5px;
  padding:1px 7px;border-radius:999px;font-weight:600;min-width:64px;text-align:center}
.sv-tag.hyp{background:color-mix(in srgb,var(--s1) 20%,transparent);color:var(--s1)}
.sv-tag.eff{background:color-mix(in srgb,var(--good) 20%,transparent);color:var(--good)}
.sv-tag.note{background:var(--plane);color:var(--ink2)}
.sv-title{color:var(--ink)}
pre.doc{white-space:pre-wrap;background:#11161c;border:1px solid #223;border-radius:6px;padding:.6em .8em;font-size:12px;line-height:1.45;overflow-x:auto}
#tab-nav h3{margin:1.2em 0 .3em}#tab-nav h4{margin:1em 0 .2em}
/* Frontier pane. Colour is a TINT behind the cell; the GLYPH wears ink tokens and carries
   the meaning, because the palette validator flagged the frontier amber at 1.79:1 against
   the light surface — below 3:1, so it may not be the only cue. Legend + glyph + the
   frontier table are the three redundant encodings. */
.fr-bar{display:flex;gap:2px;margin:10px 0 4px}
.fr-bar i{flex:1;height:14px;border-radius:2px;background:var(--grid);font-style:normal}
.fr-bar i.sent{background:color-mix(in srgb,var(--s2) 55%,transparent)}
.fr-legend{display:flex;gap:14px;flex-wrap:wrap;margin:10px 0;font-size:12px;color:var(--ink2)}
.fr-legend span{display:inline-flex;align-items:center;gap:5px}
.fr-key{width:16px;height:16px;border-radius:3px;display:inline-grid;place-items:center;
  font-size:11px;line-height:1;color:var(--ink);border:1px solid var(--border)}
.fr-key.frontier{background:color-mix(in srgb,var(--warn) 42%,transparent)}
.fr-key.tried{background:color-mix(in srgb,var(--s2) 22%,transparent)}
.fr-key.unlikely{background:var(--grid)}
.fr-grid{overflow-x:auto;margin-top:6px}
.fr-grid table{border-collapse:separate;border-spacing:2px;font-size:11px}
.fr-grid th{font-weight:600;color:var(--muted);text-align:left;white-space:nowrap}
.fr-grid th.v{writing-mode:vertical-rl;transform:rotate(180deg);padding:2px 0;font-weight:500}
.fr-grid th.n{padding-right:6px;color:var(--ink2)}
.fr-grid td{width:16px;height:16px;border-radius:3px;text-align:center;cursor:default;
  color:var(--ink);background:var(--grid)}
.fr-grid td.frontier{background:color-mix(in srgb,var(--warn) 42%,transparent);font-weight:700}
.fr-grid td.tried{background:color-mix(in srgb,var(--s2) 22%,transparent)}
.fr-grid tr.band td:first-child{border-top:1px solid var(--border)}
.fr-group{color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.5px;
  padding-top:8px}
.fr-tbl{width:100%;border-collapse:collapse;margin-top:6px;font-size:13px}
.fr-tbl th{text-align:left;color:var(--muted);font-weight:600;font-size:11px;
  text-transform:uppercase;letter-spacing:.5px;padding:4px 8px 4px 0}
.fr-tbl td{padding:6px 8px 6px 0;border-top:1px solid var(--border);vertical-align:top}
.fr-tbl tr.mine td{color:var(--accent,#4ade80);font-weight:600}
.fr-tbl td.p{font-variant-numeric:tabular-nums;font-weight:600}
.fr-cell{font-family:ui-monospace,Menlo,monospace}
/* codex — the auto-populated wiki */
.cx-nav{display:flex;gap:6px;align-items:center;margin-bottom:14px;flex-wrap:wrap}
.cx-btn{background:transparent;border:1px solid var(--border);color:var(--ink2);
  padding:5px 12px;border-radius:8px;font-size:13px;cursor:pointer}
.cx-btn.active{background:var(--plane);color:var(--ink);border-color:var(--chosen);font-weight:600}
.cx-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:12px}
.cx-card{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:12px 14px}
.cx-h{display:flex;justify-content:space-between;align-items:baseline;gap:8px;margin-bottom:6px}
.cx-t{font-weight:600}
.cx-cls{font-size:10px;text-transform:uppercase;letter-spacing:.5px;font-weight:600;
  padding:1px 7px;border-radius:999px}
.cx-cls.cls-undead{background:color-mix(in srgb,var(--s3) 22%,transparent);color:var(--s3)}
.cx-cls.cls-predator{background:color-mix(in srgb,var(--crit) 20%,transparent);color:var(--crit)}
.cx-cls.cls-benign{background:color-mix(in srgb,var(--good) 20%,transparent);color:var(--good)}
.cx-cls.cls-item{background:var(--plane);color:var(--ink2)}
.cx-b{font-size:12.5px;color:var(--ink2)}
.cx-item{display:flex;align-items:baseline;gap:8px}
.cx-mech h3{font-size:13px;color:var(--ink2);margin:14px 0 8px;text-transform:uppercase;
  letter-spacing:.5px}
.cx-doc{padding:5px 0;border-top:1px solid var(--border);font-size:13px}
.cx-doc:first-of-type{border-top:none}
/* findings — the lab notebook */
.find-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));
  gap:14px}
.finding{background:var(--surface);border:1px solid var(--border);
  border-left:4px solid var(--axis);border-radius:12px;padding:14px 16px}
/* conjectures read as "not yet established": dashed, tinted, distinct from a
   solid confirmed discovery. Kind sets the left accent colour. */
.finding.k-discovery{border-left-color:var(--s2)}
/* questions read as "open curiosity, no hypothesis yet": dotted, lightly tinted,
   between a solid confirmed fact and a dashed conjecture. */
.finding.k-question{border-left-color:var(--s3);border-left-style:dotted;
  background:color-mix(in srgb,var(--s3) 4%,var(--surface))}
.finding.k-conjecture{border-left-color:var(--s3);border-left-style:dashed;
  background:color-mix(in srgb,var(--s3) 6%,var(--surface))}
.finding.k-consideration{border-left-color:var(--s1)}
.finding.refuted{opacity:.6}
.finding .ftitle{font-size:14px;font-weight:700;margin:0 0 8px}
.finding .fbadges{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
.finding .fdetail{color:var(--ink2);font-size:13px;white-space:pre-wrap}
.finding .block{margin-top:10px;font-size:12.5px;border-radius:8px;
  padding:8px 10px;background:var(--plane)}
.finding .block .lab{display:block;font-size:11px;text-transform:uppercase;
  letter-spacing:.5px;color:var(--muted);margin-bottom:3px}
.finding .block.evidence{border-left:3px solid var(--s2)}
.finding .block.test{border-left:3px solid var(--s3)}
.finding .ftags{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.finding .tag{font-size:11px;padding:1px 8px;border-radius:999px;
  background:var(--plane);border:1px solid var(--border);color:var(--ink2);
  cursor:pointer}
.finding .ffoot{margin-top:8px;font-size:11px;color:var(--muted)}
/* status/kind/confidence badges */
.fbadge{font-size:11px;padding:2px 8px;border-radius:999px;border:1px solid var(--border);
  background:var(--plane);color:var(--ink2);font-weight:600}
.fbadge.kind{color:var(--ink)}
.fbadge.st-confirmed{color:#fff;background:var(--good);border-color:transparent}
.fbadge.st-shipped{color:#fff;background:var(--s1);border-color:transparent}
.fbadge.st-refuted{color:#fff;background:var(--crit);border-color:transparent}
.fbadge.st-open{color:var(--ink2)}
.fbadge.conf{background:transparent}
.observed table{width:100%;border-collapse:collapse;font-size:12.5px}
.observed th{text-align:left;color:var(--muted);font-weight:600;
  text-transform:uppercase;letter-spacing:.4px;font-size:11px;
  padding:4px 8px;border-bottom:1px solid var(--border)}
.observed td{padding:4px 8px;border-bottom:1px solid var(--border);
  font-variant-numeric:tabular-nums}
.observed td.k{color:var(--ink);font-variant-numeric:normal}
.observed .col3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:16px}
@media(max-width:820px){.observed .col3{grid-template-columns:1fr}}
/* roster + inventory panel — a PARTIAL, swinging view of a larger persistent
   roster, so "now" is framed against the recent range + frame age, never as an
   authoritative headcount. */
.roster .rhead{font-size:15px;color:var(--ink2)}
.roster .rhead b{color:var(--ink);font-weight:700;font-variant-numeric:tabular-nums}
.roster .rline{font-size:13px;color:var(--ink2);margin-top:10px}
.roster .rline .badge{margin:2px 6px 2px 0}
.roster .rnote{color:var(--muted);font-size:12px;font-style:italic;margin-top:12px}
.roster .ranom{color:var(--serious);font-size:12px;margin-top:10px;
  font-variant-numeric:tabular-nums}
/* logs */
pre.log{white-space:pre-wrap;font-family:ui-monospace,"SF Mono",Menlo,Consolas,
  monospace;font-size:12.5px;background:var(--surface);border:1px solid var(--border);
  border-radius:12px;padding:16px;overflow-x:auto}
.empty{color:var(--muted);padding:24px;text-align:center;font-style:italic}
mono,.mono{font-family:ui-monospace,Menlo,Consolas,monospace}
/* Party (per-character) panel */
.party-meta{color:var(--muted);margin-bottom:12px;font-size:13px}
.party-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px}
.pc{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:14px}
.pc-head{display:flex;justify-content:space-between;align-items:baseline;gap:8px}
.pc-name{font-weight:600}
.pc-role{font-size:10px;text-transform:uppercase;letter-spacing:.5px;font-weight:600;
  padding:1px 7px;border-radius:999px;margin-right:auto}
.pc-role.role-guardian{background:color-mix(in srgb,var(--s1) 22%,transparent);color:var(--s1)}
.pc-role.role-forager{background:color-mix(in srgb,var(--good) 22%,transparent);color:var(--good)}
.pc-role.role-wizard{background:color-mix(in srgb,#a371f7 22%,transparent);color:#a371f7}
.pc-role.role-fodder{background:color-mix(in srgb,#f778ba 22%,transparent);color:#f778ba}
.pc-role.role-nuisance{background:color-mix(in srgb,#e3b341 22%,transparent);color:#e3b341}
.pc-where{color:var(--muted);font-size:12px}
.bar{height:9px;border-radius:5px;background:var(--border);overflow:hidden;margin:3px 0 8px}
.bar>span{display:block;height:100%}
.bar-lbl{display:flex;justify-content:space-between;font-size:12px;color:var(--ink2)}
.hp-ok>span{background:#3fb950}.hp-warn>span{background:#d29922}.hp-crit>span{background:#f85149}
.sta>span{background:#58a6ff}
.pc-stats{display:flex;flex-wrap:wrap;gap:4px 10px;font-size:12px;margin:6px 0}
.pc-stat b{color:var(--ink)}
.gift{color:#a371f7}
.pc-row{font-size:12px;color:var(--ink2);margin:4px 0}
.pc-row .k{color:var(--muted)}
.chip{display:inline-block;background:var(--border);border-radius:6px;padding:1px 6px;margin:2px 3px 0 0;font-size:11px}
.chip.pois{background:#5a1d1d;color:#ffb4b4}
.pc-dec{font-size:11px;color:var(--muted);margin-top:8px;border-top:1px solid var(--border);padding-top:6px;font-style:italic}
</style>
</head>
<body>
<header>
  <span class="phasechip" id="phasechip" title="guild phase">&hellip;</span>
  <h1>steemer &middot; guild dashboard</h1>
  <nav>
    <button data-tab="overview" class="active">Overview</button>
    <button data-tab="party">Party</button>
    <button data-tab="decisions">Decisions</button>
    <button data-tab="map">Map</button>
    <button data-tab="codex">Codex</button>
    <button data-tab="recon">Rivals</button>
    <button data-tab="nav">How nav works</button>
    <button data-tab="timeline">Timeline</button>
    <button data-tab="findings">Findings</button>
    <button data-tab="logs">Logs</button>
  </nav>
  <span class="grow"></span>
  <label class="chk"><input type="checkbox" id="autorefresh" checked> auto-refresh</label>
  <button id="theme" title="toggle theme" style="background:transparent;border:1px solid var(--border);color:var(--ink2);border-radius:8px;padding:6px 10px;cursor:pointer">◐</button>
</header>

<main>
  <!-- OVERVIEW -->
  <section class="tab active" id="tab-overview">
    <div class="tiles" id="ov-tiles"></div>
    <div id="tickbar" class="tickbar"></div>
    <div class="card roster" id="ov-roster-card" style="display:none;margin-top:16px">
      <h2>Roster (server partial view)</h2><div id="ov-roster"></div></div>
    <div class="grid2" style="margin-top:16px">
      <div class="card"><h2>Actions sent</h2><div class="bars" id="ov-actions"></div></div>
      <div class="card"><h2>Decisions by action</h2><div class="bars" id="ov-decisions"></div></div>
      <div class="card"><h2>Events by kind</h2><div class="bars" id="ov-events"></div></div>
      <div class="card"><h2>Action errors by reason</h2><div class="bars" id="ov-errors"></div></div>
    </div>
    <div class="card"><h2>Exploration</h2><div id="ov-explore"></div></div>
  </section>

  <!-- PARTY (per-character stats) -->
  <section class="tab" id="tab-party">
    <div class="party-meta" id="party-meta"></div>
    <div class="party-grid" id="party-cards"></div>
  </section>

  <!-- DECISIONS -->
  <section class="tab" id="tab-decisions">
    <div class="filters">
      <label class="chk">char
        <select id="f-char"><option value="">all</option></select></label>
      <label class="chk">world
        <select id="f-world"><option value="">all</option></select></label>
      <label class="chk">show
        <select id="f-limit">
          <option value="50">50</option>
          <option value="100" selected>100</option>
          <option value="200">200</option>
        </select></label>
      <span class="grow"></span>
      <span class="small" id="dec-count"></span>
    </div>
    <div id="dec-list"></div>
  </section>

  <!-- MAP -->
  <section class="tab" id="tab-map">
    <div class="filters">
      <label class="chk">world <select id="m-world"></select></label>
      <label class="chk">overlay
        <select id="m-overlay">
          <option value="">none</option>
          <option value="danger">Danger (deaths / time here)</option>
          <option value="death">Deaths (raw)</option>
          <option value="occupancy">Time here (occupancy)</option>
          <option value="monster">Monsters</option>
          <option value="gold">Gold</option>
          <option value="loot">Loot</option>
        </select></label>
      <span class="small" id="map-info"></span>
      <span class="grow"></span>
      <span class="small" id="hm-info"></span>
    </div>
    <div class="map-wrap" id="mapWrap">
      <canvas id="mapCanvas"></canvas>
      <div class="map-controls">
        <button id="m-zin" title="zoom in">+</button>
        <button id="m-zout" title="zoom out">&minus;</button>
        <button id="m-fit" title="fit whole world">&#9974;</button>
      </div>
      <div class="map-coords" id="mapCoords">&mdash;</div>
    </div>
    <div class="small" style="margin-top:6px">drag to pan &middot; wheel or pinch to zoom &middot; hover for tile coords</div>
    <div class="legend" id="map-legend"></div>
  </section>

  <!-- RIVAL RECON -->
  <section class="tab" id="tab-recon">
    <div class="small" id="recon-info"></div>
    <div class="card"><h2>Guild standings</h2><div id="recon-guilds"></div></div>
    <div class="card"><h2>Where rivals actually are</h2>
      <div class="small">Latest position per rival character. Compare the depth they work at
        with ours — our characters sit near the home row.</div>
      <div id="recon-where"></div></div>
    <div class="card"><h2>Gear they field that we never have</h2>
      <div class="small">Equipment kinds worn by a rival and by none of ours.</div>
      <div id="recon-gap"></div></div>
  </section>

  <!-- CODEX -->
  <section class="tab" id="tab-nav">
    <div class="small" id="nav-info"></div>
    <div id="nav-ladder"></div>
    <div id="nav-rules"></div>
  </section>

  <section class="tab" id="tab-codex">
    <div class="cx-nav">
      <button class="cx-btn active" data-cx="monsters">Monsters</button>
      <button class="cx-btn" data-cx="lands">Lands</button>
      <button class="cx-btn" data-cx="items">Items</button>
      <button class="cx-btn" data-cx="mechanics">Mechanics</button>
      <button class="cx-btn" data-cx="frontier">Frontier</button>
      <span class="grow"></span>
      <span class="small" id="cx-info"></span>
    </div>
    <div id="cx-monsters" class="cx-pane"></div>
    <div id="cx-lands" class="cx-pane" hidden></div>
    <div id="cx-items" class="cx-pane" hidden></div>
    <div id="cx-mechanics" class="cx-pane" hidden></div>
    <div id="cx-frontier" class="cx-pane" hidden></div>
  </section>

  <!-- TIMELINE -->
  <section class="tab" id="tab-timeline">
    <div class="card"><h2>Story mode &mdash; the bot's evolution by version</h2>
      <div class="small" style="margin-bottom:10px">each strategy version's shipped hypothesis
        and its measured effect, newest first (from the findings notebook)</div>
      <div id="tl-story"></div></div>
    <div class="card" style="margin-top:16px"><h2>Version timeline (runs)</h2>
      <div id="tl-list"></div></div>
  </section>

  <!-- FINDINGS -->
  <section class="tab" id="tab-findings">
    <div class="filters">
      <label class="chk">kind
        <select id="fx-kind">
          <option value="">all</option>
          <option value="discovery">discoveries</option>
          <option value="question">questions</option>
          <option value="conjecture">conjectures</option>
          <option value="consideration">considerations</option>
        </select></label>
      <label class="chk">status
        <select id="fx-status"><option value="">all</option></select></label>
      <label class="chk">tag
        <select id="fx-tag"><option value="">all</option></select></label>
      <label class="chk">search
        <input type="text" id="fx-q" placeholder="title / detail" size="18"></label>
      <span class="grow"></span>
      <span class="small" id="fx-count"></span>
    </div>
    <div class="find-grid" id="find-list"></div>

    <div class="card observed" style="margin-top:20px">
      <h2>Observed in play (auto-derived)</h2>
      <div class="col3">
        <div>
          <h2 style="margin-top:0">Event kinds — first seen</h2>
          <div id="obs-events"></div>
        </div>
        <div>
          <h2 style="margin-top:0">Action-error reasons</h2>
          <div id="obs-errors"></div>
        </div>
        <div>
          <h2 style="margin-top:0">Exploration frontier</h2>
          <div id="obs-explore"></div>
        </div>
      </div>
    </div>
  </section>

  <!-- LOGS -->
  <section class="tab" id="tab-logs">
    <div class="filters">
      <label class="chk">file
        <select id="log-name">
          <option value="decisions">decisions.log</option>
          <option value="bugs">server_bugs.md</option>
        </select></label>
    </div>
    <pre class="log" id="log-body"></pre>
  </section>
</main>

<script>
"use strict";
const $ = s => document.querySelector(s);
const el = (t, cls, txt) => { const e=document.createElement(t);
  if(cls) e.className=cls; if(txt!=null) e.textContent=txt; return e; };
const fmtNum = n => (n==null?"—":Number(n).toLocaleString());
const esc = s => (s==null?"":String(s));
// esc() only stringifies, and its call sites are a MIX: some feed textContent (where
// escaping would render a literal &amp;) and some feed innerHTML template strings (where
// not escaping lets server-authored text inject markup — item and mob names come from
// the game, which is an evolving target). Splitting the 46 existing call sites by context
// is its own change; escHtml is the correct helper for innerHTML and is what the nav tab
// uses. The mixed use elsewhere is recorded in findings.jsonl.
const escMap = {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"};
const escHtml = s => (s==null?"":String(s).replace(/[&<>"']/g, c => escMap[c]));

async function getJSON(url, timeoutMs){
  // Bound every request: a browser caps ~6 connections per host, so an endpoint
  // that hangs (a heavy query on a large DB) would otherwise hold its socket open
  // and starve every other tab. AbortController frees the connection on timeout.
  const ctl = new AbortController();
  const t = setTimeout(()=>ctl.abort(), timeoutMs||15000);
  try{ const r = await fetch(url,{cache:"no-store", signal:ctl.signal});
       if(!r.ok) return null; return await r.json(); }
  catch(e){ return null; }
  finally{ clearTimeout(t); }
}

/* ---- tabs ---- */
let active = "overview";
document.querySelectorAll("nav button").forEach(b=>{
  b.onclick = ()=>{
    active = b.dataset.tab;
    document.querySelectorAll("nav button").forEach(x=>x.classList.toggle("active",x===b));
    document.querySelectorAll(".tab").forEach(t=>
      t.classList.toggle("active", t.id==="tab-"+active));
    loadActive();        // fresh REST load of the newly-shown tab, then subscribe
  };
});

/* ---- live-push cursors ----
   The seq/version watermark the client already holds for each source. After any
   fresh REST load we record it here and hand it back to the server on subscribe,
   so the socket streams ONLY what is newer — the race-free handoff between the
   REST pull and the push stream. */
let decCursor=0, mapSeq=0, mapTick=-1, snapVersion=-1,
    findMtime=null, obsVersion=-1, logName=null, logSize=0;

/* REST-load whichever tab is showing (first paint, tab switch, filter change,
   and the no-socket fallback). Each loadX ends by subscribing with its cursor. */
function loadActive(){
  if(active==="overview") loadOverview();
  else if(active==="party") loadParty();
  else if(active==="decisions") loadDecisions();
  else if(active==="map") loadMap();
  else if(active==="codex") loadCodex();
  else if(active==="recon") loadRecon();
  else if(active==="nav") loadNav();
  else if(active==="timeline") loadTimeline();
  else if(active==="findings") loadFindings();
  else if(active==="logs") loadLogs();
}

/* ---- theme toggle ---- */
$("#theme").onclick = ()=>{
  const cur = document.documentElement.getAttribute("data-theme");
  const next = cur==="dark" ? "light" : cur==="light" ? "dark"
    : (matchMedia("(prefers-color-scheme:dark)").matches ? "light":"dark");
  document.documentElement.setAttribute("data-theme", next);
  if(active==="map") drawMap();   // colours come from CSS vars; just repaint
};

/* ---- bar chart (single series -> blue, no legend) ---- */
function bars(container, obj){
  container.innerHTML = "";
  const entries = Object.entries(obj||{});
  if(!entries.length){ container.appendChild(el("div","small","no data")); return; }
  const max = Math.max(...entries.map(([,v])=>v), 1);
  for(const [k,v] of entries){
    const row = el("div","bar-row");
    row.appendChild(el("div","lbl", k||"(none)"));
    const track = el("div","bar-track");
    const fill = el("div","bar-fill"); fill.style.width = (100*v/max)+"%";
    track.appendChild(fill); row.appendChild(track);
    row.appendChild(el("div","num", fmtNum(v)));
    container.appendChild(row);
  }
}

/* ---- OVERVIEW ---- */
async function loadOverview(){
  const s = await getJSON("/api/snapshot");
  renderOverview(s);
  loadTickbar();   // independent fetch: the bar must work even while the snapshot cache computes
  loadPhase();     // ditto — the phase chip must be honest during cache computes
  if(s && s.ok && s.version!=null) snapVersion = s.version;
  subscribe();
}

/* v0.108.3 tick-participation bar: one block per server tick (last 500), green =
   a frame landed for that tick, red = dropped. The rate line makes a stalled
   server clock (or a dead bot) visible at a glance. */
/* v0.117.0 phase chip (operator wishlist): the header shows WHICH PHASE the guild
   is in — offline / bunker / recall / mustering / fielding — instead of a bare
   online dot. Tooltip carries the machine's own reason line. */
async function loadPhase(){
  const chip = document.getElementById("phasechip"); if(!chip) return;
  const p = await getJSON("/api/phase");
  const phase = (p && p.phase) || "offline";
  chip.className = "phasechip " + phase;
  chip.textContent = phase;
  chip.title = !p ? "" :
    `health: ${p.health||"?"} · fielded: ${p.fielded??"?"} · frame age: ` +
    `${p.frame_age_s==null?"∞":p.frame_age_s+"s"}` + (p.why ? ` · ${p.why}` : "");
}

async function loadTickbar(){
  const host = document.getElementById("tickbar"); if(!host) return;
  const t = await getJSON("/api/tickbar");
  host.innerHTML = "";
  if(!t || !t.ok || t.max_tick==null){ host.textContent = "tick data unavailable"; return; }
  const miss = new Set(t.missing||[]);
  const jump = new Set(t.jumped||[]);
  const lo = t.max_tick - (t.window||500) + 1;
  const strip = el("div","tickstrip");
  for(let k=lo;k<=t.max_tick;k++){
    const cls = miss.has(k) ? "tk miss" : jump.has(k) ? "tk jump" : "tk ok";
    const b = el("span", cls);
    if(miss.has(k)) b.title = "tick "+k+" dropped";
    else if(jump.has(k)) b.title = "tick "+k+" skipped by the server clock";
    strip.appendChild(b);
  }
  const rate = t.rate_per_min;
  const rateCls = rate==null ? "" : rate<20 ? "crit" : rate<45 ? "warn" : "good";
  const cap = el("div","tickcap");
  cap.appendChild(el("span","", `ticks ${lo}–${t.max_tick} · ${miss.size} dropped · ${jump.size} clock-skipped`));
  const r = el("span","tickrate "+rateCls,
               rate==null ? " · rate n/a" : ` · ${rate} ticks/min` + (rate<45 ? " (server slow/stalled)" : ""));
  cap.appendChild(r);
  host.appendChild(strip); host.appendChild(cap);
}
function renderOverview(s){
  const tiles = $("#ov-tiles");
  if(!s || !s.ok){
    tiles.innerHTML = "";
    const msg = (s && s.reason==="computing")
      ? "Computing KPIs… the first snapshot is being built in the background; this refreshes automatically."
      : "No data yet — waiting for the bot to write guild_log.db.";
    tiles.appendChild(el("div","empty",msg));
    ["#ov-actions","#ov-decisions","#ov-events","#ov-errors","#ov-explore"]
      .forEach(id=>$(id).innerHTML="");
    $("#ov-roster-card").style.display="none"; $("#ov-roster").innerHTML="";
    return;
  }
  const cur = s.current || {}, vol = s.volume || {};
  // The meaningful error number is the CURRENT run's AVOIDABLE rate — the lifetime
  // action_error_rate blends bad old eras, and most errors are the un-fixable
  // phantom-character death-echo. Headline the avoidable slice; show the rest as
  // context so nothing is hidden.
  const ec = s.errors_current || {};
  const avoid = ec.avoidable_rate;
  const errCls = avoid==null ? "" : avoid>0.1 ? "crit" : avoid>0.05 ? "warn" : "good";
  const pct = x => x==null ? "—" : (100*x).toFixed(x<0.1?1:0)+"%";
  // v0.108.2 FIELD TRUTH: prefer the frame-derived per-world counts (fielded_live,
  // truth from our own frame stream) over the server's chars_by_world guild view,
  // which lags by whole minutes and twice read "none fielded" while sentinels were
  // demonstrably out. Falls back to the old view for snapshots that predate it.
  const live = cur.fielded_live || null;
  const byWorld = cur.chars_by_world || {};
  const fielded = live ? Object.values(live).reduce((a,b)=>a+(b.n||0),0)
                       : Object.values(byWorld).reduce((a,b)=>a+b,0);
  const roster = (cur.chars_here||0) + fielded;
  const worldStr = (live
      ? Object.entries(live).filter(([w,d])=>d.n>0).map(([w,d])=>`${w}:${d.n}`)
      : Object.entries(byWorld).map(([w,n])=>`${w}:${n}`)
    ).join("  ") || "none fielded";

  const stat = (k,v,sub,cls)=>{
    const d = el("div","stat");
    d.appendChild(el("div","k",k));
    const vv = el("div","v "+(cls||""), v); d.appendChild(vv);
    if(sub!=null) d.appendChild(el("div","sub",sub));
    return d;
  };
  tiles.innerHTML="";
  tiles.appendChild(stat("Gold", fmtNum(cur.gold), "at tick "+esc(cur.at_tick)));
  tiles.appendChild(stat("Roster", fmtNum(roster), `${cur.chars_here||0} home · ${fielded} fielded`));
  tiles.appendChild(stat("Fielded by world", "", worldStr));
  tiles.appendChild(stat("Decisions", fmtNum(vol.decisions), "traces recorded"));
  tiles.appendChild(stat("Actions sent", fmtNum(vol.actions_sent), fmtNum(vol.action_errors)+" errored"));
  tiles.appendChild(stat("Avoidable error rate",
    avoid==null ? "—" : (100*avoid).toFixed(1)+"%",
    ec.phantom_rate!=null
      ? `run #${esc(ec.run_id)} · ${pct(ec.phantom_rate)} phantom-echo (unfixable) · ${pct(s.action_error_rate)} lifetime`
      : "current run · lower is healthier", errCls));
  tiles.appendChild(stat("Frames", fmtNum(vol.frames),
    "ticks "+(vol.tick_span?vol.tick_span.join("–"):"—")));
  tiles.appendChild(stat("Wall clock", vol.wall_seconds!=null?(vol.wall_seconds+"s"):"—", "observed span"));

  renderRoster(s);

  bars($("#ov-actions"), s.actions_by_kind);
  bars($("#ov-decisions"), s.decisions_by_action);
  bars($("#ov-events"), s.events_by_kind);
  bars($("#ov-errors"), s.action_errors_by_reason);

  // exploration table
  const ex = $("#ov-explore"); ex.innerHTML="";
  const worlds = Object.entries(s.exploration||{});
  if(!worlds.length){ ex.appendChild(el("div","small","no tiles seen yet")); }
  else for(const [w,d] of worlds){
    const row = el("div","bar-row");
    row.appendChild(el("div","lbl", w));
    const track = el("div","bar-track");
    const maxTiles = Math.max(...worlds.map(([,x])=>x.tiles_seen),1);
    const fill = el("div","bar-fill"); fill.style.width=(100*d.tiles_seen/maxTiles)+"%";
    track.appendChild(fill); row.appendChild(track);
    row.appendChild(el("div","num", fmtNum(d.tiles_seen)));
    ex.appendChild(row);
    ex.appendChild(el("div","small",
      `  ↑ max y ${esc(d.max_y_reached)} · ${fmtNum(d.notable_tiles)} notable tiles`));
  }
}

/* ---- ROSTER + INVENTORY (a PARTIAL, swinging server view) ----
   The single-frame roster is not an authoritative headcount: the game server
   shows characters intermittently, so we present "now" against the recent
   min–max range and the frame age, and surface the note, so a dip reads as a
   transient partial view rather than "we lost characters". Handles a
   missing/null roster by hiding the whole card. */
function renderRoster(s){
  const card = $("#ov-roster-card"), body = $("#ov-roster");
  body.innerHTML = "";
  const r = s && s.roster;
  if(!r){ card.style.display = "none"; return; }   // no village frame yet
  card.style.display = "";

  // Headline: "<total> now · range <min>–<max> over last <samples> frames ·
  //            frame <age>s old" — the range/age is what keeps a dip honest.
  const rng = r.range || {}, age = r.frame_age_s;
  const head = el("div","rhead");
  head.appendChild(el("b", null, fmtNum(r.total)+" now"));
  const bits = [];
  if(rng.min!=null && rng.max!=null)
    bits.push(`range ${fmtNum(rng.min)}–${fmtNum(rng.max)} over last ${fmtNum(rng.samples)} frames`);
  if(age!=null) bits.push(`frame ${esc(age)}s old`);
  if(bits.length) head.appendChild(document.createTextNode(" · "+bits.join(" · ")));
  body.appendChild(head);

  // Home count + per-world fielded (counts), each world a pill.
  const worlds = Object.entries(r.by_world || {});
  const wl = el("div","rline");
  wl.appendChild(document.createTextNode(`Home ${fmtNum(r.home)}`));
  if(worlds.length){
    wl.appendChild(document.createTextNode(" · per-world: "));
    for(const [w,n] of worlds) wl.appendChild(el("span","badge", `${esc(w)} ${fmtNum(n)}`));
  } else {
    wl.appendChild(document.createTextNode(" · none fielded"));
  }
  body.appendChild(wl);

  // Aggregate inventory across home chars (already sorted desc by the backend).
  const inv = Object.entries(r.inventory || {});
  const il = el("div","rline");
  il.appendChild(document.createTextNode("Inventory (home chars): "));
  if(inv.length){
    for(const [k,n] of inv) il.appendChild(el("span","badge", `${esc(k)}×${fmtNum(n)}`));
  } else {
    il.appendChild(el("span","small","none carried"));
  }
  body.appendChild(il);

  if(r.note) body.appendChild(el("div","rnote", r.note));

  // Recent bot-detected anomalies, if any (else the line is simply absent).
  const an = (s.anomalies_recent || []);
  if(an.length){
    body.appendChild(el("div","ranom",
      "recent anomalies: " + an.map(x=>`${esc(x.subtype)} ×${fmtNum(x.n)}`).join(" · ")));
  }
}

/* ---- DECISIONS ---- */
let decFilled = false;
async function fillDecisionFilters(){
  if(decFilled) return; decFilled = true;
  const [chars, worlds] = await Promise.all([getJSON("/api/chars"), getJSON("/api/worlds")]);
  const cs = $("#f-char"); (chars||[]).forEach(c=>{
    const o=el("option",null,c); o.value=c; cs.appendChild(o); });
  const ws = $("#f-world"); (worlds||[]).forEach(w=>{
    const o=el("option",null,w); o.value=w; ws.appendChild(o); });
}
let decRows = [];       // rows currently shown, newest-first, capped at the limit
function decCard(d){
  const card = el("div","decision");
  const head = el("div","head");
  head.appendChild(el("span","badge","tick "+esc(d.tick)));
  if(d.world) head.appendChild(el("span","badge",d.world));
  if(d.char_uid) head.appendChild(el("span","badge",d.char_uid));
  head.appendChild(el("span","badge act", d.action || "rest"));
  if(d.strategy_version) head.appendChild(el("span","badge",d.strategy_version));
  card.appendChild(head);
  // reasoning: preserve line breaks via CSS white-space:pre-wrap
  card.appendChild(el("div","reasoning", d.reasoning || "(no reasoning text)"));
  if(d.alternatives && d.alternatives.length){
    const alts = el("div","alts");
    for(const a of d.alternatives){
      const row = el("div","alt"+(a.chosen?" chosen":""));
      const sc = (a.score>=0?"+":"")+Number(a.score).toFixed(1);
      row.appendChild(el("div","score", sc));
      const why = el("div","why");
      const nm = el("span","aname", (a.chosen?"→ ":"")+esc(a.action));
      why.appendChild(nm);
      why.appendChild(document.createTextNode("  "+esc(a.why)));
      row.appendChild(why);
      alts.appendChild(row);
    }
    card.appendChild(alts);
  }
  return card;
}
function renderDecisions(){
  const list = $("#dec-list"); list.innerHTML="";
  $("#dec-count").textContent = decRows.length ? (decRows.length+" shown") : "";
  if(!decRows.length){
    list.appendChild(el("div","empty","No decisions recorded yet.")); return;
  }
  for(const d of decRows) list.appendChild(decCard(d));
}
async function loadDecisions(){
  // Populate the char/world dropdowns in the background — do NOT block the feed
  // on them. The feed itself is a fast indexed query; the dropdown lists come
  // from heavier DISTINCT scans, and awaiting them here used to leave the whole
  // tab blank whenever those were slow.
  fillDecisionFilters();
  const char=$("#f-char").value, world=$("#f-world").value, limit=$("#f-limit").value;
  const qs = new URLSearchParams();
  if(char) qs.set("char",char); if(world) qs.set("world",world); qs.set("limit",limit);
  const rows = await getJSON("/api/decisions?"+qs.toString());
  decRows = Array.isArray(rows) ? rows : [];
  // Cursor = newest seq we now hold (rows are newest-first); the push resumes
  // strictly after it, so no decision is missed or shown twice.
  decCursor = decRows.length ? decRows[0].seq : 0;
  renderDecisions();
  subscribe();
}
// A push carries only decisions newer than the cursor: prepend and trim to limit.
function applyDecisions(msg){
  const fresh = msg.rows || [];
  if(!fresh.length) return;
  decCursor = Math.max(decCursor, fresh[0].seq);
  decRows = fresh.concat(decRows).slice(0, +$("#f-limit").value);
  if(active==="decisions") renderDecisions();
}

/* ---- MAP ---- */
// Terrain colours keyed by tile kind. Known kinds get intuitive fixed hues;
// anything unseen-before falls back to a stable hash into the categorical set,
// so no kind is ever invisible. Kept simple and dependency-free (no atlas).
const TILE_COLORS = {
  floor:"#d9d7cc", path:"#cfc7ad", grass:"#7bbf5a", wall:"#4a4640",
  water:"#2a78d6", tree:"#1f7a34", bush:"#3fa15a", rock:"#8a8078",
  vein:"#eda100", ore:"#eda100", chest:"#eb6834", chest_open:"#b5754e",
  safe:"#4a3aa7", trap:"#e34948", fence:"#9c6b3f", cauldron:"#e87ba4",
  forge:"#d03b3b", lava:"#d03b3b", sand:"#e3cf8f", ice:"#a9d6f0",
  door:"#c98500", stairs:"#9085e9", portal:"#199e70"
};
const FALLBACK = ["#2a78d6","#1baf7a","#eda100","#008300","#4a3aa7","#e34948","#e87ba4","#eb6834"];
function tileColor(kind){
  if(kind in TILE_COLORS) return TILE_COLORS[kind];
  let h=0; for(const ch of (kind||"")) h=(h*31+ch.charCodeAt(0))>>>0;
  return FALLBACK[h % FALLBACK.length];
}
const cssVar = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();

// --- pan/zoom viewer state ------------------------------------------------
// The canvas is a fixed viewport; the world is drawn under an affine transform
// (translate + uniform scale). `view.scale` is screen-pixels-per-tile; `ox/oy`
// is the screen-pixel offset of world-origin (tile col 0, drawn-row 0 = the
// TOP-drawn row, i.e. the northmost). One view is stored PER WORLD so the 3s
// auto-refresh redraws with the operator's current pan/zoom intact — we only
// re-fit when the world changes or Reset is pressed.
let mapData = null;          // last fetched /api/map payload for mapWorld
let mapWorld = null;         // world currently displayed
const mapViews = {};         // world -> {scale, ox, oy}
let mapWired = false;        // interaction handlers attached once
let mapHeat = null, mapHeatWorld = null;   // lazily-fetched /api/heatmap overlay for mapWorld
const HEAT_COLORS = {danger:[255,60,60], death:[220,80,80], occupancy:[70,150,255],
                     monster:[255,150,40], gold:[255,215,0], loot:[150,120,255]};
// Fetch the heat overlay for the current world only when a layer is selected (it decodes
// ~1200 frames, so it's lazy + cached per world), then repaint the map.
async function ensureHeat(){
  const layer = ($("#m-overlay")||{}).value || "";
  const info = $("#hm-info"); if(info) info.textContent = "";
  if(!layer || !mapWorld){ drawMap(); return; }
  if(!mapHeat || mapHeatWorld !== mapWorld){
    if(info) info.textContent = "loading overlay…";
    mapHeat = await getJSON("/api/heatmap?world="+encodeURIComponent(mapWorld));
    mapHeatWorld = mapWorld;
  }
  drawMap();
}
const MIN_SCALE = 0.4, MAX_SCALE = 64;
const clampScale = s => Math.max(MIN_SCALE, Math.min(MAX_SCALE, s));

let mapWorldsFilled=false;
async function fillMapWorlds(){
  if(mapWorldsFilled) return; mapWorldsFilled=true;
  const worlds = await getJSON("/api/worlds");
  const sel=$("#m-world"); sel.innerHTML="";
  (worlds||[]).filter(w=>w!=="village").forEach(w=>{
    const o=el("option",null,w); o.value=w; sel.appendChild(o); });
  // The map may already be drawn (we no longer block on this list) — reflect the
  // world actually on screen so the dropdown and canvas agree.
  if(mapWorld && [...sel.options].some(o=>o.value===mapWorld)) sel.value=mapWorld;
  // Explicit world switch = a fresh frame-the-world view (drop any saved one).
  sel.onchange = ()=>{ delete mapViews[sel.value]; mapWorld=null; loadMap(); };
}

// Screen<->world helpers (row 0 at the BOTTOM: y increases north).
function drawnRow(y, H){ return H-1-y; }                 // world y -> drawn row
function fitView(m){
  const cv=$("#mapCanvas"); const vw=cv.clientWidth||600, vh=cv.clientHeight||400;
  const [W,H]=m.bounds; const pad=14;
  const s = clampScale(Math.min((vw-2*pad)/W, (vh-2*pad)/H));
  mapViews[m.world] = {scale:s, ox:(vw-W*s)/2, oy:(vh-H*s)/2};
}
// Zoom by `factor` while keeping the point (cx,cy) in viewport coords fixed —
// this is the "zoom toward the cursor" behaviour of Google Maps / DynMap.
function zoomAt(cx, cy, factor){
  const v = mapViews[mapWorld]; if(!v) return;
  const ns = clampScale(v.scale*factor); const f = ns/v.scale;
  v.ox = cx - (cx - v.ox)*f;
  v.oy = cy - (cy - v.oy)*f;
  v.scale = ns;
  drawMap();
}

function drawMap(){
  const cv=$("#mapCanvas"); if(!cv) return;
  const ctx=cv.getContext("2d");
  const dpr=window.devicePixelRatio||1;
  const cw=cv.clientWidth, ch=cv.clientHeight;
  cv.width=Math.max(1,Math.round(cw*dpr)); cv.height=Math.max(1,Math.round(ch*dpr));
  ctx.setTransform(dpr,0,0,dpr,0,0);   // work in CSS px; dpr for crispness
  ctx.imageSmoothingEnabled=false;
  ctx.fillStyle=cssVar("--plane")||"#111"; ctx.fillRect(0,0,cw,ch);

  const m=mapData, v=mapViews[mapWorld];
  if(!m || !v) return;
  const [W,H]=m.bounds, s=v.scale, ox=v.ox, oy=v.oy;
  // world tile (x,y) -> screen rect top-left; +0.6 overscan closes seams.
  for(const [x,y,kind] of m.tiles){
    ctx.fillStyle=tileColor(kind);
    ctx.fillRect(x*s+ox, drawnRow(y,H)*s+oy, s+0.6, s+0.6);
  }
  // heat overlay (drawn over terrain, under the moving-thing dots) — same transform
  const hl=($("#m-overlay")||{}).value||"";
  if(hl && mapHeat && mapHeat.world===mapWorld && mapHeat.layers){
    const pts=mapHeat.layers[hl]||[];
    let hmx=1; for(const p of pts) if(p[2]>hmx) hmx=p[2];
    const [cr,cg,cb]=HEAT_COLORS[hl]||[255,255,255];
    for(const [x,y,val] of pts){
      ctx.fillStyle=`rgba(${cr},${cg},${cb},${0.20+0.70*Math.sqrt(val/hmx)})`;   // sqrt: low values visible
      ctx.fillRect(x*s+ox, drawnRow(y,H)*s+oy, s+0.6, s+0.6);
    }
    const info=$("#hm-info");
    if(info){
      const unit = hl==="danger" ? "danger = deaths/time (×100; >100 deadlier than we're present)"
        : hl==="occupancy" ? "time-in-tile" : hl==="death" ? "raw deaths (survivor-biased)"
        : "sightings (sampled)";
      info.textContent = pts.length ? `${pts.length} tiles · max ${hmx} · ${unit}` : "no data for this layer";
    }
  }
  // faint grid only when zoomed in enough to read it, clipped to world extent
  if(s>=8){
    ctx.strokeStyle=cssVar("--grid")||"#333"; ctx.lineWidth=1;
    const L=ox, R=W*s+ox, T=oy, B=H*s+oy;
    ctx.beginPath();
    for(let x=0;x<=W;x++){ const X=Math.round(x*s+ox)+.5; ctx.moveTo(X,T); ctx.lineTo(X,B); }
    for(let y=0;y<=H;y++){ const Y=Math.round(y*s+oy)+.5; ctx.moveTo(L,Y); ctx.lineTo(R,Y); }
    ctx.stroke();
  }
  // overlays from the latest frame; centred on the tile, min radius so they
  // stay visible when zoomed out. Kept aligned via the same transform maths.
  const dot=(x,y,color,rFrac,ring)=>{
    const cx=(x+0.5)*s+ox, cy=(drawnRow(y,H)+0.5)*s+oy, r=Math.max(3,s*rFrac);
    ctx.beginPath(); ctx.arc(cx,cy,r,0,7); ctx.fillStyle=color; ctx.fill();
    if(ring){ ctx.lineWidth=2; ctx.strokeStyle=ring; ctx.stroke(); }
  };
  (m.items||[]).forEach(it=>{ if(it.pos) dot(it.pos[0],it.pos[1],"#eda100",0.3); });
  (m.gold||[]).forEach(g=>{ if(g.pos) dot(g.pos[0],g.pos[1],"#c98500",0.3); });
  (m.entities||[]).forEach(e=>{ if(!e.pos) return;
    dot(e.pos[0],e.pos[1], e.faction==="monster"?"#e34948":"#898781", 0.4); });
  (m.chars||[]).forEach(c=>{ if(c.pos) dot(c.pos[0],c.pos[1],"#2a78d6",0.4,cssVar("--ink")); });
}

// Viewport (mx,my) -> game tile coords, honouring row 0 at the bottom.
function tileAt(mx,my){
  const m=mapData, v=mapViews[mapWorld]; if(!m||!v) return null;
  const [W,H]=m.bounds;
  const tx=Math.floor((mx-v.ox)/v.scale);
  const gy=(H-1)-Math.floor((my-v.oy)/v.scale);
  if(tx<0||tx>=W||gy<0||gy>=H) return null;
  return {x:tx,y:gy};
}

// Attach pan / wheel-zoom / pinch / button handlers exactly once. Uses Pointer
// Events so mouse, touch-drag and two-finger pinch share one code path.
function wireMap(){
  if(mapWired) return; mapWired=true;
  const ov=$("#m-overlay"); if(ov) ov.onchange = ensureHeat;   // toggle the heat overlay
  const cv=$("#mapCanvas"), coords=$("#mapCoords");
  const pointers=new Map();       // active pointerId -> {x,y}
  let pinchDist=0;                 // last two-finger distance, 0 = not pinching

  const showCoords=(mx,my)=>{ const t=tileAt(mx,my);
    coords.textContent = t ? `x ${t.x}, y ${t.y}` : "—"; };

  cv.addEventListener("pointerdown", e=>{
    cv.setPointerCapture(e.pointerId);
    pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});
    if(pointers.size===1) cv.classList.add("grabbing");
    pinchDist=0;
  });
  cv.addEventListener("pointermove", e=>{
    const rect=cv.getBoundingClientRect();
    if(!pointers.has(e.pointerId)){ showCoords(e.clientX-rect.left,e.clientY-rect.top); return; }
    const prev=pointers.get(e.pointerId);
    if(pointers.size>=2){
      // pinch-to-zoom: scale by change in finger distance about their midpoint
      pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});
      const pts=[...pointers.values()];
      const dist=Math.hypot(pts[0].x-pts[1].x, pts[0].y-pts[1].y);
      const midx=(pts[0].x+pts[1].x)/2-rect.left, midy=(pts[0].y+pts[1].y)/2-rect.top;
      if(pinchDist>0 && dist>0) zoomAt(midx,midy, dist/pinchDist);
      pinchDist=dist;
    } else {
      // single-pointer drag = pan
      const v=mapViews[mapWorld];
      if(v){ v.ox += e.clientX-prev.x; v.oy += e.clientY-prev.y; drawMap(); }
      pointers.set(e.pointerId,{x:e.clientX,y:e.clientY});
      showCoords(e.clientX-rect.left,e.clientY-rect.top);
    }
  });
  const endPtr=e=>{ pointers.delete(e.pointerId);
    if(pointers.size<2) pinchDist=0;
    if(pointers.size===0) cv.classList.remove("grabbing"); };
  cv.addEventListener("pointerup", endPtr);
  cv.addEventListener("pointercancel", endPtr);
  cv.addEventListener("pointerleave", e=>{ if(!pointers.has(e.pointerId)) coords.textContent="—"; });

  cv.addEventListener("wheel", e=>{
    e.preventDefault();
    const rect=cv.getBoundingClientRect();
    // smooth exponential stepping; zoom centred on the cursor
    zoomAt(e.clientX-rect.left, e.clientY-rect.top, Math.exp(-e.deltaY*0.0015));
  }, {passive:false});

  $("#m-zin").onclick =()=>zoomAt(cv.clientWidth/2, cv.clientHeight/2, 1.3);
  $("#m-zout").onclick=()=>zoomAt(cv.clientWidth/2, cv.clientHeight/2, 1/1.3);
  $("#m-fit").onclick =()=>{ if(mapData){ fitView(mapData); drawMap(); } };
  // keep the framing sensible if the window resizes while the tab is open
  window.addEventListener("resize", ()=>{ if(active==="map") drawMap(); });
}

async function loadMap(){
  // Populate the world dropdown in the background; draw the map now. With no
  // selection yet the server picks the most-mapped world, so the canvas renders
  // immediately instead of waiting on the (heavier) world-list query.
  fillMapWorlds();
  wireMap();
  const world = $("#m-world").value;
  const m = await getJSON("/api/map"+(world?("?world="+encodeURIComponent(world)):""));
  const info = $("#map-info");
  if(!m || !m.bounds || !m.tiles.length){
    mapData=null; drawMap();
    info.textContent = "no tiles seen for this world yet";
    $("#map-legend").innerHTML=""; $("#mapCoords").textContent="—";
    mapSeq=0; mapTick=-1; subscribe(); return;
  }
  if(world!==m.world && m.world){ // server chose a default; reflect it
    const sel=$("#m-world"); if([...sel.options].some(o=>o.value===m.world)) sel.value=m.world;
  }
  // Index tiles by coordinate so live pushes update in place (bounded memory).
  m.tk = new Map();
  for(const t of m.tiles) m.tk.set(t[0]+","+t[1], t);
  mapData = m;
  mapSeq = m.seq||0; mapTick = (m.tick==null?-1:m.tick);
  // Preserve the view across refreshes: only fit when the world changed (or on
  // the very first draw of a world, when no saved view exists).
  if(mapWorld!==m.world || !mapViews[m.world]){ mapWorld=m.world; fitView(m); }
  if(mapHeatWorld && mapHeatWorld!==mapWorld){ mapHeat=null; mapHeatWorld=null; }  // stale on switch
  drawMap();
  renderMapMeta();
  ensureHeat();          // (re)fetch the overlay for this world if one is selected
  subscribe();
}
function renderMapMeta(){
  const m=mapData; if(!m || !m.bounds) return;
  const [W,H]=m.bounds;
  $("#map-info").textContent = `${m.world} · ${W}×${H} · ${m.tiles.length} tiles seen`
    + (m.tick!=null?` · frame @ tick ${m.tick}`:"");
  // legend: only kinds actually present, plus overlay markers
  const present = [...new Set(m.tiles.map(t=>t[2]))].sort();
  const lg = $("#map-legend"); lg.innerHTML="";
  const addLg = (color,label)=>{ const i=el("div","item");
    const sw=el("span","sw"); sw.style.background=color; i.appendChild(sw);
    i.appendChild(el("span",null,label)); lg.appendChild(i); };
  present.forEach(k=>addLg(tileColor(k), k));
  if((m.entities||[]).length) addLg("#e34948","monster / rival");
  if((m.chars||[]).length) addLg("#2a78d6","our character");
  if((m.items||[]).length || (m.gold||[]).length) addLg("#eda100","loot / gold");
}
// Live map push: merge freshly-seen tiles (by coord — bounded memory), swap in
// the moving overlay, extend bounds, and repaint — never re-pulling the whole map.
function applyMap(msg){
  const m=mapData;
  if(!m || msg.world!==mapWorld){ if(active==="map") loadMap(); return; }
  let grew=false;
  for(const t of (msg.tiles||[])){
    const key=t[0]+","+t[1], ex=m.tk.get(key);
    if(ex){ ex[2]=t[2]; }
    else { m.tk.set(key,t); m.tiles.push(t); grew=true; }
  }
  if(msg.overlay){
    const o=msg.overlay;
    m.tick=o.tick; m.entities=o.entities||[]; m.items=o.items||[];
    m.gold=o.gold||[]; m.chars=o.chars||[];
    if(Array.isArray(o.frame_bounds))
      m.bounds=[Math.max(m.bounds[0],o.frame_bounds[0]),
                Math.max(m.bounds[1],o.frame_bounds[1])];
  }
  if(grew){                      // a new coord may extend the world extent
    let mx=m.bounds[0]-1, my=m.bounds[1]-1;
    for(const t of m.tiles){ if(t[0]>mx)mx=t[0]; if(t[1]>my)my=t[1]; }
    m.bounds=[mx+1,my+1];
  }
  if(msg.cursor){ mapSeq=msg.cursor.seq; mapTick=msg.cursor.tick; }
  if(active==="map"){ drawMap(); renderMapMeta(); }
}

/* ---- RIVAL RECON ---- */
function reconTable(rows, cols){
  const t=el("table","fr-tbl");
  const hd=el("tr"); for(const c of cols) hd.appendChild(el("th",null,c.label));
  t.appendChild(hd);
  for(const r of rows){
    const tr=el("tr", r.us ? "mine" : null);
    for(const c of cols){
      const v=c.get(r);
      tr.appendChild(el("td", null, v===null||v===undefined ? "—" : String(v)));
    }
    t.appendChild(tr);
  }
  return t;
}
async function loadRecon(){
  const d=await getJSON("/api/recon"); if(!d) return;
  const info=$("#recon-info");
  if(info) info.textContent = d.tick
    ? `guild standings from the newest spectate snapshot; rival positions as of tick ${d.tick}`
    : "no intel recorded yet — is the web sidecar running? (./svc.sh up web)";
  const g=$("#recon-guilds"); g.innerHTML="";
  if(!(d.guilds||[]).length){ g.appendChild(el("div","empty","No guild intel yet.")); }
  else g.appendChild(reconTable(d.guilds, [
    {label:"guild", get:r=>r.name + (r.us ? "  (us)" : "")},
    {label:"chars", get:r=>r.characters},
    {label:"level median", get:r=>r.level_median},
    {label:"level max", get:r=>r.level_max},
    {label:"armed", get:r=>`${r.armed}/${r.roster}`},
    {label:"outfitted", get:r=>`${r.outfitted}/${r.roster}`},
    {label:"worlds", get:r=>Object.entries(r.worlds||{}).map(([k,v])=>`${k} ${v}`).join(" · ")},
  ]));
  const w=$("#recon-where"); w.innerHTML="";
  if(!(d.sightings||[]).length) w.appendChild(el("div","empty","No rival sightings recorded."));
  else w.appendChild(reconTable(d.sightings, [
    {label:"world", get:r=>r.world},
    {label:"rivals seen", get:r=>r.seen},
    {label:"depth median", get:r=>r.depth_median},
    {label:"depth max", get:r=>r.depth_max},
  ]));
  const gap=$("#recon-gap"); gap.innerHTML="";
  if(!(d.gear_gap||[]).length) gap.appendChild(el("div","empty","Nothing they field that we do not."));
  else gap.appendChild(reconTable(d.gear_gap, [
    {label:"kind", get:r=>r.kind},
    {label:"rivals fielding", get:r=>r.rivals_fielding},
  ]));
}

/* ---- CODEX ---- */
async function loadNav(){
  const d=await getJSON("/api/nav"); if(!d) return;
  const info=$("#nav-info");
  if(info) info.textContent =
    `every rung below was weighed by ${d.strategy_version||"the strategy"} in the last `+
    `${d.sampled_decisions} decisions (${d.sampled_candidates} candidates, `+
    `${d.sampled_chosen} winners). Branches that never fired in that window are absent, not zero.`;
  const lad=$("#nav-ladder");
  if(lad){
    const rows=(d.ladder||[]).map(r=>{
      const pct=Math.round((r.win_rate||0)*100);
      return `<tr><td class="num">${r.score.toFixed(1)}</td><td>${escHtml(r.label)}</td>`+
             `<td class="num">${r.considered}</td><td class="num">${pct}%</td>`+
             `<td class="small">${escHtml(r.example||"")}</td></tr>`;
    }).join("");
    lad.innerHTML = `<h3>The priority ladder — what a character weighs each tick</h3>`+
      `<p class="small">A character scores every legal move it can see and takes the highest. `+
      `Higher rungs are survival (retreat, fight what is on top of it); the low rungs are what `+
      `it does when nothing urgent is happening (push a frontier, scout, rest). "Won" is how `+
      `often that candidate beat everything else it was up against.</p>`+
      `<table class="grid"><thead><tr><th>score</th><th>branch</th><th>weighed</th>`+
      `<th>won</th><th>example reason</th></tr></thead><tbody>${rows}</tbody></table>`;
  }
  const ru=$("#nav-rules");
  if(ru){
    const rules=d.rules||{};
    const dirs=Object.entries(rules.dirs||{}).map(([k,v])=>`${k} = (${v[0]}, ${v[1]})`).join(" · ");
    const solid=(rules.solid||[]).map(s=>`<code>${escHtml(s)}</code>`).join(" ");
    const fns=(rules.functions||[]).map(f=>
      `<h4><code>${escHtml(f.name)}()</code></h4><pre class="doc">${escHtml(f.doc)}</pre>`).join("");
    ru.innerHTML = `<h3>The map rules</h3>`+
      `<p class="small">Read live out of <code>steemer/nav.py</code> at page load — these are the `+
      `values and the wording the running planner uses, not a copy that can drift.</p>`+
      `<p><b>Steps</b> (cardinal only; diagonals are gear-gated): ${escHtml(dirs)}</p>`+
      `<p><b>Blocking tiles</b>: ${solid}</p>`+
      `<pre class="doc">${escHtml(rules.module_doc||"")}</pre>${fns}`;
  }
}

const FR_GLYPH = {frontier: "\u2605", tried: "\u00b7", unlikely: ""};   // star, middot, blank

async function loadFrontier(){
  const el = $("#cx-frontier"); if(!el) return;
  el.innerHTML = '<div class="small">building the frontier…</div>';
  const d = await getJSON("/api/matrix");
  if(!d || d.ok === false){
    el.innerHTML = `<div class="small">frontier unavailable: ${escHtml((d&&d.reason)||"error")}</div>`;
    return;
  }
  const sent = new Set(d.verbs_sent || []);
  const bar = (d.verbs_all||[]).map(v =>
    `<i class="${sent.has(v)?"sent":""}" title="${escHtml(v)}${sent.has(v)?"":" — never sent"}"></i>`).join("");

  // The frontier is only useful while it is SMALL: six cells is a work queue, three hundred
  // is another wall of data. Say the number loudly so that degradation is visible.
  const fr = d.frontier || [];
  const rows = fr.map(c => `<tr>
      <td class="p">${c.prior.toFixed(2)}</td>
      <td class="fr-cell">${escHtml(c.noun)} &times; ${escHtml(c.verb)}${
          c.equipped && c.equipped!=="any" ? " &times; "+escHtml(c.equipped) : ""}</td>
      <td class="small">${escHtml(c.why)}</td></tr>`).join("");

  const g = d.grid || {rows:[], verbs:[], counts:{}};
  let lastGroup = null, body = "";
  for(const r of g.rows){
    if(r.group !== lastGroup){
      lastGroup = r.group;
      body += `<tr><th class="fr-group" colspan="${g.verbs.length+1}">${escHtml(r.group)}</th></tr>`;
    }
    body += `<tr><th class="n">${escHtml(r.noun)}</th>` + r.cells.map(c => {
      const errs = Object.keys(c.errors||{}).length
        ? " — errors: " + Object.entries(c.errors).map(([k,v])=>`${k} x${v}`).join(", ") : "";
      return `<td class="${c.state}" title="${escHtml(r.noun+" × "+c.verb)} — ${c.state}, prior ${c.prior}\n${escHtml(c.why)}${escHtml(errs)}">${FR_GLYPH[c.state]}</td>`;
    }).join("") + "</tr>";
  }

  el.innerHTML = `
    <h3>What we have never tried</h3>
    <p class="small">A cube of every noun &times; verb &times; equipped item we have observed —
      ${(d.cells_total||0).toLocaleString()} cells — scored for plausibility and crossed against
      everything we have actually sent. The equip axis is collapsed here: it varies only
      <code>attack</code>, <code>charge</code>, <code>throw</code> and <code>cast</code>, and shows in a cell's tooltip.</p>
    <p><b>${(d.verbs_never||[]).length} of ${(d.verbs_all||[]).length} protocol verbs have never been sent:</b>
       ${(d.verbs_never||[]).map(v=>`<code>${escHtml(v)}</code>`).join(" ")}</p>
    <div class="fr-bar">${bar}</div>
    <div class="small">each segment is one protocol verb; filled = we have sent it</div>

    <h3>The frontier — ${fr.length} untried cell${fr.length===1?"":"s"} at prior &ge; ${d.min_prior}</h3>
    <p class="small">Ranked most plausible first. This list is only useful while it is SHORT;
      if it grows into the hundreds the priors have gone loose and want re-tuning, not scrolling.</p>
    ${fr.length ? `<table class="fr-tbl"><thead><tr><th>prior</th><th>cell</th><th>why</th></tr></thead>
      <tbody>${rows}</tbody></table>`
      : '<div class="small">nothing untried above the threshold — either we have been thorough or the priors are too strict.</div>'}

    <h3>Coverage</h3>
    <div class="fr-legend">
      <span><i class="fr-key frontier">${FR_GLYPH.frontier}</i> never tried, plausible</span>
      <span><i class="fr-key tried">${FR_GLYPH.tried}</i> verb has been sent</span>
      <span><i class="fr-key unlikely"></i> never tried, implausible</span>
      <span class="small">${g.counts.frontier||0} / ${g.counts.tried||0} / ${g.counts.unlikely||0}</span>
    </div>
    <p class="small">&ldquo;Sent&rdquo; means we have issued that verb somewhere — not that it worked.
      There is no reliable per-cell success signal yet, so the grid does not claim one; a cell's
      tooltip carries the error breakdown where we have it.</p>
    <div class="fr-grid"><table><thead><tr><th></th>${
      g.verbs.map(v=>`<th class="v">${escHtml(v)}</th>`).join("")}</tr></thead>
      <tbody>${body}</tbody></table></div>`;
}

let codexData=null, codexWired=false;
async function loadCodex(){
  if(!codexWired){ codexWired=true;
    // The pane list is DERIVED from the buttons, not hardcoded. It used to be
    // ["monsters","lands","items","mechanics"], so adding the Frontier pane left it
    // permanently hidden — the button worked, the data loaded, and nothing appeared.
    // A list that has to be kept in sync by hand is the same failure shape as the rest of
    // today's regressions; the DOM already knows the answer.
    const cxPanes = [...document.querySelectorAll("#tab-codex .cx-btn")].map(b=>b.dataset.cx);
    const cxLoaders = {frontier: loadFrontier};
    document.querySelectorAll("#tab-codex .cx-btn").forEach(b=>{
      b.onclick=()=>{
        document.querySelectorAll("#tab-codex .cx-btn").forEach(x=>x.classList.toggle("active",x===b));
        const pane=b.dataset.cx;
        cxPanes.forEach(p=>{ const e=$("#cx-"+p); if(e) e.hidden=(p!==pane); });
        const load=cxLoaders[pane]; if(load) load();
      };
    });
  }
  const mon=$("#cx-monsters"); if(mon && !codexData) mon.innerHTML='<div class="small">building the codex from recent data… (first load of a run takes a few seconds)</div>';
  const d=await getJSON("/api/codex");
  codexData=d;
  renderCodex(d);
  // the codex builds off-thread (once per run); re-fetch until it's ready.
  if(d && d.computing && active==="codex") setTimeout(()=>{ if(active==="codex") loadCodex(); }, 1500);
}
function renderCodex(d){
  if(!d) return;
  const info=$("#cx-info");
  if(info) info.textContent = d.computing ? "building the codex… (updates when ready)"
    : (d.generated_run!=null ? ("from run #"+d.generated_run+" · "+(d.frames_sampled||0)+" frames") : "");
  const mon=$("#cx-monsters");
  if(mon){ mon.innerHTML="";
    if(!(d.monsters||[]).length){ mon.appendChild(el("div","empty","No monsters observed yet.")); }
    else{ const g=el("div","cx-grid");
      d.monsters.forEach(m=>{ const c=el("div","cx-card");
        c.innerHTML='<div class="cx-h"><span class="cx-t">'+esc(m.kind)+'</span>'
          +'<span class="cx-cls cls-'+esc(m["class"])+'">'+esc(m["class"])+'</span></div>'
          +'<div class="cx-b">'+esc(m.behavior||"?")
          +(m.est_dmg_per_hit!=null?(' · <b>'+esc(m.est_dmg_per_hit)+'</b> dmg/hit'):'')
          +(m.aggro_range!=null?(' · aggro '+esc(m.aggro_range)):'')
          +(m.chaser_score!=null?(' · chase '+esc(m.chaser_score)):'')
          +'<br><span class="k">'+esc(m.sightings)+' sightings · '+esc(m.individuals)+' seen</span></div>';
        g.appendChild(c); });
      mon.appendChild(g); } }
  const lands=$("#cx-lands");
  if(lands){ lands.innerHTML="";
    if(!(d.lands||[]).length){ lands.appendChild(el("div","empty","No lands mapped yet.")); }
    else{ const g=el("div","cx-grid");
      d.lands.forEach(l=>{
        const terr=(l.terrain||[]).slice(0,10).map(t=>'<span class="chip">'+esc(t.kind)+' '+esc(t.count)+'</span>').join("");
        const mobs=(l.mob_kinds||[]).map(k=>'<span class="chip">'+esc(k)+'</span>').join("")||'<span class="k">—</span>';
        const c=el("div","cx-card");
        c.innerHTML='<div class="cx-h"><span class="cx-t">'+esc(l.world)+'</span>'
          +'<span class="k">'+(l.size?esc(l.size[0])+'×'+esc(l.size[1]):'?')+' · '+esc(l.deaths)+' deaths</span></div>'
          +'<div class="cx-b"><div class="k">terrain</div>'+terr
          +'<div class="k" style="margin-top:6px">mobs seen</div>'+mobs+'</div>';
        g.appendChild(c); });
      lands.appendChild(g); } }
  const items=$("#cx-items");
  if(items){ items.innerHTML="";
    if(!(d.items||[]).length){ items.appendChild(el("div","empty","No items seen yet.")); }
    else{ const g=el("div","cx-grid");
      d.items.forEach(i=>{ const c=el("div","cx-card cx-item");
        c.innerHTML='<span class="cx-t">'+esc(i.kind)+'</span> <span class="cx-cls cls-item">'+esc(i.type)+'</span> <span class="k">×'+esc(i.count)+'</span>';
        g.appendChild(c); });
      items.appendChild(g); } }
  const mech=$("#cx-mechanics");
  if(mech){ mech.innerHTML=""; const M=d.mechanics||{}; const w=el("div","cx-mech");
    w.appendChild(el("h3",null,"Game rules (docs)"));
    (M.docs||[]).forEach(doc=>{ const r=el("div","cx-doc");
      r.innerHTML='<span class="cx-t">'+esc(doc.title)+'</span> <span class="k">'+esc(doc.summary||"")+'</span>';
      w.appendChild(r); });
    w.appendChild(el("h3",null,"What we've learned"));
    (M.learnings||[]).forEach(x=>{ const r=el("div","cx-doc"); r.innerHTML='<span>'+esc(x.title)+'</span>'; w.appendChild(r); });
    mech.appendChild(w); }
}

/* ---- TIMELINE ---- */
async function loadTimeline(){
  const [s, story] = await Promise.all([getJSON("/api/snapshot"), getJSON("/api/story")]);
  renderTimeline(s);
  renderStory(story);
  if(s && s.ok && s.version!=null) snapVersion = s.version;
  subscribe();
}
function renderStory(story){
  const box = $("#tl-story"); if(!box) return; box.innerHTML="";
  if(!story || !story.length){ box.appendChild(el("div","empty","No version story yet.")); return; }
  // consideration/shipped = the hypothesis; measurement/discovery/correction = the effect.
  const roleOf = k => (k==="consideration") ? "hyp"
    : (k==="measurement"||k==="discovery"||k==="correction"||k==="diagnosis") ? "eff" : "note";
  const roleLabel = {hyp:"shipped", eff:"measured", note:"note"};
  for(const v of story){
    const node = el("div","sv");
    node.appendChild(el("div","sv-ver","explorer/"+esc(v.version)));
    const items = el("div","sv-items");
    for(const e of v.entries){
      const role = roleOf(e.kind);
      const row = el("div","sv-item "+role);
      row.appendChild(el("span","sv-tag "+role, roleLabel[role]));
      row.appendChild(el("span","sv-title", esc(e.title)||"(untitled)"));
      items.appendChild(row);
    }
    node.appendChild(items);
    box.appendChild(node);
  }
}
function renderTimeline(s){
  const list = $("#tl-list"); list.innerHTML="";
  const runs = (s && s.ok && s.runs) ? s.runs : [];
  if(!runs.length){
    const computing = s && !s.ok && s.reason==="computing";
    list.appendChild(el("div","empty", computing
      ? "Computing… building the first KPI snapshot; this refreshes automatically."
      : "No runs recorded yet."));
    return; }
  const fmtTime = t => t==null ? "—" : new Date(t*1000).toLocaleString();
  // newest last in table; show newest first in the timeline
  for(const r of [...runs].reverse()){
    const wrap = el("div","run");
    const line = el("div","line"); line.appendChild(el("div","node")); wrap.appendChild(line);
    const body = el("div","body");
    body.appendChild(el("h3", `run #${r.run_id} · ${esc(r.strategy_version)||"?"}`));
    const meta = el("div","meta");
    const cell = (label,val,cls)=>{ const s=el("span"); s.appendChild(document.createTextNode(label+" "));
      const b=el("b",cls,val); s.appendChild(b); return s; };
    meta.appendChild(cell("sha", (r.git_sha||"—").slice(0,10)));
    meta.appendChild(cell("started", fmtTime(r.started_at)));
    meta.appendChild(cell("stopped", r.stopped_at?fmtTime(r.stopped_at):"running"));
    meta.appendChild(cell("frames", fmtNum(r.frames)));
    meta.appendChild(cell("actions", fmtNum(r.actions_sent)));
    const er = r.action_error_rate;
    meta.appendChild(cell("err rate", er==null?"—":(100*er).toFixed(1)+"%"));
    const gd = r.gold_delta;
    const gdCell = cell("gold Δ", gd==null?"—":(gd>0?"+":"")+fmtNum(gd),
                        gd==null?"":("delta "+(gd>=0?"up":"down")));
    meta.appendChild(gdCell);
    body.appendChild(meta);
    if(r.note) body.appendChild(el("div","small",r.note));
    wrap.appendChild(body);
    list.appendChild(wrap);
  }
}

/* ---- LOGS ---- */
$("#log-name").onchange = loadLogs;
async function loadLogs(){
  const name = $("#log-name").value;
  const r = await getJSON("/api/log?name="+encodeURIComponent(name));
  $("#log-body").textContent = r ? (r.text||"(empty)") : "(failed to load)";
  logName = name; logSize = (r && r.size!=null) ? r.size : 0;
  subscribe();
}
// Live log push: append the streamed tail (or replace on rotation), advancing the
// byte cursor so a reconnect resumes at the right offset.
function applyLog(msg){
  if(msg.name!==$("#log-name").value) return;   // a different file is selected now
  const body=$("#log-body");
  if(msg.full!=null){ body.textContent = msg.full || "(empty)"; }
  else if(msg.append){
    if(body.textContent==="(empty)") body.textContent="";
    body.textContent += msg.append;
  }
  if(msg.cursor){ logName=msg.cursor.name; logSize=msg.cursor.size; }
}

/* ---- FINDINGS ---- */
// Confidence may be a word or a 0..1 number; render both as a short label.
function confLabel(c){
  if(c==null||c==="") return null;
  if(typeof c==="number") return "conf "+Math.round(c*100)+"%";
  return "conf "+c;
}
function fmtDate(s){ if(!s) return "—"; const d=new Date(s);
  return isNaN(d) ? String(s) : d.toLocaleString(); }

let findingsRaw = [];          // last fetched notebook (unfiltered)
let findingsFiltersBuilt = false;
function buildFindingFilters(rows){
  // Populate status + tag dropdowns from the data, preserving any current pick.
  const statuses=[...new Set(rows.map(r=>r.status).filter(Boolean))].sort();
  const tags=[...new Set(rows.flatMap(r=>r.tags||[]))].sort();
  const fill=(sel,vals)=>{ const cur=sel.value;
    sel.innerHTML="<option value=''>all</option>";
    vals.forEach(v=>{ const o=el("option",null,v); o.value=v; sel.appendChild(o); });
    if(vals.includes(cur)) sel.value=cur; };
  fill($("#fx-status"),statuses); fill($("#fx-tag"),tags);
}
function renderFindings(){
  const kind=$("#fx-kind").value, status=$("#fx-status").value,
        tag=$("#fx-tag").value, q=$("#fx-q").value.trim().toLowerCase();
  // newest-updated first (fall back to created)
  const rows=[...findingsRaw].sort((a,b)=>
    String(b.updated||b.created||"").localeCompare(String(a.updated||a.created||"")));
  const list=$("#find-list"); list.innerHTML="";
  let shown=0;
  for(const f of rows){
    if(kind && f.kind!==kind) continue;
    if(status && f.status!==status) continue;
    if(tag && !(f.tags||[]).includes(tag)) continue;
    if(q){ const hay=((f.title||"")+" "+(f.detail||"")).toLowerCase();
      if(!hay.includes(q)) continue; }
    shown++;
    const card=el("div","finding k-"+esc(f.kind)+" "+esc(f.status));
    card.appendChild(el("h3","ftitle", f.title||"(untitled)"));
    const badges=el("div","fbadges");
    if(f.kind) badges.appendChild(el("span","fbadge kind", f.kind));
    if(f.status) badges.appendChild(el("span","fbadge st-"+esc(f.status), f.status));
    const cl=confLabel(f.confidence);
    if(cl) badges.appendChild(el("span","fbadge conf", cl));
    card.appendChild(badges);
    if(f.detail) card.appendChild(el("div","fdetail", f.detail));
    // Evidence matters most for discoveries; the falsification test for
    // conjectures — surface each in its own labelled block.
    const block=(cls,label,text)=>{ const b=el("div","block "+cls);
      b.appendChild(el("span","lab",label));
      b.appendChild(document.createTextNode(text)); return b; };
    if(f.evidence) card.appendChild(block("evidence","evidence", f.evidence));
    if(f.test) card.appendChild(block("test","test · how it'd be falsified", f.test));
    if((f.tags||[]).length){
      const tw=el("div","ftags");
      (f.tags||[]).forEach(t=>{ const s=el("span","tag", t);
        s.onclick=()=>{ $("#fx-tag").value=t; renderFindings(); }; tw.appendChild(s); });
      card.appendChild(tw);
    }
    card.appendChild(el("div","ffoot","updated "+fmtDate(f.updated||f.created)));
    list.appendChild(card);
  }
  if(!shown) list.appendChild(el("div","empty",
    findingsRaw.length ? "No findings match these filters." : "No findings yet."));
  $("#fx-count").textContent = shown+" / "+findingsRaw.length+" shown";
}
/* ---- Party (per-character stats) ---- */
let partyTimer=null;
async function loadParty(){
  await renderParty();
  clearInterval(partyTimer);
  partyTimer = setInterval(()=>{
    if(active==="party") renderParty();
    else { clearInterval(partyTimer); partyTimer=null; }
  }, 2000);
}
async function renderParty(){
  const res = await getJSON("/api/roster");
  const chars = (res && Array.isArray(res.chars)) ? res.chars : [];
  const meta=$("#party-meta"), grid=$("#party-cards");
  if(!grid) return;
  if(!chars.length){ if(meta) meta.textContent=""; grid.innerHTML='<div class="empty">no characters observed yet</div>'; return; }
  const byWorld={}; chars.forEach(c=>{ byWorld[c.world]=(byWorld[c.world]||0)+1; });
  if(meta) meta.textContent = chars.length+" characters — "+Object.entries(byWorld).map(([w,n])=>n+" in "+w).join(", ");
  grid.innerHTML = chars.map(pcCard).join("");
}
function pcBar(cls,val,max,label){
  const pct = max ? Math.max(0,Math.min(100,Math.round(100*val/max))) : 0;
  return '<div class="bar-lbl"><span>'+label+'</span><span>'+esc(val)+'/'+esc(max)+'</span></div>'
    +'<div class="bar '+cls+'"><span style="width:'+pct+'%"></span></div>';
}
function pcCard(c){
  const hpPct = c.max_hp ? 100*c.hp/c.max_hp : 0;
  const hpCls = hpPct>=60?"hp-ok":hpPct>=30?"hp-warn":"hp-crit";
  const stats = Object.entries(c.stats||{}).map(([k,v])=>{
    const g=(c.gifts||[]).includes(k);
    return '<span class="pc-stat'+(g?" gift":"")+'"><span class="k">'+esc(k)+'</span> <b>'+esc(v)+'</b>'+(g?"★":"")+'</span>';
  }).join("");
  const eq=c.equipment||{};
  const eqStr=["hand","offhand","outfit","trinket","boots"].map(s=> eq[s]?esc(eq[s]):"—").join(" · ");
  const inv=(c.inventory||[]);
  const invStr = inv.length ? inv.map(k=>'<span class="chip">'+esc(k)+'</span>').join("") : '<span class="k">empty</span>';
  const status=(c.status||[]).map(s=>{
    const p=/pois|burn|venom|bleed/.test(String(s));
    return '<span class="chip'+(p?" pois":"")+'">'+esc(s)+'</span>';
  }).join("");
  const carry=c.carry||{};
  return '<div class="pc">'
    +'<div class="pc-head"><span class="pc-name">'+esc(c.name)+'</span>'
      +(c.role?('<span class="pc-role role-'+esc(c.role)+'" title="risk role: guardians disengage early, foragers work the edges, wizards (int-gifted) are protected at any level, fodder (bottom rolls) is expendable, nuisance shadows WillMorr party in the vale">'+esc(c.role)+'</span>'):"")
      +'<span class="pc-where">'+esc(c.world)+(c.pos?(" ("+esc(c.pos[0])+","+esc(c.pos[1])+")"):"")+'</span></div>'
    + pcBar(hpCls, c.hp, c.max_hp, "HP")
    + (c.max_stamina!=null ? pcBar("sta", c.stamina, c.max_stamina, "Stamina") : "")
    +'<div class="pc-stats">'+stats+'</div>'
    +(status?('<div class="pc-row"><span class="k">status</span> '+status+'</div>'):"")
    +'<div class="pc-row"><span class="k">lvl</span> '+esc(c.level)+' · <span class="k">xp</span> '+esc(c.xp)
      +' · <span class="k">carry</span> '+esc(carry.used)+'/'+esc(carry.cap)+'</div>'
    +'<div class="pc-row"><span class="k">gear</span> '+eqStr+'</div>'
    +'<div class="pc-row"><span class="k">inv</span> '+invStr+'</div>'
    +(c.latest_decision?('<div class="pc-dec">'+esc(c.latest_decision)+'</div>'):"")
    +'</div>';
}

async function loadFindings(){
  const res = await getJSON("/api/findings");
  const rows = (res && res.rows) ? res.rows : (Array.isArray(res)?res:[]);
  findingsRaw = Array.isArray(rows) ? rows : [];
  findMtime = (res && res.mtime!=null) ? res.mtime : null;
  buildFindingFilters(findingsRaw);
  if(!findingsFiltersBuilt){ findingsFiltersBuilt=true;
    ["#fx-kind","#fx-status","#fx-tag"].forEach(id=>$(id).onchange=renderFindings);
    $("#fx-q").oninput=renderFindings; }
  renderFindings();
  await loadObserved();
  subscribe();
}
// Live findings push carries whichever source advanced: the authored notebook
// (rows) and/or the auto-derived observed block.
function applyFindings(msg){
  if(msg.rows){ findingsRaw = Array.isArray(msg.rows)?msg.rows:[];
    buildFindingFilters(findingsRaw); if(active==="findings") renderFindings(); }
  if(msg.observed){ renderObserved(msg.observed); }
  if(msg.cursor){
    if(msg.cursor.mtime!=null) findMtime=msg.cursor.mtime;
    if(msg.cursor.version!=null) obsVersion=msg.cursor.version;
  }
}
function obsTable(rows, cols){
  const t=el("table"); const thead=el("tr");
  cols.forEach(c=>thead.appendChild(el("th",null,c.h))); t.appendChild(thead);
  if(!rows.length){ const tr=el("tr"); const td=el("td",null,"—");
    td.colSpan=cols.length; tr.appendChild(td); t.appendChild(tr); return t; }
  for(const r of rows){ const tr=el("tr");
    cols.forEach(c=>{ const td=el("td",c.cls||null); td.textContent=c.get(r); tr.appendChild(td); });
    t.appendChild(tr); }
  return t;
}
async function loadObserved(){
  const o = await getJSON("/api/observed");
  if(o && o.version!=null) obsVersion = o.version;
  renderObserved(o);
}
function renderObserved(o){
  const ev=$("#obs-events"), er=$("#obs-errors"), ex=$("#obs-explore");
  ev.innerHTML=""; er.innerHTML=""; ex.innerHTML="";
  if(!o || !o.ok){
    ev.appendChild(el("div","small","no data yet"));
    er.appendChild(el("div","small","no data yet"));
    ex.appendChild(el("div","small","no data yet")); return;
  }
  ev.appendChild(obsTable(o.event_first_seen||[], [
    {h:"kind", get:r=>r.kind||"(none)", cls:"k"},
    {h:"first tick", get:r=>fmtNum(r.first_tick)},
    {h:"count", get:r=>fmtNum(r.n)} ]));
  er.appendChild(obsTable(o.error_reasons||[], [
    {h:"reason", get:r=>r.reason||"(none)", cls:"k"},
    {h:"count", get:r=>fmtNum(r.n)} ]));
  const rows=Object.entries(o.exploration||{}).map(([w,d])=>({w,...d}));
  ex.appendChild(obsTable(rows, [
    {h:"world", get:r=>r.w, cls:"k"},
    {h:"max y", get:r=>fmtNum(r.max_y_reached)},
    {h:"tiles seen", get:r=>fmtNum(r.tiles_seen)},
    {h:"notable", get:r=>fmtNum(r.notable_tiles)} ]));
}

/* ---- filters: a change is a fresh REST load, which re-subscribes with the new
   params + cursor. ---- */
["#f-char","#f-world","#f-limit"].forEach(id=>$(id).onchange = loadDecisions);

/* auto-refresh toggle: unchecking sends a paused subscription (the server then
   pushes nothing); re-checking does a fresh load to catch up and re-subscribes. */
$("#autorefresh").onchange = ()=>{ if($("#autorefresh").checked) loadActive(); else subscribe(); };

/* ---- live push: subscribe to the active view; apply the data the server sends ----
   REST answers "give me this view" (first paint / tab switch / filter change /
   fallback). The socket then streams ONLY what is newer for that view — actual
   data, never a "go fetch" nudge — which we apply in place. */
let ws=null, wsBackoff=1000, pollTimer=null;

// The subscription for the current view: tab, filter params, and the cursor
// (watermark) we already hold. Paused (auto-refresh off) => tab:null, so the
// server sends nothing until we resume.
function currentSub(){
  if(!$("#autorefresh").checked) return {t:"sub", tab:null};
  if(active==="decisions") return {t:"sub", tab:"decisions",
     params:{char:$("#f-char").value, world:$("#f-world").value, limit:+$("#f-limit").value},
     cursor:{seq:decCursor}};
  if(active==="map") return {t:"sub", tab:"map",
     params:{world: mapWorld||""}, cursor:{seq:mapSeq, tick:mapTick}};
  if(active==="overview"||active==="timeline") return {t:"sub", tab:active,
     cursor:{version:snapVersion}};
  if(active==="findings") return {t:"sub", tab:"findings",
     cursor:{mtime:findMtime, version:obsVersion}};
  if(active==="logs") return {t:"sub", tab:"logs",
     params:{name:$("#log-name").value}, cursor:{name:logName, size:logSize}};
  return {t:"sub", tab:null};
}
function subscribe(){ if(ws && ws.readyState===1) ws.send(JSON.stringify(currentSub())); }

function applySnapshot(msg){
  const d=msg.data;
  if(d && d.version!=null) snapVersion=d.version;
  else if(msg.cursor && msg.cursor.version!=null) snapVersion=msg.cursor.version;
  if(active==="overview") renderOverview(d);
  else if(active==="timeline") renderTimeline(d);
}
function applyPush(msg){
  if(!$("#autorefresh").checked) return;     // frozen; a fresh load will resync
  if(msg.t==="decisions") applyDecisions(msg);
  else if(msg.t==="map") applyMap(msg);
  else if(msg.t==="snapshot") applySnapshot(msg);
  else if(msg.t==="findings") applyFindings(msg);
  else if(msg.t==="log") applyLog(msg);
}

function startPollFallback(){
  // No socket: fall back to a slow REST reload of the active tab (which also
  // re-subscribes — a no-op until the socket returns).
  if(pollTimer) return;
  pollTimer=setInterval(()=>{ if($("#autorefresh").checked) loadActive(); }, 5000);
}
function stopPollFallback(){ if(pollTimer){ clearInterval(pollTimer); pollTimer=null; } }
function connectWS(){
  let sock;
  try{
    const proto = location.protocol==="https:" ? "wss:" : "ws:";
    sock = new WebSocket(proto+"//"+location.host+"/ws");
  }catch(e){ startPollFallback(); setTimeout(connectWS, wsBackoff); return; }
  ws = sock;
  sock.onopen=()=>{ wsBackoff=1000; stopPollFallback(); subscribe(); };
  sock.onmessage=(ev)=>{ let msg; try{ msg=JSON.parse(ev.data); }catch(e){ return; } applyPush(msg); };
  sock.onclose=()=>{
    if(ws===sock) ws=null;
    startPollFallback();
    setTimeout(connectWS, wsBackoff);
    wsBackoff=Math.min(wsBackoff*2, 15000);
  };
  sock.onerror=()=>{ try{ sock.close(); }catch(e){} };
}

/* first paint: REST-load the active tab, then open the socket and subscribe. */
loadActive();
connectWS();
</script>
</body>
</html>
"""


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="0.0.0.0",
                    help="bind address (default 0.0.0.0 — LAN-accessible)")
    ap.add_argument("--port", type=int, default=8800, help="port (default 8800)")
    ap.add_argument("--db", default=None,
                    help="SQLite path override; else use --config/config.toml")
    ap.add_argument("--config", default=None, help="path to config.toml")
    args = ap.parse_args()

    db_cfg = {"type": "sqlite", "path": args.db} if args.db \
        else _db.load_db_config(args.config)
    Handler.db_config = db_cfg
    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    ready = "ready" if _db_ready(db_cfg) else "no data yet (will show empty state)"
    print(f"steemer dashboard on http://{args.host}:{args.port}  "
          f"db={_db.cfg_key(db_cfg)} [{ready}]  (WebSocket push at /ws)")

    # Two background threads: the push loop sends each subscribed client the
    # actual new data for its current view once a second (the WebSocket carries
    # the data, not a "go fetch" nudge), and the snapshot worker recomputes the
    # heavy KPI aggregate off the request path so /api/snapshot never hangs a
    # connection (and never starves the rest).
    stop = threading.Event()
    pusher = threading.Thread(
        target=_push_loop, args=(db_cfg, stop), name="ws-push", daemon=True)
    snapper = threading.Thread(
        target=_snapshot_worker, args=(db_cfg, stop), name="snapshot-worker", daemon=True)
    pusher.start()
    snapper.start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nshutting down")
    finally:
        stop.set()
        httpd.server_close()


if __name__ == "__main__":
    main()
