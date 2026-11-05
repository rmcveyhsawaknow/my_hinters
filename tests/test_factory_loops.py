"""Five loops that stood the works and the deeds still on 2026-11-05: each walked every wake and nothing rose for hours."""

from pathlib import Path

from hglab import factory, tickets
from hglab.crew import MASON_KEEP, _unload
from hglab.mood import PersonaState
from hglab.persona import load_personas, load_team
from hglab.planner import WorldView, _draw_price
from hglab.quartermaster import plan_quartermaster

ROOT = Path(__file__).parents[1]
GRASS = ["g" * 128] * 128
FACTION = {"id": 5, "name": "Chocolate Factory"}


def _store(x, y, storage, owner="Treacleaxe"):
    store = {"id": x * 1000 + y, "type": "storehouse", "x": x, "y": y, "owner": owner, "policy": "faction", "faction": "Chocolate Factory"}
    if storage is not None:
        store["storage"] = dict(storage)
    return store


def test_a_store_seen_with_too_little_is_not_walked_back_to(tmp_path, monkeypatch):
    """MotherPail found 1-3 stone at the north works depot, walked for the lookout depot, lost sight of the first, took it
    for a full one and walked back: six hours between two stores, no block placed."""
    monkeypatch.setattr(factory, "ledger_path", lambda root, name: tmp_path / f"{name}.json")
    personas = load_personas(ROOT)
    builder = personas["mrs-bucket"]
    team = load_team(ROOT, "chocolate-factory")
    design, steps, _ = factory.blueprint(ROOT, "chocolate-factory")
    target = next(s for s in steps if s["section"] == "lookout" and s["kind"] == "place" and s["item"] == "stone")
    factory.mark_done(ROOT, factory.ledger_name(design, "chocolate-factory"), sorted(s["id"] for s in steps if s["section"] != "lookout" or s["kind"] == "remove"), 1, "test")
    x0, y0, x1, y1 = target["tiles"]
    cx, cy = (x0 + x1) // 2, (y0 + y1) // 2
    assert int(target["items"]) >= 4
    low, far = (cx + 1, cy + 11), (cx, cy - 5)  # both within the sixteen tiles a builder looks for a store
    state = PersonaState(mood="busy")
    observe = {"tick": 70000, "you": {"name": builder.name, "x": cx, "y": cy + 10, "faction": FACTION, "blocks_owned": 0}}
    near_low = WorldView(
        x0=cx - 6, y0=cy + 4, rows=GRASS, full_map=GRASS, tick=70000,
        structures=[_store(*low, {"stone": 2, "fiber": 300})], world_structures=[_store(*low, {"stone": 2, "fiber": 300}), _store(*far, None)],
    )
    first = factory.plan_step(builder, team, state, observe, near_low, {"berries": 5}, (cx, cy + 10), 3, mates={"Treacleaxe"})
    assert first is not None and first[0][0]["action"] == "move" and str(far) in first[1]  # past the store with too little
    assert f"{low[0]},{low[1]}:stone" in state.flags["bp_empty"]  # and it is remembered as such
    away = (cx, cy + 4)  # nearer the low store than the other, and out of sight of both
    view = WorldView(x0=cx - 6, y0=cy - 2, rows=GRASS, full_map=GRASS, tick=70000, structures=[], world_structures=[_store(*low, None), _store(*far, None)])
    again = factory.plan_step(builder, team, state, {**observe, "you": {**observe["you"], "x": away[0], "y": away[1]}}, view, {"berries": 5}, away, 3, mates={"Treacleaxe"})
    assert again is not None and str(far) in again[1] and str(low) not in again[1]  # never back to the store it saw short


def test_a_full_store_hemmed_in_by_blocks_leaves_its_turn_to_the_next():
    """The fullest store stood among the factory's buildings: the quartermaster walked toward a tile of blocks every wake
    for two days, never raised a store there, and never served the next full one."""
    hauler = load_personas(ROOT)["loompa-hauler"]
    hemmed = _store(82, 89, {"stone": 300, "wood": 200}, owner="Toffeetrowel")
    other = _store(92, 88, {"stone": 250, "wood": 230}, owner="Toffeetrowel")
    blocks = [{"x": 82 + dx, "y": 89 + dy, "count": 40, "top": 9, "owner": "Toffeetrowel"} for dx in (-1, 0, 1) for dy in (-1, 0, 1) if (dx, dy) != (0, 0)]
    view = WorldView(x0=76, y0=82, rows=GRASS, full_map=GRASS, structures=[hemmed, other], world_structures=[hemmed, other], tick=1000)
    observe = {"you": {"x": 84, "y": 88, "faction": FACTION}, "tick": 1000, "blocks": blocks}
    step = plan_quartermaster(hauler, PersonaState(mood="busy"), observe, view, {"berries": 5}, (84, 88), 3, [hemmed, other], 1000, mates={"toffeetrowel"})
    assert step is not None and "(92, 88)" in step[1] and "(82, 89)" not in step[1]
    assert all((a["x"], a["y"]) not in {(b["x"], b["y"]) for b in blocks} for a in step[0])
    closed = WorldView(x0=76, y0=82, rows=GRASS, full_map=GRASS, structures=[hemmed], world_structures=[hemmed], tick=1000, closed={(b["x"], b["y"]) for b in blocks})
    assert plan_quartermaster(hauler, PersonaState(mood="busy"), {"you": {"x": 84, "y": 88, "faction": FACTION}, "tick": 1000}, closed, {"berries": 5}, (84, 88), 3, [hemmed], 1000) is None  # closed tiles count too


def test_a_mason_holding_only_the_next_stores_cost_does_not_walk_between_stores():
    """Toffeetrowel held 20 wood, 7 stone, 5 fiber and 15 berries: heavy, yet all of it kept for the next store. Beside each
    store it had nothing to give and walked to the next one, and back, for a day."""
    a, b = _store(89, 94, {"stone": 300}), _store(90, 97, {"wood": 300})
    view = WorldView(x0=84, y0=89, rows=GRASS, full_map=GRASS, structures=[a, b], world_structures=[a, b], tick=1000)
    kept = {"wood": 20, "stone": 7, "fiber": 5, "berries": 15}
    assert _unload(kept, (90, 95), view, [a, b], 3, PersonaState(mood="busy"), 1000, sum(kept.values()), keep=MASON_KEEP) is None
    more = {**kept, "stone": 17}
    step = _unload(more, (90, 95), view, [a, b], 3, PersonaState(mood="busy"), 1000, sum(more.values()), keep=MASON_KEEP)
    assert step is not None and step[0] == [{"action": "give", "x": 89, "y": 94, "item": "stone", "qty": 7}]  # what is spare still goes in


def test_a_lapsed_ticket_seen_from_beyond_the_campus_wall_is_walked_round_to():
    """Ticket 1 lapsed while Fudgewright worked the East Works: every tile beside the vault's middle is a wall, so the route
    found nothing, the greedy step stood him against the campus wall's east face, and a stone trip walked him north again."""
    persona = load_personas(ROOT)["wonka"]
    from test_tickets import World

    world = World(persona)
    assert world.run_until_posted()
    world.goals[0]["status"] = "expired"
    world.at = (100, 83)
    obs = world.observe()
    rooms = set(world.vault.strongrooms())
    for s in obs["structures"]:
        if (s["x"], s["y"]) in rooms:
            s.pop("storage", None)  # its contents do not show from beyond the wall
    obs["_closed_world"] = [[99, y] for y in range(76, 110)] + [list(t) for t in world.vault.tiles()]  # the campus wall's east face, and the vault
    tickets.hide_vault_stores(obs, [], tickets.vault_stores([persona]))
    view = WorldView.from_observe(obs, GRASS)
    plan = tickets.plan_tickets(persona, PersonaState(mood="gentle"), obs, view, dict(obs["you"]["inventory"]), (100, 83), 100, 25, 3)
    assert plan is not None and "no longer open" in plan[1][0]
    move = plan[0][0]
    assert move["action"] == "move" and move["x"] < 99  # round the wall's north end and in, never against its east face


def test_the_last_few_wood_of_a_deed_are_taken_from_the_store_beside():
    """Plumbline owed the last 6 wood of a deed; a draw took 10 or more, so beside each store it took nothing and walked to
    the other one, two tiles away, for twelve hours."""
    plumbline = load_personas(ROOT)["plumbline"]
    store = _store(88, 93, {"wood": 120, "stone": 300}, owner="Toffeetrowel")
    view = WorldView(x0=81, y0=87, rows=GRASS, full_map=GRASS, structures=[store], world_structures=[store], tick=167000)
    bought = {"id": "nyc-park-south", "lot": "D05-NE", "price": 61, "paid": 55, "currency": "wood"}
    draw = _draw_price(plumbline, PersonaState(mood="measuring"), {"stone": 4, "berries": 5}, (87, 93), view, {"you": {"faction": FACTION}}, {"Toffeetrowel", "Plumbline"}, "wood", 6, bought)
    assert draw is not None and draw[0] == [{"action": "take", "x": 88, "y": 93, "item": "wood", "qty": 6}] and draw[2] == "deed_draw"


def test_a_builder_at_the_cap_of_blocks_still_raises_the_designs_structures(tmp_path, monkeypatch):
    """Toffeetrowel stood at the world's cap of blocks for two days, exploring, while the East Works waited on their depots:
    a storehouse or a sign is no block, so a capped builder raises those and never places a block."""
    monkeypatch.setattr(factory, "ledger_path", lambda root, name: tmp_path / f"{name}.json")
    personas = load_personas(ROOT)
    mason = personas["loompa-mason"]
    team = load_team(ROOT, "chocolate-factory")
    design, steps, _ = factory.blueprint(ROOT, "chocolate-factory")
    depot = next(s for s in steps if s["kind"] == "build" and "forest works depot" in s["name"])
    block = next(s for s in steps if s["section"] == "dairy" and s["kind"] == "place")
    led = factory.ledger_name(design, "chocolate-factory")
    factory.mark_done(ROOT, led, sorted(s["id"] for s in steps if s["id"] not in (depot["id"], block["id"])), 1, "test")
    view = WorldView(x0=100, y0=74, rows=GRASS, full_map=GRASS, tick=70000)
    pack = {"wood": 30, "stone": 30, "berries": 5}

    def plan(owned):
        observe = {"tick": 70000, "you": {"name": mason.name, "x": 104, "y": 81, "faction": FACTION, "blocks_owned": owned}}
        return factory.plan_step(mason, team, PersonaState(mood="busy"), observe, view, dict(pack), (104, 81), 3, mates={"Treacleaxe"})

    capped = plan(4090)
    assert capped is not None and all(a["action"] != "place" for a in capped[0]) and "forest works depot" in capped[1]
    assert any(a["action"] == "build" and a["type"] == "storehouse" for a in capped[0]) or capped[0][0]["action"] == "move"
    factory.mark_done(ROOT, led, [depot["id"]], 2, "test")
    assert plan(4090) is None  # only blocks left: nothing a capped builder can raise
    free = plan(0)
    assert free is not None and any(a["action"] == "place" for a in free[0])  # under the cap the block is placed as before
