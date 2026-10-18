"""The land office: survey in plots, a registry for a fee, standing offers, assets toward lending.

The world has no land rights, so the office sells what it can honestly provide: a survey of
every 10 by 10 plot from public data, a dated public registration (announced, written into
the registrar's public profile and, when the registrar passes, on a deed sign inside the
plot), standing offers that buy surplus through self-confirming goals, and a vault (the
registrar's storehouse) that fills toward lending. Fees are paid two ways: an agent outside
the collective claims the registration goal and delivers the fee into the vault (the goal
confirms itself); a collective member gives the fee into the vault directly, because the
collective never claims its own members' goals. Everything here reads public data and the
registrar's own observe; nothing private is written anywhere.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from hglab.actions import allowed_for
from hglab.persona import Persona

STATE_KEY = "land"
WORLD_SIZE = 128
COLUMNS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
CALL_SPACING_TICKS = 300
OPEN_GOALS_CAP = 2
PROFILE_LIMIT = 500
SIGN_LIMIT = 200


def plot_id(x: int, y: int, grid: int = 10) -> str:
    """Column letter by x, row number by y: (64, 63) is G06 on a 10-tile grid."""
    return f"{COLUMNS[int(x) // grid]}{int(y) // grid:02d}"


def plot_bounds(pid: str, grid: int = 10) -> tuple[int, int, int, int]:
    """Inclusive (x0, y0, x1, y1) of a plot."""
    col = COLUMNS.index(pid[0].upper())
    row = int(pid[1:])
    x0, y0 = col * grid, row * grid
    return x0, y0, min(x0 + grid - 1, WORLD_SIZE - 1), min(y0 + grid - 1, WORLD_SIZE - 1)


def plot_centre(pid: str, grid: int = 10) -> tuple[int, int]:
    x0, y0, x1, y1 = plot_bounds(pid, grid)
    return (x0 + x1) // 2, (y0 + y1) // 2


def total_plots(grid: int = 10) -> int:
    side = math.ceil(WORLD_SIZE / grid)
    return side * side


def survey(structures: list[dict[str, Any]], grid: int = 10) -> dict[str, dict[str, Any]]:
    """Plot id -> structure count, owners and the dominant holder, from the public world snapshot."""
    out: dict[str, dict[str, Any]] = {}
    for s in structures:
        if not isinstance(s, dict) or not isinstance(s.get("x"), int) or not isinstance(s.get("y"), int):
            continue
        pid = plot_id(s["x"], s["y"], grid)
        entry = out.setdefault(pid, {"structures": 0, "owners": {}})
        entry["structures"] += 1
        owner = str(s.get("owner") or "")
        if owner:
            entry["owners"][owner] = entry["owners"].get(owner, 0) + 1
    for entry in out.values():
        entry["holder"] = max(entry["owners"], key=entry["owners"].get) if entry["owners"] else None
    return out


def load_ledger(root: Path) -> dict[str, Any]:
    path = root / "config/plots.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    schema = json.loads((root / "schemas/plots.json").read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: [str(p) for p in e.path])
    if errors:
        raise ValueError("config/plots.yaml: " + "; ".join(e.message for e in errors[:5]))
    return data


def check_ledger(ledger: dict[str, Any], personas: dict[str, Persona]) -> list[str]:
    """Problems a human should fix: a registrar that does not exist or wears the wrong hats."""
    registrar = personas.get(ledger["registrar"])
    if registrar is None:
        return [f"registrar {ledger['registrar']} is not a persona"]
    allowed = allowed_for("+".join(registrar.roles))
    return [
        f"registrar {registrar.slug} cannot {action}: add the hat that may"
        for action in ("post_goal", "build", "give", "say", "set_profile", "write")
        if action not in allowed
    ]


def is_registrar(persona: Persona, ledger: dict[str, Any]) -> bool:
    return persona.slug == ledger["registrar"]


def fee_item(ledger: dict[str, Any]) -> tuple[str, int]:
    (item, qty), = ledger["fee"].items()
    return str(item), int(qty)


def registry_entries(state: dict[str, Any], ledger: dict[str, Any]) -> list[dict[str, Any]]:
    """Registered plots: the ledger's pre-registered ones, then the notebook's ``plot:holder:tick`` rows."""
    entries = [{"plot": p["id"], "holder": p["holder"], "tick": 0, "note": p.get("note", "")} for p in ledger.get("plots", [])]
    for row in state.get("registered", []) if isinstance(state.get("registered"), list) else []:
        parts = str(row).split(":")
        if len(parts) >= 2:
            entries.append({"plot": parts[0], "holder": parts[1], "tick": int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 0})
    return entries


def registry_text(entries: list[dict[str, Any]], ledger: dict[str, Any]) -> str:
    """The public profile's goals field: the registry of record, within 500 characters."""
    item, qty = fee_item(ledger)
    head = f"Land registry (10x10 plots A00-M12, fee {qty} {item} by my posted goal): "
    if not entries:
        return head + "open; no deeds yet. Deeds are announced in public and written on signs."
    rows = [f"{e['plot']} {e['holder']}" for e in entries]
    text = head + "; ".join(rows)
    while len(text) > PROFILE_LIMIT and rows:
        rows.pop()
        text = head + "; ".join(rows) + f"; +{len(entries) - len(rows)} more"
    return text[:PROFILE_LIMIT]


def deed_text(entry: dict[str, Any], registrar_name: str) -> str:
    return f"Deed {entry['plot']}: holder {entry['holder']}, registered tick {entry['tick']} by {registrar_name}. A public record, not a wall."[:SIGN_LIMIT]


def board(
    ledger: dict[str, Any],
    structures: list[dict[str, Any]],
    agents: list[dict[str, Any]],
    public_goals: list[dict[str, Any]],
    registrar_name: str,
    state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """The office's public standing: survey counts, the vault, the registry, the posted goals."""
    grid = int(ledger.get("grid", 10))
    surveyed = survey(structures, grid)
    total = total_plots(grid)
    storehouses = [
        s for s in structures
        if isinstance(s, dict) and s.get("type") == "storehouse" and str(s.get("owner", "")).casefold() == registrar_name.casefold()
    ]
    vault = {"x": int(storehouses[0]["x"]), "y": int(storehouses[0]["y"])} if storehouses else None
    mine = [g for g in public_goals if isinstance(g, dict) and str(g.get("poster", "")).casefold() == registrar_name.casefold()]
    registration = next((g for g in mine if g.get("title") == ledger["registration_title"] and g.get("status") in {"open", "claimed"}), None)
    offers = []
    for offer in ledger["offers"]:
        title = offer_title(offer)
        goal = next((g for g in mine if g.get("title") == title and g.get("status") in {"open", "claimed"}), None)
        offers.append({"id": offer["id"], "title": title, "status": offer.get("status", "open"), "goal_id": goal.get("id") if goal else None, "goal_status": goal.get("status") if goal else None})
    top = sorted(surveyed.items(), key=lambda kv: -kv[1]["structures"])[:5]
    return {
        "total": total, "occupied": len(surveyed), "free": total - len(surveyed), "vault": vault,
        "registration_goal": {"id": registration.get("id"), "status": registration.get("status")} if registration else None,
        "offers": offers, "registered": registry_entries(state or {}, ledger),
        "busiest": [{"plot": pid, "structures": e["structures"], "holder": e["holder"]} for pid, e in top],
        "agents": [{"name": a.get("name"), "plot": plot_id(a["x"], a["y"], grid)} for a in agents if isinstance(a, dict) and isinstance(a.get("x"), int) and isinstance(a.get("y"), int)],
    }


def offer_title(offer: dict[str, Any]) -> str:
    (want_item, want_qty), = offer["want"].items()
    reward = ", ".join(f"{q} {i}" for i, q in offer["reward"].items())
    return f"Offer: {reward} for {want_qty} {want_item} into the land office vault"[:80]


def render_board(b: dict[str, Any]) -> str:
    lines = [f"- plots: {b['occupied']} of {b['total']} hold structures, {b['free']} free"]
    vault = b["vault"]
    lines.append("- vault: " + (f"storehouse at ({vault['x']},{vault['y']})" if vault else "no storehouse yet"))
    reg = b["registration_goal"]
    lines.append(f"- registration goal: {'#{} {}'.format(reg['id'], reg['status']) if reg else 'not posted'}")
    for o in b["offers"]:
        lines.append(f"- offer {o['id']}: {'#{} {}'.format(o['goal_id'], o['goal_status']) if o['goal_id'] else o['status'] + ', not posted'}")
    lines.append("- registry: " + ("; ".join(f"{e['plot']} {e['holder']}" for e in b["registered"]) if b["registered"] else "no deeds yet"))
    if b["busiest"]:
        lines.append("- busiest plots: " + ", ".join(f"{x['plot']} ({x['structures']}, {x['holder']})" for x in b["busiest"]))
    return "\n".join(lines)


def registrations_due(
    ledger: dict[str, Any],
    registrar_name: str,
    b: dict[str, Any],
    public_events: list[dict[str, Any]],
    structures: list[dict[str, Any]],
    agents: list[dict[str, Any]],
    collective_names: set[str],
    now_tick: int,
) -> list[dict[str, Any]]:
    """New registrations the public log justifies: a paid registration goal, or a collective member's fee given into the vault."""
    item, qty = fee_item(ledger)
    grid = int(ledger.get("grid", 10))
    holders = {e["holder"].casefold() for e in b["registered"]}
    vault = b["vault"]
    payers: list[tuple[str, int]] = []
    for event in public_events:
        if not isinstance(event, dict):
            continue
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        actor = str(event.get("actor") or data.get("claimant") or "")
        tick = int(event.get("tick", now_tick) or now_tick)
        if event.get("type") == "goal_done" and str(data.get("poster", "")).casefold() == registrar_name.casefold() and data.get("title") == ledger["registration_title"] or (
            event.get("type") == "give" and vault and data.get("structure_type") == "storehouse"
            and int(data.get("x", event.get("x", -1)) or -1) == vault["x"] and int(data.get("y", event.get("y", -1)) or -1) == vault["y"]
            and data.get("item") == item and int(data.get("qty", 0) or 0) >= qty and actor in collective_names
        ):
            payers.append((actor, tick))
    huts = {}
    for s in structures:
        if isinstance(s, dict) and s.get("type") == "hut" and s.get("owner"):
            huts.setdefault(str(s["owner"]).casefold(), (int(s["x"]), int(s["y"])))
    positions = {str(a.get("name", "")).casefold(): (int(a["x"]), int(a["y"])) for a in agents if isinstance(a, dict) and isinstance(a.get("x"), int) and isinstance(a.get("y"), int)}
    out: list[dict[str, Any]] = []
    for name, tick in payers:
        key = name.casefold()
        if not name or key in holders or key == registrar_name.casefold():
            continue
        where = huts.get(key) or positions.get(key)
        if where is None:
            continue
        holders.add(key)
        out.append({"plot": plot_id(where[0], where[1], grid), "holder": name, "tick": tick, "at": where})
    return out


def deed_line(entries: list[dict[str, Any]], b: dict[str, Any], limit: int) -> str:
    first = entries[0]
    parts = [f"Registry note: deed {first['plot']} to {first['holder']} at tick {first['tick']}"]
    if len(entries) > 1:
        parts.append(" and " + ", ".join(f"{e['plot']} to {e['holder']}" for e in entries[1:3]) + (f" and {len(entries) - 3} more" if len(entries) > 3 else ""))
    parts.append(f". {b['free']} of {b['total']} plots still free")
    if b["registration_goal"]:
        parts.append(f"; register yours through goal #{b['registration_goal']['id']}")
    parts.append(". Ink is berry juice; the record is public.")
    line = "".join(parts)
    return line if len(line) <= limit else line[: limit - 1].rsplit(" ", 1)[0] + "."


def office_line(ledger: dict[str, Any], b: dict[str, Any], limit: int) -> str:
    item, qty = fee_item(ledger)
    if b["vault"] is None:
        line = (
            f"Land office opening: {b['occupied']} of {b['total']} plots hold structures, {b['free']} are free. The vault (a storehouse)"
            f" goes up first; registrations open at {qty} {item} once it stands. Dirt is cheap until it is not."
        )
    else:
        reg = b["registration_goal"]
        offers = [o for o in b["offers"] if o["goal_id"]]
        line = f"Land office at ({b['vault']['x']},{b['vault']['y']}): {b['occupied']} of {b['total']} plots hold structures, {b['free']} free."
        if reg:
            line += f" Register your 10x10 plot for {qty} {item}: claim goal #{reg['id']} and give the {item} into my vault."
        if offers:
            line += " Buying: " + "; ".join(f"{o['title'].removeprefix('Offer: ').split(' into')[0]} (goal #{o['goal_id']})" for o in offers[:2]) + "."
    return line if len(line) <= limit else line[: limit - 1].rsplit(" ", 1)[0] + "."


def plan_round(
    persona: Persona,
    ledger: dict[str, Any],
    observe: dict[str, Any],
    b: dict[str, Any],
    *,
    public_events: list[dict[str, Any]],
    structures: list[dict[str, Any]],
    agents: list[dict[str, Any]],
    state: dict[str, Any],
    collective_names: set[str],
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    """Deterministic office actions for one round; the caller validates and adds the notebook note.

    Order: new deeds (one public line, the profile registry, a sign when standing in the plot),
    the registration goal, affordable offers, then the office line when nothing else spoke.
    At most three actions, so the notebook note fits the four-action cap.
    """
    you = observe.get("you") or {}
    tick = int(observe.get("tick", 0) or 0)
    energy = int(you.get("energy", 0) or 0)
    reserve = persona.energy_reserve
    limit = int(persona.voice.get("max_say_chars", 280))
    inventory = {k: int(v) for k, v in (you.get("inventory") or {}).items()}
    actions: list[dict[str, Any]] = []
    reasons: list[str] = []
    update: dict[str, Any] = {}
    said = False
    if not is_registrar(persona, ledger):
        return actions, reasons, update
    due = registrations_due(ledger, persona.name, b, public_events, structures, agents, collective_names, tick)
    if due:
        rows = list(state.get("registered", [])) + [f"{e['plot']}:{e['holder']}:{e['tick']}" for e in due]
        update["registered"] = rows[-60:]
        b = {**b, "registered": registry_entries({"registered": rows}, ledger)}
        actions.append({"action": "say", "text": deed_line(due, b, limit)})
        reasons.append("new deeds: " + ", ".join(f"{e['plot']} to {e['holder']} (paid)" for e in due))
        said = True
        actions.append({"action": "set_profile", "goals": registry_text(b["registered"], ledger)})
        reasons.append("the public profile carries the registry of record")
        here = (int(you.get("x", -1)), int(you.get("y", -1)))
        grid = int(ledger.get("grid", 10))
        for entry in due:
            if plot_id(here[0], here[1], grid) == entry["plot"] and inventory.get("wood", 0) >= 1 and energy - 5 >= reserve:
                actions.append({"action": "build", "type": "sign", "text": deed_text(entry, persona.name)})
                reasons.append(f"standing inside {entry['plot']}: the deed goes on a sign here")
                energy -= 5
                break
        update["last_call_tick"] = tick
    posted = [g for g in ((observe.get("your_goals") or {}).get("posted") or []) if isinstance(g, dict) and g.get("status") in {"open", "claimed"}]
    room = max(0, OPEN_GOALS_CAP - len(posted))
    vault = b["vault"]
    if vault and b["registration_goal"] is None and room > 0 and len(actions) < 3:
        if all(inventory.get(i, 0) >= q for i, q in ledger["fee_reward"].items()) and energy - 2 >= reserve:
            item, qty = fee_item(ledger)
            actions.append({
                "action": "post_goal", "title": ledger["registration_title"],
                "description": (
                    f"Land office registration. Claim this goal, then give {qty} {item} into my storehouse at ({vault['x']},{vault['y']})"
                    f" in one give; the goal pays out at once. Your plot is the 10x10 block holding your hut (or where you stand);"
                    " whisper LandBroker to name another. The deed is announced in public, written into my profile registry and on"
                    " a sign when I pass. A registration is a dated public record and a mediator's promise, not a wall."
                ),
                "reward": dict(ledger["fee_reward"]), "expires_in_ticks": 8640,
                "condition": {"type": "deliver", "x": vault["x"], "y": vault["y"], "item": item, "qty": qty},
            })
            reasons.append("the registration offer stands in public so anyone can register while the office sleeps")
            for i, q in ledger["fee_reward"].items():
                inventory[i] = inventory.get(i, 0) - q
            room -= 1
            energy -= 2
        else:
            reasons.append("registration goal waits: the reward is not in the pack or energy is at the reserve")
    if vault:
        for offer in ledger["offers"]:
            entry = next(o for o in b["offers"] if o["id"] == offer["id"])
            if room <= 0 or len(actions) >= 3:
                break
            if offer.get("status", "open") != "open" or entry["goal_id"] is not None:
                continue
            if any(inventory.get(i, 0) < q for i, q in offer["reward"].items()) or energy - 2 < reserve:
                reasons.append(f"offer {offer['id']} waits for its reward in the pack")
                continue
            (want_item, want_qty), = offer["want"].items()
            actions.append({
                "action": "post_goal", "title": offer_title(offer),
                "description": f"Standing offer from the land office. Claim, then give {want_qty} {want_item} into my storehouse at ({vault['x']},{vault['y']}) in one give; the goal pays out at once.",
                "reward": dict(offer["reward"]), "expires_in_ticks": 8640,
                "condition": {"type": "deliver", "x": vault["x"], "y": vault["y"], "item": want_item, "qty": want_qty},
            })
            reasons.append(f"offer {offer['id']} buys surplus while the office sleeps")
            for i, q in offer["reward"].items():
                inventory[i] = inventory.get(i, 0) - q
            room -= 1
            energy -= 2
    last_call = int(state.get("last_call_tick", -10**9) or -10**9)
    if not said and tick - last_call >= CALL_SPACING_TICKS and len(actions) < 3:
        actions.append({"action": "say", "text": office_line(ledger, b, limit)})
        reasons.append("the office line: the survey count, the fee and the open offers")
        update["last_call_tick"] = tick
    return actions[:3], reasons, update


__all__ = [
    "STATE_KEY",
    "board",
    "check_ledger",
    "deed_line",
    "deed_text",
    "fee_item",
    "is_registrar",
    "load_ledger",
    "offer_title",
    "office_line",
    "plan_round",
    "plot_bounds",
    "plot_centre",
    "plot_id",
    "registrations_due",
    "registry_entries",
    "registry_text",
    "render_board",
    "survey",
    "total_plots",
]
