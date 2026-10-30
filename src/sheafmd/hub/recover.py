"""
sheafmd.hub.recover — a hub that holds its port and does not answer (SPEC 8.4, 9.4).

A hub that is stopped (SIGSTOP, a debugger) or hung still holds its port and the connections, so
the challenge ends in `HubSilent` and nothing can ask it to stop, and a command that meets it tells the
person to run `sheaf restart`, which would meet the same silence. `sheaf stop` and `sheaf restart`
break the circle here: they stop the process the pid file names, and no other.

This module kills a process, so what it may kill is narrow. `find` names a process only when ALL of
these hold, and where any of them cannot be read the answer is no:

  1. the pid is the one in `hub.pid` (`server.read_pid_file()`), a number that names one process
     (not 0, 1 or a negative one, which `kill` reads as a group, init or everything), not this
     process, and the file was written for this port: never a pid found another way;
  2. its command line is a sheaf hub's (`is_hub_command`): a Python process whose arguments end
     `-m sheafmd hub` or `<...>/sheaf hub`, with or without `--started-by WHO`. The name `sheafmd`
     anywhere would let `sheaf mcp`, or `tail -f sheafmd.log`, be taken for one;
  3. the process belongs to this user: its real, effective, saved and filesystem uid are ours;
  4. it is the process that listens on this port: one of its descriptors is the listening socket of
     127.0.0.1:<port>. A pid file that names a hub of another port, or a number that a hub of
     another port was handed, is not the process that holds this one.

A pid can be handed to another process once its owner has ended. The process is therefore known by
its pid and its start time (`/proc/<pid>/stat`; its state changes from one reading to the next and
is not part of who it is), read before the rule and again after it, and read once more before every
signal: a signal goes only to the process the rule was read on, and one that
ended or was replaced is not signalled. (A pidfd would close the last gap, microseconds wide, but
the Pythons that uv hands out are built without `os.pidfd_open`.) What this leaves is a signal to
another process of the same user, and only if the hub ended and its number was handed on within
those microseconds.

macOS has no /proc. There the same four readings come from the kernel through libproc, sysctl and
`lsof` (`sheafmd.darwin`): the start time is in microseconds since the epoch, not clock ticks since
boot, and the filesystem uid, which macOS does not have, is the effective one. A Linux whose /proc
cannot be read, and any other system, has no recovery. Where any condition
fails, `find` raises `Refusal`, whose text is that condition in a few words: the command puts it in
the message, so the person is told why nothing was stopped and not sent back to `sheaf restart`.

A hub that the service runs (`service` in its pid file, or no word on it) is never signalled: the
caller asks the service manager, which owns the process. The pid file's word is the hub's own, from
`--started-by service`.
"""
import os
import signal
import sys
import time
from pathlib import Path
from typing import NamedTuple

from .. import darwin, signals
from . import client as hubclient
from . import server

PROC = Path("/proc")                 # a test points it at files of its own
PLATFORM = sys.platform              # and says which platform this is
GRACE = hubclient.STOP_WAIT          # between SIGTERM and SIGKILL: what a stop the hub answers waits for, so
                                     # a hub that obeys SIGTERM is not killed while it ends its jobs
KILL_WAIT = 2.0                      # after SIGKILL, for the kernel to end the process
POLL = 0.05
ENDED = ("Z", "X")                   # states of a process that has ended: a zombie, or dead


class Refusal(Exception):
    """The rule names no process. The text is why, in a few words, for the message of the command."""


class Outcome(NamedTuple):
    """What `HubProcess.stop` did."""
    pid: int
    killed: bool                     # SIGTERM was not enough: SIGKILL followed the grace period
    ended: bool                      # the process is gone; False for one that outlived SIGKILL
    grace: float                     # the grace period it was given


def _linux() -> bool:
    return PLATFORM.startswith("linux")


def supported() -> bool:
    """Whether the rule can be read here: Linux with a /proc, or macOS through `sheafmd.darwin`."""
    if _linux():
        return (PROC / "self" / "stat").exists()
    return PLATFORM == "darwin" and darwin.available()


def unsupported() -> str:
    """Why the rule cannot be read here, for the message of the command."""
    if _linux():
        return "this system has no /proc to check a process by"
    return "sheaf cannot check a process on this system"


def _is_python(program: bytes) -> bool:
    """`python3.12`, `pypy3`, and `Python`: python.org's framework build on macOS re-executes itself as
    `.../Python.app/Contents/MacOS/Python`, and that is the name the kernel holds."""
    return os.path.basename(program).lower().startswith((b"python", b"pypy"))


def is_hub_command(raw: bytes) -> bool:
    """Whether a command line (`/proc/<pid>/cmdline`, NUL-separated) is a hub's: a Python process whose
    arguments end `-m sheafmd hub [--started-by WHO]`, or `<...>/sheaf hub [--started-by WHO]` (the
    `sheaf` script, which the kernel runs through its Python shebang). `vim sheaf hub` and
    `grep -m sheafmd hub` end the same way and are not Python."""
    args = raw.split(b"\0")
    if args and args[-1] == b"":
        args.pop()
    if len(args) >= 2 and args[-2] == b"--started-by" and args[-1]:
        args = args[:-2]
    if len(args) < 2 or args[-1] != b"hub" or not _is_python(args[0]):
        return False
    before = args[:-1]
    return before[-2:] == [b"-m", b"sheafmd"] or os.path.basename(before[-1]) == b"sheaf"


def read_uids(pid: int) -> tuple[int, ...] | None:
    """The real, effective, saved and filesystem uid of `pid`; None when they cannot be read."""
    return proc_uids(pid) if _linux() else darwin.uids(pid)


def read_stat(pid: int) -> tuple[str, int] | None:
    """(state, start time) of `pid`; None when it cannot be read."""
    return proc_stat(pid) if _linux() else darwin.stat(pid)


def read_cmdline(pid: int) -> bytes | None:
    """The command line of `pid`, NUL-separated; None when it cannot be read."""
    return proc_cmdline(pid) if _linux() else darwin.cmdline(pid)


def holds(pid: int, port: int) -> bool:
    """Whether `pid` holds the socket that listens on 127.0.0.1:`port`."""
    return proc_holds(pid, port) if _linux() else darwin.listens(pid, port)


def proc_uids(pid: int) -> tuple[int, ...] | None:
    """The four uids from /proc/<pid>/status."""
    try:
        text = (PROC / str(pid) / "status").read_text("ascii", "replace")
    except OSError:
        return None
    for line in text.splitlines():
        if line.startswith("Uid:"):
            try:
                return tuple(int(x) for x in line.split()[1:5])
            except ValueError:
                return None
    return None


def proc_stat(pid: int) -> tuple[str, int] | None:
    """(state, start time in clock ticks since boot) from /proc/<pid>/stat; None when it has no such file
    or it cannot be read. The command name is in parentheses and may hold anything, so the fields are
    read after the last `)`."""
    try:
        fields = (PROC / str(pid) / "stat").read_text("ascii", "replace").rsplit(")", 1)[1].split()
        return fields[0], int(fields[19])        # proc(5) fields 3 (state) and 22 (starttime), counted from `)`
    except (OSError, IndexError, ValueError):
        return None


def proc_cmdline(pid: int) -> bytes | None:
    """/proc/<pid>/cmdline."""
    try:
        return (PROC / str(pid) / "cmdline").read_bytes()
    except OSError:
        return None


def proc_holds(pid: int, port: int) -> bool:
    """Whether a descriptor of `pid` is the socket /proc/net/tcp says listens on 127.0.0.1:`port`."""
    return _holds_one_of(pid, _listening_inodes(port))


def _listening_inodes(port: int) -> set[str]:
    """The inode of every socket that listens on 127.0.0.1:`port` (/proc/net/tcp: the hub binds
    IPv4 only). The kernel prints the address as the machine's byte order reads its four bytes."""
    want = f"{int.from_bytes(bytes((127, 0, 0, 1)), sys.byteorder):08X}:{port:04X}"
    try:
        rows = (PROC / "net" / "tcp").read_text("ascii", "replace").splitlines()[1:]
    except OSError:
        return set()
    found = set()
    for row in rows:
        f = row.split()
        if len(f) >= 10 and f[1].upper() == want and f[3] == "0A":          # 0A: LISTEN
            found.add(f[9])
    return found


def _holds_one_of(pid: int, inodes: set[str]) -> bool:
    """Whether one of the descriptors of `pid` is one of these sockets (`socket:[inode]`)."""
    if not inodes:
        return False
    wanted = {f"socket:[{i}]" for i in inodes}
    fds = PROC / str(pid) / "fd"
    try:
        names = os.listdir(fds)
    except OSError:
        return False
    for name in names:
        try:
            if os.readlink(fds / name) in wanted:
                return True
        except OSError:
            continue
    return False


class HubProcess:
    """The process the rule names: its pid, and the start time that tells it from whatever is handed
    its number later. `supervised`: the service runs it, so only the service manager may stop it."""

    def __init__(self, pid: int, started: int, supervised: bool):
        self.pid, self.started, self.supervised = pid, started, supervised

    def running(self) -> bool:
        """The very process the rule was read on, and not an ended one (a zombie has ended)."""
        got = read_stat(self.pid)
        return got is not None and got[1] == self.started and got[0] not in ENDED

    def send(self, sig: int):
        """To that process only: one that has ended, or whose number was handed on, gets nothing."""
        if not self.running():
            return
        try:
            signals.send(self.pid, sig)
        except (ProcessLookupError, signals.Refused):
            pass

    def _wait(self, seconds: float) -> bool:
        """True once the process has ended, False when `seconds` pass first."""
        deadline = time.monotonic() + seconds
        while self.running():
            if time.monotonic() >= deadline:
                return False
            time.sleep(POLL)
        return True

    def stop(self) -> Outcome:
        """SIGTERM, and SIGCONT with it: a stopped process runs no handler until it continues, so a
        SIGTERM alone would wait out the grace period and end in SIGKILL, with no exit row and the
        process groups of the hub's jobs left running. Then SIGKILL, after the grace period and not
        before, for a hub that ignores SIGTERM."""
        killed = False
        self.send(signal.SIGTERM)
        self.send(signal.SIGCONT)
        if not self._wait(GRACE):
            killed = True
            self.send(signal.SIGKILL)
            self._wait(KILL_WAIT)
        return Outcome(self.pid, killed, not self.running(), GRACE)


def find(port: int) -> HubProcess:
    """The `HubProcess` that holds `port` and may be stopped; `Refusal` when the rule names none.
    `supervised` on it says that the service runs it: ask the service manager, never `stop`."""
    if not supported():
        raise Refusal(unsupported())
    if type(port) is not int:
        raise Refusal("the port is not a number")
    info = server.read_pid_file()
    if not info:
        raise Refusal("there is no pid file that names a process")
    pid = info.get("pid")
    if type(pid) is not int or not 1 < pid < 2 ** 31:                 # 2**31: past any pid_t
        raise Refusal("the pid file names no process")
    if pid == os.getpid():
        raise Refusal("the pid file names the command's own process")
    if type(info.get("port")) is not int:
        raise Refusal("the pid file does not say which port it was written for")
    if info["port"] != port:
        raise Refusal(f"the pid file was written for port {info['port']}, not {port}")
    before = read_stat(pid)
    if before is None or before[0] in ENDED:
        raise Refusal(f"pid {pid} is not running")
    raw = read_cmdline(pid)
    if raw is None:
        raise Refusal(f"the command line of pid {pid} cannot be read")
    if not is_hub_command(raw):
        raise Refusal(f"pid {pid} is not a sheaf hub")
    uids = read_uids(pid)
    if uids is None:
        raise Refusal(f"the user of pid {pid} cannot be read")
    if uids != (os.getuid(),) * 4:
        raise Refusal(f"pid {pid} is another user's process")
    if not holds(pid, port):
        raise Refusal(f"pid {pid} does not hold 127.0.0.1:{port}")
    after = read_stat(pid)
    if after is None or after[1] != before[1]:       # one process from the first reading to the last
        raise Refusal(f"pid {pid} changed while it was checked")
    return HubProcess(pid, before[1], info.get("service") is not False)

