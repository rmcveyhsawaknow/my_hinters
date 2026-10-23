"""Adaptive goals: what each persona is doing now, what it should pursue next, and why.

Inputs, all local: the newest wake record (what the persona is doing and how it went), the persona's key
results in ``agents/<slug>/metrics.yaml`` with the latest published Pulse progress when there is one,
the outcomes of each approach in the memory graph (actions taken and failed per approach), and what
teammates are pursuing. ``adapt`` picks for every persona the key result with the largest weighted gap
that no teammate already covers, names the approaches that work and the ones to avoid, and records the
assignment in the graph as ``objective`` nodes and ``pursues`` edges. ``brief`` turns a changed assignment
into an operator message on the task board, so the next wake reads it. Team suggestions name where an
in-world goal (for outsiders to claim) or a faction would move the team forward; the rule that no
collective member claims another member's goal stands, so in-world goals are for work across collectives.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from hglab.local.memory import Graph

MIN_ACTIONS = 12  # below this an approach has not been tried enough to judge
BRIEF_EVERY_HOURS = 24


def latest_record(root: Path, name: str, slug: str) -> dict[str, Any] | None:
    """The newest wake record of a persona: local runs first, then the pulled reports."""
    newest: tuple[str, dict[str, Any]] | None = None
    folders = [
        *sorted((root / "runs").glob("20*"), reverse=True)[:3],
        *sorted((root / "reports" / "agents" / slug / "runs").glob("20*"), reverse=True)[:2],
    ]
    for folder in folders:
        for path in folder.glob(f"{name}-*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            stamp = str(record.get("created_utc") or "")
            if newest is None or stamp > newest[0]:
                newest = (stamp, record)
    return newest[1] if newest else None


def activity(record: dict[str, Any] | None, name: str) -> dict[str, Any]:
    """What a persona is doing now, from its newest record, in plain fields for a page."""
    if not record:
        return {
            "summary": None,
            "approach": None,
            "mood": None,
            "mode": None,
            "utc": None,
            "tick": None,
            "ok": None,
            "energy": None,
            "pack": None,
        }
    summary = str(record.get("summary") or "")
    prefix = f"{name} ("
    if summary.startswith(prefix) and "): " in summary:
        summary = summary.split("): ", 1)[1]
    results = record.get("results") or []
    oks = sum(1 for r in results if isinstance(r, dict) and r.get("ok"))
    you = (record.get("observe") or {}).get("you") or {}
    inventory = you.get("inventory") if isinstance(you.get("inventory"), dict) else {}
    return {
        "summary": summary[:160] or None,
        "approach": record.get("approach"),
        "mood": record.get("mood"),
        "mode": record.get("wake_mode"),
        "utc": record.get("created_utc"),
        "tick": record.get("tick"),
        "ok": f"{oks}/{len(results)}" if results else None,
        "energy": you.get("energy"),
        "pack": sum(int(v or 0) for v in inventory.values()) if inventory else None,
        "reason": (str(record.get("reasons", [""])[0])[:140] if record.get("reasons") else None),
        "dry_run": bool(record.get("dry_run")),
    }


def key_results(root: Path, slug: str) -> list[dict[str, Any]]:
    path = root / "agents" / slug / "metrics.yaml"
    if not path.is_file():
        return []
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return []
    out = []
    for item in data.get("key_results") or []:
        if isinstance(item, dict) and item.get("id") and item.get("target") is not None:
            out.append(
                {
                    "id": str(item["id"]),
                    "label": str(item.get("label") or item["id"]),
                    "target": item["target"],
                    "weight": float(item.get("weight") or 0.0),
                    "measure": item.get("measure"),
                }
            )
    return out


def pulse_progress(root: Path, slug: str) -> dict[str, dict[str, Any]]:
    """Progress per key result from the last published Pulse (``reports/agents/<slug>/pulse.json``), if any."""
    path = root / "reports" / "agents" / slug / "pulse.json"
    if not path.is_file():
        return {}
    try:
        pulse = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    out: dict[str, dict[str, Any]] = {}
    block = pulse.get("on_mission") or pulse.get("mission") or {}
    rows = []
    if isinstance(block, dict):
        for value in block.values():
            if (
                isinstance(value, list)
                and value
                and isinstance(value[0], dict)
                and "id" in value[0]
            ):
                rows = value
                break
    elif isinstance(block, list):
        rows = block
    for row in rows:
        progress = row.get("progress")
        if progress is None and row.get("value") is not None and row.get("target"):
            try:
                progress = min(1.0, float(row["value"]) / float(row["target"]))
            except (TypeError, ValueError, ZeroDivisionError):
                progress = None
        out[str(row.get("id"))] = {
            "value": row.get("value"),
            "progress": progress,
            "tick": pulse.get("tick"),
        }
    return out


def approach_outcomes(graph: Graph, name: str) -> list[dict[str, Any]]:
    """Per approach: wakes, actions, failed actions and the success share, from the wake nodes."""
    rows = graph.db.execute(
        "SELECT json_extract(props, '$.approach') AS approach, COUNT(*) AS wakes, COALESCE(SUM(json_extract(props, '$.actions')), 0) AS actions,"
        " COALESCE(SUM(json_extract(props, '$.failed')), 0) AS failed FROM nodes WHERE kind = 'wake' AND json_extract(props, '$.agent') = ?"
        " AND json_extract(props, '$.approach') IS NOT NULL GROUP BY 1 ORDER BY wakes DESC",
        (name,),
    ).fetchall()
    out = []
    for r in rows:
        actions, failed = int(r["actions"] or 0), int(r["failed"] or 0)
        out.append(
            {
                "approach": r["approach"],
                "wakes": int(r["wakes"]),
                "actions": actions,
                "failed": failed,
                "success": round(1 - failed / actions, 3) if actions else None,
            }
        )
    return out


def works_and_avoid(outcomes: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    judged = [
        o
        for o in outcomes
        if o["actions"] >= MIN_ACTIONS and o["success"] is not None and o["approach"] != "rest"
    ]
    works = [
        o["approach"]
        for o in sorted(judged, key=lambda o: (-o["success"], -o["actions"]))
        if o["success"] >= 0.9
    ][:3]
    avoid = [
        o["approach"] for o in sorted(judged, key=lambda o: o["success"]) if o["success"] < 0.8
    ][:2]
    return works, avoid


def assignment_for(
    persona: Any, krs: list[dict[str, Any]], progress: dict[str, dict[str, Any]], covered: set[str]
) -> dict[str, Any] | None:
    """The key result with the largest weighted gap, halved when a teammate already pursues the same measure."""
    best: dict[str, Any] | None = None
    for kr in krs:
        if kr["weight"] <= 0:
            continue
        done = progress.get(kr["id"], {}).get("progress")
        gap = 1.0 if done is None else max(0.0, 1.0 - float(done))
        if gap <= 0:
            continue
        measure = str(kr.get("measure") or "")
        score = kr["weight"] * gap * (0.5 if measure in covered else 1.0)
        candidate = {
            "id": kr["id"],
            "label": kr["label"],
            "target": kr["target"],
            "weight": kr["weight"],
            "measure": measure,
            "progress": done,
            "score": round(score, 3),
            "shared": measure in covered,
        }
        if best is None or candidate["score"] > best["score"]:
            best = candidate
    return best


def team_suggestions(team: Any, members: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Where an in-world goal or a faction would move the team: data-backed, never a claim on a member's goal."""
    out: list[dict[str, Any]] = []
    failing = [
        (slug, o)
        for slug, m in members.items()
        for o in m.get("outcomes", [])
        if o["actions"] >= MIN_ACTIONS
        and o["success"] is not None
        and o["success"] < 0.8
        and o["approach"] in {"deposit", "migrate", "deposit_trip", "gather_trip"}
    ]
    if failing:
        slug, o = min(failing, key=lambda t: t[1]["success"])
        out.append(
            {
                "kind": "post_goal",
                "text": f"Logistics keep failing for {members[slug]['name']} ({o['approach']}: {int((1 - o['success']) * 100)}% of actions). Post an in-world goal for the delivery with a reward, so an outsider can claim it; teammates never claim it.",
                "evidence": f"{o['approach']} {o['failed']}/{o['actions']} failed",
            }
        )
    if len(members) >= 2 and not (team.extra or {}).get("faction"):
        out.append(
            {
                "kind": "faction",
                "text": f"{team.name} has no in-world faction recorded. One member founds a faction named for the team and invites the others; then `faction:` in teams/{team.slug}.yaml records it and the Pulse can count members.",
                "evidence": f"{len(members)} members, teams/{team.slug}.yaml has no faction",
            }
        )
    shared = {}
    for slug, m in members.items():
        a = m.get("assignment") or {}
        if a.get("measure"):
            shared.setdefault(a["measure"], []).append(m["name"])
    for measure, names in shared.items():
        if len(names) >= 2:
            out.append(
                {
                    "kind": "split",
                    "text": f"{' and '.join(names)} pursue the same measure ({measure}); split it by area or by hour so the team covers more.",
                    "evidence": "same measure on two assignments",
                }
            )
    return out


def adapt(
    root: Path, graph: Graph, personas: dict[str, Any], teams: dict[str, Any], tick: int = 0
) -> dict[str, Any]:
    """Assignments for every persona and suggestions for every team; written to the graph."""
    now = datetime.now(UTC).isoformat()
    per_slug: dict[str, dict[str, Any]] = {}
    for slug, persona in personas.items():
        record = latest_record(root, persona.name, slug)
        per_slug[slug] = {
            "slug": slug,
            "name": persona.name,
            "team": persona.team,
            "activity": activity(record, persona.name),
            "key_results": key_results(root, slug),
            "progress": pulse_progress(root, slug),
            "outcomes": approach_outcomes(graph, persona.name),
        }
    for slug, data in per_slug.items():
        teammates = [s for s, d in per_slug.items() if d["team"] == data["team"] and s != slug]
        covered = {
            str(kr.get("measure") or "")
            for s in teammates
            for kr in [per_slug[s].get("assignment") or {}]
            if kr.get("measure")
        }
        chosen = assignment_for(personas[slug], data["key_results"], data["progress"], covered)
        works, avoid = works_and_avoid(data["outcomes"])
        because = []
        if chosen:
            because.append(
                f"largest weighted gap among the key results ({chosen['label']}: {'no measurement yet' if chosen['progress'] is None else f'{int(chosen["progress"] * 100)}% of {chosen["target"]}'}, weight {chosen['weight']})"
            )
            if chosen["shared"]:
                because.append(
                    "a teammate pursues the same measure, so this counts half; split the ground"
                )
        if works:
            because.append(f"approaches that work for {data['name']}: {', '.join(works)}")
        if avoid:
            because.append(f"avoid until fixed: {', '.join(avoid)}")
        data["assignment"] = (
            {**chosen, "works": works, "avoid": avoid, "because": because, "utc": now}
            if chosen
            else None
        )
        if chosen:
            node = f"objective:{slug}:{chosen['id']}"
            graph.upsert_node(
                "objective",
                node,
                tick=tick,
                slug=slug,
                team=data["team"],
                label=chosen["label"],
                target=chosen["target"],
                measure=chosen["measure"],
                progress=chosen["progress"],
            )
            graph.add_edge(
                data["name"],
                node,
                "pursues",
                tick,
                score=chosen["score"],
                why=" | ".join(because)[:400],
                utc=now,
                works=works,
                avoid=avoid,
            )
    boards = {}
    for tslug, team in teams.items():
        members = {s: d for s, d in per_slug.items() if d["team"] == tslug}
        suggestions = team_suggestions(team, members)
        current_kinds = {s["kind"] for s in suggestions}
        for s in suggestions:
            graph.upsert_node(
                "suggestion",
                f"suggestion:{tslug}:{s['kind']}",
                team=tslug,
                kind=s["kind"],
                text=s["text"],
                evidence=s.get("evidence"),
                utc=now,
                active=True,
            )
        for stale in graph.nodes("suggestion"):
            if (
                stale.get("team") == tslug
                and stale.get("kind") not in current_kinds
                and stale.get("active", True)
            ):
                graph.upsert_node("suggestion", stale["id"], active=False)
        boards[tslug] = {
            "team": team.name,
            "aim": team.aim,
            "members": {
                s: {"name": d["name"], "assignment": d["assignment"], "activity": d["activity"]}
                for s, d in members.items()
            },
            "suggestions": suggestions,
        }
    return {"utc": now, "agents": per_slug, "teams": boards}


def brief(root: Path, graph: Graph, plan: dict[str, Any], sender: str = "goals") -> list[str]:
    """One operator message per persona whose assignment is new or a day old; returns the slugs briefed."""
    from hglab.local.a2a import TaskStore

    store = TaskStore(graph)
    briefed = []
    for slug, data in plan["agents"].items():
        a = data.get("assignment")
        if not a:
            continue
        node = graph.node(f"objective:{slug}:{a['id']}") or {}
        last = node.get("briefed_utc")
        if last and datetime.fromisoformat(last) > datetime.now(UTC) - timedelta(
            hours=BRIEF_EVERY_HOURS
        ):
            continue
        text = (
            f"Goal brief for {data['name']}: pursue {a['label']} (target {a['target']}). "
            + " ".join(f"{b}." for b in a["because"])
            + " This is guidance from the team's own measurements, not an order from the world."
        )
        store.create(data["name"], sender, text[:900])
        graph.upsert_node(
            "objective", f"objective:{slug}:{a['id']}", briefed_utc=datetime.now(UTC).isoformat()
        )
        briefed.append(slug)
    return briefed


def wake_guidance(root: Path, name: str, team_slug: str | None) -> dict[str, Any]:
    """What a wake on this host may read from the graph: its assignment (label, works, avoid) and the team's live suggestions."""
    path = root / "runs/local/memory.sqlite"
    if not path.is_file():
        return {}
    graph = Graph(path)
    try:
        assignment = None
        edges = graph.edges(name, kind="pursues", limit=1)
        if edges:
            node = graph.node(edges[0]["dst"]) or {}
            assignment = {
                "label": node.get("label"),
                "works": list(edges[0].get("works") or []),
                "avoid": list(edges[0].get("avoid") or []),
            }
        suggestions = [
            {k: n.get(k) for k in ("kind", "text", "evidence", "utc")}
            for n in graph.nodes("suggestion")
            if n.get("team") == team_slug and n.get("active", True)
        ]
        return {"assignment": assignment, "suggestions": suggestions}
    except Exception:  # noqa: BLE001 - guidance is optional; a wake never fails for lack of it
        return {}
    finally:
        graph.close()


def current(
    root: Path, personas: dict[str, Any], graph: Graph | None = None
) -> dict[str, dict[str, Any]]:
    """For a page: activity now plus the recorded assignment (from the graph) for every persona."""
    out = {}
    for slug, persona in personas.items():
        record = latest_record(root, persona.name, slug)
        assignment = None
        if graph is not None:
            edges = graph.edges(persona.name, kind="pursues", limit=1)
            if edges:
                node = graph.node(edges[0]["dst"]) or {}
                assignment = {
                    "label": node.get("label"),
                    "target": node.get("target"),
                    "progress": node.get("progress"),
                    "why": edges[0].get("why"),
                    "utc": edges[0].get("utc"),
                }
        out[slug] = {"activity": activity(record, persona.name), "assignment": assignment}
    return out


__all__ = [
    "activity",
    "adapt",
    "approach_outcomes",
    "assignment_for",
    "brief",
    "current",
    "key_results",
    "latest_record",
    "pulse_progress",
    "team_suggestions",
    "wake_guidance",
    "works_and_avoid",
]
