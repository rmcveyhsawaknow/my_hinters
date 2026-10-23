"""Architectures behind the glass: blueprints from the rules, assemblies seen in public builds, and what to recommend.

A blueprint is a structure type with a cost and a purpose (the table in the agent guide). An architecture is a
pattern of structures one builder raised close together: a hut beside a storehouse and a farm is a homestead,
a wall ring with a tower is a compound. The catalogue is built from the public event log alone (``build``
events carry actor, tile and type), so it needs no key and every claim in it points at public evidence.
``recommend`` answers "I want storage near a river" with the patterns that stood, their materials and the order
they were raised in. The R&D persona announces what is new here and writes the recommended plan on a sign.
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BLUEPRINTS: dict[str, dict[str, Any]] = {
    "sign": {
        "cost": {"wood": 1},
        "hp": 10,
        "repair": {"wood": 1},
        "where": "any walkable",
        "use": "message",
        "note": "holds text up to 200 characters that anyone in view reads",
    },
    "road": {
        "cost": {"stone": 1},
        "hp": 20,
        "repair": {"stone": 1},
        "where": "any walkable",
        "use": "route",
        "note": "move cost 0.5",
    },
    "wall": {
        "cost": {"stone": 2},
        "hp": 60,
        "repair": {"stone": 1},
        "where": "any walkable",
        "use": "enclosure",
        "note": "blocks movement for everyone but owner and faction",
    },
    "bridge": {
        "cost": {"wood": 15},
        "hp": 40,
        "repair": {"wood": 1},
        "where": "shallow water",
        "use": "crossing",
        "note": "makes the tile walkable",
    },
    "hut": {
        "cost": {"wood": 10, "fiber": 4},
        "hp": 40,
        "repair": {"wood": 1},
        "where": "any walkable",
        "use": "dwelling",
        "note": "home: 3 energy per tick instead of 2 while on or beside it",
    },
    "farm": {
        "cost": {"fiber": 5, "wood": 5},
        "hp": 30,
        "repair": {"wood": 1},
        "where": "grass",
        "use": "food",
        "note": "grows 3 berries every 30 ticks, cap 30, for the owner's three oldest farms",
    },
    "storehouse": {
        "cost": {"wood": 20, "stone": 10},
        "hp": 80,
        "repair": {"wood": 1},
        "where": "any walkable",
        "use": "storage",
        "note": "capacity 500, access by policy private, faction or public",
    },
    "tower": {
        "cost": {"stone": 30, "wood": 10},
        "hp": 100,
        "repair": {"stone": 1},
        "where": "any walkable",
        "use": "lookout",
        "note": "vision 10 while adjacent, for owner and faction",
    },
    "monument": {
        "cost": {"stone": 50, "ore": 10},
        "hp": 200,
        "repair": {"stone": 1},
        "where": "any walkable",
        "use": "prestige",
        "note": "holds text; a headline when built; needs a storehouse within reach for the 60 items",
    },
}

PIECES: dict[str, Any] = {
    "materials": {"wood": "wood", "stone": "stone", "thatch": "fiber", "metal": "ore"},
    "shapes": ["cube", "slab", "slope", "door", "window"],
    "facings": ["north", "east", "south", "west"],
    "rules": [
        "a block must reach level 0 or touch a block; cells already filled are skipped and cost nothing",
        "a tile is closed to others when it holds a block below level 6 that is not a door they may use",
        "place the door and the windows first, then the walls around them: openings cost no extra removal",
        "windows glow at night; slopes rise toward their facing and make roofs and ramps",
        "cost is 1 energy plus 1 per 32 blocks placed; materials come from the pack first, then storehouses within 1 tile",
    ],
}

PURPOSE_OF_PATTERN: list[tuple[frozenset[str], str]] = [
    (frozenset({"hut", "storehouse", "farm"}), "homestead"),
    (frozenset({"wall", "tower"}), "compound"),
    (frozenset({"hut", "farm"}), "smallholding"),
    (frozenset({"storehouse", "tower"}), "guarded storage"),
    (frozenset({"bridge", "road"}), "causeway"),
    (frozenset({"sign", "road"}), "signed route"),
    (frozenset({"hut", "storehouse"}), "home and store"),
]

BUILT = re.compile(
    r"^(?P<actor>[\w-]+) built an? (?P<type>\w+) at \((?P<x>-?\d+),\s*(?P<y>-?\d+)\)", re.IGNORECASE
)
CLUSTER_RADIUS = 3
CATALOGUE_PATH = Path("runs/local/architectures.json")


def build_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The build events, normalised: actor, type, x, y, tick."""
    out = []
    for event in events:
        if not isinstance(event, dict) or event.get("type") != "build":
            continue
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        kind = data.get("type")
        x, y = event.get("x"), event.get("y")
        if kind is None or x is None or y is None:
            match = BUILT.match(str(event.get("text") or ""))
            if not match:
                continue
            kind, x, y = (
                kind or match.group("type"),
                x if x is not None else int(match.group("x")),
                y if y is not None else int(match.group("y")),
            )
        out.append(
            {
                "actor": str(event.get("actor") or ""),
                "type": str(kind).lower(),
                "x": int(x),
                "y": int(y),
                "tick": int(event.get("tick") or 0),
                "id": event.get("id"),
            }
        )
    return sorted(out, key=lambda e: (e["tick"], e.get("id") or 0))


CONNECTORS = {"road", "sign"}
CAP_PER_TYPE = 2


def sites(builds: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One builder's structures raised within a few tiles of each other, in the order they went up.

    Roads and signs are connectors: they join the site they touch but never extend its reach, so a long
    road does not fuse every building along it into one pattern. Connectors touching nothing form their
    own small sites.
    """
    by_actor: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for b in builds:
        if b["actor"]:
            by_actor[b["actor"]].append(b)
    out: list[dict[str, Any]] = []
    for actor, items in by_actor.items():
        clusters: list[dict[str, Any]] = []

        def near(a: dict[str, Any], cluster: dict[str, Any], anchors_only: bool) -> bool:
            members = [
                m for m in cluster["structures"] if not anchors_only or m["type"] not in CONNECTORS
            ]
            return any(
                max(abs(a["x"] - m["x"]), abs(a["y"] - m["y"])) <= CLUSTER_RADIUS for m in members
            )

        for b in items:
            connector = b["type"] in CONNECTORS
            home = next((c for c in clusters if near(b, c, anchors_only=True)), None)
            if home is None and connector:
                home = next(
                    (
                        c
                        for c in clusters
                        if c["connectors_only"] and near(b, c, anchors_only=False)
                    ),
                    None,
                )
            if home is None:
                home = {"actor": actor, "structures": [], "connectors_only": connector}
                clusters.append(home)
            home["structures"].append(
                {"type": b["type"], "x": b["x"], "y": b["y"], "tick": b["tick"]}
            )
            if not connector:
                home["connectors_only"] = False
        for c in clusters:
            kinds = [s["type"] for s in c["structures"]]
            xs, ys = [s["x"] for s in c["structures"]], [s["y"] for s in c["structures"]]
            c.pop("connectors_only", None)
            c.update(
                {
                    "types": sorted(set(kinds)),
                    "order": kinds,
                    "count": len(kinds),
                    "bounds": [min(xs), min(ys), max(xs), max(ys)],
                    "first_tick": c["structures"][0]["tick"],
                    "last_tick": c["structures"][-1]["tick"],
                }
            )
            out.append(c)
    return out


def signature_of(order: list[str]) -> str:
    """The pattern name: each type at most twice, so twenty roads read as a route, not twenty patterns."""
    counts = Counter(order)
    return "+".join(
        sorted(Counter({k: min(v, CAP_PER_TYPE) for k, v in counts.items()}).elements())
    )


def compact_order(order: list[str]) -> list[str]:
    """The assembly order with runs of connectors collapsed, so it reads as steps."""
    out: list[str] = []
    for kind in order:
        if out and out[-1] == kind and kind in CONNECTORS:
            continue
        out.append(kind)
    return out[:8]


def purpose(types: list[str]) -> str:
    kinds = frozenset(types)
    for pattern, name in PURPOSE_OF_PATTERN:
        if pattern <= kinds:
            return name
    if len(kinds) == 1:
        return BLUEPRINTS.get(next(iter(kinds)), {}).get("use", "unknown")
    return " and ".join(sorted(BLUEPRINTS.get(k, {}).get("use", k) for k in kinds))


def materials_for(order: list[str]) -> dict[str, int]:
    total: Counter[str] = Counter()
    for kind in order:
        total.update(BLUEPRINTS.get(kind, {}).get("cost", {}))
    return dict(sorted(total.items()))


def catalogue(events: list[dict[str, Any]], when: datetime | None = None) -> dict[str, Any]:
    """Patterns of structures seen in public builds, with count, materials, the usual order and the purpose."""
    builds = build_events(events)
    all_sites = sites(builds)
    patterns: dict[str, dict[str, Any]] = {}
    for site in all_sites:
        key = signature_of(site["order"])
        entry = patterns.setdefault(
            key,
            {
                "signature": key,
                "types": site["types"],
                "count": 0,
                "builders": set(),
                "orders": Counter(), "full_orders": Counter(),
                "examples": [],
                "purpose": purpose(site["types"]),
            },
        )
        entry["count"] += 1
        entry["builders"].add(site["actor"])
        entry["orders"][" > ".join(compact_order(site["order"]))] += 1
        entry["full_orders"][" > ".join(site["order"])] += 1
        if len(entry["examples"]) < 3:
            entry["examples"].append(
                {
                    "at": site["bounds"][:2],
                    "first_tick": site["first_tick"],
                    "last_tick": site["last_tick"],
                }
            )
    rows = []
    for entry in patterns.values():
        order = entry["orders"].most_common(1)[0][0]
        full = entry["full_orders"].most_common(1)[0][0].split(" > ")
        rows.append(
            {
                "signature": entry["signature"],
                "types": entry["types"],
                "purpose": entry["purpose"],
                "count": entry["count"],
                "builders": len(entry["builders"]),
                "assembly_order": order.split(" > "),
                "materials": materials_for(full),
                "structures": len(full),
                "examples": entry["examples"],
            }
        )
    rows.sort(key=lambda r: (-r["count"], len(r["types"]), r["signature"]))
    unseen = sorted(k for k in BLUEPRINTS if not any(k in r["types"] for r in rows))
    return {
        "utc": (when or datetime.now(UTC)).isoformat(),
        "builds": len(builds),
        "sites": len(all_sites),
        "patterns": rows,
        "blueprints_seen": sorted({t for r in rows for t in r["types"]}),
        "blueprints_unseen": unseen,
    }


def recommend(cat: dict[str, Any], intention: str, limit: int = 3) -> list[dict[str, Any]]:
    """Architectures for a purpose: the patterns that stood most often first, then the single blueprint for it."""
    wanted = intention.strip().lower()
    hits = [
        r
        for r in cat.get("patterns", [])
        if wanted in r["purpose"]
        or any(wanted == t or wanted == BLUEPRINTS.get(t, {}).get("use") for t in r["types"])
    ]
    hits.sort(key=lambda r: (-r["count"], len(r["types"])))
    out = [
        {**r, "basis": f"stood {r['count']} time(s) by {r['builders']} builder(s)"}
        for r in hits[:limit]
    ]
    if not out:
        for kind, spec in BLUEPRINTS.items():
            if wanted in (kind, spec["use"]):
                out.append(
                    {
                        "signature": kind,
                        "types": [kind],
                        "purpose": spec["use"],
                        "count": 0,
                        "builders": 0,
                        "assembly_order": [kind],
                        "materials": dict(spec["cost"]),
                        "examples": [],
                        "basis": "the rules, untested here",
                        "note": spec["note"],
                    }
                )
    return out


def discoveries(previous: dict[str, Any] | None, current: dict[str, Any]) -> list[dict[str, Any]]:
    """Patterns in the current catalogue that the previous one did not have."""
    seen = {r["signature"] for r in (previous or {}).get("patterns", [])}
    return [r for r in current.get("patterns", []) if r["signature"] not in seen]


def finding_line(pattern: dict[str, Any]) -> str:
    """One public line about a pattern: numbers first, purpose, the usual order, no builder named."""
    materials = ", ".join(f"{q} {m}" for m, q in pattern["materials"].items()) or "no materials"
    where = pattern["examples"][0]["at"] if pattern.get("examples") else None
    at = f" near ({where[0]}, {where[1]})" if where else ""
    order = " then ".join(pattern["assembly_order"][:4])
    return f"Workshop note: {pattern['signature'].replace('+', ' + ')} for {pattern['purpose']}, seen {pattern['count']} time(s){at}: {materials}; raised {order}."[
        :240
    ]


def sign_text(recommended: dict[str, Any]) -> str:
    materials = ", ".join(f"{q} {m}" for m, q in recommended["materials"].items())
    return f"{recommended['purpose'].title()}: {' + '.join(recommended['types'])}. {materials}. Order: {' > '.join(recommended['assembly_order'][:4])}. {recommended.get('basis', '')}"[
        :200
    ]


def load_catalogue(root: Path) -> dict[str, Any] | None:
    path = root / CATALOGUE_PATH
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def save_catalogue(root: Path, cat: dict[str, Any]) -> Path:
    path = root / CATALOGUE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cat, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def refresh(root: Path, client: Any, days: int = 7) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Fetch the public log (keyless), rebuild the catalogue, save it; returns it and the new patterns."""
    collected: list[dict[str, Any]] = []
    before = None
    cutoff = None
    for _ in range(days * 40):
        page = client.public_events(before=before) if before else client.public_events()
        batch = page.get("events", []) if isinstance(page, dict) else []
        if not batch:
            break
        collected.extend(batch)
        before = page.get("next_before")
        newest = int(collected[0].get("tick", 0) or 0)
        cutoff = newest - days * 8640
        if not before or int(batch[-1].get("tick", 0) or 0) < cutoff:
            break
    previous = load_catalogue(root)
    current = catalogue(
        [e for e in collected if cutoff is None or int(e.get("tick", 0) or 0) >= cutoff]
    )
    save_catalogue(root, current)
    return current, discoveries(previous, current)


def ingest_architectures(graph: Any, cat: dict[str, Any]) -> int:
    """Patterns as ``architecture`` nodes in the memory graph, so cards, pages and wakes can read them."""
    added = 0
    for r in cat.get("patterns", []):
        graph.upsert_node(
            "architecture",
            f"architecture:{r['signature']}",
            purpose=r["purpose"],
            types=r["types"],
            count=r["count"],
            builders=r["builders"],
            assembly_order=r["assembly_order"],
            materials=r["materials"],
            utc=cat.get("utc"),
        )
        added += 1
    return added


__all__ = [
    "BLUEPRINTS",
    "CATALOGUE_PATH",
    "PIECES",
    "build_events",
    "catalogue",
    "discoveries",
    "finding_line",
    "ingest_architectures",
    "load_catalogue",
    "materials_for",
    "purpose",
    "recommend",
    "refresh",
    "save_catalogue",
    "sign_text",
    "sites",
]
