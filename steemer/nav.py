"""Map navigation primitives: neighbours, walkability, and BFS over remembered
tiles. Pure functions with no game or network dependency, so they are cheap to
unit-test and mutation-check — and they are shared by every strategy.

Coordinates are ``(x, y)`` tuples. ``y`` increases north; ``move S`` from row 0
exits a map to the village.
"""

from __future__ import annotations

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
) -> tuple[int, int] | None:
    """Breadth-first over remembered walkable tiles; return the *next* tile to
    step toward the nearest goal, or ``None`` if no goal is reachable.

    ``start`` itself is never returned. Neighbours of ``start`` are candidates
    even if unknown-as-goal, but only walkable tiles are expanded — so a goal on
    an unseen tile is reachable only if it is directly adjacent to a walked path.
    """
    blocked_set = set(blocked)
    came_from: dict[tuple[int, int], tuple[int, int] | None] = {start: None}
    queue: deque[tuple[int, int]] = deque([start])
    goal: tuple[int, int] | None = None
    while queue:
        current = queue.popleft()
        if current != start and is_goal(current):
            goal = current
            break
        for nxt in neighbors(current):
            if nxt in came_from:
                continue
            # allow stepping *onto* a goal tile even if unknown/solid-unseen,
            # but never expand through a non-walkable tile
            if is_goal(nxt) and nxt not in blocked_set:
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


def frontier(pos: tuple[int, int], known: dict[tuple[int, int], str]) -> bool:
    """A seen tile that still borders somewhere unseen — an exploration target."""
    return any(n not in known for n in neighbors(pos))
