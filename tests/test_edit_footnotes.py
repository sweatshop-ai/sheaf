"""A page edit of a paragraph that cites a footnote keeps the note (sheaf #163).

The page shows a citation as pandoc's `<a href="#fnN" class="footnote-ref">`, numbered by its place among
the document's citations, while the source names it by its label (`[^note]`). Pandoc's HTML reader takes that
link for a footnote with no words and writes an empty definition beside the citation, which the render shows
in place of the note. The save puts the source's label back instead. Fragments are built the way the page
builds them: the document rendered by pandoc, the block's paragraph taken from it, one word changed.
"""
import re

import pytest

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
    assert out == doc and rep["skipped"] == [(1, "block holds raw HTML the edit cannot keep; edit it in the .md")]


def test_a_merged_save_maps_the_ref_against_the_page_version_not_the_file():
    # the file gained a citation above the block since the page rendered: #fn1 is still the page's [^b]
    base = "# T\n\nA here[^b].\n\n[^a]: one\n\n[^b]: two\n"
    cur = "# T\n\nNew[^a] above.\n\nA here[^b].\n\n[^a]: one\n\n[^b]: two\n"
    html = page_paragraph(base).replace("here", "there")
    out, _ = rde.merge_edits(base, cur, [{"i": 1, "html": html}])
    assert out == cur.replace("A here", "A there")


def test_a_merged_save_refuses_a_ref_the_page_version_does_not_number_though_the_file_does():
    # #fn2 is nothing in the base; the file's second citation must not lend it a label
    base = "# T\n\nA here[^b].\n\n[^a]: one\n\n[^b]: two\n"
    cur = "# T\n\nNew[^a] above.\n\nA here[^b].\n\n[^a]: one\n\n[^b]: two\n"
    html = page_paragraph(base).replace("here", "there").replace("#fn1", "#fn2")
    out, rep = rde.merge_edits(base, cur, [{"i": 1, "html": html}])
    assert out == cur and rep["skipped"]


def test_a_label_the_page_sends_is_not_trusted():
    doc = "# T\n\nA here[^1].\n\n[^1]: the note\n"
    frag = page_paragraph(doc).replace("here", "there").replace("<a ", '<a data-rd-note="forged" ', 1)
    out, rep = rde.apply_edits(doc, [{"i": 1, "html": frag}])
    assert out == "# T\n\nA there[^1].\n\n[^1]: the note\n" and rep["skipped"] == []


def test_a_citation_in_a_tight_list_item_keeps_its_label():
    doc = "# T\n\n- A here[^n].\n- B\n\n[^n]: the note\n"
    page = pandoc(["-f", "gfm", "-t", "html5", "--no-highlight"], doc)
    html = re.search(r"<ul>[\s\S]*?</ul>", page).group(0).replace("here", "there")
    out, rep = rde.apply_edits(doc, [{"i": 1, "html": html}])
    assert rep["skipped"] == []
    assert out == doc.replace("A here", "A there")


def test_a_label_with_a_space_keeps_its_label():
    doc = "# T\n\nA here[^a b].\n\n[^a b]: the note\n"
    out, rep = edit(doc, 1)
    assert rep["skipped"] == []
    assert out == doc.replace("A here", "A there")


def test_a_save_that_changes_a_blocks_citations_makes_the_page_reload_onto_the_new_numbers():
    # Opus review 1, P1: the page kept #fn2 for P2 after its own save took P1's citation away; the next
    # save then read #fn2 in a text where it is [^c]. The remap makes the page reload (and merge until then).
    doc = "# T\n\nP1 has a[^a].\n\nP2 has b[^b].\n\nP3 has c[^c].\n\n[^a]: note A\n\n[^b]: note B\n\n[^c]: note C\n"
    p1, p2 = page_paragraph(doc, 0), page_paragraph(doc, 1)
    text1, rep1 = rde.apply_edits(doc, [{"i": 1, "html": re.sub(r'<a href="#fn1"[\s\S]*?</a>', "", p1)}])
    assert text1 == doc.replace("a[^a].", "a.") and rep1["remap"]
    # until the reload, the page keeps the hash of the text it shows, so its next save is merged against it
    text2, _ = rde.merge_edits(doc, text1, [{"i": 2, "html": p2.replace("has b", "has bb")}])
    assert text2 == text1.replace("has b[^b]", "has bb[^b]")


def test_a_save_that_keeps_a_blocks_citations_does_not_reload_the_page():
    doc = "# T\n\nA here[^1].\n\n[^1]: the note\n"
    _, rep = edit(doc, 1)
    assert rep["remap"] is False


def test_a_mounted_pages_ref_keeps_its_label():
    # Opus review 1, P2: mount.js gives every fragment link its own prefix (`u-`)
    doc = "# T\n\nB first[^z].\n\nA here[^note].\n\n[^note]: named\n\n[^z]: zed\n"
    frag = page_paragraph(doc, 1).replace("here", "there").replace('href="#fn', 'href="#u-fn')
    out, rep = rde.apply_edits(doc, [{"i": 2, "html": frag}])
    assert rep["skipped"] == [] and out == doc.replace("A here", "A there")


def test_a_tab_before_a_citation_does_not_shift_it_onto_another_label():
    # Opus review 1, P3: pandoc's columns count a tab to the next stop of 4; [^u] has no definition, so is words
    doc = "# T\n\na\ta\t[^p][^q][^u] here.\n\n[^p]: note P\n\n[^q]: note Q\n"
    out, rep = edit(doc, 1)
    # pandoc writes the tabs as spaces and the undefined [^u] as words, as it does without a footnote
    assert rep["skipped"] == [] and out == doc.replace("a\ta\t[^p][^q][^u] here", "a a [^p][^q]\\[^u\\] there")


def test_a_label_with_a_double_quote_beside_raw_inline_html_keeps_its_label():
    doc = '# T\n\nA <kbd>K</kbd> here[^a"b].\n\n[^a"b]: note\n'
    out, rep = edit(doc, 1)
    assert rep["skipped"] == [] and out == doc.replace("A <kbd>K</kbd> here", "A <kbd>K</kbd> there")


def test_a_pandoc_run_that_failed_is_not_kept_for_the_next_save(monkeypatch):
    # Opus review 2, P3: a timeout once must not refuse every later save against that text
    doc = "# T\n\nA here[^1].\n\n[^1]: the note, timed out once\n"
    real = rde._pandoc.run
    monkeypatch.setattr(rde._pandoc, "run", lambda args, text: rde._pandoc.subprocess.CompletedProcess(args, 124, "", "timeout")
                        if "gfm+sourcepos" in args else real(args, text))
    assert edit(doc, 1)[1]["skipped"]
    monkeypatch.setattr(rde._pandoc, "run", real)
    out, rep = edit(doc, 1)
    assert rep["skipped"] == [] and out == doc.replace("A here", "A there")


@pytest.mark.parametrize("tag", ["code", "samp", "tt", "var"])
def test_a_ref_inside_code_is_refused(tag):
    # Opus review 2 and 3, P3: written as code text, the citation is no longer numbered, and nothing would remap
    doc = "# T\n\nA here[^a] b.\n\n[^a]: note\n"
    frag = page_paragraph(doc).replace("here", f"<{tag}>there").replace("</a>", f"</a></{tag}>")
    out, rep = rde.apply_edits(doc, [{"i": 1, "html": frag}])
    assert out == doc and rep["skipped"]
