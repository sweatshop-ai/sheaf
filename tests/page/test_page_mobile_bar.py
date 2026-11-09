"""The bar a phone is offered after a selection (plan: "Sélection sur téléphone"), in a touch emulation: one touch opens the box
with the cursor in the field, a number does the same, the bar looks like the chat's field, and the selection is left alone while the
bar shows (the phone's own Copy menu needs it). A real keyboard and the Copy menu can only be judged on a phone."""
import pytest

from pagehelp import at, close_context, new_context, select, select_by_touch, selected, until
from sheafmd import comments as rdc
from sheafmd.source import update_file

pytestmark = pytest.mark.page

BTN = "#rd-comment-btn"
FIELD = "#rd-popover textarea"
MAIN = "main"
PLAN_MD = "# Plan\n\nSecond paragraph, about pears.\n\nA third one, about apples.\n"
UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148"


@pytest.fixture
def phone(touch_tab, site):
    site.file.write_text(PLAN_MD, encoding="utf-8")
    return touch_tab.open()


def raise_bar(phone):
    select_by_touch(phone.page, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    phone.page.wait_for_selector(BTN)
    return phone.page


def centre(p, css):
    b = p.locator(css).bounding_box()
    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2


def focused(p):
    return p.evaluate("(() => { const a = document.activeElement; return a ? a.tagName + (a.id ? '#' + a.id : '') : null; })()")


def test_touching_the_bar_opens_the_box_with_the_cursor_in_the_field(phone):
    p = raise_bar(phone)
    p.touchscreen.tap(*centre(p, BTN))
    p.wait_for_selector(FIELD)
    assert focused(p) == "TEXTAREA", "the cursor is not in the field"
    assert p.evaluate("document.activeElement.matches('#rd-popover textarea')")


def test_touching_a_number_puts_the_cursor_in_the_field_too(phone, site):
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "apples"), "apples", "Why?",
                                                     "Bea", "2026-10-14T10:00")[0])
    p = phone.open().page
    p.touchscreen.tap(*centre(p, ".rd-badge"))
    p.wait_for_selector(FIELD)
    assert focused(p) == "TEXTAREA", "the cursor is not in the field"


def test_the_bar_looks_like_the_chats_field(phone):
    p = raise_bar(phone)
    bar = p.evaluate("""() => { const s = getComputedStyle(document.querySelector('#rd-comment-btn')), b = document.querySelector('#rd-comment-btn').getBoundingClientRect();
      return {radius: s.borderTopLeftRadius, border: s.borderTopColor, size: s.fontSize, family: s.fontFamily, bg: s.backgroundColor, text: document.querySelector('#rd-comment-btn').textContent, w: b.width}; }""")
    p.touchscreen.tap(*centre(p, BTN))
    p.wait_for_selector(FIELD)
    form = p.evaluate("""() => { const f = document.querySelector('#rd-popover .rd-form'), s = getComputedStyle(f), t = document.querySelector('#rd-popover textarea');
      return {radius: s.borderTopLeftRadius, border: s.borderTopColor, size: getComputedStyle(t).fontSize, family: getComputedStyle(t).fontFamily,
              bg: s.backgroundColor, text: t.placeholder}; }""")
    assert bar["text"] == form["text"], "the bar does not carry the field's placeholder"
    assert bar["radius"] == form["radius"] and bar["border"] == form["border"]
    assert bar["size"] == form["size"] and bar["family"] == form["family"]
    assert bar["w"] > 390 * 0.7, "the bar is not a wide field"


def test_the_selection_is_left_intact_while_the_bar_shows_so_the_phones_copy_menu_has_it(phone):
    p = raise_bar(phone)
    p.wait_for_timeout(1500)
    assert selected(p) == "Second paragraph", "the bar took the selection"
    assert p.locator(BTN).count() == 1
    assert focused(p) != "BUTTON#rd-comment-btn", "the bar holds the focus: the selection would be gone on a phone"
    assert p.evaluate("document.activeElement === document.body"), "something took the focus from the selection"
    # A touch on the page's other controls does not change what is selected.
    p.evaluate("window.scrollBy(0, 3)")
    p.wait_for_timeout(500)
    assert selected(p) == "Second paragraph"


def test_a_touch_on_the_bar_does_not_move_the_cursor_before_the_box_has_opened(phone):
    """The touchstart on the bar is cancelled: the browser may not collapse the selection nor focus the bar."""
    p = raise_bar(phone)
    p.evaluate("""() => { window.__prevented = null;
      document.addEventListener('touchstart', e => { setTimeout(() => { window.__prevented = e.defaultPrevented; }, 0); }, false); }""")
    p.touchscreen.tap(*centre(p, BTN))
    p.wait_for_selector(FIELD)
    assert p.evaluate("window.__prevented") is True


@pytest.fixture
def laptop(chromium, site):
    """A touchscreen laptop: touch hardware, but the primary pointer is the mouse or trackpad, so `(pointer: coarse)` is false
    (Chromium's has_touch alone reports coarse, as a phone; the stub is what a laptop answers)."""
    c = new_context(chromium, viewport={"width": 1100, "height": 800}, has_touch=True)
    c.add_cookies([site.cookie()])
    c.add_init_script("""(() => { const m = window.matchMedia.bind(window);
      window.matchMedia = q => /pointer:\\s*coarse/.test(q) && !/any-/.test(q) ? m("not all") : m(q); })()""")
    site.file.write_text(PLAN_MD, encoding="utf-8")
    from conftest import Tab
    t = Tab(c.new_page(), site)
    t.open()
    yield t
    try:
        assert t.errors == []
    finally:
        close_context(c)


def test_a_touchscreen_laptop_takes_the_desktop_path_the_box_opens_by_itself_with_a_finger_selection_too(laptop):
    p = laptop.page
    assert p.evaluate("matchMedia('(pointer: coarse)').matches") is False
    assert p.evaluate("matchMedia('(any-pointer: coarse)').matches") is True
    select_by_touch(p, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    p.wait_for_selector(FIELD)
    assert p.locator(BTN).count() == 0, "a bar was offered on a laptop"
    assert focused(p) == "TEXTAREA"
    p.keyboard.press("Escape")
    p.wait_for_selector(FIELD, state="detached")
    select(p, at(MAIN, "A third"), at(MAIN, "apples", None))
    p.wait_for_selector(FIELD)
    assert p.locator(BTN).count() == 0
