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


def test_a_route_for_a_send_holds_the_send_the_page_makes_as_soon_as_route_returns(tab):
    """Ticket 100: on a loaded runner the browser was not yet intercepting when `route()` returned, so a send made a
    few ms later went straight to the hub. conftest's `until_live` waits for a probe; it must not itself be held
    as a send, nor leave the route short of the send."""
    p = tab.open().page
    for _ in range(20):
        held = []
        p.route("**/_/comment", lambda route: held.append(route))
        p.evaluate("fetch('/_/comment', {method: 'POST', body: '{}'}).catch(() => {}); 0")
        until(lambda: held or p.wait_for_timeout(20), what="the send to be held")
        assert len(held) == 1 and held[0].request.method == "POST"
        held[0].abort()
        p.unroute("**/_/comment")


def test_the_stream_journal_leaves_eventsource_open_to_a_subclass_a_test_installs(tab):
    """The journal wraps window.EventSource; test_page_actions.py's DEAF script does `class extends window.EventSource`
    and overrides addEventListener. A wrapper that returns a native object lost the override (ticket 100, PR 346's CI)."""
    p = tab.open().page
    assert p.evaluate("""(() => {
      class Deaf extends window.EventSource {
        addEventListener(k, f, o) { Deaf.seen = true; return super.addEventListener(k, f, o); }
      }
      const d = new Deaf('/_/live?doc=work%2Fplan.md');
      d.addEventListener('changed', () => {});
      d.close();
      return [d instanceof Deaf, !!Deaf.seen];
    })()""") == [True, True]


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
    assert page.text == "It reached the hub after all."


def test_a_toast_behind_another_does_not_come_while_the_clock_stands_still_and_the_failure_names_the_ones_that_did():
    page = QueuedToasts(("Did not go out.", 7000), ("It reached the hub after all.", 2600))
    with pytest.raises(AssertionError, match=r"timed out waiting for a toast saying 'reached the hub'; the toasts that went by: \['Did not go out.'\]"):
        toasted(page, "reached the hub", timeout=0.3)


def test_the_toasts_to_the_end_are_the_one_up_and_every_one_queued_behind_it_in_order():
    page = QueuedToasts(("Saving", 2600), ("Not saved", 7000), ("Saved", 2600))
    assert toasts_to_the_end(page, on_clock=True) == ["Saving", "Not saved", "Saved"]


def test_the_toasts_to_the_end_of_a_page_whose_queue_has_ended_are_none_not_the_last_one_said():
    """#rd-toast keeps its text when the toast goes: a second look, the queue done, must not say it again."""
    page = QueuedToasts(("The text changed while you wrote.", 2600))
    assert toasts_to_the_end(page, on_clock=True) == ["The text changed while you wrote."]
    assert toasts_to_the_end(page, on_clock=True) == []


def test_the_toasts_to_the_end_do_not_say_a_toast_that_is_up_with_no_text():
    """A test may blank #rd-toast while it is still up (writing: 'Saving' said once): that is not a toast said."""
    page = QueuedToasts(("", 2600))
    assert toasts_to_the_end(page, on_clock=True) == []


def test_the_toasts_to_the_end_of_a_page_with_none_up_are_none():
    assert toasts_to_the_end(QueuedToasts(), on_clock=True) == []


def test_the_toasts_to_the_end_are_not_at_an_end_while_the_page_reloads():
    """The page the reload brings may say a toast of its own: an assertion that one is not said must not read "none" off the gap."""
    with pytest.raises(AssertionError, match="timed out waiting for the toasts to end"):
        toasts_to_the_end(ReloadingPage("Execution context was destroyed, most likely because of a navigation"), timeout=0.3)


# ── the route wrapper of conftest.py (tickets 100 and 119) ─────────────────────────────────────────────────

class ReplacementPage:
    """A page that answers the probe of `until_live` like a browser that has not started to intercept: `answers` in turn."""
    url = "http://127.0.0.1:1/doc"

    def __init__(self, answers):
        self.answers, self.asked = list(answers), []

    def evaluate(self, expression):
        self.asked.append(expression)
        return self.answers.pop(0)

    def wait_for_timeout(self, ms):
        pass


def test_the_probe_of_a_route_is_sent_until_the_route_has_caught_it():
    from conftest import until_live
    page, log = ReplacementPage([0, 0, 204]), []
    until_live(page, "**/_/comment", log)
    assert len(page.asked) == 3 and all("x-route-probe" in a and "/_/comment" in a for a in page.asked)
    assert "caught its probe at try 3" in log[-1][1]


def test_a_route_of_another_url_is_not_probed():
    from conftest import until_live
    page = ReplacementPage([])
    for pattern in ("**/_/save", re.compile(r"/_/tell$"), re.compile(r"/_/doc\?")):
        until_live(page, pattern, [])
    assert page.asked == []


def test_a_route_made_with_a_regex_for_the_send_is_probed_too(tab, hub_journal):
    """PR 346's review: `route(re.compile(r"/_/comment$"), ...)` (test_page_work.py) had the race of ticket 100 and no probe."""
    p = tab.open().page
    held = []
    p.route(re.compile(r"/_/comment$"), lambda route: held.append(route))
    assert any("live" in what and "comment" in what for _, what in hub_journal), hub_journal
    p.evaluate("fetch('/_/comment', {method: 'POST', body: '{}'}).catch(() => {}); 0")
    until(lambda: held or p.wait_for_timeout(20), what="the send to be held")
    assert len(held) == 1 and held[0].request.method == "POST"
    held[0].abort()


def test_a_function_routed_twice_on_one_url_is_taken_off_both_by_unroute(tab):
    p = tab.open().page
    held = []

    def hold(route):
        held.append(route)
        route.abort()       # a regression fails the assert below, not by a fetch that never answers
    p.route("**/_/not-a-route-of-the-hub", hold)
    p.route("**/_/not-a-route-of-the-hub", hold)
    p.unroute("**/_/not-a-route-of-the-hub", hold)
    assert p.evaluate("fetch('/_/not-a-route-of-the-hub').then(r => r.status, () => 0)") != 0
    assert held == []


def test_a_handler_that_cannot_be_hashed_can_be_routed_and_unrouted(tab):
    class Holder:
        def __init__(self):
            self.held = []

        def __eq__(self, other):
            return self is other
        __hash__ = None

        def __call__(self, route):
            self.held.append(route)
            route.abort()
    p = tab.open().page
    h = Holder()
    p.route("**/_/not-a-route-of-the-hub", h)
    p.evaluate("fetch('/_/not-a-route-of-the-hub').catch(() => {}); 0")
    until(lambda: h.held or p.wait_for_timeout(20), what="the request to be held")
    p.unroute("**/_/not-a-route-of-the-hub", h)
    assert p.evaluate("fetch('/_/not-a-route-of-the-hub').then(r => r.status, () => 0)") != 0
    assert len(h.held) == 1


def test_the_stream_journal_keeps_real_time_when_a_test_puts_a_fake_clock_under_the_page(tab):
    """PR 346's review: the journal takes real time before the fake clock replaces `performance`, if its init script
    runs first. Playwright does not document the order; the journal of a failing test is read by its times."""
    from pagehelp import T0, reload_on_clock
    p = tab.open().page
    reload_on_clock(p, start=T0)
    p.evaluate("fetch('/_/not-a-route-of-the-hub').catch(() => {}); 0")
    times = p.evaluate("window.__sseJournal.map(e => e[0])")
    assert times and all(abs(t / 1000 - time.time()) < 120 for t in times), (times, time.time())
