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
from steemer.strategy.explorer import (Explorer, FORGE_PRODUCTS, FORGE_RECIPES,
                                       FORGE_STAMINA)


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
    assert product == "shield_iron", "the unbuyable armour must lead the ladder"
    assert (n_ing, n_lum) == FORGE_RECIPES[0]
    assert len(ids) == n_ing + n_lum


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
    exp.wont_fit.add("shield_iron")
    (product, _, _), _, _ = exp._choose_forge(_ing(2) + _lum(2), dict(EMPTY), stamina=40)
    assert product != "shield_iron"


# ---- learning from rejection -------------------------------------------------

def test_a_REJECTED_recipe_is_never_tried_again():
    """THE loop that must close. The quantities are undocumented, so the server's rejection
    is the documentation — but only if we remember it."""
    exp = Explorer()
    inv = _ing(3) + _lum(3)
    first = exp._choose_forge(inv, dict(EMPTY), stamina=40)
    recipe = first[0]
    exp._forge_attempt["c1"] = recipe
    exp.on_action_error(None, {"action": "forge", "char_uid": "c1", "reason": "crafting"})
    assert recipe in exp._forge_failed
    second = exp._choose_forge(inv, dict(EMPTY), stamina=40)
    assert second[0] != recipe, "re-offered a recipe the server had just rejected"


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
        exp._forge_attempt["c1"] = recipe
        exp.on_action_error(None, {"action": "forge", "char_uid": "c1", "reason": "crafting"})
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
