"""Enter in a table cell: which breaks end their cell and go, and which show a line (ticket 137).

A break after which the cell shows nothing is the placeholder the browser keeps at the end of a line and
goes. Python's `str.strip()` also strips a no-break space, so a typed one counted as nothing.
"""
import re

import pytest

from helpers import pandoc
from sheafmd import edit as rde

SRC = "| a | b |\n|---|---|\n| x | y |"


def saved_cell(new, src=SRC):
    html = pandoc(["-f", "gfm", "-t", "html5", "--no-highlight"], src).strip().replace(">x<", ">" + new + "<")
    out, rep = rde.apply_edits("# Title\n\n" + src + "\n", [{"i": 1, "html": html}])
    assert rep["skipped"] == []
    return out.splitlines()[-1]


def test_a_single_break_at_the_end_of_a_cell_goes():
    assert saved_cell("x<br>").startswith("| x ") and "<br>" not in saved_cell("x<br>")


def test_the_no_break_space_enter_leaves_at_the_cut_goes_with_the_break():
    row = saved_cell("x<br> ")
    assert "<br>" not in row and " " not in row


def test_a_no_break_space_typed_after_a_break_keeps_the_break():
    row = saved_cell("x<br>  ")
    assert "<br>" in row and row.count(" ") == 1


def test_a_break_between_words_is_kept():
    assert "x<br>z" in saved_cell("x<br>z")


def saved_table(html, src):
    out, rep = rde.apply_edits("# Title\n\n" + src + "\n", [{"i": 1, "html": html}])
    assert rep["skipped"] == []
    return out[len("# Title\n\n"):]


def test_a_table_with_a_backslash_stays_a_pipe_table_with_the_cut_in_its_cell():
    src = "| a | b |\n|---|---|\n| x | a\\\\b |"
    html = pandoc(["-f", "gfm", "-t", "html5", "--no-highlight"], src).strip().replace(">x<", ">x<br>\u00a0<")
    out = saved_table(html, src)
    assert "<table" not in out and "<br" not in out


def test_a_break_in_code_in_a_cell_stays_a_pipe_table():
    src = "| a |\n|---|\n| x |"
    html = pandoc(["-f", "gfm", "-t", "html5", "--no-highlight"], src).strip().replace(">x<", "><code>x<br>\u00a0</code><")
    assert "<table" not in saved_table(html, src)


def test_enter_inside_code_in_a_cell_splits_the_code_and_stays_a_pipe_table():
    src = "| a |\n|---|\n| x |"
    html = pandoc(["-f", "gfm", "-t", "html5", "--no-highlight"], src).strip().replace(">x<", "><code>red on<br>xes</code><")
    out = saved_table(html, src)
    assert "<table" not in out
    assert out.splitlines()[-1].replace(" ", "") == "|`redon`<br>`xes`|"


def test_enter_inside_code_among_words_in_a_cell_keeps_the_words():
    src = "| a |\n|---|\n| x |"
    html = pandoc(["-f", "gfm", "-t", "html5", "--no-highlight"], src).strip().replace(">x<", ">go <code>red<br>x</code> now<")
    out = saved_table(html, src)
    assert "<table" not in out
    assert "go `red`<br>`x` now" in out.splitlines()[-1]


def test_two_breaks_inside_code_in_a_cell_make_three_spans():
    src = "| a |\n|---|\n| x |"
    html = pandoc(["-f", "gfm", "-t", "html5", "--no-highlight"], src).strip().replace(">x<", "><code>a<br>b<br>c</code><")
    out = saved_table(html, src)
    assert "<table" not in out and "`a`<br>`b`<br>`c`" in out.replace(" ", "")


def test_a_cut_after_a_backslash_the_page_text_keeps_goes_with_the_break():
    # A backslash before `*` is an escape the text has to keep, so `_text_backslashes` takes it before the table goes
    # to `_cell_breaks`; `_without_placeholder_breaks` has to judge the table the same way.
    row = saved_cell("x\\*<br>\u00a0")
    assert "<br>" not in row and "\u00a0" not in row and row.startswith("| x\\\\\\* ")


def test_two_no_break_spaces_after_a_backslash_keep_the_break_and_leave_one():
    row = saved_cell("x\\*<br>\u00a0\u00a0")
    assert "<br>" in row and row.count("\u00a0") == 1


# A table `_cell_breaks` does not take (a backslash or a shortcode left in it) goes as raw HTML, and its typed break
# with it: two no-break spaces after a break are Enter's cut and a typed one, which shows (ticket 182 I).
def test_two_no_break_spaces_in_a_table_with_a_backslash_keep_the_break():
    src = "| a | b |\n|---|---|\n| x | a\\b |"
    html = pandoc(["-f", "gfm", "-t", "html5", "--no-highlight"], src).strip().replace(">x<", ">x<br>\u00a0\u00a0<")
    out = saved_table(html, src)
    assert "<table" in out and "x<br />" in out and out.count("\u00a0") == 1 and "a\\b" in out


def test_two_no_break_spaces_in_a_table_with_a_shortcode_keep_the_break():
    src = "| a | b |\n|---|---|\n| x | `:smile:` |"
    html = pandoc(["-f", "gfm", "-t", "html5", "--no-highlight"], src).strip().replace(">x<", ">x<br>\u00a0\u00a0<")
    out = saved_table(html, src)
    assert "<table" in out and "x<br />" in out and out.count("\u00a0") == 1 and ":smile:" in out


def test_one_no_break_space_after_a_break_at_the_end_of_bold_in_a_table_with_a_backslash_goes_with_it():
    src = "| a | b |\n|---|---|\n| x | a\\b |"
    html = pandoc(["-f", "gfm", "-t", "html5", "--no-highlight"], src).strip().replace(">x<", "><b>x<br></b>\u00a0<")
    out = saved_table(html, src)
    assert "<table" not in out and "<br" not in out


# Ticket 183 AF: Enter at the end of code that the cell's words go on after is a break in the cell, not the code's.
@pytest.mark.parametrize("cell", ["<code>red<br></code> now", "<code>red<br> </code> now",
                                  "<code>red <br></code> now"])
def test_enter_at_the_end_of_code_among_words_in_a_cell_stays_a_pipe_table(cell):
    src = "| a |\n|---|\n| x |"
    html = pandoc(["-f", "gfm", "-t", "html5", "--no-highlight"], src).strip().replace(">x<", ">" + cell + "<")
    out = saved_table(html, src)
    assert "<table" not in out
    row = out.splitlines()[-1]
    assert re.search(r"`red\s?`<br>\s*now", row), row


# What a save wrote for that cell before 183 AF: the whole table as raw HTML. It still reads as the same cell, and an
# edit elsewhere in the page leaves it as it is.
OLD_AF_TABLE = ('<table>\n<colgroup>\n<col style="width: 100%" />\n</colgroup>\n<thead>\n<tr>\n<th>a</th>\n</tr>\n'
                '</thead>\n<tbody>\n<tr>\n<td><code>red</code><br />\nnow</td>\n</tr>\n</tbody>\n</table>\n')


def test_the_raw_table_a_save_wrote_before_reads_as_the_cell_the_pipe_table_now_holds():
    def cell(md):
        html = pandoc(["-f", "gfm", "-t", "html5", "--no-highlight"], md)
        return re.sub(r"\s+", " ", re.search(r"<td>(.*?)</td>", html, re.S).group(1)).replace("<br />", "<br>")

    src = "| a |\n|---|\n| x |"
    html = pandoc(["-f", "gfm", "-t", "html5", "--no-highlight"], src).strip().replace(">x<", "><code>red<br></code> now<")
    assert cell(OLD_AF_TABLE) == cell(saved_table(html, src)) == "<code>red</code><br> now"


def test_the_raw_table_a_save_wrote_before_stays_as_it_is_when_another_block_is_edited():
    doc = "# Title\n\n" + OLD_AF_TABLE + "\nwords here\n"
    out, rep = rde.apply_edits(doc, [{"i": 2, "html": "<p>words there</p>"}])
    assert rep["skipped"] == []
    assert out == doc.replace("here", "there")


def test_enter_twice_at_the_end_of_code_among_words_in_a_cell_leaves_the_words_out_of_the_code():
    src = "| a |\n|---|\n| x |"
    html = pandoc(["-f", "gfm", "-t", "html5", "--no-highlight"], src).strip().replace(">x<", "><code>red<br><br></code> now<")
    out = saved_table(html, src)
    assert "<table" not in out
    row = out.splitlines()[-1]
    assert re.search(r"`red`<br><br>\s*now\s*\|$", row), row
