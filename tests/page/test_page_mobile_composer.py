"""The thread's box on a phone with its keyboard up, in Chromium and in WebKit at 390 px (ticket 03, the second trial).

Thierry's iPhone showed the field under the hint and away from the arrow, and the last bubble cut by the composer. The
keyboard is a `visualViewport` that the test controls (as in test_page_keyboard.py); only a real iPhone shows the real one.
The bar a selection offers on a phone carries the selected words, so it is read as the answer to the selection."""
import pytest

from conftest import Tab
from pagehelp import at, close_context, new_context, select_by_touch, until
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
    """The text at the top of the frame, the round arrow under it at the right, the hint below the text, as on a desktop."""
    assert got["field"]["top"] - got["form"]["top"] < 24, f"the field is not at the top of the frame: {got}"
    assert got["send"]["top"] >= got["field"]["bottom"] - 1, f"the arrow is not under the field: {got}"
    assert got["send"]["right"] > got["form"]["right"] - 40, f"the arrow is not at the right: {got}"
    if got["line"]:
        assert got["line"]["top"] >= got["field"]["bottom"] - 1, f"the hint is above the field: {got}"


def test_with_the_keyboard_up_the_field_is_at_the_top_of_the_frame_and_the_arrow_under_it_as_on_a_desktop(phone):
    page = open_thread(phone)
    assert_composer_order(page.evaluate(LAYOUT))
    keyboard(page, 844 - KEYBOARD)
    got = page.evaluate(LAYOUT)
    assert got["docked"], got
    assert_composer_order(got)


def test_the_hint_stays_under_the_field_too_with_no_agent_and_the_keyboard_up(phone):
    page = open_thread(phone, up=844 - KEYBOARD)
    got = page.evaluate(LAYOUT)
    assert got["line"] is not None and got["docked"], got
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


# ── the bar a selection offers is tied to the selection ─────────────────────────────

def raise_bar(phone, start="Second", end="paragraph"):
    phone.open()
    select_by_touch(phone.page, at(MAIN, start), at(MAIN, end, None))
    phone.page.wait_for_selector(BTN)
    return phone.page


def test_the_bar_quotes_the_selected_words_above_the_field_text(phone):
    p = raise_bar(phone)
    got = p.evaluate("""() => { const b = document.querySelector('#rd-comment-btn'), q = b.querySelector('.rd-bar-quote'), w = b.querySelector('.rd-bar-write');
      return { quote: q && q.textContent, write: w && w.textContent, qTop: q && q.getBoundingClientRect().top, wTop: w && w.getBoundingClientRect().top }; }""")
    assert got["quote"] == "“Second paragraph”", got
    assert got["write"] == "Write a message…", got
    assert got["qTop"] < got["wTop"], got


def test_a_long_selection_is_quoted_on_one_line_cut_with_an_ellipsis(phone):
    p = raise_bar(phone, "Second", "pears")
    got = p.evaluate("""() => { const q = document.querySelector('#rd-comment-btn .rd-bar-quote'), s = getComputedStyle(q), b = document.querySelector('#rd-comment-btn');
      return { white: s.whiteSpace, over: s.overflow, ell: s.textOverflow, h: q.getBoundingClientRect().height, line: parseFloat(s.lineHeight), bar: b.getBoundingClientRect().height }; }""")
    assert got["white"] == "nowrap" and got["over"] == "hidden" and got["ell"] == "ellipsis", got
    assert got["h"] <= got["line"] + 1, got


def test_the_bar_changes_its_quote_with_the_selection(phone):
    p = raise_bar(phone)
    select_by_touch(p, at(MAIN, "A third"), at(MAIN, "apples", None))
    until(lambda: p.locator(BTN + " .rd-bar-quote").inner_text().startswith("“A third"), what="the bar to quote the new selection")


def test_the_bar_is_stronger_than_the_field_and_arrives_with_a_short_entrance(phone):
    p = raise_bar(phone)
    got = p.evaluate("""() => { const s = getComputedStyle(document.querySelector('#rd-comment-btn'));
      return { w: parseFloat(s.borderTopWidth), colour: s.borderTopColor, anim: s.animationName, dur: parseFloat(s.animationDuration), shadow: s.boxShadow }; }""")
    assert got["anim"] != "none" and 0 < got["dur"] <= 0.4, got
    assert got["w"] >= 1.5 or "0.25" not in got["colour"], f"the bar wears the field's quiet border: {got}"


def test_the_bar_holds_still_for_a_person_who_asks_for_less_motion(phone):
    phone.page.emulate_media(reduced_motion="reduce")
    p = raise_bar(phone)
    assert p.evaluate("getComputedStyle(document.querySelector('#rd-comment-btn')).animationName") == "none"
