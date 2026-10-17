from pathlib import Path

from hglab.cli_personas import run_pulse
from hglab.measures import MEASURES, MeasureContext
from hglab.persona import load_personas, load_teams
from hglab.pulse import alive_gauge, bar, cron_fires_per_day, sparkline

ROOT = Path(__file__).parents[1]
EXAMPLES = ROOT / "reports/examples"


def test_pulse_snapshot_matches_committed_examples(tmp_path):
    """Regenerate every Pulse from fixtures and compare with reports/examples byte for byte.

    If this fails on purpose (a metric or renderer changed), regenerate with
    `hglab pulse --all --fixtures --out reports/examples --today 2026-10-17` and bump the
    metric spec version in the affected metrics.yaml.
    """
    out = tmp_path / "reports"
    pulses = run_pulse(ROOT, list(load_personas(ROOT)), fixtures=True, events_paths=[], runs_paths=[], fetch_public=False, judge=False, out=out, tick=None, today="2026-10-17")
    assert len(pulses) == len(load_personas(ROOT))
    for path in sorted(EXAMPLES.rglob("*.md")):
        relative = path.relative_to(EXAMPLES)
        generated = (out / relative).read_text(encoding="utf-8")
        assert generated == path.read_text(encoding="utf-8"), f"{relative} differs from the committed example"
    for slug, pulse in pulses.items():
        assert pulse["metric_version"] >= 1
        assert 0 <= pulse["alive"]["score"] <= 100
        assert "day" in (out / "agents" / slug / "pulse.md").read_text(encoding="utf-8").splitlines()[1]


def test_alive_is_one_formula_for_everyone():
    personas = load_personas(ROOT)
    teams = load_teams(ROOT)
    wonka = personas["wonka"]
    runs = [{"tick": 60000 + i * 1000, "verification": "ok"} for i in range(7)]
    ctx = MeasureContext(persona=wonka, team=teams["chocolate-factory"], personas=personas, events=[], runs=runs, now_tick=66000)
    healthy = alive_gauge(wonka, ctx)
    assert healthy["parts"]["completed"] == 7
    runs_banned = [dict(r, banned=True) for r in runs]
    ctx = MeasureContext(persona=wonka, team=teams["chocolate-factory"], personas=personas, events=[], runs=runs_banned, now_tick=66000)
    assert alive_gauge(wonka, ctx)["score"] == 0
    runs_lapsed = [dict(r, verification="lapsed") for r in runs]
    ctx = MeasureContext(persona=wonka, team=teams["chocolate-factory"], personas=personas, events=[], runs=runs_lapsed, now_tick=66000)
    assert alive_gauge(wonka, ctx)["score"] <= healthy["score"] - 20


def test_cron_counting_and_rendering_helpers():
    assert cron_fires_per_day("23 1,4,7,10,13,16,19,22 * * *") == 8
    assert cron_fires_per_day("41 */2 * * *") == 12
    assert cron_fires_per_day("7 2,8,14,20 * * *") == 4
    assert bar(100) == "██████████" and bar(0) == "░░░░░░░░░░" and len(bar(55)) == 10
    assert len(sparkline([0, 50, 100])) == 3


def test_every_metric_measure_is_registered():
    import yaml

    for path in (ROOT / "agents").glob("*/metrics.yaml"):
        spec = yaml.safe_load(path.read_text(encoding="utf-8"))
        for row in spec["key_results"] + spec["signatures"]:
            assert row["measure"] in MEASURES, (path, row["measure"])
