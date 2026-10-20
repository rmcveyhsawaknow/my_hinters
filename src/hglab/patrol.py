"""The outermost perimeter of the world: the coast of the main landmass, traced as one ordered loop.

The world is one island in deep water. Its outermost walkable ring is the coast, the last land
before the glass. ``perimeter_loop`` finds the largest 8-connected walkable region (terrain plus
bridges) and traces its outer boundary with Moore-neighbour tracing, clockwise on screen (east
along the top, south down the east side). Lakes inside the island are not part of it. The loop is
cached per map, so every wake of a patrolling persona pays for the trace once.
"""

from __future__ import annotations

from functools import lru_cache

WALKABLE = frozenset("sgfh")
# clockwise with y growing south: N, NE, E, SE, S, SW, W, NW
DIRS = ((0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1))


def _chebyshev(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


@lru_cache(maxsize=4)
def perimeter_loop(rows: tuple[str, ...], bridges: frozenset[tuple[int, int]] = frozenset()) -> tuple[tuple[int, int], ...]:
    """The coast of the main landmass as an ordered, closed loop of 8-adjacent tiles (clockwise)."""

    def walkable(x: int, y: int) -> bool:
        return 0 <= y < len(rows) and 0 <= x < len(rows[y]) and (rows[y][x] in WALKABLE or (x, y) in bridges)

    seen: set[tuple[int, int]] = set()
    land: set[tuple[int, int]] = set()
    for y in range(len(rows)):
        for x in range(len(rows[y])):
            if (x, y) in seen or not walkable(x, y):
                continue
            component = {(x, y)}
            seen.add((x, y))
            stack = [(x, y)]
            while stack:
                cx, cy = stack.pop()
                for dx, dy in DIRS:
                    tile = (cx + dx, cy + dy)
                    if tile not in seen and walkable(*tile):
                        seen.add(tile)
                        component.add(tile)
                        stack.append(tile)
            if len(component) > len(land):
                land = component
    if not land:
        return ()
    start = min(land, key=lambda t: (t[1], t[0]))  # topmost, then leftmost: its west neighbour is outside
    loop = [start]
    here, back = start, (start[0] - 1, start[1])
    states: set[tuple[tuple[int, int], tuple[int, int]]] = set()
    while len(loop) <= 8 * len(land):
        k = DIRS.index((back[0] - here[0], back[1] - here[1]))
        found = None
        for i in range(1, 9):
            dx, dy = DIRS[(k + i) % 8]
            candidate = (here[0] + dx, here[1] + dy)
            if candidate in land:
                px, py = DIRS[(k + i - 1) % 8]
                back = (here[0] + px, here[1] + py)
                found = candidate
                break
        if found is None:
            break  # a single tile of land
        if (found, back) in states:
            break  # the trace has come round to a state it has been in: the loop is closed
        states.add((found, back))
        here = found
        loop.append(here)
    if len(loop) > 1 and loop[-1] == loop[0]:
        loop.pop()
    return tuple(loop)


def oriented(loop: tuple[tuple[int, int], ...], direction: str) -> tuple[tuple[int, int], ...]:
    return tuple(reversed(loop)) if direction == "counterclockwise" else loop


def nearest_index(loop: tuple[tuple[int, int], ...], position: tuple[int, int]) -> int:
    """The loop tile nearest the walker: Chebyshev first (moves), then the straighter line (ties along a diagonal band)."""
    return min(range(len(loop)), key=lambda i: (_chebyshev(loop[i], position), abs(loop[i][0] - position[0]) + abs(loop[i][1] - position[1]), i))


def distance_to(loop: tuple[tuple[int, int], ...], position: tuple[int, int]) -> int:
    return min((_chebyshev(t, position) for t in loop), default=999)


def ahead(loop: tuple[tuple[int, int], ...], position: tuple[int, int], hint: int | None, offsets: tuple[int, ...] = (12, 24)) -> list[tuple[int, int]]:
    """Waypoints this many steps ahead of where the walker stands on the loop."""
    if not loop:
        return []
    i = hint if isinstance(hint, int) and 0 <= hint < len(loop) and _chebyshev(loop[hint], position) <= 3 else nearest_index(loop, position)
    return [loop[(i + k) % len(loop)] for k in offsets]


__all__ = ["DIRS", "ahead", "distance_to", "nearest_index", "oriented", "perimeter_loop"]
