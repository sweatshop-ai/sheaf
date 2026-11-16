"""The Sheaf mounted in the front's document (SPEC 8.6): `sheafMount.mount(host, {sheaf: true})` builds the tree and the table
in a closed shadow root from `/_/mount?sheaf=1` (data, never markup) and sheaf.js makes it live: folders that collapse, a
folder that narrows the table, a filter on titles, and a click on a row that takes the pane for the rectoverso under a
"← Sheaf" button. Every request is answered by the hub's proxy handler as Bea. The page's clock is Playwright's."""
import json
import subprocess

import pytest
from helpers import BEA, PLAN
from pagehelp import close_context, new_context, until

pytestmark = pytest.mark.page

ORIGIN = "http://sheaf.test"
SID_RC, SID_BARE = "6f1c2f0e-3a55-4a0e-9d52-0c1f6a1b7d11", "a2d8e4b1-5c70-4f53-8f02-2a9e6d3c7b90"
RC = "https://rc.example.com/code/session_abc123"
CHAT = "3f2a9c1e-77aa-4b1d-9a10-5d0e8b6c2f44"
AGENTVIEW = "http://127.0.0.1:8765"
OPENED = "window.__clicks = []; window.addEventListener('click', (e) => window.__clicks.push(e.defaultPrevented)); window.__opened = []; window.open = (...a) => { window.__opened.push(a); return null; };"
FRONT = "/_front-for-test"
FRONT_HTML = f"""<!doctype html><html><head><meta charset="utf-8"></head>
<body style="margin:0"><div id="pane" style="height:640px"></div>
<script src="/_/mount.js"></script>
<script>sheafMount.mount(document.getElementById('pane'), {json.dumps({"sheaf": True})})
  .then((m) => {{ window.__page = m; }}, (e) => {{ window.__failed = String(e); }});</script>
</body></html>"""
# The first closed root attached is the Sheaf's own: the rectoverso opened from a row attaches another, inside it (the last of
# `__roots`). `__clicks` says for each click whether something called preventDefault on it by the time it reached the window.
FIRST_ROOT = """(() => { const attach = Element.prototype.attachShadow;
  Element.prototype.attachShadow = function (o) { const r = attach.call(this, o); window.__root = window.__root || r; (window.__roots = window.__roots || []).push(r); return r; };
})();"""


@pytest.fixture
def pages(front, work):
    subprocess.run(["git", "init", "-q", str(work)], check=True)       # a git root lists a dot-folder's pages (8.6)
    for rel, title in (("plan.md", "The plan"), ("ideas/first.md", "First idea"), ("ideas/deep/second.md", "Second idea"),
                       (".tooling/n.md", "Scratch note")):
        f = work / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(PLAN.replace("# Plan", f"# {title}", 1), encoding="utf-8")
        front.hub.roots.for_document(f)
    log = front.hub.writes
    log.add("work/plan.md", "Claude Code (Bea)", "laptop", "update", session=SID_RC, link=RC)
    log.add("work/ideas/first.md", "Claude Code (Bea)", "laptop", "update", session=SID_BARE)
    log.add("work/ideas/deep/second.md", "Claude.ai (Bea)", "chat client", "update")
    log.add("work/.tooling/n.md", "Assistant (Bea)", "chat client", "update", chat=CHAT)
    return front


class AgentView:
    """The AgentView of the member's laptop, as far as the page sees it: `up` answers, `gone` is not there at all
    (the connection is refused), `ended` finds no live session and reopens it."""

    def __init__(self):
        self.mode, self.calls = "up", []

    def answer(self, route):
        req = route.request
        cors = {"Access-Control-Allow-Origin": ORIGIN, "Access-Control-Allow-Private-Network": "true",
                "Access-Control-Allow-Headers": "Content-Type, X-Fleet", "Access-Control-Allow-Methods": "POST, OPTIONS"}
        if self.mode == "gone":
            return route.abort("connectionrefused")
        if req.method == "OPTIONS":
            return route.fulfill(status=204, headers=cors)
        self.calls.append((req.url.rsplit("/", 1)[1], json.loads(req.post_data), req.headers.get("x-fleet")))
        if self.mode == "ended" and req.url.endswith("/api/jump"):
            return route.fulfill(status=404, headers=cors, content_type="text/plain", body="no such live session")
        route.fulfill(status=200, headers=cors, content_type="application/json", body='{"ok": true}')


@pytest.fixture
def agentview():
    return AgentView()


class Mounted:
    def __init__(self, page, errors):
        self.page, self.errors = page, errors

    def js(self, body, arg=None):
        return self.page.evaluate("([arg]) => { const root = window.__root; " + body + " }", [arg])

    def visible_rows(self):
        return self.js("return Array.from(root.querySelectorAll('.sheaf-row')).filter((r) => !r.hidden).map((r) => r.dataset.doc);")

    def click(self, css):
        until(lambda: self.js("return !!root.querySelector(arg);", css), what=css)
        x, y = self.js("const r = root.querySelector(arg).getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2];", css)
        self.page.mouse.click(x, y)


@pytest.fixture
def mounted(chromium, pages, agentview):
    errors = []

    def answer(route):
        path = route.request.url[len(ORIGIN):]
        if path == FRONT:
            return route.fulfill(status=200, content_type="text/html", body=FRONT_HTML)
        res = pages.get(path, member=BEA)
        route.fulfill(status=res.status, headers=dict(res.headers), body=res.body)

    context = new_context(chromium)
    context.route(f"{ORIGIN}/**", answer)
    context.route(f"{AGENTVIEW}/**", agentview.answer)
    page = context.new_page()
    page.add_init_script(OPENED)
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.add_init_script(FIRST_ROOT)
    page.goto(ORIGIN + FRONT)
    until(lambda: page.evaluate("!!(window.__page || window.__failed)"), what="the mount")
    assert page.evaluate("window.__failed || null") is None
    m = Mounted(page, errors)
    until(lambda: m.js("return !!root.querySelector('.sheaf-row');"), what="the rows in the root")
    yield m
    try:
        assert errors == [], "the Sheaf raised script errors"
    finally:
        close_context(context)


def test_the_tree_has_all_pages_on_top_then_the_root_and_its_folders_and_no_dot_folder(mounted):
    got = mounted.js("return Array.from(root.querySelectorAll('.sheaf-folder')).map((b) => [b.textContent, b.dataset.path]);")
    assert got == [["All pages", ""], ["work", "work"], ["ideas", "work/ideas"], ["deep", "work/ideas/deep"]]
    assert mounted.js("return root.querySelector('.sheaf-folder.on').textContent;") == "All pages"


def test_the_table_shows_every_page_newest_first_with_no_list_status(mounted):
    assert sorted(mounted.visible_rows()) == ["work/.tooling/n.md", "work/ideas/deep/second.md", "work/ideas/first.md", "work/plan.md"]
    heads = mounted.js("return Array.from(root.querySelectorAll('th')).map((h) => h.textContent);")
    assert heads == ["Title", "Folder", "Last write", "Last agent session", "When", "Open"]


def test_a_folder_narrows_the_table_to_itself_and_everything_below_it(mounted):
    mounted.click('.sheaf-folder[data-path="work/ideas"]')
    assert sorted(mounted.visible_rows()) == ["work/ideas/deep/second.md", "work/ideas/first.md"]
    mounted.click('.sheaf-folder[data-path="work/ideas/deep"]')
    assert mounted.visible_rows() == ["work/ideas/deep/second.md"]
    mounted.click('.sheaf-folder[data-path=""]')
    assert len(mounted.visible_rows()) == 4


def test_a_folder_collapses_and_expands(mounted):
    seen = "return root.querySelector('.sheaf-folder[data-path=\"work/ideas\"]').offsetParent !== null;"
    assert mounted.js(seen) is True
    mounted.click(".sheaf-toggle")
    assert mounted.js("return root.querySelector('.sheaf-toggle').getAttribute('aria-expanded');") == "false"
    assert mounted.js(seen) is False
    mounted.click(".sheaf-toggle")
    assert mounted.js(seen) is True


def test_the_filter_keeps_the_rows_whose_title_holds_the_words(mounted):
    mounted.js("const f = root.querySelector('.sheaf-filter'); f.value = 'idea'; f.dispatchEvent(new Event('input'));")
    assert sorted(mounted.visible_rows()) == ["work/ideas/deep/second.md", "work/ideas/first.md"]
    mounted.js("const f = root.querySelector('.sheaf-filter'); f.value = 'nothing like it'; f.dispatchEvent(new Event('input'));")
    assert mounted.visible_rows() == [] and mounted.js("return !root.querySelector('.sheaf-empty').hidden;") is True


def test_a_click_on_a_row_opens_the_rectoverso_under_a_back_button_and_back_gives_the_table_as_it_was(mounted):
    mounted.click('.sheaf-folder[data-path="work/ideas"]')
    mounted.click('.sheaf-row[data-doc="work/ideas/first.md"] .sheaf-title a')
    until(lambda: mounted.js("return !root.querySelector('.sheaf-doc').hidden;"), what="the pane for the rectoverso")
    assert mounted.js("return root.querySelector('.sheaf-main').hidden;") is True
    assert mounted.js("return root.querySelector('.sheaf-crumb').textContent;") == "work / ideas / first.md"
    mounted.click(".sheaf-back")
    until(lambda: mounted.js("return !root.querySelector('.sheaf-main').hidden;"), what="the table again")
    assert mounted.js("return root.querySelector('.sheaf-doc').hidden;") is True
    assert sorted(mounted.visible_rows()) == ["work/ideas/deep/second.md", "work/ideas/first.md"]
    assert mounted.js("return root.querySelector('.sheaf-folder.on').dataset.path;") == "work/ideas"


# ── the last agent session on a row is the way back to it (ticket 10) ───────

def cell(m, doc):
    return m.js("const c = root.querySelector('.sheaf-row[data-doc=\"' + arg + '\"] .sheaf-session');"
                " const l = c.querySelector('a, button');"
                " return {text: c.textContent, tag: l && l.tagName, href: l && l.getAttribute('href'), target: l && l.getAttribute('target'),"
                " rel: l && l.getAttribute('rel')};", doc)


def opened(m):
    return m.page.evaluate("window.__opened.map((a) => a[0])")


def test_a_click_on_the_laptop_asks_agentview_to_jump_to_that_session_and_goes_nowhere_else(mounted, agentview):
    mounted.click('.sheaf-row[data-doc="work/plan.md"] .sheaf-session a')
    until(lambda: agentview.calls, what="the jump")
    assert agentview.calls == [("jump", {"key": f"claude:{SID_RC}"}, "1")]
    assert opened(mounted) == []


def test_a_session_that_has_ended_is_reopened_on_the_laptop(mounted, agentview):
    agentview.mode = "ended"
    mounted.click('.sheaf-row[data-doc="work/plan.md"] .sheaf-session a')
    until(lambda: len(agentview.calls) == 2, what="the jump, then the reopen")
    assert agentview.calls == [("jump", {"key": f"claude:{SID_RC}"}, "1"), ("reopen", {"id": SID_RC}, "1")]
    assert opened(mounted) == []


def test_with_agentview_absent_the_remote_control_link_is_used(mounted, agentview):
    agentview.mode = "gone"
    mounted.click('.sheaf-row[data-doc="work/plan.md"] .sheaf-session a')
    until(lambda: opened(mounted), what="the Remote Control link")
    assert opened(mounted) == [RC]


def test_with_agentview_absent_and_no_remote_control_the_name_is_plain_text_afterwards(mounted, agentview):
    agentview.mode = "gone"
    assert cell(mounted, "work/ideas/first.md")["tag"] == "BUTTON"
    mounted.click('.sheaf-row[data-doc="work/ideas/first.md"] .sheaf-session button')
    until(lambda: cell(mounted, "work/ideas/first.md")["tag"] is None, what="plain text")
    assert cell(mounted, "work/ideas/first.md")["text"] == "Claude Code (Bea)"
    assert opened(mounted) == []
    assert mounted.js("return !root.querySelector('.sheaf-said').hidden;") is True


def test_an_open_webui_chat_and_a_claude_ai_write_each_read_as_the_spec_says(mounted):
    chat = cell(mounted, "work/.tooling/n.md")
    assert (chat["tag"], chat["href"], chat["target"], chat["rel"]) == ("A", f"/c/{CHAT}", "_blank", "noopener noreferrer")
    claude_ai = cell(mounted, "work/ideas/deep/second.md")
    assert claude_ai["text"] == "" and claude_ai["tag"] is None
    assert mounted.js("return root.querySelector('.sheaf-row[data-doc=\"work/ideas/deep/second.md\"] .sheaf-write').textContent;") == "Claude.ai (Bea)"


def test_the_row_holds_no_script_and_no_address_but_the_hubs_own(mounted):
    assert mounted.js("return root.querySelectorAll('script, [onclick], [href^=\"javascript:\"]').length;") == 0
    hrefs = mounted.js("return Array.from(root.querySelectorAll('.sheaf-session [href]')).map((a) => a.getAttribute('href'));")
    assert sorted(hrefs) == sorted([f"/c/{CHAT}", RC])


# ── the byline of an opened page is the same way back (ticket 10) ───────────

def open_page(m, doc):
    """Opens `doc` from its row and waits for its byline in the root the page attached."""
    m.click(f'.sheaf-row[data-doc="{doc}"] .sheaf-title a')
    until(lambda: m.page.evaluate("window.__roots.length > 1 && !!window.__roots[window.__roots.length - 1].querySelector('p.doc-by')"),
          what="the page's byline")


def byline(m):
    return m.page.evaluate("""(() => { const p = window.__roots[window.__roots.length - 1].querySelector('p.doc-by');
        const l = p.querySelector('a, button');
        return {text: p.textContent, tag: l && l.tagName, href: l && l.getAttribute('href'), target: l && l.getAttribute('target'),
                rel: l && l.getAttribute('rel')}; })()""")


def click_byline(m):
    m.page.evaluate("window.__roots[window.__roots.length - 1].querySelector('p.doc-by').scrollIntoView()")
    x, y = m.page.evaluate("""(() => { const r = window.__roots[window.__roots.length - 1].querySelector('p.doc-by .sheaf-session-link')
        .getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2]; })()""")
    m.page.mouse.click(x, y)


def test_the_byline_of_an_opened_page_names_the_session_as_its_row_does(mounted):
    open_page(mounted, "work/plan.md")
    b = byline(mounted)
    assert b["text"].startswith("Document prepared by Claude Code (Bea)")
    assert (b["tag"], b["href"], b["target"], b["rel"]) == ("A", RC, "_blank", "noopener noreferrer")


def test_a_click_on_the_byline_asks_agentview_to_jump_and_goes_nowhere_else(mounted, agentview):
    open_page(mounted, "work/plan.md")
    click_byline(mounted)
    until(lambda: agentview.calls, what="the jump")
    assert agentview.calls == [("jump", {"key": f"claude:{SID_RC}"}, "1")]
    assert opened(mounted) == []


def test_a_session_with_no_remote_control_is_a_button_in_the_byline_that_jumps(mounted, agentview):
    open_page(mounted, "work/ideas/first.md")
    assert byline(mounted)["tag"] == "BUTTON"
    click_byline(mounted)
    until(lambda: agentview.calls, what="the jump")
    assert agentview.calls == [("jump", {"key": f"claude:{SID_BARE}"}, "1")]


def test_the_byline_of_an_open_webui_write_links_to_its_chat(mounted):
    open_page(mounted, "work/.tooling/n.md")
    b = byline(mounted)
    assert (b["tag"], b["href"], b["target"]) == ("A", f"/c/{CHAT}", "_blank")


def test_a_page_with_no_session_keeps_its_byline_as_rendered(mounted):
    open_page(mounted, "work/ideas/deep/second.md")
    b = byline(mounted)
    assert b["tag"] is None and "Claude" not in b["text"]


def test_once_agentview_is_known_absent_the_remote_control_link_opens_in_the_click_itself(mounted, agentview):
    agentview.mode = "gone"
    mounted.page.context.route("https://rc.example.com/**", lambda route: route.abort())
    open_page(mounted, "work/plan.md")
    click_byline(mounted)                                    # the first click has to ask: AgentView may be there
    until(lambda: opened(mounted) == [RC], what="the Remote Control link, after the request failed")
    before = mounted.page.evaluate("window.__clicks.length")
    with mounted.page.context.expect_page() as popup:
        click_byline(mounted)                                # AgentView is known absent: the real link opens, a popup blocker has no say
    assert popup.value is not None
    assert mounted.page.evaluate("(n) => window.__clicks.slice(n)", before) == [False]
    assert opened(mounted) == [RC]                           # window.open was not used again
