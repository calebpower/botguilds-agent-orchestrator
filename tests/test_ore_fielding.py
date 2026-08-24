"""v0.99.0 — ore-hungry fielding: when the guild is short on ingots, gatherers are routed
to the ORE world (where veins are) so ore->ingot->weapon production scales. #190 measured
the arm rate stuck at 2/30 because nobody mined ore (1 char in the mines, 4 smelts).
"""
from steemer.bot import GuildBot
from steemer.strategy.explorer import INGOT_HUNGRY

HUNGRY = 3   # literal, pinned below (hygiene: no fixture derived from the constant)


def test_pinned_literal():
    assert INGOT_HUNGRY == HUNGRY


def _bot(ore_world="mines"):
    b = GuildBot(strategy="explorer")
    b.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 8,
                "maps": [{"id": "vale"}, {"id": "mines"}]}
    b.tick = 500
    # seed a vein in the ore world so _ore_world can derive it from tile memory
    b.known = {ore_world: {(3, 3): "vein", (3, 4): "floor"}, "vale": {(0, 0): "floor"}}
    from support import seat_bench
    return seat_bench(b)


def _forager(uid="f1"):
    # a FORAGER: level 3 (< GUARDIAN_LEVEL 4 -> not a guardian) and ARMED (a club, so not
    # green either) — lands squarely in the generic gatherer branch where the ore bias is.
    return {"char_uid": uid, "eid": 7, "pos": [3, 3], "hp": 30, "max_hp": 30,
            "stamina": 50, "max_stamina": 56, "level": 3, "gifts": [],
            "stats": {"str": 2, "dex": 2, "int": 1, "vit": 2, "end": 1, "agi": 1},
            "statuses": [], "carry": {"used": 0, "cap": 20}, "inventory": [],
            "equipment": {"hand": {"kind": "club"}}}


def _bare_forager(uid="b1"):
    c = _forager(uid); c["equipment"] = {"hand": None, "offhand": None, "outfit": None,
                                         "trinket": None, "boots": None}
    return c


def _fodder(uid="fd"):
    # stats sum 6 (all ones) with no int gift -> fodder; bare-handed
    c = _forager(uid)
    c["stats"] = {"str": 1, "dex": 1, "int": 1, "vit": 1, "end": 1, "agi": 1}
    c["equipment"] = {"hand": None, "offhand": None, "outfit": None, "trinket": None,
                      "boots": None}
    return c


def _village(char, stash_ingots=0, by_world=None):
    inv = [{"kind": "ingot_copper", "item_id": 1000 + i} for i in range(stash_ingots)]
    return {"world": "village", "tick": 500, "events": [],
            "guild": {"guild_id": "g_us", "gold": 50, "chars_here": [char["char_uid"]],
                      "chars_by_world": by_world or {}, "market_listings": [],
                      "inventory": inv},
            "shop": {"stock": []}, "chars": [char]}


def _embark_map(acts):
    e = [a for a in acts if a.get("action") == "embark"]
    return e[0]["map"] if e else None


# vale gets 3 bodies, mines 4 — so the SAFEST/least-crowded default is vale, NOT the ore
# world; a mines embark can therefore only be the ore bias, never the default tiebreak.
PAD = {"vale": ["va", "vb", "vc"], "mines": ["ma", "mb", "mc", "md"]}


def test_ingot_hungry_routes_a_gatherer_to_the_ORE_world():
    bot = _bot()
    acts = bot.on_frame(_village(_forager(), stash_ingots=0, by_world=PAD))
    assert _embark_map(acts) == "mines", f"ingot-hungry gatherer not routed to ore: {acts}"


def test_a_WELL_STOCKED_guild_does_NOT_force_the_ore_world():
    """Above the ingot threshold, the bias releases and the default (safest/least-crowded
    = vale here) wins — so gathering rebalances back to the surface."""
    bot = _bot()
    acts = bot.on_frame(_village(_forager(), stash_ingots=HUNGRY + 1, by_world=PAD))
    assert _embark_map(acts) == "vale", f"still forced to ore despite ingots: {acts}"


def test_no_bias_when_the_ore_world_is_unknown():
    """We cannot route to ore we have never found. Seed a NON-vein tile in the mines (and
    no vein anywhere): the derivation must return None -> default to the safest world
    (vale). This also kills an 'any tile is a vein world' mutant — that would wrongly read
    the mines (which has a floor tile) as the ore world and route there."""
    bot = _bot()
    bot.known = {"mines": {(0, 0): "floor"}}   # mines seen, but NO vein anywhere
    bot.strategy._ore_world_cache = None
    acts = bot.on_frame(_village(_forager(), stash_ingots=0, by_world=PAD))
    assert _embark_map(acts) == "vale", f"biased to a vein-less world: {acts}"


# --- v0.99.1: only MINE-WORTHY chars are ore-dispatched (protect wizards + stop churn) --

def test_a_BARE_forager_is_NOT_sent_to_the_mines():
    """v0.99.1: a bare forager can't hold the mines (it churns), so ingot-hungry or not it
    stays on the safer surface — the ore dispatch is for chars that can survive to mine."""
    bot = _bot()
    acts = bot.on_frame(_village(_bare_forager(), stash_ingots=0, by_world=PAD))
    assert _embark_map(acts) == "vale", f"a bare forager was sent to mine: {acts}"


def test_FODDER_is_sent_to_the_mines_to_mine():
    """Fodder is the designed risk-taker (expendable, gate-exempt) — the right ore
    workforce."""
    bot = _bot()
    acts = bot.on_frame(_village(_fodder(), stash_ingots=0, by_world=PAD))
    assert _embark_map(acts) == "mines", f"fodder not routed to the ore world: {acts}"


def test_an_ARMED_forager_is_still_sent_to_the_mines():
    """An armed char can hold the mines — it still gets the ore dispatch (regression of
    the original routing test, now under the mine-worthy gate)."""
    bot = _bot()
    acts = bot.on_frame(_village(_forager(), stash_ingots=0, by_world=PAD))  # _forager is armed
    assert _embark_map(acts) == "mines", f"armed forager not routed to ore: {acts}"


def test_a_WIZARD_is_never_ore_dispatched_to_the_mines():
    """Operator: 'try not to kill my wizards.' A wizard reaches its OWN escort/band-gated
    branch before the generic ore dispatch — so even ingot-hungry, an unescorted wizard
    WAITS in the village rather than being sent to mine the dangerous mines. Proves the ore
    dispatch can never grab a wizard."""
    bot = _bot()
    wiz = _forager("wiz")
    wiz["gifts"] = ["int"]
    wiz["stats"] = {"str": 2, "dex": 2, "int": 9, "vit": 2, "end": 2, "agi": 2}  # top seat
    wiz["equipment"] = {"hand": None, "offhand": None, "outfit": None, "trinket": None,
                        "boots": None}
    # no guardian fielded anywhere -> the escort gate holds the wizard home
    acts = bot.on_frame(_village(wiz, stash_ingots=0, by_world=PAD))
    assert _embark_map(acts) != "mines", f"a wizard was ore-dispatched to the mines: {acts}"
