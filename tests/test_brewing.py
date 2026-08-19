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


def test_undecoded_singletons_of_different_kinds_do_not_brew():
    # v0.8.0: three DIFFERENT undecoded kinds, one each, form no same-kind pair,
    # so nothing brews (mixing them curdled in 0.7.0). They get sold as stranded.
    brewables = [_herb("glimmerweed", 1), _herb("frostmoss", 2), _herb("sungrass", 3)]
    assert Explorer._choose_brew(brewables) == (None, None, False)


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


# --- v0.8.0: same-kind learning batches + selling stranded singletons ---

def test_undecoded_batch_is_same_kind_not_mixed():
    # two different undecoded kinds must NOT brew together (that curdled in
    # 0.7.0); a pair of the SAME kind may (it shares an essence).
    mixed = Explorer._choose_brew([_herb("glimmerweed", 1), _herb("frostmoss", 2)])
    assert mixed == (None, None, False)
    picks, ess, healing = Explorer._choose_brew(
        [_herb("frostmoss", 1), _herb("frostmoss", 2), _herb("glimmerweed", 3)])
    assert ess is None and healing is False
    assert set(_kinds(picks)) == {"frostmoss"}      # same kind only, never mixed


def test_brew_keep_ids_keeps_batchable_drops_singletons():
    keep = Explorer._brew_keep_ids([
        _herb("bone", 1), _herb("embercap", 2),   # 2 vigor (different kinds) -> batch
        _herb("frostmoss", 3), _herb("frostmoss", 4),  # 2 same undecoded kind -> batch
        _herb("moonbell", 5),                       # lone venom -> stranded
        _herb("glimmerweed", 6)])                   # lone undecoded -> stranded
    assert keep == {"bone-1", "embercap-2", "frostmoss-3", "frostmoss-4"}


def test_should_sell_sells_stranded_brewable_keeps_batchable():
    exp = Explorer()
    lone = _herb("moonbell", 1)
    assert exp._should_sell(lone, {}, brew_keep=set(), smelt_keep=set()) is True   # stranded -> sell
    keep_item = _herb("bone", 2)
    assert exp._should_sell(keep_item, {}, brew_keep={"bone-2"}, smelt_keep=set()) is False  # batchable -> keep


def test_should_sell_sells_food_keeps_medicinal_drinks():
    # v0.19.0: raw food is `uses:['drink']` but never eaten, so it is SOLD as loot
    # (the unsold-food pack was the stuck-gold / embark-thrash root cause). Only
    # KEEP supplies and actual medicinal drinks (potion*/vial*/…) are kept.
    exp = Explorer()
    ss = lambda it: exp._should_sell(it, {}, brew_keep=set(), smelt_keep=set())
    assert ss({"kind": "meat", "item_id": "m1", "uses": ["drink"]}) is True    # food -> sell
    assert ss({"kind": "egg", "item_id": "e1", "uses": ["drink"]}) is True     # food -> sell
    assert ss({"kind": "potion_red", "item_id": "p1", "uses": ["drink"]}) is False   # KEEP
    assert ss({"kind": "potion_blue", "item_id": "p2", "uses": ["drink"]}) is False  # medicinal
    assert ss({"kind": "vial_green", "item_id": "v1", "uses": ["drink"]}) is False   # medicinal


def test_shed_item_prefers_clutter_then_ore_never_keep_or_gear():
    # When overburdened we shed the least-useful thing: pure loot clutter (no
    # craft/consume use) before craft ingredients, and never a field supply or
    # carried gear (v0.15.0).
    exp = Explorer()
    potion = {"kind": "potion_red", "item_id": "P"}                       # KEEP
    sword = {"kind": "shortsword", "item_id": "W", "uses": ["equip"]}     # gear
    ore = {"kind": "ore_copper", "item_id": "O", "uses": ["smelt"]}       # craft pair
    lumber = {"kind": "lumber", "item_id": "L"}                           # pure clutter
    assert exp._shed_item({"inventory": [potion, sword, ore, lumber]}) == "L"  # clutter first
    assert exp._shed_item({"inventory": [potion, sword, ore]}) == "O"         # ore before gear/keep
    assert exp._shed_item({"inventory": [potion, sword]}) is None            # nothing sheddable
    assert exp._shed_item({"inventory": []}) is None
