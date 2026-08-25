"""v0.114.0 — proposal B: beatable-predator engagement, with the operator's condition
("go for proposal B, but protect my wizards") pinned as tests.

The engage-seek closes on a LONE, bestiary-priced predator so an armed healthy char
converts it to xp instead of coexisting with it forever (the live wolf moves ~0.22
tiles/tick and never catches a working char — pre-lever its 8 xp was simply
unfarmable). Wizard protection is structural: the `develop` gate itself excludes the
ROLE, closing the hole where a rank-chosen seat-holder without the int gift passed
`not caster` and would have traded hits.
"""
from steemer.bot import GuildBot
from steemer.strategy.explorer import (ENGAGE_KINDS, ENGAGE_SEEK_RADIUS,
                                       COMBAT_SEEK_RADIUS)


def test_pinned_literals():
    assert ENGAGE_KINDS == frozenset({"wolf", "lava_ant", "spider_brown",
                                      "crab_green"}), \
        "every member must carry a MEASURED dph <= 4.3 (findings #156/#290) before entry"
    assert ENGAGE_SEEK_RADIUS == 10


def _bot():
    b = GuildBot(strategy="explorer")
    b.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 10,
                "maps": [{"id": "vale"}, {"id": "mines"}]}
    b.tick = 500
    from support import seat_bench
    return seat_bench(b)


def _char(uid, pos=(5, 5), int_stat=1):
    # int STAT high -> outranks the bench into a wizard SEAT; gifts stay EMPTY either
    # way, so a seat-holder here is exactly the non-gifted wizard the hole was about.
    return {"char_uid": uid, "eid": abs(hash(uid)) % 10000, "pos": list(pos), "hp": 30,
            "max_hp": 30, "stamina": 48, "max_stamina": 56, "level": 5,
            "stats": {"int": int_stat}, "gifts": [], "statuses": [], "spells": [],
            "spell_cap": 1, "carry": {"used": 0, "cap": 20}, "inventory": [],
            "equipment": {"hand": {"kind": "club"}}}


def _field(chars, entities, w=24, h=24):
    tiles = [[x, y, "floor", 0, 0] for x in range(w) for y in range(h)]
    return {"type": "frame", "world": "vale", "tick": 500, "events": [],
            "bounds": [w, 200], "chars": chars,
            "visible": {"tiles": tiles, "entities": entities, "items": [],
                        "gold": []}}


def _mob(kind, pos, eid=901):
    return {"eid": eid, "kind": kind, "faction": "monster", "pos": list(pos),
            "hp_frac": 1.0}


def _acts_for(acts, uid):
    return [a for a in acts if a.get("char_uid") == uid]


# The game's compass (docs/02, nav.DIRS): NORTH IS +y — deeper into the world, away
# from the village strip at y=0. Duplicated here deliberately (test-against-source):
# a test that imported nav.DIRS would agree with an inverted compass.
STEP = {"N": (0, 1), "S": (0, -1), "E": (1, 0), "W": (-1, 0)}


def test_an_armed_guardian_attacks_the_adjacent_lone_wolf_but_a_wizard_never_does():
    """Two oracles on one fixture: the control char PROVES the fight is on offer
    (else the wizard assertion would pass vacuously on a broken develop gate), and
    the seat-holder — identical except for outranking the bench into a wizard seat,
    with NO int gift — refuses it."""
    bot = _bot()
    control = _char("ctl", pos=(5, 5), int_stat=1)
    acts = bot.on_frame(_field([control], [_mob("wolf", (5, 6))]))
    atk = [a for a in _acts_for(acts, "ctl") if a["action"] == "attack"]
    assert atk and atk[0]["target"] == [5, 6], \
        f"the control guardian did not fight the adjacent lone wolf: {acts}"

    bot2 = _bot()
    wiz = _char("wiz", pos=(5, 5), int_stat=5)   # seat, no gift — the 0.114.0 hole
    acts2 = bot2.on_frame(_field([wiz], [_mob("wolf", (5, 6))]))
    assert not [a for a in _acts_for(acts2, "wiz") if a["action"] == "attack"], \
        f"a wizard seat-holder traded hits with a predator: {acts2}"


def _dist(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def test_the_engage_seek_closes_on_a_lone_wolf_but_never_pulls_a_wizard():
    bot = _bot()
    control = _char("ctl", pos=(5, 5), int_stat=1)
    # EAST of the char, deliberately orthogonal to the northward frontier pull
    # (everything known ends at y=24, bounds say y<200): a mutant that deletes the
    # engage offer leaves only the frontier's N step, and the closing assert fails.
    wolfpos = (9, 5)
    acts = bot.on_frame(_field([control], [_mob("wolf", wolfpos)]))
    moves = [a for a in _acts_for(acts, "ctl") if a["action"] == "move"]
    assert moves, f"no move offered at all: {acts}"
    step = STEP[moves[0]["dir"]]
    after = (5 + step[0], 5 + step[1])
    assert _dist(after, wolfpos) < _dist((5, 5), wolfpos), \
        f"the control char did not close on the lone wolf: {acts}"

    bot2 = _bot()
    wiz = _char("wiz", pos=(5, 5), int_stat=5)
    acts2 = bot2.on_frame(_field([wiz], [_mob("wolf", wolfpos)]))
    for a in _acts_for(acts2, "wiz"):
        if a["action"] == "move":
            s = STEP[a["dir"]]
            after = (5 + s[0], 5 + s[1])
            assert _dist(after, wolfpos) >= _dist((5, 5), wolfpos), \
                f"the engage-seek pulled a wizard toward a predator: {acts2}"


def test_a_boar_is_not_on_the_menu():
    """Allowlist discipline: boar's measured dph is 6.0 — off the list, and the seek
    must not close on it even for a healthy armed guardian."""
    bot = _bot()
    control = _char("ctl", pos=(5, 5), int_stat=1)
    boarpos = (9, 5)
    acts = bot.on_frame(_field([control], [_mob("boar", boarpos)]))
    for a in _acts_for(acts, "ctl"):
        if a["action"] == "move":
            s = STEP[a["dir"]]
            after = (5 + s[0], 5 + s[1])
            assert _dist(after, boarpos) >= _dist((5, 5), boarpos), \
                f"the seek closed on a boar (dph 6.0, not priced for a club): {acts}"


def test_a_paired_wolf_is_not_lone_and_is_not_sought():
    """Loneness: two wolves 2 apart — arriving adjacent to one puts the other in
    range, the exact pair the swarm gate refuses. No approach."""
    bot = _bot()
    control = _char("ctl", pos=(5, 5), int_stat=1)
    w1, w2 = (9, 5), (11, 5)
    acts = bot.on_frame(_field([control], [_mob("wolf", w1, eid=901),
                                           _mob("wolf", w2, eid=902)]))
    for a in _acts_for(acts, "ctl"):
        if a["action"] == "move":
            s = STEP[a["dir"]]
            after = (5 + s[0], 5 + s[1])
            assert _dist(after, w1) >= _dist((5, 5), w1), \
                f"sought a PAIRED wolf: {acts}"
