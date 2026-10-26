"""Run a command, pass its output through, and when it goes quiet say what it is doing.

py3.11 and py3.14 CI jobs stood at 50 to 80% until the 30-minute limit
with no error line, no test name and no stack, although pytest-timeout (300 s) and faulthandler
(600 s) are set. The runner's own log showed pytest alive and ignoring SIGTERM. This runs pytest
and, when it prints nothing for QUIET seconds, writes to the log:

  * the process table with each process's state and the kernel function it sleeps in (wchan),
  * the inode and memory figures of /tmp and the machine,
  * the Python stack of the pytest process's main thread (SIGUSR2, sent to that thread alone), then
    every thread's stack (SIGUSR1); tests/conftest.py registers faulthandler on both and writes to
    the file named by SHEAF_STALL_DUMP. The main thread comes first because faulthandler dumps at
    most 100 threads, newest first, and the main thread is the oldest: a run with 100 leaked threads
    showed everything but where the test stood.

After KILL_AFTER seconds of silence (10 minutes) it ends the process group and exits 1, so the job fails with
this evidence in its log instead of at the time limit. The pytest process writes its pid to
SHEAF_PYTEST_PIDFILE, so the signal goes to it alone: a hub or a fake child has no handler.

    python tools/ci/stall_watch.py -- uv run --no-sync pytest -v -m "not page"
"""
import atexit
import ctypes
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

QUIET = float(os.environ.get("SHEAF_STALL_QUIET", "360"))
# The job has 30 minutes in all and a green Tests step takes about 19, so a hang can start late: the run
# ends 10 quiet minutes after its last output, inside the job limit for any hang before minute ~18.
KILL_AFTER = float(os.environ.get("SHEAF_STALL_KILL_AFTER", "600"))

# GNU ps and free on Linux; BSD ps on macOS has no --forest, etimes or wchan width, and no free.
SNAPSHOT = (
    ["uptime"],
    ["ps", "-eo", "pid,ppid,pgid,stat,wchan:28,etimes,pcpu,rss,args", "--forest"] if sys.platform.startswith("linux")
    else ["ps", "-axo", "pid,ppid,pgid,stat,etime,pcpu,rss,command"],
    ["df", "-i", "/tmp"],
    ["free", "-m"] if sys.platform.startswith("linux") else ["vm_stat"],
)


def say(text: str = ""):
    print(text, flush=True)


def snapshot() -> str:
    """What the machine looks like, one block per command; a command that is missing says so."""
    out = []
    for argv in SNAPSHOT:
        try:
            r = subprocess.run(argv, capture_output=True, text=True, timeout=20)
            text = "\n".join(ln[:240] for ln in (r.stdout + r.stderr).rstrip().splitlines())
            out.append(f"$ {' '.join(argv)}\n{text}")
        except (OSError, subprocess.TimeoutExpired) as e:
            out.append(f"$ {' '.join(argv)}\n({type(e).__name__}: {e})")
    return "\n\n".join(out)


def kernel_view(pid: int) -> str:
    """Where one process is in the kernel: its state, wchan and (as root) its stack."""
    lines = []
    for name in ("status", "wchan", "stack"):
        try:
            text = Path(f"/proc/{pid}/{name}").read_text()
        except OSError as e:
            lines.append(f"/proc/{pid}/{name}: {e.strerror}")
            continue
        if name == "status":
            text = "".join(ln for ln in text.splitlines(True) if ln.split(":")[0] in ("State", "Threads", "SigIgn", "SigBlk"))
        lines.append(f"/proc/{pid}/{name}: {text.strip()}")
    return "\n".join(lines)


def catches(pid: int, sig: int) -> bool:
    """Whether `pid` has a handler for `sig` (SigCgt in /proc): a signal with none ends the process,
    and a fake child or a pytest that has not yet reached its conftest has only SIGUSR1's."""
    try:
        for line in Path(f"/proc/{pid}/status").read_text().splitlines():
            if line.startswith("SigCgt:"):
                return bool(int(line.split()[1], 16) >> (sig - 1) & 1)
    except (OSError, ValueError):
        pass
    return False


def signal_main_thread(pid: int, sig: int):
    """`sig` to the main thread of `pid` (its thread id is the pid), so faulthandler's handler runs
    there; where there is no tgkill, to the process, which runs it on any thread."""
    try:
        if ctypes.CDLL(None, use_errno=True).tgkill(pid, pid, sig) == 0:
            return
    except (OSError, AttributeError):
        pass
    os.kill(pid, sig)


def wait_for_dump(dump: Path, after: int = 0):
    """Wait up to 5 s for the handler to write past `after` bytes, then until it has stopped writing."""
    size = after
    for _ in range(50):
        time.sleep(0.1)
        now = len(dump.read_text())
        if now > after and now == size:
            return
        size = now


def python_stacks(pidfile: Path, dump: Path) -> str:
    """Ask the pytest process for its main thread's stack, then for every thread's, and read what it wrote."""
    try:
        pid = int(pidfile.read_text())
    except (OSError, ValueError):
        return "no pytest pid file: the process had not started its session"
    try:
        dump.write_text("")
        if catches(pid, signal.SIGUSR2):
            signal_main_thread(pid, signal.SIGUSR2)
            wait_for_dump(dump)
        main = dump.read_text()
        os.kill(pid, signal.SIGUSR1)
        wait_for_dump(dump, len(main))
    except OSError as e:
        return f"pytest pid {pid}: {e.strerror or e}"
    text = dump.read_text()
    rest = text[len(main):] if text.startswith(main) else text
    return (f"pytest pid {pid}\n{kernel_view(pid)}\n\nmain thread:\n{main or '(no main thread dump)'}"
            f"\nall threads (at most 100, newest first):\n{rest}")


def report(quiet_for: float, pidfile: Path, dump: Path):
    say(f"\n::group::stall_watch: no output for {quiet_for:.0f} s")
    say(snapshot())
    say()
    say(python_stacks(pidfile, dump))
    say("::endgroup::")


def main(argv: list[str]) -> int:
    if "--" not in argv:
        sys.stderr.write("usage: stall_watch.py -- COMMAND [ARG...]\n")
        return 2
    cmd = argv[argv.index("--") + 1:]
    work = Path(tempfile.mkdtemp(prefix="stall-"))
    atexit.register(shutil.rmtree, work, True)
    pidfile, dump = work / "pytest.pid", work / "stacks.txt"
    env = {**os.environ, "SHEAF_PYTEST_PIDFILE": str(pidfile), "SHEAF_STALL_DUMP": str(dump)}
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, start_new_session=True)
    seen = [time.monotonic()]

    def relay():
        # Chunks, not lines: `pytest -v` prints the name of a test before it ends the line, and the
        # name of the test that is stuck is the one thing a stall must show.
        fd = proc.stdout.fileno()
        while chunk := os.read(fd, 65536):
            seen[0] = time.monotonic()
            sys.stdout.buffer.write(chunk)
            sys.stdout.buffer.flush()
    reader = threading.Thread(target=relay, daemon=True)
    reader.start()

    def cancelled(signum, _frame):
        """The job was cancelled: the child has its own session, so the runner's kill does not reach it."""
        for sig in (signal.SIGTERM, signal.SIGKILL):
            try:
                os.killpg(proc.pid, sig)
            except OSError:
                break
            time.sleep(2)
        sys.exit(128 + signum)
    signal.signal(signal.SIGTERM, cancelled)
    signal.signal(signal.SIGINT, cancelled)

    reports, last_seen = 0, seen[0]
    while proc.poll() is None:
        time.sleep(0.2)
        if seen[0] != last_seen:                   # output resumed: the next stall reports from the start
            reports, last_seen = 0, seen[0]
        quiet = time.monotonic() - seen[0]
        if quiet >= QUIET * (reports + 1):         # a report at QUIET, again at 2 x QUIET, ...
            reports += 1
            report(quiet, pidfile, dump)
        if quiet >= KILL_AFTER:
            say(f"\n::error::stall_watch: no output for {quiet:.0f} s; ending the run (the log above names where it stood)")
            # SIGTERM to the group, then SIGKILL to it whether or not the first process left: `uv`
            # exits on SIGTERM while the pytest below it ignores it, and would be left holding the pipe.
            for sig in (signal.SIGTERM, signal.SIGKILL):
                try:
                    os.killpg(proc.pid, sig)
                except OSError:
                    break
                if sig == signal.SIGTERM:
                    time.sleep(3)
            reader.join(5)
            return 1
    reader.join(10)
    return proc.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
