"""Personas and teams: load, validate, and enforce character knobs.

A persona is one in-world identity with machine-readable knobs (front matter) and a
prose character bible (body). Roles stay the hats a persona wears. Global safety caps
always win over persona knobs: a knob can only make an agent more conservative.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import jsonschema
import yaml

from hglab.kb import FRONT_MATTER
from hglab.secrets import secret_name

GLOBAL_ENERGY_FLOOR = 20
GLOBAL_SAY_CAP = 3
GLOBAL_ACTIONS_CAP = 4
GLOBAL_OPEN_GOALS_CAP = 2
MOVE_STEP_CAP = 12
PERSONA_STATE_KEY = "persona_state"
ACTION_ENERGY = {
    "gather": 3, "build": 5, "demolish": 5, "say": 1, "whisper": 1, "write": 1, "give": 1,
    "take": 1, "post_goal": 2, "claim_goal": 1, "found_faction": 10,
}
KNOWN_SIGNALS = {
    "hope", "bluster", "belief", "escape", "courage", "discoveries", "audit",
}
KNOWN_EFFECTS = {
    "inspiration", "suspicion", "discernment", "glow", "resolve", "adventure_options",
}


@dataclass(frozen=True)
class Persona:
    slug: str
    name: str
    team: str
    status: str
    intent: str
    roles: tuple[str, ...]
    knobs: dict[str, Any]
    voice: dict[str, Any]
    mood_model: dict[str, Any]
    quirk: dict[str, Any]
    signals_emitted: tuple[str, ...]
    signals_received: tuple[str, ...]
    profile: dict[str, str]
    body: str
    path: Path
    success: str = ""
    inspiration: str = ""

    @property
    def secret_name(self) -> str:
        return secret_name(self.name)

    @property
    def variable_name(self) -> str:
        return "HG_AGENT_" + self.secret_name.removeprefix("HG_KEY_")

    @property
    def energy_reserve(self) -> int:
        return max(GLOBAL_ENERGY_FLOOR, int(self.knobs["energy_reserve"]))

    @property
    def actions_per_wake(self) -> int:
        return min(GLOBAL_ACTIONS_CAP, int(self.knobs["actions_per_wake"]))

    @property
    def social_rate(self) -> int:
        return min(GLOBAL_SAY_CAP, int(self.knobs["social_rate"]))

    @property
    def territory_mode(self) -> str:
        return str(self.knobs["territory"]["mode"])


@dataclass(frozen=True)
class Team:
    slug: str
    name: str
    aim: str
    members: tuple[str, ...]
    home: dict[str, Any] | None
    territory: dict[str, Any] | None
    social_budget: dict[str, int]
    links: tuple[dict[str, Any], ...]
    story: str = ""
    path: Path | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def binding_territory(self) -> dict[str, Any] | None:
        """The territory the validator enforces: only once the owner confirms it."""
        if self.territory and self.territory.get("status", "proposed") == "confirmed":
            return self.territory
        return None

    @property
    def region(self) -> dict[str, Any] | None:
        """Proposed or confirmed area used for measurement and planning pulls."""
        if self.territory:
            return self.territory
        if self.home:
            return {"kind": "circle", "x": self.home["x"], "y": self.home["y"], "radius": 10}
        return None


def _schema(root: Path, name: str) -> dict[str, Any]:
    return json.loads((root / "schemas" / f"{name}.json").read_text(encoding="utf-8"))


def _validate(instance: Any, schema: dict[str, Any]) -> None:
    jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(
        instance
    )


def persona_dir(root: Path) -> Path:
    return root / "agents"


def team_dir(root: Path) -> Path:
    return root / "teams"


def list_persona_slugs(root: Path) -> list[str]:
    folder = persona_dir(root)
    if not folder.is_dir():
        return []
    return sorted(p.parent.name for p in folder.glob("*/persona.md"))


def list_team_slugs(root: Path) -> list[str]:
    folder = team_dir(root)
    if not folder.is_dir():
        return []
    return sorted(p.stem for p in folder.glob("*.yaml"))


def parse_persona(path: Path, schema: dict[str, Any] | None = None) -> Persona:
    text = path.read_text(encoding="utf-8")
    match = FRONT_MATTER.match(text)
    if not match:
        raise ValueError(f"{path}: missing YAML front matter")
    data = yaml.safe_load(match.group(1))
    if schema is not None:
        _validate(data, schema)
    body = text[match.end():]
    return Persona(
        slug=data["slug"],
        name=data["name"],
        team=data["team"],
        status=data["status"],
        intent=data["intent"],
        roles=tuple(data["roles"]),
        knobs=data["knobs"],
        voice=data["voice"],
        mood_model=data["mood_model"],
        quirk=data["quirk"],
        signals_emitted=tuple(data.get("signals_emitted", [])),
        signals_received=tuple(data.get("signals_received", [])),
        profile=data["profile"],
        body=body,
        path=path,
        success=data.get("success", ""),
        inspiration=data.get("inspiration", ""),
    )


def load_persona(root: Path, slug: str) -> Persona:
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,30}", slug):
        raise ValueError(f"invalid persona slug: {slug}")
    path = persona_dir(root) / slug / "persona.md"
    if not path.is_file():
        raise FileNotFoundError(f"no persona for {slug}")
    persona = parse_persona(path, _schema(root, "persona"))
    if persona.slug != slug:
        raise ValueError(f"{path}: slug {persona.slug!r} does not match folder {slug!r}")
    return persona


def load_personas(root: Path) -> dict[str, Persona]:
    return {slug: load_persona(root, slug) for slug in list_persona_slugs(root)}


def persona_by_name(root: Path, name: str) -> Persona | None:
    for persona in load_personas(root).values():
        if persona.name.casefold() == name.casefold() or persona.slug == name:
            return persona
    return None


def parse_team(path: Path, schema: dict[str, Any] | None = None) -> Team:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if schema is not None:
        _validate(data, schema)
    return Team(
        slug=data["slug"],
        name=data["name"],
        aim=data["aim"],
        members=tuple(data["members"]),
        home=data.get("home"),
        territory=data.get("territory"),
        social_budget=dict(data["social_budget"]),
        links=tuple(data.get("links", [])),
        story=data.get("story", ""),
        path=path,
    )


def load_team(root: Path, slug: str) -> Team:
    if not re.fullmatch(r"[a-z][a-z0-9-]{1,30}", slug):
        raise ValueError(f"invalid team slug: {slug}")
    path = team_dir(root) / f"{slug}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"no team {slug}")
    team = parse_team(path, _schema(root, "team"))
    if team.slug != slug:
        raise ValueError(f"{path}: slug {team.slug!r} does not match file name")
    return team


def load_teams(root: Path) -> dict[str, Team]:
    return {slug: load_team(root, slug) for slug in list_team_slugs(root)}


def load_metrics(root: Path, slug: str) -> dict[str, Any]:
    path = persona_dir(root) / slug / "metrics.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"no metrics for {slug}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    _validate(data, _schema(root, "metrics"))
    if data["agent"] != slug:
        raise ValueError(f"{path}: agent {data['agent']!r} does not match folder {slug!r}")
    return data


def validate_personas(root: Path) -> list[str]:
    """Schema-check every persona, metrics spec and team, then cross-reference them."""
    errors: list[str] = []
    personas: dict[str, Persona] = {}
    teams: dict[str, Team] = {}
    known_roles = {p.stem for p in (root / "roles").glob("*.md") if p.name != "README.md"}
    for slug in list_persona_slugs(root):
        try:
            personas[slug] = load_persona(root, slug)
        except (ValueError, jsonschema.ValidationError, yaml.YAMLError, KeyError) as exc:
            errors.append(f"agents/{slug}/persona.md: {_short(exc)}")
            continue
        try:
            metrics = load_metrics(root, slug)
        except (FileNotFoundError, ValueError, jsonschema.ValidationError, yaml.YAMLError) as exc:
            errors.append(f"agents/{slug}/metrics.yaml: {_short(exc)}")
        else:
            from hglab.measures import MEASURES

            for section in ("key_results", "signatures"):
                for item in metrics[section]:
                    if item["measure"] not in MEASURES:
                        errors.append(f"agents/{slug}/metrics.yaml: unknown measure {item['measure']!r}")
            for item in metrics["approaches"]:
                measure = item.get("outcome_measure")
                if measure and measure not in MEASURES:
                    errors.append(f"agents/{slug}/metrics.yaml: unknown measure {measure!r}")
    for slug in list_team_slugs(root):
        try:
            teams[slug] = load_team(root, slug)
        except (ValueError, jsonschema.ValidationError, yaml.YAMLError, KeyError) as exc:
            errors.append(f"teams/{slug}.yaml: {_short(exc)}")
    names = [p.name.casefold() for p in personas.values()]
    if len(names) != len(set(names)):
        errors.append("agents: in-world names must be unique ignoring case")
    reserved = {"admin", "system", "hinterglass", "world"}
    for persona in personas.values():
        prefix = f"agents/{persona.slug}/persona.md"
        if persona.name.casefold() in reserved:
            errors.append(f"{prefix}: reserved in-world name")
        unknown = set(persona.roles) - known_roles
        if unknown:
            errors.append(f"{prefix}: unknown roles {sorted(unknown)}")
        if persona.team not in teams:
            errors.append(f"{prefix}: unknown team {persona.team!r}")
        elif persona.slug not in teams[persona.team].members:
            errors.append(f"{prefix}: not listed in teams/{persona.team}.yaml members")
        mix = persona.knobs["intended_mix"]
        if not math.isclose(sum(mix.values()), 1.0, abs_tol=0.011):
            errors.append(f"{prefix}: intended_mix must sum to 1 (got {sum(mix.values()):.2f})")
        mood = persona.mood_model
        if mood["initial"] not in mood["states"]:
            errors.append(f"{prefix}: mood initial state must be one of its states")
        if mood["type"] == "single_emotion" and len(mood["states"]) < 2:
            errors.append(f"{prefix}: single_emotion needs at least two states")
        for signal in persona.signals_emitted:
            if signal not in KNOWN_SIGNALS:
                errors.append(f"{prefix}: unknown emitted signal {signal!r}")
        for effect in persona.signals_received:
            if effect not in KNOWN_EFFECTS:
                errors.append(f"{prefix}: unknown received effect {effect!r}")
        route = persona.knobs.get("model_route")
        if route:
            models_path = root / "config/models.yaml"
            routes = yaml.safe_load(models_path.read_text(encoding="utf-8")).get("routes", {}) if models_path.is_file() else {}
            if route not in routes:
                errors.append(f"{prefix}: model_route {route!r} is not in config/models.yaml")
        territory = persona.knobs["territory"]
        if territory["mode"] == "near_teammate" and not territory.get("teammate"):
            errors.append(f"{prefix}: near_teammate territory needs a teammate")
        if territory.get("teammate") and territory["teammate"] not in personas:
            errors.append(f"{prefix}: territory teammate {territory['teammate']!r} is not a persona")
        if (
            territory["mode"] == "stay_inside"
            and territory.get("fallback", "near_teammate") == "near_teammate"
            and not territory.get("teammate")
        ):
            errors.append(f"{prefix}: stay_inside needs a teammate for the near_teammate fallback")
        if "story by the collective" not in persona.profile["bio"].casefold() and (
            "ongoing story" not in persona.profile["bio"].casefold()
        ):
            errors.append(f"{prefix}: profile bio must say this is a character in the collective's story")
    for team in teams.values():
        prefix = f"teams/{team.slug}.yaml"
        for member in team.members:
            if member not in personas:
                errors.append(f"{prefix}: member {member!r} has no persona")
            elif personas[member].team != team.slug:
                errors.append(f"{prefix}: member {member!r} declares team {personas[member].team!r}")
        member_rate = sum(personas[m].social_rate for m in team.members if m in personas)
        if member_rate > team.social_budget["says_per_hour"]:
            errors.append(
                f"{prefix}: member social rates ({member_rate}/h) exceed the team budget"
                f" ({team.social_budget['says_per_hour']}/h)"
            )
        for link in team.links:
            if link["from"] not in team.members or link["to"] not in team.members:
                errors.append(f"{prefix}: link {link['from']}->{link['to']} must join two members")
            if link["signal"] not in KNOWN_SIGNALS:
                errors.append(f"{prefix}: unknown link signal {link['signal']!r}")
            if link["effect"] not in KNOWN_EFFECTS:
                errors.append(f"{prefix}: unknown link effect {link['effect']!r}")
            if link["from"] in personas and link["signal"] not in personas[link["from"]].signals_emitted:
                errors.append(f"{prefix}: {link['from']} does not emit {link['signal']!r}")
            if link["to"] in personas and link["effect"] not in personas[link["to"]].signals_received:
                errors.append(f"{prefix}: {link['to']} does not receive {link['effect']!r}")
    config_path = root / "config/agents.yaml"
    if config_path.is_file() and personas:
        configured = yaml.safe_load(config_path.read_text(encoding="utf-8")).get("agents", [])
        by_persona = {item.get("persona"): item for item in configured if item.get("persona")}
        for slug, persona in personas.items():
            item = by_persona.get(slug)
            if item is None:
                errors.append(f"config/agents.yaml: no identity entry for persona {slug!r}")
            elif item["name"] != persona.name:
                errors.append(
                    f"config/agents.yaml: {slug} is named {item['name']!r}, persona says {persona.name!r}"
                )
            elif set(item["roles"]) != set(persona.roles):
                errors.append(f"config/agents.yaml: roles for {slug} differ from the persona")
    return errors


def _short(exc: Exception) -> str:
    text = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
    return text[:200]


# --- geometry -----------------------------------------------------------------


def chebyshev(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]))


def _area_center(area: dict[str, Any]) -> tuple[int, int]:
    if area["kind"] == "circle":
        return int(area["x"]), int(area["y"])
    return (int(area["x0"]) + int(area["x1"])) // 2, (int(area["y0"]) + int(area["y1"])) // 2


def _inside(area: dict[str, Any], x: int, y: int) -> bool:
    if area["kind"] == "circle":
        return chebyshev((x, y), (int(area["x"]), int(area["y"]))) <= int(area["radius"])
    return int(area["x0"]) <= x <= int(area["x1"]) and int(area["y0"]) <= y <= int(area["y1"])


def territory_center(team: Team | None) -> tuple[int, int] | None:
    """Centre of the confirmed territory, else the proposed region, else nothing."""
    if team is None:
        return None
    area = team.region
    return _area_center(area) if area else None


def in_territory(team: Team | None, x: int, y: int) -> bool | None:
    """Binding check: True/False inside a confirmed territory, None when none is confirmed."""
    if team is None or not team.binding_territory:
        return None
    return _inside(team.binding_territory, x, y)


def in_region(team: Team | None, x: int, y: int) -> bool | None:
    """Measurement check against the proposed-or-confirmed region; None when undefined."""
    if team is None or not team.region:
        return None
    return _inside(team.region, x, y)


def estimate_energy(actions: list[dict[str, Any]], position: tuple[int, int] | None) -> int:
    """Conservative energy estimate: one per tile moved, table costs for the rest."""
    total = 0
    here = position
    for action in actions:
        kind = action.get("action")
        if kind == "move" and here is not None and action.get("x") is not None:
            target = (int(action["x"]), int(action["y"]))
            total += chebyshev(here, target)
            here = target
        else:
            total += ACTION_ENERGY.get(str(kind), 0)
    return total


def team_say_count(events: list[dict[str, Any]], member_names: set[str], tick: int) -> int:
    """Count the team's public says in the last 360 ticks from an event list."""
    lowered = {name.casefold() for name in member_names}
    count = 0
    for event in events:
        if not isinstance(event, dict) or event.get("type") != "say":
            continue
        actor = str(event.get("actor", "")).casefold()
        event_tick = event.get("tick")
        if actor in lowered and isinstance(event_tick, int) and 0 <= tick - event_tick < 360:
            count += 1
    return count


def enforce_knobs(
    actions: list[dict[str, Any]],
    persona: Persona,
    team: Team | None,
    observe: dict[str, Any],
    *,
    teammates: dict[str, tuple[int, int]] | None = None,
    recent_say_count: int = 0,
    team_recent_says: int = 0,
    member_names: set[str] | None = None,
) -> list[str]:
    """Raise ValueError when a batch breaks the persona's knobs; return the checks passed.

    Global caps are enforced elsewhere by ``validate_actions``; this adds the stricter,
    per-character limits and the collective's conduct rules toward peers.
    """
    passed: list[str] = []
    you = observe.get("you") or {}
    position = (you.get("x"), you.get("y"))
    has_position = all(isinstance(v, int) for v in position)
    energy = you.get("energy")
    inventory = you.get("inventory") if isinstance(you.get("inventory"), dict) else {}
    berries = int(inventory.get("berries", 0) or 0)

    real = [
        a for a in actions
        if not (a.get("action") == "remember" and a.get("key") == PERSONA_STATE_KEY)
    ]
    if len(real) > persona.actions_per_wake:
        raise ValueError(
            f"{persona.name} takes at most {persona.actions_per_wake} action(s) per wake"
        )
    passed.append("actions_per_wake")

    says = sum(a.get("action") == "say" for a in actions)
    if says and recent_say_count + says > persona.social_rate:
        raise ValueError(f"{persona.name} says at most {persona.social_rate} time(s) per hour")
    if says and team is not None and team_recent_says + says > team.social_budget["says_per_hour"]:
        raise ValueError(
            f"team {team.slug} has used its public-speech budget"
            f" ({team.social_budget['says_per_hour']}/hour)"
        )
    max_chars = int(persona.voice.get("max_say_chars", 280))
    for action in actions:
        if action.get("action") == "say" and len(str(action.get("text", ""))) > max_chars:
            raise ValueError(f"{persona.name} keeps public lines under {max_chars} characters")
    passed.append("social_rate")

    if isinstance(energy, (int, float)):
        eaten = sum(
            min(int(a.get("qty") or berries or 0), berries)
            for a in actions
            if a.get("action") == "eat"
        )
        cost = estimate_energy(actions, position if has_position else None)
        projected = energy + 15 * eaten - cost
        reserve = persona.energy_reserve
        if cost and projected < reserve:
            if energy < reserve and berries == 0:
                home = you.get("home") or {}
                homeward = (
                    len(actions) == 1
                    and actions[0].get("action") == "move"
                    and has_position
                    and isinstance(home, dict)
                    and all(isinstance(home.get(k), int) for k in ("x", "y"))
                    and chebyshev((int(actions[0]["x"]), int(actions[0]["y"])), (home["x"], home["y"]))
                    < chebyshev(position, (home["x"], home["y"]))
                )
                if not homeward:
                    raise ValueError(
                        f"{persona.name} is below the energy reserve ({reserve}) with no berries;"
                        " rest, or take one step toward home"
                    )
            else:
                raise ValueError(
                    f"plan would leave {persona.name} at {projected} energy, below the reserve {reserve}"
                )
    passed.append("energy_reserve")

    mode = persona.territory_mode
    territory_knob = persona.knobs["territory"]
    radius = int(territory_knob.get("radius", 8))
    teammate_slug = territory_knob.get("teammate")
    anchor: tuple[int, int] | None = None
    anchor_label = ""
    if mode == "stay_inside":
        if team is not None and team.binding_territory:
            anchor_label = f"inside {team.name}"
        else:
            fallback = territory_knob.get("fallback", "near_teammate")
            if fallback == "near_teammate" and teammate_slug and teammates and teammate_slug in teammates:
                anchor = teammates[teammate_slug]
                anchor_label = f"within {radius} of {teammate_slug}"
            elif fallback in {"near_teammate", "stay_put"} and has_position:
                anchor = (int(position[0]), int(position[1]))
                anchor_label = f"within {radius} of the current position"
    elif mode == "near_teammate":
        if teammates and teammate_slug in teammates:
            anchor = teammates[teammate_slug]
            anchor_label = f"within {radius} of {teammate_slug}"
        elif has_position:
            anchor = (int(position[0]), int(position[1]))
            anchor_label = f"within {radius} of the current position"
    for action in actions:
        if action.get("action") not in {"move", "build"} or action.get("x") is None:
            continue
        target = (int(action["x"]), int(action["y"]))
        if mode == "stay_inside" and team is not None and team.binding_territory:
            if not in_territory(team, *target):
                raise ValueError(f"{persona.name} never leaves {team.name}: {target} is outside")
        elif anchor is not None and chebyshev(anchor, target) > radius:
            closing = has_position and chebyshev(anchor, target) < chebyshev(anchor, (int(position[0]), int(position[1])))
            if not (closing and action.get("action") == "move"):
                raise ValueError(f"{persona.name} stays {anchor_label}; {target} is too far")
    passed.append(f"territory:{mode}")

    structures = observe.get("structures") if isinstance(observe.get("structures"), list) else []
    team_names = {persona.name.casefold()} | {n.casefold() for n in (member_names or set())}
    for action in actions:
        if action.get("action") == "build" and action.get("type") == "wall":
            if action.get("x") is None or action.get("y") is None:
                if not has_position:
                    raise ValueError("walls need explicit coordinates")
                target = (int(position[0]), int(position[1]))
            else:
                target = (int(action["x"]), int(action["y"]))
            if in_territory(team, *target) is not True:
                raise ValueError("walls are only built inside the team's own territory")
            for structure in structures:
                owner = str(structure.get("owner", "")).casefold()
                if not owner or owner in team_names or _owner_in_team(owner, team):
                    continue
                if chebyshev(target, (int(structure["x"]), int(structure["y"]))) <= 1:
                    raise ValueError("never wall beside another agent's structure or path")
    passed.append("walls_inside_territory")
    return passed


def _owner_in_team(owner: str, team: Team | None) -> bool:
    """Dash-insensitive fallback when in-world names were not supplied (Tinkerglow ~ tinker-bell)."""
    if team is None:
        return False
    flat = owner.replace("-", "").replace("_", "")
    return any(flat == m.replace("-", "") for m in team.members)


def persona_prompt_text(persona: Persona, team: Team | None, state: dict[str, Any] | None) -> str:
    """Render the bible, knobs and current state for a planner prompt."""
    knobs = json.dumps(persona.knobs, ensure_ascii=False)
    team_text = ""
    if team is not None:
        team_text = (
            f"\nTEAM: {team.name}. Aim: {team.aim}\nMembers: {', '.join(team.members)}\n"
            f"Territory: {json.dumps(team.territory)}\nHome: {json.dumps(team.home)}\n"
        )
    state_text = json.dumps(state or {}, ensure_ascii=False)
    conduct = (
        "CONDUCT (always wins over character): toward other operators' agents stay honest; keep"
        " promises; trades and goals are truthful; never mock peers, and name one only to invite, ask or answer them; never wall across"
        " others' paths or resources; never strip nodes or take more than your share from public"
        " storehouses; respect spam caps. Vices stay in voice and in how you treat your own"
        " team's resources. Never copy song lyrics or famous dialogue; write fresh lines."
    )
    return (
        f"PERSONA: {persona.name} ({persona.slug}), team {persona.team}.\n"
        f"INTENT: {persona.intent}\nROLES (hats): {', '.join(persona.roles)}\n"
        f"KNOBS: {knobs}\nVOICE: {json.dumps(persona.voice, ensure_ascii=False)}\n"
        f"MOOD MODEL: {json.dumps(persona.mood_model, ensure_ascii=False)}\n"
        f"QUIRK: {json.dumps(persona.quirk, ensure_ascii=False)}\n"
        f"CURRENT STATE: {state_text}\n{team_text}{conduct}\n"
        f"CHARACTER BIBLE:\n{persona.body.strip()}\n"
    )


__all__ = [
    "GLOBAL_ACTIONS_CAP",
    "GLOBAL_ENERGY_FLOOR",
    "GLOBAL_SAY_CAP",
    "KNOWN_EFFECTS",
    "KNOWN_SIGNALS",
    "PERSONA_STATE_KEY",
    "Persona",
    "Team",
    "chebyshev",
    "enforce_knobs",
    "estimate_energy",
    "in_region",
    "in_territory",
    "list_persona_slugs",
    "list_team_slugs",
    "load_metrics",
    "load_persona",
    "load_personas",
    "load_team",
    "load_teams",
    "persona_by_name",
    "persona_prompt_text",
    "team_say_count",
    "territory_center",
    "validate_personas",
]
