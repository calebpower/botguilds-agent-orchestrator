"""Feature and label functions for the offline models — the SINGLE SOURCE OF TRUTH.

This module is imported by BOTH sides of the pipeline:

  * ``tools/extract_features.py`` inside the Linux training session, to turn recorded
    frames into training rows;
  * ``steemer/models.py`` inside the live FreeBSD bot, to score the same features at
    decision time.

That is the whole design: feature parity between training and serving is enforced by
construction (one implementation), and then *proven* anyway by the shadow parity checker
(``tools/check_shadow_parity.py``), because "enforced by construction" has failed this
project before (0.55.0 hydration: same map, two readers, different beliefs).

Rules for this file, stated so a future edit cannot miss them:
  * stdlib only — no numpy, no sklearn, no DB, no I/O. The bot imports this on FreeBSD
    where none of those exist; purity is asserted by a test.
  * every feature function returns floats keyed by a FIXED name tuple. The trainer and
    the scorer both iterate those tuples; adding a feature means bumping
    FEATURE_SCHEMA_VERSION, which fail-closes every deployed model until retrained.
  * deterministic: same inputs, same outputs, no clocks, no randomness.
"""

from __future__ import annotations

import math
from typing import Any

FEATURE_SCHEMA_VERSION = 1

# Distances are capped so "nothing visible" is a finite, learnable value rather than an
# outlier the trees waste splits on.
DIST_CAP = 30.0
REFRESH_CAP = 2000.0

DOT_KINDS = frozenset({"poison", "burn"})   # mirrors explorer.DOT_KINDS; a test pins them

WORLDS = ("vale", "mines", "spire")

DEATH_FEATURES = (
    "hp_frac", "stamina_frac", "dot_active", "n_statuses", "has_heal", "carry_frac",
    "level", "stat_total", "depth_y",
    "world_vale", "world_mines", "world_spire",
    "n_mobs_w1", "n_mobs_w3", "n_mobs_w6", "sum_chaser_w6", "n_elite_w6",
    "nearest_mob_dist", "nearest_mob_chaser", "nearest_mob_dph",
    "n_allies_w3",
    "next_refresh_in", "band_undead_frac", "band_melee_preds",
)

BAND_FEATURES = (
    "world_vale", "world_mines", "world_spire",
    "prev1_danger", "prev2_danger", "prev3_danger", "prev4_danger",
    "ticks_since_refresh",
)

MOB_FEATURES = (
    "move_rate", "chaser_score", "dph", "hit_rate",
    "beh_chaser", "beh_skittish", "beh_wanderer", "beh_stationary",
    "dist_nearest_char", "n_chars_w12", "dormant", "elite",
    "hp_frac",
)

MOB_MOVE_CLASSES = ("stay", "toward", "away", "perp_left", "perp_right")


# ---------------------------------------------------------------------------
# frame normalisation
# ---------------------------------------------------------------------------

def normalize_frame(decoded: dict[str, Any]) -> dict[str, Any]:
    """A richer sibling of ``bestiary.normalize_frame``: same mob shape (delegated), but
    chars keep the survival fields death-risk needs (stamina, heal, carry, level, stats).
    Village frames normalise to empty lists, harmlessly."""
    from steemer import bestiary            # local import keeps this module's import
    base = bestiary.normalize_frame(decoded)   # graph free of heavyweight modules
    chars = []
    for c in decoded.get("chars") or []:
        pos = c.get("pos")
        if pos is None or not c.get("char_uid"):
            continue
        inv = c.get("inventory") or []
        carry = c.get("carry") or {}
        chars.append({
            "uid": c["char_uid"],
            "pos": (pos[0], pos[1]),
            "hp": c.get("hp"), "max_hp": c.get("max_hp"),
            "stamina": c.get("stamina"), "max_stamina": c.get("max_stamina"),
            "statuses": [s.get("kind") for s in (c.get("statuses") or []) if s.get("kind")],
            "has_heal": any(i.get("kind") == "potion_red" for i in inv),
            "carry_used": carry.get("used"), "carry_cap": carry.get("cap"),
            "level": c.get("level"), "stats": dict(c.get("stats") or {}),
        })
    return {"world": base["world"], "tick": base["tick"],
            "chars": chars, "mobs": base["mobs"]}


def _manhattan(a, b) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def _frac(num, den) -> float:
    try:
        if not den:
            return 0.0
        return max(0.0, min(1.0, float(num) / float(den)))
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# death risk
# ---------------------------------------------------------------------------

def death_risk_features(char: dict[str, Any], nframe: dict[str, Any],
                        profiles: dict[str, dict], band: dict[str, Any]) -> dict[str, float]:
    """Features for one of OUR characters at one tick.

    ``char`` is an entry of ``normalize_frame()['chars']``; ``profiles`` is the frozen
    bestiary snapshot (kind -> {chaser_score, move_rate, dph, hit_rate, behavior});
    ``band`` carries {next_refresh_in, undead_frac, melee_preds} from whatever context
    the caller tracks (the extractor derives it from frames; the bot already holds it).
    Unknown mob kinds contribute zeros — an unprofiled mob must not crash scoring, and
    zero is the honest prior for "never measured".
    """
    pos = char["pos"]
    mobs = nframe.get("mobs") or []
    dists = [(_manhattan(pos, m["pos"]), m) for m in mobs]
    within = lambda r: [dm for dm in dists if dm[0] <= r]
    nearest = min(dists, key=lambda dm: dm[0]) if dists else None
    def prof(m, key):
        p = profiles.get(m["kind"]) or {}
        v = p.get(key)
        return float(v) if isinstance(v, (int, float)) else 0.0
    allies = [c for c in nframe.get("chars") or [] if c["uid"] != char["uid"]]
    stats = char.get("stats") or {}
    world = nframe.get("world")
    f = {
        "hp_frac": _frac(char.get("hp"), char.get("max_hp")),
        "stamina_frac": _frac(char.get("stamina"), char.get("max_stamina")),
        "dot_active": 1.0 if any(s in DOT_KINDS for s in char.get("statuses") or []) else 0.0,
        "n_statuses": float(len(char.get("statuses") or [])),
        "has_heal": 1.0 if char.get("has_heal") else 0.0,
        "carry_frac": _frac(char.get("carry_used"), char.get("carry_cap")),
        "level": float(char.get("level") or 0),
        "stat_total": float(sum(v for v in stats.values() if isinstance(v, (int, float)))),
        "depth_y": float(pos[1]),
        "world_vale": 1.0 if world == "vale" else 0.0,
        "world_mines": 1.0 if world == "mines" else 0.0,
        "world_spire": 1.0 if world == "spire" else 0.0,
        "n_mobs_w1": float(len(within(1))),
        "n_mobs_w3": float(len(within(3))),
        "n_mobs_w6": float(len(within(6))),
        "sum_chaser_w6": float(sum(prof(m, "chaser_score") for _, m in within(6))),
        "n_elite_w6": float(sum(1 for _, m in within(6) if m.get("elite"))),
        "nearest_mob_dist": float(min(nearest[0], DIST_CAP)) if nearest else DIST_CAP,
        "nearest_mob_chaser": prof(nearest[1], "chaser_score") if nearest else 0.0,
        "nearest_mob_dph": prof(nearest[1], "dph") if nearest else 0.0,
        "n_allies_w3": float(sum(1 for a in allies if _manhattan(pos, a["pos"]) <= 3)),
        "next_refresh_in": float(min(band.get("next_refresh_in") or REFRESH_CAP, REFRESH_CAP)),
        "band_undead_frac": float(band.get("undead_frac") or 0.0),
        "band_melee_preds": float(band.get("melee_preds") or 0.0),
    }
    assert set(f) == set(DEATH_FEATURES)
    return f


def death_label(uid: str, tick: int, death_index: dict[str, list[int]], k: int) -> int:
    """1 iff this character dies within the NEXT k ticks: any death tick d with
    tick < d <= tick + k. The frame OF the death itself is labelled by the preceding
    ticks, not by itself (at tick == d the character is already dead in the event
    stream; the decision that mattered was earlier)."""
    return int(any(tick < d <= tick + k for d in death_index.get(uid, ())))


# ---------------------------------------------------------------------------
# band forecast
# ---------------------------------------------------------------------------

DANGER_CLASSES = ("calm", "melee", "undead")


def band_danger_class(undead_frac: float, melee_preds: float,
                      undead_severe: float = 0.35, melee_dense: float = 2.0) -> str:
    """The label function: the same shape the explorer's severity gates use. Undead
    dominance outranks melee density (an undead band is the one that kills wizards)."""
    if undead_frac >= undead_severe:
        return "undead"
    if melee_preds >= melee_dense:
        return "melee"
    return "calm"


def band_features(world: str, history: list[str], ticks_since_refresh: int) -> dict[str, float]:
    """``history`` is the previous danger classes for this world, newest FIRST."""
    def code(cls):
        return float(DANGER_CLASSES.index(cls)) if cls in DANGER_CLASSES else -1.0
    h = list(history) + ["calm"] * 4
    f = {
        "world_vale": 1.0 if world == "vale" else 0.0,
        "world_mines": 1.0 if world == "mines" else 0.0,
        "world_spire": 1.0 if world == "spire" else 0.0,
        "prev1_danger": code(h[0]), "prev2_danger": code(h[1]),
        "prev3_danger": code(h[2]), "prev4_danger": code(h[3]),
        "ticks_since_refresh": float(min(ticks_since_refresh, REFRESH_CAP)),
    }
    assert set(f) == set(BAND_FEATURES)
    return f


# ---------------------------------------------------------------------------
# mob next-move
# ---------------------------------------------------------------------------

def _canonical(vec: tuple[int, int], toward: tuple[int, int]) -> tuple[float, float]:
    """Rotate ``vec`` into the frame whose +x axis points along ``toward`` (the
    direction from mob to nearest char). Makes the move classes translation- and
    rotation-invariant, so one model serves every approach angle."""
    tx, ty = toward
    norm = math.hypot(tx, ty)
    if norm == 0:
        return (float(vec[0]), float(vec[1]))
    ux, uy = tx / norm, ty / norm
    return (vec[0] * ux + vec[1] * uy, -vec[0] * uy + vec[1] * ux)


def mob_move_class(prev_pos, next_pos, nearest_char_pos) -> str:
    """Classify an observed one-step move relative to the nearest character."""
    if next_pos == prev_pos:
        return "stay"
    move = (next_pos[0] - prev_pos[0], next_pos[1] - prev_pos[1])
    toward = (nearest_char_pos[0] - prev_pos[0], nearest_char_pos[1] - prev_pos[1])
    cx, cy = _canonical(move, toward)
    if abs(cx) >= abs(cy):
        return "toward" if cx > 0 else "away"
    return "perp_left" if cy > 0 else "perp_right"


def mob_features(mob: dict[str, Any], nframe: dict[str, Any],
                 profile: dict[str, Any]) -> dict[str, float]:
    pos = mob["pos"]
    chars = [c for c in nframe.get("chars") or []]
    dists = [_manhattan(pos, c["pos"]) for c in chars]
    beh = (profile or {}).get("behavior") or ""
    def pv(key):
        v = (profile or {}).get(key)
        return float(v) if isinstance(v, (int, float)) else 0.0
    f = {
        "move_rate": pv("move_rate"),
        "chaser_score": pv("chaser_score"),
        "dph": pv("dph"),
        "hit_rate": pv("hit_rate"),
        "beh_chaser": 1.0 if beh == "chaser" else 0.0,
        "beh_skittish": 1.0 if beh == "skittish" else 0.0,
        "beh_wanderer": 1.0 if beh == "wanderer" else 0.0,
        "beh_stationary": 1.0 if beh == "stationary" else 0.0,
        "dist_nearest_char": float(min(min(dists), DIST_CAP)) if dists else DIST_CAP,
        "n_chars_w12": float(sum(1 for d in dists if d <= 12)),
        "dormant": 1.0 if mob.get("dormant") else 0.0,
        "elite": 1.0 if mob.get("elite") else 0.0,
        "hp_frac": float(mob.get("hp_frac") if isinstance(mob.get("hp_frac"), (int, float)) else 1.0),
    }
    assert set(f) == set(MOB_FEATURES)
    return f


def vector(features: dict[str, float], names: tuple[str, ...]) -> list[float]:
    """The dict->ordered-list bridge both trainer and scorer use. A missing name is a
    schema violation, not a default — raise, because silence here is exactly the
    training/serving skew this module exists to prevent."""
    return [float(features[n]) for n in names]
