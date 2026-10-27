"""Routing from the memory graph's observed patterns, and the graph fed every cycle (owner, 2026-10-27)."""

import json
from pathlib import Path

from hglab import factory
from hglab.crew import plan_crew
from hglab.local.goals import adapt, wake_guidance
from hglab.local.memory import Graph, ingest_personas, ingest_recent
from hglab.local.routing import patterns, productivity, route_for
from hglab.mood import PersonaState
from hglab.persona import load_personas, load_team, load_teams
from hglab.planner import WorldView

ROOT = Path(__file__).resolve().parents[1]
GRASS = ["g" * 128] * 128


def _wake(g, agent, tick, approach, kinds, pack=None, refused=None):
    g.upsert_node("wake", f"wake:{agent}:{tick}", tick=tick, agent=agent, approach=approach, kinds=kinds, refused=refused or {}, pack=pack, mode="act", actions=sum(kinds.values()) or 1, failed=0)


def _graph(tmp_path):
    g = Graph(tmp_path / "runs/local/memory.sqlite")
    ingest_personas(g, load_personas(ROOT), load_teams(ROOT))
    for i in range(30):
        _wake(g, "MotherPail", 1000 + i, "blueprint", {"place": 1, "move": 1}, pack=40)  # the builders' blueprint works
        _wake(g, "Nougatpick", 1000 + i, "crew" if i % 2 else "explore", {"move": 1} if i % 8 else {"gather": 1}, pack=50, refused={"inventory_full": 1} if i % 5 == 0 else {})
        _wake(g, "Treacleaxe", 1000 + i, "crew", {"gather": 1, "give": 1}, pack=20)
        _wake(g, "Strayling", 1000 + i, "explore", {"move": 1}, pack=48)
        _wake(g, "Stoutheart", 1000 + i, "gather_trip", {"gather": 1}, pack=30)
    return g


def test_an_idle_hand_with_a_heavy_pack_is_routed_to_its_teams_proven_blueprint(tmp_path):
    g = _graph(tmp_path)
    personas, teams = load_personas(ROOT), load_teams(ROOT)
    pats = patterns(g, 0)
    assert pats[("chocolate-factory", "")]["blueprint"]["rate"] == 1.0
    idle = productivity(g, "Nougatpick")
    assert idle["wakes"] == 24 and idle["share"] <= 0.25 and idle["pack"] == 50 and idle["full"] >= 3
    route = route_for(personas["loompa-quarrier"], teams["chocolate-factory"], idle, pats)
    assert route and route["approach"] == "blueprint" and "changed the world in 100%" in route["why"]
    busy = route_for(personas["loompa-woodcutter"], teams["chocolate-factory"], productivity(g, "Treacleaxe"), pats)
    assert busy is None  # every wake changes something: no route


def test_a_character_keeps_its_personality_and_an_explorers_moves_count(tmp_path):
    g = _graph(tmp_path)
    personas, teams = load_personas(ROOT), load_teams(ROOT)
    pats = patterns(g, 0)
    strayling = personas["lost-boy"]
    walker = productivity(g, "Strayling", goal_kinds=frozenset({"move"}))
    assert walker["share"] == 1.0 and route_for(strayling, teams["neverland"], walker, pats) is None  # discoveries are made on foot
    idle = productivity(g, "Strayling")
    assert route_for(strayling, teams["neverland"], idle, pats) is None  # no measured goal kinds: a character keeps its own way
    assert route_for(strayling, teams["neverland"], idle, pats, goal_kinds=frozenset({"say"})) is None  # no approach of the team produces it
    route = route_for(strayling, teams["neverland"], idle, pats, goal_kinds=frozenset({"gather"}))
    assert route and route["approach"] == "gather_trip" and strayling.knobs["intended_mix"]["gather"] >= 0.15  # what the goal counts, within its own mix


def test_the_supervisor_feed_reads_new_records_once(tmp_path):
    g = Graph(tmp_path / "memory.sqlite")
    folder = tmp_path / "runs/2026-10-27"
    folder.mkdir(parents=True)
    record = {"run_id": "r1", "agent": "Nougatpick", "tick": 5, "wake_mode": "act", "approach": "crew", "actions": [{"action": "gather", "kind": "stone"}], "results": [{"ok": True}], "observe": {"you": {"inventory": {"stone": 40}}}}
    (folder / "Nougatpick-r1.json").write_text(json.dumps(record), encoding="utf-8")
    (folder / "Nougatpick-keepalive-1.json").write_text(json.dumps({**record, "run_id": "k1"}), encoding="utf-8")
    fed = ingest_recent(g, tmp_path, 0.0)
    assert fed["read"] == 1 and fed["newest"] > 0
    wake = g.node("wake:r1")
    assert wake["kinds"] == {"gather": 1} and wake["pack"] == 40 and wake["refused"] == {}
    assert ingest_recent(g, tmp_path, fed["newest"])["read"] == 0  # nothing newer: nothing read


def test_adapt_puts_the_route_first_and_the_wake_reads_it(tmp_path):
    g = _graph(tmp_path)
    personas, teams = load_personas(ROOT), load_teams(ROOT)
    plan = adapt(ROOT, g, {s: personas[s] for s in ("loompa-quarrier", "mrs-bucket")}, teams)  # the metrics from the repo, the graph from the test
    g.close()
    a = plan["agents"]["loompa-quarrier"]["assignment"]
    assert a["route"] == "blueprint" and a["prefer"][0] == "blueprint" and any("routed to the blueprint" in b for b in a["because"])
    assert plan["agents"]["mrs-bucket"]["assignment"]["route"] is None  # MotherPail builds every wake
    guidance = wake_guidance(tmp_path, "Nougatpick", "chocolate-factory")
    assert guidance["assignment"]["route"] == "blueprint"


def _hand_step(route, inventory, stores, position=(93, 99)):
    personas = load_personas(ROOT)
    hand = personas["loompa-quarrier"]
    team = load_team(ROOT, "chocolate-factory")
    observe = {"tick": 70000, "you": {"name": hand.name, "x": position[0], "y": position[1], "faction": {"id": 5, "name": "Chocolate Factory"}, "blocks_owned": 0}}
    view = WorldView(x0=82, y0=82, rows=GRASS, full_map=GRASS, structures=stores, world_structures=stores, tick=70000)
    return plan_crew(hand, team, PersonaState(mood="busy"), observe, view, dict(inventory), position, 90, hand.energy_reserve, 3, {p.name for p in personas.values()}, {p.name: s for s, p in personas.items()}, None, route=route)


def test_a_hand_with_a_full_pack_beside_full_stores_builds_from_its_pack():
    design, steps, _ = factory.blueprint(ROOT, "chocolate-factory")
    led = factory.ledger_name(design, "chocolate-factory")
    factory.mark_done(ROOT, led, sorted(s["id"] for s in steps if s["section"] != "campus-south"), 1, "test")  # only the south wall is left
    full = [{"type": "storehouse", "x": 90, "y": 99, "owner": "Toffeetrowel", "policy": "faction", "faction": "Chocolate Factory", "storage": {"stone": 300, "wood": 200}}]
    step = _hand_step(None, {"stone": 45, "berries": 5}, full)
    assert step is not None and step[2] == "blueprint" and step[0][-1]["action"] == "place"  # the pack's stone goes into the wall
    routed = _hand_step("blueprint", {"stone": 40, "berries": 5}, [{**full[0], "storage": {"stone": 10}}])
    assert routed is not None and routed[2] == "blueprint"  # routed by the graph: the blueprint before a gather


def test_a_builder_takes_the_step_its_pack_already_pays_for():
    personas = load_personas(ROOT)
    team = load_team(ROOT, "chocolate-factory")
    design, steps, _ = factory.blueprint(ROOT, "chocolate-factory")
    led = factory.ledger_name(design, "chocolate-factory")
    factory.mark_done(ROOT, led, sorted(s["id"] for s in steps if not s["section"].startswith(("campus-south", "tubes-candy"))), 1, "test")
    observe = {"tick": 70000, "you": {"name": "MotherPail", "x": 94, "y": 97, "faction": {"id": 5, "name": "Chocolate Factory"}, "blocks_owned": 0}}
    view = WorldView(x0=82, y0=82, rows=GRASS, full_map=GRASS, tick=70000)
    step = factory.plan_step(personas["loompa-quarrier"], team, PersonaState(mood="busy"), observe, view, {"stone": 40, "berries": 5}, (94, 97), 3, hands=True)
    assert step is not None and step[2] == "blueprint" and any(a.get("action") == "place" for a in step[0])
    assert factory.plan_step(personas["loompa-quarrier"], team, PersonaState(mood="busy"), observe, view, {"stone": 40}, (94, 97), 3) is None  # not a builder, not routed: nothing
