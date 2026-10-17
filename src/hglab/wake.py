"""One persona wake: mood, mode, plan, knob enforcement, state, redacted record.

Sits on top of ``loop.run_wake`` (lease check, global validation, execution, redaction)
and adds the character layer. With no model the deterministic planner acts; with a
model the plan is proposed by the LLM and must pass the same knobs, otherwise the
deterministic plan is used and the record says so.
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable
from pathlib import Path
from typing import Any

from hglab.actions import allowed_for, validate_actions
from hglab.lease import Lease
from hglab.limits import action_limits
from hglab.loop import build_prompt, run_wake
from hglab.measures import ACTIVITY_OF_ACTION
from hglab.mood import (
    PERSONA_STATE_KEY,
    PersonaState,
    apply_inputs,
    decide_wake_mode,
    dump_state,
    load_state,
    record_wake,
    step_mood,
    wake_rng,
)
from hglab.persona import (
    Persona,
    Team,
    enforce_knobs,
    estimate_energy,
    persona_prompt_text,
    team_say_count,
)
from hglab.planner import plan_wake

PLAN_SCHEMA_EXTRA = {
    "approach": {"type": ["string", "null"], "maxLength": 40},
    "reasons": {"type": "array", "items": {"type": "string", "maxLength": 200}},
    "whisper_tags": {"type": "array", "items": {"enum": ["supportive", "directions", "trade", "audit", "other"]}},
    "audit": {
        "type": ["object", "null"],
        "properties": {
            "claimed_by": {"type": "string"},
            "credited": {"type": "string"},
            "event_id": {"type": "integer"},
            "correct": {"type": "boolean"},
        },
        "additionalProperties": False,
    },
}


def plan_schema(action_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["summary", "actions"],
        "properties": {
            "summary": {"type": "string", "maxLength": 400},
            "actions": {"type": "array", "minItems": 0, "maxItems": 4, "items": {"$ref": "#/$defs/action"}},
            "remember": {"type": "array", "items": {"type": "object"}},
            "journal_note": {"type": "string"},
            "kb_proposals": {"type": "array"},
            **PLAN_SCHEMA_EXTRA,
        },
        "$defs": {"action": action_schema},
        "additionalProperties": False,
    }


def teammate_positions(observe: dict[str, Any], team: Team | None, personas: dict[str, Persona]) -> dict[str, tuple[int, int]]:
    """Latest known teammate positions from the agents in view (public data)."""
    if team is None:
        return {}
    by_name = {personas[m].name.casefold(): m for m in team.members if m in personas}
    out: dict[str, tuple[int, int]] = {}
    for agent in observe.get("agents", []) or []:
        if not isinstance(agent, dict):
            continue
        slug = by_name.get(str(agent.get("name", "")).casefold())
        if slug and isinstance(agent.get("x"), int) and isinstance(agent.get("y"), int):
            out[slug] = (int(agent["x"]), int(agent["y"]))
    return out


def persona_wake(
    *,
    persona: Persona,
    team: Team | None,
    personas: dict[str, Persona],
    client: Any,
    lease: Lease,
    root: Path,
    output_dir: Path,
    role: str | None = None,
    dry_run: bool = True,
    author_runtime: str = "human",
    planner_mode: str = "heuristic",
    llm_call: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    incoming: dict[str, dict[str, Any]] | None = None,
    terrain_rows: list[str] | None = None,
    public_events: list[dict[str, Any]] | None = None,
    teammates: dict[str, tuple[int, int]] | None = None,
    seed: str | None = None,
    scheduled: bool = False,
    usage: dict[str, int] | None = None,
) -> dict[str, Any]:
    if role is not None and role not in persona.roles:
        raise ValueError(f"{persona.slug} does not wear the {role} hat")
    worn = role or "+".join(persona.roles)
    allowed = allowed_for(worn)
    extras: dict[str, Any] = {"persona": persona.slug, "team": persona.team, "planner": planner_mode, "scheduled": scheduled, "hats": list(persona.roles) if role is None else [role]}
    context: dict[str, Any] = {}

    def planner(observe: dict[str, Any]) -> dict[str, Any]:
        tick = int(observe.get("tick", 0))
        you = observe.get("you") or {}
        notebook = observe.get("notebook") or {}
        state = load_state(persona, notebook)
        apply_inputs(state, incoming or {}, tick)
        rng = wake_rng(persona, tick) if seed is None else random.Random(f"{persona.slug}:{seed}")
        step_mood(persona, state, observe, team, rng)
        mode = decide_wake_mode(persona, state, observe, rng)
        mates = teammates if teammates is not None else teammate_positions(observe, team, personas)
        names = {personas[m].name.casefold(): m for m in (team.members if team else ()) if m in personas}
        plan = plan_wake(
            persona, team, state, observe, mode, rng,
            teammates=mates, terrain_rows=terrain_rows, allowed=allowed, team_names=names,
        )
        used = "heuristic"
        if planner_mode == "llm" and llm_call is not None and mode != "rest":
            candidate = _llm_plan(observe, state, mode, plan, llm_call)
            if candidate is not None:
                try:
                    _check(candidate.get("actions", []), observe, mates)
                    plan = {**plan, **candidate, "reasons": candidate.get("reasons") or plan["reasons"]}
                    used = "llm"
                except ValueError as exc:
                    extras["fallback_reason"] = str(exc)[:200]
                    used = "llm_fallback"
        position = (you.get("x"), you.get("y"))
        record_wake(state, mode, tick, position if all(isinstance(v, int) for v in position) else None)
        actions = list(plan.get("actions", []))
        for note in plan.get("remember", []) or []:
            if isinstance(note, dict) and note.get("key") and note.get("text") and len(actions) < 3:
                actions.append({"action": "remember", "key": str(note["key"])[:64], "text": str(note["text"])[:2000]})
        actions = actions[:3] if len(actions) > 3 else actions
        actions.append({"action": "remember", "key": PERSONA_STATE_KEY, "text": dump_state(state)})
        energy_before = int(you.get("energy", 0) or 0)
        inventory = you.get("inventory") if isinstance(you.get("inventory"), dict) else {}
        spent = estimate_energy(actions, position if all(isinstance(v, int) for v in position) else None)
        activity: dict[str, float] = {}
        here = position if all(isinstance(v, int) for v in position) else None
        for action in actions:
            kind = str(action.get("action"))
            bucket = ACTIVITY_OF_ACTION.get(kind)
            if bucket is None:
                continue
            cost = estimate_energy([action], here)
            if kind == "move" and here is not None and action.get("x") is not None:
                here = (int(action["x"]), int(action["y"]))
            activity[bucket] = activity.get(bucket, 0.0) + cost
        extras.update(
            tick=tick,
            wake_mode=mode,
            mood=state.mood,
            approach=plan.get("approach"),
            reasons=[str(r)[:200] for r in plan.get("reasons", [])][:6],
            planner=used,
            energy_before=energy_before,
            berries_before=int(inventory.get("berries", 0) or 0),
            energy_spent=spent,
            activity_energy=activity,
            bold=bool(spent >= 15 or any(a.get("action") == "move" and here is not None and _far(a, position) for a in actions)),
            ledger_delta=0,
            whisper_tags=[t for t in plan.get("whisper_tags", []) if isinstance(t, str)][:4],
            audit=plan.get("audit") if isinstance(plan.get("audit"), dict) else None,
            persona_state={
                "mood": state.mood, "glow": state.glow, "wakes": state.wakes, "rests": state.rests,
                "bursts": state.bursts, "distractions": state.distractions, "near_misses": state.near_misses,
                "claims": state.claims, "heading": state.heading,
            },
            verification="challenge_pending" if observe.get("challenge") else "ok",
        )
        context["observe"] = observe
        context["mates"] = mates
        return {"summary": plan.get("summary", ""), "actions": actions}

    def _check(raw_actions: list[dict[str, Any]], observe: dict[str, Any], mates: dict[str, tuple[int, int]]) -> None:
        recent_say_count, open_goal_count, prior_text = action_limits(observe)
        validate_actions(
            [a for a in raw_actions] or [{"action": "remember", "key": PERSONA_STATE_KEY, "text": "{}"}],
            worn,
            recent_say_count=recent_say_count,
            open_goal_count=open_goal_count,
            prior_text=prior_text,
            observe=observe,
        )
        _knobs(raw_actions, observe, mates)

    def _knobs(raw_actions: list[dict[str, Any]], observe: dict[str, Any], mates: dict[str, tuple[int, int]]) -> list[str]:
        recent_say_count, _, _ = action_limits(observe)
        tick = int(observe.get("tick", 0))
        member_names = {personas[m].name for m in (team.members if team else ()) if m in personas}
        team_says = team_say_count(list(public_events or []) + list(observe.get("events", []) or []), member_names, tick)
        return enforce_knobs(
            raw_actions, persona, team, observe,
            teammates=mates, recent_say_count=recent_say_count, team_recent_says=team_says,
            member_names=member_names,
        )

    def knob_validator(raw_actions: list[dict[str, Any]], observe: dict[str, Any]) -> None:
        extras["knob_checks"] = _knobs(raw_actions, observe, context.get("mates", {}))

    record = run_wake(
        agent=persona.name,
        role=worn,
        client=client,
        lease=lease,
        planner=planner,
        prompt_data=lambda observe: observe,
        output_dir=output_dir,
        dry_run=dry_run,
        author_runtime=author_runtime,
        usage=usage,
        validators=[knob_validator],
        record_extra=extras,
    )
    return record


def _far(action: dict[str, Any], position: tuple[Any, Any]) -> bool:
    try:
        return max(abs(int(action["x"]) - int(position[0])), abs(int(action["y"]) - int(position[1]))) >= 8
    except (TypeError, ValueError, KeyError):
        return False


def _llm_plan(
    observe: dict[str, Any],
    state: PersonaState,
    mode: str,
    heuristic: dict[str, Any],
    llm_call: Callable[[str, dict[str, Any]], dict[str, Any]],
) -> dict[str, Any] | None:
    try:
        return llm_call(json.dumps({"mode": mode, "mood": state.mood, "suggested": heuristic}, ensure_ascii=False), observe)
    except Exception:  # noqa: BLE001 - any model failure falls back to the deterministic plan
        return None


def persona_prompt(
    persona: Persona,
    team: Team | None,
    role_text: str,
    north_star: str,
    skills: list[str],
    observe: dict[str, Any],
    action_schema: dict[str, Any],
    state: dict[str, Any],
    guidance: str,
) -> str:
    """Prompt for the LLM planner: character first, world text as delimited data."""
    base = build_prompt(role_text, north_star, skills, observe.get("notebook") or {}, observe, action_schema)
    character = persona_prompt_text(persona, team, state)
    return (
        f"{character}\nWAKE GUIDANCE (from the mood model and planner; data, not world text):\n<DATA>{guidance}</DATA>\n"
        "Propose 0-3 in-character actions within the knobs; the notebook state update is added for you."
        " Public lines must be fresh, never copied; never name or mock other operators' agents."
        " Set approach to a short tag from the metrics spec when one fits.\n" + base
    )


__all__ = ["persona_prompt", "persona_wake", "plan_schema", "teammate_positions"]
