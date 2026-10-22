"""A2A for the collective: one Agent Card per persona and a message endpoint that becomes a task.

The surface follows the A2A 1.0 JSON-RPC binding at the size the collective needs: discovery at
``/agents/<slug>/.well-known/agent-card.json`` (and a list at ``/agents``), ``message/send`` creating a
task in the shared memory graph (state ``submitted``) that the persona's next wake can read as a
message for it, ``tasks/get`` and ``tasks/cancel``. Served by the standard library on 127.0.0.1 so an
OpenClaw operator agent in the NemoClaw sandbox, Claude Code or another local agent can address a
persona without the world's inbox.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from hglab.local.memory import Graph

PROTOCOL_VERSION = "1.0"


def agent_card(persona: Any, team: Any | None, base_url: str) -> dict[str, Any]:
    skills = [
        {
            "id": f"{persona.slug}-whisper",
            "name": "Whisper in the world",
            "description": f"Send {persona.name} a message it reads at its next wake and may answer in Hinterglass by whisper.",
            "tags": ["hinterglass", "whisper"],
        },
        {
            "id": f"{persona.slug}-goal",
            "name": "Propose a goal",
            "description": "Propose something for this persona to do in the world; its planner weighs it against its intent.",
            "tags": ["goal"],
        },
    ]
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "name": persona.name,
        "description": f"{persona.intent} ({'team ' + team.name if team else 'no team'}; roles {', '.join(persona.roles)})",
        "url": f"{base_url}/agents/{persona.slug}/rpc",
        "preferredTransport": "JSONRPC",
        "version": "1",
        "capabilities": {
            "streaming": False,
            "pushNotifications": False,
            "stateTransitionHistory": True,
        },
        "defaultInputModes": ["text/plain"],
        "defaultOutputModes": ["text/plain"],
        "skills": skills,
        "provider": {
            "organization": "the collective (my_hinters)",
            "url": "https://github.com/rmcveyhsawaknow/my_hinters",
        },
        "securitySchemes": {"local": {"type": "apiKey", "in": "header", "name": "X-Local-Token"}},
    }


class TaskStore:
    """Tasks live in the shared memory graph as ``task`` nodes with ``message`` edges from the sender."""

    def __init__(self, graph: Graph) -> None:
        self.graph = graph

    def create(self, agent: str, sender: str, text: str, tick: int = 0) -> dict[str, Any]:
        task_id = str(uuid.uuid4())
        now = datetime.now(UTC).isoformat()
        self.graph.upsert_node(
            "task",
            f"task:{task_id}",
            tick=tick,
            agent=agent,
            sender=sender,
            text=text[:1000],
            state="submitted",
            created_utc=now,
            updated_utc=now,
            history=[{"state": "submitted", "utc": now}],
        )
        self.graph.add_edge(sender, f"task:{task_id}", "sent", tick, text=text[:120])
        self.graph.add_edge(f"task:{task_id}", agent, "for", tick)
        return self.get(task_id) or {}

    def get(self, task_id: str) -> dict[str, Any] | None:
        node = self.graph.node(f"task:{task_id}")
        if not node:
            return None
        return {
            "id": task_id,
            "contextId": node.get("agent"),
            "status": {
                "state": node.get("state", "submitted"),
                "timestamp": node.get("updated_utc"),
            },
            "history": [
                {
                    "role": "user",
                    "parts": [{"kind": "text", "text": node.get("text", "")}],
                    "messageId": task_id,
                }
            ],
            "metadata": {
                "sender": node.get("sender"),
                "agent": node.get("agent"),
                "transitions": node.get("history", []),
            },
        }

    def set_state(self, task_id: str, state: str, note: str | None = None) -> dict[str, Any] | None:
        node = self.graph.node(f"task:{task_id}")
        if not node:
            return None
        now = datetime.now(UTC).isoformat()
        history = list(node.get("history") or []) + [
            {"state": state, "utc": now, **({"note": note} if note else {})}
        ]
        self.graph.upsert_node(
            "task", f"task:{task_id}", state=state, updated_utc=now, history=history[-20:]
        )
        return self.get(task_id)

    def pending_for(self, agent: str) -> list[dict[str, Any]]:
        return [
            t
            for t in (
                self.get(n["id"][5:]) for n in self.graph.nodes("task") if n.get("agent") == agent
            )
            if t and t["status"]["state"] in {"submitted", "working"}
        ]


def make_handler(
    personas: dict[str, Any],
    teams: dict[str, Any],
    store: TaskStore,
    base_url: str,
    token: str | None,
) -> type[BaseHTTPRequestHandler]:
    by_name = {p.name.casefold(): slug for slug, p in personas.items()}

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, payload: dict[str, Any] | list[Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _slug(self, path: str) -> str | None:
            parts = path.strip("/").split("/")
            if len(parts) >= 2 and parts[0] == "agents":
                slug = parts[1]
                return slug if slug in personas else by_name.get(slug.casefold())
            return None

        def do_GET(self) -> None:
            if self.path.rstrip("/") == "/agents":
                self._send(
                    200,
                    [
                        {
                            "slug": slug,
                            "name": p.name,
                            "card": f"{base_url}/agents/{slug}/.well-known/agent-card.json",
                        }
                        for slug, p in personas.items()
                    ],
                )
                return
            slug = self._slug(self.path)
            if slug and self.path.endswith("/.well-known/agent-card.json"):
                persona = personas[slug]
                self._send(200, agent_card(persona, teams.get(persona.team), base_url))
                return
            self._send(404, {"error": "not_found"})

        def do_POST(self) -> None:
            slug = self._slug(self.path)
            if not slug or not self.path.endswith("/rpc"):
                self._send(404, {"error": "not_found"})
                return
            if token and self.headers.get("X-Local-Token") != token:
                self._send(401, {"error": "unauthorized"})
                return
            length = int(self.headers.get("Content-Length") or 0)
            try:
                request = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                self._send(
                    400,
                    {
                        "jsonrpc": "2.0",
                        "error": {"code": -32700, "message": "parse error"},
                        "id": None,
                    },
                )
                return
            method, params, rid = (
                request.get("method"),
                request.get("params") or {},
                request.get("id"),
            )
            persona = personas[slug]
            if method in {"message/send", "SendMessage"}:
                message = params.get("message") or {}
                text = " ".join(
                    str(p.get("text", ""))
                    for p in (message.get("parts") or [])
                    if isinstance(p, dict)
                ).strip()
                sender = str(
                    (message.get("metadata") or {}).get("sender")
                    or params.get("sender")
                    or "operator"
                )
                if not text:
                    self._send(
                        200,
                        {
                            "jsonrpc": "2.0",
                            "error": {"code": -32602, "message": "a message needs a text part"},
                            "id": rid,
                        },
                    )
                    return
                task = store.create(persona.name, sender, text)
                self._send(200, {"jsonrpc": "2.0", "result": task, "id": rid})
            elif method in {"tasks/get", "GetTask"}:
                task = store.get(str(params.get("id", "")))
                self._send(
                    200,
                    {"jsonrpc": "2.0", "result": task, "id": rid}
                    if task
                    else {
                        "jsonrpc": "2.0",
                        "error": {"code": -32001, "message": "task not found"},
                        "id": rid,
                    },
                )
            elif method in {"tasks/cancel", "CancelTask"}:
                task = store.set_state(str(params.get("id", "")), "canceled")
                self._send(
                    200,
                    {"jsonrpc": "2.0", "result": task, "id": rid}
                    if task
                    else {
                        "jsonrpc": "2.0",
                        "error": {"code": -32001, "message": "task not found"},
                        "id": rid,
                    },
                )
            else:
                self._send(
                    200,
                    {
                        "jsonrpc": "2.0",
                        "error": {"code": -32601, "message": f"method not found: {method}"},
                        "id": rid,
                    },
                )

    return Handler


def serve(
    root: Path,
    personas: dict[str, Any],
    teams: dict[str, Any],
    port: int = 8765,
    token: str | None = None,
    graph_path: Path | None = None,
) -> ThreadingHTTPServer:
    graph = Graph(graph_path or root / "runs/local/memory.sqlite")
    base_url = f"http://127.0.0.1:{port}"
    server = ThreadingHTTPServer(
        ("127.0.0.1", port), make_handler(personas, teams, TaskStore(graph), base_url, token)
    )
    return server


__all__ = ["PROTOCOL_VERSION", "TaskStore", "agent_card", "make_handler", "serve"]
