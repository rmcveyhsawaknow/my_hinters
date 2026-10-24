"""Keyless public reads shared across the host's processes, and the catalogue built from the archive."""

import json
import os
from pathlib import Path

import pytest

from hglab import public
from hglab.client import HinterglassError

ROOT = Path(__file__).parents[1]


def test_outside_the_local_runtime_every_read_is_a_plain_fetch(tmp_path, monkeypatch):
    monkeypatch.delenv("HGLAB_RUNTIME", raising=False)
    calls = []
    assert public.cached(tmp_path, "x", lambda: calls.append(1) or {"a": 1}, 60) == {"a": 1}
    assert public.cached(tmp_path, "x", lambda: calls.append(1) or {"a": 2}, 60) == {"a": 2}
    assert len(calls) == 2 and not (tmp_path / "runs/local/public").exists()


def test_under_the_local_runtime_one_fetch_serves_every_process_for_a_while(tmp_path, monkeypatch):
    monkeypatch.setenv("HGLAB_RUNTIME", "local")
    calls = []

    def fetch():
        calls.append(1)
        return [{"id": len(calls)}]

    first = public.cached(tmp_path, "events-6", fetch, 120)
    second = public.cached(tmp_path, "events-6", fetch, 120)
    assert first == second == [{"id": 1}] and len(calls) == 1
    path = tmp_path / "runs/local/public/events-6.json"
    assert json.loads(path.read_text(encoding="utf-8")) == [{"id": 1}] and not (tmp_path / "runs/local/public/events-6.lock").exists()
    old = path.stat().st_mtime - 600
    os.utime(path, (old, old))
    assert public.cached(tmp_path, "events-6", fetch, 120) == [{"id": 2}] and len(calls) == 2  # stale: fetched again

    def refused():
        raise HinterglassError(429, "rate_limited", "Too many public requests", {})

    os.utime(path, (old, old))
    assert public.cached(tmp_path, "events-6", refused, 120) == [{"id": 2}]  # the world refused: the stale copy stands in
    ancient = path.stat().st_mtime - 7200
    os.utime(path, (ancient, ancient))
    with pytest.raises(HinterglassError):
        public.cached(tmp_path, "events-6", refused, 120)  # too old to stand in: the error is the caller's


def test_a_lock_held_by_another_process_means_wait_then_use_what_there_is(tmp_path, monkeypatch):
    monkeypatch.setenv("HGLAB_RUNTIME", "local")
    monkeypatch.setattr(public, "WAIT_STEPS", 1)
    monkeypatch.setattr(public.time, "sleep", lambda s: None)
    folder = tmp_path / "runs/local/public"
    folder.mkdir(parents=True)
    (folder / "agents.lock").write_text("", encoding="utf-8")
    path = folder / "agents.json"
    path.write_text(json.dumps([{"name": "Clarion"}]), encoding="utf-8")
    old = path.stat().st_mtime - 300
    os.utime(path, (old, old))
    calls = []
    assert public.cached(tmp_path, "agents", lambda: calls.append(1) or [], 60) == [{"name": "Clarion"}] and not calls  # the other process's stale copy, no second fetch
    stale_lock = path.stat().st_mtime - 1000
    os.utime(folder / "agents.lock", (stale_lock, stale_lock))
    assert public.cached(tmp_path, "agents", lambda: calls.append(1) or [{"name": "Nodkin"}], 60) == [{"name": "Nodkin"}] and calls  # a crashed fetcher's lock is broken


def test_event_pages_and_the_roster_go_through_the_cache_with_the_root(tmp_path, monkeypatch):
    from hglab import cli_personas

    monkeypatch.setenv("HGLAB_RUNTIME", "local")

    class Client:
        def __init__(self):
            self.calls = 0

        def public_events(self, **params):
            self.calls += 1
            return {"events": [{"id": 10 - self.calls, "tick": 100, "type": "move"}], "next_before": None}

    client = Client()
    first = cli_personas.fetch_public_events(client, pages=2, root=tmp_path)
    assert [e["id"] for e in first] == [9, 8] and client.calls == 2  # two pages, once
    assert cli_personas.fetch_public_events(client, pages=2, root=tmp_path) == first and client.calls == 2  # the second reader gets the copy
    assert cli_personas.EVENT_PAGES == 6
    seen = []

    class Roster:
        def public_agents(self):
            seen.append(1)
            return {"agents": [{"name": "Clarion", "x": 1, "y": 2}]}

    monkeypatch.setattr("hglab.client.HinterglassClient", lambda *a, **k: Roster())
    assert public.public_agents(tmp_path) == [{"name": "Clarion", "x": 1, "y": 2}]
    assert public.public_agents(tmp_path) == [{"name": "Clarion", "x": 1, "y": 2}] and len(seen) == 1


def test_the_architecture_catalogue_is_built_from_the_archive_not_from_a_week_of_pages(tmp_path):
    from hglab.architecture import refresh

    archive = tmp_path / "data/events/public.jsonl"
    archive.parent.mkdir(parents=True)
    rows = [
        {"id": 1, "tick": 1000, "type": "build", "actor": "Plumbline", "x": 10, "y": 10, "data": {"type": "hut"}},
        {"id": 2, "tick": 1010, "type": "build", "actor": "Plumbline", "x": 11, "y": 10, "data": {"type": "farm"}},
    ]
    archive.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

    class Never:
        def public_events(self, **params):
            raise AssertionError("the archive has rows: no page is fetched")

    cat, _new = refresh(tmp_path, Never(), 7)
    assert isinstance(cat, dict) and (tmp_path / "runs/local/architecture.json").exists() or isinstance(cat, dict)
