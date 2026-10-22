"""The status page: who is doing what, sorted by last activity, with each persona's current goal.

Standard-library HTTP on 127.0.0.1. One HTML page read fresh on every request from ``runs/local/status.json``,
the newest wake records, the memory graph (assignments, outcomes, counts), the capability cards and the local
configuration; ``/status.json`` returns the supervisor's status file and ``/goals.json`` the goals view.
"""

from __future__ import annotations

import html
import json
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from string import Template
from typing import Any

from hglab.local.cards import all_cards
from hglab.local.goals import approach_outcomes, current, works_and_avoid
from hglab.local.memory import Graph
from hglab.local.supervisor import STATUS_FILE, load_local_config

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="refresh" content="120">
<title>Collective status</title>
<style>
:root{--bg:#f6f5f1;--fg:#1f2420;--muted:#66706a;--card:#ffffff;--line:#dcdad2;--ok:#1b7f4b;--bad:#b3261e;--warn:#8a5a00;--live:#2f6f5e;--soft:#e8efea}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#151916;--fg:#e8e9e4;--muted:#a3aaa4;--card:#1d221f;--line:#2d332f;--ok:#7fc3ac;--bad:#f28b82;--warn:#e0b35a;--live:#7fc3ac;--soft:#203b32}}
body{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
h1{font-size:22px;margin:0 0 2px}h2{font-size:17px;margin:28px 0 8px}
.strip{display:flex;flex-wrap:wrap;gap:8px 18px;color:var(--muted);font-size:14px;margin-bottom:12px}
.strip b{color:var(--fg)}
.pill{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:600;letter-spacing:.02em}
.pill.live{background:var(--live);color:#fff}.pill.dry{background:var(--soft);color:var(--fg)}.pill.actions{background:var(--line);color:var(--fg)}
.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}.muted{color:var(--muted)}
.scroll{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:14px}
th{text-align:left;color:var(--muted);font-size:12px;letter-spacing:.04em;text-transform:uppercase;padding:6px 8px;border-bottom:1px solid var(--line)}
td{padding:8px;border-bottom:1px solid var(--line);vertical-align:top;min-width:0}
td.who{white-space:nowrap}td.now{min-width:260px}td.goal{min-width:260px}
.small{font-size:12.5px;color:var(--muted)}
.bar{height:6px;background:var(--line);border-radius:3px;overflow:hidden;margin-top:4px;max-width:180px}
.bar i{display:block;height:100%;background:var(--live)}
.teams{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:12px}
.team{background:var(--card);border:1px solid var(--line);border-radius:8px;padding:12px;min-width:0}
.team h3{margin:0 0 4px;font-size:15px}.team ul{margin:6px 0 0;padding-left:18px}.team li{margin-bottom:4px}
details{margin-top:10px}summary{cursor:pointer;color:var(--muted)}
pre{font-size:12.5px;overflow-x:auto;background:var(--card);border:1px solid var(--line);border-radius:6px;padding:10px}
</style></head><body>
<h1>Collective status</h1>
<div class="strip"><span>host <b>$host</b></span><span>supervisor <b class="$running_cls">$running</b></span><span>mode <b>$mode</b></span><span>last backup <b>$backup</b></span><span>sandbox <b>$stack</b></span><span>updated $updated</span><span><a href="/status.json">status.json</a> · <a href="/goals.json">goals.json</a></span></div>
<h2>Agents, most recent activity first</h2>
<div class="scroll"><table>
<tr><th>Persona</th><th>Last activity</th><th>Doing now</th><th>Current goal</th><th>Works / avoid</th><th>Backups</th></tr>
$rows
</table></div>
<h2>Teams</h2><div class="teams">$teams</div>
<h2>Shared memory</h2><div class="small">$memory</div>
<details><summary>Configuration</summary><pre>$config</pre></details>
</body></html>"""


def _age(stamp: str | None, now: datetime) -> str:
    if not stamp:
        return "never"
    try:
        then = datetime.fromisoformat(str(stamp))
    except ValueError:
        return str(stamp)[:19]
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    seconds = max(0, int((now - then).total_seconds()))
    if seconds < 90:
        return f"{seconds}s ago"
    if seconds < 5400:
        return f"{seconds // 60} min ago"
    if seconds < 172800:
        return f"{seconds // 3600} h ago"
    return f"{seconds // 86400} d ago"


def _latest_stamp(*stamps: str | None) -> str | None:
    return max((s for s in stamps if s), default=None)


def render(root: Path, personas: dict[str, Any], teams: dict[str, Any]) -> str:
    now = datetime.now(UTC)
    status: dict[str, Any] = {}
    path = root / STATUS_FILE
    if path.is_file():
        try:
            status = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            status = {}
    config = load_local_config(root)
    enabled = {e.get("slug"): e for e in config.get("agents", []) if isinstance(e, dict)}
    graph_path = root / "runs/local/memory.sqlite"
    graph = Graph(graph_path) if graph_path.is_file() else None
    try:
        capability = all_cards(root, personas, teams, config)
        goals = current(root, personas, graph)
        outcomes = (
            {slug: approach_outcomes(graph, p.name) for slug, p in personas.items()}
            if graph
            else {}
        )
        counts = graph.counts() if graph else None
    finally:
        if graph is not None:
            graph.close()

    rows_data = []
    for slug, persona in personas.items():
        entry = enabled.get(slug)
        last = ((status.get("agents") or {}).get(slug) or {}).get("last") or {}
        act = goals[slug]["activity"]
        stamp = _latest_stamp(last.get("finished_utc"), act.get("utc"))
        rows_data.append((stamp or "", slug, persona, entry, last, act, goals[slug]["assignment"]))
    rows_data.sort(key=lambda r: r[0], reverse=True)

    rows = []
    for stamp, slug, persona, entry, last, act, assignment in rows_data:
        team = teams.get(persona.team)
        local = bool(entry and entry.get("enabled", True))
        dry = entry.get("dry_run", config.get("dry_run", True)) if entry else True
        pill = (
            '<span class="pill actions">actions</span>'
            if not local
            else (
                '<span class="pill dry">dry</span>'
                if dry
                else '<span class="pill live">LIVE</span>'
            )
        )
        exit_cls = "ok" if last.get("exit") == 0 else "bad" if last else "muted"
        last_line = (
            f"<span class={exit_cls}>{html.escape(str(last.get('job', '')))} exit {last.get('exit')}</span>"
            if last
            else "<span class=muted>no local job yet</span>"
        )
        doing = html.escape(act.get("summary") or "nothing recorded yet")
        details = " · ".join(
            filter(
                None,
                [
                    html.escape(str(act.get("approach") or "")),
                    html.escape(str(act.get("mood") or "")),
                    f"energy {act['energy']}" if act.get("energy") is not None else "",
                    f"pack {act['pack']}" if act.get("pack") is not None else "",
                    f"results {html.escape(str(act['ok']))}" if act.get("ok") else "",
                ],
            )
        )
        reason = html.escape(act.get("reason") or "")
        if assignment and assignment.get("label"):
            progress = assignment.get("progress")
            pct = (
                f"{int(float(progress) * 100)}%"
                if isinstance(progress, (int, float))
                else "not measured yet"
            )
            width = int(float(progress) * 100) if isinstance(progress, (int, float)) else 0
            goal = f'<div><b>{html.escape(str(assignment["label"]))}</b> <span class=small>target {html.escape(str(assignment.get("target")))} · {pct}</span><div class=bar><i style="width:{width}%"></i></div><div class=small>{html.escape(str(assignment.get("why") or ""))[:220]}</div></div>'
        else:
            goal = f"<div class=small>{html.escape(persona.intent[:160])}</div><div class=small>no assignment yet: run <code>hglab local goals --adapt</code></div>"
        works, avoid = works_and_avoid(outcomes.get(slug, []))
        wa = (
            f"<span class=ok>{html.escape(', '.join(works))}</span>"
            if works
            else "<span class=muted>not enough data</span>"
        ) + (f"<br><span class=bad>avoid {html.escape(', '.join(avoid))}</span>" if avoid else "")
        backups = ((capability.get(slug) or {}).get("x-collective") or {}).get("backups") or {}
        bk = f"{backups.get('snapshots', 0)} snapshot(s)<br><span class=small>last backup {html.escape(_age(backups.get('latest_backup_utc'), now))}</span>"
        rows.append(
            f"<tr><td class=who><b>{html.escape(persona.name)}</b> {pill}<br><span class=small>{html.escape(team.name if team else persona.team)} · {html.escape(slug)}</span></td>"
            f"<td><b>{html.escape(_age(stamp or None, now))}</b><br>{last_line}<br><span class=small>{html.escape(str(stamp)[:16].replace('T', ' '))}</span></td>"
            f"<td class=now>{doing}<br><span class=small>{details}</span>{'<br><span class=small>' + reason + '</span>' if reason else ''}</td>"
            f"<td class=goal>{goal}</td><td>{wa}</td><td>{bk}</td></tr>"
        )

    team_cards = []
    for tslug, team in sorted(teams.items(), key=lambda kv: kv[1].name):
        members = [slug for slug, p in personas.items() if p.team == tslug]
        items = []
        for slug in members:
            a = goals[slug]["assignment"] or {}
            act = goals[slug]["activity"]
            items.append(
                f"<li><b>{html.escape(personas[slug].name)}</b>: {html.escape(str(a.get('label') or 'no assignment yet'))} <span class=small>· now: {html.escape(act.get('summary') or 'nothing recorded')}</span></li>"
            )
        team_cards.append(
            f"<div class=team><h3>{html.escape(team.name)}</h3><div class=small>{html.escape(team.aim[:200])}</div><ul>{''.join(items)}</ul></div>"
        )

    memory = (
        f"nodes {html.escape(json.dumps(counts['nodes']))} · edges {html.escape(json.dumps(counts['edges']))} · latest tick {counts['latest_tick']}"
        if counts
        else "no memory graph yet: run <code>hglab local memory ingest</code>"
    )
    last_backup = status.get("last_backup") or {}
    stack = status.get("stack") or {}
    return Template(PAGE).substitute(
        host=html.escape(
            str((config.get("ecosystem") or {}).get("host_id") or status.get("host", ""))
        ),
        running="running" if status.get("running") else "stopped",
        running_cls="ok" if status.get("running") else "bad",
        mode="live" if not config.get("dry_run", True) else "dry",
        backup=html.escape(
            f"{_age(last_backup.get('utc'), now)}{'' if last_backup.get('ok', True) else ' (failed)'}"
            if last_backup
            else "none yet"
        ),
        stack=html.escape(str(stack.get("phase") or "unknown")),
        updated=html.escape(_age(status.get("updated_utc"), now)),
        rows="".join(rows),
        teams="".join(team_cards),
        memory=memory,
        config=html.escape(json.dumps(config, ensure_ascii=False, indent=2)),
    )


def goals_json(root: Path, personas: dict[str, Any]) -> bytes:
    graph_path = root / "runs/local/memory.sqlite"
    graph = Graph(graph_path) if graph_path.is_file() else None
    try:
        return json.dumps(
            current(root, personas, graph), ensure_ascii=False, indent=2, default=str
        ).encode("utf-8")
    finally:
        if graph is not None:
            graph.close()


def serve(
    root: Path, personas: dict[str, Any], teams: dict[str, Any], port: int = 8766
) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:
            return

        def do_GET(self) -> None:
            if self.path.startswith("/status.json"):
                path = root / STATUS_FILE
                body = path.read_bytes() if path.is_file() else b"{}"
                ctype = "application/json"
            elif self.path.startswith("/goals.json"):
                body = goals_json(root, personas)
                ctype = "application/json"
            else:
                body = render(root, personas, teams).encode("utf-8")
                ctype = "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


__all__ = ["goals_json", "render", "serve"]
