"""The comment form on a phone with its keyboard up (SPEC 10.4).

iOS does not shrink the layout viewport for its keyboard: `innerHeight` stays, and `visualViewport` shrinks (and
scrolls) instead. Chromium has no keyboard, so a `visualViewport` that the test controls stands in for it.
What this cannot prove: iOS's own keyboard, its suggestion bar, the AutoFill pill and the dismiss button (they
are drawn by the system; the test leaves ACCESSORY px for them), and whether iOS zooms and pans on focus (the
test shows the cause the page controls: a 14px font, and a page wider than the screen). Only a real iPhone shows it."""
import pytest

from pagehelp import at, select, select_by_touch

pytestmark = pytest.mark.page

MD = "# Plan\n\nSecond paragraph, about pears.\n"
MAIN = "main"
BTN = "#rd-comment-btn"
POP = "#rd-popover"
ACCESSORY = 48          # px the form must keep clear above the keyboard, for the suggestion bar and the AutoFill pill (the page keeps 56)
KEYBOARD = 336          # px of keyboard on a 390x844 iPhone

# A visualViewport that the test moves, as iOS does when the keyboard opens (it shrinks, and scrolls to the focus).
FAKE_VV = """(() => {
  const t = new EventTarget();
  const vv = { width: 390, height: 844, offsetLeft: 0, offsetTop: 0, scale: 1, pageLeft: 0, pageTop: 0,
    addEventListener: (...a) => t.addEventListener(...a), removeEventListener: (...a) => t.removeEventListener(...a) };
  Object.defineProperty(window, 'visualViewport', { value: vv, configurable: true });
  window.__keyboard = (height, top) => { vv.height = height; vv.offsetTop = top || 0; t.dispatchEvent(new Event('resize')); };
})()"""


@pytest.fixture
def phone(touch_tab, site):
    site.file.write_text(MD, encoding="utf-8")
    touch_tab.page.add_init_script(FAKE_VV)
    return touch_tab.open()


def composer(phone):
    select_by_touch(phone.page, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    phone.page.wait_for_selector(BTN)
    b = phone.page.locator(BTN).bounding_box()
    phone.page.touchscreen.tap(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
    phone.page.wait_for_selector(POP + " textarea")
    phone.page.focus(POP + " textarea")
    return phone.page


def keyboard(page, height, top=0):
    page.evaluate("([h, t]) => window.__keyboard(h, t)", [height, top])
    page.wait_for_timeout(300)


def rects(page):
    """The popover, its buttons and its text field, as [left, top, right, bottom] in viewport px."""
    return page.evaluate("""() => { const r = (e) => { const b = e.getBoundingClientRect(); return [b.left, b.top, b.right, b.bottom]; };
        const p = document.querySelector('#rd-popover'), t = p.querySelector('textarea');
        return { pop: r(p), buttons: [...p.querySelectorAll('.rd-form button')].map(r), field: r(t) }; }""")


def inside(page, top, bottom):
    """The popover, every button and the field lie between `top` and `bottom` (viewport px) and inside the width."""
    got = rects(page)
    for left, t, right, b in [got["pop"], got["field"]] + got["buttons"]:
        assert left >= 0 and right <= 390, got
        assert t >= top - 0.5 and b <= bottom + 0.5, (top, bottom, got)
    return got


def test_the_form_docks_at_the_head_of_the_screen_when_a_keyboard_opens_after_it(phone):
    page = composer(phone)
    keyboard(page, 844 - KEYBOARD)
    got = inside(page, 0, 844 - KEYBOARD - ACCESSORY)
    assert got["pop"][1] <= 16, got


def test_the_buttons_come_before_the_field_so_none_is_under_the_keyboard(phone):
    page = composer(phone)
    keyboard(page, 844 - KEYBOARD)
    got = rects(page)
    assert got["buttons"] and all(b[3] <= got["field"][1] for b in got["buttons"]), got


def test_the_form_follows_the_visual_viewport_when_iOS_scrolls_it(phone):
    page = composer(phone)
    keyboard(page, 844 - KEYBOARD, 120)
    got = inside(page, 120, 120 + 844 - KEYBOARD - ACCESSORY)
    assert got["pop"][1] <= 120 + 16, got


def test_the_form_goes_back_to_its_place_when_the_keyboard_closes(phone):
    page = composer(phone)
    before = rects(page)["pop"]
    keyboard(page, 844 - KEYBOARD)
    keyboard(page, 844)
    assert rects(page)["pop"] == before
    assert page.evaluate("document.querySelector('#rd-popover').classList.contains('rd-docked')") is False


def test_the_text_field_is_16px_or_more_and_asks_for_no_autofill(phone):
    """iOS zooms into a field under 16px and pans the page sideways; it offers AutoFill to a field that does not refuse."""
    page = composer(phone)
    assert page.evaluate("parseFloat(getComputedStyle(document.querySelector('#rd-popover textarea')).fontSize)") >= 16
    got = page.evaluate("""(() => { const t = document.querySelector('#rd-popover textarea');
        return { autocomplete: t.getAttribute('autocomplete'), spellcheck: t.getAttribute('spellcheck'), name: t.getAttribute('name'), id: t.id, type: t.type }; })()""")
    assert got == {"autocomplete": "off", "spellcheck": "true", "name": None, "id": "", "type": "textarea"}


def test_the_page_is_no_wider_than_the_screen_while_the_form_is_open(phone):
    page = composer(phone)
    keyboard(page, 844 - KEYBOARD)
    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth && document.body.scrollWidth <= window.innerWidth")
    assert page.evaluate("window.scrollX") == 0


def test_a_pinch_zoom_is_not_a_keyboard_and_leaves_the_form_where_it_is(phone):
    page = composer(phone)
    page.evaluate("window.visualViewport.scale = 2")
    keyboard(page, 400)
    assert page.evaluate("document.querySelector('#rd-popover').style.maxWidth") == ""


def test_with_a_mouse_the_form_is_never_docked(tab, site):
    site.file.write_text(MD, encoding="utf-8")
    tab.page.add_init_script(FAKE_VV)
    tab.open()
    select(tab.page, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    tab.page.wait_for_selector(BTN)
    tab.page.click(BTN)
    tab.page.wait_for_selector(POP + " textarea")
    tab.page.evaluate("window.__keyboard(400, 0)")
    tab.page.wait_for_timeout(300)
    assert tab.page.evaluate("document.querySelector('#rd-popover').style.maxWidth") == ""


def test_a_screen_too_short_for_the_form_scrolls_it_and_keeps_the_keyboard_clear(phone):
    """Landscape: the keyboard leaves 150 px. The form is cut to what is left above the accessory room, and scrolls."""
    page = composer(phone)
    keyboard(page, 150)
    got = rects(page)
    assert got["pop"][3] <= 150 - ACCESSORY, got
    assert page.evaluate("(() => { const p = document.querySelector('#rd-popover'); return p.scrollHeight > p.clientHeight; })()")
