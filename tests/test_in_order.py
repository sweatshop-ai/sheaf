"""A file with IN_ORDER = True keeps its tests on one xdist worker, in the file's order (tests/conftest.py)."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ISOLATION = "tests/test_isolation.py::"


def test_the_tests_of_a_file_that_read_what_the_test_before_left_run_on_one_worker():
    """CI runs `pytest -n 4`, which hands tests to workers one by one: the test that reads the hub the test
    before it started then ran on a worker whose own list was empty (run 43232192468, `assert ([])`). Three
    tests on two workers is the smallest split of that pair."""
    ids = [ISOLATION + name for name in (
        "test_no_variable_of_the_agent_that_runs_the_suite_reaches_a_test",
        "test_a_command_that_starts_a_hub_starts_it_on_that_port",
        "test_the_hub_that_test_started_was_stopped_when_it_ended",
    )]
    r = subprocess.run([sys.executable, "-m", "pytest", "-n", "2", "-p", "no:cacheprovider", *ids],
                       cwd=ROOT, capture_output=True, text=True, timeout=240)
    assert r.returncode == 0, r.stdout[-2000:]
