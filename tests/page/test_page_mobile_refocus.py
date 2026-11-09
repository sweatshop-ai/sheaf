"""iOS may not raise the keyboard after a selection (ticket 03, Thierry's phone trial 2026-11-09), so a box that is open with its field
unfocused takes the cursor on one touch in its empty area (band, thread background, composer frame), inside that touch's own event.
A control keeps its meaning (×, −, ⋯, a link), a bubble and its selected text are content, and a scroll is not a tap."""
import pytest

from pagehelp import at, select_by_touch, until
from sheafmd import comments as rdc
from sheafmd.source import update_file

pytestmark = pytest.mark.page

FIELD = "#rd-popover textarea"
MAIN = "main"
PLAN_MD = "# Plan\n\nSecond paragraph, about pears.\n\nA third one, about apples.\n"


def focused(p):
    return p.evaluate("(() => { const a = document.activeElement; return a ? a.tagName + (a.id ? '#' + a.id : '') : null; })()")


def unfocus(p):
    p.evaluate("document.activeElement.blur()")
    assert focused(p) == "BODY"


@pytest.fixture
def thread(touch_tab, site):
    """A phone with a thread's box open (a number touched) and the cursor taken out of its field."""
    site.file.write_text(PLAN_MD, encoding="utf-8")
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "apples"), "apples",
                                                     "Why? See [the docs](https://example.invalid/docs) please.", "Ada", "2026-10-14T10:00")[0])
    p = touch_tab.open().page
    b = p.locator(".rd-badge").bounding_box()
    p.touchscreen.tap(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
    p.wait_for_selector(FIELD)
    unfocus(p)
    # What the page does at the end of a touch, as the end of that same event sees it (a focus made later would be too late
    # for the keyboard): the answer is read by a listener that runs after the page's own.
    p.evaluate("""(() => { window.__atTouchEnd = null;
      window.addEventListener('touchend', () => { window.__atTouchEnd = document.activeElement.tagName; }); })()""")
    return p


def spot(p, area):
    """A point where the finger is on that area and on no control or bubble: the box's own padding, the band's quote, the thread's
    right-hand padding, the composer frame's left edge. The point is checked to be under the element named."""
    css, where = area
    b = p.locator(css).first.bounding_box()
    pt = {"left": (b["x"] + 3, b["y"] + b["height"] / 2), "centre": (b["x"] + b["width"] / 2, b["y"] + b["height"] / 2),
          "right": (b["x"] + b["width"] - 3, b["y"] + b["height"] / 2)}[where]
    assert p.evaluate("([x, y, css]) => document.elementFromPoint(x, y) === document.querySelector(css)", [*pt, css]), \
        f"the point {pt} is not on {css} itself"
    return pt


AREAS = [("#rd-popover", "left"), ("#rd-popover .rd-quote", "centre"), ("#rd-popover .rd-scroll", "right"), ("#rd-popover .rd-form", "left")]


@pytest.mark.parametrize("area", AREAS, ids=lambda a: a[0])
def test_a_touch_in_the_empty_area_of_the_box_puts_the_cursor_in_the_field_in_that_touch(thread, area):
    p = thread
    p.touchscreen.tap(*spot(p, area))
    assert focused(p) == "TEXTAREA", f"a touch on {area[0]} left the cursor out of the field"
    if area[0].endswith(".rd-form"):
        return      # a finger beside the field is adjusted onto the field by the browser itself (Chromium targets the textarea here)
    assert p.evaluate("window.__atTouchEnd") == "TEXTAREA", "the cursor came after the touch's own event"


def test_a_touch_in_a_new_comment_box_does_the_same(touch_tab, site):
    site.file.write_text(PLAN_MD, encoding="utf-8")
    p = touch_tab.open().page
    select_by_touch(p, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    p.wait_for_selector(FIELD)
    unfocus(p)
    p.touchscreen.tap(*spot(p, ("#rd-popover", "left")))
    assert focused(p) == "TEXTAREA"


def test_a_control_keeps_its_own_meaning(thread):
    p = thread
    p.evaluate("document.querySelector('a[href^=\"https://example.invalid\"]').addEventListener('click', e => e.preventDefault())")
    for css in ["#rd-popover .rd-more summary", "#rd-popover a[href^='https://example.invalid']", "#rd-popover [data-a=status]"]:
        b = p.locator(css).first.bounding_box()
        p.touchscreen.tap(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
        assert focused(p) != "TEXTAREA", f"a touch on {css} took the cursor into the field"
        assert p.evaluate("window.__atTouchEnd") != "TEXTAREA"
    assert p.evaluate("document.querySelector('#rd-popover .rd-more').open") is True, "⋯ did not open its menu"
    b = p.locator("#rd-popover [data-a=minimize]").bounding_box()
    p.touchscreen.tap(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
    p.wait_for_selector("#rd-popover", state="detached")


def test_a_bubble_and_its_selected_text_are_content_not_empty_area(thread):
    p = thread
    b = p.locator("#rd-popover .rd-msg .rd-text").first.bounding_box()
    p.touchscreen.tap(b["x"] + 4, b["y"] + b["height"] / 2)
    assert focused(p) != "TEXTAREA", "a touch on a bubble took the cursor into the field"
    p.evaluate("""(() => { const t = document.querySelector('#rd-popover .rd-msg .rd-text'); const r = document.createRange();
      r.selectNodeContents(t); getSelection().removeAllRanges(); getSelection().addRange(r); })()""")
    unfocus(p)
    p.touchscreen.tap(b["x"] + 4, b["y"] + b["height"] / 2)
    assert focused(p) != "TEXTAREA", "a touch on selected text took the cursor into the field"


def test_scrolling_the_box_does_not_focus_the_field(thread):
    p = thread
    x, y = spot(p, ("#rd-popover", "left"))
    cdp = p.context.new_cdp_session(p)
    cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": x, "y": y + 40}]})
    for dy in (30, 15, 0, -15):
        cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [{"x": x, "y": y + dy}]})
    cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
    until(lambda: p.evaluate("window.__atTouchEnd") is not None, what="the end of the swipe")
    assert focused(p) != "TEXTAREA", "a scroll took the cursor into the field"


def test_a_field_that_has_the_cursor_is_left_alone_and_a_desktop_pointer_never_does_this(thread):
    p = thread
    p.focus(FIELD)
    p.keyboard.type("hello")
    p.touchscreen.tap(*spot(p, ("#rd-popover", "left")))
    assert p.input_value(FIELD) == "hello" and focused(p) == "TEXTAREA"


def test_selected_text_in_the_band_is_left_to_the_selection(thread):
    p = thread
    p.evaluate("""(() => { const t = document.querySelector('#rd-popover .rd-quote'); const r = document.createRange();
      r.selectNodeContents(t); getSelection().removeAllRanges(); getSelection().addRange(r); })()""")
    unfocus(p)
    p.touchscreen.tap(*spot(p, ("#rd-popover .rd-quote", "centre")))
    assert focused(p) != "TEXTAREA", "a touch on the band's selected text took the cursor into the field"
