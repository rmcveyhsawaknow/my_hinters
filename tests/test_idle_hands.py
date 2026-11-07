"""Hands that stood idle on 2026-11-06 with work in reach: a pack that paid for steps beyond the near ring, a hand lent
to another team's design gathering by its own works, and a hand shut in a building whose doors are another team's."""

from __future__ import annotations

import random
from pathlib import Path

import yaml

from hglab import crew, factory
from hglab.mood import PersonaState
from hglab.persona import load_personas, load_team
from hglab.planner import WorldView, plan_wake

ROOT = Path(__file__).resolve().parents[1]
GRASS = ["g" * 128] * 128


def _pair_root(tmp_path):
    """The Toffee Kitchens and the Whipped Cream Dairy alone, as the factory draws them: toffee's first step wants stone, the dairy's wood."""
    sections = {s["id"]: s for s in factory.load_design(ROOT, "chocolate-factory")["sections"]}
    (tmp_path / "teams" / "blueprints").mkdir(parents=True)
    design = {"name": "Pair", "title": "the pair blueprint", "team": "chocolate-factory", "version": 1, "sections": [sections["toffee"], sections["dairy"]]}
    (tmp_path / "teams" / "blueprints" / "pair.yaml").write_text(yaml.safe_dump(design), encoding="utf-8")
    return tmp_path


def test_a_pack_that_pays_for_a_step_carries_it_as_far_as_the_works_reach(tmp_path):
    root = _pair_root(tmp_path)
    personas = load_personas(ROOT)
    hand, team = personas["loompa-woodcutter"], load_team(ROOT, "chocolate-factory")
    here = (100, 95)  # the dairy's first step 12 tiles off wants wood; the toffee kitchens' 29 tiles off wants the stone in the pack
    observe = {"you": {"x": here[0], "y": here[1], "faction": {"id": 5, "name": "Chocolate Factory"}, "blocks_owned": 0}, "tick": 1000}
    view = WorldView(x0=here[0] - 5, y0=here[1] - 5, rows=GRASS, full_map=GRASS, tick=1000)
    for pack_only in (None, "stone"):
        step = factory.plan_step(hand, team, PersonaState(mood="busy"), observe, view, {"stone": 12, "berries": 5}, here, 3, root=root, hands=True, pack_only=pack_only, design_name="pair")
        assert step is not None and step[2] == "blueprint", pack_only
        assert "carrying 4 stone toward The Toffee Kitchens" in step[1]
        move = step[0][0]
        assert move["action"] == "move" and move["y"] < here[1]  # north, toward the kitchens, not to a store for the dairy's wood
    # a team whose works reach no further than the near ring leaves a step that far to the walk to its site
    neverland = load_team(ROOT, "neverland")
    away = factory.plan_step(hand, neverland, PersonaState(mood="busy"), observe, view, {"stone": 12, "berries": 5}, here, 3, root=root, hands=True, pack_only="stone", design_name="pair")
    assert away is None


def test_a_hand_away_from_its_works_gathers_the_blueprints_need_where_it_stands(monkeypatch):
    personas = load_personas(ROOT)
    hand, team = personas["lost-boy"], load_team(ROOT, "neverland")
    cfg = crew.pipeline_of(team)
    site, reach = (int(cfg["site"]["x"]), int(cfg["site"]["y"])), int(cfg.get("range", 16))

    def no_step(persona, team, state, *args, **kwargs):
        state._bp_need = "stone"  # nothing the pack pays for and no store of ours holds stone: plan_step returns None

    monkeypatch.setattr(factory, "plan_step", no_step)
    by_home = (site[0] + 4, site[1])
    nodes = [{"x": 75, "y": 49, "kind": "stone", "amount": 20, "max": 20}, {"x": by_home[0], "y": by_home[1], "kind": "stone", "amount": 20, "max": 20}]

    def plan(here):
        view = WorldView(x0=here[0] - 5, y0=here[1] - 5, rows=GRASS, full_map=GRASS, tick=1000, world_resources=nodes)
        observe = {"you": {"x": here[0], "y": here[1], "faction": {"id": 6, "name": "Neverland"}, "blocks_owned": 0}, "tick": 1000}
        return crew._blueprint(hand, team, PersonaState(mood="busy"), observe, view, {"fiber": 5, "berries": 15}, here, 3, set(), site, reach, None, None, None, hands=True)

    lent = plan((79, 30))  # at Nintendo Land, 74 tiles from the hideaway
    assert lent is not None and "toward the stone at (75, 49) for the blueprint's stone" in lent[1]
    assert lent[0][0]["y"] > 30  # south to the stone 19 tiles off, not home
    home = plan(site)
    assert home is not None and f"toward the stone at {by_home}" in home[1]  # at its own works the site's nodes come first, as before


def _museum_observe(walls, here, name, faction):
    return {
        "tick": 179600, "inbox": [], "events": [], "structures": [], "resources": [],
        "view": {"x0": here[0] - 6, "y0": here[1] - 6, "rows": ["g" * 13] * 13},
        "blocks": [{"x": x, "y": y, "count": 16, "top": 5, "owner": "Sheafwell", "closed": True, "door": (x, y) in {(78, 29), (79, 27)}} for x, y in sorted(walls)],
        "_closed_world": [list(t) for t in sorted(walls)],
        "_cells_near": [],
        "you": {"name": name, "x": here[0], "y": here[1], "energy": 100, "inventory": {"fiber": 5, "berries": 15}, "faction": faction, "blocks_owned": 120},
    }


def test_a_hand_shut_in_a_building_whose_doors_are_another_teams_puts_in_a_door_of_its_own():
    personas = load_personas(ROOT)
    hand, team = personas["lost-boy"], load_team(ROOT, "neverland")
    pocket = {(x, y) for x in (79, 80) for y in (28, 29, 30)}  # the Nintendo Museum's inside, its doors the office's
    walls = {(x, y) for x in range(78, 82) for y in range(27, 32)} - pocket
    here = (79, 30)
    observe = _museum_observe(walls, here, hand.name, {"id": 6, "name": "Neverland"})
    plan = plan_wake(hand, team, PersonaState(mood="busy"), observe, "work", random.Random(1), terrain_rows=GRASS, work=True)
    assert plan["approach"] == "escape"
    door = plan["actions"][-1]
    assert door["action"] == "place" and door["shape"] == "door" and door["material"] == "thatch"  # the pack's five fiber
    assert (door["bx"] // 4, door["by"] // 4) in walls
    # beside one closed tile on open ground there is nothing to escape
    yard = {**observe, "blocks": [{"x": 78, "y": 30, "count": 4, "top": 1, "owner": "Sheafwell", "closed": True, "door": False}], "_closed_world": [[78, 30]]}
    assert plan_wake(hand, team, PersonaState(mood="busy"), yard, "work", random.Random(1), terrain_rows=GRASS, work=True)["approach"] != "escape"


def test_a_pack_too_full_for_a_fetch_puts_its_clutter_away_and_takes_the_whole_load():
    # 2026-11-07: Nintendo Land's Landing Pad wants 36 stone, more than any hand keeping 15 berries had room for, and four
    # hands walked between the stores beside them for hours: now the clutter goes into the store and the stone comes out
    hand = load_personas(ROOT)["office-quarrier"]
    here, at = (50, 50), (51, 50)
    store = {"type": "storehouse", "x": at[0], "y": at[1], "owner": hand.name, "policy": "private", "storage": {"stone": 300}}
    other = {"type": "storehouse", "x": 50, "y": 53, "owner": hand.name, "policy": "private", "storage": {"stone": 300}}
    view = WorldView(x0=45, y0=45, rows=GRASS, full_map=GRASS, tick=1000, structures=[store, other], world_structures=[store, other])
    observe = {"you": {"x": here[0], "y": here[1], "faction": None}, "tick": 1000}
    design, target = {"name": "Nintendo Land"}, {"name": "The Landing Pad: water 1"}

    def fetch(pack):
        return factory._provision(design, target, "stone", 36, hand, PersonaState(mood="busy"), observe, view, dict(pack), here, 3)

    actions, reason, _ = fetch({"fiber": 4, "berries": 15})  # Strayling's pack: room for 31
    assert [a["action"] for a in actions] == ["give", "give", "take"] and actions[-1]["qty"] >= 36, reason
    assert {(a["item"], a["qty"]) for a in actions[:2]} == {("fiber", 4), ("berries", 10)} and all((a["x"], a["y"]) == at for a in actions)
    actions, reason, _ = fetch({"wood": 22, "fiber": 10, "berries": 15})  # Boundstone's: room for 3, and three gives to make it
    assert [a["action"] for a in actions] == ["give", "give", "give"] and "put 42 of the pack away" in reason, reason
    actions, _, _ = fetch({"berries": 5})  # the next wake, beside the same store
    assert actions == [{"action": "take", "x": at[0], "y": at[1], "item": "stone", "qty": 40}]
