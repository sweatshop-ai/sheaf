"""The Sheaf mounted over about 1000 pages, and a second listing fetched while the first pane is still open (SPEC 8.6).

Ticket 11 saw the second fetch freeze on a hub of 1067 pages. The listing tests (test_listing_loose_reads.py, test_listing_resolves_once.py)
count the hub's file reads; none of them mounts a pane of that size in a browser. This one does: pane A mounts every row, then a
second pane mounts `/_/mount?sheaf=1` beside it. The hub answers on threads (as it does when served), so the two listings overlap
there, and the page keeps a heartbeat so a renderer that stops answering is measured, not guessed."""
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest
from helpers import BEA, PLAN
from pagehelp import close_context, new_context, until

pytestmark = pytest.mark.page

ORIGIN = "http://sheaf.test"
FRONT = "/_front-for-test"
PAGES = 1000
FOLDERS = 20
FRONT_HTML = f"""<!doctype html><html><head><meta charset="utf-8"></head>
<body style="margin:0"><div id="pane" style="height:640px"></div><div id="second" style="height:640px"></div>
<script src="/_/mount.js"></script>
<script>sheafMount.mount(document.getElementById('pane'), {json.dumps({"sheaf": True})})
  .then((m) => {{ window.__page = m; }}, (e) => {{ window.__failed = String(e); }});</script>
</body></html>"""
# Every closed root the page attaches, in order: the first is pane A's, the second is the second pane's.
ROOTS = """(() => { const attach = Element.prototype.attachShadow;
  Element.prototype.attachShadow = function (o) { const r = attach.call(this, o); (window.__roots = window.__roots || []).push(r); return r; };
})();"""
# The renderer's heartbeat: a timer every 25 ms notes how long since the last one. A page that is busy for a second leaves a gap of a second.
BEAT = """window.__gaps = [];
(() => { let last = performance.now();
  setInterval(() => { const now = performance.now(); window.__gaps.push(now - last); last = now; }, 25); })();"""
SECOND = """window.__gaps = []; window.__t0 = performance.now(); window.__t1 = null;
  sheafMount.mount(document.getElementById('second'), {sheaf: true}).then(() => { window.__t1 = performance.now(); }, (e) => { window.__failed2 = String(e); });"""


@pytest.fixture
def thousand(front, work):
    subprocess.run(["git", "init", "-q", str(work)], check=True)
    for n in range(PAGES):
        f = work / f"folder{n % FOLDERS}" / f"page{n}.md"
        f.parent.mkdir(exist_ok=True)
        f.write_text(PLAN.replace("# Plan", f"# Page {n}", 1), encoding="utf-8")
    front.hub.roots.for_document(work / "folder0" / "page0.md")
    return front


class Hub:
    """The hub's answers to the page, computed on threads and handed to Playwright from the test's own: a route's handler runs only in
    the test thread, so a request is answered by `answer` putting it on a thread and by `drain` fulfilling it once the thread is done."""

    def __init__(self, front):
        self.front, self.pool, self.held = front, ThreadPoolExecutor(4), []

    def answer(self, route):
        path = route.request.url[len(ORIGIN):]
        if path == FRONT:
            return route.fulfill(status=200, content_type="text/html", body=FRONT_HTML)
        self.held.append((route, self.pool.submit(self.front.get, path, member=BEA)))

    def drain(self):
        for item in [h for h in self.held if h[1].done()]:
            self.held.remove(item)
            res = item[1].result()
            item[0].fulfill(status=res.status, headers=dict(res.headers), body=res.body)
        return True

    def wait(self, check, what, timeout=30.0):
        return until(lambda: self.drain() and check(), timeout=timeout, what=what)


def rows(page, which):
    return page.evaluate("(i) => window.__roots[i] ? window.__roots[i].querySelectorAll('.sheaf-row').length : -1", which)


def second_listing(chromium, thousand):
    """Mount pane A, start the heartbeat, mount the second pane; what the second cost, in ms, and what the renderer did meanwhile."""
    errors, hub = [], Hub(thousand)
    context = new_context(chromium)
    context.route(f"{ORIGIN}/**", hub.answer)
    try:
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.add_init_script(ROOTS)
        page.goto(ORIGIN + FRONT)
        hub.wait(lambda: page.evaluate("!!(window.__page || window.__failed)"), "pane A's mount")
        assert page.evaluate("window.__failed || null") is None
        hub.wait(lambda: rows(page, 0) == PAGES, f"{PAGES} rows in pane A")
        page.evaluate(BEAT)
        page.evaluate(SECOND)
        hub.wait(lambda: page.evaluate("window.__t1 !== null || !!window.__failed2"), "the second mount")
        assert page.evaluate("window.__failed2 || null") is None
        got = page.evaluate("({ms: window.__t1 - window.__t0, gap: Math.max(...window.__gaps), beats: window.__gaps.length})")
        got["rows"] = [rows(page, 0), rows(page, 1)]
        assert errors == [], "the Sheaf raised script errors"
        return got
    finally:
        close_context(context)


def test_a_second_listing_of_a_thousand_pages_completes_beside_the_first_and_the_renderer_answers(chromium, thousand):
    got = second_listing(chromium, thousand)
    assert False, got
