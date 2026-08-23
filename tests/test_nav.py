"""Navigation primitives — the shared pathing every strategy leans on."""

from steemer import nav


def test_neighbors_are_the_four_cardinals():
    assert set(nav.neighbors((2, 3))) == {(2, 4), (2, 2), (3, 3), (1, 3)}


def test_step_dir_only_for_adjacent():
    assert nav.step_dir((0, 0), (0, 1)) == "N"
    assert nav.step_dir((0, 0), (0, -1)) == "S"
    assert nav.step_dir((0, 0), (1, 0)) == "E"
    assert nav.step_dir((0, 0), (-1, 0)) == "W"
    assert nav.step_dir((0, 0), (2, 0)) is None      # not adjacent
    assert nav.step_dir((0, 0), (1, 1)) is None      # diagonal is not a cardinal


def test_is_walkable_fails_closed_on_the_unknown():
    known = {(0, 0): "floor", (1, 0): "wall"}
    assert nav.is_walkable((0, 0), known) is True
    assert nav.is_walkable((1, 0), known) is False       # solid
    assert nav.is_walkable((9, 9), known) is False       # never seen → not walkable
    assert nav.is_walkable((0, 0), known, blocked={(0, 0)}) is False  # occupied


def test_bfs_step_returns_first_step_toward_nearest_goal():
    # a straight corridor north
    known = {(0, 0): "floor", (0, 1): "floor", (0, 2): "floor"}
    step = nav.bfs_step((0, 0), lambda p: p[1] == 2, known)
    assert step == (0, 1)


def test_bfs_step_none_when_goal_unreachable():
    known = {(0, 0): "floor", (0, 1): "wall"}     # walled in to the north
    assert nav.bfs_step((0, 0), lambda p: p[1] == 5, known) is None


def test_bfs_step_may_end_on_an_unseen_goal_tile_if_adjacent():
    # (0,1) is a goal but has never been seen; still reachable as a final step.
    known = {(0, 0): "floor"}
    assert nav.bfs_step((0, 0), lambda p: p == (0, 1), known) == (0, 1)


def test_bfs_step_routes_around_a_blocked_tile():
    # grid 3x2 all floor; block the direct northward tile so it must detour.
    known = {(x, y): "floor" for x in range(3) for y in range(3)}
    # goal is (0,2); block (0,1) → must go via (1,x)
    step = nav.bfs_step((0, 0), lambda p: p == (0, 2), known, blocked={(0, 1)})
    assert step in {(1, 0)}          # only sane first move given the block
    # and with nothing blocked it goes straight up
    assert nav.bfs_step((0, 0), lambda p: p == (0, 2), known) == (0, 1)


def test_bfs_step_never_routes_onto_a_solid_goal_tile():
    # a wall that borders the unseen is a "frontier" by adjacency but cannot be
    # stood on; bfs must not return a step onto it (that is a guaranteed bounce).
    known = {(0, 0): "floor", (0, 1): "wall"}
    assert nav.bfs_step((0, 0), lambda p: p == (0, 1), known) is None
    # but an *unknown* goal tile adjacent to us is still reachable
    known2 = {(0, 0): "floor"}
    assert nav.bfs_step((0, 0), lambda p: p == (0, 1), known2) == (0, 1)


def test_frontier_excludes_solid_tiles():
    known = {(0, 0): "floor", (0, 1): "wall"}   # wall borders unseen but isn't standable
    assert nav.frontier((0, 1), known) is False
    assert nav.frontier((0, 0), known) is True   # floor bordering unseen


def test_frontier_is_a_seen_tile_bordering_the_unseen():
    known = {(0, 0): "floor", (0, 1): "floor"}
    assert nav.frontier((0, 1), known) is True       # borders unseen tiles
    surrounded = {(0, 0): "floor", (0, 1): "floor", (0, -1): "floor",
                  (1, 0): "floor", (-1, 0): "floor"}
    assert nav.frontier((0, 0), surrounded) is False  # all neighbours seen


def test_pathing_detours_around_a_portal_tile():
    """v0.91.0, from run #179's vanish spiral: a portal on the shortest path is an
    involuntary teleport, not a shortcut. The router must pay the two-tile detour
    rather than step on it — bfs_step AND weighted_step alike (weighted_step is the
    trek/escape router, and breakables never include portals, so it must not cross
    either). Straight-line world: (0,0) -> goal (0,4), portal at (0,2), detour via x=1."""
    known = {(x, y): "floor" for x in range(2) for y in range(5)}
    known[(0, 2)] = "portal"
    goal = lambda p: p == (0, 4)
    step = nav.bfs_step((0, 1), goal, known)
    assert step == (1, 1), f"bfs stepped toward the portal: {step}"
    wstep = nav.weighted_step((0, 1), goal, known, set())
    assert wstep == (1, 1), f"weighted_step stepped toward the portal: {wstep}"


def test_a_portal_is_not_a_desperation_exit():
    """The last-resort escape filter (explorer) is `known.get(n) not in nav.SOLID`;
    the portal must be excluded by that predicate exactly as walls are — asserted
    through the predicate the escape actually uses, with the real SOLID set."""
    known = {(5, 5): "portal", (5, 3): "wall", (4, 4): "floor"}
    clear = [n for n in nav.neighbors((5, 4)) if known.get(n) not in nav.SOLID]
    assert (5, 5) not in clear and (5, 3) not in clear
    assert (4, 4) in clear and (6, 4) in clear      # floor and UNSEEN both stay legal
