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


def test_preserve_writes_one_remember_only_when_something_arrived():
    sent = []

    class Client:
        def act(self, action):
            sent.append(action)
            return {"ok": True}

    assert preserve(Client(), {"tick": 1, "inbox": [], "notebook": {}}) is False and sent == []
    assert preserve(Client(), {"tick": 1, "inbox": [{"from": "Quill", "text": "hi", "tick": 1}], "notebook": {}}) is True
    assert sent[0]["action"] == "remember" and sent[0]["key"] == INBOX_KEY and "Quill" in sent[0]["text"]
