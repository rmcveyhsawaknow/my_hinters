"""The collective's shared memory: a property graph on SQLite, with dated snapshots.

Nodes are agents, teams, goals, lots, structures and tasks; edges are what happened between them
(whispered, gave, said to, claimed, surveyed, deeded, struck, welcomed) with the tick they happened
at. The store is one file, portable to any machine Python runs on; ``snapshot`` copies it with the
SQLite backup API and ``restore`` brings a copy back. Nothing private beyond the agents' own words
goes in: whispers are kept as short excerpts of what our agents said, never what others said to them.
"""

from __future__ import annotations

import json
import re
import shutil
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes (
  id TEXT PRIMARY KEY, kind TEXT NOT NULL, props TEXT NOT NULL DEFAULT '{}', tick INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS nodes_kind ON nodes(kind);
CREATE TABLE IF NOT EXISTS edges (
  id INTEGER PRIMARY KEY AUTOINCREMENT, src TEXT NOT NULL, dst TEXT NOT NULL, kind TEXT NOT NULL,
  tick INTEGER NOT NULL DEFAULT 0, props TEXT NOT NULL DEFAULT '{}',
  UNIQUE(src, dst, kind, tick)
);
CREATE INDEX IF NOT EXISTS edges_src ON edges(src, kind);
CREATE INDEX IF NOT EXISTS edges_dst ON edges(dst, kind);
CREATE TABLE IF NOT EXISTS snapshots (name TEXT PRIMARY KEY, utc TEXT NOT NULL, tick INTEGER NOT NULL, nodes INTEGER NOT NULL, edges INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS ingested (key TEXT PRIMARY KEY, utc TEXT NOT NULL);
"""

GAVE = re.compile(
    r"^(?P<actor>[\w-]+) gave (?P<qty>\d+) (?P<item>\w+) to (?P<to>[\w-]+)\.?$", re.IGNORECASE
)
PUT = re.compile(
    r"^(?P<actor>[\w-]+) put (?P<qty>\d+) (?P<item>\w+) into the storehouse at \((?P<x>\d+), ?(?P<y>\d+)\)\.?$",
    re.IGNORECASE,
)
STRUCK = re.compile(
    r"^(?P<actor>[\w-]+) (?:struck|tore down) (?P<owner>[\w-]+)'s (?P<kind>\w+) at \((?P<x>\d+), ?(?P<y>\d+)\)",
    re.IGNORECASE,
)
INVITED = re.compile(r"^(?P<actor>[\w-]+) invited (?P<to>[\w-]+)", re.IGNORECASE)


class Graph:
    """One connection per thread, so the A2A and UI servers can share a Graph with the main thread."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._local = threading.local()
        self.db.executescript(SCHEMA)

    @property
    def db(self) -> sqlite3.Connection:
        db = getattr(self._local, "db", None)
        if db is None:
            db = sqlite3.connect(str(self.path))
            db.row_factory = sqlite3.Row
            self._local.db = db
        return db

    # --- writing -----------------------------------------------------------------------------
    def upsert_node(self, kind: str, node_id: str, tick: int = 0, **props: Any) -> None:
        row = self.db.execute("SELECT props, tick FROM nodes WHERE id = ?", (node_id,)).fetchone()
        merged = {
            **(json.loads(row["props"]) if row else {}),
            **{k: v for k, v in props.items() if v is not None},
        }
        newest = max(int(tick), int(row["tick"]) if row else 0)
        self.db.execute(
            "INSERT INTO nodes(id, kind, props, tick) VALUES (?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET kind = excluded.kind, props = excluded.props, tick = excluded.tick",
            (node_id, kind, json.dumps(merged, ensure_ascii=False, sort_keys=True), newest),
        )
        self.db.commit()

    def add_edge(self, src: str, dst: str, kind: str, tick: int = 0, **props: Any) -> bool:
        """True when the edge is new; the same (src, dst, kind, tick) is kept once."""
        cur = self.db.execute(
            "INSERT OR IGNORE INTO edges(src, dst, kind, tick, props) VALUES (?, ?, ?, ?, ?)",
            (
                src,
                dst,
                kind,
                int(tick),
                json.dumps(
                    {k: v for k, v in props.items() if v is not None},
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ),
        )
        self.db.commit()
        return cur.rowcount == 1

    def mark_ingested(self, key: str) -> bool:
        cur = self.db.execute(
            "INSERT OR IGNORE INTO ingested(key, utc) VALUES (?, ?)",
            (key, datetime.now(UTC).isoformat()),
        )
        self.db.commit()
        return cur.rowcount == 1

    # --- reading -----------------------------------------------------------------------------
    def node(self, node_id: str) -> dict[str, Any] | None:
        row = self.db.execute(
            "SELECT id, kind, props, tick FROM nodes WHERE id = ?", (node_id,)
        ).fetchone()
        return (
            {"id": row["id"], "kind": row["kind"], "tick": row["tick"], **json.loads(row["props"])}
            if row
            else None
        )

    def nodes(self, kind: str | None = None) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT id, kind, props, tick FROM nodes WHERE (? IS NULL OR kind = ?) ORDER BY kind, id",
            (kind, kind),
        ).fetchall()
        return [
            {"id": r["id"], "kind": r["kind"], "tick": r["tick"], **json.loads(r["props"])}
            for r in rows
        ]

    def edges(
        self,
        node_id: str | None = None,
        kind: str | None = None,
        since_tick: int = 0,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT src, dst, kind, tick, props FROM edges WHERE (? IS NULL OR src = ? OR dst = ?) AND (? IS NULL OR kind = ?) AND tick >= ? ORDER BY tick DESC LIMIT ?",
            (node_id, node_id, node_id, kind, kind, int(since_tick), int(limit)),
        ).fetchall()
        return [
            {
                "src": r["src"],
                "dst": r["dst"],
                "kind": r["kind"],
                "tick": r["tick"],
                **json.loads(r["props"]),
            }
            for r in rows
        ]

    def counts(self) -> dict[str, Any]:
        nodes = {
            r["kind"]: r["n"]
            for r in self.db.execute("SELECT kind, COUNT(*) AS n FROM nodes GROUP BY kind")
        }
        edges = {
            r["kind"]: r["n"]
            for r in self.db.execute("SELECT kind, COUNT(*) AS n FROM edges GROUP BY kind")
        }
        tick = self.db.execute("SELECT COALESCE(MAX(tick), 0) AS t FROM edges").fetchone()["t"]
        return {"nodes": nodes, "edges": edges, "latest_tick": int(tick), "path": str(self.path)}

    def query(self, sql: str, limit: int = 100) -> list[dict[str, Any]]:
        """A read-only SELECT over nodes, edges and snapshots, for the MCP and CLI surfaces."""
        if not sql.strip().lower().startswith("select"):
            raise ValueError("only SELECT statements are allowed")
        rows = self.db.execute(sql).fetchmany(int(limit))
        return [dict(r) for r in rows]

    def contacts(self, agent: str, since_tick: int = 0) -> dict[str, Any]:
        """Who this agent has reached and who reached it, with the newest tick per name: what a wake reads first."""
        out: dict[str, dict[str, Any]] = {}
        for e in self.edges(agent, since_tick=since_tick, limit=500):
            other = e["dst"] if e["src"] == agent else e["src"]
            if other == agent or not other:
                continue
            entry = out.setdefault(
                other, {"sent": 0, "received": 0, "last_tick": 0, "kinds": set()}
            )
            entry["sent" if e["src"] == agent else "received"] += 1
            entry["last_tick"] = max(entry["last_tick"], int(e["tick"]))
            entry["kinds"].add(e["kind"])
        return {
            k: {**v, "kinds": sorted(v["kinds"])}
            for k, v in sorted(out.items(), key=lambda kv: -kv[1]["last_tick"])
        }

    def promises(self, agent: str | None = None) -> list[dict[str, Any]]:
        """Open promises: surveys not deeded, claims not delivered, deeds owed."""
        rows = self.edges(agent, kind="promised", limit=500)
        kept = {
            (e["src"], e["dst"], e.get("about")) for e in self.edges(agent, kind="kept", limit=500)
        }
        return [e for e in rows if (e["src"], e["dst"], e.get("about")) not in kept]

    def performance(self, agent: str | None = None) -> dict[str, Any]:
        """Wakes, actions, failures, tokens and energy per persona and model, plus local job timings."""
        wakes = self.db.execute(
            """SELECT json_extract(props, '$.agent') AS agent, json_extract(props, '$.model') AS model,
                      json_extract(props, '$.runtime') AS runtime, COUNT(*) AS wakes,
                      SUM(json_extract(props, '$.actions')) AS actions, SUM(json_extract(props, '$.failed')) AS failed,
                      SUM(json_extract(props, '$.calls')) AS calls, SUM(json_extract(props, '$.input_tokens')) AS input_tokens,
                      SUM(json_extract(props, '$.output_tokens')) AS output_tokens,
                      ROUND(AVG(json_extract(props, '$.energy_spent')), 2) AS energy_per_wake, MAX(tick) AS last_tick
               FROM nodes WHERE kind = 'wake' AND (? IS NULL OR json_extract(props, '$.agent') = ?)
               GROUP BY 1, 2, 3 ORDER BY 1, wakes DESC""",
            (agent, agent),
        ).fetchall()
        jobs = self.db.execute(
            """SELECT json_extract(props, '$.agent') AS agent, json_extract(props, '$.job') AS job, COUNT(*) AS runs,
                      SUM(CASE WHEN json_extract(props, '$.exit') = 0 THEN 0 ELSE 1 END) AS failures,
                      ROUND(AVG(json_extract(props, '$.seconds')), 1) AS seconds_per_run, MAX(json_extract(props, '$.started_utc')) AS last_utc
               FROM nodes WHERE kind = 'job' AND (? IS NULL OR json_extract(props, '$.agent') = ?)
               GROUP BY 1, 2 ORDER BY 1, 2""",
            (agent, agent),
        ).fetchall()
        return {"wakes": [dict(r) for r in wakes], "jobs": [dict(r) for r in jobs]}

    # --- snapshots ---------------------------------------------------------------------------
    def snapshot(self, name: str | None = None) -> Path:
        name = name or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", name):
            raise ValueError("a snapshot name is letters, digits, dot, dash or underscore")
        folder = self.path.with_suffix("").parent / f"{self.path.stem}.snapshots"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{name}.sqlite"
        copy = sqlite3.connect(str(target))
        with copy:
            self.db.backup(copy)
        copy.close()
        c = self.counts()
        self.db.execute(
            "INSERT OR REPLACE INTO snapshots(name, utc, tick, nodes, edges) VALUES (?, ?, ?, ?, ?)",
            (
                name,
                datetime.now(UTC).isoformat(),
                c["latest_tick"],
                sum(c["nodes"].values()),
                sum(c["edges"].values()),
            ),
        )
        self.db.commit()
        return target

    def snapshots(self) -> list[dict[str, Any]]:
        return [
            dict(r)
            for r in self.db.execute(
                "SELECT name, utc, tick, nodes, edges FROM snapshots ORDER BY utc DESC"
            )
        ]

    def restore(self, name: str) -> None:
        source = self.path.parent / f"{self.path.stem}.snapshots" / f"{name}.sqlite"
        if not source.is_file():
            raise FileNotFoundError(f"no snapshot {name}")
        self.close()
        shutil.copyfile(source, self.path)

    def close(self) -> None:
        db = getattr(self._local, "db", None)
        if db is not None:
            db.close()
            self._local.db = None


# --- ingestion -------------------------------------------------------------------------------
def ingest_personas(graph: Graph, personas: dict[str, Any], teams: dict[str, Any]) -> None:
    for slug, team in teams.items():
        graph.upsert_node(
            "team",
            f"team:{slug}",
            name=team.name,
            aim=team.aim,
            members=list(team.members),
            home=team.home,
        )
    for slug, persona in personas.items():
        graph.upsert_node(
            "agent",
            persona.name,
            slug=slug,
            team=persona.team,
            intent=persona.intent,
            roles=list(persona.roles),
            ours=True,
        )
        graph.add_edge(persona.name, f"team:{persona.team}", "member_of")


def ingest_record(graph: Graph, record: dict[str, Any]) -> int:
    """Edges from one redacted run record: what our agent did toward whom. Returns the edges added."""
    actor = str(record.get("agent") or "")
    tick = int(record.get("tick", 0) or 0)
    key = str(
        record.get("run_id") or f"{actor}:{tick}:{record.get('kind') or record.get('wake_mode')}"
    )
    if not actor or not graph.mark_ingested(key):
        return 0
    added = 0
    for action in record.get("actions", []) or []:
        kind = action.get("action")
        if kind == "whisper" and action.get("to"):
            graph.upsert_node("agent", str(action["to"]))
            added += graph.add_edge(
                actor, str(action["to"]), "whispered", tick, text=str(action.get("text", ""))[:120]
            )
        elif kind == "give" and action.get("to"):
            graph.upsert_node("agent", str(action["to"]))
            added += graph.add_edge(
                actor,
                str(action["to"]),
                "gave",
                tick,
                item=action.get("item"),
                qty=action.get("qty"),
            )
        elif kind == "say" and action.get("text"):
            text = str(action["text"])
            head = text.split(",")[0].split(" ")[0].strip("!.:")
            known = graph.node(head) if head and head != actor else None
            if known and known.get("kind") == "agent":
                added += graph.add_edge(actor, head, "said_to", tick, text=text[:120])
        elif kind == "claim_goal" and action.get("goal_id"):
            graph.upsert_node("goal", f"goal:{action['goal_id']}")
            added += graph.add_edge(actor, f"goal:{action['goal_id']}", "claimed", tick)
        elif kind == "build" and action.get("type") in {
            "sign",
            "storehouse",
            "hut",
            "tower",
            "monument",
            "farm",
            "bridge",
            "wall",
        }:
            node = f"structure:{action.get('x')},{action.get('y')}"
            graph.upsert_node("structure", node, type=action.get("type"), owner=actor, tick=tick)
            added += graph.add_edge(actor, node, "built", tick, type=action.get("type"))
    for text in record.get("reasons", []) or []:
        text = str(text)
        if text.startswith("survey for ") and ": lot " in text:
            client = text[len("survey for ") :].split(":")[0]
            lot = text.split(": lot ")[1].split(" ")[0]
            graph.upsert_node("agent", client)
            graph.upsert_node("lot", f"lot:{lot}", surveyed_for=client)
            added += graph.add_edge(
                actor, client, "promised", tick, about=f"lot:{lot}", what="survey and deed"
            )
        if text.startswith("deeds for surveyed sites paid in full: "):
            for part in text.split(": ", 1)[1].split(", "):
                if " to " in part:
                    lot, holder = part.split(" to ", 1)
                    graph.upsert_node("agent", holder.strip())
                    graph.upsert_node("lot", f"lot:{lot.strip()}", holder=holder.strip())
                    added += graph.add_edge(
                        actor, holder.strip(), "kept", tick, about=f"lot:{lot.strip()}", what="deed"
                    )
                    added += graph.add_edge(holder.strip(), f"lot:{lot.strip()}", "holds", tick)
    attrs = wake_attributes(record)
    model = attrs["model"]
    graph.upsert_node("wake", f"wake:{key}", tick=tick, **attrs)
    graph.upsert_node("model", f"model:{model}", provider=attrs.get("provider"))
    added += graph.add_edge(
        actor, f"wake:{key}", "performed", tick, model=model, actions=attrs["actions"]
    )
    added += graph.add_edge(f"wake:{key}", f"model:{model}", "used", tick, calls=attrs["calls"])
    return added


def wake_attributes(record: dict[str, Any]) -> dict[str, Any]:
    """What one wake cost and produced, and which model did the thinking (``heuristic`` when none)."""
    usage = record.get("usage") if isinstance(record.get("usage"), dict) else {}
    calls = int(usage.get("calls", 0) or 0)
    failed = record.get("failed_actions") or []
    return {
        "agent": str(record.get("agent") or ""),
        "mode": str(record.get("wake_mode") or record.get("kind") or "wake"),
        "planner": str(record.get("planner") or ("heuristic" if calls == 0 else "llm")),
        "runtime": str(record.get("author_runtime") or "human"),
        "model": str(usage.get("model") or ("heuristic" if calls == 0 else "unknown")),
        "provider": usage.get("provider"),
        "route": usage.get("route"),
        "calls": calls,
        "input_tokens": int(usage.get("input_tokens", 0) or 0),
        "output_tokens": int(usage.get("output_tokens", 0) or 0),
        "actions": len(record.get("actions") or []),
        "failed": len(failed) if isinstance(failed, list) else int(bool(failed)),
        "energy_spent": record.get("energy_spent"),
        "dry_run": bool(record.get("dry_run")),
        "approach": record.get("approach"),
        "created_utc": record.get("created_utc"),
    }


def ingest_status(graph: Graph, status: dict[str, Any], names: dict[str, str]) -> int:
    """The job history of the local supervisor: one ``job`` node per run with seconds and exit, under the persona."""
    added = 0
    for slug, entry in (status.get("agents") or {}).items():
        name = names.get(slug, slug)
        for job in (entry.get("history") or []) if isinstance(entry, dict) else []:
            if not isinstance(job, dict) or not job.get("started_utc"):
                continue
            key = f"job:{slug}:{job['started_utc']}"
            if not graph.mark_ingested(key):
                continue
            graph.upsert_node(
                "job",
                key,
                agent=name,
                slug=slug,
                job=job.get("job"),
                exit=job.get("exit"),
                seconds=job.get("seconds"),
                dry_run=job.get("dry_run"),
                started_utc=job.get("started_utc"),
                summary=str(job.get("summary", ""))[:160],
            )
            graph.upsert_node("agent", name)
            added += graph.add_edge(
                name,
                key,
                "ran",
                0,
                job=job.get("job"),
                exit=job.get("exit"),
                seconds=job.get("seconds"),
            )
    return added


def ingest_public_events(graph: Graph, events: list[dict[str, Any]]) -> int:
    """Edges from the public log: gives, deposits, strikes, invitations, and who was seen."""
    added = 0
    for event in events:
        if not isinstance(event, dict) or not event.get("actor"):
            continue
        actor, tick, kind, text = (
            str(event["actor"]),
            int(event.get("tick", 0) or 0),
            str(event.get("type")),
            str(event.get("text") or ""),
        )
        key = f"event:{event.get('id') or f'{actor}:{tick}:{kind}'}"
        if not graph.mark_ingested(key):
            continue
        graph.upsert_node("agent", actor, tick=tick, last_seen_tick=tick)
        if kind == "give":
            if m := GAVE.match(text):
                graph.upsert_node("agent", m["to"])
                added += graph.add_edge(
                    actor, m["to"], "gave", tick, item=m["item"], qty=int(m["qty"])
                )
            elif m := PUT.match(text):
                node = f"structure:{m['x']},{m['y']}"
                graph.upsert_node("structure", node, type="storehouse")
                added += graph.add_edge(
                    actor, node, "deposited", tick, item=m["item"], qty=int(m["qty"])
                )
        elif kind == "demolish":
            if m := STRUCK.match(text):
                graph.upsert_node("agent", m["owner"])
                added += graph.add_edge(
                    actor,
                    m["owner"],
                    "struck",
                    tick,
                    structure=m["kind"],
                    x=int(m["x"]),
                    y=int(m["y"]),
                    destroyed="tore down" in text,
                )
        elif kind == "faction_invited":
            if m := INVITED.match(text):
                graph.upsert_node("agent", m["to"])
                added += graph.add_edge(actor, m["to"], "invited", tick)
        elif kind == "goal_done":
            data = event.get("data") if isinstance(event.get("data"), dict) else {}
            poster, claimant = str(data.get("poster") or ""), str(data.get("claimant") or actor)
            if poster and claimant:
                graph.upsert_node("agent", poster)
                added += graph.add_edge(
                    claimant,
                    poster,
                    "completed_goal_for",
                    tick,
                    title=str(data.get("title", ""))[:80],
                )
    return added


__all__ = ["Graph", "ingest_personas", "ingest_public_events", "ingest_record"]
