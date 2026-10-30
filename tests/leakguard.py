"""The suite leaves nothing running behind it.

A hub that a test starts is a process of its own, and a test that ends without stopping it leaves it
alive for hours, on a port nobody uses, until someone kills it by hand. The tests start processes by
many roads: a command's detached hub, a test's own `Popen`, a shell script that stands for the service
manager, a `sh -c` around a child. The two ways to find them that the suite had (the pid file, and the
`Popen` calls that name `-m sheafmd hub`) each miss some of those. So a process is found by what it
carries, never by what it is called or by where it wrote its pid:

    SHEAF_TEST_RUN   the id of this pytest run, in the environment of the run from its first fixture
    SHEAF_TEST_NODE  the node id of the test that is running, for the length of that test

A child inherits both, a grandchild that detached from its parent too, and `/proc/<pid>/environ` keeps
what the process started with for as long as it lives. `left_running` reads them back, `stop_left`
ends what it finds, and the session fixture at the bottom fails the run when anything is alive at the
end of it. It needs /proc: where there is none (macOS) nothing is found and nothing is asserted."""
import os
import signal
import threading
import time
import uuid
from typing import NamedTuple

import pytest

from helpers import _has_proc, proc_state
from sheafmd import signals

RUN_VAR = "SHEAF_TEST_RUN"
NODE_VAR = "SHEAF_TEST_NODE"
SETTLE = 10.0          # how long a process that was told to go may take, before it counts as left behind
EXEC_WINDOW = 1.0      # how long a new process may take to finish its exec, and have an environment to read
KTHREAD = 0x00200000   # PF_KTHREAD, in the flags of /proc/<pid>/stat


class Left(NamedTuple):
    pid: int
    test: str          # the node id of the test that was running when it started; "" when none was
    command: str


def _environment(pid: str) -> list[bytes] | None:
    """What `pid` started with, split in `NAME=value`; None when it cannot be read (it ended, or it is
    another user's). A process that is in the middle of its exec has none yet: `[b""]`."""
    try:
        with open(f"/proc/{pid}/environ", "rb") as f:
            return f.read().split(b"\0")
    except OSError:
        return None


def _stat(pid: str) -> tuple[str, int, float] | None:
    """The state, the flags and the start (seconds since boot) of `pid`; None when it has ended."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            fields = f.read().rsplit(")", 1)[1].split()
        return fields[0], int(fields[6]), int(fields[19]) / os.sysconf("SC_CLK_TCK")
    except (OSError, IndexError, ValueError):
        return None


def _uptime() -> float:
    with open("/proc/uptime") as f:
        return float(f.read().split()[0])


def _is_executing(pid: str) -> bool:
    """A user process that is younger than EXEC_WINDOW: when its environment reads empty, it is that of
    the exec that has not finished (a shell has just started it and ended, as the fake service manager
    does), not the lack of one. A kernel thread and a zombie have none for good."""
    st = _stat(pid)
    return bool(st) and st[0] != "Z" and not st[1] & KTHREAD and _uptime() - st[2] < EXEC_WINDOW


def _after_exec(pid: str) -> list[bytes] | None:
    deadline = time.monotonic() + EXEC_WINDOW
    while time.monotonic() < deadline and _is_executing(pid):
        env = _environment(pid)
        if env != [b""]:
            return env
        time.sleep(0.005)
    return None


# Nothing that began before this process can carry the id of this run, and a scan that opens the environment
# of every process of the user only needs the ones that came after it.
THIS_RUN_BEGAN = (_stat("self") or ("", 0, 0.0))[2] if _has_proc() else 0.0


def left_running(run: str, test: str | None = None) -> list[Left]:
    """The live processes that carry `run`, and `test` as well when it is given. Never this process.
    One that has ended and is waiting to be reaped (a zombie) is not live."""
    if not _has_proc():
        return []
    want = f"{RUN_VAR}={run}".encode()
    node = f"{NODE_VAR}=".encode()
    me = os.getpid()
    found = []
    for entry in os.listdir("/proc"):
        if not entry.isdigit() or int(entry) == me:
            continue
        st = _stat(entry)
        if st is None or st[2] < THIS_RUN_BEGAN:         # it ended meanwhile, or it is older than this run
            continue
        env = _environment(entry)
        if env == [b""]:                                 # in the middle of its exec: wait for it, a moment
            env = _after_exec(entry)
        if env is None or want not in env:               # it ended meanwhile, or it is another user's, or not ours
            continue
        started_by = next((e[len(node):].decode(errors="replace") for e in env if e.startswith(node)), "")
        if test is not None and started_by != test:
            continue
        pid = int(entry)
        if proc_state(pid) != "alive":
            continue
        try:
            with open(f"/proc/{entry}/cmdline", "rb") as f:
                command = f.read().replace(b"\0", b" ").decode(errors="replace").strip()
        except OSError:
            command = ""
        found.append(Left(pid, started_by, command))
    return found


def _send(pid: int, sig: int):
    try:
        signals.send(pid, sig)
    except (OSError, signals.Refused):
        pass


def stop_left(run: str, test: str | None = None, grace: float = 5.0) -> list[Left]:
    """End every process `left_running` finds, and say which they were. SIGTERM first, and SIGCONT
    after it (as systemd sends one, so that a process that is stopped can end); SIGKILL after `grace`
    seconds to what is still there. It looks again before each step, so a pid that ended and was given
    to something else is not signalled."""
    found = left_running(run, test)
    for p in found:
        _send(p.pid, signal.SIGTERM)
        _send(p.pid, signal.SIGCONT)
    if found and not _gone_within(run, test, grace):
        for p in left_running(run, test):
            _send(p.pid, signal.SIGKILL)
        _gone_within(run, test, SETTLE)
    return found


def _gone_within(run: str, test: str | None, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while left_running(run, test):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.05)
    return True


def report(left: list[Left]) -> str:
    lines = [f"{len(left)} process{'es' if len(left) != 1 else ''} that this run started "
             "still alive at the end of it; they have been stopped:"]
    for p in left:
        lines.append(f"  pid {p.pid}, started during {p.test or 'no test (a fixture of a wider scope)'}")
        lines.append(f"      {p.command[:200]}")
    lines.append("A test that starts a process stops it, on failure too; tests/leakguard.py says how "
                 "each one is found.")
    return "\n".join(lines)


def _terminated(signum, frame):
    raise KeyboardInterrupt("SIGTERM")


@pytest.fixture(scope="session", autouse=True)
def no_process_left_behind():
    """The run has an id, from before its first test; at its end nothing that carries the id may
    be alive. What is left is stopped (this run's own, found by the id, never another run's) and the
    run fails with the tests it names. A SIGTERM (`timeout`, a stopped task) ends the run as Ctrl-C does,
    so that the fixtures that stop what the tests started still run; only a SIGKILL skips them."""
    run = uuid.uuid4().hex
    os.environ[RUN_VAR] = run
    on_main_thread = threading.current_thread() is threading.main_thread()
    before = signal.signal(signal.SIGTERM, _terminated) if on_main_thread else None
    yield run
    if before is not None:
        signal.signal(signal.SIGTERM, before)
    left = left_running(run)
    deadline = time.monotonic() + SETTLE
    while left and time.monotonic() < deadline:          # one that was just told to go may still be going
        time.sleep(0.1)
        left = left_running(run)
    if left:
        stop_left(run)
    os.environ.pop(RUN_VAR, None)
    if left:
        pytest.fail(report(left), pytrace=False)


@pytest.fixture(autouse=True)
def the_test_that_is_running(request, monkeypatch):
    """What a process of this test carries to say whose it is."""
    monkeypatch.setenv(NODE_VAR, request.node.nodeid)
