"""Essence-aware brew selection (v0.7.0).

The 0.6.0 bot brewed the first 2-4 brewables in inventory order and curdled
~50% of the time because it kept mixing the opposed vigor/venom poles. These
tests pin the fix: a brew is a *single-essence* batch, vigor preferred, and it
declines rather than mix opposites. Each assertion is mutation-checked (break
the rule, watch the test fail) per the testing ethic.
"""

from steemer import knowledge
from steemer.strategy.explorer import Explorer, BREW_MIN, BREW_MAX


def _herb(kind, i=0):
    return {"kind": kind, "item_id": f"{kind}-{i}", "uses": ["brew"]}


def _kinds(picks):
    return [p["kind"] for p in picks]


def test_essence_of_decoded_and_unknown():
    assert knowledge.essence_of("embercap") == "vigor"   # name is a red herring
    assert knowledge.essence_of("moonbell") == "venom"
    assert knowledge.essence_of("bone") == "vigor"        # calibration anchor
    assert knowledge.essence_of("glimmerweed") is None    # only LOW-conf -> undecoded
    assert knowledge.essence_of("nonesuch") is None


def test_vigor_and_venom_are_opposed_in_the_map():
    # The whole fix rests on these two being *different* essences; if a map edit
    # ever collapsed them, mixing would stop being flagged as a curdle risk.
    assert knowledge.essence_of("embercap") != knowledge.essence_of("moonbell")


def test_prefers_vigor_batch_for_healing():
    # more venom than vigor present, but vigor wins because it brews the heal.
    brewables = [_herb("embercap", 1), _herb("bone", 2),
                 _herb("moonbell", 3), _herb("moonbell", 4), _herb("moonbell", 5)]
    picks, ess, healing = Explorer._choose_brew(brewables)
    assert ess == "vigor" and healing is True
    assert set(_kinds(picks)) <= {"embercap", "bone"}   # never a moonbell in it


def test_batch_is_single_essence_never_a_mix():
    brewables = [_herb("bone", 1), _herb("embercap", 2),
                 _herb("moonbell", 3), _herb("venom_sac", 4)]
    picks, ess, _ = Explorer._choose_brew(brewables)
    essences = {knowledge.essence_of(k) for k in _kinds(picks)}
    assert essences == {ess}                 # exactly one essence in the pot
    assert essences == {"vigor"}             # and vigor was the one preferred


def test_declines_rather_than_curdle():
    # one of each pole and nothing else: every pairing mixes opposites -> brew
    # nothing (the 0.6.0 code would have brewed both and curdled).
    picks, ess, healing = Explorer._choose_brew([_herb("bone"), _herb("moonbell")])
    assert picks is None and ess is None and healing is False


def test_undecoded_herbs_brew_as_a_learning_batch():
    brewables = [_herb("glimmerweed", 1), _herb("frostmoss", 2), _herb("sungrass", 3)]
    picks, ess, healing = Explorer._choose_brew(brewables)
    assert ess is None and healing is False           # essence not yet decoded
    assert len(picks) >= BREW_MIN and set(_kinds(picks)) <= {
        "glimmerweed", "frostmoss", "sungrass"}


def test_decoded_essence_preferred_over_a_guess():
    # two venom (decoded) + three undecoded, no vigor: brew the known venom
    # batch, not the guess — a known product beats an unknown curdle risk.
    brewables = [_herb("moonbell", 1), _herb("venom_sac", 2),
                 _herb("glimmerweed", 3), _herb("frostmoss", 4), _herb("sungrass", 5)]
    picks, ess, _ = Explorer._choose_brew(brewables)
    assert ess == "venom"
    assert {knowledge.essence_of(k) for k in _kinds(picks)} == {"venom"}


def test_respects_brew_max():
    brewables = [_herb("bone", i) for i in range(BREW_MAX + 3)]   # 7 vigor herbs
    picks, ess, _ = Explorer._choose_brew(brewables)
    assert ess == "vigor" and len(picks) == BREW_MAX


def test_single_ingredient_is_not_enough():
    picks, ess, healing = Explorer._choose_brew([_herb("bone")])
    assert picks is None and BREW_MIN == 2       # a brew needs at least two
