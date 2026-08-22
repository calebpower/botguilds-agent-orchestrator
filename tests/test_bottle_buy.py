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

def test_the_potion_buy_really_is_out_of_reach_at_our_gold():
    """Not a tautology about a constant — it is the REASON this change targets bottles
    rather than lowering the reserve. At the gold we actually run (183 on #134), the
    v0.35.0 potion fallback cannot fire, so brewing has to be the supply."""
    assert Explorer._afford_potion(
        {"shop": {"stock": [{"kind": "potion_red", "buy_price": 20}]}}, 183) is None
    assert Explorer._afford_potion(
        {"shop": {"stock": [{"kind": "potion_red", "buy_price": 20}]}},
        POTION_RESERVE + 20) is not None


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
