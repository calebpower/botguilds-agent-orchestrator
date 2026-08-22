"""v0.70.0 — the map edge is not a frontier, and believing it was kept us shallow.

`nav.frontier` treated any neighbour absent from `known` as unexplored. Beyond the edge of
the world nothing is ever in `known`, so every tile on the rim looked like a permanent
frontier — and `bfs_step` returns the NEAREST goal.

Measured on the mines map: **58 of 126 "frontier" tiles sat at y=0**, the home row. The real
frontier is at depth 110-126 and the veins are at median depth 88. Our characters lived at
median depth 2 and never left, because the closest thing calling itself unexplored was the
wall they were standing next to. A self-reinforcing trap: the behaviour meant to push
characters outward was the one pinning them in place.

This was flagged in iter 69 and deferred. It turned out to be the binding constraint on
depth, which gates ore, the deeper content that carries the XP, and every vein we have
failed to reach.

What these tests do NOT prove: that characters will now go deep. Removing a false attractor
is not the same as adding a true one — if the deep frontier is unreachable they will simply
find no frontier at all, which is at least honest.
"""
import steemer.nav as nav


def _room(w, h):
    """A fully-seen rectangular world: every tile known, nothing genuinely unexplored."""
    return {(x, y): "floor" for x in range(w) for y in range(h)}


# ---- the edge is not unexplored ----------------------------------------------

def test_a_rim_tile_is_not_a_frontier_once_bounds_are_known():
    """The 58 false frontiers at y=0."""
    known = _room(5, 5)
    assert nav.frontier((2, 0), known, (5, 5)) is False
    assert nav.frontier((0, 2), known, (5, 5)) is False
    assert nav.frontier((4, 2), known, (5, 5)) is False


def test_without_bounds_the_old_edge_blind_behaviour_is_kept():
    """Callers that have no bounds (offline replays, tests, an older frame shape) must not
    change behaviour — the parameter is optional on purpose."""
    known = _room(5, 5)
    assert nav.frontier((2, 0), known, None) is True


def test_a_genuinely_unexplored_neighbour_IS_still_a_frontier():
    """The other side of the boundary. Without this the fix could pass by declaring
    nothing a frontier at all, which would silently end exploration."""
    known = _room(5, 5)
    del known[(2, 3)]
    assert nav.frontier((2, 2), known, (5, 5)) is True


def test_an_interior_tile_surrounded_by_known_ground_is_not_a_frontier():
    assert nav.frontier((2, 2), _room(5, 5), (5, 5)) is False


def test_a_solid_tile_is_never_a_frontier_however_the_bounds_fall():
    """Unchanged rule: we cannot stand on it, so it is not a place to walk to."""
    known = _room(5, 5)
    known[(2, 2)] = "wall"
    del known[(2, 3)]
    assert nav.frontier((2, 2), known, (5, 5)) is False


# ---- in_bounds itself --------------------------------------------------------

def test_in_bounds_uses_width_and_height_not_max_coordinates():
    """The frame's `bounds` is [width, height] — mines is [64, 176] with tiles at x 0-63,
    vale [72, 200] with y 0-199. An off-by-one here would either re-admit the rim or
    exclude a real column."""
    assert nav.in_bounds((63, 175), (64, 176)) is True
    assert nav.in_bounds((64, 0), (64, 176)) is False
    assert nav.in_bounds((0, 176), (64, 176)) is False
    assert nav.in_bounds((-1, 5), (64, 176)) is False
    assert nav.in_bounds((0, 0), (64, 176)) is True


def test_in_bounds_admits_everything_when_bounds_are_unknown():
    assert nav.in_bounds((-99, 9999), None) is True


# ---- the shape of the real map ----------------------------------------------

def test_the_rim_of_a_fully_mapped_world_yields_no_frontier_at_all():
    """The mines case in miniature: a world we have seen entirely has nowhere left to
    explore, and should say so rather than offering its own edge forever."""
    known = _room(6, 6)
    assert not [p for p in known if nav.frontier(p, known, (6, 6))]
    assert len([p for p in known if nav.frontier(p, known, None)]) == 20, \
        "edge-blind, every rim tile of a 6x6 claims to be a frontier"


# ---- the plumbing, which is where these things actually break -----------------

def test_the_frames_bounds_reach_the_strategy():
    """v0.66.1's lesson: a chain breaks in the MIDDLE, where both ends test clean. The
    function above is correct and useless if `bounds` never arrives, so this asserts it at
    the boundary the strategy reads."""
    from steemer.bot import GuildBot

    seen = {}

    class Spy:
        version = "spy/0"

        def act(self, _b, _c, _f, ctx, _t):
            seen["bounds"] = ctx.bounds

        def village(self, _b, _f):
            return []

    bot = GuildBot("explorer")
    bot.strategy = Spy()
    bot.on_frame({"type": "frame", "world": "mines", "tick": 1, "events": [],
                  "bounds": [64, 176],
                  "chars": [{"char_uid": "u1", "eid": 1, "pos": [0, 0], "hp": 9,
                             "max_hp": 9, "stamina": 9, "inventory": [], "equipment": {}}],
                  "visible": {"tiles": [], "entities": [], "items": [], "gold": []}})
    assert seen["bounds"] == (64, 176)


def test_a_frame_without_bounds_leaves_the_strategy_edge_blind_not_broken():
    """Village frames and older shapes carry no `bounds`; that must degrade to the old
    behaviour rather than raise."""
    from steemer.bot import GuildBot

    seen = {}

    class Spy:
        version = "spy/0"

        def act(self, _b, _c, _f, ctx, _t):
            seen["bounds"] = ctx.bounds

        def village(self, _b, _f):
            return []

    bot = GuildBot("explorer")
    bot.strategy = Spy()
    bot.on_frame({"type": "frame", "world": "mines", "tick": 1, "events": [],
                  "chars": [{"char_uid": "u1", "eid": 1, "pos": [0, 0], "hp": 9,
                             "max_hp": 9, "stamina": 9, "inventory": [], "equipment": {}}],
                  "visible": {"tiles": [], "entities": [], "items": [], "gold": []}})
    assert seen["bounds"] is None
