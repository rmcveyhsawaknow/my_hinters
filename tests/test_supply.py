"""The atelier draws on the factory's stores, and nobody gives into a store whose faction hides its contents."""

from pathlib import Path

from hglab.mood import PersonaState
from hglab.persona import load_personas
from hglab.planner import WorldView, _full_stores, _plan_deposit, _plan_deposit_trip, _plan_draw

ROOT = Path(__file__).parents[1]
ROWS = ["g" * 128] * 128


def test_plumbline_walks_to_the_factory_store_and_takes_what_the_next_build_lacks():
    plumbline = load_personas(ROOT)["plumbline"]
    assert plumbline.knobs["supply"] == {"team": "chocolate-factory", "range": 48}
    store = {"id": 1, "type": "storehouse", "x": 87, "y": 94, "owner": "Toffeetrowel", "policy": "faction", "faction": "Chocolate Factory", "storage": {"wood": 200, "stone": 100, "fiber": 40}}
    far = WorldView(x0=84, y0=56, rows=ROWS, full_map=ROWS, world_structures=[store], tick=60000)
    observe = {"tick": 60000, "you": {"name": "Plumbline", "x": 90, "y": 62, "faction": {"id": 5, "name": "Chocolate Factory"}}}
    state = PersonaState(mood="exact")
    trip = _plan_draw(plumbline, state, {"berries": 6}, (90, 62), far, observe, {"Toffeetrowel", "MotherPail"})
    assert trip is not None and trip[2] == "draw_trip" and trip[0][0]["action"] == "move" and "allied store at (87, 94)" in trip[1]
    near = WorldView(x0=81, y0=88, rows=ROWS, full_map=ROWS, structures=[store], world_structures=[store], tick=60000)
    draw = _plan_draw(plumbline, state, {"berries": 6}, (88, 94), near, {**observe, "you": {**observe["you"], "x": 88, "y": 94}}, {"Toffeetrowel"})
    assert draw is not None and draw[2] == "draw" and draw[0][0] == {"action": "take", "x": 87, "y": 94, "item": "wood", "qty": 20} and len(draw[0]) == 2
    assert _plan_draw(plumbline, state, {"wood": 30, "stone": 12}, (88, 94), near, observe, {"Toffeetrowel"}) is None  # the pack is heavy enough
    assert _plan_draw(plumbline, state, {"berries": 6}, (88, 94), near, observe, None) is None  # no supply team known
    outsider = {**observe, "you": {**observe["you"], "x": 88, "y": 94, "faction": None}}
    shut = PersonaState(mood="exact")
    assert _plan_draw(plumbline, shut, {"berries": 6}, (88, 94), near, outsider, {"Toffeetrowel"}) is None  # a faction store admits no outsider
    assert (87, 94) in _full_stores(shut, 60000)  # remembered as closed for a day
    public = {**store, "policy": "public"}
    open_view = WorldView(x0=81, y0=88, rows=ROWS, full_map=ROWS, structures=[public], world_structures=[public], tick=60000)
    assert _plan_draw(plumbline, PersonaState(mood="exact"), {"berries": 6}, (88, 94), open_view, outsider, {"Toffeetrowel"})[0][0]["action"] == "take"  # a public store admits anyone


def test_nobody_gives_into_a_store_whose_faction_hides_its_contents():
    treacleaxe = load_personas(ROOT)["loompa-woodcutter"]
    depot = {"id": 1, "type": "storehouse", "x": 86, "y": 86, "owner": "Lintelstave", "policy": "faction", "faction": "Land Office"}  # no storage: hidden from us
    public = {"id": 2, "type": "storehouse", "x": 85, "y": 92, "owner": "MotherPail", "policy": "public", "storage": {"wood": 100}}
    view = WorldView(x0=81, y0=81, rows=ROWS, full_map=ROWS, structures=[depot], world_structures=[depot, public], tick=59000)
    state = PersonaState(mood="busy")
    mates = {"Lintelstave", "MotherPail", "Treacleaxe"}
    assert _plan_deposit(treacleaxe, {"wood": 36, "stone": 5, "berries": 5}, (87, 87), view, None, mates=mates, state=state, faction="Chocolate Factory") is None
    assert (86, 86) in _full_stores(state, 59000)  # the office's depot is opaque to a factory hand: left alone for a day
    trip = _plan_deposit_trip(treacleaxe, None, {"wood": 36, "stone": 5, "berries": 5}, (87, 87), view, None, {m.casefold() for m in mates}, state=state, faction="Chocolate Factory")
    assert trip is not None and "MotherPail" in trip[1]  # the public store is the one worth the walk
    lintelstave = load_personas(ROOT)["office-steward"]
    own_view = WorldView(x0=81, y0=81, rows=ROWS, full_map=ROWS, structures=[{**depot, "storage": {"wood": 10}}], tick=59000)
    mine = _plan_deposit(lintelstave, {"wood": 36, "stone": 5, "berries": 5}, (87, 87), own_view, None, mates=mates, state=PersonaState(mood="busy"), faction="Land Office")
    assert mine is not None and mine[0][0]["action"] == "give"  # its own faction sees inside and gives
