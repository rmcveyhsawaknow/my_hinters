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
