"""
sheafmd.hub.jobs — the job runner of the hub (SPEC 8.10): the processes of every Ask and Tell.

One runner owns them all. Each child runs in its own process group (`start_new_session`), so
Cancel, a timeout and a hub stop signal that group and nothing else: the only signal this module
sends is `killpg` on the group of a child it started. A thread has at most one Ask and at most
one Tell. Jobs die with the hub; nothing reattaches.

`Job.run` is the `Runner` an adapter delivers through: a child that was killed comes back with a
negative return code, a timeout raises `subprocess.TimeoutExpired`.
"""
import os
import signal
import subprocess
import threading
import time
import traceback

from .. import diagnostics

TERM_GRACE = 5.0       # seconds between SIGTERM and SIGKILL on Cancel


def _signal_group(proc: subprocess.Popen, sig: int):
    """Signal the process group `proc` leads. Its pid is its group id (it was started with its
    own session), and that group is empty or gone once the child and its children have ended.
    A child that was reaped is never signalled: its pid is free, and a group of that number may
    be someone else's."""
    if proc.returncode is not None:
        return
    try:
        os.killpg(proc.pid, sig)
    except (ProcessLookupError, PermissionError):
        pass


class Job:
    def __init__(self, jobs: "Jobs", kind: str, address: str, cid: str):
        self.jobs, self.kind, self.address, self.cid = jobs, kind, address, cid
        self.cancelled = False
        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()

    def is_on(self, kind: str, address: str, cid: str) -> bool:
        """Whether this job is of `kind` on that comment thread of that document."""
        return self.kind == kind and self.address == address and self.cid == cid

    def run(self, argv, *, timeout, env=None, cwd=None, input=None) -> subprocess.CompletedProcess:
        """Run a child to its end, in its own process group. A job cancelled before this
        starts never starts the child. `input` is written to the child's stdin: what is private
        goes there, since the arguments of a process are readable by every user of the machine."""
        with self._lock:
            if self.cancelled:
                return subprocess.CompletedProcess(argv, -signal.SIGTERM, "", "")
            proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    stdin=subprocess.DEVNULL if input is None else subprocess.PIPE,
                                    text=True, encoding="utf-8",
                                    errors="replace", start_new_session=True, env=env, cwd=cwd)
            self._proc = proc
        try:
            out, err = proc.communicate(input, timeout=timeout)
        except subprocess.TimeoutExpired:
            _signal_group(proc, signal.SIGKILL)
            proc.communicate()
            raise
        finally:
            with self._lock:
                self._proc = None
        return subprocess.CompletedProcess(argv, proc.returncode, out, err)

    def cancel(self) -> bool:
        """Stop this job: its child's group gets SIGTERM, then SIGKILL after the grace. Returns
        whether a child was running."""
        with self._lock:
            self.cancelled = True
            proc = self._proc
            if proc is None:
                return False
            _signal_group(proc, signal.SIGTERM)
        t = threading.Timer(self.jobs.term_grace, self._kill, args=(proc,))
        t.daemon = True
        t.start()
        return True

    def _kill(self, proc: subprocess.Popen):
        with self._lock:
            if self._proc is proc:             # still the child this cancel signalled
                _signal_group(proc, signal.SIGKILL)

    def kill(self):
        """SIGKILL the group of the child running now, if there is one."""
        with self._lock:
            if self._proc is not None:
                _signal_group(self._proc, signal.SIGKILL)


class Jobs:
    def __init__(self, term_grace: float = TERM_GRACE):
        self.term_grace = term_grace
        self._lock = threading.Lock()
        self._jobs: list[tuple[Job, threading.Thread]] = []
        self._holds: list[Job] = []
        self._threads: list[threading.Thread] = []

    def start(self, kind: str, address: str, cid: str, work, on_error=None) -> Job | None:
        """Run `work(job)` in a thread. None when `kind` is "ask" or "tell" and this thread
        already has one running. `on_error(exception)` runs when `work` raises; the failure is
        written to the diagnostics log either way."""
        job = Job(self, kind, address, cid)
        with self._lock:
            if kind in ("ask", "tell") and any(j.is_on(kind, address, cid) for j, _ in self._jobs):
                return None
            t = threading.Thread(target=self._go, args=(job, work, on_error), daemon=True)
            # Started under the lock: the job is listed only with a thread that runs (a `kill_all` or a
            # `join` never finds one that does not), and the thread's own end waits for the lock.
            t.start()
            self._jobs.append((job, t))
            self._threads = [x for x in self._threads if x.is_alive()] + [t]
        return job

    def hold(self, kind: str, address: str, cid: str) -> Job:
        """Say that a job of `kind` is about to start on this comment thread: `active` lists it from
        now until `release`, so that whoever asks what runs does not find nothing in the moment
        between one job's end and the next one's start. It is no job: no worker thread, nothing to
        cancel or kill."""
        held = Job(self, kind, address, cid)
        with self._lock:
            self._holds.append(held)
        return held

    def release(self, held: Job):
        with self._lock:
            self._holds = [h for h in self._holds if h is not held]

    def held(self, kind: str, address: str, cid: str) -> bool:
        """Whether a hold of `kind` is on this comment thread: `hold` has been called for it and
        `release` has not. A job of that kind is no hold."""
        with self._lock:
            return any(h.is_on(kind, address, cid) for h in self._holds)

    def _go(self, job: Job, work, on_error):
        try:
            work(job)
        except Exception as e:
            diagnostics.record("hub", "job-failed", job.address, job_kind=job.kind, id=job.cid,
                               error=f"{type(e).__name__}: {e}",
                               traceback=traceback.format_exc()[-1900:])
            if on_error is not None:
                try:
                    on_error(e)
                except Exception:
                    pass
        finally:
            with self._lock:
                self._jobs = [(j, t) for j, t in self._jobs if j is not job]

    def _matching(self, kind: str, address: str, cid: str) -> list[Job]:
        with self._lock:
            return [j for j, _ in self._jobs if j.is_on(kind, address, cid)]

    def worker_threads(self, kind: str, address: str, cid: str) -> list[threading.Thread]:
        """The worker threads of the jobs of `kind` on this comment thread of a document, to wait
        for."""
        with self._lock:
            return [t for j, t in self._jobs if j.is_on(kind, address, cid)]

    def running(self, kind: str, address: str, cid: str) -> bool:
        """Whether a job of `kind` is on this thread, one that was cancelled included until its
        child has ended."""
        return bool(self._matching(kind, address, cid))

    def cancel(self, kind: str, address: str, cid: str) -> bool:
        """Cancel the jobs of `kind` on one thread of one document. Returns whether there was
        one: it ends by itself, at once if its child had not started, else when the child's
        group is gone."""
        found = self._matching(kind, address, cid)
        for j in found:
            j.cancel()
        return bool(found)

    def cancel_under(self, prefix: str, kinds=("ask", "tell")) -> int:
        """Cancel the jobs of `kinds` on every document whose address starts with `prefix`
        (`<root>/`): a root that is forgotten takes its running Asks and Tells with it. A "stop"
        message to a session is not one of them. Returns how many."""
        with self._lock:
            found = [j for j, _ in self._jobs if j.kind in kinds and j.address.startswith(prefix)]
        for j in found:
            j.cancel()
        return len(found)

    def active(self, kind: str, address: str | None = None) -> list:
        """With no address: [[address, id], ...] over all documents. With one: [id, ...]. A job
        that was cancelled no longer counts, though its child may take a moment to end; a hold does."""
        with self._lock:
            listed = [j for j, _ in self._jobs] + self._holds
            found = sorted({(j.address, j.cid) for j in listed
                            if j.kind == kind and not j.cancelled
                            and (address is None or j.address == address)})
        return [c for _, c in found] if address is not None else [[a, c] for a, c in found]

    def kill_all(self):
        """Stop every job and kill every child's group: a hub stop (SPEC 8.4). SIGTERM first; what
        is still running when the grace has passed gets SIGKILL from here, since the timer that
        would send it dies with the hub, which ends right after this. Returns when they are dead."""
        with self._lock:
            found = list(self._jobs)
        for j, _ in found:
            j.cancel()
        end = time.monotonic() + self.term_grace
        for _, t in found:
            t.join(max(0.0, end - time.monotonic()))
        for j, t in found:
            if t.is_alive():
                j.kill()
        for _, t in found:
            t.join(1.0)

    def join(self, timeout: float | None = None):
        """Wait for every job started so far (a test, or a clean stop)."""
        with self._lock:
            threads = list(self._threads)
        for t in threads:
            t.join(timeout)
