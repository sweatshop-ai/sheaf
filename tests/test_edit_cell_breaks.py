"""Enter in a table cell: which breaks end their cell and go, and which show a line (ticket 137).

A break after which the cell shows nothing is the placeholder the browser keeps at the end of a line and
goes. Python's `str.strip()` also strips a no-break space, so a typed one counted as nothing.
"""
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
