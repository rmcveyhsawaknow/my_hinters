"""Count walkable components in a terrain rows file (8-neighbour connectivity).

Usage: python analysis/landmass.py tests/fixtures/world/terrain.txt
Prints one integer: the number of connected walkable components.
"""

import sys
from collections import deque
from pathlib import Path

WALKABLE = set("sgfh")


def components(rows: list[str]) -> int:
    height, width = len(rows), len(rows[0])
    seen: set[tuple[int, int]] = set()
    count = 0
    for y in range(height):
        for x in range(width):
            if rows[y][x] not in WALKABLE or (x, y) in seen:
                continue
            count += 1
            queue = deque([(x, y)])
            seen.add((x, y))
            while queue:
                cx, cy = queue.popleft()
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        nx, ny = cx + dx, cy + dy
                        if 0 <= nx < width and 0 <= ny < height and (nx, ny) not in seen and rows[ny][nx] in WALKABLE:
                            seen.add((nx, ny))
                            queue.append((nx, ny))
    return count


if __name__ == "__main__":
    text = Path(sys.argv[1]).read_text(encoding="ascii")
    print(components([line.strip() for line in text.splitlines() if line.strip()]))
