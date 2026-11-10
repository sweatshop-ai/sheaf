"""The copy block on the page (ticket 05, SPEC 6.8): a `> [!COPY]` quote has a Copy button, takes edits and
comments like any quote, and the button is never part of what a save writes."""
import pytest

from pagehelp import at, comment_on, until
from sheafmd import comments as rdc

pytestmark = pytest.mark.page

QUOTE = "main blockquote.rd-copy"
TOGGLE = "#rd-mode button"
MD = ("# Plan\n\nBefore the mail.\n\n"
      "> [!COPY]\n> Hello **Anna**,\n> thanks for the call.\n>\n> Best, Thierry\n\n"
      "> A quote nobody copies.\n\nAfter.\n")


@pytest.fixture
def doc(tab, site):
    site.file.write_text(MD, encoding="utf-8")
    tab.page.context.grant_permissions(["clipboard-read", "clipboard-write"], origin=site.base)
    return tab.open()


def clipboard(page):
    return page.evaluate("navigator.clipboard.readText()")


def press_copy(page):
    page.click(f"{QUOTE} .rd-copybtn")


def test_only_the_marked_quote_has_a_copy_button_and_the_marker_is_not_shown(doc):
    p = doc.page
    assert p.locator(".rd-copybtn").count() == 1
    assert p.locator(f"{QUOTE} > .rd-copybtn").count() == 1
    assert p.locator("main blockquote:not(.rd-copy) .rd-copybtn").count() == 0
    assert "[!COPY]" not in p.inner_text("main")


def test_copy_puts_the_block_as_shown_on_the_clipboard(doc):
    press_copy(doc.page)
    until(lambda: clipboard(doc.page), what="the clipboard")
    assert clipboard(doc.page) == "Hello Anna, thanks for the call.\n\nBest, Thierry"
    assert doc.page.inner_text(f"{QUOTE} .rd-copybtn") == "Copied"


def test_copy_takes_the_text_typed_in_edit_mode_before_it_is_saved(doc):
    p = doc.page
    p.click(TOGGLE)
    p.click(f"{QUOTE} p >> nth=1")
    p.keyboard.press("Control+End")
    p.keyboard.type(" Really.")
    press_copy(p)
    until(lambda: "Really." in clipboard(p), what="the edit on the clipboard")
    assert clipboard(p) == "Hello Anna, thanks for the call.\n\nBest, Thierry Really."
    assert p.evaluate("document.activeElement.closest('blockquote') !== null")      # the caret stayed in the quote


def test_an_edit_is_saved_with_the_marker_and_without_the_button(doc, site):
    p = doc.page
    p.click(TOGGLE)
    p.click(f"{QUOTE} p >> nth=1")
    p.keyboard.press("Control+End")
    p.keyboard.type(" Really.")
    press_copy(p)
    p.click(TOGGLE)
    until(lambda: "Really." in site.file.read_text(encoding="utf-8"), what="the saved edit")
    saved = site.file.read_text(encoding="utf-8")
    assert "> [!COPY]\n> Hello **Anna**, thanks for the call.\n>\n> Best, Thierry Really." in saved
    assert "Copy" not in saved and "button" not in saved and "rd-" not in saved
    assert saved.count("[!COPY]") == 1
    assert "> A quote nobody copies." in saved


def test_entering_edit_mode_does_not_make_the_block_changed(doc, site):
    before = site.file.read_text(encoding="utf-8")
    doc.page.click(TOGGLE)
    doc.page.click(TOGGLE)
    doc.page.wait_for_timeout(600)
    assert site.file.read_text(encoding="utf-8") == before


def test_a_comment_on_the_block_is_anchored_in_the_source_after_the_selected_words(doc, site):
    c = comment_on(doc, at(QUOTE, "thanks for the call"), at(QUOTE, "thanks for the call", None), "Warmer?")
    saved = site.file.read_text(encoding="utf-8")
    assert saved.startswith("# Plan") and "> [!COPY]\n> Hello **Anna**,\n> thanks for the call" in saved
    end = saved.index("thanks for the call") + len("thanks for the call")
    assert saved[end:].startswith(saved[c.start:c.end])          # the comment sits right behind the words selected
    assert rdc.parse(saved).by_id(c.id).body == "Warmer?"
    until(lambda: doc.page.locator(f"{QUOTE} .rd-anchor").count() == 1, what="the badge in the quote")
    assert doc.page.locator(f"{QUOTE} > .rd-copybtn").count() == 1


def test_the_text_copied_leaves_the_comment_badge_out(doc, site):
    comment_on(doc, at(QUOTE, "thanks for the call"), at(QUOTE, "thanks for the call", None), "Warmer?")
    doc.page.wait_for_selector(f"{QUOTE} .rd-anchor")
    press_copy(doc.page)
    until(lambda: clipboard(doc.page), what="the clipboard")
    assert clipboard(doc.page) == "Hello Anna, thanks for the call.\n\nBest, Thierry"


def test_a_mounted_page_gets_the_button_too(chromium, site):
    # The front's copy of the page (mount.js) drops every `rd-` class the render wrote; this one it keeps.
    from test_mount_page import _front
    from pagehelp import close_context
    site.file.write_text(MD, encoding="utf-8")
    c, f = _front(chromium, site)
    try:
        f.open()
        until(lambda: f.has("blockquote.rd-copy > .rd-copybtn"), what="the Copy button in the root")
        assert not f.has("blockquote:not(.rd-copy) .rd-copybtn")
        assert f.errors == []
    finally:
        close_context(c)
