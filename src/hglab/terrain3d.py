"""The ground as the public 3D viewer draws it: a height for every tile, and where a tile's blocks stand.

The world itself has no elevation: a block's level 0 is simply the ground of its tile. The viewer on
hinterglass.com (its ``World3DScene`` bundle, read on 2026-10-25) derives a height field from the terrain
codes with seeded value noise, smooths it, builds a vertex grid of tile corners, and draws every block of
a tile from that tile's *base*: the highest of the ground under its four corners and its centre. A block
at level ``bz`` is drawn at ``base + (bz + 0.5) * 0.25``. So two tiles of one building whose bases differ
draw their floors at different heights, which is what the owner saw on the hillside factory.

This module ports that derivation exactly (the same hash, noise, smoothing, clamps and float32 storage),
so a blueprint can survey a site's bases and raise each tile on a foundation of whole levels until every
floor of the building sits on one plane. ``tests/test_terrain3d.py`` pins values computed by the viewer's
own code under Node. If the viewer changes its ground, re-read it and update this port.
"""

from __future__ import annotations

import math
import struct
from collections import deque
from functools import lru_cache
from typing import Any

BASE = {"W": -1.1, "w": -0.35, "s": 0.12, "g": 0.3, "f": 0.45, "h": 1.9, "m": 4.5}  # the viewer's per-terrain base heights
CODES = {"W": 0, "w": 1, "s": 2, "g": 3, "f": 4, "h": 5, "m": 6}
LETTERS = "Wwsgfhm"
PEAK = 6.2  # the viewer's mountain-top constant
CELL = 0.25  # a block level, in tile units (four levels a tile)
MIN_BASE = 0.04  # the viewer never draws a tile's blocks below this


def _f32(value: float) -> float:
    return struct.unpack("f", struct.pack("f", value))[0]


def _i32(value: int) -> int:
    value &= 0xFFFFFFFF
    return value - 0x100000000 if value & 0x80000000 else value


def _imul(a: int, b: int) -> int:
    return _i32(_i32(a) * _i32(b))


def hash01(x: int, y: int, seed: int) -> float:
    """The viewer's integer hash to [0, 1)."""
    r = _imul(x, 374761393) + _imul(y, 668265263) + _imul(seed, 2246822519)
    u = r & 0xFFFFFFFF
    r = _imul(_i32(u ^ (u >> 13)), 1274126177)
    u = r & 0xFFFFFFFF
    return ((u ^ (u >> 16)) & 0xFFFFFFFF) / 4294967296


def _ease(t: float) -> float:
    return t * t * (3 - 2 * t)


def noise(x: float, y: float, seed: int) -> float:
    """The viewer's value noise."""
    ix, iy = math.floor(x), math.floor(y)
    a, o = _ease(x - ix), _ease(y - iy)
    s, c, lo, u = hash01(ix, iy, seed), hash01(ix + 1, iy, seed), hash01(ix, iy + 1, seed), hash01(ix + 1, iy + 1, seed)
    return s + (c - s) * a + (lo - s) * o + (s - c - lo + u) * a * o


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else min(v, hi)


def _smoothstep(e0: float, e1: float, v: float) -> float:
    r = _clamp((v - e0) / (e1 - e0), 0, 1)
    return r * r * (3 - 2 * r)


def _distances(width: int, height: int, seed: list[bool]) -> list[int]:
    """Eight-way steps to the nearest seed tile, capped at 16 (the viewer's ``Hp``)."""
    dist = [255] * (width * height)
    queue: deque[int] = deque()
    for i, s in enumerate(seed):
        if s:
            dist[i] = 0
            queue.append(i)
    while queue:
        n = queue.popleft()
        r = dist[n]
        if r >= 16:
            continue
        cx, cy = n % width, n // width
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                ux, uy = cx + dx, cy + dy
                if ux < 0 or uy < 0 or ux >= width or uy >= height:
                    continue
                f = uy * width + ux
                if dist[f] > r + 1:
                    dist[f] = r + 1
                    queue.append(f)
    return [16 if d == 255 else d for d in dist]


class Ground:
    """The viewer's height field for one world map."""

    def __init__(self, width: int, height: int, terrain: str) -> None:
        self.width, self.height = width, height
        self.codes = [CODES.get(ch, 0) for ch in terrain[: width * height]]
        n = width * height
        self.water_dist = _distances(width, height, [c <= 1 for c in self.codes])
        self.flip = [0 if hash01(x, y, 41) < 0.5 else 1 for y in range(height) for x in range(width)]
        self.tile = [0.0] * n
        self.vert = [0.0] * ((width + 1) * (height + 1))
        self._derive()
        self._vertices()

    def _derive(self) -> None:
        w, h, codes = self.width, self.height, self.codes
        n = w * h
        into_mountain = _distances(w, h, [c != 6 for c in codes])
        into_hills = _distances(w, h, [c < 5 for c in codes])
        into_water = _distances(w, h, [c > 1 for c in codes])
        near_water = self.water_dist
        u = [0.0] * n
        for y in range(h):
            for x in range(w):
                r = y * w + x
                letter = LETTERS[codes[r]]
                a = BASE[letter]
                a += (noise(x / 7, y / 7, 11) - 0.5) * 0.45
                a += (hash01(x, y, 3) - 0.5) * 0.18
                if letter == "m":
                    e = into_mountain[r]
                    i2 = noise(x / 6, y / 6, 19)
                    s2 = (1 - abs(2 * i2 - 1)) ** 2
                    c2 = _smoothstep(0.3, 0.85, noise(x / 4, y / 4, 13))
                    a += min(e, 3) * 0.3 + (0.25 * s2 + 0.75 * c2) * 5.3 * _smoothstep(0.5, 3, e) + (noise(x / 3, y / 3, 17) - 0.5) * 0.8
                elif letter == "h":
                    a += min(into_hills[r], 3) * 0.3 + (noise(x / 4, y / 4, 23) - 0.5) * 0.5
                elif letter == "W":
                    a -= min(into_water[r], 6) * 0.14
                elif letter in ("g", "f"):
                    e = min(near_water[r], 10) / 10
                    a += e * 0.4 + (noise(x / 13, y / 13, 29) - 0.5) * 1.1 * (0.35 + 0.65 * e)
                    a += (noise(x / 12, y / 12, 31) - 0.5) * 0.7 * (0.3 + 0.7 * e)
                elif letter == "s":
                    e = min(near_water[r], 10) / 10
                    a += e * 0.4 + (noise(x / 13, y / 13, 29) - 0.5) * 1.1 * e * 0.8
                u[r] = _f32(a)
        d = u
        for p in range(2):
            out = [0.0] * n
            for y in range(h):
                for x in range(w):
                    o = y * w + x
                    total = weight = 0.0
                    for dy in (-1, 0, 1):
                        for dx in (-1, 0, 1):
                            ox, oy = int(_clamp(x + dx, 0, w - 1)), int(_clamp(y + dy, 0, h - 1))
                            k = 2 if dx == 0 and dy == 0 else 1 if dx == 0 or dy == 0 else 0.7
                            total += d[oy * w + ox] * k
                            weight += k
                    mean = total / weight
                    rate = (0.35 if p == 0 else 0.15) if codes[o] == 6 else (1 if p == 0 else 0.6)
                    out[o] = _f32(d[o] + (mean - d[o]) * rate)
            d = out
        for i in range(n):
            c, v = codes[i], d[i]
            if c == 0:
                v = min(v, -0.45)
            elif c == 1:
                v = _clamp(v, -0.7, -0.14)
            elif c == 2:
                v = _clamp(v, 0.08, 0.45 + min(near_water[i], 10) * 0.12)
            elif c in (3, 4):
                v = max(v, 0.16)
            elif c == 5:
                v = max(v, 0.9)
            else:
                v = max(v, 2.2)
            self.tile[i] = _f32(v)

    def _vertices(self) -> None:
        w, h, codes = self.width, self.height, self.codes
        for vy in range(h + 1):
            for vx in range(w + 1):
                total = 0.0
                count = land = water = mountain = hills = 0
                for dy in (-1, 0):
                    for dx in (-1, 0):
                        f = int(_clamp(vx + dx, 0, w - 1))
                        p = int(_clamp(vy + dy, 0, h - 1)) * w + f
                        m = codes[p]
                        total += self.tile[p]
                        count += 1
                        if m <= 1:
                            water += 1
                        else:
                            land += 1
                        if m == 6:
                            mountain += 1
                        if m == 5:
                            hills += 1
                v = total / count
                if land > 0 and water > 0:
                    v = -0.22 + land / count * 0.36 + (noise(vx / 2.3, vy / 2.3, 91) - 0.5) * 0.26 + (hash01(vx, vy, 93) - 0.5) * 0.08
                elif mountain == count:
                    e = _clamp((v - (PEAK - 1.2)) / 1.2, 0, 1)
                    v += (hash01(vx, vy, 71) - 0.5) * (0.9 * (1 - e) + 0.4 * e)
                elif mountain > 0:
                    v += (hash01(vx, vy, 71) - 0.5) * 0.35
                elif hills == count:
                    v += (hash01(vx, vy, 73) - 0.5) * 0.3
                elif land == count:
                    v += (hash01(vx, vy, 79) - 0.5) * 0.07
                self.vert[vy * (w + 1) + vx] = _f32(v)

    def height_at(self, x: float, y: float) -> float:
        w, h = self.width, self.height
        i, a = _clamp(x, 0, w - 1e-4), _clamp(y, 0, h - 1e-4)
        o, s = math.floor(i), math.floor(a)
        c, lo = i - o, a - s
        u = w + 1
        d, f, p, m = self.vert[s * u + o], self.vert[s * u + o + 1], self.vert[(s + 1) * u + o], self.vert[(s + 1) * u + o + 1]
        if self.flip[s * w + o] == 0:
            return d + (m - p) * c + (p - d) * lo if lo >= c else d + (f - d) * c + (m - f) * lo
        return d + (f - d) * c + (p - d) * lo if c + lo <= 1 else m + (p - m) * (1 - c) + (f - m) * (1 - lo)

    def tile_base(self, x: int, y: int) -> float:
        """Where the viewer stands a tile's blocks: the highest ground under its corners and its centre."""
        probes = ((x + 0.02, y + 0.02), (x + 0.98, y + 0.02), (x + 0.02, y + 0.98), (x + 0.98, y + 0.98), (x + 0.5, y + 0.5))
        return max(MIN_BASE, *(self.height_at(px, py) for px, py in probes))


@lru_cache(maxsize=2)
def _ground(width: int, height: int, terrain: str) -> Ground:
    return Ground(width, height, terrain)


def ground_of(world: dict[str, Any]) -> Ground:
    """The viewer's ground for a public world snapshot (``/live/world.json``), cached per terrain."""
    terrain = world["terrain"]
    if isinstance(terrain, list):
        terrain = "".join(terrain)
    return _ground(int(world.get("width", 128)), int(world.get("height", 128)), str(terrain))


def foundation(ground: Ground, tiles: list[tuple[int, int]]) -> dict[tuple[int, int], int]:
    """Whole levels of foundation per tile so the floors of a footprint stand on one plane.

    The highest tile base sets the plane; every other tile is raised by the levels nearest its shortfall
    (each level is a quarter tile), so every floor lies within half a level of the plane.
    """
    bases = {t: ground.tile_base(*t) for t in tiles}
    top = max(bases.values())
    return {t: round((top - b) / CELL) for t, b in bases.items()}


__all__ = ["BASE", "CELL", "Ground", "foundation", "ground_of", "hash01", "noise"]
