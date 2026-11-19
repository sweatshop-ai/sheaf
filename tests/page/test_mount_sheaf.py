"""The Sheaf mounted in the front's document (SPEC 8.6): `sheafMount.mount(host, {sheaf: true})` builds the tree and the table
in a closed shadow root from `/_/mount?sheaf=1` (data, never markup) and sheaf.js makes it live: folders that collapse, a
folder that narrows the table, a filter on titles, and a click on a row that takes the pane for the rectoverso under a
"← Sheaf" button. Every request is answered by the hub's proxy handler as Bea. The page's clock is Playwright's."""
import json
import re
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
        req = route.request
        res = pages.post(path, json.loads(req.post_data or "{}"), member=BEA) if req.method == "POST" else pages.get(path, member=BEA)
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
    """Opens `doc` from its row and waits for its byline in the root the page attached, and for the page to start in it: mount.js puts
    the rendered html in the root first, waits for the stylesheet, and only then starts the page, which names the session in the
    byline (page.js takeAgent, before it appends its menu). Until then the line is the one rendered ("Document prepared by Ada")."""
    m.click(f'.sheaf-row[data-doc="{doc}"] .sheaf-title a')
    until(lambda: m.page.evaluate("window.__roots.length > 1 && !!window.__roots[window.__roots.length - 1].querySelector('p.doc-by')"),
          what="the page's byline")
    until(lambda: m.page.evaluate("!!window.__roots[window.__roots.length - 1].querySelector('#rd-menu')"), what="the page started")


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


def test_the_byline_is_as_rendered_until_the_stylesheet_has_loaded_and_the_page_started(mounted):
    held = []
    mounted.page.route("**/_/mount.css*", lambda route: held.append(route))
    mounted.click('.sheaf-row[data-doc="work/plan.md"] .sheaf-title a')
    until(lambda: held, what="the page's stylesheet, held")
    assert mounted.page.evaluate("window.__roots.length") > 1
    assert byline(mounted)["text"].startswith("Document prepared by ") and "Claude Code" not in byline(mounted)["text"]
    assert not mounted.page.evaluate("!!window.__roots[window.__roots.length - 1].querySelector('#rd-menu')")
    for route in held:
        route.continue_()
    until(lambda: byline(mounted)["text"].startswith("Document prepared by Claude Code (Bea)"), what="the session's name")


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
        click_byline(mounted)                                # AgentView is known absent: the browser follows the real link itself
    assert popup.value is not None
    assert mounted.page.evaluate("(n) => window.__clicks.slice(n)", before) == [False]
    assert opened(mounted) == [RC]                           # window.open was not used again


def test_a_session_that_has_ended_is_reopened_from_the_byline(mounted, agentview):
    agentview.mode = "ended"
    open_page(mounted, "work/plan.md")
    click_byline(mounted)
    until(lambda: len(agentview.calls) == 2, what="the jump, then the reopen")
    assert [c[0] for c in agentview.calls] == ["jump", "reopen"]


def test_with_agentview_absent_and_no_remote_control_the_byline_name_is_plain_text_afterwards(mounted, agentview):
    agentview.mode = "gone"
    open_page(mounted, "work/ideas/first.md")
    click_byline(mounted)
    until(lambda: byline(mounted)["tag"] is None, what="plain text")
    assert byline(mounted)["text"].startswith("Document prepared by Claude Code (Bea)")
    assert opened(mounted) == []


def test_the_row_share_button_shares_an_own_loose_page_and_is_gone_afterwards(mounted, pages):
    member = pages.hub.proxy.members[BEA]
    root, _ = pages.hub.loose.root_for(member)
    mine = root.path / "2026-11" / "mine.md"
    mine.parent.mkdir(parents=True)
    mine.write_text("# Mine\n\nText.\n", encoding="utf-8")
    mounted.page.reload()
    until(lambda: mounted.page.evaluate("!!window.__root"), what="the page after the reload")
    until(lambda: mounted.js("return !!root.querySelector('.sheaf-row');"), what="the rows in the root")
    until(lambda: mounted.js("return root.querySelectorAll('.sheaf-share').length;") == 1, what="one Share button")
    assert mounted.js("return root.querySelector('.sheaf-share').closest('.sheaf-row').dataset.title;") == "mine"
    mounted.click(".sheaf-share")
    until(lambda: mounted.js("return !root.querySelector('.sheaf-share') && !!root.querySelector('.sheaf-shared');"), what="Shared")
    assert "- [x] Share" in mine.read_text(encoding="utf-8")


def test_the_row_move_button_puts_an_own_loose_page_in_a_typed_folder_and_the_old_address_forwards(mounted, pages):
    member = pages.hub.proxy.members[BEA]
    root, _ = pages.hub.loose.root_for(member)
    mine = root.path / "2026-11" / "mine.md"
    mine.parent.mkdir(parents=True)
    mine.write_text("# Mine\n\nText.\n", encoding="utf-8")
    mounted.page.reload()
    until(lambda: mounted.page.evaluate("!!window.__root"), what="the page after the reload")
    until(lambda: mounted.js("return !!root.querySelector('.sheaf-row');"), what="the rows in the root")
    until(lambda: mounted.js("return root.querySelectorAll('.sheaf-move').length;") == 1, what="one Move button, on the own page")
    mounted.click(".sheaf-move")
    until(lambda: mounted.js("return !!root.querySelector('.sheaf-move-form input');"), what="the folder field")
    mounted.js("const f = root.querySelector('.sheaf-move-form'); f.querySelector('input').value = 'tidy/up'; f.requestSubmit();")
    until(lambda: (root.path / "tidy" / "up" / "mine.md").exists(), what="the page in its new folder")
    assert not mine.exists() and not (root.path / "2026-11").exists()
    until(lambda: mounted.js("return root.querySelector('.sheaf-row[data-title=\"mine\"]').dataset.doc.endsWith('/tidy/up/mine.md');"),
          what="the row follows the page")
    assert pages.get(f"/{root.name}/2026-11/mine.md").status == 302


def test_the_row_move_to_another_tiroir_button_asks_for_the_address_and_says_why_when_it_cannot_move(mounted, pages):
    member = pages.hub.proxy.members[BEA]
    root, _ = pages.hub.loose.root_for(member)
    mine = root.path / "2026-11" / "mine.md"
    mine.parent.mkdir(parents=True)
    mine.write_text("# Mine\n\nText.\n", encoding="utf-8")
    mounted.page.reload()
    until(lambda: mounted.page.evaluate("!!window.__root"), what="the page after the reload")
    until(lambda: mounted.js("return !!root.querySelector('.sheaf-row');"), what="the rows in the root")
    until(lambda: mounted.js("return root.querySelectorAll('.sheaf-move-tiroir').length;") == 1, what="one button, on the own page")
    mounted.click(".sheaf-move-tiroir")
    until(lambda: mounted.js("return !!root.querySelector('.sheaf-move-tiroir-form input');"), what="the address field")
    mounted.js("const f = root.querySelector('.sheaf-move-tiroir-form'); f.querySelector('input').value = 'https://other.example.com'; "
               "f.requestSubmit();")
    until(lambda: mounted.js("const s = root.querySelector('.sheaf-said'); return !!s && !s.hidden && s.textContent.length > 0;"),
          what="the sentence that says why the page did not move")
    assert mine.exists() and pages.get(f"/{root.name}/2026-11/mine.md").status == 200


def own_pages(mounted, pages, *names):
    member = pages.hub.proxy.members[BEA]
    root, _ = pages.hub.loose.root_for(member)
    for name in names:
        path = root.path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("# Mine\n\nText.\n", encoding="utf-8")
    mounted.page.reload()
    until(lambda: mounted.page.evaluate("!!window.__root"), what="the page after the reload")
    until(lambda: mounted.js("return !!root.querySelector('.sheaf-row');"), what="the rows in the root")
    return root


def rename_form(mounted, path, to):
    mounted.js("const b = root.querySelector('.sheaf-rename-folder[data-path=\"" + path + "\"]'); b.click();")
    until(lambda: mounted.js("return !!root.querySelector('.sheaf-rename-form input');"), what="the folder field")
    mounted.js("const f = root.querySelector('.sheaf-rename-form'); f.querySelector('input').value = '" + to + "'; f.requestSubmit();")


def test_a_rename_pressed_before_the_stylesheet_has_loaded_still_opens_its_form(mounted, pages):
    # The rows stand in the root while the mount waits for its stylesheet; the click listener came after that wait, so a press
    # in between was lost (CI: test_rename_folder_onto_a_taken_name... timed out at "the folder field", 9 of 240 runs).
    held = []
    mounted.page.route("**/_/mount.css*", lambda route: held.append(route))
    member = pages.hub.proxy.members[BEA]
    root, _ = pages.hub.loose.root_for(member)
    (root.path / "old").mkdir(parents=True)
    (root.path / "old" / "a.md").write_text("# Mine\n\nText.\n", encoding="utf-8")
    mounted.page.reload()
    until(lambda: mounted.page.evaluate("!!window.__root"), what="the page after the reload")
    until(lambda: mounted.js("return !!root.querySelector('.sheaf-rename-folder');"), what="the rows in the root")
    until(lambda: held, what="the stylesheet's request, held")
    mounted.js("root.querySelector('.sheaf-rename-folder').click();")
    for route in held:
        route.continue_()
    until(lambda: mounted.js("return !!root.querySelector('.sheaf-rename-form input');"), what="the folder field")


def test_rename_folder_is_offered_on_the_own_loose_folders_only(mounted, pages):
    root = own_pages(mounted, pages, "2026-11/mine.md")
    paths = mounted.js("return Array.from(root.querySelectorAll('.sheaf-rename-folder')).map((b) => b.dataset.path);")
    assert paths == [f"{root.name}/2026-11"]


def test_rename_folder_moves_each_page_and_the_old_address_forwards(mounted, pages):
    root = own_pages(mounted, pages, "old/a.md", "old/sub/b.md")
    rename_form(mounted, f"{root.name}/old", "new")
    until(lambda: (root.path / "new" / "a.md").exists() and (root.path / "new" / "sub" / "b.md").exists(), what="the pages in the new folder")
    assert not (root.path / "old").exists()
    assert pages.get(f"/{root.name}/old/a.md").status == 302
    until(lambda: mounted.js("return Array.from(root.querySelectorAll('.sheaf-rename-folder')).map((b) => b.dataset.path).includes('" + root.name + "/new');"),
          what="the tree drawn again with the new folder")


def test_rename_folder_onto_a_taken_name_says_which_page_and_moves_nothing(mounted, pages):
    root = own_pages(mounted, pages, "old/a.md", "other/a.md")
    rename_form(mounted, f"{root.name}/old", "other")
    until(lambda: mounted.js("const s = root.querySelector('.sheaf-said'); return !!s && !s.hidden && s.textContent.includes('a.md');"),
          what="the refusal names the page")
    assert (root.path / "old" / "a.md").exists() and (root.path / "other" / "a.md").exists()


# ── Connect a laptop, in the Sheaf (ticket 33) ──────────────────────────────

TOKEN = re.compile(r"sheaf_mcp_[A-Za-z0-9_-]{43}")


def laptops_open(m):
    m.click(".sheaf-laptops-open")
    until(lambda: m.js("return !root.querySelector('.sheaf-laptops').hidden;"), what="the Laptops panel")


def laptop_names(m):
    return m.js("return Array.from(root.querySelectorAll('.sheaf-laptop-row .sheaf-laptop-name')).map((n) => n.textContent);")


def connect_named(m, name):
    m.js("const i = root.querySelector('.sheaf-laptop-input'); i.value = arg; i.dispatchEvent(new Event('input'));", name)
    m.click(".sheaf-laptop-connect")


def test_connect_a_laptop_names_it_and_shows_one_line_once(mounted):
    seen = []
    mounted.page.on("console", lambda msg: seen.append(msg.text))
    laptops_open(mounted)
    connect_named(mounted, "Work MacBook")
    until(lambda: mounted.js("return !root.querySelector('.sheaf-laptop-made').hidden;"), what="the line")
    line = mounted.js("return root.querySelector('.sheaf-laptop-line').textContent;")
    assert re.fullmatch(r"sheaf connect \S+ sheaf_mcp_[A-Za-z0-9_-]{43}", line), line
    until(lambda: laptop_names(mounted) == ["Work MacBook"], what="the laptop in the list")
    assert not any(TOKEN.search(t) for t in seen), "the token went to the console"


def test_the_token_is_not_kept_once_the_member_leaves_the_panel(mounted):
    laptops_open(mounted)
    connect_named(mounted, "Work MacBook")
    until(lambda: mounted.js("return !root.querySelector('.sheaf-laptop-made').hidden;"), what="the line")
    token = TOKEN.search(mounted.js("return root.querySelector('.sheaf-laptop-line').textContent;")).group(0)
    kept = "return [root.innerHTML, root.textContent, document.documentElement.outerHTML, location.href, JSON.stringify(Object.entries(localStorage)), JSON.stringify(Object.entries(sessionStorage))].join('|');"
    mounted.click(".sheaf-laptops-open")                                   # the same switch closes the panel
    assert token not in mounted.js(kept)
    laptops_open(mounted)
    assert mounted.js("return root.querySelector('.sheaf-laptop-made').hidden;") is True
    mounted.click('.sheaf-viewswitch[data-view=""]')                       # the Sheaf is drawn again
    until(lambda: mounted.js("return !!root.querySelector('.sheaf-row') && root.querySelector('.sheaf-laptops').hidden;"), what="the Sheaf again")
    assert token not in mounted.js(kept)


def test_the_list_holds_the_members_laptops_by_name_and_never_a_token(mounted, pages):
    from helpers import CAL
    assert pages.post("/_/laptops", {"name": "Old MacBook"}, member=BEA).status == 200
    assert pages.post("/_/laptops", {"name": "Cal's laptop"}, member=CAL).status == 200
    laptops_open(mounted)
    until(lambda: laptop_names(mounted) == ["Old MacBook"], what="the member's laptops")
    assert not TOKEN.search(mounted.js("return root.innerHTML + root.textContent;"))


def test_revoke_asks_a_second_click_then_the_laptop_is_gone(mounted, pages):
    assert pages.post("/_/laptops", {"name": "Old MacBook"}, member=BEA).status == 200
    laptops_open(mounted)
    until(lambda: laptop_names(mounted) == ["Old MacBook"], what="the laptop")
    mounted.click(".sheaf-laptop-revoke")
    assert laptop_names(mounted) == ["Old MacBook"]
    assert "Really revoke" in mounted.js("return root.querySelector('.sheaf-laptop-revoke').textContent;")
    mounted.click(".sheaf-laptop-revoke")
    until(lambda: laptop_names(mounted) == [], what="the laptop gone")
    assert pages.get("/_/laptops", member=BEA).json()["laptops"] == []


def test_a_refusal_of_the_hub_is_shown_and_no_line_is_drawn(mounted, pages):
    assert pages.post("/_/laptops", {"name": "Old MacBook"}, member=BEA).status == 200
    laptops_open(mounted)
    until(lambda: laptop_names(mounted) == ["Old MacBook"], what="the laptop")
    connect_named(mounted, "old macbook")
    until(lambda: "already have a laptop" in mounted.page.evaluate("window.__root.querySelector('.sheaf-said').textContent"),
          what="the hub's words")
    assert mounted.js("return root.querySelector('.sheaf-laptop-made').hidden;") is True


# The pane on a phone: 390 px wide, the folder tree stacks above the table instead of keeping a column of its own, and the
# table, the tabs and the Laptops form read in the full width. The desktop layout is unchanged.
PHONE = {"width": 390, "height": 844}
DESKTOP = {"width": 1280, "height": 800}
MEASURE = """const box = (s) => { const e = root.querySelector(s); return e && !e.hidden ? e.getBoundingClientRect() : null; };
  const lines = (s) => Array.from(root.querySelectorAll(s)).filter((e) => e.offsetParent !== null).map((e) => e.getBoundingClientRect().height);"""


def test_on_a_phone_the_tree_stacks_above_the_table_and_the_table_has_the_width(mounted):
    mounted.page.set_viewport_size(PHONE)
    got = mounted.js(MEASURE + " return {tree: box('.sheaf-tree'), main: box('.sheaf-main'), view: box('.sheaf-view')};")
    assert got["tree"]["width"] >= 340, "the tree takes a column beside the table"
    assert got["main"]["width"] >= 340
    assert got["main"]["y"] >= got["tree"]["y"] + got["tree"]["height"] - 1, "the table is not under the tree"


def test_on_a_phone_the_tabs_and_the_rows_read_without_scrolling_sideways(mounted):
    mounted.page.set_viewport_size(PHONE)
    got = mounted.js(MEASURE + """
    const main = root.querySelector('.sheaf-main');
    const edge = root.querySelector('.sheaf-main').getBoundingClientRect().right;
    const cells = Array.from(root.querySelectorAll('.sheaf-row td')).filter((e) => e.offsetParent !== null);
    return {over: cells.filter((e) => e.getBoundingClientRect().right > edge + 0.5).length, tabs: lines('.sheaf-viewswitch, .sheaf-laptops-open'), titles: lines('.sheaf-row .sheaf-title'),
            sideways: main.scrollWidth > main.clientWidth, sheaf: root.querySelector('.sheaf-view').scrollWidth > root.querySelector('.sheaf-view').clientWidth};""")
    assert got["tabs"] and max(got["tabs"]) < 40, "a tab name wraps"
    assert got["titles"] and max(got["titles"]) < 80, "a title wraps letter by letter"
    assert got["over"] == 0, "a cell runs past the pane's edge"
    assert not got["sideways"] and not got["sheaf"], "a row needs a sideways scroll"


def test_on_a_phone_the_laptops_field_and_button_fit_and_the_button_has_one_line(mounted):
    mounted.page.set_viewport_size(DESKTOP)
    mounted.page.evaluate("const p = document.getElementById('pane'); p.style.width = '390px'; p.style.marginLeft = '24px';")     # a narrow pane that does not start at x=0
    mounted.click(".sheaf-laptops-open")
    until(lambda: mounted.js("return !!root.querySelector('.sheaf-laptops') && !root.querySelector('.sheaf-laptops').hidden;"), what="the Laptops panel")
    got = mounted.js(MEASURE + """
    const m = root.querySelector('.sheaf-main'), edge = m.getBoundingClientRect().right;
    const i = box('.sheaf-laptop-input'), b = box('.sheaf-laptop-connect');
    return {edge, input: i, button: b, sideways: m.scrollWidth > m.clientWidth};""")
    assert got["input"]["x"] + got["input"]["width"] <= got["edge"] + 0.5, "the field is cut at the right edge"
    assert got["button"]["x"] + got["button"]["width"] <= got["edge"] + 0.5 and got["button"]["height"] < 40, "the button is cut or wraps"
    assert not got["sideways"]


def test_on_a_desktop_the_tree_keeps_its_column_beside_the_table(mounted):
    mounted.page.set_viewport_size(DESKTOP)
    got = mounted.js(MEASURE + " return {tree: box('.sheaf-tree'), main: box('.sheaf-main')};")
    assert 220 <= got["tree"]["width"] < 260 and got["main"]["x"] >= got["tree"]["x"] + got["tree"]["width"] - 1


def test_on_a_phone_the_trash_view_shows_no_table_of_pages(mounted):
    mounted.page.set_viewport_size(PHONE)
    mounted.click('.sheaf-viewswitch[data-view="trash"]')
    until(lambda: mounted.js("return !!root.querySelector('.sheaf-viewswitch[data-view=\"trash\"].on');"), what="the Trash view")
    assert mounted.js("return Array.from(root.querySelectorAll('.sheaf-row')).filter((r) => r.offsetParent !== null).length;") == 0


def test_on_a_phone_an_opened_page_keeps_the_height_of_the_pane(mounted):
    mounted.page.set_viewport_size(PHONE)
    mounted.click('.sheaf-row[data-doc="work/ideas/first.md"] .sheaf-title a')
    until(lambda: mounted.js("const d = root.querySelector('.sheaf-doc'); return !!d && !d.hidden;"), what="the page opened")
    got = mounted.js(MEASURE + " return {view: box('.sheaf-view'), body: box('.sheaf-doc-body')};")
    assert got["view"]["height"] >= 600, "the view shrinks to its content"
    assert got["body"]["height"] >= 400, "the opened page has no room to draw or scroll in"


def test_on_a_phone_the_tree_takes_a_third_of_the_pane_at_most_not_of_the_screen(mounted):
    mounted.page.set_viewport_size(PHONE)
    mounted.page.evaluate("document.getElementById('pane').style.height = '300px';")        # the screen is 844 high, the pane 300
    got = mounted.js(MEASURE + " return {tree: box('.sheaf-tree'), natural: root.querySelector('.sheaf-tree').scrollHeight};")
    assert got["natural"] > 91, "the tree is too short to show the cap"
    assert got["tree"]["height"] <= 91, "the tree is capped by the screen's height, not the pane's"


def test_a_narrow_pane_on_a_desktop_screen_gets_the_phone_layout(mounted):
    mounted.page.set_viewport_size(DESKTOP)
    mounted.page.evaluate("document.getElementById('pane').style.width = '390px';")
    got = mounted.js(MEASURE + " return {tree: box('.sheaf-tree'), main: box('.sheaf-main')};")
    assert got["tree"]["width"] >= 340, "the tree takes a column beside the table"
    assert got["main"]["y"] >= got["tree"]["y"] + got["tree"]["height"] - 1, "the table is not under the tree"


def test_on_a_phone_a_pane_with_no_height_of_its_own_still_shows_the_table(mounted):
    mounted.page.set_viewport_size(PHONE)
    mounted.page.evaluate("document.getElementById('pane').style.height = 'auto';")
    got = mounted.js(MEASURE + " return {main: box('.sheaf-main'), rows: lines('.sheaf-row')};")
    assert got["rows"] and got["main"]["height"] >= sum(got["rows"]), "the table collapses in a pane with no height"
