import json

from hglab.inbox import INBOX_KEY, merge_inbox, note_for, preserve, stored


def test_whispers_are_kept_in_the_notebook_and_merged_back_without_duplicates():
    answer = {"from": "LandBroker", "text": "SITE for factory: lot I08-SE, anchor (87,87), 3 free lots beside it; price 45 wood.", "tick": 46182}
    observe = {"tick": 46200, "inbox": [answer], "notebook": {}}
    note = note_for(observe, 46200)
    assert note is not None and json.loads(note)["whispers"][0]["from"] == "LandBroker"
    later = {"tick": 46300, "inbox": [], "notebook": {INBOX_KEY: note}}
    assert note_for(later, 46300) is None  # nothing new arrived: no note to write
    assert [w["from"] for w in stored(later)] == ["LandBroker"]
    merged = merge_inbox({**later, "inbox": [answer, {"from": "Quill", "text": "hello", "tick": 46290}]})
    assert [w["from"] for w in merged] == ["LandBroker", "Quill"]  # the kept copy and the live one are the same whisper
    old = {"tick": 46200 + 3 * 8640, "inbox": [{"from": "Quill", "text": "new", "tick": 46200 + 3 * 8640}], "notebook": {INBOX_KEY: note}}
    assert [w["from"] for w in json.loads(note_for(old, old["tick"]))["whispers"]] == ["Quill"]  # two days on, the old answer drops


def test_the_verification_look_keeps_whispers_for_the_planner():
    from hglab import cli

    sent = []

    class Client:
        def observe(self):
            return {"tick": 10, "inbox": [{"id": 1, "from": "LandBroker", "text": "SITE for works: lot I09-SE, anchor (87,97); price 76 wood.", "tick": 9}], "notebook": {}}

        def act(self, action):
            sent.append(action)
            return {"ok": True}

    assert cli.ensure_verified(Client()) is False  # no challenge
    assert len(sent) == 1 and sent[0]["action"] == "remember" and sent[0]["key"] == INBOX_KEY and "SITE for works" in sent[0]["text"]
    later = {"tick": 12, "inbox": [], "notebook": {INBOX_KEY: sent[0]["text"]}}
    assert [w["from"] for w in merge_inbox(later)] == ["LandBroker"]  # the loop's own observe finds it in the notebook

    class Quiet(Client):
        def observe(self):
            return {"tick": 10, "inbox": [], "notebook": {}}

    assert cli.keep_whispers(Quiet(), Quiet().observe()) is False and len(sent) == 1


def test_preserve_writes_one_remember_only_when_something_arrived():
    sent = []

    class Client:
        def act(self, action):
            sent.append(action)
            return {"ok": True}

    assert preserve(Client(), {"tick": 1, "inbox": [], "notebook": {}}) is False and sent == []
    assert preserve(Client(), {"tick": 1, "inbox": [{"from": "Quill", "text": "hi", "tick": 1}], "notebook": {}}) is True
    assert sent[0]["action"] == "remember" and sent[0]["key"] == INBOX_KEY and "Quill" in sent[0]["text"]
