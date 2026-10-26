"""The helper the hub tests share to ask whether a process is alive, a zombie or gone, on a
platform with a /proc and on one without (macOS)."""
import os
import signal
import subprocess
import time

import pytest

import helpers
from helpers import gone, proc_state


@pytest.fixture(params=["as_is", "no_proc"])
def proc_branch(request, monkeypatch):
    """Both ways the helper reads a process: as the platform has it (/proc on Linux), and
    with the /proc branch faked absent, which is macOS: `kill -0` and `ps`."""
    if request.param == "no_proc":
        monkeypatch.setattr(helpers, "_has_proc", lambda: False)


@pytest.fixture
def child():
    p = subprocess.Popen(["sleep", "60"])
    yield p
    p.kill()
    p.wait()


def until(cond, seconds=5.0):
    end = time.time() + seconds
    while time.time() < end and not cond():
        time.sleep(0.02)
    return cond()


def test_a_process_is_alive_then_a_zombie_until_reaped_then_gone(proc_branch, child):
    assert proc_state(child.pid) == "alive"
    child.kill()
    assert until(lambda: proc_state(child.pid) != "alive")
    assert proc_state(child.pid) == "zombie"
    assert child.wait() == -signal.SIGKILL                # reading its state reaped nothing
    assert proc_state(child.pid) == "gone"


def test_gone_is_false_for_a_live_process_and_reaps_one_that_ended(proc_branch, child):
    assert not gone(child.pid)
    child.kill()
    assert until(lambda: gone(child.pid))
    assert proc_state(child.pid) == "gone"                       # gone() reaped the zombie


def test_a_process_that_kill_is_refused_for_is_alive_when_ps_lists_it(monkeypatch):
    """`kill -0` on another user's process is refused (PermissionError); it still exists."""
    monkeypatch.setattr(helpers, "_has_proc", lambda: False)

    def refused(pid, sig):
        raise PermissionError
    monkeypatch.setattr(helpers.os, "kill", refused)
    assert proc_state(os.getpid()) == "alive"
