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

def inside_window(p, b):
    """(whether the box `b` lies inside the window, what was compared): the second part is for the failure message."""
    size = p.evaluate("({w: document.documentElement.clientWidth, h: window.innerHeight})")
    return b["x"] >= 0 and b["y"] >= 0 and b["x"] + b["width"] <= size["w"] and b["y"] + b["height"] <= size["h"], (b, size)


def test_a_box_moved_to_the_lower_right_is_inside_the_window_after_it_shrinks(tab, site):
    p = open_thread(tab)
    drag(p, 5000, 5000)
    size = p.viewport_size
    p.set_viewport_size({"width": size["width"] - 200, "height": size["height"] - 200})
    until(lambda: inside_window(p, rect(p))[0], what="the moved box back inside the smaller window")


def test_a_box_dropped_inside_the_smaller_window_does_not_move_when_it_shrinks(tab, site):
    p = open_thread(tab)
    drag(p, -60, 40)
    before = rect(p)
    size = p.viewport_size
    p.set_viewport_size({"width": size["width"] - 20, "height": size["height"] - 20})
    p.evaluate("new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")
    assert inside_window(p, before)[0], "the test's own premise: the box lies inside the smaller window"
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
    until(lambda: inside_window(p, rect(p))[0], what="the grown box inside the window")


def test_a_box_held_at_the_foot_of_a_short_page_keeps_its_edge_when_the_page_shrinks_again(tab, site):
    """The box is the lowest part of the fixture's short page: when it shrinks again (the line "being sent" goes), the page
    ends higher and the browser scrolls up to that end. The box keeps its edge (MOVE_EDGE, 8 px) above the window's foot
    instead of ending flush with it, where a fraction of a pixel puts it outside."""
    p = open_thread(tab)
    drag(p, 0, 5000)
    before = rect(p)
    p.fill(FIELD, "Because.\n\nAnd a second paragraph.\n\nAnd a third one, so that the box grows.")
    p.keyboard.press("Enter")
    until(lambda: p.locator("#rd-popover .rd-msg").count() == 2, what="the reply in the thread")
    until(lambda: rect(p)["height"] > before["height"], what="the box taller with the reply")
    p.wait_for_timeout(500)                 # the line "being sent" gone, the page scrolled to its new end
    foot = p.evaluate("window.innerHeight")
    b = rect(p)
    assert b["y"] + b["height"] <= foot - 8 + 0.5, (b, foot)


# ── Ticket 183 BN, BO, BP: a box scrolled out of view, the observer of a closed box, the room under a moved box ──────────────

LONG = "# Plan\n\nA paragraph about apples.\n\n" + "".join(f"Paragraph {i} of the long page, to scroll past.\n\n" for i in range(80))


def open_long_thread(tab):
    """The thread on `apples` open at the head of a page long enough to scroll the box out of view."""
    from pagehelp import open_with_comment
    open_with_comment(tab, LONG, "apples", "Why?", "Bea")
    tab.page.click(".rd-badge")
    tab.page.wait_for_selector(FIELD)
    return tab.page


def page_place(p):
    """The box's place in the page (not on the screen): what a scroll leaves as it is."""
    return p.evaluate("(() => { const b = document.querySelector('#rd-popover'); return [b.offsetLeft, b.offsetTop]; })()")


def frames(p):
    p.evaluate("new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)))")


def room_under_box(p):
    """(whether the empty room lies right under the box, what was measured)."""
    got = p.evaluate("""(() => { const b = document.querySelector('#rd-popover'), r = document.querySelector('.rd-room');
        return r && { follows: r.previousSibling === b, top: parseFloat(r.style.top), foot: b.offsetTop + b.offsetHeight,
                      height: parseFloat(r.style.height) }; })()""")
    return bool(got) and got["follows"] and abs(got["top"] - got["foot"]) < 1 and got["height"] == 8, got


@pytest.mark.parametrize("change", [60, -60], ids=["url-bar-hidden", "url-bar-shown"])
def test_a_box_scrolled_out_of_view_stays_where_it_was_dropped_when_the_window_height_changes(tab, site, change):
    """183 BN: a phone's URL bar that hides or shows changes the window's height while the reader scrolls. A box the reader
    scrolled out of view with the text was pulled back into view by it."""
    p = open_long_thread(tab)
    drag(p, -60, 40)
    before = page_place(p)
    p.evaluate("window.scrollTo(0, 2000)")
    frames(p)
    assert rect(p)["y"] + rect(p)["height"] <= 0, "the test's own premise: the box lies above the window"
    size = p.viewport_size
    p.set_viewport_size({"width": size["width"], "height": size["height"] + change})
    frames(p)
    p.wait_for_timeout(100)
    assert page_place(p) == before


def test_a_box_inside_the_window_is_still_held_inside_when_the_window_shrinks_on_a_long_page(tab, site):
    """183 BN's other side: the box lay inside the window before it shrank, and wholly past its new foot after."""
    p = open_long_thread(tab)
    drag(p, 0, 5000)
    size = p.viewport_size
    p.set_viewport_size({"width": size["width"], "height": size["height"] - 400})
    until(lambda: inside_window(p, rect(p))[0], what="the moved box back inside the smaller window")


def test_a_closed_moved_box_is_no_longer_observed(tab, site):
    """183 BO: the observer set on the first drag is let go with the box, which it otherwise keeps in memory."""
    tab.page.add_init_script("""(() => {
      const RO = window.ResizeObserver;
      window.__boxObservers = [];
      window.ResizeObserver = class extends RO {
        observe(el, o) { if (el.id === 'rd-popover') window.__boxObservers.push(this); this.__on = true; return super.observe(el, o); }
        disconnect() { this.__on = false; return super.disconnect(); }
      };
    })()""")
    p = open_thread(tab)
    drag(p, -60, 40)
    assert p.evaluate("window.__boxObservers.length") == 1
    p.click(".rd-head button[title=Close]")
    until(lambda: p.locator(BOX).count() == 0, what="the box closed by its button")
    assert p.evaluate("window.__boxObservers.map((o) => o.__on)") == [False]


def test_the_room_follows_a_box_scrolled_out_of_view_that_changes_size(tab, site):
    """183 BP: a box the reader scrolled away is left where it was dropped when it grows, and the room under it moves to its
    new foot. The box grows by a part added to its thread: a reply sent from the field scrolls the page back to it."""
    p = open_long_thread(tab)
    drag(p, -60, 40)
    before = page_place(p)
    height = rect(p)["height"]
    p.evaluate("window.scrollTo(0, 2000)")
    frames(p)
    p.evaluate("""(() => { const d = document.createElement('div'); d.style.height = '120px';
        document.querySelector('#rd-popover .rd-msg').append(d); })()""")
    until(lambda: rect(p)["height"] > height, what="the box taller")
    frames(p)
    assert p.evaluate("window.scrollY") == 2000, "the test's own premise: the box is still scrolled away"
    assert page_place(p) == before
    ok, got = room_under_box(p)
    assert ok, got
