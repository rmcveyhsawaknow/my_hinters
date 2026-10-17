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
