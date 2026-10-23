import shutil
from pathlib import Path

import yaml

from hglab.persona import load_persona
from hglab.workflows import caller_text, generate_callers

ROOT = Path(__file__).parents[1]


def test_generated_callers_are_current_and_guarded():
    done, problems = generate_callers(ROOT, check=True)
    assert problems == []
    assert len(done) == len(list((ROOT / 'agents').glob('*/persona.md')))
    for path in (ROOT / ".github/workflows").glob("agent-*.yml"):
        text = path.read_text(encoding="utf-8")
        data = yaml.safe_load(text)
        job = data["jobs"]["agent"]
        assert "vars.HG_ENABLED == 'true'" in job["if"]
        assert "vars.HG_AGENT_" in job["if"]
        assert job["uses"] == "./.github/workflows/_agent.yml"
        assert "inherit" not in text
        assert set(job["secrets"]) == {"hg_key", "anthropic_api_key", "openai_api_key"}
        assert job["secrets"]["hg_key"].startswith("${{ secrets.HG_KEY_")
        assert data[True]["workflow_dispatch"]["inputs"]["dry_run"]["default"] is True  # YAML parses `on` as True
        slug = path.stem.removeprefix("agent-")
        has_work = bool(load_persona(ROOT, slug).knobs.get("work"))
        assert len(data[True]["schedule"]) == (5 if has_work else 4)  # the shift's schedule only for personas that work shifts (the fool has none)


def test_wonka_caller_uses_the_persona_cron_and_secret():
    wonka = load_persona(ROOT, "wonka")
    text = caller_text(wonka)
    assert wonka.knobs["cadence"]["cron"] in text
    assert wonka.secret_name == "HG_KEY_FUDGEWRIGHT"
    assert f"secrets.{wonka.secret_name}" in text
    assert f"vars.{wonka.variable_name} == 'on'" in text
    assert "jitter_minutes: 20" in text


def test_sync_check_fails_on_orphans_and_missing_callers(tmp_path):
    for folder in ("agents", "teams", "schemas", "roles", "config"):
        shutil.copytree(ROOT / folder, tmp_path / folder)
    workflows = tmp_path / ".github/workflows"
    workflows.mkdir(parents=True)
    shutil.copy(ROOT / ".github/workflows/_agent.yml", workflows / "_agent.yml")
    _done, problems = generate_callers(tmp_path, check=True)
    assert len(problems) == len(list((tmp_path / 'agents').glob('*/persona.md'))) and all("has no caller" in p for p in problems)
    generate_callers(tmp_path, check=False)
    assert generate_callers(tmp_path, check=True) == ([f".github/workflows/agent-{s}.yml" for s in sorted(p.name for p in (tmp_path / "agents").iterdir())], [])
    (workflows / "agent-ghost.yml").write_text("name: ghost\n", encoding="utf-8")
    _, problems = generate_callers(tmp_path, check=True)
    assert any("agent-ghost.yml has no persona" in p for p in problems)
    (workflows / "agent-wonka.yml").write_text("stale\n", encoding="utf-8")
    _, problems = generate_callers(tmp_path, check=True)
    assert any("wonka is stale" in p for p in problems)


def test_reusable_workflow_has_three_jobs_and_no_inherited_secrets():
    text = (ROOT / ".github/workflows/_agent.yml").read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    assert set(data["jobs"]) >= {"keepalive", "tick", "pulse", "retro"}
    assert "secrets: inherit" not in text
    assert "workflow_call" in data[True]
    assert data["jobs"]["tick"]["needs"] == "keepalive"
    assert "pull_request_target" not in text


def test_keepalive_runs_hourly_just_after_the_shift_so_agents_never_doze():
    from hglab.persona import load_persona
    from hglab.workflows import keepalive_cron

    wonka = load_persona(ROOT, "wonka")  # work shift at minute 3
    assert keepalive_cron(wonka) == "36 * * * *"
    assert '- cron: "36 * * * *"  # keepalive' in caller_text(wonka)
