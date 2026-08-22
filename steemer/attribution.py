"""Attribution-safe measurement. Ask questions here, not in ad-hoc SQL.

Named `attribution` rather than `metrics` because `steemer/metrics.py` already
exists and computes the loop's KPI snapshot. This module answers a different
question — WHOSE events these are, and whether the run is old enough to ask.

This module exists because of a measured failure rate, not a style preference. Across one
24-hour stretch the loop produced SIX attribution errors, every one of them from a hand-written
query that computed a number before establishing what the number counted:

  * a reported forge success rate of 35% -> 68% that counted RIVAL forges (retracted)
  * two "it has stopped entirely" alarms taken minutes after a deploy (both false)
  * a "97% of opportunities missed" figure comparing a stateful bot to a stateless replay
  * a blind spot sized from SIGHTINGS rather than distinct tiles (overstated ~100x)
  * a near-revert of a good change on numbers confounded by a loot-band shift

`orchestrator/loop.md` already carried a "Metric attribution" section through all of it, and
memory already warned that death queries count rivals. A directive that cannot fail does not
change behaviour; a function signature does. So:

  * `ours_only` DEFAULTS TO TRUE everywhere, and excluding it takes a deliberate argument
  * anything run-scoped raises `TooEarly` below MIN_MATURE_FRAMES
  * `compare()` will not hand back a delta without the band context beside it
  * `distinct_entities()` exists so "how many" is never answered with "how often"

The rule this replaces: ad-hoc SQL for a number you intend to REPORT is a defect.
"""

from __future__ import annotations

import json
import zlib
from typing import Any, Iterable

# A run younger than this cannot support a claim that something changed or stopped. Sized
# from the same evidence as `shadow.MIN_DECISIONS`: v0.48.0 was declared inert from 28
# offers and was not, and two more false alarms came from minutes-old samples. ~20k frames
# is roughly a quarter-hour of play at the rate this bot runs.
MIN_MATURE_FRAMES = 20_000

# A band shift moves loot density by an order of magnitude WITHIN a single run (measured:
# 0.052 -> 1.839 -> 0.002 items/frame). Two runs whose densities differ by more than this
# ratio are not comparable on any income metric without saying so.
BAND_COMPARABLE_RATIO = 1.5


class TooEarly(RuntimeError):
    """Raised when a run has not accumulated enough frames to support a claim."""


class Unattributed(RuntimeError):
    """Raised when we cannot establish which characters are ours."""


_EID_CACHE: dict[tuple[int, int], set[int]] = {}


def _decode(payload: Any) -> dict:
    if isinstance(payload, (bytes, bytearray)) and payload[:1] == b"x":
        payload = zlib.decompress(payload)
    return json.loads(payload)


def run_exists(conn, run_id: int) -> bool:
    """Is there such a run at all?

    Worth its own function because `frame_count` answers 0 for a run that never existed and
    for a run that recorded nothing, and a silent zero is the exact hazard this module is
    here to remove. Callers that must tell "no data" from "no such thing" ask this first.
    """
    cur = conn.execute("SELECT 1 FROM runs WHERE run_id=? LIMIT 1", (run_id,))
    return cur.fetchone() is not None


def frame_count(conn, run_id: int) -> int:
    # Through the Connection wrapper (`?` placeholders, dialect-translated) rather than a
    # raw cursor: raw `%s` is MariaDB-only and would make this module untestable on SQLite.
    cur = conn.execute("SELECT COUNT(*) FROM frames WHERE run_id=?", (run_id,))
    return cur.fetchone()[0]


def require_mature(conn, run_id: int, min_frames: int = MIN_MATURE_FRAMES) -> int:
    """Refuse to answer about a run too young to have an answer.

    The two false "it has stopped" alarms both came from sampling within minutes of a
    deploy. This turns that into an exception instead of a paragraph in a report.
    """
    n = frame_count(conn, run_id)
    if n < min_frames:
        raise TooEarly(
            f"run {run_id} has {n} frames, under {min_frames}: too young to support a "
            f"claim about what changed. Wait, or pass min_frames= deliberately.")
    return n


def our_eids(conn, run_id: int) -> set[int]:
    """The `eid`s belonging to OUR characters in this run.

    Event streams (`forged`, `death`, `sale`, `xp`) are WORLD-WIDE: they carry every guild's
    activity. `eid` and `char_uid` are different namespaces, so ownership can only be
    established by reading our own characters out of the frames.
    """
    key = (id(conn), run_id)
    if key in _EID_CACHE:
        return _EID_CACHE[key]
    cur = conn.execute("SELECT json FROM frames WHERE run_id=?", (run_id,))
    eids: set[int] = set()
    for (payload,) in cur.fetchall():
        for ch in _decode(payload).get("chars") or []:
            if ch.get("eid") is not None:
                eids.add(ch["eid"])
    if not eids:
        raise Unattributed(f"run {run_id} shows no characters of ours; cannot attribute")
    _EID_CACHE[key] = eids
    return eids


def events(conn, run_id: int, kind: str, ours_only: bool = True) -> list[dict]:
    """Event payloads of one kind. OURS ONLY unless you say otherwise, out loud."""
    cur = conn.execute("SELECT payload_json FROM events WHERE run_id=? AND kind=?",
                       (run_id, kind))
    rows = [json.loads(p) for (p,) in cur.fetchall()]
    if not ours_only:
        return rows
    mine = our_eids(conn, run_id)
    guild = our_guild_id(conn)
    out = []
    for r in rows:
        # Two ownership channels, because the server uses both: `eid` on character events
        # and `guild_id` on guild events such as `sale`.
        if r.get("eid") is not None:
            if r["eid"] in mine:
                out.append(r)
        elif guild is not None and r.get("guild_id") == guild:
            out.append(r)
    return out


def our_guild_id(conn) -> str | None:
    """Derived from the newest per-character decision's `char_uid` (`<guild_id>_c<n>`),
    never hardcoded.

    The WHERE clause is the fix for a FLAKY oracle (2026-08-23). Guild-level decisions —
    recruit, embark — are recorded with char_uid NULL, and there are 476k of them, so the
    bare "newest row" read returned None whenever the live bot's last write happened to be
    one. That made `rate_per(..., "sale")` answer 0.0 on roughly one call in three, and the
    claims ledger — whose whole job is to catch wrong numbers — reported a CONTRADICTED
    claim against data that had not changed. An attribution oracle that races the live
    bot's write head is worse than a wrong one: it cries wolf exactly as often as the
    village loop acts.
    """
    cur = conn.execute("SELECT char_uid FROM decisions "
                       "WHERE char_uid IS NOT NULL AND char_uid != '' "
                       "ORDER BY seq DESC LIMIT 1")
    row = cur.fetchone()
    if not row or not row[0]:
        return None
    parts = str(row[0]).split("_")
    return "_".join(parts[:2]) if len(parts) >= 2 else None


def rate_per(conn, run_id: int, kind: str, per: int = 10_000,
             ours_only: bool = True, mature: bool = True) -> float:
    """Events of `kind` per `per` frames, attributed to us by default."""
    n = require_mature(conn, run_id) if mature else frame_count(conn, run_id)
    return len(events(conn, run_id, kind, ours_only)) * per / max(n, 1)


def distinct_entities(conn, run_id: int, kind: str, key: str = "eid",
                      ours_only: bool = True) -> int:
    """How MANY, not how OFTEN.

    The frame stream re-reports the same entity every tick, so a raw event count answers
    "how many sightings" — which once made 22 chests look like thousands.
    """
    return len({r.get(key) for r in events(conn, run_id, kind, ours_only)
                if r.get(key) is not None})


def band_context(conn, run_id: int) -> dict[str, Any]:
    """Loot density for the run — the confounder that invalidates most income comparisons."""
    cur = conn.execute("SELECT json FROM frames WHERE run_id=?", (run_id,))
    items = 0
    frames = 0
    for (payload,) in cur.fetchall():
        f = _decode(payload)
        frames += 1
        items += len((f.get("visible") or {}).get("items") or [])
    return {"frames": frames, "items_per_frame": items / max(frames, 1)}


def compare(conn, run_a: int, run_b: int, kind: str, per: int = 10_000,
            ours_only: bool = True) -> dict[str, Any]:
    """Two runs on one metric, WITH the band context and an explicit comparability verdict.

    There is no way to get the delta out of this function without the confounder beside it.
    That is the entire design: a near-revert of a good change came from comparing runs whose
    loot density differed by 2.7x.
    """
    a = {"run": run_a, "rate": rate_per(conn, run_a, kind, per, ours_only),
         **band_context(conn, run_a)}
    b = {"run": run_b, "rate": rate_per(conn, run_b, kind, per, ours_only),
         **band_context(conn, run_b)}
    lo, hi = sorted((a["items_per_frame"], b["items_per_frame"]))
    ratio = (hi / lo) if lo > 0 else float("inf")
    comparable = ratio <= BAND_COMPARABLE_RATIO
    return {
        "kind": kind, "a": a, "b": b,
        "delta": b["rate"] - a["rate"],
        "band_ratio": ratio,
        "comparable": comparable,
        "verdict": ("comparable" if comparable else
                    f"NOT COMPARABLE: loot density differs {ratio:.1f}x — this delta is "
                    f"confounded by the band, not attributable to a change"),
    }

# --- decision shares --------------------------------------------------------------------
#
# The trap this exists to close, paid for on 2026-08-22: v0.72.0 was justified by "cohesion
# was 25% of ALL DECISIONS on run #150". It was not. 25% was the share of decision traces in
# which cohesion appeared as a CANDIDATE — counting every tick it was offered and LOST. The
# share where it was actually CHOSEN was 11.6%. Offered and chosen are different questions
# with the same-sounding English name, and the wrong one overstated the problem twofold.
#
# Both are legitimate measurements. `offered` sizes how often a behaviour competes, `chosen`
# sizes what it costs. So both are here, neither is the default, and the caller has to say
# which it means.

def decision_share(conn, run_id: int, needle: str, chosen: bool = True,
                   mature: bool = True) -> float:
    """Fraction of this run's decisions in which `needle` names a candidate's reason.

    `chosen=True` counts only the candidate that WON the tick; `chosen=False` counts a
    mention anywhere in the trace, losing candidates included. They are not
    interchangeable — see above.

    Reads the `chosen` flag out of `alternatives_json` rather than pattern-matching
    `decisions.reasoning`. That column stores the WHOLE trace — "saw:", every weighed
    candidate, then "chose:" — so a LIKE against it answers "was this behaviour offered",
    never "was it taken", no matter which of the two you meant. The first draft of this
    function made exactly that substitution, which is the same error one layer down from
    the one it was written to prevent.
    """
    if mature:
        require_mature(conn, run_id)
    rows = conn.execute("SELECT alternatives_json FROM decisions WHERE run_id=?",
                        (run_id,)).fetchall()
    if not rows:
        return 0.0
    hits = 0
    for (blob,) in rows:
        if not blob or needle not in blob:
            continue          # cheap pre-filter; the parse below is the actual test
        try:
            cands = json.loads(blob)
        except (TypeError, ValueError):
            continue
        if any(needle in (c.get("why") or "") and (c.get("chosen") or not chosen)
               for c in cands):
            hits += 1
    return hits / len(rows)
