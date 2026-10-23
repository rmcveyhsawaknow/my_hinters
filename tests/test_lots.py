from hglab.lots import (
    all_lots,
    free_lots,
    homestead_ring,
    lot_anchor,
    lot_bounds,
    lot_id,
    lot_price,
    stake_text,
    staked_lots,
    total_lots,
)


def test_lot_ids_bounds_and_anchors():
    assert lot_id(67, 56) == "G05-SE" and lot_id(67, 52) == "G05-NE" and lot_id(60, 60) == "G06-NW" and lot_id(0, 0) == "A00-NW" and lot_id(127, 127) == "M12-SE"
    assert lot_bounds("G05-NE") == (65, 50, 69, 54) and lot_anchor("G05-NE") == (67, 52) and lot_bounds("G05-SE") == (65, 55, 69, 59)
    assert lot_bounds("M12-SE") == (125, 125, 127, 127)
    assert total_lots() == 676 and len(set(all_lots())) == 676
    structures = [{"type": "hut", "x": 67, "y": 56, "owner": "Quill"}, {"type": "road", "x": 2, "y": 2, "owner": "Cairn"}]
    assert "G05-SE" not in free_lots(structures) and "A00-NW" not in free_lots(structures) and len(free_lots(structures)) == 674
    ring = homestead_ring(structures, exclude_owner="LandBroker")
    assert "G05-NE" in ring and "G05-NW" in ring and "G05-SE" in ring and len(ring) == 9
    assert homestead_ring([{"type": "hut", "x": 67, "y": 56, "owner": "LandBroker"}], exclude_owner="LandBroker") == set()
    assert len(stake_text("G05-NE", "LandBroker")) <= 200 and stake_text("G05-NE", "LandBroker").startswith("Lot G05-NE")
    signs = [{"type": "sign", "x": 67, "y": 57, "owner": "LandBroker", "text": stake_text("G05-SE", "LandBroker")}, {"type": "sign", "x": 1, "y": 1, "owner": "LandBroker", "text": "Welcome"}]
    assert list(staked_lots(signs, "LandBroker")) == ["G05-SE"]


def test_the_lot_price_rises_as_free_lots_run_out():
    assert lot_price(1.0) == 5 and lot_price(0.9) == 6 and lot_price(0.5) == 10 and lot_price(0.25) == 20 and lot_price(0.1) == 50
    assert lot_price(0.01) == 50 and lot_price(0.0) == 50
    prices = [lot_price(s / 100) for s in range(100, 0, -5)]
    assert prices == sorted(prices)


def test_holdings_are_the_best_staked_lots_plus_every_ore_lot_and_the_floor_protects_spawn_and_homesteads():
    from hglab.lots import holding_text, holdings, lot_anchor, node_floor, stake_text

    rows = ["g" * 128] * 128
    terrain = lambda x, y: rows[y][x] if 0 <= x < 128 and 0 <= y < 128 else None
    lots = ["B02-NW", "B02-NE", "C02-NW", "C02-NE", "D02-NW"]
    signs = [{"type": "sign", "x": lot_anchor(lid)[0], "y": lot_anchor(lid)[1], "owner": "LandBroker", "text": stake_text(lid, "LandBroker")} for lid in lots]
    ore = {"kind": "ore", "x": lot_anchor("D02-NW")[0] + 1, "y": lot_anchor("D02-NW")[1], "amount": 9}
    stones = [{"kind": "stone", "x": lot_anchor("B02-NW")[0] + dx, "y": lot_anchor("B02-NW")[1], "amount": 20} for dx in (-1, 0, 1)]
    woods = [{"kind": "wood", "x": lot_anchor("C02-NE")[0], "y": lot_anchor("C02-NE")[1] + 1, "amount": 30}]
    hut = {"type": "hut", "x": lot_anchor("C02-NW")[0], "y": lot_anchor("C02-NW")[1], "owner": "Quill"}
    cfg = {"keep": 2, "always_ore": True, "floor": 0, "protect_spawn": 12, "protect_homesteads": True}
    held = holdings(cfg, [*signs, hut], terrain, [ore, *stones, *woods], [], 1000, "LandBroker")
    assert [h["lot"] for h in held] == ["B02-NW", "D02-NW"]  # stone three times, then the ore: the two most valuable; timber is third
    one = holdings({**cfg, "keep": 1}, [*signs, hut], terrain, [ore, *stones, *woods], [], 1000, "LandBroker")
    assert [h["lot"] for h in one] == ["B02-NW", "D02-NW"] and one[-1]["ore"] == 1 and one[-1]["rank"] == 2  # the ore lot is kept whatever its rank
    assert [h["lot"] for h in holdings({**cfg, "keep": 1, "always_ore": False}, [*signs, hut], terrain, [ore, *stones, *woods], [], 1000, "LandBroker")] == ["B02-NW"]
    assert holdings(None, signs, terrain, [], [], 1000, "LandBroker") == []
    text = holding_text(cfg, held[0], "LandBroker")
    assert text.startswith("Lot B02-NW: land office holding (stone near") and "Not for sale" in text and len(text) <= 200
    assert node_floor(cfg, (ore["x"], ore["y"]), [*signs, hut], "LandBroker") == 0  # worked to the floor
    assert node_floor(cfg, (66, 66), [*signs, hut], "LandBroker") == 5  # the spawn area keeps the collective floor
    assert node_floor(cfg, (hut["x"] + 2, hut["y"]), [*signs, hut], "LandBroker") == 5  # so does another resident's homestead ring
    assert node_floor({**cfg, "protect_homesteads": False}, (hut["x"] + 2, hut["y"]), [*signs, hut], "LandBroker") == 0
