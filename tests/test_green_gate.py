"""v0.92.0 — the GREEN-RECRUIT band gate (run #180: 16 dead, all fresh recruits, all
shallow, killed by a chaser-pit band on vale's spawn strip; zero were fodder by choice).

A GREEN char — level <= 1 AND bare hands, and not fodder — embarks only into a world the
danger ledger does not currently call dangerous; with no safe world open it waits in the
village, exactly like a band-gated wizard. Fodder stays exempt (sacrifice doctrine), and
so does anyone armed or level 2+.

Danger fixture values are LITERALS (melee_preds=3 > the dense threshold of 2; fresh
tick) with a pin below — the hygiene ratchet forbids deriving fixtures from the
constants under test.
"""
from steemer.bot import GuildBot

DENSE = 2          # duplicated from COHESION_PRED_DENSE; pinned below
TTL = 1200         # duplicated from THREAT_TTL; pinned below


def test_the_pinned_literals_still_match():
    from steemer.strategy import explorer
    assert explorer.COHESION_PRED_DENSE == DENSE
    assert explorer.THREAT_TTL == TTL


def _bot():
    # roster_cap 8 = the 7 fielded padders + the one villager: AT cap, so the recruit
    # branch (which returns early and preempts every embark — the vacuous-oracle trap
    # this file hit on its first run) stays closed and only the gate decides.
    b = GuildBot(strategy="explorer")
    b.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 8,
                "maps": [{"id": "vale"}, {"id": "mines"}]}
    b.tick = 500
    from support import seat_bench
    return seat_bench(b)


# vale holds 3, mines 4: ABSENT the gate the fewest-bodies tiebreak sends the villager
# to VALE — so in every both-worlds-open test the hot world is also the DEFAULT pick,
# and a deleted gate cannot pass by coincidence.
PAD = {"vale": ["va", "vb", "vc"], "mines": ["ma", "mb", "mc", "md"]}


def _recruit(uid, level=1, armed=False, stats_total=9):
    # stats sum 9 (> the fodder line) so role stays forager; armed toggles the gate
    stats = {"str": 2, "dex": 2, "int": 1, "vit": 2, "end": 1, "agi": 1}
    assert sum(stats.values()) == stats_total
    return {"char_uid": uid, "eid": abs(hash(uid)) % 10000, "pos": [3, 3], "hp": 20,
            "max_hp": 20, "stamina": 48, "max_stamina": 56, "level": level,
            "stats": stats, "gifts": ["str", "agi"], "statuses": [], "spells": [],
            "spell_cap": 1, "carry": {"used": 0, "cap": 20}, "inventory": [],
            "equipment": {"hand": {"kind": "club"}} if armed else {}}


def _fodder(uid):
    c = _recruit(uid)
    c["stats"] = {"str": 1, "dex": 1, "int": 1, "vit": 1, "end": 1, "agi": 1}
    return c


def _village(here_chars, by_world_uids):
    return {"world": "village", "tick": 500, "events": [],
            "guild": {"guild_id": "g_us", "gold": 50,
                      "chars_here": [c["char_uid"] for c in here_chars],
                      "chars_by_world": by_world_uids, "market_listings": []},
            "shop": {"stock": []}, "chars": here_chars}


def _mark_dangerous(bot, world, tick=500):
    # melee_preds 3 > DENSE (2), observed at the current tick (well inside TTL)
    bot.strategy._world_danger[world] = (0.0, 3.0, tick)


def _embarks(acts):
    return [a for a in acts if a.get("action") == "embark"]


def test_a_green_recruit_waits_out_a_hot_band():
    """Both worlds dangerous -> the level-1 bare-handed recruit does NOT embark.
    Padding at 8 (not 9): an embark must be POSSIBLE so only the gate can hold it back
    (the vacuous-at-world-cap trap caught by test_escort's own mutant)."""
    bot = _bot()
    _mark_dangerous(bot, "vale")
    _mark_dangerous(bot, "mines")
    acts = bot.on_frame(_village([_recruit("fresh")], PAD))
    assert not _embarks(acts), f"green recruit embarked into a hot band: {acts}"


def test_a_green_recruit_routes_to_the_SAFE_world():
    bot = _bot()
    _mark_dangerous(bot, "vale")
    acts = bot.on_frame(_village([_recruit("fresh")], PAD))
    emb = _embarks(acts)
    assert emb and emb[0]["map"] == "mines", \
        f"expected embark to the safe mines (vale is hot AND the default tiebreak), got {acts}"


def test_fodder_is_EXEMPT_from_the_gate():
    """The sacrifice doctrine is operator-directed: bottom rolls still ship out into
    the hot band."""
    bot = _bot()
    _mark_dangerous(bot, "vale")
    _mark_dangerous(bot, "mines")
    acts = bot.on_frame(_village([_fodder("meat")], PAD))
    assert _embarks(acts), "fodder was band-gated — the sacrifice doctrine broke"


def test_an_armed_level1_is_not_green():
    bot = _bot()
    _mark_dangerous(bot, "vale")
    _mark_dangerous(bot, "mines")
    acts = bot.on_frame(_village([_recruit("clubber", armed=True)], PAD))
    assert _embarks(acts), "an ARMED level-1 was gated; the gate is about bare hands"


def test_a_stale_danger_read_does_not_gate():
    """Danger older than THREAT_TTL is forgotten — the default is to field, or a single
    hot cycle would freeze recruitment flow forever."""
    bot = _bot()
    bot.strategy._world_danger["vale"] = (0.0, 3.0, 500 - TTL)     # exactly expired
    bot.strategy._world_danger["mines"] = (0.0, 3.0, 500 - TTL)
    acts = bot.on_frame(_village([_recruit("fresh")], PAD))
    assert _embarks(acts), "an expired danger read still gated the recruit"
