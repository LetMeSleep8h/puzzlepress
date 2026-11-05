"""Cooperative cancellation and work-unit progress for long engine operations.

Expensive loops (preparing drawings, drawing pages, inspecting PDF pages, measuring
artwork, generating puzzles, writing package files) call `checkpoint(stage, done,
total)`. With no watcher installed, as in every CLI command and test, it does
nothing at all, so outputs and behavior are unchanged. A caller that installs one
with `watching(hook)` hears each checkpoint in this thread and context only; the
hook may record progress and may raise `Cancelled` to stop the work at that point.

`Cancelled` derives from BaseException, like KeyboardInterrupt, so a broad
`except Exception` that turns a damaged page into a finding can never swallow a
cancellation. Every engine writer stages its files and cleans up in `finally` or
`except BaseException` blocks, so stopping at a checkpoint leaves no partial output.
Between checkpoints work is not interruptible: a single ReportLab save, pypdf read
or one drawing's preparation runs to its end (the documented cancellation boundary).
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar

# (stage, units done, units total); either count may be None when not measurable.
Checkpoint = Callable[[str, int | None, int | None], None]

_WATCHER: ContextVar[Checkpoint | None] = ContextVar("puzzlepress_checkpoint", default=None)


class Cancelled(BaseException):
    """Work stopped on request at a checkpoint of `stage`."""

    def __init__(self, stage: str) -> None:
        self.stage = stage
        super().__init__(f"Cancelled during {stage}.")


def checkpoint(stage: str, done: int | None = None, total: int | None = None) -> None:
    """A safe point to stop: tells the installed watcher, if any, how far `stage` is."""
    watcher = _WATCHER.get()
    if watcher is not None:
        watcher(stage, done, total)


@contextmanager
def watching(hook: Checkpoint) -> Iterator[None]:
    """Install `hook` for checkpoints reached in this context until the block ends."""
    token = _WATCHER.set(hook)
    try:
        yield
    finally:
        _WATCHER.reset(token)


__all__ = ["Cancelled", "Checkpoint", "checkpoint", "watching"]
