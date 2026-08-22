"""v0.63.0 — keep the tome, learn the form.

"Magic / spellweaving" has sat near the top of the wishlist for fifty passes, and I had
assumed the block was cost: a tome is 120-150 gold against a 150-gold arm floor, so buying
one would strand a bare character. That was never the block.

We have SOLD 74 TOMES — tome_ring x22, tome_step x16, tome_field x14, tome_veil x13,
tome_bolt x9 — most recently on runs #130, #135 and #137, for **36-44 gold apiece**. Each one
is a whole spell FORM (docs/06: a tome teaches a form by being `use`d, and is consumed).
`learned` events in our entire recorded history: ZERO.

The mechanism is the same leak as `bone` and raw `ore`: a tome carries `use`, not `equip`,
so `_should_sell` files it under "pure loot -> bank it". We do not need to BUY what keeps
falling into our hands; we need to stop selling it.

What these tests do NOT prove: that a learned form is worth casting, or that casting works
at all. That is the next slice. This one stops the bleeding and gets a form into a
character's head.
"""
from steemer.strategy.explorer import Explorer, TOME_PREFIX


class _Bot:
    config: dict = {}

    def __init__(self, tick=500):
        self.tick = tick
        self.storage = None


def _tome(kind="tome_bolt", i=0):
    return {"kind": kind, "item_id": f"{kind}-{i}", "uses": ["use"], "tier": 1}


def _char(spells=(), cap=1, inv=None):
    return {"char_uid": "u1", "pos": [0, 0], "hp": 20, "max_hp": 20, "stamina": 40,
            "level": 3, "stats": {"int": 2}, "carry": {"used": 3, "cap": 21},
            "spells": list(spells), "spell_cap": cap,
            "inventory": inv if inv is not None else [_tome()],
            "equipment": {"hand": {"kind": "club"}, "offhand": None, "outfit": None,
                          "trinket": None, "boots": None}}


def _frame(char, gold=200, tick=500):
    return {"world": "village", "tick": tick, "guild": {"gold": gold},
            "shop": {"stock": []}, "chars": [char]}


def _acts(exp, char, gold=200, tick=500):
    """A distinct `tick` per call matters: a character that just acted is skipped for
    VILLAGE_ACTION_COOLDOWN (v0.14.0, the run-#38 re-send storm guard), so two calls at
    the same tick would test the cooldown rather than the thing under test."""
    return exp.village(_Bot(tick), _frame(char, gold, tick))


EMPTY_EQP = {s: None for s in ("hand", "offhand", "outfit", "trinket", "boots")}


# ---- stop selling the form ----------------------------------------------------

def test_a_tome_is_not_sold_while_the_character_can_learn_it():
    """The defect itself, 74 times over."""
    exp = Explorer()
    assert exp._should_sell(_tome(), dict(EMPTY_EQP), set(), set(), set(), set(),
                            can_learn=True) is False


def test_a_tome_IS_sold_once_the_character_is_at_its_spell_cap():
    """At the cap a new form FORGETS the oldest (docs/06), so there it really is surplus
    and the anti-clog rule stands. Without this the change would trade one hoarding bug
    for another."""
    exp = Explorer()
    assert exp._should_sell(_tome(), dict(EMPTY_EQP), set(), set(), set(), set(),
                            can_learn=False) is True


def test_ordinary_loot_is_unaffected():
    exp = Explorer()
    junk = {"kind": "tomato", "item_id": "t1", "uses": [], "tier": 1}
    assert exp._should_sell(junk, dict(EMPTY_EQP), set(), set(), set(), set(),
                            can_learn=True) is True


# ---- capacity ------------------------------------------------------------------

def test_capacity_is_read_from_the_frame_not_assumed():
    assert Explorer._can_learn(_char(spells=(), cap=1)) is True
    assert Explorer._can_learn(_char(spells=("bolt",), cap=1)) is False
    assert Explorer._can_learn(_char(spells=("bolt",), cap=2)) is True


def test_an_unknown_capability_is_not_guessed():
    """A frame without `spell_cap` must not be treated as "room for one" — acting on a
    guess is what curdles brews and storms unknown_product."""
    c = _char()
    del c["spell_cap"]
    assert Explorer._can_learn(c) is False


# ---- learning ------------------------------------------------------------------

def test_it_uses_a_carried_tome():
    acts = _acts(Explorer(), _char())
    assert acts and acts[0]["action"] == "use"
    assert acts[0]["item_id"] == "tome_bolt-0"


def test_learning_is_ordered_BEFORE_selling():
    """Ordering is the whole fix: the sell step runs first for anything it considers loot,
    which is how 74 tomes went to the counter for 36 gold before anything could use them."""
    exp = Explorer()
    char = _char(inv=[{"kind": "tomato", "item_id": "junk", "uses": [], "tier": 1},
                      _tome()])
    acts = _acts(exp, char)
    assert acts and acts[0]["action"] == "use", f"expected `use` first, got {acts}"


def test_a_character_at_its_cap_does_not_learn():
    acts = _acts(Explorer(), _char(spells=("bolt",), cap=1))
    assert not any(a.get("action") == "use" for a in acts)


def test_a_refused_tome_is_not_retried_for_that_character():
    """INT gates which tomes a character may use (docs/06), so a refusal is durable
    information about THAT character — the same learn-by-rejection as the equip slots and
    the forge recipes. Without it we would re-issue every village visit forever."""
    exp = Explorer()
    char = _char()
    acts = _acts(exp, char)
    assert acts[0]["action"] == "use"
    exp.on_action_error(None, {"char_uid": "u1", "action": "use",
                               "reason": "stat_requirement"})
    assert ("u1", "tome_bolt") in exp._tome_failed
    assert not any(a.get("action") == "use" for a in _acts(exp, _char(), tick=900))


def test_a_refusal_does_not_condemn_a_DIFFERENT_tome():
    """The refusal is about this character and this tome's INT gate, not about tomes."""
    exp = Explorer()
    _acts(exp, _char())
    exp.on_action_error(None, {"char_uid": "u1", "action": "use",
                               "reason": "stat_requirement"})
    acts = _acts(exp, _char(inv=[_tome("tome_veil")]), tick=900)
    assert acts and acts[0]["action"] == "use"
    assert acts[0]["item_id"] == "tome_veil-0"


def test_a_failed_use_of_a_NON_tome_condemns_nothing():
    """`use` is also how potions are drunk (2,582 sent). A failed potion must not
    blacklist a tome."""
    exp = Explorer()
    exp._using["u1"] = "potion_red"
    exp.on_action_error(None, {"char_uid": "u1", "action": "use", "reason": "whatever"})
    assert exp._tome_failed == set()


def test_the_tome_prefix_covers_the_forms_we_have_actually_seen():
    """Asserted against the kinds observed in our own sale history rather than a copy of
    the constant: tome_ring, tome_step, tome_field, tome_veil, tome_bolt."""
    for kind in ("tome_ring", "tome_step", "tome_field", "tome_veil", "tome_bolt"):
        assert kind.startswith(TOME_PREFIX)
