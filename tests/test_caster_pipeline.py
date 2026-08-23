"""v0.83.0 — the caster pipeline: pre-bank INT on the gifted, buy the tome when rich.

Magic is untouched by every guild on the server (0 implements in ~340k observations, 0
spells anywhere). The chain is tome -> INT -> `learned` -> cast. These tests pin the two
new links; what they cannot prove is the INT threshold itself (unknown until the first
`use` succeeds — a refusal is free and `_tome_to_learn` already retries after stat
growth, which existing tests in test_field_learning.py cover).
"""
from steemer.bot import GuildBot


def _bot():
    b = GuildBot(strategy="explorer")
    b.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 10,
                "maps": [{"id": "vale"}]}
    b.tick = 500
    return b


def _char(gifts=("int",), int_=1, xp=50, inv=(), uid="c1"):
    return {"char_uid": uid, "eid": 7, "hp": 30, "max_hp": 30, "xp": xp,
            "inventory": list(inv), "stats": {"vit": 8, "end": 8, "str": 8, "int": int_},
            "gifts": list(gifts), "spells": [], "spell_cap": 1,
            "equipment": {"hand": {"kind": "club"}, "offhand": None, "outfit": None,
                          "trinket": None, "boots": None}}


def _frame(char, gold=50, stock=()):
    return {"world": "village", "tick": 500, "events": [],
            "guild": {"guild_id": "g_us", "gold": gold, "chars_here": [char["char_uid"]],
                      "chars_by_world": {}, "market_listings": []},
            "shop": {"stock": list(stock)}, "chars": [char]}


def _first(acts, kind):
    return next((a for a in acts if a.get("action") == kind), None)


# ---- pre-banking INT ----------------------------------------------------------

def test_an_int_GIFTED_char_banks_INT_first():
    """INT at 1, gifted (cost 8//2=4), 50 XP banked: the spend goes to INT, not VIT —
    the pre-bank that runs in parallel with saving for the tome."""
    acts = _bot().on_frame(_frame(_char()))
    sp = _first(acts, "spend_xp")
    assert sp and sp["stat"] == "int", f"the gifted caster banked {sp} instead of int"


def test_an_UNGIFTED_char_keeps_the_survival_priority():
    acts = _bot().on_frame(_frame(_char(gifts=("str", "end"))))
    sp = _first(acts, "spend_xp")
    assert sp is None or sp["stat"] != "int", f"ungifted char banked int: {sp}"


def test_at_the_caster_target_the_gifted_char_reverts_to_survival():
    """INT 6 = CASTER_INT_TARGET (duplicated: see the pin below): the pre-bank stops and
    XP goes back to durability. Without this the gift would drain every XP forever."""
    acts = _bot().on_frame(_frame(_char(int_=6)))
    sp = _first(acts, "spend_xp")
    assert sp is None or sp["stat"] != "int", f"kept banking int past the target: {sp}"
    from steemer.strategy.explorer import CASTER_INT_TARGET
    assert CASTER_INT_TARGET == 6, "the target moved; re-read the numbers in this test"


# ---- buying the tome ----------------------------------------------------------

_TOME_STOCK = ({"kind": "tome_veil", "buy_price": 120},
               {"kind": "potion_red", "buy_price": 20})


def test_the_designate_buys_the_tome_above_the_reserve():
    """220 = 120 tome + 100 potion reserve: the magic unlock must never eat the heal."""
    char = _char(inv=[{"kind": "potion_red", "item_id": "p", "uses": ["drink"]}])
    acts = _bot().on_frame(_frame(char, gold=220, stock=_TOME_STOCK))
    buy = _first(acts, "buy")
    assert buy and buy["kind"] == "tome_veil", f"no tome at 220 gold: {acts}"


def test_no_tome_below_the_line():
    char = _char(inv=[{"kind": "potion_red", "item_id": "p", "uses": ["drink"]}])
    acts = _bot().on_frame(_frame(char, gold=219, stock=_TOME_STOCK))
    buy = _first(acts, "buy")
    assert not (buy and buy["kind"] == "tome_veil"), f"ate into the heal reserve: {buy}"


def test_an_UNGIFTED_char_never_buys_a_tome():
    """The tome is consumed on learning by its HOLDER; buying it onto a char whose INT
    will never rise strands 120g of unlock on the wrong shelf."""
    char = _char(gifts=("str",), inv=[{"kind": "potion_red", "item_id": "p",
                                       "uses": ["drink"]}])
    acts = _bot().on_frame(_frame(char, gold=400, stock=_TOME_STOCK))
    buy = _first(acts, "buy")
    assert not (buy and buy["kind"] == "tome_veil"), f"ungifted char bought the tome: {buy}"


def test_a_char_already_HOLDING_a_tome_does_not_buy_another():
    """The held tome is marked REFUSED first, deliberately: a learnable tome triggers the
    village learning branch before the buy is ever reached, which shadowed this guard's
    mutant. The reachable case is a refused tome waiting on INT — exactly when a naive
    buy would stack a second 120g unlock behind the first."""
    bot = _bot()
    char = _char(inv=[{"kind": "potion_red", "item_id": "p", "uses": ["drink"]},
                      {"kind": "tome_veil", "item_id": "t", "uses": ["use"]}])
    bot.strategy._tome_failed[("c1", "tome_veil")] = 10 ** 9   # refused, bar unreachably high
    acts = bot.on_frame(_frame(char, gold=400, stock=_TOME_STOCK))
    buy = _first(acts, "buy")
    assert not (buy and buy["kind"] == "tome_veil"), f"hoarded a second tome: {buy}"
