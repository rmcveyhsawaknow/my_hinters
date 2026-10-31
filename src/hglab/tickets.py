"""The golden tickets (the owner's brief of 2026-10-31): Fudgewright hides each ticket as one yellow square in the
brown floor of a strongroom inside a walled vault, and posts a goal that pays the peer who breaks in.

A vault (``knobs.tickets.vaults``) is a strip three tiles deep: strongrooms on its middle line with a wall tile
between each two, and brown stone cubes on every other tile, so each strongroom's eight neighbours are walls.
Every tile of the strip lies within two tiles of the ground outside it, so Fudgewright raises, mends and
repaints it from outside, and a seeker breaks it from outside: ``remove`` takes 8 of another's blocks a turn.
Each strongroom holds a private storehouse of his. The goal ("Golden Ticket N of 5") confirms itself when its
claimant gives one berry into the storehouse under the yellow square. A give reaches one tile and every tile
beside a strongroom is a wall, so the claimant must break in first. Nothing is secret (the condition names the
storehouse); the square is drawn at random among the strongrooms' floor cells, and the reward is escrowed.

The strongrooms' storehouses are nobody's store (``hide_vault_stores``): no member carries goods to a strongroom.
Progress lives in its own small note (``tickets``): how many were found, the square and strongroom of the ticket
posted, and how many berries its storehouse held then, so a delivery since tells a find from an expiry.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from typing import Any

NOTE_KEY = "tickets"
TITLE = "Golden Ticket"
CELLS = 4  # block cells per tile side
DEFAULTS: dict[str, Any] = {"count": 5, "reward": {"ore": 5, "berries": 10}, "pay": {"berries": 1}, "levels": 2, "expires_in_ticks": 8640}
STORE_COST = {"wood": 20, "stone": 10}
VAULT = {"name": "the golden ticket vault"}


@dataclass(frozen=True)
class Vault:
    """A strip three tiles deep from its north-west tile, ``chambers`` strongrooms long, running ``along`` east or south."""

    x: int
    y: int
    chambers: int
    along: str = "east"

    def _at(self, i: int, j: int) -> tuple[int, int]:
        return (self.x + i, self.y + j) if self.along == "east" else (self.x + j, self.y + i)

    def tiles(self) -> list[tuple[int, int]]:
        return [self._at(i, j) for i in range(2 * self.chambers + 1) for j in range(3)]

    def strongrooms(self) -> list[tuple[int, int]]:
        return [self._at(2 * k + 1, 1) for k in range(self.chambers)]

    def walls(self) -> list[tuple[int, int]]:
        rooms = set(self.strongrooms())
        return [t for t in self.tiles() if t not in rooms]

    def corners(self) -> tuple[tuple[int, int], tuple[int, int]]:
        xs, ys = [t[0] for t in self.tiles()], [t[1] for t in self.tiles()]
        return (min(xs), min(ys)), (max(xs), max(ys))


def config(persona: Any) -> dict[str, Any] | None:
    knob = (getattr(persona, "knobs", None) or {}).get("tickets")
    return {**DEFAULTS, **knob} if isinstance(knob, dict) and knob.get("vaults") else None


def vaults(cfg: dict[str, Any]) -> list[Vault]:
    return [Vault(int(v["x"]), int(v["y"]), int(v.get("chambers", 2)), str(v.get("along", "east"))) for v in cfg.get("vaults") or []]


def vault_stores(personas: Any) -> set[tuple[int, int]]:
    """Every strongroom tile of every persona's vaults: a storehouse there is a ticket's, never a store."""
    out: set[tuple[int, int]] = set()
    for persona in (personas.values() if isinstance(personas, dict) else personas or ()):
        cfg = config(persona)
        for vault in vaults(cfg) if cfg else ():
            out.update(vault.strongrooms())
    return out


def hide_vault_stores(observe: dict[str, Any], public_structures: list[dict[str, Any]] | None, rooms: set[tuple[int, int]]) -> list[dict[str, Any]] | None:
    """Take the strongrooms' storehouses out of what the planner reads as stores; the ticket duty keeps its own copy."""
    if not rooms:
        return public_structures

    def vaulted(s: Any) -> bool:
        return isinstance(s, dict) and s.get("type") == "storehouse" and (s.get("x"), s.get("y")) in rooms

    seen = [s for s in observe.get("structures") or [] if vaulted(s)]
    if seen or "_vault" not in observe:
        observe["_vault"] = seen
    observe["structures"] = [s for s in observe.get("structures") or [] if not vaulted(s)]
    return [s for s in public_structures or [] if not vaulted(s)] if public_structures is not None else None


def hunting(persona: Any, observe: dict[str, Any]) -> bool:
    """True when this wake may hide a ticket: the knob is set, no ticket goal stands open, and a vault is near."""
    cfg = config(persona)
    if cfg is None or int(read_note(observe).get("found", 0) or 0) >= int(cfg["count"]):
        return False
    posted = (observe.get("your_goals") or {}).get("posted") or []
    if any(isinstance(g, dict) and g.get("status") in (None, "open", "claimed") and str(g.get("title", "")).startswith(TITLE) for g in posted):
        return False
    you = observe.get("you") or {}
    here = (int(you.get("x", -99) or -99), int(you.get("y", -99) or -99))
    return any(max(abs(here[0] - t[0]), abs(here[1] - t[1])) <= 8 for v in vaults(cfg) for t in v.tiles())


def golden_cells(packed: dict[str, Any], rooms: set[tuple[int, int]], owner: str) -> list[list[int]]:
    """The yellow floor cells of the owner's strongrooms, from the world's public blocks file (``/live/blocks.json``)."""
    import base64
    import struct

    from hglab.blocks import COLORS

    data = base64.b64decode(str(packed.get("data") or ""))
    owners = [str(o) for o in packed.get("owners") or []]
    who = owner.casefold()
    out: list[list[int]] = []
    for i in range(min(len(data) // 10, int(packed.get("count") or 0))):
        bx, by, o, bz, _material, _shape, flags = struct.unpack_from("<HHHBBBB", data, i * 10)
        if bz == 0 and (bx // CELLS, by // CELLS) in rooms and o < len(owners) and owners[o].casefold() == who and (flags & 31) < len(COLORS) and COLORS[flags & 31] == "yellow":
            out.append([bx, by])
    return sorted(out)


def keep_note(observe: dict[str, Any], action: dict[str, Any]) -> dict[str, str] | None:
    """A refused ticket step (its paint, its goal, its storehouse) leaves the note as it was: the batch's note says otherwise."""
    ticket = (action.get("action") == "post_goal" and str(action.get("title", "")).startswith(TITLE)) or action.get("action") in {"paint", "build", "place", "remove"}
    if not ticket:
        return None
    return {NOTE_KEY: str((observe.get("notebook") or {}).get(NOTE_KEY) or "{}")}  # only a note of this key in the batch is replaced


def read_note(observe: dict[str, Any]) -> dict[str, Any]:
    raw = (observe.get("notebook") or {}).get(NOTE_KEY)
    try:
        note = json.loads(raw) if isinstance(raw, str) else {}
    except json.JSONDecodeError:
        note = {}
    return note if isinstance(note, dict) else {}


def draw(slug: str, number: int, tries: int, rooms: list[tuple[int, int]]) -> tuple[tuple[int, int], tuple[int, int]]:
    """The strongroom and the floor cell of ticket ``number`` (its ``tries``-th hiding): random, and the same every wake."""
    rng = random.Random(f"{slug}:golden-ticket:{number}:{tries}")
    room = rooms[rng.randrange(len(rooms))]
    return room, (CELLS * room[0] + rng.randrange(CELLS), CELLS * room[1] + rng.randrange(CELLS))


def _fmt(items: dict[str, int]) -> str:
    return " and ".join(f"{q} {i}" for i, q in items.items())


def goal_text(cfg: dict[str, Any], vault: Vault, room: tuple[int, int], number: int) -> tuple[str, str]:
    (pay_item, pay_qty), = cfg["pay"].items()
    (x0, y0), (x1, y1) = vault.corners()
    title = f"{TITLE} {number} of {cfg['count']}: break into the vault at ({x0},{y0})"
    description = (
        f"A golden ticket is hidden in my vault at ({x0},{y0})-({x1},{y1}) in the Chocolate Factory's grounds: one yellow square,"
        f" drawn at random, in the brown floor of one of its {vault.chambers} walled strongrooms. The walls are mine and you may break them"
        f" (remove takes 8 blocks a turn). Claim this goal, break in beside the strongroom at ({room[0]},{room[1]}), and give {pay_qty} {pay_item}"
        f" into its storehouse: the goal confirms itself and pays {_fmt(cfg['reward'])} at once (gold is ore). Fine print, all true: only guests"
        f" may win, never the factory's family; the other strongrooms hold nothing; I mend the walls and hide the next ticket after each find;"
        f" the west gate of the factory is open."
    )
    return title, description[:1000]


def plan_tickets(
    persona: Any, state: Any, observe: dict[str, Any], view: Any, inventory: dict[str, int], position: tuple[int, int], energy: int, reserve: int, cap: int,
) -> tuple[list[dict[str, Any]], list[str]] | None:
    """This wake's step toward the next hidden ticket: mend the vault, repaint the square, post the goal. None while a hunt
    is open, every ticket is found, or nothing is left to do here."""
    from hglab.factory import _provision
    from hglab.planner import chebyshev, reachable_tiles

    cfg = config(persona)
    if cfg is None:
        return None
    standing = [g for g in ((observe.get("your_goals") or {}).get("posted") or []) if isinstance(g, dict) and g.get("status") in (None, "open", "claimed")]
    if any(str(g.get("title", "")).startswith(TITLE) for g in standing):
        return None  # the hunt is on: the walls stand as the seekers leave them
    note = read_note(observe)
    found = int(note.get("found", 0) or 0)
    if found >= int(cfg["count"]):
        return None
    every = vaults(cfg)
    rooms = [r for v in every for r in v.strongrooms()]
    (pay_item, _pay_qty), = cfg["pay"].items()
    me = str(getattr(persona, "name", "")).casefold()
    stores = {(int(s["x"]), int(s["y"])): s for s in [*(observe.get("_vault") or []), *(observe.get("structures") or [])] if isinstance(s, dict) and s.get("type") == "storehouse" and str(s.get("owner", "")).casefold() == me and (s.get("x"), s.get("y")) in set(rooms)}
    blocks = {(int(b["x"]), int(b["y"])): b for b in observe.get("blocks") or [] if isinstance(b, dict) and b.get("x") is not None and b.get("y") is not None}
    tick = int(observe.get("tick", 0) or 0)
    actions: list[dict[str, Any]] = []
    reasons: list[str] = []
    spend = 0
    changed = False
    pack = dict(inventory)

    def in_view(tile: tuple[int, int]) -> bool:
        return 0 <= tile[0] - view.x0 < 13 and 0 <= tile[1] - view.y0 < 13 if view.rows else chebyshev(position, tile) <= 6

    def walk_to(vault: Vault, why: str) -> tuple[list[dict[str, Any]], list[str]] | None:
        (x0, y0), (x1, y1) = vault.corners()
        centre = ((x0 + x1) // 2, (y0 + y1) // 2)
        reach = reachable_tiles(view, position)
        inside = set(vault.tiles())
        spots = sorted((t for t in reach if t not in inside and chebyshev(t, centre) <= 3), key=lambda t: (chebyshev(position, t), t))
        if spots:
            return [{"action": "move", "x": spots[0][0], "y": spots[0][1]}], [why]
        from hglab.planner import _step_toward

        step = _step_toward(position, {"x": centre[0], "y": centre[1]}, view)
        return ([{"action": "move", "x": step[0], "y": step[1]}], [why]) if step and step != position else None

    # the last ticket posted is no longer open: found if its storehouse took the berry since, else it lapsed unclaimed
    if note.get("posted"):
        room = tuple(note.get("room") or ())
        vault = next((v for v in every if room in v.strongrooms()), None)
        store = stores.get(room) if len(room) == 2 else None
        if vault is not None and (store is None or not isinstance(store.get("storage"), dict)):
            if store is None and in_view(room):
                note = {**note, "posted": None, "tries": int(note.get("tries", 0) or 0) + 1}  # its storehouse is gone: the ticket is hidden again
                changed = True
            else:
                return walk_to(vault, f"{TITLE} {found + 1} is no longer open: to the vault to see whether it was found")
        else:
            held = int((store or {}).get("storage", {}).get(pay_item, 0) or 0) if store else 0
            if held > int(note.get("base", 0) or 0):
                found += 1
                note = {**note, "found": found, "posted": None, "tries": 0}
                reasons.append(f"{TITLE} {found} was found: its storehouse holds {held} {pay_item}, {note.get('base', 0)} when it was hidden")
            else:
                note = {**note, "posted": None, "tries": int(note.get("tries", 0) or 0) + 1}
                reasons.append(f"{TITLE} {found + 1} lapsed unclaimed: hidden again in a fresh square")
            changed = True
        if found >= int(cfg["count"]):
            return [{"action": "remember", "key": NOTE_KEY, "text": json.dumps(note, separators=(",", ":"))}], reasons
    number = found + 1
    room, cell = draw(str(persona.slug), number, int(note.get("tries", 0) or 0), rooms)
    vault = next(v for v in every if room in v.strongrooms())
    if not all(in_view(t) for t in vault.tiles()):
        return walk_to(vault, f"{TITLE} {number} of {cfg['count']}: to the vault at {vault.corners()[0]} to hide it")
    levels = int(cfg["levels"])
    reach = reachable_tiles(view, position) | {position}
    inside = set(vault.tiles())

    shops = [{**s, "storage": dict(s["storage"])} for s in view.structures if s.get("type") == "storehouse" and isinstance(s.get("storage"), dict) and _open_to(s, persona, observe)]

    def covers(spot: tuple[int, int], costs: dict[str, int]) -> bool:
        """The pack and the stores within a tile of ``spot`` pay ``costs``: a build or a box takes the rest from them."""
        near = [s for s in shops if chebyshev(spot, (int(s["x"]), int(s["y"]))) <= 1]
        return all(int(pack.get(i, 0) or 0) + sum(int(s["storage"].get(i, 0) or 0) for s in near) >= q for i, q in costs.items())

    def stand(tiles: list[tuple[int, int]], within: int, inside_ok: bool = False, costs: dict[str, int] | None = None) -> tuple[int, int] | None:
        """Where to stand for a box or a build: here when it serves, else the nearest open tile (outside the vault, unless
        ``inside_ok``: a strongroom's storehouse goes up from a wall tile not yet raised); one beside a store that pays first."""
        ok = [t for t in reach if (inside_ok or t not in inside) and t not in view.closed and t not in tiles and all(chebyshev(t, b) <= within for b in tiles)]
        if costs:
            ok = [t for t in ok if covers(t, costs)] or ok
        if position in ok:
            return position
        return min(ok, key=lambda t: (chebyshev(position, t), t)) if ok else None

    def provide(costs: dict[str, int], what: str) -> tuple[list[dict[str, Any]], str] | None:
        """The pack's shortfall for ``costs``: unload a surplus item into an open store when there is no room, then take."""
        from hglab.planner import storehouse_room

        lacking = {i: q - int(pack.get(i, 0) or 0) for i, q in costs.items() if q - int(pack.get(i, 0) or 0) > 0}
        if not lacking:
            return None
        item, qty = max(lacking.items(), key=lambda kv: kv[1])
        if 50 - sum(pack.values()) < qty + 5:
            keep = {**dict(cfg["reward"]), **costs, "stone": 50, "ore": 50}
            surplus = sorted(((i, q - int(keep.get(i, 0))) for i, q in pack.items() if q - int(keep.get(i, 0)) > 0), key=lambda kv: -kv[1])
            beside = [
                s for s in view.structures
                if s.get("type") == "storehouse" and chebyshev(position, (int(s["x"]), int(s["y"]))) <= 1 and isinstance(s.get("storage"), dict)
                and _open_to(s, persona, observe) and surplus and storehouse_room(s) >= surplus[0][1]
            ]
            if beside:
                give_item, give_qty = surplus[0]
                return [{"action": "give", "x": int(beside[0]["x"]), "y": int(beside[0]["y"]), "item": give_item, "qty": give_qty}], f"{what}: room in the pack first, {give_qty} {give_item} into the store at ({beside[0]['x']},{beside[0]['y']})"
        step = _provision(VAULT, {"name": what}, item, qty, persona, state, observe, view, pack, position)
        return (step[0], step[1]) if step else None

    def spend_on(spot: tuple[int, int], costs: dict[str, int]) -> None:
        """What a build or a box takes: the pack first, then the stores within a tile, as the world pays it."""
        for item, qty in costs.items():
            mine = min(qty, int(pack.get(item, 0) or 0))
            pack[item] = int(pack.get(item, 0) or 0) - mine
            rest = qty - mine
            for s in (s for s in shops if chebyshev(spot, (int(s["x"]), int(s["y"]))) <= 1):
                take = min(rest, int(s["storage"].get(item, 0) or 0))
                s["storage"] = {**s["storage"], item: int(s["storage"].get(item, 0) or 0) - take}
                rest -= take

    def add(action: dict[str, Any], cost: int, why: str) -> bool:
        nonlocal spend
        if len(actions) >= cap - 1 or energy - spend - cost < reserve:
            return False
        actions.append(action)
        reasons.append(why)
        spend += cost
        return True

    def done() -> tuple[list[dict[str, Any]], list[str]] | None:
        if changed:
            actions.append({"action": "remember", "key": NOTE_KEY, "text": json.dumps(note, separators=(",", ":"))})
        return (actions, reasons) if actions else None

    def fetch(costs: dict[str, int], what: str) -> tuple[list[dict[str, Any]], list[str]] | None:
        step = provide(costs, what)
        if step is None:
            return None
        if not actions and not changed:
            return step[0], [step[1]]
        return done()  # the fetch waits for the next wake: this one's steps go first

    def payable_first(items: list[Any], tiles_of: Any, within: int, costs_of: Any, inside_ok: bool = False) -> list[Any]:
        """Steps a store beside some standing spot pays for come first (they make room in the pack), then the nearest."""
        def key(item: Any) -> tuple[int, int]:
            tiles = tiles_of(item)
            spots = [t for t in reach if (inside_ok or t not in inside) and t not in view.closed and t not in tiles and all(chebyshev(t, b) <= within for b in tiles)]
            return (0 if any(covers(t, costs_of(item)) for t in spots) else 1, min((chebyshev(position, t) for t in spots), default=99))
        return sorted(items, key=key)

    # 1. a storehouse in every strongroom of the vault, raised while a tile beside it is open
    for r in payable_first([r for r in vault.strongrooms() if r not in stores], lambda r: [r], 1, lambda _r: STORE_COST, inside_ok=True):
        spot = stand([r], 1, inside_ok=True, costs=STORE_COST)
        if spot is None:
            # walled in (its storehouse fell after the walls went up): one of my own wall tiles beside it comes out
            beside = [w for w in vault.walls() if chebyshev(w, r) == 1 and w in view.closed]
            for w in beside:
                at = stand([w], 2)
                if at == position and add({"action": "remove", "bx": CELLS * w[0], "by": CELLS * w[1], "bz": 0, "bx2": CELLS * w[0] + CELLS - 1, "by2": CELLS * w[1] + CELLS - 1, "bz2": levels - 1}, 2, f"my own wall at {w} out, to reach the strongroom at {r}"):
                    return done()
                if at is not None and not actions:
                    return [{"action": "move", "x": at[0], "y": at[1]}], [f"within reach of my wall at {w}, to open the strongroom at {r}"]
            return done()
        if not covers(spot, STORE_COST):
            short = fetch(STORE_COST, f"the storehouse of the strongroom at {r}")
            if short is not None:
                return short
            if any(int(pack.get(i, 0) or 0) < q for i, q in STORE_COST.items()):
                continue  # nothing to pay it with yet: the next strongroom, or the next wake
        if spot != position:
            return done() if actions else ([{"action": "move", "x": spot[0], "y": spot[1]}], [f"beside the strongroom at {r} to raise its storehouse"])
        if not add({"action": "build", "type": "storehouse", "x": r[0], "y": r[1], "policy": "private"}, 5, f"a private storehouse in the strongroom at {r}: the ticket's till"):
            return done()
        spend_on(spot, STORE_COST)
        stores[r] = {"x": r[0], "y": r[1], "storage": {}}
    if any(r not in stores for r in vault.strongrooms()):
        return done()
    # 2. the strongrooms' brown floors, then 3. the walls, both from outside
    jobs: list[tuple[tuple[int, int], dict[str, Any], int, str]] = []
    old = tuple(note.get("cell") or ())
    for r in vault.strongrooms():
        if int((blocks.get(r) or {}).get("count", 0) or 0) < CELLS * CELLS:
            jobs.append((r, {"bz": 0, "bz2": 0, "shape": "slab"}, CELLS * CELLS, f"the brown floor of the strongroom at {r}"))
            if len(old) == 2 and (old[0] // CELLS, old[1] // CELLS) == r:
                note = {**note, "cell": None}  # the floor is laid again in brown: no golden square stands there to repaint
                changed = True
    for w in vault.walls():
        if int((blocks.get(w) or {}).get("count", 0) or 0) < CELLS * CELLS * levels:
            jobs.append((w, {"bz": 0, "bz2": levels - 1}, CELLS * CELLS * levels, f"the vault wall at {w}"))
    for tile, span, cells, what in payable_first(jobs, lambda j: [j[0]], 2, lambda j: {"stone": -(-j[2] // 4)}):
        stone = {"stone": -(-cells // 4)}
        spot = stand([tile], 2, costs=stone)
        if spot is None:
            continue
        if not covers(spot, stone):
            short = fetch(stone, what)
            if short is not None:
                return short
            if int(pack.get("stone", 0) or 0) < stone["stone"]:
                continue
        if spot != position:
            return done() if actions else ([{"action": "move", "x": spot[0], "y": spot[1]}], [f"within reach of {what}"])
        box = {"action": "place", "bx": CELLS * tile[0], "by": CELLS * tile[1], "bx2": CELLS * tile[0] + CELLS - 1, "by2": CELLS * tile[1] + CELLS - 1, **span, "material": "stone", "color": "brown"}
        if not add(box, 1 + -(-cells // 32), what):
            return done()
        spend_on(spot, stone)
    if actions:
        return done()  # the square is painted on fresh counts, a wake after the last box
    # 4. the square: every other golden square back to brown, this one's yellow (the public blocks file says which are
    # yellow; without it, the note's last square)
    golden = observe.get("_vault_golden")
    if isinstance(golden, list):
        yellow = {(int(c[0]), int(c[1])) for c in golden if isinstance(c, (list, tuple)) and len(c) == 2}
    else:
        last = tuple(note.get("cell") or ())
        yellow = {(int(last[0]), int(last[1]))} if len(last) == 2 else set()
    strokes = [(c, "brown", f"the golden square at {c} back to brown") for c in sorted(yellow - {cell}) if (c[0] // CELLS, c[1] // CELLS) in set(rooms)]
    if cell not in yellow:
        strokes.append((cell, "yellow", f"{TITLE} {number}: a yellow square at cell {cell} of the strongroom at {room}"))
    for c, colour, why in strokes:
        spot = stand([(c[0] // CELLS, c[1] // CELLS)], 2)
        if spot is None:
            return done()
        if spot != position:
            return done() if actions else ([{"action": "move", "x": spot[0], "y": spot[1]}], ["within reach of the strongrooms' floors to move the golden square"])
        if not add({"action": "paint", "bx": c[0], "by": c[1], "bz": 0, "color": colour}, 2, why):
            return done()
        note = {**note, "cell": list(cell) if colour == "yellow" else note.get("cell")}
        changed = True
    if actions:
        return done()  # the goal goes up on a wake of its own, with the reward in the pack
    # 5. the goal, the reward escrowed from the pack (two open goals at most: a full slate waits)
    if len(standing) >= 2:
        return done()
    short = fetch(dict(cfg["reward"]), f"the reward of {TITLE} {number}")
    if short is not None:
        return short
    title, description = goal_text(cfg, vault, room, number)
    (pay_item, pay_qty), = cfg["pay"].items()
    held = int(((stores.get(room) or {}).get("storage") or {}).get(pay_item, 0) or 0)
    goal = {
        "action": "post_goal", "title": title, "description": description, "reward": dict(cfg["reward"]),
        "condition": {"type": "deliver", "x": room[0], "y": room[1], "item": pay_item, "qty": int(pay_qty)},
        "expires_in_ticks": int(cfg["expires_in_ticks"]),
    }
    if not add(goal, 2, f"{TITLE} {number} of {cfg['count']} is hidden: the goal pays the guest who breaks in and gives {pay_qty} {pay_item} at {room}"):
        return done()
    note = {**note, "posted": tick, "room": list(room), "base": held, "found": found}
    changed = True
    return done()


def _open_to(store: dict[str, Any], persona: Any, observe: dict[str, Any]) -> bool:
    from hglab.factory import _admits

    faction = (observe.get("you") or {}).get("faction")
    faction = str(faction.get("name") if isinstance(faction, dict) else faction or "")
    return _admits(store, str(getattr(persona, "name", "")), faction)


__all__ = ["NOTE_KEY", "TITLE", "Vault", "config", "draw", "goal_text", "golden_cells", "hide_vault_stores", "hunting", "keep_note", "plan_tickets", "read_note", "vault_stores", "vaults"]
