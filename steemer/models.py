"""Stdlib-only scorer for the exported JSON models — the live half of the ML pipeline.

Training happens in a Linux reaper session with sklearn; what ships is data: JSON trees
and coefficients under ``models/``, walked here with nothing but the standard library.
The bot's runtime gains no dependencies, and a model is deployed the way everything else
in this project is deployed — by commit, with a birth certificate.

FAIL-CLOSED, absolutely: every public function returns ``None`` on ANY defect — file
absent, JSON malformed, schema version mismatch, missing feature, non-finite output,
stale training date. ``None`` means "the ladder decides exactly as it always has".
A model can only ever ADD information; it can never be the reason the bot breaks.

Export conventions (mirrored by tools/train_models.py, pinned by tests):
  * a tree node is ``{"f": <feature index>, "t": <threshold>, "l": <node>, "r": <node>}``;
    a leaf is ``{"v": <value>}``. LEFT is ``x[f] <= t``.
  * binary GBM: ``score = base + sum(tree values)``, probability = sigmoid(score),
    then optional isotonic calibration as a step-function lookup {"x": [...], "y": [...]}
    (bisect_right; clamped to the outer steps).
  * multiclass GBM: ``trees[stage][class]``; per-class scores softmaxed.
  * logistic: ``{classes, coef[class][i], intercept[class]}``, softmax over dots.
"""

from __future__ import annotations

import json
import math
import os
import time
from bisect import bisect_right
from typing import Any

from steemer import mlfeat

MODELS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                          "models")
STALE_DAYS = 60          # manual retraining is the process; silence must not rot into it

_cache: dict[str, Any] = {}
_warned: set[str] = set()


def _warn_once(name: str, why: str) -> None:
    if name not in _warned:
        _warned.add(name)
        print(f"[models] {name} disabled: {why}", flush=True)


def _load(name: str) -> dict | None:
    if name in _cache:
        return _cache[name]
    path = os.path.join(MODELS_DIR, f"{name}.json")
    meta_path = os.path.join(MODELS_DIR, f"{name}.meta.json")
    try:
        with open(path, encoding="utf-8") as fh:
            model = json.load(fh)
        with open(meta_path, encoding="utf-8") as fh:
            meta = json.load(fh)
    except (OSError, json.JSONDecodeError) as e:
        _warn_once(name, f"unreadable ({e.__class__.__name__})")
        _cache[name] = None
        return None
    if model.get("schema_version") != mlfeat.FEATURE_SCHEMA_VERSION:
        _warn_once(name, f"schema {model.get('schema_version')} != "
                         f"{mlfeat.FEATURE_SCHEMA_VERSION}")
        _cache[name] = None
        return None
    trained = meta.get("trained_at_epoch")
    if isinstance(trained, (int, float)) and \
            time.time() - trained > STALE_DAYS * 86400:
        _warn_once(name, f"stale (> {STALE_DAYS} days)")
        _cache[name] = None
        return None
    model["_meta"] = meta
    _cache[name] = model
    return model


def _walk(node: dict, x: list[float]) -> float:
    while "v" not in node:
        node = node["l"] if x[node["f"]] <= node["t"] else node["r"]
    return float(node["v"])


def _sigmoid(z: float) -> float:
    if z < -60:
        return 0.0
    if z > 60:
        return 1.0
    return 1.0 / (1.0 + math.exp(-z))


def _softmax(zs: list[float]) -> list[float]:
    m = max(zs)
    es = [math.exp(z - m) for z in zs]
    s = sum(es)
    return [e / s for e in es]


def _calibrate(p: float, cal: dict | None) -> float:
    if not cal:
        return p
    xs, ys = cal.get("x") or [], cal.get("y") or []
    if not xs or len(xs) != len(ys):
        raise ValueError("malformed calibration")
    i = bisect_right(xs, p) - 1
    return float(ys[max(0, min(i, len(ys) - 1))])


def score_death_risk(features: dict[str, float]) -> float | None:
    """Calibrated P(death within the primary window) for one character, or None."""
    try:
        m = _load("death_risk")
        if m is None:
            return None
        x = mlfeat.vector(features, tuple(m["feature_names"]))
        z = float(m["base_score"]) + sum(_walk(t, x) for t in m["trees"])
        p = _calibrate(_sigmoid(z), m.get("calibration"))
        if not (0.0 <= p <= 1.0) or not math.isfinite(p):
            raise ValueError("out of range")
        return p
    except Exception as e:                            # noqa: BLE001 — fail closed, always
        _warn_once("death_risk", f"scoring failed ({e.__class__.__name__})")
        return None


def score_band(features: dict[str, float]) -> dict[str, float] | None:
    try:
        m = _load("band_forecast")
        if m is None:
            return None
        x = mlfeat.vector(features, tuple(m["feature_names"]))
        zs = [float(m["intercept"][k]) + sum(c * v for c, v in zip(m["coef"][k], x))
              for k in range(len(m["classes"]))]
        ps = _softmax(zs)
        if any(not math.isfinite(p) for p in ps):
            raise ValueError("non-finite")
        return dict(zip(m["classes"], ps))
    except Exception as e:                            # noqa: BLE001
        _warn_once("band_forecast", f"scoring failed ({e.__class__.__name__})")
        return None


def score_mob(features: dict[str, float]) -> dict[str, float] | None:
    try:
        m = _load("mob_move")
        if m is None:
            return None
        x = mlfeat.vector(features, tuple(m["feature_names"]))
        zs = []
        for k in range(len(m["classes"])):
            z = float(m["base_scores"][k])
            for stage in m["trees"]:
                z += _walk(stage[k], x)
            zs.append(z)
        ps = _softmax(zs)
        if any(not math.isfinite(p) for p in ps):
            raise ValueError("non-finite")
        return dict(zip(m["classes"], ps))
    except Exception as e:                            # noqa: BLE001
        _warn_once("mob_move", f"scoring failed ({e.__class__.__name__})")
        return None


def load_profiles() -> dict:
    """The frozen bestiary snapshot for runtime feature parity. Fail-closed to {} —
    an unprofiled world scores with zero mob priors rather than not at all."""
    if "_profiles" in _cache:
        return _cache["_profiles"]
    try:
        with open(os.path.join(MODELS_DIR, "bestiary_snapshot.json"), encoding="utf-8") as fh:
            snap = json.load(fh)
        if snap.get("schema_version") != mlfeat.FEATURE_SCHEMA_VERSION:
            raise ValueError("snapshot schema mismatch")
        _cache["_profiles"] = snap.get("kinds") or {}
    except Exception as e:                            # noqa: BLE001
        _warn_once("bestiary_snapshot", f"unavailable ({e.__class__.__name__})")
        _cache["_profiles"] = {}
    return _cache["_profiles"]


def available(name: str) -> bool:
    """Is a scoreable artifact deployed? Lets the bot skip feature computation entirely
    when nothing would consume it."""
    return _load(name) is not None


def reset_cache() -> None:
    """Test hook: models are otherwise cached for the process lifetime."""
    _cache.clear()
    _warned.clear()
