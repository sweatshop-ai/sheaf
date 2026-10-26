"""Who sent the signal that stops the hub.

A Python signal handler is not told who sent the signal. Where the OS gives siginfo (Linux), the
hub blocks SIGTERM and SIGINT in every thread and one thread takes them with `sigtimedwait`, which
returns the sender's pid; the command line is read from /proc at that moment, since the sender may
be gone a second later. Without `sigtimedwait` (macOS) nothing is blocked, the ordinary handler
runs, and the row names the signal only (SPEC 8.4, 15)."""
import contextlib
import signal
import subprocess
import threading
from pathlib import Path

STOPPING = (signal.SIGTERM, signal.SIGINT)
POLL = 0.25                              # how long the watcher waits before it looks at `done` again
BLOCKS = hasattr(signal, "sigtimedwait") and hasattr(signal, "pthread_sigmask")


def name(signum: int) -> str:
    try:
        return signal.Signals(signum).name
    except ValueError:
        return str(signum)


def cmdline(pid: int) -> str | None:
    """The command line of `pid` with a space between the arguments, None when /proc has none
    (a process that ended, or no /proc)."""
    try:
        raw = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return None
    text = raw.removesuffix(b"\0").replace(b"\0", b" ").decode("utf-8", "surrogateescape")
    return text or None


def who(info) -> dict:
    """The row fields for one siginfo: the signal, and the sender when the kernel names a process
    (si_pid is 0 for a signal the kernel itself raised)."""
    row = {"signal": name(info.si_signo)}
    if info.si_pid > 0:
        row["sender_pid"] = info.si_pid
        line = cmdline(info.si_pid)
        if line:
            row["sender_cmdline"] = line
    return row


@contextlib.contextmanager
def open_to_signals():
    """Around the start of a child: the child inherits the mask of the thread that starts it, and a
    process the hub starts must get SIGTERM and SIGINT (a cancelled job is sent one, a person's
    Ctrl-C reaches a PDF render). A thread that blocks neither is left as it is. The thread is
    open only while the child is made; a signal that lands on it then is taken by the ordinary
    handler, with no sender in its row."""
    if not BLOCKS or not set(STOPPING) & signal.pthread_sigmask(signal.SIG_BLOCK, ()):
        yield
        return
    old = signal.pthread_sigmask(signal.SIG_UNBLOCK, STOPPING)
    try:
        yield
    finally:
        signal.pthread_sigmask(signal.SIG_SETMASK, old)


def _install_popen():
    """Every child of the hub is made by `subprocess.Popen`, so the thread is opened there once
    and not at each call site (a new one would start a child that ignores SIGTERM). It stays in
    place for the life of the process: a request thread still running when the hub closes is
    blocked still, and its child must not inherit that. A `Popen` that something else replaced
    since (a test harness does) is wrapped in its turn."""
    original = subprocess.Popen.__init__
    if getattr(original, "opens_to_signals", False):
        return

    def init(self, *args, **kwargs):
        with open_to_signals():
            original(self, *args, **kwargs)
    init.opens_to_signals = True
    subprocess.Popen.__init__ = init


class Signals:
    """Created before the hub has a thread: blocks the signals in the calling thread, which every
    thread made after it inherits. `start(deliver)` runs `deliver(signum, who)` in a thread for each
    signal; `close()` ends the thread and puts the mask back."""

    def __init__(self):
        self._old = None
        self._thread = None
        self._done = threading.Event()
        if BLOCKS:
            self._old = signal.pthread_sigmask(signal.SIG_BLOCK, STOPPING)
            _install_popen()

    def start(self, deliver):
        if self._old is None:
            return
        self._thread = threading.Thread(target=self._wait, args=(deliver,), name="signals", daemon=True)
        self._thread.start()

    def _wait(self, deliver):
        while not self._done.is_set():
            info = signal.sigtimedwait(STOPPING, POLL)
            if info is not None:
                deliver(info.si_signo, who(info))

    def close(self):
        self._done.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
        if self._old is not None:
            signal.pthread_sigmask(signal.SIG_SETMASK, self._old)
