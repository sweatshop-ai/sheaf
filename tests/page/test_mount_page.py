"""The page mounted in the front's document (#116 step 2, slice iii): page.js runs in the closed shadow root that
page/mount.js builds, through `sheafPage.create(root, cfg, {body, remount})`, not in a document of its own.

A "front" here is a page of the hub's origin (Playwright answers its address) that loads `/_/mount.js` and mounts the
sheaf in a pane, as the loader will. The root stays CLOSED, as in production; the test reaches it through the one
reference an init script keeps (`window.__root`), and acts on it with the real mouse and keyboard at the places it
measures there. The comment test runs in Chromium, Firefox and WebKit: selection in a shadow root is where they differ.
"""
import json
import re

import pytest
from helpers import PLAN
from pagehelp import (BLUE, DOC, HOST, PAGE_TIMEOUT_MS, RED, assert_readable, close_context, drop_host, new_context, until,
                      wear_host)

from sheafmd import comments as rdc

pytestmark = pytest.mark.page

FRONT = "/_front-for-test"
FRONT_HTML = f"""<!doctype html><html><head><meta charset="utf-8"></head>
<body style="margin:0"><header id="front" style="height:60px">the front</header>
<div id="pane" style="height:640px"></div>
<script src="/_/mount.js"></script>
<script>window.__front = true;
window.__before = window.__live.size;          // the listeners the front holds before the mount
sheafMount.mount(document.getElementById('pane'), {{doc: {json.dumps(DOC)},
  upgrade: (v) => {{ (window.__upgrades = window.__upgrades || []).push(v); }},
  navigate: (path) => {{ (window.__moves = window.__moves || []).push(path); }}}})
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


def test_the_mounted_page_wears_the_fronts_font_once_the_loader_sets_it_on_the_host(front):
    """#152: the loader sets `--front-font` on the host, as it sets the colours, and the wrapper takes it as its family,
    as the old frame's body took `body.style.fontFamily`: code keeps its own. Taken off again, the theme's comes back."""
    f = front.open()
    theme = f.js("return getComputedStyle(root.querySelector('.rd-root')).fontFamily;")
    f.page.evaluate("document.getElementById('pane').style.setProperty('--front-font', '\"Front Sans\", serif')")
    got = f.js("""const of = (s) => getComputedStyle(root.querySelector(s)).fontFamily;
      return [of('.rd-root'), of('main p'), of('main pre code')];""")
    assert got[0] == '"Front Sans", serif' and got[1] == got[0] and got[2] != got[0], got
    f.page.evaluate("document.getElementById('pane').style.removeProperty('--front-font')")
    assert f.js("return getComputedStyle(root.querySelector('.rd-root')).fontFamily;") == theme


RULE = ':host([style*="--front-font"]) .rd-root{font-family:var(--front-font)}'


@pytest.mark.parametrize("kept", [False, True], ids=["fresh", "kept-mount-css"])
@pytest.mark.parametrize("tail", [".note{color:#333", ".note{color:#333}/* not closed"])
def test_a_theme_that_ends_open_does_not_swallow_the_fronts_font(chromium, site, tmp_path, tail, kept):
    """#152's gap: a user theme that ends inside a block or a comment swallows any rule after it in its stylesheet.
    The rule that hands the wrapper `--front-font` comes before the theme, so the theme cannot reach it; and it does
    with a `/_/mount.css` a browser kept from before the rule (under 1.0.1's `?v=`, before #179 named it by content)."""
    theme = tmp_path / "open-theme"
    theme.mkdir()
    (theme / "theme.toml").write_text('name = "open"\n', encoding="utf-8")
    (theme / "theme.css").write_text("body{font-family:Georgia,serif}\n" + tail, encoding="utf-8")
    site.hub.render(site.file, {"theme": str(theme)}, None)
    c, f = _front(chromium, site)
    if kept:
        f.page.route("**/_/mount.css*", lambda r: r.fulfill(response=(got := r.fetch()),
                                                             body=got.text().replace(RULE, "")))
    try:
        f.open()
        assert "Georgia" in f.js("return getComputedStyle(root.querySelector('.rd-root')).fontFamily;")
        f.page.evaluate("document.getElementById('pane').style.setProperty('--front-font', '\"Front Sans\", serif')")
        assert f.js("return getComputedStyle(root.querySelector('.rd-root')).fontFamily;") == '"Front Sans", serif'
        assert f.errors == []
    finally:
        close_context(c)


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


def _mount_again(front, opts_js):
    """mount() again on the front's pane, with `opts_js` (a JS object literal); the handle lands in window.__page."""
    front.page.evaluate("window.__page = null; window.__again = null; sheafMount.mount(document.getElementById('pane'), "
                        + opts_js + ").then((m) => { window.__page = m; }, (e) => { window.__again = String(e); });")
    until(lambda: front.page.evaluate("!!(window.__page || window.__again)"), what="the second mount")
    assert front.page.evaluate("window.__again") is None


def test_a_mount_that_failed_can_be_tried_again_on_the_same_pane(front):
    """A failed first mount must not cost the pane its shadow root: attachShadow throws the second time (Ines's P2)."""
    hits = []

    def once(route):
        hits.append(route.request.url)
        if len(hits) == 1:
            route.fulfill(status=503, content_type="application/json", body='{"error": "the hub is starting"}')
        else:
            route.continue_()

    front.page.route("**/_/mount?doc=*", once)
    front.page.goto(front.site.base + FRONT)
    assert "503" in until(lambda: front.page.evaluate("window.__failed || null"), what="the failed mount")
    _mount_again(front, "{doc: %s}" % json.dumps(DOC))
    until(lambda: front.has("#rd-menu-btn"), what="the page after the second try")


def test_a_pane_mounts_again_after_an_unmount_and_over_a_page_still_standing(front):
    """The loader moves from a sheaf to the list and back in the same pane."""
    front.open()
    front.page.evaluate("window.__page.unmount()")
    _mount_again(front, "{doc: %s}" % json.dumps(DOC))
    until(lambda: front.has("#rd-menu-btn"), what="the page mounted again")
    # A mount over a page that still stands takes that page down first: one page, one stream.
    _mount_again(front, "{doc: %s}" % json.dumps(DOC))
    until(lambda: front.has("#rd-menu-btn"), what="the page mounted over the first")
    front.page.wait_for_timeout(500)
    assert front.js("return root.querySelectorAll('#rd-menu-btn').length;") == 1
    assert front.page.evaluate("window.__streams.filter((e) => e.readyState !== 2).length") == 1


# The name of the new hub's mount.js, which the page hands the loader to load (#179): one name per build, so the
# loader's once-per-name guard lets every upgrade through, a second one under the same version too.
NEXT_JS = "9" * 16


def _another_version(route):
    res = route.fetch()
    got = res.json()
    got["version"] = "9.9.9-next"
    got["assets"]["mount.js"] = NEXT_JS
    route.fulfill(response=res, body=json.dumps(got))


def test_a_hub_of_another_version_hands_the_remount_to_the_loader(front):
    """A hub upgrade under a mounted page: the page.js in memory is the old one, so the remount builds nothing with it and
    tells the loader the new version, which loads the new script (Ines's P2)."""
    front.open()
    front.js("root.querySelector('main').__old = 1;")
    front.page.route("**/_/mount?doc=*", _another_version)
    front.site.file.write_text(front.site.file.read_text().replace("about pears", "about plums"), encoding="utf-8")
    assert until(lambda: front.page.evaluate("window.__upgrades || null"), what="the loader told") == [NEXT_JS]
    front.page.wait_for_timeout(300)
    assert front.js("return root.querySelector('main').__old;") == 1, "the old script built the new page"
    # Told once: a later trigger of a remount does not call the loader again, and the old page says what is happening.
    front.site.file.write_text(front.site.file.read_text().replace("about plums", "about figs"), encoding="utf-8")
    front.page.wait_for_timeout(2500)
    assert front.page.evaluate("window.__upgrades") == [NEXT_JS]
    assert "updated" in front.js("return root.getElementById('rd-toast').textContent;")


def _another_script(route):
    res = route.fetch()
    got = res.json()
    got["script"] = "f" * 16
    got["assets"]["mount.js"] = NEXT_JS
    route.fulfill(response=res, body=json.dumps(got))


def test_a_hub_with_other_scripts_under_the_same_version_hands_the_remount_to_the_loader(front):
    """#179: the page's scripts changed under the hub's version (a build between releases, #152's way). The page.js in
    memory is the old one all the same, so the hub's script name, not its version, tells an upgrade."""
    front.open()
    front.js("root.querySelector('main').__old = 1;")
    front.page.route("**/_/mount?doc=*", _another_script)
    front.site.file.write_text(front.site.file.read_text().replace("about pears", "about plums"), encoding="utf-8")
    assert until(lambda: front.page.evaluate("window.__upgrades || null"), what="the loader told") == [NEXT_JS]
    front.page.wait_for_timeout(300)
    assert front.js("return root.querySelector('main').__old;") == 1, "the old script built the new page"


def test_this_mount_js_served_by_a_hub_from_before_179_mounts_by_the_version_alone(front):
    """Opus review 1 of #180, P1: between the reinstall and the restart of an upgrade from 1.0.2, the old hub serves this
    mount.js with only the version written in, and answers with no `script` and no `assets`. The page mounts as a 1.0.2
    page would, and never takes the mark it was not given for another hub's scripts (an upgrade on every answer)."""
    def as_the_old_hub_serves_it(route):
        res = route.fetch()
        body = re.sub(r'const SCRIPT = "[0-9a-f]+";', "const SCRIPT = '@@SHEAF_SCRIPT@@';", res.text(), count=1)
        assert "@@SHEAF_SCRIPT@@" in body
        route.fulfill(response=res, body=body)

    def as_the_old_hub_answers(route):
        res = route.fetch()
        got = res.json()
        del got["script"], got["assets"]
        route.fulfill(response=res, body=json.dumps(got))

    front.page.route("**/_/mount.js*", as_the_old_hub_serves_it)
    front.page.route("**/_/mount?doc=*", as_the_old_hub_answers)
    front.open()
    # Opus review 2, P2: not `?v=<version>`, which that hub keeps for a year whatever files are on its disk
    assert front.js("return root.querySelector('link[rel=stylesheet]').getAttribute('href');") == "/_/mount.css"
    front.site.file.write_text(front.site.file.read_text().replace("about pears", "about plums"), encoding="utf-8")
    until(lambda: "plums" in front.js("return root.querySelector('main').textContent;"), what="the remount")
    assert front.page.evaluate("window.__upgrades || null") is None


_TYPED = ("const e = new InputEvent('beforeinput', {cancelable: true, bubbles: true});"
          "root.querySelector('main').dispatchEvent(e); return e.defaultPrevented;")


def test_every_remount_after_an_upgrade_leaves_the_old_page_writable(front):
    """The loader's upgrade is slow or failed and the file changes again: the second settle had set `settling` and
    written the keep, and the remount told nobody, so the page went read-only in silence (gate P2 of 5453534)."""
    front.open()
    front.page.route("**/_/mount?doc=*", _another_version)
    front.site.file.write_text(front.site.file.read_text().replace("about pears", "about plums"), encoding="utf-8")
    until(lambda: front.page.evaluate("window.__upgrades || null"), what="the loader told")
    until(lambda: front.js(_TYPED) is False, what="the page writable after the first change")
    front.js("root.getElementById('rd-toast').textContent = '';")
    front.site.file.write_text(front.site.file.read_text().replace("about plums", "about figs"), encoding="utf-8")
    until(lambda: "updated" in front.js("return root.getElementById('rd-toast').textContent;"),
          what="the second change said in the page")
    assert front.js(_TYPED) is False, "typing is refused after the second change"
    assert front.page.evaluate("Object.keys(sessionStorage).filter((k) => k.endsWith('rd-keep'))") == []
    assert front.page.evaluate("window.__upgrades") == [NEXT_JS]


def test_a_first_mount_of_another_version_builds_nothing_and_without_a_loader_says_reload(front):
    front.page.route("**/_/mount?doc=*", _another_version)
    front.page.goto(front.site.base + FRONT)
    assert until(lambda: front.page.evaluate("window.__upgrades || null"), what="the loader told") == [NEXT_JS]
    assert not front.has("#rd-menu-btn")
    # It took nothing of the pane: no root was attached, so the loader's new script can still attach its own there.
    assert front.page.evaluate("window.__root === undefined")
    # No loader to hand it to: the pane says so instead of running the old script on the new hub.
    front.page.evaluate("const d = document.createElement('div'); d.id = 'pane2'; document.body.append(d);"
                        "window.__page = null; sheafMount.mount(d, {doc: %s}).then((m) => { window.__page = m; });"
                        % json.dumps(DOC))
    until(lambda: front.page.evaluate("!!window.__page"), what="the second pane")
    assert "reload" in front.js("return root.textContent;").lower()
    assert not front.has("#rd-menu-btn")


def test_a_remount_that_fails_says_so_in_the_page_and_the_next_one_still_works(front):
    """A signed-out mounted page went silent: the remount's failure was swallowed (Ines's P2)."""
    front.open()
    refuse = [True]
    front.page.route("**/_/mount?doc=*", lambda route: route.fulfill(
        status=401, content_type="application/json", body='{"error": "sign in"}') if refuse else route.continue_())
    front.site.file.write_text(front.site.file.read_text().replace("about pears", "about plums"), encoding="utf-8")
    until(lambda: "401" in (front.js("const t = root.getElementById('rd-toast'); return t.className.includes('err') "
                                     "? t.textContent : '';") or ""), what="the failure said in the page")
    # The keep the reload wrote is not left for a later mount of this sheaf in the tab to restore.
    assert front.page.evaluate("Object.keys(sessionStorage).filter((k) => k.endsWith('rd-keep'))") == []
    refuse.clear()
    front.site.file.write_text(front.site.file.read_text().replace("about plums", "about figs"), encoding="utf-8")
    until(lambda: "about figs" in front.js("return root.querySelector('main').textContent;"), what="the next remount")


def test_of_two_mounts_on_one_pane_the_one_called_last_stands_whichever_answers_first(front):
    """The loader moves on before the first answer is in: the older mount must not take the pane over the newer one
    (gate P2 of 2e9856f: the answer that came last won, and dropping the older handle left the pane empty)."""
    front.open()
    front.page.evaluate("""(() => {
      const f = window.fetch; let n = 0;
      window.fetch = function (u, o) { const p = f(u, o);
        if (String(u).startsWith('/_/mount?doc=') && n++ === 0) return new Promise((r) => setTimeout(() => r(p), 1500));
        return p; };
      const pane = document.getElementById('pane');
      window.__order = [];
      sheafMount.mount(pane, {doc: %s}).then((m) => { window.__h1 = m; __order.push(1); });
      sheafMount.mount(pane, {doc: %s}).then((m) => { window.__h2 = m; __order.push(2);
        window.__root.querySelector('main').__mark = 2; });
    })()""" % (json.dumps(DOC), json.dumps(DOC)))
    until(lambda: front.page.evaluate("window.__order.length === 2"), what="both mounts to settle")
    front.page.wait_for_timeout(300)
    assert front.js("return root.querySelector('main').__mark;") == 2, "the older mount replaced the newer page"
    front.page.evaluate("window.__h1.unmount()")
    assert front.js("return root.querySelectorAll('#rd-menu-btn').length;") == 1, "dropping the older handle took the page"
    assert front.page.evaluate("window.__streams.filter((e) => e.readyState !== 2).length") == 1


def test_a_mount_overtaken_before_its_answer_resolves_to_a_handle_that_says_so(front):
    """The loader awaits mount A and reads its title after the user already clicked B: A's handle threw a TypeError from
    its getters, and a failed fetch of A was swallowed (gate P2 of 5453534)."""
    front.open()
    got = front.page.evaluate("""(async () => {
      const f = window.fetch; let n = 0;
      window.fetch = function (u, o) {
        if (String(u).startsWith('/_/mount?doc=') && n++ === 0)
          return new Promise((r, no) => setTimeout(() => no(new TypeError('offline')), 800));
        return f(u, o); };
      const pane = document.getElementById('pane');
      const a = sheafMount.mount(pane, {doc: %s});
      const b = sheafMount.mount(pane, {doc: %s});
      const h = await a, k = await b;
      return [h.overtaken, h.title, h.config, h.toc, h.dirty(), k.overtaken, typeof k.title];
    })()""" % (json.dumps(DOC), json.dumps(DOC)))
    assert got == [True, None, None, None, False, False, "string"], got
    assert front.js("return root.querySelectorAll('#rd-menu-btn').length;") == 1


HEADS = "# Plan\n\n" + "".join(f"## Part {i}\n\n" + "".join(f"Line {i}.{j}.\n\n" for j in range(12)) for i in range(1, 8))


def test_a_contents_link_scrolls_the_pane_to_its_heading_and_leaves_the_front_where_it_is(front):
    """A fragment in a shadow root is looked up in the front's document: the click scrolled nothing and changed the
    front's hash. mount.js scrolls the root's own element into view instead."""
    front.site.file.write_text(HEADS, encoding="utf-8")
    front.open()
    link = "nav a[href$='part-6']"
    until(lambda: front.has(link), what="the contents")
    href = front.js("return root.querySelector(arg).getAttribute('href');", link)
    assert href.startswith("#u-"), href
    front.click(link)
    until(lambda: front.js("const h = root.getElementById(arg.slice(1)), w = root.querySelector('.rd-root');"
                           "return Math.abs(h.getBoundingClientRect().top - w.getBoundingClientRect().top) < 40;", href),
          what="the heading at the top of the pane")
    assert front.page.evaluate("location.hash") == ""
    assert front.page.evaluate("window.__moves || null") is None


def test_a_link_to_a_page_of_the_hub_goes_to_the_loader_and_a_modified_click_does_not(front):
    """The root is closed, so the front cannot see which link in it was clicked: a plain click on a link of the origin
    is handed to opts.navigate, which moves the front; a ctrl-click, a target or a download is the browser's."""
    front.site.file.write_text(PLAN.replace("Last paragraph.", "See [the list](/list?show=mine), [out](https://example.org/x),"
                                            " [new](/list), [file](/list/a.md), [hub](/_/export?doc=x)."), encoding="utf-8")
    front.open()
    front.click("main a[href='/list?show=mine']")
    assert until(lambda: front.page.evaluate("window.__moves || null"), what="the move") == ["/list?show=mine"]
    assert front.page.evaluate("location.pathname") == FRONT
    # What mount.js decided, read on the front's side of the root; the front then stops the browser following it.
    front.page.evaluate("document.getElementById('pane').addEventListener('click', (e) => {"
                        " window.__prevented = e.defaultPrevented; e.preventDefault(); })")
    clicked = """const a = root.querySelector(arg[0]); if (arg[1]) a.setAttribute(arg[1], '_blank');
      a.dispatchEvent(new MouseEvent('click', {bubbles: true, composed: true, cancelable: true, button: 0, ctrlKey: !!arg[2]}));
      return window.__prevented;"""
    assert front.js(clicked, ["main a[href='/list']", None, True]) is False
    assert front.js(clicked, ["main a[href='/list/a.md']", "target", False]) is False
    assert front.js(clicked, ["main a[href^='https:']", None, False]) is False
    assert front.js(clicked, ["main a[href='/list']", "download", False]) is False
    # A route of the hub itself is no page for the loader to mount: the browser's (gate P3 of e01c79d).
    assert front.js(clicked, ["main a[href^='/_/']", None, False]) is False
    assert front.page.evaluate("window.__moves") == ["/list?show=mine"]


# A sheaf's own action buttons (page.css, #rd-actions): a one-off, a toggle, and each pressed, put at the top of `arg`
# (the mounted page's wrapper) or of the body; their colours and the background they stand on.
ACTS = """const top = arg ? root.querySelector(arg) : document.body;
  let bar = root.getElementById('rd-actions');
  if (!bar) { bar = document.createElement('div'); bar.id = 'rd-actions'; top.prepend(bar); }
  bar.replaceChildren(...[['one-off', 'Approve'], ['toggle', 'Share'], ['one-off pressed', 'Approved'],
    ['toggle pressed', 'Shared']].map(([c, t]) => Object.assign(document.createElement('button'),
      {className: 'rd-act ' + c, textContent: t})));
  const cs = (s) => getComputedStyle(bar.querySelector(s));
  return {once: [cs('.one-off:not(.pressed)').borderTopColor, cs('.one-off:not(.pressed)').color],
          toggle: [cs('.toggle:not(.pressed)').borderTopColor, cs('.toggle:not(.pressed)').color],
          pressed: [cs('.one-off.pressed').backgroundColor, cs('.toggle.pressed').backgroundColor,
                    cs('.one-off.pressed').color],
          bg: getComputedStyle(top).backgroundColor};"""


def acts_of_own(page):
    return page.evaluate("([arg]) => { const root = document; " + ACTS + " }", [None])


def assert_acts_of(got, scheme):
    assert got["once"] == [RED[scheme]] * 2 and got["toggle"] == [BLUE[scheme]] * 2, got
    assert got["pressed"] == [RED[scheme], BLUE[scheme], got["bg"]], got
    for c in (RED[scheme], BLUE[scheme]):
        assert_readable(c, got["bg"])


@pytest.mark.parametrize("os, host", [("dark", "light"), ("light", "dark"), ("dark", "dark"), ("light", "light")])
def test_a_mounted_sheafs_action_buttons_follow_the_scheme_the_loader_sets_on_the_host_not_the_oss(front, os, host):
    """#169: `#rd-actions .rd-act` took its red and blue from `prefers-color-scheme` while the mounted page's background
    is the front's. They follow the `color-scheme` the loader sets on the host, and the OS's while the host sets none."""
    front.page.emulate_media(color_scheme=os)
    front.open()
    assert_acts_of(front.js(ACTS, ".rd-root"), os)
    wear_host(front.page, host)
    got = front.js(ACTS, ".rd-root")
    assert got["bg"] == HOST[host]["--bg"], got
    assert_acts_of(got, host)
    drop_host(front.page, host)
    assert_acts_of(front.js(ACTS, ".rd-root"), os)


@pytest.mark.parametrize("os", ["light", "dark"])
def test_a_sheafs_action_buttons_on_its_own_page_follow_the_os(tab, os):
    tab.page.emulate_media(color_scheme=os)
    tab.open()
    assert_acts_of(acts_of_own(tab.page), os)


def a_theme(tmp_path, name, css):
    theme = tmp_path / name
    theme.mkdir()
    (theme / "theme.toml").write_text(f'name = "{name}"\n', encoding="utf-8")
    (theme / "theme.css").write_text(css, encoding="utf-8")
    return str(theme)


LIGHT_THEME = ":root{--bg:#fff;--fg:#111;color-scheme:light}body{background:var(--bg)}\n"
# Dark on a dark OS, with no `color-scheme` said.
SILENT_THEME = (":root{--bg:#fff;--fg:#111}@media (prefers-color-scheme:dark){:root{--bg:#14171a;--fg:#eee}}"
                "body{background:var(--bg)}\n")


@pytest.mark.parametrize("css, scheme", [(LIGHT_THEME, "light"), (SILENT_THEME, "dark")], ids=["says-light", "says-none"])
def test_on_its_own_page_a_theme_that_says_its_scheme_keeps_it_and_one_that_says_none_follows_the_os(tab, site, tmp_path,
                                                                                                     css, scheme):
    """#169 review: the buttons follow the page's `color-scheme`; a theme that goes dark on a dark OS without saying so
    had the light red on its dark background (2.9:1). page.css gives the root the OS's scheme in a layer, so a theme's
    own still wins: on a dark OS, a light theme keeps light buttons and a silent one gets dark ones."""
    site.hub.render(site.file, {"theme": a_theme(tmp_path, "t", css)}, None)
    tab.page.emulate_media(color_scheme="dark")
    tab.open()
    assert_acts_of(acts_of_own(tab.page), scheme)


def test_a_mounted_theme_that_says_its_own_scheme_keeps_it_over_the_mounts_fallback(chromium, site, tmp_path):
    """#169: mount.css gives the host `color-scheme: light dark` where the loader sets none, so the buttons follow the OS
    there; a theme that says a scheme of its own on its :root (its :host in the mount) keeps it, the fallback being in
    a layer. Here a light theme on a dark OS: light buttons."""
    site.hub.render(site.file, {"theme": a_theme(tmp_path, "light", LIGHT_THEME)}, None)
    c, f = _front(chromium, site)
    try:
        f.page.emulate_media(color_scheme="dark")
        f.open()
        assert_acts_of(f.js(ACTS, ".rd-root"), "light")
        assert f.errors == []
    finally:
        close_context(c)
