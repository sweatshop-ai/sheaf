"""Ticket 187 BZ. `strip_data_attrs` drops the `data-` attributes `_sanitize` strips from the page fragment. It
ran its pattern over the whole start tag, so whitespace then `data-` inside another attribute's quoted value
was taken for an attribute: the value lost its tail and its closing quote, the source side of the comparison
became broken HTML, and a list whose row held such a link refused every tick."""
import pytest

from sheafmd import edit as rde
from sheafmd.hub import the_list

LIST = """# M

- [ ] Deploy a/b#1: [spec](https://x.y "{title}")
- [ ] Merge a/b#2: two
"""


@pytest.mark.parametrize("tag", [
    '<a href="https://x.y" title="the data-sheet">',
    "<a href='https://x.y' title='the data-sheet'>",
    '<abbr title="a data-driven plan">',
    '<a title="x data-y=z" href="h">',
])
def test_a_quoted_value_that_holds_data_is_kept_whole(tag):
    html = tag + "spec</a>"
    assert rde.strip_data_attrs(html) == html


@pytest.mark.parametrize("html, want", [
    ('<span class="emoji" data-emoji="smile">x</span>', '<span class="emoji">x</span>'),
    ('<span data-a data-b=\'1\' data-c=2 class="k">x</span>', '<span class="k">x</span>'),
    ('<span title="the data-sheet" data-emoji="smile">x</span>', '<span title="the data-sheet">x</span>'),
    ('<p data-rd-fresh="1" data-x="y">x</p>', '<p data-rd-fresh="1">x</p>'),
    ('<img src="a.png" data-x="y"/>', '<img src="a.png"/>'),
])
def test_data_attributes_go_and_the_pages_own_stay(html, want):
    assert rde.strip_data_attrs(html) == want


@pytest.mark.parametrize("title", ["the data-sheet", "the sheet"])
def test_a_row_ticks_when_a_link_title_holds_data(title):
    text = LIST.format(title=title)
    edit = the_list.tick_edit(text, 1, "Merge")
    assert edit is not None, "the row's button refuses the tick"
    # The page's save of that edit ticks the one box and leaves the rest of the list as written (no pandoc rewrite).
    out, _ = rde.apply_edits(text, [edit])
    assert out == text.replace("- [ ] Merge", "- [x] Merge")
