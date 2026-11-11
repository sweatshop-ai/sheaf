"""The touch path on the mounted page: page.js runs in a closed shadow root there, where `document.activeElement` is the host and
only `root.activeElement` is the field. The standalone page's touch tests (test_page_mobile_collapse.py) cannot see that difference."""
import pytest
from pagehelp import PAGE_TIMEOUT_MS, close_context, new_context, until
from test_mount_page import Front

pytestmark = pytest.mark.page

SELECT = """const [from, to] = arg;
  const w = document.createTreeWalker(root.querySelector('main'), NodeFilter.SHOW_TEXT);
  let n; while ((n = w.nextNode()) && !n.data.includes(from));
  const r = new Range(); r.setStart(n, n.data.indexOf(from)); r.setEnd(n, n.data.indexOf(from) + to);
  getSelection().removeAllRanges(); getSelection().addRange(r);"""
TOUCH = "document.dispatchEvent(new TouchEvent(arg, {bubbles: true, cancelable: true, composed: true}));"


@pytest.fixture
def phone_front(chromium, site):
    c = new_context(chromium, viewport={"width": 390, "height": 844}, has_touch=True, is_mobile=True,
                    user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) Mobile/15E148")
    c.set_default_timeout(PAGE_TIMEOUT_MS)
    c.add_cookies([site.cookie()])
    f = Front(c.new_page(), site)
    yield f
    try:
        assert f.errors == [], "the page raised script errors"
    finally:
        close_context(c)


def test_on_the_mounted_page_the_page_words_selected_again_after_a_touch_opened_the_box_are_let_go_and_the_caret_goes_to_the_end(phone_front):
    f = phone_front.open()
    f.js(TOUCH, "touchstart")
    f.js(SELECT, ["pears", 5])
    f.js(TOUCH, "touchend")
    until(lambda: f.has("#rd-popover textarea"), what="the box, opened by the release")
    assert f.js("return root.activeElement && root.activeElement.tagName;") == "TEXTAREA"
    f.js("const t = root.querySelector('#rd-popover textarea'); t.value = 'abc'; t.setSelectionRange(0, 0);")
    f.js(SELECT, ["pears", 5])                  # what iOS does a few ms after the release
    f.page.wait_for_timeout(200)
    assert f.js("const t = root.querySelector('#rd-popover textarea'); return [t.selectionStart, t.selectionEnd];") == [3, 3]


TAP = """const [id] = arg;
  const el = id === 'main' ? root.querySelector('main') : root.getElementById(id);
  const r = el.getBoundingClientRect();
  const touch = new Touch({identifier: 1, target: el, clientX: r.left + 2, clientY: r.top + 2});
  const fire = (type, touches) => el.dispatchEvent(new TouchEvent(type, {bubbles: true, cancelable: true, composed: true,
                                    touches, targetTouches: touches, changedTouches: [touch]}));
  fire('touchstart', [touch]);
  fire('touchend', []);"""


def box_open_with_the_cursor_gone(f):
    f.js(TOUCH, "touchstart")
    f.js(SELECT, ["pears", 5])
    f.js(TOUCH, "touchend")
    until(lambda: f.has("#rd-popover textarea"), what="the box, opened by the release")
    f.page.wait_for_timeout(300)          # past what the opening touch does to the field
    f.js("root.activeElement && root.activeElement.blur(); getSelection().removeAllRanges();")
    assert f.js("return root.activeElement && root.activeElement.tagName;") != "TEXTAREA"


def test_on_the_mounted_page_a_tap_in_the_empty_area_of_the_box_puts_the_cursor_in_the_field(phone_front):
    f = phone_front.open()
    box_open_with_the_cursor_gone(f)
    f.js(TAP, ["rd-popover"])
    assert f.js("return root.activeElement && root.activeElement.tagName;") == "TEXTAREA"


def test_on_the_mounted_page_a_tap_outside_the_box_focuses_nothing(phone_front):
    f = phone_front.open()
    box_open_with_the_cursor_gone(f)
    f.js(TAP, ["main"])
    assert f.js("return root.activeElement && root.activeElement.tagName;") != "TEXTAREA"
