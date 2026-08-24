"""v0.52.0 — FORGING: the last step of the M3a chain.

Deferred since docs/07 because the `product` name was "unpublished" and a blind guess
storms `unknown_product`. It was never unpublished — 189 rival `forged`/`forge_started`
events in our own database name it outright, e.g.
`{"kind": "forge_started", "product": "shield_iron", "ticks": 14}`.

`shield_iron` leads the product ladder deliberately: it is ARMOUR, the shop does not sell
it at any price, and 100% of our characters have an empty offhand. It is the one product
where forging is not the cheaper route but the ONLY route.

Recipe QUANTITIES are still undocumented, so the design is learn-by-rejection: try a small
ordered ladder and let the server's error blacklist what does not work. These tests pin
that loop closing — an attempt that is never remembered would retry the same doomed recipe
forever, which is the shape of every re-send bug this project has had.
"""
from steemer.strategy.explorer import (Explorer, FORGE_PRODUCTS, FORGE_WEAPON_FIRST,
                                       FORGE_RECIPES, FORGE_STAMINA, FORGE_FAIL_LIMIT)


def _ing(n=1, kind="ingot_copper"):
    return [{"kind": kind, "item_id": f"{kind}-{i}", "uses": ["forge"]} for i in range(n)]


def _lum(n=1):
    return [{"kind": "lumber", "item_id": f"lumber-{i}", "uses": ["forge"]} for i in range(n)]


EMPTY = {s: None for s in ("hand", "offhand", "outfit", "trinket", "boots")}


# ---- when it fires -----------------------------------------------------------

def test_it_forges_when_holding_both_an_ingot_and_lumber():
    exp = Explorer()
    got = exp._choose_forge(_ing(1) + _lum(1), dict(EMPTY), stamina=40)
    assert got is not None
    (product, n_ing, n_lum), ids, why = got
    # v0.95.0: an EMPTY HAND forges a WEAPON first (arming beats armouring the offhand)
    assert product == "spear", "a bare hand must forge a weapon before a shield"
    assert (n_ing, n_lum) == FORGE_RECIPES[0]
    assert len(ids) == n_ing + n_lum


def test_forge_priority_is_WEAPON_FIRST_only_when_the_hand_is_empty():
    """v0.95.0, from the idle-village / passive-char reports (28/30 bare-handed). A char
    that can't fight forges a weapon before armour; an already-armed char still forges the
    unbuyable shield. The SAME materials, different order — the whole fix is the order."""
    exp = Explorer()
    # empty hand -> spear (weapon)
    (bare_product, _, _), _, _ = exp._choose_forge(_ing(2) + _lum(2), dict(EMPTY), stamina=40)
    assert bare_product == "spear", f"bare hand should forge a weapon, got {bare_product}"
    # hand already holds a club -> shield_iron (armour) leads again
    armed = dict(EMPTY, hand={"kind": "club"})
    (armed_product, _, _), _, _ = exp._choose_forge(_ing(2) + _lum(2), armed, stamina=40)
    assert armed_product == "shield_iron", \
        f"an armed char should forge armour, got {armed_product}"
    assert FORGE_WEAPON_FIRST[0] == "spear" and FORGE_PRODUCTS[0] == "shield_iron"


def test_it_does_NOT_forge_without_metal():
    exp = Explorer()
    assert exp._choose_forge(_lum(4), dict(EMPTY), stamina=40) is None


def test_it_does_NOT_forge_without_lumber():
    exp = Explorer()
    assert exp._choose_forge(_ing(4), dict(EMPTY), stamina=40) is None


def test_it_refuses_below_the_stamina_cost():
    """docs/07: brew/forge cost 15, paid up front. Attempting under that spends the tick
    and earns a bounce, which is exactly what the MOVE_STAMINA_SAFETY lesson was about."""
    exp = Explorer()
    assert exp._choose_forge(_ing(1) + _lum(1), dict(EMPTY), stamina=FORGE_STAMINA - 1) is None
    assert exp._choose_forge(_ing(1) + _lum(1), dict(EMPTY), stamina=FORGE_STAMINA) is not None


def test_it_skips_a_product_the_character_already_WEARS():
    """Forging a shield for someone already holding one banks nothing."""
    exp = Explorer()
    eqp = dict(EMPTY, offhand={"kind": "shield_iron"})
    (product, _, _), _, _ = exp._choose_forge(_ing(2) + _lum(2), eqp, stamina=40)
    assert product != "shield_iron"


def test_it_skips_a_product_learned_UNUSABLE():
    exp = Explorer()
    exp.wont_fit["shield_iron"] = 999
    (product, _, _), _, _ = exp._choose_forge(_ing(2) + _lum(2), dict(EMPTY), stamina=40)
    assert product != "shield_iron"


# ---- learning from rejection -------------------------------------------------

def _reject(exp, recipe, uid="c1"):
    exp._forge_attempt[uid] = recipe
    exp.on_action_error(None, {"action": "forge", "char_uid": uid, "reason": "crafting"})


def test_a_repeatedly_REJECTED_recipe_is_abandoned():
    """THE loop that must close — but v0.64.0 changed WHEN it closes.

    v0.52.0 abandoned a recipe on its FIRST refusal, which assumed `wrong_materials` is a
    function of (product, ingots, lumber). Run #140 showed it is not: the identical
    product, material kinds and quantities both succeeded and failed within one run. A
    one-strike permanent blacklist against a non-deterministic signal is a ratchet, and it
    had condemned all five spear recipes and all five shield_iron recipes — including
    `(spear, 1, 1)`, which produced `forged` events on runs #129 and #140.

    So a refusal now costs a strike, and FORGE_FAIL_LIMIT of them abandon the recipe."""
    exp = Explorer()
    inv = _ing(3) + _lum(3)
    recipe = exp._choose_forge(inv, dict(EMPTY), stamina=40)[0]
    # Counts hardcoded, NOT derived from FORGE_FAIL_LIMIT. A fixture sized from the
    # constant under test moves with it — setting the limit to 1 made the old version
    # vacuous, and mutation testing has now caught me doing this FOUR times
    # (VEIN_SEEK_RANGE, SCARCE_LONE_KEEP, OVERBURDENED_TTL, here). "One refusal does not
    # condemn; three do" is the policy claim, independent of the number.
    _reject(exp, recipe)
    assert recipe not in exp._forge_failed, "one refusal must not condemn a recipe"
    _reject(exp, recipe)
    _reject(exp, recipe)
    assert recipe in exp._forge_failed, "three refusals abandon it"
    later = exp._choose_forge(inv, dict(EMPTY), stamina=40)
    assert later is None or later[0] != recipe, "re-offered an abandoned recipe"


def test_a_PROVEN_recipe_survives_any_number_of_refusals():
    """Proof outranks refusal, and this is the case that broke the forge: `(spear, 1, 1)`
    demonstrably works, and refusals had still condemned it."""
    exp = Explorer()
    inv = _ing(3) + _lum(3)
    recipe = exp._choose_forge(inv, dict(EMPTY), stamina=40)[0]
    exp._forge_proven.add(recipe)
    for _ in range(FORGE_FAIL_LIMIT * 3):
        _reject(exp, recipe)
    assert recipe not in exp._forge_failed
    assert exp._forge_fails.get(recipe, 0) == 0, "a proven recipe accrues no strikes"


def test_it_walks_the_recipe_ladder_and_then_moves_to_the_next_product():
    """Every quantity for a product is tried before giving up on it, and then the ladder
    advances rather than stalling."""
    exp = Explorer()
    inv = _ing(3) + _lum(3)
    seen = []
    for _ in range(len(FORGE_RECIPES) + 2):
        got = exp._choose_forge(inv, dict(EMPTY), stamina=40)
        if got is None:
            break
        recipe = got[0]
        seen.append(recipe)
        for _ in range(FORGE_FAIL_LIMIT):     # v0.64.0: abandoning takes FORGE_FAIL_LIMIT
            _reject(exp, recipe)
    assert len(seen) == len(set(seen)), f"repeated a recipe: {seen}"
    assert {r[0] for r in seen} & set(FORGE_PRODUCTS[1:]), "never advanced past the first product"


def test_a_rejection_for_a_DIFFERENT_action_does_not_blacklist_a_recipe():
    """A move or buy failure must not poison the forge ladder — the over-broad version of
    exactly this rule caused the v0.49.0 retry storm."""
    exp = Explorer()
    exp._forge_attempt["c1"] = ("shield_iron", 1, 1)
    exp.on_action_error(None, {"action": "move", "char_uid": "c1", "reason": "not_enough_stamina"})
    assert exp._forge_failed == set()


def test_an_unattributable_rejection_blacklists_nothing():
    exp = Explorer()
    exp.on_action_error(None, {"action": "forge", "char_uid": "nobody", "reason": "crafting"})
    assert exp._forge_failed == set()


# ---- v0.64.0: crediting a completed forge ------------------------------------

def test_a_forged_event_proves_the_recipe_that_character_last_attempted():
    """The positive-evidence half. Without it the ladder only ever loses options: every
    refusal removes one and nothing ever restores one, so the forge trends to inert.

    Driven through the REAL GuildBot, because the credit depends on the bot's event
    parsing and the strategy's pending attempt agreeing — two halves that a stub would let
    drift apart."""
    from steemer.bot import GuildBot

    bot = GuildBot("explorer")
    exp = Explorer()
    bot.strategy = exp
    recipe = ("spear", 1, 1)
    exp._forge_attempt["u1"] = recipe
    bot.tick = 100
    bot._forged["u1"] = 100

    frame = {"world": "village", "tick": 100, "guild": {"gold": 0},
             "shop": {"stock": []},
             "chars": [{"char_uid": "u1", "pos": [0, 0], "hp": 9, "max_hp": 9,
                        "stamina": 40, "level": 1, "stats": {}, "spells": [],
                        "spell_cap": 1, "carry": {"used": 0, "cap": 21},
                        "inventory": [], "equipment": {}}]}
    exp.village(bot, frame)
    assert recipe in exp._forge_proven


def test_a_forged_event_CLEARS_an_earlier_wrongful_abandonment():
    """The run-#140 repair itself: `(spear, 1, 1)` had been abandoned, and it works."""
    from steemer.bot import GuildBot

    bot = GuildBot("explorer")
    exp = Explorer()
    bot.strategy = exp
    recipe = ("spear", 1, 1)
    exp._forge_failed.add(recipe)
    exp._forge_fails[recipe] = FORGE_FAIL_LIMIT
    exp._forge_attempt["u1"] = recipe
    bot.tick = 100
    bot._forged["u1"] = 100
    exp.village(bot, {"world": "village", "tick": 100, "guild": {"gold": 0},
                      "shop": {"stock": []},
                      "chars": [{"char_uid": "u1", "pos": [0, 0], "hp": 9, "max_hp": 9,
                                 "stamina": 40, "level": 1, "stats": {}, "spells": [],
                                 "spell_cap": 1, "carry": {"used": 0, "cap": 21},
                                 "inventory": [], "equipment": {}}]})
    assert recipe not in exp._forge_failed, "proof must undo a wrongful abandonment"
    assert exp._forge_fails.get(recipe, 0) == 0


def test_the_forged_credit_expires_so_a_later_attempt_is_not_credited_by_an_old_forge():
    """A stale `forged` event must not vouch for a DIFFERENT recipe attempted much later.
    The window only has to outlive a craft (10-14 ticks by the server's own
    `forge_started`), not the run — offsets hardcoded, as above."""
    from steemer.bot import GuildBot

    bot = GuildBot("explorer")
    bot._forged["u1"] = 100
    bot.tick = 110
    assert bot.recently_forged("u1") is True, "still fresh 10 ticks on — a craft takes that"
    bot.tick = 400
    assert bot.recently_forged("u1") is False, "300 ticks later it vouches for nothing"


def test_the_forged_window_stays_in_the_band_that_case_assumes():
    from steemer.bot import FORGED_TTL
    assert 14 < FORGED_TTL < 300


def test_a_forged_event_for_ANOTHER_guild_proves_us_nothing():
    """Events name an `eid`, a different namespace from `char_uid`. Rivals forge constantly
    (189 of their events are in our history) and crediting theirs would validate recipes we
    have never successfully run."""
    from steemer.bot import GuildBot

    bot = GuildBot("explorer")
    bot.tick = 50
    bot.on_frame({"type": "frame", "world": "vale", "tick": 50, "events": [
        {"kind": "forged", "eid": 999999, "item": "spear"}],
        "chars": [{"char_uid": "u1", "eid": 7, "pos": [0, 0], "hp": 9, "max_hp": 9,
                   "stamina": 9, "inventory": [], "equipment": {}}],
        "visible": {"tiles": [], "entities": [], "items": [], "gold": []}})
    assert bot.recently_forged("u1") is False


# ---- v0.98.0 smith pipeline: a TOOL in hand still forges a weapon --------------------
from steemer.strategy.explorer import FORGE_HAND_TOOLS


def test_a_pickaxe_in_hand_still_forges_a_WEAPON():
    """#189: one pickaxe-wielding miner forged shield_iron 418x because a tool filled its
    hand and read as 'armed'. A tool is not a weapon — weapon-first must still fire."""
    exp = Explorer()
    assert "pickaxe" in FORGE_HAND_TOOLS
    eqp = dict(EMPTY, hand={"kind": "pickaxe"})
    (product, _, _), _, _ = exp._choose_forge(_ing(2) + _lum(2), eqp, stamina=40)
    assert product == "spear", f"a pickaxe-holder forged {product}, not a weapon"


def test_a_real_WEAPON_in_hand_still_forges_armour():
    """A char already holding a real weapon (club) is armed — it forges the shield."""
    exp = Explorer()
    eqp = dict(EMPTY, hand={"kind": "club"})
    (product, _, _), _, _ = exp._choose_forge(_ing(2) + _lum(2), eqp, stamina=40)
    assert product == "shield_iron", f"an armed char forged {product}, not armour"
