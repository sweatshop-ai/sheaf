"""The Comment / Edit switch is one button, a toggle (ticket 03, D): `Edit (E)` in Comment mode, `Save (Ctrl+S)` in Edit mode, the
same size for both. A click on Save saves and returns to Comment mode; a save that fails or is refused keeps the person in Edit
with what they typed."""
import pytest

from pagehelp import P1, toast, until

pytestmark = pytest.mark.page

TOGGLE = "#rd-mode button"
MD = "# Plan\n\nSecond paragraph, about pears.\n\nA third one, about apples.\n"


def editing(page):
    return page.evaluate("document.body.classList.contains('rd-editing')")


def label(page):
    return page.inner_text(TOGGLE)


def size(page):
    b = page.locator(TOGGLE).bounding_box()
    return round(b["width"], 2), round(b["height"], 2)


def type_into_first_paragraph(page):
    page.focus(P1)
    page.keyboard.press("Control+End")
    page.keyboard.type(" and plums")


@pytest.fixture
def doc(tab, site):
    site.file.write_text(MD, encoding="utf-8")
    return tab.open()


def test_it_is_one_button_that_reads_edit_then_save_with_its_keys_and_keeps_its_size(doc):
    p = doc.page
    assert p.locator(TOGGLE).count() == 1
    assert label(p) == "Edit (E)"
    before = size(p)
    p.click(TOGGLE)
    until(lambda: editing(p), what="edit mode")
    assert p.locator(TOGGLE).count() == 1 and label(p) == "Save (Ctrl+S)"
    assert size(p) == before, "the button changed size with its label"
    assert p.locator(TOGGLE).bounding_box() is not None


def test_on_touch_the_labels_have_no_key_to_hint_at(touch_tab, site):
    site.file.write_text(MD, encoding="utf-8")
    p = touch_tab.open().page
    assert label(p) == "Edit"
    before = size(p)
    p.touchscreen.tap(*[v for v in (lambda b: (b["x"] + b["width"] / 2, b["y"] + b["height"] / 2))(p.locator(TOGGLE).bounding_box())])
    until(lambda: editing(p), what="edit mode")
    assert label(p) == "Save" and size(p) == before


def test_the_e_key_enters_edit_and_inside_an_editable_area_it_is_a_letter(doc):
    p = doc.page
    p.keyboard.press("e")
    until(lambda: editing(p), what="edit mode by the E key")
    assert label(p) == "Save (Ctrl+S)"
    p.focus(P1)
    p.keyboard.press("Control+End")
    p.keyboard.press("e")
    assert editing(p) and p.inner_text(P1).endswith("e"), "E typed in an editable area was taken for the key"


def test_a_click_on_save_saves_and_returns_to_comment_mode(doc, site):
    p = doc.page
    p.click(TOGGLE)
    type_into_first_paragraph(p)
    p.click(TOGGLE)
    until(lambda: "and plums" in site.file.read_text(encoding="utf-8"), what="the typed words in the file")
    until(lambda: not editing(p), what="comment mode")
    assert label(p) == "Edit (E)"
    assert p.locator("main [contenteditable=true]").count() == 0


def test_a_click_on_save_with_nothing_changed_returns_to_comment_mode(doc):
    p = doc.page
    p.click(TOGGLE)
    p.click(TOGGLE)
    until(lambda: not editing(p), what="comment mode")


def test_a_save_that_fails_keeps_the_person_in_edit_with_what_they_typed(doc, site):
    p = doc.page
    p.click(TOGGLE)
    type_into_first_paragraph(p)
    p.route("**/_/save", lambda route: route.fulfill(status=500, content_type="application/json", body='{"ok": false, "error": "disk full"}'))
    p.click(TOGGLE)
    until(lambda: "save failed" in toast(p), what="the toast that says the save failed")
    assert editing(p) and label(p) == "Save (Ctrl+S)"
    assert "and plums" in p.inner_text(P1)
    assert "and plums" not in site.file.read_text(encoding="utf-8")
    p.unroute("**/_/save")
    p.click(TOGGLE)
    until(lambda: "and plums" in site.file.read_text(encoding="utf-8"), what="the words saved by a second click")
    until(lambda: not editing(p), what="comment mode")


def test_ctrl_s_saves_and_stays_in_edit_as_before(doc, site):
    p = doc.page
    p.click(TOGGLE)
    type_into_first_paragraph(p)
    p.keyboard.press("Control+s")
    until(lambda: "and plums" in site.file.read_text(encoding="utf-8"), what="the words in the file")
    assert editing(p) and label(p) == "Save (Ctrl+S)"


def test_the_toggle_is_a_page_control_not_a_click_beside_an_open_box(doc, site):
    from sheafmd import comments as rdc
    from sheafmd.source import update_file
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "apples"), "apples", "Why?", "Bea", "2026-10-14T10:00")[0])
    p = doc.open().page
    p.click(".rd-badge")
    p.wait_for_selector("#rd-popover textarea")
    p.click(TOGGLE)
    p.wait_for_timeout(400)
    assert p.locator("#rd-popover").count() == 1
