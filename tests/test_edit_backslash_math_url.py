"""A backslash in inline math or in a bare-URL link keeps its text on a page edit (ticket 137).

Pandoc's gfm writer leaves a backslash bare; `_text_backslashes` left math alone, so the page text of
`$a\\\\b$` changed, and a bare URL's text, written as a link label, lost its backslash.
"""
import re

import pytest

from sheafmd import edit as rde
from test_edit_backslash import page_fragment, saved


def words(fragment):
    return " ".join(re.sub(r"<[^>]*>", "", fragment).split())


@pytest.mark.parametrize("src", [
    "$a\\\\b$ here",
    "$a\\b$ here",
    "$a\\\\\\\\b$ here",
    "$x\\\\$ and $y$ here",
])
def test_a_backslash_in_inline_math_keeps_the_page_text(src):
    out = saved(src)
    assert words(page_fragment(out)) == words(page_fragment(src.replace("here", "there")))


def anchors(fragment):
    return re.findall(r'<a href="([^"]*)"', fragment)


@pytest.mark.parametrize("src", [
    "see http://x.com/a\\b here",
    "see http://x.com/a\\\\b here",
    "see http://x.com/a\\*b here",
    "see http://x.com/a\\\\ here",
])
def test_a_backslash_in_a_bare_url_keeps_its_address_and_text(src):
    out = saved(src)
    want = page_fragment(src.replace("here", "there"))
    assert anchors(page_fragment(out)) == anchors(want)
    assert words(page_fragment(out)) == words(want)


def test_a_bare_url_with_a_backslash_and_a_pipe_in_a_cell_keeps_its_row():
    src = "| a | b |\n|---|---|\n| http://x.com/a\\\\\\|c | here |"
    out = saved(src)
    assert all(line.count("|") - line.count("\\|") == 3 for line in out.strip().splitlines())
