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
    """A selection by touch opens the box by itself (ticket 03, E); the cursor goes to the field as a tap in it would."""
    select_by_touch(phone.page, at(MAIN, "Second"), at(MAIN, "paragraph", None))
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


def test_the_field_comes_first_and_the_arrow_beside_it_at_the_top_all_above_the_keyboard(phone):
    """Restated on 2026-11-09 (G): the field and the round arrow are in one row, the arrow at the top right of the box, as
    Thierry asked after the third trial (the first layout had the arrow above, the second under the field); none of them under
    the keyboard (the popover is docked at the head of what can be seen)."""
    page = composer(phone)
    keyboard(page, 844 - KEYBOARD)
    got = inside(page, 0, 844 - KEYBOARD - ACCESSORY)
    assert got["buttons"] and all(b[0] >= got["field"][2] - 1 for b in got["buttons"]), got
    assert all(abs(b[1] - got["field"][1]) < 12 for b in got["buttons"]), got


def test_a_selection_made_with_the_keyboard_already_up_opens_the_box_above_the_keyboard(phone):
    """F: the keyboard is up before the selection (another field had it); the box that opens by itself is docked in what can be seen."""
    page = phone.page
    keyboard(page, 844 - KEYBOARD)
    select_by_touch(page, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    page.wait_for_selector(POP + " textarea")
    page.wait_for_timeout(300)
    got = inside(page, 0, 844 - KEYBOARD - ACCESSORY)
    assert page.evaluate("document.querySelector('#rd-popover').classList.contains('rd-docked')"), got


def test_the_box_opened_by_a_touchend_with_the_keyboard_rising_afterwards_stays_above_it(phone):
    """F: the order on a phone is box first, keyboard a moment later (the focus raises it)."""
    page = phone.page
    select_by_touch(page, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    page.wait_for_selector(POP + " textarea")
    keyboard(page, 844 - KEYBOARD, 60)
    inside(page, 60, 60 + 844 - KEYBOARD - ACCESSORY)


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
    # Chromium lays out in 1/64 px: the first cycle settles the popover one such unit higher (726.40625 to 726.390625)
    # and six more cycles leave it there, so it is rounding, not drift. Compared to a unit, not exactly.
    assert rects(page)["pop"] == pytest.approx(before, abs=1 / 64 + 1e-6)
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
    tab.page.wait_for_selector(POP + " textarea")      # a mouse selection opens the box by itself
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


def test_the_thread_stays_readable_above_the_reply_field_in_a_short_frame(touch_tab):
    """A reply to a comment in a frame 320 px high (the page in an embedding app, its keyboard up): the popover is
    in the text, not docked, and its height is capped. The field and the buttons took all of it and squeezed the
    comment to a sliver (its author line cut through by the field, its text out of sight). The thread keeps a
    comment's worth of room, and the popover scrolls instead."""
    from sheafmd import comments as rdc
    from sheafmd.source import update_file
    site = touch_tab.site
    site.file.write_text(MD, encoding="utf-8")
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "Second paragraph"), "Second paragraph",
                                                     "Nearly good, only a pity about my name.", "Ada", "2026-10-25T21:01")[0])
    page = touch_tab.open().page
    page.set_viewport_size({"width": 390, "height": 320})
    page.click(".rd-badge")
    page.wait_for_selector(POP + " textarea")
    got = page.evaluate("""() => { const p = document.querySelector('#rd-popover'), r = (e) => e.getBoundingClientRect();
        const s = p.querySelector('.rd-scroll'), m = s.querySelector('.rd-msg'), t = p.querySelector('textarea');
        return { scroll: [r(s).top, r(s).bottom], field: [r(t).top, r(t).bottom], msg: r(m).height,
                 shown: s.clientHeight, content: s.scrollHeight, pop: r(p).height, scrolls: p.scrollHeight > p.clientHeight }; }""")
    assert got["shown"] >= got["content"], got       # the whole thread (one comment) is in view
    assert got["scroll"][1] <= got["field"][0] + 0.5, got   # and the field starts below it


def test_a_long_thread_leaves_the_field_in_reach_above_the_keyboard(phone):
    """The thread gives way to the form, down to its floor: with a long comment and the keyboard up, the field and
    its buttons are still inside the docked popover and above the keyboard."""
    from sheafmd import comments as rdc
    from sheafmd.source import update_file
    update_file(phone.site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "Second paragraph"), "Second paragraph",
                                                           "Nearly good, only a pity about my name. " * 20, "Ada", "2026-10-25T21:01")[0])
    page = phone.open().page
    page.click(".rd-badge")
    page.wait_for_selector(POP + " textarea")
    page.focus(POP + " textarea")
    keyboard(page, 450)
    got = rects(page)
    assert got["pop"][3] <= 450 - ACCESSORY, got
    assert got["field"][1] >= got["pop"][1] and got["field"][3] <= got["pop"][3], got
    assert all(b[3] <= got["pop"][3] for b in got["buttons"]), got


def test_a_short_thread_is_not_stretched_to_the_floor(touch_tab):
    """The floor only stops the thread giving way further; a thread shorter than it keeps the height it has."""
    from sheafmd import comments as rdc
    from sheafmd.source import update_file
    site = touch_tab.site
    site.file.write_text(MD, encoding="utf-8")
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "Second paragraph"), "Second paragraph",
                                                     "Short.", "Ada", "2026-10-25T21:01")[0])
    page = touch_tab.open().page
    page.click(".rd-badge")
    page.wait_for_selector(POP + " .rd-scroll")
    got = page.evaluate("(() => { const s = document.querySelector('#rd-popover .rd-scroll'); return [s.clientHeight, s.scrollHeight]; })()")
    assert got[0] == got[1] and got[0] < 84, got


def test_the_thread_floor_follows_the_width_the_thread_wraps_at(touch_tab):
    """A thread that is one line wide and three lines narrow: the floor is measured again when the frame is resized
    (a phone turned, an embedding frame resized), not kept from the first width."""
    from sheafmd import comments as rdc
    from sheafmd.source import update_file
    site = touch_tab.site
    site.file.write_text(MD, encoding="utf-8")
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "Second paragraph"), "Second paragraph",
                                                     "Nearly good, only a pity about my name.", "Ada", "2026-10-25T21:01")[0])
    page = touch_tab.open().page
    page.click(".rd-badge")
    page.wait_for_selector(POP + " .rd-scroll")
    page.set_viewport_size({"width": 230, "height": 844})
    page.wait_for_timeout(300)
    got = page.evaluate("""(() => { const s = document.querySelector('#rd-popover .rd-scroll');
        const m = [...s.querySelectorAll('.rd-msg')].pop();
        return [parseFloat(s.style.minHeight), Math.min(s.scrollHeight, Math.max(84, Math.min(m.offsetHeight + 8, 160)))]; })()""")
    assert abs(got[0] - got[1]) < 1 and got[1] > 80, got


def test_the_thread_floor_follows_a_resize_with_a_mouse_too(tab):
    """The same, on a page with no touch screen (an embedding frame narrowed on a desktop)."""
    from sheafmd import comments as rdc
    from sheafmd.source import update_file
    tab.site.file.write_text(MD, encoding="utf-8")
    update_file(tab.site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "Second paragraph"), "Second paragraph",
                                                         "Nearly good, only a pity about my name.", "Ada", "2026-10-25T21:01")[0])
    page = tab.open().page
    page.click(".rd-badge")
    page.wait_for_selector(POP + " .rd-scroll")
    page.set_viewport_size({"width": 230, "height": 844})
    page.wait_for_timeout(300)
    got = page.evaluate("""(() => { const s = document.querySelector('#rd-popover .rd-scroll');
        const m = [...s.querySelectorAll('.rd-msg')].pop();
        return [parseFloat(s.style.minHeight), Math.min(s.scrollHeight, Math.max(84, Math.min(m.offsetHeight + 8, 160)))]; })()""")
    assert abs(got[0] - got[1]) < 1 and got[1] > 80, got
