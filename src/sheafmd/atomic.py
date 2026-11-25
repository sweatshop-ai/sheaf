"""
sheafmd.atomic — write a file so that it is either the old one or the whole new one.
"""
import os
from collections.abc import Callable
from pathlib import Path

from .source import _write_atomic


def write_text_atomic(path: Path, text: str, mode: int | None = None,
                      check: Callable[[], None] | None = None):
    """A file that is either the old one or the whole new one: a share copy cut short by a crash must
    not be there to be sent. `mode` is the permission bits the file gets (default: what a new file gets under the
    umask). `check` is called once the new file is whole and read back, just before it takes the old
    one's place, and refuses by raising: what was true when the caller looked can have changed since.
    Written by source._write_atomic, with its looks for a swapped temp file, for a caller that
    holds no file lock."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode is None:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask
    _write_atomic(path, text, mode, check, locked=False)
