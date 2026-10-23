from hglab.features import compact, compare


def _snap(**overrides):
    base = {
        "tick": 100, "api_version": "0.13.3", "guide_sha256": "a" * 64, "guide_actions": ["move", "say", "build"],
        "guide_blueprints": ["hut", "farm"], "event_types": ["move", "say", "build"], "structure_types": ["hut"],
        "factions": ["Wayfarers:open"], "agents": ["Quill", "Cairn"], "agent_count": 2, "world_stats": {}, "guide_format": 2,
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

    old_guide = "| action | params | energy | rules |\n|---|---|---|---|\n| `build` | `type, x?, y?` | 5 | On your tile or an adjacent tile; consumes materials. |\n| `say` | `text` | 1 | Heard within 8 tiles. |\n"
    new_guide = "| action | params | energy | rules |\n|---|---|---|---|\n| `build` | `type, x?, y?` | 5 | On your tile or an adjacent tile. Paid from your inventory first; the rest from storehouses within 1 tile. |\n| `say` | `text` | 1 | Heard within 8 tiles. |\n"
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
    stale = _snap(guide_actions=["move", "say"], guide_format=1)  # a snapshot made the old way
    current = _snap(guide_actions=["move", "say", "take", "write"], guide_format=GUIDE_FORMAT)
    assert not any(d["kind"] == "new_action" for d in compare(stale, current))
    fresh = compact(current)
    assert fresh["guide_format"] == GUIDE_FORMAT
    assert [d["kind"] for d in compare(fresh, {**current, "guide_actions": [*current["guide_actions"], "sing"]})] == ["new_action"]


def test_weather_and_ruin_events_count_as_documented():
    found = compare(_snap(), _snap(event_types=["move", "say", "build", "weather_changed", "ruin"]))
    texts = [d["text"] for d in found if d["kind"] == "new_event_type"]
    assert texts and all("(documented)" in t for t in texts)


class _Response:
    def __init__(self, text):
        self.text = text
        self.is_success = True


class _Http:
    def __init__(self, guide):
        self.guide = guide

    def get(self, path):
        return _Response(self.guide)


class _FakeClient:
    """Just enough of the public API for a snapshot."""

    GUIDE = (
        "| action | params | energy | rules |\n|---|---|---|---|\n"
        "| `move` | `x, y` | 1 | walks |\n| `say` | `text` | 1 | speaks |\n| `build` | `type` | 5 | builds |\n"
        "| type | cost | hp | terrain | function |\n|---|---|---|---|---|\n| `hut` | wood 10, fiber 4 | 40 | any walkable | home |\n"
    )

    def __init__(self, version="0.33.1", guide=None):
        self.version = version
        self.http = _Http(guide or self.GUIDE)

    def request(self, method, path, params=None, **kwargs):
        if path == "/api/v1":
            return {"tick": 1000, "version": self.version}
        if path == "/api/v1/world/events":
            return {"events": [{"id": 1, "type": "move", "actor": "Quill"}, {"id": 2, "type": "build", "actor": "Quill", "data": {"type": "hut"}}, {"id": 3, "type": "eat", "actor": "Quill"}]}
        if path == "/live/world.json":
            return {"structures": [{"type": "hut"}], "stats": {}}
        if path == "/api/v1/world/factions":
            return {"factions": [{"name": "Wayfarers", "membership": "open"}]}
        if path == "/api/v1/world/agents":
            return {"agents": [{"name": "Quill"}, {"name": "Cairn"}]}
        raise AssertionError(path)


def test_the_watch_seeds_its_baseline_quietly_then_queues_real_changes_and_marks_what_was_said(tmp_path):
    from hglab.features import load_baseline, mark_announced, pending_news, queue_news, watch

    first = watch(tmp_path, _FakeClient(), archive_guide=False)
    assert first["queued"] == 0 and first["pending"] == 0 and load_baseline(tmp_path)["api_version"] == "0.33.1"  # the first look says nothing
    again = watch(tmp_path, _FakeClient(), archive_guide=False)
    assert again["discoveries"] == [] and again["pending"] == 0  # the same surface: nothing to say, and eat/build/move are not "new"
    bumped = _FakeClient(version="0.34.0", guide=_FakeClient.GUIDE.replace("| `build` | `type` | 5 | builds |", "| `build` | `type` | 5 | builds |\n| `trade` | `to, item` | 2 | trades |"))
    third = watch(tmp_path, bumped, archive_guide=False)
    kinds = {d["kind"] for d in third["discoveries"]}
    assert {"api_version", "new_action"} <= kinds and third["queued"] >= 2 and third["pending"] >= 2
    texts = [r["text"] for r in pending_news(tmp_path)]
    assert any("API 0.33.1 became 0.34.0" in x for x in texts) and any("`trade`" in x for x in texts)
    fourth = watch(tmp_path, bumped, archive_guide=False)
    assert fourth["queued"] == 0 and fourth["pending"] == third["pending"]  # queued once, still pending
    said = "News from the glass! " + " ".join(texts)
    assert mark_announced(tmp_path, [said], 1200) == len(texts) and pending_news(tmp_path) == []
    assert queue_news(tmp_path, [{"kind": "api_version", "text": texts[0]}], 1300) == []  # announced lately: not queued again
    assert len(queue_news(tmp_path, [{"kind": "api_version", "text": texts[0]}], 1300 + 3 * 8640 + 1)) == 1  # three days on it may be news again


def test_a_memory_trimmed_of_every_kind_seen_reports_no_new_kinds():
    previous = compact(_snap())
    previous.pop("event_types", None)
    previous.pop("event_types_seen", None)
    previous.pop("structure_types", None)
    previous.pop("structure_types_seen", None)
    kinds = {d["kind"] for d in compare(previous, _snap(event_types=["move", "say", "build", "eat"], structure_types=["hut", "farm"]))}
    assert "new_event_type" not in kinds and "new_structure_type" not in kinds


def test_the_state_note_sheds_the_kinds_seen_last_among_the_feature_trims():
    import json as _json

    from hglab.mood import STATE_TEXT_LIMIT, PersonaState, dump_state

    state = PersonaState(mood="bright")
    state.flags["features"] = {
        "api_version": "0.33.1", "event_types_seen": ["move", "say", "build", "eat", "gather", "give"],
        "block_pieces": {"material": ["wood"] * 120, "shape": ["cube"] * 120}, "observe_fields": [f"field_{i}" for i in range(120)],
        "action_row_hashes": {f"a{i}": "0123456789abcdef" for i in range(40)}, "agents": [f"agent{i}" for i in range(30)],
    }
    text = dump_state(state)
    assert len(text) <= STATE_TEXT_LIMIT
    features = _json.loads(text)["flags"]["features"]
    assert features["event_types_seen"] == ["move", "say", "build", "eat", "gather", "give"] and "block_pieces" not in features
