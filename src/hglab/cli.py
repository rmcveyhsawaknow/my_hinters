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
from hglab.challenge import answer_with_retries, response_schema
from hglab.client import HinterglassClient, HinterglassError
from hglab.config import validate_config
from hglab.kb import FRONT_MATTER, build_index, create, validate
from hglab.lease import Lease, acquire, release
from hglab.limits import action_limits
from hglab.llm import structured_call
from hglab.loop import build_prompt, run_wake
from hglab.observatory import Observatory
from hglab.prove import prove_all, prove_claim
from hglab.secrets import get_api_key, get_secret, set_github_secret, store_api_key, store_secret

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
    result = structured_call(
        "challenge", prompt, response_schema(prompt),
        root=root, output_tokens=output_tokens,
    )
    if usage is not None:
        usage.update(
            calls=usage["calls"] + 1,
            input_tokens=usage["input_tokens"] + result.input_tokens,
            output_tokens=usage["output_tokens"] + result.output_tokens,
        )
    return json.dumps(result.value)


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
            if error.code in {"challenge_failed", "challenge_expired"}:
                return {"ok": False}
            raise

    result = answer_with_retries(
        fetch, lambda prompt: challenge_responder(prompt, usage), submit, retries=2
    )
    if not result.get("ok"):
        raise ValueError("daily verification did not succeed")
    return True


@app.command()
def doctor() -> None:
    """Check local setup without contacting the world or exposing key values."""
    root = repo_root()
    missing = [path for path in ("config/agents.yaml", "config/models.yaml", ".mcp.json") if not (root / path).exists()]
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
        f"OpenAI {'yes' if get_secret('OPENAI_API_KEY', root) else 'no'}"
    )
    typer.echo(f"Missing local files: {', '.join(missing) if missing else 'none'}")
    typer.echo("Connectivity not checked; no live request was made.")


@app.command()
def observe(agent: str = typer.Option(..., "--agent"), as_json: bool = typer.Option(False, "--json")) -> None:
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
def tick(
    agent: str = typer.Option(..., "--agent"),
    role: str = typer.Option(..., "--role"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Run a leased, validated wake; use --dry-run to plan without actions."""
    api_key = get_api_key(agent, repo_root())
    if not api_key:
        raise typer.BadParameter(f"no key configured for {agent}")
    root = repo_root()
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
    schema = {
        "type": "object",
        "required": ["summary", "actions"],
        "properties": {
            "summary": {"type": "string"},
            "actions": {
                "type": "array", "minItems": 1, "maxItems": 4,
                "items": {"$ref": "#/$defs/action"},
            },
            "remember": {"type": "array"},
            "journal_note": {"type": "string"},
            "kb_proposals": {"type": "array"},
        },
        "$defs": {"action": json.loads((root / "schemas/action.json").read_text())},
        "additionalProperties": False,
    }
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
            schema["$defs"]["action"],
        )
        budget = yaml.safe_load((root / "config/budget.yaml").read_text(encoding="utf-8"))["tick"]
        if usage["calls"] >= budget["max_llm_calls"]:
            raise ValueError("tick LLM call budget exhausted")
        output_tokens = min(
            1600, budget["max_output_tokens"] - usage["output_tokens"]
        )
        if output_tokens < 1:
            raise ValueError("tick output-token budget exhausted")
        result = structured_call(
            role_config["model_route"], prompt, schema, root=root,
            output_tokens=output_tokens,
            author_runtime=os.environ.get("HGLAB_RUNTIME", "human"),
        )
        usage.update(
            calls=usage["calls"] + 1,
            input_tokens=usage["input_tokens"] + result.input_tokens,
            output_tokens=usage["output_tokens"] + result.output_tokens,
        )
        return result.value

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
    bio: str = typer.Option("Hinterglass Research Collective; we publish analyses of public events.", "--bio"),
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
                "challenge", prompt, response_schema(prompt),
                root=repo_root(), output_tokens=500,
            ).value
        )

    def submit(challenge_id: str, answer: dict) -> dict:
        try:
            return client.request(
                "POST", "/api/v1/register/complete",
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
    for pair in params or []:
        if "=" not in pair:
            raise typer.BadParameter(f"expected key=value, got {pair!r}")
        key, value = pair.split("=", 1)
        values[key] = yaml.safe_load(value)
    client = HinterglassClient(api_key=api_key)
    lease = acquire(client, agent)
    if lease is None:
        raise typer.BadParameter(f"identity {agent} already has an active lease")
    try:
        observe = client.observe()
        answer_daily_challenge(client, observe)
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
    if errors:
        raise typer.BadParameter("\n".join(errors))
    stale = []
    for target, text in generated:
        if check:
            if not target.exists() or target.read_text(encoding="utf-8") != text:
                stale.append(str(target.relative_to(root)))
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
    if stale:
        raise typer.BadParameter(f"generated assets stale: {', '.join(stale)}")
    typer.echo("Claude assets are current." if check else f"Generated {len(generated)} Claude assets.")


@kb_app.command("validate")
def kb_validate() -> None:
    errors = validate(repo_root())
    if errors:
        raise typer.BadParameter("\n".join(errors))
    typer.echo("Knowledge base valid.")


@config_app.command("validate")
def config_validate() -> None:
    errors = validate_config(repo_root())
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
def observatory_collect() -> None:
    paths = Observatory(HinterglassClient(), repo_root()).collect_all()
    typer.echo(f"Collected {len(paths)} public archive file(s).")


@app.command()
def prove(claim_id: str | None = typer.Argument(None), changed: bool = typer.Option(False, "--changed")) -> None:
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


@key_app.command("store")
def key_store(name: str = typer.Argument(...)) -> None:
    """Prompt for an allowed model key and store it in the OS keyring."""
    if name not in {"ANTHROPIC_API_KEY", "OPENAI_API_KEY"}:
        raise typer.BadParameter("supported names are ANTHROPIC_API_KEY and OPENAI_API_KEY")
    value = getpass.getpass(f"Enter {name}: ")
    store_secret(name, value)
    typer.echo(f"Stored {name} securely.")
