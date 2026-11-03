"""Nobody who can build stands idle (the owner's instruction of 2026-11-03): a hand with nothing of its own to raise lends
a hand to another team's open blueprint, the memory graph routes idle hands there, and Neverland's hands walk their grounds."""

from pathlib import Path

from hglab import factory
from hglab import help as helping
from hglab.help import can_help, open_teams, plan_help, plan_roam
from hglab.local.routing import route_for
from hglab.mood import PersonaState
from hglab.persona import load_personas, load_teams
from hglab.planner import WorldView, _plan_crew, plan_wake

ROOT = Path(__file__).resolve().parents[1]
GRASS = ["g" * 128] * 128


def _observe(position, faction="Neverland", tick=1000):
    return {"you": {"x": position[0], "y": position[1], "faction": {"id": 9, "name": faction}, "blocks_owned": 0}, "tick": tick}


def _view(position):
    return WorldView(x0=position[0] - 6, y0=position[1] - 6, rows=GRASS, full_map=GRASS, tick=1000)


def test_who_may_lend_a_hand():
    personas, teams = load_personas(ROOT), load_teams(ROOT)
    assert can_help(personas["loompa-quarrier"], teams["chocolate-factory"]) and can_help(personas["lost-boy"], teams["neverland"])
    assert can_help(personas["tinker-bell"], teams["neverland"]) and can_help(personas["plumbline"], teams["atelier"])  # builders without a crew knob
    assert can_help(personas["land-broker"], teams["exchange"])  # the registrar builds too (2026-11-03)
    assert not can_help(personas["grandpa-joe"], teams["chocolate-factory"])  # GrandadPail builds nothing (the owner, 2026-10-24)
    assert not can_help(personas["town-fool"], teams["commons"]) and not can_help(personas["navy"], teams["admiralty"])  # the fool speaks, the Navy charts


def test_the_nearest_open_works_come_first_and_finished_teams_are_skipped(monkeypatch):
    teams = load_teams(ROOT)
    near_office = [t.slug for t in open_teams(teams, teams["neverland"], (73, 73))]
    assert near_office[0] == "exchange" and "chocolate-factory" in near_office and "neverland" not in near_office  # never one's own team
    near_factory = [t.slug for t in open_teams(teams, teams["exchange"], (92, 96))]
    assert near_factory[0] == "chocolate-factory"
    monkeypatch.setattr(factory, "design_complete", lambda root, name: name != "treetop-hideaway")  # every design done but Neverland's
    assert [t.slug for t in open_teams(teams, teams["exchange"], (73, 73))] == ["neverland"]
    assert [t.slug for t in open_teams(teams, teams["commons"], (73, 73))] == ["neverland"]  # a team without a blueprint helps anyone


def test_a_neverland_hand_by_the_factory_lends_a_hand_to_its_blueprint():
    personas, teams = load_personas(ROOT), load_teams(ROOT)
    strayling = personas["lost-boy"]
    here = (87, 90)  # by the Cocoa Silo's tile (87,89): the first ready step of the factory's wild expansion
    step = plan_help(strayling, teams["neverland"], teams, PersonaState(mood="busy"), _observe(here), _view(here), {"stone": 40, "wood": 20, "berries": 5}, here, 3, mates={"Stoutheart", "Lagalong"})
    assert step is not None and step[2] == "help" and step[1].startswith("a hand lent to The Chocolate Factory: the factory blueprint")
    assert any(a.get("action") == "place" for a in step[0])  # the pack pays, the factory's ledger settles it like any other
    assert plan_help(personas["grandpa-joe"], teams["chocolate-factory"], teams, PersonaState(mood="busy"), _observe(here), _view(here), {"stone": 40}, here, 3) is None


def test_the_crew_wrapper_falls_back_to_helping_and_then_roaming(monkeypatch):
    from hglab import crew

    personas, teams = load_personas(ROOT), load_teams(ROOT)
    nibs = personas["nibs"]
    here = (62, 104)
    monkeypatch.setattr(crew, "plan_crew", lambda *a, **k: None)  # the hideaway's pipeline has nothing this wake
    sentinel = ([{"action": "place", "bx": 0, "by": 0, "bz": 0, "material": "wood"}], "a hand lent to The Chocolate Factory: x", "help")
    monkeypatch.setattr(helping, "plan_help", lambda *a, **k: sentinel)
    args = (nibs, teams["neverland"], PersonaState(mood="busy"), _observe(here), _view(here), {"wood": 10}, here, 80, 20, 3, None, None, None)
    assert _plan_crew(*args, cast={"teams": teams}) == sentinel
    monkeypatch.setattr(helping, "plan_help", lambda *a, **k: None)
    state = PersonaState(mood="busy")
    roam = _plan_crew(nibs, teams["neverland"], state, _observe(here), _view(here), {"wood": 10}, here, 80, 20, 3, None, None, None, cast={"teams": teams})
    assert roam is not None and roam[2] == "roam" and roam[0][0]["action"] == "move" and "the Treetop Hideaway blueprint's grounds" in roam[1]
    assert plan_roam(nibs, teams["neverland"], state, _observe(here), _view(here), here, 3) is None  # one roaming step a wake
    assert plan_roam(personas["loompa-quarrier"], teams["chocolate-factory"], PersonaState(mood="busy"), _observe(here), _view(here), here, 3) is None  # the factory's hands do not roam


def test_the_graph_routes_an_idle_hand_whose_designs_are_done_to_help(monkeypatch):
    personas, teams = load_personas(ROOT), load_teams(ROOT)
    idle = {"wakes": 24, "productive": 2, "share": 0.083, "full": 0, "pack": 10, "approaches": {}}
    assert route_for(personas["loompa-quarrier"], teams["chocolate-factory"], idle, {}) is None  # the factory is open: its own pipeline is the route
    monkeypatch.setattr(factory, "design_complete", lambda root, name: True)
    route = route_for(personas["loompa-quarrier"], teams["chocolate-factory"], idle, {})
    assert route and route["approach"] == "help" and "its team's designs are done" in route["why"]
    route = route_for(personas["tinker-bell"], teams["neverland"], idle, {}, done=True)
    assert route and route["approach"] == "help" and "every key result met" in route["why"]
    assert route_for(personas["grandpa-joe"], teams["chocolate-factory"], idle, {}) is None  # never GrandadPail


def test_a_builder_without_a_crew_knob_lends_a_hand_in_its_shift(monkeypatch):
    import random

    from hglab import planner

    personas, teams = load_personas(ROOT), load_teams(ROOT)
    plumbline = personas["plumbline"]
    monkeypatch.setattr(planner, "_plan_blueprint", lambda *a, **k: None)  # Lower Manhattan stands and the next deed is not paid
    monkeypatch.setattr(planner, "_plan_site_trade", lambda *a, **k: None)
    placed = ([{"action": "place", "bx": 348, "by": 356, "bz": 0, "material": "stone"}], "a hand lent to The Chocolate Factory: the factory blueprint: x", "help")
    monkeypatch.setattr(helping, "plan_help", lambda *a, **k: placed)
    observe = {
        "tick": 1000, "inbox": [], "events": [], "view": {"x0": 81, "y0": 83, "rows": ["g" * 13] * 13}, "structures": [], "resources": [],
        "you": {"name": "Plumbline", "x": 87, "y": 89, "energy": 90, "inventory": {"stone": 30, "berries": 5}, "faction": {"id": 5, "name": "Chocolate Factory"}, "blocks_owned": 0},
    }
    plan = plan_wake(plumbline, teams["atelier"], PersonaState(mood="busy"), observe, "work", random.Random(1), terrain_rows=GRASS, work=True, cast={"teams": teams})
    assert placed[0][0] in plan["actions"] and plan["approach"] == "help"
