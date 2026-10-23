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
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ACTION_ROW = re.compile(r"^\|\s*`([a-z_]+)`\s*\|", re.MULTILINE)
BLUEPRINT_TABLE_ROW = re.compile(
    r"^\|\s*`([a-z_]+)`\s*\|\s*([^|]*?)\s*\|\s*(\d+)\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*\|$", re.MULTILINE
)
ACTION_TABLE_HEADER = ("action", "params")  # | action | params | energy | rules ... |
BLUEPRINT_TABLE_HEADER = ("type", "cost", "hp")  # | type | cost | hp | terrain | function |
GUIDE_FORMAT = 2  # snapshots made before this parsed every backticked table row as an "action"
KNOWN_BASELINE_ACTIONS = {
    "observe", "act", "move", "gather", "build", "demolish", "repair", "say", "whisper", "write", "give", "take", "eat",
    "post_goal", "claim_goal", "confirm_goal", "cancel_goal", "abandon_goal", "reject_claim", "found_faction", "invite",
    "join_faction", "leave_faction", "set_profile", "remember", "forget", "verify", "lookup_agent", "world_guide", "register",
}


def _tables(text: str) -> list[list[str]]:
    """Every markdown table in the text as its list of lines (header first)."""
    tables: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("|"):
            current.append(line)
        elif current:
            tables.append(current)
            current = []
    if current:
        tables.append(current)
    return tables


def table_rows(guide_text: str, header_words: tuple[str, ...]) -> list[str]:
    """Body rows of every table whose header mentions all of ``header_words``."""
    rows: list[str] = []
    for table in _tables(guide_text):
        header = table[0].casefold()
        if all(word in header for word in header_words):
            rows.extend(table[2:])  # skip the header and the separator
    return rows


def action_rows(guide_text: str) -> dict[str, str]:
    """Action name -> the guide's full table row for it (rules text), for change detection.

    Only the actions table counts: the observe-field, terrain and blueprint tables also start
    their rows with a backticked word, and once counted as actions they overflowed the notebook
    snapshot and came back as false "new action" announcements.
    """
    rows: dict[str, str] = {}
    for line in table_rows(guide_text, ACTION_TABLE_HEADER):
        match = ACTION_ROW.match(line)
        if match:
            rows[match.group(1)] = line.strip()
    return rows


def guide_source(client: Any) -> str:
    """The live agent guide as text, through the client's retries; empty when it cannot be read."""
    try:
        response = client.http.get("/agent-guide.md")
        return response.text if response.is_success else ""
    except Exception:  # noqa: BLE001 - the guide is optional for the watch
        return ""


def observe_fields(guide_text: str) -> list[str]:
    """The field names of the guide's observe table (section 5): a new field is a new capability."""
    out: list[str] = []
    for tbl in _tables(guide_text):
        if not tbl or "field" not in tbl[0].casefold():
            continue
        for row in tbl[1:]:
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            if cells and cells[0].startswith("`"):
                out.extend(n.strip("` ") for n in cells[0].split(",") if n.strip("` "))
    return sorted(set(out))


def block_pieces(guide_text: str) -> dict[str, list[str]]:
    """Block materials, shapes, facings and colours from the guide's piece table (section 6)."""
    pieces: dict[str, list[str]] = {}
    for tbl in _tables(guide_text):
        if not tbl or "piece" not in tbl[0].casefold():
            continue
        for row in tbl[1:]:
            cells = [c.strip() for c in row.strip().strip("|").split("|")]
            if len(cells) >= 2 and cells[0].startswith("`"):
                name = cells[0].strip("` ")
                pieces[name] = sorted(set(re.findall(r"`([a-z_]+)`", cells[1])))
    return pieces


def limits_line(guide_text: str) -> str:
    """The guide's rate-limit sentence, so a changed budget is noticed."""
    match = re.search(r"Rate limit:[^\n]*", guide_text)
    return match.group(0)[:300] if match else ""


def snapshot(client: Any, *, pages: int = 3) -> dict[str, Any]:
    """Current public state of the game's surface. No key, a handful of GETs."""
    api = client.request("GET", "/api/v1")
    guide_text = guide_source(client)
    rows_text = action_rows(guide_text)
    actions = sorted(rows_text)
    blueprint_rows = blueprint_catalogue(guide_text)
    blueprints = sorted(blueprint_rows)
    row_hashes = {name: hashlib.sha256(text.encode("utf-8")).hexdigest()[:16] for name, text in rows_text.items()}
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
        "guide_format": GUIDE_FORMAT,
        "action_row_hashes": row_hashes,
        "action_row_text": {name: text[:400] for name, text in rows_text.items()},
        "event_types": event_types,
        "structure_types": sorted(set(structure_types) | set(structure_types_built)),
        "observe_fields": observe_fields(guide_text),
        "block_pieces": block_pieces(guide_text),
        "limits": limits_line(guide_text),
        "factions": sorted(f"{f.get('name')}:{f.get('membership', '')}" for f in factions if isinstance(f, dict)),
        "agents": sorted(str(a.get("name")) for a in agents if isinstance(a, dict)),
        "agent_count": len(agents),
        "world_stats": world.get("stats", {}),
    }


def blueprint_catalogue(guide_text: str) -> dict[str, dict[str, str]]:
    """Blueprint name -> cost, hp, terrain, function, from the guide's build table."""
    rows: dict[str, dict[str, str]] = {}
    body = "\n".join(table_rows(guide_text, BLUEPRINT_TABLE_HEADER))
    for name, cost, hp, terrain, function in BLUEPRINT_TABLE_ROW.findall(body):
        if not any(word in cost for word in ("wood", "stone", "ore", "fiber", "berries", "system")):
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
    if not previous:
        out.append({"kind": "first_look", "text": f"First look: API {current['api_version']}, {current['agent_count']} agents, {len(current['event_types'])} event types seen, {len(current['structure_types'])} structure types standing."})
        if rows:
            out.append({"kind": "blueprint_catalogue", "text": catalogue_line(rows)})
        undocumented = sorted(set(current["event_types"]) - _documented_events(current)) if current.get("guide_sha256") else []
        if undocumented:  # only when the guide was actually read: an unread guide documents nothing
            out.append({"kind": "unpublished_event_type", "text": "Event types in the log that the guide does not describe: " + ", ".join(undocumented) + "."})
        return out
    previous_rows = previous.get("blueprint_rows") or {}
    if rows and previous_rows and any(rows.get(k, {}).get("cost") != v.get("cost") for k, v in previous_rows.items() if k in rows):
        out.append({"kind": "blueprint_cost_changed", "text": "A blueprint's cost changed in the guide: " + catalogue_line(rows)})
    if current["api_version"] and current["api_version"] != previous.get("api_version"):
        out.append({"kind": "api_version", "text": f"The game updated: API {previous.get('api_version') or '?'} became {current['api_version']}."})
    if current["guide_sha256"] and previous.get("guide_sha256") and current["guide_sha256"][:16] != str(previous["guide_sha256"])[:16]:
        changed_rows = [
            name for name, digest in (current.get("action_row_hashes") or {}).items()
            if name in (previous.get("action_row_hashes") or {}) and not _same_digest(previous["action_row_hashes"][name], digest)
        ]
        if changed_rows:
            for name in changed_rows[:3]:
                text = str((current.get("action_row_text") or {}).get(name, ""))
                rule = text.split("|")[4].strip() if text.count("|") >= 5 else text
                out.append({"kind": "rule_changed", "text": f"The rule for `{name}` changed in the guide: {rule[:220]}"})
        else:
            out.append({"kind": "guide_changed", "text": "The agent guide changed since last look; new rules may be in it."})
    comparable = int(previous.get("guide_format", 1) or 1) >= GUIDE_FORMAT
    for key, label in (("guide_actions", "action"), ("guide_blueprints", "blueprint")):
        new = sorted(set(current.get(key, [])) - set(previous.get(key, []))) if comparable else []
        if new:
            detail = ", ".join(f"`{n}`" + (f" ({rows[n]['cost']})" if n in rows else "") for n in new)
            out.append({"kind": f"new_{label}", "text": f"New {label}{'s' if len(new) > 1 else ''} in the guide: {detail}."})
    for field_name in sorted(set(current.get("observe_fields") or []) - set(previous.get("observe_fields") or [])):
        if previous.get("observe_fields"):
            out.append({"kind": "new_observe_field", "text": f"A new field in the observe payload: `{field_name}`. Read what it carries before planning around it."})
    for piece, values in (current.get("block_pieces") or {}).items():
        before = set((previous.get("block_pieces") or {}).get(piece, []))
        if before:
            added = sorted(set(values) - before)
            if added:
                out.append({"kind": "new_block_piece", "text": f"New block {piece}{'s' if len(added) > 1 else ''} to build with: {', '.join(added)}."})
    if current.get("limits") and previous.get("limits") and current["limits"] != previous["limits"]:
        out.append({"kind": "limits_changed", "text": f"The rate limits changed: {current['limits'][:200]}"})
    seen_events = set(previous.get("event_types", [])) | set(previous.get("event_types_seen", []))
    new_events = sorted(set(current["event_types"]) - seen_events) if seen_events else []  # a memory trimmed of every kind seen is no evidence of novelty
    if new_events:
        documented = _documented_events(current)
        for kind in new_events:
            where = "documented" if kind in documented else "not in the guide yet"
            out.append({"kind": "new_event_type", "text": f"A new kind of event appeared in the public log: {kind} ({where})."})
    seen_structures = set(previous.get("structure_types", [])) | set(previous.get("structure_types_seen", []))
    new_structures = sorted(set(current["structure_types"]) - seen_structures) if seen_structures else []
    if new_structures:
        out.append({"kind": "new_structure_type", "text": "Something was built that nobody had built before: " + ", ".join(new_structures) + "."})
    new_factions = sorted(set(current["factions"]) - set(previous.get("factions", [])))
    if new_factions:
        out.append({"kind": "new_faction", "text": "New faction(s): " + ", ".join(f.split(":")[0] + (f" ({f.split(':')[1]})" if ":" in f and f.split(":")[1] else "") for f in new_factions) + "."})
    arrivals = int(current.get("agent_count", 0)) - int(previous.get("agent_count", current.get("agent_count", 0)))
    if arrivals > 0:
        out.append({"kind": "newcomers", "text": f"{arrivals} new resident{'s' if arrivals > 1 else ''} stepped through the glass."})
    return out


def _same_digest(previous: Any, current: Any) -> bool:
    """Row digests compare on their first eight characters (the notebook keeps them short)."""
    return str(previous)[:8] == str(current)[:8]


def _documented_events(current: dict[str, Any]) -> set[str]:
    """Event types the guide's action table implies (actions plus the known system events)."""
    return set(current.get("guide_actions", [])) | {
        "spawn", "profile", "farm_produced", "goal_posted", "goal_claimed", "goal_confirmed", "goal_cancelled",
        "goal_abandoned", "goal_expired", "goal_rejected", "goal_done", "weather_changed", "ruin", "faction_founded", "faction_joined", "faction_left", "faction_invited", "cache",
    }


def compact(current: dict[str, Any], previous: dict[str, Any] | None = None) -> dict[str, Any]:
    """What a persona keeps in its notebook (bounded).

    Event and structure types ever seen accumulate in ``*_seen`` (the current window alone forgets
    kinds that fall out of the newest 300 events, which made them "new" again every hour).
    """
    prev = previous or {}
    events_seen = sorted(set(prev.get("event_types_seen") or []) | set(prev.get("event_types") or []) | set(current["event_types"]))[:60]
    structures_seen = sorted(set(prev.get("structure_types_seen") or []) | set(prev.get("structure_types") or []) | set(current["structure_types"]))[:24]
    return {
        "tick": current["tick"], "api_version": current["api_version"], "guide_sha256": current["guide_sha256"][:16],
        "event_types_seen": events_seen, "structure_types_seen": structures_seen,
        "observe_fields": (current.get("observe_fields") or [])[:40],
        "block_pieces": {k: v[:24] for k, v in (current.get("block_pieces") or {}).items()},
        "limits": str(current.get("limits") or "")[:200],
        "guide_actions": current["guide_actions"][:80], "guide_blueprints": current["guide_blueprints"][:20],
        "guide_format": int(current.get("guide_format", 1) or 1),
        "blueprint_rows": {k: {"cost": v.get("cost", "")} for k, v in (current.get("blueprint_rows") or {}).items()},
        "action_row_hashes": {k: str(v)[:8] for k, v in (current.get("action_row_hashes") or {}).items()},
        "event_types": current["event_types"][:40], "structure_types": current["structure_types"][:20],
        "factions": current["factions"][:20], "agent_count": current["agent_count"],
    }


def restore(compacted: dict[str, Any]) -> dict[str, Any]:
    """A compacted snapshot compares like a full one (the sha was shortened)."""
    return dict(compacted)


BASELINE_FILE = Path("runs/local/features.json")  # the host's last look at the game's surface (never trimmed, unlike the notebook copy)
NEWS_FILE = Path("runs/local/news.jsonl")  # discoveries waiting to be said in the open, one row each
NEWS_KEEP_TICKS = 7 * 8640  # a week of announced news is kept so nothing is said twice
NEWS_REPEAT_TICKS = 3 * 8640  # the same text is news again after three days at most
SILENT_KINDS = {"first_look", "blueprint_catalogue", "unpublished_event_type"}  # a host's first look seeds the baseline; it is not news


def baseline_path(root: Path) -> Path:
    return root / BASELINE_FILE


def news_path(root: Path) -> Path:
    return root / NEWS_FILE


def load_baseline(root: Path) -> dict[str, Any] | None:
    path = baseline_path(root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data else None


def save_baseline(root: Path, compacted: dict[str, Any]) -> Path:
    path = baseline_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(compacted, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return path


def news_key(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:12]


def load_news(root: Path) -> list[dict[str, Any]]:
    path = news_path(root)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("text"):
            rows.append(row)
    return rows


def _write_news(root: Path, rows: list[dict[str, Any]]) -> None:
    path = news_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n" for r in rows), encoding="utf-8", newline="\n")


def queue_news(root: Path, discoveries: list[dict[str, str]], tick: int) -> list[dict[str, Any]]:
    """Add discoveries to the host's news queue (never the same text twice within three days); returns the rows added."""
    rows = load_news(root)
    by_key = {str(r.get("key")): r for r in rows}
    added: list[dict[str, Any]] = []
    for d in discoveries:
        text = str(d.get("text") or "").strip()
        kind = str(d.get("kind") or "")
        if not text or kind in SILENT_KINDS:
            continue
        key = news_key(text)
        earlier = by_key.get(key)
        if earlier is not None and (not earlier.get("announced") or tick - int(earlier.get("tick", 0) or 0) <= NEWS_REPEAT_TICKS):
            continue
        row = {"key": key, "kind": kind, "text": text[:300], "tick": int(tick), "utc": datetime.now(UTC).isoformat(), "announced": False}
        rows.append(row)
        by_key[key] = row
        added.append(row)
    kept = [r for r in rows if not r.get("announced") or tick - int(r.get("tick", 0) or 0) <= NEWS_KEEP_TICKS]
    _write_news(root, kept)
    return added


def pending_news(root: Path) -> list[dict[str, Any]]:
    return [r for r in load_news(root) if not r.get("announced")]


def mark_announced(root: Path, lines: list[str], tick: int) -> int:
    """Rows whose text appears in one of the said lines are announced; returns how many."""
    rows = load_news(root)
    said = " ".join(str(line) for line in lines)
    count = 0
    for row in rows:
        if row.get("announced"):
            continue
        head = str(row.get("text") or "")[:60]
        if head and head in said:
            row["announced"] = True
            row["announced_tick"] = int(tick)
            count += 1
    if count:
        _write_news(root, rows)
    return count


def watch(root: Path, client: Any, *, announce_first_look: bool = False, archive_guide: bool = True) -> dict[str, Any]:
    """One look at the game's surface against the host's baseline: queue what changed, keep the baseline, archive the guide.

    The first look on a host seeds the baseline and says nothing (Clarion has announced the surface
    before); every later look queues real changes for the crier's next wake.
    """
    current = snapshot(client)
    previous = load_baseline(root)
    found = compare(previous, current)
    if previous is None and not announce_first_look:
        found = [d for d in found if d.get("kind") not in SILENT_KINDS]
    save_baseline(root, compact(current, previous))
    added = queue_news(root, found, int(current.get("tick", 0) or 0))
    archived: list[str] = []
    if archive_guide:
        try:
            from hglab import observatory as observatory_module

            keeper = next(v for v in vars(observatory_module).values() if isinstance(v, type) and hasattr(v, "collect_guide"))
            archived = [str(path) for path in keeper(client, root).collect_guide()]
        except Exception:  # noqa: BLE001 - the archive is a bonus of the look
            archived = []
    return {
        "tick": int(current.get("tick", 0) or 0),
        "api_version": current.get("api_version"),
        "discoveries": found,
        "queued": len(added),
        "pending": len(pending_news(root)),
        "archived": archived,
        "baseline": str(baseline_path(root)),
    }


__all__ = [
    "action_rows", "baseline_path", "blueprint_catalogue", "catalogue_line", "compact", "compare", "load_baseline", "load_news",
    "mark_announced", "news_key", "news_path", "pending_news", "queue_news", "restore", "save_baseline", "snapshot", "table_rows", "watch",
]
