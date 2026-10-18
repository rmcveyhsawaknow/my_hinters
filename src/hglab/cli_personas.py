"""CLI commands for personas, teams, influence, the Pulse, the cast, and deployment.

Registered into the main ``hglab`` app by ``cli.register_persona_commands``. Everything
here runs from fixtures with no key; live paths need the identity key and stay behind
``--dry-run`` until the owner enables live operation.
"""

from __future__ import annotations

import io
import json
import os
import random
import re
import subprocess
import tarfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer
import yaml

from hglab.client import HinterglassClient, HinterglassError
from hglab.data import latest_tick, load_events, load_history, load_runs
from hglab.fixtures import FixtureClient, load_fixture, load_terrain_rows
from hglab.influence import SIGNALS, compute_team, incoming_effects
from hglab.judge import judge_available, run_judge
from hglab.kb import make_id
from hglab.lease import acquire, release
from hglab.limits import action_limits
from hglab.measures import MEASURES, load_kb_items
from hglab.persona import (
    Persona,
    Team,
    enforce_knobs,
    list_persona_slugs,
    load_metrics,
    load_persona,
    load_personas,
    load_team,
    load_teams,
    persona_by_name,
    team_say_count,
    validate_personas,
)
from hglab.pulse import compute_pulse, render_community, render_pulse, render_team, write_pulse
from hglab.secrets import get_api_key, get_secret
from hglab.wake import persona_prompt, persona_wake, plan_schema
from hglab.watchdog import WAKE_WATCHDOG_SECONDS, armed
from hglab.workflows import caller_path, generate_callers

persona_app = typer.Typer(help="Personas: validate, inspect, create, and check in-world names.")
team_app = typer.Typer(help="Teams: territory and membership.")
influence_app = typer.Typer(help="Influence signals between teammates.")
community_app = typer.Typer(help="The whole cast: status board, rounds, scenes.")
deploy_app = typer.Typer(help="Promote an agent from local play to GitHub Actions.")
reports_app = typer.Typer(help="Reports branch helpers.")

FIXTURES = Path("tests/fixtures")
SCENES: dict[str, list[tuple[str, str]]] = {
    "boast_and_audit": [("grandpa-joe", "burst"), ("wonka", "act")],
    "second_star": [("tinker-bell", "act"), ("nibs", "act"), ("tootles", "act")],
    "lean_week": [("mrs-bucket", "act"), ("grandpa-joe", "rest"), ("wonka", "act")],
    "distraction": [("lost-boy", "distracted"), ("tinker-bell", "act")],
}


def root_dir() -> Path:
    return Path.cwd()


def resolve_persona(root: Path, agent: str) -> Persona:
    persona = persona_by_name(root, agent)
    if persona is None:
        raise typer.BadParameter(f"no persona named {agent!r}; see `hglab persona list`")
    return persona


def team_of(root: Path, persona: Persona) -> Team | None:
    try:
        return load_team(root, persona.team)
    except FileNotFoundError:
        return None


# --- shared data assembly ----------------------------------------------------


def fetch_public_events(client: HinterglassClient, pages: int = 20) -> list[dict[str, Any]]:
    """Read-only public event pages (no key); stops at the first repeated cursor."""
    events: list[dict[str, Any]] = []
    before: Any = None
    seen: set[Any] = set()
    for _ in range(pages):
        params: dict[str, Any] = {"limit": 100}
        if before is not None:
            params["before"] = before
        page = client.public_events(**params)
        rows = page.get("events", [])
        if not rows:
            break
        events.extend(r for r in rows if isinstance(r, dict))
        before = page.get("next_before") or page.get("before") or rows[-1].get("id")
        if before is None or before in seen:
            break
        seen.add(before)
    return events


def gather_inputs(
    root: Path,
    *,
    fixtures: bool,
    events_paths: list[Path],
    runs_paths: list[Path],
    fetch_public: bool,
    tick: int | None,
) -> dict[str, Any]:
    personas = load_personas(root)
    teams = load_teams(root)
    paths = list(events_paths)
    if fixtures:
        paths.append(root / FIXTURES / "world/events.jsonl")
    elif (root / "data/events").is_dir():
        paths.append(root / "data/events")
    events = load_events(paths)
    if fetch_public:
        try:
            events = load_events([]) + _merge(events, fetch_public_events(HinterglassClient()))
        except (HinterglassError, OSError) as exc:
            typer.echo(f"public fetch failed ({exc}); using local events only", err=True)
    runs_by_slug: dict[str, list[dict[str, Any]]] = {}
    for slug, persona in personas.items():
        extra = list(runs_paths)
        if fixtures:
            extra.append(root / FIXTURES / "runs" / f"{slug}.jsonl")
        runs_by_slug[slug] = load_runs(root, persona.name, slug, extra, include_local=not fixtures)
    all_runs = [r for rows in runs_by_slug.values() for r in rows]
    now_tick = tick or latest_tick(events, all_runs, fallback=0)
    if fixtures and not tick:
        for observe_path in (root / FIXTURES / "observe").glob("*.json"):
            try:
                now_tick = max(now_tick, int(json.loads(observe_path.read_text(encoding="utf-8")).get("tick", 0)))
            except (json.JSONDecodeError, ValueError):
                continue
    return {"personas": personas, "teams": teams, "events": events, "runs": runs_by_slug, "kb": load_kb_items(root), "tick": now_tick}


def _merge(local: list[dict[str, Any]], remote: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id = {e.get("id"): e for e in local}
    by_id.update({e.get("id"): e for e in remote if e.get("id") is not None})
    return sorted(by_id.values(), key=lambda e: (int(e.get("tick", 0)), int(e.get("id", 0))))


# --- tick (persona path) -----------------------------------------------------


def persona_tick(root: Path, persona: Persona, **kwargs: Any) -> dict[str, Any]:
    """One wake under a watchdog.

    A wake that stalls (a network call that never returns, a model call that hangs) prints
    every thread's stack to stderr and exits non-zero once the jitter plus ten minutes have
    passed, instead of holding the runner and the lease until the job timeout.
    """
    jitter = int(kwargs.get("jitter_minutes", 0) or 0)
    seconds = min(jitter, 25) * 60 + WAKE_WATCHDOG_SECONDS
    if kwargs.get("scheduled") and not kwargs.get("quiet"):
        typer.echo(f"watchdog: this wake must finish within {seconds // 60} minutes")
    with armed(seconds):
        return _persona_tick(root, persona, **kwargs)


def _persona_tick(
    root: Path,
    persona: Persona,
    *,
    role: str | None,
    dry_run: bool,
    fixture: Path | None,
    planner: str,
    seed: str | None,
    events_paths: list[Path],
    jitter_minutes: int,
    scheduled: bool,
    force_mode: str | None = None,
    quiet: bool = False,
    extra_events: list[dict[str, Any]] | None = None,
    work: bool = False,
    inputs: dict[str, Any] | None = None,
) -> dict[str, Any]:
    personas = load_personas(root)
    team = team_of(root, persona)
    author_runtime = os.environ.get("HGLAB_RUNTIME", "human")
    usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    roster: dict[str, tuple[int, int]] = {}
    owned: dict[str, int] = {}
    world: dict[str, Any] = {}

    def progress(message: str) -> None:
        """Phase markers for the Actions log, so a stalled wake shows where it stopped."""
        if scheduled and not quiet:
            typer.echo(f"  - {message}")

    if fixture is not None:
        payload = load_fixture(fixture)
        if extra_events:
            payload["events"] = list(payload.get("events", [])) + list(extra_events)
        client: Any = FixtureClient(payload)
        inputs = inputs or gather_inputs(root, fixtures=True, events_paths=events_paths, runs_paths=[], fetch_public=False, tick=None)
    else:
        api_key = get_api_key(persona.name, root)
        if not api_key:
            raise typer.BadParameter(f"no key configured for {persona.name}; use --fixture for a keyless dry run")
        client = HinterglassClient(api_key=api_key)
        if jitter_minutes > 0:
            delay = random.Random().uniform(0, min(jitter_minutes, 25) * 60)
            typer.echo(f"jitter: sleeping {delay / 60:.1f} minutes")
            time.sleep(delay)
        inputs = inputs or gather_inputs(root, fixtures=False, events_paths=events_paths, runs_paths=[], fetch_public=not work, tick=None)
        roster = public_teammate_positions(personas, team)
        world = fetch_public_world()
        owned = structure_counts(world, persona.name)
        progress(f"inputs: {len(inputs['events'])} public events, world tick {inputs['tick']}")
    if work:
        planner = "heuristic"
    if planner == "auto":
        planner = "llm" if fixture is None and _model_key(root) else "heuristic"
    if planner == "llm" and not _model_key(root):
        raise typer.BadParameter("the llm planner needs ANTHROPIC_API_KEY or OPENAI_API_KEY")
    budget_hold = ""
    if planner == "llm":
        from hglab.budget import status as budget_status

        state = budget_status(root)
        if state.over:
            budget_hold = state.reason
            planner = "heuristic"
            typer.echo(f"budget hold: {budget_hold}; using the deterministic planner this wake")
    incoming: dict[str, dict[str, Any]] = {}
    if team is not None and inputs["tick"]:
        team_result = compute_team(team, personas, inputs["events"], inputs["runs"], inputs["tick"], kb_items=inputs["kb"])
        incoming = incoming_effects(team_result, persona.slug)
    environment = build_environment(root, persona, team, personas, inputs, live=fixture is None, public_world=world or (fixture_world(root) if fixture is not None else None))
    progress("environment: digest ready" + (", feature snapshot taken" if environment and environment.get("features_now") else ""))
    if fixture is not None:
        terrain_path = root / FIXTURES / "world/terrain.txt"
        terrain = load_terrain_rows(terrain_path) if terrain_path.is_file() else None
    else:
        terrain = terrain_rows_from_world(world)  # the public map; the fixture map is a different world
    lease = acquire(client, persona.name)
    if lease is None:
        if scheduled:
            typer.echo(f"{persona.name}: lease held by another runtime (local play or an overlapping job); skipping this wake")
            raise typer.Exit(code=0)
        raise typer.BadParameter(f"identity {persona.name} already has an active lease")
    progress("lease acquired")
    llm_call = None
    if planner == "llm":
        llm_call = _make_llm_call(root, persona, team, role or persona.roles[0], usage, worn=role or "+".join(persona.roles))
    try:
        observe = client.observe()
        progress(f"observe: tick {observe.get('tick')}, energy {(observe.get('you') or {}).get('energy')}")
        if observe.get("challenge"):
            if fixture is None or _model_key(root):
                from hglab.cli import answer_daily_challenge

                answer_daily_challenge(client, observe, usage)
            else:
                typer.echo("verification challenge pending in the fixture; no model key to answer it (dry run continues)")
    except Exception:
        release(client, lease)
        raise
    if force_mode:
        _force_mode(persona, force_mode)
    else:
        _restore_mode()
    progress(f"planning: {planner} planner" + (f" ({budget_hold})" if budget_hold else ""))
    record = persona_wake(
        persona=persona, team=team, personas=personas, client=client, lease=lease, root=root,
        output_dir=root / "runs" / datetime.now(UTC).date().isoformat(), role=role, dry_run=dry_run,
        author_runtime=author_runtime, planner_mode=planner, llm_call=llm_call, incoming=incoming,
        terrain_rows=terrain, public_events=inputs["events"], seed=seed, scheduled=scheduled, usage=usage,
        budget_hold=budget_hold, environment=environment, work=work, teammates=roster or None,
        owned_counts=owned or None, registrar_name=_registrar_name(root, personas),
    )
    if not quiet:
        echo_record(record)
    if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary_path).open("a", encoding="utf-8") as summary:
            summary.write(f"\n### {persona.name} wake\n\n- mode: {record.get('wake_mode')} · mood: {record.get('mood')} · planner: {record.get('planner')}\n- actions: {len(record['actions'])} · dry run: {record['dry_run']}\n- LLM calls: {usage['calls']} · output tokens: {usage['output_tokens']}\n")
    return record


def fetch_public_world() -> dict[str, Any]:
    """The public world snapshot (structures, agents, factions), or an empty dict when it cannot be read."""
    try:
        world = HinterglassClient().request("GET", "/live/world.json")
    except (HinterglassError, OSError, ValueError):
        return {}
    return world if isinstance(world, dict) else {}


def terrain_rows_from_world(world: dict[str, Any]) -> list[str] | None:
    """The public map as rows of terrain codes (the codes observe's view uses: W w s g f h m)."""
    if not isinstance(world, dict):
        return None
    terrain = world.get("terrain")
    width = int(world.get("width", 128) or 128)
    if isinstance(terrain, list) and terrain and all(isinstance(row, str) for row in terrain):
        return [str(row) for row in terrain]
    if isinstance(terrain, str) and width > 0 and len(terrain) >= width * width and len(terrain) % width == 0:
        return [terrain[i * width:(i + 1) * width] for i in range(len(terrain) // width)]
    return None


def fixture_world(root: Path) -> dict[str, Any]:
    """The fixture world's structures and agents in the public snapshot's shape."""
    world_dir = root / FIXTURES / "world"
    out: dict[str, Any] = {}
    for key in ("structures", "agents"):
        path = world_dir / f"{key}.json"
        if path.is_file():
            data = json.loads(path.read_text(encoding="utf-8"))
            out[key] = data.get(key, []) if isinstance(data, dict) else list(data)
    return out


def structure_counts(world: dict[str, Any], name: str) -> dict[str, int]:
    """How many structures of each type the named agent owns anywhere.

    Only an agent's three oldest farms grow (API 0.22.0), so the planner must know about farms
    standing out of view before it pays for another.
    """
    counts: dict[str, int] = {}
    for structure in world.get("structures", []) if isinstance(world, dict) else []:
        if not isinstance(structure, dict):
            continue
        owner = structure.get("owner") or structure.get("owner_name") or ""
        if str(owner).casefold() == name.casefold():
            kind = str(structure.get("type"))
            counts[kind] = counts.get(kind, 0) + 1
    return counts


def public_structure_counts(name: str) -> dict[str, int]:
    """Structure counts for one agent straight from the public snapshot (no key)."""
    return structure_counts(fetch_public_world(), name)


def _registrar_name(root: Path, personas: dict[str, Persona]) -> str | None:
    """The land office's in-world name, when a ledger names a registrar that exists."""
    if not (root / "config/plots.yaml").is_file():
        return None
    from hglab.land import load_ledger

    try:
        registrar = personas.get(load_ledger(root)["registrar"])
    except (OSError, ValueError):
        return None
    return registrar.name if registrar else None


def public_teammate_positions(personas: dict[str, Persona], team: Team | None) -> dict[str, tuple[int, int]]:
    """Teammate positions from the public roster (no key), so a follower can find a leader out of view."""
    if team is None:
        return {}
    try:
        agents = HinterglassClient().public_agents().get("agents", [])
    except (HinterglassError, OSError):
        return {}
    by_name = {personas[m].name.casefold(): m for m in team.members if m in personas}
    out: dict[str, tuple[int, int]] = {}
    for agent in agents:
        slug = by_name.get(str(agent.get("name", "")).casefold())
        if slug and isinstance(agent.get("x"), int) and isinstance(agent.get("y"), int):
            out[slug] = (int(agent["x"]), int(agent["y"]))
    return out


def build_environment(
    root: Path,
    persona: Persona,
    team: Team | None,
    personas: dict[str, Persona],
    inputs: dict[str, Any],
    *,
    live: bool,
    public_world: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """World digest from the public feed (plus open goals and factions when live)."""
    from hglab.environment import digest

    if not inputs["events"]:
        return None
    team_names = {personas[m].name for m in (team.members if team else ()) if m in personas}
    goals: list[dict[str, Any]] = []
    factions: list[dict[str, Any]] = []
    if live:
        try:
            client = HinterglassClient()
            goals = client.public_goals().get("goals", [])
            factions = client.public_factions().get("factions", [])
        except (HinterglassError, OSError):
            goals, factions = [], []
    else:
        goals_path = root / FIXTURES / "world/goals.json"
        if goals_path.is_file():
            goals = json.loads(goals_path.read_text(encoding="utf-8")).get("goals", [])
    now_tick = inputs["tick"]
    if live:
        try:
            now_tick = max(now_tick, int(HinterglassClient().request("GET", "/api/v1").get("tick", now_tick)))
        except (HinterglassError, OSError, ValueError):
            pass
    collective_names = {p.name for p in personas.values()}
    result = digest(inputs["events"], now_tick, self_name=persona.name, team_names=team_names, collective_names=collective_names, open_goals=goals, factions=factions)
    if (root / "config/requests.yaml").is_file():
        from hglab.crier import board, load_ledger, render_board

        try:
            ledger = load_ledger(root)
            claimed: list[dict[str, Any]] = []
            if live:
                try:
                    claimed = list(HinterglassClient().public_goals("claimed").get("goals", []))
                except (HinterglassError, OSError):
                    claimed = []
            says = [e for e in inputs["events"] if isinstance(e, dict) and e.get("type") == "say" and now_tick - int(e.get("tick", 0) or 0) <= 8640]
            collector = personas.get(ledger["collector"])
            if collector is not None:
                b = board(ledger, list(goals) + claimed, factions, collector.name, says)
                result["collector_board"] = b
                result["collector_board_text"] = render_board(b)
        except (OSError, ValueError):
            pass
    if (root / "config/plots.yaml").is_file() and public_world:
        from hglab.land import board as land_board
        from hglab.land import load_ledger as load_land_ledger
        from hglab.land import render_board as render_land_board

        try:
            ledger = load_land_ledger(root)
            registrar = personas.get(ledger["registrar"])
            if registrar is not None:
                lb = land_board(ledger, public_world.get("structures", []), public_world.get("agents", []), list(goals), registrar.name)
                result["land_office"] = {k: lb[k] for k in ("total", "occupied", "free", "vault", "registration_goal", "offers")}
                result["land_office_text"] = f"{registrar.name} (the collective's land office)\n" + render_land_board(lb)
        except (OSError, ValueError):
            pass
    if persona.quirk.get("type") == "feature_watch":
        from hglab.features import snapshot

        try:
            result["features_now"] = snapshot(HinterglassClient()) if live else _fixture_feature_snapshot(root, inputs)
        except (HinterglassError, OSError, ValueError) as exc:
            result["features_error"] = str(exc)[:120]
    return result


def _fixture_feature_snapshot(root: Path, inputs: dict[str, Any]) -> dict[str, Any]:
    events = inputs["events"]
    return {
        "tick": inputs["tick"], "api_version": "fixture", "guide_sha256": "", "guide_actions": [], "guide_blueprints": [],
        "event_types": sorted({str(e.get("type")) for e in events}),
        "structure_types": sorted({str((e.get("data") or {}).get("type")) for e in events if e.get("type") == "build" and (e.get("data") or {}).get("type")}),
        "factions": [], "agents": sorted({str(e.get("actor")) for e in events if e.get("actor")}), "agent_count": len({e.get("actor") for e in events}), "world_stats": {},
    }


def _force_mode(persona: Persona, mode: str) -> None:
    """Scene staging: override the wake mode decision for this process only."""
    import hglab.wake as wake_module

    def forced(*_args: Any, **_kwargs: Any) -> str:
        return mode

    wake_module.decide_wake_mode = forced  # type: ignore[assignment]


def _restore_mode() -> None:
    import hglab.mood as mood_module
    import hglab.wake as wake_module

    wake_module.decide_wake_mode = mood_module.decide_wake_mode


def _model_key(root: Path) -> bool:
    return bool(get_secret("ANTHROPIC_API_KEY", root) or get_secret("OPENAI_API_KEY", root))


def _make_llm_call(root: Path, persona: Persona, team: Team | None, role: str, usage: dict[str, int], *, worn: str | None = None) -> Any:
    from hglab.llm import structured_call

    hats = (worn or role).split("+")
    bodies = []
    skill_names: list[str] = []
    role_config: dict[str, Any] = {}
    for hat in hats:
        charter = (root / "roles" / f"{hat}.md").read_text(encoding="utf-8")
        front, body_text = charter.split("---", 2)[1:]
        config = yaml.safe_load(front)
        role_config = role_config or config
        bodies.append(f"HAT {hat}:\n{body_text.strip()}")
        skill_names.extend(n for n in config["skills"] if n not in skill_names)
    body = "\n\n".join(bodies)
    skills = [
        (root / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        for name in skill_names
        if (root / "skills" / name / "SKILL.md").exists()
    ]
    action_schema = json.loads((root / "schemas/action.json").read_text(encoding="utf-8"))
    schema = plan_schema(action_schema)
    north_star = (root / "kb/NORTH_STAR.md").read_text(encoding="utf-8")
    budget = yaml.safe_load((root / "config/budget.yaml").read_text(encoding="utf-8"))["tick"]

    route = persona.knobs.get("model_route") or role_config["model_route"]

    def call(guidance: str, observe: dict[str, Any]) -> dict[str, Any]:
        if usage["calls"] >= budget["max_llm_calls"]:
            raise ValueError("tick LLM call budget exhausted")
        output_tokens = min(2500, budget["max_output_tokens"] - usage["output_tokens"])
        if output_tokens < 1:
            raise ValueError("tick output-token budget exhausted")
        trimmed = dict(observe)
        events = observe.get("events") if isinstance(observe.get("events"), list) else []
        trimmed["events"] = events[-30:]
        prompt = persona_prompt(persona, team, body, north_star, skills, trimmed, action_schema, {}, guidance)
        result = structured_call(route, prompt, schema, root=root, output_tokens=output_tokens, author_runtime=os.environ.get("HGLAB_RUNTIME", "human"))
        usage.update(calls=usage["calls"] + 1, input_tokens=usage["input_tokens"] + result.input_tokens, output_tokens=usage["output_tokens"] + result.output_tokens, model=result.model, provider=result.provider, route=route)
        return result.value

    return call


def echo_record(record: dict[str, Any]) -> None:
    typer.echo(f"{record['agent']} · {record.get('wake_mode')} · mood {record.get('mood')} · planner {record.get('planner')}"
               + (f" (fallback: {record['fallback_reason']})" if record.get("fallback_reason") else "")
               + (f" (model error: {record['llm_error']})" if record.get("llm_error") else "")
               + (f" (budget hold: {record['budget_hold']})" if record.get("budget_hold") else ""))
    typer.echo(f"  {record.get('summary', '')}")
    for index, action in enumerate(record["actions"]):
        shown = {k: (v if k != "text" or len(str(v)) <= 90 else str(v)[:87] + "...") for k, v in action.items()}
        typer.echo(f"  {index + 1}. {json.dumps(shown, ensure_ascii=False)}")
    for reason in record.get("reasons", []):
        typer.echo(f"  why: {reason}")
    if record.get("knob_checks"):
        typer.echo(f"  knobs passed: {', '.join(record['knob_checks'])}")
    typer.echo(f"  {'dry run, nothing sent' if record['dry_run'] else 'executed: ' + str(len(record['results'])) + ' result(s)'}; record {record['run_id']}")


# --- shift: deterministic work between character wakes -----------------------


def shift_command(
    agent: str = typer.Option(..., "--agent"),
    minutes: int | None = typer.Option(None, "--minutes", help="Shift length (default: the persona's work knob)"),
    interval_seconds: int | None = typer.Option(None, "--interval-seconds", help="Pause between wakes (default: the knob)"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    fixture: Path | None = typer.Option(None, "--fixture"),  # noqa: B008
    max_wakes: int | None = typer.Option(None, "--max-wakes"),
    scheduled: bool = typer.Option(False, "--scheduled"),
    announce: bool = typer.Option(True, "--announce/--no-announce", help="End the shift with one public line about it"),
) -> None:
    """Work shift: deterministic wakes (build, gather, deposit, migrate) every few minutes, then one public line."""
    root = root_dir()
    persona = resolve_persona(root, agent)
    records: list[dict[str, Any]] = []
    knob = persona.knobs.get("work") or {"minutes": 25, "interval_seconds": 300}
    length = minutes if minutes is not None else int(knob["minutes"])
    pause = interval_seconds if interval_seconds is not None else int(knob["interval_seconds"])
    deadline = time.monotonic() + length * 60
    wakes = 0
    attempts = 0
    inputs = gather_inputs(root, fixtures=fixture is not None, events_paths=[], runs_paths=[], fetch_public=fixture is None, tick=None)
    typer.echo(f"{persona.name} work shift: up to {length} min, a wake every {pause} s")
    while True:
        attempts += 1
        try:
            record = persona_tick(root, persona, role=None, dry_run=dry_run, fixture=fixture, planner="heuristic", seed=None, events_paths=[], jitter_minutes=0, scheduled=scheduled, work=True, inputs=inputs, quiet=True)
            records.append(record)
            wakes += 1
            energy = int(record.get("energy_before", 0) or 0) - int(record.get("energy_spent", 0) or 0)
            typer.echo(f"  wake {wakes}: {record.get('summary', '')} · {len(record['actions'])} action(s), energy about {energy}, approach {record.get('approach')}")
        except (typer.BadParameter, typer.Exit, ValueError, RuntimeError) as exc:
            typer.echo(f"  wake skipped: {getattr(exc, 'message', None) or str(exc) or 'lease held elsewhere'}"[:200])
            energy = 100
        if max_wakes is not None and attempts >= max_wakes:
            break
        wait = pause
        if energy < persona.energy_reserve + 10:
            wait = max(wait, int((persona.energy_reserve + 15 - energy) / 2 * 10))  # +2 energy per 10-second tick
        if time.monotonic() + wait > deadline:
            break
        if fixture is None:
            time.sleep(wait)
    typer.echo(f"shift over: {wakes} wake(s)")
    collector = _collector_duties(root, persona)
    spoke = False
    if collector:
        typer.echo(f"  collector duties ({', '.join(sorted(collector))})" + (": the round may speak for this shift" if "collect" in collector else ""))
        try:
            spoke = bool(crier_round(root, persona, dry_run=dry_run, fixture=fixture, scheduled=scheduled).get("said"))
        except (typer.BadParameter, typer.Exit, ValueError, RuntimeError, OSError) as exc:
            typer.echo(f"  collector round skipped: {str(exc)[:200]}")
    if _land_duty(root, persona):
        typer.echo("  land office duties: the round may speak for this shift")
        try:
            spoke = bool(land_round(root, persona, dry_run=dry_run, fixture=fixture, scheduled=scheduled).get("said")) or spoke
        except (typer.BadParameter, typer.Exit, ValueError, RuntimeError, OSError) as exc:
            typer.echo(f"  land office round skipped: {str(exc)[:200]}")
    if announce and records and not spoke:
        announce_shift(root, persona, records, dry_run=dry_run, fixture=fixture, scheduled=scheduled)


def _land_duty(root: Path, persona: Persona) -> bool:
    """Whether this persona is the land office's registrar."""
    if not (root / "config/plots.yaml").is_file():
        return False
    from hglab.land import is_registrar, load_ledger

    try:
        return is_registrar(persona, load_ledger(root))
    except (OSError, ValueError):
        return False


def land_round(root: Path, persona: Persona, *, dry_run: bool, fixture: Path | None, scheduled: bool, quiet: bool = False) -> dict[str, Any]:
    """One land office round: deeds for paid registrations, the registration goal, offers, the office line."""
    from hglab.actions import redact_result, validate_actions
    from hglab.land import STATE_KEY, board, is_registrar, load_ledger, plan_round, render_board

    ledger = load_ledger(root)
    if not is_registrar(persona, ledger):
        typer.echo(f"{persona.name}: not the land office registrar")
        return {"skipped": "no land duties"}
    personas = load_personas(root)
    team = team_of(root, persona)
    collective_names = {p.name for p in personas.values()}
    goals, _factions, agents, events = _public_board_inputs(root, fixture=fixture)
    world = fixture_world(root) if fixture is not None else fetch_public_world()
    structures = list(world.get("structures", []))
    agents = list(world.get("agents", []) or agents)
    if fixture is not None:
        client: Any = FixtureClient(load_fixture(fixture))
    else:
        api_key = get_api_key(persona.name, root)
        if not api_key:
            raise typer.BadParameter(f"no key configured for {persona.name}")
        client = HinterglassClient(api_key=api_key)
    lease = acquire(client, persona.name)
    if lease is None:
        if scheduled:
            typer.echo(f"{persona.name}: lease held elsewhere; skipping the land office round")
            return {"skipped": "lease held"}
        raise typer.BadParameter(f"identity {persona.name} already has an active lease")
    record: dict[str, Any] = {
        "agent": persona.name, "persona": persona.slug, "kind": "land_round",
        "recorded_utc": datetime.now(UTC).isoformat(), "dry_run": dry_run, "scheduled": scheduled,
    }
    b: dict[str, Any] = {}
    reasons: list[str] = []
    dropped: list[str] = []
    results: list[dict[str, Any]] = []
    try:
        observe = client.observe()
        if observe.get("challenge") and (fixture is None or _model_key(root)):
            from hglab.cli import answer_daily_challenge

            answer_daily_challenge(client, observe, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
        tick = int(observe.get("tick", 0) or 0)
        # the registrar's own view beats the snapshot for its storehouse (the snapshot may lag)
        structures = structures + [s for s in observe.get("structures", []) if isinstance(s, dict) and s.get("type") == "storehouse" and str(s.get("owner", "")).casefold() == persona.name.casefold()]
        raw_state = (observe.get("notebook") or {}).get(STATE_KEY)
        try:
            state = json.loads(raw_state) if isinstance(raw_state, str) else {}
        except json.JSONDecodeError:
            state = {}
        if not isinstance(state, dict):
            state = {}
        b = board(ledger, structures, agents, goals, persona.name, state)
        recent = [e for e in events if isinstance(e, dict) and tick - int(e.get("tick", 0) or 0) <= 8640]
        actions, reasons, update = plan_round(persona, ledger, observe, b, public_events=recent, structures=structures, agents=agents, state=state, collective_names=collective_names)
        if update:
            actions.append({"action": "remember", "key": STATE_KEY, "text": json.dumps({**state, **update}, separators=(",", ":"))[:2000]})
        worn = "+".join(persona.roles)
        recent_say_count, open_goal_count, prior_text = action_limits(observe)
        member_names = {personas[m].name for m in (team.members if team else ()) if m in personas}
        team_says = team_say_count(list(observe.get("events", []) or []), member_names, tick)
        kept = []
        for action in actions:
            try:
                validated = validate_actions([action], worn, recent_say_count=recent_say_count, open_goal_count=open_goal_count, prior_text=prior_text, observe=observe)[0]
                if action["action"] == "say":
                    enforce_knobs([action], persona, team, observe, recent_say_count=recent_say_count, team_recent_says=team_says, member_names=member_names)
                    recent_say_count += 1
                if action["action"] == "post_goal":
                    open_goal_count += 1
                kept.append(validated)
            except ValueError as exc:
                dropped.append(f"{action['action']}: {exc}")
        if not dry_run:
            for validated in kept:
                try:
                    result = client.act(validated.model_dump(exclude_none=True))
                except Exception as exc:  # noqa: BLE001 - a world refusal is a failed result, not a crash
                    result = {"ok": False, "error": str(getattr(exc, "code", None) or type(exc).__name__)[:40]}
                results.append(redact_result(result))
                if not result.get("ok", False):
                    break
        record.update({
            "tick": tick, "board": {k: v for k, v in b.items() if k != "agents"}, "actions": [a.model_dump(exclude_none=True) for a in kept],
            "reasons": reasons, "dropped": dropped, "results": results, "said": any(a.action == "say" for a in kept),
        })
    finally:
        release(client, lease)
    out_dir = root / "runs" / datetime.now(UTC).date().isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{persona.name}-land-{int(time.time())}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    if not quiet:
        typer.echo(f"{persona.name} land office round · tick {record.get('tick')}")
        if b:
            typer.echo(render_board(b))
        for action in record.get("actions", []):
            shown = {k: (v if not isinstance(v, str) or len(v) <= 90 else v[:87] + "...") for k, v in action.items()}
            typer.echo(f"  -> {json.dumps(shown, ensure_ascii=False)}")
        for reason in reasons:
            typer.echo(f"  why: {reason}")
        for item in dropped:
            typer.echo(f"  dropped: {item}")
        typer.echo(f"  {'dry run, nothing sent' if dry_run else 'executed: ' + str(len(results)) + ' result(s)'}")
    return record


land_app = typer.Typer(help="The land office: survey in 10x10 plots, a registry for a fee, standing offers, a vault toward lending.")


@land_app.command("board")
def land_board_command(fixtures: bool = typer.Option(False, "--fixtures", help="Read the fixture world instead of the public endpoints")) -> None:
    """The office's public standing: survey counts, vault, registration goal, offers, registry (no key needed)."""
    from hglab.land import board, check_ledger, load_ledger, render_board

    root = root_dir()
    ledger = load_ledger(root)
    personas = load_personas(root)
    registrar = personas[ledger["registrar"]]
    fixture = (root / FIXTURES / "observe" / f"{ledger['registrar']}.json") if fixtures else None
    goals, _factions, agents, _events = _public_board_inputs(root, fixture=fixture)
    world = fixture_world(root) if fixtures else fetch_public_world()
    typer.echo(render_board(board(ledger, list(world.get("structures", [])), list(world.get("agents", []) or agents), goals, registrar.name)))
    for problem in check_ledger(ledger, personas):
        typer.echo(f"  ! {problem}")


@land_app.command("round")
def land_round_command(
    agent: str = typer.Option(..., "--agent"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    fixture: Path | None = typer.Option(None, "--fixture"),  # noqa: B008
    scheduled: bool = typer.Option(False, "--scheduled"),
) -> None:
    """One land office round for the registrar (a no-op for every other persona)."""
    root = root_dir()
    persona = resolve_persona(root, agent)
    land_round(root, persona, dry_run=dry_run, fixture=fixture, scheduled=scheduled)


@land_app.command("validate")
def land_validate_command() -> None:
    """Check the ledger against its schema and the registrar's hats."""
    from hglab.land import check_ledger, load_ledger

    root = root_dir()
    ledger = load_ledger(root)
    problems = check_ledger(ledger, load_personas(root))
    for problem in problems:
        typer.echo(f"  ! {problem}")
    if problems:
        raise typer.Exit(code=1)
    typer.echo(f"config/plots.yaml: registrar {ledger['registrar']}, fee {ledger['fee']}, {len(ledger['offers'])} offer(s), {len(ledger['plots'])} pre-registered plot(s)")


def _collector_duties(root: Path, persona: Persona) -> set[str]:
    """What the collector ledger asks of this persona (empty when there is no ledger)."""
    if not (root / "config/requests.yaml").is_file():
        return set()
    from hglab.crier import duties, load_ledger

    try:
        return duties(persona, load_ledger(root))
    except (OSError, ValueError):
        return set()


def _active_names(agents: list[dict[str, Any]], tick: int) -> list[str]:
    """Residents seen in the last day, most recent first (everyone, when the roster has no times)."""
    rows = [a for a in agents if isinstance(a, dict) and a.get("name")]

    def seen(agent: dict[str, Any]) -> int:
        return int(agent.get("last_seen_tick") or 0)

    active = [a for a in rows if tick - seen(a) <= 8640] or rows
    active.sort(key=seen, reverse=True)
    return [str(a["name"]) for a in active]


def _public_board_inputs(root: Path, *, fixture: Path | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Public goals (open and claimed), factions, residents and recent events, from the world or the fixtures."""
    if fixture is not None:
        world = root / FIXTURES / "world"
        goals = json.loads((world / "goals.json").read_text(encoding="utf-8")).get("goals", [])
        factions_path = world / "factions.json"
        factions = json.loads(factions_path.read_text(encoding="utf-8")).get("factions", []) if factions_path.is_file() else []
        agents_data = json.loads((world / "agents.json").read_text(encoding="utf-8"))
        agents = agents_data.get("agents", []) if isinstance(agents_data, dict) else list(agents_data)
        return goals, factions, agents, load_events([world / "events.jsonl"])
    client = HinterglassClient()
    goals: list[dict[str, Any]] = []
    factions: list[dict[str, Any]] = []
    agents: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    try:
        goals = list(client.public_goals("open").get("goals", [])) + list(client.public_goals("claimed").get("goals", []))
        factions = client.public_factions().get("factions", [])
        agents = client.public_agents().get("agents", [])
        events = fetch_public_events(client, pages=3)
    except (HinterglassError, OSError) as exc:
        typer.echo(f"public reads failed ({exc}); the board may be partial", err=True)
    return goals, factions, agents, events


def crier_round(root: Path, persona: Persona, *, dry_run: bool, fixture: Path | None, scheduled: bool, quiet: bool = False) -> dict[str, Any]:
    """One collector round: found the owed theme faction, post missing goals, confirm feedback, make the call."""
    from hglab.actions import redact_result, validate_actions
    from hglab.crier import STATE_KEY, board, duties, load_ledger, plan_round, render_board

    ledger = load_ledger(root)
    mine = duties(persona, ledger)
    if not mine:
        typer.echo(f"{persona.name}: no collector duties in config/requests.yaml")
        return {"skipped": "no collector duties"}
    personas = load_personas(root)
    team = team_of(root, persona)
    collector_name = personas[ledger["collector"]].name
    goals, factions, agents, events = _public_board_inputs(root, fixture=fixture)
    if fixture is not None:
        client: Any = FixtureClient(load_fixture(fixture))
    else:
        api_key = get_api_key(persona.name, root)
        if not api_key:
            raise typer.BadParameter(f"no key configured for {persona.name}")
        client = HinterglassClient(api_key=api_key)
    lease = acquire(client, persona.name)
    if lease is None:
        if scheduled:
            typer.echo(f"{persona.name}: lease held elsewhere; skipping the collector round")
            return {"skipped": "lease held"}
        raise typer.BadParameter(f"identity {persona.name} already has an active lease")
    record: dict[str, Any] = {
        "agent": persona.name, "persona": persona.slug, "kind": "collector_round",
        "recorded_utc": datetime.now(UTC).isoformat(), "dry_run": dry_run, "scheduled": scheduled,
    }
    b: dict[str, Any] = {"themes": [], "requests": []}
    reasons: list[str] = []
    dropped: list[str] = []
    results: list[dict[str, Any]] = []
    try:
        observe = client.observe()
        if observe.get("challenge") and (fixture is None or _model_key(root)):
            from hglab.cli import answer_daily_challenge

            answer_daily_challenge(client, observe, {"calls": 0, "input_tokens": 0, "output_tokens": 0})
        tick = int(observe.get("tick", 0) or 0)
        says = [e for e in events if isinstance(e, dict) and e.get("type") == "say" and tick - int(e.get("tick", 0) or 0) <= 8640]
        b = board(ledger, goals, factions, collector_name, says)
        raw_state = (observe.get("notebook") or {}).get(STATE_KEY)
        try:
            state = json.loads(raw_state) if isinstance(raw_state, str) else {}
        except json.JSONDecodeError:
            state = {}
        if not isinstance(state, dict):
            state = {}
        from hglab.crier import faction_name

        factions_of = {str(a.get("name")): faction_name(a.get("faction")) for a in agents if isinstance(a, dict) and a.get("name")}
        actions, reasons, update = plan_round(
            persona, ledger, observe, b, active_names=_active_names(agents, tick), state=state, public_events=events, factions_of=factions_of,
        )
        if update:
            actions.append({"action": "remember", "key": STATE_KEY, "text": json.dumps({**state, **update}, separators=(",", ":"))[:2000]})
        worn = "+".join(persona.roles)
        recent_say_count, open_goal_count, prior_text = action_limits(observe)
        member_names = {personas[m].name for m in (team.members if team else ()) if m in personas}
        team_says = team_say_count(list(observe.get("events", []) or []), member_names, tick)
        kept = []
        for action in actions:
            try:
                validated = validate_actions([action], worn, recent_say_count=recent_say_count, open_goal_count=open_goal_count, prior_text=prior_text, observe=observe)[0]
                if action["action"] == "say":
                    enforce_knobs([action], persona, team, observe, recent_say_count=recent_say_count, team_recent_says=team_says, member_names=member_names)
                    recent_say_count += 1
                if action["action"] == "post_goal":
                    open_goal_count += 1
                kept.append(validated)
            except ValueError as exc:
                dropped.append(f"{action['action']}: {exc}")
        if not dry_run:
            for validated in kept:
                try:
                    result = client.act(validated.model_dump(exclude_none=True))
                except Exception as exc:  # noqa: BLE001 - a world refusal is a failed result, not a crash
                    result = {"ok": False, "error": str(getattr(exc, "code", None) or type(exc).__name__)[:40]}
                results.append(redact_result(result))
                if not result.get("ok", False):
                    break
        record.update({
            "tick": tick, "duties": sorted(mine), "board": b, "actions": [a.model_dump(exclude_none=True) for a in kept],
            "reasons": reasons, "dropped": dropped, "results": results, "asked": list(update.get("asked", []))[-3:] if update else [],
            "said": any(a.action == "say" for a in kept),
        })
    finally:
        release(client, lease)
    out_dir = root / "runs" / datetime.now(UTC).date().isoformat()
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{persona.name}-collector-{int(time.time())}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    if not quiet:
        typer.echo(f"{persona.name} collector round · duties {', '.join(sorted(mine))} · tick {record.get('tick')}")
        typer.echo(render_board(b))
        for action in record.get("actions", []):
            shown = {k: (v if not isinstance(v, str) or len(v) <= 90 else v[:87] + "...") for k, v in action.items()}
            typer.echo(f"  -> {json.dumps(shown, ensure_ascii=False)}")
        for reason in reasons:
            typer.echo(f"  why: {reason}")
        for item in dropped:
            typer.echo(f"  dropped: {item}")
        typer.echo(f"  {'dry run, nothing sent' if dry_run else 'executed: ' + str(len(results)) + ' result(s)'}")
    return record


crier_app = typer.Typer(help="The collector programme: requests as goals, themes as open factions, membership as the vote.")


@crier_app.command("board")
def crier_board_command(fixtures: bool = typer.Option(False, "--fixtures", help="Read the fixture world instead of the public endpoints")) -> None:
    """Every theme and request with its public standing (no key needed)."""
    from hglab.crier import board, check_ledger, load_ledger, render_board

    root = root_dir()
    ledger = load_ledger(root)
    personas = load_personas(root)
    fixture = (root / FIXTURES / "observe/town-crier.json") if fixtures else None
    goals, factions, _agents, events = _public_board_inputs(root, fixture=fixture)
    tick = max([int(e.get("tick", 0) or 0) for e in events if isinstance(e, dict)] + [0])
    says = [e for e in events if isinstance(e, dict) and e.get("type") == "say" and tick - int(e.get("tick", 0) or 0) <= 8640]
    typer.echo(render_board(board(ledger, goals, factions, personas[ledger["collector"]].name, says)))
    for problem in check_ledger(ledger, personas):
        typer.echo(f"  ! {problem}")


@crier_app.command("round")
def crier_round_command(
    agent: str = typer.Option(..., "--agent"),
    dry_run: bool = typer.Option(False, "--dry-run"),
    fixture: Path | None = typer.Option(None, "--fixture"),  # noqa: B008
    scheduled: bool = typer.Option(False, "--scheduled"),
) -> None:
    """One collector round for this persona (a no-op for personas without duties)."""
    root = root_dir()
    persona = resolve_persona(root, agent)
    crier_round(root, persona, dry_run=dry_run, fixture=fixture, scheduled=scheduled)


@crier_app.command("validate")
def crier_validate_command() -> None:
    """Check the ledger against its schema and the personas' hats."""
    from hglab.crier import check_ledger, load_ledger

    root = root_dir()
    ledger = load_ledger(root)
    problems = check_ledger(ledger, load_personas(root))
    for problem in problems:
        typer.echo(f"  ! {problem}")
    if problems:
        raise typer.Exit(code=1)
    typer.echo(f"config/requests.yaml: {len(ledger['themes'])} theme(s), {len(ledger['requests'])} request(s), collector {ledger['collector']}")


def announce_shift(root: Path, persona: Persona, records: list[dict[str, Any]], *, dry_run: bool, fixture: Path | None, scheduled: bool) -> None:
    """One validated public line about the shift, through the lease and every cap."""
    from hglab.actions import allowed_for, validate_actions
    from hglab.talk import compose_line, summarise_shift

    team = team_of(root, persona)
    summary = summarise_shift(records)
    usage: dict[str, Any] = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    line, source = compose_line(persona, team, summary, root, usage=usage)
    worn = "+".join(persona.roles)
    if "say" not in allowed_for(worn):
        typer.echo(f"  no announcement: {persona.name}'s hats cannot say")
        return
    if fixture is not None:
        client: Any = FixtureClient(load_fixture(fixture))
    else:
        api_key = get_api_key(persona.name, root)
        if not api_key:
            return
        client = HinterglassClient(api_key=api_key)
    lease = acquire(client, persona.name)
    if lease is None:
        typer.echo("  no announcement: lease held elsewhere")
        return
    try:
        observe = client.observe()
        recent_say_count, open_goal_count, prior_text = action_limits(observe)
        personas = load_personas(root)
        member_names = {personas[m].name for m in (team.members if team else ()) if m in personas}
        team_says = team_say_count(list(observe.get("events", []) or []), member_names, int(observe.get("tick", 0)))
        action = {"action": "say", "text": line}
        try:
            validate_actions([action], worn, recent_say_count=recent_say_count, open_goal_count=open_goal_count, prior_text=prior_text, observe=observe)
            enforce_knobs([action], persona, team, observe, recent_say_count=recent_say_count, team_recent_says=team_says, member_names=member_names)
        except ValueError as exc:
            typer.echo(f"  no announcement: {exc}")
            return
        result = {"ok": True}
        if not dry_run:
            result = client.act(action)
        typer.echo(f"  said ({source}{'' if result.get('ok') else ', refused: ' + str(result.get('error'))}): {line}")
        record = {
            "run_id": f"announce-{int(time.time())}", "kind": "announce", "agent": persona.name, "persona": persona.slug,
            "tick": observe.get("tick"), "created_utc": datetime.now(UTC).isoformat(), "author_runtime": os.environ.get("HGLAB_RUNTIME", "human"),
            "actions": [action] if result.get("ok") else [], "results": [{"ok": bool(result.get("ok"))}], "failed_actions": 0 if result.get("ok") else 1,
            "dry_run": dry_run, "usage": usage, "source": source, "shift_summary": summary, "work": True, "wake_mode": "announce",
        }
        folder = root / "runs" / datetime.now(UTC).date().isoformat()
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{persona.name}-announce-{int(time.time())}.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    finally:
        release(client, lease)


# --- persona commands --------------------------------------------------------


@persona_app.command("validate")
def persona_validate() -> None:
    """Schema-check personas, metrics and teams, and cross-reference config."""
    errors = validate_personas(root_dir())
    if errors:
        raise typer.BadParameter("\n".join(errors))
    typer.echo(f"{len(list_persona_slugs(root_dir()))} persona(s) valid.")


@persona_app.command("list")
def persona_list() -> None:
    root = root_dir()
    teams = load_teams(root)
    for slug, persona in load_personas(root).items():
        team = teams.get(persona.team)
        typer.echo(f"{slug:<14} {persona.name:<12} {persona.team:<18} {persona.status:<10} {', '.join(persona.roles)}  cron {persona.knobs['cadence']['cron']}" + ("" if team else "  (team missing)"))


@persona_app.command("show")
def persona_show(agent: str = typer.Option(..., "--agent"), bible: bool = typer.Option(False, "--bible")) -> None:
    root = root_dir()
    persona = resolve_persona(root, agent)
    data = {k: getattr(persona, k) for k in ("slug", "name", "team", "status", "intent", "roles", "knobs", "voice", "mood_model", "quirk", "signals_emitted", "signals_received")}
    typer.echo(yaml.safe_dump(json.loads(json.dumps(data)), sort_keys=False, allow_unicode=True))
    if bible:
        typer.echo(persona.body)


@persona_app.command("secret-name")
def persona_secret_name(agent: str = typer.Option(..., "--agent")) -> None:
    """Print the environment variable / GitHub secret name for this identity (never a value)."""
    typer.echo(resolve_persona(root_dir(), agent).secret_name)


@persona_app.command("variable-name")
def persona_variable_name(agent: str = typer.Option(..., "--agent")) -> None:
    typer.echo(resolve_persona(root_dir(), agent).variable_name)


@persona_app.command("check-name")
def persona_check_name(name: str = typer.Argument(...)) -> None:
    """Check an in-world name against the rules and the public agents endpoint (read-only)."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,24}", name):
        raise typer.BadParameter("names are 3-24 characters of letters, digits, _ or -")
    if name.casefold() in {"admin", "system", "hinterglass", "world"}:
        raise typer.BadParameter("that name is reserved")
    taken_locally = [p.slug for p in load_personas(root_dir()).values() if p.name.casefold() == name.casefold()]
    if taken_locally:
        typer.echo(f"{name}: planned for persona {taken_locally[0]} in this repo (status {load_persona(root_dir(), taken_locally[0]).status})")
    try:
        HinterglassClient().public_agent(name)
    except HinterglassError as error:
        if error.status_code == 404:
            typer.echo(f"{name}: available in-world (public agents endpoint returned 404)")
            return
        raise
    typer.echo(f"{name}: TAKEN in-world by an existing agent; choose another (never retry the same)")


@persona_app.command("new")
def persona_new(answers: Path = typer.Option(..., "--answers", help="YAML answers from the hg-new-agent interview")) -> None:  # noqa: B008
    """Generate persona, metrics, team updates, kb goal and bets, and a disabled workflow."""
    root = root_dir()
    data = yaml.safe_load(answers.read_text(encoding="utf-8"))
    created = scaffold_agent(root, data)
    for path in created:
        typer.echo(f"created {path.relative_to(root).as_posix()}")
    errors = validate_personas(root)
    if errors:
        raise typer.BadParameter("generated files need fixes:\n" + "\n".join(errors))
    typer.echo("all valid. Preview: hglab tick --agent " + data["slug"] + " --dry-run --fixture tests/fixtures/observe/" + data["slug"] + ".json (write that fixture first) · registration is a separate, owner-approved step: hglab register --name " + data["name"])


def scaffold_agent(root: Path, data: dict[str, Any]) -> list[Path]:
    """Write every file a new agent needs from interview answers with sensible defaults."""
    slug = data["slug"]
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,30}", slug):
        raise ValueError("slug must be lowercase letters, digits and dashes")
    name = data["name"]
    team_slug = data["team"]
    today = datetime.now(UTC).date().isoformat()
    created: list[Path] = []
    knobs = {
        "cadence": {"cron": data.get("cron", "17 */3 * * *"), "jitter_minutes": int(data.get("jitter_minutes", 15))},
        "rest_probability": float(data.get("rest_probability", 0.1)),
        "actions_per_wake": int(data.get("actions_per_wake", 3)),
        "energy_reserve": int(data.get("energy_reserve", 25)),
        "risk_appetite": float(data.get("risk_appetite", 0.5)),
        "exploration_rate": float(data.get("exploration_rate", 0.3)),
        "territory": data.get("territory", {"mode": "prefer_inside", "radius": 8}),
        "social_rate": int(data.get("social_rate", 1)),
        "intended_mix": data.get("intended_mix", {"build": 0.3, "gather": 0.3, "social": 0.15, "explore": 0.15, "trade": 0.1}),
    }
    if data.get("build_priority"):
        knobs["build_priority"] = list(data["build_priority"])
    if data.get("model_route"):
        knobs["model_route"] = str(data["model_route"])
    if data.get("work"):
        knobs["work"] = dict(data["work"])
    traits = data.get("traits") or [{"name": "steady", "shows_up_as": "Keeps to the plan and reports plainly."}] * 3
    front = {
        "slug": slug, "name": name, "team": team_slug, "status": "draft",
        "intent": data["intent"], "success": data.get("success", ""), "inspiration": data.get("inspiration", ""),
        "roles": list(data.get("roles", ["builder"])), "knobs": knobs,
        "voice": data.get("voice", {"register": "Plain and brief.", "rules": ["Say what you did and what you need."], "never": ["Name or mock a peer."], "max_say_chars": 200}),
        "mood_model": data.get("mood_model", {"type": "steady", "states": ["steady"], "initial": "steady", "inputs": []}),
        "quirk": data.get("quirk", {"type": "none", "plain_english": "No special decision rule; the knobs carry the character."}),
        "signals_emitted": list(data.get("signals_emitted", [])),
        "signals_received": list(data.get("signals_received", [])),
        "profile": data.get("profile", {"bio": f"{data.get('concept', name)}. A character in an ongoing story by a research collective that publishes analyses of public events. Honest to all.", "goals": data["intent"]}),
    }
    bible = [
        f"# {name}", "", "## Backstory", "", data.get("backstory", data.get("concept", "TODO: backstory.")), "",
        "## Voice", "", front["voice"]["register"], "", "## Signature moves", "",
        *[f"- {t['name']}: {t['shows_up_as']}" for t in traits], "",
        "## Relationships", "", data.get("relationships", "TODO: relationships, ironies."), "",
        "## Example in-world lines", "", *[f"- \"{line}\"" for line in data.get("example_lines", ["TODO: write three fresh lines."])], "",
        "## Boundaries", "", data.get("boundaries", "Vices stay in voice and in how the character treats its own team's resources. Toward peers: honest, promises kept, never a wall across a path, never a stripped node. A character in an ongoing story by the collective; the profile says so."), "",
    ]
    folder = root / "agents" / slug
    folder.mkdir(parents=True, exist_ok=True)
    persona_path = folder / "persona.md"
    persona_path.write_text("---\n" + yaml.safe_dump(front, sort_keys=False, allow_unicode=True) + "---\n\n" + "\n".join(bible), encoding="utf-8", newline="\n")
    created.append(persona_path)
    metrics = {
        "version": 1, "agent": slug, "headline": data.get("headline", data["intent"][:60]),
        "key_results": data.get("key_results") or [
            {"id": "structures", "label": "structures built", "measure": "events.structures_built", "params": {}, "target": 6, "weight": 0.4, "format": "{value}/{target} built"},
            {"id": "goals_for_peers", "label": "goals completed for peers", "measure": "events.goals_completed_for_peers", "params": {}, "target": 2, "weight": 0.3, "format": "{value} for peers"},
            {"id": "replies", "label": "replies received", "measure": "events.replies_received", "params": {}, "target": 3, "weight": 0.3, "format": "{value} replies"},
        ],
        "signatures": data.get("signatures") or [
            {"id": "rest_share", "label": "share of wakes resting", "measure": "runs.rest_share", "range": [0.0, 0.3]},
            {"id": "energy_mix", "label": "intended vs actual energy mix", "measure": "runs.energy_mix_match", "range": [0.6, 1.0]},
        ],
        "traits": traits[:7],
        "approaches": data.get("approaches") or [{"id": "default_plan", "label": "the default plan", "hypothesis": None, "outcome_measure": "events.structures_built"}],
    }
    metrics_path = folder / "metrics.yaml"
    metrics_path.write_text(yaml.safe_dump(metrics, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
    created.append(metrics_path)
    team_path = root / "teams" / f"{team_slug}.yaml"
    if team_path.exists():
        team_data = yaml.safe_load(team_path.read_text(encoding="utf-8"))
        if slug not in team_data["members"]:
            team_data["members"].append(slug)
    else:
        team_data = {"slug": team_slug, "name": data.get("team_name", team_slug.replace("-", " ").title()), "aim": data.get("team_aim", data["intent"]), "members": [slug], "home": None, "territory": None, "social_budget": {"says_per_hour": 3}, "links": []}
    for link in data.get("links", []):
        if link not in team_data["links"]:
            team_data["links"].append(link)
    team_data["social_budget"]["says_per_hour"] = max(team_data["social_budget"]["says_per_hour"], sum(_social_rate(root, m) for m in team_data["members"] if m != slug) + knobs["social_rate"])
    team_path.parent.mkdir(parents=True, exist_ok=True)
    team_path.write_text(yaml.safe_dump(team_data, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
    created.append(team_path)
    config_path = root / "config/agents.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not any(item.get("persona") == slug for item in config["agents"]):
        config["agents"].append({"name": name, "persona": slug, "team": team_slug, "enabled": False, "roles": front["roles"], "runtime": "actions-anthropic"})
        config_path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
        created.append(config_path)
    goal_id = make_id("goal", f"{slug} {data.get('goal_title', 'first aim')}")
    goal_path = root / "kb/goals" / f"{goal_id}.md"
    if not goal_path.exists():
        goal_path.write_text(
            "---\n" + yaml.safe_dump({"id": goal_id, "type": "goal", "title": f"{name}: {data.get('goal_title', data['intent'][:60])}", "status": "proposed", "created": today, "updated": today, "author_runtime": "claude-code", "roles": [slug, *front["roles"]], "links": [f"agents/{slug}/persona.md"], "parent": None, "success_test": data.get("success", "Checkable from the public event log."), "score": 0.5}, sort_keys=False)
            + "---\n\n" + data["intent"] + "\n", encoding="utf-8", newline="\n")
        created.append(goal_path)
    for index, bet in enumerate(data.get("bets", [])[:3], start=1):
        hyp_id = make_id("hypothesis", f"{slug} {bet.get('slug', f'bet {index}')}")
        hyp_path = root / "kb/hypotheses" / f"{hyp_id}.md"
        if not hyp_path.exists():
            hyp_path.write_text(
                "---\n" + yaml.safe_dump({"id": hyp_id, "type": "hypothesis", "title": bet["title"], "status": "proposed", "created": today, "updated": today, "author_runtime": "claude-code", "roles": [slug], "links": [f"agents/{slug}/metrics.yaml"], "prediction": bet.get("prediction", ""), "falsifier": bet.get("falsifier", ""), "prereg_commit": "", "window_start_utc": ""}, sort_keys=False)
                + "---\n\n" + bet.get("rationale", "Approach bet filed from the hg-new-agent interview.") + "\n", encoding="utf-8", newline="\n")
            created.append(hyp_path)
    persona = load_persona(root, slug)
    target = caller_path(root, slug)
    from hglab.workflows import caller_text

    target.write_text(caller_text(persona), encoding="utf-8", newline="\n")
    created.append(target)
    return created


def _social_rate(root: Path, slug: str) -> int:
    try:
        return load_persona(root, slug).social_rate
    except (FileNotFoundError, ValueError):
        return 0


# --- team commands -----------------------------------------------------------


@team_app.command("list")
def team_list() -> None:
    for slug, team in load_teams(root_dir()).items():
        typer.echo(f"{slug:<18} {team.name:<24} members {', '.join(team.members)}  territory {'confirmed' if team.binding_territory else ('proposed' if team.territory else 'none')}  says/h {team.social_budget['says_per_hour']}")


@team_app.command("set-territory")
def team_set_territory(
    team: str = typer.Option(..., "--team"),
    x: int = typer.Option(..., "--x"),
    y: int = typer.Option(..., "--y"),
    radius: int = typer.Option(8, "--radius"),
    confirm: bool = typer.Option(False, "--confirm", help="Mark the territory confirmed (binding for stay_inside and walls)."),
    note: str = typer.Option("", "--note"),
) -> None:
    """Record a team territory (proposed by default). Confirming is the owner's call."""
    root = root_dir()
    path = root / "teams" / f"{team}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    data["territory"] = {"kind": "circle", "x": x, "y": y, "radius": radius, "status": "confirmed" if confirm else "proposed"}
    if note:
        data["territory"]["note"] = note
    if not data.get("home"):
        data["home"] = {"x": x, "y": y, "status": "confirmed" if confirm else "proposed"}
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8", newline="\n")
    errors = validate_personas(root)
    if errors:
        raise typer.BadParameter("\n".join(errors))
    typer.echo(f"{team}: territory circle ({x},{y}) r{radius} {'confirmed' if confirm else 'proposed'}.")


# --- influence ---------------------------------------------------------------


@influence_app.command("compute")
def influence_compute(
    team: str = typer.Option(..., "--team"),
    fixtures: bool = typer.Option(False, "--fixtures", help="Use the committed fixtures."),
    events: list[Path] = typer.Option([], "--events"),  # noqa: B008
    runs: list[Path] = typer.Option([], "--runs"),  # noqa: B008
    fetch_public: bool = typer.Option(False, "--fetch-public"),
    tick: int | None = typer.Option(None, "--tick"),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Recompute every influence signal and link for a team."""
    root = root_dir()
    inputs = gather_inputs(root, fixtures=fixtures, events_paths=events, runs_paths=runs, fetch_public=fetch_public, tick=tick)
    team_obj = load_team(root, team)
    result = compute_team(team_obj, inputs["personas"], inputs["events"], inputs["runs"], inputs["tick"], kb_items=inputs["kb"])
    if as_json:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=1))
        return
    typer.echo(f"{team_obj.name} · tick {result['tick']}")
    for slug, signals in result["signals"].items():
        for name, payload in signals.items():
            typer.echo(f"  {slug:<12} {name:<12} {payload['value']:>5.1f}  {payload['explanation']}")
    typer.echo("links:")
    for link in result["links"]:
        typer.echo(f"  {link['from']} --{link['signal']} {link['decayed_value']:.0f}--> {link['to']}.{link['effect']}  ({link['plain_english']})")
    for slug in team_obj.members:
        effects = incoming_effects(result, slug)
        if effects:
            typer.echo(f"  {slug} receives: " + ", ".join(f"{k} {v['value']:.0f}" for k, v in effects.items() if k not in SIGNALS))


# --- pulse -------------------------------------------------------------------


def run_pulse(
    root: Path,
    slugs: list[str],
    *,
    fixtures: bool,
    events_paths: list[Path],
    runs_paths: list[Path],
    fetch_public: bool,
    judge: bool,
    out: Path,
    tick: int | None,
    today: str | None,
    write_team_and_community: bool = True,
) -> dict[str, dict[str, Any]]:
    inputs = gather_inputs(root, fixtures=fixtures, events_paths=events_paths, runs_paths=runs_paths, fetch_public=fetch_public, tick=tick)
    personas, teams = inputs["personas"], inputs["teams"]
    team_results: dict[str, dict[str, Any]] = {}
    for team_slug, team in teams.items():
        team_results[team_slug] = compute_team(team, personas, inputs["events"], inputs["runs"], inputs["tick"], kb_items=inputs["kb"])
    pulses: dict[str, dict[str, Any]] = {}
    for slug in slugs:
        persona = personas[slug]
        metrics = load_metrics(root, slug)
        judge_result = None
        cache = out / "agents" / slug / "judge.json"
        if judge and judge_available(root):
            from hglab.budget import status as budget_status

            if budget_status(root).over:
                typer.echo(f"budget hold: {budget_status(root).reason}; judge skipped for {slug}", err=True)
                judge = False
        if judge and judge_available(root):
            judge_result = run_judge(persona, metrics, inputs["events"], inputs["runs"][slug], root, author_runtime=os.environ.get("HGLAB_RUNTIME"))
            if judge_result:
                cache.parent.mkdir(parents=True, exist_ok=True)
                cache.write_text(json.dumps(judge_result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
        if judge_result is None:
            for candidate in (cache, root / FIXTURES / "judge" / f"{slug}.json" if fixtures else None):
                if candidate and candidate.is_file():
                    judge_result = json.loads(candidate.read_text(encoding="utf-8"))
                    break
        history_path = out / "agents" / slug / "history.jsonl"
        history = load_history(history_path)
        if not history and fixtures:
            history = load_history(root / FIXTURES / "history" / f"{slug}.jsonl")
        pulse = compute_pulse(
            persona=persona, team=teams.get(persona.team), personas=personas, metrics=metrics,
            events=inputs["events"], runs=inputs["runs"][slug], now_tick=inputs["tick"], kb_items=inputs["kb"],
            judge=judge_result, history=history, team_result=team_results.get(persona.team), runs_by_slug=inputs["runs"], today=today,
        )
        write_pulse(pulse, out)
        pulses[slug] = pulse
    if write_team_and_community:
        (out / "teams").mkdir(parents=True, exist_ok=True)
        for team_slug, team in teams.items():
            if any(m in pulses for m in team.members):
                (out / "teams" / f"{team_slug}.md").write_text(render_team(team, pulses, team_results[team_slug], personas), encoding="utf-8", newline="\n")
        if set(pulses) >= set(personas):
            (out / "community.md").write_text(render_community(pulses, teams), encoding="utf-8", newline="\n")
    return pulses


def pulse_command(
    agent: str | None = typer.Option(None, "--agent"),
    team: str | None = typer.Option(None, "--team"),
    all_agents: bool = typer.Option(False, "--all"),
    fixtures: bool = typer.Option(False, "--fixtures", help="Compute from the committed fixtures (no key)."),
    events: list[Path] = typer.Option([], "--events"),  # noqa: B008
    runs: list[Path] = typer.Option([], "--runs"),  # noqa: B008
    fetch_public: bool = typer.Option(False, "--fetch-public", help="Read public events live (no key)."),
    judge: bool = typer.Option(False, "--judge", help="Run the LLM judge if a model key exists (budget-capped)."),
    out: Path = typer.Option(Path("reports"), "--out"),  # noqa: B008
    tick: int | None = typer.Option(None, "--tick"),
    today: str | None = typer.Option(None, "--today", help="Date label for history (default: today UTC)."),
) -> None:
    """Recompute the Pulse for one agent, a team, or everyone, and write the reports."""
    root = root_dir()
    personas = load_personas(root)
    if agent:
        slugs = [resolve_persona(root, agent).slug]
    elif team:
        slugs = list(load_team(root, team).members)
    elif all_agents:
        slugs = list(personas)
    else:
        raise typer.BadParameter("give --agent, --team or --all")
    pulses = run_pulse(root, slugs, fixtures=fixtures, events_paths=events, runs_paths=runs, fetch_public=fetch_public, judge=judge, out=out, tick=tick, today=today)
    for pulse in pulses.values():
        typer.echo(render_pulse(pulse).split("```")[1].strip())
        typer.echo("")
    typer.echo(f"written to {out.as_posix()}/ (metric spec v{', v'.join(sorted({str(p['metric_version']) for p in pulses.values()}))})")


# --- retro -------------------------------------------------------------------


def retro_command(
    agent: str = typer.Option(..., "--agent"),
    fixtures: bool = typer.Option(False, "--fixtures"),
    fetch_public: bool = typer.Option(False, "--fetch-public"),
    out: Path = typer.Option(Path("reports"), "--out"),  # noqa: B008
) -> None:
    """Weekly retrospective: propose persona or metric changes as a reviewable file."""
    root = root_dir()
    persona = resolve_persona(root, agent)
    pulses = run_pulse(root, [persona.slug], fixtures=fixtures, events_paths=[], runs_paths=[], fetch_public=fetch_public, judge=False, out=out, tick=None, today=None, write_team_and_community=False)
    pulse = pulses[persona.slug]
    proposals = retro_proposals(persona, pulse)
    runs = load_runs(root, persona.name, persona.slug, [root / FIXTURES / "runs" / f"{persona.slug}.jsonl"] if fixtures else [], include_local=not fixtures)
    own = []
    for run in runs[-60:]:
        for item in run.get("adaptation_proposals") or []:
            if item and item not in own:
                own.append(str(item))
    notes = [str(r.get("journal_note")) for r in runs[-60:] if r.get("journal_note")]
    paces = [str((r.get("environment") or {}).get("pace")) for r in runs[-60:] if r.get("environment")]
    path = root / "agents" / persona.slug / "RETRO.md"
    lines = [f"# {persona.name} · weekly retrospective ({pulse['date']})", "", f"Metric spec v{pulse['metric_version']}. Alive {pulse['alive']['score']} · On mission {pulse['on_mission']['score']} · In character {pulse['in_character']['score']}.", "", "Proposals from the measurements (a human approves by editing persona.md or metrics.yaml and bumping `version`):", ""]
    lines += [f"- {p}" for p in proposals] or ["- No changes proposed this week."]
    lines += ["", "Proposals the agent made from what it saw in the public feed (review before adopting; world text was treated as data):", ""]
    lines += [f"- {p}" for p in own[:12]] or ["- None recorded."]
    if paces:
        from collections import Counter

        lines += ["", "World pace seen at wake time: " + ", ".join(f"{k} {v}" for k, v in Counter(paces).most_common())]
    if notes:
        lines += ["", "Journal notes (latest first):", ""] + [f"- {n[:200]}" for n in reversed(notes[-6:])]
    lines += ["", "Working: " + pulse["approaches"]["working"], "Not working: " + pulse["approaches"]["not_working"], "Next bet: " + pulse["approaches"]["next_bet"], ""]
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    typer.echo("\n".join(lines))
    typer.echo(f"written to {path.relative_to(root).as_posix()}")


def retro_proposals(persona: Persona, pulse: dict[str, Any]) -> list[str]:
    proposals: list[str] = []
    for row in pulse["in_character"]["signatures"]:
        if row["inside"] is False:
            lo, hi = row["range"]
            proposals.append(f"signature `{row['id']}` is {row['value']} against {lo}–{hi}: either a knob drifted (check `{row['measure']}` inputs) or widen the range in metrics.yaml")
    for row in pulse["on_mission"]["rows"]:
        if row["progress"] is not None and row["progress"] < 0.3 and pulse["alive"]["parts"]["completed"] >= 20:
            proposals.append(f"key result `{row['id']}` is at {row['progress']:.0%} after {pulse['alive']['parts']['completed']} wakes: lower the target, change the approach, or drop the result")
    for row in pulse["approaches"]["rows"]:
        if row["wakes"] >= 5 and row["outcome"] in (0, 0.0) and row.get("hypothesis"):
            proposals.append(f"approach `{row['id']}` spent {row['energy']:.0f} energy over {row['wakes']} wakes with no outcome: mark {row['hypothesis']} as a refutation candidate")
    if pulse["alive"]["parts"]["completed"] < pulse["alive"]["parts"]["scheduled"] * 0.8:
        proposals.append(f"only {pulse['alive']['parts']['completed']} of {pulse['alive']['parts']['scheduled']} scheduled wakes happened: check the workflow and the cadence `{persona.knobs['cadence']['cron']}`")
    if not pulse["community"]["norms_kept"]:
        proposals.append("norm breaches: " + "; ".join(pulse["community"]["norm_breaches"]) + " — tighten the voice or territory rules")
    return proposals


# --- keepalive ---------------------------------------------------------------


def keepalive_command(
    agent: str = typer.Option(..., "--agent"),
    fixture: Path | None = typer.Option(None, "--fixture"),  # noqa: B008
    scheduled: bool = typer.Option(False, "--scheduled", help="Exit cleanly when the lease is held elsewhere"),
) -> None:
    """Observe, answer a verification challenge if one is pending, record presence. No LLM otherwise."""
    root = root_dir()
    persona = persona_by_name(root, agent)
    name = persona.name if persona else agent
    if fixture is not None:
        client: Any = FixtureClient(load_fixture(fixture))
    else:
        api_key = get_api_key(name, root)
        if not api_key:
            raise typer.BadParameter(f"no key configured for {name}")
        client = HinterglassClient(api_key=api_key)
    lease = acquire(client, name)
    if lease is None:
        if scheduled:
            typer.echo(f"{name}: lease held by another runtime; skipping this keepalive")
            raise typer.Exit(code=0)
        raise typer.BadParameter(f"identity {name} already has an active lease")
    usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    status = "ok"
    try:
        observe = client.observe()
        if observe.get("challenge"):
            if fixture is not None and not _model_key(root):
                status = "challenge_pending"
            else:
                from hglab.cli import answer_daily_challenge

                try:
                    answer_daily_challenge(client, observe, usage)
                    status = "answered"
                except (ValueError, HinterglassError) as exc:
                    status = f"lapsed: {str(exc)[:80]}"
        you = observe.get("you") or {}
        record = {
            "kind": "keepalive", "agent": name, "persona": persona.slug if persona else None,
            "tick": observe.get("tick"), "energy": you.get("energy"), "x": you.get("x"), "y": you.get("y"),
            "verification": status, "verified_until": you.get("verified_until"), "created_utc": datetime.now(UTC).isoformat(),
            "author_runtime": os.environ.get("HGLAB_RUNTIME", "human"), "usage": usage,
        }
        folder = root / "runs" / datetime.now(UTC).date().isoformat()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{name}-keepalive-{int(time.time())}.json"
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
        until = f", verified until {record['verified_until']}" if record.get("verified_until") else ""
        typer.echo(f"{name}: tick {record['tick']}, energy {record['energy']}, verification {status}{until}; recorded {path.relative_to(root).as_posix()}")
    finally:
        release(client, lease)


# --- community ---------------------------------------------------------------


@community_app.command("board")
def community_board(
    fixtures: bool = typer.Option(False, "--fixtures"),
    public: bool = typer.Option(False, "--public", help="Read the live public agents and events endpoints (no key)."),
) -> None:
    """Status board of all agents and teams."""
    root = root_dir()
    inputs = gather_inputs(root, fixtures=fixtures, events_paths=[], runs_paths=[], fetch_public=public, tick=None)
    personas, teams = inputs["personas"], inputs["teams"]
    public_agents: dict[str, dict[str, Any]] = {}
    if public:
        try:
            public_agents = {a["name"].casefold(): a for a in HinterglassClient().public_agents().get("agents", [])}
        except (HinterglassError, OSError) as exc:
            typer.echo(f"public agents fetch failed: {exc}", err=True)
    signals: dict[str, dict[str, Any]] = {}
    for team in teams.values():
        result = compute_team(team, personas, inputs["events"], inputs["runs"], inputs["tick"], kb_items=inputs["kb"])
        for slug, payload in result["signals"].items():
            signals[slug] = payload
    typer.echo(f"tick {inputs['tick']} · {len(inputs['events'])} events · {sum(len(r) for r in inputs['runs'].values())} wakes")
    typer.echo(f"{'agent':<12} {'team':<18} {'alive':<9} {'where':<10} {'energy':<7} {'goal':<36} {'signals':<30} notable")
    for team_slug, team in sorted(teams.items()):
        for slug in team.members:
            persona = personas[slug]
            runs = inputs["runs"].get(slug, [])
            last = runs[-1] if runs else None
            fixture_path = root / FIXTURES / "observe" / f"{slug}.json"
            observe = load_fixture(fixture_path) if fixtures and fixture_path.is_file() else None
            you = (observe or {}).get("you") or public_agents.get(persona.name.casefold()) or {}
            where = f"({you.get('x', '?')},{you.get('y', '?')})"
            energy = you.get("energy", "?")
            alive = "registered" if public_agents.get(persona.name.casefold()) else ("fixture" if observe else persona.status)
            own = [e for e in inputs["events"] if str(e.get("actor", "")).casefold() == persona.name.casefold()]
            notable = "; ".join(str(e.get("text", ""))[:40] for e in own[-2:]) or "—"
            sig = ", ".join(f"{k} {v['value']:.0f}" for k, v in signals.get(slug, {}).items()) or "—"
            goal = (last or {}).get("summary", persona.intent)[:36] if last else persona.intent[:36]
            typer.echo(f"{persona.name:<12} {team.name:<18} {alive:<9} {where:<10} {energy!s:<7} {goal:<36} {sig:<30} {notable}")


@community_app.command("round")
def community_round(
    dry_run: bool = typer.Option(True, "--dry-run/--live"),
    fixtures: bool = typer.Option(True, "--fixtures/--no-fixtures"),
    planner: str = typer.Option("heuristic", "--planner"),
    seed: str | None = typer.Option(None, "--seed"),
) -> None:
    """Each agent takes one turn in cadence order, respecting leases."""
    root = root_dir()
    personas = load_personas(root)
    order = sorted(personas.values(), key=lambda p: int(p.knobs["cadence"]["cron"].split()[0].split(",")[0]))
    for persona in order:
        fixture = root / FIXTURES / "observe" / f"{persona.slug}.json" if fixtures else None
        if fixtures and not fixture.is_file():
            typer.echo(f"{persona.name}: no fixture, skipped")
            continue
        try:
            persona_tick(root, persona, role=None, dry_run=dry_run, fixture=fixture, planner=planner, seed=seed, events_paths=[], jitter_minutes=0, scheduled=False)
        except typer.BadParameter as exc:
            typer.echo(f"{persona.name}: {exc}")
        typer.echo("")


@community_app.command("scene")
def community_scene(
    name: str = typer.Option(..., "--scene", help=", ".join(SCENES)),
    dry_run: bool = typer.Option(True, "--dry-run/--live"),
    seed: str | None = typer.Option("scene", "--seed"),
) -> None:
    """Stage a team scene from fixtures, for example Grandad Pail boasts and Fudgewright audits."""
    root = root_dir()
    if name not in SCENES:
        raise typer.BadParameter(f"unknown scene; choose from {', '.join(SCENES)}")
    carried: list[dict[str, Any]] = []
    for slug, mode in SCENES[name]:
        persona = load_persona(root, slug)
        fixture = root / FIXTURES / "observe" / f"{slug}.json"
        typer.echo(f"--- {persona.name} ({mode}) ---")
        record = persona_tick(root, persona, role=None, dry_run=dry_run, fixture=fixture, planner="heuristic", seed=seed, events_paths=[], jitter_minutes=0, scheduled=False, force_mode=mode, extra_events=carried)
        payload = load_fixture(fixture)
        you = payload.get("you") or {}
        for action in record.get("actions", []):
            if action.get("action") == "say":
                carried.append({
                    "id": 10_000 + len(carried), "tick": int(payload.get("tick", 0)), "type": "say", "actor": persona.name,
                    "x": you.get("x"), "y": you.get("y"), "text": f"{persona.name} says: {action['text']}", "data": {"text": action["text"]},
                })
        typer.echo("")


@community_app.command("retro")
def community_retro(fixtures: bool = typer.Option(False, "--fixtures"), out: Path = typer.Option(Path("reports"), "--out")) -> None:  # noqa: B008
    """Community retrospective: every Pulse plus the cross-agent approaches table."""
    root = root_dir()
    pulses = run_pulse(root, list(load_personas(root)), fixtures=fixtures, events_paths=[], runs_paths=[], fetch_public=False, judge=False, out=out, tick=None, today=None)
    typer.echo((out / "community.md").read_text(encoding="utf-8"))
    typer.echo(f"{len(pulses)} pulses written under {out.as_posix()}/")


# --- deploy ------------------------------------------------------------------


@deploy_app.command("check")
def deploy_check(agent: str = typer.Option(..., "--agent")) -> None:
    """Check secret presence by name, regenerate the caller, and print the exact variable to flip."""
    root = root_dir()
    persona = resolve_persona(root, agent)
    errors = validate_personas(root)
    if errors:
        raise typer.BadParameter("\n".join(errors))
    _done, problems = generate_callers(root, check=False)
    typer.echo(f"caller workflow: .github/workflows/agent-{persona.slug}.yml ({'current' if not problems else '; '.join(problems)})")
    secret = persona.secret_name
    present = secret_exists(secret)
    typer.echo(f"secret {secret}: {'present' if present else 'MISSING' if present is False else 'unknown (gh not available)'}")
    typer.echo(f"variable to flip: {persona.variable_name} = on   (gh variable set {persona.variable_name} --body on)")
    typer.echo("kill switch: HG_ENABLED must also be 'true'; set it last, unset it first.")
    typer.echo(f"dry run on Actions: gh workflow run agent-{persona.slug}.yml -f job=tick -f dry_run=true")
    typer.echo(f"keep {persona.variable_name} off while you play {persona.name} locally; the lease prevents double driving but one path is clearer.")


def secret_exists(name: str) -> bool | None:
    try:
        result = subprocess.run(["gh", "secret", "list", "--json", "name"], capture_output=True, text=True, check=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    try:
        names = {item.get("name") for item in json.loads(result.stdout or "[]")}
    except json.JSONDecodeError:
        return None
    return name in names


# --- reports -----------------------------------------------------------------


@reports_app.command("pull")
def reports_pull(branch: str = typer.Option("reports", "--branch"), remote: str = typer.Option("origin", "--remote")) -> None:
    """Fetch the reports branch and unpack reports/ into the working tree."""
    root = root_dir()
    fetch = subprocess.run(["git", "fetch", remote, f"{branch}:refs/remotes/{remote}/{branch}"], check=False, capture_output=True, text=True, cwd=root)
    if fetch.returncode != 0:
        raise typer.BadParameter(f"no {branch} branch on {remote} yet ({fetch.stderr.strip()[:120]})")
    archive = subprocess.run(["git", "archive", "--format=tar", f"{remote}/{branch}", "reports"], capture_output=True, cwd=root, check=True)
    count = 0
    with tarfile.open(fileobj=io.BytesIO(archive.stdout), mode="r:") as tar:
        for member in tar.getmembers():
            if not member.name.startswith("reports/") or ".." in member.name:
                continue
            tar.extract(member, path=root, filter="data")
            count += 1
    typer.echo(f"pulled {count} entries into reports/ from {remote}/{branch}")


# --- world -------------------------------------------------------------------

world_app = typer.Typer(help="The public feed as the site shows it: All, Building, Trade & Goals, Talk, Factions.")


@world_app.command("digest")
def world_digest(
    agent: str | None = typer.Option(None, "--agent", help="Read it from this persona's point of view (team vs peers)."),
    fixtures: bool = typer.Option(False, "--fixtures"),
    fetch_public: bool = typer.Option(True, "--fetch-public/--no-fetch-public", help="Read the live public feed (no key)."),
    as_json: bool = typer.Option(False, "--json"),
) -> None:
    """Pace of change, counts by category, who is active, headlines, open peer goals."""
    from hglab.environment import render

    root = root_dir()
    inputs = gather_inputs(root, fixtures=fixtures, events_paths=[], runs_paths=[], fetch_public=fetch_public and not fixtures, tick=None)
    personas = inputs["personas"]
    persona = resolve_persona(root, agent) if agent else next(iter(personas.values()))
    team = inputs["teams"].get(persona.team)
    result = build_environment(root, persona, team, personas, inputs, live=fetch_public and not fixtures)
    if result is None:
        raise typer.BadParameter("no public events available; try --fetch-public or --fixtures")
    typer.echo(json.dumps(result, ensure_ascii=False, indent=1) if as_json else render(result))


@world_app.command("watch")
def world_watch(
    snapshot_file: Path = typer.Option(Path("reports/world/features.json"), "--snapshot-file", help="Where the last look is kept"),  # noqa: B008
    write_kb: bool = typer.Option(False, "--write-kb", help="File one idea card per discovery for the archivist"),
    as_json: bool = typer.Option(False, "--json"),
    catalogue: bool = typer.Option(False, "--catalogue", help="Also print the buildable-structure catalogue with costs"),
) -> None:
    """What changed in the game's public surface since the last look (API, guide, event and structure types, factions, residents)."""
    from hglab.features import catalogue_line, compact, compare, snapshot
    from hglab.kb import make_id

    root = root_dir()
    previous = json.loads(snapshot_file.read_text(encoding="utf-8")) if snapshot_file.is_file() else None
    current = snapshot(HinterglassClient())
    discoveries = compare(previous, current)
    snapshot_file.parent.mkdir(parents=True, exist_ok=True)
    snapshot_file.write_text(json.dumps(compact(current), ensure_ascii=False, indent=1) + "\n", encoding="utf-8", newline="\n")
    if as_json:
        typer.echo(json.dumps({"current": compact(current), "discoveries": discoveries}, ensure_ascii=False, indent=1))
    else:
        typer.echo(f"API {current['api_version']} · tick {current['tick']} · {current['agent_count']} agents · {len(current['event_types'])} event types · {len(current['structure_types'])} structure types · {len(current['factions'])} faction(s)")
        for d in discoveries:
            typer.echo(f"  [{d['kind']}] {d['text']}")
        if not discoveries:
            typer.echo("  nothing new since the last look")
        if catalogue and current.get("blueprint_rows"):
            typer.echo("  catalogue: " + catalogue_line(current["blueprint_rows"]))
            for name, row in current["blueprint_rows"].items():
                typer.echo(f"    {name:<11} {row['cost']:<22} hp {row['hp']:<4} {row['terrain']:<14} {row['function']}")
    if write_kb:
        today = datetime.now(UTC).date().isoformat()
        for d in discoveries:
            if d["kind"] in {"first_look"}:
                continue
            item_id = make_id("idea", f"feature {d['kind']} {current['tick']}")
            path = root / "kb/ideas" / f"{item_id}.md"
            if path.exists():
                continue
            path.write_text(
                "---\n" + yaml.safe_dump({"id": item_id, "type": "idea", "title": d["text"][:80], "status": "proposed", "created": today, "updated": today, "author_runtime": os.environ.get("HGLAB_RUNTIME", "human"), "roles": ["town-crier", "observer"], "links": ["src/hglab/features.py"]}, sort_keys=False)
                + "---\n\n## Technique\nfeature watch: public surface compared with the last snapshot\n\n## Why it might work\n"
                + d["text"] + "\n\n## Cheapest test\nRead the guide and the public log for the named type or version.\n\n## Kill criterion\nThe change is absent from both on a second look.\n",
                encoding="utf-8", newline="\n",
            )
            typer.echo(f"  filed {path.relative_to(root).as_posix()}")


# --- budget ------------------------------------------------------------------

budget_app = typer.Typer(help="Model spend: month-to-date from usage records, caps, and a projection.")


@budget_app.command("status")
def budget_status_command(project: bool = typer.Option(False, "--project", help="Also project a month from cadences and routes.")) -> None:
    """Show estimated spend this month and today against the caps."""
    from hglab.budget import projected_month, status

    root = root_dir()
    state = status(root)
    typer.echo(f"month to date: ${state.month_usd:.2f} of ${state.monthly_cap_usd:.2f} cap · today: ${state.today_usd:.2f} of ${state.daily_cap_usd:.2f} · {state.calls} call(s)")
    for model, cost in sorted(state.by_model.items()):
        typer.echo(f"  {model:<22} ${cost:.4f}")
    if state.over:
        typer.echo(f"HOLD: {state.reason}; wakes fall back to the deterministic planner and the judge is skipped")
    if project:
        typer.echo("projection for a full month at the configured mix:")
        for key, value in projected_month(root).items():
            typer.echo(f"  {key:<40} ${value:.2f}")


@reports_app.command("prune")
def reports_prune(days: int = typer.Option(14, "--days"), folder: Path = typer.Option(Path("reports"), "--folder")) -> None:  # noqa: B008
    """Delete run records older than N days under reports/agents/*/runs (pulses and history stay)."""
    cutoff = datetime.now(UTC).timestamp() - days * 86400
    removed = 0
    for path in folder.glob("agents/*/runs/*/*.json"):
        try:
            created = json.loads(path.read_text(encoding="utf-8")).get("created_utc")
            when = datetime.fromisoformat(created).timestamp() if created else path.stat().st_mtime
        except (json.JSONDecodeError, ValueError, OSError):
            when = path.stat().st_mtime
        if when < cutoff:
            path.unlink()
            removed += 1
    for day_dir in folder.glob("agents/*/runs/*"):
        if day_dir.is_dir() and not any(day_dir.iterdir()):
            day_dir.rmdir()
    typer.echo(f"pruned {removed} record(s) older than {days} days")


# --- registration -------------------------------------------------------------


def register_persona_commands(app: typer.Typer) -> None:
    app.add_typer(persona_app, name="persona")
    app.add_typer(team_app, name="team")
    app.add_typer(influence_app, name="influence")
    app.add_typer(community_app, name="community")
    app.add_typer(deploy_app, name="deploy")
    app.add_typer(reports_app, name="reports")
    app.add_typer(budget_app, name="budget")
    app.add_typer(crier_app, name="crier")
    app.add_typer(land_app, name="land")
    app.add_typer(world_app, name="world")
    app.command("pulse")(pulse_command)
    app.command("shift")(shift_command)
    app.command("retro")(retro_command)
    app.command("keepalive")(keepalive_command)


__all__ = ["MEASURES", "persona_tick", "register_persona_commands", "run_pulse", "scaffold_agent"]
