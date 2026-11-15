"""A table inside a quote or a list, read as pandoc reads it (ticket 87, point 2 of ticket 75).

`parse` must find a comment exactly when pandoc shows it as raw HTML, and a comment written on a cell must be
found again, whatever container marker, tab or nesting stands in front of the row. Every form below is one of
the shapes that the five rounds of PR 307 found by hand; the expected answer is pandoc's, bundled (3.9).
"""
import pytest
from helpers import pandoc

import fuzz_containers as fz
from sheafmd import comments as rdc

# (source with C1 where the comment goes, whether pandoc shows it as a comment)
FORMS = [
    # point 1: a header line that looks like a delimiter row; the cells beyond the table's columns are dropped
    ("> |---|\n> |---|\n> | `p | C1 q` | r |\n", False),
    ("> - |---|\n>   |---|\n>   | `p | C1 q` | r |\n", False),
    ("1. |---|---|\n   |---|---|\n   para `a | C1 b` text\n   |---|\n", True),
    ("> - ---|---\n>   ---|---\n>   | `x | C1 y` | z |\n", True),
    # point 5: a tab after a marker in a quote
    ("> -\t| a `x | b C1 y` |\n>   |---|---|\n", True),
    ("> - | a `x | b C1 y` |\n>    |---|---|\n", True),
    # point 6: a table that opens the item under the item before
    ("- q\n- | a `x | b C1 y` |\n  |---|---|\n", True),
    ("1. q\n2. | a `x | b C1 y` |\n   |---|---|\n", True),
    # point 7: pandoc goes on with the table through a line that opens a container
    ("- | x | y |\n  ---|---\n  - item `a | C1 z` | z\n", True),
    ("> | a |\n> |---|\n> > | `a | C1 b` |\n", False),
    # point 8: a quote opened after a list marker
    ("1. > | a | b |\n  > |---|---|\n  > | `x | C1 y` | y` |\n", False),
    ("-  > | a | b |\n   > |---|---|\n   > | `x | C1 y` | y` |\n", True),
    ("+\t> | a | b |\n   > |---|---|\n   > | `x | C1 y` | y` |\n", False),
    ("- > | a | b |\n  > |---|---|\n  > | `x | C1 y` | y` |\n", True),
    # point 9: a tab after the `>`
    ("> |a|b|\n>\t  |---|---|\n> | `x | C1 y` | y` |\n", False),
    # point 10: a `>` with no space after it
    (">- | a | b |\n>  |---|---|\n>  | `x | C1 y` | y` |\n", False),
    (">10. | a | b |\n>     |---|---|\n>     | `x | C1 y` | y` |\n", True),
    # point 11: a row back at the quote's column closes the table
    ("> - q\n>\n>   | a | b |\n>   |---|---|\n> | `x | C1 y` | y` |\n", False),
    # a code span over two lines in a quote or a list has two ranges: it is code
    ("> | a |\n> |---|\n>\n> `p x\n> y C1 q`\n", False),
    ("- | a |\n  |---|\n\n  `p x\n  y C1 q`\n", False),
    # an indented line after a blank line in an item is code, not a row
    ("- q\n\n  | a | b |\n  |---|---|\n\n      | `x` | y C1 |\n", False),
]


@pytest.mark.parametrize("form, shown", FORMS)
def test_parse_finds_a_comment_in_a_quote_or_a_list_exactly_when_pandoc_shows_it(form, shown):
    md = form.replace("C1", fz.C)
    assert fz.pandoc_sees(pandoc, md) is shown          # the oracle: pandoc's own reading
    assert fz.parse_sees(rdc, md) is shown
    assert fz.parse_sees(rdc, md.replace("\n", "\r\n")) is fz.pandoc_sees(pandoc, md.replace("\n", "\r\n"))


@pytest.mark.parametrize("form, shown", FORMS)
def test_a_comment_written_in_a_quote_or_a_list_is_found_again_or_refused(form, shown):
    md = form.replace("C1", fz.TARGET)
    if fz.TARGET not in pandoc(["-f", "gfm", "-t", "html"], md):
        pytest.skip("pandoc drops this cell: there is no text to select")
    assert fz.write_outcome(rdc, pandoc, md) in ("ok", "refused")


def test_a_row_that_pandoc_reads_is_a_row_wherever_its_header_looks_like_a_delimiter():
    md = "> |---|\n> |---|\n> | `p | q` | r |\n"
    assert rdc.in_table_row(md, md.index("p |"))
    assert rdc.in_table_row(md, md.index("---"))


def test_a_line_that_pandoc_reads_no_cell_on_is_no_row_unless_the_splitter_reads_it_as_one():
    assert not rdc.in_table_row("> some words\n> more words\n", 5)
    assert not rdc.in_table_row("> a | b\n", 3)         # no delimiter row, no table


def test_a_table_in_a_quote_is_read_by_one_pandoc_run_per_block(monkeypatch):
    calls = []
    real = rdc._sourcepos_html
    monkeypatch.setattr(rdc, "_sourcepos_html", lambda block: calls.append(block) or real(block))
    rdc._read_tables.cache_clear()
    md = "> | a | b |\n> |---|---|\n> | `x | %s | y` |\n" % fz.C
    for _ in range(3):
        assert rdc.parse(md).comments
    assert len(calls) == 1


def test_no_pandoc_run_is_made_for_a_block_that_cannot_hold_a_table_or_a_comment(monkeypatch):
    monkeypatch.setattr(rdc, "_sourcepos_html", lambda block: pytest.fail("pandoc was run"))
    rdc._read_tables.cache_clear()
    rdc.parse("> `a | b`\n> text %s\n" % fz.C)                      # no delimiter row
    rdc.parse("> | a | b |\n> |---|---|\n> | `x` | y |\n")          # no comment


# The fuzzer of tests/fuzz_containers.py: random quotes and lists of every marker, tab and nesting, with a
# table in them; pandoc is the oracle. A few seeds here, whole runs with `python tests/fuzz_containers.py SEED N
# BASE_SRC`, which also counts "head wrong where base right" (0 and 0 on seeds 3 and 4, 80 and 100 cases per
# generator). What stays wrong is a block that the splitter cuts at a delimiter row that pandoc does not read as
# the table's (SPEC 10.4): under one case in ten, where main is wrong in one of five.
@pytest.mark.parametrize("seed", ["a", "b"])
def test_the_fuzzer_finds_few_comments_lost_or_invented_in_a_quote_or_a_list(seed):
    res = fz.run(seed, 25, rdc, None, pandoc)
    for name, r in res.items():
        for what in ("parse", "write"):
            assert r[what]["wrong_head"] * 8 <= r[what]["cases"], (name, what, r[what]["shown"][:3])


# ticket 87, point 12: a heading in a quote or a list takes its comment at the end of its words, on its line
@pytest.mark.parametrize("md, quote, head", [
    ("> # head line\n> text\n", "head", "> # head line"),
    ("- # head line\n  text\n", "line", "- # head line"),
    (">\t# head\tline\n>\ttext\n", "head", ">\t# head\tline"),
    ("> - # a `b` c\n>   text\n", "b", "> - # a `b` c"),
    ("1. ## head line ##\n   text\n", "head", "1. ## head line"),
])
def test_a_comment_on_a_heading_in_a_quote_or_a_list_goes_at_the_end_of_its_words_on_one_line(md, quote, head):
    from test_anchoring import sel
    s, e = sel(md, quote)
    out, cid = rdc.add_comment(md, 0, s, e, quote, "why\nmore", "Ada", "2026-11-14T10:00")
    assert out.startswith(head + "<!-- sheaf-comment id=%s" % cid), out
    first = out.split("\n", 1)[0]
    assert first.endswith("-->") or first.endswith("-->" + md.split("\n", 1)[0][len(head):])
    page = pandoc(["-f", "gfm", "-t", "html", "--wrap=none"], out)
    assert "&lt;!--" not in page and "<h" in page
    assert [c.id for c in rdc.parse(out).comments] == [cid]
    again = rdc.reply(out, cid, "a\nb", "Bob", "2026-11-14T11:00")
    assert again.split("\n", 1)[0].count("-->") == 1 and again.count("\n") == out.count("\n")


def test_the_offset_of_a_position_past_the_end_of_the_block_is_the_end_of_the_block():
    off = rdc._offset_fn("abc\ndef")
    assert off(2, 40) == 7 and off(1, 99) == 7


# Round 1 of the review of PR 351: a comment is named by where pandoc puts it, not by its text, which pandoc changes
# (a tab becomes spaces, `\|` becomes `|` in a cell).
def test_a_tab_in_the_body_or_a_reply_of_a_comment_in_a_quoted_cell_does_not_hide_it():
    md = "> | a | b |\n> |---|---|\n> | xx | yy |\n"
    s, e = sel_of(md, "xx")
    out, cid = rdc.add_comment(md, 0, s, e, "xx", "col1\tcol2", "Ada", "2026-11-14T10:00")
    assert [c.id for c in rdc.parse(out).comments] == [cid]
    again = rdc.reply(out, cid, "an\tanswer\nline2", "Bob", "2026-11-14T11:00")
    found = rdc.parse(again).comments
    assert [c.id for c in found] == [cid] and len(found[0].replies) == 1


def test_an_escaped_pipe_in_a_comment_in_a_quoted_cell_does_not_hide_it():
    md = ("> | a | b |\n> |---|---|\n> | xx<!-- sheaf-comment id=c1 by=A at=2026-01-01T00:00 status=open "
          "quote=\"x\" a \\| b --> | yy |\n")
    assert [c.id for c in rdc.parse(md).comments] == ["c1"]


def test_a_heading_ending_in_an_image_takes_its_comment_on_its_line():
    md = "> # head ![img](x.png)\n"
    s, e = sel_of(md, "head")
    out, cid = rdc.add_comment(md, 0, s, e, "head", "why\nmore", "Ada", "2026-11-14T10:00")
    assert out.count("\n") == 1 and "&lt;!--" not in pandoc(["-f", "gfm", "-t", "html"], out)
    assert [c.id for c in rdc.parse(out).comments] == [cid]


def sel_of(md, quote):
    from test_anchoring import sel
    return sel(md, quote)
