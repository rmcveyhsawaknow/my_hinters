"""``hglab local``: the local agents framework from the command line (and, through it, from MCP)."""

from __future__ import annotations

import json
import threading
import webbrowser
from datetime import UTC, datetime
from pathlib import Path

import typer

from hglab.local.memory import Graph, ingest_personas, ingest_public_events, ingest_record
from hglab.local.supervisor import JOBS, STATUS_FILE, Supervisor, due_jobs, load_local_config
from hglab.persona import load_personas, load_teams

local_app = typer.Typer(
    help="The local agents framework: supervisor, shared memory, A2A cards, MCP and a status page."
)
memory_app = typer.Typer(
    help="The shared memory graph on SQLite: ingest, query, snapshot, restore."
)
local_app.add_typer(memory_app, name="memory")


def _root() -> Path:
    from hglab.cli import repo_root

    return repo_root()


def _graph(root: Path) -> Graph:
    return Graph(root / "runs/local/memory.sqlite")


@local_app.command("status")
def local_status(as_json: bool = typer.Option(False, "--json")) -> None:
    """Which agents run here, what is due this minute, and each agent's last local job."""
    root = _root()
    config = load_local_config(root)
    personas = load_personas(root)
    path = root / STATUS_FILE
    status = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"agents": {}}
    now = datetime.now(UTC).replace(second=0, microsecond=0)
    rows = []
    for entry in config.get("agents", []):
        slug = str(entry.get("slug"))
        persona = personas.get(slug)
        if persona is None:
            continue
        last = (status.get("agents", {}).get(slug) or {}).get("last") or {}
        rows.append(
            {
                "slug": slug,
                "name": persona.name,
                "enabled": bool(entry.get("enabled", True)),
                "dry_run": bool(entry.get("dry_run", config.get("dry_run", True))),
                "due_now": due_jobs(persona, now, entry),
                "last": last,
            }
        )
    if as_json:
        typer.echo(
            json.dumps(
                {
                    "running": status.get("running", False),
                    "updated_utc": status.get("updated_utc"),
                    "agents": rows,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    typer.echo(
        f"supervisor {'running' if status.get('running') else 'stopped'} · dry_run default {config.get('dry_run', True)} · {len(rows)} agent(s) configured"
    )
    for row in rows:
        last = row["last"]
        tail = (
            f"last {last.get('job')} exit {last.get('exit')} at {str(last.get('finished_utc', ''))[:19]}: {str(last.get('summary', ''))[:80]}"
            if last
            else "no local job yet"
        )
        typer.echo(
            f"  {row['name']:12} {'on ' if row['enabled'] else 'off'} {'dry' if row['dry_run'] else 'LIVE'} · due now: {', '.join(row['due_now']) or '-'} · {tail}"
        )


@local_app.command("once")
def local_once(
    agent: str = typer.Option(..., "--agent"),
    job: str = typer.Option("tick", "--job", help="tick, shift, keepalive, crier or land"),
    live: bool = typer.Option(False, "--live", help="Act in the world (default: dry run)"),
) -> None:
    """Run one job for one agent now, as the supervisor would."""
    if job not in JOBS:
        raise typer.BadParameter(f"job must be one of {', '.join(JOBS)}")
    record = Supervisor(_root()).run_once(agent, job, not live)
    typer.echo(json.dumps(record, ensure_ascii=False, indent=2))
    raise typer.Exit(code=0 if record.get("exit") == 0 else 1)


@local_app.command("run")
def local_run(
    minutes: int | None = typer.Option(
        None, "--minutes", help="Stop after this many minutes (default: run until interrupted)"
    ),
) -> None:
    """Run the supervisor: every minute, every due job for every enabled agent."""
    root = _root()
    personas = load_personas(root)
    Supervisor(root).loop(personas, minutes)


@local_app.command("ui")
def local_ui(
    port: int | None = typer.Option(None, "--port"),
    open_browser: bool = typer.Option(False, "--open"),
) -> None:
    """Serve the status page on 127.0.0.1 (default port from config/local.yaml, 8766)."""
    from hglab.local.ui import serve

    root = _root()
    config = load_local_config(root)
    port = port or int(config.get("ui_port", 8766))
    server = serve(root, load_personas(root), load_teams(root), port)
    url = f"http://127.0.0.1:{port}/"
    typer.echo(f"status page at {url} (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    server.serve_forever()


@local_app.command("a2a")
def local_a2a(
    port: int | None = typer.Option(None, "--port"),
    token: str | None = typer.Option(
        None, "--token", help="Require this X-Local-Token header on RPC calls"
    ),
) -> None:
    """Serve one A2A agent card per persona and take messages for them (127.0.0.1, default port 8765)."""
    from hglab.local.a2a import serve

    root = _root()
    config = load_local_config(root)
    port = port or int(config.get("a2a_port", 8765))
    server = serve(root, load_personas(root), load_teams(root), port, token)
    typer.echo(f"A2A at http://127.0.0.1:{port}/agents (Ctrl+C to stop)")
    server.serve_forever()


@local_app.command("mcp")
def local_mcp() -> None:
    """Serve the management tools over MCP on stdio (for Claude Code: claude mcp add hinters -- hglab local mcp)."""
    from hglab.local.mcp_server import build_server

    build_server(_root()).run()


@memory_app.command("ingest")
def memory_ingest(
    records: bool = typer.Option(True, "--records/--no-records"),
    events: bool = typer.Option(True, "--events/--no-events"),
    days: int = typer.Option(3, "--days"),
) -> None:
    """Feed the graph from the personas, the pulled run records and the public log (keyless)."""
    root = _root()
    personas, teams = load_personas(root), load_teams(root)
    graph = _graph(root)
    try:
        ingest_personas(graph, personas, teams)
        added = 0
        if records:
            seen = 0
            for path in sorted((root / "reports/agents").rglob("*.json")) + sorted(
                (root / "runs").rglob("*.json")
            ):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    continue
                if isinstance(data, dict) and "actions" in data and not data.get("dry_run"):
                    added += ingest_record(graph, data)
                    seen += 1
            typer.echo(f"records: {seen} read, {added} edge(s) added")
        if events:
            from hglab.client import HinterglassClient

            client = HinterglassClient(api_key="")
            collected: list[dict] = []
            before = None
            cutoff_tick = None
            for _ in range(days * 30):
                page = client.public_events(before=before) if before else client.public_events()
                batch = page.get("events", []) if isinstance(page, dict) else []
                if not batch:
                    break
                collected.extend(batch)
                before = page.get("next_before")
                newest = int(collected[0].get("tick", 0) or 0)
                cutoff_tick = newest - days * 8640
                if not before or int(batch[-1].get("tick", 0) or 0) < cutoff_tick:
                    break
            n = ingest_public_events(
                graph,
                [
                    e
                    for e in collected
                    if cutoff_tick is None or int(e.get("tick", 0) or 0) >= cutoff_tick
                ],
            )
            typer.echo(f"public events: {len(collected)} read, {n} edge(s) added")
        typer.echo(json.dumps(graph.counts(), ensure_ascii=False))
    finally:
        graph.close()


@memory_app.command("query")
def memory_query(sql: str = typer.Argument(...), limit: int = typer.Option(50, "--limit")) -> None:
    """A read-only SELECT over nodes(id, kind, props, tick), edges(src, dst, kind, tick, props), snapshots."""
    graph = _graph(_root())
    try:
        typer.echo(json.dumps(graph.query(sql, limit), ensure_ascii=False, indent=2))
    finally:
        graph.close()


@memory_app.command("contacts")
def memory_contacts(
    agent: str = typer.Argument(...), since_tick: int = typer.Option(0, "--since-tick")
) -> None:
    """Who an in-world name has reached and been reached by."""
    graph = _graph(_root())
    try:
        typer.echo(json.dumps(graph.contacts(agent, since_tick), ensure_ascii=False, indent=2))
    finally:
        graph.close()


@memory_app.command("snapshot")
def memory_snapshot(name: str | None = typer.Argument(None)) -> None:
    """Copy the graph to runs/local/memory.snapshots/<name>.sqlite (dated when no name is given)."""
    graph = _graph(_root())
    try:
        path = graph.snapshot(name)
        typer.echo(f"snapshot written: {path}")
        for row in graph.snapshots()[:10]:
            typer.echo(
                f"  {row['name']}: {row['utc'][:19]} tick {row['tick']} nodes {row['nodes']} edges {row['edges']}"
            )
    finally:
        graph.close()


@memory_app.command("restore")
def memory_restore(name: str = typer.Argument(...)) -> None:
    """Replace the graph with a snapshot."""
    graph = _graph(_root())
    try:
        graph.restore(name)
        typer.echo(f"restored {name}: {json.dumps(graph.counts())}")
    finally:
        graph.close()


__all__ = ["local_app"]
