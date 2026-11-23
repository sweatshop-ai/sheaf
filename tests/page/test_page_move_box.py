"""The comment box is moved by its band (ticket 174): a drag with a mouse or a finger, the box inside the screen, kept where it
was dropped while it is open, placed as usual at the next open."""
import pytest

from pagehelp import until

pytestmark = pytest.mark.page

FIELD = "#rd-popover textarea"
BOX = "#rd-popover"
BAND = "#rd-popover .rd-head .rd-quote"


def open_thread(tab):
    """A comment of Bea's on the page, its thread open."""
    from pagehelp import open_with_comment
    open_with_comment(tab, None, "apples", "Why?", "Bea")
    tab.page.click(".rd-badge")
    tab.page.wait_for_selector(FIELD)
    return tab.page


def rect(p, sel=BOX):
    return p.locator(sel).bounding_box()


def drag(p, dx, dy, sel=BAND):
    """Press in the middle of `sel`, move by (dx, dy) in steps, release."""
    b = rect(p, sel)
    x, y = b["x"] + b["width"] / 2, b["y"] + b["height"] / 2
    p.mouse.move(x, y)
    p.mouse.down()
    for i in range(1, 9):
        p.mouse.move(x + dx * i / 8, y + dy * i / 8)
    p.mouse.up()


def test_a_drag_by_the_band_moves_the_box(tab, site):
    p = open_thread(tab)
    before = rect(p)
    drag(p, -60, 40)
    after = rect(p)
    assert abs(after["x"] - (before["x"] - 60)) < 2 and abs(after["y"] - (before["y"] + 40)) < 2, (before, after)


def test_the_band_has_a_move_cursor_and_its_buttons_keep_theirs(tab, site):
    p = open_thread(tab)
    cursor = "(s) => getComputedStyle(document.querySelector(s)).cursor"
    assert p.evaluate(cursor, ".rd-head") == "move"
    assert p.evaluate(cursor, ".rd-head button[title=Close]") == "pointer"


def test_the_box_stays_inside_the_screen(tab, site):
    p = open_thread(tab)
    size = p.evaluate("({w: document.documentElement.clientWidth, h: window.innerHeight})")
    drag(p, 5000, 5000)
    b = rect(p)
    assert b["x"] + b["width"] <= size["w"] and b["y"] + b["height"] <= size["h"], (b, size)
    drag(p, -5000, -5000)
    b = rect(p)
    assert b["x"] >= 0 and b["y"] >= 0, b


def test_a_press_on_a_band_button_is_a_click_and_starts_no_drag(tab, site):
    p = open_thread(tab)
    before = rect(p)
    drag(p, 80, 80, sel=".rd-head button[title=Resolve]")
    assert rect(p) == before
    p.click(".rd-head button[title=Close]")
    until(lambda: p.locator(BOX).count() == 0, what="the box closed by its button")


def test_a_drag_selects_no_text_and_offers_no_comment_button(tab, site):
    p = open_thread(tab)
    drag(p, -100, 60)
    assert p.evaluate("window.getSelection().toString()") == ""
    assert p.locator("#rd-comment-btn").count() == 0 or not p.locator("#rd-comment-btn").is_visible()


def test_the_box_keeps_its_place_when_a_reply_arrives(tab, site):
    p = open_thread(tab)
    drag(p, -60, 70)
    before = rect(p)
    p.fill(FIELD, "Because.")
    p.keyboard.press("Enter")
    until(lambda: p.locator("#rd-popover .rd-msg").count() == 2, what="the reply in the thread")
    after = rect(p)
    assert abs(after["x"] - before["x"]) < 2 and abs(after["y"] - before["y"]) < 2, (before, after)


def test_the_next_open_places_the_box_as_usual(tab, site):
    p = open_thread(tab)
    first = rect(p)
    drag(p, -60, 70)
    p.click(".rd-head button[title=Close]")
    p.click(".rd-badge")
    p.wait_for_selector(FIELD)
    again = rect(p)
    assert abs(again["x"] - first["x"]) < 2 and abs(again["y"] - first["y"]) < 2, (first, again)


# ── Ticket 183 X: a moved box is held inside the visible area again ─────────────────────────────────────────────────────────

def inside(p, b):
    size = p.evaluate("({w: document.documentElement.clientWidth, h: window.innerHeight})")
    return b["x"] >= 0 and b["y"] >= 0 and b["x"] + b["width"] <= size["w"] and b["y"] + b["height"] <= size["h"], (b, size)


def test_a_box_moved_to_the_lower_right_is_inside_the_window_after_it_shrinks(tab, site):
    p = open_thread(tab)
    drag(p, 5000, 5000)
    size = p.viewport_size
    p.set_viewport_size({"width": size["width"] - 200, "height": size["height"] - 200})
    until(lambda: inside(p, rect(p))[0], what="the moved box back inside the smaller window")


def test_a_box_dropped_inside_the_smaller_window_does_not_move_when_it_shrinks(tab, site):
    p = open_thread(tab)
    drag(p, -60, 40)
    before = rect(p)
    size = p.viewport_size
    p.set_viewport_size({"width": size["width"] - 20, "height": size["height"] - 20})
    p.evaluate("new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")
    assert inside(p, before)[0], "the test's own premise: the box lies inside the smaller window"
    after = rect(p)
    assert abs(after["x"] - before["x"]) < 2 and abs(after["y"] - before["y"]) < 2, (before, after)


def test_a_box_moved_to_the_foot_that_grows_with_a_reply_keeps_its_controls_in_view(tab, site):
    p = open_thread(tab)
    drag(p, 0, 5000)
    before = rect(p)
    p.fill(FIELD, "Because.\n\nAnd a second paragraph.\n\nAnd a third one, so that the box grows.")
    p.keyboard.press("Enter")
    until(lambda: p.locator("#rd-popover .rd-msg").count() == 2, what="the reply in the thread")
    until(lambda: rect(p)["height"] > before["height"], what="the box taller with the reply")
    until(lambda: inside(p, rect(p))[0], what="the grown box inside the window")
