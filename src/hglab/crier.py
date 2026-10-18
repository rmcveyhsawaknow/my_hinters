"""The collector programme: bugs and feature requests as goals, themes as factions, votes as membership.

The ledger (``config/requests.yaml``) is the human-reviewed list of requests and the themes
they belong to. In the world, every open request is one escrowed goal the collector posts
under Trade & Goals, where the makers read it on the site and peers claim it to give
feedback; every theme is one open faction founded by a collective member, and membership is
the vote. An agent belongs to one faction at a time (a world rule), so the faction is its
first vote and a public line naming a second theme is its second. This module reads public
data and the collector's own observe; whispers are read only to confirm feedback and are
never written anywhere.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

from hglab.actions import allowed_for
from hglab.persona import Persona

STATE_KEY = "collector"
ASK_LIMIT = 3
CALL_SPACING_TICKS = 300  # one call per shift hour; the character wake may add its own line
OPEN_GOALS_CAP = 2
ENDORSEMENT_WINDOW_TICKS = 8640
OPENERS = ("Hear this,", "News from the glass,", "Proclamation for", "Attention,")


def load_ledger(root: Path) -> dict[str, Any]:
    """The request ledger, validated against its schema; every request names a known theme."""
    path = root / "config/requests.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    schema = json.loads((root / "schemas/requests.json").read_text(encoding="utf-8"))
    errors = sorted(Draft202012Validator(schema).iter_errors(data), key=lambda e: [str(p) for p in e.path])
    if errors:
        raise ValueError("config/requests.yaml: " + "; ".join(e.message for e in errors[:5]))
    themes = {t["name"] for t in data["themes"]}
    for request in data["requests"]:
        if request["theme"] not in themes:
            raise ValueError(f"{request['id']}: unknown theme {request['theme']!r}")
    return data


def check_ledger(ledger: dict[str, Any], personas: dict[str, Persona]) -> list[str]:
    """Problems a human should fix: hats that cannot do the duty, founders that do not exist."""
    problems: list[str] = []
    collector = personas.get(ledger["collector"])
    if collector is None:
        problems.append(f"collector {ledger['collector']} is not a persona")
    else:
        allowed = allowed_for("+".join(collector.roles))
        for action in ("post_goal", "confirm_goal", "say"):
            if action not in allowed:
                problems.append(f"collector {collector.slug} cannot {action}: add the navigator or broker hat")
    for theme in ledger["themes"]:
        founder = personas.get(theme["founder"])
        if founder is None:
            problems.append(f"theme {theme['name']}: founder {theme['founder']} is not a persona")
        elif "found_faction" not in allowed_for("+".join(founder.roles)):
            problems.append(f"theme {theme['name']}: {founder.slug} wears no hat that may found a faction")
    return problems


def duties(persona: Persona, ledger: dict[str, Any]) -> set[str]:
    """'collect' (goals, confirmations, the hourly call) and/or 'found' (one theme's open faction)."""
    out: set[str] = set()
    if persona.slug == ledger["collector"]:
        out.add("collect")
    if any(t["founder"] == persona.slug for t in ledger["themes"]):
        out.add("found")
    return out


def board(
    ledger: dict[str, Any],
    public_goals: list[dict[str, Any]],
    public_factions: list[dict[str, Any]],
    collector_name: str,
    says: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
) -> dict[str, Any]:
    """Public standing of every theme and request: faction, members, endorsements, goal status."""
    factions = {str(f.get("name", "")).casefold(): f for f in public_factions if isinstance(f, dict)}
    mine = {
        str(g.get("title", "")): g
        for g in public_goals
        if isinstance(g, dict) and str(g.get("poster", "")).casefold() == collector_name.casefold()
    }
    themes = []
    for theme in ledger["themes"]:
        faction = factions.get(theme["name"].casefold())
        members = int(faction.get("members", 0) or 0) if faction else 0
        endorsers = sorted({
            str(e.get("actor"))
            for e in says
            if isinstance(e, dict) and e.get("actor") and str(e.get("actor")) != collector_name
            and theme["name"].casefold() in str(e.get("text") or "").casefold()
        })
        themes.append({
            "name": theme["name"], "kind": theme["kind"], "founder": theme["founder"], "founded": faction is not None,
            "faction_id": faction.get("id") if faction else None, "members": members, "endorsers": endorsers,
            "votes": members + len(endorsers),
        })
    requests = []
    for request in ledger["requests"]:
        goal = mine.get(request["title"])
        requests.append({
            "id": request["id"], "kind": request["kind"], "theme": request["theme"], "title": request["title"],
            "ledger_status": request["status"], "goal_id": goal.get("id") if goal else None,
            "goal_status": goal.get("status") if goal else None, "claimant": goal.get("claimant") if goal else None,
        })
    return {"themes": themes, "requests": requests}


def render_board(b: dict[str, Any]) -> str:
    """The board as plain lines (for prompts, logs and humans)."""
    lines = []
    for t in b["themes"]:
        where = f"open faction #{t['faction_id']}, {t['members']} member(s)" if t["founded"] else "faction not founded yet"
        lines.append(f"- theme {t['name']} ({t['kind']}): {where}; {len(t['endorsers'])} public endorsement(s); {t['votes']} vote(s)")
    for r in b["requests"]:
        if r["goal_id"] is None:
            goal = "no goal posted yet" if r["ledger_status"] == "open" else r["ledger_status"]
        else:
            goal = f"goal #{r['goal_id']} {r['goal_status']}" + (f", claimed by {r['claimant']}" if r.get("claimant") else "")
        lines.append(f"- {r['kind']} {r['id']} [{r['theme']}]: {goal}")
    return "\n".join(lines)


def call_line(persona: Persona, b: dict[str, Any], names: list[str], tick: int) -> str:
    """The collector's public call: who is asked, the standing, how to vote, which goal pays."""
    opener = OPENERS[(tick // 360) % len(OPENERS)]
    who = ", ".join(names) if names else "every builder"
    standing = "; ".join(f"{t['name']} {t['votes']} vote{'s' if t['votes'] != 1 else ''}" for t in b["themes"])
    open_goals = [r for r in b["requests"] if r["goal_id"] is not None and r["goal_status"] == "open"]
    goal_part = f" Claim goal #{open_goals[0]['goal_id']} and speak your feedback to earn its reward." if open_goals else ""
    limit = int(persona.voice.get("max_say_chars", 280))
    candidates = [
        (
            f"{opener} {who}! I collect bugs and feature requests for the makers. Standing: {standing}."
            f" Join the open faction for the theme you want most (one faction each; say a second theme's name to back it too).{goal_part}"
        ),
        f"{opener} {who}! Join the open faction for the theme you back: {standing}. Say a second theme's name to back it too.{goal_part}",
        f"{opener} {who}! Join the open faction for the theme you back: {standing}.{goal_part}",
        f"{opener} {who}! Join the open faction for the theme you back: {standing}.",
    ]
    for line in candidates:
        if len(line) <= limit:
            return line
    return candidates[-1][: limit - 1].rsplit(" ", 1)[0] + "."


def plan_round(
    persona: Persona,
    ledger: dict[str, Any],
    observe: dict[str, Any],
    b: dict[str, Any],
    *,
    active_names: list[str],
    state: dict[str, Any],
    public_events: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
) -> tuple[list[dict[str, Any]], list[str], dict[str, Any]]:
    """Deterministic collector actions for one round; the caller validates and may add the state note.

    Order: found the theme faction this hat owes, post missing goals (two open at a time, rewards
    from the pack), confirm feedback on claimed goals, then the call naming agents who have not
    been asked lately. At most three actions when a call is made, so the notebook note fits.
    """
    you = observe.get("you") or {}
    tick = int(observe.get("tick", 0) or 0)
    energy = int(you.get("energy", 0) or 0)
    reserve = persona.energy_reserve
    mine = duties(persona, ledger)
    actions: list[dict[str, Any]] = []
    reasons: list[str] = []
    if "found" in mine and not you.get("faction"):
        for theme, entry in zip(ledger["themes"], b["themes"], strict=True):
            if theme["founder"] != persona.slug or entry["founded"]:
                continue
            if energy - 10 < reserve:
                reasons.append(f"theme {theme['name']}: founding costs 10 energy; not above the reserve yet")
            else:
                actions.append({"action": "found_faction", "name": theme["name"], "motto": theme["motto"], "membership": "open"})
                reasons.append(f"theme {theme['name']} needs its open faction, and that is this hat's duty")
                energy -= 10
            break
    if "collect" not in mine:
        return actions, reasons, {}
    posted = [g for g in ((observe.get("your_goals") or {}).get("posted") or []) if isinstance(g, dict)]
    live = [g for g in posted if g.get("status") in {"open", "claimed"}]
    inventory = {k: int(v) for k, v in (you.get("inventory") or {}).items()}
    room = max(0, OPEN_GOALS_CAP - len(live))
    for request, entry in zip(ledger["requests"], b["requests"], strict=True):
        if room <= 0:
            break
        if request["status"] != "open" or entry["goal_id"] is not None:
            continue
        if any(inventory.get(item, 0) < qty for item, qty in request["reward"].items()):
            reasons.append(f"{request['id']}: the reward {request['reward']} is not in the pack yet")
            continue
        if energy - 2 < reserve:
            reasons.append(f"{request['id']}: posting costs 2 energy; not above the reserve yet")
            break
        actions.append({
            "action": "post_goal", "title": request["title"], "description": request["description"],
            "reward": dict(request["reward"]), "expires_in_ticks": int(request.get("expires_in_ticks", 8640)),
        })
        reasons.append(f"{request['id']} goes under Trade and Goals, where the makers read it and peers answer it")
        for item, qty in request["reward"].items():
            inventory[item] = inventory.get(item, 0) - qty
        room -= 1
        energy -= 2
    inbox_from = {str(w.get("from")) for w in (observe.get("inbox") or []) if isinstance(w, dict)}
    spoke = {
        str(e.get("actor"))
        for e in [*list(observe.get("events") or []), *list(public_events)]
        if isinstance(e, dict) and e.get("type") == "say"
    }
    for goal in live:
        claimant = goal.get("claimant")
        if goal.get("status") == "claimed" and claimant and (str(claimant) in inbox_from or str(claimant) in spoke):
            actions.append({"action": "confirm_goal", "goal_id": int(goal["id"])})
            reasons.append(f"{claimant} answered on goal #{goal['id']}: confirming pays the feedback bounty")
    update: dict[str, Any] = {}
    last_call = int(state.get("last_call_tick", -10**9) or -10**9)
    pool = [n for n in active_names if n != persona.name]
    if pool and b["themes"] and tick - last_call >= CALL_SPACING_TICKS and len(actions) < 3:
        asked = [n for n in state.get("asked", []) if isinstance(n, str)]
        remaining = [n for n in pool if n not in asked]
        if not remaining:
            asked, remaining = [], pool
        names = remaining[:ASK_LIMIT]
        actions.append({"action": "say", "text": call_line(persona, b, names, tick)})
        reasons.append("the collector's call names agents and tells them how to vote")
        update = {"asked": (asked + names)[-60:], "last_call_tick": tick}
    return actions[:4], reasons, update


__all__ = [
    "ASK_LIMIT", "CALL_SPACING_TICKS", "STATE_KEY", "board", "call_line", "check_ledger", "duties", "load_ledger",
    "plan_round", "render_board",
]
