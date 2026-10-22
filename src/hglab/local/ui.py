"""A quick status page: agents, teams, the supervisor's last jobs, the memory graph, the configuration.

Standard-library HTTP on 127.0.0.1, one HTML page that reads ``runs/local/status.json``, the local
configuration and the memory graph's counts on every request, and a JSON view at ``/status.json``.
"""

from __future__ import annotations

import html
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from string import Template
from typing import Any

from hglab.local.memory import Graph
from hglab.local.supervisor import STATUS_FILE, load_local_config

PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Collective status</title>
<style>
:root{--bg:#f7f6f2;--fg:#1d1d1b;--muted:#6b6a66;--card:#fff;--line:#e4e2dc;--ok:#1b7f4b;--bad:#b3261e;--warn:#9a6b00}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#15161a;--fg:#ecebe6;--muted:#a4a39c;--card:#1f2127;--line:#2f323a}}
body{margin:0;padding:16px;background:var(--bg);color:var(--fg);font:15px/1.45 system-ui,sans-serif}
h1{font-size:20px;margin:0 0 4px}h2{font-size:16px;margin:24px 0 8px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:12px}
.muted{color:var(--muted)}.ok{color:var(--ok)}.bad{color:var(--bad)}.warn{color:var(--warn)}
table{border-collapse:collapse;width:100%}td,th{padding:4px 6px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
code{font-size:13px}
</style></head><body>
<h1>Collective status</h1><div class="muted">host $host · supervisor $running · updated $updated · <a href="/status.json">status.json</a></div>
<h2>Agents</h2><div class="cards">$agents</div>
<h2>Shared memory</h2><div class="card">$memory</div>
<h2>Configuration</h2><div class="card"><pre><code>$config</code></pre></div>
</body></html>"""


def render(root: Path, personas: dict[str, Any], teams: dict[str, Any]) -> str:
    status = {}
    path = root / STATUS_FILE
    if path.is_file():
        try:
            status = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            status = {}
    config = load_local_config(root)
    enabled = {e.get("slug"): e for e in config.get("agents", []) if isinstance(e, dict)}
    cards = []
    for slug, persona in sorted(personas.items(), key=lambda kv: (kv[1].team, kv[0])):
        entry = enabled.get(slug)
        last = ((status.get("agents") or {}).get(slug) or {}).get("last") or {}
        state = "local" if entry and entry.get("enabled", True) else "actions"
        cls = "ok" if last.get("exit") == 0 else "bad" if last else "muted"
        team = teams.get(persona.team)
        cards.append(
            f"<div class=card><strong>{html.escape(persona.name)}</strong> <span class=muted>{html.escape(slug)} · {html.escape(team.name if team else persona.team)}</span>"
            f"<div class=muted>{html.escape(persona.intent[:140])}</div>"
            f"<div>runtime: <strong>{state}</strong>{' (dry run)' if entry and entry.get('dry_run', config.get('dry_run', True)) else ''}</div>"
            + (
                f"<div class={cls}>last {html.escape(str(last.get('job')))} exit {last.get('exit')} at {html.escape(str(last.get('finished_utc', ''))[:19])}: {html.escape(str(last.get('summary', ''))[:140])}</div>"
                if last
                else "<div class=muted>no local job yet</div>"
            )
            + f"<div class=muted>cadence <code>{html.escape(str((persona.knobs.get('cadence') or {}).get('cron', '')))}</code> · work <code>{html.escape(str((persona.knobs.get('work') or {}).get('cron', '')))}</code></div></div>"
        )
    graph_path = root / "runs/local/memory.sqlite"
    if graph_path.is_file():
        g = Graph(graph_path)
        c = g.counts()
        g.close()
        memory = f"nodes {html.escape(json.dumps(c['nodes']))}<br>edges {html.escape(json.dumps(c['edges']))}<br>latest tick {c['latest_tick']}"
    else:
        memory = "<span class=muted>no memory graph yet: run <code>hglab local memory ingest</code></span>"
    return Template(PAGE).substitute(
        host=html.escape(str(status.get("host", ""))),
        running="running" if status.get("running") else "stopped",
        updated=html.escape(str(status.get("updated_utc", ""))[:19]),
        agents="".join(cards),
        memory=memory,
        config=html.escape(json.dumps(config, ensure_ascii=False, indent=2)),
    )


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
            else:
                body = render(root, personas, teams).encode("utf-8")
                ctype = "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


__all__ = ["render", "serve"]
