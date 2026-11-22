"""A test never touches the hub of whoever runs the suite: its state is its own whatever the test does
to its patches, and the only processes it signals are the ones it started."""
import os
import signal
import subprocess
import sys

import pytest

from sheafmd import config, paths
from sheafmd.hub import server


def test_a_monkeypatch_undo_in_the_test_leaves_every_folder_the_tests_own(tmp_path, monkeypatch):
    """`monkeypatch.undo()` once restored the runner's HOME and state folder, and the teardown read the
    runner's hub.pid and stopped the hub it named."""
    monkeypatch.setattr(sys, "argv", ["x"])
    monkeypatch.undo()
    for folder in (paths.state_dir(), paths.config_file(), paths.cache_dir(), server.pid_file()):
        assert tmp_path in folder.parents, folder
    assert os.environ["HOME"].startswith(str(tmp_path)) and os.path.expanduser("~").startswith(str(tmp_path))
    assert config.port() != config.DEFAULT_PORT


def test_a_monkeypatch_undo_in_the_test_leaves_the_patches_of_the_fixtures_in_place(monkeypatch):
    before = subprocess.Popen
    monkeypatch.undo()
    assert subprocess.Popen is before and subprocess.Popen.__name__ == "Tracked"
    assert os.kill.__name__ == "guarded_kill"


@pytest.fixture
def sent_by_the_guard(spawned):
    """Every signal that passes the guard, recorded and never sent."""
    class Log(list):
        real = spawned.kill

        def sent(self):
            """What was sent: a probe (signal 0, which `proc_state` makes where there is no /proc) sends nothing."""
            return [e for e in self if e[1] != 0]

        def send_again(self):
            spawned.kill = self.real            # a test that left a process of its own stops it for real

    log = Log()
    spawned.kill = lambda pid, sig: log.append((pid, sig))
    return log


def test_a_live_process_the_test_did_not_start_is_not_signalled(sent_by_the_guard):
    """The parent of the run is another process of this user, alive, and none of the test's."""
    with pytest.raises(AssertionError, match="a process it did not start"):
        os.kill(os.getppid(), signal.SIGTERM)
    assert sent_by_the_guard.sent() == []


def test_the_pid_in_a_hub_file_is_not_a_reason_to_signal_it(sent_by_the_guard, monkeypatch):
    """A pid in a hub.pid is a pid like any other: what it names is signalled only when the test started
    it, however the file was found and whatever the test did to its environment before."""
    server.pid_file().parent.mkdir(parents=True, exist_ok=True)
    server.pid_file().write_text(f'{{"pid": {os.getppid()}, "port": {config.port()}}}')
    monkeypatch.undo()
    with pytest.raises(AssertionError, match="did not start"):
        os.kill(server.read_pid_file()["pid"], signal.SIGKILL)
    assert sent_by_the_guard.sent() == []
    server.pid_file().unlink()                # nothing for the teardown to stop


def test_a_process_the_test_started_is_signalled(sent_by_the_guard):
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    os.kill(p.pid, signal.SIGTERM)
    os.kill(p.pid, signal.SIGKILL)               # and a later signal to the same one
    assert sent_by_the_guard == [(p.pid, signal.SIGTERM), (p.pid, signal.SIGKILL)]
    sent_by_the_guard.send_again()
    p.kill()
    p.wait(10)


def test_a_signal_that_sends_nothing_is_not_stopped_by_the_guard(sent_by_the_guard):
    os.kill(os.getppid(), 0)
    assert sent_by_the_guard == [(os.getppid(), 0)]


def test_a_process_that_is_ending_is_not_a_reason_to_refuse_the_second_signal(sent_by_the_guard):
    """A daemon told to go reads empty before it is a zombie: the signal that follows is let through, and a
    live process of the run, one that has an environment, is not taken for one that ends."""
    from helpers import wait_until_ended
    from leakguard import is_ending
    done = subprocess.Popen([sys.executable, "-c", "pass"])
    wait_until_ended(done.pid)                              # ended, and not yet reaped: a zombie
    assert is_ending(done.pid)
    live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    assert not is_ending(live.pid)
    sent_by_the_guard.send_again()
    live.kill()
    live.wait(10)
    done.wait(10)
