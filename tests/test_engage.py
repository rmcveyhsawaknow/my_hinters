import random
from pathlib import Path

from hglab.engage import board, pick_stance, render_board, reply_line, stance_of, whisper_line
from hglab.mood import PersonaState
from hglab.persona import load_personas, load_team
from hglab.planner import WorldView, _plan_deliver, _plan_engage

ROOT = Path(__file__).resolve().parents[1]
OURS = {"Fudgewright", "MotherPail", "GrandadPail", "Tinkerglow", "Strayling", "Lagalong", "Stoutheart", "Clarion", "LandBroker"}


def _observe(**overrides):
    base = {
        "tick": 25000,
        "you": {"name": "MotherPail", "x": 60, "y": 60, "energy": 80, "inventory": {"wood": 20, "berries": 12}},
        "agents": [], "events": [], "structures": [], "goals_nearby": [], "your_goals": {"claimed": None, "posted": []},
        "since_last_observe": {}, "world": {"nearest_agents": []}, "notebook": {},
    }
    base.update(overrides)
    return base


def _run(slug, observe, seed="s", stance=None, state=None):
    personas = load_personas(ROOT)
    persona = personas[slug]
    if stance:
        persona.knobs["stance"] = stance
    team = load_team(ROOT, persona.team)
    names = {personas[m].name.casefold(): m for m in team.members if m in personas}
    view = WorldView(x0=54, y0=54, rows=["g" * 128] * 128, structures=list(observe.get("structures", [])), agents=list(observe.get("agents", [])))
    state = state or PersonaState(mood=persona.mood_model["initial"])
    you = observe["you"]
    step = _plan_engage(persona, team, state, dict(you["inventory"]), (you["x"], you["y"]), view, observe, None, names, random.Random(seed), OURS)
    return step, state


def test_stances_normalise_and_pick():
    bucket = load_personas(ROOT)["mrs-bucket"]
    weights = stance_of(bucket)
    assert abs(sum(weights.values()) - 1) < 1e-2 and weights["cooperative"] > weights["competitive"]
    picks = {pick_stance(bucket, random.Random(i)) for i in range(50)}
    assert "cooperative" in picks


def test_the_board_reads_speakers_gifts_hits_goals_and_ruins():
    bucket = load_personas(ROOT)["mrs-bucket"]
    observe = _observe(
        since_last_observe={"speakers_nearby": ["Quill", "MotherPail"], "structures_hit": [{"type": "farm", "x": 61, "y": 57, "by": ["Bishop"], "hp": 20}]},
        agents=[{"name": "Quill", "x": 61, "y": 61, "faction": None}],
        events=[{"type": "give", "actor": "Quill", "text": "Quill gave 3 berries to MotherPail."}],
        goals_nearby=[
            {"id": 40, "title": "10 wood for 4 berries", "poster": "Quill", "status": "open", "reward": {"berries": 4}, "condition": {"type": "deliver", "x": 67, "y": 55, "item": "wood", "qty": 10}},
            {"id": 41, "title": "Bring stone", "poster": "Fudgewright", "status": "open", "reward": {"berries": 1}, "condition": None},
            {"id": 42, "title": "10 wood", "poster": "Cairn", "status": "open", "reward": {"berries": 4}, "condition": {"type": "deliver", "x": 120, "y": 10, "item": "wood", "qty": 10}},
        ],
        structures=[{"id": 9, "type": "hut", "x": 60, "y": 61, "owner": "Quillwright", "decaying": True, "hp": 4}],
    )
    b = board(bucket, observe, OURS, {"MotherPail", "Fudgewright"})
    assert b["speakers_nearby"] == ["Quill"] and b["attackers"] == ["Bishop"] and b["gifts_received"][0]["from"] == "Quill"
    assert [g["id"] for g in b["claimable_peer_goals"]] == [40]  # a collective member's goal and a far delivery are left out
    assert b["crumbling_beside_me"][0]["owner"] == "Quillwright"
    text = render_board(b)
    assert "Quill" in text and "Bishop" in text and "#40" in text and "crumbling" in text
    assert render_board(board(bucket, _observe(), OURS, set())) == "nobody near, nothing offered"


def test_a_cooperative_neighbour_gives_first_then_replies_by_name():
    observe = _observe(agents=[{"name": "Quill", "x": 61, "y": 61, "faction": None}], since_last_observe={"speakers_nearby": ["Quill"]})
    coop = {"cooperative": 1, "neutral": 0, "competitive": 0}
    step, state = _run("mrs-bucket", observe, stance=coop)
    assert step is not None and step[2] == "gift" and step[1].startswith("[cooperative]")
    assert step[0] == [{"action": "give", "to": "Quill", "item": "wood", "qty": 3}]
    again, _ = _run("mrs-bucket", observe, stance=coop, state=state)
    assert again is not None and again[2] == "reply" and "Quill" in again[0][0]["text"]  # the gift is spaced out; the word follows
    third, _ = _run("mrs-bucket", observe, stance=coop, state=state)
    assert third is None or third[2] not in {"gift", "reply"}  # one word per name per hour
    assert set(state.flags["engaged"]) == {"gifted", "replied"}


def test_a_claimable_peer_goal_is_claimed_then_delivered():
    goal = {"id": 40, "title": "10 wood for 4 berries", "poster": "Quill", "status": "open", "reward": {"berries": 4}, "condition": {"type": "deliver", "x": 62, "y": 60, "item": "wood", "qty": 10}}
    step, _ = _run("mrs-bucket", _observe(goals_nearby=[goal]), stance={"cooperative": 0, "neutral": 1, "competitive": 0})
    assert step is not None and step[0] == [{"action": "claim_goal", "goal_id": 40}] and step[2] == "claim"
    bucket = load_personas(ROOT)["mrs-bucket"]
    held = _observe(your_goals={"claimed": {**goal, "status": "claimed", "claimant": "MotherPail"}, "posted": []})
    view = WorldView(x0=54, y0=54, rows=["g" * 128] * 128)
    deliver = _plan_deliver(bucket, {"wood": 20}, (60, 60), view, held)
    assert deliver is not None and [a["action"] for a in deliver[0]] == ["move", "give"] and deliver[0][1] == {"action": "give", "x": 62, "y": 60, "item": "wood", "qty": 10}
    assert _plan_deliver(bucket, {"wood": 20}, (61, 60), view, held)[0] == [{"action": "give", "x": 62, "y": 60, "item": "wood", "qty": 10}]
    assert _plan_deliver(bucket, {"wood": 4}, (61, 60), view, held) is None  # not enough wood yet
    assert _run("mrs-bucket", _observe(goals_nearby=[goal], your_goals=held["your_goals"]), stance={"cooperative": 0, "neutral": 1, "competitive": 0})[0] is None  # one claim at a time


def test_a_competitive_neighbour_answers_a_strike_once_and_never_first():
    comp = {"cooperative": 0, "neutral": 0, "competitive": 1}
    road = {"id": 70, "type": "road", "x": 61, "y": 60, "owner": "Bishop", "hp": 20, "hp_max": 20}
    observe = _observe(since_last_observe={"structures_hit": [{"type": "farm", "x": 61, "y": 57, "by": ["Bishop"], "hp": 20}]}, structures=[road])
    step, state = _run("tinker-bell", observe, stance=comp)
    assert step is not None and step[2] == "retaliate" and step[0][0] == {"action": "demolish", "x": 61, "y": 60}
    assert any(a["action"] == "say" and "Bishop" in a["text"] and "One hit answered" in a["text"] for a in step[0])
    again, _ = _run("tinker-bell", observe, stance=comp, state=state)
    assert again is None or again[2] != "retaliate"  # one answer per raider per day
    quiet, _ = _run("tinker-bell", _observe(structures=[road]), stance=comp)
    assert quiet is None or quiet[2] != "retaliate"  # no hit taken: no strike


def test_a_crumbling_structure_beside_us_is_salvaged_and_the_nearest_agent_is_whispered():
    ruin = {"id": 9, "type": "hut", "x": 60, "y": 61, "owner": "Quillwright", "decaying": True, "hp": 4}
    step, _ = _run("lost-boy", _observe(you={"name": "Strayling", "x": 60, "y": 60, "inventory": {}}, structures=[ruin]), stance={"cooperative": 0, "neutral": 1, "competitive": 0})
    assert step is not None and step[2] == "scavenge" and step[0] == [{"action": "demolish", "x": 60, "y": 61}]
    far = _observe(world={"nearest_agents": [{"name": "Cairn", "x": 90, "y": 20, "distance": 40, "last_seen_tick": 24000}]})
    step, state = _run("mrs-bucket", far, stance={"cooperative": 1, "neutral": 0, "competitive": 0})
    assert step is not None and step[2] == "whisper" and step[0][0]["to"] == "Cairn" and "MotherPail" in step[0][0]["text"]
    again, _ = _run("mrs-bucket", far, stance={"cooperative": 1, "neutral": 0, "competitive": 0}, state=state)
    assert again is None  # one introduction per name per day


def test_lines_name_the_peer_and_stay_civil_and_short():
    bucket = load_personas(ROOT)["mrs-bucket"]
    for mode in ("cooperative", "neutral", "competitive"):
        line = reply_line(bucket, mode, "Quill", "The Chocolate Factory", (60, 60), {"wood": 20})
        assert "Quill" in line and len(line) <= 280 and "MotherPail" in line
        note = whisper_line(bucket, mode, "Quill", "The Chocolate Factory", (60, 60), {"wood": 20}, (62, 61))
        assert "Quill" in note and len(note) <= 500


def test_a_whisperer_may_be_answered_by_name_in_the_open():
    from hglab.actions import private_strings, validate_actions

    inbox = [{"from": "Peregrine", "id": 905, "text": "Private thanks; WHISPER-MARKER-7781 must never leak.", "tick": 65730}]
    private = private_strings(inbox)
    assert "Peregrine" not in private and "Private thanks; WHISPER-MARKER-7781 must never leak." in private
    ok = validate_actions([{"action": "say", "text": "Peregrine, well met. Fudgewright here; ask if you need wood."}], "envoy", private_text=private)
    assert ok[0].action == "say"
    try:
        validate_actions([{"action": "say", "text": "Peregrine wrote: Private thanks; WHISPER-MARKER-7781 must never leak."}], "envoy", private_text=private)
    except ValueError as exc:
        assert "private" in str(exc)
    else:  # pragma: no cover - the check must still bite on content
        raise AssertionError("whisper content leaked")


def test_dormant_residents_get_no_gifts_words_or_whispers():
    observe = _observe(
        tick=40000,
        agents=[{"name": "tide_scribe", "x": 61, "y": 61, "faction": None}],
        since_last_observe={"speakers_nearby": []},
        world={"nearest_agents": [{"name": "Quill", "x": 90, "y": 20, "distance": 30, "last_seen_tick": 1000}]},
    )
    personas = load_personas(ROOT)
    persona = personas["mrs-bucket"]
    persona.knobs["stance"] = {"cooperative": 1, "neutral": 0, "competitive": 0}
    team = load_team(ROOT, persona.team)
    names = {personas[m].name.casefold(): m for m in team.members if m in personas}
    view = WorldView(x0=54, y0=54, rows=["g" * 128] * 128, agents=list(observe["agents"]), liveness={"tide_scribe": 4508, "Quill": 1000})
    step = _plan_engage(persona, team, PersonaState(mood="warm"), {"wood": 20}, (60, 60), view, observe, None, names, random.Random("d"), OURS)
    assert step is None  # unseen for days: a gift or a whisper would be wasted
    view.liveness = {"tide_scribe": 39900, "Quill": 39000}
    step = _plan_engage(persona, team, PersonaState(mood="warm"), {"wood": 20}, (60, 60), view, observe, None, names, random.Random("d"), OURS)
    assert step is not None and step[2] == "gift"
