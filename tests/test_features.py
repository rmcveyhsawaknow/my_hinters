from hglab.features import compact, compare


def _snap(**overrides):
    base = {
        "tick": 100, "api_version": "0.13.3", "guide_sha256": "a" * 64, "guide_actions": ["move", "say", "build"],
        "guide_blueprints": ["hut", "farm"], "event_types": ["move", "say", "build"], "structure_types": ["hut"],
        "factions": ["Wayfarers:open"], "agents": ["Quill", "Cairn"], "agent_count": 2, "world_stats": {},
    }
    base.update(overrides)
    return base


def test_first_look_reports_the_surface_and_undocumented_event_types():
    found = compare(None, _snap(event_types=["move", "say", "build", "mystery_event"]))
    kinds = [d["kind"] for d in found]
    assert kinds[0] == "first_look" and "unpublished_event_type" in kinds
    assert "mystery_event" in found[1]["text"]


def test_compare_names_every_kind_of_change():
    previous = compact(_snap())
    current = _snap(api_version="0.14.0", guide_sha256="b" * 64, guide_actions=["move", "say", "build", "trade"], guide_blueprints=["hut", "farm", "well"],
                    event_types=["move", "say", "build", "trade", "weather"], structure_types=["hut", "well"], factions=["Wayfarers:open", "Lanterns:invite"], agents=["Quill", "Cairn", "Clarion"], agent_count=3)
    kinds = {d["kind"] for d in compare(previous, current)}
    assert kinds == {"api_version", "guide_changed", "new_action", "new_blueprint", "new_event_type", "new_structure_type", "new_faction", "newcomers"}
    texts = " ".join(d["text"] for d in compare(previous, current))
    assert "`trade`" in texts and "weather (not in the guide yet)" in texts and "Lanterns (invite)" in texts
    assert compare(compact(current), current) == []


def test_blueprint_catalogue_is_parsed_from_the_guide_table():
    from hglab.features import blueprint_catalogue, catalogue_line

    guide = (
        "| type | cost | hp | terrain | function |\n|---|---|---|---|---|\n"
        "| `sign` | wood 1 | 10 | any walkable | holds `text` |\n"
        "| `hut` | wood 10, fiber 4 | 40 | any walkable | home: 3 energy per tick |\n"
        "| `cache` | system only | 10 | any | dropped items |\n"
    )
    rows = blueprint_catalogue(guide)
    assert set(rows) == {"sign", "hut", "cache"} and rows["hut"]["cost"] == "wood 10, fiber 4"
    line = catalogue_line(rows)
    assert line.startswith("2 things can be built") and "cache" not in line
    first = compare(None, {**_snap(), "blueprint_rows": rows})
    assert any(d["kind"] == "blueprint_catalogue" for d in first)


def test_changed_guide_rows_are_named():
    import hashlib

    from hglab.features import action_rows

    old_guide = "| `build` | `type, x?, y?` | 5 | On your tile or an adjacent tile; consumes materials. |\n| `say` | `text` | 1 | Heard within 8 tiles. |\n"
    new_guide = "| `build` | `type, x?, y?` | 5 | On your tile or an adjacent tile. Paid from your inventory first; the rest from storehouses within 1 tile. |\n| `say` | `text` | 1 | Heard within 8 tiles. |\n"
    old_rows = action_rows(old_guide)
    assert set(old_rows) == {"build", "say"}
    previous = {**_snap(), "guide_sha256": hashlib.sha256(old_guide.encode()).hexdigest(), "action_row_hashes": {k: hashlib.sha256(v.encode()).hexdigest()[:16] for k, v in old_rows.items()}}
    new_rows = action_rows(new_guide)
    current = {**_snap(), "guide_sha256": hashlib.sha256(new_guide.encode()).hexdigest(), "action_row_hashes": {k: hashlib.sha256(v.encode()).hexdigest()[:16] for k, v in new_rows.items()}, "action_row_text": new_rows}
    found = compare(previous, current)
    changed = [d for d in found if d["kind"] == "rule_changed"]
    assert len(changed) == 1 and "`build`" in changed[0]["text"] and "storehouses within 1 tile" in changed[0]["text"]


def test_an_api_bump_with_a_new_action_and_its_event_type_is_announced():
    previous = _snap()
    current = _snap(
        api_version="0.19.0", guide_actions=["move", "say", "build", "reject_claim"],
        event_types=["move", "say", "build", "goal_rejected"],
    )
    kinds = {d["kind"]: d["text"] for d in compare(previous, current)}
    assert "0.19.0" in kinds["api_version"]
    assert "reject_claim" in kinds["new_action"]
    assert "goal_rejected (documented)" in kinds["new_event_type"]


def test_the_notebook_snapshot_is_slim_and_still_finds_arrivals_and_rule_changes():
    import json

    from hglab.features import compact

    full = _snap(agents=[f"a{i}" for i in range(80)], agent_count=80, action_row_hashes={f"act{i}": "f" * 16 for i in range(30)})
    kept = compact(full)
    assert "agents" not in kept and all(len(v) == 8 for v in kept["action_row_hashes"].values())
    assert len(json.dumps(kept, separators=(",", ":"))) < 1500
    later = {
        **full, "agent_count": 83, "guide_sha256": "b" * 64,
        "action_row_hashes": {**full["action_row_hashes"], "act1": "0" * 16},
        "action_row_text": {"act1": "| `act1` | x | 1 | the new rule |"},
    }
    kinds = {d["kind"]: d["text"] for d in compare(kept, later)}
    assert kinds["newcomers"].startswith("3 new residents") and "act1" in kinds["rule_changed"]
    assert compare({}, later)[0]["kind"] == "first_look"


GUIDE_WITH_THREE_TABLES = """
## 5. The observe payload

| field | meaning |
|---|---|
| `you` | who you are |
| `view` | what you see |

## 6. Actions

| action | params | energy | rules and specific failures |
|---|---|---|---|
| `move` | `x, y` | 1 | walks |
| `say` | `text` | 1 | speaks |
| `leave_faction` | none | 0 | leaves |

| type | cost | hp | terrain | function |
|---|---|---|---|---|
| `sign` | wood 1 | 10 | any walkable | holds text |
| `hut` | wood 10, fiber 4 | 40 | any walkable | home |
| `cache` | system only | 10 | any | dropped items |
"""


def test_only_the_actions_table_counts_as_actions_and_only_blueprints_as_blueprints():
    from hglab.features import GUIDE_FORMAT, action_rows, blueprint_catalogue, compact

    assert sorted(action_rows(GUIDE_WITH_THREE_TABLES)) == ["leave_faction", "move", "say"]
    assert sorted(blueprint_catalogue(GUIDE_WITH_THREE_TABLES)) == ["cache", "hut", "sign"]
    stale = _snap(guide_actions=["move", "say"])  # a snapshot from before the fix: no guide_format
    current = _snap(guide_actions=["move", "say", "take", "write"], guide_format=GUIDE_FORMAT)
    assert not any(d["kind"] == "new_action" for d in compare(stale, current))
    fresh = compact(current)
    assert fresh["guide_format"] == GUIDE_FORMAT
    assert [d["kind"] for d in compare(fresh, {**current, "guide_actions": [*current["guide_actions"], "sing"]})] == ["new_action"]
