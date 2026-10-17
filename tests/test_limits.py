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
