"""Spend ledger and caps for model calls.

Every run record, keepalive record and judge file carries ``usage`` with token counts and
the model that produced them. This module prices those from ``config/budget.yaml`` and
compares month-to-date and today's spend against the caps. When a cap is hit, planners
fall back to the deterministic path and the judge is skipped; verification challenges are
always allowed (one small call, and lapsing costs more than it saves).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml


@dataclass
class BudgetStatus:
    month_usd: float
    today_usd: float
    monthly_cap_usd: float
    daily_cap_usd: float
    calls: int
    by_model: dict[str, float]

    @property
    def over(self) -> bool:
        return self.month_usd >= self.monthly_cap_usd or self.today_usd >= self.daily_cap_usd

    @property
    def reason(self) -> str:
        if self.month_usd >= self.monthly_cap_usd:
            return f"monthly cap reached (${self.month_usd:.2f} of ${self.monthly_cap_usd:.2f})"
        if self.today_usd >= self.daily_cap_usd:
            return f"daily cap reached (${self.today_usd:.2f} of ${self.daily_cap_usd:.2f})"
        return ""


def load_budget(root: Path) -> dict[str, Any]:
    return yaml.safe_load((root / "config/budget.yaml").read_text(encoding="utf-8"))


def call_cost(usage: dict[str, Any], pricing: dict[str, dict[str, float]]) -> float:
    """Price one usage block; unknown models are priced at the most expensive known rate."""
    model = str(usage.get("model") or "")
    if not pricing:
        return 0.0
    rates = pricing.get(model) or max(pricing.values(), key=lambda r: float(r.get("input", 0)))
    input_tokens = float(usage.get("input_tokens", 0) or 0)
    output_tokens = float(usage.get("output_tokens", 0) or 0)
    cached = float(usage.get("cache_read_input_tokens", 0) or 0)
    cost = (input_tokens - cached) / 1e6 * float(rates.get("input", 0))
    cost += cached / 1e6 * float(rates.get("cache_read", rates.get("input", 0) * 0.1))
    cost += output_tokens / 1e6 * float(rates.get("output", 0))
    return max(0.0, cost)


def _created(record: dict[str, Any]) -> datetime | None:
    raw = record.get("created_utc")
    if not isinstance(raw, str):
        return None
    try:
        value = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def usage_records(root: Path) -> list[dict[str, Any]]:
    """Every local or pulled record that carries a usage block."""
    folders = [root / "runs", root / "reports/agents"]
    records: dict[str, dict[str, Any]] = {}
    for folder in folders:
        if not folder.is_dir():
            continue
        for path in folder.rglob("*.json"):
            if path.name in {"pulse.json"}:
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if isinstance(data, dict) and isinstance(data.get("usage"), dict) and data.get("created_utc"):
                key = str(data.get("run_id") or path.resolve())
                records[key] = data
    return list(records.values())


def status(root: Path, now: datetime | None = None, records: list[dict[str, Any]] | None = None) -> BudgetStatus:
    now = now or datetime.now(UTC)
    budget = load_budget(root)
    pricing = budget.get("pricing_usd_per_mtok", {})
    caps = budget.get("caps", {})
    month_usd = today_usd = 0.0
    calls = 0
    by_model: dict[str, float] = {}
    for record in records if records is not None else usage_records(root):
        created = _created(record)
        if created is None or created.year != now.year or created.month != now.month:
            continue
        usage = record["usage"]
        if not usage.get("calls") and not usage.get("input_tokens"):
            continue
        cost = call_cost(usage, pricing)
        month_usd += cost
        calls += int(usage.get("calls", 1) or 1)
        model = str(usage.get("model") or "unknown")
        by_model[model] = by_model.get(model, 0.0) + cost
        if created.date() == now.date():
            today_usd += cost
    return BudgetStatus(
        month_usd=round(month_usd, 4), today_usd=round(today_usd, 4),
        monthly_cap_usd=float(caps.get("monthly_usd", 100)), daily_cap_usd=float(caps.get("daily_usd", 6)),
        calls=calls, by_model={k: round(v, 4) for k, v in by_model.items()},
    )


def projected_month(root: Path) -> dict[str, float]:
    """Rough monthly projection from cadences and the configured routes (no network)."""
    from hglab.persona import load_personas
    from hglab.pulse import cron_fires_per_day

    budget = load_budget(root)
    pricing = budget.get("pricing_usd_per_mtok", {})
    models = yaml.safe_load((root / "config/models.yaml").read_text(encoding="utf-8"))["routes"]
    estimate = budget.get("estimate", {"tick_input_tokens": 11000, "tick_output_tokens": 400, "judge_input_tokens": 3000, "judge_output_tokens": 300, "challenge_input_tokens": 400, "challenge_output_tokens": 120})
    totals: dict[str, float] = {}
    for persona in load_personas(root).values():
        route = persona.knobs.get("model_route", "tick")
        model = models.get(route, models["tick"])["model"]
        wakes = cron_fires_per_day(persona.knobs["cadence"]["cron"]) * 30 * (1 - float(persona.knobs["rest_probability"]))
        cost = wakes * call_cost({"model": model, "input_tokens": estimate["tick_input_tokens"], "output_tokens": estimate["tick_output_tokens"]}, pricing)
        totals[f"ticks:{persona.slug}:{model}"] = round(cost, 2)
    judge_model = models["review"]["model"]
    totals[f"judge:{judge_model}"] = round(7 * 30 * call_cost({"model": judge_model, "input_tokens": estimate["judge_input_tokens"], "output_tokens": estimate["judge_output_tokens"]}, pricing), 2)
    challenge_model = models["challenge"]["model"]
    totals[f"challenges:{challenge_model}"] = round(7 * 30 * call_cost({"model": challenge_model, "input_tokens": estimate["challenge_input_tokens"], "output_tokens": estimate["challenge_output_tokens"]}, pricing), 2)
    talk_model = models.get("talk", models["tick"])["model"]
    shifts_per_month = sum(cron_fires_per_day(p.knobs["work"]["cron"]) * 30 for p in load_personas(root).values() if p.knobs.get("work"))
    totals[f"shift lines:{talk_model}"] = round(shifts_per_month * call_cost({"model": talk_model, "input_tokens": estimate.get("talk_input_tokens", 1800), "output_tokens": estimate.get("talk_output_tokens", 60)}, pricing), 2)
    totals["total"] = round(sum(totals.values()), 2)
    return totals


__all__ = ["BudgetStatus", "call_cost", "load_budget", "projected_month", "status", "usage_records"]
