"""Ends the run at the first test that times out inside the Playwright driver.

The page tests share one driver (the session-scoped `chromium` fixture of tests/page/conftest.py). Once it
stops answering, every test left asks it the same question and waits out the per-test `timeout`, one after the
other: CI, run 43288137873, ten tests and 53 min, until the job's own limit cancelled it with no line saying
why, and with the traceback of the first test cut off, since pytest prints those at the end. A Playwright call
has a timeout of its own (30 s), so a test still inside the driver after 300 s is not waiting for the page.
Loaded by tests/conftest.py."""
import pytest

# Frames of the pytest-timeout traceback that say the main thread was waiting for the driver (the ticket's journal:
# `playwright/sync_api/_context_manager.py`, `greenlet_main`), not in a call on a page
DRIVER_FRAMES = ("playwright/sync_api/_context_manager.py", "in greenlet_main")
TIMED_OUT = "from pytest-timeout"
TAIL_LINES = 40


def stalled_in_driver(report):
    """The traceback of a failed phase that pytest-timeout ended inside Playwright, else None."""
    if not report.failed or report.longrepr is None:
        return None
    text = str(report.longrepr)
    if TIMED_OUT in text and all(frame in text for frame in DRIVER_FRAMES):
        return text
    return None


_config = None


def pytest_configure(config):
    global _config
    _config = config


def pytest_runtest_logreport(report):
    text = stalled_in_driver(report)
    if text is None:
        return
    tail = "\n".join(text.splitlines()[-TAIL_LINES:])
    # on the terminal at once: the failure summary, where pytest prints this traceback, is the part a cancelled job loses
    out = _config.pluginmanager.getplugin("terminalreporter")
    out.write_line(f"\n--- {report.nodeid}: timed out in the Playwright driver ({report.when}); the last {TAIL_LINES} "
                   f"lines of its traceback:\n{tail}\n---")
    pytest.exit(f"the Playwright driver no longer answers: {report.nodeid} timed out in it ({report.when}), "
                "and every test after it would wait the same", returncode=1)
