"""A backslash right before a comment or a footnote citation survives a page edit (ticket 137).

`apply_edits` swaps a comment or a citation for a placeholder that starts with a letter, so a backslash
before it was left bare and escaped what came back in its place.
"""
import pytest

from helpers import pandoc
from sheafmd import edit as rde


def page_fragment(block_md):
    return pandoc(["-f", "gfm", "-t", "html5", "--no-highlight"], block_md).strip()


def saved(block_md, tail=""):
    doc = "# Title\n\n" + block_md + "\n" + tail
    out, rep = rde.apply_edits(doc, [{"i": 1, "html": page_fragment(block_md + tail).split("</p>")[0].replace("here", "there") + "</p>"}])
    assert rep["skipped"] == []
    return out[len("# Title\n\n"):]


def test_a_backslash_before_a_comment_stays_a_backslash():
    out = saved("a\\\\<!-- c -->here")
    assert out == "a\\\\<!-- c -->there\n"


def test_a_backslash_before_a_footnote_citation_keeps_the_citation():
    out = saved("x\\\\[^1] here", "\n[^1]: note\n")
    assert out.startswith("x\\\\[^1] there\n")


@pytest.mark.parametrize("src", [
    "a\\\\\\\\<!-- c -->here",
    "a <!-- c -->here",
])
def test_other_backslash_counts_before_a_comment(src):
    assert saved(src) == src.replace("here", "there") + "\n"
