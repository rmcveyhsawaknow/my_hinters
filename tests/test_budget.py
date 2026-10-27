from datetime import UTC, datetime
from pathlib import Path

from hglab.budget import call_cost, projected_month, status

ROOT = Path(__file__).parents[1]
PRICING = {"claude-haiku-5-5": {"input": 0.10, "output": 0.50}, "claude-sonnet-5-5": {"input": 2.0, "output": 10.0}}


def test_call_cost_prices_known_models_and_charges_unknown_at_the_top_rate():
    haiku = call_cost({"model": "claude-haiku-5-5", "input_tokens": 1_000_000, "output_tokens": 100_000}, PRICING)
    assert abs(haiku - 0.15) < 1e-9
    unknown = call_cost({"model": "mystery", "input_tokens": 1_000_000, "output_tokens": 0}, PRICING)
    assert unknown == 2.0


def test_status_sums_this_month_and_today_and_flags_the_cap():
    now = datetime(2026, 10, 17, 20, tzinfo=UTC)
    records = [
        {"run_id": "a", "created_utc": "2026-10-17T10:00:00+00:00", "usage": {"calls": 1, "model": "claude-sonnet-5-5", "input_tokens": 1_000_000, "output_tokens": 0}},
        {"run_id": "b", "created_utc": "2026-10-02T10:00:00+00:00", "usage": {"calls": 1, "model": "claude-sonnet-5-5", "input_tokens": 1_000_000, "output_tokens": 0}},
        {"run_id": "c", "created_utc": "2026-09-30T10:00:00+00:00", "usage": {"calls": 1, "model": "claude-sonnet-5-5", "input_tokens": 50_000_000, "output_tokens": 0}},
        {"run_id": "d", "created_utc": "2026-10-17T11:00:00+00:00", "usage": {"calls": 0, "input_tokens": 0, "output_tokens": 0}},
    ]
    state = status(ROOT, now=now, records=records)
    assert state.month_usd == 4.0 and state.today_usd == 2.0 and state.calls == 2
    assert not state.over
    heavy = [{"run_id": "x", "created_utc": "2026-10-17T12:00:00+00:00", "usage": {"calls": 1, "model": "claude-sonnet-5-5", "input_tokens": 60_000_000, "output_tokens": 0}}]
    state = status(ROOT, now=now, records=heavy)
    assert state.over and "monthly cap" in state.reason


def test_projection_stays_well_under_the_monthly_cap():
    totals = projected_month(ROOT)
    assert 0 < totals["total"] < 100  # under the monthly cap, the Navy's model wakes bounded by its own allowance (2026-10-26; before it, under 60)
    from hglab.persona import load_personas

    navy = load_personas(ROOT)["navy"]
    assert totals["ticks:navy:claude-sonnet-5-5"] <= float(navy.knobs["max_usd_daily"]) * 30  # Sonnet 5.5 since 2026-10-27
