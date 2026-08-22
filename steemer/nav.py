"""Map navigation primitives: neighbours, walkability, and BFS over remembered
tiles. Pure functions with no game or network dependency, so they are cheap to
unit-test and mutation-check — and they are shared by every strategy.

Coordinates are ``(x, y)`` tuples. ``y`` increases north; ``move S`` from row 0
exits a map to the village.
"""

from __future__ import annotations

import heapq
from collections import deque
from typing import Callable, Iterable

# Cardinal steps only (diagonals are gear-gated and rejected by default).
DIRS: dict[str, tuple[int, int]] = {"N": (0, 1), "S": (0, -1), "E": (1, 0), "W": (-1, 0)}

# Tile kinds that block movement. A bot may only *know* a tile is solid once it
# has seen it; unknown tiles are treated as walls by the planner (fail closed).
SOLID: frozenset[str] = frozenset({
    "wall", "chest", "chest_open", "safe", "trap", "water", "tree", "bush",
    "fence", "rock", "vein", "cauldron", "forge",
})


def neighbors(pos: tuple[int, int]) -> list[tuple[int, int]]:
    x, y = pos
    return [(x, y + 1), (x, y - 1), (x + 1, y), (x - 1, y)]


def step_dir(frm: tuple[int, int], to: tuple[int, int]) -> str | None:
    """The cardinal direction name from one tile to an adjacent tile, or None."""
    delta = (to[0] - frm[0], to[1] - frm[1])
    for name, vec in DIRS.items():
        if vec == delta:
            return name
    return None


def is_walkable(
    pos: tuple[int, int],
    known: dict[tuple[int, int], str],
    blocked: Iterable[tuple[int, int]] = (),
) -> bool:
    """A tile is walkable if we've seen it, it isn't solid, and nothing occupies
    it. Unknown tiles are *not* walkable — the planner refuses to route through
    terrain it has never seen rather than guess."""
    if pos in set(blocked):
        return False
    kind = known.get(pos)
    return kind is not None and kind not in SOLID


def bfs_step(
    start: tuple[int, int],
    is_goal: Callable[[tuple[int, int]], bool],
    known: dict[tuple[int, int], str],
    blocked: Iterable[tuple[int, int]] = (),
    max_depth: int | None = None,
) -> tuple[int, int] | None:
    """Breadth-first over remembered walkable tiles; return the *next* tile to
    step toward the nearest goal, or ``None`` if no goal is reachable.

    ``start`` itself is never returned. Neighbours of ``start`` are candidates
    even if unknown-as-goal, but only walkable tiles are expanded — so a goal on
    an unseen tile is reachable only if it is directly adjacent to a walked path.

    ``max_depth`` bounds the search to that many steps from ``start``. Without it a
    goal that is merely UNREACHABLE — behind a wall, or on the far side of the map —
    costs a full sweep of the world's known component, and pays it again every frame
    for every character that wants one. The accumulated map is ~7,000 tiles per world,
    the frame budget is ~83ms, and a slow consumer does not block: a ZeroMQ DEALER
    DROPS. That is exactly how run #120 lost 3.7% of its stream, so a caller that
    searches speculatively should bound the cost rather than hope the goal is close.
    """
    blocked_set = set(blocked)
    came_from: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    depth: dict[tuple[int, int], int] = {start: 0}
    queue: deque[tuple[int, int]] = deque([start])
    goal: tuple[int, int] | None = None
    while queue:
        current = queue.popleft()
        if current != start and is_goal(current):
            goal = current
            break
        if max_depth is not None and depth[current] >= max_depth:
            continue                      # expand no further, but keep draining the queue
        for nxt in neighbors(current):
            if nxt in came_from:
                continue
            depth[nxt] = depth[current] + 1
            # allow stepping *onto* a goal tile even if it is unknown (e.g. loot
            # or an enemy on an as-yet-unseen tile), but NEVER onto a known-solid
            # tile — a "frontier" wall borders the unseen yet cannot be stood on,
            # and routing onto it is a guaranteed bounce (move_failed).
            if is_goal(nxt) and nxt not in blocked_set and known.get(nxt) not in SOLID:
                came_from[nxt] = current
                queue.append(nxt)
                continue
            if is_walkable(nxt, known, blocked_set):
                came_from[nxt] = current
                queue.append(nxt)
    if goal is None:
        return None
    # walk the chain back to the first step out of start
    node = goal
    while came_from[node] is not None and came_from[node] != start:
        node = came_from[node]  # type: ignore[assignment]
    return node


def in_bounds(pos: tuple[int, int], bounds: tuple[int, int] | None) -> bool:
    """Is this coordinate inside the world at all? ``bounds`` is the frame's
    ``[width, height]``; without it every coordinate is admitted, which is the old
    behaviour."""
    if bounds is None:
        return True
    w, h = bounds
    return 0 <= pos[0] < w and 0 <= pos[1] < h


def frontier(pos: tuple[int, int], known: dict[tuple[int, int], str],
             bounds: tuple[int, int] | None = None) -> bool:
    """A *standable* seen tile that still borders the UNSEEN — a place we can actually
    move to in order to reveal new ground. A solid tile that happens to border the unseen
    is not a frontier: we cannot stand on it.

    ``bounds`` excludes the edge of the world, and without it this function lies in a way
    that shaped the whole bot. A neighbour merely absent from ``known`` counted as
    unexplored — and beyond the map edge nothing is ever in `known`, so every tile on the
    rim looked like a permanent frontier. Measured on the mines: 58 of 126 "frontier" tiles
    sat at y=0, the home row, and `bfs_step` returns the NEAREST goal. Characters living at
    depth 2 therefore chose the false rim frontier every time and never reached the real one
    at depth 110-126 — or the veins at median depth 88. A self-reinforcing trap: shallow
    characters were kept shallow by the very behaviour meant to push them outward.
    """
    if known.get(pos) in SOLID:
        return False
    return any(n not in known and in_bounds(n, bounds) for n in neighbors(pos))

# v0.80.0 — BREAKABLE terrain. Trees and veins are SOLID to `bfs_step`, and that is the
# "checkers" defect from the operator's screenshot: a character stood at a pine belt it
# has been able to CHOP since 0.45.0 (~4 attacks, `terrain_destroyed`, and the tile
# becomes floor) and read it as a dead end. Here a breakable tile is not a wall but an
# EXPENSIVE step: BREAK_COST approximates the four attack ticks plus the move, so a short
# detour still beats chopping, and a long one loses to it — which is the trade a person
# makes without noticing.
BREAK_COST = 5


def weighted_step(
    start: tuple[int, int],
    is_goal: Callable[[tuple[int, int]], bool],
    known: dict[tuple[int, int], str],
    blocked: Iterable[tuple[int, int]] = (),
    breakable: frozenset[str] = frozenset(),
    max_cost: int | None = None,
) -> tuple[int, int] | None:
    """Dijkstra over remembered tiles; return the next tile toward the CHEAPEST goal.

    Like ``bfs_step`` but a tile whose kind is in ``breakable`` costs ``BREAK_COST`` to
    enter instead of being impassable. The caller inspects the returned tile's kind: a
    breakable next tile means "attack it", anything else means "move". ``blocked`` stays
    absolute (predator-adjacency is danger, not terrain), unknown tiles stay walls (fail
    closed), and other SOLID kinds stay walls (nothing chops masonry). ``max_cost`` bounds
    the search frontier by path cost, the weighted analogue of ``max_depth``.
    """
    blocked_set = set(blocked)
    came_from: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    dist: dict[tuple[int, int], int] = {start: 0}
    heap: list[tuple[int, int, tuple[int, int]]] = [(0, 0, start)]
    tie = 0
    goal: tuple[int, int] | None = None
    while heap:
        d, _, current = heapq.heappop(heap)
        if d > dist.get(current, 10 ** 9):
            continue                       # stale heap entry
        if current != start and is_goal(current):
            goal = current
            break
        if max_cost is not None and d >= max_cost:
            continue
        for nxt in neighbors(current):
            if nxt in blocked_set:
                continue
            kind = known.get(nxt)
            if kind in breakable:
                step_cost = BREAK_COST
            elif is_walkable(nxt, known, blocked_set) or (is_goal(nxt) and kind not in SOLID):
                step_cost = 1
            else:
                continue
            nd = d + step_cost
            if nd < dist.get(nxt, 10 ** 9):
                dist[nxt] = nd
                came_from[nxt] = current
                tie += 1
                heapq.heappush(heap, (nd, tie, nxt))
    if goal is None:
        return None
    node = goal
    while came_from[node] is not None and came_from[node] != start:
        node = came_from[node]  # type: ignore[assignment]
    return node
