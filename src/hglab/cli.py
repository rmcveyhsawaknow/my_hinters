"""Command-line entry point."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import typer

from hglab.actions import redact_observe
from hglab.kb import build_index, create, validate

app = typer.Typer(help="Safe tools for the Hinterglass research collective.")
kb_app = typer.Typer(help="Curate the local knowledge base.")
lease_app = typer.Typer(help="Manage identity leases.")
app.add_typer(kb_app, name="kb")
app.add_typer(lease_app, name="lease")


def repo_root() -> Path:
    return Path.cwd()


@app.command()
def doctor() -> None:
    """Check local setup without contacting the world or exposing key values."""
    root = repo_root()
    missing = [path for path in ("config/agents.yaml", "config/models.yaml", ".mcp.json") if not (root / path).exists()]
    typer.echo(f"Python: {sys.version_info.major}.{sys.version_info.minor}")
    typer.echo(f"Hinterglass key configured: {'yes' if any(k.startswith('HG_KEY_') for k in os.environ) else 'no'}")
    typer.echo(f"Missing local files: {', '.join(missing) if missing else 'none'}")
    typer.echo("Connectivity not checked; no live request was made.")


@app.command()
def observe(agent: str = typer.Option(..., "--agent"), as_json: bool = typer.Option(False, "--json")) -> None:
    """Safely report that live observation requires explicit future setup."""
    del agent
    if as_json:
        typer.echo(json.dumps(redact_observe({"status": "offline"}), sort_keys=True))
    else:
        typer.echo("Offline scaffold: no world request was made.")


@app.command()
def tick(
    agent: str = typer.Option(..., "--agent"),
    role: str = typer.Option(..., "--role"),
    dry_run: bool = typer.Option(False, "--dry-run"),
) -> None:
    """Plan a local dry run; live ticks are unavailable until core safety checks are configured."""
    del agent, role
    if not dry_run:
        raise typer.BadParameter("live ticks are not enabled in this scaffold; use --dry-run")
    typer.echo("Dry run only: no network request or world action was made.")


@app.command()
def register(
    name: str = typer.Option(..., "--name"),
    bio: str = typer.Option("Hinterglass Research Collective; we publish analyses of public events.", "--bio"),
    to_gh_secret: bool = typer.Option(False, "--to-gh-secret"),
) -> None:
    """Registration is intentionally not automated in this offline scaffold."""
    del name, bio, to_gh_secret
    raise typer.BadParameter("registration is a live action; follow docs/setup-local.md manually")


@app.command()
def sync(check: bool = typer.Option(False, "--check")) -> None:
    """Generate Claude assets from canonical roles and skills (once present)."""
    root = repo_root()
    generated = []
    for source in sorted((root / "roles").glob("*.md")):
        if source.name == "README.md":
            continue
        target = root / ".claude/agents" / source.name
        body = source.read_text(encoding="utf-8")
        if body.startswith("---"):
            body = body.split("---", 2)[2].lstrip()
        generated_text = f"---\nname: {source.stem}\ndescription: Canonical role charter for {source.stem}.\n---\n\n{body}"
        generated.append((target, generated_text))
    for source in sorted((root / "skills").glob("*/SKILL.md")):
        target = root / ".claude/skills" / source.parent.name / "SKILL.md"
        generated.append((target, source.read_text(encoding="utf-8")))
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


@kb_app.command("index")
def kb_index() -> None:
    typer.echo(f"Updated {build_index(repo_root())}")


@kb_app.command("new")
def kb_new(kind: str, title: str) -> None:
    typer.echo(f"Created {create(repo_root(), kind, title)}")


@lease_app.command("acquire")
def lease_acquire(agent: str = typer.Option(..., "--agent")) -> None:
    del agent
    raise typer.BadParameter("leases require a verified live identity; no request was made")


@lease_app.command("release")
def lease_release(agent: str = typer.Option(..., "--agent")) -> None:
    del agent
    raise typer.BadParameter("leases require a verified live identity; no request was made")


@lease_app.command("status")
def lease_status(agent: str = typer.Option(..., "--agent")) -> None:
    del agent
    raise typer.BadParameter("leases require a verified live identity; no request was made")
