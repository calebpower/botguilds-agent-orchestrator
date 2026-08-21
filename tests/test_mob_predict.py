"""Tests for the mob move-predictor (steemer.mob_predict)."""
from steemer.mob_predict import predict, evaluate, _step_toward


def test_step_toward_picks_the_distance_reducing_neighbour():
    assert _step_toward((0, 0), (5, 0)) == (1, 0)     # east toward the target
    assert _step_toward((0, 0), (0, 5)) == (0, 1)     # north
    assert _step_toward((3, 3), (3, 3)) == (3, 3)     # already there -> stay


def test_chaser_is_predicted_to_step_toward_the_nearest_char():
    prof = {"behavior": "chaser", "move_rate": 0.9, "chaser_score": 0.94}
    p = predict(prof, (5, 5), [(8, 5), (0, 0)])       # nearest char is east at (8,5)
    assert p["toward"] == (6, 5)                       # steps east toward it
    assert p["predicted"] == (6, 5)                    # moves >50% of ticks -> predict the step
    assert p["confidence"] == "high"                   # chaser_score >= 0.7


def test_slow_chaser_best_guess_is_stay_but_toward_still_reported():
    # a chaser that only moves 22% of ticks: the single best guess is "stays", yet the
    # direction it WOULD step is still exposed for tactics (dodge into the gap).
    prof = {"behavior": "chaser", "move_rate": 0.22, "chaser_score": 0.9}
    p = predict(prof, (5, 5), [(9, 5)])
    assert p["predicted"] == (5, 5)                    # < 0.5 move_rate -> predict stay
    assert p["toward"] == (6, 5)                        # but the chase direction is known


def test_stationary_mob_is_predicted_to_stay_with_high_confidence():
    p = predict({"behavior": "stationary", "move_rate": 0.02}, (7, 7), [(1, 1)])
    assert p["predicted"] == (7, 7) and p["confidence"] == "high"


def test_no_characters_means_no_toward_prediction():
    p = predict({"behavior": "chaser", "move_rate": 0.9}, (5, 5), [])
    assert p["toward"] is None and p["predicted"] == (5, 5)


def _f(tick, mobs, chars, world="w"):
    return {"world": world, "tick": tick,
            "chars": [{"pos": c} for c in chars],
            "mobs": [{"eid": e, "kind": k, "pos": p} for e, k, p in mobs]}


def test_evaluate_scores_a_chaser_that_really_chases():
    # a wolf (eid 1) closing one tile/tick on a stationary char -> the predictor should score
    # 'toward_when_moved' == 1.0. Self-testing the oracle: it must credit a real chase.
    bestiary = {"wolf": {"behavior": "chaser", "move_rate": 1.0, "chaser_score": 1.0}}
    frames = [_f(t, [(1, "wolf", [10 - t, 0])], [[0, 0]]) for t in range(6)]
    res = evaluate(bestiary, frames)
    assert res["toward_when_moved"] == 1.0
    assert res["by_behavior"]["chaser"]["exact"] == 1.0    # predicted step == actual, every tick
