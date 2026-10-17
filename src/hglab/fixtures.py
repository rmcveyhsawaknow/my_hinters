"""Fixture-backed world client for dry runs and tests. No network, no key."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from hglab.persona import chebyshev


def load_fixture(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or "you" not in data:
        raise ValueError(f"{path}: an observe fixture needs a 'you' block")
    return data


def load_terrain_rows(path: Path) -> list[str]:
    rows = [line.rstrip("\r\n") for line in path.read_text(encoding="ascii").splitlines() if line.strip()]
    if len(rows) != 128 or any(len(r) != 128 for r in rows):
        raise ValueError(f"{path}: expected 128 rows of 128 terrain codes")
    return rows


class FixtureClient:
    """Replays one observe payload and simulates the few state changes a wake makes.

    ``remember``/``forget`` update the notebook so the lease and persona state round-trip;
    ``move``, ``eat`` and ``gather`` adjust position, energy and inventory roughly as the
    world would, so a multi-action dry run stays self-consistent. Everything else returns
    ``ok`` without side effects.
    """

    def __init__(self, observe: dict[str, Any], *, fail_actions: set[str] | None = None) -> None:
        self._observe = copy.deepcopy(observe)
        self._observe.setdefault("notebook", {})
        self.actions: list[dict[str, Any]] = []
        self.fail_actions = fail_actions or set()
        self.observe_count = 0

    def observe(self) -> dict[str, Any]:
        self.observe_count += 1
        return copy.deepcopy(self._observe)

    def act(self, action: dict[str, Any]) -> dict[str, Any]:
        self.actions.append(copy.deepcopy(action))
        kind = action.get("action")
        if kind in self.fail_actions:
            return {"ok": False, "error": "not_allowed", "message": "fixture refusal"}
        notebook = self._observe.setdefault("notebook", {})
        you = self._observe.setdefault("you", {})
        if kind == "remember":
            if action["key"] not in notebook and len(notebook) >= 50:
                return {"ok": False, "error": "not_allowed", "message": "notebook full"}
            notebook[action["key"]] = action["text"]
        elif kind == "forget":
            if action["key"] not in notebook:
                return {"ok": False, "error": "not_found", "message": "unknown key"}
            notebook.pop(action["key"], None)
        elif kind == "move":
            here = (int(you.get("x", 0)), int(you.get("y", 0)))
            target = (int(action["x"]), int(action["y"]))
            cost = chebyshev(here, target)
            if cost > 12:
                return {"ok": False, "error": "too_far", "message": "no path within 12 steps"}
            if you.get("energy", 0) < cost:
                return {"ok": False, "error": "insufficient_energy", "message": "rest first"}
            you["x"], you["y"] = target
            you["energy"] = int(you.get("energy", 0)) - cost
        elif kind == "eat":
            inventory = you.setdefault("inventory", {})
            berries = int(inventory.get("berries", 0))
            if berries <= 0:
                return {"ok": False, "error": "insufficient_materials", "message": "no berries"}
            energy = int(you.get("energy", 0))
            maximum = int(you.get("energy_max", 100))
            needed = max(0, -(-(maximum - energy) // 15))
            qty = min(berries, needed, int(action.get("qty") or needed) or needed)
            inventory["berries"] = berries - qty
            you["energy"] = min(maximum, energy + 15 * qty)
        elif kind == "gather":
            if you.get("energy", 0) < 3:
                return {"ok": False, "error": "insufficient_energy", "message": "rest first"}
            inventory = you.setdefault("inventory", {})
            if sum(int(v) for v in inventory.values()) >= 50:
                return {"ok": False, "error": "inventory_full", "message": "pack is full"}
            kind_wanted = action.get("kind") or "wood"
            inventory[kind_wanted] = int(inventory.get(kind_wanted, 0)) + 5
            you["energy"] = int(you.get("energy", 0)) - 3
        elif kind in {"build", "demolish"}:
            you["energy"] = int(you.get("energy", 0)) - 5
        elif kind in {"say", "whisper", "write", "give", "take", "claim_goal"}:
            you["energy"] = int(you.get("energy", 0)) - 1
        return {"ok": True, "result": {}, "agent": {k: you.get(k) for k in ("x", "y", "energy", "inventory")}}


__all__ = ["FixtureClient", "load_fixture", "load_terrain_rows"]
