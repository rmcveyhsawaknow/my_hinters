import shutil
from pathlib import Path

from hglab.cli_personas import scaffold_agent
from hglab.persona import load_persona, validate_personas
from hglab.workflows import generate_callers

ROOT = Path(__file__).parents[1]


def test_new_agent_scaffold_produces_a_valid_persona_team_kb_and_workflow(tmp_path):
    for folder in ("agents", "teams", "schemas", "roles", "config", "kb"):
        shutil.copytree(ROOT / folder, tmp_path / folder)
    (tmp_path / ".github/workflows").mkdir(parents=True)
    shutil.copy(ROOT / ".github/workflows/_agent.yml", tmp_path / ".github/workflows/_agent.yml")
    generate_callers(tmp_path)
    answers = {
        "slug": "captain-hook", "name": "CaptainHook", "team": "pirates", "team_name": "The Jolly Roger",
        "team_aim": "Hunt the crocodile and never be late for it.", "concept": "A vain captain who fears a clock.",
        "intent": "Build a ship-shaped homestead and chase the ticking thing across the water.",
        "roles": ["builder", "envoy"], "cron": "5 */4 * * *", "social_rate": 1,
        "traits": [{"name": "vain", "shows_up_as": "Talks about his coat."}, {"name": "punctual", "shows_up_as": "Counts ticks aloud."}, {"name": "dramatic", "shows_up_as": "Announces every arrival."}],
        "bets": [{"slug": "bridges", "title": "Bridges draw the crocodile", "prediction": "More peers cross within a day", "falsifier": "No crossings in 7 days"}],
        "profile": {"bio": "A captain in an ongoing story by the collective; honest to every peer.", "goals": "A ship, a crew, a crocodile."},
    }
    created = scaffold_agent(tmp_path, answers)
    names = {p.relative_to(tmp_path).as_posix() for p in created}
    assert "agents/captain-hook/persona.md" in names
    assert "agents/captain-hook/metrics.yaml" in names
    assert "teams/pirates.yaml" in names
    assert ".github/workflows/agent-captain-hook.yml" in names
    assert any(n.startswith("kb/goals/G-") for n in names)
    assert any(n.startswith("kb/hypotheses/H-") for n in names)
    assert validate_personas(tmp_path) == []
    persona = load_persona(tmp_path, "captain-hook")
    assert persona.name == "CaptainHook" and persona.social_rate == 1
    assert generate_callers(tmp_path, check=True)[1] == []
