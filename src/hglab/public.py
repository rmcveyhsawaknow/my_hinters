"""Keyless public reads shared across the local runtime's processes.

The world allows sixty keyless requests a minute from one address, in bursts of thirty. Twenty-one
personas' jobs on one host each read the public log, roster, goals and factions, and several start at
the same minute, so the reads go through one small disk cache under ``runs/local/public``: the first
process to need a page fetches it and the others read its copy, a copy up to half an hour old stands
in when the world refuses a fetch, and no process fetches what another is fetching. Outside the local
runtime (``HGLAB_RUNTIME`` unset, as under Actions or in the tests) every call is a plain fetch.
"""

from __future__ import annotations

import contextlib
import json
import os
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

STALE_OK = 1800  # seconds a stale copy may stand in for a fetch the world refused or another process holds
LOCK_STALE = 120  # a lock older than this belongs to a crashed fetcher
WAIT_STEPS = 24  # half-second waits for another process's fetch before using what there is
EVENTS_AGE = 120
AGENTS_AGE = 60
GOALS_AGE = 120
FACTIONS_AGE = 300


def cache_dir(root: Path | None) -> Path | None:
    """Where this host keeps its shared public copies; None outside the local runtime."""
    if root is None or os.environ.get("HGLAB_RUNTIME") != "local":
        return None
    return Path(root) / "runs/local/public"


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _age(path: Path) -> float | None:
    try:
        return time.time() - path.stat().st_mtime
    except OSError:
        return None


def cached(root: Path | None, name: str, fetch: Callable[[], Any], max_age: int, *, stale_ok: int = STALE_OK) -> Any:
    """``fetch()`` at most once per ``max_age`` seconds across every process on this host.

    A fresh copy is returned without a request. When another process holds the fetch, this one waits
    for its copy and falls back to the stale one; when the fetch fails (the keyless limit, an outage) a
    copy younger than ``stale_ok`` is returned and the error is raised otherwise.
    """
    folder = cache_dir(root)
    if folder is None:
        return fetch()
    path = folder / f"{name}.json"
    age = _age(path)
    if age is not None and age <= max_age:
        value = _read(path)
        if value is not None:
            return value
    folder.mkdir(parents=True, exist_ok=True)
    lock = folder / f"{name}.lock"
    lock_age = _age(lock)
    if lock_age is not None and lock_age > LOCK_STALE:
        with contextlib.suppress(OSError):
            lock.unlink()
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        for _ in range(WAIT_STEPS):
            time.sleep(0.5)
            age = _age(path)
            if age is not None and age <= max_age:
                value = _read(path)
                if value is not None:
                    return value
        age = _age(path)
        if age is not None and age <= stale_ok:
            value = _read(path)
            if value is not None:
                return value
        return fetch()
    except OSError:
        return fetch()
    try:
        try:
            value = fetch()
        except Exception:
            age = _age(path)
            if age is not None and age <= stale_ok:
                stale = _read(path)
                if stale is not None:
                    return stale
            raise
        tmp = path.with_suffix(".tmp")
        with contextlib.suppress(OSError, TypeError, ValueError):
            tmp.write_text(json.dumps(value), encoding="utf-8")
            os.replace(tmp, path)
        return value
    finally:
        os.close(fd)
        with contextlib.suppress(OSError):
            lock.unlink()


def public_agents(root: Path | None, max_age: int = AGENTS_AGE) -> list[dict[str, Any]]:
    """The public roster (name, position, faction, last seen), shared for a minute."""
    from hglab.client import HinterglassClient

    rows = cached(root, "agents", lambda: list(HinterglassClient().public_agents().get("agents", [])), max_age)
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def public_goals(root: Path | None, status: str = "open", max_age: int = GOALS_AGE) -> list[dict[str, Any]]:
    """The public goals of one status, shared for two minutes."""
    from hglab.client import HinterglassClient

    rows = cached(root, f"goals-{status}", lambda: list(HinterglassClient().public_goals(status).get("goals", [])), max_age)
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


def public_factions(root: Path | None, max_age: int = FACTIONS_AGE) -> list[dict[str, Any]]:
    """The public faction list, shared for five minutes."""
    from hglab.client import HinterglassClient

    rows = cached(root, "factions", lambda: list(HinterglassClient().public_factions().get("factions", [])), max_age)
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


__all__ = ["AGENTS_AGE", "EVENTS_AGE", "FACTIONS_AGE", "GOALS_AGE", "cache_dir", "cached", "public_agents", "public_factions", "public_goals"]
