"""Validate repository YAML configuration against checked-in schemas."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
import yaml

CONFIG_SCHEMAS = {
    "agents": "agents",
    "collective": "collective",
    "models": "models",
    "budget": "budget",
}


def validate_config(root: Path) -> list[str]:
    errors = []
    for config_name, schema_name in CONFIG_SCHEMAS.items():
        try:
            value: Any = yaml.safe_load(
                (root / f"config/{config_name}.yaml").read_text(encoding="utf-8")
            )
            schema_doc = json.loads(
                (root / f"schemas/{schema_name}.json").read_text(encoding="utf-8")
            )
            validator_type = jsonschema.validators.validator_for(schema_doc)
            validator_type.check_schema(schema_doc)
            validator_type(
                schema_doc, format_checker=jsonschema.FormatChecker()
            ).validate(value)
        except (OSError, yaml.YAMLError, jsonschema.ValidationError, jsonschema.SchemaError) as exc:
            errors.append(f"config/{config_name}.yaml: {exc}")
    try:
        agents = yaml.safe_load((root / "config/agents.yaml").read_text(encoding="utf-8"))["agents"]
        names = [agent["name"].casefold() for agent in agents]
        reserved = {"admin", "system", "hinterglass", "world"}
        if len(names) != len(set(names)):
            errors.append("config/agents.yaml: agent names must be unique ignoring case")
        if reserved.intersection(names):
            errors.append("config/agents.yaml: reserved agent name")
        known_roles = {path.stem for path in (root / "roles").glob("*.md") if path.name != "README.md"}
        for agent in agents:
            unknown = set(agent["roles"]) - known_roles
            if unknown:
                errors.append(f"config/agents.yaml: unknown roles for {agent['name']}: {sorted(unknown)}")
    except (OSError, KeyError, TypeError, yaml.YAMLError) as exc:
        errors.append(f"config/agents.yaml: {exc}")
    return errors
