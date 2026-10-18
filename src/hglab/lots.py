"""Lots: the land office's unit of sale, a 5 by 5 block inside the 10 by 10 plots.

Lot ids read ``F05-NW``: the plot (column letter by x, row by y) and the quadrant. The lot grid
is 26 by 26 (the last column and row are narrower), 676 lots in all. A lot is free when no
structure stands in it; staking a lot means one sign on its anchor tile (the centre), the
cheapest claim the world allows, and the price of a lot rises as free lots run out.
"""

from __future__ import annotations

import math
from typing import Any

LOT = 5
WORLD = 128
COLUMNS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
QUADRANTS = ("NW", "NE", "SW", "SE")
GRID = math.ceil(WORLD / LOT)  # 26 lot columns and rows


def lot_grid(x: int, y: int) -> tuple[int, int]:
    return int(x) // LOT, int(y) // LOT


def lot_id_from_grid(lx: int, ly: int) -> str:
    return f"{COLUMNS[lx // 2]}{ly // 2:02d}-{QUADRANTS[(ly % 2) * 2 + lx % 2]}"


def lot_id(x: int, y: int) -> str:
    """(67, 56) lies in plot G05, north-east quadrant: G05-NE."""
    return lot_id_from_grid(*lot_grid(x, y))


def lot_grid_of(lid: str) -> tuple[int, int]:
    plot, quadrant = lid.split("-")
    col, row = COLUMNS.index(plot[0].upper()), int(plot[1:])
    q = QUADRANTS.index(quadrant.upper())
    return col * 2 + q % 2, row * 2 + q // 2


def lot_bounds(lid: str) -> tuple[int, int, int, int]:
    lx, ly = lot_grid_of(lid)
    x0, y0 = lx * LOT, ly * LOT
    return x0, y0, min(x0 + LOT - 1, WORLD - 1), min(y0 + LOT - 1, WORLD - 1)


def lot_anchor(lid: str) -> tuple[int, int]:
    """The tile a claim sign goes on: the lot's centre."""
    x0, y0, x1, y1 = lot_bounds(lid)
    return (x0 + x1) // 2, (y0 + y1) // 2


def all_lots() -> list[str]:
    return [lot_id_from_grid(lx, ly) for ly in range(GRID) for lx in range(GRID)]


def total_lots() -> int:
    return GRID * GRID


def occupied_lots(structures: list[dict[str, Any]]) -> set[str]:
    return {
        lot_id(s["x"], s["y"]) for s in structures
        if isinstance(s, dict) and isinstance(s.get("x"), int) and isinstance(s.get("y"), int)
    }


def free_lots(structures: list[dict[str, Any]]) -> set[str]:
    return set(all_lots()) - occupied_lots(structures)


def homestead_ring(structures: list[dict[str, Any]], exclude_owner: str) -> set[str]:
    """Lots holding another agent's hut, plus the ring of lots around each: the office leaves homesteads room."""
    ring: set[str] = set()
    for s in structures:
        if not isinstance(s, dict) or s.get("type") != "hut" or str(s.get("owner", "")).casefold() == exclude_owner.casefold():
            continue
        if not isinstance(s.get("x"), int) or not isinstance(s.get("y"), int):
            continue
        lx, ly = lot_grid(s["x"], s["y"])
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if 0 <= lx + dx < GRID and 0 <= ly + dy < GRID:
                    ring.add(lot_id_from_grid(lx + dx, ly + dy))
    return ring


def lot_price(free_share: float, base: int = 5, cap: int = 50) -> int:
    """Price of one lot: the base while land is plentiful, rising as free lots run out, never above the cap.

    With half the lots free a lot costs twice the base; with a tenth free, ten times; the cap keeps it
    inside what one give can deliver (50).
    """
    share = max(min(float(free_share), 1.0), 0.0)
    return int(max(base, min(cap, round(base / max(share, base / cap)))))


def staked_lots(structures: list[dict[str, Any]], registrar: str) -> dict[str, dict[str, Any]]:
    """Lot id -> the office's claim sign standing on it (a sign owned by the registrar whose text starts with 'Lot ')."""
    out: dict[str, dict[str, Any]] = {}
    for s in structures:
        if not isinstance(s, dict) or s.get("type") != "sign" or str(s.get("owner", "")).casefold() != registrar.casefold():
            continue
        if not str(s.get("text") or "").startswith("Lot ") or not isinstance(s.get("x"), int) or not isinstance(s.get("y"), int):
            continue
        out[lot_id(s["x"], s["y"])] = s
    return out


def stake_text(lid: str, registrar: str) -> str:
    return f"Lot {lid}: staked by {registrar} for the land office. For sale; buy through my posted goal or ask by whisper."[:200]


__all__ = [
    "GRID", "LOT", "all_lots", "free_lots", "homestead_ring", "lot_anchor", "lot_bounds", "lot_grid", "lot_grid_of", "lot_id",
    "lot_id_from_grid", "lot_price", "occupied_lots", "stake_text", "staked_lots", "total_lots",
]
