"""Ticket 191: the Codex NO-GO findings on #581, #594 and #595 that still held on main.

A link address with a space and a backslash, a shortcode the reader typed in a changed part too long to diff, a
backslash in another block than the shortcode after it, and a span's bold weight read through a quoted escape and a
relative `lighter`.
"""
import re

from sheafmd import edit as rde
from test_edit_emoji import page_fragment


def saved_as(md, html):
    doc = "# Title\n\n" + md + "\n"
    out, rep = rde.apply_edits(doc, [{"i": 1, "html": html}])
    assert rep["skipped"] == []
    return out[len("# Title\n\n"):]


def rendered_href(md):
    return re.search(r'href="([^"]*)"', page_fragment(md)).group(1)


# 581: an address with white space goes between `<` and `>`, where its backslash must still be escaped.
def test_an_address_with_a_space_and_a_backslash_keeps_both():
    src = "[x](<http://a\\ b>) here"
    out = saved_as(src, page_fragment(src).replace("here", "there"))
    assert rendered_href(out) == rendered_href(src) == "http://a\\ b", out


# 594: in a changed part placed by order, a shortcode the reader typed beside one the source escapes is the emoji.
def test_a_typed_shortcode_in_a_long_change_stays_an_emoji_beside_an_escaped_one():
    old = " ".join(f"w{i}" for i in range(400))
    new = " ".join(f"v{i}" for i in range(400))
    out = saved_as(f"A \\:smile: {old} end", f"<p>A :smile: {new} :smile: end</p>")
    assert out.startswith("A \\:smile: v0") and out.endswith("v399 :smile: end\n"), out[-40:]


def test_places_by_order_past_the_word_diff_keeps_a_literal_by_its_neighbours(monkeypatch):
    monkeypatch.setattr(rde, "_DIFF_BOUND", 0)
    old = "x :smile: y"
    new = ":smile: z x :smile: y"
    olds = [(m.start(), m.group(1)) for m in rde._SHORTCODE_TEXT.finditer(old)]
    assert rde._places_by_order(old, new, olds) == {new.rindex(":smile:")}
    assert rde._places_by_order(old, ":smile: z :smile:", olds) == set()


def test_places_by_order_where_the_counts_differ_keeps_a_literal_by_its_words():
    old = "a b :smile: c d"
    new = ":smile: a b :smile: c d :smile:"
    olds = [(m.start(), m.group(1)) for m in rde._SHORTCODE_TEXT.finditer(old)]
    assert rde._places_by_order(old, new, olds) == {new.index(":smile: c")}


# 594: a backslash that ends another block is not typed before the shortcode.
def test_a_backslash_ending_a_block_does_not_escape_the_shortcode_after_it():
    md = rde.html_block_to_md("<div>\\</div>:smile:")
    assert "\\:smile:" not in md and ":smile:" in md, md


def test_a_backslash_in_an_inline_mark_before_the_shortcode_still_escapes_it():
    md = rde.html_block_to_md("<p>a <em>\\</em>:smile: b</p>")
    assert "\\:smile:" in md, md


# 595: an escaped quote does not end a quoted CSS value.
def test_an_escaped_quote_in_a_quoted_value_ends_no_declaration():
    html = '<p>Two <span style="content:&quot;x\\&quot;;font-weight:700;y&quot;">plain</span> words</p>'
    assert rde.html_block_to_md(html, source="Two words") == "Two plain words"


# 595: `lighter` is relative to the weight it inherits.
def test_lighter_inside_a_heavy_span_stays_bold():
    html = ('<p><span style="font-weight:900">a <span style="font-weight:lighter">still</span> b</span>'
            ' words</p>')
    assert rde.html_block_to_md(html, source="Old words") == "**a still b** words"


def test_lighter_inside_a_bold_span_is_plain():
    html = '<p><span style="font-weight:700">a <span style="font-weight:lighter">plain</span> b</span> words</p>'
    assert rde.html_block_to_md(html, source="Old words") == "**a** plain **b** words"


def test_an_escaped_shortcode_whose_neighbours_changed_stays_text_in_a_long_change():
    # The reverse of the case above: the source's own `\:smile:` keeps its escape when the words on both sides of it
    # changed and the reader typed another `:smile:` elsewhere.
    old_a = " ".join(f"w{i}" for i in range(400))
    old_b = " ".join(f"x{i}" for i in range(400))
    new_a = " ".join(f"v{i}" for i in range(400))
    new_b = " ".join(f"y{i}" for i in range(400))
    out = saved_as(f"aaaa {old_a} \\:smile: {old_b}", f"<p>aaaa :smile: {new_a} :smile: {new_b}</p>")
    assert out.count("\\:smile:") == 1 and out.count(":smile:") == 2, out


def test_bolder_inside_a_light_span_is_plain():
    html = '<p><span style="font-weight:300">a <span style="font-weight:bolder">b</span> c</span> words</p>'
    assert rde.html_block_to_md(html, source="Old words") == "a b c words"


def test_a_literal_with_punctuation_glued_to_it_keeps_its_escape_in_a_long_change():
    old = " ".join(f"w{i}" for i in range(400))
    new = " ".join(f"v{i}" for i in range(400))
    out = saved_as(f"A \\:smile: {old} end", f"<p>A (:smile:) {new} :smile: end</p>")
    assert out.startswith("A (\\:smile:) v0") and out.endswith("v399 :smile: end\n"), (out[:20], out[-30:])


def test_a_literal_whose_word_was_edited_keeps_its_escape_in_a_long_change():
    old = " ".join(f"w{i}" for i in range(400))
    new = " ".join(f"v{i}" for i in range(400))
    out = saved_as(f"A foo\\:smile:bar {old} end", f"<p>A fooX:smile:bar {new} :smile: end</p>")
    assert out.startswith("A fooX\\:smile:bar v0") and out.endswith("v399 :smile: end\n"), (out[:25], out[-30:])
