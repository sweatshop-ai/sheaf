"""Links keep their address on a page edit: the link cluster of ticket 137.

A `<table` in a link's title counted as a raw HTML table, so the text after it was written as HTML; a relative
link whose text is its address and holds a lone `)` was left to pandoc, which writes `<address>` only for the
schemes it knows; pandoc's `<url>` was unwrapped where GFM's domain rules do not link the bare URL; and a link
whose address the sanitiser drops (an `ftp://` one) was written as its text alone.
"""
import pytest

from sheafmd import edit as rde
from test_edit_backslash import saved
from test_edit_url_followups import anchors, same_page


def page_links(block_md):
    return anchors(rde._render_source(block_md))


# A backslash in the text arms the raw-table depth count, which took the title's `<table` for a tag.
@pytest.mark.parametrize("src", [
    '[t](http://x.com "a <table b") and a\\\\\\\\b here',
    '[t](http://x.com "a <table b") and [u](http://x.com/a\\(b) here',
    '[t](http://x.com "a <table b") and :smile: here',
])
def test_a_table_tag_in_a_link_title_is_no_raw_table(src):
    out = saved(src)
    same_page(src, out)
    assert '"a <table b")' in out
    assert (":smile:" in out) == (":smile:" in src)     # the emoji goes back as its shortcode, not as drawn


@pytest.mark.parametrize("src", ["[foo\\)](foo\\)) here", "[x:foo\\)](x:foo\\)) here",
                                 "[mailto:a@b.c\\)](mailto:a@b.c\\)) here", "[/a(](/a\\() here"])
def test_a_link_whose_text_is_its_address_keeps_a_lone_parenthesis(src):
    same_page(src, saved(src))


@pytest.mark.parametrize("src", ["see <http://x.com/a)> here", "see <ftp://x.com/a)> here"])
def test_an_absolute_address_with_a_lone_parenthesis_stays_between_angle_brackets(src):
    out = saved(src)
    same_page(src, out)
    assert out == src.replace("here", "there") + "\n"


@pytest.mark.parametrize("src", ["see <http://localhost> here", "see <http://localhost:8080/x> here"])
def test_an_address_with_no_dot_in_its_domain_stays_a_link(src):
    same_page(src, saved(src))


@pytest.mark.parametrize("url", ["http://my_site.com", "http://a.b_c.org/x", "http://a.b.c_d"])
def test_an_underscore_in_the_last_two_labels_keeps_the_angle_brackets(url):
    # GFM does not link such a URL written bare; pandoc's reader does, so the test reads the written form.
    assert saved(f"see <{url}> here") == f"see <{url}> there\n"


@pytest.mark.parametrize("url", ["http://a_b.x.com/c", "http://127.0.0.1/x", "http://x.com/a_b"])
def test_an_underscore_outside_the_last_two_labels_is_still_written_bare(url):
    assert saved(f"see <{url}> here") == f"see {url} there\n"


@pytest.mark.parametrize("src", [
    "[x](ftp://a.com/b) here",
    "[x](ftp://a\\\\b) here",
    "a [x](ftp://a.com/b) and [y](ftp://c.com/d) here",
    "| a | b |\n|---|---|\n| [x](ftp://a.com/b) | c here |",
])
def test_a_link_the_sanitiser_drops_keeps_its_address_in_the_md(src):
    out = saved(src)
    assert page_links(out) == page_links(src)


def test_a_link_the_sanitiser_drops_is_matched_by_its_text():
    # The page sends the link without its address, as the rendered page shows it; the reader deleted the first.
    src = "[x](ftp://a.com/b) and [y](ftp://c.com/d) here"
    frag = '<p>and <a>y</a> there</p>'
    out = rde.html_block_to_md(frag, src, [])
    assert page_links(out) == ["ftp://c.com/d"]


def test_a_link_the_source_did_not_have_gets_no_address():
    out = rde.html_block_to_md('<p><a>z</a> there</p>', "[x](ftp://a.com/b) here", [])
    assert out == "z there"


def test_two_such_links_of_one_text_after_one_was_deleted_stay_text():
    # Which of the two went is unknown: the one left must not take the other's address.
    src = "[x](ftp://a.com/b) and [x](ftp://c.com/d) here"
    out = rde.html_block_to_md('<p>and <a>x</a> there</p>', src, [])
    assert out == "and x there"


def test_an_anchor_with_a_name_gets_no_address():
    src = '<a name="x">x</a> and [x](ftp://a.com/b) here'
    out = rde.html_block_to_md('<p><a name="x">x</a> and <a>x</a> there</p>', src, [])
    assert out.endswith(" and [x](ftp://a.com/b) there")


def test_a_link_with_an_emoji_in_its_text_keeps_its_address():
    src = "[go :smile:](ftp://a.com/b) here"
    assert page_links(saved(src)) == ["ftp://a.com/b"]
