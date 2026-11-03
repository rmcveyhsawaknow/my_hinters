"""Tests never read or write this host's live state under runs/local."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _private_blueprint_ledger(tmp_path_factory, monkeypatch):
    """Every test starts from an empty blueprint ledger of its own.

    The ledger at runs/local/blueprints records the live factory's progress; a test that read it passed
    or failed with how far the real builders had got (test_shift's monument wake, 2026-10-25).
    """
    from hglab import factory

    folder = tmp_path_factory.mktemp("blueprints")
    monkeypatch.setattr(factory, "ledger_path", lambda root, name: folder / f"{name}.json")


@pytest.fixture(autouse=True)
def _private_office_ledger(tmp_path_factory, monkeypatch):
    """Every test starts with no eviction notices: the live ones are at runs/local/office/evictions.json."""
    from hglab import evict

    folder = tmp_path_factory.mktemp("office")
    monkeypatch.setattr(evict, "shared_path", lambda root: folder / "evictions.json")


ROOT = Path(__file__).resolve().parents[1]


def office_team(walls=False):
    """The exchange team as it stood before 2026-11-03: without the New York blueprint focus (tests/test_office_builds.py
    covers that), and with the walls enabled when a test is about them (the mechanism stands, switched off by the owner)."""
    from hglab.persona import load_team as _load_team

    team = _load_team(ROOT, "exchange")
    cfg = team.extra["pipeline"]
    for key in ("blueprint", "next_blueprint", "builders", "focus"):
        cfg.pop(key, None)
    if walls:
        cfg["claims"]["walls"]["enabled"] = True
    return team


@pytest.fixture(autouse=True)
def _private_fill_board(tmp_path_factory, monkeypatch):
    """Every test starts with an empty fill board: the live one is at runs/local/office/fill.json (hglab.fill, 2026-11-03)."""
    from hglab import fill

    folder = tmp_path_factory.mktemp("fill")
    monkeypatch.setattr(fill, "board_path", lambda root: folder / "fill.json")

