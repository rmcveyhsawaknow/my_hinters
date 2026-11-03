"""The land office's fill board and its gathering throttle (the owner, 2026-11-03).

A storehouse shows its contents only to an agent beside it, so the office's members could not tell a full
store out of sight from an empty one: the mason waited for "every store full" among stores he could not see,
and the hands gathered into a jam. Every live wake of an office member writes the office's stores it saw, with
their contents (``runs/local/office/fill.json``), and every member reads them back for six hours.

The owner's rule: while every store of the office is past the mark (``claims.overflow_at``), its hands gather
nothing; under it, as many gather as the room left under the mark holds packs (``PACK``), the hand whose kinds
the office holds least of against its stock (``pipeline.stock``) first, then the hauler, the mason and the
registrar. Gathering and not gathering balance themselves on the store levels: the walls, a new store's cost and
the sales desk draw the stores down and the hands take up gathering again; a new store's room puts them back to
work at once.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

FILL = "runs/local/office/fill.json"
SEEN_TICKS = 2160  # a sighting stands for six hours
KEEP_TICKS = 8640  # and is forgotten after a day
PACK = 50  # a hand's pack: one gathering slot is room for one pack under the mark
CAPACITY = 500  # a storehouse (hglab.planner.STOREHOUSE_CAPACITY)
ROLE_KINDS = {"quarrier": ("stone", "ore"), "woodcutter": ("wood",), "provisioner": ("fiber", "berries")}  # the gatherers (hglab.crew.GATHERERS)
ROLE_ORDER = {"hauler": 1, "mason": 2}  # after the gatherers; a member with no crew role (the registrar) last


def board_path(root: Path) -> Path:
    return Path(root) / FILL


def load_board(root: Path) -> dict[str, dict[str, Any]]:
    """Tile ``"x,y"`` to ``{"tick", "storage"}``: the last time an office member saw the store, and what it held."""
    try:
        data = json.loads(board_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): v for k, v in data.items() if isinstance(v, dict)} if isinstance(data, dict) else {}


def record(root: Path, structures: list[dict[str, Any]], owners: set[str], tick: int) -> int:
    """Put the owners' stores seen with their contents onto the board; returns how many. Live wakes only."""
    owners_cf = {str(o).casefold() for o in owners}
    seen: dict[str, dict[str, Any]] = {}
    for s in structures or []:
        if not isinstance(s, dict) or s.get("type") != "storehouse" or str(s.get("owner", "")).casefold() not in owners_cf:
            continue
        storage = s.get("storage")
        if not isinstance(storage, dict) or not isinstance(s.get("x"), int) or not isinstance(s.get("y"), int):
            continue
        seen[f"{s['x']},{s['y']}"] = {"tick": int(tick), "storage": {str(k): int(v or 0) for k, v in storage.items()}}
    if not seen:
        return 0
    board = load_board(root)
    for key, entry in seen.items():
        if int((board.get(key) or {}).get("tick", -1) or -1) <= int(tick):
            board[key] = entry
    board = {k: v for k, v in board.items() if int(tick) - int(v.get("tick", 0) or 0) <= KEEP_TICKS}
    path = board_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".fill-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(dict(sorted(board.items())), handle, ensure_ascii=False, indent=1)
    os.replace(tmp, path)
    return len(seen)


def enrich(stores: list[dict[str, Any]], board: dict[str, dict[str, Any]], tick: int) -> list[dict[str, Any]]:
    """Stores out of view take their contents from the board when seen within ``SEEN_TICKS`` (a copy, ``seen`` the tick)."""
    out: list[dict[str, Any]] = []
    for s in stores:
        entry = board.get(f"{s.get('x')},{s.get('y')}")
        if isinstance(s.get("storage"), dict) or not entry or not isinstance(entry.get("storage"), dict):
            out.append(s)
            continue
        seen = int(entry.get("tick", -1) or -1)
        out.append({**s, "storage": dict(entry["storage"]), "seen": seen} if 0 <= tick - seen <= SEEN_TICKS else s)
    return out


def levels(stores: list[dict[str, Any]], full: set[tuple[int, int]], room_min: int) -> dict[str, Any]:
    """What the known stores hold: ``known``, ``past`` (at or past the mark, or refused a give lately), ``room``
    (left under the mark, summed), ``slots`` (packs that room holds) and ``held`` per kind."""
    mark = CAPACITY - int(room_min)
    known = past = room = 0
    held: dict[str, int] = {}
    for s in stores:
        storage = s.get("storage")
        if not isinstance(storage, dict):
            continue
        known += 1
        for item, qty in storage.items():
            held[str(item)] = held.get(str(item), 0) + int(qty or 0)
        total = sum(int(v or 0) for v in storage.values())
        if (int(s["x"]), int(s["y"])) in full or total >= mark:
            past += 1
            continue
        room += mark - total
    return {"known": known, "past": past, "room": room, "slots": room // PACK, "held": held, "mark": mark}


def order(members: list[str], crew_roles: dict[str, str] | None, held: dict[str, int], stock: dict[str, Any]) -> list[str]:
    """The members in the order they take a gathering slot: the gatherer whose kinds the office holds least of
    against its stock first, then the hauler, the mason, and the members with no crew role (the registrar)."""
    roles = crew_roles or {}

    def need(slug: str) -> float:
        kinds = ROLE_KINDS.get(roles.get(slug, ""), ())
        ratios = [held.get(k, 0) / float(stock[k]) for k in kinds if float(stock.get(k, 0) or 0) > 0]
        return min(ratios) if ratios else float("inf")

    def key(slug: str) -> tuple[int, float, str]:
        role = roles.get(slug, "")
        tier = 0 if role in ROLE_KINDS else ROLE_ORDER.get(role, 3)
        return tier, need(slug), slug

    return sorted(members, key=key)


def decide(slug: str, members: list[str], crew_roles: dict[str, str] | None, stores: list[dict[str, Any]], full: set[tuple[int, int]], room_min: int, stock: dict[str, Any]) -> tuple[bool, str]:
    """Whether this member gathers now, and why (for the wake's reasons)."""
    lv = levels(stores, full, room_min)
    share = round(100 * lv["mark"] / CAPACITY)
    if not lv["known"]:
        return True, "no store of the office seen lately: gather as before"
    if not lv["slots"]:
        return False, f"every store of the office seen lately is past {share}% ({lv['past']} of {lv['known']}): no gathering; the walls and the stores draw them down"
    ranked = order(members, crew_roles, lv["held"], stock)
    place = ranked.index(slug) if slug in ranked else len(ranked)
    if place < lv["slots"]:
        return True, f"the office's stores have room for {lv['slots']} pack(s) under {share}%: gathering, {place + 1} of {min(lv['slots'], len(ranked))}"
    return False, f"the office's stores have room for {lv['slots']} pack(s) under {share}%, taken by the hands its stock is shortest for: no gathering this wake"


__all__ = ["FILL", "KEEP_TICKS", "PACK", "SEEN_TICKS", "board_path", "decide", "enrich", "levels", "load_board", "order", "record"]
