"""From a selection in the rendered page to a position in the markdown source.

Offsets count non-whitespace characters of the block's rendered text, so the page
and the server agree whatever whitespace each render happens to put between tags.
"""
import pytest
from helpers import pandoc

from sheafmd import comments as rdc


def html(md):
    return pandoc(["-f", "gfm", "-t", "html"], md)


def sel(block, quote, occurrence=0):
    """Offsets of `quote` in the block's projection, as the page would send them."""
    proj = rdc.projection(block).text
    q = "".join(quote.split())
    i = -1
    for _ in range(occurrence + 1):
        i = proj.index(q, i + 1)
    return i, i + len(q)


@pytest.mark.parametrize("block, quote, expect", [
    ("The gap is 52 and more.\n", "gap", "The gap| is 52 and more.\n"),
    ("The gap is **52%** and it matters.\n", "The gap is 52%", "The gap is **52%**| and it matters.\n"),
    ("See [the report](http://x.y/z) now.\n", "the report", "See [the report](http://x.y/z)| now.\n"),
    ("Salt &amp; pepper.\n", "Salt &", "Salt &amp;| pepper.\n"),
    ("## A heading here\n", "heading", "## A heading| here\n"),
    ("| A | B |\n|---|---|\n| cell **b** | x |\n", "cell b", "| A | B |\n|---|---|\n| cell **b**| | x |\n"),
    ("The gap is 52.\n", "ga", "The ga|p is 52.\n"),
    ("- one\n- two items\n", "two", "- one\n- two| items\n"),
    ("Città è **bello** qui.\n", "bello", "Città è **bello**| qui.\n"),
    ("Line one\nline two.\n", "one line", "Line one\nline| two.\n"),
])
def test_insertion_point(block, quote, expect):
    s, e = sel(block, quote)
    at = rdc.anchor_point(block, s, e, quote)
    assert block[:at] + "|" + block[at:] == expect


def test_selection_ending_on_a_plain_word_inside_bold_stays_inside_it():
    block = "The gap is **52%** here.\n"
    s, e = sel(block, "52")
    at = rdc.anchor_point(block, s, e, "52")
    assert block[:at] == "The gap is **52"
    assert "<strong>52<!-- x -->%</strong>" in html(block[:at] + "<!-- x -->" + block[at:])


@pytest.mark.parametrize("block, quote, expect", [
    ("Run `abcdef` now.\n", "Run abc", "Run `abcdef`| now.\n"),
    ("A **bold `code` tail** end.\n", "A bold co", "A **bold `code`| tail** end.\n"),
    ("See [`the report`](http://x.y/z) now.\n", "See the rep", "See [`the report`|](http://x.y/z) now.\n"),
    ("Use `a_b` and `c`.\n", "Use a_", "Use `a_b`| and `c`.\n"),
])
def test_selection_ending_inside_a_formatted_run_goes_at_the_end_of_that_run(block, quote, expect):
    # SPEC 10.4 (D24): a selection ending inside a formatted run puts the comment at the
    # end of that run; it used to raise AnchorError("ends inside a formatted word").
    s, e = sel(block, quote)
    at = rdc.anchor_point(block, s, e, quote)
    assert block[:at] + "|" + block[at:] == expect


def test_add_comment_on_a_selection_ending_inside_inline_code_lands_after_the_code():
    md = "Run `abcdef` now.\n"
    s, e = sel(md, "Run abc")
    md2, cid = rdc.add_comment(md, block=0, start=s, end=e, quote="Run abc", body="why",
                               by="Ada", at="2026-10-23T10:00")
    assert md2.startswith("Run `abcdef`<!-- sheaf-comment id=" + cid)
    assert "<code>abcdef</code><!-- sheaf-comment" in html(md2)


def test_quote_that_does_not_match_the_offsets_is_refused():
    block = "The gap is 52.\n"
    with pytest.raises(rdc.AnchorError, match="select it again"):
        rdc.anchor_point(block, 0, 3, "gap")


def test_existing_comment_is_not_part_of_the_text():
    c = rdc.Comment(id="c1", by="T", at="2026-01-01T00:00", quote="gap", body="note")
    block = "The gap" + rdc.format(c, one_line=False) + " is 52 and more.\n"
    s, e = sel(block, "52")
    at = rdc.anchor_point(block, s, e, "52")
    assert block[at:] == " and more.\n"


def test_add_comment_renders_invisibly_after_its_text():
    md = "# Title\n\nThe gap is **52%** and it matters.\n\n| A | B |\n|---|---|\n| cell | x |\n"
    s, e = sel("The gap is **52%** and it matters.\n", "The gap is 52%")
    md2, cid = rdc.add_comment(md, block=1, start=s, end=e, quote="The gap is 52%",
                               body="Source?\n\n- old figure", by="Ada", at="2026-09-22T10:00")
    assert cid == "c1"
    out = html(md2)
    assert "<strong>52%</strong><!-- sheaf-comment id=c1" in out
    assert "old figure" not in out.split("<!--")[0] + out.split("-->")[-1]
    s, e = sel("| A | B |\n|---|---|\n| cell | x |\n", "cell")
    md3, cid2 = rdc.add_comment(md2, block=2, start=s, end=e, quote="cell",
                                body="a | b", by="T", at="2026-09-22T10:01")
    assert cid2 == "c2"
    assert "<td>cell<!-- sheaf-comment id=c2" in html(md3)
    # The table was not reformatted: comments are inserted, not round-tripped.
    assert "| A | B |\n|---|---|\n| cell<!--" in md3
    got = rdc.parse(md3).by_id("c2")
    assert got.body == "a | b" and got.quote == "cell"


def test_add_comment_refuses_code_and_locked_blocks():
    md = "Para.\n\n```\ncode here\n```\n"
    with pytest.raises(rdc.AnchorError, match="code"):
        rdc.add_comment(md, block=1, start=0, end=4, quote="code", body="x", by="T",
                        at="2026-09-22T10:00")


def test_find_quote_in_document_uses_the_projection():
    md = "Intro.\n\nThe gap is **52%** here.\n\nThe gap is small.\n"
    assert rdc.find_quote(md, "The gap is 52%")[0] == 1
    with pytest.raises(rdc.AnchorError, match="2 places"):
        rdc.find_quote(md, "The gap is")
    with pytest.raises(rdc.AnchorError, match="does not occur"):
        rdc.find_quote(md, "nowhere")


def test_a_task_list_box_is_not_text():
    # pandoc's sourcepos HTML writes a task box as a ☐ or ☒ character; the page
    # shows a checkbox, which has no text. Counted on one side only, it shifted every
    # selection after a box and the reader was told to select the text again
    # (2026-10-01, three checklist pages, comment-400).
    block = "- [ ] Open the page.\n- [x] Paste the key here.\n"
    page_text = "Openthepage.Pastethekeyhere."
    assert rdc.projection(block).text == page_text
    i = page_text.index("Pastethekey")
    at = rdc.anchor_point(block, i, i + len("Pastethekey"), "Paste the key")
    assert block[:at].endswith("Paste the key")


def test_a_box_typed_in_the_text_is_still_text():
    assert rdc.projection("Tick ☐ when done.\n").text == "Tick☐whendone."
    assert rdc.projection("- ☐ is a box\n").text == "☐isabox"
