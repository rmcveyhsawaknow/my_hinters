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
