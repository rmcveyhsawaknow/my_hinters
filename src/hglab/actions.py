"""Action validation shared by every runtime."""

from __future__ import annotations

import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

ACTION_TEXT_LIMITS = {"say": 280, "whisper": 500, "write": 200, "remember": 2000}
COMMON_ACTIONS = {
    "move", "gather", "build", "demolish", "repair", "say", "whisper", "write", "give", "take",
    "eat", "post_goal", "claim_goal", "confirm_goal", "cancel_goal", "abandon_goal", "reject_claim",
    "found_faction", "join_faction", "leave_faction", "invite", "set_profile", "remember", "forget",
}
URL_OR_EMAIL = re.compile(
    r"(?:https?://|www\.|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,})", re.IGNORECASE
)
SECRET = re.compile(
    r"(?:hg_[A-Za-z0-9_-]{20,}|sk-(?:ant-)?[A-Za-z0-9_-]{12,})", re.IGNORECASE
)

ROLE_ACTIONS = {
    "navigator": {
        "post_goal", "claim_goal", "cancel_goal", "abandon_goal", "reject_claim", "remember", "forget", "say",
        "move", "gather", "eat", "set_profile", "join_faction", "leave_faction",
    },
    "builder": {"move", "gather", "build", "repair", "write", "give", "take", "remember", "forget", "eat", "join_faction", "leave_faction"},
    "surveyor": {"move", "gather", "repair", "write", "remember", "forget", "eat", "join_faction", "leave_faction"},
    "broker": {
        "move", "claim_goal", "confirm_goal", "reject_claim", "give", "take", "whisper", "write", "remember", "forget", "eat",
        "found_faction", "invite", "join_faction", "leave_faction",
    },
    "envoy": {
        "say", "whisper", "found_faction", "join_faction", "leave_faction", "invite", "set_profile",
        "remember", "forget", "eat",
    },
    "experimenter": {"move", "gather", "build", "repair", "say", "remember", "forget", "eat", "join_faction", "leave_faction"},
    "observer": set(),
    "physicist": set(),
    "social-scientist": set(),
    "statistician": set(),
    "methodologist": set(),
    "conjecturer": set(),
    "skeptic": set(),
    "archivist": set(),
    "warden": set(),
    "conductor": set(),
    "toolsmith": set(),
}


class ProposedAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    action: str
    text: str | None = None
    description: str | None = Field(default=None, max_length=1000)
    title: str | None = Field(default=None, min_length=3, max_length=80)
    to: str | None = Field(default=None, max_length=24)
    x: int | None = Field(default=None, ge=0, le=127)
    y: int | None = Field(default=None, ge=0, le=127)
    qty: int | None = Field(default=None, ge=1)
    item: Literal["wood", "stone", "ore", "fiber", "berries"] | None = None
    kind: Literal["wood", "stone", "ore", "fiber", "berries"] | None = None
    type: Literal["sign", "road", "wall", "bridge", "hut", "farm", "storehouse", "tower", "monument"] | None = None
    policy: Literal["private", "faction", "public"] | None = None
    membership: Literal["invite", "open"] | None = None
    key: str | None = Field(default=None, max_length=64)
    bio: str | None = Field(default=None, max_length=500)
    goals: str | None = Field(default=None, max_length=500)
    motto: str | None = Field(default=None, max_length=100)
    name: str | None = Field(default=None, max_length=24)
    reward: dict[str, int] | None = None
    expires_in_ticks: int | None = Field(default=None, ge=1, le=8640)
    goal_id: int | None = Field(default=None, ge=1)
    faction_id: int | None = Field(default=None, ge=1)
    condition: dict[str, Any] | None = None

    @field_validator("text", "description", "title", "to")
    @classmethod
    def safe_text(cls, value: str | None) -> str | None:
        if value is not None and (URL_OR_EMAIL.search(value) or SECRET.search(value)):
            raise ValueError("text contains a URL, email address, or secret")
        return value


def _validate_condition(condition: Any) -> None:
    """A self-confirming goal condition (API 0.22.0): a delivery into the poster's storehouse, or a build."""
    if not isinstance(condition, dict) or condition.get("type") not in {"deliver", "build"}:
        raise ValueError("goal condition must be an object of type deliver or build")
    if condition["type"] == "deliver":
        missing = [key for key in ("x", "y", "item", "qty") if condition.get(key) is None]
        if missing:
            raise ValueError(f"deliver condition requires {', '.join(missing)}")
        if condition["item"] not in {"wood", "stone", "ore", "fiber", "berries"} or not isinstance(condition["qty"], int) or not 1 <= condition["qty"] <= 50:
            raise ValueError("deliver condition needs a valid item and a qty of 1 to 50")
        return
    if condition.get("blueprint") not in {"sign", "road", "wall", "bridge", "hut", "farm", "storehouse", "tower", "monument"}:
        raise ValueError("build condition needs a known blueprint")
    if condition.get("radius") is not None:
        if condition.get("x") is None or condition.get("y") is None:
            raise ValueError("build condition radius needs x and y")
        if not isinstance(condition["radius"], int) or not 0 <= condition["radius"] <= 16:
            raise ValueError("build condition radius must be 0 to 16")


def allowed_for(role: str) -> set[str]:
    """Allowlist for one hat, or the union for a '+'-joined set of hats worn together."""
    allowed: set[str] = set()
    for hat in role.split("+"):
        allowed |= ROLE_ACTIONS.get(hat, set())
    return allowed


def validate_action(raw: dict[str, Any], role: str, prior_text: set[str] | None = None) -> ProposedAction:
    """Validate schema-level fields, role permissions, and text constraints."""
    for key, value in raw.items():
        if isinstance(value, str) and (URL_OR_EMAIL.search(value) or SECRET.search(value)):
            raise ValueError(f"{key} contains a URL, email address, or secret")
    action = ProposedAction.model_validate(raw)
    if action.action not in COMMON_ACTIONS:
        raise ValueError(f"unknown action: {action.action}")
    if action.action not in allowed_for(role):
        raise ValueError(f"{role} may not perform {action.action}")
    limit = ACTION_TEXT_LIMITS.get(action.action)
    text = action.text
    if limit is not None and (text is None or len(text) > limit):
        raise ValueError(f"{action.action} text must be present and at most {limit} characters")
    if action.action == "post_goal":
        if action.title is None or not 3 <= len(action.title) <= 80:
            raise ValueError("goal title must be 3 to 80 characters")
        if action.description is None or len(action.description) > 1000:
            raise ValueError("goal description must be at most 1000 characters")
        if not isinstance(raw.get("reward"), dict) or not raw["reward"]:
            raise ValueError("post_goal requires a non-empty reward")
        for item, quantity in raw["reward"].items():
            if item not in {"wood", "stone", "ore", "fiber", "berries"} or not isinstance(quantity, int) or quantity < 1:
                raise ValueError("goal reward must contain positive quantities of valid items")
        if raw.get("condition") is not None:
            _validate_condition(raw["condition"])
    if action.action == "build" and raw.get("text") is not None and len(raw["text"]) > 200:
        raise ValueError("sign text must be at most 200 characters")
    required = {
        "move": ("x", "y"),
        "gather": (),
        "build": ("type",),
        "demolish": ("x", "y"),
        "repair": ("x", "y"),
        "say": ("text",),
        "whisper": ("to", "text"),
        "write": ("x", "y", "text"),
        "give": ("item", "qty"),
        "take": ("x", "y", "item", "qty"),
        "remember": ("key", "text"),
        "forget": ("key",),
        "claim_goal": ("goal_id",),
        "confirm_goal": ("goal_id",),
        "cancel_goal": ("goal_id",),
        "abandon_goal": ("goal_id",),
        "reject_claim": ("goal_id",),
        "join_faction": ("faction_id",),
    }
    missing = [field for field in required.get(action.action, ()) if raw.get(field) is None]
    if missing:
        raise ValueError(f"{action.action} requires {', '.join(missing)}")
    if action.action == "give" and not raw.get("to") and not {
        "x", "y"
    }.issubset(raw):
        raise ValueError("give requires a recipient or storehouse coordinates")
    if action.action == "found_faction" and not raw.get("name"):
        raise ValueError("found_faction requires a faction name")
    if action.action == "invite" and not raw.get("name"):
        raise ValueError("invite requires the invitee's name")
    if action.action == "set_profile" and raw.get("bio") is None and raw.get("goals") is None:
        raise ValueError("set_profile requires bio or goals")
    if prior_text and text and text.casefold() in {item.casefold() for item in prior_text}:
        raise ValueError("repeated text is not allowed")
    return action


def validate_actions(
    raw_actions: list[dict[str, Any]],
    role: str,
    *,
    recent_say_count: int = 0,
    open_goal_count: int = 0,
    prior_text: set[str] | None = None,
    private_text: set[str] | None = None,
    observe: dict[str, Any] | None = None,
) -> list[ProposedAction]:
    """Apply wake, spam, and open-goal limits to a proposed action batch."""
    if not 1 <= len(raw_actions) <= 4:
        raise ValueError("a wake must contain one to four actions")
    actions: list[ProposedAction] = []
    seen = {value.casefold() for value in prior_text or set()}
    for raw in raw_actions:
        action = validate_action(raw, role, seen)
        for value in private_text or set() if action.action not in {"remember", "forget"} else ():
            if len(value) >= 8 and any(
                value.casefold() in str(raw.get(field, "")).casefold()
                for field in ("text", "description", "title", "bio", "goals")
            ):
                raise ValueError("action text must not disclose private notebook or inbox content")
        actions.append(action)
        if action.text:
            seen.add(action.text)
    if recent_say_count + sum(action.action == "say" for action in actions) > 3:
        raise ValueError("at most three unprompted says are allowed per hour")
    posted = sum(action.action == "post_goal" for action in actions)
    cancelled = sum(action.action == "cancel_goal" for action in actions)
    if open_goal_count + posted - cancelled > 2:
        raise ValueError("at most two goals may be open")
    if observe:
        you = observe.get("you") or {}
        energy = you.get("energy")
        inventory = you.get("inventory") or {}
        berries = inventory.get("berries", 0) if isinstance(inventory, dict) else 0
        if isinstance(energy, (int, float)) and energy <= 20:
            if berries <= 0:
                raise ValueError("energy is low; rest at a hut before taking another action")
            if actions[0].action != "eat":
                raise ValueError("energy is low; eat berries before taking another action")
        position = (you.get("x"), you.get("y"))
        for action in actions:
            if (
                action.action == "move"
                and all(isinstance(v, int) for v in (*position, action.x, action.y))
                and max(abs(action.x - position[0]), abs(action.y - position[1])) > 12
            ):
                raise ValueError("movement exceeds the 12-step limit")
            if action.action == "move" and isinstance(action.x, int) and isinstance(action.y, int):
                position = (action.x, action.y)  # the world runs the batch in order: later checks start here
                continue
            if (
                action.action == "build"
                and action.x is not None
                and action.y is not None
                and all(isinstance(v, int) for v in position)
                and max(abs(action.x - position[0]), abs(action.y - position[1])) > 1
            ):
                raise ValueError("build target must be on or adjacent to the agent")
        if actions[0].action == "eat" and actions[0].qty and actions[0].qty > berries:
            raise ValueError("cannot eat more berries than are in inventory")
    return actions


def redact_observe(observe: dict[str, Any]) -> dict[str, Any]:
    """Copy an observe response with private inbox and notebook content removed."""
    redacted = dict(observe)
    redacted.pop("inbox", None)
    redacted.pop("notebook", None)
    you = redacted.get("you")
    if isinstance(you, dict):
        redacted["you"] = {key: value for key, value in you.items() if key != "notebook"}
    return redacted


def redact_result(result: dict[str, Any]) -> dict[str, Any]:
    """Keep only safe action status fields, excluding returned event content."""
    safe: dict[str, Any] = {}
    if isinstance(result.get("ok"), bool):
        safe["ok"] = result["ok"]
    if isinstance(result.get("error"), str):
        safe["error"] = result["error"]
    return safe


def private_strings(value: Any) -> set[str]:
    """Collect string leaves from content that must not be copied to public output."""
    if isinstance(value, str):
        return {value} if value else set()
    if isinstance(value, dict):
        return set().union(*(private_strings(child) for child in value.values()))
    if isinstance(value, list):
        return set().union(*(private_strings(child) for child in value))
    return set()


def redact_private_text(value: str, private_text: set[str]) -> str:
    for private in sorted(private_text, key=len, reverse=True):
        if len(private) >= 8:
            value = re.sub(re.escape(private), "[REDACTED]", value, flags=re.IGNORECASE)
    value = SECRET.sub("[REDACTED]", value)
    return value


__all__ = [
    "ProposedAction",
    "ValidationError",
    "allowed_for",
    "private_strings",
    "redact_observe",
    "redact_private_text",
    "redact_result",
    "validate_action",
    "validate_actions",
]
