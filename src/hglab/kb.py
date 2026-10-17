"""Knowledge-base ID generation, front-matter validation, and index building."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path
from typing import Any

import jsonschema
import yaml

PREFIXES = {
    "goal": "G", "idea": "I", "hypothesis": "H", "experiment": "E", "claim": "C",
    "method": "M", "principle": "P", "review": "R", "journal": "J",
}
TYPE_DIRECTORIES = {
    "goal": "goals",
    "idea": "ideas",
    "hypothesis": "hypotheses",
    "experiment": "experiments",
    "claim": "claims",
    "method": "methods",
    "principle": "principles",
    "review": "reviews",
    "journal": "journal",
}
FRONT_MATTER = re.compile(r"\A---\s*\n(.*?)\n---(?:\s*\n)?", re.DOTALL)


def make_id(kind: str, title: str, today: date | None = None) -> str:
    if kind not in PREFIXES:
        raise ValueError(f"unknown knowledge item type: {kind}")
    slug = re.sub(r"[^a-z0-9]+", "-", title.casefold()).strip("-") or "untitled"
    return f"{PREFIXES[kind]}-{(today or date.today()):%Y%m%d}-{slug}"


def validate(root: Path) -> list[str]:
    schema = json.loads((root / "schemas/kb-item.json").read_text(encoding="utf-8"))
    errors: list[str] = []
    seen_ids: set[str] = set()
    for path in sorted((root / "kb").rglob("*.md")):
        if path.name in {"INDEX.md", "NORTH_STAR.md"} or "templates" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        match = FRONT_MATTER.match(text)
        if not match:
            errors.append(f"{path.relative_to(root)}: missing YAML front matter")
            continue
        try:
            data: dict[str, Any] = yaml.safe_load(match.group(1))
            for field in ("created", "updated"):
                if field in data and not isinstance(data[field], str):
                    data[field] = data[field].isoformat()
            jsonschema.Draft202012Validator(
                schema, format_checker=jsonschema.FormatChecker()
            ).validate(data)
            if path.stem != data["id"]:
                raise ValueError("filename must match front-matter ID")
            if data["id"] in seen_ids:
                raise ValueError(f"duplicate knowledge item ID: {data['id']}")
            seen_ids.add(data["id"])
        except (yaml.YAMLError, jsonschema.ValidationError, TypeError, ValueError) as exc:
            errors.append(f"{path.relative_to(root)}: {exc}")
    return errors


def build_index(root: Path) -> Path:
    kb = root / "kb"
    entries: list[tuple[str, str, str, str]] = []
    for path in sorted(kb.rglob("*.md")):
        if path.name in {"INDEX.md", "NORTH_STAR.md"} or "templates" in path.parts:
            continue
        match = FRONT_MATTER.match(path.read_text(encoding="utf-8"))
        if match:
            data = yaml.safe_load(match.group(1))
            entries.append(
                (
                    str(data.get("type", "")),
                    str(data.get("id", "")),
                    str(data.get("title", "")),
                    path.relative_to(kb).as_posix(),
                )
            )
    sections = ["# Knowledge base index", "", "North Star: [read first](NORTH_STAR.md)", ""]
    for kind, item_id, title, relative_path in entries:
        sections.append(f"- **{kind}** [{item_id}]({relative_path}) — {title}")
    path = kb / "INDEX.md"
    path.write_text("\n".join(sections) + "\n", encoding="utf-8")
    return path


def create(root: Path, kind: str, title: str) -> Path:
    item_id = make_id(kind, title)
    destination = root / "kb" / TYPE_DIRECTORIES[kind] / f"{item_id}.md"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        raise FileExistsError(f"knowledge item already exists: {item_id}")
    today = date.today().isoformat()
    data: dict[str, Any] = {
        "id": item_id, "type": kind, "title": title, "status": "proposed",
        "created": today, "updated": today, "author_runtime": "human", "roles": [], "links": [],
    }
    if kind == "claim":
        data.update(proof_level="P0", evidence=[], prove_cmd="", expected=None, tolerance=0)
    if kind == "hypothesis":
        data.update(prediction="", falsifier="", prereg_commit="", window_start_utc="")
    if kind == "goal":
        data.update(parent=None, success_test="", score=0)
    destination.write_text(f"---\n{yaml.safe_dump(data, sort_keys=False)}---\n\n", encoding="utf-8")
    return destination
