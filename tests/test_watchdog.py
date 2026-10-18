import faulthandler

import pytest

from hglab.watchdog import armed


def _spy(monkeypatch):
    calls: list[tuple] = []
    monkeypatch.setattr(
        faulthandler, "dump_traceback_later",
        lambda seconds, repeat=False, file=None, exit=False: calls.append(("arm", seconds, exit)),
    )
    monkeypatch.setattr(faulthandler, "cancel_dump_traceback_later", lambda: calls.append(("cancel",)))
    return calls


def test_the_watchdog_is_armed_to_exit_and_cancelled_afterwards(monkeypatch):
    calls = _spy(monkeypatch)
    with armed(90):
        assert calls == [("arm", 90, True)]
    assert calls[-1] == ("cancel",)


def test_the_watchdog_is_cancelled_even_when_the_wake_fails(monkeypatch):
    calls = _spy(monkeypatch)
    with pytest.raises(RuntimeError), armed(30):
        raise RuntimeError("world refused")
    assert calls == [("arm", 30, True), ("cancel",)]


def test_a_stream_without_a_descriptor_leaves_the_wake_unguarded(monkeypatch):
    def refuse(seconds, repeat=False, file=None, exit=False):
        raise ValueError("file is not a valid file descriptor")

    monkeypatch.setattr(faulthandler, "dump_traceback_later", refuse)
    monkeypatch.setattr(faulthandler, "cancel_dump_traceback_later", lambda: (_ for _ in ()).throw(AssertionError("not armed")))
    with armed(60):
        pass


def test_zero_seconds_arms_nothing(monkeypatch):
    calls = _spy(monkeypatch)
    with armed(0):
        pass
    assert calls == []


def test_persona_tick_arms_the_watchdog_for_jitter_plus_the_wake(monkeypatch, tmp_path):
    from pathlib import Path

    from hglab import cli_personas
    from hglab.persona import load_persona

    root = Path(__file__).resolve().parents[1]
    seen = {}

    def fake_armed(seconds):
        seen["seconds"] = seconds
        return armed(0)

    monkeypatch.setattr(cli_personas, "armed", fake_armed)
    monkeypatch.setattr(cli_personas, "_persona_tick", lambda root, persona, **kwargs: {"ok": True})
    record = cli_personas.persona_tick(root, load_persona(root, "town-crier"), jitter_minutes=10, scheduled=True, quiet=True)
    assert record == {"ok": True} and seen["seconds"] == 10 * 60 + cli_personas.WAKE_WATCHDOG_SECONDS
