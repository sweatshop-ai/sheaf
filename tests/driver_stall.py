"""Ends the run at the first test that times out inside the Playwright driver.

The page tests share one driver (the session-scoped `chromium` fixture of tests/page/conftest.py). Once it
stops answering, every test left asks it the same question and waits out the per-test `timeout`, one after the
other: CI, run 43288137873, ten tests and 53 min, until the job's own limit cancelled it with no line saying
why, and with the traceback of the first test cut off, since pytest prints those at the end. A Playwright call
has a timeout of its own (30 s), so a test still inside the driver after 300 s is not waiting for the page,
unless it sits in a wait loop of its own; either way pytest-timeout's exception has ended the driver's dispatcher
for good, and every later call into it spins for ever.
That is also why the run is ended with `os._exit` and not `pytest.exit`: the session teardown of the `chromium`
fixture closes the browser and stops the driver, and it never returns (the Opus review of PR 260: the job held
until tools/ci/stall_watch.py killed it, 600 s of silence later). The process goes after the report is written.
The stall can follow a failure the log never explained (runs 43288137873 and 43326825430: the same page test failed
53 s in, then the driver stopped answering), so a page test that fails also shows its traceback at once.
Loaded by tests/conftest.py."""
import os
import re
import sys

# Frames of the pytest-timeout traceback that say the main thread was waiting for the driver (the ticket's journal:
# the `_context_manager` module of playwright.sync_api, `greenlet_main`), not in a call on a page
DRIVER_FRAMES = ("playwright/sync_api/_context_manager.py", "in greenlet_main")
TIMED_OUT = "from pytest-timeout"
FRAME_LINE = re.compile(r"^\S+:\d+: ")     # `path:line: in function`, the stack without the source around it


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


def say_a_page_test_failed(report):
    """A page test that fails shows its traceback now. pytest prints it in the failure summary at the end of the
    run, and a run that ends in the 60 min limit never gets there: CI, runs 43288137873 and 43326825430, the same
    test failed 53 s in and the log never said why."""
    if not report.failed or "page" not in report.keywords:
        return
    out = _config.pluginmanager.getplugin("terminalreporter")
    out.write_line(f"\n--- {report.nodeid} failed ({report.when}):\n{report.longreprtext}\n---")
    out.flush()


def pytest_runtest_logreport(report):
    text = stalled_in_driver(report)
    if text is None:
        say_a_page_test_failed(report)
        return
    stack = "\n".join(line for line in text.splitlines() if FRAME_LINE.match(line))
    # on the terminal at once: the failure summary, where pytest prints this traceback, is the part a cancelled job loses
    out = _config.pluginmanager.getplugin("terminalreporter")
    out.write_line(f"\n--- {report.nodeid}: timed out in the Playwright driver ({report.when}); its stack:\n{stack}\n---")
    out.write_line(f"!!! the Playwright driver no longer answers: {report.nodeid} timed out in it ({report.when}), "
                   "and every test after it would wait the same !!!")
    out.flush()
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(1)
