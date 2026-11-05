"""The signposts and Halloween at Winter River (the owner's brief of 2026-11-05): once Nintendo Land is complete a sign
beside every landmark no design labels, and once every design stands a Halloween town after the film's model of
Winter River, with the ghost in the striped suit at its heart."""

from pathlib import Path

import pytest

from hglab import factory
from hglab.blocks import _box_cells
from hglab.lots import lot_anchor, lot_id
from hglab.mood import PersonaState
from hglab.persona import load_personas, load_team, load_teams
from hglab.planner import WorldView

ROOT = Path(__file__).resolve().parents[1]
NAME = "halloween"
LOTS = {"J02-SE", "J03-NE", "J03-SE", "J04-NE", "J04-SE", "J05-NE", "K02-SW", "K03-NW", "K03-NE", "K03-SW", "K03-SE", "K04-NW", "K04-NE", "K04-SW", "K04-SE", "K05-NW", "K05-NE", "L03-SW", "L04-NW", "L04-SW", "L05-NW"}
CENTRES = {lot_anchor(lid) for lid in LOTS}  # the office's claim signs
OTHERS = ["chocolate-factory", "lower-manhattan", "midtown", "central-park", "uptown", "treetop-hideaway", "nintendo-land", "signposts"]
GRASS = ["g" * 128] * 128
FACTION = {"id": 5, "name": "Chocolate Factory"}


def _bp(name=NAME):
    return factory.blueprint(ROOT, name)


def _world():
    """The site as the public world showed it at tick 170600: the fixture terrain, the claim signs, LandBroker's roads and
    sign, and the cache the river goes round."""
    rows = (ROOT / "tests/fixtures/world/terrain.txt").read_text(encoding="utf-8").splitlines()
    structures = [{"x": x, "y": y, "type": "sign"} for x, y in CENTRES] + [{"x": 98, "y": 26, "type": "sign"}]
    structures += [{"x": 102, "y": 31, "type": "road"}, {"x": 106, "y": 32, "type": "road"}, {"x": 102, "y": 48, "type": "cache"}]
    return {"terrain": "".join(rows), "width": 128, "height": 128, "structures": structures, "resources": []}


def _low_tiles(steps):
    """Tiles a block below level 6 closes: everything but the slabs on the ground."""
    out = set()
    for s in steps:
        if s["kind"] != "place":
            continue
        a = s["action"]
        if a.get("shape") == "slab" and int(a["bz"]) == 0 and int(a.get("bz2", 0)) == 0:
            continue
        out |= {(x // 4, y // 4) for x, y, z in _box_cells(a) if z < 6}
    return out


def test_halloween_keeps_every_rule_and_a_pack_pays_for_any_step():
    design, steps, _ = _bp()
    assert design["team"] == "commons" and design["commute"] is True and "land" not in design  # the collective's ground by contract
    assert design["after"] == OTHERS  # once all the building is complete and every sign made
    assert factory.check(design, steps) == [] and factory.check(design, steps, _world()) == []
    places = [s for s in steps if s["kind"] == "place"]
    assert all(s["box_cells"] <= factory.PACK_CELLS and s["items"] <= factory.PACK_LIMIT for s in places)
    info = factory.summary(design, steps)
    assert 6000 <= info["blocks"] <= 8000 and info["materials"].get("ore", 0) == 0  # within the room left under the cap; no metal
    assert {lid for s in steps for lid in factory.step_lots(s)} <= LOTS
    assert not _low_tiles(steps) & CENTRES  # the river and Village Street pass over the claim signs as slabs, nothing else touches them


def test_the_model_town_its_ghost_and_its_creepy_things():
    design, steps, _ = _bp()
    sections = {s["id"]: s for s in design["sections"]}
    town = {"maitland-house", "covered-bridge", "church", "hardware", "library", "library-lions", "school", "fire-house", "barber", "town-green"}
    afterlife = {"graveyard", "crypt", "striped-ghost", "handbook", "waiting-room", "sandworm"}
    creepy = {"haunted-woods", "pumpkin-patch", "great-jack", "dark-house", "lantern-house"}
    assert set(sections) == town | afterlife | creepy
    tops = {sid: v["top"] for sid, v in factory.summary(design, steps)["sections"].items()}
    assert tops["striped-ghost"] == factory.TOP_LEVEL == max(tops.values())  # the main character stands tallest
    ghost = [s for s in steps if s["section"] == "striped-ghost" and "suit stripe" in s["name"]]
    assert {s["action"]["color"] for s in ghost} == {"black", "white"} and len(ghost) == 6  # the striped suit
    house = sections["maitland-house"]
    assert house["foundation_block"] == ["stone", "green"] and max(max(r) for r in house["foundation"]) == 3  # the house on its hill
    spider = [s for s in steps if s["section"] == "maitland-house" and s["name"].startswith("The Maitland House: spider")]
    roof = [s for s in steps if s["section"] == "maitland-house" and "roof" in s["name"] and "spider" not in s["name"]]
    assert spider and min(s["action"]["bz"] for s in spider) >= max(s["action"]["bz"] for s in roof) - 1  # the opening's spider on the roof
    worm = [s for s in steps if s["section"] == "sandworm" and "sandworm" in s["name"]]
    assert {s["action"]["color"] for s in worm} >= {"black", "white"} and max(s["top"] for s in worm) >= 12  # striped, rearing up
    river = [s for s in steps if s["section"] == "river-winter"]
    assert river and all(s["action"]["shape"] == "slab" and s["action"]["bz"] == 0 and s["action"]["color"] == "blue" for s in river)


def test_every_halloween_section_has_a_sign_beside_it_on_a_free_tile():
    design, steps, _ = _bp()
    signs = {s["section"]: s for s in steps if s["kind"] == "build"}
    assert set(signs) == {s["id"] for s in design["sections"]}
    low = _low_tiles(steps)
    spots = [(s["action"]["x"], s["action"]["y"]) for s in signs.values()]
    assert len(set(spots)) == len(spots)
    for section in design["sections"]:
        sign = signs[section["id"]]
        assert sign["beside"] and 3 <= len(sign["action"]["text"]) <= 200 and sign["costs"] == {"wood": 1}
        assert (sign["action"]["x"], sign["action"]["y"]) not in CENTRES | low and lot_id(sign["action"]["x"], sign["action"]["y"]) in LOTS


def test_a_sculpture_draws_its_boxes_and_a_section_may_colour_its_own_plinth():
    piece = {"id": "imp", "tiles": [10, 10, 10, 10], "style": "sculpture", "foundation": [[2]], "foundation_block": ["stone", "green"],
             "boxes": [{"name": "body", "cells": [1, 1, 0, 2, 2, 1], "block": ["stone", "black"]}, {"name": "hat", "cells": [1, 1, 2, 1, 1, 2], "block": ["wood", "orange"], "shape": "slope", "facing": "south"}]}
    steps = factory.expand({"sections": [piece]})
    plinth, body, hat = steps
    assert plinth["action"]["color"] == "green" and plinth["action"]["bz2"] == 1  # two levels of green under the figure
    assert (body["action"]["bx"], body["action"]["by"], body["action"]["bz"], body["action"]["bx2"], body["action"]["bz2"]) == (41, 41, 2, 42, 3)  # lifted onto it
    assert hat["action"]["shape"] == "slope" and hat["action"]["facing"] == "south" and hat["supported"]
    with pytest.raises(ValueError):
        factory.expand({"sections": [{**piece, "boxes": [{"cells": [0, 0, 0, 4, 0, 0]}]}]})  # a piece outside its tiles


def test_the_signposts_label_every_landmark_no_design_does():
    design, steps, _ = _bp("signposts")
    assert design["after"] == ["nintendo-land"] and design["team"] == "commons" and design["commute"] is True
    assert factory.check(design, steps) == [] and all(s["kind"] == "build" and s["action"]["type"] == "sign" for s in steps)  # signs, no blocks
    ids = {s["id"] for s in design["sections"]}
    assert {"great-tree", "west-tree", "lookout-tree"} <= ids  # the hideaway's oldest trees, the only design buildings without one
    assert {"hut-fudgewright", "hut-plumbline", "house-toffeetrowel", "west-gate", "ticket-vault"} <= ids
    hideaway, _hsteps, _ = _bp("treetop-hideaway")
    signed = {s["id"] for s in hideaway["sections"] if s.get("sign")}
    assert {s["id"] for s in hideaway["sections"]} - signed == {"great-tree", "west-tree", "lookout-tree"}
    others = set()
    for name in OTHERS[:-1]:
        _d, other_steps, _i = _bp(name)
        others |= {(x, y) for s in other_steps for x in range(s["tiles"][0], s["tiles"][2] + 1) for y in range(s["tiles"][1], s["tiles"][3] + 1)}
    for s in steps:
        assert s["beside"] and (s["action"]["x"], s["action"]["y"]) not in others and len(s["action"]["text"]) <= 200, s["id"]


def test_every_chain_ends_with_the_signposts_and_halloween_and_the_lots_leave_the_office():
    for slug in ("chocolate-factory", "exchange", "neverland", "atelier"):
        assert factory.team_designs(load_team(ROOT, slug))[-3:] == ["nintendo-land", "signposts", "halloween"], slug
    exclude = set(load_team(ROOT, "exchange").extra["pipeline"]["claims"]["exclude"])
    assert LOTS <= exclude  # never worked, walled or policed by the office


def test_halloween_waits_for_every_design_and_the_signposts_for_nintendo_land():
    _design, steps, _ = _bp("nintendo-land")
    assert not factory.design_open(ROOT, "signposts") and not factory.design_open(ROOT, NAME)
    factory.mark_done(ROOT, "nintendo-land", [s["id"] for s in steps], 1, "test")
    assert factory.design_open(ROOT, "signposts") and not factory.design_open(ROOT, NAME)  # the factory and the rest still stand open
    for name in OTHERS[:-1]:
        design, other, _ = _bp(name)
        factory.mark_done(ROOT, factory.ledger_name(design, name), [s["id"] for s in other], 1, "test")
    assert not factory.design_open(ROOT, NAME)  # and the signs
    _sd, signs, _ = _bp("signposts")
    factory.mark_done(ROOT, "signposts", [s["id"] for s in signs], 1, "test")
    assert factory.design_open(ROOT, NAME)


def test_neverland_reaches_the_signposts_after_nintendo_land_but_not_halloween_before_the_factory():
    personas, teams = load_personas(ROOT), load_teams(ROOT)
    mason = personas["nibs"]
    team = teams["neverland"]
    for name in ("treetop-hideaway", "nintendo-land"):
        design, steps, _ = _bp(name)
        factory.mark_done(ROOT, factory.ledger_name(design, name), [s["id"] for s in steps], 1, "test")
    _sd, signs, _ = _bp("signposts")
    first = next(s for s in signs if s["section"] == "great-tree")
    view = WorldView(x0=70, y0=100, rows=GRASS, full_map=GRASS, tick=1000)
    observe = {"tick": 1000, "you": {"name": mason.name, "x": 76, "y": 105, "faction": {"id": 9, "name": "Neverland"}, "blocks_owned": 0}}
    step = factory.plan_step(mason, team, PersonaState(mood="busy"), observe, view, {"wood": 3, "berries": 5}, (76, 105), 3)
    assert step is not None and step[0] == [first["action"]] and step[1].startswith("the Signposts blueprint")  # the sign beside the Great Tree
    factory.mark_done(ROOT, "signposts", [s["id"] for s in signs], 2, "test")
    assert factory.plan_step(mason, team, PersonaState(mood="busy"), observe, view, {"wood": 3, "berries": 5}, (76, 105), 3) is None  # Halloween waits for the factory


def test_a_sign_whose_tile_another_structure_took_is_recorded_blocked_not_tried_forever():
    personas, teams = load_personas(ROOT), load_teams(ROOT)
    mason = personas["nibs"]
    for name in ("treetop-hideaway", "nintendo-land"):
        design, steps, _ = _bp(name)
        factory.mark_done(ROOT, factory.ledger_name(design, name), [s["id"] for s in steps], 1, "test")
    _sd, signs, _ = _bp("signposts")
    great = next(s for s in signs if s["section"] == "great-tree")
    road = {"type": "road", "x": great["action"]["x"], "y": great["action"]["y"], "owner": "Lagalong"}
    view = WorldView(x0=70, y0=100, rows=GRASS, full_map=GRASS, tick=1000, world_structures=[road])
    observe = {"tick": 1000, "you": {"name": mason.name, "x": 76, "y": 105, "faction": {"id": 9, "name": "Neverland"}, "blocks_owned": 0}}
    step = factory.plan_step(mason, teams["neverland"], PersonaState(mood="busy"), observe, view, {"wood": 3, "berries": 5}, (76, 105), 3)
    assert step is not None and great["action"] not in step[0] and step[0][-1]["action"] == "build" and "The West Tree" in step[1]  # the next tree's sign instead
    done = factory.load_ledger(ROOT, "signposts")["done"]
    assert done[great["id"]]["by"].startswith("blocked: another structure stands on its tile") and "road" in done[great["id"]]["by"]
