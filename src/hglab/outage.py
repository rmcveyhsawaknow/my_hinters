"""Turn a Hinterglass outage into a warning on a scheduled run instead of a failed job.

On 2026-10-21 the world answered nothing within 18 seconds from 13:54 to about 20:40 UTC, and every
keepalive, tick and work shift failed on its first request, about 155 red runs. The client now
retries reads; when the world still does not answer, ``tolerate_outage`` ends the command with a
GitHub warning annotation and a line in the step summary, exit code 0 under Actions (the next
scheduled run tries again) and 1 everywhere else.
"""

from __future__ import annotations

import functools
import os
from collections.abc import Callable
from typing import Any

import typer

from hglab.client import WorldUnreachable


def tolerate_outage[F: Callable[..., Any]](func: F) -> F:
    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except WorldUnreachable as exc:
            note = f"Hinterglass did not answer ({exc}); this run is skipped and the next scheduled run tries again."
            typer.echo(note, err=True)
            if os.environ.get("GITHUB_ACTIONS") == "true":
                print(f"::warning title=Hinterglass unreachable::{note}", flush=True)
                summary = os.environ.get("GITHUB_STEP_SUMMARY")
                if summary:
                    with open(summary, "a", encoding="utf-8") as handle:
                        handle.write(f"> **Hinterglass unreachable.** {note}\n")
                raise typer.Exit(code=0) from exc
            raise typer.Exit(code=1) from exc

    return wrapper  # type: ignore[return-value]


__all__ = ["tolerate_outage"]
