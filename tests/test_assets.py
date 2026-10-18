import json
from pathlib import Path

import jsonschema
import yaml

from hglab.config import validate_config
from hglab.kb import FRONT_MATTER

ROOT = Path(__file__).parents[1]


def test_all_role_and_skill_front_matter_matches_schemas():
    role_schema = json.loads((ROOT / "schemas/role-frontmatter.json").read_text())
    skill_schema = json.loads((ROOT / "schemas/skill-frontmatter.json").read_text())
    roles = sorted(path for path in (ROOT / "roles").glob("*.md") if path.name != "README.md")
    skills = sorted((ROOT / "skills").glob("*/SKILL.md"))
    assert len(roles) == 17
    assert len(skills) == 28
    for path, schema in [
        *((path, role_schema) for path in roles),
        *((path, skill_schema) for path in skills),
    ]:
        match = FRONT_MATTER.match(path.read_text(encoding="utf-8"))
        assert match
        jsonschema.validate(yaml.safe_load(match.group(1)), schema)


def test_checked_in_configuration_matches_schemas():
    assert validate_config(ROOT) == []
