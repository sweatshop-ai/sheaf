"""`wait_until_ended`: a wait for a process to end that has a deadline, so a process that does not end fails the test and never hangs the run."""
import subprocess
import sys
import time

import pytest
from helpers import proc_state, wait_until_ended


def test_a_process_that_never_ends_fails_the_wait_at_its_deadline():
    live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        start = time.monotonic()
        with pytest.raises(TimeoutError):
            wait_until_ended(live.pid, seconds=0.3)
        assert time.monotonic() - start < 5
    finally:
        live.kill()
        live.wait(10)


def test_a_process_that_has_ended_but_is_not_yet_reaped_returns_the_wait():
    done = subprocess.Popen([sys.executable, "-c", "pass"])
    wait_until_ended(done.pid, seconds=10)
    assert proc_state(done.pid) == "zombie"        # it had ended and nobody had reaped it: the wait returned on that
    done.wait(10)
