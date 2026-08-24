"""v0.101.0 — the tome fund: SAVE gold for the magic unlock instead of draining it on
discretionary buys. #193 was one tome (150g) from breaking a glass ceiling nobody on the
server has touched — the arch-wizard hit INT 6 — but armour (@70) and bottle (@32) buys
kept gold pinned at ~30, below the tome line. While a tome-ready seat exists and no tome
is bought, those buys are suppressed so gold climbs to the tome.
"""
from steemer.bot import GuildBot
from steemer.strategy.explorer import TOME_BUY_MIN_INT

MIN_INT = 4   # literal, pinned below


def test_pinned_literal():
    assert TOME_BUY_MIN_INT == MIN_INT


def _bot():
    b = GuildBot(strategy="explorer")
    b.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 10, "maps": [{"id": "vale"}]}
    b.tick = 500
    from support import seat_bench
    return seat_bench(b)


def _ready_wizard(uid="wiz", int_=6, hand="club", inv=()):
    # an int-gifted seat (int high enough to top the bench) that is TOME-READY (>= 4)
    return {"char_uid": uid, "eid": 7, "hp": 30, "max_hp": 30, "xp": 0,
            "inventory": list(inv), "stats": {"str": 8, "vit": 8, "end": 8, "int": int_},
            "gifts": ["int"], "spells": [], "spell_cap": 1,
            "equipment": {"hand": {"kind": hand} if hand else None, "offhand": None,
                          "outfit": None, "trinket": None, "boots": None}}


def _village(char, gold, stock):
    # pad chars_by_world to the roster cap so the recruit branch (a guild action that
    # returns before the per-char buys) never preempts what these tests exercise
    pad = {"vale": [f"p{i}" for i in range(10)]}
    return {"world": "village", "tick": 500, "events": [],
            "guild": {"guild_id": "g_us", "gold": gold, "chars_here": [char["char_uid"]],
                      "chars_by_world": pad, "market_listings": [], "inventory": []},
            "shop": {"stock": list(stock)}, "chars": [char]}


ARMOR_STOCK = [{"kind": "shield_wood", "buy_price": 40}]


def _bought(acts, kind):
    return any(a.get("action") == "buy" and a.get("kind") == kind for a in acts)


def test_armor_is_SUPPRESSED_while_saving_for_the_tome():
    """A tome-ready wizard (INT 6, armed), gold 100 (above the armour floor 70, below the
    tome line 150): armour must NOT be bought — the gold is being saved for the tome."""
    bot = _bot()
    acts = bot.on_frame(_village(_ready_wizard(), gold=100, stock=ARMOR_STOCK))
    assert not _bought(acts, "shield_wood"), f"drained the tome fund on armour: {acts}"




def test_the_tome_ITSELF_still_buys_once_gold_reaches_the_line():
    """Saving works: at 150 the tome fires (the fund's whole purpose)."""
    bot = _bot()
    acts = bot.on_frame(_village(_ready_wizard(),
                                 gold=150, stock=[{"kind": "tome_veil", "buy_price": 120}]))
    assert _bought(acts, "tome_veil"), f"saved but never bought the tome: {acts}"


def test_no_saving_when_no_wizard_is_tome_ready():
    """A wizard still below the INT gate is not tome-ready — armour buys normally (no fund
    to protect yet)."""
    bot = _bot()
    acts = bot.on_frame(_village(_ready_wizard(int_=3), gold=100, stock=ARMOR_STOCK))
    assert _bought(acts, "shield_wood"), f"suppressed armour with no tome-ready seat: {acts}"


def test_the_fund_RELEASES_once_the_tome_is_bought():
    """Saving is not forever: once the tome is bought (_tome_bought set), a tome-ready
    wizard's armour buys resume — otherwise gold would be hoarded past the unlock."""
    bot = _bot()
    bot.strategy._tome_bought = True          # the tome has already been bought this run
    acts = bot.on_frame(_village(_ready_wizard(), gold=100, stock=ARMOR_STOCK))
    assert _bought(acts, "shield_wood"), f"still saving after the tome was bought: {acts}"
