"""The copy block (SPEC 6.8): a quote whose first line is `[!COPY]` is a block to copy.

The server's half: the page marks it, the share copy and the PDF show a plain quote, a save keeps the
marker, and a comment's offsets do not count the marker, which the page does not show."""
import re

import pytest
from helpers import pandoc
from test_save_roundtrip import blocks_of

import sheafmd
from sheafmd import comments as rdc
from sheafmd import copyblock
from sheafmd import edit as rde

MAIL = "> [!COPY]\n> Hello **Anna**,\n> thanks for the call.\n>\n> Best, Thierry\n"
DOC = "# Plan\n\nBefore.\n\n" + MAIL + "\nAfter.\n"


def page_of(tmp_path, text, **kw):
    f = tmp_path / "doc.md"
    f.write_text(text, encoding="utf-8")
    return sheafmd.render(f, **kw)


def quotes(out):
    return re.findall(r"<blockquote[^>]*>[\s\S]*?</blockquote>", out)


def test_the_page_marks_the_quote_and_does_not_show_the_marker(tmp_path):
    [q] = quotes(page_of(tmp_path, DOC, share=False))
    assert q.startswith('<blockquote class="rd-copy">')
    assert "COPY" not in q and "[!" not in q
    assert "Hello <strong>Anna</strong>" in q and "Best, Thierry" in q


def test_the_share_copy_shows_a_plain_quote_without_marker_class_or_script(tmp_path):
    out = page_of(tmp_path, DOC, share=True)
    [q] = quotes(out)
    assert q.startswith("<blockquote>")
    assert "COPY" not in out and "class=\"rd-copy\"" not in out and "<button" not in out and "<script" not in out
    assert "Hello <strong>Anna</strong>" in q


@pytest.mark.parametrize("quote", [
    "> [!copy]\n> text\n",            # the marker is upper case
    "> [!COPY] text on the line\n",   # the marker is a line of its own
    "> intro\n> [!COPY]\n> text\n",   # and the first one
    "> [!COPY]\n",                    # nothing to copy
])
def test_anything_else_stays_a_quote_as_before(tmp_path, quote):
    out = page_of(tmp_path, "# T\n\n" + quote, share=False)
    assert 'class="rd-copy"' not in out
    assert out.count("<blockquote") == 1


def test_the_marker_may_be_followed_by_a_blank_quote_line(tmp_path):
    [q] = quotes(page_of(tmp_path, "# T\n\n> [!COPY]\n>\n> text\n", share=False))
    assert q.startswith('<blockquote class="rd-copy">') and "COPY" not in q and "text" in q


def test_a_copy_block_inside_a_list_item_is_left_as_a_quote(tmp_path):
    out = page_of(tmp_path, "# T\n\n- item\n\n  > [!COPY]\n  > text\n", share=False)
    assert 'class="rd-copy"' not in out and "[!COPY]" in out


# ── saving ──────────────────────────────────────────────────────────────────

def saved(md, edit=lambda h: h):
    """The block as the page holds it (marker class, no marker text), edited, and written back."""
    block = blocks_of(md)[0]
    frag = edit(page_of_block(block.content))
    return rde.html_block_to_md(frag, block.content)


def page_of_block(md):
    html = copyblock.mark(pandoc(["-f", "gfm", "-t", "html5", "--no-highlight"], copyblock.hide(md)).strip(), page=True)
    return re.sub(r"[ \t]*\n[ \t]*(?=[^<\s])", " ", html)      # pandoc wraps at 72 columns, a test edits words


def test_an_edited_copy_block_keeps_its_marker_on_save():
    out = saved(MAIL, lambda h: h.replace("thanks for the call", "thanks for your time"))
    assert out.startswith("> [!COPY]\n>\n> Hello **Anna**")
    assert "thanks for your time" in out and "the call" not in out
    assert out.count("[!COPY]") == 1 and "\\[" not in out


def test_the_marker_survives_a_second_round_trip():
    once = saved(MAIL, lambda h: h.replace("Anna", "Bo"))
    again = saved(once, lambda h: h.replace("Bo", "Cy"))
    assert again.startswith("> [!COPY]\n") and "Cy" in again


def test_a_copy_block_nobody_touched_is_found_unchanged():
    block = blocks_of(MAIL)[0]
    assert rde._unchanged(block, page_of_block(block.content))


def test_a_copy_block_with_a_changed_word_is_found_changed():
    block = blocks_of(MAIL)[0]
    assert not rde._unchanged(block, page_of_block(block.content).replace("Anna", "Bo"))


def test_the_page_button_never_reaches_the_markdown():
    btn = '<button class="rd-copybtn" data-rd-ui contenteditable="false">Copy</button>'
    out = saved(MAIL, lambda h: h.replace('class="rd-copy">', 'class="rd-copy">' + btn, 1))
    assert "Copy" not in out and "button" not in out
    assert out == saved(MAIL)


# ── comments ────────────────────────────────────────────────────────────────

def test_a_selection_in_a_copy_block_anchors_where_the_page_saw_it():
    # The page shows "Hello Anna,thanks for the call.Best, Thierry": the marker is not on it.
    proj = rdc.projection(MAIL).text
    assert proj.startswith("HelloAnna,")
    i = proj.index("thanks")
    j = i + len("thanksforthecall.")
    at = rdc.anchor_point(MAIL, i, j, "thanks for the call.")
    assert MAIL[:at].endswith("thanks for the call.")


def test_a_tick_made_away_from_the_page_in_a_copy_block_takes_the_quick_path():
    # ticked_html renders the block as the page does, so a task in a copy block is found as drawn.
    md = "> [!COPY]\n> - [ ] first\n> - [ ] second\n"
    block = blocks_of(md)[0]
    frag = rde.ticked_html(block, 1)
    assert frag is not None and 'class="rd-copy"' in frag


# ── review of 163c92b: what a save does to the first thing in the block, and odd corners ──

FIRST_CHILDREN = {
    "fence": "> [!COPY]\n> ```\n> code line\n> ```\n> after\n",
    "table": "> [!COPY]\n> | a | b |\n> |---|---|\n> | 1 | 2 |\n> after\n",
    "ordered list from 3": "> [!COPY]\n> 3. three\n> 4. four\n",
    "indented code": "> [!COPY]\n>\n>     code line\n>\n> after\n",
}


@pytest.mark.parametrize("md", FIRST_CHILDREN.values(), ids=FIRST_CHILDREN)
def test_a_block_whose_first_child_is_not_a_paragraph_keeps_its_shape_through_a_save(md):
    block = blocks_of(md)[0]
    out = saved(md, lambda h: h.replace("after", "AFTER").replace("four", "FOUR").replace("code line", "code line!"))
    again = pandoc(["-f", "gfm", "-t", "html5", "--no-highlight"], copyblock.hide(out))
    first = pandoc(["-f", "gfm", "-t", "html5", "--no-highlight"], copyblock.hide(block.content))
    shape = lambda h: re.findall(r"<(pre|table|ol|ul|p|h\d)\b", copyblock.mark(h, page=True))
    assert shape(again) == shape(first), out


def test_emptying_a_copy_block_deletes_it_as_it_does_a_plain_quote():
    block = blocks_of(MAIL)[0]
    assert rde.html_block_to_md('<blockquote class="rd-copy"><p><br></p></blockquote>', block.content) == ""


def test_text_that_looks_like_the_stand_in_is_left_alone(tmp_path):
    word = "RDCOPYMARKQX7"          # what the first draft used; a document may hold it (this repo's own notes do)
    out = page_of(tmp_path, f"# T\n\nA paragraph saying {word} here.\n", share=True)
    assert f"saying {word} here" in out and "[!COPY]" not in out
    assert "\\[" not in rde.html_block_to_md(f"<p>saying {word} here</p>")


@pytest.mark.parametrize("quote", [
    "> [!COPY]\n> ---\n> text\n",
    "> [!COPY]\n> text\n> ---\n",
    "> [!COPY]\n> ===\n> text\n",
])
def test_a_setext_underline_in_the_first_paragraph_makes_it_no_copy_block(quote):
    assert not copyblock.is_copy_block(quote.rstrip("\n"))
    assert copyblock.hide(quote) == quote


@pytest.mark.parametrize("quote", [
    "> [!COPY]\n> ```yaml\n> ---\n> a: 1\n> ```\n",           # a prompt holding YAML front matter
    "> [!COPY]\n> ```\n> Title\n> =====\n> ```\n",           # a mail with a rule of its own in a fence
    "> [!COPY]\n>     ---\n",                                 # indented code
    "> [!COPY]\n> - a\n>   ---\n",                           # a list item's own heading
])
def test_an_underline_after_the_first_paragraph_ended_is_no_reason_to_refuse_the_block(quote):
    assert copyblock.is_copy_block(quote.rstrip("\n"))


# The page and the comment offsets must agree whatever the source: the offsets are read from pandoc's own tree.
ODD = [
    "> [!COPY]\n> a\n>     b\n> ---\n",
    "> [!COPY]\n> a\n> \tb\n> ---\n",
    "> [!COPY]\n> a\n> 2024. Year\n> ---\n",
    "> [!COPY]\n> a\n> 1. \n> ---\n",
    "> [!COPY]\n> a\n> - \n> ---\n",
    "> [!COPY]\n> a\n> ***\n> b\n> ---\n",
    "> [!COPY]\n> words\n> ---\n",
    "> [!COPY]\n> ===\n> text\n",
    "> [!COPY]\n> ```yaml\n> ---\n> a: 1\n> ```\n",
    "> [!COPY]\n> - a\n>   ---\n",
    "> [!COPY]\n> text\n",
]


def shown(md):
    """The characters the page shows for a block of the source, as the render writes them."""
    from bs4 import BeautifulSoup
    html = copyblock.mark(pandoc(["-f", "gfm", "-t", "html5", "--no-highlight"], copyblock.hide(md)), page=True)
    return "".join(BeautifulSoup(html, "html.parser").get_text().split())


@pytest.mark.parametrize("md", ODD)
def test_the_comment_offsets_count_what_the_page_shows(md):
    block = md.rstrip("\n")
    assert rdc.projection(block).text == shown(block).replace("[!COPY]", "[!COPY]")


def test_the_stand_in_is_as_long_as_the_marker_so_columns_on_its_line_keep_their_place():
    assert len(copyblock.STAND_IN) == len(copyblock.MARKER)


def test_a_comment_on_a_marker_pandoc_does_not_hide_lands_on_it_not_two_lines_below():
    # A backtick in a fence's info string is no fence: the page shows `[!COPY]` in a heading.
    block = "> [!COPY]\n> a\n> ```lo`ng\n> ---"
    proj = rdc.projection(block).text
    i = proj.index("[!COPY]")
    at = rdc.anchor_point(block, i, i + 7, "[!COPY]")
    assert block[:at].endswith("[!COPY]")
