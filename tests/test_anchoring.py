"""From a selection in the rendered page to a position in the markdown source.

Offsets count non-whitespace characters of the block's rendered text, so the page
and the server agree whatever whitespace each render happens to put between tags.
"""
import re

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


# ── a comment on words of a heading goes at the end of the heading (ticket 55) ──

HEADINGS = [
    # (markdown, quote, the heading line with the block's place marked)
    ("## Done when\n", "Done", "## Done when|\n"),
    ("## Done when\n", "when", "## Done when|\n"),
    ("## Done when   \n", "Done", "## Done when|   \n"),
    ("## Done when ##\n", "Done", "## Done when| ##\n"),
    ("## C#\n", "C", "## C#|\n"),
    ("# **Done** when\n", "Done", "# **Done** when|\n"),
    ("Done when\n=========\n", "Done", "Done when|\n=========\n"),
    ("Done\nwhen we ship\n---\n", "Done", "Done\nwhen we ship|\n---\n"),
    # A backslash that ends the text would escape the `<` of the block: the block goes before it.
    ("## A\\\n", "A", "## A|\\\n"),
    ("## A \\\n", "A", "## A |\\\n"),
    ("## A\\ ##\n", "A", "## A|\\ ##\n"),
    ("Line A\\\n=======\n", "A", "Line A|\\\n=======\n"),
    ("## A\\\\\n", "A", "## A\\\\|\n"),           # two backslashes are one escaped backslash
]


def comment_on(md, quote):
    s, e = sel(md, quote)
    return rdc.add_comment(md, block=0, start=s, end=e, quote=quote, body="why", by="Ada", at="2026-11-13T10:00")


@pytest.mark.parametrize("md, quote, expect", HEADINGS)
def test_a_comment_on_words_of_a_heading_goes_at_the_end_of_the_heading(md, quote, expect):
    out, cid = comment_on(md, quote)
    raw = out[len(expect.split("|")[0]):out.index("-->") + 3]
    assert raw.startswith("<!-- sheaf-comment id=" + cid) and 'quote="%s"' % quote in raw
    assert out.replace(raw, "|", 1) == expect
    assert rdc.parse(out).comments[0].quote == quote


@pytest.mark.parametrize("md, quote", [(md, quote) for md, quote, _ in HEADINGS])
def test_the_heading_is_whole_for_a_reader_that_drops_the_comment(md, quote):
    out, _ = comment_on(md, quote)
    assert re.sub(r"<!--.*?-->", "", out) == md
    page = pandoc(["-f", "gfm", "-t", "html", "--wrap=none"], out)
    assert page.count("<!--") == 1
    assert re.sub(r"<!--.*?-->", "", page) == pandoc(["-f", "gfm", "-t", "html", "--wrap=none"], md)


def test_a_comment_on_a_paragraph_still_goes_after_the_selection():
    md = "The gap is 52 and more.\n"
    s, e = sel(md, "gap")
    out, _ = rdc.add_comment(md, 0, s, e, "gap", "why", "Ada", "2026-11-13T10:00")
    assert out.startswith("The gap<!-- sheaf-comment")


def test_a_heading_quote_that_is_stale_is_still_refused():
    # The anchor of a heading ignores the selection, but the selection is still checked (SPEC 10.4).
    with pytest.raises(rdc.AnchorError, match="text changed"):
        rdc.add_comment("## Done when\n", 0, 0, 4, "Nope", "why", "Ada", "2026-11-13T10:00")


# ── heading edge cases (ticket 58) ──

@pytest.mark.parametrize("space", ["\u00a0", "\u3000"])
def test_a_heading_with_a_no_break_or_full_width_space_after_the_hashes_takes_a_comment(space):
    # blocks.ATX_RE reads any \s after the hashes as a heading, pandoc reads a paragraph: the
    # heading anchor is None there and add_comment used to add it to the offset (TypeError).
    md = "#%sFoo bar\n" % space
    out, cid = comment_on(md, "Foo")
    assert out.startswith("#%sFoo<!-- sheaf-comment id=%s" % (space, cid))
    assert re.sub(r"<!--.*?-->", "", out) == md


@pytest.mark.parametrize("md", ["### ###\n", "# #\n", "## ##  \n"])
def test_a_heading_that_is_only_hashes_has_no_place_for_a_block(md):
    assert rdc.heading_anchor(md) is None


def test_a_heading_with_an_unclosed_opener_takes_the_block_before_it_and_keeps_every_word():
    md = "# The <!-- marker\n"
    out, cid = comment_on(md, "The")
    assert out.startswith("# The<!-- sheaf-comment id=%s" % cid)
    assert re.sub(r"<!--.*?-->", "", out, count=1) == md
    page = pandoc(["-f", "gfm", "-t", "html", "--wrap=none"], out)
    assert "marker" in page and [c.id for c in rdc.parse(out).comments] == [cid]


def test_an_opener_in_a_code_span_of_a_heading_is_not_an_opener():
    md = "# Use `<!--` here\n"
    out, _ = comment_on(md, "here")
    assert out.startswith("# Use `<!--` here<!-- sheaf-comment")


@pytest.mark.parametrize("md, quote", [("# <!-- marker\n", "marker"), ("## <!-- a b\n", "a")])
def test_a_heading_whose_words_all_follow_an_unclosed_opener_refuses_the_comment(md, quote):
    # A block after the selection would sit inside the opener and close it.
    s, e = sel(md, quote)
    with pytest.raises(rdc.AnchorError):
        rdc.add_comment(md, 0, s, e, quote, "why", "Ada", "2026-11-13T10:00")
