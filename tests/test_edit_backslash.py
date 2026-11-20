"""A page edit keeps the backslashes the reader typed (ticket 137).

Pandoc's gfm writer leaves a backslash bare, so `a\\b` on the page was written as `a\\b` and read back as one
backslash, and a backslash before a character the writer escapes swallowed that character.
"""
import pytest

from helpers import pandoc
from sheafmd import edit as rde


def page_fragment(block_md):
    return pandoc(["-f", "gfm", "-t", "html5", "--no-highlight"], block_md).strip()


def saved(block_md, old="here", new="there"):
    doc = "# Title\n\n" + block_md + "\n"
    out, rep = rde.apply_edits(doc, [{"i": 1, "html": page_fragment(block_md).replace(old, new)}])
    assert rep["skipped"] == []
    return out[len("# Title\n\n"):]


@pytest.mark.parametrize("src", [
    r"a \\ b here",
    r"a\\\\b here",
    r"a\\\* here",
    r"c\\\_d here",
    r"a\\\\\\\*b here",
    r"end \\\\ here",
    r"*em\\\\* here",
    r"a\\\\\\b here",
    "C:\\path here",
    "a `c\\d` here",
])
def test_an_edit_keeps_the_text_of_a_paragraph_with_backslashes(src):
    out = saved(src)
    assert page_fragment(out) == page_fragment(src.replace("here", "there"))


def test_a_backslash_before_a_letter_stays_a_single_backslash():
    assert saved("C:\\path here") == "C:\\path there\n"


def test_a_backslash_in_code_is_not_doubled():
    assert saved("a `c\\d` here") == "a `c\\d` there\n"


def test_a_backslash_in_a_table_cell_keeps_its_text():
    src = "| a | b |\n|---|---|\n| x\\\\\\\\y | here |"
    assert page_fragment(saved(src)) == page_fragment(src.replace("here", "there"))
