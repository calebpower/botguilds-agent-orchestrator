"""v0.49.0 — the in-flight intent latch: a stale frame must not buy the same thing twice.

Measured on run #117: one character bought SIX clubs at ticks 1397061/67/73/79/85/91 —
exactly VILLAGE_ACTION_COOLDOWN apart — and another bought four, then re-equipped the SAME
item_id five times. ~135 gold wasted in one run against a treasury that hovers near 145 and
has never sustained the 200 armor floor.

The cause is that a TIMER is the wrong termination condition for "has my purchase landed?".
When the frame is staler than the cooldown, the character still looks bare when the timer
expires, so the buy goes out again. The latch replaces elapsed time with observation:
confirmation clears it, an explicit rejection clears it, and the TTL is only a safety net
so a silently-failed action cannot block a character forever.
"""
from steemer.strategy.explorer import Explorer, INTENT_TTL
from steemer.bot import GuildBot


def _bot():
    b = GuildBot(strategy="explorer")
    b.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 30,
                "maps": [{"id": "vale"}], "shop": {}}
    return b


def _char(inv=(), eqp=None, uid="c1"):
    return {"char_uid": uid, "pos": [0, 0], "hp": 30, "max_hp": 30, "stamina": 40,
            "carry": {"used": 0, "cap": 20}, "inventory": list(inv), "stats": {"str": 4},
            "equipment": eqp if eqp is not None else {"hand": None}}


def _vframe(char, tick, gold=500):
    return {"world": "village", "tick": tick,
            "guild": {"gold": gold, "chars_here": [char["char_uid"]], "chars_by_world": {}},
            "shop": {"stock": [{"kind": "club", "buy_price": 15, "sell_price": 3}]},
            "chars": [char]}


# ---- intent identity ---------------------------------------------------------

def test_a_buy_is_keyed_by_KIND_because_that_is_what_can_double_spend():
    assert Explorer._intent_key({"action": "buy", "kind": "club"}) == "buy:club"


def test_an_equip_is_keyed_by_item_id():
    assert Explorer._intent_key({"action": "equip", "item_id": 77}) == "equip:77"


def test_a_SELL_is_deliberately_not_latched():
    """Each sale names a distinct item_id, so a repeat cannot double-spend the way a
    repeated `buy {kind}` can — latching it would only slow the village loop down."""
    assert Explorer._intent_key({"action": "sell", "item_id": 5}) is None


# ---- confirmation, both directions -------------------------------------------

def test_a_buy_lands_when_the_kind_appears_in_the_inventory():
    assert Explorer._intent_landed("buy:club", _char(inv=[{"kind": "club", "item_id": 1}]))


def test_a_buy_ALSO_lands_when_the_kind_is_already_equipped():
    """The equip step can run before we next look, so checking inventory alone would miss
    it and buy a second one."""
    c = _char(eqp={"hand": {"kind": "club"}})
    assert Explorer._intent_landed("buy:club", c)


def test_a_buy_has_NOT_landed_while_the_frame_is_still_stale():
    assert not Explorer._intent_landed("buy:club", _char())


def test_an_equip_lands_when_the_item_LEAVES_the_inventory():
    assert Explorer._intent_landed("equip:9", _char(inv=[{"kind": "x", "item_id": 8}]))


def test_an_equip_has_NOT_landed_while_the_item_is_still_carried():
    assert not Explorer._intent_landed("equip:9", _char(inv=[{"kind": "x", "item_id": 9}]))


# ---- end to end: the six-club storm ------------------------------------------

def test_a_stale_frame_does_NOT_buy_the_same_club_twice():
    """THE regression. The same bare character, seen again well past the 6-tick cooldown
    with the purchase not yet reflected, must not buy a second club."""
    bot = _bot()
    char = _char()
    first = bot.on_frame(_vframe(char, tick=3))
    assert first and first[0]["action"] == "buy" and first[0]["kind"] == "club"
    # ...same stale char, 30 ticks later — five cooldowns' worth
    second = bot.on_frame(_vframe(char, tick=33))
    assert not any(a.get("action") == "buy" for a in second), second


def test_it_buys_again_once_the_TTL_gives_up_AND_forgets_the_abandoned_intent():
    """The safety net: a silently-failed purchase must not block the character forever.

    The second assertion matters on its own — falling through would let it buy again even
    if the entry were left behind, so only checking the buy leaves the abandoned intent
    untested. State that still claims something is in flight after we have given up on it
    lies to every later reader of that dict."""
    bot = _bot()
    char = _char()
    bot.on_frame(_vframe(char, tick=3))
    assert "c1" in bot.strategy._village_intent
    later = bot.on_frame(_vframe(char, tick=3 + INTENT_TTL + 1))
    assert any(a.get("action") == "buy" for a in later), later
    # re-issued, so the entry present now must be the NEW intent, not the abandoned one
    key, issued = bot.strategy._village_intent["c1"]
    assert issued == 3 + INTENT_TTL + 1, "the abandoned intent was never cleared"


def test_a_REJECTION_frees_the_character_immediately():
    """An explicit error is as good a termination as a confirmation — we know it did not
    land. Only silence should wait out the TTL. Without this the latch blocks the
    wrong_slot -> next-slot retry for a full TTL."""
    bot = _bot()
    char = _char()
    bot.on_frame(_vframe(char, tick=3))
    bot.strategy.on_action_error(bot, {"action": "buy", "char_uid": "c1",
                                       "reason": "not_enough_gold"})
    again = bot.on_frame(_vframe(char, tick=12))
    assert any(a.get("action") == "buy" for a in again), again


def test_a_CONFIRMED_purchase_frees_the_character_without_waiting():
    bot = _bot()
    char = _char()
    bot.on_frame(_vframe(char, tick=3))
    armed = _char(inv=[{"kind": "club", "item_id": 42, "uses": ["equip"]}])
    nxt = bot.on_frame(_vframe(armed, tick=12))
    assert nxt and nxt[0]["action"] == "equip", nxt      # moved on to equipping it


def test_an_abandoned_intent_is_cleared_even_when_the_char_has_NOTHING_to_do():
    """The only case where clearing is observable — and therefore the only honest test of
    it. When the character goes on to act, `_village_act` overwrites the entry anyway; it
    is a character with no village action available whose stale intent would otherwise
    linger, telling any later reader that a purchase is still in flight when we gave up on
    it long ago."""
    bot = _bot()
    char = _char()
    bot.on_frame(_vframe(char, tick=3))
    assert "c1" in bot.strategy._village_intent
    # Armed, carrying nothing, broke: no buy, no sell, no equip, no brew. The weapon is
    # deliberately NOT a club — with a club equipped the intent would be CONFIRMED and this
    # would silently test the confirmation path instead of the TTL path. (It did, until a
    # mutation survivor pointed it out.)
    idle = _char(eqp={"hand": {"kind": "dagger"}, "offhand": {"kind": "x"},
                      "outfit": {"kind": "x"}, "trinket": {"kind": "x"},
                      "boots": {"kind": "x"}})
    acts = bot.on_frame(_vframe(idle, tick=3 + INTENT_TTL + 1, gold=0))
    assert not any(a.get("char_uid") == "c1" for a in acts), acts
    assert "c1" not in bot.strategy._village_intent, "abandoned intent was left behind"
