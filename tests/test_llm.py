from pathlib import Path

from hglab.llm import route_config

ROOT = Path(__file__).parents[1]


def _keys(monkeypatch, anthropic: bool, openai: bool):
    monkeypatch.setattr(
        "hglab.llm.get_secret",
        lambda name, root=None: ("x" if (name == "ANTHROPIC_API_KEY" and anthropic) or (name == "OPENAI_API_KEY" and openai) else None),
    )


def test_review_route_runs_on_the_vendor_whose_key_exists(monkeypatch):
    _keys(monkeypatch, anthropic=True, openai=False)
    selected = route_config("review", ROOT, author_runtime="actions-anthropic")
    assert selected["provider"] == "anthropic"
    assert selected["model"] != "TODO"
    _keys(monkeypatch, anthropic=False, openai=True)
    selected = route_config("tick", ROOT)
    assert selected["provider"] == "anthropic"  # no usable OpenAI model id configured; config unchanged


def test_strict_schema_drops_constraints_and_closes_objects():
    from hglab.llm import strict_schema

    loose = {
        "$schema": "x", "type": "object",
        "properties": {"n": {"type": "integer", "minimum": 1, "maximum": 5}, "s": {"type": "string", "maxLength": 3, "pattern": "^a"}},
        "additionalProperties": True,
        "$defs": {"inner": {"type": "object", "properties": {"k": {"type": "string"}}, "additionalProperties": True}},
    }
    strict = strict_schema(loose)
    assert "$schema" not in strict and strict["additionalProperties"] is False
    assert strict["properties"]["n"] == {"type": "integer"}
    assert strict["properties"]["s"] == {"type": "string"}
    assert strict["$defs"]["inner"]["additionalProperties"] is False
    assert loose["properties"]["n"]["minimum"] == 1  # the original is untouched
