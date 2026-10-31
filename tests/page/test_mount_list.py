"""The list mounted in the front's document (#116 step 2, slice iv): `sheafMount.mount(host, {list})` builds the rows
in a closed shadow root from `/_/mount?list=` (data, never markup) and runs the list's script there
(`sheafList.create(root, {body, remount})`); a press remounts the list in place where the page of its own reloads.

The front is a page at the list's origin that loads `/_/mount.js`; every request is answered by the hub's proxy
handler as Nell, as tests/page/test_page_list.py does for the page of its own. The page's clock is Playwright's."""
import json

import pytest
from pagehelp import close_context, new_context, until
from test_hub_list import JOEY, NELL, box, github, sheaves  # noqa: F401  (the hub with its list, as there)
from test_mount_page import KEEP_ROOT

pytestmark = pytest.mark.page

ORIGIN = "http://list.test"
FRONT = "/_front-for-test"
GA4 = "list/initech/website/2026-10-27-ga4-property.md"


def front_html(opts):
    return f"""<!doctype html><html><head><meta charset="utf-8"></head>
<body style="margin:0"><h1 id="front" style="font-size:31px">the front</h1>
<div id="pane" style="height:640px"></div>
<script src="/_/mount.js"></script>
<script>window.__front = true;
sheafMount.mount(document.getElementById('pane'), Object.assign({json.dumps(opts)},
  {{navigate: (path) => {{ (window.__moves = window.__moves || []).push(path); }}}}))
  .then((m) => {{ window.__page = m; }}, (e) => {{ window.__failed = String(e); }});</script>
</body></html>"""


class Mounted:
    def __init__(self, page, ticks, errors):
        self.page, self.ticks, self.errors = page, ticks, errors

    def js(self, body, arg=None):
        return self.page.evaluate("([arg]) => { const root = window.__root; " + body + " }", [arg])

    def button(self, doc):
        return f'button.list-act[data-doc="{doc}"]'

    def text(self, css):
        return self.js("const e = root.querySelector(arg); return e ? e.textContent : null;", css)

    def press(self, css):
        until(lambda: self.text(css) is not None, what=css)
        x, y = self.js("const r = root.querySelector(arg).getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2];",
                       css)
        self.page.mouse.click(x, y)


# Keeps the name of every key the page stores in sessionStorage.
SET_KEYS = """(() => { const set = Storage.prototype.setItem, keys = window.__setKeys = [];
  Storage.prototype.setItem = function (k, v) { keys.push(k); return set.call(this, k, v); }; })();"""


def mount_the_list(chromium, box, opts=None, **options):  # noqa: F811
    ticks, errors, refuse = [], [], []

    def answer(route):
        req = route.request
        path = req.url[len(ORIGIN):]
        if refuse and path.startswith("/_/mount?"):
            return route.fulfill(status=refuse[0], content_type="application/json", body='{"error": "sign in"}')
        if path == FRONT:
            return route.fulfill(status=200, content_type="text/html", body=front_html(opts or {"list": "list"}))
        if req.method == "POST" and path == "/_/tick":
            body = json.loads(req.post_data)
            res = box.post("/_/tick", body, member=NELL)
            ticks.append((body, res.status))
        else:
            res = box.get(path, member=NELL)
        route.fulfill(status=res.status, headers=dict(res.headers), body=res.body)

    context = new_context(chromium, **options)
    context.route(f"{ORIGIN}/**", answer)
    page = context.new_page()
    page.on("pageerror", lambda e: errors.append(str(e)))
    page.add_init_script(KEEP_ROOT)
    page.add_init_script(SET_KEYS)
    page.clock.install()
    page.goto(ORIGIN + FRONT)
    until(lambda: page.evaluate("!!(window.__page || window.__failed)"), what="the mount")
    assert page.evaluate("window.__failed || null") is None
    m = Mounted(page, ticks, errors)
    m.refuse = refuse
    until(lambda: m.text(".list-row") is not None, what="the list's rows in the root")
    yield m
    try:
        assert errors == [], "the list raised script errors"
    finally:
        close_context(context)


@pytest.fixture
def mounted(chromium, box):  # noqa: F811
    yield from mount_the_list(chromium, box)


ROWS = """return Array.from(root.querySelectorAll('.list-row')).map((r) => [
  r.querySelector('a.list-title').getAttribute('href'), r.querySelector('a.list-title').textContent,
  Array.from(r.querySelectorAll('button.list-act')).map((b) => [b.dataset.doc, b.dataset.action || null, b.dataset.word,
    b.dataset.hash || null, b.className, b.getAttribute('aria-pressed'), b.disabled, b.textContent]),
  r.querySelector('.list-meta').textContent]);"""


def test_the_list_mounts_in_the_closed_root_with_the_rows_buttons_and_filters_of_the_page(mounted, chromium, box):  # noqa: F811
    m = mounted
    got = m.js(ROWS)
    own = m.page.context.new_page()
    own.goto(ORIGIN + "/list")
    assert own.evaluate("(() => { const root = document; " + ROWS + " })()") == got
    assert [r[1] for r in got] == ["Reply to Joey about column L", "James needs the GA4 property id",
                                   "Prep for the call of Thursday"]
    filters = m.js("return Array.from(root.querySelectorAll('a.list-filter')).map((a) => "
                   "[a.textContent, a.getAttribute('href'), a.getAttribute('aria-current')]);")
    assert filters == [["My projects", "/list", "page"], ["Only mine", "/list?show=mine", None],
                       ["All of the team", "/list?show=all", None]]
    # Nothing of the list in the front's document, and the list's style stays in the root.
    assert m.page.evaluate("document.querySelectorAll('.list-row, .list-act').length") == 0
    assert m.page.evaluate("getComputedStyle(document.getElementById('front')).fontSize") == "31px"
    assert m.js("return getComputedStyle(root.querySelector('.list-act.one-off')).borderTopLeftRadius;") == "999px"


def test_a_press_waits_five_seconds_with_undo_then_ticks_and_remounts_without_the_row_not_reloading_the_front(
        mounted, sheaves):  # noqa: F811
    m = mounted
    m.press(m.button(JOEY))
    assert m.text(m.button(JOEY)) == "Undo"
    assert m.page.evaluate("window.__page.dirty()") is True        # a press in its window is lost by a move
    m.page.clock.run_for(4900)
    assert m.ticks == []
    m.page.clock.run_for(200)
    until(lambda: m.ticks, what="the tick")
    assert [(b["action"], b["word"], s) for b, s in m.ticks] == [(0, "Approve", 200)]
    assert "- [x] Approve" in (sheaves / JOEY[5:]).read_text(encoding="utf-8")
    until(lambda: m.text(m.button(JOEY)) is None, what="the remount without the row's button")
    assert m.page.evaluate("window.__front") is True               # the front was not reloaded
    assert m.page.evaluate("window.__page.dirty()") is False
    assert m.js("return root.querySelectorAll('.sheaf-list').length;") == 1


def test_a_refusal_beside_a_press_that_went_through_is_said_after_the_remount_under_a_key_of_the_mount(
        mounted, sheaves):  # noqa: F811
    m = mounted
    path = sheaves / GA4[5:]
    path.write_text(path.read_text(encoding="utf-8").replace("- [ ] Done @dora", "- [x] Done @dora"), encoding="utf-8")
    m.press(m.button(JOEY))
    m.press(m.button(GA4))
    m.page.clock.run_for(5100)
    until(lambda: len(m.ticks) == 2, what="both ticks")
    until(lambda: m.text(m.button(JOEY)) is None, what="the remount")
    until(lambda: m.js("const e = root.querySelector('.list-error'); return !!e && !e.hidden;"), what="the refusal said again")
    assert m.page.evaluate("Object.keys(sessionStorage).filter((k) => k.includes('sheaf-list-said'))") == []
    assert m.page.evaluate("window.__setKeys") == ["sheaf-mount:sheaf-list-said"]


def test_an_unmount_while_a_press_waits_sends_nothing(mounted, sheaves):  # noqa: F811
    m = mounted
    before = (sheaves / JOEY[5:]).read_text(encoding="utf-8")
    m.press(m.button(JOEY))
    m.page.evaluate("window.__page.unmount()")
    m.page.clock.run_for(10_000)
    m.page.wait_for_timeout(200)
    assert m.ticks == []
    assert (sheaves / JOEY[5:]).read_text(encoding="utf-8") == before
    assert m.js("return root.childNodes.length;") == 0


def test_a_title_with_markup_is_shown_as_its_text_in_the_mounted_list(chromium, box, sheaves):  # noqa: F811
    joey = sheaves / JOEY[5:]
    joey.write_text(joey.read_text(encoding="utf-8").replace(
        "# Reply to Joey about column L", "# Reply <img src=/x onerror=window.__pwned=1> & co"), encoding="utf-8")
    box.hub.the_list.poll()
    for m in mount_the_list(chromium, box):
        m.page.wait_for_timeout(200)
        assert m.js("return root.querySelectorAll('img').length;") == 0
        assert "Reply <img src=/x onerror=window.__pwned=1> & co" in m.js(ROWS)[0][1]
        assert m.page.evaluate("window.__pwned || null") is None


def test_the_list_mounts_with_the_filter_it_is_asked_for(chromium, box):  # noqa: F811
    for m in mount_the_list(chromium, box, {"list": "list", "show": "mine"}):
        assert [r[1] for r in m.js(ROWS)] == ["Reply to Joey about column L"]
        assert m.js("return root.querySelector('a.list-filter[aria-current=page]').textContent;") == "Only mine"


@pytest.mark.parametrize("href", ["javascript:alert(1)", "//evil.test/x", "/\\evil.test/x", "/\t/evil.test/x",
                                  "/\n/evil.test/x", "/\r/evil.test", "/ /evil.test", "https://evil.test/x", "list", "/%2F/evil.test"])
def test_render_keeps_no_address_that_is_not_a_path_on_the_origin(mounted, href):
    """A link the list draws is a path of the hub's: another scheme, `//`, a backslash, and any control or space (the
    URL parser drops a tab, CR or LF, so `/<tab>/host` reads as `//host`) are dropped; the hub sends none of them."""
    got = mounted.page.evaluate("""(h) => { const f = sheafList.render({filters: [{label: 'x', href: h, on: false}],
        sections: [{title: 's', count: 1, groups: [{name: 'g', rows: [{title: 't', href: h, meta: '', actions: []}]}]}]},
        document.body); return Array.from(f.querySelectorAll('a')).map((a) => a.getAttribute('href')); }""", href)
    assert got == ([None, None] if href != "/%2F/evil.test" else [href, href])
    if href == "/%2F/evil.test":
        assert mounted.page.evaluate("(h) => new URL(h, location.href).origin === location.origin", href)


def test_a_remount_that_fails_after_a_press_says_so_and_gives_the_buttons_back(mounted, sheaves):  # noqa: F811
    """The list's remount failure was swallowed and `reloading` stayed set: every button dead, nothing said (gate P3 of
    b9db2ab, with Ines's P2)."""
    m = mounted
    m.press(m.button(JOEY))
    m.refuse.append(401)
    m.page.clock.run_for(5100)
    until(lambda: m.ticks, what="the tick")
    until(lambda: m.js("const e = root.querySelector('.list-error'); return !e.hidden && e.textContent.includes('401');"),
          what="the failure said above the rows")
    m.refuse.clear()
    m.press(m.button(GA4))
    assert m.text(m.button(GA4)) == "Undo", "the other rows' buttons are dead"


def test_a_filter_and_a_title_clicked_in_the_mounted_list_go_to_the_loader_not_the_front(mounted):
    """The list's links moved the whole front window (gate P3 of b9db2ab): mount.js hands them to opts.navigate."""
    m = mounted
    m.press("a.list-filter[href='/list?show=all']")
    assert until(lambda: m.page.evaluate("window.__moves || null"), what="the move") == ["/list?show=all"]
    title = m.js("return root.querySelector('a.list-title').getAttribute('href');")
    m.press("a.list-title")
    until(lambda: len(m.page.evaluate("window.__moves")) == 2, what="the second move")
    assert m.page.evaluate("window.__moves")[1] == title
    assert m.page.evaluate("[location.pathname, window.__front]") == [FRONT, True]
