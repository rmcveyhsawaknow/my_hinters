"""The land office builds the larger New York (the owner's instruction of 2026-11-03): its walls stop, every hand takes
the next Midtown step before unloading or gathering, and the office raises a client's design on its own staked lots
before the deed is paid."""

from pathlib import Path

from hglab import factory
from hglab.crew import plan_crew
from hglab.lots import lot_id
from hglab.mood import PersonaState
from hglab.persona import load_personas, load_team
from hglab.planner import WorldView
from hglab.walls import walls_cfg

ROOT = Path(__file__).resolve().parents[1]
GRASS = ["g" * 128] * 128
OFFICE = ["land-broker", "office-quarrier", "office-feller", "office-reaper", "office-drayman", "office-steward"]


def _step(slug, inventory, position, view=None, room=3, state=None):
    personas = load_personas(ROOT)
    persona, team = personas[slug], load_team(ROOT, "exchange")
    observe = {"you": {"x": position[0], "y": position[1], "faction": {"id": 7, "name": "Land Office"}, "blocks_owned": 0}, "tick": 1000}
    view = view or WorldView(x0=position[0] - 6, y0=position[1] - 6, rows=GRASS, full_map=GRASS, tick=1000)
    return plan_crew(
        persona, team, state or PersonaState(mood="busy"), observe, view, dict(inventory), position, 80, persona.energy_reserve, room,
        {p.name for p in personas.values()}, {p.name: s for s, p in personas.items()}, None,
    )


def test_the_team_file_turns_the_office_to_new_york_and_its_walls_off():
    team = load_team(ROOT, "exchange")
    cfg = team.extra["pipeline"]
    assert factory.team_designs(team) == ["midtown", "central-park", "uptown", "nintendo-land"] and cfg["focus"] == "blueprint"
    assert walls_cfg(cfg["claims"]) is None and cfg["claims"]["walls"]["enabled"] is False  # the walls stop for now; the mechanism stays for when the owner turns it back on
    assert set(cfg["builders"]) == set(OFFICE)  # every hand and the registrar
    midtown = {s["id"] for s in factory.load_design(ROOT, "midtown")["sections"]} | {"streets"}
    assert all(sec in midtown for secs in cfg["builders"].values() for sec in secs)
    exclude = set(cfg["claims"]["exclude"])
    assert {"D03-NW", "E03-SE", "F03-SW", "F02-NE", "G03-SE", "J03-SW"} <= exclude  # Uptown's and Nintendo Land's lots leave the holdings


def test_the_office_raises_a_clients_design_on_its_own_staked_lots_before_the_deed():
    exchange, atelier, factory_team = load_team(ROOT, "exchange"), load_team(ROOT, "atelier"), load_team(ROOT, "chocolate-factory")
    land = factory.load_design(ROOT, "midtown")["land"]
    assert factory.lands_own(exchange, land) and not factory.lands_own(atelier, land) and not factory.lands_own(factory_team, land)
    assert not factory.lands_own(exchange, {**land, "registrar": "Someone"})  # another registrar's lots are not the office's


def test_a_hand_with_stone_takes_a_midtown_step_before_walling_or_unloading():
    here = (36, 61)  # beside St Patrick's first tile (35,60)
    full = {"id": 1, "type": "storehouse", "x": 37, "y": 62, "owner": "LandBroker", "policy": "faction", "faction": "Land Office", "storage": {"stone": 500}}
    view = WorldView(x0=30, y0=55, rows=GRASS, full_map=GRASS, structures=[full], world_structures=[full], tick=1000)
    step = _step("office-quarrier", {"stone": 20, "berries": 5}, here, view)
    assert step is not None and step[2] == "blueprint" and step[1].startswith("the Midtown blueprint") and any(a["action"] == "place" for a in step[0])
    assert all(a.get("type") != "wall" for a in step[0])  # no wall, though the store is full and the pack holds the stone
    heavy = _step("office-feller", {"wood": 40, "berries": 5}, (31, 64), view)  # beside the Plaza Hotel's first tile (30-31,63): a heavy pack of wood lays its wooden step first
    assert heavy is not None and heavy[2] == "blueprint" and any(a["action"] == "place" for a in heavy[0])


def test_every_midtown_lot_is_the_offices_own_so_no_step_waits_on_a_deed():
    design, steps, _ = factory.blueprint(ROOT, "midtown")
    lots = {lot_id(x, y) for s in steps for x in range(s["tiles"][0], s["tiles"][2] + 1) for y in range(s["tiles"][1], s["tiles"][3] + 1)}
    assert lots <= set(design["land"]["lots"])
    personas = load_personas(ROOT)
    broker, team = personas["land-broker"], load_team(ROOT, "exchange")
    here = (36, 61)
    observe = {"you": {"x": here[0], "y": here[1], "faction": {"id": 7, "name": "Land Office"}, "blocks_owned": 0}, "tick": 1000}
    view = WorldView(x0=30, y0=55, rows=GRASS, full_map=GRASS, tick=1000)
    step = factory.plan_step(broker, team, PersonaState(mood="busy"), observe, view, {"stone": 20, "berries": 5}, here, 3, mates={"Lintelstave"})
    assert step is not None and any(a["action"] == "place" for a in step[0])  # the registrar builds too, on ground nobody has deeded yet
    plumbline = personas["plumbline"]
    gated = factory.plan_step(plumbline, load_team(ROOT, "atelier"), PersonaState(mood="busy"), {**observe, "you": {**observe["you"], "faction": {"id": 5, "name": "Chocolate Factory"}}}, view, {"stone": 20, "berries": 5}, here, 3, design_name="midtown")
    assert gated is None  # the Atelier still waits for its deed (land_wanted): the client buys before it builds
