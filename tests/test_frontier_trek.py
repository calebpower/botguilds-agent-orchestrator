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


# ---- v0.80.0: chess, not checkers — the trek chops through ---------------------
#
# Operator screenshots, 2026-08-22: a character stood at a pine belt and read it as a dead
# end, while holding the chop mechanic it has had since 0.45.0. `tree` was SOLID to every
# path search, so a forest was masonry. Now a breakable tile is an expensive STEP
# (nav.BREAK_COST ~ four attack ticks plus the move), and the trek spends actions now for
# position later.

def _belt_frame(char):
    """The known map is seeded on the bot: a corridor to the frontier CLOSED by a tree
    belt at y=20 — no detour exists. The old trek returned None here and the character
    declared the world looted-out one screen away from unexplored ground."""
    tiles = [[x, y, "floor", 0, 0] for x in range(4) for y in range(0, 4)]
    return {"type": "frame", "world": "vale", "tick": 500, "events": [],
            "bounds": [4, 100], "chars": [char],
            "visible": {"tiles": tiles, "entities": [], "items": [], "gold": []}}


def _seed_belt(bot):
    known = {(x, y): "floor" for x in range(4) for y in range(60)}
    for x in range(4):
        known[(x, 20)] = "tree"          # a full belt: no way around, only through
    bot.known["vale"] = known


def test_a_tree_belt_is_a_ROUTE_not_a_dead_end():
    """The healed trekker walks toward the belt rather than giving up: the cheapest path
    to the frontier at y=59 goes through one tree."""
    bot = _bot()
    _seed_belt(bot)
    acts = bot.on_frame(_belt_frame(_char(healed=True)))
    assert acts and acts[0]["action"] == "move" and acts[0]["dir"] == "N", \
        f"a chop-through route existed and the trek declined it: {acts}"


def test_ADJACENT_to_the_belt_the_axe_swings():
    """At (1,19), one south of the tree line, the action must be the attack that clears
    the belt — never a move into a solid tile (a guaranteed move_failed bounce).

    The attack comes from 0.45.0's opportunistic adjacent-harvest, NOT from a trek-side
    chop offer: a trek-side one was written, shadowed in every reachable case (a breakable
    next-step is by definition adjacent, and adjacency fires the harvest first, which sets
    `productive` and skips the trek), and deleted when its mutant survived. This test pins
    the COMPOSITION: route to the belt, harvest swings, the felled tile is a path."""
    bot = _bot()
    _seed_belt(bot)
    acts = bot.on_frame(_belt_frame(_char(healed=True, pos=(1, 19))))
    assert acts and acts[0]["action"] == "attack" and acts[0]["target"] == [1, 20], \
        f"expected to chop the belt tree at [1,20]: {acts}"


def test_a_cheap_DETOUR_still_beats_the_axe():
    """Nav-level, with a geometry where the arithmetic is STRICT: from (1,19), adjacent to
    the belt, the only northward step is the tree (chop 5, total 44 to a frontier) while
    the gap detour totals 42 — so the cheapest path MUST start east. Two earlier drafts of
    this test failed instructively: at equal cost the tie legitimately broke north (both
    routes pass the gap), and through the bot the opportunistic adjacent-harvest (3.3)
    chops any tree it stands beside regardless of routing. The routing claim lives here;
    the bot-level claim below is only "move, don't chop"."""
    import steemer.nav as nav
    known = {(x, y): "floor" for x in range(4) for y in range(60)}
    for x in range(4):
        known[(x, 20)] = "tree"
    known[(3, 20)] = "floor"
    step = nav.weighted_step((1, 19), lambda p: nav.frontier(p, known, (4, 100)),
                             known, breakable=frozenset({"tree", "vein"}))
    assert step == (2, 19), f"cheapest path starts east through the gap, got {step}"


def test_through_the_bot_a_gapped_belt_is_WALKED_not_chopped():
    """One tile back, where no adjacency short-circuits routing: the trek must offer a
    MOVE along a cheapest path (north or east both qualify — the tie is legitimate),
    never an attack, because the gap makes chopping strictly worse."""
    bot = _bot()
    _seed_belt(bot)
    bot.known["vale"][(3, 20)] = "floor"          # the gap
    acts = bot.on_frame(_belt_frame(_char(healed=True, pos=(1, 18))))
    assert acts and acts[0]["action"] == "move" and acts[0]["dir"] in ("N", "E"), \
        f"expected a walk toward the gap, not the axe: {acts}"


def test_a_WALL_belt_is_still_a_dead_end():
    """Masonry is not choppable. Same geometry with `wall` must find nothing and fall
    through to the looted-out retreat — otherwise the trek would hurl attacks at stone."""
    bot = _bot()
    _seed_belt(bot)
    for x in range(4):
        bot.known["vale"][(x, 20)] = "wall"
    acts = bot.on_frame(_belt_frame(_char(healed=True, pos=(1, 19))))
    assert acts and not any(a.get("action") == "attack" for a in acts), \
        f"tried to chop masonry: {acts}"
    assert acts[0].get("dir") == "S", f"should give up and head home: {acts}"


def test_weighted_step_NEVER_routes_through_a_blocked_tile():
    """`blocked` is danger (predator-adjacency), not terrain, and it is absolute: a chop
    route that passes beside a predator is not a route. Geometry: the only physical path
    (the chopped tree) is blocked -> no route at all, even though the terrain allows one."""
    import steemer.nav as nav
    known = {(x, y): "floor" for x in range(3) for y in range(30)}
    for x in range(3):
        known[(x, 10)] = "tree"
    step = nav.weighted_step((1, 5), lambda p: p[1] >= 20, known,
                             blocked={(x, 10) for x in range(3)},
                             breakable=frozenset({"tree"}))
    assert step is None, f"routed through a blocked tile: {step}"


# ---- v0.80.1: stale memory costs more to walk on -------------------------------

def test_a_LONGER_fresh_route_beats_a_shorter_stale_one():
    """The stale corridor is strictly SHORTER, deliberately: an equal-length version of
    this test passed with the bias deleted, because the tie happened to break toward the
    fresh side — an oracle that cannot fail. Here the unbiased router must pick the short
    stale corridor (17*1 < 20*1), and only the bias (17*STALE_COST=51 > ~22) can send it
    the fresh way — so the mutant that deletes the bias fails and the tie cannot save it."""
    import steemer.nav as nav
    known = {(1, y): "floor" for y in range(18)}          # stale corridor, 17 steps home
    known.update({(x, 17): "floor" for x in (2, 3)})      # spur east to the fresh corridor
    known.update({(4, y): "floor" for y in range(18)})    # fresh corridor, ~20 via spur
    fresh = {(2, 17), (3, 17)} | {(4, y) for y in range(18)}
    step = nav.weighted_step((1, 17), lambda p: p[1] == 0, known, fresh=fresh)
    assert step == (2, 17), f"took the short stale corridor despite the bias: {step}"


def test_an_ONLY_STALE_route_is_still_taken():
    """The bias must reorder, never remove: a hurt character whose single route home is
    unverified memory takes it anyway — refusing would be the 0.42/0.50 stuck-death
    rebuilt out of freshness instead of walls."""
    import steemer.nav as nav
    known = {(1, y): "floor" for y in range(30)}
    step = nav.weighted_step((1, 29), lambda p: p[1] == 0, known, fresh=set())
    assert step == (1, 28), f"a stale-only route was refused: {step}"


def test_no_freshness_data_means_no_bias():
    """fresh=None (tests, replays, callers that predate 0.80.1) must behave exactly like
    the unbiased router — asserted so the default can never silently become 'everything
    is stale'."""
    import steemer.nav as nav
    known = {(1, y): "floor" for y in range(10)}
    assert nav.weighted_step((1, 9), lambda p: p[1] == 0, known) == (1, 8)


def test_the_RETREAT_routes_through_fresh_ground_THROUGH_THE_BOT():
    """The plumbing test the mutants demanded: dropping `fresh=ctx.fresh` from the
    retreat left every other test green. A scout walks the eastern corridor early in the
    run (its tiles become seen-this-run); a heal-less character deep at the junction then
    retreats — and must step EAST toward the verified corridor, though the remembered
    western one is a tile shorter."""
    bot = _bot()
    known = {(1, y): "floor" for y in range(26)}          # stale corridor (shorter)
    known.update({(x, 25): "floor" for x in (2, 3)})
    known.update({(4, y): "floor" for y in range(26)})    # fresh corridor
    bot.known["vale"] = known
    scout_tiles = [[4, y, "floor", 0, 0] for y in range(26)]
    bot.on_frame({"type": "frame", "world": "vale", "tick": 499, "events": [],
                  "bounds": [6, 100], "chars": [],
                  "visible": {"tiles": scout_tiles, "entities": [], "items": [], "gold": []}})
    deep = _char(healed=False, pos=(2, 25))
    acts = bot.on_frame({"type": "frame", "world": "vale", "tick": 500, "events": [],
                         "bounds": [6, 100], "chars": [deep],
                         "visible": {"tiles": [[x, 25, "floor", 0, 0] for x in (1, 2, 3)],
                                     "entities": [], "items": [], "gold": []}})
    assert acts and acts[0]["action"] == "move" and acts[0]["dir"] == "E", \
        f"retreated down the unverified corridor: {acts}"
