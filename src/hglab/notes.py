"""Notebook notes that fit the world's 2000-character value limit and still parse.

The collector's and the land office's state notes used to be ``json.dumps(...)[:2000]``: once a state
outgrew the limit the cut JSON no longer parsed, the next round started from nothing, and every
invitation and deed was forgotten and repeated. ``fit_note`` drops the oldest entries of the longest
lists first, then whole keys, until the note fits, and never returns invalid JSON.
"""

from __future__ import annotations

import json
from typing import Any

NOTE_LIMIT = 2000


def fit_note(payload: dict[str, Any], limit: int = NOTE_LIMIT) -> str:
    """Serialise ``payload`` compactly within ``limit`` characters, trimming lists from their oldest end."""
    state = {k: (list(v) if isinstance(v, list) else v) for k, v in payload.items()}
    text = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    while len(text) > limit:
        lists = [k for k, v in state.items() if isinstance(v, list) and len(v) > 1]
        if lists:
            longest = max(lists, key=lambda k: len(json.dumps(state[k], ensure_ascii=False)))
            keep = max(1, len(state[longest]) * 3 // 4)
            state[longest] = state[longest][-keep:]
        else:
            dicts = [k for k, v in state.items() if isinstance(v, dict) and len(v) > 1]
            if dicts:
                biggest = max(dicts, key=lambda k: len(json.dumps(state[k], ensure_ascii=False)))
                oldest = next(iter(state[biggest]))
                state[biggest] = {k: v for k, v in state[biggest].items() if k != oldest}
            elif len(state) > 1:
                bulkiest = max(state, key=lambda k: len(json.dumps(state[k], ensure_ascii=False)))
                state.pop(bulkiest)
            else:
                state = {}
        text = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    return text


__all__ = ["NOTE_LIMIT", "fit_note"]
