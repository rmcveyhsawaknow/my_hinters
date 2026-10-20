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


def test_faction_membership_and_invite_follow_the_live_guide():
    founded = validate_action(
        {"action": "found_faction", "name": "Snozzberry Works", "membership": "open"}, "broker"
    )
    assert founded.membership == "open"
    with pytest.raises(ValueError, match="invitee"):
        validate_action({"action": "invite"}, "envoy")
    assert validate_action({"action": "invite", "name": "Peregrine"}, "envoy").name == "Peregrine"
    with pytest.raises(ValueError, match="may not perform"):
        validate_action({"action": "invite", "name": "Peregrine"}, "surveyor")


def test_reject_claim_is_a_poster_action_that_needs_a_goal_id():
    import pytest

    from hglab.actions import allowed_for, validate_action

    assert "reject_claim" in allowed_for("navigator") and "reject_claim" in allowed_for("broker")
    assert "reject_claim" not in allowed_for("builder")
    assert validate_action({"action": "reject_claim", "goal_id": 3}, "navigator").action == "reject_claim"
    with pytest.raises(ValueError):
        validate_action({"action": "reject_claim"}, "navigator")


def test_goal_conditions_are_checked_for_shape():
    import pytest

    from hglab.actions import validate_action

    base = {"action": "post_goal", "title": "10 wood for 5 stone", "description": "give into my storehouse", "reward": {"stone": 5}}
    deliver = {**base, "condition": {"type": "deliver", "x": 66, "y": 61, "item": "wood", "qty": 10}}
    assert validate_action(deliver, "navigator").condition["type"] == "deliver"
    build = {**base, "condition": {"type": "build", "blueprint": "bridge", "x": 60, "y": 70, "radius": 2}}
    assert validate_action(build, "navigator").condition["blueprint"] == "bridge"
    for bad in (
        {"type": "deliver", "x": 66, "y": 61, "item": "wood"},
        {"type": "deliver", "x": 66, "y": 61, "item": "gold", "qty": 10},
        {"type": "deliver", "x": 66, "y": 61, "item": "wood", "qty": 51},
        {"type": "build", "blueprint": "castle"},
        {"type": "build", "blueprint": "hut", "radius": 3},
        {"type": "wish"},
    ):
        with pytest.raises(ValueError):
            validate_action({**base, "condition": bad}, "navigator")


def test_repair_is_a_builders_and_surveyors_action_that_needs_a_tile():
    import pytest

    from hglab.actions import allowed_for, validate_action

    assert "repair" in allowed_for("builder") and "repair" in allowed_for("surveyor") and "repair" in allowed_for("experimenter")
    assert "repair" not in allowed_for("navigator") and "repair" not in allowed_for("envoy")
    assert validate_action({"action": "repair", "x": 71, "y": 84}, "builder").action == "repair"
    with pytest.raises(ValueError):
        validate_action({"action": "repair", "x": 71}, "builder")


def test_a_cancel_in_the_batch_frees_a_goal_slot_for_the_post_after_it():
    import pytest

    from hglab.actions import validate_actions

    post = {"action": "post_goal", "title": "Buy a lot", "description": "give wood into the vault", "reward": {"berries": 1}}
    validate_actions([{"action": "cancel_goal", "goal_id": 8}, post], "navigator", open_goal_count=2)
    with pytest.raises(ValueError):
        validate_actions([post], "navigator", open_goal_count=2)


def test_a_build_after_a_move_is_checked_from_where_the_move_ends():
    import pytest

    from hglab.actions import validate_actions

    observe = {"you": {"x": 10, "y": 10, "energy": 50, "inventory": {"wood": 5}}, "tick": 1}
    batch = [{"action": "move", "x": 20, "y": 10}, {"action": "build", "type": "sign", "x": 21, "y": 10, "text": "Lot D02-NW: staked"}]
    assert [a.action for a in validate_actions(batch, "builder", observe=observe)] == ["move", "build"]
    with pytest.raises(ValueError):
        validate_actions([{"action": "build", "type": "sign", "x": 21, "y": 10, "text": "far"}], "builder", observe=observe)
    with pytest.raises(ValueError):
        validate_actions([{"action": "move", "x": 20, "y": 10}, {"action": "move", "x": 33, "y": 10}], "builder", observe=observe)


def test_a_private_note_may_be_restated_in_the_notebook_but_not_said():
    import pytest

    from hglab.actions import validate_actions

    secret = "Peregrine thanks you for the farm, privately"
    validate_actions([{"action": "remember", "key": "notes", "text": secret + " and more"}], "builder", private_text={secret})
    with pytest.raises(ValueError):
        validate_actions([{"action": "say", "text": "Hear this: " + secret}], "envoy", private_text={secret})


def test_block_actions_are_checked_for_size_and_reach():
    import pytest

    from hglab.actions import allowed_for, validate_actions

    assert {"place", "remove", "paint"} <= allowed_for("builder") and "place" not in allowed_for("navigator")
    observe = {"you": {"x": 66, "y": 61, "energy": 50, "inventory": {"stone": 20}}, "tick": 1}
    walls = {"action": "place", "bx": 260, "by": 240, "bz": 0, "bx2": 271, "by2": 251, "bz2": 2, "material": "stone", "fill": "walls"}
    assert validate_actions([walls], "builder", observe=observe)[0].fill == "walls"
    with pytest.raises(ValueError):
        validate_actions([{**walls, "bz2": 5}], "builder", observe=observe)  # 432 cells
    with pytest.raises(ValueError):
        validate_actions([{"action": "place", "bx": 300, "by": 240, "bz": 0, "material": "stone"}], "builder", observe=observe)  # 9 tiles east
    with pytest.raises(ValueError):
        validate_actions([{"action": "place", "bx": 264, "by": 244, "bz": 0}], "builder", observe=observe)  # no material
    assert validate_actions([{"action": "paint", "bx": 264, "by": 244, "bz": 3, "color": "purple"}], "surveyor", observe=observe)[0].color == "purple"
