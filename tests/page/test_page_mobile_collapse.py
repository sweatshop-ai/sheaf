"""On Thierry's iPhone (trial of 2026-11-10) a focus() made in the pointerup of a long-press release raised the keyboard and the field
stayed the active element, but iOS fired one more selectionchange 1 to 7 ms later and the page's words were selected again: the
cursor was not in the box. A box opened by a touch takes that selection away and puts the caret at the end of its field. Emulation
cannot make the selection come back by itself, so the tests fire it."""
import pytest

from pagehelp import at, select_by_touch
from test_page_selection import MAIN, PLAN_MD, TOUCH_END, TOUCH_START, FIELD

pytestmark = pytest.mark.page

SELECT_AGAIN = """() => { const w = document.createTreeWalker(document.querySelector('main'), NodeFilter.SHOW_TEXT);
  let n; while ((n = w.nextNode()) && !n.nodeValue.includes('pears'));
  const r = document.createRange(); r.setStart(n, 0); r.setEnd(n, 6);
  getSelection().removeAllRanges(); getSelection().addRange(r); }"""
STATE = """() => { const t = document.querySelector('#rd-popover textarea'), s = getSelection();
  return {collapsed: s.isCollapsed, active: document.activeElement.tagName, from: t.selectionStart, to: t.selectionEnd, len: t.value.length,
          marked: [...(CSS.highlights.get('rd-widened') || [])].map(String)}; }"""


@pytest.fixture
def phone(touch_tab, site):
    site.file.write_text(PLAN_MD, encoding="utf-8")
    return touch_tab.open()


def opened_by_touchend(p):
    p.evaluate(TOUCH_START)
    select_by_touch(p, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    got = p.evaluate(TOUCH_END)
    assert got == {"box": True, "active": "TEXTAREA"}, got


def test_the_page_words_selected_again_after_the_open_are_let_go_and_the_caret_stands_at_the_end_of_the_field(phone):
    p = phone.page
    opened_by_touchend(p)
    p.evaluate("""() => { const t = document.querySelector('#rd-popover textarea'); t.value = 'abc'; t.setSelectionRange(0, 0); }""")
    p.evaluate(SELECT_AGAIN)            # what iOS does a few ms after the release
    p.wait_for_timeout(200)
    got = p.evaluate(STATE)
    assert got["collapsed"] is True, "the page's words stayed selected beside the field"
    assert (got["active"], got["from"], got["to"]) == ("TEXTAREA", 3, 3), got
    assert got["marked"] == ["Second paragraph"], "the passage is no longer marked"


def test_a_finger_still_down_after_the_selection_appeared_opens_nothing_until_its_release_and_the_release_opens_it_with_the_cursor(phone):
    """Trial of 2026-11-10: a long press followed by a slide kept the finger down past the 600 ms settle; the timer opened the box and
    cut the selection under the moving finger, outside any gesture. The release is the page's moment."""
    p = phone.page
    p.evaluate(TOUCH_START)
    select_by_touch(p, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    p.wait_for_timeout(1000)            # well past the settle (600 ms on a phone), finger still down
    assert p.locator("#rd-popover").count() == 0, "the timer opened the box under a finger that was still down"
    got = p.evaluate(TOUCH_END)
    assert got == {"box": True, "active": "TEXTAREA"}, got


def test_a_touch_cancelled_before_the_selection_is_not_a_finger_down_and_the_settle_opens_the_box(phone):
    p = phone.page
    p.evaluate(TOUCH_START)
    p.evaluate("document.dispatchEvent(new TouchEvent('touchcancel', {bubbles: true}))")     # the finger is gone, no touchend
    select_by_touch(p, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    p.wait_for_selector(FIELD, timeout=5000)     # the settle (600 ms) opens it, well before the 10 s ceiling


def test_a_touch_that_never_ended_stops_holding_the_settle_after_ten_seconds(phone):
    """No touchend and no touchcancel reached the page (restated 2026-11-10: the old test fired a touchcancel, so the ceiling was never reached)."""
    p = phone.page
    p.evaluate(TOUCH_START)
    p.wait_for_timeout(10300)                    # the touch start is older than FINGER_MAX_MS and nothing ended it
    select_by_touch(p, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    p.wait_for_selector(FIELD, timeout=5000)     # the settle opens it; a finger still counting would hold it back


def test_a_selection_of_the_page_long_after_the_open_is_left_alone(phone):
    p = phone.page
    opened_by_touchend(p)
    p.wait_for_timeout(1400)            # past the window in which the open's own selection comes back
    p.evaluate(SELECT_AGAIN)
    p.wait_for_timeout(900)
    assert p.evaluate(STATE)["collapsed"] is False, "a later selection was taken away"
