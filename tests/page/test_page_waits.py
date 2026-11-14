"""The waits of the page tests deliver the events Playwright has for the test."""
import re
import signal
import time
from pathlib import Path

import pytest

from pagehelp import PageStalled, reloaded, toast, toasted, toasts_to_the_end, until

pytestmark = pytest.mark.page

PlaywrightError = pytest.importorskip("playwright.sync_api").Error


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


class ReloadingPage:
    """A page whose `evaluate` fails the way Playwright's does when a poll lands on a reload (ticket 53)."""
    def __init__(self, message):
        self.message = message

    def evaluate(self, expression):
        raise PlaywrightError(self.message)


@pytest.mark.parametrize("message", [
    "TypeError: Cannot read properties of null (reading 'textContent')",     # the new page has no #rd-toast yet
    "Execution context was destroyed, most likely because of a navigation",  # the poll fell on the navigation
])
def test_reading_the_toast_during_a_reload_says_not_yet_instead_of_raising(message):
    assert toast(ReloadingPage(message)) == ""
    # a poll inside `until` gets "not yet" too, the way the refusal waits of test_page_actions.py call it
    assert until(lambda: "reload the page" not in toast(ReloadingPage(message)), timeout=1, what="no toast yet")


def test_reading_the_toast_still_raises_for_any_other_driver_error():
    """A driver that has gone away must stay visible: only the two errors of a reload are an answer."""
    with pytest.raises(PlaywrightError, match="Target closed"):
        toast(ReloadingPage("Target page, context or browser has been closed: Target closed"))


class QueuedToasts:
    """A page whose toasts queue as the page's do (ticket 62): the next one is shown as soon as the one up has had its
    time, and time passes only when the test runs the clock. `toasts` is (text, ms) in the order they were said."""
    def __init__(self, *toasts):
        self.queue, self.text, self.left, self.clock = list(toasts), "", 0, self
        self._next()

    def _next(self):
        if self.queue:
            self.text, self.left = self.queue.pop(0)

    def evaluate(self, expression):
        return [self.text, self.left > 0]

    def run_for(self, ms):
        self.left -= ms
        if self.left <= 0:
            self.left = 0
            self._next()


def test_a_toast_behind_a_red_one_comes_when_the_clock_is_run_on():
    page = QueuedToasts(("Did not go out.", 7000), ("New reply.", 2600), ("It reached the hub after all.", 2600))
    toasted(page, "reached the hub", on_clock=True)
    assert toast_text(page) == "It reached the hub after all."


def test_a_toast_behind_another_does_not_come_while_the_clock_stands_still_and_the_failure_names_the_ones_that_did():
    page = QueuedToasts(("Did not go out.", 7000), ("It reached the hub after all.", 2600))
    with pytest.raises(AssertionError, match=r"timed out waiting for a toast saying 'reached the hub'; the toasts that went by: \['Did not go out.'\]"):
        toasted(page, "reached the hub", timeout=0.3)


def toast_text(page):
    return page.text


def test_the_toasts_to_the_end_are_the_one_up_and_every_one_queued_behind_it_in_order():
    page = QueuedToasts(("Saving", 2600), ("Not saved", 7000), ("Saved", 2600))
    assert toasts_to_the_end(page, on_clock=True) == ["Saving", "Not saved", "Saved"]


def test_the_toasts_to_the_end_of_a_page_with_none_up_are_none():
    assert toasts_to_the_end(QueuedToasts(), on_clock=True) == []


def test_the_toasts_to_the_end_are_not_at_an_end_while_the_page_reloads():
    """The page the reload brings may say a toast of its own: an assertion that one is not said must not read "none" off the gap."""
    with pytest.raises(AssertionError, match="timed out waiting for the toasts to end"):
        toasts_to_the_end(ReloadingPage("Execution context was destroyed, most likely because of a navigation"), timeout=0.3)
