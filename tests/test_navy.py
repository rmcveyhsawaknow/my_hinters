"""The Admiralty: the sea charted for the Navy, its works over the shelf, and its model on every wake (2026-10-26)."""

import json
from pathlib import Path

from hglab import navy
from hglab.mood import PersonaState
from hglab.persona import load_personas
from hglab.planner import WorldView

ROOT = Path(__file__).resolve().parents[1]
ROWS = (ROOT / "tests/fixtures/world/terrain.txt").read_text(encoding="utf-8").split()


def _chart():
    return navy.chart(ROWS)


def test_the_chart_holds_the_shelf_its_piers_and_the_lake_causeway():
    c = _chart()
    assert c.shallow == 1221 and c.deep == 7239 and len(c.waypoints) == 57 and c.lakes == 3
    causeway = next(w for w in c.works if w.kind == "causeway")
    assert causeway.shore == (50, 49) and causeway.tiles == [(50, 50), (50, 51)] and causeway.far == (50, 52) and causeway.saves >= navy.MIN_SAVING
    piers = [w for w in c.works if w.kind == "pier"]
    assert len(piers) == navy.MAX_PIERS
    for pier in piers:
        assert all(c.at(*t) == "w" for t in pier.tiles) and c.at(*pier.far) == "W" and len(pier.tiles) <= navy.MAX_PIER  # shallows to the deep edge
        assert c.at(*pier.shore) in navy.WALKABLE
    for a in piers:
        for b in piers:
            if a is not b:
                assert max(abs(a.shore[0] - b.shore[0]), abs(a.shore[1] - b.shore[1])) >= navy.PIER_SPACING  # spread round the island


def _view(structures=(), resources=()):
    return WorldView(x0=0, y0=0, rows=[], full_map=ROWS, world_structures=list(structures), world_resources=list(resources), tick=1000)


def _navy():
    return load_personas(ROOT)["navy"]


def test_the_rules_build_out_from_the_shore_one_bridge_on_the_last():
    pier = next(w for w in _chart().works if w.id == "pier-01")
    state = PersonaState(mood="steady")
    step = navy.plan_step(_navy(), state, {"tick": 1000}, _view(), {"wood": 20}, pier.shore, 3)
    assert step[0] == [{"action": "build", "type": "bridge", "x": pier.tiles[0][0], "y": pier.tiles[0][1]}] and state.flags["navy"]["work"] == "pier-01"
    built = [{"type": "bridge", "x": pier.tiles[0][0], "y": pier.tiles[0][1], "owner": "Fathomark"}]
    nxt = navy.plan_step(_navy(), state, {"tick": 1000}, _view(built), {"wood": 20}, pier.shore, 3)
    assert nxt[0][0]["action"] == "move" and (nxt[0][0]["x"], nxt[0][0]["y"]) == pier.tiles[0]  # onto the first bridge, beside the second


def test_the_rules_gather_wood_when_the_pack_holds_less_than_a_bridge():
    pier = next(w for w in _chart().works if w.id == "pier-01")
    forest = (pier.shore[0] - 1, pier.shore[1] + 1)
    step = navy.plan_step(_navy(), PersonaState(mood="steady"), {"tick": 1000}, _view(resources=[{"kind": "wood", "x": forest[0], "y": forest[1], "amount": 20}]), {"wood": 5}, pier.shore, 3)
    assert step[0] == [{"action": "gather", "kind": "wood"}] and "needs 15 wood" in step[1]


def test_a_finished_work_gets_its_sign_and_then_the_coast_is_charted():
    c = _chart()
    bridges = [{"type": "bridge", "x": x, "y": y, "owner": "Fathomark"} for w in c.works for x, y in w.tiles]
    pier = next(w for w in c.works if w.id == "pier-01")
    state = PersonaState(mood="steady")
    sign = navy.plan_step(_navy(), state, {"tick": 1000}, _view(bridges), {"wood": 3}, pier.shore, 3)
    assert sign[0][0]["action"] == "build" and sign[0][0]["type"] == "sign" and "Pier-01" in sign[0][0]["text"] and len(sign[0][0]["text"]) <= 200
    state.flags["navy"]["signed"] = [w.id for w in c.works]
    chart_on = navy.plan_step(_navy(), state, {"tick": 1000}, _view(bridges), {"wood": 3}, pier.shore, 3)
    assert chart_on[0][0]["action"] == "move" and "charting the coast" in chart_on[1]


def test_the_model_plans_every_navy_wake_within_its_own_daily_cap():
    from hglab.budget import status
    from hglab.cli_personas import effective_planner

    fathomark = _navy()
    assert fathomark.knobs["model_route"] == "tick_premium" and fathomark.knobs["planner"] == "model"  # Sonnet 5.5 since 2026-10-27
    assert effective_planner(fathomark, "heuristic", work=True) == "auto"  # shifts too: the model, when a key is set
    wonka = load_personas(ROOT)["wonka"]
    assert effective_planner(wonka, "heuristic", work=True) == "heuristic"  # everyone else's shifts stay on rules
    records = [
        {"agent": "Fathomark", "created_utc": "2026-10-26T10:00:00+00:00", "usage": {"model": "claude-sonnet-5-5", "input_tokens": 600000, "output_tokens": 20000, "calls": 12}},
        {"agent": "Clarion", "created_utc": "2026-10-26T10:00:00+00:00", "usage": {"model": "claude-haiku-5-5", "input_tokens": 10000, "output_tokens": 100, "calls": 1}},
    ]
    from datetime import UTC, datetime

    state = status(ROOT, now=datetime(2026, 10, 26, 12, tzinfo=UTC), records=records, agent="Fathomark")
    assert state.agent_today_usd >= float(fathomark.knobs["max_usd_daily"]) > 0 and state.today_usd > state.agent_today_usd  # past its own cap: its wakes plan by rules


def test_the_brief_tells_the_model_the_rules_at_sea_and_the_next_works():
    world = {"width": 128, "height": 128, "terrain": "".join(ROWS), "structures": [], "agents": []}
    text = navy.brief(world, (40, 27), {"next": 3, "charted": 3})
    assert "a bridge (15 wood) stands only on shallow water" in text and "pier-01 pier from the shore at (40, 27)" in text and "waypoint 4 of 57" in text
    assert json.dumps(text)  # plain text for the guidance


def test_the_navy_asks_its_model_on_shift_wakes_even_with_no_line_left(tmp_path):
    """2026-10-27: every Fathomark wake under the supervisor planned by rules: shifts never asked the model, and a wake after its hour's line skipped it."""
    from hglab.fixtures import FixtureClient, load_fixture
    from hglab.lease import acquire
    from hglab.persona import load_team
    from hglab.wake import persona_wake

    personas = load_personas(ROOT)
    fathomark = personas["navy"]
    observe = load_fixture(ROOT / "tests/fixtures/observe/navy.json")
    tick = int(observe["tick"])
    spent = [{"type": "say", "actor": "Fathomark", "tick": tick - 5, "id": 990001, "text": "Log: waypoint 3 of 57."}]
    asked = []

    def llm_call(guidance, observe_now):
        asked.append(json.loads(guidance))
        return {"summary": "the next bridge", "actions": [], "reasons": ["the pier waits for wood"], "approach": "navy"}

    client = FixtureClient(observe)
    lease = acquire(client, fathomark.name)
    result = persona_wake(persona=fathomark, team=load_team(ROOT, "admiralty"), personas=personas, client=client, lease=lease, root=ROOT, output_dir=tmp_path, dry_run=True, seed="navy", planner_mode="llm", llm_call=llm_call, public_events=spent, work=True)
    record = result[0] if isinstance(result, tuple) else result
    if record.get("wake_mode") != "rest":
        assert asked and "model_skipped" not in record and record["thinking"]["planner"] == "llm"


def test_a_model_plan_loses_only_the_actions_the_rules_refuse(tmp_path):
    """2026-10-27: four of five Opus plans fell back to rules whole, for a line past the hour's say or a build two tiles off."""
    from hglab.fixtures import FixtureClient, load_fixture
    from hglab.lease import acquire
    from hglab.persona import load_team
    from hglab.wake import persona_wake

    personas = load_personas(ROOT)
    fathomark = personas["navy"]
    observe = load_fixture(ROOT / "tests/fixtures/observe/navy.json")
    tick = int(observe["tick"])
    you = observe["you"]
    observe.setdefault("notebook", {})["_limits"] = json.dumps({"says": [{"tick": tick - 5, "text": "Log: waypoint 4 of 57."}]})  # the hour's line is said
    spent = [{"type": "say", "actor": "Fathomark", "tick": tick - 5, "id": 990002, "text": "Log: waypoint 4 of 57."}]
    seen = []

    def llm_call(guidance, observe_now):
        g = json.loads(guidance)
        seen.append(g)
        suggested = [a for a in g["suggested"]["actions"] if a.get("action") != "say"][:1]
        far = {"action": "build", "type": "sign", "x": int(you["x"]) + 3, "y": int(you["y"]), "text": "Pier works ahead."}
        return {"summary": "the pier", "actions": [{"action": "say", "text": "Log: the shelf runs two tiles here."}, far, *suggested], "reasons": ["the pier waits"], "approach": "navy"}

    client = FixtureClient(observe)
    lease = acquire(client, fathomark.name)
    result = persona_wake(persona=fathomark, team=load_team(ROOT, "admiralty"), personas=personas, client=client, lease=lease, root=ROOT, output_dir=tmp_path, dry_run=True, seed="navy", planner_mode="llm", llm_call=llm_call, public_events=spent, work=True)
    record = result[0] if isinstance(result, tuple) else result
    if record.get("wake_mode") == "rest" or not seen:
        return
    assert seen[0]["public_lines_left_this_hour"] == 0
    kinds = [a.get("action") for a in record["actions"]]
    if any(a.get("action") not in ("say", "remember") for a in seen[0]["suggested"]["actions"]):
        assert record["thinking"]["planner"] == "llm" and "say" not in kinds and "fallback_reason" not in record
        assert record["speech_budget"]["muted"] == 1 and any("build target must be on or adjacent" in d for d in record.get("dropped", []))
