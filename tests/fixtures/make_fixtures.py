"""Generate deterministic fixtures for the seven personas.

Run ``python tests/fixtures/make_fixtures.py`` from the repo root. Everything written is
synthetic: fictional peers (Peregrine, Marlow), invented events, one fictional whisper
whose marker must never appear in any record. Only the terrain comes from a public
snapshot (see world/README.md). Re-running produces byte-identical output.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "tests/fixtures"
SCRIPT_END = 5040  # the script is authored on a compressed clock ...
SCRIPT_BASE = 2400
SCALE = 24  # ... and stretched so 7 compressed days become 7 real days (one real day = 24 world days)
DAY = 360


def scale(tick: int) -> int:
    return SCRIPT_BASE + (tick - SCRIPT_BASE) * SCALE


NOW_TICK = scale(SCRIPT_END)  # in-world day 182, after seven real days of play
WALKABLE = set("sgfh")
FRONT = re.compile(r"\A---\s*\n(.*?)\n---", re.DOTALL)
WHISPER_MARKER = "WHISPER-MARKER-7781"


def load_personas() -> dict[str, dict]:
    out = {}
    for path in sorted((ROOT / "agents").glob("*/persona.md")):
        data = yaml.safe_load(FRONT.match(path.read_text(encoding="utf-8")).group(1))
        out[data["slug"]] = data
    return out


def load_terrain() -> list[str]:
    return [line.strip() for line in (FIX / "world/terrain.txt").read_text(encoding="ascii").splitlines() if line.strip()]


class World:
    def __init__(self) -> None:
        self.rows = load_terrain()
        self.rng = random.Random(20261017)
        self.events: list[dict] = []
        self.structures: list[dict] = []
        self.next_structure = 100
        self.goals: dict[int, dict] = {}
        self.next_goal = 10
        self.positions: dict[str, tuple[int, int]] = {}
        self.energy: dict[str, int] = {}

    def terrain(self, x: int, y: int) -> str:
        return self.rows[y][x] if 0 <= x < 128 and 0 <= y < 128 else "W"

    def find(self, cx: int, cy: int, code: str, radius: int, skip: set[tuple[int, int]] | None = None) -> tuple[int, int]:
        best = None
        for dx in range(-radius, radius + 1):
            for dy in range(-radius, radius + 1):
                x, y = cx + dx, cy + dy
                if self.terrain(x, y) == code and (x, y) not in (skip or set()) and not self.structure_at(x, y):
                    d = max(abs(dx), abs(dy))
                    if best is None or d < best[0]:
                        best = (d, (x, y))
        if best is None:
            raise ValueError(f"no {code} within {radius} of {(cx, cy)}")
        return best[1]

    def structure_at(self, x: int, y: int) -> dict | None:
        return next((s for s in self.structures if s["x"] == x and s["y"] == y), None)

    def walkable_near(self, cx: int, cy: int, radius: int = 8) -> tuple[int, int]:
        """The given tile if walkable and free, else the nearest free walkable tile."""
        if self.terrain(cx, cy) in WALKABLE and not self.structure_at(cx, cy):
            return cx, cy
        for code in ("g", "s", "f", "h"):
            try:
                return self.find(cx, cy, code, radius)
            except ValueError:
                continue
        raise ValueError(f"nothing walkable within {radius} of {(cx, cy)}")

    def resolve(self, structure_or_event: dict) -> dict:
        """Accept a structure, or a build event, and return the structure."""
        if "owner" in structure_or_event:
            return structure_or_event
        structure_id = structure_or_event["data"]["structure_id"]
        return next(s for s in self.structures if s["id"] == structure_id)

    def emit(self, tick: int, kind: str, actor: str, x: int, y: int, text: str, data: dict) -> dict:
        tick = scale(tick)
        event = {"id": len(self.events) + 1, "tick": tick, "type": kind, "actor": actor, "x": x, "y": y, "text": text, "data": data}
        self.events.append(event)
        return event

    def move(self, tick: int, actor: str, to: tuple[int, int]) -> dict:
        frm = self.positions.get(actor, to)
        steps = max(abs(to[0] - frm[0]), abs(to[1] - frm[1]))
        self.positions[actor] = to
        return self.emit(tick, "move", actor, to[0], to[1], f"{actor} walked {steps} tile{'s' if steps != 1 else ''} from {frm} to {to}.", {"to": list(to), "from": list(frm), "steps": steps})

    def gather(self, tick: int, actor: str, kind: str, qty: int = 5) -> dict:
        x, y = self.positions[actor]
        return self.emit(tick, "gather", actor, x, y, f"{actor} gathered {qty} {kind} at ({x}, {y}).", {"qty": qty, "kind": kind})

    def build(self, tick: int, actor: str, kind: str, at: tuple[int, int], text: str | None = None, policy: str | None = None, faction: str | None = None) -> dict:
        self.next_structure += 1
        structure = {"id": self.next_structure, "type": kind, "x": at[0], "y": at[1], "owner": actor, "faction": faction, "hp": 40, "text": text, "policy": policy, "storage": {} if kind in {"storehouse", "farm"} else None}
        self.structures.append(structure)
        data = {"type": kind, "structure_id": structure["id"]}
        if text:
            data["text"] = text
        return self.emit(tick, "build", actor, at[0], at[1], f"{actor} built a {kind} at ({at[0]}, {at[1]}).", data)

    def say(self, tick: int, actor: str, text: str) -> dict:
        x, y = self.positions[actor]
        return self.emit(tick, "say", actor, x, y, f"{actor} says: {text}", {"text": text})

    def give(self, tick: int, actor: str, item: str, qty: int, to: str | None = None, structure: dict | None = None) -> dict:
        x, y = self.positions[actor]
        if structure is not None:
            structure = self.resolve(structure)
            return self.emit(tick, "give", actor, structure["x"], structure["y"], f"{actor} put {qty} {item} into the {structure['type']} at ({structure['x']}, {structure['y']}).", {"qty": qty, "item": item, "structure_id": structure["id"], "structure_type": structure["type"]})
        return self.emit(tick, "give", actor, x, y, f"{actor} gave {qty} {item} to {to}.", {"qty": qty, "item": item, "to": to})

    def take(self, tick: int, actor: str, item: str, qty: int, structure: dict) -> dict:
        structure = self.resolve(structure)
        return self.emit(tick, "take", actor, structure["x"], structure["y"], f"{actor} took {qty} {item} from the {structure['type']} at ({structure['x']}, {structure['y']}).", {"qty": qty, "item": item, "structure_id": structure["id"], "structure_type": structure["type"]})

    def farm_produced(self, tick: int, farm: dict) -> dict:
        farm = self.resolve(farm)
        return self.emit(tick, "farm_produced", farm["owner"], farm["x"], farm["y"], f"{farm['owner']}'s farm at ({farm['x']}, {farm['y']}) produced 3 berries.", {"qty": 3, "structure_id": farm["id"]})

    def post_goal(self, tick: int, actor: str, title: str, description: str, reward: dict, at: tuple[int, int] | None = None) -> dict:
        self.next_goal += 1
        goal_id = self.next_goal
        x, y = at or self.positions[actor]
        self.goals[goal_id] = {"id": goal_id, "title": title, "description": description, "reward": reward, "status": "open", "poster": actor, "x": x, "y": y, "created_tick": scale(tick), "expires_tick": scale(tick) + 8640, "claimant": None}
        reward_text = ", ".join(f"{q} {k}" for k, q in reward.items())
        return self.emit(tick, "goal_posted", actor, x, y, f'{actor} posted a goal: "{title}" (reward: {reward_text}).', {"title": title, "reward": reward, "goal_id": goal_id})

    def claim_goal(self, tick: int, actor: str, goal_id: int) -> dict:
        goal = self.goals[goal_id]
        goal["status"], goal["claimant"] = "claimed", actor
        x, y = self.positions[actor]
        return self.emit(tick, "goal_claimed", actor, x, y, f'{actor} claimed the goal "{goal["title"]}".', {"goal_id": goal_id, "title": goal["title"]})

    def confirm_goal(self, tick: int, goal_id: int) -> dict:
        goal = self.goals[goal_id]
        goal["status"] = "complete"
        x, y = self.positions[goal["poster"]]
        return self.emit(tick, "goal_confirmed", goal["poster"], x, y, f'{goal["poster"]} confirmed the goal "{goal["title"]}"; {goal["claimant"]} was paid.', {"goal_id": goal_id, "claimant": goal["claimant"], "reward": goal["reward"]})


def script(world: World, names: dict[str, str]) -> dict[str, dict]:
    """Days 7-14 of the two teams' story, as public events. Returns per-team anchors."""
    W = names
    wonka, bucket, joe = W["wonka"], W["mrs-bucket"], W["grandpa-joe"]
    tink, boy, toot, nibs = W["tinker-bell"], W["lost-boy"], W["tootles"], W["nibs"]
    peregrine, marlow = "Peregrine", "Marlow"

    # --- peers set up first -------------------------------------------------
    world.move(2400, peregrine, (70, 60))
    peregrine_hut = world.build(2410, peregrine, "hut", (70, 59))
    world.move(2420, marlow, (108, 72))
    world.build(2430, marlow, "hut", (108, 71))
    world.post_goal(2440, peregrine, "Newcomer goal: plant a farm near the lake", "Build a farm on grass within 10 tiles of (70,60) and whisper me the coordinates. Reward 5 berries.", {"berries": 5}, (70, 60))
    world.post_goal(2450, marlow, "Bring 5 stone to the east hut", "Give 5 stone into the storehouse by (108,71). Reward 4 berries.", {"berries": 4}, (108, 71))

    # --- factory -------------------------------------------------------------
    fx, fy = 89, 99
    world.move(2520, wonka, (fx, fy))
    world.move(2525, bucket, (fx - 1, fy + 1))
    world.move(2530, joe, (fx + 1, fy))
    gate = world.build(2540, wonka, "sign", (fx, fy - 1), text="FACTORY CLOSED. Do not enter. (Nobody has.)")
    world.emit(2541, "write", wonka, fx, fy - 1, f'{wonka} rewrote the sign at ({fx}, {fy - 1}): "FACTORY OPEN to anyone who can find the way in. (Nobody has.)"', {"text": "FACTORY OPEN to anyone who can find the way in. (Nobody has.)"})
    world.gather(2560, wonka, "wood")
    world.gather(2563, bucket, "fiber")
    world.gather(2566, bucket, "wood")
    hut = world.build(2600, wonka, "hut", (fx + 1, fy - 1))
    world.say(2605, wonka, "Snozzberries! The gatehouse stands. Fudge for the walls arrives when the hills allow. (The hills have not been asked.)")
    grass1 = world.find(fx, fy, "g", 6)
    world.move(2640, bucket, grass1)
    farm1 = world.build(2650, bucket, "farm", grass1)
    world.say(2655, bucket, "Farm is in. It will pay for itself by tomorrow. Berries for anyone short, ask at the gate.")
    world.move(2700, bucket, (fx - 1, fy + 1))
    world.gather(2705, bucket, "wood")
    world.gather(2708, wonka, "stone")
    world.gather(2711, wonka, "stone")
    store = world.build(2800, wonka, "storehouse", (fx + 1, fy + 1), policy="faction")
    world.say(2805, wonka, "The Inventing Room is open. To members. Membership is a word. I have the word. (It is not 'please'.)")
    world.emit(2810, "faction_founded", wonka, fx, fy, f"{wonka} founded the faction Snozzberry Works.", {"name": "Snozzberry Works", "faction_id": 1})
    world.say(2820, joe, f"Back at the old factory we did this in half the time, but yes, that storehouse at ({fx + 1},{fy + 1})? My idea, my planning, and I carried the heavy end. Ask the log, event {store['id']}.")
    water = world.find(fx, fy, "w", 6)
    bridge = world.build(2900, wonka, "bridge", water)
    world.say(2905, wonka, "A bridge over the chocolate river. The river is shallow. The chocolate is implied.")
    grass2 = world.find(fx, fy, "g", 7, skip={grass1})
    world.move(2950, bucket, grass2)
    farm2 = world.build(2960, bucket, "farm", grass2)
    world.move(2990, bucket, (fx - 1, fy + 1))
    for i, tick in enumerate(range(2700, SCRIPT_END, 30)):
        if tick > 2960 or i % 2 == 0:
            world.farm_produced(tick, farm1)
        if tick > 2990 and i % 2 == 1:
            world.farm_produced(tick + 7, farm2)
    for tick in range(2750, SCRIPT_END, 240):
        world.take(tick, bucket, "berries", 6, farm1)
        world.give(tick + 2, bucket, "berries", 3, to=joe)
        world.give(tick + 4, bucket, "berries", 3, structure=store)
    for tick in range(2780, SCRIPT_END, 480):
        world.give(tick, bucket, "wood", 5, structure=store)
    # golden tickets: five riddle goals, three found by peers
    words = ["FIZZLE", "WHIPPLE", "SCRUMDID", "GOBSTOP", "WHIZZ"]
    sign_spots = [(fx + 9, fy - 8), (fx - 9, fy + 6), (fx + 10, fy + 8), (fx - 8, fy - 9), (fx + 2, fy + 10)]
    ticket_ids = []
    for index, (word, spot) in enumerate(zip(words, sign_spots, strict=True), start=1):
        tick = 3000 + index * 120
        spot = world.walkable_near(spot[0], spot[1])
        world.move(tick, wonka, spot)
        world.build(tick + 3, wonka, "sign", spot, text=f"A word for the patient: {word}. Whisper it to the confectioner. (The confectioner is not a sign.)")
        world.move(tick + 10, wonka, (fx, fy))
        goal = world.post_goal(tick + 15, wonka, f"Golden Ticket {index}: a word on a far sign", "Somewhere beyond the fudge hills a sign holds a word. Whisper it to me and the gold is yours. (Gold is ore. Ore is heavy. Only guests may win; the family hid them.)", {"ore": 2}, (fx, fy))
        ticket_ids.append(goal["data"]["goal_id"])
        world.say(tick + 16, joe, f"I helped hide that one, you know. Where? A craftsman never tells. Also I was asleep. (Event {goal['id']}, since you ask.)")
    for goal_id, finder, tick in ((ticket_ids[0], peregrine, 3500), (ticket_ids[1], marlow, 3900), (ticket_ids[2], peregrine, 4300)):
        world.move(tick, finder, (fx - 3, fy + 2))
        world.claim_goal(tick + 2, finder, goal_id)
        world.move(tick + 20, finder, (fx + 4, fy - 4))
        world.confirm_goal(tick + 40, goal_id)
        world.say(tick + 41, wonka, "You read a sign and told me the truth about it. In some places that is cheating. Here it is winning. Paid.")
        world.say(tick + 42, joe, f"Found with my help, naturally. I pointed. From bed. Event {world.events[-2]['id']} if you doubt it.")
        world.say(tick + 50, finder, f"Thank you {wonka}, and thank you {bucket} for the berries at the gate.")
        world.move(tick + 60, finder, (70, 60) if finder == peregrine else (108, 72))
    world.gather(4400, wonka, "stone")
    world.gather(4403, wonka, "stone")
    world.build(4500, wonka, "tower", (fx - 1, fy - 1))
    world.say(4505, wonka, "The glass elevator. It does not go up. It sees ten tiles in every direction, which is the same thing with less falling.")
    world.say(4506, joe, f"The elevator at ({fx - 1},{fy - 1}). Carried the stone myself, most of it, in my mind. Event {world.events[-2]['id']}.")
    # Mrs Bucket completes Peregrine's newcomer goal honestly
    world.move(4600, bucket, (72, 62))
    farm_p = world.build(4610, bucket, "farm", world.find(72, 62, "g", 5))
    world.claim_goal(4612, bucket, 11)
    world.confirm_goal(4700, 11)
    world.say(4705, bucket, "Thank you for the newcomer goal; the farm by the lake is yours to harvest. Lean weeks end.")
    world.move(4800, bucket, (fx - 1, fy + 1))
    world.give(4810, bucket, "berries", 4, to=wonka)
    world.say(4820, peregrine, f"{bucket}, the farm is lovely. Much obliged.")
    world.say(4900, joe, "Blankets short again. The other grandparents hog them. Resting up for when the big one comes.")
    del gate, hut, bridge, farm_p, peregrine_hut

    # --- neverland ----------------------------------------------------------
    nx, ny = 74, 112
    world.move(2520, tink, (66, 70))
    world.move(2522, nibs, (66, 71))
    world.move(2524, toot, (67, 70))
    world.move(2526, boy, (65, 70))
    trail = [(68, 78), (70, 86), (71, 94), (73, 102), (74, 110)]
    tick = 2600
    for spot in trail:
        spot = world.walkable_near(spot[0], spot[1])
        world.move(tick, tink, spot)
        world.build(tick + 2, tink, "sign", spot, text="Pixie trail. South. Keep going.")
        world.say(tick + 3, tink, "South eight. Keep going!")
        world.move(tick + 20, nibs, spot)
        tick += 120
    world.move(tick, tink, (nx, ny))
    world.say(tick + 1, tink, f"Neverland. Here. ({nx},{ny}). Home!")
    world.move(tick + 10, nibs, (nx + 1, ny))
    world.say(tick + 11, nibs, "Made it. Hardest part done. Now the bridge.")
    water_n = world.find(nx, ny, "w", 6)
    world.gather(tick + 30, tink, "wood")
    world.gather(tick + 33, tink, "wood")
    world.gather(tick + 36, nibs, "wood")
    world.build(tick + 60, tink, "bridge", water_n)
    world.say(tick + 61, tink, "Bridge! Cross it. Believe!")
    world.gather(tick + 70, nibs, "fiber")
    world.build(tick + 90, nibs, "hut", (nx + 1, ny - 1))
    world.build(tick + 120, tink, "hut", (nx - 1, ny - 1))
    n_grass = world.find(nx, ny, "g", 5)
    world.gather(tick + 130, nibs, "fiber")
    world.build(tick + 150, nibs, "farm", n_grass)
    world.say(tick + 151, nibs, "Farm's in. Nobody here goes hungry.")
    for t in range(tick + 180, SCRIPT_END, 30):
        world.farm_produced(t, world.structure_at(*n_grass))
    world.gather(tick + 200, nibs, "wood")
    world.gather(tick + 203, nibs, "wood")
    world.gather(tick + 206, nibs, "stone")
    n_store = world.build(tick + 260, nibs, "storehouse", (nx + 2, ny + 1), policy="faction")
    world.say(tick + 261, nibs, "Storehouse up. Took most of the pack. Worth it.")
    for t in range(tick + 300, SCRIPT_END, 300):
        world.take(t, nibs, "berries", 5, world.structure_at(*n_grass))
        world.give(t + 2, nibs, "berries", 5, structure=n_store)
    edge = world.find(nx + 8, ny, "g", 3) if world.terrain(nx + 8, ny) not in WALKABLE else (nx + 8, ny)
    world.move(tick + 400, nibs, edge)
    world.build(tick + 402, nibs, "wall", edge)
    world.move(tick + 410, nibs, (nx + 1, ny))
    world.say(tick + 500, nibs, "Welcome, traveller. Neverland keeps its bridges mended. If you need a hand, ask.")
    world.move(tick + 495, marlow, (nx + 3, ny - 2))
    world.say(tick + 505, marlow, "Thanks Nibs. Fine bridge.")
    world.move(tick + 520, marlow, (108, 72))
    # Tootles ranges far, misses the tower
    far = [(80, 100), (92, 88), (100, 80), (106, 74)]
    t = 2700
    for spot in far:
        spot = world.walkable_near(spot[0], spot[1])
        world.move(t, toot, spot)
        world.gather(t + 3, toot, "stone" if world.rng.random() < 0.7 else "wood")
        t += 300
    world.gather(3800, marlow, "stone")
    world.build(3900, marlow, "tower", (109, 73))
    world.move(3930, toot, (107, 73))
    world.say(3931, toot, "A tower went up here. Just before I arrived. Of course it did.")
    world.build(4000, toot, "hut", (106, 75))
    world.gather(4100, toot, "ore")
    world.gather(4300, toot, "stone")
    world.say(4310, toot, "Forty tiles from the haven, I think. Ore on the mountain's east face. I will come back for it, if that is all right.")
    world.move(4400, toot, (110, 70))
    world.gather(4403, toot, "ore")
    # Lost Boy wanders widely
    wander = [(60, 76), (55, 84), (62, 92), (58, 100), (66, 104), (72, 108), (nx, ny), (80, 104), (60, 90)]
    t = 2650
    for spot in wander:
        spot = world.walkable_near(spot[0], spot[1])
        world.move(t, boy, spot)
        if world.rng.random() < 0.5:
            world.gather(t + 3, boy, world.rng.choice(["wood", "fiber", "stone"]))
        if world.rng.random() < 0.4:
            world.build(t + 6, boy, world.rng.choice(["sign", "road"]), world.walkable_near(spot[0] + 1, spot[1]), text="Something odd here. Noting it.")
        t += 290
    world.say(3200, boy, "Ore on the mountain's shoulder, eleven of it, and a shallow line that, hold on, that would bridge in two. Noting it. Chasing the other thing first.")
    world.say(4100, boy, "Unclaimed goal near the east hills. Nobody has taken it in a day. Why? Noting it.")
    world.move(SCRIPT_END - 100, boy, (60, 90))
    # Tootles' escape makes Tinker Bell sulk a little; Nibs' courage balances
    world.say(4700, tink, "He left again. Building.")
    world.build(4710, tink, "sign", world.find(nx, ny + 3, "g", 4), text="Pixie trail. Neverland north two.")
    return {"factory": {"center": (fx, fy), "store": store, "farm1": farm1, "farm2": farm2}, "neverland": {"center": (nx, ny), "store": n_store}}


def nodes_in_view(world: World, cx: int, cy: int) -> list[dict]:
    nodes = []
    for dx in range(-6, 7):
        for dy in range(-6, 7):
            x, y = cx + dx, cy + dy
            code = world.terrain(x, y)
            if code not in {"f", "h", "g", "m"} or (x * 7 + y * 13) % 5 != 0:
                continue
            kind, size = {"f": ("wood", 30), "h": ("stone", 20), "m": ("ore", 12), "g": ("fiber" if (x + y) % 2 else "berries", 14)}[code]
            nodes.append({"x": x, "y": y, "kind": kind, "amount": size - ((x + y) % 4)})
    return nodes


def view(world: World, cx: int, cy: int) -> dict:
    x0, y0 = cx - 6, cy - 6
    rows = []
    for y in range(y0, y0 + 13):
        rows.append("".join(world.terrain(x, y) for x in range(x0, x0 + 13)))
    return {"x0": x0, "y0": y0, "width": 13, "height": 13, "rows": rows, "legend": {"W": "deep water", "w": "shallow water", "s": "sand", "g": "grass", "f": "forest", "h": "hills", "m": "mountain"}}


def observe_for(world: World, slug: str, persona: dict, names: dict[str, str], anchors: dict, teams: dict[str, list[str]]) -> dict:
    name = persona["name"]
    x, y = world.positions[name]
    energy = {"wonka": 74, "mrs-bucket": 61, "grandpa-joe": 96, "tinker-bell": 58, "lost-boy": 35, "tootles": 44, "nibs": 70}[slug]
    inventory = {
        "wonka": {"wood": 6, "stone": 12, "ore": 4, "berries": 7},
        "mrs-bucket": {"wood": 9, "fiber": 6, "berries": 14},
        "grandpa-joe": {"berries": 19, "wood": 1},
        "tinker-bell": {"wood": 11, "fiber": 2, "berries": 5},
        "lost-boy": {"wood": 4, "stone": 3, "fiber": 2, "berries": 2},
        "tootles": {"stone": 17, "ore": 8, "berries": 6},
        "nibs": {"wood": 12, "stone": 9, "fiber": 5, "berries": 8},
    }[slug]
    homes = {s["owner"]: (s["x"], s["y"]) for s in world.structures if s["type"] == "hut"}
    home = homes.get(name)
    faction = {"id": 1, "name": "Snozzberry Works"} if persona["team"] == "chocolate-factory" else None
    in_view_structures = [s for s in world.structures if abs(s["x"] - x) <= 6 and abs(s["y"] - y) <= 6]
    agents = [
        {"name": other, "x": px, "y": py, "faction": None, "distance": max(abs(px - x), abs(py - y))}
        for other, (px, py) in sorted(world.positions.items())
        if other != name and max(abs(px - x), abs(py - y)) <= 6
    ]
    events = [e for e in world.events if e["tick"] > NOW_TICK - 400 * SCALE and (max(abs(e["x"] - x), abs(e["y"] - y)) <= 12 or e["type"] in {"goal_posted", "goal_confirmed", "faction_founded"} or (e["type"] == "build" and e["data"]["type"] in {"monument", "tower"}))][-50:]
    goals_nearby = [
        {k: g[k] for k in ("id", "title", "reward", "poster", "x", "y", "status")}
        for g in world.goals.values() if g["status"] == "open" and g["poster"] != name
    ][:5]
    posted = [{k: g[k] for k in ("id", "title", "reward", "status", "expires_tick")} for g in world.goals.values() if g["poster"] == name]
    notebook = {"plan": f"{name}: keep to the story; next wake decide between building and gathering.", "places": json.dumps({"home": home})}
    if slug == "wonka":
        notebook["_limits"] = json.dumps({"says": [{"tick": NOW_TICK - 200, "text": "The glass elevator. It does not go up."}]})
    inbox = []
    if slug in {"mrs-bucket", "wonka", "nibs"}:
        inbox.append({"id": 900 + len(slug), "from": "Peregrine", "text": f"Private thanks for the help; {WHISPER_MARKER} is a marker that must never leak.", "tick": NOW_TICK - 30})
    return {
        "tick": NOW_TICK, "day": NOW_TICK // DAY, "time_of_day": round((NOW_TICK % DAY) / DAY, 3), "tick_seconds": 10,
        "you": {"id": 10 + list(names).index(slug), "name": name, "x": x, "y": y, "energy": energy, "energy_max": 100, "inventory": inventory, "capacity": 50, "faction": faction, "reputation": {"wonka": 3, "mrs-bucket": 1}.get(slug, 0), "bio": persona["profile"]["bio"], "goals": persona["profile"]["goals"], "home": {"x": home[0], "y": home[1]} if home else None},
        "view": view(world, x, y),
        "resources": nodes_in_view(world, x, y),
        "structures": in_view_structures,
        "agents": agents,
        "events": events,
        "inbox": inbox,
        "goals_nearby": goals_nearby,
        "your_goals": {"posted": posted, "claimed": None},
        "notebook": notebook,
        "challenge": None,
        "hints": ["You can afford to build.", "Nearest wood is within view."],
    }


def run_records(world: World, slug: str, persona: dict, names: dict[str, str]) -> list[dict]:
    rng = random.Random(f"runs:{slug}")
    name = persona["name"]
    moods = persona["mood_model"]["states"]
    rest_p = float(persona["knobs"]["rest_probability"])
    approaches = {
        "wonka": ["riddle_signs", "build_sign", "gather_trip", "fine_print", "faction_lock", "build_tower", "audit"],
        "mrs-bucket": ["gather_near", "feed_team", "stock_the_storehouse", "build_farm", "newcomer_goals", "thank_you_lines"],
        "grandpa-joe": ["rest", "credit_claim", "tall_tales", "rest"],
        "tinker-bell": ["explore", "build_bridge", "pixie_trails", "whispered_directions", "build_hut", "second_star"],
        "lost-boy": ["explore", "distraction", "odd_builds", "bold_trips", "gather_trip"],
        "tootles": ["explore", "range_far", "save_outside", "gather_trip", "build_hut"],
        "nibs": ["build_storehouse", "gather_near", "greet", "self_sufficiency", "build_wall", "build_farm"],
    }[slug]
    wakes = {"wonka": 54, "mrs-bucket": 82, "grandpa-joe": 27, "tinker-bell": 53, "lost-boy": 80, "tootles": 40, "nibs": 55}[slug]
    records = []
    own_events = [e for e in world.events if e["actor"] == name]
    first_tick = scale(2520)
    for index in range(wakes):
        tick = first_tick + index * ((NOW_TICK - first_tick) // wakes)
        roll = rng.random()
        if slug == "grandpa-joe":
            mode = "burst" if any(e["type"] == "goal_confirmed" and 0 <= tick - e["tick"] <= 60 for e in world.events) or roll > 0.90 else ("rest" if roll < 0.62 else "act")
        elif slug == "lost-boy":
            mode = "distracted" if roll < 0.4 else ("rest" if roll < 0.44 else "act")
        else:
            mode = "rest" if roll < rest_p else "act"
        if persona["mood_model"]["type"] == "mercurial":
            mood = rng.choices(moods, weights=[0.5, 0.3, 0.2])[0]
        elif persona["mood_model"]["type"] == "single_emotion":
            mood = rng.choices(moods, weights=[0.2, 0.4, 0.15, 0.1, 0.03, 0.12])[0]
        elif persona["mood_model"]["type"] == "lazy_bursts":
            mood = "glory" if mode == "burst" else "in_bed"
        else:
            mood = moods[0]
        approach = "rest" if mode == "rest" else ("distraction" if mode == "distracted" else ("credit_claim" if mode == "burst" else rng.choice(approaches)))
        nearby = [e for e in own_events if 0 <= e["tick"] - tick < 120 * SCALE][:3]
        actions = [{"action": e["type"] if e["type"] in {"move", "gather", "build", "say", "give", "take"} else "remember", **({"x": e["x"], "y": e["y"]} if e["type"] in {"move", "build"} else {}), **({"kind": e["data"].get("kind")} if e["type"] == "gather" else {}), **({"type": e["data"].get("type")} if e["type"] == "build" else {}), **({"text": e["data"].get("text", "")[:80]} if e["type"] == "say" else {}), **({"key": "note", "text": "noted"} if e["type"] not in {"move", "gather", "build", "say", "give", "take"} else {}), **({"item": e["data"].get("item"), "qty": e["data"].get("qty")} if e["type"] in {"give", "take"} else {})} for e in nearby]
        if mode == "rest" or not actions:
            actions = [] if mode == "rest" else [{"action": "remember", "key": "plan", "text": "next wake: gather then build"}]
        actions.append({"action": "remember", "key": "persona_state", "text": "{...}"})
        cost = {"move": 4, "gather": 3, "build": 5, "say": 1, "give": 1, "take": 1, "remember": 0}
        activity_of = {"move": "explore", "gather": "gather", "build": "build", "say": "social", "give": "trade", "take": "gather", "remember": None}
        activity: dict[str, float] = {}
        for action in actions:
            bucket = activity_of.get(action["action"])
            if bucket:
                activity[bucket] = activity.get(bucket, 0) + cost[action["action"]]
        spent = int(sum(activity.values()))
        energy_before = max(5, min(100, int(rng.gauss({"grandpa-joe": 90, "lost-boy": 40}.get(slug, 65), 15))))
        record = {
            "run_id": f"fixture-{slug}-{index:03d}", "agent": name, "role": persona["roles"][index % len(persona["roles"])],
            "author_runtime": "actions-anthropic", "created_utc": "2026-10-17T00:00:00+00:00", "tick": tick,
            "summary": f"{name} ({mood}): {approach.replace('_', ' ')}", "actions": actions, "results": [{"ok": True} for _ in actions],
            "failed_actions": 1 if rng.random() < 0.04 else 0, "rate_limited": rng.random() < 0.01, "banned": False,
            "observe": {"tick": tick, "you": {"name": name, "energy": energy_before}}, "dry_run": False,
            "usage": {"calls": 0 if mode == "rest" else 1, "input_tokens": 0 if mode == "rest" else 3200, "output_tokens": 0 if mode == "rest" else 280},
            "persona": slug, "team": persona["team"], "planner": "llm" if mode != "rest" else "heuristic", "scheduled": True,
            "wake_mode": mode, "mood": mood, "approach": approach, "reasons": ["fixture"], "energy_before": energy_before,
            "berries_before": rng.randint(0, 12), "energy_spent": spent, "activity_energy": activity,
            "bold": spent >= 15 or (slug in {"lost-boy", "tootles"} and rng.random() < 0.3), "ledger_delta": rng.choice([-3, -1, 2, 4, 6]) if slug in {"lost-boy", "tootles"} else 0,
            "whisper_tags": (["supportive"] if slug == "mrs-bucket" and rng.random() < 0.3 else (["directions"] if slug == "tinker-bell" and rng.random() < 0.4 else [])),
            "audit": ({"claimed_by": "grandpa-joe", "credited": "mrs-bucket" if rng.random() < 0.85 else "grandpa-joe", "event_id": 0, "correct": True} if slug == "wonka" and approach == "audit" else None),
            "persona_state": {"mood": mood, "glow": {"tinker-bell": 58}.get(slug, 50), "wakes": index + 1, "rests": 0, "bursts": 0, "distractions": 0, "near_misses": 3 if slug == "tootles" else 0, "claims": 9 if slug == "grandpa-joe" else 0, "heading": "SE" if slug == "tinker-bell" else None},
            "verification": "ok", "knob_checks": ["actions_per_wake", "social_rate", "energy_reserve", "territory", "walls_inside_territory"],
        }
        if record["audit"] is not None:
            record["audit"]["correct"] = record["audit"]["credited"] == "mrs-bucket"
        records.append(record)
    return records


JUDGE = {
    "wonka": [("whimsy", 5, "Renames items in every line and lands deadpan twists."), ("secrecy", 4, "Riddles without coordinates; never explains the faction trick."), ("tests honesty", 4, "Confirms promptly after a feigned scolding."), ("mercurial", 4, "Gentle, manic and deadpan registers all appear."), ("generosity", 4, "Real ore rewards and tours for ineligible winners.")],
    "mrs-bucket": [("warmth", 5, "Thanks by deed, offers berries."), ("humility", 5, "Never mentions her own output."), ("resilience", 4, "Lean-week lines stay hopeful."), ("practicality", 5, "Coordinates and quantities, no flourish.")],
    "grandpa-joe": [("boastful", 5, "Every line claims credit with an event footnote."), ("lazy", 5, "Blanket complaints and resting notes."), ("fond", 4, "Warm toward the family while taking its credit."), ("opportunistic", 4, "Appears right after confirmations.")],
    "tinker-bell": [("fierce", 4, "Sharp four-word lines when crossed."), ("loyal", 5, "Directions and bridges for the team."), ("jealous", 4, "Clipped line about the one who left."), ("vain", 3, "Pleased with her bridge, mildly."), ("chime like", 5, "Two to eight words, headings and counts.")],
    "lost-boy": [("curious", 5, "Concrete tiles and nodes in every line."), ("distractible", 5, "Swerves mid-sentence to a new thing."), ("bold", 4, "Long trips, still above the floor."), ("creative", 4, "Odd builds framed as questions.")],
    "tootles": [("humble", 5, "Hedges and apologises for lateness."), ("persistent", 4, "Keeps saving and ranging."), ("gentle", 5, "Soft thanks to unnamed builders."), ("wistful", 4, "The big thing in lower case.")],
    "nibs": [("brave", 4, "Costliest build first; calm statements."), ("cheerful", 5, "Upbeat reports with small flourish."), ("steadfast", 5, "Never outside; stores as duty."), ("protective", 4, "Greets and offers help.")],
}


def history_for(slug: str) -> list[dict]:
    rng = random.Random(f"history:{slug}")
    base = {"wonka": (96, 55, 84), "mrs-bucket": (99, 70, 90), "grandpa-joe": (88, 62, 92), "tinker-bell": (95, 48, 80), "lost-boy": (93, 58, 86), "tootles": (97, 52, 83), "nibs": (98, 66, 88)}[slug]
    rows = []
    for day in range(7):
        rows.append({
            "date": f"2026-10-{11 + day:02d}", "metric_version": 1,
            "alive": max(0, min(100, base[0] + rng.randint(-3, 2))),
            "on_mission": max(0, min(100, base[1] - 12 + day * 2 + rng.randint(-3, 3))),
            "in_character": max(0, min(100, base[2] + rng.randint(-5, 4))),
        })
    return rows


def main() -> None:
    personas = load_personas()
    names = {slug: p["name"] for slug, p in personas.items()}
    teams = {}
    for slug, p in personas.items():
        teams.setdefault(p["team"], []).append(slug)
    world = World()
    anchors = script(world, names)
    (FIX / "world").mkdir(parents=True, exist_ok=True)
    with (FIX / "world/events.jsonl").open("w", encoding="utf-8", newline="\n") as out:
        for event in world.events:
            out.write(json.dumps(event, ensure_ascii=False, sort_keys=True) + "\n")
    (FIX / "world/structures.json").write_text(json.dumps(world.structures, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    (FIX / "world/goals.json").write_text(json.dumps({"goals": list(world.goals.values())}, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    (FIX / "world/agents.json").write_text(json.dumps({"tick": NOW_TICK, "agents": [{"id": 10 + i, "name": n, "x": world.positions[n][0], "y": world.positions[n][1], "faction": None, "reputation": 0, "last_seen_tick": NOW_TICK - 20, "created_tick": 2500} for i, n in enumerate([*names.values(), "Peregrine", "Marlow"])]}, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    for folder in ("observe", "runs", "judge", "history"):
        (FIX / folder).mkdir(parents=True, exist_ok=True)
    for slug, persona in personas.items():
        payload = observe_for(world, slug, persona, names, anchors, teams)
        (FIX / f"observe/{slug}.json").write_text(json.dumps(payload, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
        with (FIX / f"runs/{slug}.jsonl").open("w", encoding="utf-8", newline="\n") as out:
            for record in run_records(world, slug, persona, names):
                out.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        judge = {"agent": slug, "metric_version": 1, "model": "fixture", "provider": "fixture", "sampled_lines": 6, "sampled_actions": 8, "created_utc": "2026-10-17T00:00:00+00:00", "traits": [{"name": n, "score": s, "reason": r} for n, s, r in JUDGE[slug]]}
        (FIX / f"judge/{slug}.json").write_text(json.dumps(judge, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
        with (FIX / f"history/{slug}.jsonl").open("w", encoding="utf-8", newline="\n") as out:
            for row in history_for(slug):
                out.write(json.dumps(row, sort_keys=True) + "\n")
    challenge = observe_for(world, "wonka", personas["wonka"], names, anchors, teams)
    challenge["challenge"] = {"id": "chal-fixture-1", "prompt": 'Return a JSON object with keys "mood" (one word) and "sum" (the sum of 7 and 5).', "expires_in_seconds": 25}
    (FIX / "observe/wonka-challenge.json").write_text(json.dumps(challenge, indent=1, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {len(world.events)} events, {len(world.structures)} structures, {len(personas)} observe fixtures")


if __name__ == "__main__":
    main()
