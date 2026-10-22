"""A five-field cron matcher for the personas' cadence and work knobs (minute hour day month weekday).

Supports ``*``, lists (``1,4,7``), ranges (``1-5``) and steps (``*/2``, ``1-30/5``); weekday 0 and 7
are both Sunday, as cron has it. Times are UTC, like the GitHub schedules the knobs were written for.
"""

from __future__ import annotations

from datetime import datetime

RANGES = ((0, 59), (0, 23), (1, 31), (1, 12), (0, 7))


def _field(spec: str, lo: int, hi: int) -> set[int]:
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        step = 1
        if "/" in part:
            part, step_text = part.split("/", 1)
            step = max(1, int(step_text))
        if part in ("*", ""):
            start, end = lo, hi
        elif "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(part)
            if step > 1:
                end = hi
        out.update(range(start, end + 1, step))
    return out


def parse(expr: str) -> list[set[int]]:
    fields = expr.split()
    if len(fields) != 5:
        raise ValueError(f"a cron expression has five fields: {expr!r}")
    return [_field(f, lo, hi) for f, (lo, hi) in zip(fields, RANGES, strict=True)]


def matches(expr: str, when: datetime) -> bool:
    minute, hour, day, month, weekday = parse(expr)
    dow = (when.weekday() + 1) % 7  # Monday is 0 in Python, 1 in cron; Sunday 0 (or 7)
    return (
        when.minute in minute
        and when.hour in hour
        and when.day in day
        and when.month in month
        and (dow in weekday or (dow == 0 and 7 in weekday))
    )


__all__ = ["matches", "parse"]
