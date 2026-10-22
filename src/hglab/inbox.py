"""Whispers that outlive the observe that delivered them.

The world marks a whisper read on delivery: whichever of our entry points observes first (the hourly
keepalive, the collector or land office round, a wake) is the only one that ever sees it. The land
office's answer to Fudgewright's brief was delivered to a keepalive and lost to the wake that would
have read it. ``preserve`` writes unread whispers into the agent's own notebook under ``_inbox``
(private, redacted from every record), and ``merge_inbox`` gives a wake the notebook's copies beside
the live ones. Entries older than two days drop out; at most twelve are kept.
"""

from __future__ import annotations

import json
from typing import Any

from hglab.notes import fit_note

INBOX_KEY = "_inbox"
KEEP = 12
KEEP_TICKS = 2 * 8640
TEXT_LIMIT = 400


def stored(observe: dict[str, Any]) -> list[dict[str, Any]]:
    raw = (observe.get("notebook") or {}).get(INBOX_KEY)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if isinstance(raw, dict):
        raw = raw.get("whispers")
    return [w for w in raw if isinstance(w, dict) and w.get("from") and w.get("text")] if isinstance(raw, list) else []


def _key(w: dict[str, Any]) -> tuple[str, str]:
    return str(w.get("from", "")).casefold(), str(w.get("text", ""))[:80]


def merge_inbox(observe: dict[str, Any]) -> list[dict[str, Any]]:
    """The live inbox plus the notebook's kept whispers, newest last, no duplicates."""
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for w in [*stored(observe), *(observe.get("inbox") or [])]:
        if not isinstance(w, dict) or not w.get("from") or not w.get("text"):
            continue
        k = _key(w)
        if k in seen:
            continue
        seen.add(k)
        out.append({"from": str(w["from"]), "text": str(w["text"])[:TEXT_LIMIT], "tick": int(w.get("tick", 0) or 0)})
    return out


def note_for(observe: dict[str, Any], tick: int) -> str | None:
    """The ``_inbox`` note to remember after this observe, or None when nothing new arrived."""
    live = [w for w in (observe.get("inbox") or []) if isinstance(w, dict) and w.get("from") and w.get("text")]
    if not live:
        return None
    merged = [w for w in merge_inbox(observe) if tick - int(w.get("tick", 0) or 0) <= KEEP_TICKS][-KEEP:]
    return fit_note({"whispers": merged})


def preserve(client: Any, observe: dict[str, Any]) -> bool:
    """Remember the whispers this observe delivered; True when a note was written."""
    note = note_for(observe, int(observe.get("tick", 0) or 0))
    if note is None:
        return False
    try:
        result = client.act({"action": "remember", "key": INBOX_KEY, "text": note})
    except Exception:  # noqa: BLE001 - keeping a whisper is best effort
        return False
    return bool(result.get("ok", True))


__all__ = ["INBOX_KEY", "merge_inbox", "note_for", "preserve", "stored"]
