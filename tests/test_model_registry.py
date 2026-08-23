"""Registry canary (ML Pass 2): schema drift breaks the BUILD, never the bot.

Every artifact committed under models/ must parse, match the live feature schema, and
name only features the corresponding mlfeat function actually produces. The scorer would
fail closed at runtime anyway — but silently-disabled models are exactly the inert-ship
failure this project keeps re-learning, so drift must be loud at the gate.
"""
import json
import os

import pytest

from steemer import mlfeat

MODELS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "models")

_EXPECTED_NAMES = {
    "death_risk": set(mlfeat.DEATH_FEATURES),
    "band_forecast": set(mlfeat.BAND_FEATURES),
    "mob_move": set(mlfeat.MOB_FEATURES),
}


def check_models_dir(models_dir: str) -> None:
    """The canary body, parameterised so its self-test can aim it at a broken dir —
    a module-global patch was aimed at the wrong import copy and DID NOT RAISE."""
    if not os.path.isdir(models_dir):
        return
    files = [f for f in sorted(os.listdir(models_dir))
             if f.endswith(".json") and not f.endswith(".meta.json")
             and f != "bestiary_snapshot.json"]
    for fn in files:
        with open(os.path.join(models_dir, fn)) as fh:
            m = json.load(fh)
        assert m.get("schema_version") == mlfeat.FEATURE_SCHEMA_VERSION, \
            f"{fn}: schema {m.get('schema_version')} != {mlfeat.FEATURE_SCHEMA_VERSION}"
        name = fn[:-5]
        if name in _EXPECTED_NAMES:
            unknown = set(m.get("feature_names") or []) - _EXPECTED_NAMES[name]
            assert not unknown, f"{fn} names features mlfeat does not produce: {unknown}"
        meta = os.path.join(models_dir, f"{name}.meta.json")
        assert os.path.exists(meta), f"{fn} has no birth certificate ({name}.meta.json)"


def test_every_committed_model_parses_and_matches_the_schema():
    check_models_dir(MODELS)


def test_the_bestiary_snapshot_matches_the_schema():
    path = os.path.join(MODELS, "bestiary_snapshot.json")
    assert os.path.exists(path), "no frozen profile snapshot — features cannot be scored"
    with open(path) as fh:
        s = json.load(fh)
    assert s.get("schema_version") == mlfeat.FEATURE_SCHEMA_VERSION
    assert s.get("kinds"), "empty snapshot"
    for kind, p in s["kinds"].items():
        for key in ("move_rate", "chaser_score", "dph", "hit_rate", "behavior"):
            assert key in p, f"{kind} missing {key}"


def test_the_canary_itself_can_fail(tmp_path):
    """Self-test: a model with a bogus schema version must trip the canary — otherwise
    this whole file is a green light wired to nothing."""
    bogus = tmp_path / "death_risk.json"
    bogus.write_text(json.dumps({"schema_version": 999, "feature_names": []}))
    (tmp_path / "death_risk.meta.json").write_text("{}")
    (tmp_path / "bestiary_snapshot.json").write_text(json.dumps(
        {"schema_version": mlfeat.FEATURE_SCHEMA_VERSION, "kinds": {"wolf": {
            "move_rate": 1, "chaser_score": 1, "dph": 1, "hit_rate": 1,
            "behavior": "chaser"}}}))
    with pytest.raises(AssertionError):
        check_models_dir(str(tmp_path))
