"""`openat2` is a Linux call (number 437): on another system `libc.syscall(437, ...)` is no such call, and macOS
ends the process with SIGSYS (CI run 44788583073: pytest died on its first test with exit code 140)."""
import sys

import pytest

from sheafmd import beneath


class _Libc:
    def __init__(self):
        self.called = []

    def syscall(self, *args):
        self.called.append(args)
        return -1


@pytest.mark.parametrize("platform", ["darwin", "win32", "freebsd14"])
def test_openat2_is_never_asked_of_a_system_that_is_not_linux(monkeypatch, platform):
    libc = _Libc()
    monkeypatch.setattr(sys, "platform", platform)
    monkeypatch.setattr(beneath, "_LIBC", libc)
    monkeypatch.setattr(beneath, "_HAS_OPENAT2", None)
    with pytest.raises(NotImplementedError):
        beneath._openat2(3, "a", 0)
    assert libc.called == []


def test_a_file_that_cannot_be_read_still_has_an_identity_by_the_walk(tmp_path, monkeypatch):
    """`meta`: the walk gives its identity and status without a descriptor. `os.O_PATH` is Linux's: macOS has none, and
    the first mode 000 file ended in AttributeError there (CI run 44828043440), told to a token as a failure of the hub;
    `O_EVTONLY` is refused there as well (run 44829164316)."""
    import os
    if os.geteuid() == 0:
        pytest.skip("root reads a file of mode 000")
    f = tmp_path / "a.md"
    f.write_text("x")
    f.chmod(0)
    monkeypatch.setattr(beneath, "FALLBACK", True)
    try:
        with beneath.open_beneath(tmp_path, "a.md", meta=True) as op:
            st = f.stat()
            assert op.fd is None
            assert op.file == (st.st_dev, st.st_ino)
            assert op.stat().st_ino == st.st_ino
    finally:
        f.chmod(0o644)
