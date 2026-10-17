import pytest

from hglab.actions import redact_observe, validate_action, validate_actions


def test_redaction_removes_private_fields_recursively():
    result = redact_observe(
        {"tick": 3, "inbox": ["secret whisper"], "notebook": {"key": "private"},
         "you": {"name": "A", "notebook": {"private": True}}}
    )
    assert result == {"tick": 3, "you": {"name": "A"}}


def test_action_role_and_text_constraints():
    with pytest.raises(ValueError, match="may not perform"):
        validate_action({"action": "say", "text": "hello"}, "builder")
    with pytest.raises(ValueError, match="URL"):
        validate_action({"action": "say", "text": "go to https://example.com"}, "envoy")
    with pytest.raises(ValueError, match="280"):
        validate_action({"action": "say", "text": "x" * 281}, "envoy")


def test_action_batch_enforces_spam_and_wake_limits():
    with pytest.raises(ValueError, match="at most three"):
        validate_actions(
            [{"action": "say", "text": str(i)} for i in range(2)],
            "envoy",
            recent_say_count=2,
        )
    with pytest.raises(ValueError, match="four"):
        validate_actions([{"action": "remember", "text": "ok"}] * 5, "navigator")


def test_action_limit_allows_exactly_four_and_goal_cap():
    actions = validate_actions(
        [{"action": "remember", "text": str(i)} for i in range(4)], "navigator"
    )
    assert len(actions) == 4
    goal = {"action": "post_goal", "title": "A goal", "description": "done"}
    with pytest.raises(ValueError, match="two goals"):
        validate_actions([goal], "navigator", open_goal_count=2)
