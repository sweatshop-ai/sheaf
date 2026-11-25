"""Ticket 197: the Codex NO-GO findings on #634, #642 and #658 that still held on main.

A closing tag with no opener that climbs out of nested elements past a comment, the `data-` attributes of a start
tag read as the page's parser reads them, an escaped shortcode among typed ones when every word around it changed,
and a <b> whose own style sets its weight.
"""
import html.parser

import pytest
from test_edit_191 import saved_as
from test_edit_inline_html import saved

from sheafmd import edit as rde

# 634: after stepping over a comment between two elements it climbs out of, the tag goes on climbing.

@pytest.mark.parametrize("src,page", [
    ("- a\n- </x1>*<!-- f1 -->**<!-- f2 -->Start** rest* b here.",
     "<ul>\n<li>a</li>\n<li><em><!-- f1 --><strong><!-- f2 -->Start</strong> rest</em> b there.</li>\n</ul>"),
    ("- a\n- </x1>*<!-- f1 -->**Start** rest* b here.",
     "<ul>\n<li>a</li>\n<li><em><!-- f1 --><strong>Start</strong> rest</em> b there.</li>\n</ul>"),
    ("*a **Start<!-- f2 -->**<!-- f1 -->*</x1> b here.",
     "<p><em>a <strong>Start<!-- f2 --></strong><!-- f1 --></em> b there.</p>"),
], ids=["item-comments-at-two-depths", "item-comment-between-elements", "after-words-comments-at-two-depths"])
def test_a_closing_tag_with_no_opener_climbs_out_of_every_element_past_the_comments_between_them(src, page):
    assert saved(src, html=page) == src.replace("here", "there") + "\n"


# 642: `strip_data_attrs` reads each attribute as the page's parser (`_sanitize`, html.parser) does.

def _parsed(tag):
    """The tag name, the (name, value) pairs html.parser reads from the start tag `tag`, and whether it reads it
    as self-closing."""
    seen = []

    class P(html.parser.HTMLParser):
        def handle_starttag(self, name, attrs):
            seen.append((name, attrs, False))

        def handle_startendtag(self, name, attrs):
            seen.append((name, attrs, True))

    P().feed(tag)
    return seen[0]


@pytest.mark.parametrize("tag", [
    "<div data-x == title>",
    "<div title == data-x=1>",
    "<div data-x=\"1\"title=a'b>",
    "<div data-x='1'title=\"t\" data-y=2 class=k>",
    "<div a=== data-x=1 b>",
    "<div/data-x >",
    "<div\t/data-xtitle >",
])
def test_data_attributes_go_and_the_others_stay_as_the_parser_reads_them(tag):
    out = rde.strip_data_attrs(tag)
    name, attrs, closed = _parsed(tag)
    assert _parsed(out) == (name, [(n, v) for n, v in attrs if not n.startswith("data-")], closed), out


# 658: with every word around it changed, an escaped shortcode keeps its escape at its own place, not at a
# `:name:` the reader typed elsewhere.

def test_an_escaped_shortcode_among_changed_words_keeps_its_escape_at_its_place():
    old_a = " ".join(f"w{i}" for i in range(400))
    old_b = " ".join(f"x{i}" for i in range(400))
    new_a = " ".join(f"v{i}" for i in range(400))
    new_b = " ".join(f"y{i}" for i in range(400))
    out = saved_as(f"aaaa {old_a} \\:smile: {old_b}", f"<p>aaaa :smile: {new_a} :smile: {new_b}</p>")
    at = out.index("\\:smile:")
    assert out == f"aaaa :smile: {new_a} \\:smile: {new_b}\n", out[max(0, at - 20):at + 30]


# 658: a <b>'s own `font-weight` replaces its default `bolder`, and is relative to the weight its parent has.

def test_a_bold_tag_whose_own_style_says_lighter_is_read_from_its_parent():
    page = ('<p><span style="font-weight:500"><b style="font-weight:lighter"><span style="font-weight:bolder">'
            'plain</span></b></span> words</p>')
    assert rde.html_block_to_md(page, source="Old words") == "plain words"


def test_a_bold_tag_whose_own_style_says_bolder_is_bolder_once():
    from bs4 import BeautifulSoup

    soup = BeautifulSoup('<p><b style="font-weight:bolder"><span>x</span></b></p>', "html.parser")
    # bolder than the 400 around it, once: 700, not bolder than its own default 700 (900).
    assert rde._inherited_weight(soup.span) == 700
