"""Ticket 137 follow-ups in `edit.py`: an empty merged region, a typed backslash in another text node than its
shortcode, the cost of placing the source's literal shortcodes, and a dropped address on a mounted page.

The cost tests count pandoc renders, which run in a child process, and time the diff with `time.process_time()`
and gc disabled, so that the other workers of a parallel run do not count.
"""
import time

import pytest

from sheafmd import edit as rde
from test_edit_emoji import page_fragment
from test_merge import FOUR, lines_html, second_save


# 84: the file deletes one line of the page's split save and the page's next save drops every other line, so the
# edit and the file together leave nothing of the block.
EMPTIED = {
    "typed above": (["Typed above.", "Second paragraph here."], 0),
    "split off": (["Second paragraph here.", "Split off."], 1),
    "three lines, the middle deleted": (["Second paragraph here.", "Middle.", "Last."], 1),
    "three lines, the last deleted": (["Second paragraph here.", "Middle.", "Last."], 2),
}


@pytest.mark.parametrize("scene", EMPTIED)
def test_a_line_the_file_deleted_stays_deleted_when_the_edit_leaves_nothing_else(scene):
    lines, gone = EMPTIED[scene]
    saved = lines_html(lines)
    once, _ = rde.apply_edits(FOUR, [{"i": 2, "html": saved}])
    cur = once.replace(lines[gone] + "\n\n", "")
    new, rep = rde.merge_edits(FOUR, cur, second_save(2, lines_html([lines[gone]]), saved), at="2026-10-18T10:00")
    assert new == "# Title\n\nFirst paragraph here.\n\nThird paragraph here.\n\nFourth paragraph here.\n"
    assert rep["changed"] == [2] and rep["conflicts"] == []


def test_an_emptied_region_at_the_end_of_the_file_goes_as_a_deleted_last_block_does():
    base = "# Title\n\nSecond paragraph here.\n"
    saved = lines_html(["Typed above.", "Second paragraph here."])
    once, _ = rde.apply_edits(base, [{"i": 1, "html": saved}])
    cur = once.replace("Typed above.\n\n", "")
    new, rep = rde.merge_edits(base, cur, second_save(1, lines_html(["Typed above."]), saved), at="2026-10-18T10:00")
    assert new == rde.apply_edits(base, [{"i": 1, "html": "<p></p>"}])[0]
    assert rep["conflicts"] == []


def test_a_comment_in_an_emptied_region_keeps_the_block_as_before():
    # Nothing is left to hold the comment, so the merge does not take the region out; the edit goes where the merge
    # put it, as before, and the comment is kept.
    from test_merge import with_comment
    saved = lines_html(["Typed above.", "Second paragraph here."])
    once, _ = rde.apply_edits(FOUR, [{"i": 2, "html": saved}])
    cur, _ = with_comment(once.replace("Typed above.\n\n", ""), "Second paragraph")
    new, _ = rde.merge_edits(FOUR, cur, second_save(2, lines_html(["Typed above."]), saved), at="2026-10-18T10:00")
    assert "Why?" in new


# 88: the backslash the reader typed is in another text node than the shortcode after it.
@pytest.mark.parametrize("typed", [
    "<em>\\</em>:smile:",
    "<em>x\\</em>:smile:",
    "<strong>\\</strong>:smile:",
    "\\<em>:smile:</em>",
    'x\\<a href="https://e.com">:smile:</a>',
])
def test_a_backslash_typed_in_another_text_node_keeps_the_shortcode_text(typed):
    html = page_fragment("a b here").replace("b", typed)
    out, rep = rde.apply_edits("# T\n\na b here\n", [{"i": 1, "html": html}])
    assert rep["skipped"] == []
    shown = page_fragment(out[len("# T\n\n"):])
    assert "emoji" not in shown and ":smile:" in shown and "\\" in shown


@pytest.mark.parametrize("typed", [
    "<code>\\</code>:smile:",           # a backslash in code is the code's
    "x\\<br>:smile:",                   # a break between them
])
def test_a_backslash_not_beside_the_shortcode_leaves_its_emoji(typed):
    html = page_fragment("a b here").replace("b", typed)
    out, rep = rde.apply_edits("# T\n\na b here\n", [{"i": 1, "html": html}])
    assert rep["skipped"] == []
    assert "emoji" in page_fragment(out[len("# T\n\n"):])


def test_a_backslash_typed_in_another_paragraph_leaves_its_emoji():
    out = rde.html_block_to_md("<p>a\\</p><p>:smile: here</p>", "a b here", [])
    assert ":smile: here" in out and "\\:smile:" not in out


# 89: the source holds `\:` but no `\:name:`.
@pytest.fixture
def renders(monkeypatch):
    """The sources `_render_source` was asked to render during the test."""
    seen, real = [], rde._render_source
    monkeypatch.setattr(rde, "_render_source", lambda s: seen.append(s) or real(s))
    return seen


@pytest.mark.parametrize("src", ["a\\: b here", "a `x\\:` b here", "a \\:no shortcode: here"])
def test_a_source_without_an_escaped_shortcode_is_not_rendered_to_place_one(renders, src):
    html = page_fragment(src).replace("here", ":smile: there")
    rde.html_block_to_md(html, src, [])
    assert renders == []


def test_a_failed_render_does_not_refuse_an_edit_with_no_escaped_shortcode(monkeypatch):
    src = "a\\: b here"
    monkeypatch.setattr(rde, "_render_source", lambda s: None)
    out = rde.html_block_to_md(page_fragment(src).replace("here", ":smile: there"), src, [])
    assert out == "a: b :smile: there"      # the page shows `a: b`; the source's own `\\:` escaped nothing


def test_an_escaped_shortcode_the_page_no_longer_holds_is_not_rendered(renders):
    rde.html_block_to_md("<p>a :tada: there</p>", "a \\:smile: here", [])
    assert renders == []


# 90: the diff of the source's render against the page's text.
def _colon_list(n):
    return "\n".join(f"- item {k}: some words, at 10:30 here" for k in range(n)) + "\n- last \\:smile: here"


def _cpu(fn):
    """(fn's result, the CPU seconds it took); the caller holds `no_gc`."""
    t = time.process_time()
    return fn(), time.process_time() - t


@pytest.mark.parametrize("change", ["item 0:", "item 300:"])
def test_placing_a_literal_shortcode_in_a_long_block_does_not_grow_with_its_square(no_gc, change):
    # 600 items with a colon each, about 24,000 characters of shortcode text: on main the diff took seconds.
    src = _colon_list(600)
    html = page_fragment(src).replace(change, change.replace("item", "entry"))
    out, cpu = _cpu(lambda: rde.html_block_to_md(html, src, []))
    assert out.endswith("- last \\:smile: here")
    assert cpu < 1.0, cpu


def test_a_long_block_changed_at_both_ends_keeps_its_literal_shortcode(no_gc):
    # The changed middle is the whole block: past the bound, the literal is placed by its name's order.
    src = _colon_list(600)
    html = page_fragment(src).replace("item 0:", "entry 0:").replace("item 599:", "entry 599:")
    out, cpu = _cpu(lambda: rde.html_block_to_md(html, src, []))
    assert out.endswith("- last \\:smile: here")
    assert cpu < 1.0, cpu


@pytest.mark.parametrize("src, old, new, want", [
    # The literal in the common start, in the common end, and in the changed middle.
    ("\\:smile: a b here", "here", ":smile: there", "\\:smile: a b :smile: there"),
    ("x :smile: b \\:smile: here", "x", "y :tada:", "y :tada: :smile: b \\:smile: here"),
    ("a \\:smile: b here", "a", ":smile: and", ":smile: and \\:smile: b here"),
])
def test_a_literal_shortcode_is_placed_wherever_the_edit_is(src, old, new, want):
    html = page_fragment(src).replace(old, new, 1)
    assert rde.html_block_to_md(html, src, []) == want


def test_a_bounded_diff_places_by_order_where_the_counts_agree():
    old = "x :smile: and :smile: y"
    new = "z :smile: and :smile: w"
    olds = [(m.start(), m.group(1)) for m in rde._SHORTCODE_TEXT.finditer(old)][1:]
    assert rde._places_by_order(old, new, olds) == {new.rindex(":smile:")}


def test_a_bounded_diff_places_every_one_of_the_name_where_the_counts_differ():
    old = "x :smile: y"
    new = ":smile: z :smile:"
    olds = [(m.start(), m.group(1)) for m in rde._SHORTCODE_TEXT.finditer(old)]
    assert rde._places_by_order(old, new, olds) == {0, new.rindex(":smile:")}


# 99: on a mounted page an `<a name>` arrives without its name.
def test_a_dropped_address_comes_back_beside_an_anchor_that_lost_its_name():
    src = '<a name="x">x</a> and [x](ftp://a.com/b) here'
    out = rde.html_block_to_md("<p><a>x</a> and <a>x</a> there</p>", src, [])
    assert out == "x and [x](ftp://a.com/b) there"


def test_an_anchor_that_lost_its_name_after_the_link_gets_no_address():
    src = '[x](ftp://a.com/b) and <a name="x">x</a> here'
    out = rde.html_block_to_md("<p><a>x</a> and <a>x</a> there</p>", src, [])
    assert out == "[x](ftp://a.com/b) and x there"


def test_a_deleted_named_anchor_leaves_the_link_its_address():
    # A page that keeps names sends the link alone; as on main, the link keeps its address.
    src = '<a name="x">x</a> and [x](ftp://a.com/b) here'
    out = rde.html_block_to_md("<p>and <a>x</a> there</p>", src, [])
    assert out == "and [x](ftp://a.com/b) there"


def test_a_named_anchor_kept_beside_its_link_keeps_both():
    src = '<a name="x">x</a> and [x](ftp://a.com/b) here'
    out = rde.html_block_to_md('<p><a name="x">x</a> and <a>x</a> there</p>', src, [])
    assert out.endswith(" and [x](ftp://a.com/b) there")


def test_two_links_of_one_text_with_one_deleted_leave_both_text():
    # Which went is unknown, so neither takes an address.
    src = "[x](ftp://a.com/b) and [x](ftp://c.com/d) here"
    out = rde.html_block_to_md("<p>and <a>x</a> there</p>", src, [])
    assert out == "and x there"
