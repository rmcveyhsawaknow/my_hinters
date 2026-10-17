"""Execute reproducibility commands for knowledge-base claims."""

from __future__ import annotations

import json
import math
import re
import shlex
import subprocess
from pathlib import Path
from typing import Any

import yaml

from hglab.kb import FRONT_MATTER


def prove_claim(root: Path, claim_id: str) -> bool:
    if not re.fullmatch(r"C-[0-9]{8}-[a-z0-9-]+", claim_id):
        raise ValueError("invalid claim ID")
    path = next((root / "kb").rglob(f"{claim_id}.md"), None)
    if path is None:
        raise FileNotFoundError(f"claim not found: {claim_id}")
    match = FRONT_MATTER.match(path.read_text(encoding="utf-8"))
    if not match:
        raise ValueError(f"{claim_id} has no valid front matter")
    item: dict[str, Any] = yaml.safe_load(match.group(1))
    if item.get("type") != "claim" or item.get("proof_level") not in {"P2", "P3", "P4"}:
        raise ValueError(f"{claim_id} is not a reproducible claim")
    command = item.get("prove_cmd")
    if not command:
        raise ValueError(f"{claim_id} has no prove_cmd")
    result = subprocess.run(
        shlex.split(command), cwd=root, capture_output=True, text=True, timeout=120, check=True
    )
    expected = item.get("expected")
    actual_text = result.stdout.strip()
    if isinstance(expected, (int, float)) and not isinstance(expected, bool):
        try:
            actual = float(actual_text)
        except ValueError as exc:
            raise ValueError("analysis output must be numeric for numeric expected values") from exc
        tolerance = float(item.get("tolerance", 0))
        if not math.isclose(actual, float(expected), rel_tol=tolerance, abs_tol=tolerance):
            raise ValueError(f"result {actual} differs from expected {expected}")
    elif actual_text != str(expected):
        try:
            actual_json = json.loads(actual_text)
        except json.JSONDecodeError:
            actual_json = actual_text
        if actual_json != expected:
            raise ValueError(f"result {actual_json!r} differs from expected {expected!r}")
    return True


def prove_all(root: Path) -> list[str]:
    """Prove every P2+ claim and return IDs checked."""
    checked = []
    for path in sorted((root / "kb").rglob("*.md")):
        match = FRONT_MATTER.match(path.read_text(encoding="utf-8"))
        if not match:
            continue
        item = yaml.safe_load(match.group(1))
        if item.get("type") == "claim" and item.get("proof_level") in {"P2", "P3", "P4"}:
            prove_claim(root, str(item["id"]))
            checked.append(str(item["id"]))
    return checked
