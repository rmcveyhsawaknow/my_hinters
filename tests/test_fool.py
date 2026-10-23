"""The town fool, the local model route, and the rule that every run says its model."""

import json
from pathlib import Path

from hglab.fixtures import FixtureClient, load_fixture
from hglab.fool import insights, numbers_of, pick, rephrase
from hglab.lease import acquire
from hglab.mood import PersonaState
from hglab.persona import load_personas, load_team
from hglab.planner import _plan_fool, _plan_model_note
from hglab.wake import persona_wake

ROOT = Path(__file__).parents[1]
FIX = ROOT / "tests/fixtures"


def _public():
    agents = [{"name": f"A{i}", "faction": "Chocolate Factory" if i < 8 else None, "last_seen_tick": 9000 if i < 12 else 100} for i in range(20)]
    structures = [{"type": "road"} for _ in range(60)] + [{"type": "hut"} for _ in range(10)] + [{"type": "farm"} for _ in range(5)]
    resources = [{"kind": "wood"} for _ in range(40)] + [{"kind": "ore"} for _ in range(3)] + [{"kind": "stone"} for _ in range(12)]
    events = [{"type": "move", "tick": 9500} for _ in range(70)] + [{"type": "say", "tick": 9600} for _ in range(20)] + [{"type": "goal_posted", "tick": 9700}, {"type": "goal_posted", "tick": 9800}]
    return agents, structures, resources, events


def test_the_fool_sees_the_big_picture_in_plain_numbers():
    agents, structures, resources, events = _public()
    facts = insights(agents=agents, structures=structures, resources=resources, events=events, tick=10000, collective={f"A{i}" for i in range(15)}, season="autumn", weather="clear")
    kinds = [f["kind"] for f in facts]
    assert {"population", "families", "factions", "structures", "resources", "activity", "goals", "season"} <= set(kinds)
    by = {f["kind"]: f["text"] for f in facts}
    assert by["population"].startswith("20 of us live behind the glass now, and 12 moved since yesterday.")
    assert "60 of them are roads: more than everything else put together" in by["structures"]
    assert "3 ore nodes" in by["resources"] and "40 wood nodes" in by["resources"]
    assert "92 things done since yesterday, 70 were steps: 76%" in by["activity"]
    assert by["goals"].startswith("2 goals went up since yesterday and nobody claimed one")
    assert "Winter is 1 day away" in by["season"]
    assert facts[0]["weight"] >= facts[-1]["weight"] and all(f["key"] for f in facts)
    assert pick(facts, {facts[0]["key"]}) == facts[1] and pick(facts, {f["key"] for f in facts}) is None
    assert insights(agents=[], structures=[], resources=[], events=[], tick=1) == []


def test_the_fool_says_the_most_striking_unsaid_fact_once_and_moves_on():
    personas = load_personas(ROOT)
    fool = personas["town-fool"]
    assert fool.quirk["type"] == "big_picture" and fool.knobs["model_route"] == "fool" and fool.knobs["challenge_route"] == "fool" and "work" not in fool.knobs
    agents, structures, resources, events = _public()
    env = {"insights": insights(agents=agents, structures=structures, resources=resources, events=events, tick=10000, season="winter")}
    state = PersonaState(mood="wondering")
    observe = {"tick": 10000, "you": {"name": fool.name}, "events": [], "notebook": {}}
    first = _plan_fool(fool, state, observe, env)
    assert first is not None and first[2] == "fool" and first[0][0]["action"] == "say" and first[0][0]["text"] == env["insights"][0]["text"]
    second = _plan_fool(fool, state, observe, env)
    assert second is not None and second[0][0]["text"] == env["insights"][1]["text"]  # the first fact was said; the next one follows
    assert _plan_fool(personas["town-crier"], state, observe, env) is None  # only the fool's quirk speaks these
    assert len(first[0][0]["text"]) <= fool.voice["max_say_chars"]


def test_the_local_model_puts_the_fact_in_the_fools_words_and_the_plain_sentence_stands_when_a_number_is_lost():
    fool = load_personas(ROOT)["town-fool"]
    fact = "20 of us live behind the glass now, and 12 moved since yesterday."
    plan = {"actions": [{"action": "say", "text": fact}], "approach": "fool"}

    class Result:
        def __init__(self, line):
            self.value = {"line": line}
            self.input_tokens, self.output_tokens, self.model, self.provider = 70, 20, "qwen3.5:9b", "ollama"

    usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    extras = {}
    out = rephrase(plan, fool, ROOT, usage, extras, caller=lambda prompt, schema: Result("Twenty of us live here, says the count: 20, and 12 of them moved since yesterday. The rest sit still."))
    assert out["actions"][0]["text"].startswith("Twenty of us") and extras["fool_line"] == "model"
    assert usage["calls"] == 1 and usage["model"] == "qwen3.5:9b" and usage["provider"] == "ollama" and usage["route"] == "fool"
    plan2 = {"actions": [{"action": "say", "text": fact}], "approach": "fool"}
    out2 = rephrase(plan2, fool, ROOT, {}, extras := {}, caller=lambda prompt, schema: Result("Lots of us live here and some moved."))
    assert out2["actions"][0]["text"] == fact and extras["fool_line"] == "template"  # the numbers were dropped: the plain fact stands
    plan3 = {"actions": [{"action": "say", "text": fact}], "approach": "fool"}

    def failing(prompt, schema):
        raise ConnectionError("ollama is down")

    out3 = rephrase(plan3, fool, ROOT, {}, extras := {}, caller=failing)
    assert out3["actions"][0]["text"] == fact and extras["fool_line"] == "template" and "ollama is down" in extras["fool_model_error"]
    assert numbers_of("4 goals, 76% of 92") == ["4", "76%", "92"]


def test_the_fool_route_is_a_local_model_that_never_falls_back_to_a_vendor(monkeypatch):
    from hglab import llm
    from hglab.llm import route_config, structured_call

    monkeypatch.setattr("hglab.llm.get_secret", lambda name, root=None: None)  # no vendor key at all
    selected = route_config("fool", ROOT)
    assert selected["provider"] == "ollama" and selected["model"] == "qwen3.5:9b" and selected["base_url"].startswith("http://127.0.0.1")
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"model": "qwen3.5:9b", "message": {"content": json.dumps({"line": "Twenty of us live here."})}, "done_reason": "stop", "prompt_eval_count": 66, "eval_count": 12}

    def fake_post(url, json=None, timeout=None):
        calls.append((url, json))
        return Response()

    monkeypatch.setattr(llm.httpx, "post", fake_post) if hasattr(llm, "httpx") else monkeypatch.setattr("httpx.post", fake_post)
    result = structured_call("fool", "say something", {"type": "object", "properties": {"line": {"type": "string"}}, "required": ["line"]}, root=ROOT, output_tokens=120)
    assert result.value == {"line": "Twenty of us live here."} and result.provider == "ollama" and result.model == "qwen3.5:9b" and result.input_tokens == 66
    url, payload = calls[0]
    assert url == "http://127.0.0.1:11434/api/chat" and payload["model"] == "qwen3.5:9b" and payload["think"] is False and payload["format"]["additionalProperties"] is False and payload["options"]["num_predict"] == 120


def test_the_fools_challenges_go_to_its_local_route_too(monkeypatch):
    from hglab import cli

    seen = {}

    class Result:
        def __init__(self):
            self.value = {"answer": "12"}
            self.input_tokens, self.output_tokens, self.model, self.provider = 10, 2, "qwen3.5:9b", "ollama"

    def fake_call(route, prompt, schema, **kwargs):
        seen["route"] = route
        return Result()

    monkeypatch.setattr(cli, "structured_call", fake_call)
    monkeypatch.setattr(cli, "response_schema", lambda prompt: {"type": "object", "properties": {"answer": {"type": "string"}}})
    monkeypatch.setattr(cli, "finalize_answer", lambda prompt, value: value)
    usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    cli.challenge_responder("What is 7 + 5? Reply with the key answer.", usage, "fool")
    assert seen["route"] == "fool" and usage["route"] == "fool" and usage["provider"] == "ollama"
    cli.challenge_responder("What is 7 + 5? Reply with the key answer.", {"calls": 0, "input_tokens": 0, "output_tokens": 0})
    assert seen["route"] == "challenge"  # everyone else keeps the challenge route


def test_every_run_records_its_model_and_the_profile_says_it_once_a_day(tmp_path):
    from hglab.actions import allowed_for

    for role in ("builder", "surveyor", "experimenter", "envoy", "navigator"):
        assert "set_profile" in allowed_for(role), role
    personas = load_personas(ROOT)
    nibs = personas["nibs"]
    observe = {"tick": 5000, "you": {"name": nibs.name, "bio": str(nibs.profile["bio"])}}
    state = PersonaState(mood="cheerful")
    assert _plan_model_note(nibs, observe, state) is None  # no label this wake: nothing to say
    observe["_model_label"] = "claude-haiku-5-5 on route tick"
    step = _plan_model_note(nibs, observe, state)
    assert step is not None and step[0][0]["action"] == "set_profile" and step[0][0]["bio"].endswith("Thinks with claude-haiku-5-5 on route tick.") and len(step[0][0]["bio"]) <= 500
    assert _plan_model_note(nibs, observe, state) is None  # once a day
    later = {"tick": 5000 + 8641, "you": {"name": nibs.name, "bio": step[0][0]["bio"]}, "_model_label": "claude-haiku-5-5 on route tick"}
    assert _plan_model_note(nibs, later, PersonaState(mood="cheerful")) is None  # the profile already says it
    changed = {"tick": 5000 + 8641, "you": {"name": nibs.name, "bio": step[0][0]["bio"]}, "_model_label": "claude-opus-5-5 on route tick_opus"}
    renewed = _plan_model_note(nibs, changed, PersonaState(mood="cheerful"))
    assert renewed is not None and renewed[0][0]["bio"].count("Thinks with") == 1 and renewed[0][0]["bio"].endswith("Thinks with claude-opus-5-5 on route tick_opus.")
    # A note that names something else is wrong in public: replaced after two hours, not a day
    wrong = {"tick": 5000 + 800, "you": {"name": nibs.name, "bio": "A builder. Thinks with rules only (no model)."}, "_model_label": "claude-haiku-5-5 on routes tick and talk"}
    soon = PersonaState(mood="cheerful")
    soon.flags["last_profile_tick"] = 5000
    fixed = _plan_model_note(nibs, wrong, soon)
    assert fixed is not None and fixed[0][0]["bio"].endswith("Thinks with claude-haiku-5-5 on routes tick and talk.") and "rules only" not in fixed[0][0]["bio"]
    soon.flags["last_profile_tick"] = 5000 + 700
    assert _plan_model_note(nibs, wrong, soon) is None  # not within two hours of the last note
    fool = personas["town-fool"]
    dotted = {"tick": 90000, "you": {"name": fool.name, "bio": "Sits where the paths cross. Thinks with qwen3.5:9b on route fool."}, "_model_label": "qwen3.5:9b on route fool_b"}
    again = _plan_model_note(fool, dotted, PersonaState(mood="wondering"))
    assert again is not None and "5:9b on route fool." not in again[0][0]["bio"] and again[0][0]["bio"].count("Thinks with") == 1  # a dotted model id does not end the note early
    fixture = load_fixture(FIX / "observe/nibs.json")
    client = FixtureClient(fixture)
    lease = acquire(client, nibs.name)
    result = persona_wake(persona=nibs, team=load_team(ROOT, "neverland"), personas=personas, client=client, lease=lease, root=ROOT, output_dir=tmp_path, dry_run=True, work=True, seed="model", model_label="rules only (no model)")
    record = result[0] if isinstance(result, tuple) else result
    assert record["thinking"]["model"] == "heuristic" and record["thinking"]["label"] == "rules only (no model)" and record["thinking"]["planner"] == "heuristic"
    assert "_model_label" not in json.dumps(record["observe"])
    profile = next((a for a in record["actions"] if a["action"] == "set_profile"), None)
    assert profile is not None and profile["bio"].endswith("Thinks with rules only (no model).")


def test_the_label_names_the_identitys_models_even_on_a_rules_only_shift(monkeypatch):
    """A work shift plans by rules, but the identity still thinks on its route and speaks its shift lines on talk."""
    from hglab import cli_personas

    monkeypatch.setattr("hglab.llm.get_secret", lambda name, root=None: None)
    monkeypatch.setattr(cli_personas, "_model_key", lambda root: True)
    personas = load_personas(ROOT)
    label = cli_personas._model_label
    assert label(ROOT, personas["nibs"], None) == "claude-haiku-5-5 on routes tick and talk"
    assert label(ROOT, personas["town-crier"], None) == "claude-sonnet-5-5 on route tick_premium and claude-haiku-5-5 on route talk for shift lines"
    assert label(ROOT, personas["wonka"], None).startswith("claude-opus-5-5 on route tick_opus")
    assert label(ROOT, personas["loompa-mason"], None) == "claude-haiku-5-5 on route tick"  # its hats cannot say, so no shift lines
    assert label(ROOT, personas["town-fool"], None) == "qwen3.5:9b on route fool"
    monkeypatch.setattr(cli_personas, "_model_key", lambda root: False)
    assert label(ROOT, personas["nibs"], None) == "rules only (no model)"  # no vendor key: nothing thinks for it
    assert label(ROOT, personas["town-fool"], None) == "qwen3.5:9b on route fool"  # the local model needs no key


def test_the_fools_fixture_wake_says_one_plain_truth_and_nothing_else_costly(tmp_path):
    personas = load_personas(ROOT)
    fool = personas["town-fool"]
    observe = load_fixture(FIX / "observe/town-fool.json")
    client = FixtureClient(observe)
    lease = acquire(client, fool.name)
    agents, structures, resources, events = _public()
    result = persona_wake(
        persona=fool, team=load_team(ROOT, fool.team), personas=personas, client=client, lease=lease, root=ROOT, output_dir=tmp_path,
        dry_run=True, seed="fool", public_agents=agents, public_structures=structures, public_resources=resources, public_events=events,
        environment={"tick": 10000, "pace": "quiet", "hour": {"all": 0}, "day": {"all": 0}, "peers_active": []},
    )
    record = result[0] if isinstance(result, tuple) else result
    says = [a for a in record["actions"] if a["action"] == "say"]
    assert record["approach"] == "fool" and len(says) == 1 and numbers_of(says[0]["text"]) and record["thinking"]["model"] == "heuristic"
    assert all(a["action"] in {"say", "set_profile", "remember", "eat"} for a in record["actions"])
