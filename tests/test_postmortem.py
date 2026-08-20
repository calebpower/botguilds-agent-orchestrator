"""Tests for the death post-mortem taxonomy (steemer.postmortem)."""
from steemer.postmortem import classify_death


def _tick(t, hp, pos, ents=()):
    return {"tick": t, "hp": hp, "pos": pos, "ents": list(ents)}


def test_melee_burst_from_an_adjacent_predator_stuck():
    # full-HP char takes -15 the tick a golem is adjacent, without having moved -> a
    # melee burst by a stuck char (the golem_stone death signature from run #85).
    trace = [
        _tick(1, 24, (5, 5), [("golem_stone", (5, 6))]),
        _tick(2, 24, (5, 5), [("golem_stone", (5, 6))]),
        _tick(3, 9,  (5, 5), [("golem_stone", (5, 6))]),   # -15 blow, golem adjacent
        _tick(4, 2,  (5, 5), [("golem_stone", (5, 6))]),
    ]
    d = classify_death(trace)
    assert d["cause"] == "melee_burst"
    assert d["killer"] == "golem_stone"
    assert d["killing_blow"] == 15
    assert d["mobility"] == "stuck"


def test_dot_bleed_with_no_hostile_adjacent_while_fleeing():
    # steady small HP loss with NOTHING hostile nearby, char moving toward the edge ->
    # DoT bleed, fleeing (the poison-retreat signature we chased before it was refuted).
    trace = [
        _tick(1, 12, (8, 4)),
        _tick(2, 9,  (8, 3)),
        _tick(3, 6,  (8, 2)),
        _tick(4, 3,  (8, 1)),
    ]
    d = classify_death(trace)
    assert d["cause"] == "dot_bleed"
    assert d["killer"] is None
    assert d["mobility"] == "fleeing"


def test_undead_dot_when_the_nearest_hostile_is_undead():
    # a cultist two tiles away chipping HP (not an adjacent burst) -> undead_dot.
    trace = [
        _tick(1, 20, (3, 3), [("cultist", (3, 5))]),
        _tick(2, 16, (3, 3), [("cultist", (3, 5))]),
        _tick(3, 12, (3, 4), [("cultist", (3, 5))]),
    ]
    d = classify_death(trace)
    assert d["cause"] == "undead_dot"
    assert d["killer"] == "cultist"


def test_benign_wildlife_is_never_blamed():
    # a chicken adjacent during the HP loss is NOT a killer (benign) -> falls through to
    # dot_bleed (no hostile near), killer None.
    trace = [
        _tick(1, 20, (2, 2), [("chicken", (2, 3))]),
        _tick(2, 10, (2, 2), [("chicken", (2, 3))]),
    ]
    d = classify_death(trace)
    assert d["killer"] is None
    assert d["cause"] == "dot_bleed"


def test_too_short_a_trace_is_unknown_not_a_crash():
    assert classify_death([])["cause"] == "unknown"
    assert classify_death([_tick(1, 10, (0, 0))])["cause"] == "unknown"
