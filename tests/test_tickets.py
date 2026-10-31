"""The golden tickets (owner, 2026-10-31): a yellow square in a walled strongroom, and a goal that pays the guest who breaks in."""

import base64
import json
import struct
from pathlib import Path

from hglab import tickets
from hglab.mood import PersonaState
from hglab.persona import load_personas
from hglab.planner import WorldView

ROOT = Path(__file__).resolve().parents[1]
GRASS = ["g" * 128] * 128
STORE = (92, 88)  # the factory's store beside the vault (a faction store the confectioner may take from)


class World:
    """Just enough world for the ticket duty: blocks per tile, storehouses, golden cells, goals, one walker."""

    def __init__(self, persona, at=(91, 86)):
        self.persona = persona
        self.cfg = tickets.config(persona)
        self.vault = tickets.vaults(self.cfg)[0]
        self.at = at
        self.pack = {"wood": 27, "fiber": 5, "berries": 15}
        self.blocks: dict[tuple[int, int], int] = {}
        self.stores = {STORE: {"type": "storehouse", "x": STORE[0], "y": STORE[1], "owner": "Toffeetrowel", "policy": "faction", "faction": "Chocolate Factory", "storage": {"stone": 200, "wood": 80, "ore": 30, "berries": 100, "fiber": 90}}}  # full, as the factory's stores are
        self.golden: set[tuple[int, int]] = set()
        self.goals: list[dict] = []
        self.note = None
        self.tick = 120000

    def observe(self):
        x, y = self.at
        walls = set(self.vault.walls())
        obs = {
            "tick": self.tick,
            "you": {"name": self.persona.name, "x": x, "y": y, "energy": 100, "inventory": dict(self.pack), "faction": {"id": 5, "name": "Chocolate Factory"}},
            "view": {"x0": x - 6, "y0": y - 6, "rows": ["g" * 13] * 13},
            "structures": [dict(s) for s in self.stores.values()],
            "blocks": [{"x": t[0], "y": t[1], "count": n, "closed": t in walls and n > 0} for t, n in self.blocks.items() if n],
            "your_goals": {"posted": [g for g in self.goals if g["status"] == "open"], "claimed": None},
            "notebook": {tickets.NOTE_KEY: self.note} if self.note else {},
            "_vault_golden": [list(c) for c in sorted(self.golden)],
        }
        return obs

    def wake(self):
        obs = self.observe()
        tickets.hide_vault_stores(obs, [], tickets.vault_stores([self.persona]))
        view = WorldView.from_observe(obs, GRASS)
        you = obs["you"]
        plan = tickets.plan_tickets(self.persona, PersonaState(mood="gentle"), obs, view, dict(you["inventory"]), (you["x"], you["y"]), 100, 25, 3)
        for action in (plan or ([], []))[0]:
            self.apply(action)
        self.tick += 30
        return plan

    def pay(self, costs):
        """The pack first, then the stores within a tile that admit the walker, as the world pays a build or a box."""
        for item, qty in costs.items():
            mine = min(qty, self.pack.get(item, 0))
            self.pack[item] = self.pack.get(item, 0) - mine
            rest = qty - mine
            for (sx, sy), store in self.stores.items():
                if rest and max(abs(sx - self.at[0]), abs(sy - self.at[1])) <= 1 and (store["owner"] == self.persona.name or store.get("policy") == "faction"):
                    take = min(rest, store["storage"].get(item, 0))
                    store["storage"][item] -= take
                    rest -= take
            assert rest == 0, f"short of {rest} {item} at {self.at}"

    def apply(self, a):
        kind = a["action"]
        if kind == "move":
            assert (a["x"], a["y"]) not in set(self.vault.walls()) or not self.blocks.get((a["x"], a["y"]))
            self.at = (a["x"], a["y"])
        elif kind == "take":
            store = self.stores[(a["x"], a["y"])]
            assert store["storage"][a["item"]] >= a["qty"] and max(abs(a["x"] - self.at[0]), abs(a["y"] - self.at[1])) <= 1
            store["storage"][a["item"]] -= a["qty"]
            self.pack[a["item"]] = self.pack.get(a["item"], 0) + a["qty"]
            assert sum(self.pack.values()) <= 50
        elif kind == "give":
            self.pack[a["item"]] -= a["qty"]
            store = self.stores[(a["x"], a["y"])]
            assert sum(store["storage"].values()) + a["qty"] <= 500
            store["storage"][a["item"]] = store["storage"].get(a["item"], 0) + a["qty"]
        elif kind == "build":
            assert a["type"] == "storehouse" and a["policy"] == "private" and max(abs(a["x"] - self.at[0]), abs(a["y"] - self.at[1])) <= 1
            self.pay(tickets.STORE_COST)
            self.stores[(a["x"], a["y"])] = {"type": "storehouse", "x": a["x"], "y": a["y"], "owner": self.persona.name, "policy": "private", "storage": {}}
        elif kind == "place":
            tile = (a["bx"] // 4, a["by"] // 4)
            assert max(abs(tile[0] - self.at[0]), abs(tile[1] - self.at[1])) <= 2 and tile not in {self.at}
            cells = (a["bx2"] - a["bx"] + 1) * (a["by2"] - a["by"] + 1) * (a["bz2"] - a["bz"] + 1)
            assert cells <= 256 and a["color"] == "brown"
            self.pay({"stone": -(-cells // 4)})
            self.blocks[tile] = cells
        elif kind == "paint":
            cell = (a["bx"], a["by"])
            assert max(abs(cell[0] // 4 - self.at[0]), abs(cell[1] // 4 - self.at[1])) <= 2
            (self.golden.add if a["color"] == "yellow" else self.golden.discard)(cell)
        elif kind == "remove":
            self.blocks[(a["bx"] // 4, a["by"] // 4)] = 0
        elif kind == "post_goal":
            for item, qty in a["reward"].items():
                self.pack[item] -= qty
                assert self.pack[item] >= 0
            self.goals.append({"id": len(self.goals) + 1, "title": a["title"], "status": "open", "condition": a["condition"], "reward": a["reward"]})
        elif kind == "remember":
            assert a["key"] == tickets.NOTE_KEY
            self.note = a["text"]
        else:
            raise AssertionError(f"unexpected action {a}")

    def run_until_posted(self, wakes=60):
        for _ in range(wakes):
            if any(g["status"] == "open" for g in self.goals):
                return True
            self.wake()
        return any(g["status"] == "open" for g in self.goals)


def _wonka():
    return load_personas(ROOT)["wonka"]


def test_the_vault_is_a_strip_of_walled_strongrooms_every_tile_reachable_from_outside():
    vault = tickets.vaults(tickets.config(_wonka()))[0]
    assert vault.strongrooms() == [(94, 85), (94, 87)] and len(vault.walls()) == 13
    assert vault.corners() == ((93, 84), (95, 88))
    for room in vault.strongrooms():
        around = {(room[0] + dx, room[1] + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)} - {room}
        assert around <= set(vault.walls())  # a give or a build beside it needs a wall down first
    outside = {(x, y) for x in range(91, 98) for y in range(82, 91)} - set(vault.tiles())
    assert all(any(max(abs(t[0] - o[0]), abs(t[1] - o[1])) <= 2 for o in outside) for t in vault.tiles())  # raised, mended and broken from outside


def test_the_confectioner_raises_the_vault_hides_a_ticket_and_posts_its_goal():
    world = World(_wonka())
    assert world.run_until_posted()
    vault = world.vault
    assert all(r in world.stores for r in vault.strongrooms())
    assert all(world.blocks.get(w) == 32 for w in vault.walls()) and all(world.blocks.get(r) == 16 for r in vault.strongrooms())
    assert len(world.golden) == 1
    (cell,) = world.golden
    goal = world.goals[0]
    room = (goal["condition"]["x"], goal["condition"]["y"])
    assert (cell[0] // 4, cell[1] // 4) == room and room in vault.strongrooms()
    assert goal["title"].startswith("Golden Ticket 1 of 5") and goal["condition"] == {"type": "deliver", "x": room[0], "y": room[1], "item": "berries", "qty": 1}
    assert goal["reward"] == {"ore": 5, "berries": 10}
    note = json.loads(world.note)
    assert note["posted"] and note["room"] == list(room) and note["base"] == 0 and note["found"] == 0
    assert world.wake() is None  # the hunt is on: nothing more to do


def test_a_find_moves_the_square_mends_the_walls_and_hides_the_next_ticket():
    world = World(_wonka())
    assert world.run_until_posted()
    goal = world.goals[0]
    room = (goal["condition"]["x"], goal["condition"]["y"])
    breach = next(w for w in world.vault.walls() if max(abs(w[0] - room[0]), abs(w[1] - room[1])) == 1)
    world.blocks[breach] = 0  # a guest broke in beside the strongroom
    world.stores[room]["storage"]["berries"] = 1  # and gave the berry: the goal confirmed itself
    goal["status"] = "done"
    assert world.run_until_posted()
    second = world.goals[-1]
    assert second["title"].startswith("Golden Ticket 2 of 5")
    assert world.blocks[breach] == 32  # mended before the next hunt
    (cell,) = world.golden  # one golden square: the found one is brown again
    assert (cell[0] // 4, cell[1] // 4) == (second["condition"]["x"], second["condition"]["y"])
    assert cell == tickets.draw("wonka", 2, 0, world.vault.strongrooms())[1]  # drawn at random, the same every wake
    note = json.loads(world.note)
    assert note["found"] == 1 and note["base"] == world.stores[(second["condition"]["x"], second["condition"]["y"])]["storage"].get("berries", 0)


def test_a_ticket_that_lapses_unclaimed_is_hidden_again_under_the_same_number():
    world = World(_wonka())
    assert world.run_until_posted()
    world.goals[0]["status"] = "expired"
    assert world.run_until_posted()
    assert world.goals[-1]["title"].startswith("Golden Ticket 1 of 5")
    assert json.loads(world.note)["tries"] == 1 and len(world.golden) == 1


def test_the_strongrooms_storehouses_are_nobodys_store():
    rooms = tickets.vault_stores(load_personas(ROOT))
    assert rooms == {(94, 85), (94, 87)}
    vaulted = {"type": "storehouse", "x": 94, "y": 85, "owner": "Fudgewright", "storage": {"berries": 2}}
    store = {"type": "storehouse", "x": 92, "y": 88, "owner": "Toffeetrowel"}
    obs = {"structures": [vaulted, store]}
    public = tickets.hide_vault_stores(obs, [dict(vaulted), dict(store)], rooms)
    assert obs["structures"] == [store] and public == [store] and obs["_vault"] == [vaulted]


def test_the_golden_square_is_read_from_the_public_blocks_file():
    from hglab.blocks import COLORS

    def block(bx, by, bz, owner, colour):
        return struct.pack("<HHHBBBB", bx, by, owner, bz, 1, 1, COLORS.index(colour))

    rows = [block(377, 341, 0, 0, "yellow"), block(378, 341, 0, 0, "brown"), block(377, 349, 0, 1, "yellow"), block(372, 336, 0, 0, "yellow")]
    packed = {"owners": ["Fudgewright", "Mara"], "count": len(rows), "data": base64.b64encode(b"".join(rows)).decode()}
    assert tickets.golden_cells(packed, {(94, 85), (94, 87)}, "Fudgewright") == [[377, 341]]  # mine, on a strongroom floor, yellow


def test_a_ticket_found_by_its_condition_counts_for_the_pulse():
    from hglab.measures import MeasureContext, goals_confirmed_for_peers
    from hglab.persona import load_team

    personas = load_personas(ROOT)
    done = {"id": 9, "type": "goal_done", "tick": 120400, "actor": "Mara", "data": {"goal_id": 31, "title": "Golden Ticket 1 of 5: break into the vault at (93,84)", "claimant": "Mara", "poster": "Fudgewright"}}
    ctx = MeasureContext(personas["wonka"], load_team(ROOT, "chocolate-factory"), personas, [done, dict(done, id=10)], [], 120500)
    assert goals_confirmed_for_peers(ctx, {"title_contains": "Golden Ticket"}) == 1.0  # the claimant acted; the poster is in the data; once
