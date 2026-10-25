"""The land office clears its staked lots of what others built there without buying them.

By the owner's instruction of 2026-10-25: objects built on a lot the office has staked, by an agent
who has neither bought the lot nor registered it with the office, are taken down by the office's hands,
and so is anything standing where a wall of the office's ring belongs. The office stakes only empty lots,
so whatever an outsider has there went up after the claim sign did.

The office keeps its dealing honest, as its stake signs promise a sale: the registrar whispers each
builder a notice first (what stands where, the lot's price, how to buy or register, how long), and the
hands take nothing down until ``notice_ticks`` have passed since that notice. What a notice covers:
structures in the public snapshot and the block placements of the public event log, on policed lots.

Never touched: the collective's own builds (every persona of this repository), except a road of ours
on a tile where a wall of the ring belongs, which comes down without a notice; caches; lots sold,
deeded or registered to anyone (their signs, and the registry the land round shares); ground under
contract (``claims.exclude``: the Chocolate Factory's plots); the spawn circle (``claims.protect_spawn``).
Bridges are not spared.

The notices and the registry live in a small shared ledger on this host
(``runs/local/office/evictions.json``): written by the registrar's land round, read by the hands.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from hglab.lots import QUADRANTS, lot_id, staked_lots
from hglab.walls import _near_spawn

SHARED = "runs/local/office/evictions.json"
NOTICE_TICKS = 360  # one real hour between the notice and the first hit (the owner, 2026-10-25)
SPARE = frozenset({"cache"})  # bridges are not spared (the owner, 2026-10-25)
DEED_SIGN = re.compile(r"^Deed ([A-Z][0-9]{2}(?:-(?:NW|NE|SW|SE))?): holder ([A-Za-z0-9_-]{3,24})")
SOLD_SIGN = re.compile(r"^Lot ([A-Z][0-9]{2}-(?:NW|NE|SW|SE)): held by ([A-Za-z0-9_-]{3,24})")


def evict_cfg(claims: dict[str, Any] | None) -> dict[str, Any] | None:
    cfg = (claims or {}).get("evict")
    if not isinstance(cfg, dict) or not cfg.get("enabled", True):
        return None
    return cfg


def notice_ticks(cfg: dict[str, Any] | None) -> int:
    return int((cfg or {}).get("notice_ticks", NOTICE_TICKS) or 0)


def shared_path(root: Path) -> Path:
    return Path(root) / SHARED


def load_shared(root: Path) -> dict[str, Any]:
    """The shared ledger: ``notices`` {owner: {tick, lots, count}}, ``held`` {lot or plot: holder}."""
    try:
        data = json.loads(shared_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not isinstance(data, dict):
        data = {}
    data.setdefault("notices", {})
    data.setdefault("held", {})
    return data


def save_shared(root: Path, data: dict[str, Any]) -> None:
    path = shared_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".evictions-", suffix=".json")
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        json.dump(data, handle, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def _lots_of(plot: str) -> list[str]:
    """A lot id names itself; a 10x10 plot id names its four lots."""
    return [plot] if "-" in plot else [f"{plot}-{q}" for q in QUADRANTS]


def held_lots(structures: list[dict[str, Any]], registrar: str, shared: dict[str, Any] | None = None) -> dict[str, str]:
    """Lot -> holder: bought (the claim sign names a holder), deeded (a deed sign), or in the registry the land round shares."""
    out: dict[str, str] = {}
    for plot, holder in ((shared or {}).get("held") or {}).items():
        for lid in _lots_of(str(plot)):
            out[lid] = str(holder)
    for s in structures:
        if not isinstance(s, dict) or s.get("type") != "sign" or str(s.get("owner", "")).casefold() != registrar.casefold():
            continue
        text = str(s.get("text") or "")
        deed, sold = DEED_SIGN.match(text), SOLD_SIGN.match(text)
        if deed:
            for lid in _lots_of(deed.group(1)):
                out[lid] = deed.group(2)
        elif sold:
            out[sold.group(1)] = sold.group(2)
    return out


def policed_lots(claims: dict[str, Any] | None, structures: list[dict[str, Any]], held: dict[str, str]) -> set[str]:
    """The office's staked lots it still keeps the ground of: not held by anyone, not under contract, not by the spawn."""
    if not claims or not claims.get("registrar"):
        return set()
    excluded = {str(lid).upper() for lid in (claims.get("exclude") or [])}
    spawn = int(claims.get("protect_spawn", 12) or 0)
    return {
        lid for lid in staked_lots(structures, str(claims["registrar"]))
        if lid not in excluded and lid not in held and not (spawn and _near_spawn(lid, spawn))
    }


def intruders(policed: set[str], structures: list[dict[str, Any]], collective: set[str] | frozenset[str]) -> list[dict[str, Any]]:
    """Structures of agents outside the collective on policed lots (bridges and caches spared)."""
    out = []
    for s in structures:
        if not isinstance(s, dict) or s.get("type") in SPARE or not isinstance(s.get("x"), int) or not isinstance(s.get("y"), int):
            continue
        owner = str(s.get("owner") or "")
        if not owner or owner.casefold() in collective:
            continue
        lid = lot_id(s["x"], s["y"])
        if lid in policed:
            out.append({"id": s.get("id"), "type": str(s.get("type")), "x": s["x"], "y": s["y"], "owner": owner, "lot": lid, "hp": s.get("hp")})
    return out


def ring_roads(policed: set[str], structures: list[dict[str, Any]], collective: set[str] | frozenset[str]) -> list[dict[str, Any]]:
    """The collective's own roads standing where a wall of a policed lot's ring belongs (never a gate): they come down too."""
    from hglab.walls import gates, ring

    out = []
    for s in structures:
        if not isinstance(s, dict) or s.get("type") != "road" or not isinstance(s.get("x"), int) or not isinstance(s.get("y"), int):
            continue
        owner = str(s.get("owner") or "")
        if not owner or owner.casefold() not in collective:
            continue
        lid = lot_id(s["x"], s["y"])
        here = (s["x"], s["y"])
        if lid in policed and here in set(ring(lid)) and here not in gates(lid):
            out.append({"id": s.get("id"), "type": "road", "x": s["x"], "y": s["y"], "owner": owner, "lot": lid, "hp": s.get("hp")})
    return out


def block_builders(policed: set[str], events: list[dict[str, Any]], collective: set[str] | frozenset[str]) -> dict[str, set[str]]:
    """Owner -> lots, for block placements in the public event log on policed lots by agents outside the collective."""
    out: dict[str, set[str]] = {}
    for e in events:
        if not isinstance(e, dict) or e.get("type") != "place" or not isinstance(e.get("x"), int) or not isinstance(e.get("y"), int):
            continue
        actor = str(e.get("actor") or "")
        if not actor or actor.casefold() in collective:
            continue
        lid = lot_id(e["x"], e["y"])
        if lid in policed:
            out.setdefault(actor, set()).add(lid)
    return out


def due_owners(shared: dict[str, Any], tick: int, wait: int) -> set[str]:
    """Owners (casefolded) whose notice is at least ``wait`` ticks old."""
    return {
        str(name).casefold() for name, notice in (shared.get("notices") or {}).items()
        if isinstance(notice, dict) and tick - int(notice.get("tick", tick) or tick) >= wait
    }


def notice_text(owner: str, items: list[dict[str, Any]], lots: list[str], price: int | None, currency: str, hours: int, vault: dict[str, Any] | None) -> str:
    """The notice whispered to a builder: what stands where, the price, how to buy or register, and when."""
    what = ", ".join(f"{i['type']} at ({i['x']},{i['y']})" for i in items[:4])
    more = f" and {len(items) - 4} more" if len(items) > 4 else ""
    if not items:
        what = "blocks"
    where = ", ".join(lots[:4]) + (" and others" if len(lots) > 4 else "")
    cost = f" from {price} {currency}" if price else ""
    pay = f" (claim my lot-sale goal, then give the price into my storehouse at ({vault['x']},{vault['y']}))" if vault else ""
    text = (
        f"Land office notice for {owner}: your {what}{more} stand on lot {where}, staked by the land office before you built."
        f" Buy the lot{cost}{pay} or register it with me within {hours} hour{'s' if hours != 1 else ''}, and it stays. After that the office's hands"
        " take down what you built there. Whisper me to buy."
    )
    return text[:500]


def plan_notice(
    claims: dict[str, Any] | None,
    structures: list[dict[str, Any]],
    events: list[dict[str, Any]],
    collective: set[str] | frozenset[str],
    shared: dict[str, Any],
    *,
    prices: dict[str, int] | None = None,
    currency: str = "wood",
    vault: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str, list[str], str] | None:
    """One notice per round, to the builder with the most on policed lots who has had none: (whisper, owner, lots, reason)."""
    cfg = evict_cfg(claims)
    if cfg is None or not claims:
        return None
    held = held_lots(structures, str(claims["registrar"]), shared)
    policed = policed_lots(claims, structures, held)
    if not policed:
        return None
    noticed = {str(n).casefold() for n in (shared.get("notices") or {})}
    by_owner: dict[str, list[dict[str, Any]]] = {}
    for item in intruders(policed, structures, collective):
        by_owner.setdefault(item["owner"], []).append(item)
    lots_of: dict[str, set[str]] = {owner: {i["lot"] for i in items} for owner, items in by_owner.items()}
    for owner, lots in block_builders(policed, events, collective).items():
        lots_of.setdefault(owner, set()).update(lots)
        by_owner.setdefault(owner, [])
    waiting = sorted((o for o in lots_of if o.casefold() not in noticed), key=lambda o: (-len(by_owner[o]) - len(lots_of[o]), o))
    if not waiting:
        return None
    owner = waiting[0]
    lots = sorted(lots_of[owner])
    price = min((int((prices or {}).get(lid, 0) or 0) for lid in lots if (prices or {}).get(lid)), default=None)
    hours = max(1, round(notice_ticks(cfg) / 360))
    text = notice_text(owner, sorted(by_owner[owner], key=lambda i: (i["lot"], i["x"], i["y"])), lots, price, currency, hours, vault)
    reason = f"{owner} built on staked lot {', '.join(lots[:3])} without buying it: a notice first, the hands after {hours} hour{'s' if hours != 1 else ''}"
    return {"action": "whisper", "to": owner, "text": text}, owner, lots, reason


def record_notice(shared: dict[str, Any], owner: str, lots: list[str], tick: int) -> dict[str, Any]:
    notices = dict(shared.get("notices") or {})
    notices[owner] = {"tick": tick, "lots": lots[:12]}
    return {**shared, "notices": notices}


__all__ = [
    "NOTICE_TICKS",
    "SHARED",
    "SPARE",
    "block_builders",
    "due_owners",
    "evict_cfg",
    "held_lots",
    "intruders",
    "load_shared",
    "notice_text",
    "notice_ticks",
    "plan_notice",
    "policed_lots",
    "record_notice",
    "ring_roads",
    "save_shared",
    "shared_path",
]
