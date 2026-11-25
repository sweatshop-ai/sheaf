"""The index page's script in a real browser (SPEC 8.6): the words it keeps true between events."""
import re
from importlib import resources

import pytest

from helpers import comment
from pagehelp import close_context, new_context, until
from sheafmd.hub import index

pytestmark = pytest.mark.page

ROW = "#roots li.doc"


def script_ago() -> str:
    """`ago` as page/index.js writes it, taken out of the script whole."""
    src = resources.files("sheafmd.page").joinpath("index.js").read_text(encoding="utf-8")
    found = re.search(r"^  function ago\(sec\) \{\n.*?^  \}\n", src, re.S | re.M)
    assert found, "page/index.js has no function ago(sec)"
    return found.group(0)


def test_the_script_says_how_long_ago_in_the_words_the_hub_writes(chromium):
    """The hub writes "N min ago" in each row and the script rewrites it every 30 s: the same
    seconds must read the same, or a row says "2 min ago" and then "1 min ago" at the next
    refresh. The hub floors the minutes."""
    seconds = [0, 44, 45, 59, 60, 89, 90, 100, 119, 120, 150, 3539, 3540, 3599, 3600, 5399,
               86399, 86400, 172799, 172800, 30 * 86400 - 1]
    page = chromium.new_page()
    try:
        said = page.evaluate(f"(seconds) => {{ {script_ago()} return seconds.map(ago); }}", seconds)
    finally:
        page.close()
    assert dict(zip(seconds, said)) == {s: index.ago(s) for s in seconds}


class IndexTab:
    """The index page, open and signed in, its stream open on the hub. `errors` holds every script
    error it raised."""

    def __init__(self, context, site):
        self.page, self.errors = context.new_page(), []
        self.page.on("pageerror", lambda e: self.errors.append(str(e)))
        self.page.goto(f"{site.base}/")
        self.page.wait_for_selector("#roots", state="attached")
        until(lambda: site.hub.index_bus.count() == 1, what="the index stream open on the hub")

    def dot(self):
        row = self.page.query_selector(ROW)
        return row and row.get_attribute("data-dot")

    def hub_line(self):
        """What the page says about the hub, or "" while it says nothing."""
        return "" if self.page.eval_on_selector("#live", "e => e.hidden") else self.page.inner_text("#live")


@pytest.fixture
def index_tab(context, site):
    t = IndexTab(context, site)
    yield t
    assert t.errors == [], "the index page raised script errors"


def test_the_index_page_moves_a_dot_with_no_tab_open_on_the_document(site, index_tab):
    """Nobody has the document open: the dot moves because the hub's sweep sees the file change
    and tells the index stream, and the script asks for the page again (SPEC 8.6, 8.8)."""
    before = index_tab.dot()
    assert before and before != "blue"
    comment(site.file)
    until(lambda: index_tab.dot() == "blue", timeout=15, what="the dot of a document with an open comment")


def test_the_index_page_drops_the_row_of_a_root_that_is_forgotten(site, index_tab):
    name = site.hub.roots.address(site.file).split("/")[0]
    assert index_tab.page.query_selector(ROW)
    site.hub.forget_root(name)
    until(lambda: index_tab.page.query_selector(ROW) is None, timeout=15, what="the row of the forgotten root")


def test_the_index_page_says_the_hub_stopped_and_is_current_again_when_it_runs(site, index_tab):
    assert index_tab.hub_line() == ""
    site.stop()
    until(lambda: "The hub stopped" in index_tab.hub_line(), what="the line that the hub stopped")
    comment(site.file)
    site.start()
    until(lambda: index_tab.hub_line() == "", timeout=15, what="the line gone once the hub runs again")
    until(lambda: index_tab.dot() == "blue", timeout=15, what="the dot of what changed while the hub was away")


def test_the_index_page_says_reconnecting_and_not_stopped_when_the_hub_restarts_for_an_upgrade(site, index_tab):
    """`sheaf restart` sends `hub-stopping` with reason `upgrade`: no stop line, as on the document page
    (SPEC 8.4, 8.6)."""
    site.stop("upgrade")
    until(lambda: index_tab.hub_line() == "Reconnecting to the hub…", what="the line that the page reconnects")
    site.start()
    until(lambda: index_tab.hub_line() == "", timeout=15, what="the line gone once the hub runs again")


@pytest.fixture
def shared(chromium, site):
    """A browser whose tabs share one stream (page/live.js), as every browser with Web Locks does."""
    c = new_context(chromium, shared=True, viewport={"width": 1100, "height": 800})
    c.add_cookies([site.cookie()])
    yield c
    close_context(c)


def test_a_join_whose_answer_is_lost_leaves_no_stream_on_the_hub(site, shared):
    """The hub took the index's join, and its answer never reached the browser (a network error after the hub had it).
    The page asks for a new stream under a new key; the first key got no leave, and the hub counted two index tabs for
    the life of the connection (ticket 189 A). The leader leaves a key whose join had no answer."""
    lost, joins = [], []

    def once(route):
        index = route.request.post_data_json.get("doc") == ""
        if index:
            joins.append(1)
        if index and not lost:
            route.fetch()                # the hub takes the join
            lost.append(1)
            route.abort("connectionreset")   # and the browser hears no answer
        else:
            route.continue_()
    shared.route("**/_/live/join", once)
    tab = IndexTab.__new__(IndexTab)
    tab.page, tab.errors = shared.new_page(), []
    tab.page.on("pageerror", lambda e: tab.errors.append(str(e)))
    tab.page.goto(f"{site.base}/")
    tab.page.wait_for_selector("#roots", state="attached")
    until(lambda: lost, what="the index's first join taken by the hub and its answer lost")
    until(lambda: len(joins) >= 2 and tab.hub_line() == "", timeout=15, what="the index joined again")
    until(lambda: site.hub.index_bus.count() == 1, timeout=15, what="one index stream on the hub, not two")
    tab.page.wait_for_timeout(2500)      # a ghost would stay: the count holds at one (not time.sleep: routes)
    assert site.hub.index_bus.count() == 1
    assert tab.errors == []


def test_the_index_page_joins_again_after_its_join_is_refused(site, shared):
    """A join the hub does not take (429, a network error, a 404 at a rollover) closes the index's stream for good
    (readyState 2), and the page said "Reconnecting to the hub…" for ever. It asks for a new stream, as the document
    page does: the line goes, and a change reaches the list."""
    refused = []

    def once(route):
        if route.request.post_data_json.get("doc") == "" and not refused:
            refused.append(1)
            route.fulfill(status=429, content_type="application/json", body='{"ok": false, "error": "too many"}')
        else:
            route.continue_()
    shared.route("**/_/live/join", once)
    tab = IndexTab.__new__(IndexTab)
    tab.page, tab.errors = shared.new_page(), []
    tab.page.on("pageerror", lambda e: tab.errors.append(str(e)))
    tab.page.goto(f"{site.base}/")
    tab.page.wait_for_selector("#roots", state="attached")
    until(lambda: refused, what="the index's first join refused")
    until(lambda: site.hub.index_bus.count() == 1, timeout=15, what="the index stream open on the hub again")
    until(lambda: tab.hub_line() == "", what="no line about the hub once it is joined")
    comment(site.file)
    until(lambda: tab.dot() == "blue", timeout=15, what="the dot of a document with an open comment")
    assert tab.errors == []
