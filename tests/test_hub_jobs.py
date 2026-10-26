"""The job runner (SPEC 8.10): every Ask and Tell child runs in its own process group, Cancel
kills that group and nothing else, a timeout kills the group, and a thread has at most one Ask.

The children are real processes, small shell scripts of the test's own; the unrelated process
the tests keep beside them stands for everything else on the machine, which a Cancel must leave
alone."""
import os
import signal
import subprocess
import threading
import time

import pytest

from helpers import proc_state
from sheafmd import diagnostics
from sheafmd.hub.jobs import Jobs


def alive(pid: int) -> bool:
    """The process exists and is not a zombie waiting to be reaped."""
    return proc_state(pid) == "alive"


def wait_done(results, seconds=10.0):
    end = time.time() + seconds
    while not results and time.time() < end:
        time.sleep(0.02)
    assert results, "the job never finished"


def wait_dead(pid, seconds=5.0):
    end = time.time() + seconds
    while time.time() < end:
        if not alive(pid):
            return True
        time.sleep(0.02)
    return not alive(pid)


def wait_for(path, seconds=5.0):
    end = time.time() + seconds
    while time.time() < end:
        if path.exists() and path.read_text().strip():
            return path.read_text().strip()
        time.sleep(0.02)
    raise AssertionError(f"{path} was never written")


@pytest.fixture
def bystander():
    """A process nothing in the job runner started."""
    p = subprocess.Popen(["sleep", "60"])
    yield p
    p.kill()
    p.wait()


@pytest.fixture
def jobs():
    j = Jobs(term_grace=0.5)
    yield j
    j.kill_all()
    j.join(5)


def script(tmp_path, body, name="child.sh"):
    f = tmp_path / name
    f.write_text("#!/bin/sh\n" + body + "\n")
    f.chmod(0o755)
    return str(f)


def sh(script_path):
    """The command that runs a script made by `script`: through the shell, never by exec of the
    file. A thread of the test forking while another writes a script holds a copy of the write
    handle until its own exec, and exec of a file open for writing anywhere fails with errno 26,
    "Text file busy" (the CI failures: pid1 or pid2 'never written', never pid0, on py3.13 and
    py3.14; the race is reproduced on py3.11 too)."""
    return ["/bin/sh", script_path]


def run_in(jobs, kind, cid, work, address="work/plan.md"):
    done = []

    def go(job):
        done.append(work(job))
    started = jobs.start(kind, address, cid, go)
    return started, done


# ── the process side ─────────────────────────────────────────────────────────

def test_a_script_runs_while_a_forked_sibling_still_holds_a_write_handle_on_it(jobs, tmp_path):
    """The race of the pid files, held still: a child stalled between fork and exec keeps the write
    handle it inherited, so exec of the file fails with ETXTBSY; `sh` does not exec it."""
    child = script(tmp_path, "echo ran")
    with open(child, "a"):                          # the handle a sibling's fork would copy
        try:
            subprocess.run([child])
        except OSError as busy:
            assert busy.errno == 26
        else:
            pytest.skip("this kernel runs a file that is open for writing; the race is Linux's")
        _, done = run_in(jobs, "ask", "c1", lambda job: job.run(sh(child), timeout=10))
        jobs.join(10)
    assert done[0].stdout == "ran\n"

def test_a_child_runs_in_its_own_process_group_and_its_output_comes_back(jobs, tmp_path):
    pidfile = tmp_path / "pid"
    child = script(tmp_path, f'echo $$ > {pidfile}\necho out\necho err >&2\nexit 3')
    started, done = run_in(jobs, "ask", "c1", lambda job: job.run(sh(child), timeout=10))
    jobs.join(10)
    r = done[0]
    assert (r.returncode, r.stdout, r.stderr) == (3, "out\n", "err\n")
    assert started is not None


def test_the_childs_group_is_its_own_not_the_hubs(jobs, tmp_path):
    seen = tmp_path / "pgid"
    child = script(tmp_path, f'ps -o pgid= -p $$ > {seen}\nsleep 0.2')
    run_in(jobs, "ask", "c1", lambda job: job.run(sh(child), timeout=10))
    jobs.join(10)
    assert int(seen.read_text()) != os.getpgrp()


def test_a_child_gets_no_input_and_the_environment_and_folder_it_is_given(jobs, tmp_path):
    # the count is unquoted so the shell drops the blanks BSD wc pads it with
    child = script(tmp_path, 'echo "$FOO" "$(pwd)"; echo $(cat | wc -c)')
    _, done = run_in(jobs, "ask", "c1", lambda job: job.run(
        sh(child), timeout=10, env={**os.environ, "FOO": "bar"}, cwd=str(tmp_path)))
    jobs.join(10)
    assert done[0].stdout == f"bar {tmp_path}\n0\n"


def test_the_input_a_child_is_given_reaches_its_stdin_and_never_its_arguments(jobs, tmp_path):
    child = script(tmp_path, 'echo "$#"; cat')
    _, done = run_in(jobs, "ask", "c1", lambda job: job.run(sh(child), timeout=10, input="private text\n"))
    jobs.join(10)
    assert done[0].stdout == "0\nprivate text\n"


def test_a_child_that_never_reads_its_input_does_not_hang_the_job(jobs, tmp_path):
    child = script(tmp_path, "exit 3")
    _, done = run_in(jobs, "ask", "c1", lambda job: job.run(sh(child), timeout=10, input="x" * 1_000_000))
    jobs.join(10)
    assert done[0].returncode == 3


# ── Cancel ───────────────────────────────────────────────────────────────────

def test_cancel_kills_the_childs_whole_group_and_nothing_else(jobs, tmp_path, bystander):
    mine, other = tmp_path / "mine", tmp_path / "grandchild"
    sibling = tmp_path / "sibling"
    child = script(tmp_path, f'sleep 60 &\necho $! > {other}\necho $$ > {mine}\nwait')
    other_job = script(tmp_path, f'echo $$ > {sibling}\nsleep 60', "other.sh")
    _, a = run_in(jobs, "ask", "c1", lambda job: job.run(sh(child), timeout=60))
    _, b = run_in(jobs, "ask", "c2", lambda job: job.run(sh(other_job), timeout=60))
    child_pid, grandchild_pid = int(wait_for(mine)), int(wait_for(other))
    sibling_pid = int(wait_for(sibling))
    assert jobs.cancel("ask", "work/plan.md", "c1") is True
    wait_done(a)
    assert a[0].returncode < 0                                 # killed, not finished
    assert wait_dead(child_pid) and wait_dead(grandchild_pid)
    assert alive(bystander.pid)                                # nobody else was touched
    assert alive(sibling_pid)                                  # nor another job's child
    assert alive(os.getpid())


def test_cancel_reaches_a_grandchild_that_outlives_its_parent(jobs, tmp_path):
    grand = tmp_path / "grand"
    child = script(tmp_path, f'sleep 60 &\necho $! > {grand}\nexit 0')
    _, done = run_in(jobs, "ask", "c1", lambda job: job.run(sh(child), timeout=60))
    gpid = int(wait_for(grand))
    time.sleep(0.2)                                            # the parent has exited by now
    assert jobs.cancel("ask", "work/plan.md", "c1") is True
    jobs.join(10)
    assert wait_dead(gpid)


def test_a_child_that_ignores_sigterm_is_killed_after_the_grace(jobs, tmp_path):
    pidfile = tmp_path / "pid"
    child = script(tmp_path, f'trap "" TERM\necho $$ > {pidfile}\nwhile true; do sleep 0.1; done')
    _, done = run_in(jobs, "ask", "c1", lambda job: job.run(sh(child), timeout=60))
    pid = int(wait_for(pidfile))
    jobs.cancel("ask", "work/plan.md", "c1")
    jobs.join(10)
    assert wait_dead(pid)
    assert done[0].returncode == -signal.SIGKILL


def test_a_cancel_that_comes_before_the_child_starts_stops_it_from_starting(jobs, tmp_path):
    marker = tmp_path / "ran"
    child = script(tmp_path, f'echo yes > {marker}')

    def work(job):
        job.cancel()
        return job.run(sh(child), timeout=10)
    _, done = run_in(jobs, "ask", "c1", work)
    jobs.join(10)
    assert done[0].returncode < 0 and not marker.exists()


def test_cancel_of_a_job_that_is_not_running_says_so(jobs):
    assert jobs.cancel("ask", "work/plan.md", "nope") is False


def test_cancel_names_a_kind_and_never_touches_the_other(jobs, tmp_path):
    pidfile = tmp_path / "pid"
    child = script(tmp_path, f'echo $$ > {pidfile}\nsleep 60')
    run_in(jobs, "tell", "c1", lambda job: job.run(sh(child), timeout=60))
    pid = int(wait_for(pidfile))
    assert jobs.cancel("ask", "work/plan.md", "c1") is False
    assert alive(pid)
    assert jobs.cancel("tell", "work/plan.md", "c1") is True
    jobs.join(10)
    assert wait_dead(pid)


def test_a_cancel_on_another_document_does_not_touch_this_one(jobs, tmp_path):
    pidfile = tmp_path / "pid"
    child = script(tmp_path, f'echo $$ > {pidfile}\nsleep 60')
    run_in(jobs, "ask", "c1", lambda job: job.run(sh(child), timeout=60), address="work/a.md")
    pid = int(wait_for(pidfile))
    assert jobs.cancel("ask", "work/b.md", "c1") is False
    assert alive(pid)


# ── timeouts and stopping ────────────────────────────────────────────────────

def test_a_timeout_kills_the_whole_group_and_raises(jobs, tmp_path):
    grand = tmp_path / "grand"
    child = script(tmp_path, f'sleep 60 &\necho $! > {grand}\nwait')
    errors = []

    def work(job):
        try:
            job.run(sh(child), timeout=0.4)
        except subprocess.TimeoutExpired as e:
            errors.append(e)
    run_in(jobs, "ask", "c1", work)
    gpid = int(wait_for(grand))
    jobs.join(10)
    assert len(errors) == 1 and wait_dead(gpid)


def test_stopping_the_hub_kills_every_jobs_group(jobs, tmp_path, bystander):
    files = []
    for n in range(3):
        f = tmp_path / f"pid{n}"
        files.append(f)
        child = script(tmp_path, f'echo $$ > {f}\nsleep 60', f"c{n}.sh")
        run_in(jobs, "ask" if n % 2 else "tell", f"c{n}", lambda job, c=child: job.run(sh(c), timeout=60))
    pids = [int(wait_for(f)) for f in files]
    jobs.kill_all()
    jobs.join(10)
    assert all(wait_dead(p) for p in pids)
    assert alive(bystander.pid)


def test_a_hub_stop_returns_only_when_a_child_that_ignores_sigterm_is_dead(jobs, tmp_path):
    """The hub process ends right after it stops its jobs, and the timer that sends SIGKILL
    after the grace dies with it: a stop that returned on SIGTERM would leave the child running."""
    pidfile = tmp_path / "pid"
    child = script(tmp_path, f'trap "" TERM\necho $$ > {pidfile}\nwhile true; do sleep 0.1; done')
    _, done = run_in(jobs, "ask", "c1", lambda job: job.run(sh(child), timeout=60))
    pid = int(wait_for(pidfile))
    started = time.monotonic()
    jobs.kill_all()
    took = time.monotonic() - started
    assert not alive(pid)                                     # at once, not "soon"
    assert jobs.term_grace <= took < jobs.term_grace + 3      # it waited out the grace, no longer


def test_a_hub_stop_does_not_wait_for_children_that_end_on_sigterm(jobs, tmp_path):
    pidfile = tmp_path / "pid"
    child = script(tmp_path, f'echo $$ > {pidfile}\nsleep 60')
    run_in(jobs, "tell", "c1", lambda job: job.run(sh(child), timeout=60))
    pid = int(wait_for(pidfile))
    started = time.monotonic()
    jobs.kill_all()
    assert time.monotonic() - started < jobs.term_grace
    assert not alive(pid)


def test_a_cancel_after_the_child_was_reaped_signals_no_group(jobs, tmp_path, monkeypatch):
    """Once the child is reaped its pid is free, and a group of that number may be someone
    else's. A Cancel that lands between the reaping and the job letting go of the child must
    send nothing. The race is made certain here: the Cancel comes right after the reaping."""
    sent, holder = [], []
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: sent.append((pgid, sig)))

    class CancelledAfterReaping(subprocess.Popen):
        def communicate(self, *args, **kwargs):
            result = super().communicate(*args, **kwargs)
            holder[0].cancel()
            return result
    monkeypatch.setattr(subprocess, "Popen", CancelledAfterReaping)
    child = script(tmp_path, "exit 0")

    def work(job):
        holder.append(job)
        return job.run(sh(child), timeout=10)
    _, done = run_in(jobs, "ask", "c1", work)
    wait_done(done)
    assert done[0].returncode == 0
    assert sent == []


# ── the registry ─────────────────────────────────────────────────────────────

def test_a_thread_has_at_most_one_ask_at_a_time(jobs, tmp_path):
    pidfile = tmp_path / "pid"
    child = script(tmp_path, f'echo $$ > {pidfile}\nsleep 60')
    first, _ = run_in(jobs, "ask", "c1", lambda job: job.run(sh(child), timeout=60))
    wait_for(pidfile)
    second, _ = run_in(jobs, "ask", "c1", lambda job: None)
    other_thread, _ = run_in(jobs, "ask", "c2", lambda job: None)
    assert first is not None and second is None and other_thread is not None
    jobs.cancel("ask", "work/plan.md", "c1")
    jobs.join(10)
    again, _ = run_in(jobs, "ask", "c1", lambda job: None)
    assert again is not None


def test_a_thread_has_at_most_one_tell_and_a_stop_beside_it(jobs, tmp_path):
    pidfile = tmp_path / "pid"
    child = script(tmp_path, f'echo $$ > {pidfile}\nsleep 60')
    first, _ = run_in(jobs, "tell", "c1", lambda job: job.run(sh(child), timeout=60))
    wait_for(pidfile)
    assert jobs.running("tell", "work/plan.md", "c1") and not jobs.running("ask", "work/plan.md", "c1")
    second, _ = run_in(jobs, "tell", "c1", lambda job: None)
    other_thread, _ = run_in(jobs, "tell", "c2", lambda job: None)
    stop, _ = run_in(jobs, "stop", "c1", lambda job: None)
    assert first is not None and second is None and other_thread is not None and stop is not None
    jobs.cancel("tell", "work/plan.md", "c1")
    jobs.join(10)
    again, _ = run_in(jobs, "tell", "c1", lambda job: None)
    assert again is not None and not jobs.running("tell", "work/plan.md", "c2")


def test_the_running_jobs_are_listed_by_kind(jobs, tmp_path):
    pidfile = tmp_path / "pid"
    child = script(tmp_path, f'echo $$ > {pidfile}\nsleep 60')
    run_in(jobs, "ask", "c1", lambda job: job.run(sh(child), timeout=60), address="work/a.md")
    wait_for(pidfile)
    assert jobs.active("ask") == [["work/a.md", "c1"]]
    assert jobs.active("tell") == []
    assert jobs.active("ask", "work/a.md") == ["c1"] and jobs.active("ask", "work/b.md") == []
    jobs.cancel("ask", "work/a.md", "c1")
    jobs.join(10)
    assert jobs.active("ask") == []


def test_a_job_that_raises_is_written_down_and_leaves_the_registry(jobs):
    errors = []
    started = jobs.start("ask", "work/plan.md", "c1", lambda job: 1 / 0,
                         on_error=lambda e: errors.append(type(e).__name__))
    jobs.join(10)
    assert started is not None and errors == ["ZeroDivisionError"]
    assert jobs.active("ask") == []
    assert [r for r in diagnostics.read() if r["kind"] == "job-failed"]


def test_a_job_that_raises_in_its_error_handler_still_leaves_the_registry(jobs):
    def broken(e):
        raise RuntimeError("again")
    jobs.start("ask", "work/plan.md", "c1", lambda job: 1 / 0, on_error=broken)
    jobs.join(10)
    assert jobs.active("ask") == []


def test_a_hold_counts_as_an_active_job_of_its_kind_until_it_is_released(jobs):
    """A step that will start a job (the stop message of a cancelled Tell) says so before it
    does, so that whoever asks what runs never finds the hub idle in between."""
    hold = jobs.hold("stop", "work/plan.md", "c1")
    assert jobs.active("stop") == [["work/plan.md", "c1"]]
    assert jobs.active("stop", "work/plan.md") == ["c1"] and jobs.active("tell") == []
    jobs.release(hold)
    assert jobs.active("stop") == []
    jobs.release(hold)                                   # a second release is no error
    assert jobs.active("stop") == []


def test_a_hold_is_no_job_that_a_cancel_or_a_hub_stop_acts_on(jobs):
    hold = jobs.hold("stop", "work/plan.md", "c1")
    assert not jobs.running("stop", "work/plan.md", "c1")
    assert jobs.worker_threads("stop", "work/plan.md", "c1") == []
    assert not jobs.cancel("stop", "work/plan.md", "c1")
    assert jobs.cancel_under("work/", kinds=("stop",)) == 0
    jobs.kill_all()
    assert jobs.active("stop") == [["work/plan.md", "c1"]]       # still held: only its owner ends it
    jobs.release(hold)


def test_a_hold_is_held_for_its_kind_and_thread_until_it_is_released(jobs):
    """`held` tells whether a hold of that kind is on that thread: a Tell start asks it of a cancel
    that is not over."""
    assert not jobs.held("stop", "work/plan.md", "c1")
    hold = jobs.hold("stop", "work/plan.md", "c1")
    assert jobs.held("stop", "work/plan.md", "c1")
    assert not jobs.held("tell", "work/plan.md", "c1")           # another kind
    assert not jobs.held("stop", "work/plan.md", "c2")           # another thread
    assert not jobs.held("stop", "work/other.md", "c1")          # another document
    jobs.release(hold)
    assert not jobs.held("stop", "work/plan.md", "c1")


def test_a_job_is_no_hold(jobs):
    """A stop message that is listed has the cancel behind it: only a hold means a cancel is under way."""
    release = threading.Event()
    jobs.start("stop", "work/plan.md", "c1", lambda job: release.wait(10))
    assert jobs.active("stop") == [["work/plan.md", "c1"]]
    assert not jobs.held("stop", "work/plan.md", "c1")
    release.set()
    jobs.join(10)


def test_a_job_whose_thread_cannot_start_is_not_left_listed(jobs, monkeypatch):
    def refuse(self):
        raise RuntimeError("can't start new thread")
    with monkeypatch.context() as m:
        m.setattr(threading.Thread, "start", refuse)
        with pytest.raises(RuntimeError):
            jobs.start("ask", "work/a.md", "c1", lambda job: None)
    assert jobs.running("ask", "work/a.md", "c1") is False and jobs.active("ask") == []
    jobs.join(1)                                # no thread that never started is waited for
    jobs.kill_all()
    assert jobs.start("ask", "work/a.md", "c1", lambda job: None) is not None
