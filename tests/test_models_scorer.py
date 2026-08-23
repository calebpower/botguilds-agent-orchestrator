"""The stdlib scorer (ML Pass 2) — hand-computed oracle, fail-closed everything.

Two oracle strategy per the house ethic: (1) the HAND ORACLE in this file — a two-tree
model small enough to walk on paper, every expected number derived in the comments;
(2) the SKLEARN PARITY fixture (tests/fixtures/models/) generated inside the training
session by tools/gen_model_fixtures.py and asserted by test_sklearn_parity below —
that half skips until the fixture lands and then never regresses.
"""
import json
import math
import os
import time

import pytest

from steemer import mlfeat, models


@pytest.fixture()
def mdir(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "MODELS_DIR", str(tmp_path))
    models.reset_cache()
    yield tmp_path
    models.reset_cache()


def _write(mdir, name, model, meta=None):
    model.setdefault("schema_version", mlfeat.FEATURE_SCHEMA_VERSION)
    with open(os.path.join(mdir, f"{name}.json"), "w") as fh:
        json.dump(model, fh)
    with open(os.path.join(mdir, f"{name}.meta.json"), "w") as fh:
        json.dump(meta or {"trained_at_epoch": time.time()}, fh)


# ---- the hand oracle -----------------------------------------------------------
#
# Model: features (a, b); base_score = -1.0
#   tree1: if a <= 0.5 -> +0.4 else -0.2
#   tree2: if b <= 2.0 -> (if a <= 0.1 -> +1.0 else +0.3) else -0.5
# Input (a=0.3, b=1.0): tree1 left (+0.4); tree2 left, inner right (+0.3)
#   z = -1.0 + 0.4 + 0.3 = -0.3 ; p = 1/(1+e^0.3) = 0.42555748...
# Input (a=0.7, b=3.0): tree1 right (-0.2); tree2 right (-0.5)
#   z = -1.7 ; p = 1/(1+e^1.7) = 0.15446527...

_HAND = {
    "model": "gbm_binary",
    "feature_names": ["a", "b"],
    "base_score": -1.0,
    "trees": [
        {"f": 0, "t": 0.5, "l": {"v": 0.4}, "r": {"v": -0.2}},
        {"f": 1, "t": 2.0,
         "l": {"f": 0, "t": 0.1, "l": {"v": 1.0}, "r": {"v": 0.3}},
         "r": {"v": -0.5}},
    ],
}


def test_the_hand_computed_two_tree_model(mdir):
    _write(mdir, "death_risk", dict(_HAND))
    p1 = models.score_death_risk({"a": 0.3, "b": 1.0})
    p2 = models.score_death_risk({"a": 0.7, "b": 3.0})
    assert abs(p1 - 1 / (1 + math.exp(0.3))) < 1e-12, p1
    assert abs(p2 - 1 / (1 + math.exp(1.7))) < 1e-12, p2


def test_the_boundary_goes_LEFT():
    """x[f] <= t routes left — the stated export convention. At exactly a=0.5 tree1
    takes +0.4, not -0.2. An off-by-one here skews every prediction near every split."""
    from steemer.models import _walk
    assert _walk(_HAND["trees"][0], [0.5, 0.0]) == 0.4
    assert _walk(_HAND["trees"][0], [0.5000001, 0.0]) == -0.2


def test_isotonic_calibration_is_a_step_lookup(mdir):
    """cal maps raw p through steps: x=[0.0, 0.4, 0.8], y=[0.1, 0.5, 0.9].
    raw 0.42555... falls in [0.4, 0.8) -> 0.5; raw 0.15446... in [0.0, 0.4) -> 0.1."""
    m = dict(_HAND)
    m["calibration"] = {"x": [0.0, 0.4, 0.8], "y": [0.1, 0.5, 0.9]}
    _write(mdir, "death_risk", m)
    assert models.score_death_risk({"a": 0.3, "b": 1.0}) == 0.5
    assert models.score_death_risk({"a": 0.7, "b": 3.0}) == 0.1


def test_logistic_band_scores_softmax(mdir):
    """classes [calm, undead]; coef calm=[1,0], undead=[0,1]; intercepts 0.
    features (a=2, b=1): z = [2, 1] -> softmax = e^2/(e^2+e^1), e^1/(...)."""
    _write(mdir, "band_forecast", {
        "model": "logistic", "feature_names": ["a", "b"],
        "classes": ["calm", "undead"],
        "coef": [[1.0, 0.0], [0.0, 1.0]], "intercept": [0.0, 0.0]})
    out = models.score_band({"a": 2.0, "b": 1.0})
    e2, e1 = math.exp(2), math.exp(1)
    assert abs(out["calm"] - e2 / (e2 + e1)) < 1e-12
    assert abs(out["undead"] - e1 / (e2 + e1)) < 1e-12
    assert abs(sum(out.values()) - 1.0) < 1e-12


# ---- fail-closed: every defect yields None, never an exception -----------------

def test_absent_model_scores_None(mdir):
    assert models.score_death_risk({"a": 1.0, "b": 1.0}) is None


def test_truncated_json_scores_None(mdir):
    with open(os.path.join(mdir, "death_risk.json"), "w") as fh:
        fh.write('{"model": "gbm_bin')
    with open(os.path.join(mdir, "death_risk.meta.json"), "w") as fh:
        json.dump({}, fh)
    assert models.score_death_risk({"a": 1.0, "b": 1.0}) is None


def test_schema_mismatch_scores_None(mdir):
    m = dict(_HAND); m["schema_version"] = 999
    _write(mdir, "death_risk", m)
    assert models.score_death_risk({"a": 1.0, "b": 1.0}) is None


def test_missing_feature_scores_None(mdir):
    _write(mdir, "death_risk", dict(_HAND))
    assert models.score_death_risk({"a": 1.0}) is None      # b absent -> vector raises


def test_nan_threshold_scores_None(mdir):
    m = json.loads(json.dumps(_HAND))
    m["trees"][0]["t"] = float("nan")
    m["base_score"] = float("nan")
    _write(mdir, "death_risk", m)
    out = models.score_death_risk({"a": 1.0, "b": 1.0})
    assert out is None


def test_a_stale_model_scores_None(mdir):
    _write(mdir, "death_risk", dict(_HAND),
           meta={"trained_at_epoch": time.time() - (models.STALE_DAYS + 1) * 86400})
    assert models.score_death_risk({"a": 0.3, "b": 1.0}) is None


def test_malformed_calibration_scores_None(mdir):
    m = dict(_HAND); m["calibration"] = {"x": [0.1, 0.2], "y": [0.5]}
    _write(mdir, "death_risk", m)
    assert models.score_death_risk({"a": 0.3, "b": 1.0}) is None


# ---- sklearn parity (fixture generated inside the training session) ------------

FIX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures", "models")


@pytest.mark.skipif(not os.path.exists(os.path.join(FIX, "tiny_gbm.json")),
                    reason="parity fixture not yet generated (tools/gen_model_fixtures.py)")
def test_sklearn_parity(monkeypatch):
    """The second oracle: sklearn's own predict_proba outputs, recorded at fixture
    generation time inside the Linux session, must match the stdlib walker exactly."""
    monkeypatch.setattr(models, "MODELS_DIR", FIX)
    models.reset_cache()
    with open(os.path.join(FIX, "expected_scores.jsonl")) as fh:
        cases = [json.loads(l) for l in fh]
    assert cases, "empty parity fixture"
    for case in cases:
        got = models.score_death_risk(case["features"])
        assert got is not None and abs(got - case["expected"]) < 1e-9, \
            f"parity break: {got} vs {case['expected']}"
    models.reset_cache()
