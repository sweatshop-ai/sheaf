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
    ('<img src="a.png" data-x="y"/>', '<img src="a.png"/>'),
    # `_sanitize` strips the page's own too: raw HTML in the source carrying one must compare equal.
    ('<p data-rd-fresh="1" data-x="y" class="k">x</p>', '<p class="k">x</p>'),
    ('<span DATA-X="1" class="k">x</span>', '<span class="k">x</span>'),
    # A name straight after a quote or a `/` is one to the page's parser.
    ('<a b="x"data-y="z">x</a>', '<a b="x">x</a>'),
    ("<a b='x'data-y='z' c=\"d\">x</a>", "<a b='x' c=\"d\">x</a>"),
    ('<a/data-x="1">x</a>', '<a/>x</a>'),
])
def test_data_attributes_go_whatever_their_name_or_place(html, want):
    assert rde.strip_data_attrs(html) == want


@pytest.mark.parametrize("title", ["the data-sheet", "the sheet"])
def test_a_row_ticks_when_a_link_title_holds_data(title):
    text = LIST.format(title=title)
    edit = the_list.tick_edit(text, 1, "Merge")
    assert edit is not None, "the row's button refuses the tick"
    # The page's save of that edit ticks the one box and leaves the rest of the list as written (no pandoc rewrite).
    out, _ = rde.apply_edits(text, [edit])
    assert out == text.replace("- [ ] Merge", "- [x] Merge")


# Ticket 187, follow-up from #637's review. A quote opens a quoted value only straight after `=`; inside a bare value
# or a name it is a plain character, as the page's parser reads it. `_START_TAG_RE` took any quote for an opening one,
# so a tag holding an unpaired quote was never matched and kept its `data-` attributes on the source side.
@pytest.mark.parametrize("html, want", [
    ("<a href=a'b data-x=\"1\" title=\"t\">x</a>", "<a href=a'b title=\"t\">x</a>"),
    ('<a href=a"b data-x=1>x</a>', '<a href=a"b>x</a>'),
    ("<a b'c data-x=1 d>x</a>", "<a b'c d>x</a>"),
    ("<a href=x'y'data-z=1 data-x=2>x</a>", "<a href=x'y'data-z=1>x</a>"),
])
def test_a_quote_inside_a_bare_value_or_a_name_is_no_quoted_value(html, want):
    assert rde.strip_data_attrs(html) == want


@pytest.mark.parametrize("html", [
    "<a href=a'b data-x=\"1\" title=\"t\">x</a>",
    '<a href=a"b data-x=1 c="d e">x</a>',
    "<a b'c data-x=1 d>x</a>",
    '<a title="a > b" data-x=1 c>x</a>',
    '<a b=="x" data-y=2>x</a>',
    '<a b="x"data-y="z" c=\'d\'>x</a>',
])
def test_the_attributes_left_are_those_the_page_keeps(html):
    """The source side keeps exactly the attributes `_sanitize` keeps on the page side, values included."""
    from bs4 import BeautifulSoup
    page = {k: v for k, v in BeautifulSoup(html, "html.parser").a.attrs.items() if not k.startswith("data-")}
    assert BeautifulSoup(rde.strip_data_attrs(html), "html.parser").a.attrs == page



@pytest.mark.parametrize("src", ["<div class=a'b data-x=1>blk</div>", "<p title=a'b data-x=1>p</p>"])
def test_a_raw_html_block_with_an_unpaired_quote_is_unchanged(src):
    """Pandoc escapes such a tag inline (it is text there), but passes a raw HTML block through as written. On main
    that block never compared equal to the page, so every save sent it through pandoc."""
    from types import SimpleNamespace
    assert rde._unchanged(SimpleNamespace(content=src), rde._render_source(src))

def test_a_start_tag_that_never_closes_is_read_in_linear_time(no_gc):
    import time
    # 24 readings of two each: an exponential pattern takes seconds here, so it fails rather than hangs.
    html = "<a" + ' b="x"' * 24
    t = time.process_time()
    rde.strip_data_attrs(html)
    assert time.process_time() - t < 0.5
