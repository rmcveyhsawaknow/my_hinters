from datetime import date

from hglab.kb import build_index, make_id, validate


def test_kb_ids_are_stable_and_type_prefixed():
    assert make_id("hypothesis", "Road cost!", date(2026, 10, 17)) == "H-20261017-road-cost"


def test_seed_items_validate_and_index(tmp_path):
    root = tmp_path
    (root / "schemas").mkdir()
    (root / "kb/goals").mkdir(parents=True)
    (root / "schemas/kb-item.json").write_text(
        '{"type":"object","required":["id","type","title","status","created","updated","author_runtime","roles","links"]}',
        encoding="utf-8",
    )
    (root / "kb/NORTH_STAR.md").write_text("# North Star\n", encoding="utf-8")
    (root / "kb/goals/G-20260101-test.md").write_text(
        "---\nid: G-20260101-test\ntype: goal\ntitle: Test\nstatus: proposed\n"
        "created: 2026-01-01\nupdated: 2026-01-01\nauthor_runtime: human\nroles: []\nlinks: []\n---\n",
        encoding="utf-8",
    )
    assert validate(root) == []
    path = build_index(root)
    assert "G-20260101-test" in path.read_text(encoding="utf-8")
