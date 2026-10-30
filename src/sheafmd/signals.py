"""
sheafmd.signals — the one place sheaf signals, probes or reaps a process (sheaf#85).

`kill` reads a pid as more than one process when it is 0 (the caller's own group), negative (a
group; -1 is every process the user may signal) or 1 (init), `killpg` reads a group the same way,
and `waitpid(-1)` reaps any child. A pid read from a file can be any of these, and so can one handed
over by a caller that did not check it: on macOS the teardown of the tests once sent SIGTERM to the
-1 a test had written into `hub.pid`, and the CI runner went down with every other process of its
user. So every `os.kill`, `os.killpg` and `os.waitpid` of the product, its tests and its CI tools
is made here, and `tests/test_signals.py` fails on one made anywhere else.

`send` refuses, with `Refused`, before anything is sent:

  1. a pid that does not name one process: not an `int` (a `bool` is one in Python, and `True` is
     1), or not 1 < pid < 2**31;
  2. the caller's own process;
  3. a process that is not this user's: its real uid, from /proc/<pid>/status where there is one
     and from `ps` where not (macOS), is not ours; one whose uid cannot be read is not ours.

`send_group` takes the `Popen` of a child this process started in a session of its own, never a
number: the group is ours because its leader is our child, and it is known by that child, not by
a uid that ends with the leader while the rest of the group runs on. It refuses a child that was
reaped (its number is free, and a group of that number may be someone else's), one whose pid does
not name one process, and one that does not lead a group of its own (it was not started in a session
of its own: its group is the caller's, and the signal would reach the caller).

None of this needs /proc to refuse a -1, 0 or 1, so a system without one refuses as Linux does. A
caller that must know more (that the process is the hub of a port, `hub/recover.py`) checks it
first: this is the floor every signal stands on, not the whole rule.

`exists` and `reap` take any value and treat one that names no single process as nothing there
(`exists` answers for init, 1, which a signal 0 only asks about).
"""
import os
import subprocess
from pathlib import Path

PROC = Path("/proc")                 # a test points it at files of its own
PID_LIMIT = 2 ** 31                  # past any pid_t
POPEN = subprocess.Popen             # the class itself: a test may put a subclass of it in its place


class Refused(Exception):
    """Nothing was sent. The text is why, in a few words."""


def one_process(pid) -> bool:
    """Whether `pid` is a number that `kill` reads as one process: a whole number above 1."""
    return type(pid) is int and 1 < pid < PID_LIMIT


def owner(pid: int) -> int | None:
    """The real uid of `pid`, or None when it cannot be read (it ended, or there is no way to look)."""
    try:
        for line in (PROC / str(pid) / "status").read_text("ascii", "replace").splitlines():
            if line.startswith("Uid:"):
                return int(line.split()[1])
        return None
    except (OSError, IndexError, ValueError):
        pass
    if (PROC / "self" / "status").exists():                  # a /proc that has no such pid: it ended
        return None
    try:
        r = subprocess.run(["ps", "-o", "ruid=", "-p", str(pid)], capture_output=True, text=True, timeout=10)
        return int(r.stdout.strip())
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def check(pid, what: str = "pid"):
    """Raise `Refused` unless `pid` names one process of this user's that is not this one (rules 1 to 3)."""
    if not one_process(pid):
        raise Refused(f"{what} {pid!r} does not name one process")
    if pid == os.getpid():
        raise Refused(f"{what} {pid} is this process")
    uid = owner(pid)
    if uid is None and not exists(pid):
        raise ProcessLookupError(f"no process {pid}")        # as `os.kill` says it: it ended
    if uid is None:
        raise Refused(f"the user of {what} {pid} cannot be read")
    if uid != os.getuid():
        raise Refused(f"{what} {pid} is another user's process")


def send(pid, sig: int):
    """`sig` to the one process `pid`, which is this user's and not this process. Raises `Refused`, and
    what `os.kill` raises (ProcessLookupError for one that has ended, here or in between)."""
    check(pid)
    os.kill(pid, sig)


def send_group(proc: subprocess.Popen, sig: int):
    """`sig` to the process group that `proc`, a child of this process started with its own session,
    leads. Raises `Refused`, and what `os.killpg` raises (ProcessLookupError once the group is empty)."""
    if not isinstance(proc, POPEN):
        raise Refused(f"{proc!r} is not a child this process started")
    if proc.returncode is not None:
        raise Refused(f"child {proc.pid} was reaped: its number is free")
    if not one_process(proc.pid):
        raise Refused(f"group {proc.pid!r} does not name one process group")
    try:
        leads = os.getpgid(proc.pid) == proc.pid
    except ProcessLookupError:
        leads = True             # an ended leader that is not reaped yet holds its number, and so its group's
    if not leads:
        raise Refused(f"child {proc.pid} does not lead a group of its own")
    os.killpg(proc.pid, sig)


def exists(pid) -> bool:
    """Whether a process `pid` exists (signal 0, which sends nothing), another user's too, init (1)
    too. A value that names no single process names nothing that exists: `kill(-1, 0)` and
    `kill(0, 0)` succeed whenever any process does."""
    if not (type(pid) is int and 0 < pid < PID_LIMIT):
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def reap(pid):
    """Reap `pid` if it is an ended child of this process; nothing for any other value, so a -1 or 0 from
    a file never reaps a child that someone else waits for."""
    if not one_process(pid):
        return
    try:
        os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        pass
