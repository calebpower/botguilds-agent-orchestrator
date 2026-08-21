"""Mob move prediction — turn the bestiary's behaviour CLASS into a next-tile predictor.

The bestiary (:mod:`steemer.bestiary`) learns, per mob kind, whether it chases, how often
it moves (``move_rate``), and how reliably a move closes on a character (``chaser_score``).
This packages that into a usable prediction the strategy can act on ("where will this
predator be next tick, so I can dodge into the gap or line up a safe attack for XP") and,
crucially, a way to MEASURE how good the prediction is — an accurate predictor is proof we
understand the mechanic.

Pure core (:func:`predict`) + an offline accuracy check (:func:`evaluate`) over recorded
frames, so the claim is testable and never tautological (it scores predictions against what
actually happened next, not against the profile it came from).
"""
from __future__ import annotations

from typing import Any, Iterable

_DIRS = [(0, 1), (0, -1), (1, 0), (-1, 0)]


def _manhattan(a, b) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _nearest(pos, chars):
    best, bd = None, None
    for c in chars:
        d = _manhattan(pos, c)
        if bd is None or d < bd:
            best, bd = c, d
    return best, bd


def _step_toward(a, b):
    """The neighbour of ``a`` that most reduces distance to ``b`` (one greedy tile)."""
    best, bd = a, _manhattan(a, b)
    for dx, dy in _DIRS:
        n = (a[0] + dx, a[1] + dy)
        d = _manhattan(n, b)
        if d < bd:
            best, bd = n, d
    return best


def predict(profile: dict[str, Any], mob_pos, char_positions) -> dict[str, Any]:
    """Predict a mob's NEXT-tick position from its bestiary ``profile`` (``behavior``,
    ``move_rate``, ``chaser_score``) and the current character positions.

    Returns ``{predicted, move_prob, toward, confidence}``:
    * ``predicted`` — the single best-guess next tile.
    * ``move_prob`` — P(it moves at all) ≈ ``move_rate``.
    * ``toward`` — the tile a chaser steps to WHEN it moves (None if not a chaser / no char).
    * ``confidence`` — high / medium / low.
    """
    mr = profile.get("move_rate") or 0.0
    behavior = profile.get("behavior")
    mob_pos = (mob_pos[0], mob_pos[1])
    if behavior == "stationary" or not char_positions:
        # barely moves -> best guess is "stays put", and we're fairly sure of it
        return {"predicted": mob_pos, "move_prob": mr, "toward": None,
                "confidence": "high" if behavior == "stationary" else "low"}
    target, _ = _nearest(mob_pos, [(c[0], c[1]) for c in char_positions])
    if behavior == "chaser":
        toward = _step_toward(mob_pos, target)
        cs = profile.get("chaser_score") or 0.0
        # it moves ~move_rate of ticks; predict the step only if it moves more often than not.
        return {"predicted": toward if mr >= 0.5 else mob_pos, "move_prob": mr,
                "toward": toward, "confidence": "high" if cs >= 0.7 else "medium"}
    # wanderer / skittish: it moves, but not reliably toward a char -> best single guess is stay
    return {"predicted": mob_pos, "move_prob": mr, "toward": None, "confidence": "low"}


def evaluate(bestiary: dict[str, dict], frames: Iterable[dict]) -> dict[str, Any]:
    """Accuracy of :func:`predict` over an ordered stream of NORMALISED frames (the
    :func:`steemer.bestiary.normalize_frame` shape). For every consecutive same-eid, same-
    world observation with a character in view, predict tick T's next tile from the profile
    and compare to what the mob ACTUALLY did at T+1. Reports overall and per-behaviour:
    * ``exact`` — predicted tile == actual next tile.
    * ``toward_when_moved`` — of the ticks it moved, fraction it moved toward the nearest
      char (the chaser claim), i.e. the directional accuracy the tactics rely on.
    """
    from collections import Counter
    last: dict[Any, dict] = {}
    tot = Counter(); exact = Counter(); moved = Counter(); toward = Counter()
    for fr in frames:
        world, tick = fr.get("world"), fr.get("tick")
        chars = [c["pos"] for c in fr.get("chars") or []]
        for m in fr.get("mobs") or []:
            eid, kind, pos = m["eid"], m["kind"], m["pos"]
            prev = last.get(eid)
            prof = bestiary.get(kind)
            if prev is not None and prof is not None and prev["world"] == world \
                    and tick is not None and 0 < (tick - prev["tick"]) <= 3 and prev["chars"]:
                pr = predict(prof, prev["pos"], prev["chars"])
                b = prof.get("behavior") or "?"
                tot[b] += 1
                if tuple(pr["predicted"]) == (pos[0], pos[1]):
                    exact[b] += 1
                if pos != prev["pos"]:
                    moved[b] += 1
                    nt, _ = _nearest(prev["pos"], prev["chars"])
                    if _manhattan(pos, nt) < _manhattan(prev["pos"], nt):
                        toward[b] += 1
            last[eid] = {"world": world, "tick": tick, "pos": pos, "chars": chars}

    def rate(a, b):
        return round(a / b, 3) if b else None
    per = {}
    for b in tot:
        per[b] = {"n": tot[b], "exact": rate(exact[b], tot[b]),
                  "toward_when_moved": rate(toward[b], moved[b]), "moves": moved[b]}
    T = sum(tot.values())
    return {"samples": T, "exact": rate(sum(exact.values()), T),
            "toward_when_moved": rate(sum(toward.values()), sum(moved.values()) or 0),
            "by_behavior": per}
