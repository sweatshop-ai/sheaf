"""A plain task line's label ticks its box (SPEC 10.11, action-buttons 02): the words before the first `:` or ` — `,
else the first word, tick or untick it like a <label>; the rest of the line is ordinary text."""
import pytest

from pagehelp import mark, open_box, until

pytestmark = pytest.mark.page

SHEAF = """# Plan

- [ ] Approved: the quote of 12 November
- [ ] Ordered — the quote of 14 November
- [ ] Plain words here

Body paragraph.
"""
ON = "- [x] Approved: the quote of 12 November"
OFF = "- [ ] Approved: the quote of 12 November"

# The middle of the characters of the item's text from `start` to `end`, as the page draws them.
SPOT = """([sel, start, end]) => {
  const li = document.querySelector(sel);
  const w = document.createTreeWalker(li, NodeFilter.SHOW_TEXT);
  const r = document.createRange();
  let n, at = 0, set = 0;
  while ((n = w.nextNode())) {
    for (const [pos, side] of [[start, 0], [end, 1]]) {
      if (pos >= at && pos <= at + n.data.length && set === side) {
        if (side === 0) r.setStart(n, pos - at); else r.setEnd(n, pos - at);
        set++;
      }
    }
    at += n.data.length;
  }
  const q = r.getBoundingClientRect();
  return [q.left + q.width / 2, q.top + q.height / 2, q.left, q.top + q.height / 2, q.right, q.height];
}"""
ITEM = "main li:nth-of-type(1)"


def spot(p, start, end, sel=ITEM):
    return p.evaluate(SPOT, [sel, start, end])


@pytest.fixture
def sheaf(tab):
    tab.site.file.write_text(SHEAF, encoding="utf-8")
    tab.open()
    tab.page.wait_for_selector("main input[type=checkbox]")
    return tab


def test_a_click_on_the_label_ticks_and_a_second_click_unticks(sheaf):
    p, f = sheaf.page, sheaf.site.file
    x, y = spot(p, 0, len("Approved"))[:2]
    mark(p)
    p.mouse.click(x, y)
    until(lambda: ON in f.read_text(encoding="utf-8"), what="the tick in the file")
    assert p.locator("main input[type=checkbox]").first.is_checked()
    mark(p)
    p.mouse.click(x, y)
    until(lambda: OFF in f.read_text(encoding="utf-8"), what="the untick in the file")


def test_the_label_of_a_line_with_a_dash_is_the_words_before_it(sheaf):
    p, f = sheaf.page, sheaf.site.file
    x, y = spot(p, 0, len("Ordered"), "main li:nth-of-type(2)")[:2]
    mark(p)
    p.mouse.click(x, y)
    until(lambda: "- [x] Ordered — the quote" in f.read_text(encoding="utf-8"), what="the tick in the file")


def test_the_label_of_a_line_with_no_colon_is_its_first_word(sheaf):
    p, f = sheaf.page, sheaf.site.file
    x, y = spot(p, 0, len("Plain"), "main li:nth-of-type(3)")[:2]
    mark(p)
    p.mouse.click(x, y)
    until(lambda: "- [x] Plain words here" in f.read_text(encoding="utf-8"), what="the tick in the file")


def test_a_click_on_the_rest_of_the_line_ticks_nothing(sheaf):
    p, f = sheaf.page, sheaf.site.file
    start = len("Approved: the ")
    x, y = spot(p, start, start + len("quote"))[:2]
    p.mouse.click(x, y)
    p.wait_for_timeout(600)
    assert f.read_text(encoding="utf-8") == SHEAF
    assert p.locator("main input[type=checkbox]").first.is_checked() is False


def test_a_drag_selection_from_the_label_opens_the_chat_box_and_ticks_nothing(sheaf):
    p, f = sheaf.page, sheaf.site.file
    x0, y0 = spot(p, 0, 1)[2:4]
    x1, y1 = spot(p, len("Approved: the quote"), len("Approved: the quote"))[2:4]
    p.mouse.move(x0 + 1, y0)
    p.mouse.down()
    p.mouse.move(x1, y1, steps=8)
    p.mouse.up()
    open_box(p)
    assert p.locator("#rd-popover textarea").is_visible()
    assert f.read_text(encoding="utf-8") == SHEAF


def test_on_a_phone_the_label_is_44_px_high_to_touch(touch_tab):
    t = touch_tab
    t.site.file.write_text(SHEAF, encoding="utf-8")
    t.open()
    p, f = t.page, t.site.file
    p.wait_for_selector("main input[type=checkbox]")
    x, y, _, _, _, h = spot(p, 0, len("Approved"))
    assert h < 44
    p.touchscreen.tap(x, y + 20)           # 20 px under the middle of a line that is under 30 px high
    until(lambda: ON in f.read_text(encoding="utf-8"), what="the tick in the file")
