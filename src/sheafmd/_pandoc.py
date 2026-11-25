"""The one place the bundled pandoc is started (SPEC 3.2).

A document can make pandoc run without end and grow without bound (pandoc 3.9: a footnote
that cites itself, `[^1]: a [^1]`), so every call has a heap cap and a time limit. A run that
hits either one comes back as a failed run, like a document pandoc cannot read.

A render runs pandoc more than once. Inside `budget()` the runs share one limit, so a request
that renders (`sheaf open`, whose client waits a little longer than TIMEOUT) is answered within it."""
import subprocess
import time
from contextlib import contextmanager
from contextvars import ContextVar

import pypandoc

HEAP = "-M1g"      # a 470 KB document needs about 180 MB
TIMEOUT = 120      # seconds
_deadline: ContextVar[float | None] = ContextVar("pandoc_deadline", default=None)
_clock = time.monotonic
_SPENT = f"pandoc did not finish this render in time: its runs share {TIMEOUT} seconds"


@contextmanager
def budget():
    """Every run inside shares TIMEOUT seconds of the clock, counted from here; one already open is kept."""
    outer = _deadline.get()
    token = _deadline.set(_clock() + TIMEOUT if outer is None else outer)
    try:
        yield
    finally:
        _deadline.reset(token)


def run(args: list[str], text: str) -> subprocess.CompletedProcess:
    cmd = [pypandoc.get_pandoc_path(), *args, "+RTS", HEAP, "-RTS"]
    end, limit = _deadline.get(), TIMEOUT
    if end is not None:
        limit = min(TIMEOUT, end - _clock())
        if limit <= 0:
            return subprocess.CompletedProcess(cmd, 124, "", _SPENT)
    try:
        return subprocess.run(cmd, input=text, capture_output=True, text=True,
                              encoding="utf-8", timeout=limit)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, 124, "", _SPENT if end is not None else f"pandoc did not finish in {TIMEOUT} seconds")
