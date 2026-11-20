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
