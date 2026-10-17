"""Time-bounded challenge parsing and local response validation."""

from __future__ import annotations

import concurrent.futures
import json
import re
from collections.abc import Callable, Iterable
from typing import Any

JSON_OBJECT = re.compile(r"\{[^{}]*\}")
KEY_PATTERN = re.compile(r"""["']([A-Za-z_][A-Za-z0-9_-]*)["']\s*:""")


def required_keys(prompt: str) -> set[str]:
    """Infer explicit JSON keys shown by a challenge prompt."""
    keys: set[str] = set()
    for match in JSON_OBJECT.finditer(prompt):
        keys.update(KEY_PATTERN.findall(match.group()))
    for clause in re.findall(r"\b(?:keys|fields)\b[^.!?\n]*", prompt, re.IGNORECASE):
        keys.update(re.findall(r"""["'`]([A-Za-z_][A-Za-z0-9_-]*)["'`]""", clause))
    return keys


def response_schema(prompt: str) -> dict[str, Any]:
    keys = required_keys(prompt)
    return {
        "type": "object",
        "properties": {key: {"type": ["string", "number", "boolean"]} for key in keys},
        "required": sorted(keys),
        "additionalProperties": False,
    }


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
