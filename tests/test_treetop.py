"""The Treetop Hideaway (the owner's instruction of 2026-11-02): Neverland's treehouses, its crew and its builders."""

import json
from pathlib import Path

from hglab import factory
from hglab.crew import pipeline_of, plan_crew
from hglab.mood import PersonaState
from hglab.persona import load_personas, load_team
from hglab.planner import WorldView

ROOT = Path(__file__).parents[1]
FOREST = ["f" * 128] * 128
NAME = "treetop-hideaway"


def _bp():
    return factory.blueprint(ROOT, NAME)


def _store(x, y, storage, owner="Stoutheart"):
    return {"id": 1, "type": "storehouse", "x": x, "y": y, "owner": owner, "policy": "faction", "faction": "Neverland", "storage": dict(storage)}


def test_the_hideaway_keeps_every_rule_and_stands_on_free_forest():
    design, steps, _ = _bp()
    assert design["team"] == "neverland" and factory.ledger_name(design, NAME) == NAME  # version 1 keeps the plain name
    assert factory.check(design, steps) == []  # boxes within reach, supported in order, nothing above the ceiling
    assert all(s["box_cells"] <= factory.PACK_CELLS for s in steps if s["kind"] == "place")  # a pack pays for any step
    sections = {s["id"] for s in design["sections"]}
    assert sections == {"great-tree", "west-tree", "lookout-tree"} and all(s.get("style") == "treehouse" for s in design["sections"])
    trunks = [(int(x), int(y)) for s in design["sections"] for x, y in s["trunks"]]
    rows = (ROOT / "tests/fixtures/world/terrain.txt").read_text(encoding="utf-8").splitlines()
    structures = json.loads((ROOT / "tests/fixtures/world/structures.json").read_text(encoding="utf-8"))
    on_tiles = {(s["x"], s["y"]) for s in (structures.get("structures", structures) if isinstance(structures, dict) else structures)}
    for x, y in trunks:
        assert rows[y][x] == "f" and (x, y) not in on_tiles  # a trunk closes its tile: forest, nothing else there
    for step in steps:
        if step["kind"] != "place":
            continue
        low = step["action"]["bz"] < 6
        assert not low or step["name"].split(": ")[-1].startswith("trunk")  # only the trunks stand below level 6
        if step["section"].startswith("bridge-"):
            assert step["action"]["bz"] >= 6 and step["action"]["material"] == "wood"
    assert factory.materials(steps)["wood"] < 500 and 0 < factory.materials(steps)["fiber"] < 100
    assert not any("foundation" in s["name"] for s in steps)  # a treehouse stands on its trunks, never a plinth


def test_the_team_file_names_the_hideaway_and_its_builders():
    team = load_team(ROOT, "neverland")
    cfg = pipeline_of(team)
    assert cfg["blueprint"] == NAME and factory.team_designs(team) == [NAME]
    assert set(cfg["builders"]) <= set(team.members) and set(cfg["builders"]) == {"tinker-bell", "nibs", "lost-boy", "tootles"}
    assert factory.builder_sections(team, "tinker-bell")[0] == "lookout-tree" and factory.builder_sections(team, "nibs")[0] == "great-tree"


def test_a_neverland_builder_places_a_trunk_from_its_pack_or_the_store_beside_it(tmp_path, monkeypatch):
    monkeypatch.setattr(factory, "ledger_path", lambda root, name: tmp_path / f"{name}.json")
    personas = load_personas(ROOT)
    tink = personas["tinker-bell"]
    team = load_team(ROOT, "neverland")
    observe = {"tick": 142000, "you": {"name": tink.name, "x": 82, "y": 104, "faction": {"id": 9, "name": "Neverland"}, "blocks_owned": 0}}
    view = WorldView(x0=70, y0=96, rows=FOREST, full_map=FOREST, tick=142000)
    step = factory.plan_step(tink, team, PersonaState(mood="busy"), observe, view, {"wood": 12, "berries": 5}, (82, 104), 3, mates={"Stoutheart"})
    assert step is not None and step[2] == "blueprint" and "Treetop Hideaway" in step[1]
    place = step[0][-1]
    assert place["action"] == "place" and place["material"] == "wood" and place["bz"] == 0 and "trunk" in step[1]  # the Lookout Tree's first trunk, from the pack
    store = _store(81, 103, {"wood": 60})
    beside = WorldView(x0=70, y0=96, rows=FOREST, full_map=FOREST, structures=[store], world_structures=[store], tick=142000)
    empty = factory.plan_step(tink, team, PersonaState(mood="busy"), observe, beside, {"berries": 5}, (82, 104), 3, mates={"Stoutheart"})
    assert empty is not None and empty[0][0]["action"] in {"take", "place", "move"}  # the store beside the site pays, or the wood is taken into the pack


def test_strayling_fells_the_forest_for_the_hideaway_when_the_store_is_short():
    personas = load_personas(ROOT)
    stray = personas["lost-boy"]
    team = load_team(ROOT, "neverland")
    assert stray.knobs["crew"] == {"role": "woodcutter"} and personas["tootles"].knobs["crew"] == {"role": "hauler"} and personas["nibs"].knobs["crew"] == {"role": "mason"}
    store = _store(74, 104, {"wood": 20, "fiber": 80})  # short of the 200 wood the stock wants
    nodes = [{"x": 71, "y": 104, "kind": "wood", "amount": 30}, {"x": 76, "y": 104, "kind": "wood", "amount": 30}, {"x": 72, "y": 110, "kind": "fiber", "amount": 12}]
    view = WorldView(x0=60, y0=96, rows=FOREST, full_map=FOREST, structures=[store], world_structures=[store], resources=nodes, tick=142000)
    observe = {"tick": 142000, "you": {"name": stray.name, "x": 73, "y": 103, "faction": {"id": 9, "name": "Neverland"}}}
    names = {p.name: s for s, p in personas.items()}
    step = plan_crew(stray, team, PersonaState(mood="busy"), observe, view, {"berries": 5}, (73, 103), 80, stray.energy_reserve, 3, set(names), names, None)
    assert step is not None and step[2] == "crew"
    kinds = [a["action"] for a in step[0]]
    assert "gather" in kinds or "move" in kinds
    assert all(a.get("kind") == "wood" for a in step[0] if a["action"] == "gather") and "wood" in step[1]
