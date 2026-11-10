"""Selecting text (SPEC 10.4, D24): a selection that ends inside a formatted run is widened to the
whole run and the comment lands after it; one that cannot hold a comment shows a disabled button
that says why, before the click."""
import pytest

from pagehelp import at, box, open_box, select, select_by_touch, selected, until
from sheafmd import comments as rdc

pytestmark = pytest.mark.page

PLAN_MD = """# Plan

Some **bold word** and a [link text](https://example.com/x) here.

Second paragraph, about pears.

- first item
- second item

| a | b |
|---|---|
| one | two |

```python
print("code")
```
"""

BOLD_P = "p:has(strong)"
MAIN = "main"           # the second paragraph's words are found by their text, under the page's one <main>
BTN = "#rd-comment-btn"
FIELD = "#rd-popover textarea"


@pytest.fixture
def doc(tab, site):
    site.file.write_text(PLAN_MD, encoding="utf-8")
    return tab.open()


def settled(page):
    """Wait out the 350 ms a selection must stand still before the page reacts to it."""
    page.wait_for_timeout(600)


def quoted(page):
    """The passage the open box quotes, without the quotation marks round it."""
    return page.inner_text("#rd-popover .rd-quote").strip("\u201c\u201d")


def comment_on_selection(tab, text="A thought."):
    """A mouse selection has opened the box by itself; a touch screen is offered the Comment bar first."""
    open_box(tab.page)
    tab.page.fill("#rd-popover textarea", text)
    tab.page.click("#rd-popover button[data-f=ok]")
    return until(lambda: rdc.parse(tab.site.file.read_text()).comments or None, what="the comment in the file")


def test_a_selection_ending_inside_a_bold_word_is_widened_and_the_comment_lands_after_it(doc):
    select(doc.page, at(BOLD_P, "Some "), at(BOLD_P + " strong", "bold word", 2))
    doc.page.wait_for_selector(FIELD)
    assert quoted(doc.page) == "Some bold word"
    (c,) = comment_on_selection(doc)
    md = doc.site.file.read_text()
    assert c.quote == "Some bold word"
    assert md[:md.index("<!--")].endswith("Some **bold word**")


def test_a_selection_starting_inside_a_bold_word_is_widened_too(doc):
    select(doc.page, at(BOLD_P + " strong", "bold word", 2), at(BOLD_P, " and a ", None))
    doc.page.wait_for_selector(FIELD)
    assert quoted(doc.page) == "bold word and a"
    (c,) = comment_on_selection(doc)
    assert c.quote == "bold word and a"


def test_a_selection_ending_inside_a_link_is_widened_and_the_comment_lands_after_it(doc):
    select(doc.page, at(BOLD_P, " and a "), at(BOLD_P + " a", "link text", 3))
    doc.page.wait_for_selector(FIELD)
    assert quoted(doc.page) == "and a link text"
    (c,) = comment_on_selection(doc)
    md = doc.site.file.read_text()
    assert c.quote == "and a link text"
    assert md[:md.index("<!--")].endswith("[link text](https://example.com/x)")


def test_a_selection_that_starts_after_a_bold_word_does_not_take_it_in(doc):
    select(doc.page, at(BOLD_P, " and a ", 1), at(BOLD_P + " a", "link text", 4))
    doc.page.wait_for_selector(FIELD)
    assert "bold" not in quoted(doc.page)


@pytest.mark.parametrize("start, end, reason", [
    (at("p:has(strong)", "here"), at("p:nth-of-type(3)", "pears", 2), "One paragraph at a time"),
    (at("ul", "first item"), at("ul", "second", 3), "One paragraph at a time"),
    (at("td", "one"), at("td:nth-of-type(2)", "two", 2), "One table cell at a time"),
    (at("pre", "print", 1), at("pre", "code", 2), "No comments in code, charts, images or raw HTML"),
    (at(".doc-by", "Document"), at(".doc-by", "prepared", 3), "This text is not in the .md"),
])
def test_a_selection_that_cannot_hold_a_comment_shows_a_disabled_button_with_its_reason(
        doc, start, end, reason):
    select(doc.page, start, end)
    btn = doc.page.wait_for_selector(BTN)
    assert btn.inner_text() == reason
    assert btn.is_disabled()
    btn.click(force=True)
    assert doc.page.query_selector("#rd-popover") is None
    assert rdc.parse(doc.site.file.read_text()).comments == []


def test_with_a_mouse_the_refused_selections_button_is_under_the_selection_and_on_the_screen(doc):
    select(doc.page, at(MAIN, "Second"), at("ul", "first item", 5))      # two blocks: refused, so the button stays
    doc.page.wait_for_selector(BTN)
    assert doc.page.evaluate("getComputedStyle(document.querySelector('#rd-comment-btn')).position") == "absolute"
    b = doc.page.locator(BTN).bounding_box()
    assert b["y"] >= doc.page.evaluate("getSelection().getRangeAt(0).getBoundingClientRect().bottom")
    assert b["y"] + b["height"] <= doc.page.viewport_size["height"]


def test_a_triple_click_on_a_paragraph_is_that_paragraph(doc):
    doc.page.click("p:has-text('Second paragraph')", click_count=3)
    doc.page.wait_for_selector(FIELD)
    assert quoted(doc.page) == "Second paragraph, about pears."
    (c,) = comment_on_selection(doc)
    assert c.quote == "Second paragraph, about pears."


def test_the_click_that_ends_a_real_double_click_or_drag_does_not_close_the_box_it_opened(doc):
    p = doc.page
    b = box(p, MAIN, "Second")
    p.mouse.dblclick(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
    p.wait_for_selector(FIELD)
    settled(p)
    assert p.locator(FIELD).count() == 1 and quoted(p) == "Second"
    p.click("#rd-popover .rd-quote")                  # a press inside the box is nothing beside it
    a, z = box(p, MAIN, "Second"), box(p, MAIN, "pears")
    p.mouse.move(a["x"] + 1, a["y"] + a["height"] / 2)
    p.mouse.down()
    p.mouse.move(z["x"] + z["width"] - 1, z["y"] + z["height"] / 2, steps=5)
    p.mouse.up()
    until(lambda: quoted(p) == "Second paragraph, about pears", what="the box for the dragged passage")
    settled(p)
    assert p.locator("#rd-popover").count() == 1 and p.evaluate("document.activeElement.tagName") == "TEXTAREA"


def test_the_passage_stays_marked_in_the_text_while_the_box_is_open_and_the_mark_goes_with_it(doc):
    p = doc.page
    select(p, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    p.wait_for_selector(FIELD)
    marked = "[...(CSS.highlights.get('rd-widened') || [])].map(String)"
    assert p.evaluate(marked) == ["Second paragraph"]
    settled(p)
    assert p.evaluate(marked) == ["Second paragraph"]      # the cursor left the text for the field; the mark stays
    p.click("#rd-popover button[data-a=minimize]")
    until(lambda: p.evaluate(marked) == [], what="the mark gone with the box")


def test_a_selection_changed_with_shift_and_the_arrows_opens_the_box_once_it_is_usable(doc):
    """SPEC 10.4: the keyboard fires `selectionchange` too; the offer follows the selection. A refused one keeps
    its disabled button; once the arrows bring the selection back inside one paragraph, the box opens by itself."""
    p = doc.page
    select(p, at(MAIN, "Second"), at("ul", "first item", 2))
    assert p.wait_for_selector(BTN).is_disabled()
    p.keyboard.press("Shift+ArrowLeft")
    settled(p)
    assert p.locator(FIELD).count() == 0 and p.locator(BTN).is_disabled()      # still across two blocks
    for _ in range(2):
        p.keyboard.press("Shift+ArrowLeft")
    p.wait_for_selector(FIELD)
    assert quoted(p) == "Second paragraph, about pears."
    assert p.locator(BTN).count() == 0
    (c,) = comment_on_selection(doc)
    assert c.quote == "Second paragraph, about pears."


LIST_TABLE_MD = """# Plan

- Item text before

  | a | b |
  |---|---|
  | one | two |

  Text after
"""


@pytest.mark.parametrize("start, end", [
    (at("li p", "Item text"), at("td", "one", None)),        # text outside the cell, then the cell
    (at("td", "one"), at("li", "Text after", None)),         # the cell, then the text outside it
])
def test_a_selection_between_a_table_cell_and_text_outside_it_in_the_same_block_says_one_cell(
        tab, site, start, end):
    site.file.write_text(LIST_TABLE_MD, encoding="utf-8")
    doc = tab.open()
    select(doc.page, start, end)
    btn = doc.page.wait_for_selector(BTN)
    assert btn.inner_text() == "One table cell at a time"
    assert btn.is_disabled()


# In edit mode the selection is the person's: what they type replaces what they selected, so the
# page widens only what a comment would quote, never the selection itself.
EDIT_DOC = """# Plan

**Important note about the deadline** for the report.

Read the [project plan](https://example.com/p) today.
"""


@pytest.fixture
def editing(tab, site):
    site.file.write_text(EDIT_DOC, encoding="utf-8")
    tab.open()
    tab.page.keyboard.press("e")
    tab.page.wait_for_selector("main p[contenteditable]")
    return tab


def double_click(page, css, word):
    b = box(page, css, word)
    page.mouse.dblclick(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
    until(lambda: selected(page) == word, what="the word selected")
    settled(page)                       # a button or a box would have come by now


def test_in_edit_mode_typing_over_a_double_clicked_word_of_a_bold_run_replaces_only_that_word(editing):
    p = editing.page
    double_click(p, "main strong", "deadline")
    p.keyboard.type("date")
    assert p.inner_text("main strong") == "Important note about the date"
    p.keyboard.press("Control+s")
    until(lambda: "**Important note about the date** for the report." in editing.site.file.read_text(),
          what="the edit in the file")


def test_in_edit_mode_typing_over_a_drag_into_a_link_keeps_the_rest_of_the_link(editing):
    p = editing.page
    a, z = box(p, "main p:has(a)", "the"), box(p, "main a", "project")
    p.mouse.move(a["x"] + 1, a["y"] + a["height"] / 2)
    p.mouse.down()
    p.mouse.move(z["x"] + z["width"] - 1, z["y"] + z["height"] / 2)
    p.mouse.up()
    until(lambda: selected(p), what="the dragged selection")
    p.keyboard.type("our")
    # The browser keeps the space before the link as a no-break space.
    assert p.inner_text("main p:has-text('today.')").replace("\xa0", " ") == "Read our plan today."
    assert p.inner_text("main p:has-text('today.') a[href='https://example.com/p']").strip() == "plan"
    p.keyboard.press("Control+s")
    until(lambda: "Read our" in editing.site.file.read_text(), what="the edit in the file")
    assert "plan](https://example.com/p) today." in editing.site.file.read_text()


def test_in_edit_mode_a_double_clicked_word_of_a_bold_run_stays_that_word_and_offers_nothing(editing):
    """Was: a comment on the word still quotes the whole run. In Edit a selection only selects: no button, no
    box, and nothing painted over it, so what is typed replaces the word the person chose. The whole-run quote
    is the Comment mode's (the bold-run tests above)."""
    p = editing.page
    double_click(p, "main strong", "deadline")
    assert selected(p) == "deadline"
    assert p.evaluate("CSS.highlights.has('rd-widened')") is False
    assert p.locator(BTN).count() == 0 and p.locator("#rd-popover").count() == 0


def test_in_edit_mode_a_selection_changed_from_the_keyboard_is_not_painted_or_offered(editing):
    """Was: painted and offered again. The selection grows as the person made it; nothing answers it."""
    p = editing.page
    double_click(p, "main strong", "deadline")
    for _ in range(len(" for")):
        p.keyboard.press("Shift+ArrowRight")
    until(lambda: selected(p) == "deadline for", what="the longer selection")
    settled(p)
    assert p.evaluate("CSS.highlights.has('rd-widened')") is False
    assert p.locator(BTN).count() == 0 and p.locator("#rd-popover").count() == 0


def test_in_edit_mode_collapsing_the_selection_from_the_keyboard_leaves_no_highlight_and_no_button(editing):
    p = editing.page
    double_click(p, "main strong", "deadline")
    p.keyboard.press("ArrowRight")
    until(lambda: selected(p) == "", what="the selection collapsed")
    settled(p)
    assert not p.evaluate("CSS.highlights.has('rd-widened')") and p.locator(BTN).count() == 0


def test_in_edit_mode_typing_over_a_selected_word_raises_no_button_and_paints_nothing(editing):
    p = editing.page
    double_click(p, "main strong", "deadline")
    p.keyboard.insert_text("date")          # one input event; far less than the 350 ms of a settled selection
    assert p.locator(BTN).count() == 0
    assert p.evaluate("CSS.highlights.has('rd-widened')") is False


def test_a_word_selected_in_edit_mode_gives_the_whole_run_when_the_person_switches_to_comment_and_selects_again(editing):
    p = editing.page
    double_click(p, "main strong", "deadline")
    p.click("#rd-mode button[data-m=save]")
    select(p, at("main strong", "deadline"), at("main strong", "deadline", None))
    p.wait_for_selector(FIELD)
    assert quoted(p) == "Important note about the deadline"


def _centre(b):
    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2


# ---- a selection made by touch (SPEC 10.4) ----------------------------------------------------------------


@pytest.fixture
def phone(touch_tab, site):
    site.file.write_text(PLAN_MD, encoding="utf-8")
    return touch_tab.open()


def touch_box(phone, start="Second", end="paragraph"):
    """A selection by touch, and the box it opens by itself once settled."""
    select_by_touch(phone.page, at(MAIN, start), at(MAIN, end, None))
    phone.page.wait_for_selector(FIELD)
    return phone.page


def refuse_by_touch(phone):
    select_by_touch(phone.page, at(BOLD_P, "Some "), at(MAIN, "pears", None))
    phone.page.wait_for_selector(BTN)
    return phone.page


# Restated on 2026-11-09 (ticket 03, E): on a phone a usable selection opens the box by itself, as with a mouse; no bar is offered
# for it. The bar stays only for a refused selection (a disabled button with its reason). The tests of the tappable bar are gone:
# a tap on the bar, a finger that travels from it, a click eaten by the browser, the thumb that collapses the selection, and the
# 2 s thumb timer (six tests) no longer apply, since nothing tappable is offered; their ground is the touchend test below.

def test_a_touch_selection_with_no_mouse_event_opens_the_box_by_itself_with_no_bar(phone):
    p = touch_box(phone)
    assert p.locator(BTN).count() == 0, "a bar was offered for a usable selection"
    assert quoted(p) == "Second paragraph"


def test_a_touch_selection_opens_a_box_whose_comment_is_saved(phone):
    select_by_touch(phone.page, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    (c,) = comment_on_selection(phone, "From the phone.")
    assert c.quote == "Second paragraph"


def test_a_touch_selection_ending_inside_a_bold_word_is_widened(phone):
    select_by_touch(phone.page, at(BOLD_P, "Some "), at(BOLD_P + " strong", "bold word", 2))
    phone.page.wait_for_selector(FIELD)
    assert quoted(phone.page) == "Some bold word"
    assert phone.page.evaluate("[...(CSS.highlights.get('rd-widened') || [])].map(String)") == ["Some bold word"]      # the cursor is in the field: the passage is marked


def test_a_touch_selection_across_two_paragraphs_gets_the_disabled_button_with_its_reason(phone):
    refuse_by_touch(phone)
    assert phone.page.locator(BTN).is_disabled()
    assert phone.page.locator(BTN).inner_text() == "One paragraph at a time"
    assert phone.page.locator(FIELD).count() == 0


def test_a_touch_selection_in_code_gets_the_disabled_button_with_its_reason(phone):
    select_by_touch(phone.page, at("pre", "print"), at("pre", "code", None))
    phone.page.wait_for_selector(BTN)
    assert phone.page.locator(BTN).is_disabled()


def test_dragging_a_handle_opens_one_box_for_the_selection_it_ends_on(phone):
    """Each step of a drag fires selectionchange; the box waits for the drag to settle."""
    p = phone.page
    for end in ("Sec", "Second", "Second para"):
        select_by_touch(p, at(MAIN, "Second"), at(MAIN, end, None))
        p.wait_for_timeout(40)
        assert p.locator("#rd-popover").count() == 0
    p.wait_for_selector(FIELD)
    assert p.locator("#rd-popover").count() == 1
    assert quoted(p) == "Second para"


def test_clearing_a_refused_touch_selection_removes_the_button(phone):
    refuse_by_touch(phone)
    phone.page.evaluate("getSelection().removeAllRanges()")
    phone.page.wait_for_selector(BTN, state="detached")


def test_typing_in_the_comment_form_raises_no_button(phone):
    p = touch_box(phone)
    p.fill(FIELD, "words typed")
    p.wait_for_timeout(900)
    assert p.locator(BTN).count() == 0
    assert p.locator("#rd-popover").count() == 1


def test_the_refused_selections_bar_is_fixed_at_the_foot_of_the_screen_not_beside_the_selection(phone):
    """iOS draws its own callout (Copy / Search / >) beside the selection, above or below it, over
    anything there: the bar waits at the foot of the screen, where no callout is."""
    refuse_by_touch(phone)
    assert phone.page.evaluate("getComputedStyle(document.querySelector('#rd-comment-btn')).position") == "fixed"
    b = phone.page.locator(BTN).bounding_box()
    assert 0 <= b["x"] and b["x"] + b["width"] <= 390
    assert 844 - 40 <= b["y"] + b["height"] <= 844
    menu = phone.page.locator("#rd-menu-btn").bounding_box()
    assert b["x"] + b["width"] <= menu["x"] or b["y"] + b["height"] <= menu["y"]
    phone.page.evaluate("window.scrollBy(0, 5)")
    assert phone.page.locator(BTN).bounding_box()["y"] == b["y"]


def test_a_refused_selection_at_the_foot_of_a_phone_is_not_covered_by_the_bar(phone):
    phone.page.evaluate("""() => { const p = [...document.querySelectorAll('main p')].find(e => e.textContent.includes('pears'));
      window.scrollBy(0, p.getBoundingClientRect().bottom - window.innerHeight + 4); }""")
    refuse_by_touch(phone)
    b = phone.page.locator(BTN).bounding_box()
    sel = phone.page.evaluate("(() => { const r = getSelection().getRangeAt(0).getBoundingClientRect(); return {y: r.y, h: r.height}; })()")
    assert 0 <= b["y"] and b["y"] + b["height"] <= 844
    assert b["y"] >= sel["y"] + sel["h"] or b["y"] + b["height"] <= sel["y"]


def test_a_touch_selection_across_two_table_cells_gets_the_disabled_button_with_its_reason(phone):
    select_by_touch(phone.page, at("table", "one"), at("table", "two", None))
    phone.page.wait_for_selector(BTN)
    assert phone.page.locator(BTN).inner_text() == "One table cell at a time"


def test_a_mouse_that_was_never_let_go_does_not_silence_a_touch_selection(phone):
    phone.page.evaluate("document.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}))")
    phone.page.evaluate("window.dispatchEvent(new Event('blur'))")
    touch_box(phone)


def test_a_late_selectionchange_does_not_raise_a_button_over_the_open_form(phone):
    """Widening a selection redraws it and fires one more selectionchange, after the box is up."""
    select_by_touch(phone.page, at(BOLD_P, "Some "), at(BOLD_P + " strong", "bold word", 2))
    phone.page.wait_for_selector(FIELD)
    phone.page.wait_for_timeout(1000)
    assert phone.page.locator(BTN).count() == 0
    assert phone.page.locator("#rd-popover").count() == 1


def test_the_passage_stays_marked_and_quoted_when_the_selection_collapses_as_the_field_takes_the_cursor(phone):
    p = touch_box(phone)
    marked = "[...(CSS.highlights.get('rd-widened') || [])].map(String)"
    p.evaluate("getSelection().removeAllRanges()")
    p.wait_for_timeout(900)
    assert p.evaluate(marked) == ["Second paragraph"]
    assert quoted(p) == "Second paragraph" and p.locator("#rd-popover").count() == 1


TOUCH_END = """() => { document.dispatchEvent(new TouchEvent('touchend', {bubbles: true, cancelable: true, composed: true}));
  const a = document.activeElement; return {box: !!document.querySelector('#rd-popover'), active: a && a.tagName}; }"""
TOUCH_START = "() => document.dispatchEvent(new TouchEvent('touchstart', {bubbles: true, cancelable: true, composed: true}))"


def test_the_touchend_that_ends_a_selection_opens_the_box_and_puts_the_cursor_in_the_field_in_that_same_event(phone):
    """iOS raises the keyboard for a focus() made inside a touch event and not for one made later: no settle delay here."""
    p = phone.page
    p.evaluate(TOUCH_START)
    select_by_touch(p, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    got = p.evaluate(TOUCH_END)         # in the same task, 600 ms before the settle would have opened it
    assert got == {"box": True, "active": "TEXTAREA"}, got


def test_a_tap_away_from_a_standing_selection_does_not_open_the_box(phone):
    """The finger lands on a selection that stands (same words at touchstart and touchend): that touch ends nothing, and the tap
    then clears the selection, so the settled selection that follows is empty."""
    p = phone.page
    select_by_touch(p, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    p.evaluate(TOUCH_START)
    got = p.evaluate(TOUCH_END)
    assert got["box"] is False, got
    p.evaluate("getSelection().removeAllRanges()")
    p.wait_for_timeout(900)
    assert p.locator("#rd-popover").count() == 0
