"""Seven tabs in one browser (ticket 160). A browser opens six connections to a host at most, and
each sheaf tab held one for its event stream: the seventh page never loaded, and a comment sent
from any tab waited for ever. The tabs now share one stream (page/live.js): the seventh loads at
once, the hub counts every tab, and a change on disk still reaches all of them."""
import time

import pytest

from pagehelp import DOC, RELOADING, close_context, new_context, until, rewrite

pytestmark = pytest.mark.page

TABS = 7


@pytest.fixture
def shared(chromium, site):
    c = new_context(chromium, shared=True, viewport={"width": 1100, "height": 800})
    c.add_cookies([site.cookie()])
    yield c
    close_context(c)


def opened(context, site):
    p = context.new_page()
    errors = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.goto(site.url)
    p.wait_for_selector("#rd-menu-btn", state="attached")
    return p, errors


def shows(p, text):
    """Whether the page shows `text`. A change from outside reloads the page, so a read can fall on the reload:
    that is not yet."""
    try:
        return text in p.evaluate("document.body.textContent")
    except Exception as e:
        if any(said in str(e) for said in RELOADING):
            return False
        raise


def test_seven_tabs_load_count_and_all_hear_a_change(shared, site):
    pages = [opened(shared, site) for _ in range(TABS - 1)]
    until(lambda: site.hub.tabs(DOC) == TABS - 1, what="six tabs counted by the hub")
    t0 = time.monotonic()
    pages.append(opened(shared, site))
    assert time.monotonic() - t0 < 1.0, "the seventh tab took more than a second to load"
    until(lambda: site.hub.tabs(DOC) == TABS, what="seven tabs counted by the hub")
    f = site.file
    rewrite(f, f.read_text(encoding="utf-8") + "\nFrom outside.\n")
    for n, (p, _) in enumerate(pages):
        until(lambda: shows(p, "From outside."),
              what=f"the change in tab {n + 1}")
    assert [e for _, e in pages] == [[]] * TABS


def test_a_tab_that_closes_leaves_the_count_and_the_leaders_tab_hands_over(shared, site):
    pages = [opened(shared, site) for _ in range(3)]
    until(lambda: site.hub.tabs(DOC) == 3, what="three tabs counted")
    pages[0][0].close()          # the first tab took the lock: the stream moves to another
    until(lambda: site.hub.tabs(DOC) == 2, what="two tabs counted")
    f = site.file
    rewrite(f, f.read_text(encoding="utf-8") + "\nAfter the hand-over.\n")
    for p, _ in pages[1:]:
        until(lambda: shows(p, "After the hand-over."), what="the change heard")
    # A change from outside reloads both pages; the hub drops a closed page's stream within its next read check.
    until(lambda: site.hub.tabs(DOC) == 2, what="two tabs counted after the reload")


def test_a_frozen_leader_hands_the_stream_over_and_takes_it_back_on_resume(shared, site):
    """Chrome freezes a background tab (memory saver, battery saver). A frozen leader keeps its lock and relays
    nothing, so the visible tabs would stop hearing changes. On `freeze` it lets go; on `resume` it queues again."""
    pages = [opened(shared, site) for _ in range(3)]
    until(lambda: site.hub.tabs(DOC) == 3, what="three tabs counted")
    leader = pages[0][0]         # the first tab took the lock
    cdp = shared.new_cdp_session(leader)
    cdp.send("Page.enable")
    cdp.send("Page.setWebLifecycleState", {"state": "frozen"})
    f = site.file
    f.write_text(f.read_text(encoding="utf-8") + "\nWhile frozen.\n", encoding="utf-8")
    for n, (p, _) in enumerate(pages[1:], 2):
        until(lambda: shows(p, "While frozen."), what=f"the change in tab {n} while the leader is frozen")
    cdp.send("Page.setWebLifecycleState", {"state": "active"})
    until(lambda: site.hub.tabs(DOC) == 3, what="three tabs counted after the resume")
    f.write_text(f.read_text(encoding="utf-8") + "\nAfter the resume.\n", encoding="utf-8")
    for n, (p, _) in enumerate(pages):
        until(lambda: shows(p, "After the resume."), what=f"the change in tab {n + 1} after the resume")


def test_a_frozen_tab_that_waits_for_the_lock_is_not_handed_it(shared, site):
    """The leader and a second tab freeze together: the lock must pass to the third, not to the frozen second,
    whose request was queued and could never run."""
    pages = [opened(shared, site) for _ in range(3)]
    until(lambda: site.hub.tabs(DOC) == 3, what="three tabs counted")
    for p, _ in pages[:2]:
        shared.new_cdp_session(p).send("Page.setWebLifecycleState", {"state": "frozen"})
    f = site.file
    f.write_text(f.read_text(encoding="utf-8") + "\nWith two tabs frozen.\n", encoding="utf-8")
    until(lambda: shows(pages[2][0], "With two tabs frozen."), what="the change in the third tab")


def test_a_tab_that_leaves_without_a_leave_is_dropped_when_its_lock_frees(shared, site):
    """A tab that crashes sends no `pagehide` and says nothing: only its Web Lock is freed. The leader must hear
    that from the lock itself, not from a poll every SWEEP (2 s), which Chrome slows to once a minute in a tab
    hidden for five minutes. The tab here says nothing (its `leave` is dropped) and closes."""
    pages = [opened(shared, site) for _ in range(3)]
    until(lambda: site.hub.tabs(DOC) == 3, what="three tabs counted")
    pages[2][0].evaluate("BroadcastChannel.prototype.postMessage = function () {}")
    t0 = time.monotonic()
    pages[2][0].close()
    until(lambda: site.hub.tabs(DOC) == 2, timeout=1.0, what="two tabs counted after the tab went")
    assert time.monotonic() - t0 < 1.0
