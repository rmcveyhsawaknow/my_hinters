from pathlib import Path

from hglab.data import load_events, load_runs
from hglab.influence import SIGNALS, compute_team, incoming_effects
from hglab.measures import MeasureContext, load_kb_items
from hglab.persona import KNOWN_SIGNALS, load_personas, load_teams

ROOT = Path(__file__).parents[1]
FIX = ROOT / "tests/fixtures"
NOW = 65760


def _inputs():
    personas = load_personas(ROOT)
    events = load_events([FIX / "world/events.jsonl"])
    runs = {s: load_runs(ROOT, p.name, s, [FIX / "runs" / f"{s}.jsonl"]) for s, p in personas.items()}
    return personas, events, runs


def test_every_known_signal_has_exactly_one_function():
    assert set(SIGNALS) == KNOWN_SIGNALS


def test_each_signal_is_bounded_and_explained_on_fixture_events():
    personas, events, runs = _inputs()
    teams = load_teams(ROOT)
    for team in teams.values():
        for slug in team.members:
            ctx = MeasureContext(persona=personas[slug], team=team, personas=personas, events=events, runs=runs[slug], now_tick=NOW, kb_items=load_kb_items(ROOT))
            for name in personas[slug].signals_emitted:
                result = SIGNALS[name](ctx)
                assert 0 <= result.value <= 100, (slug, name, result.value)
                assert result.explanation and name.title() in result.explanation or "Fairness" in result.explanation


def test_signals_tell_the_story_in_the_fixtures():
    personas, events, runs = _inputs()
    teams = load_teams(ROOT)
    factory = compute_team(teams["chocolate-factory"], personas, events, runs, NOW)
    neverland = compute_team(teams["neverland"], personas, events, runs, NOW)
    s = factory["signals"]
    assert s["mrs-bucket"]["hope"]["value"] > 0
    assert s["grandpa-joe"]["bluster"]["value"] > 0
    assert s["grandpa-joe"]["bluster"]["parts"]["share_of_team_work_claimed"] > 0
    assert s["wonka"]["audit"]["value"] == 100.0
    n = neverland["signals"]
    assert n["tootles"]["escape"]["value"] > 50  # he is far away
    assert n["tootles"]["belief"]["value"] == 0
    assert n["nibs"]["belief"]["value"] > n["lost-boy"]["belief"]["value"]
    assert n["nibs"]["courage"]["value"] > 0
    assert n["lost-boy"]["discoveries"]["parts"]["new_tiles"] >= 5


def test_effects_fold_links_with_weights_and_glow_starts_neutral():
    personas, events, runs = _inputs()
    teams = load_teams(ROOT)
    neverland = compute_team(teams["neverland"], personas, events, runs, NOW)
    effects = incoming_effects(neverland, "tinker-bell")
    expected = 50.0
    for link in neverland["links"]:
        if link["to"] == "tinker-bell" and link["effect"] == "glow":
            expected += link["weight"] * link["decayed_value"]
    assert effects["glow"]["value"] == round(max(0.0, min(100.0, expected)), 1)
    assert "escape" in effects and "courage" in effects  # raw signals kept for mood models
    resolve = incoming_effects(neverland, "nibs")["resolve"]["value"]
    assert resolve == round(0.5 * neverland["signals"]["tootles"]["escape"]["value"], 1)


def test_links_decay_with_age():
    personas, events, runs = _inputs()
    teams = load_teams(ROOT)
    fresh = compute_team(teams["chocolate-factory"], personas, events, runs, NOW)
    later = compute_team(teams["chocolate-factory"], personas, events, runs, NOW + 8640)
    hope_now = next(l for l in fresh["links"] if l["signal"] == "hope")["decayed_value"]
    hope_later = next(l for l in later["links"] if l["signal"] == "hope")["decayed_value"]
    assert hope_later < hope_now
