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


def test_fudgewright_alone_runs_its_character_wakes_on_opus(monkeypatch):
    import yaml

    from hglab.persona import load_personas

    _keys(monkeypatch, anthropic=True, openai=False)
    selected = route_config("tick_opus", ROOT)
    assert selected == {"provider": "anthropic", "model": "claude-opus-5-5", "effort": "medium"}
    personas = load_personas(ROOT)
    on_opus = sorted(s for s, p in personas.items() if p.knobs.get("model_route") == "tick_opus")
    assert on_opus == ["navy", "wonka"]  # Fudgewright's riddle hunts and audits, and the Navy by the owner's instruction (2026-10-26) within its own daily allowance
    prices = yaml.safe_load((ROOT / "config/budget.yaml").read_text(encoding="utf-8"))["pricing_usd_per_mtok"]
    assert prices["claude-opus-5-5"]["input"] == 4.0 and prices["claude-opus-5-5"]["output"] == 20.0  # the spend ledger prices Opus calls
