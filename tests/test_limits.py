from hglab.limits import action_limits


def test_limits_count_recent_public_speech_and_open_goals():
    counts = action_limits(
        {
            "tick": 200,
            "you": {"id": "self"},
            "events": [
                {"type": "say", "agent_id": "self", "tick": 150, "text": "hello"},
                {"type": "say", "agent_id": "peer", "tick": 199, "text": "peer"},
                {"type": "say", "agent_id": "self", "tick": 1, "text": "old"},
            ],
            "your_goals": [{"status": "open"}, {"status": "claimed"}, {"status": "complete"}],
        }
    )
    assert counts == (2, 2, {"hello"})


def test_limits_read_reserved_notebook_key():
    assert action_limits(
        {
            "tick": 10,
            "notebook": {"_limits": '{"says":[{"tick":8,"text":"Repeat"}]}'},
        }
    ) == (1, 0, {"repeat"})


def test_limits_match_live_event_shape_by_actor_name_and_dict_goals():
    counts = action_limits(
        {
            "tick": 400,
            "you": {"id": 7, "name": "Fudgewright"},
            "events": [
                {"id": 1, "tick": 390, "type": "say", "actor": "Fudgewright",
                 "text": "Fudgewright says: snozzberries!", "data": {"text": "snozzberries!"}},
                {"id": 2, "tick": 395, "type": "say", "actor": "Peregrine",
                 "text": "Peregrine says: hello", "data": {"text": "hello"}},
            ],
            "your_goals": {"posted": [{"status": "open"}, {"status": "complete"}], "claimed": None},
        }
    )
    assert counts == (1, 1, {"snozzberries!"})
