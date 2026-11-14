"""Share is a tick box on the page (SPEC 10.11, action-buttons 03): `- [ ] Shared with the team`, or the older
`- [ ] Share`, is drawn as a checkbox where its line is, and its label, the whole line, ticks and unticks it. No button
in a row above the document; the press is sent at once (the hub's `/_/tick`, 9.11), refused to a member who is not the
sheaf's owner."""
import pytest

from helpers import BEA
from pagehelp import mark, toast, until
from sheafmd.hub import proxy

pytestmark = pytest.mark.page

SHEAF = """# Plan

- [ ] Approve
- [ ] Shared with the team

Body paragraph.
"""
OLD = SHEAF.replace("Shared with the team", "Share")

# The middle of the words of the item whose text holds `needle`, as the page draws them.
SPOT = """(needle) => {
  const li = [...document.querySelectorAll('main li')].find(x => x.textContent.includes(needle));
  const w = document.createTreeWalker(li, NodeFilter.SHOW_TEXT);
  const r = document.createRange();
  let n, first = null, last = null;
  while ((n = w.nextNode())) { if (!n.data.trim()) continue; first = first || n; last = n; }
  r.setStart(first, first.data.search(/\\S/)); r.setEnd(last, last.data.length);
  const q = r.getBoundingClientRect();
  return [q.left + 3, q.top + q.height / 2, q.right - 3];
}"""


@pytest.fixture
def opened(tab):
    def open_with(text):
        tab.site.file.write_text(text, encoding="utf-8")
        tab.open()
        tab.page.wait_for_selector("button.rd-act")         # Approve's button; its own box is hidden behind it
        share_box(tab.page).wait_for()
        return tab
    return open_with


def share_box(p):
    return p.locator("main li:has-text('Approve') ~ li input[type=checkbox]")


def test_share_is_a_visible_tick_box_and_there_is_no_row_of_buttons_above_the_document(opened):
    p = opened(SHEAF).page
    assert share_box(p).is_visible() and share_box(p).is_enabled()
    assert p.locator("#rd-actions").count() == 0
    assert p.locator("button.rd-act.toggle").count() == 0
    assert p.locator("button.rd-act").count() == 1, "only Approve is a button"


def test_a_click_on_any_of_the_words_of_the_label_ticks_share_and_a_second_click_unticks_it(opened):
    t = opened(SHEAF)
    p, f = t.page, t.site.file
    left, y, right = p.evaluate(SPOT, "Shared with the team")
    p.mouse.click(right, y)                     # the last word, not the first: the label is the whole line
    until(lambda: "- [x] Shared with the team" in f.read_text(encoding="utf-8"), what="the tick in the file")
    until(lambda: share_box(p).is_checked(), what="the box ticked on the page")
    assert "- [ ] Approve" in f.read_text(encoding="utf-8")
    p.mouse.click(left, y)
    until(lambda: "- [ ] Shared with the team" in f.read_text(encoding="utf-8"), what="the untick in the file")
    until(lambda: not share_box(p).is_checked(), what="the box unticked on the page")


def test_a_click_on_the_box_itself_ticks_share_at_once_without_an_undo(opened):
    t = opened(SHEAF)
    p, f = t.page, t.site.file
    share_box(p).click()
    until(lambda: "- [x] Shared with the team" in f.read_text(encoding="utf-8"), timeout=3, what="the tick, no 5 s wait")


def test_the_older_share_line_works_the_same_way(opened):
    t = opened(OLD)
    p, f = t.page, t.site.file
    share_box(p).click()
    until(lambda: "- [x] Share\n" in f.read_text(encoding="utf-8"), what="the tick of the older line")
    until(lambda: share_box(p).is_checked(), what="the box ticked on the page")
    share_box(p).click()
    until(lambda: "- [ ] Share\n" in f.read_text(encoding="utf-8"), what="the untick of the older line")
    assert "Shared with the team" not in f.read_text(encoding="utf-8")


def test_a_click_on_a_box_of_another_word_still_says_to_press_its_button(opened):
    t = opened(SHEAF)
    p, f = t.page, t.site.file
    p.locator("main input[type=checkbox]").first.dispatch_event("click")
    until(lambda: "with its button" in toast(p), what="the line that points to the button")
    assert f.read_text(encoding="utf-8") == SHEAF


def test_a_member_who_is_not_the_owner_is_told_so_and_nothing_is_written(tab, site, work):
    bea = proxy.Member(BEA, "Bea", (str(work),))
    real = site.hub.page
    site.hub.page = lambda e, nonce, member=None: real(e, nonce, member=bea)
    site.file.write_text(SHEAF, encoding="utf-8")
    tab.open()
    tab.page.wait_for_selector("button.rd-act")
    share_box(tab.page).wait_for()
    mark(tab.page)
    share_box(tab.page).click()
    until(lambda: "Only the owner of this sheaf can share it." in toast(tab.page), what="the refusal")
    tab.page.wait_for_timeout(300)
    assert site.file.read_text(encoding="utf-8") == SHEAF
    assert not share_box(tab.page).is_checked()
