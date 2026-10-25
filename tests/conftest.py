"""Tests never read or write this host's live state under runs/local."""

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
