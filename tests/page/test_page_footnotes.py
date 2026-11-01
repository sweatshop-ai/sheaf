"""A paragraph that cites a footnote, edited on the page (sheaf #163): the save keeps the note."""
import pytest

from pagehelp import type_at_end, until

pytestmark = pytest.mark.page

DOC_TEXT = "# Plan\n\nFirst[^z] line.\n\nThe body cites[^note] twice[^note].\n\n[^note]: the note words\n\n[^z]: zed\n"


def test_typing_in_a_paragraph_that_cites_a_footnote_keeps_its_labels_and_the_notes_words(tab):
    p, f = tab.page, tab.site.file
    f.write_text(DOC_TEXT, encoding="utf-8")
    tab.open()
    type_at_end(p, "main p:has-text('The body')", " typed")
    until(lambda: "typed" in f.read_text(encoding="utf-8"), timeout=10, what="the autosave")
    assert f.read_text(encoding="utf-8") == DOC_TEXT.replace("twice[^note].", "twice[^note]. typed")
    p.reload()
    until(lambda: "the note words" in p.inner_text("#fn2"), what="the note's words on the page")
