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


LIVE_PROMPT = (
    'Reply with only JSON with keys offer, total, motto and reversed. offer: in under 30 words, a trade you would propose'
    ' to a stranger who is carrying 3 berries; mention the word "berries". total: the value of 3 times 9. motto: a motto'
    ' of at most 6 words for a guild of builders. reversed: the word "granite" spelled backwards.'
)
SECOND_PROMPT = (
    "Reply with only JSON with keys plan, mood, verse and sum. plan: in under 40 words, what you would build with 2 stone and"
    ' 3 wood at the edge of a forest. mood: one word. verse: a two-line rhyme of at least 6 words that mentions the word'
    ' "bridge". sum: the value of 14 + 19.'
)
THIRD_PROMPT = (
    "Reply with only JSON with keys route, omen, distance and haiku. route: in under 30 words, how you would reach a hill."
    " omen: one word. distance: the distance from (33, 32) to (59, 30) when distance is max(|dx|, |dy|). haiku: three short"
    ' lines, at least 5 words in all, that mention the word "hare".'
)


def test_mechanical_parts_of_a_challenge_are_computed_not_guessed():
    from hglab.challenge import clauses, mechanical_answers, response_schema

    assert set(clauses(LIVE_PROMPT)) == {"offer", "total", "motto", "reversed"}
    assert mechanical_answers(LIVE_PROMPT) == {"total": 27, "reversed": "etinarg"}
    assert mechanical_answers(SECOND_PROMPT) == {"sum": 33}
    assert mechanical_answers(THIRD_PROMPT) == {"distance": 26}
    schema = response_schema(LIVE_PROMPT)["properties"]
    assert schema["total"] == {"type": "integer"} and schema["offer"] == {"type": "string"} and schema["reversed"] == {"type": "string"}
    assert response_schema(THIRD_PROMPT)["properties"]["distance"] == {"type": "integer"}
    assert response_schema(SECOND_PROMPT)["properties"]["verse"] == {"type": "string"}  # "at least 6 words" is not a quantity


def test_finalize_honours_word_limits_quoted_words_one_word_and_lines():
    from hglab.challenge import finalize_answer

    sloppy = {
        "offer": " ".join(["word"] * 45) + " I will trade",  # too long, and never says berries
        "total": "twenty seven",
        "motto": "Build it well and build it to last forever",
        "reversed": "granite",
    }
    done = finalize_answer(LIVE_PROMPT, sloppy)
    assert done["total"] == 27 and done["reversed"] == "etinarg"
    assert len(done["offer"].split()) <= 29 and "berries" in done["offer"]
    assert len(done["motto"].split()) <= 6
    second = finalize_answer(SECOND_PROMPT, {"plan": "A small hut", "mood": "Hopeful!!", "verse": "over the bridge we go and then we rest below", "sum": "33"})
    assert second["mood"] == "Hopeful" and second["sum"] == 33 and second["verse"].count("\n") == 1 and "bridge" in second["verse"]
    third = finalize_answer(THIRD_PROMPT, {"route": "walk", "omen": "stone", "distance": 1, "haiku": "a hare sits by the still river and waits for dusk"})
    assert third["distance"] == 26 and third["haiku"].count("\n") == 2


def test_a_failed_verify_hands_back_a_fresh_challenge_to_answer():
    import json

    from hglab.cli import answer_daily_challenge
    from hglab.client import HinterglassError

    seen: list[str] = []

    class Client:
        def __init__(self):
            self.verified = False

        def observe(self):
            return {"challenge": None if self.verified else {"id": "c1", "prompt": LIVE_PROMPT, "expires_in_seconds": 25}}

        def verify(self, challenge_id, answer):
            if challenge_id == "c1":
                raise HinterglassError(403, "verification_required", "wrong", {"challenge": {"id": "c2", "prompt": SECOND_PROMPT}})
            self.verified = True
            return {"ok": True, "verified_until": "later"}

    import hglab.cli as cli_module

    def fake_responder(prompt, usage=None):
        seen.append(prompt)
        return json.dumps({"offer": "berries for wood", "total": 27, "motto": "build", "reversed": "etinarg", "plan": "a hut", "mood": "calm", "verse": "a bridge\nso high", "sum": 33})

    original = cli_module.challenge_responder
    cli_module.challenge_responder = fake_responder
    try:
        client = Client()
        assert answer_daily_challenge(client, client.observe()) is True
    finally:
        cli_module.challenge_responder = original
    assert seen == [LIVE_PROMPT, SECOND_PROMPT] and client.verified


def test_the_games_plain_key_list_is_understood():
    assert required_keys(LIVE_PROMPT) == {"offer", "total", "motto", "reversed"}
    assert required_keys(SECOND_PROMPT) == {"plan", "mood", "verse", "sum"}
    assert required_keys(THIRD_PROMPT) == {"route", "omen", "distance", "haiku"}
    assert required_keys('Reply with keys "a" and "b". a: one word. b: one word.') == {"a", "b"}
