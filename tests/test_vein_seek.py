"""v0.54.0 — SEEK ore: forge-to-arm slice 2.

Run #130 measured the M3a bottleneck exactly: 120 trees destroyed against 5 veins, lumber
piling up while ore trickled. The cause is NOT scarcity — the accumulated map knows 83 vein
tiles in the mines and half our character-frames are already in the mines. It is DENSITY.
Slice 1 harvests only what a character is already ADJACENT to, and vale's 357 trees are
thick enough to brush past constantly while 83 veins among ~4,900 mine floor tiles are not.

The risk being designed against is the v0.46.0 regression, which had this exact shape: a
change made "for the forge" that quietly cost us the income paying for weapons. So the
narrowness is the feature, and most of these tests pin a case where it must NOT fire.

What these tests do NOT prove: that walking to a vein is worth the ticks it costs. That is
a live measurement on the next run (ore drops per 1k frames, against move_failed and gold).
"""
import steemer.nav as nav
from steemer.strategy.base import FieldContext
from steemer.strategy.explorer import (Explorer, ORE_KINDS, VEIN_SEEK_RANGE,
                                       VEIN_SEEK_SCORE, FORGE_RESERVE_PER_CHAR)


def _corridor(length=30, vein_at=None, kind="vein"):
    """A 1-wide walkable corridor along y=0, optionally with a resource tile at the end."""
    known = {(x, 0): "floor" for x in range(length)}
    if vein_at is not None:
        known[(vein_at, 0)] = kind
    return known


def _ctx(known, world="mines"):
    return FieldContext(world=world, known=known)


def _char(metal=0, used=3, cap=21, kind="ore_copper"):
    return {"char_uid": "u1", "carry": {"used": used, "cap": cap},
            "inventory": [{"kind": kind, "item_id": f"m{i}"} for i in range(metal)]}


# ---- it walks toward ore -----------------------------------------------------

def test_it_steps_toward_a_known_vein():
    known = _corridor(vein_at=6)
    step = Explorer._ore_step((0, 0), _ctx(known), set())
    assert step == (1, 0), "first step of the path toward the vein"


def test_it_targets_the_tile_BESIDE_the_vein_not_the_vein_itself():
    """A vein is SOLID — scenery you break, not ground you stand on. Asking to path ONTO
    it finds nothing at all (bfs_step refuses to enter a solid tile), so the character
    would simply never seek. The goal must be a walkable neighbour, and slice 1 does the
    breaking from there.

    Two oracles: we DO get a step toward a distant vein (below), and once adjacent there
    is nothing further to walk toward (here)."""
    known = _corridor(vein_at=3)
    assert Explorer._ore_step((2, 0), _ctx(known), set()) is None, \
        "already beside it — nowhere better to go"
    assert Explorer._ore_step((0, 0), _ctx(known), set()) == (1, 0), \
        "but from a distance it must still find a route"


def test_it_does_not_seek_a_tree():
    """Ore only. Slice 1 already brings back more lumber than the forge can use, and
    seeking trees would spend ticks re-solving a problem we do not have."""
    known = _corridor(vein_at=6, kind="tree")
    assert Explorer._ore_step((0, 0), _ctx(known), set()) is None
    assert "tree" not in ORE_KINDS


def test_it_ignores_a_vein_an_expedition_away():
    """The distances here are DELIBERATELY hardcoded rather than derived from
    VEIN_SEEK_RANGE. A fixture computed from the constant under test moves with it, so it
    agrees with itself no matter what the constant becomes — mutation testing caught
    exactly that: widening the range to 90 left the original test green. 25 tiles is the
    policy claim ("that is an expedition, not a detour"), independent of the number."""
    assert Explorer._ore_step((0, 0), _ctx(_corridor(length=60, vein_at=25)), set()) is None


def test_it_still_walks_to_a_vein_a_detour_away():
    """The other side of the same boundary — without this, "ignores distant veins" would
    pass just as well if the character never sought anything at all."""
    assert Explorer._ore_step(
        (0, 0), _ctx(_corridor(length=60, vein_at=10)), set()) == (1, 0)


def test_the_range_stays_in_the_band_those_two_cases_assume():
    """The pair above pins BEHAVIOUR at 10 and 25. This pins the constant they straddle,
    so a change to VEIN_SEEK_RANGE that invalidates their premise fails here and says so,
    rather than quietly making one of them vacuous."""
    assert 10 < VEIN_SEEK_RANGE < 25


def test_it_routes_around_a_blocked_tile():
    known = {(x, y): "floor" for x in range(6) for y in range(3)}
    known[(4, 1)] = "vein"
    step = Explorer._ore_step((0, 1), _ctx(known), {(1, 1)})
    assert step is not None and step != (1, 1)


# ---- when it must NOT fire ---------------------------------------------------

def test_a_char_at_the_forge_reserve_does_not_seek_more():
    assert Explorer._wants_ore(_char(metal=FORGE_RESERVE_PER_CHAR)) is False
    assert Explorer._wants_ore(_char(metal=FORGE_RESERVE_PER_CHAR - 1)) is True


def test_ingots_count_toward_the_reserve_as_well_as_ore():
    """Both are metal for forging; counting only raw ore would send a character already
    carrying four ingots on a pointless walk."""
    assert Explorer._wants_ore(
        _char(metal=FORGE_RESERVE_PER_CHAR, kind="ingot_iron")) is False


def test_a_full_char_does_not_seek():
    assert Explorer._wants_ore(_char(used=20, cap=21)) is False
    assert Explorer._wants_ore(_char(used=19, cap=21)) is True


def test_a_char_with_no_carry_field_is_allowed_to_seek():
    """Absent carry data must not silently disable the behaviour — the frame shape has
    changed under us before, and a missing field reading as "full" would make this inert
    with nothing in the logs to say so."""
    c = _char()
    del c["carry"]
    assert Explorer._wants_ore(c) is True


def test_no_known_vein_means_no_step():
    assert Explorer._ore_step((0, 0), _ctx(_corridor()), set()) is None


# ---- the cost bound ----------------------------------------------------------

def test_the_search_is_bounded_and_does_not_sweep_the_map():
    """An UNREACHABLE goal previously cost a full sweep of the world's known component,
    every frame, for every character that wanted one — and a slow consumer does not block,
    it DROPS (run #120 lost 3.7% of its stream that way). Counting the tiles the goal test
    is asked about is the oracle: bounded search asks about far fewer than the map holds."""
    known = {(x, y): "floor" for x in range(120) for y in range(120)}   # 14,400 tiles
    asked = []

    def is_goal(t):
        asked.append(t)
        return False

    nav.bfs_step((60, 60), is_goal, known, (), max_depth=VEIN_SEEK_RANGE)
    bounded = len(asked)
    asked.clear()
    nav.bfs_step((60, 60), is_goal, known, ())
    assert bounded < len(asked) / 4, f"bounded {bounded} vs unbounded {len(asked)}"
    assert bounded < 1000


def test_the_SEEK_itself_is_bounded_not_just_the_primitive():
    """bfs_step gained the bound, but it is _ore_step that must PASS it — and an unbounded
    seek is invisible in behaviour (same answer, vastly more work), so the oracle has to be
    the work done. Counting map lookups is that oracle."""
    class Counting(dict):
        def __init__(self, *a):
            super().__init__(*a)
            self.gets = 0

        def get(self, k, d=None):
            self.gets += 1
            return super().get(k, d)

    known = Counting({(x, y): "floor" for x in range(120) for y in range(120)})
    ctx = _ctx(known)                       # no vein anywhere: the worst case
    Explorer._ore_step((60, 60), ctx, set())
    bounded = known.gets
    assert bounded < 6000, f"an unbounded sweep of 14,400 tiles; did {bounded} lookups"


def test_the_bound_does_not_break_a_goal_inside_it():
    known = {(x, y): "floor" for x in range(30) for y in range(30)}
    known[(5, 0)] = "coin"
    step = nav.bfs_step((0, 0), lambda t: known.get(t) == "coin", known, (), max_depth=10)
    assert step == (1, 0)


def test_an_unbounded_search_is_still_the_default():
    """Existing callers must be unaffected — every other seek in the strategy relies on
    reaching goals well beyond VEIN_SEEK_RANGE."""
    known = {(x, 0): "floor" for x in range(60)}
    known[(50, 0)] = "coin"
    assert nav.bfs_step((0, 0), lambda t: known.get(t) == "coin", known, ()) == (1, 0)


# ---- the score ---------------------------------------------------------------

def test_it_is_scored_below_forming_up_and_above_wandering():
    """A character in a world dangerous enough to form up must not wander off alone to
    mine; a character with nothing better to do should walk to ore rather than at random."""
    from steemer.strategy.explorer import COHESION_SCORE
    assert VEIN_SEEK_SCORE < COHESION_SCORE
    assert VEIN_SEEK_SCORE > 2.5          # the frontier/push-north offer


# ---- v0.57.0: the field goal bound, and what it must NOT bound ---------------

def test_an_errand_beyond_the_goal_range_is_not_taken():
    """Hydrating the map (v0.55.0) made every chest ever seen reachable from anywhere,
    and chest-beelining went from 0.047 to 0.70 decisions per frame while move failures
    went 5.2% -> 19.4%. Opportunistic goals are now bounded."""
    from steemer.strategy.explorer import FIELD_GOAL_RANGE
    known = {(x, 0): "floor" for x in range(80)}
    known[(60, 0)] = "chest"
    # The real beeline's goal is a tile ADJACENT to a chest — a chest is solid, so a
    # search that targets the chest tile itself finds nothing regardless of any bound
    # and the test would pass for the wrong reason.
    beside_chest = lambda p: any(known.get(n) == "chest" for n in nav.neighbors(p))
    assert Explorer._step((0, 0), beside_chest, _ctx(known), set()) is None
    assert FIELD_GOAL_RANGE < 59


def test_an_errand_within_the_goal_range_is_still_taken():
    known = {(x, 0): "floor" for x in range(80)}
    known[(10, 0)] = "chest"
    beside_chest = lambda p: any(known.get(n) == "chest" for n in nav.neighbors(p))
    assert Explorer._step((0, 0), beside_chest, _ctx(known), set()) == (1, 0)


def test_walking_HOME_is_never_bounded():
    """The bound must not reach the retreat. A character at y=100 walking home to heal is
    not on an errand, and capping it would leave it unable to find a route and offering
    `rest` instead — precisely the stuck-death of v0.42.0/v0.50.0.

    Asserted through _retreat itself rather than _step, because the defect would live in
    how the caller invokes the helper, not in the helper."""
    known = {(0, y): "floor" for y in range(101)}
    offers = []

    def offer(action, score, why, urgent=False):
        offers.append((action, score, why))

    Explorer()._retreat("u1", (0, 100), _ctx(known), set(), offer, 8.5, "hurt — walking home")
    assert offers, "a hurt character 100 tiles from home must still find a route"
    assert offers[0][0]["dir"] == "S"
