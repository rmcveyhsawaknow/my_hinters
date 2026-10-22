import json
import random
from pathlib import Path

import httpx
import respx

from hglab.features import block_pieces, compact, compare, limits_line, observe_fields
from hglab.mood import PersonaState
from hglab.persona import load_personas, load_team
from hglab.planner import _plan_news, plan_wake

ROOT = Path(__file__).resolve().parents[1]
GUIDE = """## 5. The observe payload

| field | meaning |
|---|---|
| `tick`, `day` | clock |
| `you` | you |
| `blocks` | tiles with blocks |

## 6. Actions

| piece | choices |
|---|---|
| `material` | `wood` (paid with wood), `stone` (stone), `thatch` (fiber), `metal` (ore) |
| `shape` | `cube`, `slab`, `slope`, `door`, `window` |

- Rate limit: 120 requests per minute per agent, one budget shared by REST and MCP.
"""


def _snapshot(**over):
    base = {"tick": 46000, "api_version": "0.33.1", "guide_sha256": "a" * 64, "guide_actions": ["move", "say"], "guide_blueprints": ["hut"], "blueprint_rows": {}, "guide_format": 2, "action_row_hashes": {}, "action_row_text": {}, "event_types": ["move", "say"], "structure_types": ["hut"], "factions": [], "agents": ["Clarion"], "agent_count": 1, "world_stats": {}, "observe_fields": ["blocks", "day", "tick", "you"], "block_pieces": {"material": ["metal", "stone", "thatch", "wood"], "shape": ["cube", "door", "slab", "slope", "window"]}, "limits": "Rate limit: 120 requests per minute per agent"}
    base.update(over)
    return base


def test_the_guide_s_fields_pieces_and_limits_are_read_and_their_changes_named():
    assert observe_fields(GUIDE) == ["blocks", "day", "tick", "you"]
    assert block_pieces(GUIDE)["material"] == ["metal", "stone", "thatch", "wood"] and "window" in block_pieces(GUIDE)["shape"]
    assert limits_line(GUIDE).startswith("Rate limit: 120")
    previous = compact(_snapshot())
    current = _snapshot(observe_fields=["blocks", "day", "tick", "weather", "you"], block_pieces={"material": ["glass", "metal", "stone", "thatch", "wood"], "shape": ["cube", "door", "slab", "slope", "window"]}, limits="Rate limit: 60 requests per minute per agent", api_version="0.34.0")
    kinds = {d["kind"]: d["text"] for d in compare(previous, current)}
    assert kinds["api_version"] == "The game updated: API 0.33.1 became 0.34.0."
    assert "weather" in kinds["new_observe_field"] and "glass" in kinds["new_block_piece"] and kinds["limits_changed"].startswith("The rate limits changed")


def test_event_kinds_once_seen_stay_seen():
    previous = compact(_snapshot(event_types=["move", "say", "demolish"]))
    later = compact(_snapshot(event_types=["move", "say"]), previous)  # demolish fell out of the newest 300 events
    assert "demolish" in later["event_types_seen"]
    back = _snapshot(event_types=["move", "say", "demolish"])
    assert not [d for d in compare(later, back) if d["kind"].startswith("new_event")]  # not new again
    assert [d for d in compare(later, _snapshot(event_types=["move", "say", "blocks_crumbled"])) if "blocks_crumbled" in d["text"]]


def test_the_crier_says_the_news_whatever_planner_runs_and_only_once():
    personas = load_personas(ROOT)
    crier = personas["town-crier"]
    team = load_team(ROOT, crier.team)
    env = {"discoveries": ["The game updated: API 0.33.1 became 0.34.0.", "New block material to build with: glass."], "discovery_kinds": ["api_version", "new_block_piece"]}
    observe = {"tick": 46000, "you": {"name": "Clarion", "x": 64, "y": 54, "energy": 90, "inventory": {"wood": 10}}, "notebook": {}, "events": [], "agents": [], "structures": [], "resources": [], "goals_nearby": [], "your_goals": {}, "since_last_observe": {}, "world": {}}
    state = PersonaState(mood="bright")
    step = _plan_news(crier, state, observe, env)
    assert step is not None and step[2] == "news" and step[0][0]["action"] == "say"
    assert step[0][0]["text"].startswith("News from the glass!") and "0.34.0" in step[0][0]["text"] and "glass" in step[0][0]["text"] and len(step[0][0]["text"]) <= 280
    assert _plan_news(crier, state, observe, env) is None  # said once
    assert _plan_news(personas["wonka"], PersonaState(mood="mercurial"), observe, env) is None  # only the feature watch announces
    names = {personas[m].name.casefold(): m for m in team.members if m in personas}
    observe["view"] = {"x0": 58, "y0": 48, "rows": ["g" * 13] * 13}
    plan = plan_wake(crier, team, PersonaState(mood="bright"), observe, "act", random.Random("n"), teammates=None, terrain_rows=None, allowed=None, team_names=names, work=True, collective_names={p.name for p in personas.values()}, environment=env)
    assert plan["actions"][0]["action"] == "say" and plan["actions"][0]["text"].startswith("News from the glass!"), json.dumps(plan["actions"])


@respx.mock
def test_the_observatory_archives_the_guide_when_it_changes(tmp_path):
    from hglab.client import HinterglassClient
    from hglab.observatory import Observatory

    respx.get("https://hinterglass.com/api/v1").mock(return_value=httpx.Response(200, json={"version": "0.33.1", "tick": 46000}))
    guide = respx.get("https://hinterglass.com/agent-guide.md").mock(return_value=httpx.Response(200, text=GUIDE))
    observatory = Observatory(HinterglassClient(), tmp_path)
    first = observatory.collect_guide()
    assert any(p.name == "versions.jsonl" for p in first) and any(p.name.startswith("agent-guide-") for p in first)
    assert observatory.collect_guide() == []  # nothing changed: nothing written
    guide.mock(return_value=httpx.Response(200, text=GUIDE + "\n- A new rule.\n"))
    second = observatory.collect_guide()
    assert any(p.name.startswith("agent-guide-") for p in second)
    lines = (tmp_path / "data/guide/versions.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and json.loads(lines[1])["api_version"] == "0.33.1"


def test_no_guide_means_no_undocumented_event_announcement():
    first = compare(None, _snapshot(guide_sha256="", guide_actions=[], event_types=["move", "say", "build"]))
    assert [d for d in first if d["kind"] == "first_look"] and not [d for d in first if d["kind"] == "unpublished_event_type"]
