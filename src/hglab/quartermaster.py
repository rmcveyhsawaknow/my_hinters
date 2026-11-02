"""The quartermaster: building is never blocked by a full store (the owner, 2026-11-02).

One hand carries the duty (``knobs.quartermaster``: Caramelcart, the factory's hauler). Every store it may
take from is kept at or under a share of its capacity (``target``, three quarters). A store past the mark
gets its load moved into a store beside it that stands under the mark, a pack at a time: a take and a give
in one wake, both within a tile. With no such neighbour, another storehouse rises beside the full one and
the full one pays for it (a build pays from the pack first and then from storehouses within a tile that
admit the builder), so the hands can unload again by the next wake. Only stores whose contents show can be
judged: an opaque store of another faction is nobody's to balance, and its own hands raise another when it
fills (``claims.stores_max``). Nothing here speaks.

On 2026-10-31 every store of the office held 500 and the hands' gives were refused store by store for a
day each; at the works the mason raised another only once every store was full, and he stands at the
world's cap of blocks now. The quartermaster acts at the mark instead, before any give is refused.
"""

from __future__ import annotations

from typing import Any

from hglab.mood import PersonaState
from hglab.persona import Persona
from hglab.planner import (
    STOREHOUSE_CAPACITY,
    WorldView,
    _step_toward,
    chebyshev,
    materials_ok,
    neighbours,
    shortfall,
    with_storage,
)

DEFAULTS = {"target": 0.75, "stores_max": 24, "range": 40}
STORE_COST = {"wood": 20, "stone": 10}
KINDS = ("wood", "stone", "fiber", "ore", "berries")

Step = tuple[list[dict[str, Any]], str, str]


def config(persona: Persona) -> dict[str, Any] | None:
    knob = persona.knobs.get("quartermaster")
    if not isinstance(knob, dict):
        return None
    return {**DEFAULTS, **knob}


def held(store: dict[str, Any]) -> int | None:
    """Items a store holds, or None when its contents are hidden from us."""
    storage = store.get("storage")
    if not isinstance(storage, dict):
        return None
    return sum(int(v or 0) for v in storage.values())


def admits(persona: Persona, store: dict[str, Any], faction: str) -> bool:
    policy = str(store.get("policy") or "private")
    theirs = store.get("faction")
    theirs = str(theirs.get("name") if isinstance(theirs, dict) else theirs or "")
    return str(store.get("owner", "")).casefold() == persona.name.casefold() or policy == "public" or (policy == "faction" and bool(faction) and theirs.casefold() == faction.casefold())


def _where(store: dict[str, Any]) -> tuple[int, int]:
    return int(store["x"]), int(store["y"])


def _faction(observe: dict[str, Any]) -> str:
    faction = (observe.get("you") or {}).get("faction")
    return str(faction.get("name") if isinstance(faction, dict) else faction or "")


def plan_quartermaster(
    persona: Persona,
    state: PersonaState | None,
    observe: dict[str, Any],
    view: WorldView,
    inventory: dict[str, int],
    position: tuple[int, int],
    room: int,
    stores: list[dict[str, Any]],
    tick: int = 0,
    mates: set[str] | frozenset[str] = frozenset(),
) -> Step | None:
    """One step toward every readable store standing under the mark, or None when they all do.

    ``stores`` are the team's stores (the works' and its depots): the fullest one past the mark is served
    first. A move toward it is one action; the take and the give, or the build, happen beside it.
    ``mates`` (casefolded names) are the team: their buildings are no strangers' to raise a store beside.
    """
    cfg = config(persona)
    if cfg is None or room < 1:
        return None
    mark = int(float(cfg["target"]) * STOREHOUSE_CAPACITY)
    faction = _faction(observe)
    mates = {*mates, persona.name.casefold()}
    readable = [s for s in stores if held(s) is not None and admits(persona, s, faction)]
    over = sorted((s for s in readable if int(held(s) or 0) > mark), key=lambda s: (-int(held(s) or 0), chebyshev(position, _where(s))))
    if not over:
        return None
    full = over[0]
    where = _where(full)
    if chebyshev(position, where) > int(cfg["range"]):
        return None
    partners = [s for s in readable if _where(s) != where and chebyshev(_where(s), where) <= 1 and int(held(s) or 0) < mark]
    if partners:
        partner = max(partners, key=lambda s: mark - int(held(s) or 0))
        return _balance(full, partner, inventory, position, view, room, mark)
    ours = [s for s in stores if admits(persona, s, faction)]
    if len(ours) >= int(cfg["stores_max"]):
        return None  # at the cap of stores: the pipeline's own full-store rules take over
    return _raise(persona, full, readable, inventory, position, view, faction, mates)


def _balance(full: dict[str, Any], partner: dict[str, Any], inventory: dict[str, int], position: tuple[int, int], view: WorldView, room: int, mark: int) -> Step | None:
    """Carry the excess from the full store into the one beside it: a take and a give, standing within a tile of both."""
    where, into = _where(full), _where(partner)
    if chebyshev(position, where) <= 1 and chebyshev(position, into) <= 1:
        storage = full.get("storage") if isinstance(full.get("storage"), dict) else {}
        item = max(KINDS, key=lambda k: int(storage.get(k, 0) or 0))
        pack = sum(inventory.values())
        qty = min(int(held(full) or 0) - mark, mark - int(held(partner) or 0), 50 - pack, int(storage.get(item, 0) or 0))
        if qty < 1:
            return None
        actions = [{"action": "take", "x": where[0], "y": where[1], "item": item, "qty": qty}]
        if room >= 2:
            actions.append({"action": "give", "x": into[0], "y": into[1], "item": item, "qty": qty})
        return actions, f"the store at {where} holds {held(full)} of {STOREHOUSE_CAPACITY}, past three quarters: move {qty} {item} into the store at {into} ({held(partner)})", "crew"
    stand = [t for t in [*neighbours(*where), where] if chebyshev(t, into) <= 1 and (t == position or view.free_tile(*t) or t in (where, into))]
    if not stand:
        return None
    target = min(stand, key=lambda t: (chebyshev(position, t), t))
    step = _step_toward(position, {"x": target[0], "y": target[1]}, view)
    if step is None or step == position:
        return None
    return [{"action": "move", "x": step[0], "y": step[1]}], f"the store at {where} holds {held(full)} of {STOREHOUSE_CAPACITY}, past three quarters: walk to it to move the excess into the store at {into}", "crew"


def _raise(persona: Persona, full: dict[str, Any], readable: list[dict[str, Any]], inventory: dict[str, int], position: tuple[int, int], view: WorldView, faction: str, mates: set[str]) -> Step | None:
    """Another storehouse beside the full one, paid by the full one; its wood and stone fetched first when it holds neither."""
    where = _where(full)
    nodes = {(int(r["x"]), int(r["y"])) for r in (view.world_resources or view.resources) if isinstance(r.get("x"), int) and isinstance(r.get("y"), int)}
    tiles = [t for t in neighbours(*where) if view.free_tile(*t) and t not in nodes and not _beside_a_stranger(t, view, mates, faction)]
    if not tiles:
        return None
    tile = min(tiles, key=lambda t: (chebyshev(position, t), t))
    storage = full.get("storage") if isinstance(full.get("storage"), dict) else {}
    payable = materials_ok(with_storage(inventory, storage), "storehouse") if chebyshev(position, where) <= 1 else materials_ok(with_storage(inventory, {k: int(storage.get(k, 0) or 0) for k in STORE_COST}), "storehouse")
    if payable:
        if position == tile or (chebyshev(position, tile) <= 1 and chebyshev(position, where) <= 1):
            paid = "the pack" if materials_ok(inventory, "storehouse") else f"the pack and the full store at {where}"
            return [{"action": "build", "type": "storehouse", "x": tile[0], "y": tile[1], "policy": "faction"}], f"the store at {where} holds {held(full)} of {STOREHOUSE_CAPACITY}, past three quarters, and no store beside it has room: raise another at {tile}, paid from {paid}", "crew"
        step = _step_toward(position, {"x": tile[0], "y": tile[1]}, view)
        if step is None or step == position:
            return None
        return [{"action": "move", "x": step[0], "y": step[1]}], f"the store at {where} holds {held(full)} of {STOREHOUSE_CAPACITY}, past three quarters: walk to {tile} to raise another store beside it", "crew"
    # the full store holds no wood or stone to pay with: fetch the shortfall from a store that does
    lacking = shortfall(with_storage(inventory, {k: int(storage.get(k, 0) or 0) for k in STORE_COST}), "storehouse")
    pack_room = 50 - sum(inventory.values())
    for store in sorted(readable, key=lambda s: chebyshev(position, _where(s))):
        if _where(store) == where:
            continue
        have = store.get("storage") if isinstance(store.get("storage"), dict) else {}
        takes = [{"action": "take", "x": _where(store)[0], "y": _where(store)[1], "item": k, "qty": min(q, int(have.get(k, 0) or 0), pack_room)} for k, q in lacking.items() if int(have.get(k, 0) or 0) >= 1]
        takes = [t for t in takes if t["qty"] >= 1]
        if not takes:
            continue
        if chebyshev(position, _where(store)) <= 1:
            what = ", ".join(f"{t['qty']} {t['item']}" for t in takes)
            return takes, f"the store at {where} is past three quarters but holds no wood or stone for another: take {what} from the store at {_where(store)}", "crew"
        step = _step_toward(position, {"x": _where(store)[0], "y": _where(store)[1]}, view)
        if step is None or step == position:
            continue
        return [{"action": "move", "x": step[0], "y": step[1]}], f"the store at {where} is past three quarters but holds no wood or stone for another: fetch them from the store at {_where(store)}", "crew"
    return None


def _beside_a_stranger(tile: tuple[int, int], view: WorldView, mates: set[str], faction: str) -> bool:
    """A store never rises beside another resident's building (the walls' rule, kept here too)."""
    for s in [*view.world_structures, *view.structures]:
        if s.get("type") in ("road", "sign", "bridge") or not isinstance(s.get("x"), int):
            continue
        if chebyshev(tile, (int(s["x"]), int(s["y"]))) > 1:
            continue
        owner = str(s.get("owner", "")).casefold()
        theirs = s.get("faction")
        theirs = str(theirs.get("name") if isinstance(theirs, dict) else theirs or "")
        if owner not in mates and not (faction and theirs.casefold() == faction.casefold()):
            return True
    return False


__all__ = ["DEFAULTS", "admits", "config", "held", "plan_quartermaster"]
