"""
sheafmd.atomic — write a file so that it is either the old one or the whole new one.
"""
import os
import tempfile
from collections.abc import Callable
from pathlib import Path


def write_text_atomic(path: Path, text: str, mode: int | None = None,
                      check: Callable[[], None] | None = None):
    """A file that is either the old one or the whole new one: a share copy cut short by a crash must
    not be there to be sent. `mode` is the permission bits the file gets (default: what a new file gets under the
    umask). `check` is called once the new file is whole, just before it takes the old one's
    place, and refuses by raising: what was true when the caller looked can have changed since."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".sheaf-tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        if mode is None:
            umask = os.umask(0)
            os.umask(umask)
            mode = 0o666 & ~umask
        os.chmod(tmp, mode)
        if check is not None:
            check()
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
