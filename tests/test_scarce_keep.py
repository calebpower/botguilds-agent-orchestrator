"""v0.59.0 — SCARCE CHAIN INPUTS: a stranded singleton is half a pair, not clutter.

The stranded-singleton rule (v0.8.0/v0.10.0) sells a lone brewable or a lone ore because
it cannot form a batch or a pair. That is right for ABUNDANT things — an unsold-food pack
once pinned characters `full` forever and drove the embark/return thrash.

It is wrong for the two inputs we are bottlenecked on, and run #135 caught both going over
the counter while the chains that need them starved: 2 `bone` (a VIGOR herb, the only route
to `potion_red`, which is what lifts POISON_SAFE_DEPTH and therefore gates every vein we
have failed to reach) and 5 `ore_copper` (raw forge feedstock — FORGE_FEEDSTOCK_PREFIXES
covers `ingot` but not the ore an ingot is smelted from).

What these tests do NOT prove: that keeping them produces more potion_red or more ingots.
That is a live measurement. They prove only that we stop banking the inputs.
"""
import steemer.knowledge as knowledge
from steemer.strategy.explorer import Explorer, SCARCE_LONE_KEEP


def _it(kind, i=0, uses=()):
    return {"kind": kind, "item_id": f"{kind}-{i}", "uses": list(uses), "tier": 1}


EMPTY_EQP = {s: None for s in ("hand", "offhand", "outfit", "trinket", "boots")}


def _sells(item, inv):
    """Would this item be sold, given the whole inventory it sits in?"""
    return Explorer()._should_sell(item, dict(EMPTY_EQP), set(), set(), set(),
                                   Explorer._scarce_keep_ids(inv))


# ---- the two families ---------------------------------------------------------

def test_a_lone_vigor_herb_is_kept():
    """`bone` is vigor, and vigor is the only route to potion_red."""
    assert knowledge.essence_of("bone") == "vigor"
    inv = [_it("bone", uses=["brew"])]
    assert _sells(inv[0], inv) is False


def test_a_lone_raw_ore_is_kept():
    inv = [_it("ore_copper", uses=["smelt"])]
    assert _sells(inv[0], inv) is False


def test_a_lone_NON_vigor_brewable_is_still_sold():
    """The anti-clog rule is untouched for everything that is not scarce — this is the
    boundary that keeps the change narrow. `moonbell` is venom, not vigor."""
    assert knowledge.essence_of("moonbell") == "venom"
    inv = [_it("moonbell", uses=["brew"])]
    assert _sells(inv[0], inv) is True


def test_pure_loot_is_still_sold():
    inv = [_it("tomato")]
    assert _sells(inv[0], inv) is True


# ---- bounded, so it cannot become the clog the old rule prevented -------------

def test_it_keeps_at_most_a_couple_per_kind():
    """The count here is DELIBERATELY hardcoded rather than derived from
    SCARCE_LONE_KEEP. A fixture sized from the constant under test moves with it and
    agrees with itself no matter what — mutation testing caught exactly that, since
    raising the cap to 99 left the original version green. "Six ore, at most a couple
    kept" is the policy claim, independent of the number."""
    lots = [_it("ore_copper", i, uses=["smelt"]) for i in range(6)]
    keep = Explorer._scarce_keep_ids(lots)
    assert len(keep) <= 2, f"kept {len(keep)} of 6 — that is a hoard, not a spare half-pair"
    assert _sells(lots[-1], lots) is True, "the surplus above the cap is clutter again"


def test_the_cap_stays_in_the_band_the_case_above_assumes():
    """The test above pins BEHAVIOUR at six items. This pins the constant it straddles, so
    a change to SCARCE_LONE_KEEP that invalidates its premise fails here and says so,
    rather than quietly making it vacuous."""
    assert 1 <= SCARCE_LONE_KEEP <= 2


def test_the_cap_is_per_KIND_not_per_character():
    """Two different scarce kinds each get their own allowance — they pair with their own
    kind, so capping them jointly would sell a half-pair to make room for another."""
    inv = ([_it("ore_copper", i, uses=["smelt"]) for i in range(2)]
           + [_it("ore_iron", i, uses=["smelt"]) for i in range(2)])
    keep = Explorer._scarce_keep_ids(inv)
    assert {i["item_id"] for i in inv if i["kind"] == "ore_copper"} & keep
    assert {i["item_id"] for i in inv if i["kind"] == "ore_iron"} & keep


# ---- it reads the essence map rather than hardcoding a list -------------------

def test_vigor_membership_comes_from_the_knowledge_map():
    """The essence map is per-world DATA that gets updated as brews decode herbs. If this
    list were duplicated in the strategy, a newly decoded vigor herb would be sold until
    someone remembered to edit two files.

    Checked against the map's OWN contents rather than a copy of them: every kind the map
    calls vigor must be kept, whatever that set happens to be."""
    vigor = [k for k, v in knowledge.ESSENCE.items() if v == "vigor"]
    assert vigor, "premise: the map knows at least one vigor herb"
    for kind in vigor:
        inv = [_it(kind, uses=["brew"])]
        assert _sells(inv[0], inv) is False, f"{kind} is vigor and must be kept"


def test_an_undecoded_herb_is_not_treated_as_vigor():
    """`essence_of` returns None for anything not decoded, and None is not vigor — acting
    on a guess is exactly what knowledge.py refuses to do."""
    assert knowledge.essence_of("sungrass") is None
    inv = [_it("sungrass", uses=["brew"])]
    assert _sells(inv[0], inv) is True
