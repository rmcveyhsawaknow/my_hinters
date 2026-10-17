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


def test_action_batch_enforces_energy_and_world_distance():
    observation = {
        "you": {"x": 3, "y": 4, "energy": 15, "inventory": {"berries": 2}}
    }
    with pytest.raises(ValueError, match="eat berries"):
        validate_actions([{"action": "move", "x": 4, "y": 4}], "navigator", observe=observation)
    assert validate_actions(
        [{"action": "eat", "qty": 1}], "navigator", observe=observation
    )[0].action == "eat"
    observation["you"]["energy"] = 80
    with pytest.raises(ValueError, match="12-step"):
        validate_actions(
            [{"action": "move", "x": 20, "y": 4}], "navigator", observe=observation
        )


def test_action_limit_allows_exactly_four_and_goal_cap():
    actions = validate_actions(
        [{"action": "remember", "key": f"note-{i}", "text": str(i)} for i in range(4)], "navigator"
    )
    assert len(actions) == 4
    goal = {
        "action": "post_goal",
        "title": "A goal",
        "description": "done",
        "reward": {"berries": 1},
    }
    with pytest.raises(ValueError, match="two goals"):
        validate_actions([goal], "navigator", open_goal_count=2)


def test_goal_and_faction_actions_require_live_guide_ids():
    with pytest.raises(ValueError, match="goal_id"):
        validate_action({"action": "claim_goal"}, "broker")
    assert validate_action({"action": "confirm_goal", "goal_id": 3}, "broker").goal_id == 3
    with pytest.raises(ValueError, match="faction_id"):
        validate_action({"action": "join_faction", "name": "Factory"}, "envoy")
    assert validate_action({"action": "join_faction", "faction_id": 1}, "envoy").faction_id == 1
    with pytest.raises(ValueError, match="bio or goals"):
        validate_action({"action": "set_profile"}, "envoy")
