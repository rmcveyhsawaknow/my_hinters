"""``hglab local``: the local agents framework from the command line (and, through it, from MCP)."""

from __future__ import annotations

import json
import threading
import webbrowser
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

from hglab.local.memory import (
    Graph,
    ingest_personas,
    ingest_public_events,
    ingest_record,
    ingest_status,
)
from hglab.local.supervisor import JOBS, STATUS_FILE, Supervisor, due_jobs, load_local_config
from hglab.persona import load_personas, load_teams

local_app = typer.Typer(
    help="The local agents framework: supervisor, shared memory, A2A cards, MCP and a status page."
)
memory_app = typer.Typer(
    help="The shared memory graph on SQLite: ingest, query, snapshot, restore."
)
local_app.add_typer(memory_app, name="memory")
tasks_app = typer.Typer(
    help="A2A tasks: messages a persona reads at its next wake.", no_args_is_help=True
)
local_app.add_typer(tasks_app, name="tasks")


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


@local_app.command("up")
def local_up(
    minutes: int | None = typer.Option(
        None, "--minutes", help="Stop the supervisor after this many minutes"
    ),
    stack: bool = typer.Option(
        True,
        "--stack/--no-stack",
        help="Bring the NemoClaw side up first (Docker, gateway, Ollama, sandbox)",
    ),
    ui: bool = typer.Option(True, "--ui/--no-ui"),
    a2a: bool = typer.Option(True, "--a2a/--no-a2a"),
    auth: str | None = typer.Option(
        None,
        "--auth",
        help="GCP auth for backups this run: service_account (the key in the keyring, default) or gcloud (the signed-in session)",
    ),
) -> None:
    """Bring the whole local environment up in one process: the NemoClaw stack, the status page, the A2A endpoint and the supervisor loop. This is what runs after a reboot."""
    _set_auth(auth)
    root = _root()
    config = load_local_config(root)
    personas, teams = load_personas(root), load_teams(root)
    if stack and config.get("nemoclaw"):
        from hglab.local.stack import stack_up

        result = stack_up(config, say=lambda line: typer.echo(f"stack: {line}"))
        typer.echo(
            f"stack: {'ready' if result.get('ok') else 'not ready'}; {json.dumps({k: v for k, v in result.items() if k in ('docker', 'gateway', 'ollama', 'phase', 'openclaw', 'model', 'provider')})}"
        )
    if ui:
        from hglab.local.ui import serve as serve_ui

        port = int(config.get("ui_port", 8766))
        threading.Thread(
            target=serve_ui(root, personas, teams, port).serve_forever, daemon=True
        ).start()
        typer.echo(f"status page at http://127.0.0.1:{port}/")
    if a2a:
        from hglab.local.a2a import serve as serve_a2a

        port = int(config.get("a2a_port", 8765))
        threading.Thread(
            target=serve_a2a(root, personas, teams, port, None).serve_forever, daemon=True
        ).start()
        typer.echo(f"A2A at http://127.0.0.1:{port}/agents")
    Supervisor(root).loop(personas, minutes)


@local_app.command("stack")
def local_stack(
    up: bool = typer.Option(False, "--up", help="Start what is down instead of only reporting"),
) -> None:
    """The NemoClaw side: Docker, the OpenShell gateway, Ollama and the sandbox (through WSL on Windows)."""
    from hglab.local.stack import stack_status, stack_up

    config = load_local_config(_root())
    result = stack_up(config, say=typer.echo) if up else stack_status(config)
    typer.echo(json.dumps(result, ensure_ascii=False, indent=2))


service_app = typer.Typer(
    help="Start the environment at logon: a Scheduled Task on Windows, a systemd user unit on Linux.",
    no_args_is_help=True,
)
local_app.add_typer(service_app, name="service")


@service_app.command("install")
def service_install(
    auth: str | None = typer.Option(
        None, "--auth", help="Bake `--auth gcloud` (or service_account) into the logon start"
    ),
) -> None:
    """Register the logon start (runs `hglab local up` from this checkout, a minute after logon)."""
    from hglab.local.service import install

    _set_auth(auth)
    typer.echo(json.dumps(install(_root(), auth=auth), ensure_ascii=False, indent=2))


@service_app.command("remove")
def service_remove() -> None:
    """Unregister the logon start."""
    from hglab.local.service import remove

    typer.echo(json.dumps(remove(_root()), ensure_ascii=False, indent=2))


@service_app.command("status")
def service_status() -> None:
    """Whether the logon start is registered and what it last did."""
    from hglab.local.service import status

    typer.echo(json.dumps(status(_root()), ensure_ascii=False, indent=2))


@local_app.command("goals")
def local_goals(
    agent: str | None = typer.Option(None, "--agent", help="Persona slug or in-world name"),
    adapt_now: bool = typer.Option(
        False,
        "--adapt",
        help="Recompute assignments from the evidence and record them in the graph",
    ),
    brief_now: bool = typer.Option(
        False,
        "--brief",
        help="With --adapt: leave each changed assignment as an operator message for the next wake",
    ),
) -> None:
    """What each persona is doing now and the goal it pursues, with the evidence; --adapt recomputes, --brief delivers."""
    from hglab.local.goals import adapt, brief, current

    root = _root()
    personas, teams = load_personas(root), load_teams(root)
    graph = _graph(root)
    try:
        if adapt_now:
            plan = adapt(root, graph, personas, teams)
            briefed = brief(root, graph, plan) if brief_now else []
            view = {
                slug: {
                    "name": d["name"],
                    "team": d["team"],
                    "assignment": d["assignment"],
                    "activity": d["activity"],
                }
                for slug, d in plan["agents"].items()
            }
            out: dict[str, Any] = {
                "utc": plan["utc"],
                "agents": view,
                "teams": plan["teams"],
                "briefed": briefed,
            }
        else:
            out = {"agents": current(root, personas, graph)}
    finally:
        graph.close()
    if agent:
        name = _persona_name(root, agent)
        out["agents"] = {s: v for s, v in out["agents"].items() if personas[s].name == name}
    typer.echo(json.dumps(out, ensure_ascii=False, indent=2, default=str))


@local_app.command("cards")
def local_cards(
    write: bool = typer.Option(False, "--write", help="Write runs/local/cards/<slug>.json"),
    agent: str | None = typer.Option(None, "--agent"),
) -> None:
    """Capability cards: the A2A card of each persona with roles, skills, tools, datasets, performance by model and backups."""
    from hglab.local.cards import all_cards, write_cards

    root = _root()
    config = load_local_config(root)
    personas, teams = load_personas(root), load_teams(root)
    if write:
        paths = write_cards(root, personas, teams, config)
        typer.echo(
            f"{len(paths)} card(s) written under {paths[0].parent}" if paths else "no personas"
        )
        return
    cards = all_cards(root, personas, teams, config)
    if agent:
        name = _persona_name(root, agent)
        cards = {s: c for s, c in cards.items() if c["name"] == name}
    typer.echo(json.dumps(list(cards.values()), ensure_ascii=False, indent=2))


backup_app = typer.Typer(
    help="Host backups: configuration, supervisor state and a graph snapshot, pushed to a local directory or gs://bucket/prefix.",
    no_args_is_help=True,
)
local_app.add_typer(backup_app, name="backup")


def _set_auth(auth: str | None) -> None:
    import os

    from hglab.local.backup import AUTH_ENV, AUTH_MODES

    if auth is None:
        return
    if auth not in AUTH_MODES:
        raise typer.BadParameter(f"--auth must be one of {', '.join(AUTH_MODES)}")
    os.environ[AUTH_ENV] = auth


@backup_app.command("push")
def backup_push(
    target: str | None = typer.Option(
        None,
        "--target",
        help="local:<dir> or gs://bucket/prefix (default from config ecosystem.backup_target)",
    ),
    auth: str | None = typer.Option(None, "--auth", help="service_account (default) or gcloud"),
) -> None:
    """Make a backup and copy it to the target."""
    from hglab.local.backup import push

    _set_auth(auth)
    root = _root()
    typer.echo(
        json.dumps(push(root, load_local_config(root), target), ensure_ascii=False, indent=2)
    )


@backup_app.command("list")
def backup_list(
    target: str | None = typer.Option(None, "--target"),
    auth: str | None = typer.Option(None, "--auth", help="service_account (default) or gcloud"),
) -> None:
    """The backups at the target, newest first."""
    from hglab.local.backup import list_backups

    _set_auth(auth)
    root = _root()
    typer.echo(
        json.dumps(
            list_backups(root, load_local_config(root), target), ensure_ascii=False, indent=2
        )
    )


ARCHIVE_ARGUMENT = typer.Argument(..., exists=True, dir_okay=False)


@backup_app.command("restore")
def backup_restore(
    archive: Path = ARCHIVE_ARGUMENT,
    force: bool = typer.Option(False, "--force", help="Overwrite state that already exists"),
) -> None:
    """Unpack a backup into this checkout (state files and the graph), skipping what already exists unless forced."""
    from hglab.local.backup import restore

    typer.echo(json.dumps(restore(_root(), archive, force), ensure_ascii=False, indent=2))


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
            status_path = root / STATUS_FILE
            if status_path.is_file():
                try:
                    status = json.loads(status_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    status = {}
                jobs = ingest_status(graph, status, {slug: p.name for slug, p in personas.items()})
                typer.echo(f"local jobs: {jobs} run(s) added")
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


@memory_app.command("performance")
def memory_performance(
    agent: str | None = typer.Option(None, "--agent", help="Persona slug or in-world name"),
) -> None:
    """Wakes, actions, failures and tokens per persona and model, plus local job timings."""
    root = _root()
    name = _persona_name(root, agent) if agent else None
    graph = _graph(root)
    try:
        typer.echo(json.dumps(graph.performance(name), ensure_ascii=False, indent=2))
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


def _persona_name(root: Path, agent: str) -> str:
    personas = load_personas(root)
    if agent in personas:
        return personas[agent].name
    for p in personas.values():
        if p.name.casefold() == agent.casefold():
            return p.name
    raise typer.BadParameter(f"no persona {agent}")


@tasks_app.command("send")
def tasks_send(
    agent: str = typer.Option(..., "--agent", help="Persona slug or in-world name"),
    text: str = typer.Option(..., "--text"),
    sender: str = typer.Option("operator", "--sender"),
) -> None:
    """Leave a message a persona reads at its next wake (a submitted A2A task)."""
    from hglab.local.a2a import TaskStore

    root = _root()
    name = _persona_name(root, agent)
    graph = _graph(root)
    try:
        task = TaskStore(graph).create(name, sender, text)
    finally:
        graph.close()
    typer.echo(json.dumps({"id": task["id"], "agent": name, "state": task["status"]["state"]}))


@tasks_app.command("list")
def tasks_list(
    agent: str | None = typer.Option(None, "--agent"),
    everything: bool = typer.Option(False, "--all", help="Completed and canceled tasks too"),
) -> None:
    """The tasks on the board, open ones by default."""
    root = _root()
    name = _persona_name(root, agent) if agent else None
    graph = _graph(root)
    try:
        rows = []
        for node in graph.nodes("task"):
            if name and node.get("agent") != name:
                continue
            if not everything and node.get("state") not in {"submitted", "working"}:
                continue
            rows.append(
                {
                    "id": node["id"][5:],
                    "agent": node.get("agent"),
                    "sender": node.get("sender"),
                    "state": node.get("state"),
                    "text": str(node.get("text", ""))[:120],
                    "updated_utc": node.get("updated_utc"),
                }
            )
    finally:
        graph.close()
    typer.echo(json.dumps(rows, ensure_ascii=False, indent=2))
