"""The leak guard: a run that leaves a process behind fails, and says whose it was; and the
reaper of the suite (tests/conftest.py) leaves nothing for it to find.

Most of these run pytest inside the test, in a folder of its own. With `-p leakguard` that run has the
guard and nothing else, so a process left behind there is the guard's to find and not the reaper's;
with `-p conftest` it has everything the suite's own tests have. Where there is no /proc (macOS)
nothing can be found and nothing is asserted."""
import os
import signal
import subprocess
import sys
import time
import uuid
from pathlib import Path

import pytest

import leakguard
from helpers import _has_proc, gone, is_stopped, proc_state
from sheafmd import signals

pytestmark = pytest.mark.skipif(not _has_proc(), reason="the guard reads /proc")

TESTS = Path(__file__).parent
SUFFIX = uuid.uuid4().hex


def rid(name):
    """An identifier for a test to hand to a process of its own, as unique as the run that reads it back:
    a runner or a probe on the same host runs these tests at the same moment, and an identifier that is
    the same string in both lets one run's guard find the other's process."""
    return f"{name}-{SUFFIX}"


def inner_run(tmp_path, source, plugin="leakguard"):
    """`pytest` on one test file with `source`, in `tmp_path/inner`, with `plugin` (a module of tests/)
    loaded. The test writes the pid of what it leaves to `pid` in its folder."""
    inner = tmp_path / "inner"
    inner.mkdir()
    (inner / "test_inner.py").write_text(source)
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(TESTS), os.environ.get("PYTHONPATH", "")])}
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-p", plugin,
                        f"--basetemp={inner / 'bt'}"], cwd=inner, env=env,
                       capture_output=True, text=True, timeout=120)
    pid_file = inner / "pid"
    return r, int(pid_file.read_text()) if pid_file.exists() else None


def kill_if_left(pid):
    if pid and not gone(pid):
        signals.send(pid, signal.SIGKILL)


def really_gone(pid, seconds=10):
    """The process is gone: its parent (a pytest that has ended) is not there to reap it, so
    whoever adopted it does, in a moment."""
    deadline = time.time() + seconds
    while time.time() < deadline:
        if gone(pid):
            return True
        time.sleep(0.05)
    return False


LEAVES_ONE = '''
import subprocess

def test_it_leaves_a_process_running():
    p = subprocess.Popen(["sleep", "300"], start_new_session=True)
    open("pid", "w").write(str(p.pid))
'''


def test_a_run_that_leaves_a_process_running_fails_and_names_the_test_and_the_process(tmp_path):
    r, pid = inner_run(tmp_path, LEAVES_ONE)
    try:
        assert r.returncode == 1, r.stdout
        assert "1 process that this run started still alive at the end of it" in r.stdout, r.stdout
        assert f"pid {pid}, started during test_inner.py::test_it_leaves_a_process_running" in r.stdout
        assert "sleep 300" in r.stdout
        assert really_gone(pid), "the guard names a process and leaves it running"
    finally:
        kill_if_left(pid)


LEAVES_ONE_DETACHED = '''
import subprocess

def test_a_shell_starts_one_and_exits():
    subprocess.run(["sh", "-c", "nohup sleep 300 >/dev/null 2>&1 & echo $! > pid"], check=True)
'''


def test_a_process_that_a_shell_started_and_left_to_init_is_found_too(tmp_path):
    """The fake service manager of tests/test_service.py is this shape: a script that starts the hub
    and ends, so the hub is no child of the test, and no pid file or `Popen` of the test names it."""
    r, pid = inner_run(tmp_path, LEAVES_ONE_DETACHED)
    try:
        assert r.returncode == 1, r.stdout
        assert f"pid {pid}, started during test_inner.py::test_a_shell_starts_one_and_exits" in r.stdout
        assert really_gone(pid)
    finally:
        kill_if_left(pid)


CLEAN = '''
import subprocess

def test_it_starts_a_process_and_ends_it():
    p = subprocess.Popen(["sleep", "300"])
    p.terminate()
    p.wait(timeout=30)
    subprocess.run(["true"], check=True)
'''


def test_a_run_whose_tests_end_what_they_start_passes(tmp_path):
    r, _ = inner_run(tmp_path, CLEAN)
    assert r.returncode == 0, r.stdout
    assert "1 passed" in r.stdout and "still alive at the end of it" not in r.stdout


def test_a_process_of_another_run_is_not_this_runs_to_stop(tmp_path):
    other = subprocess.Popen(["sleep", "300"], env={**os.environ, leakguard.RUN_VAR: rid("another-run")})
    try:
        r, _ = inner_run(tmp_path, CLEAN)
        assert r.returncode == 0, r.stdout
        assert other.poll() is None
        assert [p.pid for p in leakguard.left_running(rid("another-run"))] == [other.pid]
    finally:
        other.kill()
        other.wait(timeout=30)


def test_what_a_process_carries_says_which_test_started_it():
    run = rid("run-of-this-test")
    env = {**os.environ, leakguard.RUN_VAR: run, leakguard.NODE_VAR: "tests/x.py::t"}
    p = subprocess.Popen(["sleep", "300"], env=env)
    try:
        got = leakguard.left_running(run)
        assert [(g.pid, g.test) for g in got] == [(p.pid, "tests/x.py::t")]
        assert "sleep 300" in got[0].command
        assert leakguard.left_running(run, test="tests/x.py::t") == got
        assert leakguard.left_running(run, test="tests/x.py::another") == []
        assert leakguard.left_running(rid("another-run")) == []
    finally:
        p.kill()
        p.wait(timeout=30)


def test_a_process_whose_exec_is_not_done_is_waited_for_and_found(monkeypatch):
    """A shell has just started it and ended: for a few milliseconds its environment reads empty. The
    first guard missed a process that way on CI, on a runner with few processes to look at first."""
    p = subprocess.Popen(["sleep", "300"], env={**os.environ, leakguard.RUN_VAR: rid("run-in-exec")})
    try:
        real, empty = leakguard._environment, []

        def not_yet(pid):
            if pid == str(p.pid) and len(empty) < 5:
                empty.append(pid)
                return [b""]
            return real(pid)
        monkeypatch.setattr(leakguard, "_environment", not_yet)
        assert [g.pid for g in leakguard.left_running(rid("run-in-exec"))] == [p.pid]
        assert len(empty) == 5
    finally:
        p.kill()
        p.wait(timeout=30)


def test_a_new_process_that_has_no_environment_is_waited_for_a_moment_and_no_longer():
    p = subprocess.Popen(["sleep", "300"], env={})
    try:
        started = time.monotonic()
        assert leakguard.left_running(rid("no-run-has-this-id")) == []
        assert time.monotonic() - started < leakguard.EXEC_WINDOW + 2
    finally:
        p.kill()
        p.wait(timeout=30)


def test_a_process_that_began_before_this_run_is_not_read(monkeypatch):
    env = {**os.environ, leakguard.RUN_VAR: rid("run-older")}
    p = subprocess.Popen(["sleep", "300"], env=env)
    try:
        assert [g.pid for g in leakguard.left_running(rid("run-older"))] == [p.pid]
        monkeypatch.setattr(leakguard, "THIS_RUN_BEGAN", leakguard._uptime() + 1000)
        assert leakguard.left_running(rid("run-older")) == []
    finally:
        p.kill()
        p.wait(timeout=30)


def test_a_process_that_has_ended_and_is_not_reaped_yet_is_not_left_running():
    env = {**os.environ, leakguard.RUN_VAR: rid("run-of-the-zombie")}
    p = subprocess.Popen(["true"], env=env)
    try:
        deadline = time.time() + 10
        while proc_state(p.pid) == "alive" and time.time() < deadline:
            time.sleep(0.02)
        assert leakguard.left_running(rid("run-of-the-zombie")) == []
    finally:
        p.wait(timeout=30)


def test_a_process_that_ignores_sigterm_is_killed_after_the_grace():
    run = rid("run-that-ignores-term")
    env = {**os.environ, leakguard.RUN_VAR: run}
    p = subprocess.Popen(["sh", "-c", 'trap "" TERM; exec sleep 300'], env=env)
    try:
        for _ in range(100):                           # the trap is set before the exec; wait for the exec
            if any(g.command.startswith("sleep") for g in leakguard.left_running(run)):
                break
            time.sleep(0.02)
        started = time.monotonic()
        got = leakguard.stop_left(run, grace=0.3)
        assert [g.pid for g in got] == [p.pid]
        assert p.wait(timeout=30) == -signal.SIGKILL
        assert time.monotonic() - started >= 0.3
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(timeout=30)


def test_a_process_that_is_stopped_is_continued_so_that_it_can_end():
    env = {**os.environ, leakguard.RUN_VAR: rid("run-that-is-stopped")}
    p = subprocess.Popen(["sleep", "300"], env=env)
    try:
        signals.send(p.pid, signal.SIGSTOP)
        for _ in range(100):
            if is_stopped(p.pid):
                break
            time.sleep(0.02)
        started = time.monotonic()
        leakguard.stop_left(rid("run-that-is-stopped"), grace=30)
        assert p.wait(timeout=30) == -signal.SIGTERM        # it went on the SIGTERM, not on the SIGKILL
        assert time.monotonic() - started < 10
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(timeout=30)


# ── the reaper of the suite leaves nothing for the guard ─────────────────────

def test_the_reaper_of_the_suite_stops_what_a_shell_left_to_init(tmp_path):
    """The shape of the fake service manager: a script starts the hub in the background and ends."""
    r, pid = inner_run(tmp_path, LEAVES_ONE_DETACHED, plugin="conftest")
    try:
        assert r.returncode == 0, r.stdout
        assert "1 passed" in r.stdout and "still alive at the end of it" not in r.stdout
        assert really_gone(pid)
    finally:
        kill_if_left(pid)


FAILS_WITH_ONE_LEFT = '''
import subprocess

def test_it_starts_one_and_then_fails():
    subprocess.run(["sh", "-c", "nohup sleep 300 >/dev/null 2>&1 & echo $! > pid"], check=True)
    assert False, "the test fails with its process still running"
'''


def test_the_reaper_of_the_suite_stops_what_a_failed_test_left(tmp_path):
    r, pid = inner_run(tmp_path, FAILS_WITH_ONE_LEFT, plugin="conftest")
    try:
        assert r.returncode == 1 and "1 failed" in r.stdout, r.stdout
        assert "still alive at the end of it" not in r.stdout                 # the failure is the test's own; nothing is left behind it
        assert really_gone(pid)
    finally:
        kill_if_left(pid)


LEAVES_A_HUB_THAT_IS_STILL_STARTING = '''
import subprocess, sys

def test_a_manager_starts_a_hub_and_the_test_ends_before_it_has_a_pid_file(port):
    subprocess.run(["sh", "-c", 'nohup "$0" -m sheafmd hub --started-by service >/dev/null 2>&1 & echo $! > pid',
                    sys.executable], check=True)
'''


def test_the_reaper_of_the_suite_stops_a_hub_that_had_no_pid_file_when_its_test_ended(tmp_path):
    """The leak the guard is for, in one test: the hub is no child of the test, and a reaper that looks for
    the pid file or for the `Popen` of the test misses it, and the hub binds its port after the look."""
    r, pid = inner_run(tmp_path, LEAVES_A_HUB_THAT_IS_STILL_STARTING, plugin="conftest")
    try:
        assert r.returncode == 0, r.stdout
        assert really_gone(pid)
    finally:
        kill_if_left(pid)


STOPPED_BY_SIGTERM = '''
import os, signal, subprocess, time

def test_the_run_is_told_to_stop_while_a_process_of_the_test_runs():
    p = subprocess.Popen(["sleep", "300"], start_new_session=True)
    open("pid", "w").write(str(p.pid))
    os.kill(os.getpid(), signal.SIGTERM)
    time.sleep(60)
'''


def test_a_run_that_is_sent_sigterm_ends_like_ctrl_c_and_stops_what_its_tests_started(tmp_path):
    """`timeout` and a stopped task send SIGTERM, which ended the run where it stood, fixtures and all."""
    r, pid = inner_run(tmp_path, STOPPED_BY_SIGTERM)
    try:
        assert r.returncode > 0, f"the run was ended by the signal itself ({r.returncode}): {r.stdout}"
        assert really_gone(pid)
    finally:
        kill_if_left(pid)


TWIN = ["-k", "carries_says or ignores_sigterm or another_run or exec_is_not_done or began_before"]


def test_two_runs_of_these_tests_at_once_on_one_host_do_not_find_each_others_processes(tmp_path):
    """CI runners and probe rounds share a host and a user, and an identifier that is the
    same string in both runs lets one run's guard find the other's `sleep 300`, one pid too many."""
    env = {**os.environ, "PYTHONPATH": os.pathsep.join([str(TESTS), os.environ.get("PYTHONPATH", "")])}
    twins = [subprocess.Popen([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                               f"--basetemp={tmp_path / name}", str(Path(__file__)), *TWIN],
                              cwd=TESTS, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
             for name in ("a", "b")]
    outputs = [t.communicate(timeout=120)[0] for t in twins]
    assert [t.returncode for t in twins] == [0, 0], "\n".join(outputs)
    assert all("5 passed" in out for out in outputs), \
        "the -k of TWIN no longer selects 5 tests:\n" + "\n".join(outputs)
