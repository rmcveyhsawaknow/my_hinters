"""Feature watch: what changed in Hinterglass since we last looked.

Reads only public surfaces (the API root, the live guide, the public event log, the live
world snapshot, the faction list) and compares them with the last snapshot a persona kept
in its notebook. Published changes show up as a new API version or new rows in the
guide's action and blueprint tables; unpublished ones show up first in the data: an
event type nobody documented, a structure type that was never built before, a faction
with a new membership rule. Everything here is public data and is treated as data.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

ACTION_ROW = re.compile(r"^\|\s*`([a-z_]+)`\s*\|", re.MULTILINE)
BLUEPRINT_TABLE_ROW = re.compile(
    r"^\|\s*`([a-z_]+)`\s*\|\s*([^|]*?)\s*\|\s*(\d+)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|$", re.MULTILINE
)
BLUEPRINT_ROW = re.compile(r"^\|\s*`(sign|road|wall|bridge|hut|farm|storehouse|tower|monument|cache|[a-z_]+)`\s*\|\s*(?:wood|stone|ore|fiber|berries|system|none)", re.MULTILINE)
KNOWN_BASELINE_ACTIONS = {
    "observe", "act", "move", "gather", "build", "demolish", "say", "whisper", "write", "give", "take", "eat",
    "post_goal", "claim_goal", "confirm_goal", "cancel_goal", "abandon_goal", "found_faction", "invite",
    "join_faction", "leave_faction", "set_profile", "remember", "forget", "verify", "lookup_agent", "world_guide", "register",
}


def snapshot(client: Any, *, pages: int = 3) -> dict[str, Any]:
    """Current public state of the game's surface. No key, a handful of GETs."""
    api = client.request("GET", "/api/v1")
    guide_text = ""
    try:
        import httpx

        response = httpx.get("https://hinterglass.com/agent-guide.md", timeout=18)
        if response.is_success:
            guide_text = response.text
    except Exception:  # noqa: BLE001 - the guide is optional for the watch
        guide_text = ""
    actions = sorted(set(ACTION_ROW.findall(guide_text)))
    blueprints = sorted({m for m in BLUEPRINT_ROW.findall(guide_text)})
    blueprint_rows = blueprint_catalogue(guide_text)
    events: list[dict[str, Any]] = []
    before = None
    for _ in range(pages):
        params: dict[str, Any] = {"limit": 100}
        if before is not None:
            params["before"] = before
        page = client.request("GET", "/api/v1/world/events", params=params)
        rows = page.get("events", [])
        if not rows:
            break
        events.extend(r for r in rows if isinstance(r, dict))
        before = page.get("next_before") or rows[-1].get("id")
        if before is None:
            break
    event_types = sorted({str(e.get("type")) for e in events})
    structure_types_built = sorted({str((e.get("data") or {}).get("type")) for e in events if e.get("type") == "build" and (e.get("data") or {}).get("type")})
    try:
        world = client.request("GET", "/live/world.json")
    except Exception:  # noqa: BLE001
        world = {}
    structure_types = sorted({str(s.get("type")) for s in world.get("structures", []) if isinstance(s, dict)})
    try:
        factions = client.request("GET", "/api/v1/world/factions").get("factions", [])
    except Exception:  # noqa: BLE001
        factions = []
    agents = client.request("GET", "/api/v1/world/agents").get("agents", [])
    return {
        "tick": int(api.get("tick", 0)),
        "api_version": str(api.get("version", "")),
        "guide_sha256": hashlib.sha256(guide_text.encode("utf-8")).hexdigest() if guide_text else "",
        "guide_actions": actions,
        "guide_blueprints": blueprints,
        "blueprint_rows": blueprint_rows,
        "event_types": event_types,
        "structure_types": sorted(set(structure_types) | set(structure_types_built)),
        "factions": sorted(f"{f.get('name')}:{f.get('membership', '')}" for f in factions if isinstance(f, dict)),
        "agents": sorted(str(a.get("name")) for a in agents if isinstance(a, dict)),
        "agent_count": len(agents),
        "world_stats": world.get("stats", {}),
    }


def blueprint_catalogue(guide_text: str) -> dict[str, dict[str, str]]:
    """Blueprint name -> cost, hp, terrain, function, from the guide's build table."""
    rows: dict[str, dict[str, str]] = {}
    for name, cost, hp, terrain, function in BLUEPRINT_TABLE_ROW.findall(guide_text):
        if name in {"type", "action"} or not any(word in cost for word in ("wood", "stone", "ore", "fiber", "berries", "system")):
            continue
        rows[name] = {"cost": cost.strip(), "hp": hp, "terrain": terrain.strip(), "function": function.strip()[:80]}
    return rows


def catalogue_line(rows: dict[str, dict[str, str]]) -> str:
    """One sentence listing what can be built and what it costs (system-made caches aside)."""
    parts = [f"{name} ({row['cost']})" for name, row in rows.items() if "system" not in row["cost"]]
    return f"{len(parts)} things can be built: " + ", ".join(parts) + "."


def compare(previous: dict[str, Any] | None, current: dict[str, Any]) -> list[dict[str, str]]:
    """Discoveries since the previous snapshot, each with a kind and one plain sentence."""
    out: list[dict[str, str]] = []
    rows = current.get("blueprint_rows") or {}
    if previous is None:
        out.append({"kind": "first_look", "text": f"First look: API {current['api_version']}, {current['agent_count']} agents, {len(current['event_types'])} event types seen, {len(current['structure_types'])} structure types standing."})
        if rows:
            out.append({"kind": "blueprint_catalogue", "text": catalogue_line(rows)})
        undocumented = sorted(set(current["event_types"]) - _documented_events(current))
        if undocumented:
            out.append({"kind": "unpublished_event_type", "text": "Event types in the log that the guide does not describe: " + ", ".join(undocumented) + "."})
        return out
    previous_rows = previous.get("blueprint_rows") or {}
    if rows and previous_rows and any(rows.get(k, {}).get("cost") != v.get("cost") for k, v in previous_rows.items() if k in rows):
        out.append({"kind": "blueprint_cost_changed", "text": "A blueprint's cost changed in the guide: " + catalogue_line(rows)})
    if current["api_version"] and current["api_version"] != previous.get("api_version"):
        out.append({"kind": "api_version", "text": f"The game updated: API {previous.get('api_version') or '?'} became {current['api_version']}."})
    if current["guide_sha256"] and previous.get("guide_sha256") and current["guide_sha256"][:16] != str(previous["guide_sha256"])[:16]:
        out.append({"kind": "guide_changed", "text": "The agent guide changed since last look; new rules may be in it."})
    for key, label in (("guide_actions", "action"), ("guide_blueprints", "blueprint")):
        new = sorted(set(current.get(key, [])) - set(previous.get(key, [])))
        if new:
            detail = ", ".join(f"`{n}`" + (f" ({rows[n]['cost']})" if n in rows else "") for n in new)
            out.append({"kind": f"new_{label}", "text": f"New {label}{'s' if len(new) > 1 else ''} in the guide: {detail}."})
    new_events = sorted(set(current["event_types"]) - set(previous.get("event_types", [])))
    if new_events:
        documented = _documented_events(current)
        for kind in new_events:
            where = "documented" if kind in documented else "not in the guide yet"
            out.append({"kind": "new_event_type", "text": f"A new kind of event appeared in the public log: {kind} ({where})."})
    new_structures = sorted(set(current["structure_types"]) - set(previous.get("structure_types", [])))
    if new_structures:
        out.append({"kind": "new_structure_type", "text": "Something was built that nobody had built before: " + ", ".join(new_structures) + "."})
    new_factions = sorted(set(current["factions"]) - set(previous.get("factions", [])))
    if new_factions:
        out.append({"kind": "new_faction", "text": "New faction(s): " + ", ".join(f.split(":")[0] + (f" ({f.split(':')[1]})" if ":" in f and f.split(":")[1] else "") for f in new_factions) + "."})
    newcomers = sorted(set(current["agents"]) - set(previous.get("agents", [])))
    if newcomers:
        out.append({"kind": "newcomers", "text": f"{len(newcomers)} new resident{'s' if len(newcomers) > 1 else ''} stepped through the glass."})
    return out


def _documented_events(current: dict[str, Any]) -> set[str]:
    """Event types the guide's action table implies (actions plus the known system events)."""
    return set(current.get("guide_actions", [])) | {
        "spawn", "profile", "farm_produced", "goal_posted", "goal_claimed", "goal_confirmed", "goal_cancelled",
        "goal_abandoned", "goal_expired", "faction_founded", "faction_joined", "faction_left", "faction_invited", "cache",
    }


def compact(current: dict[str, Any]) -> dict[str, Any]:
    """What a persona keeps in its notebook (bounded)."""
    return {
        "tick": current["tick"], "api_version": current["api_version"], "guide_sha256": current["guide_sha256"][:16],
        "guide_actions": current["guide_actions"][:40], "guide_blueprints": current["guide_blueprints"][:20],
        "blueprint_rows": {k: {"cost": v.get("cost", "")} for k, v in (current.get("blueprint_rows") or {}).items()},
        "event_types": current["event_types"][:40], "structure_types": current["structure_types"][:20],
        "factions": current["factions"][:20], "agents": current["agents"][:60], "agent_count": current["agent_count"],
    }


def restore(compacted: dict[str, Any]) -> dict[str, Any]:
    """A compacted snapshot compares like a full one (the sha was shortened)."""
    return dict(compacted)


__all__ = ["blueprint_catalogue", "catalogue_line", "compact", "compare", "restore", "snapshot"]
