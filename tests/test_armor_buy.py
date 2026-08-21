"""v0.47.0 — we buy ARMOR, not only weapons.

The gap this closes was self-inflicted and had survived 114 runs: characters have five
equipment slots (`hand`, `offhand`, `outfit`, `trinket`, `boots`), but the shop buy was
gated on `WEAPON_KINDS` and on `hand` being empty, so we had bought for exactly one of
them. Measured on run #114: 0% of our characters wear any armor, while rival guild
g_63837f fields ~60% of its characters in spear + smith_apron. `shield_wood` costs 25g and
carries no stat requirement, and every one of our characters has an empty offhand.

The shop does not say which slot a kind occupies (every `slot` field is null), so the buy
reuses what EQUIPPING has already learned — `slot_wrong` / `wont_fit` — rather than
guessing. Those guards are what stop us re-buying a shield forever, and they are tested.
"""
from steemer.strategy.explorer import Explorer, ARMOR_BUY_FLOOR


STOCK = [
    {"kind": "club", "buy_price": 15, "sell_price": 3},
    {"kind": "shield_wood", "buy_price": 25, "sell_price": 5},
    {"kind": "fickle_pearl", "buy_price": 30, "sell_price": 6},
    {"kind": "striders", "buy_price": 90, "sell_price": 18},
    {"kind": "tome_bolt", "buy_price": 150, "sell_price": 30, "req": {"int": 7}},
]
FRAME = {"shop": {"stock": STOCK}}
EMPTY = {s: None for s in ("hand", "offhand", "outfit", "trinket", "boots")}


def _char(**kw):
    base = {"char_uid": "c1", "stats": {"str": 2}, "inventory": []}
    base.update(kw)
    return base


def test_buys_the_CHEAPEST_affordable_armor():
    """Cheapest-first arms the most characters per coin — the same reasoning that made the
    15g club beat waiting for a 45g shortsword in v0.13.0."""
    exp = Explorer()
    assert exp._afford_armor(_char(), dict(EMPTY), FRAME, gold=500) == ("shield_wood", 25)


def test_buys_nothing_when_it_cannot_afford_any():
    exp = Explorer()
    assert exp._afford_armor(_char(), dict(EMPTY), FRAME, gold=10) is None


def test_a_weapon_is_never_bought_as_armor():
    """ARMOR_KINDS and WEAPON_KINDS must stay disjoint in effect, or the armor step would
    race the weapon step for the same coins."""
    exp = Explorer()
    kind, _ = exp._afford_armor(_char(), dict(EMPTY), FRAME, gold=500)
    assert kind != "club"


def test_does_not_rebuy_a_kind_the_character_already_WEARS():
    """The forever-loop this guard exists to prevent: without it a character with a shield
    equipped would buy another every village visit."""
    exp = Explorer()
    eqp = dict(EMPTY, offhand={"kind": "shield_wood"})
    assert exp._afford_armor(_char(), eqp, FRAME, gold=500) == ("fickle_pearl", 30)


def test_does_not_rebuy_a_kind_the_character_already_CARRIES():
    """Two oracles for the same claim: worn is checked, and so is carried — a piece bought
    last tick is in the inventory, not the slot, until the equip step runs."""
    exp = Explorer()
    char = _char(inventory=[{"kind": "shield_wood", "item_id": "s1"}])
    assert exp._afford_armor(char, dict(EMPTY), FRAME, gold=500) == ("fickle_pearl", 30)


def test_respects_a_stat_requirement():
    """The stat-gated piece must be the ONLY armor on offer, or the cheapest-first rule
    excludes it for being expensive and the requirement check is never exercised at all —
    which is exactly how the first version of this test passed while a mutant that
    deleted the requirement check SURVIVED."""
    exp = Explorer()
    stock = {"shop": {"stock": [{"kind": "shield_iron", "buy_price": 40,
                                 "req": {"str": 9}}]}}
    weak = _char(stats={"str": 2})
    assert exp._afford_armor(weak, dict(EMPTY), stock, gold=5000) is None
    strong = _char(stats={"str": 9})
    assert exp._afford_armor(strong, dict(EMPTY), stock, gold=5000) == ("shield_iron", 40)


def test_skips_a_kind_learned_not_to_FIT():
    """`wont_fit` is populated when an equip is refused for a stat requirement."""
    exp = Explorer()
    exp.wont_fit.add("shield_wood")
    assert exp._afford_armor(_char(), dict(EMPTY), FRAME, gold=500) == ("fickle_pearl", 30)


def test_skips_a_kind_with_no_empty_slot_left_it_could_go_into():
    """The slot guard. Once equipping has learned a kind is wrong for every slot that is
    still empty, buying another is pure waste."""
    exp = Explorer()
    eqp = dict(EMPTY, offhand={"kind": "lantern"})   # only offhand filled
    for slot in ("hand", "outfit", "trinket", "boots"):
        exp.slot_wrong["shield_wood"].add(slot)
    got = exp._afford_armor(_char(), eqp, FRAME, gold=500)
    assert got is not None and got[0] != "shield_wood"


def test_buys_nothing_when_every_slot_is_full():
    exp = Explorer()
    full = {s: {"kind": "x"} for s in EMPTY}
    assert exp._afford_armor(_char(), full, FRAME, gold=5000) is None


def test_an_empty_shop_is_not_a_crash():
    exp = Explorer()
    assert exp._afford_armor(_char(), dict(EMPTY), {"shop": {"stock": []}}, gold=500) is None
    assert exp._afford_armor(_char(), dict(EMPTY), {}, gold=500) is None


def test_the_armor_floor_sits_ABOVE_the_weapon_floor():
    """Ordering claim, asserted on the constants themselves: a bare character arming must
    never lose a coin race to an equipped character buying a shield."""
    from steemer.strategy.explorer import WEAPON_BUY_FLOOR
    assert ARMOR_BUY_FLOOR > WEAPON_BUY_FLOOR
