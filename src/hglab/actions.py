"""Action validation shared by every runtime."""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

ACTION_TEXT_LIMITS = {"say": 280, "whisper": 500, "write": 200, "remember": 2000}
COMMON_ACTIONS = {
    "move", "gather", "build", "demolish", "say", "whisper", "write", "give", "take",
    "eat", "post_goal", "claim_goal", "confirm_goal", "cancel_goal", "abandon_goal",
    "found_faction", "join_faction", "leave_faction", "set_profile", "remember", "forget",
}
URL_OR_EMAIL = re.compile(
    r"(?:https?://|www\.|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,})", re.IGNORECASE
)
SECRET = re.compile(
    r"(?:hg_[A-Za-z0-9_-]{20,}|sk-(?:ant-)?[A-Za-z0-9_-]{12,})", re.IGNORECASE
)

ROLE_ACTIONS = {
    "navigator": {"post_goal", "claim_goal", "cancel_goal", "remember", "say", "move", "gather"},
    "builder": {"move", "gather", "build", "give", "take", "remember"},
    "surveyor": {"move", "gather", "write", "remember"},
    "broker": {"move", "claim_goal", "confirm_goal", "give", "take", "remember"},
    "envoy": {"say", "whisper", "found_faction", "join_faction", "leave_faction", "set_profile"},
    "experimenter": {"move", "gather", "build", "say", "remember"},
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
    model_config = ConfigDict(extra="allow")

    action: str
    text: str | None = None
    description: str | None = None
    title: str | None = None
    to: str | None = None
    x: int | None = Field(default=None, ge=0, le=127)
    y: int | None = Field(default=None, ge=0, le=127)
    qty: int | None = Field(default=None, ge=1)

    @field_validator("text", "description", "title", "to")
    @classmethod
    def safe_text(cls, value: str | None) -> str | None:
        if value is not None and (URL_OR_EMAIL.search(value) or SECRET.search(value)):
            raise ValueError("text contains a URL, email address, or secret")
        return value


def validate_action(raw: dict[str, Any], role: str, prior_text: set[str] | None = None) -> ProposedAction:
    """Validate schema-level fields, role permissions, and text constraints."""
    action = ProposedAction.model_validate(raw)
    if action.action not in COMMON_ACTIONS:
        raise ValueError(f"unknown action: {action.action}")
    if action.action not in ROLE_ACTIONS.get(role, set()):
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
) -> list[ProposedAction]:
    """Apply wake, spam, and open-goal limits to a proposed action batch."""
    if len(raw_actions) > 4:
        raise ValueError("a wake may contain at most four actions")
    actions = [validate_action(raw, role, prior_text) for raw in raw_actions]
    if recent_say_count + sum(action.action == "say" for action in actions) > 3:
        raise ValueError("at most three unprompted says are allowed per hour")
    if open_goal_count + sum(action.action == "post_goal" for action in actions) > 2:
        raise ValueError("at most two goals may be open")
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


__all__ = [
    "ProposedAction", "ValidationError", "redact_observe", "validate_action", "validate_actions",
]
