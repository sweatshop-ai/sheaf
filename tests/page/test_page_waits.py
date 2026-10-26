"""The waits of the page tests deliver the events Playwright has for the test."""
import re
import signal
import time
from pathlib import Path

import pytest

from pagehelp import PageStalled, reloaded, until

pytestmark = pytest.mark.page


def test_a_wait_gets_the_request_a_page_makes_after_the_test_last_called_playwright(tab):
    """`page.route` handlers run only while the test is inside a call into Playwright. This request leaves the
    page 100 ms after the last such call, so only a wait that itself calls Playwright ever sees it."""
    p = tab.open().page
    held = []
    p.route("**/_/not-a-route-of-the-hub", lambda route: held.append(route))
    p.evaluate("setTimeout(() => fetch('/_/not-a-route-of-the-hub').catch(() => {}), 100)")
    until(lambda: held, what="the request the page made on its own")
    held[0].abort()


def test_no_page_test_waits_by_sleeping_or_by_a_wait_of_its_own():
    """`pagehelp.until` is the one wait. A sleep in a test thread, or a second `until`, brings the old
    defect back; a `time.sleep` inside a patch of the hub (it runs on the hub's thread) does not."""
    here = Path(__file__).parent
    found = []
    for f in sorted(here.glob("*.py")):
        if f.name in ("pagehelp.py", Path(__file__).name):
            continue
        for n, line in enumerate(f.read_text(encoding="utf-8").splitlines(), 1):
            sleeps = "time.sleep(" in line and "LiveDocument" not in line
            own_wait = re.match(r"\s*def (until|wait_until|wait_for)\(", line)
            if sleeps or own_wait:
                found.append(f"{f.name}:{n}: {line.strip()}")
    assert found == []


# A page that never answers `evaluate` (Page.evaluate takes no timeout) used to block a run for ever:
# the one stall seen was at 1.5% CPU for 11 minutes. These two never answer on purpose.
STALL = "new Promise(r => setTimeout(r, 9000))"


def test_a_wait_on_a_page_that_stalls_fails_instead_of_blocking(tab):
    p = tab.open().page
    began = time.monotonic()
    with pytest.raises(PageStalled, match="the stalled page"):
        until(lambda: p.evaluate(STALL), timeout=1, what="the stalled page")
    assert time.monotonic() - began < 20


def test_a_reload_wait_on_a_page_that_stalls_fails_instead_of_blocking(tab):
    class Stalled:
        """The page of the test, whose `evaluate` (all `gone` calls) takes longer than the wait gives it."""
        evaluate = staticmethod(lambda expression: tab.page.evaluate(STALL))

    tab.open()
    began = time.monotonic()
    with pytest.raises(PageStalled, match="the page to reload"):
        reloaded(Stalled, timeout=1)
    assert time.monotonic() - began < 20


def test_a_wait_puts_back_the_timer_that_was_pending(tab):
    p = tab.open().page
    signal.setitimer(signal.ITIMER_REAL, 100)
    try:
        until(lambda: p.evaluate("true"))
        left, _ = signal.getitimer(signal.ITIMER_REAL)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert 80 < left < 100


def test_a_pending_timer_that_ends_sooner_is_left_alone(tab):
    p = tab.open().page
    signal.setitimer(signal.ITIMER_REAL, 50)
    try:
        until(lambda: p.evaluate("true"), timeout=100)
        left, _ = signal.getitimer(signal.ITIMER_REAL)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
    assert 30 < left < 50
