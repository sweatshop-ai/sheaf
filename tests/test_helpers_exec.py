"""`write_executable`: a script the product will exec is never handed back while a forked
sibling still holds a write handle on it."""
import subprocess
import threading

import pytest

from agent_fakes import FakeClaude
from helpers import wait_until_executable, write_executable


def busy(path) -> bool:
    """Whether the kernel refuses to exec `path` right now, with ETXTBSY."""
    try:
        subprocess.run([str(path)], capture_output=True)
    except OSError as e:
        return e.errno == 26
    return False


def test_an_exec_of_a_file_held_open_for_writing_waits_for_the_holder_to_let_go(tmp_path):
    """The race of the fakes, held still: the handle a sibling's fork would copy is open, the kernel
    refuses the exec, and `wait_until_executable` returns only after the handle is closed."""
    script = write_executable(tmp_path / "fake", "#!/bin/sh\necho ran\n")
    holder = open(script, "a")
    try:
        if not busy(script):
            pytest.skip("this kernel runs a file that is open for writing; the race is Linux's")
        threading.Timer(0.2, holder.close).start()
        wait_until_executable(script)
        assert holder.closed
        assert not busy(script)
        assert subprocess.run([str(script)], capture_output=True, text=True).stdout == "ran\n"
    finally:
        holder.close()


def test_a_file_nobody_holds_open_is_handed_back_at_once(tmp_path):
    script = write_executable(tmp_path / "fake", "#!/bin/sh\necho ran\n")
    wait_until_executable(script, seconds=0.5)
    assert subprocess.run([str(script)], capture_output=True, text=True).stdout == "ran\n"


def test_a_holder_that_never_lets_go_is_an_error_not_a_hang(tmp_path):
    script = write_executable(tmp_path / "fake", "#!/bin/sh\n")
    with open(script, "a"):
        if not busy(script):
            pytest.skip("this kernel runs a file that is open for writing; the race is Linux's")
        with pytest.raises(TimeoutError):
            wait_until_executable(script, seconds=0.1)


def test_fakes_written_while_sibling_threads_fork_run_every_time(tmp_path):
    """The race itself, not held still: threads fork all the while the main thread writes a fake and
    the product's exec follows. Each fake the tests share (`FakeClaude`, `write_executable`) must run
    on every round; written with `write_text` and `chmod`, a round in a few hundred fails with errno 26."""
    stop = threading.Event()

    def forker():
        while not stop.is_set():
            subprocess.run(["/bin/true"])

    threads = [threading.Thread(target=forker) for _ in range(4)]
    for t in threads:
        t.start()
    try:
        for n in range(300):
            fake = FakeClaude(tmp_path / f"c{n}")
            subprocess.run([str(fake.bin)], input=b"", capture_output=True, check=True)
            plain = write_executable(tmp_path / f"p{n}", "#!/bin/sh\nexit 0\n")
            subprocess.run([str(plain)], check=True)
    finally:
        stop.set()
        for t in threads:
            t.join()
