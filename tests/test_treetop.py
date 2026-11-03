"""The Treetop Hideaway (the owner's instructions of 2026-11-02 and 2026-11-03): Neverland's treehouses, its crew and its builders."""

import hashlib
import json
from pathlib import Path

from hglab import factory
from hglab.crew import pipeline_of, plan_crew
from hglab.lots import lot_id
from hglab.mood import PersonaState
from hglab.persona import load_personas, load_team
from hglab.planner import WorldView

ROOT = Path(__file__).parents[1]
FOREST = ["f" * 128] * 128
NAME = "treetop-hideaway"
OLD_TREES = {"great-tree", "west-tree", "lookout-tree"}
NEW_TREES = {"story-tree", "watch-tree", "mending-tree", "hollow-oak", "strays-tree", "crows-nest-tree"}  # 2026-11-03: twice what stood
# The 71 steps of 2026-11-02, as `hglab factory show` expanded them before the expansion of 2026-11-03. The ledger names
# them (65 of 71 built by then), so the expansion only adds: none of these may change its id, name or action.
OLD_STEP_IDS = [
    "great-tree:00", "great-tree:01", "great-tree:02", "great-tree:03", "great-tree:04", "great-tree:05", "great-tree:06", "great-tree:07",
    "great-tree:08", "great-tree:09", "great-tree:10", "great-tree:11", "great-tree:12", "great-tree:13", "great-tree:14", "great-tree:15",
    "great-tree:16", "great-tree:17", "great-tree:18", "great-tree:19", "great-tree:20", "great-tree:21",
    "west-tree:00", "west-tree:01", "west-tree:02", "west-tree:03", "west-tree:04", "west-tree:05", "west-tree:06", "west-tree:07",
    "west-tree:08", "west-tree:09", "west-tree:10", "west-tree:11", "west-tree:12", "west-tree:13", "west-tree:14", "west-tree:15",
    "west-tree:16", "west-tree:17", "west-tree:18",
    "lookout-tree:00", "lookout-tree:01", "lookout-tree:02", "lookout-tree:03", "lookout-tree:04", "lookout-tree:05", "lookout-tree:06",
    "lookout-tree:07", "lookout-tree:08", "lookout-tree:09", "lookout-tree:10", "lookout-tree:11", "lookout-tree:12", "lookout-tree:13",
    "lookout-tree:14", "lookout-tree:15", "lookout-tree:16", "lookout-tree:17", "lookout-tree:18", "lookout-tree:19",
    "bridge-west:00", "bridge-west:01", "bridge-west:02", "bridge-west:03", "bridge-west:04",
    "bridge-east:00", "bridge-east:01", "bridge-east:02", "bridge-east:03", "bridge-east:04",
]
# sha256 of json.dumps([[id, name, action], ...] over OLD_STEP_IDS, sort_keys=True, separators=(",", ":")), taken before the edit
OLD_STEPS_SHA256 = "54677340b90f18d7a8b38c5c3f9d883cead34df97745c4595b1d79c65e9de4a3"


def _bp():
    return factory.blueprint(ROOT, NAME)


def _store(x, y, storage, owner="Stoutheart"):
    return {"id": 1, "type": "storehouse", "x": x, "y": y, "owner": owner, "policy": "faction", "faction": "Neverland", "storage": dict(storage)}


def _cell_rect(tiles):
    x0, y0, x1, y1 = (int(v) for v in tiles)
    return 4 * x0, 4 * y0, 4 * x1 + 3, 4 * y1 + 3


def _beside(cell, rect):
    """A cell just outside the rect, face to face with one of its cells (where a bridge meets a railing)."""
    bx, by = cell[0], cell[1]
    x0, y0, x1, y1 = rect
    return (y0 <= by <= y1 and bx in (x0 - 1, x1 + 1)) or (x0 <= bx <= x1 and by in (y0 - 1, y1 + 1))


def test_the_hideaway_keeps_every_rule_and_stands_on_free_forest():
    design, steps, _ = _bp()
    assert design["team"] == "neverland" and factory.ledger_name(design, NAME) == NAME  # version 1 keeps the plain name
    assert factory.check(design, steps) == []  # boxes within reach, supported in order, nothing above the ceiling
    assert all(s["box_cells"] <= factory.PACK_CELLS for s in steps if s["kind"] == "place")  # a pack pays for any step
    sections = {s["id"] for s in design["sections"]}
    assert sections == OLD_TREES | NEW_TREES and all(s.get("style") == "treehouse" for s in design["sections"])
    trunks = [(int(x), int(y)) for s in design["sections"] for x, y in s["trunks"]]
    assert len(trunks) == len(set(trunks)) == 30
    rows = (ROOT / "tests/fixtures/world/terrain.txt").read_text(encoding="utf-8").splitlines()
    structures = json.loads((ROOT / "tests/fixtures/world/structures.json").read_text(encoding="utf-8"))
    on_tiles = {(s["x"], s["y"]) for s in (structures.get("structures", structures) if isinstance(structures, dict) else structures)}
    for x, y in trunks:
        assert rows[y][x] == "f" and (x, y) not in on_tiles  # a trunk closes its tile: forest, nothing else there
        assert not (x % 5 == 2 and y % 5 == 2)  # never on a lot's centre, where the office's claim sign stands
    for step in steps:
        if step["kind"] != "place":
            continue
        low = step["action"]["bz"] < 6
        assert not low or step["name"].split(": ")[-1].startswith("trunk") or "rope ladder" in step["name"]  # only trunks and their ladders stand below level 6
        if step["section"].startswith("bridge-"):
            assert step["action"]["bz"] >= 6 and step["action"]["material"] == "wood"
    need = factory.materials(steps)
    assert set(need) == {"wood", "fiber"} and need["wood"] < 1100 and 0 < need["fiber"] < 250  # wood and thatch from the woods around
    assert not any("foundation" in s["name"] for s in steps)  # a treehouse stands on its trunks, never a plinth


def test_the_hideaway_grows_by_twice_what_stood_with_a_ladder_up_every_trunk():
    """2026-11-03: six more trees beside the three, and rope ladders so the decks read as reachable (walkers have no height)."""
    design, steps, _ = _bp()
    secs = {s["id"]: s for s in design["sections"]}
    old = set(OLD_STEP_IDS)
    assert sum(s["cells"] for s in steps) >= 3 * sum(s["cells"] for s in steps if s["id"] in old)  # 1468 blocks, now 4503
    halls = 0
    for sid, sec in secs.items():
        x0, y0, x1, y1 = sec["tiles"]
        trunks = [(int(x), int(y)) for x, y in sec["trunks"]]
        deck = int(sec.get("deck", 6))
        assert x1 - x0 == y1 - y0 in (2, 3) and len(trunks) in (3, 4) and 6 <= deck and deck + 5 <= factory.TOP_LEVEL
        assert any(y == y0 for _x, y in trunks)  # the first deck strip rests on a trunk
        ladders = [s for s in steps if s["section"] == sid and "rope ladder" in s["name"]]
        assert len(ladders) == len(trunks), sid
        got = {(a["bx"], a["by"], a["bz"], a["bz2"], a["material"], a.get("color")) for a in (s["action"] for s in ladders)}
        assert got == {(4 * x, 4 * y + 1, 0, deck - 1, "thatch", "tan") for x, y in trunks}  # up the trunk's west face, inside its own tile
        if sid in NEW_TREES:
            assert sec["ladders"] is True and sec["sign"]["text"] and len(sec.get("doors") or []) in (1, 2)
            assert (sec["cabin"][2] - sec["cabin"][0], sec["cabin"][3] - sec["cabin"][1]) == (1, 1)  # a cabin of two by two tiles
            halls += x1 - x0 == 3
        else:
            assert "ladders" not in sec and "sign" not in sec  # the old trees' sections stand as they were; their ladders are tubes
    assert halls == 1  # one bigger hall tree among the new
    signs = [s for s in steps if s["kind"] == "build" and s["action"]["type"] == "sign"]
    assert len(signs) == len(NEW_TREES) and all(s["beside"] for s in signs)
    colours = {(secs[s]["cabin_color"], secs[s]["roof_cap"][1], secs[s]["door"][1]) for s in NEW_TREES}
    assert len(colours) == len(NEW_TREES)  # every new tree in its own colours


def test_the_old_steps_keep_their_ids_and_actions():
    """The ledger names the steps of 2026-11-02: the expansion appends, it never renumbers. ``ladders: true`` on an old tree
    would hang each ladder straight after its trunk and shift every later id, so the old trees' ladders are tubes in
    their own sections after their last step, with the very actions ``ladders: true`` would make."""
    design, steps, _ = _bp()
    by = {s["id"]: s for s in steps}
    assert len(OLD_STEP_IDS) == 71 and all(i in by for i in OLD_STEP_IDS)
    blob = json.dumps([[i, by[i]["name"], by[i]["action"]] for i in OLD_STEP_IDS], sort_keys=True, separators=(",", ":"))
    assert hashlib.sha256(blob.encode("utf-8")).hexdigest() == OLD_STEPS_SHA256
    assert by["great-tree:00"]["action"] == {"action": "place", "bx": 293, "by": 417, "bz": 0, "bx2": 294, "by2": 418, "bz2": 5, "material": "wood", "color": "brown"}
    assert by["west-tree:06"]["name"] == "The West Tree: railing" and by["bridge-west:00"]["rests_on"] == ["west-tree:06"]
    for sec in OLD_TREES:
        ids = [s["id"] for s in steps if s["section"] == sec]
        before = [i for i in OLD_STEP_IDS if i.startswith(f"{sec}:")]
        assert ids[: len(before)] == before and all("rope ladder" in by[i]["name"] for i in ids[len(before):])
    alone = factory.expand({**design, "sections": [s for s in design["sections"] if s["id"] in OLD_TREES], "tubes": [t for t in design["tubes"] if t["section"] in ("bridge-west", "bridge-east")]})
    assert [(s["id"], s["action"], s["cells"], s["rests_on"]) for s in alone] == [(i, by[i]["action"], by[i]["cells"], by[i]["rests_on"]) for i in OLD_STEP_IDS]
    with_flag = factory.expand({**design, "sections": [{**s, "ladders": True} if s["id"] == "great-tree" else s for s in design["sections"]], "tubes": []})
    flagged = {s["name"].split(": ")[-1]: s["action"] for s in with_flag if s["section"] == "great-tree" and "rope ladder" in s["name"]}
    tubes = {s["name"].removeprefix("tube ").removesuffix(" (tan) leg 1"): s["action"] for s in steps if s["section"] == "great-tree" and "rope ladder" in s["name"]}
    assert flagged == tubes and len(tubes) == 4  # the same ladders as the flag would hang, so a later move to the flag keeps the ledger


def test_the_rope_bridges_join_the_nine_trees_into_one_hideaway():
    design, steps, _ = _bp()
    rects = {s["id"]: _cell_rect(s["tiles"]) for s in design["sections"]}
    decks = {s["id"]: int(s.get("deck", 6)) for s in design["sections"]}
    names = {s["id"]: s["name"] for s in steps}
    links: dict[str, set[str]] = {sid: set() for sid in rects}
    bridges = [t for t in design["tubes"] if t["section"].startswith("bridge-")]
    assert len(bridges) == 9 and len({t["section"] for t in bridges}) == 9
    for tube in bridges:
        assert tube["material"] == "wood" and tube["color"] == "tan" and int(tube.get("size", 1)) == 1
        ends = []
        for point in (tube["path"][0], tube["path"][-1]):
            trees = [sid for sid, rect in rects.items() if _beside(point, rect)]
            assert len(trees) == 1, (tube["name"], point)
            assert point[2] == decks[trees[0]] + 1  # level with the railing it meets
            ends.append(trees[0])
        a, b = ends
        assert a != b
        links[a].add(b)
        links[b].add(a)
        for _name, action in factory._tube_steps(tube):
            for bx, by, bz in factory._cells_of(action):
                assert bz >= 6  # nobody's way through the woods is barred
                assert not any(r[0] <= bx <= r[2] and r[1] <= by <= r[3] for r in rects.values())  # never through a deck, a cabin or a roof
        legs = [s for s in steps if s["section"] == tube["section"]]
        assert all(s["supported"] for s in legs)
        assert any(names[r].endswith("railing") for r in legs[0]["rests_on"])  # hung from one railing
        assert any(names[r].endswith("railing") for r in legs[-1]["rests_on"])  # and tied to the far one
    seen, todo = set(), ["great-tree"]
    while todo:
        cur = todo.pop()
        if cur not in seen:
            seen.add(cur)
            todo.extend(links[cur] - seen)
    assert seen == set(rects)  # one hideaway: every tree reaches every other over the bridges
    assert all(links[s] for s in NEW_TREES)


def test_the_new_trees_keep_off_the_factory_and_the_riddle_ring():
    design, steps, _ = _bp()
    team = load_team(ROOT, "neverland")
    ring = {(int(s["x"]), int(s["y"])) for s in team.border["signs"]}
    new = [s for s in steps if s["id"] not in set(OLD_STEP_IDS) and not (s["section"] in OLD_TREES and "rope ladder" in s["name"])]
    tiles = {(x, y) for s in new for x in range(s["tiles"][0], s["tiles"][2] + 1) for y in range(s["tiles"][1], s["tiles"][3] + 1)}
    assert not tiles & ring  # no trunk, deck, sign or bridge on a riddle sign
    assert all(not (x >= 78 and y <= 101) for x, y in tiles)  # three tiles and more from the campus wall (x 80, y 99)
    trunks = {(int(x), int(y)) for s in design["sections"] if s["id"] in NEW_TREES for x, y in s["trunks"]}
    on_ring = {(x, y) for x in range(64, 85) for y in (102, 109)} | {(x, y) for x in (64, 84) for y in range(102, 110)}
    assert not trunks & on_ring  # no new trunk closes a tile on the ring's rows or columns
    assert {lot_id(x, y) for x, y in tiles} == {"G10-NW", "G10-NE", "G10-SE", "H09-SW", "H09-SE", "H10-NW", "H10-SW", "H10-SE", "I10-SW"}


def test_the_team_file_names_the_hideaway_and_its_builders():
    team = load_team(ROOT, "neverland")
    cfg = pipeline_of(team)
    assert cfg["blueprint"] == NAME and factory.team_designs(team)[0] == NAME  # the hideaway first; the next designs wait for it
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


def test_the_decks_come_in_one_row_strips_and_a_bridge_waits_for_the_railing_it_hangs_from():
    """2026-11-03: the trunks stood and nothing rose on them. The two-row deck strips (32 wood) were more than a hand's
    pack carries beside its berries, and the rope bridges, their own sections, were tried first and refused as unsupported."""
    design, steps, _ = _bp()
    decks = [s for s in steps if "deck row" in s["name"]]
    assert len(decks) == 29 and all(s["box_cells"] <= factory.TREE_DECK_CELLS and s["items"] <= 16 for s in decks)  # 10 old strips, 19 new
    assert all(s["items"] <= 16 for s in steps if s["kind"] == "place")  # one trip to the woods pays for any step
    for s in steps:
        if s["kind"] == "place" and not any(z == 0 for _, _, z in factory._cells_of(s["action"])):
            assert s["rests_on"], s["id"]  # every step off the ground names what holds it up
    trunks = {s["id"] for s in steps if "trunk" in s["name"]}
    ready = factory.ready_steps(steps, trunks)
    assert {s["name"] for s in ready if s["section"] in OLD_TREES} == {"The Great Tree: deck row 1", "The West Tree: deck row 1", "The Lookout Tree: deck row 1"}
    assert all(s["name"].split(": ")[-1].startswith("rope ladder 1 ") for s in ready if s["section"] in NEW_TREES)  # a new tree's ladder follows its first trunk
    assert not any(s["section"].startswith("bridge-") for s in ready)  # no bridge before its railing
    bridge = next(s for s in steps if s["id"] == "bridge-west:00")
    assert bridge["rests_on"] == ["west-tree:06"] and next(s for s in steps if s["id"] == "west-tree:06")["name"].endswith("railing")
    held_up = trunks | {s["id"] for s in steps if s["section"] == "west-tree"}
    assert "bridge-west:00" in {s["id"] for s in factory.ready_steps(steps, held_up)}
    assert "bridge-west:00" in {s["id"] for s in factory.ready_steps(steps, trunks, skip={"west-tree:06"})}  # planned this wake counts as standing
    assert factory.check(design, steps) == []
