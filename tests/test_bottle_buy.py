"""v0.58.0 — BUYING BOTTLES: the hole in the heal supply.

v0.35.0 raised POTION_RESERVE from 100 to 600 on good evidence — heals were 99.6%
FREE-BREWED (4,511 drinks against 16 buys) and the potion-buy was pinning gold at ~100.
That reasoning was correct GIVEN that brewing keeps supplying heals. Nothing guaranteed
it. Brewing needs a `bottle_empty`, and there was never any path to acquire one: the kind
appeared in exactly two places, KEEP (never sell) and the brew gate (count them).

The bottles ran out and the premise failed silently. Run #134, 31,011 frames: 0 brews, 0
`potion_red` carried by any character, and the buy fallback frozen because `gold - 20 >=
600` cannot pass at 183 gold. Downstream, an un-healed character is capped at
POISON_SAFE_DEPTH=12, the shallowest vein sits at y=26, our characters sat at a MEDIAN
DEPTH OF 2 — and v0.54.0's vein-seek walked toward ore it could never reach (751 seek
decisions, 0 characters ever adjacent to a vein, 0 veins broken).

What these tests do NOT prove: that buying bottles restores heals, depth, or ore. That is
a live measurement — brews > 0, potion_red carried > 0%, depth p90 above 12, veins broken
above 0 — and it is the whole point of the change.
"""
from steemer.strategy.explorer import (Explorer, BOTTLE_KEEP, WEAPON_BUY_FLOOR,
                                       POTION_RESERVE)


def _Bot(tick=500):
    """The REAL GuildBot, not a stub. Three times now a hand-rolled double has drifted from
    the interface `village()` actually calls (a missing `observe`, then a missing
    `recently_forged`), and each time the test failed for a reason that had nothing to do
    with what it was testing. A double that has to track the original is a liability."""
    from steemer.bot import GuildBot
    bot = GuildBot("explorer")
    bot.tick = tick
    return bot


def _herb(kind="sungrass", i=0):
    return {"kind": kind, "item_id": f"{kind}-{i}", "uses": ["brew", "taste"], "tier": 1}


def _frame(gold, inv, stock=None):
    if stock is None:
        stock = [{"kind": "bottle_empty", "buy_price": 2},
                 {"kind": "club", "buy_price": 15}]
    return {
        "world": "village", "tick": 500,
        "guild": {"gold": gold},
        "shop": {"stock": stock},
        "chars": [{"char_uid": "u1", "pos": [0, 0], "hp": 20, "max_hp": 20,
                   "stamina": 40, "level": 3, "stats": {}, "carry": {"used": 3, "cap": 21},
                   "inventory": inv,
                   "equipment": {"hand": {"kind": "club"}, "offhand": None,
                                 "outfit": None, "trinket": None, "boots": None}}],
    }


def _buys(gold=WEAPON_BUY_FLOOR + 50, inv=None, stock=None):
    inv = [_herb(i=0), _herb(i=1)] if inv is None else inv
    acts = Explorer().village(_Bot(), _frame(gold, inv, stock))
    return [a for a in acts if a.get("action") == "buy"]


# ---- it buys the missing part ------------------------------------------------

def test_it_buys_a_bottle_when_it_holds_brewables_and_none():
    buys = _buys()
    assert buys, "herbs in the pack and no bottle — the bottle is the only missing part"
    assert buys[0]["kind"] == "bottle_empty"


def test_it_does_not_buy_a_second_bottle():
    inv = [_herb(i=0), _herb(i=1),
           {"kind": "bottle_empty", "item_id": "b0", "uses": []}]
    assert _buys(inv=inv) == [], f"one bottle is a brew's worth (BOTTLE_KEEP={BOTTLE_KEEP})"


def test_it_does_not_buy_a_bottle_with_nothing_to_brew():
    """Gating on a brewable BATCH is what makes this useful rather than a standing 2g
    tax on every character that walks into the village."""
    assert _buys(inv=[]) == []


def test_it_does_not_buy_a_bottle_for_a_batch_that_would_curdle():
    """_choose_brew refuses to mix opposing essences; with no safe batch there is
    nothing a bottle would enable, so there is nothing to buy."""
    inv = [_herb("sungrass", 0), _herb("venom_sac", 1)]
    picks, _, _ = Explorer._choose_brew(inv)
    assert picks is None, "premise: these two cannot be batched safely"
    assert _buys(inv=inv) == []


def test_it_does_not_buy_a_bottle_the_shop_does_not_stock():
    assert _buys(stock=[{"kind": "club", "buy_price": 15}]) == []


# ---- it never competes with arming -------------------------------------------

def test_it_will_not_spend_below_the_weapon_floor():
    """Two gold is trivial, but the ladder still has to hold: arming a bare character is
    the top priority and a bottle must never be the reason gold sits under that floor."""
    assert _buys(gold=WEAPON_BUY_FLOOR) == []
    assert _buys(gold=WEAPON_BUY_FLOOR + 1)


def test_arming_a_bare_character_still_outranks_the_bottle():
    """Ordering, asserted end to end: a bare-handed character with herbs and no bottle
    buys the WEAPON, not the bottle."""
    f = _frame(WEAPON_BUY_FLOOR + 50, [_herb(i=0), _herb(i=1)],
               stock=[{"kind": "bottle_empty", "buy_price": 2},
                      {"kind": "club", "buy_price": 15}])
    f["chars"][0]["equipment"]["hand"] = None
    buys = [a for a in Explorer().village(_Bot(), f) if a.get("action") == "buy"]
    assert buys and buys[0]["kind"] == "club"


# ---- the premise this change rests on ----------------------------------------

def test_bottles_are_still_the_cheap_route_even_now_the_potion_buy_is_reachable():
    """This test used to assert the OPPOSITE — that the potion fallback could not fire at
    our gold (183 on #134) and therefore brewing had to be the supply. v0.69.0 deliberately
    changed that premise, on evidence: seven `potion_red` brewed across ~180,000 frames.

    What survives is the reason bottles came FIRST: a bottle is 2 gold against a potion's
    20, so brewing remains an order of magnitude cheaper per heal wherever it can happen.
    Both routes are now open, which is the point."""
    shop = {"shop": {"stock": [{"kind": "potion_red", "buy_price": 20},
                               {"kind": "bottle_empty", "buy_price": 2}]}}
    assert Explorer._afford_potion(shop, 183) is not None, "reachable at the gold we run"
    assert Explorer._afford_potion(shop, POTION_RESERVE) is None, "never below the floor"
    assert Explorer._shop_price(shop, "bottle_empty") * 10 <= \
        Explorer._afford_potion(shop, 183)[1], "a bottle is far cheaper than a potion"


def test_the_shop_price_is_read_from_the_frame_not_hardcoded():
    assert Explorer._shop_price({"shop": {"stock": [{"kind": "bottle_empty",
                                                    "buy_price": 7}]}}, "bottle_empty") == 7
    assert Explorer._shop_price({"shop": {"stock": []}}, "bottle_empty") is None
    assert Explorer._shop_price({}, "bottle_empty") is None
    assert Explorer._shop_price({"shop": {"stock": [{"kind": "bottle_empty",
                                                     "buy_price": None}]}},
                                "bottle_empty") is None
    # A stock entry with NO price key at all — the shape that raises rather than
    # merely returning the wrong answer, which is why it needs its own case.
    assert Explorer._shop_price({"shop": {"stock": [{"kind": "bottle_empty"}]}},
                                "bottle_empty") is None


# ---- v0.76.0: the heal ranks ABOVE arming, and below the arm FLOOR ------------

def test_the_potion_reserve_sits_BELOW_the_arm_floor():
    """v0.69.0 pinned these EQUAL, reasoning that a heal ranks with arming. The arithmetic
    made that strictly worse than it sounded: the weapon fires at `gold > 150` while
    `_afford_potion` needs `gold - 20 >= 150`, i.e. 170. So the heal was HARDER to afford
    than the weapon and was checked after it, and with a bare bench there is always someone
    to arm — the surplus went at 151 every time and 170 was never reached. Run #157: zero
    potions bought, zero brewed, gold sitting at 149.

    The heal must therefore have first call on gold the weapon cannot touch."""
    from steemer.strategy.explorer import WEAPON_BUY_FLOOR
    assert POTION_RESERVE < WEAPON_BUY_FLOOR, \
        "the heal must be affordable at gold the arm floor has already refused"


def test_a_heal_is_bought_at_THE_GOLD_WE_ACTUALLY_RAN():
    """149 is not a round number, it is the treasury on run #157 at the moment the roster
    was pinned to the bottom 12 rows of the map for want of a 20-gold potion."""
    shop = {"shop": {"stock": [{"kind": "potion_red", "buy_price": 20}]}}
    assert Explorer._afford_potion(shop, 149) == ("potion_red", 20)
    assert Explorer._afford_potion(shop, 200) == ("potion_red", 20)


def test_the_heal_still_has_a_floor_of_its_own():
    """Lowering the reserve is not removing it. The 0.24.0-era drain pinned gold at ~100 by
    spending without one, and POTION_KEEP=1 per character plus this floor are what keep the
    v0.76.0 reordering a one-off redirection rather than a standing leak."""
    shop = {"shop": {"stock": [{"kind": "potion_red", "buy_price": 20}]}}
    # Written out, not derived from POTION_RESERVE. Sized from the constant, this test
    # agreed with itself for any value — the mutant that sets the reserve to ZERO, which is
    # precisely the 0.24.0 drain, left it green.
    assert Explorer._afford_potion(shop, 119) is None, "spent below the 100 floor"
    assert Explorer._afford_potion(shop, 120) == ("potion_red", 20)
    assert POTION_RESERVE == 100, "the floor moved; re-read the numbers in this test"


def test_it_still_refuses_when_the_shop_has_no_heal():
    """Stocked with things that are NOT heals, deliberately: an EMPTY stock cannot tell a
    kind check from no check at all, so the test would pass with the check deleted."""
    tempting = {"shop": {"stock": [{"kind": "potion_blue", "buy_price": 18},
                                   {"kind": "bomb", "buy_price": 60}]}}
    assert Explorer._afford_potion(tempting, 500) is None
    assert Explorer._afford_potion({"shop": {"stock": []}}, 500) is None


# ---- v0.76.0: the ORDER, which is where the bug actually lived ----------------

def _bare_frame(gold):
    """A bare-handed, heal-less character in a shop stocking both. This is run #157's
    situation: someone always needs arming, so the arm branch always had a claim on the
    surplus, and the heal branch below it never saw gold it could use."""
    f = _frame(gold, [], stock=[{"kind": "potion_red", "buy_price": 20},
                                {"kind": "club", "buy_price": 15}])
    f["chars"][0]["equipment"]["hand"] = None
    return f


def test_the_HEAL_is_bought_before_the_weapon():
    """The lever of v0.76.0, stated as an ordering rather than as a number.

    A weapon buys marginal damage in content the character is not allowed to walk to; a
    heal buys the walk. Measured on #157: characters carrying a heal ran to a median y of
    ~50, those without to a median of 0.
    """
    acts = [a for a in Explorer().village(_Bot(), _bare_frame(149))
            if a.get("action") == "buy"]
    assert acts, "bought nothing at 149 gold with both items in stock"
    assert acts[0]["kind"] == "potion_red", \
        f"armed before healing — the ordering bug is back: {acts}"


def test_a_HEALED_character_then_gets_armed():
    """The other side, and the reason this is a REORDERING rather than a deprioritising of
    arming: once the heal is in the pack, the same gold goes to the weapon. Without this
    the suite would be equally happy with a bot that never armed anyone again."""
    f = _bare_frame(WEAPON_BUY_FLOOR + 50)
    f["chars"][0]["inventory"] = [{"kind": "potion_red", "item_id": "p1", "uses": ["use"]}]
    acts = [a for a in Explorer().village(_Bot(), f) if a.get("action") == "buy"]
    assert acts and acts[0]["kind"] == "club", f"expected to arm a healed char: {acts}"


# ---- v0.78.0: the vault outranks the shop ------------------------------------

def _vault_frame(gold, banked_potions=1, char_potion=False):
    """A heal-less character home, with potions sitting in the guild inventory. Run #159's
    discovery: 202 banked potion_red — ~10x everything ever bought — while the treasury
    ground at 109 buying more at 20g."""
    f = _frame(gold, [{"kind": "potion_red", "item_id": "held", "uses": ["drink"]}]
                     if char_potion else [],
               stock=[{"kind": "potion_red", "buy_price": 20}])
    f["guild"]["inventory"] = [{"kind": "potion_red", "item_id": 900 + i, "tier": 1}
                               for i in range(banked_potions)] + \
                              [{"kind": "bottle_empty", "item_id": 800}]
    return f


def _acts(frame):
    return Explorer().village(_Bot(), frame)


def test_a_banked_potion_is_WITHDRAWN_not_bought():
    acts = [a for a in _acts(_vault_frame(gold=200)) if a.get("action") in ("drop", "buy")]
    assert acts and acts[0]["action"] == "drop" and acts[0]["item_id"] == 900, \
        f"spent gold on a potion the vault already holds: {acts}"


def test_the_withdrawal_works_when_the_shop_buy_is_UNAFFORDABLE():
    """The whole point: it is free. Gold below every floor must not block it."""
    acts = [a for a in _acts(_vault_frame(gold=5)) if a.get("action") in ("drop", "buy")]
    assert acts and acts[0]["action"] == "drop", f"a free withdrawal was gated on gold: {acts}"


def test_an_EMPTY_vault_falls_back_to_the_shop():
    acts = [a for a in _acts(_vault_frame(gold=200, banked_potions=0))
            if a.get("action") in ("drop", "buy")]
    assert acts and acts[0]["action"] == "buy" and acts[0]["kind"] == "potion_red", \
        f"with no banked potion the shop buy must still fire: {acts}"


def test_only_a_POTION_is_withdrawn_never_the_bottles_beside_it():
    """The vault also holds 404 bottle_empty; kind matters, not vault position."""
    f = _vault_frame(gold=200)
    f["guild"]["inventory"].reverse()          # bottle first in the list
    acts = [a for a in _acts(f) if a.get("action") == "drop"]
    assert acts and acts[0]["item_id"] == 900, f"withdrew the wrong kind: {acts}"


def test_a_char_already_HOLDING_a_potion_does_not_withdraw_another():
    acts = [a for a in _acts(_vault_frame(gold=200, char_potion=True))
            if a.get("action") == "drop"]
    assert not acts, f"hoarded a second potion past POTION_KEEP: {acts}"


def test_the_withdrawal_is_reachable_THROUGH_THE_BOT():
    """Drives GuildBot.on_frame — the wiring, not just the strategy method. The village
    reachability gate requires this, and it is the gate that would have caught 0.68.0."""
    bot = _Bot()
    f = _vault_frame(gold=5)
    f["chars"][0]["char_uid"] = "u1"
    acts = bot.on_frame(f)
    drops = [a for a in acts if a.get("action") == "drop"]
    assert drops and drops[0]["item_id"] == 900, \
        f"the withdrawal never came out of on_frame: {acts}"


# ---- v0.78.1: phantom vault ids are remembered, not retried -------------------

def test_a_REFUSED_vault_id_is_never_tried_again():
    """Run #160: the head of the vault list was a phantom — 1,181 withdrawals of item
    13913, every one rejected no_such_item, ~1 per frame. A dead id is not a stale-frame
    repeat (the case the no-latch reasoning covered); it is dead FOREVER, so the fix is
    memory, not spacing. After the rejection the next attempt must name the NEXT id."""
    exp = Explorer()
    bot = _Bot()
    f = _vault_frame(gold=200, banked_potions=3)
    f["chars"][0]["char_uid"] = "u1"
    first = [a for a in exp.village(bot, f) if a.get("action") == "drop"]
    assert first and first[0]["item_id"] == 900
    exp.on_action_error(bot, {"action": "drop", "char_uid": "u1", "reason": "no_such_item"})
    bot.tick += 10                                     # clear the per-char cooldown
    second = [a for a in exp.village(bot, f) if a.get("action") == "drop"]
    assert second and second[0]["item_id"] == 901, \
        f"retried the phantom instead of moving on: {second}"


def test_withdrawals_FAIL_CLOSED_after_too_many_phantoms():
    """A vault whose entries keep failing is a vault we do not understand. After
    VAULT_DEAD_LIMIT phantoms the withdrawal stops for the run and the SHOP BUY takes
    over — asserting the fallback, not just the silence, because a heal-less roster is
    the whole disease."""
    # 8 duplicated on purpose, not imported: a fixture sized from VAULT_DEAD_LIMIT agrees
    # with itself at any value. The pin below fails loudly if the constant moves.
    PHANTOMS = 8
    from steemer.strategy.explorer import VAULT_DEAD_LIMIT
    assert VAULT_DEAD_LIMIT == PHANTOMS, "the limit moved; re-read the numbers in this test"
    exp = Explorer()
    bot = _Bot()
    f = _vault_frame(gold=200, banked_potions=PHANTOMS + 4)
    f["chars"][0]["char_uid"] = "u1"
    for i in range(PHANTOMS):
        acts = [a for a in exp.village(bot, f) if a.get("action") == "drop"]
        assert acts, f"stopped early at phantom {i}"
        exp.on_action_error(bot, {"action": "drop", "char_uid": "u1",
                                  "reason": "no_such_item"})
        bot.tick += 10
    acts = exp.village(bot, f)
    drops = [a for a in acts if a.get("action") == "drop"]
    buys = [a for a in acts if a.get("action") == "buy"]
    assert not drops, f"kept withdrawing past the fail-closed limit: {drops}"
    assert buys and buys[0]["kind"] == "potion_red", \
        f"the shop fallback did not take over: {acts}"


def test_an_UNRELATED_drop_error_does_not_poison_the_vault():
    """Field loot-sheds also use `drop`; their failures must not count against vault ids.
    The pending map only holds ids WE offered as withdrawals."""
    exp = Explorer()
    bot = _Bot()
    exp.on_action_error(bot, {"action": "drop", "char_uid": "ghost",
                              "reason": "no_such_item"})
    assert not exp._vault_dead
