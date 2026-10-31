"""The page mounted in the front's document (#116 step 2, slice iii): page.js runs in the closed shadow root that
page/mount.js builds, through `sheafPage.create(root, cfg, {body, remount})`, not in a document of its own.

A "front" here is a page of the hub's origin (Playwright answers its address) that loads `/_/mount.js` and mounts the
sheaf in a pane, as the loader will. The root stays CLOSED, as in production; the test reaches it through the one
reference an init script keeps (`window.__root`), and acts on it with the real mouse and keyboard at the places it
measures there. The comment test runs in Chromium, Firefox and WebKit: selection in a shadow root is where they differ.
"""
import json

import pytest
from pagehelp import DOC, PAGE_TIMEOUT_MS, close_context, new_context, until

from sheafmd import comments as rdc

pytestmark = pytest.mark.page

FRONT = "/_front-for-test"
FRONT_HTML = f"""<!doctype html><html><head><meta charset="utf-8"></head>
<body style="margin:0"><header id="front" style="height:60px">the front</header>
<div id="pane" style="height:640px"></div>
<script src="/_/mount.js"></script>
<script>window.__front = true;
window.__before = window.__live.size;          // the listeners the front holds before the mount
sheafMount.mount(document.getElementById('pane'), {{doc: {json.dumps(DOC)}}})
  .then((m) => {{ window.__page = m; }}, (e) => {{ window.__failed = String(e); }});</script>
</body></html>"""
# Keeps the closed root where the test can find it; nothing else about the root changes.
# Also counts the listeners held on the document and the window, and keeps every EventSource opened, so a test can see
# what an unmounted page left behind.
KEEP_ROOT = """(() => { const attach = Element.prototype.attachShadow;
  Element.prototype.attachShadow = function (o) { const r = attach.call(this, o); window.__root = r; return r; };
  const live = window.__live = new Set(), add = EventTarget.prototype.addEventListener,
        remove = EventTarget.prototype.removeEventListener;
  const id = (t, type, fn, o) => [t === document ? 'd' : 'w', type, fn, !!(o === true || (o && o.capture))];
  const key = new Map();
  const k = (t, type, fn, o) => { const a = id(t, type, fn, o); let m = key.get(fn);
    if (!m) key.set(fn, m = new Map()); const s = a[0] + a[1] + a[3]; return [m, s]; };
  EventTarget.prototype.addEventListener = function (type, fn, o) {
    if ((this === document || this === window) && fn) { const [m, s] = k(this, type, fn, o);
      if (!m.has(s)) { const e = {}; m.set(s, e); live.add(e); } }
    return add.call(this, type, fn, o); };
  EventTarget.prototype.removeEventListener = function (type, fn, o) {
    if ((this === document || this === window) && fn) { const [m, s] = k(this, type, fn, o);
      if (m.has(s)) { live.delete(m.get(s)); m.delete(s); } }
    return remove.call(this, type, fn, o); };
  const ES = window.EventSource, streams = window.__streams = [];
  window.EventSource = function (url, o) { const e = new ES(url, o); streams.push(e); return e; };
  window.EventSource.prototype = ES.prototype; })();"""


class Front:
    """A tab on the front with the sheaf mounted in its pane."""

    def __init__(self, page, site):
        self.page, self.site, self.errors = page, site, []
        page.on("pageerror", lambda e: self.errors.append(str(e)))
        page.add_init_script(KEEP_ROOT)
        page.route(site.base + FRONT, lambda route: route.fulfill(status=200, content_type="text/html", body=FRONT_HTML))

    def open(self):
        self.page.goto(self.site.base + FRONT)
        until(lambda: self.page.evaluate("!!(window.__page || window.__failed)"), what="the mount")
        assert self.page.evaluate("window.__failed || null") is None
        until(lambda: self.has("#rd-menu-btn"), what="the page's menu button in the root")
        return self

    def has(self, css):
        return self.page.evaluate("s => !!(window.__root && window.__root.querySelector(s))", css)

    def js(self, body, arg=None):
        """`body` runs with `root` (the closed root) and `arg` in scope."""
        return self.page.evaluate("([arg]) => { const root = window.__root; " + body + " }", [arg])

    def centre(self, css):
        b = self.js("const r = root.querySelector(arg).getBoundingClientRect(); return [r.x + r.width / 2, r.y + r.height / 2];", css)
        return b

    def click(self, css):
        until(lambda: self.has(css), what=css)
        x, y = self.centre(css)
        self.page.mouse.click(x, y)

    def point(self, css, word, end=False):
        """Viewport (x, y) just inside the start or the end of `word` under `css` in the root."""
        return self.js("""const [css, word, end] = arg;
          const w = document.createTreeWalker(root.querySelector(css), NodeFilter.SHOW_TEXT);
          for (let n = w.nextNode(); n; n = w.nextNode()) {
            const i = n.data.indexOf(word);
            if (i < 0) continue;
            const r = new Range(), at = end ? i + word.length - 1 : i;
            r.setStart(n, at); r.setEnd(n, at + 1);
            const b = r.getBoundingClientRect();
            return [end ? b.right - 1 : b.left + 1, b.top + b.height / 2];
          }
          return null;""", [css, word, end])

    def drag(self, a, b):
        m = self.page.mouse
        m.move(*a)
        m.down()
        m.move((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, steps=4)
        m.move(*b, steps=4)
        m.up()


def _front(browser, site):
    c = new_context(browser, viewport={"width": 1100, "height": 760}) if browser.browser_type.name == "chromium" else \
        browser.new_context(viewport={"width": 1100, "height": 760})
    c.set_default_timeout(PAGE_TIMEOUT_MS)
    c.add_cookies([site.cookie()])
    return c, Front(c.new_page(), site)


@pytest.fixture
def front(chromium, site):
    c, f = _front(chromium, site)
    yield f
    try:
        assert f.errors == [], "the page raised script errors"
    finally:
        close_context(c)


@pytest.fixture(params=["chromium", "firefox", "webkit"])
def any_front(request, site, chromium):
    if request.param == "chromium":
        browser, own = chromium, False
    else:
        try:
            browser, own = getattr(chromium.pw, request.param).launch(), True
        except Exception as e:      # noqa: BLE001 - not installed, or its libraries are missing here (CI fails on a skip)
            pytest.skip(f"{request.param} cannot start here: {str(e).splitlines()[0]}")
    c, f = _front(browser, site)
    yield f
    try:
        assert f.errors == [], "the page raised script errors"
    finally:
        c.close()
        if own:
            browser.close()


def test_the_mounted_page_builds_its_parts_in_the_root_and_none_in_the_front(front):
    front.open()
    for part in ("#rd-menu-btn", "#rd-menu", "#rd-toast", "#rd-panel"):
        assert front.has(part), part
    assert front.page.evaluate("document.querySelector('[data-rd-ui]') === null")
    assert front.page.evaluate("window.__front === true")


def test_the_mounted_page_wears_its_theme_in_the_root_and_leaves_the_front_alone(front):
    """The theme's variables, the font and the body's rules (#128's wrap among them) reach the wrapper in the root."""
    f = front.open()
    got = f.js("""const cs = getComputedStyle(root.querySelector('.rd-root'));
      return [cs.fontFamily, cs.backgroundColor, cs.getPropertyValue('--accent').trim(), cs.overflowWrap];""")
    assert "Times" not in got[0] and got[1] != "rgba(0, 0, 0, 0)" and got[2] and got[3] == "break-word", got
    assert f.page.evaluate("getComputedStyle(document.body).fontFamily") != got[0]
    assert f.page.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--accent')") == ""


def test_the_menu_opens_from_a_click_in_the_root_and_a_click_elsewhere_in_it_closes_it(front):
    front.open()
    front.click("#rd-menu-btn")
    until(lambda: front.has("#rd-menu.open"), what="the open menu")
    front.click("main p")
    until(lambda: not front.has("#rd-menu.open"), what="the menu to close")


def test_a_comment_on_a_selection_dragged_in_the_root_reaches_the_file(any_front):
    f = any_front.open()
    f.drag(f.point("main", "about", end=False), f.point("main", "apples", end=True))
    until(lambda: f.has("#rd-comment-btn:not([disabled])"), what="the Comment button")
    f.click("#rd-comment-btn")
    until(lambda: f.has("#rd-popover textarea"), what="the comment form")
    x, y = f.centre("#rd-popover textarea")
    f.page.mouse.click(x, y)
    f.page.keyboard.type("Ripe ones?")
    f.click("#rd-popover button[data-f=ok]")
    c = until(lambda: (rdc.parse(f.site.file.read_text()).comments or [None])[0], what="the comment in the file")
    assert c.quote == "about apples" and c.body == "Ripe ones?"


def test_the_comment_button_sits_under_the_selection_in_the_pane(front):
    front.open()
    front.drag(front.point("main", "about"), front.point("main", "apples", end=True))
    until(lambda: front.has("#rd-comment-btn"), what="the Comment button")
    sel_bottom = front.point("main", "apples", end=True)[1]
    _, by = front.centre("#rd-comment-btn")
    assert sel_bottom < by < sel_bottom + 60


def test_an_edit_makes_the_page_dirty_for_the_loader_and_is_stored_under_a_key_of_its_own(front):
    front.open()
    assert front.page.evaluate("window.__page.dirty()") is False
    front.click("main p")
    front.page.keyboard.press("e")
    until(lambda: front.has(".rd-root.rd-editing main [contenteditable=true]"), what="edit mode")
    front.click("main p")
    front.page.keyboard.press("End")
    front.page.keyboard.type(" more")
    until(lambda: front.page.evaluate("window.__page.dirty()") is True, what="dirty")
    # The unsaved edit is stored as the page's draft, under a key of the mounted page: the origin is the front's.
    keys = until(lambda: [k for k in front.page.evaluate("Object.keys(localStorage)") if "sheaf-draft:" in k],
                 what="the stored draft")
    assert all(k.startswith("sheaf-mount:") for k in keys), keys


def test_an_outside_change_remounts_in_place_and_keeps_the_scroll(front):
    front.site.file.write_text(front.site.file.read_text() + "".join(f"\nFiller {i}.\n" for i in range(80)),
                               encoding="utf-8")
    front.open()
    front.page.evaluate("window.__same_front = 1")
    front.js("root.querySelector('main').__old = 1; root.querySelector('.rd-root').scrollTop = 600;")
    front.site.file.write_text(front.site.file.read_text().replace("about pears", "about plums"), encoding="utf-8")
    until(lambda: "about plums" in front.js("return root.querySelector('main').textContent;"), what="the change")
    assert front.page.evaluate("window.__same_front === 1"), "the front reloaded"
    assert front.js("return root.querySelector('main').__old === undefined;"), "the page was not built again"
    until(lambda: abs(front.js("return root.querySelector('.rd-root').scrollTop;") - 600) < 2, what="the scroll kept")


def test_unmount_takes_the_page_off_the_document_and_the_window(front):
    front.open()
    asked = []
    front.page.on("request", lambda r: asked.append(r.url) if "/_/" in r.url else None)
    front.page.evaluate("window.__page.unmount()")
    assert not front.has("#rd-menu-btn")
    asked.clear()
    front.page.mouse.click(300, 300)
    front.page.keyboard.press("e")
    front.page.wait_for_timeout(3000)
    assert asked == [], asked
    assert front.page.evaluate("typeof CSS.highlights === 'undefined' || !CSS.highlights.has('rd-open')")
    assert_nothing_left(front)


def assert_nothing_left(front):
    """No listener of the page on the document or the window, no stream open, no part of the page in the root."""
    assert front.page.evaluate("window.__live.size") == front.page.evaluate("window.__before")
    assert front.page.evaluate("window.__streams.length") > 0
    assert front.page.evaluate("window.__streams.every((e) => e.readyState === 2)")
    assert not front.has("#rd-menu-btn")


def test_unmount_while_a_remount_is_out_leaves_no_page_behind(front):
    front.open()
    until(lambda: front.page.evaluate("window.__streams.length") > 0, what="the stream")
    front.page.evaluate("window.__page.remount().then(() => { window.__settled = 'done'; }, (e) => { window.__settled = String(e); });"
                        "window.__page.unmount();")
    assert until(lambda: front.page.evaluate("window.__settled || null"), what="the remount to settle") == "done"
    front.page.wait_for_timeout(1500)
    assert_nothing_left(front)


def test_two_remounts_at_once_both_settle_and_one_page_stands(front):
    front.open()
    front.page.evaluate("Promise.all([window.__page.remount(), window.__page.remount()])"
                        ".then(() => { window.__settled = 'done'; }, (e) => { window.__settled = String(e); });")
    assert until(lambda: front.page.evaluate("window.__settled || null"), what="both remounts to settle") == "done"
    front.page.wait_for_timeout(500)
    assert front.js("return root.querySelectorAll('#rd-menu-btn').length;") == 1
    assert front.page.evaluate("window.__streams.filter((e) => e.readyState !== 2).length") == 1
