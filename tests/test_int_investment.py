"""v0.67.0 — invest INT in the character that has demonstrably been refused a tome.

Run #145 finally exercised the whole magic chain and showed exactly one link broken. Two
tomes DROPPED; we picked them up and KEPT them (v0.63.0 — zero tomes sold, against 74 sold
historically); we issued `use` on exactly those item_ids; and the server answered
`stat_requirement` five times. Every link works except the stat.

INT was absent from `XP_PRIORITY` altogether, so it never rose above its starting 1-2 — and
INT gates which tomes a character may use, `max_mana`, `spell_cap` AND `essence_cap`. Magic
was locked out of the game by our XP policy, not by the game.

The investment is targeted rather than a reordering of the survival priority for everyone:
only a character CARRYING a tome it has ALREADY been refused. That refusal is recorded
(v0.63.0), the retry-on-growth is built (v0.65.1), so this closes the loop with no new
machinery and no cost to any character not carrying a tome.

What these tests do NOT prove: that INT 8 is enough for any particular tome, or that a
learned form is worth casting. The first is discovered by retrying as INT climbs; the second
is the still-unbuilt casting slice.
"""
from steemer.strategy.explorer import (Explorer, XP_PRIORITY, XP_PRIORITY_CASTER,
                                       XP_STAT_TARGET)


def _tome(kind="tome_bolt"):
    return {"kind": kind, "item_id": f"{kind}-1", "uses": ["use"]}


def _char(xp=500, **stats):
    base = {"vit": 8, "end": 8, "str": 8, "int": 1}
    base.update(stats)
    return {"char_uid": "u1", "stats": base, "gifts": [], "xp": xp}


# ---- the targeting -----------------------------------------------------------

def test_a_refused_tome_holder_wants_INT():
    exp = Explorer()
    exp._tome_failed[("u1", "tome_bolt")] = 6
    assert exp._needs_int("u1", [_tome()]) is True


def test_merely_HOLDING_a_tome_is_not_enough():
    """An unrefused tome may simply not have been tried yet — the next village visit will
    try it. Only a character we have WATCHED be turned away has shown that INT is the
    obstacle, and spending XP on a guess costs survival stats."""
    exp = Explorer()
    assert exp._needs_int("u1", [_tome()]) is False


def test_a_refusal_for_a_DIFFERENT_tome_does_not_count():
    exp = Explorer()
    exp._tome_failed[("u1", "tome_veil")] = 6
    assert exp._needs_int("u1", [_tome("tome_bolt")]) is False


def test_another_characters_refusal_does_not_count():
    exp = Explorer()
    exp._tome_failed[("someone_else", "tome_bolt")] = 6
    assert exp._needs_int("u1", [_tome()]) is False


def test_a_character_carrying_no_tome_never_wants_INT():
    exp = Explorer()
    exp._tome_failed[("u1", "tome_bolt")] = 6
    assert exp._needs_int("u1", [{"kind": "club", "item_id": "c1"}]) is False


# ---- what it changes ---------------------------------------------------------

def test_a_refused_tome_holder_raises_INT_first():
    assert Explorer._pick_xp_stat(_char(), wants_int=True) == "int"


def test_everyone_else_keeps_the_survival_priority_untouched():
    """The survival ordering was earned across the whole poison-death arc; this change must
    not touch it for the characters it was written for."""
    assert Explorer._pick_xp_stat(_char(vit=1), wants_int=False) == "vit"
    assert Explorer._pick_xp_stat(_char(vit=8, end=1), wants_int=False) == "end"
    assert XP_PRIORITY_CASTER[1:] == XP_PRIORITY, "the survival order is preserved beneath INT"


def test_INT_still_respects_the_cap_and_falls_back():
    """At the cap the caster must not stall — it goes back to whatever survival stat it
    can still use, or the tome-holder would bank XP forever."""
    assert Explorer._pick_xp_stat(
        _char(int=XP_STAT_TARGET, vit=1), wants_int=True) == "vit"


def test_INT_still_respects_affordability():
    """The v0.22.0 lesson: returning an unaffordable stat means spend_xp never fires at
    all. A caster with almost no XP must still spend it on something cheap."""
    poor = _char(xp=1, int=7, vit=1)
    assert Explorer._xp_cost(7, False) > 1, "premise: INT at 7 is unaffordable here"
    assert Explorer._pick_xp_stat(poor, wants_int=True) != "int"


def test_a_caster_with_no_affordable_stat_banks_rather_than_erroring():
    assert Explorer._pick_xp_stat(_char(xp=0), wants_int=True) is None
