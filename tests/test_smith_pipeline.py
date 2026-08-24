"""v0.98.0 — the smith pipeline: forge-to-arm's real bottleneck was material CONVERGENCE.

On #189 the arm rate was stuck: 0/28 bare chars held both a lumber AND an ingot (a
spear needs both on one char), while 19 lumber sat unused in the guild stash. Ingots are
the scarce material; lumber is plentiful. So a char holding an ingot but no lumber
withdraws a lumber from the stash to become forge-ready. (Fix A — a tool in hand still
forges a weapon — is pinned in test_forge.py.)
"""
from steemer.bot import GuildBot
from steemer.strategy.explorer import VAULT_DEAD_LIMIT

VAULT_DEAD = 8   # literal, pinned below (hygiene: fixtures must not derive from the constant under test)


def _bot():
    b = GuildBot(strategy="explorer")
    b.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 10,
                "maps": [{"id": "vale"}]}
    b.tick = 500
    from support import seat_bench
    return seat_bench(b)


def _smith(inv, uid="c1"):
    return {"char_uid": uid, "eid": 7, "hp": 30, "max_hp": 30, "xp": 0,
            "inventory": list(inv), "stats": {"str": 8, "vit": 8, "end": 8, "int": 1},
            "gifts": [], "spells": [], "spell_cap": 1,
            "equipment": {"hand": None, "offhand": None, "outfit": None,
                          "trinket": None, "boots": None}}


def _village(char, stash=()):
    return {"world": "village", "tick": 500, "events": [],
            "guild": {"guild_id": "g_us", "gold": 50, "chars_here": [char["char_uid"]],
                      "chars_by_world": {}, "market_listings": [],
                      "inventory": list(stash)},
            "shop": {"stock": []}, "chars": [char]}


def _ingot(iid=1):
    return {"kind": "ingot_copper", "item_id": iid, "uses": ["forge"]}


def _lumber_stash(iid=900):
    return {"kind": "lumber", "item_id": iid}


def _drop(acts):
    return next((a for a in acts if a.get("action") == "drop"), None)


def test_an_ingot_holder_withdraws_lumber_from_the_stash():
    """The convergence unlock: an ingot but no lumber, 19 in the stash -> withdraw one."""
    bot = _bot()
    acts = bot.on_frame(_village(_smith([_ingot()]), stash=[_lumber_stash(901)]))
    d = _drop(acts)
    assert d is not None and d["item_id"] == 901, f"did not withdraw stash lumber: {acts}"


def test_no_withdrawal_when_the_char_ALREADY_has_lumber():
    """A forge-ready char (both materials) must go straight to forging, not withdraw."""
    bot = _bot()
    acts = bot.on_frame(_village(_smith([_ingot(), {"kind": "lumber", "item_id": 5,
                                                    "uses": ["forge"]}]),
                                 stash=[_lumber_stash(901)]))
    assert _drop(acts) is None, f"withdrew lumber despite already holding some: {acts}"


def test_no_withdrawal_without_an_ingot():
    """The ingot is the scarce half; with NO ingot there is nothing to pair, so a char
    carrying neither material must not pull lumber it cannot use. Empty inventory isolates
    the ingot condition (a lumber-only char is already covered by the 'not has_lumber'
    guard) — so this is the case that kills a 'has_ingot = True' mutant."""
    bot = _bot()
    acts = bot.on_frame(_village(_smith([]), stash=[_lumber_stash(901)]))
    assert _drop(acts) is None, f"withdrew lumber with no ingot to pair: {acts}"


def test_the_vault_dead_failsafe_stops_withdrawing():
    """Mirror of the potion vault-mirage guard: once VAULT_DEAD_LIMIT phantom ids are
    known, stop withdrawing this run rather than storm no_such_item."""
    assert VAULT_DEAD_LIMIT == VAULT_DEAD    # guard the literal below
    bot = _bot()
    bot.strategy._vault_dead = set(range(VAULT_DEAD))
    acts = bot.on_frame(_village(_smith([_ingot()]), stash=[_lumber_stash(901)]))
    assert _drop(acts) is None, "kept withdrawing past the vault-dead limit"
