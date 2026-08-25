"""v0.53.0 — EQUIP-UPGRADE: letting new gear displace worse gear.

Run #129 forged five items and then SOLD every one of them. The chain was entirely
mechanical: `_equip_action` filled only EMPTY slots, so the brute-force slot search
tried a forged spear in outfit/trinket/boots, learned all three were `wrong_slot`,
and left `hand` — occupied by a 15-gold club — as the only slot it fit. At that
point `_should_sell`'s "keep it only while a slot it could still go into remains"
was satisfied for selling, and the spear went to the shop counter.

So forging was not merely incomplete, it was value-DESTROYING: it converted an ingot
and a lumber into pocket change. These tests pin the two halves of the repair — the
swap itself, and the sell guard that lets the swap ever get a turn — plus the
learn-by-rejection kill-switch, because equipping into an occupied slot is an
undocumented mechanic and may simply not exist.

What these tests do NOT prove: that the server accepts a swap at all. That is
unknowable offline; SWAP_GIVE_UP is the hedge, and `test_it_stops_swapping_*` is
what proves the hedge closes.
"""
import pytest

from steemer.strategy.explorer import Explorer, EQUIP_SLOTS, SWAP_GIVE_UP


def _item(kind, uses=("equip", "attack"), item_id=None):
    return {"kind": kind, "item_id": item_id or f"{kind}-1", "uses": list(uses)}


def _eqp(**worn):
    slots = {s: None for s in EQUIP_SLOTS}
    slots.update({s: _item(k) for s, k in worn.items()})
    return slots


def _armed(exp):
    """The exact run-#129 state that sold the spear: club in hand, bought shield in
    offhand, and outfit/trinket/boots already learned wrong for a spear — so every
    slot is either occupied or ruled out, which is what made it sellable."""
    exp.price.update({"club": 15, "spear": 70, "shield_wood": 25})
    exp.slot_wrong["spear"].update({"outfit", "trinket", "boots"})
    return _eqp(hand="club", offhand="shield_wood")


# ---- the swap ----------------------------------------------------------------

def test_it_swaps_a_dearer_weapon_into_an_occupied_slot():
    exp = Explorer()
    eqp = _armed(exp)
    act = exp._equip_action("u1", [_item("spear")], eqp)
    assert act is not None, "a 70g spear must displace a 15g club"
    assert act["slot"] == "hand"
    assert act["item_id"] == "spear-1"


def test_it_marks_a_swap_in_flight_so_a_rejection_can_be_attributed():
    exp = Explorer()
    exp._equip_action("u1", [_item("spear")], _armed(exp))
    assert "u1" in exp._equip_upgrade
    assert exp.equipping["u1"] == ("spear", "hand")


def test_filling_an_empty_slot_is_not_marked_as_a_swap():
    """Pass 1 must clear the flag, or a plain equip's rejection would be booked
    against the swap kill-switch and burn it down for free."""
    exp = Explorer()
    exp._equip_upgrade.add("u1")
    act = exp._equip_action("u1", [_item("spear")], _eqp())
    assert act["slot"] == "hand"
    assert "u1" not in exp._equip_upgrade


def test_an_empty_slot_is_preferred_over_a_swap():
    exp = Explorer()
    exp.price.update({"club": 15, "spear": 70})
    act = exp._equip_action("u1", [_item("spear")], _eqp(offhand="club"))
    assert act["slot"] == "hand", "fill the empty hand rather than displace the offhand"


# ---- when it must NOT fire ---------------------------------------------------

def test_it_does_not_displace_a_kind_with_itself():
    """A second spear must not evict the spear already worn — the prices are equal
    by definition, so this would be a swap issued every single village visit."""
    exp = Explorer()
    exp.price.update({"spear": 70})
    eqp = _eqp(hand="spear")
    assert exp._upgrade_slot("spear", eqp) is None
    # Asked of _upgrade_slot rather than _equip_action on purpose: with the other four
    # slots empty, _equip_action would (correctly) fill one, and the swap rule would
    # never be the thing observed.


def test_it_does_not_swap_for_a_cheaper_item():
    exp = Explorer()
    exp.price.update({"club": 15, "spear": 70, "shield_wood": 25})
    exp.slot_wrong["club"].update({"outfit", "trinket", "boots"})
    assert exp._equip_action(
        "u1", [_item("club")], _eqp(hand="spear", offhand="shield_wood")) is None


def test_it_does_not_swap_for_an_equally_priced_item():
    """Equal is not better. Two same-priced kinds would otherwise displace each
    other every village visit, forever."""
    exp = Explorer()
    exp.price.update({"club": 15, "dagger": 15, "shield_wood": 25})
    exp.slot_wrong["dagger"].update({"outfit", "trinket", "boots"})
    assert exp._equip_action(
        "u1", [_item("dagger")], _eqp(hand="club", offhand="shield_wood")) is None


@pytest.mark.parametrize("known", ["mine", "theirs"])
def test_an_unknown_price_blocks_the_swap(known):
    """An unseen price must not read as zero — that would let any item displace
    anything the shop happens not to stock."""
    exp = Explorer()
    exp.price.update({"spear": 70} if known == "mine" else {"club": 15})
    exp.slot_wrong["spear"].update({"outfit", "trinket", "boots"})
    assert exp._equip_action(
        "u1", [_item("spear")], _eqp(hand="club", offhand="shield_wood")) is None
    # ...and it must DECLINE, not raise: comparing a missing price against a known one
    # is exactly where a None slips into a `>` and takes the whole frame down.
    assert exp._upgrade_slot("spear", _eqp(hand="club", offhand="shield_wood")) is None


def test_it_does_not_swap_across_gear_classes():
    """A 70g spear must not evict a 25g shield. The prices are comparable only within
    a job — this exact proposal (spear -> offhand) is what the class rule was added
    for, and it came out of a test, not a theory."""
    exp = Explorer()
    exp.price.update({"spear": 70, "shield_wood": 25})
    assert exp._upgrade_slot("spear", _eqp(offhand="shield_wood")) is None


def test_an_unclassified_kind_never_swaps():
    """We know what WEAPON_KINDS and ARMOR_KINDS are; everything else is unranked,
    and unranked must mean "leave it alone", not "compare anyway"."""
    exp = Explorer()
    exp.price.update({"club": 15, "lantern": 90})
    assert Explorer._gear_class("lantern") is None
    assert exp._upgrade_slot("lantern", _eqp(hand="club")) is None


def test_it_does_not_swap_into_a_slot_the_kind_is_known_wrong_for():
    exp = Explorer()
    exp.price.update({"club": 15, "spear": 70})
    exp.slot_wrong["spear"].add("hand")
    assert exp._upgrade_slot("spear", _eqp(hand="club")) is None


def test_it_does_not_swap_a_kind_that_fails_its_stat_requirement():
    exp = Explorer()
    eqp = _armed(exp)
    exp.wont_fit["spear"] = 999
    assert exp._equip_action("u1", [_item("spear")], eqp) is None


# ---- learn by rejection ------------------------------------------------------

def test_a_refused_swap_is_not_retried_for_that_pair():
    """The PAIR is burned, not the kind: a spear refused from `hand` may still be
    offered to another occupied slot (and the server will teach us if that is
    nonsense). What must never happen is re-issuing the identical doomed swap —
    that is the shape of every re-send storm this project has had."""
    exp = Explorer()
    eqp = _armed(exp)
    exp._equip_action("u1", [_item("spear")], eqp)
    exp.on_action_error(None, {"char_uid": "u1", "action": "equip",
                               "reason": "slot_occupied"})
    assert ("spear", "hand") in exp._swap_failed
    assert exp._upgrade_slot("spear", eqp) != "hand"
    exp._swap_failed.add(("spear", "offhand"))
    assert exp._equip_action("u1", [_item("spear")], eqp) is None


def test_wrong_slot_still_teaches_the_slot_map_not_the_swap_map():
    """`wrong_slot` means the kind does not belong there at all — that is slot
    learning, not evidence about swapping, and must not spend a refusal."""
    exp = Explorer()
    exp._equip_action("u1", [_item("spear")], _armed(exp))
    exp.on_action_error(None, {"char_uid": "u1", "action": "equip",
                               "reason": "wrong_slot"})
    assert "hand" in exp.slot_wrong["spear"]
    assert exp._swap_failed == set()
    assert exp._swap_refusals == 0


def test_it_stops_swapping_entirely_after_enough_refusals():
    exp = Explorer()
    exp.price.update({"club": 15, "spear": 70, "dagger": 20, "bow": 85})
    for kind in ("spear", "dagger", "bow")[:SWAP_GIVE_UP]:
        exp.equipping["u1"] = (kind, "hand")
        exp._equip_upgrade.add("u1")
        exp.on_action_error(None, {"char_uid": "u1", "action": "equip",
                                   "reason": "slot_occupied"})
    assert exp._swap_unsupported is True
    # Ask about a kind whose pair was NOT among the refusals, or the blacklist alone
    # would answer None and the kill-switch would never be the thing under test.
    assert ("shortsword", "hand") not in exp._swap_failed
    exp.price["shortsword"] = 45
    assert exp._upgrade_slot("shortsword", _eqp(hand="club")) is None


def test_a_successful_swap_leaves_no_refusal_behind():
    """Two oracles for the same claim: nothing was recorded as failed, AND the
    kill-switch counter never moved."""
    exp = Explorer()
    exp._equip_action("u1", [_item("spear")], _armed(exp))
    assert exp._swap_failed == set()
    assert exp._swap_refusals == 0
    assert exp._swap_unsupported is False


# ---- the sell guard ----------------------------------------------------------

def test_it_keeps_gear_that_out_values_what_we_are_wearing():
    """The run-#129 defect itself."""
    exp = Explorer()
    eqp = _armed(exp)
    assert exp._should_sell(_item("spear"), eqp, set(), set()) is False


def test_it_still_sells_gear_that_can_never_be_worn():
    exp = Explorer()
    exp.price.update({"club": 15, "dagger": 20, "shield_wood": 25})
    exp.slot_wrong["club"].update({"outfit", "trinket", "boots"})
    assert exp._should_sell(
        _item("club"), _eqp(hand="dagger", offhand="shield_wood"), set(), set()) is True


def test_the_sell_guard_dies_with_the_kill_switch():
    """If swapping turns out not to exist, holding the item forever is dead weight —
    it must go back to being sellable."""
    exp = Explorer()
    eqp = _armed(exp)
    exp._swap_unsupported = True
    assert exp._should_sell(_item("spear"), eqp, set(), set()) is True


# ---- price learning ----------------------------------------------------------

def test_it_learns_prices_from_the_shop_stock():
    exp = Explorer()
    exp._learn_prices({"shop": {"stock": [{"kind": "spear", "buy_price": 70},
                                          {"kind": "club", "buy_price": 15}]}})
    assert exp.price == {"spear": 70, "club": 15}


def test_it_ignores_stock_entries_with_no_usable_price():
    exp = Explorer()
    exp._learn_prices({"shop": {"stock": [{"kind": "pike", "buy_price": None},
                                          {"kind": "bow"},
                                          {"buy_price": 30}]}})
    assert exp.price == {}


def test_a_frame_with_no_shop_is_harmless():
    exp = Explorer()
    exp._learn_prices({})
    exp._learn_prices({"shop": None})
    exp._learn_prices({"shop": {"stock": None}})   # the shape that actually raises
    assert exp.price == {}


def test_it_reads_a_worn_slot_given_either_frame_shape():
    assert Explorer._worn_kind({"kind": "club"}) == "club"
    assert Explorer._worn_kind("club") == "club"
    assert Explorer._worn_kind(None) is None
    assert Explorer._worn_kind({"item_id": 7}) is None


# ---- v0.109.1: proven slots never probe --------------------------------------

def test_a_kind_seen_worn_never_probes_other_slots():
    """Run #206: a char already WEARING a club walked a second club through
    offhand/outfit/trinket/boots — four wrong_slot errors for a kind whose slot its
    own hand was proving the whole time. Wearing a kind proves its slot; a second
    copy with the proven slot occupied is simply not equipped (it becomes sellable
    surplus, which is income)."""
    exp = Explorer()
    act = exp._equip_action("c1", [_item("club", item_id="club-2")],
                            _eqp(hand="club"))
    assert act is None, f"probed a second copy of a proven-slot kind: {act}"


def test_the_proof_carries_ACROSS_characters():
    """Char A wearing a spear teaches the guild spear->hand; char B, hand occupied,
    holding a spear, must not probe it into offhand — the learning is global."""
    exp = Explorer()
    exp._equip_action("a", [], _eqp(hand="spear"))                 # A teaches
    act = exp._equip_action("b", [_item("spear", item_id="sp-b")],
                            _eqp(hand="club"))
    assert act is None, f"char B probed a kind char A had already proven: {act}"


def test_an_unproven_kind_still_probes_and_a_proven_one_fills_its_empty_slot():
    """The guard must not starve arming: an unproven kind keeps the trial ladder,
    and a proven kind still equips into its (empty) proven slot."""
    exp = Explorer()
    a1 = exp._equip_action("c1", [_item("gadget")], _eqp())
    assert a1 is not None and a1["slot"] == "hand", f"trial ladder broken: {a1}"
    exp.slot_right["club"] = "hand"
    a2 = exp._equip_action("c2", [_item("club")], _eqp())
    assert a2 is not None and a2["slot"] == "hand", f"proven kind failed to equip: {a2}"
