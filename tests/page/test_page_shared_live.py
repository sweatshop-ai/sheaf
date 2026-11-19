"""Seven tabs in one browser (ticket 160). A browser opens six connections to a host at most, and
each sheaf tab held one for its event stream: the seventh page never loaded, and a comment sent
from any tab waited for ever. The tabs now share one stream (page/live.js): the seventh loads at
once, the hub counts every tab, and a change on disk still reaches all of them."""
import time

import pytest

from pagehelp import DOC, close_context, new_context, until

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


def test_seven_tabs_load_count_and_all_hear_a_change(shared, site):
    pages = [opened(shared, site) for _ in range(TABS - 1)]
    until(lambda: site.hub.tabs(DOC) == TABS - 1, what="six tabs counted by the hub")
    t0 = time.monotonic()
    pages.append(opened(shared, site))
    assert time.monotonic() - t0 < 1.0, "the seventh tab took more than a second to load"
    until(lambda: site.hub.tabs(DOC) == TABS, what="seven tabs counted by the hub")
    f = site.file
    f.write_text(f.read_text(encoding="utf-8") + "\nFrom outside.\n", encoding="utf-8")
    for n, (p, _) in enumerate(pages):
        until(lambda: "From outside." in p.evaluate("document.body.textContent"),
              what=f"the change in tab {n + 1}")
    assert [e for _, e in pages] == [[]] * TABS


def test_a_tab_that_closes_leaves_the_count_and_the_leaders_tab_hands_over(shared, site):
    pages = [opened(shared, site) for _ in range(3)]
    until(lambda: site.hub.tabs(DOC) == 3, what="three tabs counted")
    pages[0][0].close()          # the first tab took the lock: the stream moves to another
    until(lambda: site.hub.tabs(DOC) == 2, what="two tabs counted")
    f = site.file
    f.write_text(f.read_text(encoding="utf-8") + "\nAfter the hand-over.\n", encoding="utf-8")
    for p, _ in pages[1:]:
        until(lambda: "After the hand-over." in p.evaluate("document.body.textContent"), what="the change heard")
    assert site.hub.tabs(DOC) == 2
