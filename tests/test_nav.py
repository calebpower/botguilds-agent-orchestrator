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


def test_frontier_is_a_seen_tile_bordering_the_unseen():
    known = {(0, 0): "floor", (0, 1): "floor"}
    assert nav.frontier((0, 1), known) is True       # borders unseen tiles
    surrounded = {(0, 0): "floor", (0, 1): "floor", (0, -1): "floor",
                  (1, 0): "floor", (-1, 0): "floor"}
    assert nav.frontier((0, 0), surrounded) is False  # all neighbours seen
