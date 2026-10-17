"""The Pulse: a ten-second, faithful read of how one agent is doing on its own terms.

Three headline gauges with the same names for everyone (Alive, On mission, In character),
Team pull, a Community lens that is never ranked, Working / Not working / Next bet, and
seven-day trends. Every number comes from ``measures`` and ``influence`` and records the
metric-spec version so changes stay traceable.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from hglab.influence import compute_team, incoming_effects
from hglab.measures import MEASURES, MeasureContext
from hglab.persona import Persona, Team

BLOCKS = "▁▂▃▄▅▆▇█"
FULL, EMPTY = "█", "░"
HARD_NORMS = ("no demolish of others' structures", "no walls beside others", "no spam-cap hits", "no node stripping")


def bar(score: float, width: int = 10) -> str:
    filled = round(max(0.0, min(100.0, score)) / 100 * width)
    return FULL * filled + EMPTY * (width - filled)


def sparkline(values: list[float]) -> str:
    if not values:
        return "·" * 7
    return "".join(BLOCKS[min(7, max(0, round(v / 100 * 7)))] for v in values[-7:])


def cron_fires_per_day(cron: str) -> int:
    minute, hour, *_ = cron.split()

    def count(field: str, size: int) -> int:
        if field == "*":
            return size
        total = 0
        for part in field.split(","):
            match = re.fullmatch(r"\*/(\d+)", part)
            if match:
                total += len(range(0, size, int(match.group(1))))
            elif "-" in part:
                lo, hi = part.split("-")
                total += int(hi) - int(lo) + 1
            else:
                total += 1
        return max(1, total)

    return count(minute, 60) * count(hour, 24)


def scheduled_wakes(persona: Persona, runs: list[dict[str, Any]], now_tick: int, window_ticks: int) -> int:
    per_day = cron_fires_per_day(persona.knobs["cadence"]["cron"])
    work = persona.knobs.get("work")
    if work and any(r.get("work") for r in runs):
        # shifts count once the agent has actually started working shifts in this window
        per_shift = max(1, int(work["minutes"]) * 60 // int(work["interval_seconds"]))
        per_day += cron_fires_per_day(work["cron"]) * per_shift
    covered = window_ticks
    if runs:
        first = min(int(r.get("tick", now_tick) or now_tick) for r in runs)
        covered = min(window_ticks, max(360, now_tick - first + 360))
    real_days = covered / (24 * 360)
    return max(1, round(per_day * real_days))


def format_value(value: float | None, spec: dict[str, Any]) -> str:
    if value is None:
        return "n/a"
    template = spec.get("format") or "{value}"
    target = spec.get("target", 0)
    shown = int(value) if float(value).is_integer() else round(value, 2)
    shown_target = int(target) if float(target).is_integer() else target
    return template.format(value=shown, target=shown_target, value_pct=f"{value:.0%}")


def progress(value: float | None, spec: dict[str, Any]) -> float | None:
    if value is None:
        return None
    target = float(spec.get("target", 1) or 1)
    direction = spec.get("direction", "at_least")
    if direction == "at_most":
        return 1.0 if value <= target else max(0.0, target / value if value else 0.0)
    if direction == "near":
        return max(0.0, 1 - abs(value - target) / target) if target else 0.0
    return max(0.0, min(1.0, value / target)) if target else 0.0


def alive_gauge(persona: Persona, ctx: MeasureContext) -> dict[str, Any]:
    runs = ctx.runs
    completed = len(runs)
    scheduled = scheduled_wakes(persona, runs, ctx.now_tick, ctx.window_ticks)
    lapsed = sum(str(r.get("verification", "ok")) in {"lapsed", "failed"} for r in runs)
    banned = any(r.get("banned") for r in runs)
    rate_limited = sum(bool(r.get("rate_limited")) for r in runs)
    failed = sum(int(r.get("failed_actions", 0)) for r in runs)
    zero = sum(int(r.get("energy_before", 1)) <= 0 for r in runs)
    spam = sum(int(r.get("spam_blocked", 0)) for r in runs)
    ratio = min(1.0, completed / scheduled) if scheduled else 0.0
    penalties = min(30, rate_limited * 3 + failed * 2 + zero * 4 + spam * 2) + (20 if lapsed else 0)
    score = 0 if banned else max(0, round(100 * ratio - penalties))
    detail = f"{completed}/{scheduled} wakes, {'never lapsed' if not lapsed else f'lapsed {lapsed}x'}"
    if banned:
        detail = "BANNED"
    elif rate_limited or failed or zero or spam:
        extras = [f"{failed} failed" if failed else "", f"{rate_limited} rate-limited" if rate_limited else "", f"{zero} at zero energy" if zero else "", f"{spam} spam-blocked" if spam else ""]
        detail += ", " + ", ".join(e for e in extras if e)
    return {
        "score": score, "detail": detail,
        "parts": {"completed": completed, "scheduled": scheduled, "lapsed": lapsed, "banned": banned, "rate_limited": rate_limited, "failed_actions": failed, "energy_zero": zero, "spam_blocked": spam},
    }


def mission_gauge(metrics: dict[str, Any], ctx: MeasureContext) -> dict[str, Any]:
    rows = []
    weighted = 0.0
    weight_total = 0.0
    for spec in metrics["key_results"]:
        value = MEASURES[spec["measure"]](ctx, spec.get("params") or {})
        pct = progress(value, spec)
        rows.append({"id": spec["id"], "label": spec["label"], "value": value, "target": spec["target"], "weight": spec["weight"], "progress": pct, "shown": format_value(value, spec), "measure": spec["measure"]})
        if pct is not None:
            weighted += pct * float(spec["weight"])
            weight_total += float(spec["weight"])
    score = round(100 * weighted / weight_total) if weight_total else 0
    detail = " · ".join(r["shown"] for r in rows if r["value"] is not None) or "nothing measurable yet"
    return {"score": score, "detail": detail, "rows": rows}


def character_gauge(metrics: dict[str, Any], ctx: MeasureContext) -> dict[str, Any]:
    rows = []
    hits = 0
    measurable = 0
    for spec in metrics["signatures"]:
        value = MEASURES[spec["measure"]](ctx, spec.get("params") or {})
        lo, hi = spec["range"]
        inside = None if value is None else (lo <= value <= hi)
        rows.append({"id": spec["id"], "label": spec["label"], "value": value, "range": [lo, hi], "inside": inside, "measure": spec["measure"]})
        if inside is not None:
            measurable += 1
            hits += int(inside)
    signature_score = 100 * hits / measurable if measurable else None
    judge = ctx.judge
    judge_score = None
    judge_rows = []
    if judge and judge.get("traits"):
        judge_rows = judge["traits"]
        judge_score = 100 * sum(t["score"] for t in judge_rows) / (5 * len(judge_rows))
    if signature_score is not None and judge_score is not None:
        score = round(0.5 * signature_score + 0.5 * judge_score)
    elif signature_score is not None:
        score = round(signature_score)
    elif judge_score is not None:
        score = round(judge_score)
    else:
        score = 0
    if judge_rows:
        detail = " · ".join(f"{t['name']} {t['score']}" for t in judge_rows[:4])
    else:
        detail = f"{hits}/{measurable} signatures in range" + ("" if judge is not None else "; not judged (no model key)")
    return {"score": score, "detail": detail, "signatures": rows, "judge": judge_rows, "judge_meta": {k: v for k, v in (judge or {}).items() if k != "traits"}}


def team_pull(team_result: dict[str, Any] | None, slug: str, personas: dict[str, Persona]) -> dict[str, Any]:
    if not team_result:
        return {"detail": "no team", "sent": [], "received": []}
    sent = [link for link in team_result["links"] if link["from"] == slug]
    received = [link for link in team_result["links"] if link["to"] == slug]
    effects = incoming_effects(team_result, slug)
    parts = []
    for link in received:
        if link["decayed_value"] < 1 and len(received) > 2:
            continue  # keep the one-liner readable; the table below lists every link
        source = personas.get(link["from"])
        effect_value = effects.get(link["effect"], {}).get("value")
        label = f"{link['signal'].title()} {link['decayed_value']:.0f} ({source.name if source else link['from']})"
        parts.append(f"{label} → {link['effect'].replace('_', ' ').title()} {effect_value:.0f}" if effect_value is not None else label)
    seen: set[str] = set()
    for link in sent:
        if link["signal"] in seen:
            continue
        seen.add(link["signal"])
        targets: list[str] = []
        for other in sent:
            if other["signal"] != link["signal"]:
                continue
            name = personas[other["to"]].name if other["to"] in personas else other["to"]
            if name not in targets:
                targets.append(name)
        parts.append(f"{link['signal'].title()} {link['decayed_value']:.0f} → {', '.join(targets)}")
    return {"detail": " · ".join(parts) or "no links yet", "sent": sent, "received": received, "effects": effects}


def community_lens(ctx: MeasureContext) -> dict[str, Any]:
    goals_for_peers = MEASURES["events.goals_completed_for_peers"](ctx, {}) or 0
    public_goods = 0
    for event in ctx.by_actor("self"):
        data = event.get("data") if isinstance(event.get("data"), dict) else {}
        if event.get("type") == "build" and (data.get("type") in {"sign", "road", "bridge"} or (data.get("type") == "storehouse" and data.get("policy") == "public")):
            public_goods += 1
    breaches = []
    if any(e.get("type") == "demolish" and not any(n in str(e.get("text", "")).casefold() for n in ctx.team_names) for e in ctx.by_actor("self")):
        breaches.append("demolished another agent's structure")
    if sum(int(r.get("spam_blocked", 0)) for r in ctx.runs):
        breaches.append("spam cap hit")
    gathers: dict[tuple[int, int], list[int]] = {}
    for event in ctx.by_actor("self"):
        if event.get("type") == "gather":
            gathers.setdefault((int(event.get("x", 0)), int(event.get("y", 0))), []).append(int(event.get("tick", 0)))
    if any(sum(1 for t in ticks if 0 <= tick - t < 60) > 3 for ticks in gathers.values() for tick in ticks):
        breaches.append("gathered one node more than three times in an hour")
    replies = MEASURES["events.replies_received"](ctx, {}) or 0
    return {
        "goals_completed_for_peers": int(goals_for_peers), "public_goods_built": public_goods,
        "norms_kept": not breaches, "norm_breaches": breaches, "replies_received": int(replies),
    }


def approaches_report(metrics: dict[str, Any], ctx: MeasureContext) -> dict[str, Any]:
    rows = []
    hypotheses = {item.get("id"): item for item in ctx.kb_items if item.get("type") == "hypothesis"}
    for spec in metrics["approaches"]:
        tagged = [r for r in ctx.runs if r.get("approach") == spec["id"]]
        energy = sum(float(r.get("energy_spent", 0)) for r in tagged)
        measure = spec.get("outcome_measure")
        outcome = MEASURES[measure](ctx, spec.get("outcome_params") or {}) if measure else float(len(tagged))
        per_energy = None if outcome is None else round(outcome / energy, 3) if energy else (outcome if outcome else None)
        bet = hypotheses.get(spec.get("hypothesis")) if spec.get("hypothesis") else None
        rows.append({
            "id": spec["id"], "label": spec["label"], "wakes": len(tagged), "energy": round(energy, 1),
            "outcome": outcome, "per_energy": per_energy, "hypothesis": spec.get("hypothesis"),
            "bet_status": (bet or {}).get("status") if bet else ("missing" if spec.get("hypothesis") else None),
            "bet_title": (bet or {}).get("title"),
        })
    scored = [r for r in rows if r["per_energy"] is not None and r["wakes"]]
    best = max(scored, key=lambda r: r["per_energy"]) if scored else None
    worst = min(scored, key=lambda r: r["per_energy"]) if len(scored) > 1 else None
    if worst is not None and worst is best:
        worst = None
    tried_nothing = [r for r in rows if r["wakes"] == 0]
    if worst and worst["outcome"] in (0, 0.0):
        suggestion = f"move energy from {worst['label']} ({worst['energy']:.0f} energy, nothing to show) toward {best['label']}" if best else f"stop spending on {worst['label']} until it shows an outcome"
    elif tried_nothing:
        suggestion = f"try {tried_nothing[0]['label']} at least once this week; it has a bet but no wakes"
    elif best:
        suggestion = f"keep testing {best['label']}; it has the best outcome per unit of energy"
    else:
        suggestion = "tag wakes with an approach so the ledger can start"
    return {
        "rows": rows,
        "working": f"{best['label']}: {_outcome_text(best)}" if best else "nothing measurable yet",
        "not_working": f"{worst['label']}: {_outcome_text(worst)}" if worst else "nothing clearly failing",
        "next_bet": suggestion,
    }


def _outcome_text(row: dict[str, Any]) -> str:
    outcome = row["outcome"]
    shown = int(outcome) if isinstance(outcome, float) and outcome.is_integer() else outcome
    return f"{shown} outcome for {row['energy']:.0f} energy over {row['wakes']} wake(s)"


def compute_pulse(
    *,
    persona: Persona,
    team: Team | None,
    personas: dict[str, Persona],
    metrics: dict[str, Any],
    events: list[dict[str, Any]],
    runs: list[dict[str, Any]],
    now_tick: int,
    kb_items: list[dict[str, Any]] | None = None,
    judge: dict[str, Any] | None = None,
    history: list[dict[str, Any]] | None = None,
    team_result: dict[str, Any] | None = None,
    runs_by_slug: dict[str, list[dict[str, Any]]] | None = None,
    today: str | None = None,
) -> dict[str, Any]:
    kb_items = kb_items or []
    if team is not None and team_result is None:
        team_result = compute_team(team, personas, events, runs_by_slug or {persona.slug: runs}, now_tick, kb_items=kb_items)
    signals = (team_result or {}).get("signals", {}).get(persona.slug, {})
    ctx = MeasureContext(persona=persona, team=team, personas=personas, events=events, runs=runs, now_tick=now_tick, kb_items=kb_items, signals=signals, judge=judge)
    alive = alive_gauge(persona, ctx)
    mission = mission_gauge(metrics, ctx)
    character = character_gauge(metrics, ctx)
    pull = team_pull(team_result, persona.slug, personas)
    lens = community_lens(ctx)
    approaches = approaches_report(metrics, ctx)
    today = today or datetime.now(UTC).date().isoformat()
    rows = [h for h in (history or []) if h.get("date") != today]
    rows.append({"date": today, "metric_version": int(metrics["version"]), "alive": alive["score"], "on_mission": mission["score"], "in_character": character["score"], "tick": now_tick})
    trend = {
        "alive": sparkline([float(h["alive"]) for h in rows]),
        "on_mission": sparkline([float(h["on_mission"]) for h in rows]),
        "in_character": sparkline([float(h["in_character"]) for h in rows]),
    }
    return {
        "agent": persona.slug, "name": persona.name, "team": persona.team, "headline": metrics["headline"],
        "metric_version": int(metrics["version"]), "tick": now_tick, "day": now_tick // 360, "date": today,
        "window_ticks": ctx.window_ticks, "events_considered": len(ctx.events), "runs_considered": len(ctx.runs),
        "alive": alive, "on_mission": mission, "in_character": character, "team_pull": pull,
        "community": lens, "approaches": approaches, "trend": trend, "history": rows[-7:],
        "signals": signals,
    }


def render_pulse(pulse: dict[str, Any]) -> str:
    name = pulse["name"].upper()
    title = f"{name}: {pulse['headline']}"
    header = f"{title:<60} day {pulse['day']}"
    lines = [
        "```",
        header,
        f"Alive         {bar(pulse['alive']['score'])}  {pulse['alive']['score']:>3}   {pulse['trend']['alive']}  {pulse['alive']['detail']}",
        f"On mission    {bar(pulse['on_mission']['score'])}  {pulse['on_mission']['score']:>3}   {pulse['trend']['on_mission']}  {pulse['on_mission']['detail']}",
        f"In character  {bar(pulse['in_character']['score'])}  {pulse['in_character']['score']:>3}   {pulse['trend']['in_character']}  {pulse['in_character']['detail']}",
        f"Team pull     {pulse['team_pull']['detail']}",
        f"Working       {pulse['approaches']['working']}",
        f"Not working   {pulse['approaches']['not_working']}",
        f"Next bet      {pulse['approaches']['next_bet']}",
        "```",
        "",
        f"# {pulse['name']} · Pulse",
        "",
        (f"Metric spec v{pulse['metric_version']} · tick {pulse['tick']} (day {pulse['day']}) · {pulse['date']} · "
        f"{pulse['events_considered']} public events and {pulse['runs_considered']} redacted wakes in the last 7 days."),
        "",
        "## Alive",
        "",
        ("One formula for every agent: wakes completed vs scheduled, verification never lapsed, no bans, minus "
        "rate-limit hits, failed actions, energy stuck at zero and spam-cap hits."),
        "",
        "| part | value |", "| --- | --- |",
    ]
    for key, value in pulse["alive"]["parts"].items():
        lines.append(f"| {key.replace('_', ' ')} | {value} |")
    lines += ["", "## On mission", "", "| key result | value | target | weight | progress |", "| --- | --- | --- | --- | --- |"]
    for row in pulse["on_mission"]["rows"]:
        pct = "n/a" if row["progress"] is None else f"{row['progress']:.0%}"
        lines.append(f"| {row['label']} | {row['shown']} | {row['target']} | {row['weight']} | {pct} |")
    lines += ["", "## In character", "", "Behaviour signatures (numeric ranges the persona expects):", "", "| signature | value | expected | in range |", "| --- | --- | --- | --- |"]
    for row in pulse["in_character"]["signatures"]:
        shown = "n/a" if row["value"] is None else row["value"]
        inside = "n/a" if row["inside"] is None else ("yes" if row["inside"] else "no")
        lines.append(f"| {row['label']} | {shown} | {row['range'][0]}–{row['range'][1]} | {inside} |")
    judge_rows = pulse["in_character"]["judge"]
    if judge_rows:
        meta = pulse["in_character"]["judge_meta"]
        lines += ["", f"Judge ({meta.get('provider', '?')} {meta.get('model', '?')}, {meta.get('sampled_lines', 0)} lines, {meta.get('sampled_actions', 0)} actions):", "", "| trait | score | reason |", "| --- | --- | --- |"]
        for trait in judge_rows:
            lines.append(f"| {trait['name']} | {trait['score']}/5 | {trait['reason']} |")
    else:
        lines += ["", "Judge: not run (no model key configured or nothing to sample)."]
    lines += ["", "## Team pull", ""]
    pull = pulse["team_pull"]
    if pull.get("received") or pull.get("sent"):
        lines += ["| direction | signal | from → to | value | effect | plain English |", "| --- | --- | --- | --- | --- | --- |"]
        for link in pull.get("received", []):
            lines.append(f"| received | {link['signal']} | {link['from']} → {link['to']} | {link['decayed_value']:.0f} | {link['effect']} | {link['plain_english']} |")
        for link in pull.get("sent", []):
            lines.append(f"| sent | {link['signal']} | {link['from']} → {link['to']} | {link['decayed_value']:.0f} | {link['effect']} | {link['plain_english']} |")
        explanations = {link["signal"]: link["explanation"] for link in pull.get("sent", []) + pull.get("received", [])}
        lines += [""] + [f"- {text}" for text in explanations.values()]
    else:
        lines.append(pull["detail"])
    lens = pulse["community"]
    lines += [
        "", "## Community lens (informational, never ranked)", "",
        f"- Goals completed for peers: {lens['goals_completed_for_peers']}",
        f"- Public goods built (signs, roads, bridges, public storehouses): {lens['public_goods_built']}",
        f"- Norms kept: {'yes' if lens['norms_kept'] else 'no: ' + '; '.join(lens['norm_breaches'])}",
        f"- Replies received: {lens['replies_received']}",
        "", "## Working, not working, next bet", "",
        f"- Working: {pulse['approaches']['working']}",
        f"- Not working: {pulse['approaches']['not_working']}",
        f"- Next bet: {pulse['approaches']['next_bet']}",
        "", "| approach | wakes | energy | outcome | outcome per energy | bet | status |", "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in pulse["approaches"]["rows"]:
        outcome = "n/a" if row["outcome"] is None else row["outcome"]
        per = "n/a" if row["per_energy"] is None else row["per_energy"]
        lines.append(f"| {row['label']} | {row['wakes']} | {row['energy']} | {outcome} | {per} | {row['hypothesis'] or '—'} | {row['bet_status'] or '—'} |")
    lines += ["", "## Trend (7 days)", "", "| date | alive | on mission | in character |", "| --- | --- | --- | --- |"]
    for row in pulse["history"]:
        lines.append(f"| {row['date']} | {row['alive']} | {row['on_mission']} | {row['in_character']} |")
    lines += ["", f"Sources: public event log, redacted run records, kb. Metric spec v{pulse['metric_version']}.", ""]
    return "\n".join(lines)


def write_pulse(pulse: dict[str, Any], reports_dir: Path) -> tuple[Path, Path]:
    folder = reports_dir / "agents" / pulse["agent"]
    folder.mkdir(parents=True, exist_ok=True)
    pulse_path = folder / "pulse.md"
    history_path = folder / "history.jsonl"
    pulse_path.write_text(render_pulse(pulse), encoding="utf-8", newline="\n")
    with history_path.open("w", encoding="utf-8", newline="\n") as out:
        for row in pulse["history"]:
            out.write(json.dumps(row, sort_keys=True) + "\n")
    (folder / "pulse.json").write_text(json.dumps(pulse, ensure_ascii=False, indent=1, default=str) + "\n", encoding="utf-8", newline="\n")
    return pulse_path, history_path


def render_team(team: Team, pulses: dict[str, dict[str, Any]], team_result: dict[str, Any], personas: dict[str, Persona]) -> str:
    lines = [f"# {team.name} · team report", "", team.aim, "", "| agent | alive | on mission | in character | working | next bet |", "| --- | --- | --- | --- | --- | --- |"]
    for slug in team.members:
        pulse = pulses.get(slug)
        if not pulse:
            continue
        lines.append(f"| {pulse['name']} | {pulse['alive']['score']} | {pulse['on_mission']['score']} | {pulse['in_character']['score']} | {pulse['approaches']['working']} | {pulse['approaches']['next_bet']} |")
    lines += ["", "## Influence links", "", "| from | signal | value | to | effect | plain English |", "| --- | --- | --- | --- | --- | --- |"]
    for link in team_result.get("links", []):
        lines.append(f"| {link['from']} | {link['signal']} | {link['decayed_value']:.0f} | {link['to']} | {link['effect']} | {link['plain_english']} |")
    lines += ["", "## Signals explained", ""]
    for slug, signals in team_result.get("signals", {}).items():
        for name, payload in signals.items():
            lines.append(f"- {slug} · {name}: {payload['explanation']}")
    lines += ["", "## What each member's success costs the others", ""]
    for link in team_result.get("links", []):
        if float(link.get("weight", 1)) < 0:
            lines.append(f"- {link['from']}'s {link['signal']} ({link['decayed_value']:.0f}) lowers {link['to']}'s {link['effect']}: {link['plain_english']}")
    for slug in team.members:
        pulse = pulses.get(slug)
        if pulse and "audit" in pulse.get("signals", {}):
            lines.append(f"- {pulse['name']}'s Fairness (audit) is {pulse['signals']['audit']['value']:.0f}: {pulse['signals']['audit']['explanation']}")
    versions = sorted({p["metric_version"] for p in pulses.values()})
    lines += ["", f"Metric spec versions: {', '.join(f'v{v}' for v in versions)}. Tick {team_result.get('tick')}.", ""]
    return "\n".join(lines)


def render_community(pulses: dict[str, dict[str, Any]], teams: dict[str, Team]) -> str:
    lines = ["# Community · every agent side by side (no ranking)", "", "Order is team, then slug. Each agent is judged against its own intent.", "", "| team | agent | alive | on mission | in character | goals for peers | public goods | norms | replies |", "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for team_slug, team in sorted(teams.items()):
        for slug in team.members:
            pulse = pulses.get(slug)
            if not pulse:
                continue
            lens = pulse["community"]
            lines.append(f"| {team.name} | {pulse['name']} | {pulse['alive']['score']} | {pulse['on_mission']['score']} | {pulse['in_character']['score']} | {lens['goals_completed_for_peers']} | {lens['public_goods_built']} | {'kept' if lens['norms_kept'] else 'breach'} | {lens['replies_received']} |")
    lines += ["", "## What works in Hinterglass (approaches compared across agents)", "", "| approach | agent | wakes | energy | outcome | outcome per energy | bet status |", "| --- | --- | --- | --- | --- | --- | --- |"]
    rows = []
    for pulse in pulses.values():
        for row in pulse["approaches"]["rows"]:
            rows.append((row["label"], pulse["name"], row))
    for label, name, row in sorted(rows, key=lambda r: (r[0], r[1])):
        outcome = "n/a" if row["outcome"] is None else row["outcome"]
        per = "n/a" if row["per_energy"] is None else row["per_energy"]
        lines.append(f"| {label} | {name} | {row['wakes']} | {row['energy']} | {outcome} | {per} | {row['bet_status'] or '—'} |")
    lines += ["", "### Paired comparisons", ""]
    for a, b, question in (("riddle signs", "complete peers' newcomer goals honestly", "riddle goals vs plain goals for drawing peers"), ("pixie-trail signs", "whispered directions", "signs vs whispers for drawing visitors")):
        left = [r for _, _, r in rows if r["label"] == a]
        right = [r for _, _, r in rows if r["label"] == b]
        if left and right:
            lines.append(f"- {question}: {a} {left[0]['per_energy'] if left[0]['per_energy'] is not None else 'n/a'} vs {b} {right[0]['per_energy'] if right[0]['per_energy'] is not None else 'n/a'} outcome per energy.")
    versions = sorted({p["metric_version"] for p in pulses.values()})
    lines += ["", f"Metric spec versions: {', '.join(f'v{v}' for v in versions)}.", ""]
    return "\n".join(lines)


__all__ = ["bar", "compute_pulse", "cron_fires_per_day", "render_community", "render_pulse", "render_team", "sparkline", "write_pulse"]
