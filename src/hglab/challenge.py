"""Time-bounded challenge parsing and local response validation."""

from __future__ import annotations

import concurrent.futures
import json
import re
from collections.abc import Callable, Iterable
from typing import Any

JSON_OBJECT = re.compile(r"\{[^{}]*\}")
KEY_PATTERN = re.compile(r"""["']([A-Za-z_][A-Za-z0-9_-]*)["']\s*:""")


KEY_LIST = re.compile(
    r"\b(?:keys?|fields?)\s+((?:[A-Za-z_][A-Za-z0-9_-]*)(?:\s*,\s*[A-Za-z_][A-Za-z0-9_-]*)*(?:,?\s*and\s+[A-Za-z_][A-Za-z0-9_-]*)?)",
    re.IGNORECASE,
)


def required_keys(prompt: str) -> set[str]:
    """Infer the JSON keys a challenge prompt asks for.

    Three spellings are in use: a JSON object shown in the prompt, quoted names after "keys"/"fields",
    and the plain list the live game sends ("Reply with only JSON with keys offer, total, motto and
    reversed."). A plain-list name counts only when the prompt later explains it as ``name:``.
    """
    keys: set[str] = set()
    for match in JSON_OBJECT.finditer(prompt):
        keys.update(KEY_PATTERN.findall(match.group()))
    for clause in re.findall(r"\b(?:keys|fields)\b[^.!?\n]*", prompt, re.IGNORECASE):
        keys.update(re.findall(r"""["'`]([A-Za-z_][A-Za-z0-9_-]*)["'`]""", clause))
    for match in KEY_LIST.finditer(prompt):
        for name in re.split(r"\s*,\s*|\s+and\s+", match.group(1)):
            name = name.strip()
            if name and re.search(rf"\b{re.escape(name)}:\s", prompt):
                keys.add(name)
    return keys


NUMERIC_CUES = re.compile(
    r"\b(value of|sum|total|times|plus|minus|product|difference|distance|how many|number of|count|divided|multiplied|added|subtract)\b",
    re.IGNORECASE,
)
WORD_LIMIT = re.compile(r"\b(in under|under|at most|no more than|fewer than|less than)\s+(\d+)\s+words", re.IGNORECASE)
QUOTED_WORD = re.compile(r"(?:mention|include|contain|use)s?\s+the\s+word\s+\"([^\"]+)\"", re.IGNORECASE)
LINE_COUNTS = {"two-line": 2, "two lines": 2, "three-line": 3, "three lines": 3, "three short lines": 3, "four lines": 4}


def clauses(prompt: str) -> dict[str, str]:
    """Each key's own instructions: the text after ``key:`` up to the next key's ``name:``."""
    keys = required_keys(prompt)
    marks = sorted(
        (m.start(), m.end(), key)
        for key in keys
        for m in re.finditer(rf"\b{re.escape(key)}:\s", prompt)
    )
    out: dict[str, str] = {}
    for index, (_, end, key) in enumerate(marks):
        stop = marks[index + 1][0] if index + 1 < len(marks) else len(prompt)
        out.setdefault(key, prompt[end:stop].strip())
    return out


def mechanical_answers(prompt: str) -> dict[str, Any]:
    """The parts of a challenge a program answers better than a model: arithmetic, distances, reversals, letter counts."""
    out: dict[str, Any] = {}
    for key, clause in clauses(prompt).items():
        arithmetic = re.search(r"value of\s+(-?\d+)\s*(\+|plus|times|x|\*|multiplied by|-|minus|less)\s*(-?\d+)", clause, re.IGNORECASE)
        if arithmetic:
            a, op, b = int(arithmetic[1]), arithmetic[2].lower(), int(arithmetic[3])
            out[key] = a + b if op in {"+", "plus"} else a * b if op in {"times", "x", "*", "multiplied by"} else a - b
            continue
        points = re.search(r"\((-?\d+),\s*(-?\d+)\)\s*to\s*\((-?\d+),\s*(-?\d+)\)", clause)
        if points and "max(" in clause:
            out[key] = max(abs(int(points[3]) - int(points[1])), abs(int(points[4]) - int(points[2])))
            continue
        backwards = re.search(r"\"([^\"]+)\"\s+(?:spelled|spelt|written)\s+backwards", clause, re.IGNORECASE)
        if backwards:
            out[key] = backwards[1][::-1]
            continue
        letters = re.search(r"number of letters in\s+\"([^\"]+)\"", clause, re.IGNORECASE)
        if letters:
            out[key] = len(letters[1])
    return out


def response_schema(prompt: str) -> dict[str, Any]:
    """One typed property per key: an integer where the clause asks for a quantity, a string otherwise (no unions)."""
    keys = required_keys(prompt)
    texts = clauses(prompt)
    properties = {}
    for key in sorted(keys):
        clause = texts.get(key, "")
        numeric = bool(NUMERIC_CUES.search(clause)) and not re.search(r"\bwords?\b", clause, re.IGNORECASE)
        properties[key] = {"type": "integer" if numeric else "string"}
    return {"type": "object", "properties": properties, "required": sorted(keys), "additionalProperties": False}


def _ensure_lines(text: str, lines: int) -> str:
    if text.count("\n") >= lines - 1:
        return text
    words = text.replace("\n", " ").split()
    if len(words) < lines:
        return text
    size = -(-len(words) // lines)
    return "\n".join(" ".join(words[i:i + size]) for i in range(0, len(words), size))


def finalize_answer(prompt: str, answer: dict[str, Any]) -> dict[str, Any]:
    """Mechanical keys from code, numbers as integers, word limits and quoted words honoured, line counts met."""
    out = dict(answer)
    out.update(mechanical_answers(prompt))
    for key, clause in clauses(prompt).items():
        value = out.get(key)
        if isinstance(value, str) and NUMERIC_CUES.search(clause) and re.fullmatch(r"\s*-?\d+\s*", value):
            out[key] = int(value)
            continue
        if not isinstance(value, str):
            continue
        text = " ".join(value.split()) if "\n" not in value else value.strip()
        needed = [m[1] for m in QUOTED_WORD.finditer(clause)]
        for word in needed:
            if word.casefold() not in text.casefold():
                text = (text.rstrip(".") + f" {word}").strip()
        limit = WORD_LIMIT.search(clause)
        if limit:
            cap = int(limit[2]) - (1 if re.match(r"in under|under|fewer than|less than", limit[1], re.IGNORECASE) else 0)
            words = text.split()
            if len(words) > max(cap, 1):
                words = words[:max(cap, 1)]
                for word in needed:
                    if not any(word.casefold() in w.casefold() for w in words):
                        words[-1] = word
                text = " ".join(words)
        if re.search(r"\bone word\b", clause, re.IGNORECASE):
            first = text.split()[0] if text.split() else text
            text = re.sub(r"[^A-Za-z-]", "", first) or first
        for phrase, lines in LINE_COUNTS.items():
            if phrase in clause.casefold():
                text = _ensure_lines(text, lines)
                break
        out[key] = text
    return out


def answer_challenge(
    prompt: str,
    responder: Callable[[str], str],
    *,
    required: Iterable[str] | None = None,
    timeout: float = 18,
) -> dict[str, Any]:
    """Call one responder and accept only a JSON object with required keys."""
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    future = executor.submit(responder, prompt)
    try:
        raw = future.result(timeout=timeout)
    except concurrent.futures.TimeoutError as exc:
        future.cancel()
        raise TimeoutError("challenge response exceeded its deadline") from exc
    finally:
        executor.shutdown(wait=False, cancel_futures=True)
    try:
        result = json.loads(raw)
    except (json.JSONDecodeError, TypeError) as exc:
        raise ValueError("challenge answer must be a JSON object") from exc
    if not isinstance(result, dict):
        raise TypeError("challenge answer must be a JSON object")
    missing = set(required if required is not None else required_keys(prompt)) - result.keys()
    if missing:
        raise ValueError(f"challenge answer missing required keys: {', '.join(sorted(missing))}")
    return result


def answer_with_retries(
    fetch_challenge: Callable[[], tuple[str, str]],
    responder: Callable[[str], str],
    submit: Callable[[str, dict[str, Any]], dict[str, Any]],
    *,
    retries: int = 2,
    timeout: float = 18,
) -> dict[str, Any]:
    """Fetch a fresh challenge after each failure, with at most two retries."""
    last_error: Exception | None = None
    for _ in range(retries + 1):
        challenge_id, prompt = fetch_challenge()
        try:
            answer = answer_challenge(prompt, responder, timeout=timeout)
            result = submit(challenge_id, answer)
            if result.get("ok", True):
                return result
            last_error = ValueError("challenge answer rejected")
        except (TimeoutError, ValueError, TypeError) as exc:
            last_error = exc
    assert last_error is not None
    raise last_error
