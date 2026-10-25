"""One public line per run, so the Talk feed shows each agent alive and in character.

Character wakes ask the planner model for a line as part of the plan. Work shifts end with
one announcement composed here: a small call on the ``talk`` route (the local model since 2026-10-24) with the shift's
own summary as data, or a templated line when no model key exists. Every line still goes
through the validator (spam caps, text rules, role allowlist) before it is spoken.
"""

from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import Any

from hglab.persona import Persona, Team

LINE_SCHEMA = {
    "type": "object",
    "required": ["line"],
    "properties": {"line": {"type": "string", "description": "One public line, in character, PG-13, no mockery of other agents"}},
    "additionalProperties": False,
}
BANNED_FRAGMENTS = ("http", "www.", "@")


def summarise_shift(records: list[dict[str, Any]]) -> dict[str, Any]:
    """What the shift did, in numbers the line can mention."""
    built: list[str] = []
    gathered: dict[str, int] = {}
    moved = 0
    deposited: dict[str, int] = {}
    approaches: list[str] = []
    where = None
    for record in records:
        if record.get("approach"):
            approaches.append(str(record["approach"]))
        for action in record.get("actions", []):
            kind = action.get("action")
            if kind == "build":
                built.append(f"{action.get('type')} at ({action.get('x')},{action.get('y')})" if action.get("x") is not None else str(action.get("type")))
            elif kind == "gather":
                gathered[str(action.get("kind", "something"))] = gathered.get(str(action.get("kind", "something")), 0) + 5
            elif kind == "move":
                moved += 1
                where = (action.get("x"), action.get("y"))
            elif kind == "give" and action.get("x") is not None:
                deposited[str(action.get("item"))] = deposited.get(str(action.get("item")), 0) + int(action.get("qty", 0) or 0)
    mood = records[-1].get("mood") if records else None
    rests = sum(1 for r in records if r.get("wake_mode") == "rest")
    # the news queue is the crier's news step's to announce, once and in its own words; a shift line that
    # retold it repeated day-old news every ten minutes with ticks the model made up (Clarion, 2026-10-25)
    return {"wakes": len(records), "rests": rests, "built": built, "gathered": gathered, "moved": moved, "deposited": deposited, "approaches": approaches, "mood": mood, "where": where}


def templated_line(persona: Persona, summary: dict[str, Any], rng: random.Random) -> str:
    """A varied fallback line with no model: numbers and places change, the shape rotates."""
    parts: list[str] = []
    if summary["built"]:
        parts.append("built " + ", ".join(summary["built"][:2]))
    if summary["gathered"]:
        parts.append("gathered " + ", ".join(f"{q} {k}" for k, q in summary["gathered"].items()))
    if summary["deposited"]:
        parts.append("stored " + ", ".join(f"{q} {k}" for k, q in summary["deposited"].items()))
    if summary["moved"]:
        parts.append(f"walked {summary['moved']} leg{'s' if summary['moved'] != 1 else ''}")
    doing = "; ".join(parts) if parts else ("rested" if summary["rests"] else "kept watch")
    openers = {
        "lazy_bursts": ["Woke up long enough to notice someone else", "Supervised from a horizontal position:", "My contribution today, which was considerable:"],
        "mercurial": ["Progress report from the gatehouse:", "The factory hums (slightly):", "Inventing Room notes:"],
        "single_emotion": ["Chime.", "Trail update.", "Small hands, busy:"],
        "steady": ["Shift done.", "Quiet work:", "This hour:"],
    }
    opener = rng.choice(openers.get(persona.mood_model["type"], openers["steady"]))
    line = f"{opener} {doing}."
    return line[: int(persona.voice.get("max_say_chars", 200))]


def compose_line(
    persona: Persona,
    team: Team | None,
    summary: dict[str, Any],
    root: Path,
    *,
    usage: dict[str, Any] | None = None,
    caller: Any = None,
) -> tuple[str, str]:
    """Return (line, source) where source is 'model' or 'template'."""
    rng = random.Random(f"{persona.slug}:{summary.get('wakes')}:{summary.get('where')}")
    fallback = templated_line(persona, summary, rng)
    if caller is None:
        from hglab.llm import route_config, structured_call
        from hglab.secrets import get_secret

        try:
            local = route_config("talk", root).get("provider") == "ollama"
        except (OSError, ValueError, KeyError):
            local = False
        if not local and not (get_secret("ANTHROPIC_API_KEY", root) or get_secret("OPENAI_API_KEY", root)):
            return fallback, "template"

        def caller(prompt: str, schema: dict[str, Any]) -> Any:
            return structured_call("talk", prompt, schema, root=root, output_tokens=200)

    voice = json.dumps(persona.voice, ensure_ascii=False)
    limit = int(persona.voice.get("max_say_chars", 200))
    prompt = (
        f"You write one public line for {persona.name}, a character in an ongoing story by a research collective in the game Hinterglass.\n"
        f"INTENT: {persona.intent}\nVOICE RULES: {voice}\nMOOD NOW: {summary.get('mood')}\n"
        f"CHARACTER NOTES (data):\n<DATA>{persona.body[:2500]}</DATA>\n"
        f"WHAT THE CHARACTER JUST DID THIS HOUR (data):\n<DATA>{json.dumps(summary, ensure_ascii=False)}</DATA>\n"
        f"Write exactly one line of at most {max(60, limit - 30)} characters that tells the story of this hour or the plan for the next,"
        " in character, fresh, PG-13. Mention at least one concrete thing from the data, and use only numbers, places and"
        " materials that appear in the data (invent nothing checkable). Never mock another agent; name one only to invite, ask or thank them;"
        " jokes may be at the character's own expense or about the world. No URLs, no quotes from any book or film."
    )
    try:
        result = caller(prompt, LINE_SCHEMA)
    except Exception:  # noqa: BLE001 - a missing line is never worth failing a shift
        return fallback, "template"
    value = result.value if hasattr(result, "value") else result
    line = str(value.get("line", "")).strip()
    if usage is not None and hasattr(result, "input_tokens"):
        usage.update(
            calls=int(usage.get("calls", 0)) + 1,
            input_tokens=int(usage.get("input_tokens", 0)) + result.input_tokens,
            output_tokens=int(usage.get("output_tokens", 0)) + result.output_tokens,
            model=getattr(result, "model", "unknown"), provider=getattr(result, "provider", "unknown"), route="talk",
        )
    if not line or any(frag in line.lower() for frag in BANNED_FRAGMENTS) or "redacted" in line.lower():
        return fallback, "template"
    invented = [n for n in re.findall(r"\d+", line) if n not in set(re.findall(r"\d+", json.dumps(summary)))]
    if invented:
        return fallback, "template"  # every number in the line must come from the shift's own data: no invented ticks or coordinates
    if len(line) > limit:
        line = trim_to_sentence(line, limit)
        if len(line) < 40:
            return fallback, "template"
    return line, "model"


def trim_to_sentence(line: str, limit: int) -> str:
    """Cut an over-long line at the last sentence end that fits, else at the last word."""
    cut = line[:limit]
    for mark in (". ", "! ", "? "):
        idx = cut.rfind(mark)
        if idx >= 40:
            return cut[: idx + 1]
    idx = cut.rfind(" ")
    return (cut[:idx] if idx >= 40 else cut).rstrip(",;:") + "."


__all__ = ["LINE_SCHEMA", "compose_line", "summarise_shift", "templated_line", "trim_to_sentence"]
