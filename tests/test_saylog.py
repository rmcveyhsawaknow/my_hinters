"""The three-an-hour rule holds whatever observe shows: every line said here is logged and counted."""

import json

import httpx

from hglab import saylog
from hglab.client import HinterglassClient
from hglab.limits import action_limits


def test_lines_said_here_are_counted_even_when_observe_has_dropped_them(tmp_path, monkeypatch):
    monkeypatch.setenv("HGLAB_RUNTIME", "local")
    monkeypatch.chdir(tmp_path)
    busy = {"tick": 1000, "you": {"name": "GrandadPail"}, "events": [{"type": "move", "actor": "Treacleaxe", "tick": 999}] * 50, "notebook": {}}
    assert action_limits(busy)[0] == 0  # fifty other events: his own lines are not in view
    for tick, text in ((600, "too old"), (800, "one"), (900, "two"), (990, "three")):
        saylog.record("GrandadPail", tick, text)
    assert saylog.merge(busy) == 3 and action_limits(busy)[0] == 3  # the last hour's three lines count: no fourth
    assert json.loads(json.dumps(busy["notebook"]["_limits"]))["says"][0]["text"] == "one"
    assert saylog.merge(busy) == 3 and action_limits(busy)[0] == 3  # merging twice counts once
    other = {"tick": 1000, "you": {"name": "MotherPail"}, "events": [], "notebook": {}}
    assert saylog.merge(other) == 0 and action_limits(other)[0] == 0  # each agent its own log
    monkeypatch.delenv("HGLAB_RUNTIME")
    assert not saylog.enabled()


def test_the_client_logs_accepted_lines_and_merges_them_into_every_observe(tmp_path, monkeypatch):
    monkeypatch.setenv("HGLAB_RUNTIME", "local")
    monkeypatch.chdir(tmp_path)
    state = {"tick": 2000}

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, json={"tick": state["tick"], "you": {"name": "Clarion"}, "events": [], "notebook": {}})
        body = json.loads(request.content)
        return httpx.Response(200, json={"ok": body.get("text") != "refused", "result": {}})

    client = HinterglassClient(api_key="x", http=httpx.Client(base_url="https://example.invalid", transport=httpx.MockTransport(handler)), rate_per_minute=6000)
    client.observe()
    client.act({"action": "say", "text": "Hear this!"})
    client.act({"action": "say", "text": "refused"})
    client.act({"action": "move", "x": 1, "y": 1})
    assert [r["text"] for r in saylog.load("Clarion")] == ["Hear this!"]  # only accepted lines
    state["tick"] = 2100
    assert action_limits(client.observe())[0] == 1
    state["tick"] = 2400
    assert action_limits(client.observe())[0] == 0  # an hour on, the line no longer counts
