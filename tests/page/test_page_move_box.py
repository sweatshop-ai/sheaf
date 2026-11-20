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
