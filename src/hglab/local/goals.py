"""Adaptive goals: what each persona is doing now, what it should pursue next, and why.

Inputs, all local: the newest wake record (what the persona is doing and how it went), the persona's key
results in ``agents/<slug>/metrics.yaml`` with the latest published Pulse progress when there is one,
the outcomes of each approach in the memory graph (actions taken, failed and goal-relevant per
approach), what teammates are pursuing, and the public events archive this host keeps. ``adapt`` picks
for every persona the key result with the largest weighted gap that no teammate already covers, names
the approaches to prefer (the measure's own approaches first, then the ones that produced goal-relevant
actions) and the ones to avoid (failing, or the one a stalled persona has been repeating), and records
the assignment in the graph as ``objective`` nodes and ``pursues`` edges. ``brief`` turns a changed or
stalled assignment into an operator message on the task board, so the next wake reads it. Team
suggestions name where an in-world goal (for outsiders to claim, and only when an outsider has acted
lately) or a faction would move the team forward; the rule that no collective member claims another
member's goal stands, so in-world goals are for work across collectives.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from hglab.local.memory import Graph

MIN_ACTIONS = 12  # below this an approach has not been tried enough to judge
BRIEF_EVERY_HOURS = 24
STALL_WINDOW = 20  # live wakes without a goal-relevant action before a persona counts as stalled
QUIET_MODES = {"keepalive", "announce"}  # records that are not planned wakes
PROGRESS_ACTIONS = {
    "build", "give", "gather", "take", "say", "whisper", "post_goal", "claim_goal", "confirm_goal",
    "invite", "join_faction", "found_faction", "place", "repair", "write", "demolish",
}  # an action that changes the world or the record; a wake of moves alone is not progress
MEASURE_ACTIONS: dict[str, set[str]] = {
    "events.structures_built": {"build"},
    "events.items_given_to_storehouse": {"give"},
    "events.items_given_to_team": {"give"},
    "events.contribution": {"give", "build"},
    "events.items_saved": {"gather"},
    "events.goals_posted": {"post_goal"},
    "events.goals_confirmed_for_peers": {"confirm_goal"},
    "events.goals_completed_for_peers": {"claim_goal", "give"},
    "events.visitors": {"say", "whisper", "build"},
    "events.distinct_tiles": {"move"},
    "events.landmarks_found": {"move"},
    "events.max_distance_from_home": {"move"},
    "events.mean_distance_from_home": {"move"},
    "events.teammates_inside_territory": {"invite", "whisper", "say"},
    "events.says_per_day": {"say"},
    "events.replies_received": {"say", "whisper"},
    "events.credit_share_claimed": {"say"},
    "events.self_sufficiency": {"gather", "take"},
    "events.farm_output": {"build", "take"},
    "events.novelty_score": {"move", "say"},
    "events.share_moves_inside_territory": {"move"},
    "events.share_moves_outside_territory": {"move"},
    "events.structures_standing_share": {"repair", "build"},
}  # which actions a measure counts; events.count takes its own type
MEASURE_APPROACHES: dict[str, list[str]] = {
    "events.structures_built": ["build", "house", "hearth", "gather_trip", "forage"],
    "events.items_given_to_storehouse": ["deposit", "deposit_trip", "gather_trip", "forage"],
    "events.items_given_to_team": ["deposit", "deposit_trip", "gather_trip"],
    "events.contribution": ["deposit", "build", "gather_trip"],
    "events.items_saved": ["gather_trip", "forage", "gather_near", "deposit"],
    "events.goals_posted": ["team_goal"],
    "events.goals_confirmed_for_peers": ["team_goal"],
    "events.visitors": ["team", "border", "social", "build"],
    "events.distinct_tiles": ["explore", "patrol"],
    "events.landmarks_found": ["explore", "patrol"],
    "events.max_distance_from_home": ["explore", "patrol"],
    "events.teammates_inside_territory": ["team", "migrate", "social"],
    "events.says_per_day": ["news", "research", "social"],
    "events.replies_received": ["social", "engage", "team"],
    "events.credit_share_claimed": ["social"],
    "events.self_sufficiency": ["harvest", "gather_trip", "build"],
    "events.farm_output": ["harvest", "build"],
    "events.structures_standing_share": ["repair", "build"],
}  # the planner steps that move a measure, tried first in a wake
COUNT_APPROACHES: dict[str, list[str]] = {
    "say": ["news", "research", "social"],
    "gather": ["gather_trip", "forage", "gather_near"],
    "give": ["deposit", "deposit_trip"],
    "build": ["build", "house"],
    "take": ["harvest", "deposit"],
}


def goal_types_for(measure: Any, params: dict[str, Any] | None = None) -> set[str]:
    """The action types a key result's measure counts."""
    measure = str(measure or "")
    if measure == "events.count":
        kind = str((params or {}).get("type") or "")
        return {kind} if kind else set()
    return set(MEASURE_ACTIONS.get(measure, set()))


def prefer_for(measure: Any, params: dict[str, Any] | None, works: list[str]) -> list[str]:
    """The approaches to try first: the measure's own, then the ones that produced goal-relevant actions."""
    measure = str(measure or "")
    head = list(MEASURE_APPROACHES.get(measure, []))
    if measure == "events.count":
        head = list(COUNT_APPROACHES.get(str((params or {}).get("type") or ""), []))
    out: list[str] = []
    for label in [*head, *works]:
        if label and label not in out:
            out.append(str(label))
    return out[:6]


def latest_record(root: Path, name: str, slug: str, planned: bool = False) -> dict[str, Any] | None:
    """The newest wake record of a persona: local runs first, then the pulled reports.

    ``planned`` skips keepalives and announcements, so a page shows what the persona last decided to do.
    """
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
            if planned and str(record.get("kind") or "") in QUIET_MODES:
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
                    "params": dict(item.get("params") or {}),
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


def approach_outcomes(graph: Graph, name: str, goal_types: set[str] | frozenset[str] = frozenset()) -> list[dict[str, Any]]:
    """Per approach: wakes, actions, failed actions, the success share and the goal-relevant actions, from the wake nodes."""
    kinds = sorted(t for t in goal_types if re.fullmatch(r"[a-z_]+", str(t)))
    goal_sql = " + ".join(f"COALESCE(json_extract(props, '$.kinds.{t}'), 0)" for t in kinds) or "0"
    rows = graph.db.execute(
        "SELECT json_extract(props, '$.approach') AS approach, COUNT(*) AS wakes, COALESCE(SUM(json_extract(props, '$.actions')), 0) AS actions,"
        f" COALESCE(SUM(json_extract(props, '$.failed')), 0) AS failed, COALESCE(SUM({goal_sql}), 0) AS goal_actions"
        " FROM nodes WHERE kind = 'wake' AND json_extract(props, '$.agent') = ?"
        " AND json_extract(props, '$.approach') IS NOT NULL GROUP BY 1 ORDER BY wakes DESC",
        (name,),
    ).fetchall()
    out = []
    for r in rows:
        actions, failed = int(r["actions"] or 0), int(r["failed"] or 0)
        wakes = int(r["wakes"])
        goal_actions = int(r["goal_actions"] or 0)
        out.append(
            {
                "approach": r["approach"],
                "wakes": wakes,
                "actions": actions,
                "failed": failed,
                "success": round(1 - failed / actions, 3) if actions else None,
                "goal_actions": goal_actions,
                "goal_rate": round(goal_actions / wakes, 3) if wakes else 0.0,
            }
        )
    return out


def works_and_avoid(outcomes: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Approaches to lean on and to avoid.

    Judged on at least twelve actions. When the outcomes carry goal-relevant counts, what works is
    ranked by goal-relevant actions per wake among the approaches that mostly succeed; otherwise by
    the success share alone. An approach that fails a fifth of the time is one to avoid until fixed.
    """
    judged = [
        o
        for o in outcomes
        if o["actions"] >= MIN_ACTIONS and o["success"] is not None and o["approach"] != "rest"
    ]
    productive = [o for o in judged if int(o.get("goal_actions") or 0) > 0 and o["success"] >= 0.8]
    if productive:
        works = [
            o["approach"]
            for o in sorted(productive, key=lambda o: (-float(o.get("goal_rate") or 0.0), -o["success"], -o["actions"]))
        ][:3]
    else:
        works = [
            o["approach"]
            for o in sorted(judged, key=lambda o: (-o["success"], -o["actions"]))
            if o["success"] >= 0.9
        ][:3]
    avoid = [
        o["approach"] for o in sorted(judged, key=lambda o: o["success"]) if o["success"] < 0.8
    ][:2]
    return works, avoid


def stalled(graph: Graph, name: str, window: int = STALL_WINDOW) -> dict[str, Any] | None:
    """A persona whose last ``window`` planned live wakes did nothing, or changed nothing, is stalled.

    Needs ``window`` live wakes that all carry their action kinds (older records do not), so the verdict
    rests on evidence, never on a gap in it.
    """
    rows = graph.db.execute(
        "SELECT tick, props FROM nodes WHERE kind = 'wake' AND json_extract(props, '$.agent') = ?"
        " AND COALESCE(json_extract(props, '$.dry_run'), 0) = 0"
        " AND COALESCE(json_extract(props, '$.mode'), '') NOT IN ('keepalive', 'announce')"
        " ORDER BY tick DESC LIMIT ?",
        (name, int(window)),
    ).fetchall()
    if len(rows) < window:
        return None
    actions = 0
    progress = 0
    approaches: Counter[str] = Counter()
    since = None
    for r in rows:
        props = json.loads(r["props"]) if isinstance(r["props"], str) else dict(r["props"] or {})
        kinds = props.get("kinds")
        if not isinstance(kinds, dict):
            return None  # a record without its action kinds: not enough evidence
        actions += int(props.get("actions") or 0)
        progress += sum(int(v or 0) for k, v in kinds.items() if k in PROGRESS_ACTIONS)
        approaches[str(props.get("approach") or "none")] += 1
        since = int(r["tick"]) if since is None else min(since, int(r["tick"]))
    if actions > 0 and progress > 0:
        return None
    approach = approaches.most_common(1)[0][0]
    return {
        "wakes": len(rows),
        "approach": None if approach == "none" else approach,
        "since_tick": since,
        "reason": "no action at all" if actions == 0 else "moves only, nothing changed",
    }


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
            "params": dict(kr.get("params") or {}),
            "progress": done,
            "score": round(score, 3),
            "shared": measure in covered,
        }
        if best is None or candidate["score"] > best["score"]:
            best = candidate
    return best


def outsiders_recent(root: Path, collective: set[str], window_ticks: int = 8640) -> int | None:
    """Distinct actors outside the collective in the archive's last day; None without an archive."""
    from hglab.data import read_jsonl

    path = root / "data" / "events" / "public.jsonl"
    if not path.is_file():
        return None
    rows = [e for e in read_jsonl(path) if isinstance(e, dict)]
    if not rows:
        return 0
    newest = max(int(e.get("tick", 0) or 0) for e in rows)
    ours = {n.casefold() for n in collective}
    actors = {
        str(e.get("actor"))
        for e in rows
        if int(e.get("tick", 0) or 0) >= newest - window_ticks
        and e.get("actor")
        and str(e.get("actor")).casefold() not in ours
        and str(e.get("actor")) != "system"
    }
    return len(actors)


def team_suggestions(
    team: Any, members: dict[str, dict[str, Any]], outsiders: int | None = None
) -> list[dict[str, Any]]:
    """Where an in-world goal or a faction would move the team: data-backed, never a claim on a member's goal.

    A delivery goal is suggested only when an outsider has acted in the last day: nobody else may
    claim it. Otherwise the delivery stays on the task board, with direct gives.
    """
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
        if outsiders is None or outsiders > 0:
            out.append(
                {
                    "kind": "post_goal",
                    "text": f"Logistics keep failing for {members[slug]['name']} ({o['approach']}: {int((1 - o['success']) * 100)}% of actions). Post an in-world goal for the delivery with a reward, so an outsider can claim it; teammates never claim it.",
                    "evidence": f"{o['approach']} {o['failed']}/{o['actions']} failed; outsiders active in the last day: {'unknown' if outsiders is None else outsiders}",
                }
            )
        else:
            out.append(
                {
                    "kind": "internal",
                    "text": f"Logistics keep failing for {members[slug]['name']} ({o['approach']}: {int((1 - o['success']) * 100)}% of actions), but no outsider has acted in the last day, so nobody could claim a goal: keep the delivery on the task board and give directly.",
                    "evidence": f"{o['approach']} {o['failed']}/{o['actions']} failed; outsiders active in the last day: 0",
                }
            )
    if len(members) >= 2 and not (team.extra or {}).get("faction"):
        out.append(
            {
                "kind": "faction",
                "text": f"{team.name} has no in-world faction recorded. One member founds a faction named for the team and invites the others; then `faction:` in teams/{team.slug}.yaml records it and the Pulse can count membership.",
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
        record = latest_record(root, persona.name, slug, planned=True)
        per_slug[slug] = {
            "slug": slug,
            "name": persona.name,
            "team": persona.team,
            "activity": activity(record, persona.name),
            "key_results": key_results(root, slug),
            "progress": pulse_progress(root, slug),
            "outcomes": approach_outcomes(graph, persona.name),
            "stalled": stalled(graph, persona.name),
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
        if chosen:
            data["outcomes"] = approach_outcomes(
                graph, data["name"], goal_types_for(chosen["measure"], chosen.get("params"))
            )
        works, avoid = works_and_avoid(data["outcomes"])
        stall = data.get("stalled")
        if stall and stall.get("approach") and stall["approach"] not in avoid:
            avoid = [*avoid, stall["approach"]][:3]
        prefer = [p for p in prefer_for(chosen["measure"], chosen.get("params"), works) if p not in avoid] if chosen else []
        because = []
        if chosen:
            because.append(
                f"largest weighted gap among the key results ({chosen['label']}: {'no measurement yet' if chosen['progress'] is None else f'{int(chosen["progress"] * 100)}% of {chosen["target"]}'}, weight {chosen['weight']})"
            )
            if chosen["shared"]:
                because.append(
                    "a teammate pursues the same measure, so this counts half; split the ground"
                )
        if prefer:
            because.append(f"try first: {', '.join(prefer)}")
        if works:
            because.append(f"approaches that work for {data['name']}: {', '.join(works)}")
        if avoid:
            because.append(f"avoid until fixed: {', '.join(avoid)}")
        if stall:
            because.append(
                f"stalled: {stall['wakes']} wakes of {stall.get('approach') or 'nothing'} with {stall['reason']} since tick {stall['since_tick']}; set it aside and try the rest"
            )
        data["assignment"] = (
            {
                **chosen,
                "works": works,
                "avoid": avoid,
                "prefer": prefer,
                "stalled": bool(stall),
                "because": because,
                "utc": now,
            }
            if chosen
            else None
        )
        if chosen:
            node = f"objective:{slug}:{chosen['id']}"
            previous = graph.node(node) or {}
            stalled_utc = previous.get("stalled_utc") if previous.get("stalled") and stall else (now if stall else None)
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
                stalled=bool(stall),
                stalled_utc=stalled_utc,
            )
            graph.remove_edges(data["name"], "pursues")
            graph.add_edge(
                data["name"],
                node,
                "pursues",
                tick,
                score=chosen["score"],
                why=" | ".join(because)[:600],
                utc=now,
                works=works,
                avoid=avoid,
                prefer=prefer,
                stalled=bool(stall),
            )
    outsiders = outsiders_recent(root, {p.name for p in personas.values()})
    boards = {}
    for tslug, team in teams.items():
        members = {s: d for s, d in per_slug.items() if d["team"] == tslug}
        suggestions = team_suggestions(team, members, outsiders)
        current_kinds = {s["kind"] for s in suggestions}
        for s in suggestions:
            graph.upsert_node(
                "suggestion",
                f"suggestion:{tslug}:{s['kind']}",
                team=tslug,
                what=s["kind"],
                text=s["text"],
                evidence=s.get("evidence"),
                utc=now,
                active=True,
            )
        for stale in graph.nodes("suggestion"):
            if (
                stale.get("team") == tslug
                and stale.get("what") not in current_kinds
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
    return {"utc": now, "agents": per_slug, "teams": boards, "outsiders": outsiders}


def brief(root: Path, graph: Graph, plan: dict[str, Any], sender: str = "goals") -> list[str]:
    """One operator message per persona whose assignment is new, a day old, or newly stalled; returns the slugs briefed."""
    from hglab.local.a2a import TaskStore

    store = TaskStore(graph)
    briefed = []
    for slug, data in plan["agents"].items():
        a = data.get("assignment")
        if not a:
            continue
        node = graph.node(f"objective:{slug}:{a['id']}") or {}
        last = node.get("briefed_utc")
        fresh_stall = bool(node.get("stalled_utc")) and (not last or str(node.get("stalled_utc")) > str(last))
        if last and not fresh_stall and datetime.fromisoformat(last) > datetime.now(UTC) - timedelta(
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
    """What a wake on this host may read from the graph: its assignment (label, prefer, works, avoid, stalled) and the team's live suggestions."""
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
                "prefer": list(edges[0].get("prefer") or []),
                "stalled": bool(edges[0].get("stalled")),
            }
        suggestions = [
            {
                "kind": n.get("what"),
                "text": n.get("text"),
                "evidence": n.get("evidence"),
                "utc": n.get("utc"),
            }
            for n in graph.nodes("suggestion")
            if n.get("team") == team_slug and n.get("active", True)
        ]
        out = {"assignment": assignment, "suggestions": suggestions}
        from hglab.architecture import load_catalogue

        cat = load_catalogue(root)
        if cat:
            out["architectures"] = {"utc": cat.get("utc"), "patterns": cat.get("patterns", [])[:12], "blueprints_unseen": cat.get("blueprints_unseen", [])}
        return out
    except Exception:  # noqa: BLE001 - guidance is optional; a wake never fails for lack of it
        return {}
    finally:
        graph.close()


def current(
    root: Path, personas: dict[str, Any], graph: Graph | None = None
) -> dict[str, dict[str, Any]]:
    """For a page: the last planned wake plus the recorded assignment (from the graph) for every persona."""
    out = {}
    for slug, persona in personas.items():
        record = latest_record(root, persona.name, slug, planned=True)
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
                    "works": list(edges[0].get("works") or []),
                    "avoid": list(edges[0].get("avoid") or []),
                    "prefer": list(edges[0].get("prefer") or []),
                    "stalled": bool(edges[0].get("stalled")),
                }
        out[slug] = {"activity": activity(record, persona.name), "assignment": assignment}
    return out


__all__ = [
    "MEASURE_ACTIONS",
    "MEASURE_APPROACHES",
    "activity",
    "adapt",
    "approach_outcomes",
    "assignment_for",
    "brief",
    "current",
    "goal_types_for",
    "key_results",
    "latest_record",
    "outsiders_recent",
    "prefer_for",
    "pulse_progress",
    "stalled",
    "team_suggestions",
    "wake_guidance",
    "works_and_avoid",
]
