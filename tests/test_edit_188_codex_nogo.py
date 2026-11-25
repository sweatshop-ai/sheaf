"""Ticket 188: the Codex re-check of five merged PRs (#559, #555, #494, #571, #554), the findings that still held on
main. One test (or one parametrized test) per box of the ticket."""
from types import SimpleNamespace

import pytest

from sheafmd import edit as rde
from sheafmd import orderedtask


# ── A (#559, serious): a markdown hard break is in the source, not new ──
# `_unwrap_strays` counted the source's tags in its markdown, where a hard break is `\` or two spaces, never a `<br>`:
# both breaks of `Alpha\` `\` `Beta` were taken for new ones, and any edit of the paragraph split it in two.

@pytest.mark.parametrize("src", ["Alpha\\\n\\\nBeta\n", "Alpha  \n\\\nBeta\n"], ids=["backslash", "two spaces then a backslash"])
def test_the_hard_breaks_of_the_source_stay_breaks_when_the_paragraph_is_edited(src):
    page = rde._render_source(src).replace("Beta", "Beta too")
    strays = []
    got = rde.html_block_to_md(page, source=src, strays=strays)
    assert got == "Alpha\\\n\\\nBeta too", got
    assert strays == []


@pytest.mark.parametrize("src, page, md", [
    ("Alpha\\\nBeta gamma\n", "<p>Alpha<br>\nBeta<span><br></span><span><br></span>gamma</p>", "Alpha\\\nBeta\n\ngamma"),
    # the two new breaks come before the source's own: they are no hard breaks of the source (the review of 188)
    ("Alpha\\\nBeta\n", "<p>Alpha<br><br>New<br>\nBeta</p>", "Alpha\n\nNew\\\nBeta"),
    # a raw <br> of the source beside a markdown hard break
    ("Alpha<br>Beta\\\nGamma delta\n", "<p>Alpha<br>Beta<br>\nGamma<span><br></span><span><br></span>delta</p>",
     "Alpha\\\nBeta\\\nGamma\n\ndelta"),
    # the source's own double break, the words after it edited, and a new one after them
    ("Alpha\\\n\\\nBeta gamma\n", "<p>Alpha<br>\n<br>\nBeta too<span><br></span><span><br></span>gamma</p>",
     "Alpha\\\n\\\nBeta too\n\ngamma"),
], ids=["a break before them", "a break after them", "a raw break", "the source's run kept, a new one split"])
def test_two_new_breaks_in_a_paragraph_with_a_break_of_its_own_still_make_two_paragraphs(src, page, md):
    assert rde.html_block_to_md(page, source=src, strays=[]) == md


# ── B (#559, minor): a double break with no words before it does not end the scan ──

def test_a_double_break_with_no_words_before_it_leaves_the_next_one_to_split():
    got = rde.html_block_to_md("<p><span><br></span><span><br></span>Alpha<span><br></span><span><br></span>Beta</p>",
                               source="x", strays=[])
    assert got.endswith("Alpha\n\nBeta"), got


# ── C (#555, minor): a tag inside an HTML comment is no tag ──

@pytest.mark.parametrize("src", ['a <!-- <span data-x="1"> --> b\n', '<!-- <p data-rd-x="1"> -->\n\n'],
                         ids=["inline", "block"])
def test_a_data_attribute_written_inside_an_html_comment_is_kept_on_both_sides(src):
    assert rde.strip_data_attrs(f"<p>{src}</p>") == f"<p>{src}</p>"
    assert rde._unchanged(SimpleNamespace(content=src), rde._render_source(src))


# ── D (#494, minor): the label of an ordered task ends at a tag, not at tag-shaped text inside one ──

@pytest.mark.parametrize("src, inside", [
    ('1. [ ] a <span title="</p>">x</span> b\n', '<span title="</p>">x</span>'),
    ('1. [ ] a <span title="<div">x</span> b\n', '<span title="<div">x</span>'),
    ("1. [ ] a <span title='</li>'>x</span> b\n", "<span title='</li>'>x</span>"),
    ("1. [ ] a <!-- </p> --> b\n", "<!-- </p> -->"),
], ids=["</p> in a value", "<div in a value", "</li> in a single-quoted value", "</p> in a comment"])
def test_tag_shaped_text_inside_an_ordered_task_label_does_not_end_the_label(src, inside):
    html = rde._render_source(src, keep=False)
    assert f'<label><input type="checkbox" />a {inside} b</label>' in html, html


# ── E (#494, minor): a CR is gone before pandoc reads the mark, as pandoc deletes it ──

@pytest.mark.parametrize("src", ["7.\r [ ] a\n", "1. [ \r] a\n", "1.\r\t[x] a\n"])
def test_a_carriage_return_in_an_ordered_task_mark_still_draws_the_box(src):
    assert '<input type="checkbox"' in rde._render_source(src, keep=False)


def test_hide_drops_carriage_returns_as_pandoc_does():
    assert orderedtask.hide("1. [ ] a\r\n2. b\r\n") == "1.   a\n2. b\n"


# ── G (#571, minor): a remnant the browser leaves in an emptied first half is no heading ──

@pytest.mark.parametrize("html", [
    '<h2><em></em><div data-rd-split="">cd</div></h2>',
    '<h2><em><br></em><div data-rd-split="">cd</div></h2>',
    '<h2><strong></strong> <div data-rd-split="">cd</div></h2>',
], ids=["empty em", "em with a br", "empty strong and a space"])
def test_an_emptied_first_half_with_an_empty_mark_left_in_it_goes(html):
    assert rde.html_block_to_md(html) == "## cd"


def test_a_first_half_with_a_comment_in_it_is_not_empty():
    got = rde.html_block_to_md('<h2>RDCMTAAAAAAAAAA<div data-rd-split="">cd</div></h2>', comments={"RDCMTAAAAAAAAAA"})
    assert got == "## RDCMTAAAAAAAAAA\n\n## cd", got


# ── H (#571, minor): the no-break space Enter leaves goes from a promoted half too ──

@pytest.mark.parametrize("html", ['<h2><div data-rd-split="">\xa0cd</div></h2>',
                                  '<h2><em></em><div data-rd-split="">\xa0cd</div></h2>'])
def test_the_cut_space_goes_from_a_half_that_becomes_the_heading(html):
    assert rde.html_block_to_md(html) == "## cd"


# ── F (#571, serious, hub side): a split line holding only a comment is no half ──

def test_a_split_line_holding_only_a_comment_is_a_paragraph_not_a_heading():
    got = rde.html_block_to_md('<h2>Ab<div data-rd-split="">RDCMTAAAAAAAAAA</div></h2>', comments={"RDCMTAAAAAAAAAA"})
    assert got == "## Ab\n\nRDCMTAAAAAAAAAA", got
