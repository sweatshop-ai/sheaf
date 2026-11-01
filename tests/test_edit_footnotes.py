"""A page edit of a paragraph that cites a footnote keeps the note (sheaf #163).

The page shows a citation as pandoc's `<a href="#fnN" class="footnote-ref">`, numbered by its place among
the document's citations, while the source names it by its label (`[^note]`). Pandoc's HTML reader takes that
link for a footnote with no words and writes an empty definition beside the citation, which the render shows
in place of the note. The save puts the source's label back instead. Fragments are built the way the page
builds them: the document rendered by pandoc, the block's paragraph taken from it, one word changed.
"""
import re

from helpers import pandoc
from sheafmd import edit as rde


def page_paragraph(doc, k=0):
    """The k-th paragraph of the page's render of `doc`, citations numbered as the page numbers them."""
    return re.findall(r"<p>[\s\S]*?</p>", pandoc(["-f", "gfm", "-t", "html5", "--no-highlight"], doc))[k]


def edit(doc, i, k=0, old="here", new="there"):
    return rde.apply_edits(doc, [{"i": i, "html": page_paragraph(doc, k).replace(old, new)}])


def test_an_edit_of_a_paragraph_that_cites_a_footnote_keeps_the_note():
    doc = "# T\n\nA here[^1].\n\n[^1]: the note\n"
    out, rep = edit(doc, 1)
    assert rep["skipped"] == []
    assert out == "# T\n\nA there[^1].\n\n[^1]: the note\n"


def test_the_citation_keeps_its_own_label_not_the_page_number():
    doc = "# T\n\nB first[^z].\n\nA here[^note].\n\n[^note]: named\n\n[^z]: zed\n"
    out, rep = edit(doc, 2, k=1)
    assert rep["skipped"] == []
    assert out == doc.replace("A here", "A there")


def test_two_citations_of_one_label_in_a_block_stay_one_label_with_one_definition():
    doc = "# T\n\nA here[^1] b[^1].\n\n[^1]: the note\n"
    out, rep = edit(doc, 1)
    assert rep["skipped"] == []
    assert out == "# T\n\nA there[^1] b[^1].\n\n[^1]: the note\n"


def test_citations_before_the_block_and_in_a_note_number_as_the_page_numbers_them():
    # pandoc numbers each citation in text order; one inside a note's own words gets none
    doc = "# T\n\nB `[^q]` x[^a][^b].\n\nA here[^b] and[^a].\n\n[^a]: one [^b]\n\n[^b]: two\n"
    out, rep = edit(doc, 2, k=1)
    assert rep["skipped"] == []
    assert out == doc.replace("A here", "A there")


def test_a_citation_after_words_in_another_script_maps_to_its_label():
    doc = "# T\n\nÉté — 日本[^x] b.\n\nA here[^y].\n\n[^x]: ex\n\n[^y]: why\n"
    out, rep = edit(doc, 2, k=1)
    assert rep["skipped"] == []
    assert out == doc.replace("A here", "A there")


def test_a_ref_the_document_does_not_number_is_refused_never_an_empty_definition():
    doc = "# T\n\nA here[^1].\n\n[^1]: the note\n"
    frag = page_paragraph(doc).replace("here", "there").replace("#fn1", "#fn7")
    out, rep = rde.apply_edits(doc, [{"i": 1, "html": frag}])
    assert out == doc and rep["skipped"] and rep["changed"] == []


def test_deleting_the_citation_on_the_page_leaves_the_definition_alone():
    doc = "# T\n\nA here[^1].\n\n[^1]: the note\n"
    out, _ = rde.apply_edits(doc, [{"i": 1, "html": "<p>A there.</p>"}])
    assert out == "# T\n\nA there.\n\n[^1]: the note\n"


def test_a_lone_closing_tag_beside_a_footnote_is_still_refused():
    # sheaf #161: the refusal stays as it was
    doc = "# T\n\nA here[^1] </x1>b.\n\n[^1]: the note\n"
    frag = page_paragraph(doc).replace("here", "there").replace("</x1>", "")
    out, rep = rde.apply_edits(doc, [{"i": 1, "html": frag}])
    assert out == doc and rep["skipped"]


def test_a_merged_save_maps_the_ref_against_the_page_version_not_the_file():
    # the file gained a citation above the block since the page rendered: #fn1 is still the page's [^b]
    base = "# T\n\nA here[^b].\n\n[^a]: one\n\n[^b]: two\n"
    cur = "# T\n\nNew[^a] above.\n\nA here[^b].\n\n[^a]: one\n\n[^b]: two\n"
    html = page_paragraph(base).replace("here", "there")
    out, _ = rde.merge_edits(base, cur, [{"i": 1, "html": html}])
    assert out == cur.replace("A here", "A there")
