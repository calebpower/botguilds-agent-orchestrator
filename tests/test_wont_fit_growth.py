"""v0.65.0 — a stat refusal must expire when the character out-grows it.

The HANDOFF asks one question of every latch in the strategy: WHAT RESTORES AN OPTION? For
`wont_fit` the answer had been "nothing", and that is a ratchet with a known key — the gate
is a STAT requirement and stats GROW. `spend_xp` has fired 2,151 times; between runs #129 and
#141 our maxima went str 2->6, vit 3->8, level 6->18. A kind refused at str 2 stayed refused
at str 6 forever, in all seven places `wont_fit` is consulted: equipping (twice), the armour
buy, the forge product ladder, and the SELL rule — which then banks the item.

There was a second fault stacked on it. Keyed on KIND alone, the set was global: one weak
character's refusal condemned that kind for every stronger character too.

Both are fixed by recording the BAR rather than a bare "no" — the stat total that was
refused — so the restoring event is explicit and per-character.

What these tests do NOT prove: that the refused stat is the one that grew. The frame never
says which requirement was short, so the sum is a proxy; a character that grew the wrong
stat simply gets one more refusal, which raises the bar and costs a single action.
"""
from steemer.strategy.explorer import Explorer

EMPTY = {s: None for s in ("hand", "offhand", "outfit", "trinket", "boots")}


def _char(uid="u1", **stats):
    return {"char_uid": uid, "stats": stats or {"str": 2}}


def _refuse(exp, uid, kind, slot="hand"):
    exp.equipping[uid] = (kind, slot)
    exp.on_action_error(None, {"char_uid": uid, "action": "equip",
                               "reason": "stat_requirement"})


# ---- the ratchet, released ---------------------------------------------------

def test_a_refusal_holds_while_the_character_has_not_grown():
    exp = Explorer()
    exp._stat_total["u1"] = 6
    _refuse(exp, "u1", "bow")
    assert exp._wont_fit("bow", "u1") is True


def test_growing_past_the_bar_restores_the_option():
    """The defect itself: str 2 -> 6 happened, and the refusal never noticed."""
    exp = Explorer()
    exp._stat_total["u1"] = 6
    _refuse(exp, "u1", "bow")
    exp._stat_total["u1"] = 7
    assert exp._wont_fit("bow", "u1") is False


def test_a_second_refusal_raises_the_bar_rather_than_re_latching():
    """Otherwise a grown character would retry every single village visit forever — the
    storm every latch in this file exists to stop."""
    exp = Explorer()
    exp._stat_total["u1"] = 6
    _refuse(exp, "u1", "bow")
    exp._stat_total["u1"] = 9
    assert exp._wont_fit("bow", "u1") is False
    _refuse(exp, "u1", "bow")
    assert exp._wont_fit("bow", "u1") is True, "the bar is now 9"


def test_a_weaker_characters_refusal_cannot_LOWER_the_bar():
    """The bar is the highest refusal seen, not the latest. Otherwise a weak character
    trying a bow after a strong one had already been refused would drop the bar to its own
    total — and the strong character, which we know cannot wear it, would start retrying
    every village visit."""
    exp = Explorer()
    exp._stat_total["strong"] = 20
    _refuse(exp, "strong", "bow")
    assert exp.wont_fit["bow"] == 20
    exp._stat_total["weak"] = 6
    _refuse(exp, "weak", "bow")
    assert exp.wont_fit["bow"] == 20, "a weaker refusal must not lower the bar"
    assert exp._wont_fit("bow", "strong") is True


# ---- it is no longer one character's verdict on everyone ---------------------

def test_a_weak_characters_refusal_does_not_condemn_a_strong_one():
    """`wont_fit` was a set of KINDS, so this was exactly backwards: the weakest character
    to try a bow decided whether anyone could wear one."""
    exp = Explorer()
    exp._stat_total["weak"] = 6
    exp._stat_total["strong"] = 20
    _refuse(exp, "weak", "bow")
    assert exp._wont_fit("bow", "weak") is True
    assert exp._wont_fit("bow", "strong") is False


def test_without_a_character_in_hand_the_question_is_about_the_BEST_of_us():
    """The sell rule and the forge ladder have no character in hand. A kind that one of us
    can wear must not be banked as unusable — that is how gear is lost."""
    exp = Explorer()
    exp._stat_total["weak"] = 6
    _refuse(exp, "weak", "bow")
    assert exp._wont_fit("bow") is True, "nobody has out-grown it yet"
    exp._stat_total["strong"] = 20
    assert exp._wont_fit("bow") is False, "now someone has"


def test_a_kind_never_refused_is_never_blocked():
    exp = Explorer()
    exp._stat_total["u1"] = 1
    assert exp._wont_fit("club", "u1") is False


# ---- the stat total ----------------------------------------------------------

def test_the_stat_total_is_the_sum_of_the_frames_stats():
    assert Explorer._stat_sum({"stats": {"str": 3, "vit": 4}}) == 7
    assert Explorer._stat_sum({"stats": {}}) == 0
    assert Explorer._stat_sum({}) == 0


def test_non_numeric_stats_do_not_break_the_total():
    """The frame shape has changed under us before; a string where an int was expected must
    not take the whole decision path down."""
    assert Explorer._stat_sum({"stats": {"str": 3, "gift": "int"}}) == 3


def test_the_sell_rule_stops_banking_gear_we_have_out_grown():
    """End to end, through the rule that actually loses the item."""
    exp = Explorer()
    exp._stat_total["weak"] = 6
    _refuse(exp, "weak", "bow")
    bow = {"kind": "bow", "item_id": "b1", "uses": ["equip"]}
    assert exp._should_sell(bow, dict(EMPTY), set(), set(), set(), set()) is True
    exp._stat_total["strong"] = 20
    assert exp._should_sell(bow, dict(EMPTY), set(), set(), set(), set()) is False
