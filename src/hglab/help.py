"""Lending a hand to another team's blueprint, and walking one's own grounds (the owner's instruction of 2026-11-03).

Every team raises its own designs first (``pipeline.blueprint``, then ``pipeline.next_blueprint``). By the owner's
instruction of 2026-11-03 nobody who can build stands idle while another team's blueprint is open: a crew hand whose
pipeline has nothing for it this wake, or a builder whose own designs are done or waiting on a deed, takes a step of
another team's blueprint instead, the nearest works first. The step is the other team's own plan (``factory.plan_step``
with ``hands=True``: any section, nearest and payable first), paid from the helper's pack and its own faction's stores,
and settled into that team's ledger like any other. The world's cap of blocks is per owner, so more hands on one
design is also more room under it.

Who helps: a persona with a ``crew`` knob, or one of its team's ``pipeline.builders`` (Tinkerglow, Plumbline). Characters
with neither keep their own ways: GrandadPail builds nothing (the owner, 2026-10-24), the fool and the crier speak, the
Navy charts. The memory graph routes idle hands here too (``hglab.local.routing``: ``help``), and the planner falls
back to it whenever the team's own pipeline yields nothing.

Roaming (``pipeline.roam: true``, Neverland): a hand with nothing to raise and nobody to help walks its team's own
grounds, one move a wake toward another of the design's sections, so the hideaway is lived in and not only built.
"""

from __future__ import annotations

from typing import Any

from hglab import factory
from hglab.factory import load_design, plan_step, root_of, team_designs

Step = tuple[list[dict[str, Any]], str, str]
ROAM_SPAN = 60  # ticks one roaming target stands before the next section is chosen


def can_help(persona: Any, team: Any) -> bool:
    """A crew hand, or one of its team's builders; characters with neither keep their own ways."""
    return isinstance(persona.knobs.get("crew"), dict) or factory.builder_sections(team, persona.slug) is not None


def _site(team: Any) -> tuple[int, int] | None:
    cfg = (getattr(team, "extra", None) or {}).get("pipeline")
    site = cfg.get("site") if isinstance(cfg, dict) else None
    if isinstance(site, dict) and isinstance(site.get("x"), int) and isinstance(site.get("y"), int):
        return int(site["x"]), int(site["y"])
    return None


def open_teams(teams: dict[str, Any], team: Any, position: tuple[int, int]) -> list[Any]:
    """The other teams whose designs are still open, the nearest works first."""
    from hglab.planner import chebyshev

    own = getattr(team, "slug", None)
    out: list[tuple[int, str, Any]] = []
    for slug, other in (teams or {}).items():
        if slug == own or not team_designs(other):
            continue
        root = root_of(other)
        if all(factory.design_complete(root, name) for name in team_designs(other)):
            continue
        site = _site(other) or (64, 64)
        out.append((chebyshev(position, site), str(slug), other))
    return [other for _d, _s, other in sorted(out, key=lambda t: (t[0], t[1]))]


def plan_help(
    persona: Any,
    team: Any,
    teams: dict[str, Any] | None,
    state: Any,
    observe: dict[str, Any],
    view: Any,
    inventory: dict[str, int],
    position: tuple[int, int],
    room: int,
    mates: set[str] | None = None,
) -> Step | None:
    """A step of another team's open blueprint for a builder with nothing of its own to raise, or None."""
    if not teams or room < 1 or not can_help(persona, team):
        return None
    for other in open_teams(teams, team, position):
        step = plan_step(persona, other, state, observe, view, inventory, position, room, mates=mates, hands=True)
        if step is not None:
            actions, why, _label = step
            return actions, f"a hand lent to {other.name}: {why}", "help"
    return None


def plan_roam(persona: Any, team: Any, state: Any, observe: dict[str, Any], view: Any, position: tuple[int, int], room: int) -> Step | None:
    """One move a wake across the team's own design (``pipeline.roam``): toward the section whose turn it is."""
    from hglab.planner import _step_toward, chebyshev

    cfg = (getattr(team, "extra", None) or {}).get("pipeline") if team is not None else None
    if not isinstance(cfg, dict) or not cfg.get("roam") or not cfg.get("blueprint") or room < 1:
        return None
    tick = int(observe.get("tick", 0) or 0)
    if getattr(state, "_roamed", None) == tick:
        return None  # one roaming step a wake: the rest of it is for anything that comes up
    try:
        design = load_design(root_of(team), str(cfg["blueprint"]))
    except (OSError, ValueError):
        return None
    sections = [s for s in design.get("sections") or [] if isinstance(s.get("tiles"), list) and len(s["tiles"]) == 4]
    if not sections:
        return None
    turn = (tick // ROAM_SPAN + sum(ord(c) for c in str(persona.slug))) % len(sections)
    for k in range(len(sections)):
        section = sections[(turn + k) % len(sections)]
        x0, y0, x1, y1 = (int(v) for v in section["tiles"])
        tiles = [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1) if (x, y) != position and view.walkable(x, y)]
        if not tiles:
            continue
        goal = min(tiles, key=lambda t: (chebyshev(position, t), t))
        if chebyshev(position, goal) <= 1 and k == 0:
            continue  # already under this one: on to the next
        target = _step_toward(position, {"x": goal[0], "y": goal[1]}, view)
        if target is not None and target != position:
            state._roamed = tick
            title = str(design.get("title") or "the blueprint")
            return [{"action": "move", "x": target[0], "y": target[1]}], f"walking {title}'s grounds: toward {section.get('name') or section.get('id')} at {goal}", "roam"
    return None


__all__ = ["ROAM_SPAN", "can_help", "open_teams", "plan_help", "plan_roam"]
