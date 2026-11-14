"""From a selection in the rendered page to a position in the markdown source.

Offsets count non-whitespace characters of the block's rendered text, so the page
and the server agree whatever whitespace each render happens to put between tags.
"""
import re
import time

import pytest
from helpers import pandoc

from sheafmd import comments as rdc
from sheafmd.blocks import split_md_blocks


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


@pytest.mark.parametrize("md", ["### ###\n", "# #\n", "## ##  \n", "## #\n"])
def test_a_heading_that_is_only_hashes_has_no_place_for_a_block(md):
    assert rdc.heading_anchor(md) is None


def test_a_heading_with_an_unclosed_opener_takes_the_block_before_it_and_keeps_every_word():
    md = "# The <!-- marker\n"
    out, cid = comment_on(md, "The")
    assert out.startswith("# The<!-- sheaf-comment id=%s" % cid)
    assert re.sub(r"<!--.*?-->", "", out, count=1) == md
    page = pandoc(["-f", "gfm", "-t", "html", "--wrap=none"], out)
    assert "marker" in page and [c.id for c in rdc.parse(out).comments] == [cid]
    # Every word of the heading is still on the page, in order, and the comment is read once.
    text = re.sub(r"<[^>]+>", " ", page).split()
    assert text[:1] == ["The"] and "marker" in text and text.count("marker") == 1


@pytest.mark.parametrize("md, quote", [("# a <!-- x\n", "a"), ("## Ab cd <!-- x y\n", "Ab")])
def test_an_atx_heading_with_a_word_before_an_unclosed_opener_takes_the_block_before_it(md, quote):
    out, cid = comment_on(md, quote)
    head = md.split(" <!--")[0]
    assert out.startswith("%s<!-- sheaf-comment id=%s" % (head, cid))
    assert re.sub(r"<!--.*?-->", "", out, count=1) == md
    assert [c.id for c in rdc.parse(out).comments] == [cid]


def test_a_comment_on_words_after_an_unclosed_opener_is_written_before_it():
    # Ticket 65, point 3: the documented limit (SPEC 10.4): the page highlights only text before
    # the block, so these words get no highlight, and none of them is lost.
    md = "# The <!-- marker\n"
    out, cid = comment_on(md, "marker")
    assert out.startswith("# The<!-- sheaf-comment id=%s" % cid)
    assert out.endswith(" <!-- marker\n") and re.sub(r"<!--.*?-->", "", out, count=1) == md


def test_a_setext_heading_with_an_unclosed_opener_takes_the_block_before_it():
    md = "The <!-- marker\n==========\n"
    out, cid = comment_on(md, "The")
    assert out.startswith("The<!-- sheaf-comment id=%s" % cid)


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


@pytest.mark.parametrize("md, word", [("## ## ##\n", "##"), ("#  #  #\n", "#"), ("# # #\n", "#")])
def test_a_heading_whose_word_is_made_of_hashes_takes_a_comment(md, word):
    # Ticket 65, point 1: the page shows the word (CommonMark reads the last run as the closing
    # hashes and the first as the text), so it is not an empty heading.
    out, cid = comment_on(md, word)
    assert re.sub(r"<!--.*?-->", "", out, count=1) == md
    assert [c.id for c in rdc.parse(out).comments] == [cid]


def test_a_backtick_in_a_raw_tag_does_not_hide_the_opener_after_it():
    # Ticket 65, point 2: read left to right, the backtick of the tag's attribute opens no code
    # span that runs on to the one after the opener.
    md = "# a <span title='`'>s</span> <!-- b `x`\n"
    out, cid = comment_on(md, "a")
    assert out.startswith("# a <span title='`'>s</span><!-- sheaf-comment id=%s" % cid)
    assert re.sub(r"<!--.*?-->", "", out, count=1) == md
    assert [c.id for c in rdc.parse(out).comments] == [cid]


@pytest.mark.parametrize("para", [
    "\\<b title='`'> word `and` y",          # an escaped `<` opens no tag
    "x <b tè='`'> word `and` y",        # an attribute name is ASCII
    "x <b\u000btitle='`'> word `and` y",     # a vertical tab is no whitespace of a tag
    "x <b\u000ctitle='`'> word `and` y",     # nor a form feed (pandoc, gfm)
    "x <b title='`'\u000c> word `and` y",
])
def test_text_that_only_looks_like_a_tag_does_not_hide_a_comment_from_parse(para):
    # Ticket 65 follow-up (Opus review 1, F1): the backtick in the "tag" opens a code span, as in
    # pandoc, so the block lands inside it on write; parse must find what add_comment wrote, or a
    # second comment reuses its id.
    md = "Intro.\n\n%s\n" % para
    s, e = sel(rdc.split_md_blocks(md)[1].content, "word")
    out, cid = rdc.add_comment(md, 1, s, e, "word", "why", "Ada", "2026-11-14T10:00")
    assert [c.id for c in rdc.parse(out).comments] == [cid]
    _, cid2 = rdc.add_comment(out, 0, 0, 5, "Intro", "again", "Bob", "2026-11-14T10:01")
    assert cid2 != cid


def test_a_tag_after_an_escaped_backslash_is_still_a_tag_and_hides_its_backtick():
    # `\\<b ...>`: the backslash is escaped, so the `<` opens a tag and its backtick opens no span.
    md = "Intro.\n\n\\\\<b title='`'> word `and` y\n"
    s, e = sel(rdc.split_md_blocks(md)[1].content, "word")
    out, cid = rdc.add_comment(md, 1, s, e, "word", "why", "Ada", "2026-11-14T10:00")
    assert [c.id for c in rdc.parse(out).comments] == [cid]
    assert "<code>" not in pandoc(["-f", "gfm", "-t", "html"], out.split("-->")[0].split("<!--")[0])


# ── table cells (ticket 57) ──

def _cells(row):
    """The cells of a row as the GFM reader splits it: at every `|` with no odd run of backslashes before it."""
    return [c.strip() for c in re.split(r"(?<!\\)(?:\\\\)*\|", row.strip())[1:-1]]


TABLES = [
    # (md, quote, text before the block, text of the row after it)
    ("| a | b |\n|---|---|\n| one | two |\n", "n", "| a | b |\n|---|---|\n| one", " | two |\n"),
    ("| a | b |\n|---|---|\n| one two | x |\n", "one", "| a | b |\n|---|---|\n| one two", " | x |\n"),
    ("| a | b |\n|---|---|\n| x | one two |\n", "one", "| a | b |\n|---|---|\n| x | one two", " |\n"),
    ("|a|b|\n|-|-|\n|one|two|\n", "n", "|a|b|\n|-|-|\n|one", "|two|\n"),
    ("| a | b |\n|---|---|\n| one\\|two | x |\n", "one", "| a | b |\n|---|---|\n| one\\|two", " | x |\n"),
    ("| a | b |\n|---|---|\n| `x\\|y` z | q |\n", "z", "| a | b |\n|---|---|\n| `x\\|y` z", " | q |\n"),
    ("| a | b |\n|---|---|\n| `x\\|y` z | q |\n", "x", "| a | b |\n|---|---|\n| `x\\|y` z", " | q |\n"),
    ("| a | b |\n|---|---|\n| one \\\\| two |\n", "one", "| a | b |\n|---|---|\n| one \\\\", "| two |\n"),
    ("| a | b |\n|---|---|\n| one | two\n", "one", "| a | b |\n|---|---|\n| one", " | two\n"),
    ("| a | b |\n|---|---|\n| one | two\n", "two", "| a | b |\n|---|---|\n| one | two", "\n"),
]


@pytest.mark.parametrize("md, quote, before, after", TABLES)
def test_a_comment_on_words_of_a_table_cell_goes_at_the_end_of_the_cell(md, quote, before, after):
    s, e = sel(md, quote)
    out, cid = rdc.add_comment(md, 0, s, e, quote, "why", "Ada", "2026-11-14T10:00")
    assert out.startswith(before + "<!-- sheaf-comment id=%s" % cid) and out.endswith("-->" + after)
    assert re.sub(r"<!--.*?-->", "", out, count=1) == md
    c = rdc.parse(out).comments[0]
    assert c.quote == quote


def test_a_cell_is_whole_for_a_reader_that_compares_cells():
    md = "| a | b |\n|---|---|\n| one two | x |\n"
    s, e = sel(md, "one")
    out, _ = rdc.add_comment(md, 0, s, e, "one", "why", "Ada", "2026-11-14T10:00")
    page = pandoc(["-f", "gfm", "-t", "html", "--wrap=none"], out)
    assert "<td>one two" in page.replace("\n", "") and "one<!--" not in page
    assert page.count("<!--") == 1


def test_a_comment_in_a_cell_of_the_header_row_goes_at_the_end_of_that_cell():
    md = "| alpha beta | b |\n|---|---|\n| x | y |\n"
    s, e = sel(md, "alpha")
    out, cid = rdc.add_comment(md, 0, s, e, "alpha", "why", "Ada", "2026-11-14T10:00")
    assert out.startswith("| alpha beta<!-- sheaf-comment id=%s" % cid)


def test_a_code_span_that_runs_across_cells_does_not_take_the_block_inside_it():
    # Opus review 1, P1: pandoc splits the cells first, parse reads code spans over the whole table, so a
    # block at the end of the cell would sit in a span parse sees and the comment would be lost.
    md = "| a | b |\n|---|---|\n| one `x | y` z |\n"
    s, e = sel(md, "one")
    out, cid = rdc.add_comment(md, 0, s, e, "one", "why", "Ada", "2026-11-14T10:00")
    assert [c.id for c in rdc.parse(out).comments] == [cid]
    assert re.sub(r"<!--.*?-->", "", out, count=1) == md


@pytest.mark.parametrize("cell, quote, expect", [
    ("C:\\ dir\\", "dir", "| C:\\ dir<C>\\ | x |"),       # one backslash would escape the `<`
    ("C:\\ dir\\\\", "dir", "| C:\\ dir\\\\<C> | x |"),    # two are a backslash
])
def test_a_cell_that_ends_in_a_backslash_keeps_the_block_from_being_escaped(cell, quote, expect):
    md = "| a | b |\n|---|---|\n| %s | x |\n" % cell
    s, e = sel(md, quote)
    out, cid = rdc.add_comment(md, 0, s, e, quote, "why", "Ada", "2026-11-14T10:00")
    assert re.sub(r"<!--.*?-->", "<C>", out, count=1).endswith(expect + "\n")
    page = pandoc(["-f", "gfm", "-t", "html", "--wrap=none"], out)
    assert "&lt;!--" not in page and [c.id for c in rdc.parse(out).comments] == [cid]


def test_a_cell_with_an_unclosed_opener_takes_the_block_before_it():
    md = "| a | b |\n|---|---|\n| one | x <!-- open |\n"
    s, e = sel(md, "x")
    out, cid = rdc.add_comment(md, 0, s, e, "x", "why", "Ada", "2026-11-14T10:00")
    assert out.startswith("| a | b |\n|---|---|\n| one | x<!-- sheaf-comment id=%s" % cid)
    assert re.sub(r"<!--.*?-->", "", out, count=1) == md
    assert [c.id for c in rdc.parse(out).comments] == [cid]


# ── ticket 66: what is left of PR 286 ──

def _slow(md):
    """Seconds `heading_anchor` takes for `md` (the scan, not the pandoc projection that anchoring
    also pays for, which a loaded laptop makes slow)."""
    t = time.perf_counter()
    rdc.heading_anchor(md)
    return time.perf_counter() - t


@pytest.mark.parametrize("heading", [
    "Title\n=====\n",                                                # setext: the text is the lines above
    "# Title\n",
])
def test_a_long_heading_full_of_tags_before_an_unclosed_opener_is_read_in_linear_time(heading):
    # Point 1: 9 KB of tags then `<!--` took 1.6 s, 36 KB took 21.8 s (each pass searched on from
    # the position again), and the hub is blocked while a comment is anchored.
    tags = "<b>x</b> " * 1000
    md = heading.replace("Title", "Title " + tags + "<!-- end", 1)
    assert _slow(md) < 0.3
    md4 = heading.replace("Title", "Title " + tags * 4 + "<!-- end", 1)
    assert _slow(md4) < 0.5


def test_an_ordinary_closed_comment_owns_its_backtick():
    # Point 2: the backtick in `<!-- todo `x -->` opens no span that runs on to the one in `code`,
    # so the comment written on "word" is found by parse.
    md = "See <!-- todo `x --> the word and use `code` here.\n"
    out, cid = comment_on(md, "word")
    assert [c.id for c in rdc.parse(out).comments] == [cid]
    assert rdc._mask_code(md).count("`") == 1          # only `code` is blanked, the comment's own backtick stays


@pytest.mark.parametrize("opener", ["<!-->", "<!--->"])
def test_an_empty_comment_opener_is_a_whole_comment_not_an_unclosed_one(opener):
    # Point 3: CommonMark, pandoc and the list (hub/the_list.py) read it as a whole comment, so it
    # owns its backtick and nothing is unclosed. (The share copy refuses a page with one in a
    # heading, before and after this change: render.COMMENT_RE does not know it.)
    assert rdc._unclosed_opener(f"a {opener} b") == -1
    assert rdc._mask_code(f"a {opener} `x` b <!-- c `y` -->") == f"a {opener}     b <!-- c `y` -->"
    md = f"# The {opener} end\n"
    assert rdc.heading_anchor(md) == len(f"# The {opener} end")
    assert "<!--" in pandoc(["-f", "gfm", "-t", "html"], md)    # pandoc reads a comment there too


@pytest.mark.parametrize("para", [
    "<b title='`'> word `and` y",           # a real tag owns its backtick
    "</b > word `x` y",
    "<b title='`' /> word `and` y",
    "<b title=a`b> word `and` y",           # an unquoted value may not hold a backtick: no tag
    "<b title=`a`> word `and` y",
    "<b a='1'b='`'> word `and` y",          # no space between attributes: no tag
    "<1b title='`'> word `and` y",          # a tag name starts with a letter
    "<b title='`' title2> word `and` y",
    "<b =x='`'> word `and` y",
    "<!-- a `x --> word `and` y",           # a comment owns its backtick
    "<!--> word `and` y",
    "<!---> word `and` y",
    "\\<!-- a `x --> word `and` y",         # an escaped opener opens nothing
])
def test_parse_reads_text_that_looks_like_a_tag_or_comment_as_pandoc_does(para):
    # Point 5a: whether a backtick is code in pandoc is whether `_mask_code` blanks it.
    para = "x " + para         # at the start of a line `<!--` and a tag begin an HTML block, which is no inline text
    code_in_pandoc = "<code>" in pandoc(["-f", "gfm", "-t", "html"], para + "\n")
    assert (rdc._mask_code(para) != para) == code_in_pandoc


# ── ticket 66, Opus review 1 ──

def test_code_after_an_unclosed_ordinary_opener_is_not_a_broken_comment():
    # b2: pandoc reads a bare `<!--` as text and the backticks after it as code.
    md = "A bare <!-- opens a comment; a note starts with `<!-- sheaf-comment id=c1`.\n"
    assert rdc.parse(md).malformed == []
    assert rdc._mask_code("a <!-- b `x` c") == "a <!-- b     c"


def test_a_block_of_many_unclosed_openers_is_read_in_linear_time():
    # Opus narrow review: every later opener repeated the failed search for `-->`, 597 ms at 80 KB.
    md = "a " + "<!-- x " * 12000 + " `z`\n"
    t = time.perf_counter()
    assert rdc._mask_code(md).count("`") == 0
    assert rdc._unclosed_opener(md) == 2
    assert time.perf_counter() - t < 0.3


# ── ticket 68: what is left of PR 288 ──

@pytest.mark.parametrize("opener", ["<!-->", "<!--->"])
def test_a_cell_with_an_empty_comment_takes_a_comment_on_its_words(opener):
    # Point 1: pandoc reads the opener as a whole, empty comment, so the cell has a place (ticket 66).
    md = "| a | b |\n|---|---|\n| %s w | y |\n" % opener
    s, e = sel(md, "w")
    out, cid = rdc.add_comment(md, 0, s, e, "w", "why", "Ada", "2026-11-14T10:00")
    assert out.startswith("| a | b |\n|---|---|\n| %s w<!-- sheaf-comment id=%s" % (opener, cid))
    assert [c.id for c in rdc.parse(out).comments] == [cid]


HEAD3 = "| h | i | j |\n|---|---|---|\n"


@pytest.mark.parametrize("row, quote, before", [
    ("| a ` b | one two | c ` |", "one", "| a ` b | one two"),            # backticks across cells are no code
    ("| a \\` b z | c |\n| d \\` e | f |", "b", "| a \\` b z"),         # nor are escaped ones across rows
])
def test_a_backtick_in_another_cell_does_not_hide_a_comment_from_parse(row, quote, before):
    # Point 3: pandoc splits the cells first, so a code span cannot run from one cell or row to another.
    md = HEAD3 + row + "\n"
    s, e = sel(md, quote)
    out, cid = rdc.add_comment(md, 0, s, e, quote, "why", "Ada", "2026-11-14T10:00")
    assert out.startswith(HEAD3 + before + "<!-- sheaf-comment id=%s" % cid)
    assert [c.id for c in rdc.parse(out).comments] == [cid]
    assert re.sub(r"<!--.*?-->", "", out, count=1) == md


def test_a_code_span_inside_one_cell_still_hides_a_comment_written_in_it_from_nothing():
    md = HEAD3 + "| `a | b` | c | d |\n"
    assert rdc.parse(md.replace("| c |", "| c <!-- sheaf-comment id=c1 by=A at=2026-11-14T10:00 status=open quote=\"c\" -->|")).comments[0].id == "c1"
    md = HEAD3 + "| x `<!-- sheaf-comment id=c1 by=A at=2026-11-14T10:00 status=open quote=\"c\" -->` | c | d |\n"
    assert rdc.parse(md).comments == []                # inside one cell's code, an example


@pytest.mark.parametrize("prefix, para", [("> ", ""), ("- ", ""), ("  ", "- x\n\n"), ("> > ", ""), ("1. ", "")])
def test_a_table_in_a_quote_or_a_list_takes_a_one_line_comment_at_the_end_of_the_cell(prefix, para):
    # Point 4: the block is a quote or a list, not a table; a comment of several lines would cut the row.
    rows = ["| a | b |", "|---|---|", "| one two | y |"]
    pad = " " * len(prefix) if prefix.strip() in ("-", "1.") else prefix
    md = para + prefix + rows[0] + "\n" + "".join(pad + r + "\n" for r in rows[1:])
    s, e = sel(md, "one", 0) if not para else sel(md, "one")
    out, cid = rdc.add_comment(md, 0, s, e, "one", "why\nmore", "Ada", "2026-11-14T10:00")
    assert re.sub(r"<!--.*?-->", "<C>", out, count=1).endswith("| one two<C> | y |\n"), out
    assert out.count("\n") == md.count("\n")
    page = pandoc(["-f", "gfm", "-t", "html", "--wrap=none"], out)
    assert page.count("<table>") == 1 and "&lt;!--" not in page and "<td>one two<!--" in page
    assert [c.id for c in rdc.parse(out).comments] == [cid]
    again = rdc.reply(out, cid, "and more\nlines", "Bob", "2026-11-14T11:00")
    assert again.count("\n") == md.count("\n")         # a reply keeps the comment on the row's line
    assert pandoc(["-f", "gfm", "-t", "html", "--wrap=none"], again).count("<table>") == 1


def test_a_paragraph_in_a_quote_that_holds_a_table_still_takes_a_comment_of_several_lines():
    md = "> some words here\n>\n> | a | b |\n> |---|---|\n> | one | y |\n"
    s, e = sel(md, "words")
    out, cid = rdc.add_comment(md, 0, s, e, "words", "why\nmore", "Ada", "2026-11-14T10:00")
    assert "words<!-- sheaf-comment id=%s" % cid in out and "\n-->" in out
    assert pandoc(["-f", "gfm", "-t", "html", "--wrap=none"], out).count("<table>") == 1


def test_a_row_with_no_pipe_after_a_table_is_a_paragraph_as_pandoc_reads_it():
    # Point 5: cmark-gfm would read the line as a row; pandoc, which renders the file, ends the table.
    md = "| a | b |\n|---|---|\n| one | two |\nlazy row\n"
    assert [b.kind for b in split_md_blocks(md)] == ["table", "para"]
    page = pandoc(["-f", "gfm", "-t", "html", "--wrap=none"], md)
    assert page.count("<tr>") == 2 and "<p>lazy row</p>" in page


@pytest.mark.parametrize("md", [
    "> | one a | b |\n> |---|---|\n> | x | y |\n",
    "- x\n\n  | one a | b |\n  |---|---|\n  | p | y |\n",
])
def test_a_comment_on_the_header_of_a_table_in_a_quote_or_a_list_stays_on_the_row(md):
    s, e = sel(md, "one")
    out, cid = rdc.add_comment(md, 0, s, e, "one", "why\nmore", "Ada", "2026-11-14T10:00")
    assert re.sub(r"<!--.*?-->", "<C>", out, count=1).count("one a<C> | b |") == 1, out
    assert [c.id for c in rdc.parse(out).comments] == [cid] and out.count("\n") == md.count("\n")


def test_a_cell_in_a_code_span_that_runs_across_cells_of_a_quoted_table_is_refused_not_lost():
    md = "> | a | b |\n> |---|---|\n> | `x | one | z` | q |\n"
    s, e = sel(md, "one")
    with pytest.raises(rdc.AnchorError):
        rdc.add_comment(md, 0, s, e, "one", "why", "Ada", "2026-11-14T10:00")
