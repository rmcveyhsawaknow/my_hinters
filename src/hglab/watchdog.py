"""A watchdog for wakes: a stall prints every thread's stack and exits, instead of hanging.

A scheduled wake that never returns (a network call with no effective timeout, a model
call that hangs) would otherwise hold the runner and the identity lease until the job
timeout, with nothing in the log to say where it stopped. ``faulthandler`` runs its timer
on a separate thread, so the dump arrives even when the main thread is blocked in C code.
"""

from __future__ import annotations

import faulthandler
import sys
from collections.abc import Iterator
from contextlib import contextmanager

WAKE_WATCHDOG_SECONDS = 600


@contextmanager
def armed(seconds: int) -> Iterator[None]:
    """Within the block, a stall longer than ``seconds`` dumps all stacks to stderr and exits 1."""
    if seconds <= 0:
        yield
        return
    try:
        faulthandler.dump_traceback_later(seconds, repeat=False, file=sys.__stderr__, exit=True)
    except (AttributeError, OSError, ValueError):
        yield  # no real stderr (an in-memory stream under a test runner): run unguarded
        return
    try:
        yield
    finally:
        faulthandler.cancel_dump_traceback_later()


__all__ = ["WAKE_WATCHDOG_SECONDS", "armed"]
