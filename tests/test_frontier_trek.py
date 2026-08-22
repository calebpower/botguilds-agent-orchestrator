"""v0.77.0 — the frontier trek: healed characters walk to unexplored ground, however far.

The measurement that forced this (run #158, 58k frames, mature): heal-first (0.76.0)
raised potion buys 0 -> 17 and the median fielded y DID NOT MOVE (3), looted-out share
DID NOT MOVE (29%). The stated falsification's "not the only pin" branch fired. The pin:
after 0.70.0 removed the false frontiers, the nearest TRUE frontier sits 64-192 tiles from
the spawn strip — beyond the 20-tile errand bound in every world — so the frontier offers
never fire from where the roster lives and nothing pulls north.

The trek is unbounded ON PURPOSE, and that needs saying because 0.57.0 added the bound
after unbounded errands caused a 4x move-failure regression. That regression was about
CONTENTS (chests remembered from a stale map); the trek chases TERRAIN, which the map
remembers durably — and `_retreat` has always walked the same map unbounded in the other
direction. What these tests do not prove: that trekking is WORTH it (deaths may rise with
depth — that is next run's measurement, stated in the commit).
"""
from steemer.bot import GuildBot
from steemer.strategy.explorer import TREK_SCORE, SAY_SCORE, FRONTIER_NORTH_SCORE


def _bot():
    b = GuildBot(strategy="explorer")
    b.config = {"party_cap": 5, "world_cap": 10, "roster_cap": 10,
                "maps": [{"id": "vale"}]}
    b.tick = 500
    return b


def _char(healed, pos=(1, 1)):
    inv = [{"kind": "potion_red", "item_id": "p1", "uses": ["use"]}] if healed else []
    return {"char_uid": "c1", "eid": 7, "pos": list(pos), "hp": 30, "max_hp": 30,
            "stamina": 40, "max_stamina": 60, "level": 3, "stats": {}, "gifts": [],
            "statuses": [], "spells": [], "spell_cap": 1, "carry": {"used": 1, "cap": 20},
            "inventory": inv, "equipment": {"hand": {"kind": "club"}}}


def _frame(char, items=()):
    """A 4-wide corridor, fully visible only near the character; the KNOWN map is seeded
    on the bot below, reaching y=59 with bounds [4,100] — so the one true frontier row is
    58 tiles north: far beyond FIELD_GOAL_RANGE=20, like every real world since 0.70.0."""
    tiles = [[x, y, "floor", 0, 0] for x in range(4) for y in range(0, 4)]
    return {"type": "frame", "world": "vale", "tick": 500, "events": [],
            "bounds": [4, 100], "chars": [char],
            "visible": {"tiles": tiles, "entities": [], "items": list(items), "gold": []}}


def _seed_map(bot, depth=60):
    bot.known["vale"] = {(x, y): "floor" for x in range(4) for y in range(depth)}


def test_a_HEALED_char_treks_to_a_frontier_FAR_beyond_the_errand_bound():
    bot = _bot()
    _seed_map(bot)
    acts = bot.on_frame(_frame(_char(healed=True)))
    assert acts and acts[0]["action"] == "move" and acts[0]["dir"] == "N", \
        f"expected a northward trek toward the frontier at y=59: {acts}"


def test_a_BARE_char_does_NOT_trek():
    """A character with no heal bounces off POISON_SAFE_DEPTH at y=12, so the trek would
    walk it 11 tiles into a forced U-turn. It heads home to re-embark instead — asserting
    the direction, not just the absence, so this fails loudly if the ladder changes."""
    bot = _bot()
    _seed_map(bot)
    acts = bot.on_frame(_frame(_char(healed=False)))
    assert acts and acts[0]["action"] == "move" and acts[0]["dir"] == "S", \
        f"a bare char should walk home, not trek: {acts}"


def test_real_local_work_still_beats_the_trek():
    """Loot on the corridor floor: gathering (4.0) must win, healed or not. The trek fills
    an EMPTY tick; it must never displace income. Both actions are a northward move here,
    so the assertion reads the winning candidate's REASON, not the action."""
    from steemer.reasoning import DecisionTrace
    from steemer.strategy.base import FieldContext
    bot = _bot()
    _seed_map(bot)
    ctx = FieldContext(world="vale", known=bot.known["vale"], loot={(1, 3)},
                       bounds=(4, 100))
    tr = DecisionTrace(tick=500, world="vale", char_uid="c1")
    bot.strategy.act(bot, _char(healed=True), {"world": "vale", "tick": 500,
                                               "chars": [_char(healed=True)]}, ctx, tr)
    top = max(c.score for c in tr.candidates)
    won = [c.why for c in tr.candidates if c.score == top]
    assert any("loot" in w for w in won), f"the trek displaced gathering: {won}"
    assert not any("trekking" in w for w in won)


def test_the_trek_sits_between_the_fillers_and_the_local_frontier_push():
    """Pins the band. What this does NOT prove: that TREK_SCORE < gathering matters — the
    trek is offered only inside `if not productive:`, so it structurally cannot co-occur
    with a gathering offer, and the mutant that raises it above 4.0 is unobservable (it
    survived; the placement is the real guard, and test_real_local_work asserts that)."""
    assert SAY_SCORE < TREK_SCORE < FRONTIER_NORTH_SCORE
