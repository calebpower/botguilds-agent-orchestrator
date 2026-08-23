"""ML Pass 3 — shadow scoring through the bot: visible, recorded, and inert.

Three claims, each the negation of a way shadow wiring could rot:
  * REACHABLE: with artifacts deployed, scores actually land in the intel table through
    GuildBot.on_frame (the correct-but-unreachable failure class, 5 historical cases);
  * INERT: the action stream is IDENTICAL with and without models — shadow means shadow
    (the Pass-4 acceptance will prove this again on live runs via shadow.py);
  * FAIL-CLOSED AT THE SEAM: a model that explodes mid-score must cost nothing but a
    warning line.
"""
import json
import math
import os
import time

import pytest

from steemer import mlfeat, models
from steemer.bot import GuildBot, SHADOW_EVERY

# 5 duplicated as a literal in the cadence fixture (the hygiene ratchet forbids sizing
# fixtures from the constant under test); pinned so drift is loud.
CADENCE = 5
from steemer.storage import Storage


@pytest.fixture()
def mdir(tmp_path, monkeypatch):
    monkeypatch.setattr(models, "MODELS_DIR", str(tmp_path))
    models.reset_cache()
    yield tmp_path
    models.reset_cache()


def _deploy_death_model(mdir):
    """A real, walkable artifact over the REAL feature schema: one tree on hp_frac.
    hp 30/30 -> hp_frac 1.0 > 0.5 -> right leaf -2.0 -> p = sigmoid(-2)."""
    tree = {"f": list(mlfeat.DEATH_FEATURES).index("hp_frac"), "t": 0.5,
            "l": {"v": 2.0}, "r": {"v": -2.0}}
    with open(os.path.join(mdir, "death_risk.json"), "w") as fh:
        json.dump({"schema_version": mlfeat.FEATURE_SCHEMA_VERSION,
                   "model": "gbm_binary",
                   "feature_names": list(mlfeat.DEATH_FEATURES),
                   "base_score": 0.0, "trees": [tree]}, fh)
    with open(os.path.join(mdir, "death_risk.meta.json"), "w") as fh:
        json.dump({"trained_at_epoch": time.time()}, fh)


def _bot(storage=None):
    b = GuildBot(strategy="explorer", storage=storage)
    b.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 10,
                "maps": [{"id": "vale"}]}
    b.tick = 500
    return b


def _frame(tick):
    tiles = [[x, y, "floor", 0, 0] for x in range(5) for y in range(5)]
    return {"world": "vale", "tick": tick, "events": [],
            "chars": [{"char_uid": "c1", "eid": 7, "pos": [2, 2], "hp": 30,
                       "max_hp": 30, "stamina": 40, "max_stamina": 56, "level": 3,
                       "stats": {}, "gifts": [], "statuses": [], "spells": [],
                       "carry": {"used": 0, "cap": 20}, "inventory": [],
                       "equipment": {"hand": {"kind": "club"}}}],
            "visible": {"tiles": tiles, "entities": [], "items": [], "gold": []}}


def test_shadow_scores_REACH_the_intel_table_through_the_bot(mdir, tmp_path):
    _deploy_death_model(mdir)
    st = Storage(str(tmp_path / "s.db"))
    st.begin_run("sha", "test/0")
    bot = _bot(storage=st)
    bot.on_frame(_frame(500))
    st.conn.commit()
    rows = st.conn.execute(
        "SELECT payload_json FROM intel WHERE kind='model_score'").fetchall()
    assert rows, "no shadow score reached intel through on_frame"
    payload = json.loads(rows[0][0])
    assert payload["model"] == "death_risk"
    expected = 1.0 / (1.0 + math.exp(2.0))            # hp_frac 1.0 -> right leaf -2.0
    assert abs(payload["scores"]["c1"] - round(expected, 4)) < 1e-6, payload


def test_scoring_respects_the_cadence(mdir, tmp_path):
    """One score per char per SHADOW_EVERY ticks — the budget guard."""
    assert SHADOW_EVERY == CADENCE, "the cadence moved; re-read the numbers in this test"
    _deploy_death_model(mdir)
    st = Storage(str(tmp_path / "s.db"))
    st.begin_run("sha", "test/0")
    bot = _bot(storage=st)
    for t in range(500, 506):          # six ticks: scores land at 500 and 505
        bot.tick = t
        bot.on_frame(_frame(t))
    st.conn.commit()
    n = st.conn.execute(
        "SELECT COUNT(*) FROM intel WHERE kind='model_score'").fetchone()[0]
    assert n == 2, f"expected 2 scores across six ticks at cadence 5, got {n}"


def test_shadow_is_INERT_actions_identical_with_and_without_models(mdir):
    """The whole meaning of shadow-first: byte-identical action streams."""
    bot_off = _bot()
    plain = [bot_off.on_frame(_frame(t)) for t in range(500, 520)]
    _deploy_death_model(mdir)
    models.reset_cache()
    bot_on = _bot()
    scored = [bot_on.on_frame(_frame(t)) for t in range(500, 520)]
    assert plain == scored, "shadow scoring changed the action stream"


def test_a_model_that_EXPLODES_costs_a_warning_not_the_frame(mdir, tmp_path):
    """Corrupt artifact (tree references feature index 9999): the scorer's IndexError
    must be swallowed to None inside the shadow path and the frame must still act."""
    with open(os.path.join(mdir, "death_risk.json"), "w") as fh:
        json.dump({"schema_version": mlfeat.FEATURE_SCHEMA_VERSION,
                   "model": "gbm_binary",
                   "feature_names": list(mlfeat.DEATH_FEATURES),
                   "base_score": 0.0,
                   "trees": [{"f": 9999, "t": 0.5, "l": {"v": 1}, "r": {"v": -1}}]}, fh)
    with open(os.path.join(mdir, "death_risk.meta.json"), "w") as fh:
        json.dump({"trained_at_epoch": time.time()}, fh)
    bot = _bot()
    acts = bot.on_frame(_frame(500))
    assert acts, "a corrupt model artifact silenced the bot"
