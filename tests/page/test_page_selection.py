"""Selecting text (SPEC 10.4, D24): a selection that ends inside a formatted run is widened to the
whole run and the comment lands after it; one that cannot hold a comment shows a disabled button
that says why, before the click."""
import pytest

from pagehelp import at, box, select, select_by_touch, selected, until
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


@pytest.fixture
def doc(tab, site):
    site.file.write_text(PLAN_MD, encoding="utf-8")
    return tab.open()


def settled(page):
    """Wait out the 350 ms a selection must stand still before the page reacts to it."""
    page.wait_for_timeout(600)


def comment_on_selection(tab, text="A thought."):
    tab.page.click(BTN)
    tab.page.fill("#rd-popover textarea", text)
    tab.page.click("#rd-popover button[data-f=ok]")
    return until(lambda: rdc.parse(tab.site.file.read_text()).comments or None, what="the comment in the file")


def test_a_selection_ending_inside_a_bold_word_is_widened_and_the_comment_lands_after_it(doc):
    select(doc.page, at(BOLD_P, "Some "), at(BOLD_P + " strong", "bold word", 2))
    doc.page.wait_for_selector(BTN)
    assert selected(doc.page) == "Some bold word"
    (c,) = comment_on_selection(doc)
    md = doc.site.file.read_text()
    assert c.quote == "Some bold word"
    assert md[:md.index("<!--")].endswith("Some **bold word**")


def test_a_selection_starting_inside_a_bold_word_is_widened_too(doc):
    select(doc.page, at(BOLD_P + " strong", "bold word", 2), at(BOLD_P, " and a ", None))
    doc.page.wait_for_selector(BTN)
    assert selected(doc.page).strip() == "bold word and a"
    (c,) = comment_on_selection(doc)
    assert c.quote == "bold word and a"


def test_a_selection_ending_inside_a_link_is_widened_and_the_comment_lands_after_it(doc):
    select(doc.page, at(BOLD_P, " and a "), at(BOLD_P + " a", "link text", 3))
    doc.page.wait_for_selector(BTN)
    assert selected(doc.page).strip() == "and a link text"
    (c,) = comment_on_selection(doc)
    md = doc.site.file.read_text()
    assert c.quote == "and a link text"
    assert md[:md.index("<!--")].endswith("[link text](https://example.com/x)")


def test_a_selection_that_starts_after_a_bold_word_does_not_take_it_in(doc):
    select(doc.page, at(BOLD_P, " and a ", 1), at(BOLD_P + " a", "link text", 4))
    doc.page.wait_for_selector(BTN)
    assert "bold" not in selected(doc.page)


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


def test_with_a_mouse_the_button_is_under_the_selection_and_on_the_screen(doc):
    select(doc.page, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    doc.page.wait_for_selector(BTN)
    assert doc.page.evaluate("getComputedStyle(document.querySelector('#rd-comment-btn')).position") == "absolute"
    b = doc.page.locator(BTN).bounding_box()
    sel = box(doc.page, MAIN, "Second paragraph")
    assert b["y"] >= sel["y"] + sel["height"]


def test_a_triple_click_on_a_paragraph_is_that_paragraph(doc):
    doc.page.click("p:has-text('Second paragraph')", click_count=3)
    btn = doc.page.wait_for_selector(BTN)
    assert btn.inner_text() == "Comment" and not btn.is_disabled()
    (c,) = comment_on_selection(doc)
    assert c.quote == "Second paragraph, about pears."


def test_a_selection_extended_with_shift_and_the_arrows_gets_the_button_for_what_it_now_holds(doc):
    """SPEC 10.4: the keyboard fires `selectionchange` too; the button follows the selection."""
    p = doc.page
    b = box(p, MAIN, "Second")
    p.mouse.dblclick(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)
    p.wait_for_selector(BTN)
    assert selected(p) == "Second"
    for _ in range(len(" paragraph")):
        p.keyboard.press("Shift+ArrowRight")
    until(lambda: p.evaluate("getSelection().toString()") == "Second paragraph", what="the longer selection")
    settled(p)
    assert p.locator(BTN).count() == 1
    (c,) = comment_on_selection(doc)
    assert c.quote == "Second paragraph"


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
    page.wait_for_selector(BTN)


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
    p.wait_for_selector(BTN)
    p.keyboard.type("our")
    # The browser keeps the space before the link as a no-break space.
    assert p.inner_text("main p:has-text('today.')").replace("\xa0", " ") == "Read our plan today."
    assert p.inner_text("main p:has-text('today.') a[href='https://example.com/p']").strip() == "plan"
    p.keyboard.press("Control+s")
    until(lambda: "Read our" in editing.site.file.read_text(), what="the edit in the file")
    assert "plan](https://example.com/p) today." in editing.site.file.read_text()


def test_in_edit_mode_a_comment_on_a_word_of_a_bold_run_still_quotes_the_whole_run(editing):
    p = editing.page
    double_click(p, "main strong", "deadline")
    assert selected(p) == "deadline"
    # What the comment will quote is painted instead of selected.
    assert p.evaluate("[...CSS.highlights.get('rd-widened')].map(String)") == ["Important note about the deadline"]
    (c,) = comment_on_selection(editing)
    md = editing.site.file.read_text()
    assert c.quote == "Important note about the deadline"
    assert md[:md.index("<!--")].endswith("**Important note about the deadline**")


def test_in_edit_mode_a_selection_changed_from_the_keyboard_is_painted_and_offered_again(editing):
    p = editing.page
    double_click(p, "main strong", "deadline")
    for _ in range(len(" for")):
        p.keyboard.press("Shift+ArrowRight")
    until(lambda: p.evaluate("[...(CSS.highlights.get('rd-widened') || [])].map(String)") ==
          ["Important note about the deadline for"], what="the passage painted again")
    assert p.locator(BTN).count() == 1
    (c,) = comment_on_selection(editing)
    assert c.quote == "Important note about the deadline for"


def test_in_edit_mode_collapsing_the_selection_from_the_keyboard_takes_the_highlight_and_the_button(editing):
    p = editing.page
    double_click(p, "main strong", "deadline")
    p.keyboard.press("ArrowRight")
    until(lambda: not p.evaluate("CSS.highlights.has('rd-widened')") and p.locator(BTN).count() == 0,
          what="the highlight and the button gone")


def test_in_edit_mode_the_button_is_gone_the_moment_a_selected_word_is_typed_over(editing):
    p = editing.page
    double_click(p, "main strong", "deadline")
    p.keyboard.insert_text("date")          # one input event; far less than the 350 ms of a settled selection
    assert p.locator(BTN).count() == 0
    assert p.evaluate("CSS.highlights.has('rd-widened')") is False


def _centre(b):
    return b["x"] + b["width"] / 2, b["y"] + b["height"] / 2


# ---- a selection made by touch (SPEC 10.4) ----------------------------------------------------------------


@pytest.fixture
def phone(touch_tab, site):
    site.file.write_text(PLAN_MD, encoding="utf-8")
    return touch_tab.open()


def test_a_touch_selection_with_no_mouse_event_raises_the_comment_button(phone):
    select_by_touch(phone.page, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    phone.page.wait_for_selector(BTN)
    assert phone.page.locator(BTN).is_enabled()


def test_a_touch_selection_gives_a_button_that_opens_the_form_and_the_comment_is_saved(phone):
    select_by_touch(phone.page, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    phone.page.wait_for_selector(BTN)
    (c,) = comment_on_selection(phone, "From the phone.")
    assert c.quote == "Second paragraph"


def test_a_touch_selection_ending_inside_a_bold_word_is_widened(phone):
    select_by_touch(phone.page, at(BOLD_P, "Some "), at(BOLD_P + " strong", "bold word", 2))
    phone.page.wait_for_selector(BTN)
    assert selected(phone.page) == "Some bold word"


def test_a_touch_selection_across_two_paragraphs_gets_the_disabled_button_with_its_reason(phone):
    select_by_touch(phone.page, at(BOLD_P, "Some "), at(MAIN, "pears", None))
    phone.page.wait_for_selector(BTN)
    assert phone.page.locator(BTN).is_disabled()
    assert phone.page.locator(BTN).inner_text() == "One paragraph at a time"


def test_a_touch_selection_in_code_gets_the_disabled_button_with_its_reason(phone):
    select_by_touch(phone.page, at("pre", "print"), at("pre", "code", None))
    phone.page.wait_for_selector(BTN)
    assert phone.page.locator(BTN).is_disabled()


def test_dragging_a_handle_raises_one_button_for_the_selection_it_ends_on(phone):
    """Each step of a drag fires selectionchange; the button waits for the drag to settle."""
    p = phone.page
    for end in ("Sec", "Second", "Second para"):
        select_by_touch(p, at(MAIN, "Second"), at(MAIN, end, None))
        p.wait_for_timeout(40)
        assert p.locator(BTN).count() == 0
    p.wait_for_selector(BTN)
    assert p.locator(BTN).count() == 1


def test_clearing_a_touch_selection_removes_the_button(phone):
    select_by_touch(phone.page, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    phone.page.wait_for_selector(BTN)
    phone.page.evaluate("getSelection().removeAllRanges()")
    phone.page.wait_for_selector(BTN, state="detached")


def test_typing_in_the_comment_form_raises_no_button(phone):
    select_by_touch(phone.page, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    phone.page.wait_for_selector(BTN)
    phone.page.click(BTN)
    phone.page.fill("#rd-popover textarea", "words typed")
    phone.page.wait_for_timeout(600)
    assert phone.page.locator(BTN).count() == 0


def test_on_a_phone_the_button_is_a_fixed_bar_at_the_foot_of_the_screen_not_beside_the_selection(phone):
    """iOS draws its own callout (Copy / Search / >) beside the selection, above or below it, over
    anything there: the button waits at the foot of the screen, where no callout is."""
    select_by_touch(phone.page, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    phone.page.wait_for_selector(BTN)
    assert phone.page.evaluate("getComputedStyle(document.querySelector('#rd-comment-btn')).position") == "fixed"
    b = phone.page.locator(BTN).bounding_box()
    assert 0 <= b["x"] and b["x"] + b["width"] <= 390
    assert 844 - 40 <= b["y"] + b["height"] <= 844
    menu = phone.page.locator("#rd-menu-btn").bounding_box()
    assert b["x"] + b["width"] <= menu["x"] or b["y"] + b["height"] <= menu["y"]
    phone.page.evaluate("window.scrollBy(0, 5)")
    assert phone.page.locator(BTN).bounding_box()["y"] == b["y"]


def test_a_selection_at_the_foot_of_a_phone_is_not_covered_by_the_button(phone):
    phone.page.evaluate("""() => { const p = [...document.querySelectorAll('main p')].find(e => e.textContent.includes('Second paragraph'));
      window.scrollBy(0, p.getBoundingClientRect().bottom - window.innerHeight + 4); }""")
    select_by_touch(phone.page, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    phone.page.wait_for_selector(BTN)
    b = phone.page.locator(BTN).bounding_box()
    sel = phone.page.evaluate("(() => { const r = getSelection().getRangeAt(0).getBoundingClientRect(); return {y: r.y, h: r.height}; })()")
    assert 0 <= b["y"] and b["y"] + b["height"] <= 844
    assert b["y"] >= sel["y"] + sel["h"] or b["y"] + b["height"] <= sel["y"]


def test_a_finger_that_travels_from_the_button_is_not_a_tap(phone):
    select_by_touch(phone.page, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    phone.page.wait_for_selector(BTN)
    x, y = _centre(phone.page.locator(BTN).bounding_box())
    phone.page.evaluate("""([x, y]) => {
      const b = document.querySelector('#rd-comment-btn'), t = (cy) => new Touch({identifier: 1, target: b, clientX: x, clientY: cy});
      b.dispatchEvent(new TouchEvent('touchstart', {bubbles: true, cancelable: true, touches: [t(y)], changedTouches: [t(y)]}));
      b.dispatchEvent(new TouchEvent('touchend', {bubbles: true, cancelable: true, touches: [], changedTouches: [t(y - 20)]})); }""", [x, y])
    phone.page.wait_for_timeout(500)
    assert phone.page.locator("#rd-popover").count() == 0
    phone.page.touchscreen.tap(x, y)
    phone.page.wait_for_selector("#rd-popover textarea")


def test_a_tap_opens_the_form_even_when_the_browser_eats_the_click(phone):
    """iOS can take a tap on a selection for the end of the selection and send no click."""
    select_by_touch(phone.page, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    phone.page.wait_for_selector(BTN)
    phone.page.evaluate("window.addEventListener('click', e => e.stopImmediatePropagation(), true)")
    phone.page.touchscreen.tap(*_centre(phone.page.locator(BTN).bounding_box()))
    phone.page.wait_for_selector("#rd-popover textarea")
    assert "Second paragraph" in phone.page.locator("#rd-popover .rd-quote").inner_text()


def test_a_tap_that_clears_the_selection_at_touchstart_still_opens_the_form_with_that_selection(phone):
    select_by_touch(phone.page, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    phone.page.wait_for_selector(BTN)
    phone.page.evaluate("""() => {
      document.addEventListener('touchstart', () => getSelection().removeAllRanges(), true);
      window.addEventListener('click', e => e.stopImmediatePropagation(), true); }""")
    phone.page.touchscreen.tap(*_centre(phone.page.locator(BTN).bounding_box()))
    phone.page.wait_for_selector("#rd-popover textarea")
    assert "Second paragraph" in phone.page.locator("#rd-popover .rd-quote").inner_text()


def test_one_tap_opens_one_form_when_the_click_arrives_too(phone):
    select_by_touch(phone.page, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    phone.page.wait_for_selector(BTN)
    phone.page.touchscreen.tap(*_centre(phone.page.locator(BTN).bounding_box()))
    phone.page.wait_for_selector("#rd-popover textarea")
    phone.page.wait_for_timeout(500)
    assert phone.page.locator("#rd-popover").count() == 1


def test_a_touch_selection_across_two_table_cells_gets_the_disabled_button_with_its_reason(phone):
    select_by_touch(phone.page, at("table", "one"), at("table", "two", None))
    phone.page.wait_for_selector(BTN)
    assert phone.page.locator(BTN).inner_text() == "One table cell at a time"


def test_the_button_stays_when_the_selection_collapses_under_the_thumb_that_taps_it(phone):
    select_by_touch(phone.page, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    phone.page.wait_for_selector(BTN)
    phone.page.dispatch_event(BTN, "pointerdown")
    phone.page.evaluate("getSelection().removeAllRanges()")
    phone.page.wait_for_timeout(700)
    phone.page.click(BTN)
    phone.page.wait_for_selector("#rd-popover textarea")


def test_a_mouse_that_was_never_let_go_does_not_silence_a_touch_selection(phone):
    phone.page.evaluate("document.dispatchEvent(new MouseEvent('mousedown', {bubbles: true}))")
    phone.page.evaluate("window.dispatchEvent(new Event('blur'))")
    select_by_touch(phone.page, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    phone.page.wait_for_selector(BTN)


def test_a_late_selectionchange_does_not_raise_a_button_over_the_open_form(phone):
    """Widening a selection redraws it and fires one more selectionchange, after the button is up."""
    select_by_touch(phone.page, at(BOLD_P, "Some "), at(BOLD_P + " strong", "bold word", 2))
    phone.page.wait_for_selector(BTN)
    phone.page.click(BTN)
    phone.page.wait_for_selector("#rd-popover textarea")
    phone.page.wait_for_timeout(800)
    assert phone.page.locator(BTN).count() == 0
    assert phone.page.locator("#rd-popover").count() == 1


def test_a_tap_that_never_landed_does_not_leave_a_button_for_the_old_passage_after_a_new_selection(phone):
    select_by_touch(phone.page, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    phone.page.wait_for_selector(BTN)
    phone.page.dispatch_event(BTN, "pointerdown")        # the finger went down on the button and slid off: no click, no tap
    select_by_touch(phone.page, at(MAIN, "first"), at(MAIN, "item", None))        # within the 2 s: a long press elsewhere
    phone.page.wait_for_timeout(2600)                    # the thumb's 2 s are over
    phone.page.click(BTN)
    phone.page.wait_for_selector("#rd-popover textarea")
    quote = phone.page.locator("#rd-popover .rd-quote").inner_text()
    assert "first item" in quote and "Second" not in quote


def test_a_second_tap_on_the_old_bar_inside_the_two_seconds_opens_the_form_on_the_new_passage(phone):
    select_by_touch(phone.page, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    phone.page.wait_for_selector(BTN)
    x, y = _centre(phone.page.locator(BTN).bounding_box())
    phone.page.dispatch_event(BTN, "pointerdown")        # the finger went down on the bar and slid off
    select_by_touch(phone.page, at(MAIN, "first"), at(MAIN, "item", None))        # within the 2 s: a long press elsewhere
    phone.page.wait_for_timeout(800)                     # the selection has settled, the thumb's 2 s are not over
    phone.page.touchscreen.tap(x, y)                     # a second tap on the bar, where it stood
    phone.page.wait_for_selector("#rd-popover textarea")
    quote = phone.page.locator("#rd-popover .rd-quote").inner_text()
    assert "first item" in quote and "Second" not in quote


def test_a_button_whose_tap_never_clicked_goes_when_the_selection_is_gone(phone):
    select_by_touch(phone.page, at(MAIN, "Second"), at(MAIN, "paragraph", None))
    phone.page.wait_for_selector(BTN)
    phone.page.dispatch_event(BTN, "pointerdown")
    phone.page.evaluate("getSelection().removeAllRanges()")
    phone.page.wait_for_selector(BTN, state="detached", timeout=4000)
