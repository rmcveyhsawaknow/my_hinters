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
import re
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from hglab.actions import allowed_for
from hglab.lots import (
    free_lots,
    lot_anchor,
    lot_price,
    lot_value,
    site_search,
    staked_lots,
    terrain_lookup,
    total_lots,
)
from hglab.persona import Persona

LOT_ID = re.compile(r"\b([A-M][0-9]{2}-(?:NW|NE|SW|SE))\b", re.IGNORECASE)

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


def registry_text(entries: list[dict[str, Any]], ledger: dict[str, Any], b: dict[str, Any] | None = None) -> str:
    """The public profile's goals field: the registry of record and the lot market, within 500 characters."""
    item, qty = fee_item(ledger)
    market = ""
    if b and b.get("lots"):
        lots = b["lots"]
        market = f"Lots (5x5): {lots['staked']} staked, {lots['for_sale']} for sale at {lots['price']} {lots['currency']} each, {lots['free']} of {lots['total']} free in the world. "
    head = f"{market}Land registry (10x10 plots, fee {qty} {item}): "
    if not entries:
        return (head + "open; no deeds yet.")[:PROFILE_LIMIT]
    rows = [f"{e['plot']} {e['holder']}" for e in entries]
    text = head + "; ".join(rows)
    while len(text) > PROFILE_LIMIT and rows:
        rows.pop()
        text = head + "; ".join(rows) + f"; +{len(entries) - len(rows)} more"
    return text[:PROFILE_LIMIT]


def lot_market(
    ledger: dict[str, Any],
    structures: list[dict[str, Any]],
    registrar_name: str,
    sold: set[str],
    *,
    world: dict[str, Any] | None = None,
    agents: list[dict[str, Any]] | None = None,
    tick: int = 0,
) -> dict[str, Any]:
    """Free lots in the world, the office's staked lots, how many are for sale, and today's prices.

    With the public map at hand every unsold lot is priced by its worth (``lot_value``) at today's
    scarcity; the standing sale goal asks the median, and a buyer names a lot whose price they covered.
    """
    cfg = ledger.get("lots") or {}
    free = free_lots(structures)
    total = total_lots()
    staked = staked_lots(structures, registrar_name)
    unsold = [lid for lid in staked if lid not in sold]
    base, cap = int(cfg.get("base_price", 5)), int(cfg.get("price_cap", 50))
    share = len(free) / total
    flat = lot_price(share, base, cap)
    prices: dict[str, int] = {}
    tags: dict[str, list[str]] = {}
    if world and unsold:
        terrain = terrain_lookup(world)
        resources = [r for r in world.get("resources", []) if isinstance(r, dict)]
        for lid in unsold:
            value = lot_value(lid, terrain, resources, structures, list(agents or []), tick, exclude_owner=registrar_name)
            prices[lid] = lot_price(share, base, cap, value["score"])
            tags[lid] = value["tags"]
    price = sorted(prices.values())[len(prices) // 2] if prices else flat
    return {
        "total": total, "free": len(free), "free_share": round(share, 3), "staked": len(staked), "for_sale": len(unsold),
        "unsold": sorted(unsold), "sold": len(sold), "price": price, "base_price": flat, "prices": prices, "tags": tags,
        "currency": str(cfg.get("currency", "wood")),
    }


def sale_title(ledger: dict[str, Any]) -> str:
    return str((ledger.get("lots") or {}).get("sale_title", "Buy a 5x5 lot from the land office"))


def sold_lots(entries: list[dict[str, Any]]) -> set[str]:
    return {e["plot"] for e in entries if "-" in str(e["plot"])}


def deed_text(entry: dict[str, Any], registrar_name: str) -> str:
    return f"Deed {entry['plot']}: holder {entry['holder']}, registered tick {entry['tick']} by {registrar_name}. A public record, not a wall."[:SIGN_LIMIT]


def board(
    ledger: dict[str, Any],
    structures: list[dict[str, Any]],
    agents: list[dict[str, Any]],
    public_goals: list[dict[str, Any]],
    registrar_name: str,
    state: dict[str, Any] | None = None,
    *,
    world: dict[str, Any] | None = None,
    tick: int = 0,
) -> dict[str, Any]:
    """The office's public standing: survey counts, the vault, the registry, the lot market, the posted goals."""
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
    sale = next((g for g in mine if g.get("title") == sale_title(ledger) and g.get("status") in {"open", "claimed"}), None)
    offers = []
    for offer in ledger["offers"]:
        title = offer_title(offer)
        goal = next((g for g in mine if g.get("title") == title and g.get("status") in {"open", "claimed"}), None)
        offers.append({"id": offer["id"], "title": title, "status": offer.get("status", "open"), "goal_id": goal.get("id") if goal else None, "goal_status": goal.get("status") if goal else None})
    registered = registry_entries(state or {}, ledger)
    lots = lot_market(ledger, structures, registrar_name, sold_lots(registered), world=world, agents=agents, tick=tick)
    top = sorted(surveyed.items(), key=lambda kv: -kv[1]["structures"])[:5]
    sale_condition = sale.get("condition") if sale and isinstance(sale.get("condition"), dict) else {}
    return {
        "total": total, "occupied": len(surveyed), "free": total - len(surveyed), "vault": vault,
        "registration_goal": {"id": registration.get("id"), "status": registration.get("status")} if registration else None,
        "sale_goal": {"id": sale.get("id"), "status": sale.get("status"), "qty": sale_condition.get("qty")} if sale else None,
        "offers": offers, "registered": registered, "lots": lots,
        "surveys": dict((state or {}).get("surveys") or {}),
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
    lots = b.get("lots") or {}
    if lots:
        sale = b.get("sale_goal")
        lines.append(
            f"- lots: {lots['staked']} staked, {lots['for_sale']} for sale at {lots['price']} {lots['currency']} each"
            f" ({lots['free']} of {lots['total']} free in the world); sale goal {f'#{sale['id']} {sale['status']} at {sale.get('qty')}' if sale else 'not posted'}"
        )
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
    lots = b.get("lots") or {}
    if b["vault"] is None:
        line = (
            f"Land office opening: {b['occupied']} of {b['total']} plots hold structures, {b['free']} are free. The vault (a storehouse)"
            f" goes up first; registrations open at {qty} {item} once it stands. Dirt is cheap until it is not."
        )
    else:
        reg = b["registration_goal"]
        sale = b.get("sale_goal")
        line = f"Land office: {lots.get('staked', 0)} lots staked, {lots.get('for_sale', 0)} for sale at {lots.get('price')} {lots.get('currency', 'wood')} each; {lots.get('free')} of {lots.get('total')} lots still free, so the price climbs as the map fills."
        if sale:
            line += f" Buy: claim goal #{sale['id']} and give the {lots.get('currency', 'wood')} into my vault."
        if reg:
            line += f" Register your own plot for {qty} {item}: goal #{reg['id']}."
    return line if len(line) <= limit else line[: limit - 1].rsplit(" ", 1)[0] + "."


def sales_due(
    ledger: dict[str, Any],
    registrar_name: str,
    b: dict[str, Any],
    public_events: list[dict[str, Any]],
    inbox: list[dict[str, Any]],
    structures: list[dict[str, Any]],
    agents: list[dict[str, Any]],
    now_tick: int,
) -> list[dict[str, Any]]:
    """Lots paid for since the last round: each goal_done on the sale goal buys the lot the buyer named by
    whisper, else the unsold staked lot nearest their hut (or where they stand)."""
    unsold = list((b.get("lots") or {}).get("unsold", []))
    if not unsold:
        return []
    named: dict[str, str] = {}
    for w in inbox:
        if isinstance(w, dict) and w.get("from"):
            match = LOT_ID.search(str(w.get("text") or ""))
            if match:
                named[str(w["from"]).casefold()] = match.group(1).upper()
    huts = {}
    for s in structures:
        if isinstance(s, dict) and s.get("type") == "hut" and s.get("owner"):
            huts.setdefault(str(s["owner"]).casefold(), (int(s["x"]), int(s["y"])))
    positions = {str(a.get("name", "")).casefold(): (int(a["x"]), int(a["y"])) for a in agents if isinstance(a, dict) and isinstance(a.get("x"), int) and isinstance(a.get("y"), int)}
    out: list[dict[str, Any]] = []
    taken: set[str] = set()
    title = sale_title(ledger)
    for event in public_events:
        if not isinstance(event, dict) or event.get("type") != "goal_done":
            continue
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if str(data.get("poster", "")).casefold() != registrar_name.casefold() or data.get("title") != title:
            continue
        buyer = str(event.get("actor") or data.get("claimant") or "")
        if not buyer or buyer.casefold() == registrar_name.casefold():
            continue
        choice = named.get(buyer.casefold())
        if choice not in unsold or choice in taken:
            where = huts.get(buyer.casefold()) or positions.get(buyer.casefold())
            pool = [lid for lid in unsold if lid not in taken]
            if not pool:
                break
            choice = min(pool, key=lambda lid: (max(abs(lot_anchor(lid)[0] - where[0]), abs(lot_anchor(lid)[1] - where[1])) if where else 0, lid))
        taken.add(choice)
        out.append({"plot": choice, "holder": buyer, "tick": int(event.get("tick", now_tick) or now_tick), "price": data.get("delivered") or (b.get("sale_goal") or {}).get("qty")})
    return out


PAID_INTO = re.compile(r"put (\d+) (\w+) into the storehouse at \((\d+),\s*(\d+)\)", re.IGNORECASE)


def surveys_due(ledger: dict[str, Any], registrar_name: str, state: dict[str, Any], world: dict[str, Any] | None, structures: list[dict[str, Any]], agents: list[dict[str, Any]], tick: int) -> list[dict[str, Any]]:
    """Site requests in the ledger that the office has not yet surveyed: the best lot for each brief, priced."""
    requests = [r for r in (ledger.get("site_requests") or []) if isinstance(r, dict)]
    if not requests or not world:
        return []
    done = state.get("surveys") if isinstance(state.get("surveys"), dict) else {}
    cfg = ledger.get("lots") or {}
    share = len(free_lots(structures)) / total_lots()
    terrain = terrain_lookup(world)
    resources = [r for r in world.get("resources", []) if isinstance(r, dict)]
    out: list[dict[str, Any]] = []
    for request in requests:
        rid = str(request.get("id"))
        if rid in done:
            continue
        found = site_search(request, terrain, resources, structures, agents, tick, registrar=registrar_name, limit=1)
        if not found:
            continue
        best = found[0]
        price = lot_price(share, int(cfg.get("base_price", 5)), int(cfg.get("price_cap", 50)), best["score"])
        out.append({"id": rid, "client": str(request.get("client", "")), "lot": best["lot"], "anchor": best["centre"], "expandable": best["expandable"], "reasons": best["reasons"], "price": price, "tick": tick})
    return out


def survey_whisper(survey: dict[str, Any], vault: dict[str, Any] | None, currency: str) -> str:
    where = f" Put the {currency} into my storehouse at ({vault['x']},{vault['y']}); the deed follows." if vault else ""
    reasons = "; ".join(str(r) for r in survey["reasons"][:4])
    return (
        f"SITE for {survey['id']}: lot {survey['lot']}, anchor ({survey['anchor'][0]},{survey['anchor'][1]}), {len(survey['expandable'])} free lots beside it to grow into;"
        f" {reasons}; price {survey['price']} {currency}.{where}"
    )[:500]


def survey_line(survey: dict[str, Any], currency: str, limit: int) -> str:
    reasons = ", ".join(str(r) for r in survey["reasons"][:3])
    return f"Survey for {survey['client']}: lot {survey['lot']} at ({survey['anchor'][0]},{survey['anchor'][1]}), {len(survey['expandable'])} free lots beside it; {reasons}. The office asks {survey['price']} {currency}."[:limit]


def paid_deeds(state: dict[str, Any], public_events: list[dict[str, Any]], structures: list[dict[str, Any]], registrar_name: str) -> list[dict[str, Any]]:
    """Surveys whose client has put the price into the office's storehouses since the survey: their deeds."""
    surveys = state.get("surveys") if isinstance(state.get("surveys"), dict) else {}
    vaults = {(int(s["x"]), int(s["y"])) for s in structures if isinstance(s, dict) and s.get("type") == "storehouse" and str(s.get("owner", "")).casefold() == registrar_name.casefold()}
    out: list[dict[str, Any]] = []
    for rid, survey in surveys.items():
        if not isinstance(survey, dict) or survey.get("deeded") or not survey.get("client"):
            continue
        paid = 0
        for event in public_events:
            if not isinstance(event, dict) or event.get("type") != "give" or str(event.get("actor", "")).casefold() != str(survey["client"]).casefold():
                continue
            if int(event.get("tick", 0) or 0) < int(survey.get("tick", 0) or 0):
                continue
            match = PAID_INTO.search(str(event.get("text") or ""))
            if match and (int(match.group(3)), int(match.group(4))) in vaults and match.group(2).casefold() == str(survey.get("currency", "wood")).casefold():
                paid += int(match.group(1))
        if paid >= int(survey.get("price", 0) or 0):
            out.append({"id": rid, "plot": survey["lot"], "holder": survey["client"], "paid": paid, "anchor": survey.get("anchor")})
    return out


def sale_line(sales: list[dict[str, Any]], b: dict[str, Any], limit: int) -> str:
    lots = b.get("lots") or {}
    first = sales[0]
    line = f"Registry note: lot {first['plot']} sold to {first['holder']} at tick {first['tick']}"
    if len(sales) > 1:
        line += " and " + ", ".join(f"{s['plot']} to {s['holder']}" for s in sales[1:3])
    line += f". {lots.get('for_sale', 0)} lots still for sale at {lots.get('price')} {lots.get('currency', 'wood')}; {lots.get('free')} of {lots.get('total')} free in the world. The deed is public; the sign stays as the marker."
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
    world: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    """Deterministic office actions for one round; the caller validates and adds the notebook note.

    Order: deeds for paid registrations and lot sales (one public line, the profile registry, a sign
    or a rewrite when standing there), the lot sale goal at today's price (cancel and repost when the
    price moved), the registration goal, affordable offers, then the office line when nothing else
    spoke. At most three actions, so the notebook note fits the four-action cap.
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
    here = (int(you.get("x", -1)), int(you.get("y", -1)))
    grid = int(ledger.get("grid", 10))
    due = registrations_due(ledger, persona.name, b, public_events, structures, agents, collective_names, tick)
    sales = sales_due(ledger, persona.name, b, public_events, list(observe.get("inbox") or []), structures, agents, tick)
    if due or sales:
        rows = list(state.get("registered", [])) + [f"{e['plot']}:{e['holder']}:{e['tick']}" for e in due + sales]
        update["registered"] = rows[-80:]
        entries = registry_entries({"registered": rows}, ledger)
        b = {**b, "registered": entries, "lots": lot_market(ledger, structures, persona.name, sold_lots(entries))}
        line = sale_line(sales, b, limit) if sales else deed_line(due, b, limit)
        actions.append({"action": "say", "text": line})
        reasons.append("new deeds: " + ", ".join(f"{e['plot']} to {e['holder']}" for e in due + sales))
        said = True
        actions.append({"action": "set_profile", "goals": registry_text(entries, ledger, b)})
        reasons.append("the public profile carries the registry of record and today's lot price")
        for entry in due:
            if plot_id(here[0], here[1], grid) == entry["plot"] and inventory.get("wood", 0) >= 1 and energy - 5 >= reserve:
                actions.append({"action": "build", "type": "sign", "text": deed_text(entry, persona.name)})
                reasons.append(f"standing inside {entry['plot']}: the deed goes on a sign here")
                energy -= 5
                break
        for sale in sales:
            anchor = lot_anchor(sale["plot"])
            if max(abs(anchor[0] - here[0]), abs(anchor[1] - here[1])) <= 1 and len(actions) < 3:
                actions.append({"action": "write", "x": anchor[0], "y": anchor[1], "text": f"Lot {sale['plot']}: held by {sale['holder']}, bought from the land office at tick {sale['tick']}. A public record, not a wall."[:SIGN_LIMIT]})
                reasons.append(f"standing by lot {sale['plot']}: the claim sign now names its buyer")
                break
        update["last_call_tick"] = tick
    posted = [g for g in ((observe.get("your_goals") or {}).get("posted") or []) if isinstance(g, dict) and g.get("status") in {"open", "claimed"}]
    room = max(0, OPEN_GOALS_CAP - len(posted))
    vault = b["vault"]
    lots = b.get("lots") or {}
    cfg = ledger.get("lots") or {}
    # a client's site: survey once (a whisper with the lot and its price, a public line), then the deed once the price is in the vault
    currency = str(cfg.get("currency", "wood"))
    deeds = paid_deeds(state, public_events, structures, persona.name)
    if deeds and len(actions) < 3:
        surveys_state = dict(state.get("surveys") or {})
        for deed in deeds:
            surveys_state[deed["id"]] = {**surveys_state.get(deed["id"], {}), "deeded": tick}
        update["surveys"] = surveys_state
        rows = list(update.get("registered", state.get("registered", []))) + [f"{d['plot']}:{d['holder']}:{tick}" for d in deeds]
        update["registered"] = rows[-80:]
        if not said:
            d = deeds[0]
            actions.append({"action": "say", "text": f"Deed: lot {d['plot']} is {d['holder']}'s, {d['paid']} {currency} paid into the land office. Build well; the record is public."[:limit]})
            said = True
        reasons.append("deeds for surveyed sites paid in full: " + ", ".join(f"{d['plot']} to {d['holder']}" for d in deeds))
    # a client who asks again (their SURVEY REQUEST whisper is in the inbox) is answered again: the first answer may have been lost
    asked_again = {str(w.get("from", "")).casefold(): str(w.get("text", "")) for w in (observe.get("inbox") or []) if isinstance(w, dict) and "SURVEY REQUEST" in str(w.get("text", "")).upper()}
    for rid, survey in (state.get("surveys") or {}).items():
        if not isinstance(survey, dict) or survey.get("deeded") or len(actions) >= 2 or energy - 1 < reserve:
            continue
        client = str(survey.get("client", ""))
        since = tick - int(survey.get("answered", survey.get("tick", 0)) or 0)
        reminders = int(survey.get("reminders", 0) or 0)
        asked = client.casefold() in asked_again and rid.casefold() in asked_again[client.casefold()].casefold() and since >= 300
        due = reminders < 3 and since >= 720  # a whisper may have gone to a keepalive: remind every two hours, three times
        if asked or due:
            again = {"id": rid, "client": client, "lot": survey["lot"], "anchor": tuple(survey.get("anchor") or (0, 0)), "expandable": [], "reasons": [str(r) for r in survey.get("reasons", [])] or ["as surveyed"], "price": int(survey.get("price", 0) or 0)}
            actions.append({"action": "whisper", "to": client, "text": survey_whisper(again, vault, str(survey.get("currency", currency)))})
            surveys_state = dict(update.get("surveys", state.get("surveys") or {}))
            surveys_state[rid] = {**survey, "answered": tick, "reminders": reminders + (0 if asked else 1)}
            update["surveys"] = surveys_state
            reasons.append(f"{client} {'asked again for' if asked else 'has not paid for'} {rid}: the answer goes out once more")
            energy -= 1
    for survey in surveys_due(ledger, persona.name, state, world, structures, agents, tick):
        if len(actions) >= 2 or energy - 2 < reserve:
            break
        actions.append({"action": "whisper", "to": survey["client"], "text": survey_whisper(survey, vault, currency)})
        if not said:
            actions.append({"action": "say", "text": survey_line(survey, currency, limit)})
            said = True
        surveys_state = dict(update.get("surveys", state.get("surveys") or {}))
        surveys_state[survey["id"]] = {"client": survey["client"], "lot": survey["lot"], "anchor": list(survey["anchor"]), "price": survey["price"], "currency": currency, "tick": tick, "reasons": [str(r) for r in survey["reasons"][:4]]}
        update["surveys"] = surveys_state
        reasons.append(f"survey for {survey['client']}: lot {survey['lot']} ({', '.join(survey['reasons'][:3])}) at {survey['price']} {currency}")
        energy -= 2
    sale_goal = b.get("sale_goal")
    if vault and lots.get("for_sale", 0) > 0 and len(actions) < 3:
        price = int(lots["price"])
        currency = str(lots.get("currency", "wood"))
        reward = dict(cfg.get("sale_reward") or {"berries": 1})
        can_pay = all(inventory.get(i, 0) >= q for i, q in reward.items())
        if sale_goal and sale_goal.get("status") == "open" and sale_goal.get("qty") not in (None, price) and energy >= reserve:
            actions.append({"action": "cancel_goal", "goal_id": int(sale_goal["id"])})
            reasons.append(f"the lot price moved from {sale_goal.get('qty')} to {price} {currency}: the old listing comes down")
            room += 1
            sale_goal = None
        if sale_goal is None and room <= 0 and can_pay and energy >= reserve:
            open_offer = next((o for o in b["offers"] if o.get("goal_id") and o.get("goal_status") == "open"), None)
            if open_offer is not None:
                actions.append({"action": "cancel_goal", "goal_id": int(open_offer["goal_id"])})
                reasons.append(f"offer {open_offer['id']} gives its slot to the lot listing (its escrow comes back)")
                room += 1
        if sale_goal is None and room > 0 and can_pay and energy - 2 >= reserve and len(actions) < 3:
            actions.append({
                "action": "post_goal", "title": sale_title(ledger),
                "description": (
                    f"Land office sale. {lots['for_sale']} lots of 5x5 tiles are for sale from {lots.get('base_price', price)} {currency}; a lot's price is on its"
                    f" claim sign (ore, stone, water views and neighbours raise it) and all rise as free lots run out ({lots['free']} of {lots['total']} free)."
                    f" This listing asks the median, {price} {currency}. Claim this goal, then give {price} {currency} into my storehouse"
                    f" at ({vault['x']},{vault['y']}) in one give; it pays out at once. Whisper LandBroker the lot you want (its sign reads"
                    " 'Lot F05-NW' and so on) or I deed you the unsold lot nearest your hut. A 10x10 plot is four lots. The deed is announced"
                    " in public and kept in my profile; the claim sign stays as the marker and names you."
                ),
                "reward": reward, "expires_in_ticks": 8640,
                "condition": {"type": "deliver", "x": vault["x"], "y": vault["y"], "item": currency, "qty": price},
            })
            reasons.append(f"the lot listing stands in public at today's price of {price} {currency}")
            for i, q in reward.items():
                inventory[i] = inventory.get(i, 0) - q
            room -= 1
            energy -= 2
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
        reasons.append("the office line: lots staked and for sale, today's price, the fee")
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
    "lot_market",
    "offer_title",
    "office_line",
    "paid_deeds",
    "plan_round",
    "plot_bounds",
    "plot_centre",
    "plot_id",
    "registrations_due",
    "registry_entries",
    "registry_text",
    "render_board",
    "sale_line",
    "sale_title",
    "sales_due",
    "sold_lots",
    "survey",
    "survey_line",
    "survey_whisper",
    "surveys_due",
    "total_plots",
]
