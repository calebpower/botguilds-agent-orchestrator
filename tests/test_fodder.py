"""v0.87.0 — fodder (operator: "if we get a really shitty recruit, we should probably
classify them as 'fodder' and have them sacrifice themselves").

Scoped conservatively this pass: classification (bottom ~11% of rolls), NOT ONE COIN ever
spent on them, maximum boldness, hits traded down to 40% hp. Deliberate bait mechanics
(pulling aggro off the party) are deferred until we see how free-trading fodder dies.
"""
from steemer.bot import GuildBot
from steemer.strategy.explorer import role_of


def _stats(total):
    base = {"str": 1, "dex": 1, "int": 1, "vit": 1, "end": 1, "agi": 1}
    extra = total - 6
    for k in list(base):
        while extra > 0 and base[k] < 2:
            base[k] += 1; extra -= 1
    return base


def test_the_bottom_rolls_are_fodder():
    assert role_of({"gifts": ["str", "agi"], "level": 1, "stats": _stats(6)}) == "fodder"
    assert role_of({"gifts": ["str", "agi"], "level": 1, "stats": _stats(7)}) == "fodder"
    assert role_of({"gifts": ["str", "agi"], "level": 1, "stats": _stats(8)}) == "forager"


def test_an_int_gifted_bad_roll_is_STILL_a_wizard():
    """INT is the point; the gift halves the grind regardless of the other dice."""
    assert role_of({"gifts": ["int", "agi"], "level": 1, "stats": _stats(6)}) == "wizard"


def test_levelling_never_promotes_fodder_out_of_its_class():
    assert role_of({"gifts": ["str", "agi"], "level": 9, "stats": _stats(7)}) == "fodder"


def test_missing_stats_are_UNKNOWN_not_bad():
    """A char we cannot fully read must never be condemned to the expendable class:
    sparse stat dicts (test fixtures, partial frames) read as forager, not fodder."""
    assert role_of({"gifts": ["str"], "level": 1, "stats": {"vit": 1}}) == "forager"


def test_not_one_coin_is_spent_on_fodder():
    """Gold for everything, shop stocked with everything, hand empty, no heal — and the
    fodder character buys NOTHING. The same frame with a forager buys (the control that
    keeps this test able to fail)."""
    def frame(char):
        return {"world": "village", "tick": 3, "events": [],
                "guild": {"guild_id": "g_us", "gold": 400, "chars_here": [char["char_uid"]],
                          "chars_by_world": {"mines": [f"v{i}" for i in range(9)]},
                          "market_listings": []},
                "shop": {"stock": [{"kind": "potion_red", "buy_price": 20},
                                   {"kind": "club", "buy_price": 15}]},
                "chars": [char]}
    def ch(uid, stats):
        return {"char_uid": uid, "eid": 7, "hp": 30, "max_hp": 30, "xp": 0,
                "inventory": [], "stats": stats, "gifts": ["str", "agi"],
                "equipment": {"hand": None, "offhand": None, "outfit": None,
                              "trinket": None, "boots": None}}
    bot = GuildBot(strategy="explorer")
    bot.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 10,
                  "maps": [{"id": "vale"}]}
    bot.tick = 500
    fodder_acts = bot.on_frame(frame(ch("f1", _stats(6))))
    assert not any(a.get("action") == "buy" for a in fodder_acts), \
        f"spent coin on fodder: {fodder_acts}"
    bot2 = GuildBot(strategy="explorer")
    bot2.config = bot.config; bot2.tick = 500
    forager_acts = bot2.on_frame(frame(ch("f2", _stats(9))))
    assert any(a.get("action") == "buy" for a in forager_acts), \
        f"the CONTROL forager bought nothing — this test can no longer fail: {forager_acts}"
