"""Command-line entry point."""

from __future__ import annotations

import getpass
import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import jsonschema
import typer
import yaml

from hglab.actions import redact_observe, validate_actions
from hglab.challenge import answer_with_retries, finalize_answer, response_schema
from hglab.client import HinterglassClient, HinterglassError
from hglab.config import validate_config
from hglab.kb import FRONT_MATTER, build_index, create, validate
from hglab.lease import Lease, acquire, release
from hglab.limits import action_limits
from hglab.llm import structured_call
from hglab.loop import build_prompt, run_wake
from hglab.observatory import Observatory
from hglab.outage import tolerate_outage
from hglab.persona import persona_by_name, validate_personas
from hglab.prove import prove_all, prove_claim
from hglab.secrets import get_api_key, get_secret, set_github_secret, store_api_key, store_secret
from hglab.workflows import generate_callers

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

app = typer.Typer(help="Safe tools for the Hinterglass research collective.")
kb_app = typer.Typer(help="Curate the local knowledge base.")
config_app = typer.Typer(help="Validate repository configuration.")
lease_app = typer.Typer(help="Manage identity leases.")
observatory_app = typer.Typer(help="Collect unauthenticated public data.")
key_app = typer.Typer(help="Store model credentials without passing them on the command line.")
app.add_typer(kb_app, name="kb")
app.add_typer(config_app, name="config")
app.add_typer(lease_app, name="lease")
app.add_typer(observatory_app, name="observatory")
app.add_typer(key_app, name="key")
from hglab.local.cli import local_app

app.add_typer(local_app, name="local")


def repo_root() -> Path:
    return Path.cwd()


def challenge_responder(prompt: str, usage: dict[str, int] | None = None) -> str:
    root = repo_root()
    budget = yaml.safe_load((root / "config/budget.yaml").read_text(encoding="utf-8"))["tick"]
    if usage and usage["calls"] >= budget["max_llm_calls"]:
        raise ValueError("tick LLM call budget exhausted")
    output_tokens = min(500, budget["max_output_tokens"] - (usage or {}).get("output_tokens", 0))
    if output_tokens < 1:
        raise ValueError("tick output-token budget exhausted")
    instructions = (
        "Answer this verification challenge exactly and reply with the JSON object only, using the keys it names."
        " Hard rules: a word limit is strict (count the words); a quoted word must appear verbatim; 'one word' means"
        " a single word with no punctuation; 'two lines' or 'three lines' means separate lines joined with a newline;"
        " an arithmetic or distance answer is a plain integer. The challenge:\n"
    )
    result = structured_call(
        "challenge",
        instructions + prompt,
        response_schema(prompt),
        root=root,
        output_tokens=output_tokens,
    )
    if usage is not None:
        usage.update(
            calls=usage["calls"] + 1,
            input_tokens=usage["input_tokens"] + result.input_tokens,
            output_tokens=usage["output_tokens"] + result.output_tokens,
            model=result.model,
            provider=result.provider,
            route="challenge",
        )
    return json.dumps(finalize_answer(prompt, result.value))


def answer_daily_challenge(
    client: HinterglassClient, observe: dict, usage: dict[str, int] | None = None
) -> bool:
    challenge = observe.get("challenge")
    if not challenge:
        return False
    pending = [challenge]

    def fetch() -> tuple[str, str]:
        fresh = pending.pop() if pending else client.observe().get("challenge")
        if not fresh:
            raise ValueError("observe returned no verification challenge")
        return fresh["id"], fresh["prompt"]

    def submit(challenge_id: str, answer: dict) -> dict:
        try:
            return client.verify(challenge_id, answer)
        except HinterglassError as error:
            if error.code in {"challenge_failed", "challenge_expired", "verification_required"}:
                # a failed answer comes back as 403 verification_required with a fresh challenge in the body
                fresh = error.details.get("challenge") if isinstance(error.details, dict) else None
                if isinstance(fresh, dict) and fresh.get("id") and fresh.get("prompt"):
                    pending.append(fresh)
                return {"ok": False}
            raise

    result = answer_with_retries(
        fetch, lambda prompt: challenge_responder(prompt, usage), submit, retries=2
    )
    if not result.get("ok"):
        raise ValueError("daily verification did not succeed")
    return True


def ensure_verified(client: HinterglassClient, usage: dict[str, int] | None = None) -> bool:
    """Observe and answer a pending verification challenge before anything else.

    Once verification lapses every action but observe answers 403, the lease included, so this
    runs before the lease is taken. Returns True when a challenge was answered.
    """
    observe = client.observe()
    if not observe.get("challenge"):
        return False
    answer_daily_challenge(client, observe, usage)
    return True


@app.command()
def doctor() -> None:
    """Check local setup without contacting the world or exposing key values."""
    root = repo_root()
    missing = [
        path
        for path in ("config/agents.yaml", "config/models.yaml", ".mcp.json")
        if not (root / path).exists()
    ]
    typer.echo(f"Python: {sys.version_info.major}.{sys.version_info.minor}")
    try:
        agents = yaml.safe_load((root / "config/agents.yaml").read_text(encoding="utf-8"))["agents"]
        has_key = any(get_api_key(item["name"], root) for item in agents)
    except (OSError, KeyError, TypeError, yaml.YAMLError):
        has_key = False
    typer.echo(f"Hinterglass key configured: {'yes' if has_key else 'no'}")
    typer.echo(
        "Model keys configured: "
        f"Anthropic {'yes' if get_secret('ANTHROPIC_API_KEY', root) else 'no'}, "
        f"OpenAI {'yes' if get_secret('OPENAI_API_KEY', root) else 'no'}, "
        f"GCP service account {'yes' if get_secret('GCP_SERVICE_ACCOUNT_KEY', root) else 'no'}"
    )
    typer.echo(f"Missing local files: {', '.join(missing) if missing else 'none'}")
    persona_errors = validate_personas(root)
    from hglab.persona import list_persona_slugs

    typer.echo(
        f"Personas: {len(list_persona_slugs(root))} ({'valid' if not persona_errors else str(len(persona_errors)) + ' problem(s); run hglab persona validate'})"
    )
    typer.echo("Connectivity not checked; no live request was made.")


@app.command()
def observe(
    agent: str = typer.Option(..., "--agent"), as_json: bool = typer.Option(False, "--json")
) -> None:
    """Observe an identity and redact private fields before display."""
    api_key = get_api_key(agent, repo_root())
    if not api_key:
        raise typer.BadParameter(f"no key configured for {agent}")
    result = redact_observe(HinterglassClient(api_key=api_key).observe())
    if as_json:
        typer.echo(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        typer.echo(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))


@app.command()
@tolerate_outage
def tick(
    agent: str = typer.Option(
        ..., "--agent", help="Persona slug, in-world name, or legacy identity"
    ),
    role: str | None = typer.Option(
        None, "--role", help="Hat to wear (default: the persona's first role)"
    ),
    dry_run: bool = typer.Option(False, "--dry-run"),
    fixture: Path | None = typer.Option(
        None, "--fixture", help="Observe fixture: keyless, offline wake"
    ),  # noqa: B008
    planner: str = typer.Option("auto", "--planner", help="heuristic, llm, or auto"),
    seed: str | None = typer.Option(None, "--seed", help="Replay seed for the persona planner"),
    events: list[Path] = typer.Option(
        [], "--events", help="Public event archives for influence signals"
    ),  # noqa: B008
    jitter_minutes: int = typer.Option(0, "--jitter-minutes"),
    scheduled: bool = typer.Option(
        False, "--scheduled", help="Mark the record as a scheduled wake"
    ),
) -> None:
    """Run a leased, validated wake; use --dry-run to plan without actions.

    Agents with a persona (agents/<slug>/persona.md) take a persona wake: mood, mode, knobs
    and the deterministic planner, with the LLM planner when a model key exists. Pass
    --fixture to run any persona offline with no key at all.
    """
    root = repo_root()
    persona = persona_by_name(root, agent)
    if persona is not None:
        from hglab.cli_personas import persona_tick

        persona_tick(
            root,
            persona,
            role=role,
            dry_run=dry_run,
            fixture=fixture,
            planner=planner,
            seed=seed,
            events_paths=list(events),
            jitter_minutes=jitter_minutes,
            scheduled=scheduled,
        )
        return
    if role is None:
        raise typer.BadParameter("--role is required for identities without a persona")
    api_key = get_api_key(agent, repo_root())
    if not api_key:
        raise typer.BadParameter(f"no key configured for {agent}")
    client = HinterglassClient(api_key=api_key)
    charter_path = root / "roles" / f"{role}.md"
    if not charter_path.is_file():
        raise typer.BadParameter(f"unknown role: {role}")
    charter = charter_path.read_text(encoding="utf-8")
    front_matter, body = charter.split("---", 2)[1:]
    role_config = yaml.safe_load(front_matter)
    skills = [
        (root / "skills" / name / "SKILL.md").read_text(encoding="utf-8")
        for name in role_config["skills"]
        if (root / "skills" / name / "SKILL.md").exists()
    ]
    from hglab.wake import normalise_plan, plan_schema

    action_schema = json.loads((root / "schemas/action.json").read_text())
    schema = plan_schema(action_schema)
    lease = acquire(client, agent)
    if lease is None:
        raise typer.BadParameter(f"identity {agent} already has an active lease")
    usage = {"calls": 0, "input_tokens": 0, "output_tokens": 0}
    try:
        observe = client.observe()
        answer_daily_challenge(client, observe, usage)
    except Exception:
        release(client, lease)
        raise

    def planner(current_observe: dict) -> dict:
        prompt = build_prompt(
            body,
            (root / "kb/NORTH_STAR.md").read_text(encoding="utf-8"),
            skills,
            current_observe.get("notebook", {}),
            current_observe,
            action_schema,
        )
        budget = yaml.safe_load((root / "config/budget.yaml").read_text(encoding="utf-8"))["tick"]
        if usage["calls"] >= budget["max_llm_calls"]:
            raise ValueError("tick LLM call budget exhausted")
        output_tokens = min(1600, budget["max_output_tokens"] - usage["output_tokens"])
        if output_tokens < 1:
            raise ValueError("tick output-token budget exhausted")
        result = structured_call(
            role_config["model_route"],
            prompt,
            schema,
            root=root,
            output_tokens=output_tokens,
            author_runtime=os.environ.get("HGLAB_RUNTIME", "human"),
        )
        usage.update(
            calls=usage["calls"] + 1,
            input_tokens=usage["input_tokens"] + result.input_tokens,
            output_tokens=usage["output_tokens"] + result.output_tokens,
            model=result.model,
            provider=result.provider,
        )
        return normalise_plan(result.value)

    record = run_wake(
        agent=agent,
        role=role,
        client=client,
        lease=lease,
        planner=planner,
        prompt_data=lambda value: value,
        output_dir=root / "runs" / datetime.now(UTC).date().isoformat(),
        dry_run=dry_run,
        author_runtime=os.environ.get("HGLAB_RUNTIME", "human"),
        usage=usage,
    )
    typer.echo(f"Run {record['run_id']} recorded; actions: {len(record['actions'])}.")
    if summary_path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(summary_path).open("a", encoding="utf-8") as summary:
            summary.write(
                f"\n### hglab usage\n\n- Calls: {usage['calls']}\n"
                f"- Input tokens: {usage['input_tokens']}\n"
                f"- Output tokens: {usage['output_tokens']}\n"
            )


@app.command()
def register(
    name: str = typer.Option(..., "--name"),
    bio: str = typer.Option(
        "Hinterglass Research Collective; we publish analyses of public events.", "--bio"
    ),
    to_gh_secret: bool = typer.Option(False, "--to-gh-secret"),
) -> None:
    """Register an identity, solve its proof challenge, and store the key safely."""
    client = HinterglassClient()

    def fetch() -> tuple[str, str]:
        payload = client.request("POST", "/api/v1/register", json={"name": name, "bio": bio})
        return payload["challenge_id"], payload["prompt"]

    def responder(prompt: str) -> str:
        return json.dumps(
            structured_call(
                "challenge",
                prompt,
                response_schema(prompt),
                root=repo_root(),
                output_tokens=500,
            ).value
        )

    def submit(challenge_id: str, answer: dict) -> dict:
        try:
            return client.request(
                "POST",
                "/api/v1/register/complete",
                json={"challenge_id": challenge_id, "answer": answer},
            )
        except HinterglassError as error:
            if error.code in {"challenge_failed", "challenge_expired"}:
                return {"ok": False}
            raise

    completed = answer_with_retries(fetch, responder, submit, retries=2)
    api_key = completed["api_key"]
    store_api_key(name, api_key)
    if to_gh_secret:
        set_github_secret(name, api_key)
    typer.echo(f"Registered {name}; key stored securely.")


register_app = typer.Typer(
    help="Two-step registration where the operator (or the chat assistant) answers the challenge."
)
app.add_typer(register_app, name="register-manual")


@register_app.command("start")
def register_manual_start(
    name: str = typer.Option(..., "--name"),
    bio: str | None = typer.Option(None, "--bio", help="Defaults to the persona's profile bio"),
    challenge_file: Path = typer.Option(Path("runs/.challenge.json"), "--challenge-file"),  # noqa: B008
) -> None:
    """Post the registration and print the 25-second challenge prompt; answer with `answer`."""
    root = repo_root()
    if bio is None:
        persona = persona_by_name(root, name)
        bio = (
            persona.profile["bio"]
            if persona
            else "Hinterglass Research Collective; we publish analyses of public events."
        )
    payload = HinterglassClient().request(
        "POST", "/api/v1/register", json={"name": name, "bio": bio}
    )
    challenge_file.parent.mkdir(parents=True, exist_ok=True)
    challenge_file.write_text(
        json.dumps(
            {
                "name": name,
                "challenge_id": payload["challenge_id"],
                "started_utc": datetime.now(UTC).isoformat(),
            }
        ),
        encoding="utf-8",
    )
    typer.echo(
        f"Challenge for {name}, expires in {payload.get('expires_in_seconds', 25)} seconds. Prompt:"
    )
    typer.echo(payload["prompt"])


@register_app.command("answer")
def register_manual_answer(
    answer: str = typer.Option(..., "--answer", help="The JSON object the prompt asked for"),
    challenge_file: Path = typer.Option(Path("runs/.challenge.json"), "--challenge-file"),  # noqa: B008
    to_gh_secret: bool = typer.Option(False, "--to-gh-secret"),
) -> None:
    """Submit the answer, store the key in the keyring (never printed), optionally as a GitHub secret."""
    data = json.loads(challenge_file.read_text(encoding="utf-8"))
    parsed = json.loads(answer)
    if not isinstance(parsed, dict):
        raise typer.BadParameter("the answer must be a JSON object")
    try:
        completed = HinterglassClient().request(
            "POST",
            "/api/v1/register/complete",
            json={"challenge_id": data["challenge_id"], "answer": parsed},
        )
    except HinterglassError as error:
        challenge_file.unlink(missing_ok=True)
        raise typer.BadParameter(f"registration failed: {error.code}: {error.message}") from error
    challenge_file.unlink(missing_ok=True)
    name = data["name"]
    store_api_key(name, completed["api_key"])
    where = "the OS keyring"
    if to_gh_secret:
        set_github_secret(name, completed["api_key"])
        where += f" and GitHub secret HG_KEY_{name.upper().replace('-', '_')}"
    typer.echo(
        f"Registered {name}; key stored in {where}. Agent id {completed.get('agent', {}).get('id', '?')}."
    )


@app.command()
def act(
    agent: str = typer.Option(..., "--agent"),
    role: str = typer.Option(..., "--role"),
    action: str = typer.Argument(...),
    params: list[str] = typer.Argument(None),  # noqa: B008
) -> None:
    """Validate and execute one explicitly requested action."""
    api_key = get_api_key(agent, repo_root())
    if not api_key:
        raise typer.BadParameter(f"no key configured for {agent}")
    values = {}
    text_fields = {"text", "title", "description", "bio", "goals", "motto", "to", "name", "key"}
    for pair in params or []:
        if "=" not in pair:
            raise typer.BadParameter(f"expected key=value, got {pair!r}")
        key, value = pair.split("=", 1)
        values[key] = value if key in text_fields else yaml.safe_load(value)
    client = HinterglassClient(api_key=api_key)
    ensure_verified(client)
    lease = acquire(client, agent)
    if lease is None:
        raise typer.BadParameter(f"identity {agent} already has an active lease")
    try:
        observe = client.observe()
        recent_say_count, open_goal_count, prior_text = action_limits(observe)
        validated = validate_actions(
            [{"action": action, **values}],
            role,
            recent_say_count=recent_say_count,
            open_goal_count=open_goal_count,
            prior_text=prior_text,
            observe=observe,
        )[0]
        from hglab.actions import redact_result

        result = client.act(validated.model_dump(exclude_none=True))
        typer.echo(json.dumps(redact_result(result), ensure_ascii=False))
    finally:
        release(client, lease)


@app.command()
def verify(agent: str = typer.Option(..., "--agent")) -> None:
    """Answer a daily verification challenge returned by observe."""
    api_key = get_api_key(agent, repo_root())
    if not api_key:
        raise typer.BadParameter(f"no key configured for {agent}")
    client = HinterglassClient(api_key=api_key)
    lease = acquire(client, agent)
    if lease is None:
        raise typer.BadParameter(f"identity {agent} already has an active lease")
    try:
        verified = answer_daily_challenge(client, client.observe())
        typer.echo("Verification succeeded." if verified else "Identity is currently verified.")
    finally:
        release(client, lease)


@app.command()
def sync(check: bool = typer.Option(False, "--check")) -> None:
    """Generate Claude assets from canonical roles and skills (once present)."""
    root = repo_root()
    generated = []
    errors = []
    role_schema = json.loads((root / "schemas/role-frontmatter.json").read_text(encoding="utf-8"))
    skill_schema = json.loads((root / "schemas/skill-frontmatter.json").read_text(encoding="utf-8"))
    for source in sorted((root / "roles").glob("*.md")):
        if source.name == "README.md":
            continue
        target = root / ".claude/agents" / source.name
        body = source.read_text(encoding="utf-8")
        match = FRONT_MATTER.match(body)
        if not match:
            errors.append(f"{source.relative_to(root)}: missing front matter")
            continue
        try:
            metadata = yaml.safe_load(match.group(1))
            jsonschema.validate(metadata, role_schema)
            if metadata["name"] != source.stem:
                raise ValueError("role name must match filename")
        except (jsonschema.ValidationError, ValueError, TypeError) as error:
            errors.append(f"{source.relative_to(root)}: {error}")
            continue
        if body.startswith("---"):
            body = body.split("---", 2)[2].lstrip()
        generated_text = f"---\nname: {source.stem}\ndescription: Canonical role charter for {source.stem}.\n---\n\n{body}"
        generated.append((target, generated_text))
    for source in sorted((root / "skills").glob("*/SKILL.md")):
        target = root / ".claude/skills" / source.parent.name / "SKILL.md"
        content = source.read_text(encoding="utf-8")
        match = FRONT_MATTER.match(content)
        if not match:
            errors.append(f"{source.relative_to(root)}: missing front matter")
            continue
        try:
            metadata = yaml.safe_load(match.group(1))
            jsonschema.validate(metadata, skill_schema)
            if metadata["name"] != source.parent.name:
                raise ValueError("skill name must match directory")
        except (jsonschema.ValidationError, ValueError, TypeError) as error:
            errors.append(f"{source.relative_to(root)}: {error}")
            continue
        generated.append((target, content))
    errors.extend(validate_personas(root))
    if errors:
        raise typer.BadParameter("\n".join(errors))
    stale = []
    for target, text in generated:
        if check:
            if not target.exists() or target.read_text(encoding="utf-8") != text:
                stale.append(str(target.relative_to(root)))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8", newline="\n")
    callers, problems = generate_callers(root, check=check)
    if stale:
        raise typer.BadParameter(f"generated assets stale: {', '.join(stale)}")
    if problems:
        raise typer.BadParameter("agent workflows out of sync:\n" + "\n".join(problems))
    typer.echo(
        f"Claude assets and {len(callers)} agent workflow(s) are current."
        if check
        else f"Generated {len(generated)} Claude assets and {len(callers)} agent workflow(s)."
    )


@kb_app.command("validate")
def kb_validate() -> None:
    errors = validate(repo_root())
    if errors:
        raise typer.BadParameter("\n".join(errors))
    typer.echo("Knowledge base valid.")


@config_app.command("validate")
def config_validate() -> None:
    errors = validate_config(repo_root()) + validate_personas(repo_root())
    if errors:
        raise typer.BadParameter("\n".join(errors))
    typer.echo("Configuration valid.")


@kb_app.command("index")
def kb_index() -> None:
    typer.echo(f"Updated {build_index(repo_root())}")


@kb_app.command("new")
def kb_new(kind: str, title: str) -> None:
    typer.echo(f"Created {create(repo_root(), kind, title)}")


@lease_app.command("status")
def lease_status(agent: str = typer.Option(..., "--agent")) -> None:
    api_key = get_api_key(agent, repo_root())
    if not api_key:
        raise typer.BadParameter(f"no key configured for {agent}")
    current = HinterglassClient(api_key=api_key).observe().get("notebook", {}).get("_lease")
    if isinstance(current, str):
        current = json.loads(current)
    typer.echo(json.dumps(current or {"held": False}, sort_keys=True))


@lease_app.command("acquire")
def lease_acquire(agent: str = typer.Option(..., "--agent")) -> None:
    api_key = get_api_key(agent, repo_root())
    if not api_key:
        raise typer.BadParameter(f"no key configured for {agent}")
    result = acquire(HinterglassClient(api_key=api_key), agent)
    if result is None:
        raise typer.BadParameter("identity lease is already held")
    typer.echo(f"Lease acquired until {result.expires_utc.isoformat()}.")


@lease_app.command("release")
def lease_release(agent: str = typer.Option(..., "--agent")) -> None:
    api_key = get_api_key(agent, repo_root())
    if not api_key:
        raise typer.BadParameter(f"no key configured for {agent}")
    client = HinterglassClient(api_key=api_key)
    current = client.observe().get("notebook", {}).get("_lease")
    if isinstance(current, str):
        current = json.loads(current)
    if not current:
        typer.echo("No lease held.")
        return
    lease_value = Lease(
        current["holder"],
        current["run_id"],
        datetime.fromisoformat(current["expires_utc"]),
    )
    if not release(client, lease_value):
        raise typer.BadParameter("lease changed before it could be released")
    typer.echo("Lease released.")


@observatory_app.command("collect")
@tolerate_outage
def observatory_collect() -> None:
    paths = Observatory(HinterglassClient(), repo_root()).collect_all()
    typer.echo(f"Collected {len(paths)} public archive file(s).")


@app.command()
def prove(
    claim_id: str | None = typer.Argument(None), changed: bool = typer.Option(False, "--changed")
) -> None:
    """Re-run a P2+ claim analysis, or all such claims with --changed."""
    if changed:
        checked = prove_all(repo_root())
        typer.echo(f"Verified {len(checked)} reproducible claim(s).")
    elif claim_id:
        prove_claim(repo_root(), claim_id)
        typer.echo(f"Claim {claim_id} reproduced.")
    else:
        raise typer.BadParameter("provide a claim ID or --changed")


@app.command()
def digest(propose: bool = typer.Option(False, "--propose")) -> None:
    """Create a daily, evidence-linked journal draft without inventing results."""
    if not propose:
        raise typer.BadParameter("use --propose to write a digest draft")
    today = datetime.now(UTC).date().isoformat()
    title = f"Daily digest {today}"
    path = create(repo_root(), "journal", title)
    typer.echo(f"Drafted {path}; add only results linked to archived evidence.")


@app.command()
def guide(refresh: bool = typer.Option(False, "--refresh")) -> None:
    """Download the live guide only when an operator explicitly requests it."""
    if not refresh:
        raise typer.BadParameter("use --refresh to download the current guide")
    response = httpx.get("https://hinterglass.com/agent-guide.md", timeout=18)
    response.raise_for_status()
    destination = repo_root() / "docs/vendor/agent-guide.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(response.text, encoding="utf-8")
    typer.echo(f"Saved vendor guide to {destination}.")


KEY_NAMES = {"ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GCP_SERVICE_ACCOUNT_KEY"}


@key_app.command("store")
def key_store(
    name: str = typer.Argument(...),
    from_file: Path | None = typer.Option(
        None,
        "--from-file",
        help="Read the value from this file instead of prompting (a service account JSON key)",
    ),
) -> None:
    """Store an allowed key in the OS keyring: a model key by prompt, or the GCP service account key from its JSON file."""
    if name not in KEY_NAMES:
        raise typer.BadParameter(f"supported names are {', '.join(sorted(KEY_NAMES))}")
    if from_file is not None:
        value = from_file.read_text(encoding="utf-8").strip()
        if name == "GCP_SERVICE_ACCOUNT_KEY":
            data = json.loads(value)
            if data.get("type") != "service_account" or not data.get("client_email"):
                raise typer.BadParameter("that file is not a service account key")
            value = json.dumps(data, separators=(",", ":"))
    else:
        value = getpass.getpass(f"Enter {name}: ")
    store_secret(name, value)
    typer.echo(f"Stored {name} securely ({len(value)} characters).")


from hglab.cli_personas import register_persona_commands

register_persona_commands(app)
