"""What a phone does after a selection (plan: "Sélection sur téléphone"), in a touch emulation: the box opens by itself with the
cursor in the field, a number does the same, and a touchscreen laptop takes the desktop path. A real keyboard can only be judged on a phone.
Restated on 2026-11-09 (ticket 03, E): the bar a selection used to offer is gone for a usable selection; four tests of it
(bar shaped like the field, selection left intact for the phone's Copy menu, touchstart cancelled, bar opens box) no longer apply."""
import pytest

from pagehelp import at, close_context, new_context, select, select_by_touch
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


def centre(p, css):
    b = p.locator(css).bounding_box()
    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2


def focused(p):
    return p.evaluate("(() => { const a = document.activeElement; return a ? a.tagName + (a.id ? '#' + a.id : '') : null; })()")


def test_a_touch_selection_opens_the_box_with_the_cursor_in_the_field_and_no_bar(phone):
    select_by_touch(phone.page, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    phone.page.wait_for_selector(FIELD)
    assert focused(phone.page) == "TEXTAREA", "the cursor is not in the field"
    assert phone.page.locator(BTN).count() == 0


def test_touching_a_number_puts_the_cursor_in_the_field_too(phone, site):
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "apples"), "apples", "Why?",
                                                     "Bea", "2026-10-14T10:00")[0])
    p = phone.open().page
    p.touchscreen.tap(*centre(p, ".rd-badge"))
    p.wait_for_selector(FIELD)
    assert focused(p) == "TEXTAREA", "the cursor is not in the field"


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
