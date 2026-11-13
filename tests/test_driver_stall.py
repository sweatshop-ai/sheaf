"""CI, run 43288137873: the Playwright driver of the session stopped answering in one page test, and the ten
page tests after it each waited out their 300 s before the job's 60 min ended it, with no line saying why. The
first test that times out inside the driver now ends the run, names itself and shows where it stood."""
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

TESTS = Path(__file__).resolve().parent

# A driver that never answers, laid out as Playwright's is: the frame `greenlet_main` of
# the `_context_manager` module of playwright.sync_api, where the main thread waits for the driver.
FAKE_DRIVER = '''
import threading


def greenlet_main():
    threading.Event().wait()
'''

SUITE = '''
from playwright.sync_api._context_manager import greenlet_main


def test_first_asks_the_driver():
    greenlet_main()


def test_second_asks_the_driver():
    greenlet_main()


def test_third_asks_the_driver():
    greenlet_main()
'''


# The session fixture of tests/page/conftest.py closes the browser and stops the driver when the run ends. After
# the alarm has interrupted the driver's dispatcher those calls never return (found by the Opus review of PR 260).
HANGING_TEARDOWN = '''

import pytest


@pytest.fixture(scope="session", autouse=True)
def browser():
    yield
    greenlet_main()
'''


def run(tmp_path, *args, hanging_teardown=False, suite_text=SUITE):
    driver = tmp_path / "fake" / "playwright" / "sync_api"
    driver.mkdir(parents=True)
    (driver.parent / "__init__.py").write_text("")
    (driver / "__init__.py").write_text("")
    (driver / "_context_manager.py").write_text(textwrap.dedent(FAKE_DRIVER))
    suite = tmp_path / "suite"
    suite.mkdir()
    (suite / "test_driver.py").write_text(textwrap.dedent(suite_text) + (HANGING_TEARDOWN if hanging_teardown else ""))
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": f"{tmp_path / 'fake'}:{TESTS}"}
    start = time.monotonic()
    try:
        r = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--timeout=1", "-v", *args],
                           cwd=suite, env=env, capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or b"") + (e.stderr or b"")
        pytest.fail("the run was still going after 30 s:\n" + (out.decode() if isinstance(out, bytes) else out))
    return r, r.stdout + r.stderr, time.monotonic() - start


def test_without_the_hook_every_test_waits_out_its_own_limit(tmp_path):
    r, out, _ = run(tmp_path)

    assert r.returncode == 1, out
    assert out.count("Failed: Timeout (>1.0s)") >= 3, out


def test_the_first_test_that_times_out_in_the_driver_ends_the_run_and_names_itself(tmp_path):
    r, out, _ = run(tmp_path, "-p", "driver_stall")

    assert r.returncode == 1, out
    assert "test_driver.py::test_first_asks_the_driver" in out, out
    assert "Playwright driver no longer answers" in out, out
    assert "greenlet_main" in out, out        # where it stood, for the log that the cancel cuts short
    assert "test_second_asks_the_driver" not in out, out


def test_a_test_that_times_out_elsewhere_does_not_end_the_run(tmp_path):
    (tmp_path / "suite").mkdir()
    (tmp_path / "suite" / "test_slow.py").write_text(
        "import threading\n\n\ndef test_slow():\n    threading.Event().wait()\n\n\ndef test_fine():\n    pass\n")
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": str(TESTS)}
    r = subprocess.run([sys.executable, "-m", "pytest", "-p", "no:cacheprovider", "--timeout=1", "-p", "driver_stall",
                        "-v"], cwd=tmp_path / "suite", env=env, capture_output=True, text=True, timeout=120)
    out = r.stdout + r.stderr

    assert "test_fine PASSED" in out, out
    assert "Playwright driver" not in out, out


def test_the_run_ends_at_once_though_the_session_teardown_would_ask_the_dead_driver_for_ever(tmp_path):
    r, out, took = run(tmp_path, "-p", "driver_stall", hanging_teardown=True)

    assert r.returncode == 1, out
    assert "Playwright driver no longer answers" in out, out
    assert took < 20, out


# CI, runs 43288137873 and 43326825430: the same page test failed 53 s after the one before it, with no traceback in
# the log (pytest prints those at the end, which the cancelled job never reached), and the driver stopped answering
# after it. The traceback is on the terminal when the test fails.
FAILS_THEN_STALLS = '''
import pytest
from playwright.sync_api._context_manager import greenlet_main


@pytest.mark.page
def test_first_fails_on_its_own():
    assert "the box is ticked" == "the box is not", "the distinctive failure"


@pytest.mark.page
def test_second_asks_the_driver():
    greenlet_main()
'''


def test_a_page_test_that_fails_shows_its_traceback_at_once_not_at_the_end_of_the_run(tmp_path):
    r, out, _ = run(tmp_path, "-p", "driver_stall", suite_text=FAILS_THEN_STALLS)

    assert r.returncode == 1, out
    assert "the distinctive failure" in out, out
    assert "test_first_fails_on_its_own" in out, out
    assert out.index("the distinctive failure") < out.index("Playwright driver no longer answers"), out


def test_a_test_that_is_not_a_page_test_keeps_its_traceback_for_the_end_of_the_run(tmp_path):
    r, out, _ = run(tmp_path, "-p", "driver_stall", suite_text=FAILS_THEN_STALLS.replace("@pytest.mark.page\n", ""))

    assert r.returncode == 1, out
    assert "the distinctive failure" not in out, out
