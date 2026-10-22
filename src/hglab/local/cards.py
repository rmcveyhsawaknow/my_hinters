"""Capability cards: a persona's A2A agent card extended with what it can do, where it reads, how it performs and how it is backed up.

The standard A2A card stays intact so any A2A client can discover and message the agent; the
``x-collective`` block carries roles (from the charters in ``roles/``), skills, tools, datasets, the
data boundary, performance by model from the memory graph, backup state, the host and a signature slot.
Cards are what a host publishes to the ecosystem index (docs/reference-architecture.md, section 4.1).
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from hglab.local.a2a import agent_card
from hglab.local.backup import host_id, latest_backup_utc
from hglab.local.memory import Graph

CARDS_DIR = Path("runs/local/cards")
LOCAL_TOOLS = [
    "hglab:memory_query",
    "hglab:contacts",
    "hglab:promises",
    "hglab:send_message",
    "hglab:performance",
]
DATASETS = ["hinterglass:world", "collective:reports", "collective:kb"]


def role_charter(root: Path, role: str) -> dict[str, Any]:
    """The front matter of ``roles/<role>.md``: mission, allowed actions, skills, outputs."""
    path = root / "roles" / f"{role}.md"
    if not path.is_file():
        return {}
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    try:
        data = yaml.safe_load(text[3:end])
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def capability_card(
    persona: Any, team: Any | None, root: Path, config: dict[str, Any], graph: Graph | None = None
) -> dict[str, Any]:
    eco = config.get("ecosystem") or {}
    card = agent_card(persona, team, f"http://127.0.0.1:{int(config.get('a2a_port', 8765))}")
    roles, skills, actions = [], set(), set()
    for role in persona.roles:
        charter = role_charter(root, role)
        roles.append(
            {
                "name": role,
                "title": charter.get("title"),
                "mission": charter.get("mission"),
                "allowed_actions": list(charter.get("allowed_actions") or []),
                "outputs": list(charter.get("outputs") or []),
            }
        )
        skills.update(charter.get("skills") or [])
        actions.update(charter.get("allowed_actions") or [])
    performance: list[dict[str, Any]] = []
    backups: dict[str, Any] = {"snapshots": 0, "latest_snapshot_utc": None}
    if graph is not None:
        performance = graph.performance(persona.name)["wakes"]
        snapshots = graph.snapshots()
        backups = {
            "snapshots": len(snapshots),
            "latest_snapshot_utc": snapshots[0]["utc"] if snapshots else None,
        }
    backups["latest_backup_utc"] = latest_backup_utc(root, config)
    card["x-collective"] = {
        "slug": persona.slug,
        "team": persona.team,
        "host": host_id(config),
        "runtime": "hglab-local",
        "data_boundary": str(eco.get("data_boundary", "internal")),
        "roles": roles,
        "skills": sorted(skills),
        "tools": [f"hinterglass:{a}" for a in sorted(actions)] + LOCAL_TOOLS,
        "datasets": list(DATASETS),
        "performance": performance,
        "backups": backups,
        "published_utc": datetime.now(UTC).isoformat(),
        "signature": None,
    }
    return card


def all_cards(
    root: Path, personas: dict[str, Any], teams: dict[str, Any], config: dict[str, Any]
) -> dict[str, dict[str, Any]]:
    graph_path = root / "runs/local/memory.sqlite"
    graph = Graph(graph_path) if graph_path.is_file() else None
    try:
        return {
            slug: capability_card(p, teams.get(p.team), root, config, graph)
            for slug, p in sorted(personas.items())
        }
    finally:
        if graph is not None:
            graph.close()


def write_cards(
    root: Path, personas: dict[str, Any], teams: dict[str, Any], config: dict[str, Any]
) -> list[Path]:
    folder = root / CARDS_DIR
    folder.mkdir(parents=True, exist_ok=True)
    written = []
    for slug, card in all_cards(root, personas, teams, config).items():
        path = folder / f"{slug}.json"
        path.write_text(json.dumps(card, ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(path)
    return written


__all__ = [
    "CARDS_DIR",
    "DATASETS",
    "LOCAL_TOOLS",
    "all_cards",
    "capability_card",
    "role_charter",
    "write_cards",
]
