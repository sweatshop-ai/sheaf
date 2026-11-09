"""The thread's box on a phone with its keyboard up, in Chromium and in WebKit at 390 px (ticket 03, the second trial).

Thierry's iPhone showed the field under the hint and away from the arrow, and the last bubble cut by the composer. The
keyboard is a `visualViewport` that the test controls (as in test_page_keyboard.py); only a real iPhone shows the real one.
"""
import pytest

from conftest import Tab
from pagehelp import new_context
from sheafmd import comments as rdc
from sheafmd.source import update_file

pytestmark = pytest.mark.page

MD = "# Plan\n\nSecond paragraph, about pears.\n\nA third one, about apples.\n"
MAIN = "main"
BTN = "#rd-comment-btn"
POP = "#rd-popover"
FIELD = POP + " textarea"
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"
KEYBOARD = 336
FAKE_VV = """(() => {
  const t = new EventTarget();
  const vv = { width: 390, height: 844, offsetLeft: 0, offsetTop: 0, scale: 1, pageLeft: 0, pageTop: 0,
    addEventListener: (...a) => t.addEventListener(...a), removeEventListener: (...a) => t.removeEventListener(...a) };
  Object.defineProperty(window, 'visualViewport', { value: vv, configurable: true });
  window.__keyboard = (height, top) => { vv.height = height; vv.offsetTop = top || 0; t.dispatchEvent(new Event('resize')); };
})()"""


@pytest.fixture(params=["chromium", "webkit"])
def phone(request, site, chromium):
    if request.param == "chromium":
        browser, own = chromium, False
    else:
        try:
            browser, own = chromium.pw.webkit.launch(), True
        except Exception as e:      # noqa: BLE001 - not installed, or its libraries are missing here (CI fails on a skip)
            pytest.skip(f"webkit cannot start here: {str(e).splitlines()[0]}")
    c = new_context(browser, viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True, user_agent=UA)
    c.add_cookies([site.cookie()])
    site.file.write_text(MD, encoding="utf-8")
    t = Tab(c.new_page(), site)
    t.page.add_init_script(FAKE_VV)
    t.engine = request.param
    yield t
    try:
        assert t.errors == [], "the page raised script errors"
    finally:
        c.close()
        if own:
            browser.close()


def keyboard(page, height, top=0):
    page.evaluate("([h, t]) => window.__keyboard(h, t)", [height, top])
    page.wait_for_timeout(300)


def talk(site, n):
    """A thread of `n` messages, the last one two lines long."""
    def add(t):
        t = rdc.add_comment(t, *rdc.find_quote(t, "Second paragraph"), "Second paragraph", "First message.", "Ada", "2026-10-25T21:00")[0]
        for i in range(2, n):
            t = rdc.reply(t, "c1", f"Message number {i}.", "Bea", f"2026-10-25T21:{i:02d}")
        return rdc.reply(t, "c1", "Le budget ne couvre que trois jours, le reste dépend de la saison et du client.", "Bea", "2026-10-25T21:59")
    update_file(site.file, add)


def open_thread(phone, n=6, up=None):
    talk(phone.site, n)
    page = phone.open().page
    if up:
        keyboard(page, up)
    page.touchscreen.tap(*centre(page, ".rd-badge"))
    page.wait_for_selector(FIELD)
    page.focus(FIELD)
    return page


def centre(p, css):
    b = p.locator(css).bounding_box()
    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2


LAYOUT = """() => { const r = (e) => { const b = e.getBoundingClientRect(); return b ? {top: b.top, bottom: b.bottom, left: b.left, right: b.right} : null; };
  const q = (s) => document.querySelector(s), last = [...document.querySelectorAll('#rd-popover .rd-scroll .rd-msg')].pop();
  const s = q('#rd-popover .rd-scroll'), line = q('#rd-popover .rd-agent-line');
  return { pop: r(q('#rd-popover')), form: r(q('#rd-popover .rd-form')), field: r(q('#rd-popover textarea')), send: r(q('#rd-popover .rd-send')),
           line: line ? r(line) : null, scroll: r(s), last: r(last), docked: q('#rd-popover').classList.contains('rd-docked'),
           atEnd: s.scrollTop + s.clientHeight >= s.scrollHeight - 1, popTop: q('#rd-popover').scrollTop }; }"""


def assert_composer_order(got):
    """The text field and the round arrow in one row, the arrow at the top right of the box, and no hint line (G, third trial)."""
    assert got["line"] is None, f"the hint line is still drawn: {got}"
    assert got["field"]["top"] - got["form"]["top"] < 24, f"the field is not at the top of the frame: {got}"
    assert got["send"]["left"] >= got["field"]["right"] - 1, f"the arrow is not beside the field: {got}"
    assert abs(got["send"]["top"] - got["field"]["top"]) < 12, f"the arrow is not at the top of the box: {got}"
    assert got["send"]["right"] > got["form"]["right"] - 40, f"the arrow is not at the right: {got}"


def test_with_the_keyboard_up_the_field_and_the_arrow_share_a_row_arrow_at_the_top_right(phone):
    page = open_thread(phone)
    assert_composer_order(page.evaluate(LAYOUT))
    keyboard(page, 844 - KEYBOARD)
    got = page.evaluate(LAYOUT)
    assert got["docked"], got
    assert_composer_order(got)


def test_the_hint_line_is_gone_with_no_agent_and_the_keyboard_up(phone):
    """Restated: the hint "Render this page from an agent session..." used to stay under the field; it is not drawn at all now."""
    page = open_thread(phone, up=844 - KEYBOARD)
    got = page.evaluate(LAYOUT)
    assert got["line"] is None and got["docked"], got
    assert_composer_order(got)


def test_a_growing_field_keeps_the_arrow_at_the_top(phone):
    page = open_thread(phone)
    page.fill(FIELD, "A long message. " * 12)
    got = page.evaluate(LAYOUT)
    assert got["field"]["bottom"] - got["field"]["top"] > 60, got
    assert_composer_order(got)


@pytest.mark.parametrize("n", [1, 2, 6])
@pytest.mark.parametrize("height", [520, 420, 360])
def test_the_thread_opens_on_its_last_message_fully_visible_when_the_keyboard_makes_the_box_short(phone, n, height):
    page = open_thread(phone, n, up=height)
    got = page.evaluate(LAYOUT)
    assert got["docked"] and got["atEnd"], got
    assert got["last"]["top"] >= got["scroll"]["top"] - 0.5 or got["scroll"]["bottom"] - got["scroll"]["top"] < got["last"]["bottom"] - got["last"]["top"], got
    assert got["last"]["bottom"] <= min(got["scroll"]["bottom"], got["form"]["top"]) + 0.5, f"the last bubble is cut: {got}"
    assert got["popTop"] == 0, got


def test_the_keyboard_rising_after_the_box_opened_leaves_the_last_message_fully_visible(phone):
    page = open_thread(phone, 6)
    keyboard(page, 420)
    got = page.evaluate(LAYOUT)
    assert got["docked"] and got["atEnd"], got
    assert got["last"]["bottom"] <= min(got["scroll"]["bottom"], got["form"]["top"]) + 0.5, f"the last bubble is cut: {got}"


# The five tests of the bar that quoted the selection (quote line, ellipsis, quote changing, stronger border and entrance, reduced
# motion) were removed on 2026-11-09 with the bar itself (ticket 03, E): a usable selection opens the box, so no bar is offered
# and there is nothing to quote, animate or restyle. The refused selection's disabled bar is tested in test_page_selection.py.
