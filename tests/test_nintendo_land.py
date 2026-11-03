"""Nintendo Land (the owner's instruction of 2026-11-03): a themed land in the island's open north for every team to build once its own works are done."""

from pathlib import Path

from hglab import factory
from hglab.blocks import _box_cells
from hglab.lots import lot_anchor, lot_id

ROOT = Path(__file__).resolve().parents[1]
NAME = "nintendo-land"
LOTS = {"F02-NE", "F02-SE", "F03-NE", "F03-SE", "J02-NW", "J02-SW", "J03-NW", "J03-SW"} | {
    f"{c}{r}-{q}" for c in "GHI" for r in ("02", "03") for q in ("NW", "NE", "SW", "SE")
}
CENTRES = {lot_anchor(lid) for lid in LOTS}  # the office's claim signs
ROADS = [(58, 38), (63, 28), (70, 37), (71, 37)]  # Lagalong's roads on the site, read at tick 153228
WALLS = [(68, 39), (69, 39)]  # Sheafwell's walls on G03-SE
FLAT = {"park", "pool", "treehouse"}  # slabs and decks that leave their tiles open: no plinth under them


def _bp():
    return factory.blueprint(ROOT, NAME)


def _world():
    """The site as the public world showed it: the fixture terrain (unchanged on these tiles since 2026-10-17), the claim signs, the roads and the walls."""
    rows = (ROOT / "tests/fixtures/world/terrain.txt").read_text(encoding="utf-8").splitlines()
    structures = [{"x": x, "y": y, "type": "sign"} for x, y in CENTRES]
    structures += [{"x": x, "y": y, "type": "road"} for x, y in ROADS] + [{"x": x, "y": y, "type": "wall"} for x, y in WALLS]
    return {"terrain": "".join(rows), "width": 128, "height": 128, "structures": structures, "resources": []}


def _tiles(section):
    x0, y0, x1, y1 = (int(v) for v in section["tiles"])
    return {(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}


def test_nintendo_land_keeps_every_rule_and_a_pack_pays_for_any_step():
    design, steps, _ = _bp()
    assert design["team"] == "commons" and design["commute"] is True and "land" not in design  # the collective's ground by contract: no deed to wait on
    assert factory.ledger_name(design, NAME) == NAME  # version 1 keeps the plain name
    assert factory.check(design, steps) == []  # boxes within a builder's reach, supported in order, every sign beside its building
    assert factory.check(design, steps, _world()) == []  # on land, inside the plots, off the claim signs, the roads and the walls
    places = [s for s in steps if s["kind"] == "place"]
    assert all(s["box_cells"] <= factory.PACK_CELLS and s["items"] <= factory.PACK_LIMIT for s in places)
    info = factory.summary(design, steps)
    assert 12000 <= info["blocks"] <= 16000  # a large land, within what the teams can raise between them
    assert info["materials"].get("ore", 0) <= 20  # ore is scarce: no metal anywhere
    assert {lid for s in steps for lid in factory.step_lots(s)} <= LOTS  # every step on the thirty-two lots of the site
    assert {lot_id(x, y)[:3] for s in places for x in range(s["tiles"][0], s["tiles"][2] + 1) for y in range(s["tiles"][1], s["tiles"][3] + 1)} <= set(design["plots"])


def test_a_theme_park_of_many_buildings_and_styles_over_half_the_site():
    design, steps, _ = _bp()
    sections = design["sections"]
    assert 28 <= len(sections) <= 36 and len({s["id"] for s in sections}) == len(sections)
    assert len({s["style"] for s in sections}) >= 10  # halls, towers, temples, a church, parks, pools, a fort, a statue, treehouses
    ground = set().union(*(_tiles(s) for s in sections))
    assert len(ground) >= 400  # tiles under buildings, lawns and ponds: half the forty by twenty
    tops = {sid: v["top"] for sid, v in factory.summary(design, steps)["sections"].items()}
    assert tops["peach-castle"] == tops["super-mushroom"] == factory.TOP_LEVEL and tops["sages-spire"] >= factory.TOP_LEVEL - 1  # the tallest at the ceiling
    assert sum(1 for s in sections if s["style"] not in FLAT and tops[s["id"]] <= 10) >= 15  # most of the rest low, so the skyline varies
    streets = [s for s in steps if s["section"] == "streets"]
    assert len({s["action"]["color"] for s in streets}) >= 2 and all(s["action"]["shape"] == "slab" and s["action"]["bz"] == 0 for s in streets)  # the circuit closes no tile


def test_every_section_has_a_sign_beside_it_on_a_free_tile():
    design, steps, _ = _bp()
    signs = {s["section"]: s for s in steps if s["kind"] == "build" and s["action"].get("type") == "sign"}
    sections = {str(s["id"]): s for s in design["sections"]}
    assert set(signs) == set(sections)  # one sign per building and monument, the section's last step
    low = {(x // 4, y // 4) for s in steps if s["kind"] == "place" for x, y, z in _box_cells(s["action"]) if z < 6}
    spots = [(s["action"]["x"], s["action"]["y"]) for s in signs.values()]
    assert len(set(spots)) == len(spots)  # one sign a tile
    for sid, section in sections.items():
        sign = signs[sid]
        x0, y0, x1, y1 = (int(v) for v in section["tiles"])
        sx, sy = sign["action"]["x"], sign["action"]["y"]
        assert sign["beside"] and x0 - 1 <= sx <= x1 + 1 and y0 - 1 <= sy <= y1 + 1 and not (x0 <= sx <= x1 and y0 <= sy <= y1), sid
        assert 3 <= len(sign["action"]["text"]) <= 200 and len(str(section["sign"]["text"])) <= 200 and sign["costs"] == {"wood": 1}
        assert (sx, sy) not in CENTRES and (sx, sy) not in low and lot_id(sx, sy) in LOTS, sid  # off the claim signs and every block below level 6


def test_the_claim_signs_keep_their_tiles_and_the_lawns_stay_open():
    design, steps, _ = _bp()
    low = {}
    for s in steps:
        if s["kind"] == "place":
            for x, y, z in _box_cells(s["action"]):
                if z < 6:
                    low.setdefault((x // 4, y // 4), set()).add(s["section"])
    assert not {c: low[c] for c in CENTRES if c in low}  # no block below level 6 on any lot's centre tile
    for section in design["sections"]:
        if section["style"] in FLAT:
            assert not any(int(k) for row in section.get("foundation") or [] for k in row), section["id"]  # a plinth would close the open tiles
    for s in steps:
        if s["kind"] == "place" and s["section"].startswith("tubes-"):
            cells = _box_cells(s["action"])
            assert min(z for _, _, z in cells) >= 6 or min(z for _, _, z in cells) == 0, s["id"]  # a tube closes only the tiles its legs stand on
    trunks = [(int(x), int(y)) for s in design["sections"] if s["style"] == "treehouse" for x, y in s["trunks"]]
    rows = (ROOT / "tests/fixtures/world/terrain.txt").read_text(encoding="utf-8").splitlines()
    assert all(rows[y][x] == "f" and (x, y) not in CENTRES for x, y in trunks)  # every trunk on forest, none on a claim sign


def test_the_history_walk_leads_to_the_museum_and_the_districts_hold_their_works():
    design, steps, _ = _bp()
    ids = {s["id"] for s in design["sections"]}
    assert {"peach-castle", "super-mushroom", "course-meadow", "goal-fort", "grandstand", "museum", "kirby-house", "healing-centre", "gym",
            "town-square", "lost-woods", "master-sword", "temple-of-time", "sages-spire", "landing-pad", "kong-treehouse", "barrel-tower"} <= ids
    history = [s for s in design["sections"] if s["sign"]["text"][:4].isdigit()]
    assert [s["sign"]["text"][:4] for s in history] == ["1889", "1980", "1983", "1989"]  # the company's own story, in order, toward the museum's door
    sections = {s["section"] for s in steps}
    assert {"tubes-warp-pipes", "tubes-question-blocks", "tubes-flagpole", "tubes-mushroom-cap", "tubes-kart", "tubes-gunship", "tubes-rope-bridges"} <= sections
    cap = [s for s in steps if s["section"] == "tubes-mushroom-cap"]
    assert all(s["supported"] and s["top"] >= 12 for s in cap)  # the red cap rests on the stem's top, three cells out all round
