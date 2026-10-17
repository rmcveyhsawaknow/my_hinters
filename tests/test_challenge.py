import time

import pytest

from hglab.challenge import answer_challenge, answer_with_retries, required_keys


def test_challenge_requires_json_object_and_prompt_keys():
    prompt = 'Return JSON like {"mood": "calm", "plan": "..."}'
    assert required_keys(prompt) == {"mood", "plan"}
    assert answer_challenge(prompt, lambda _: '{"mood":"calm","plan":"wait"}') == {
        "mood": "calm",
        "plan": "wait",
    }
    with pytest.raises(ValueError, match="missing required keys"):
        answer_challenge(prompt, lambda _: '{"mood":"calm"}')
    with pytest.raises(TypeError, match="JSON object"):
        answer_challenge(prompt, lambda _: "[]")
    assert required_keys('Return an object with keys "answer" and "mood".') == {
        "answer",
        "mood",
    }


def test_challenge_has_a_hard_timeout():
    with pytest.raises(TimeoutError, match="deadline"):
        answer_challenge("Return {}", lambda _: time.sleep(0.1), timeout=0.01)


def test_failed_submission_fetches_a_fresh_challenge_at_most_twice():
    challenges = iter([("1", '{"a": 1}'), ("2", '{"a": 2}')])
    submitted = []
    result = answer_with_retries(
        lambda: next(challenges),
        lambda prompt: prompt,
        lambda challenge_id, answer: submitted.append(challenge_id) or {"ok": challenge_id == "2"},
        retries=1,
    )
    assert result["ok"]
    assert submitted == ["1", "2"]
