"""The land office's walls: its staked lots ringed in stone, a gate open in the middle of every side.

By the owner's instruction of 2026-10-25 the office's hands turn the stone its full stores cannot hold
into walls around its staked lots, the holdings first (``teams/exchange.yaml: pipeline.claims.walls``).
A wall costs 2 stone and blocks everyone but its owner's faction, so the conduct rule every persona
inherits (never a wall across anyone's path) is kept by the shape and by what is left alone:

- the middle tile of each side of a lot is a gate and is never walled; the lots share one grid, so
  the gates of neighbouring lots line up into straight corridors through any walled stretch;
- a wall goes only on a free tile: roads, bridges, signs and every other structure stay as they are;
- never on a resource node, on a tile where someone stands, or beside another resident's hut,
  storehouse, farm, tower, monument or bridge;
- never on a lot near the spawn (``protect_spawn``), in a homestead's ring of lots
  (``protect_homesteads``), holding another resident's building, sold or deeded, or under contract
  to a client (``exclude``: the Chocolate Factory's four plots).
"""

from __future__ import annotations

from typing import Any

from hglab.lots import WORLD_CENTRE, homestead_ring, lot_bounds, lot_id, staked_lots

WALL_COST = 2  # stone per wall (the guide)
WALL_ENERGY = 5  # a build costs 5 energy
WALL_DRAW = 30  # stone a hand takes from a full store at a time, to wall with
NO_WALL_TICKS = 8640  # a tile where the world refused a wall is left open for a day
VISITED = frozenset({"hut", "storehouse", "farm", "tower", "monument", "bridge"})  # another resident's: no wall beside it


def walls_cfg(claims: dict[str, Any] | None) -> dict[str, Any] | None:
    """The walls block of the claims config, or None when the office raises no walls."""
    cfg = (claims or {}).get("walls")
    if not isinstance(cfg, dict) or not cfg.get("enabled", True):
        return None
    return cfg


def gates(lid: str) -> set[tuple[int, int]]:
    """The middle tile of each side of a lot: always left open."""
    x0, y0, x1, y1 = lot_bounds(lid)
    mx, my = (x0 + x1) // 2, (y0 + y1) // 2
    return {(mx, y0), (mx, y1), (x0, my), (x1, my)}


def ring(lid: str) -> list[tuple[int, int]]:
    """The lot's border tiles, gates included, clockwise from its north-west corner."""
    x0, y0, x1, y1 = lot_bounds(lid)
    top = [(x, y0) for x in range(x0, x1 + 1)]
    right = [(x1, y) for y in range(y0 + 1, y1 + 1)]
    bottom = [(x, y1) for x in range(x1 - 1, x0 - 1, -1)] if y1 > y0 else []
    left = [(x0, y) for y in range(y1 - 1, y0, -1)] if x1 > x0 else []
    return [*top, *right, *bottom, *left]


def _sold(structures: list[dict[str, Any]], registrar: str) -> set[str]:
    """Lots the office has sold or deeded: their claim sign names a holder, or a deed sign stands there."""
    out: set[str] = set()
    for s in structures:
        if not isinstance(s, dict) or s.get("type") != "sign" or str(s.get("owner", "")).casefold() != registrar.casefold():
            continue
        text = str(s.get("text") or "")
        if (text.startswith("Deed ") or " held by " in text) and isinstance(s.get("x"), int) and isinstance(s.get("y"), int):
            out.add(lot_id(s["x"], s["y"]))
    return out


def _near_spawn(lid: str, radius: int) -> bool:
    x0, y0, x1, y1 = lot_bounds(lid)
    cx, cy = min(max(WORLD_CENTRE[0], x0), x1), min(max(WORLD_CENTRE[1], y0), y1)  # the lot's tile nearest the centre
    return max(abs(cx - WORLD_CENTRE[0]), abs(cy - WORLD_CENTRE[1])) <= radius


def wall_lots(
    claims: dict[str, Any] | None,
    held: list[dict[str, Any]],
    structures: list[dict[str, Any]],
    office: set[str] | frozenset[str],
    held_by: set[str] | frozenset[str] = frozenset(),
) -> tuple[list[str], list[str]]:
    """The lots to wall: (holdings in rank order, then the other staked lots when ``scope`` is ``staked``).

    ``office`` holds the casefolded names of the office's members: a lot with anyone else's building is
    never walled.
    """
    cfg = walls_cfg(claims)
    if cfg is None or not claims or not claims.get("registrar"):
        return [], []
    registrar = str(claims["registrar"])
    excluded = {str(lid).upper() for lid in (claims.get("exclude") or [])}
    spawn = int(claims.get("protect_spawn", 12) or 0)
    homes = homestead_ring(structures, registrar) if claims.get("protect_homesteads", True) else set()
    sold = _sold(structures, registrar)
    foreign = {
        lot_id(int(s["x"]), int(s["y"]))
        for s in structures
        if isinstance(s, dict) and s.get("type") in VISITED and isinstance(s.get("x"), int) and isinstance(s.get("y"), int)
        and str(s.get("owner", "")).casefold() not in office
    }

    def allowed(lid: str) -> bool:
        return lid not in excluded and lid not in sold and lid not in held_by and lid not in homes and lid not in foreign and not (spawn and _near_spawn(lid, spawn))

    first = [str(h["lot"]) for h in held if allowed(str(h["lot"]))]
    rest: list[str] = []
    if str(cfg.get("scope", "holdings")) == "staked":
        seen = set(first) | {str(h["lot"]) for h in held}
        rest = sorted(lid for lid in staked_lots(structures, registrar) if lid not in seen and allowed(lid))
    return first, rest


def blocked_near(structures: list[dict[str, Any]], office: set[str] | frozenset[str]) -> set[tuple[int, int]]:
    """Tiles beside (or under) anything of anyone outside the office, a road or sign included: never walled.

    The same rule the persona knob check enforces ("never wall beside another agent's structure or
    path"); a planned wall that broke it would have the whole wake refused (2026-10-25: three hands lost
    a shift that way).
    """
    out: set[tuple[int, int]] = set()
    for s in structures:
        owner = str(s.get("owner") or "").casefold() if isinstance(s, dict) else ""
        if not owner or owner in office:
            continue
        if not isinstance(s.get("x"), int) or not isinstance(s.get("y"), int):
            continue
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                out.add((s["x"] + dx, s["y"] + dy))
    return out


def open_tiles(lid: str, free: Any, skip: set[tuple[int, int]]) -> list[tuple[int, int]]:
    """The ring tiles of a lot still to wall: not a gate, free (``free(x, y)``), not in ``skip``."""
    gate = gates(lid)
    return [t for t in ring(lid) if t not in gate and t not in skip and free(*t)]


def no_wall(state: Any, tick: int) -> set[tuple[int, int]]:
    """Tiles where the world refused a wall within the day."""
    flags = state.flags.get("no_wall") if state is not None and isinstance(getattr(state, "flags", None), dict) and isinstance(state.flags.get("no_wall"), dict) else {}
    out: set[tuple[int, int]] = set()
    for key, seen in flags.items():
        if tick - int(seen or 0) > NO_WALL_TICKS:
            continue
        try:
            x, y = (int(v) for v in str(key).split(","))
        except ValueError:
            continue
        out.add((x, y))
    return out


def mark_no_wall(state: Any, where: tuple[int, int], tick: int) -> None:
    if state is None:
        return
    flags = state.flags.get("no_wall") if isinstance(state.flags.get("no_wall"), dict) else {}
    flags[f"{where[0]},{where[1]}"] = tick
    state.flags["no_wall"] = dict(sorted(flags.items(), key=lambda kv: -int(kv[1] or 0))[:8])


__all__ = [
    "NO_WALL_TICKS", "VISITED", "WALL_COST", "WALL_DRAW", "WALL_ENERGY", "blocked_near", "gates", "mark_no_wall",
    "no_wall", "open_tiles", "ring", "wall_lots", "walls_cfg",
]
