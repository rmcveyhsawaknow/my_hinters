"""The land office's fill board and its gathering throttle (the owner, 2026-11-03): no gathering while every store
is past the mark; under it, as many hands gather as the room under the mark holds packs, the shortest kind first."""

import random
from pathlib import Path

from conftest import office_team

from hglab import fill
from hglab.crew import plan_crew
from hglab.mood import PersonaState
from hglab.persona import load_personas
from hglab.planner import WorldView, plan_wake

ROOT = Path(__file__).resolve().parents[1]
ROWS = ["g" * 128] * 128
OFFICE = ["land-broker", "office-quarrier", "office-feller", "office-reaper", "office-drayman", "office-steward"]
ROLES = {"office-quarrier": "quarrier", "office-feller": "woodcutter", "office-reaper": "provisioner", "office-drayman": "hauler", "office-steward": "mason"}
STOCK = {"ore": 60, "stone": 300, "wood": 300, "fiber": 150, "berries": 150}


def _store(x, y, storage=None, owner="Lintelstave"):
    s = {"type": "storehouse", "x": x, "y": y, "owner": owner, "policy": "faction", "faction": "Land Office"}
    if storage is not None:
        s["storage"] = dict(storage)
    return s


def test_the_board_keeps_what_the_office_saw_and_lends_it_to_stores_out_of_view_for_six_hours(tmp_path):
    seen = [_store(80, 74, {"wood": 400}), _store(90, 77, {"stone": 50}, owner="Stranger"), _store(95, 70)]  # a stranger's store and one with no contents shown are not recorded
    assert fill.record(tmp_path, seen, {"Lintelstave", "LandBroker"}, 1000) == 1
    board = fill.load_board(tmp_path)
    assert board == {"80,74": {"tick": 1000, "storage": {"wood": 400}}}
    out_of_view = [_store(80, 74), _store(81, 76)]
    lent = fill.enrich(out_of_view, board, 1000 + fill.SEEN_TICKS)
    assert lent[0]["storage"] == {"wood": 400} and lent[0]["seen"] == 1000 and "storage" not in lent[1]
    assert "storage" not in fill.enrich(out_of_view, board, 1001 + fill.SEEN_TICKS)[0]  # stale after six hours
    assert "storage" not in fill.enrich(out_of_view, board, 999)[0]  # a sighting from the future (another clock) is no sighting
    in_view = [_store(80, 74, {"wood": 10})]
    assert fill.enrich(in_view, board, 1000)[0]["storage"] == {"wood": 10}  # what the wake sees beats the board
    fill.record(tmp_path, [_store(80, 74, {"wood": 300})], {"Lintelstave"}, 900)
    assert fill.load_board(tmp_path)["80,74"]["tick"] == 1000  # an older sighting never overwrites a newer one
    fill.record(tmp_path, [_store(81, 76, {"wood": 5})], {"Lintelstave"}, 1000 + fill.KEEP_TICKS + 1)
    assert set(fill.load_board(tmp_path)) == {"81,76"}  # a day on, the old sighting is forgotten


def test_slots_follow_the_room_under_the_mark_and_the_shortest_kind_goes_first():
    room_min = 125  # three quarters of 500
    past = [_store(80, 74, {"wood": 380}), _store(81, 76, {"stone": 400})]
    assert fill.levels(past, set(), room_min)["slots"] == 0
    ok, why = fill.decide("office-quarrier", OFFICE, ROLES, past, set(), room_min, STOCK)
    assert not ok and why.startswith("every store of the office seen lately is past 75% (2 of 2)")
    roomy = [*past, _store(82, 76, {"wood": 115, "ore": 60})]  # 200 under the mark: four packs; the ore at its stock
    lv = fill.levels(roomy, set(), room_min)
    assert lv["room"] == 200 and lv["slots"] == 4 and lv["known"] == 3 and lv["past"] == 2
    assert fill.levels(roomy, {(82, 76)}, room_min)["slots"] == 0  # a store that refused a give lately counts as past the mark
    ranked = fill.order(OFFICE, ROLES, lv["held"], STOCK)
    assert ranked[:3] == ["office-reaper", "office-quarrier", "office-feller"] and ranked[3:] == ["office-drayman", "office-steward", "land-broker"]  # no fiber or berries held: the reaper first; the ore at stock, the stone past it: the quarrier
    assert fill.decide("office-reaper", OFFICE, ROLES, roomy, set(), room_min, STOCK)[0]
    assert fill.decide("office-drayman", OFFICE, ROLES, roomy, set(), room_min, STOCK)[0]  # four slots: the hauler too
    assert not fill.decide("office-steward", OFFICE, ROLES, roomy, set(), room_min, STOCK)[0]  # the fifth waits
    one = [*past, _store(82, 76, {"wood": 265, "ore": 60})]  # one pack of room
    assert fill.decide("office-reaper", OFFICE, ROLES, one, set(), room_min, STOCK)[0] and not fill.decide("office-feller", OFFICE, ROLES, one, set(), room_min, STOCK)[0]
    assert fill.decide("office-feller", OFFICE, ROLES, [_store(80, 74)], set(), room_min, STOCK) == (True, "no store of the office seen lately: gather as before")


def _quarrier(storage, monkeypatch=None, board=None, in_view=True):
    personas = load_personas(ROOT)
    persona = personas["office-quarrier"]
    team = office_team()
    store = _store(73, 74, storage)
    public = {k: v for k, v in store.items() if k != "storage"}
    nodes = [{"kind": "stone", "x": 76, "y": 72, "amount": 20}]
    view = WorldView(x0=67, y0=66, rows=ROWS, full_map=ROWS, structures=[store] if in_view else [], world_structures=[public], world_resources=nodes, resources=nodes, tick=1000)
    if monkeypatch is not None:
        monkeypatch.setattr(fill, "load_board", lambda root: board or {})
    observe = {"you": {"x": 75, "y": 72, "faction": {"id": 7, "name": "Land Office"}}, "tick": 1000}
    roles = {slug: str((p.knobs.get("crew") or {}).get("role") or "") for slug, p in personas.items() if isinstance(p.knobs.get("crew"), dict)}
    state = PersonaState(mood="busy")
    step = plan_crew(persona, team, state, observe, view, {"berries": 5}, (75, 72), 80, persona.energy_reserve, 3, {p.name for p in personas.values()}, {p.name: s for s, p in personas.items()}, None, crew_roles=roles)
    return step, state


def test_the_quarrier_gathers_only_while_the_office_has_room_under_the_mark(monkeypatch):
    step, _ = _quarrier({"wood": 100})
    assert step is not None and any(a["action"] == "gather" for a in step[0])
    capped, state = _quarrier({"wood": 400})
    assert capped is None or all(a["action"] != "gather" for a in capped[0])
    assert state._gather_capped.startswith("every store of the office seen lately is past 75%")
    board = {"73,74": {"tick": 900, "storage": {"wood": 420}}}  # out of view, seen a little earlier by a teammate
    far, state = _quarrier(None, monkeypatch, board, in_view=False)
    assert (far is None or all(a["action"] != "gather" for a in far[0])) and state._gather_capped


def test_the_registrar_gathers_nothing_on_his_rounds_while_every_store_is_past_the_mark():
    personas = load_personas(ROOT)
    broker = personas["land-broker"]
    team = office_team()
    names = {personas[m].name.casefold(): m for m in team.members}  # as the wake hands them over

    def gathers(storage):
        observe = {
            "tick": 1000, "inbox": [], "events": [], "view": {"x0": 74, "y0": 66, "rows": ["g" * 13] * 13},
            "structures": [_store(80, 73, storage)], "resources": [{"kind": "stone", "x": 81, "y": 72, "amount": 20}, {"kind": "wood", "x": 79, "y": 71, "amount": 20}],
            "you": {"name": "LandBroker", "x": 80, "y": 72, "energy": 90, "inventory": {"berries": 5}, "faction": {"id": 7, "name": "Land Office"}, "blocks_owned": 0},
        }
        plan = plan_wake(broker, team, PersonaState(mood="ambitious"), observe, "work", random.Random(3), terrain_rows=ROWS, work=True, registrar_name="LandBroker", collective_names={"LandBroker", "Lintelstave"}, team_names=names)
        return [a for a in plan["actions"] if a["action"] == "gather"]

    assert gathers({"wood": 100})  # room under the mark: his rounds gather as ever
    assert not gathers({"wood": 400})  # every store past it: nothing


def test_a_model_s_plan_obeys_the_throttle_too(tmp_path, monkeypatch):
    """The registrar's character wakes are planned by a model on some routes: the wake drops its gathers while every store is past the mark."""
    import copy

    from hglab.fixtures import FixtureClient, load_fixture
    from hglab.lease import acquire
    from hglab.wake import persona_wake

    monkeypatch.setattr("hglab.wake.decide_wake_mode", lambda *a, **k: "act")
    personas = load_personas(ROOT)
    broker = personas["land-broker"]
    base = load_fixture(ROOT / "tests/fixtures/observe/land-broker.json")

    def picker(_guidance, observe):
        return {"summary": "berries for the vault", "actions": [{"action": "gather", "kind": "berries"}], "approach": "gather_near"}

    def wake(storage):
        observe = copy.deepcopy(base)
        observe["structures"] = [*observe.get("structures", []), _store(65, 63, storage)]
        client = FixtureClient(observe)
        return persona_wake(persona=broker, team=office_team(), personas=personas, client=client, lease=acquire(client, broker.name), root=ROOT, output_dir=tmp_path, dry_run=True, planner_mode="llm", llm_call=picker, seed="gate")

    roomy = wake({"wood": 10})  # room for seven packs: the registrar, last of the six, gathers too
    assert any(a["action"] == "gather" for a in roomy["actions"]) and "office_gate" not in roomy
    capped = wake({"wood": 420})
    assert all(a["action"] != "gather" for a in capped["actions"]) and capped["office_gate"].startswith("every store of the office seen lately is past 75%")
