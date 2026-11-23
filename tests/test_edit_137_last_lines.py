"""Ticket 137, the last `edit.py` lines: a line typed after Enter or Shift+Enter that markdown would read as a block of
its own, a top-level <div> a paste brings, a line indented by a space and a tab, a split line the file changed, a
comment the file gave a split line that the next save drops, and where an emoji span of the page came from.
"""
import pytest

from sheafmd import _pandoc, comments as rdc, edit as rde
from sheafmd.blocks import split_md_blocks
from test_edit_emoji import saved as emoji_saved
from test_merge import FOUR, REST, SPLIT_SHAPES, lines_html, second_save, second_saves, with_comment


def save(source, html):
    out, rep = rde.apply_edits("# T\n\n" + source + "\n", [{"i": 1, "html": html}])
    assert rep["skipped"] == []
    return out[len("# T\n\n"):]


def rendered(md):
    return _pandoc.run(["-f", "gfm", "-t", "html5"], md).stdout


# 22: a line of text that markdown reads as a block of its own. Pandoc's writer escapes `***`, `___`, `# x`, `> x` and
# a list marker at the start of a paragraph, but not `---`, a line of `=` or `-`, nor a list marker after a break.
TYPED_LINES = {
    "--- after Enter": ("Ab", "<p>Ab<div>---</div></p>", "---"),
    "--- as a paragraph": ("Ab", "<p>Ab</p><p>---</p>", "---"),
    "-- - after Enter": ("Ab", "<p>Ab<div>-- -</div></p>", "-- -"),
    "--- in a heading's plain line": ("## Ab", "<h2>Ab<div>---</div></h2>", "---"),
    "--- after Shift+Enter": ("Ab", "<p>Ab<br>---</p>", "---"),
    "=== after Shift+Enter": ("Ab", "<p>Ab<br>===</p>", "==="),
    "- after Shift+Enter": ("Ab", "<p>Ab<br>-</p>", "-"),
    "- x after Shift+Enter": ("Ab", "<p>Ab<br>- x</p>", "- x"),
    "+ x after Shift+Enter": ("Ab", "<p>Ab<br>+ x</p>", "+ x"),
    "1. x after Shift+Enter": ("Ab", "<p>Ab<br>1. x</p>", "1. x"),
    "--- in a list item": ("- Ab", "<ul><li>Ab</li><li>---</li></ul>", "---"),
    "--- in a quote": ("> Ab", "<blockquote><p>Ab<div>---</div></p></blockquote>", "---"),
    "--- after Shift+Enter in a list item": ("- Ab", "<ul><li>Ab<br>---</li></ul>", "---"),
    "--- after Shift+Enter in an ordered item": ("1. Ab", "<ol><li>Ab<br>---</li></ol>", "---"),
    "--- in italics after Shift+Enter": ("Ab", "<p>Ab<br><em>---</em></p>", "---"),
}


@pytest.mark.parametrize("scene", TYPED_LINES)
def test_a_typed_line_that_markdown_reads_as_a_block_stays_its_text(scene):
    source, html, line = TYPED_LINES[scene]
    out = rendered(save(source, html))
    assert "<hr" not in out and out.count("<h1") + out.count("<h2") == html.count("<h2"), out
    assert out.count("<li") == html.count("<li") and out.count("<ul") + out.count("<ol") <= 1, out
    assert line in out and "\\" not in out, out


@pytest.mark.parametrize("html", ["<p>Ab<br>-\n-\n-</p>", "<p>Ab<br>--\n-</p>"])
def test_a_line_of_dashes_broken_over_lines_in_the_html_stays_its_text(html):
    out = rendered(save("Ab", html))
    assert "<hr" not in out and "<h2" not in out, out


def test_a_shortcode_in_a_comment_of_the_source_is_not_one_of_its_emoji():
    assert rde._source_emoji('a :smile: <!-- c1 quote=":tada: :smile:" -->') == {"smile": [True]}


@pytest.mark.parametrize("source, found", [
    ("a \\\\:smile: b", {"smile": [True]}),                   # an escaped backslash escapes nothing after it
    ("a \\<!-- :smile: --> b", {"smile": [True]}),              # an escaped comment is text
    ('<span title=":smile:">x</span> :smile:', {"smile": [True]}),  # an attribute is not text
    ('<span class="emoji" data-emoji="smile" title=":tada:">x</span> :smile:', {"smile": [False, True]}),
    ('<span class="emoji" data-emoji="smile" title="> :tada:">x</span> :smile:', {"smile": [False, True]}),
    ('\\<span class="emoji" data-emoji="smile">x</span> :smile:', {"smile": [True]}),  # an escaped tag is text
    ("`:smile:` and\n\n```\n:smile:\n```\n\n:smile:", {"smile": [True]}),          # code draws none
    ("a \\:smile: b", {}),
])
def test_the_source_emoji_are_the_ones_markdown_draws(source, found):
    assert rde._source_emoji(source) == found


def test_a_comment_the_file_added_whose_quote_the_page_changes_is_an_orphan_as_on_a_plain_save():
    # SPEC 5.4: a quote the edit no longer holds makes an orphan, the page's own comment and the file's alike.
    i = FOUR.split("\n\n").index("Third paragraph here.")
    cur, cid = with_comment(FOUR, "Third paragraph here", body="Agent asks", by="Claude")
    new, _ = rde.merge_edits(FOUR, cur, [{"i": i, "html": "<p>Third paragraph hare.</p>"}], at="2026-10-18T10:00")
    base, mine = with_comment(FOUR, "Third paragraph here", body="Mine")
    out, _ = rde.apply_edits(base, [{"i": i, "html": "<p>Third paragraph hare.</p>"}])
    assert rdc.parse(new).by_id(cid).orphan and rdc.parse(out).by_id(mine).orphan


def test_a_private_use_character_in_the_text_leaves_the_typed_line_its_text():
    # The token is picked among characters the text does not hold, as an emoji token is (ticket 181, E).
    out = save("Ab \uF8FC", "<p>Ab \uF8FC<br>---</p>")
    assert "\uF8FC" in out and "<hr" not in rendered(out) and "<h2" not in rendered(out), out

@pytest.mark.parametrize("source, html, md", [
    ("Ab", "<p>Ab</p><hr><p>cd</p>", "Ab\n\n" + "-" * 72 + "\n\ncd\n"),
    ("Ab", "<p>Ab<code>---</code></p>", "Ab`---`\n"),
    ("Ab", "<p>Ab --- cd</p>", "Ab --- cd\n"),
    ("Ab", "<p>Ab<br>2) x</p>", "Ab\\\n2) x\n"),
    ("| a |\n|---|\n| b |", "<table><thead><tr><th>a</th></tr></thead><tbody><tr><td>---</td></tr></tbody></table>",
     "| a   |\n|-----|\n| --- |\n"),
])
def test_a_rule_code_a_line_inside_words_and_a_table_cell_are_left_as_pandoc_writes_them(source, html, md):
    assert save(source, html) == md


@pytest.mark.parametrize("source, html, md", [
    ("Ab", '<p>Ab</p><div style="color: red;">cd</div>', "Ab\n\ncd\n"),
    ("Ab", '<div style="color: red;">cd</div><p>Ab</p>', "cd\n\nAb\n"),
    ("> Ab", "<blockquote><p>Ab</p><div>cd</div></blockquote>", "> Ab\n>\n> cd\n"),
    ("Ab", '<p>Ab<div style="color: red;">cd</div></p>', "Ab\n\ncd\n"),
    ("Ab", '<p>Ab <span>x</span><div style="color: red;">cd</div>ef</p>', "Ab x\n\ncd\n\nef\n"),
])
def test_a_pasted_div_beside_a_block_is_a_paragraph_with_no_break_before_it(source, html, md):
    assert save(source, html) == md


# 23: a line indented by one to three spaces and a tab starts at column 4: pandoc reads it as code.
@pytest.mark.parametrize("line", [" \tcode here", "  \tcode here", "   \tcode here", "\tcode here"])
def test_a_line_indented_by_spaces_and_a_tab_to_column_four_is_code(line):
    blocks = split_md_blocks(f"# T\n\n{line}\n\nAfter.\n")
    assert [b.kind for b in blocks] == ["heading", "indented_code", "para"]
    assert "<pre><code>code here" in rendered(f"{line}\n")


def test_a_paragraph_line_indented_by_a_space_and_a_tab_continues_the_paragraph():
    assert [b.kind for b in split_md_blocks("# T\n\nPara\n \tcontinued\n")] == ["heading", "para"]


# 27: the file changes a line of the page's split save. Where the next save leaves the line as the page saved it,
# the file's change stands in its place; where the page changed it too, the page's is written with the note.
def file_changed(line):
    return line[:-1] + ", by Claude."


CHANGED_SPLIT_LINE = [(shape, k, name) for shape, lines in SPLIT_SHAPES.items() for k, x in enumerate(lines)
                      if x != "Second paragraph here." for name, _ in second_saves(lines)]


@pytest.mark.parametrize("shape, k, second", CHANGED_SPLIT_LINE,
                         ids=[f"{s} / line {k} changed / {n}" for s, k, n in CHANGED_SPLIT_LINE])
def test_a_split_line_the_file_changed_is_written_once(shape, k, second):
    lines = SPLIT_SHAPES[shape]
    saved = lines_html(lines)
    once, _ = rde.apply_edits(FOUR, [{"i": 2, "html": saved}])
    cur = once.replace(lines[k], file_changed(lines[k]))
    after = dict(second_saves(lines))[second]
    new, rep = rde.merge_edits(FOUR, cur, second_save(2, lines_html(after), saved), at="2026-10-18T10:00")
    prose = rde._prose(new)
    page = [x for x in after if x != lines[k]]
    if lines[k] in after:
        # The page left the line as it saved it: the file's change stands, in its place, with no note.
        expect = [file_changed(x) if x == lines[k] else x for x in after]
        assert prose == "# Title\n\nFirst paragraph here.\n\n" + "\n\n".join(expect) + REST, new
        assert rep["conflicts"] == []
    else:
        # The page changed the line or took it out: the page's lines are written, the file's words go in the note.
        assert file_changed(lines[k]) not in prose and all(x in prose for x in page), new
        [note] = [c for c in rdc.parse(new).comments if c.by == "sheaf"]
        assert note.body == rde._both_note(file_changed(lines[k])) and not note.orphan
        assert rep["conflicts"] == [{"i": 2, "kind": "both"}]


def test_two_split_lines_the_file_changed_and_the_page_typed_on_each_get_a_note_each():
    lines = ["Typed above.", "Second paragraph here.", "Split off."]
    saved = lines_html(lines)
    once, _ = rde.apply_edits(FOUR, [{"i": 2, "html": saved}])
    cur = once.replace("Typed above.", "Typed above, by Claude.").replace("Split off.", "Split off, by Claude.")
    after = ["Typed above. More.", "Second paragraph here.", "Split off. More."]
    new, rep = rde.merge_edits(FOUR, cur, second_save(2, lines_html(after), saved), at="2026-10-18T10:00")
    assert rde._prose(new) == "# Title\n\nFirst paragraph here.\n\n" + "\n\n".join(after) + REST
    notes = sorted(c.body for c in rdc.parse(new).comments if c.by == "sheaf")
    assert notes == sorted(rde._both_note(x) for x in ("Typed above, by Claude.", "Split off, by Claude."))


# 32: a comment the file gave a split line, whose words the next save takes out, is an orphan (SPEC 5.4, "Orphan"),
# as one the page itself takes the words of is; it is not moved onto the line before.
@pytest.mark.parametrize("second", [["Second paragraph here."], ["Second paragraph here. More."]])
def test_a_comment_the_file_gave_a_split_line_the_next_save_drops_is_an_orphan(second):
    saved = lines_html(["Second paragraph here.", "Split off."])
    once, _ = rde.apply_edits(FOUR, [{"i": 2, "html": saved}])
    cur, cid = with_comment(once, "Split off", body="Agent asks", by="Claude")
    new, rep = rde.merge_edits(FOUR, cur, second_save(2, lines_html(second), saved), at="2026-10-18T10:00")
    c = rdc.parse(new).by_id(cid)
    assert c and c.orphan and c.body == "Agent asks" and new.count("Agent asks") == 1
    assert [b for b in rde._prose(new).split("\n\n") if b.strip()] == [
        "# Title", "First paragraph here.", second[0], "Third paragraph here.", "Fourth paragraph here.\n"]
    assert new.index(second[0]) < new.index(f"id={cid}") < new.index("Third paragraph")


def test_a_comment_the_file_added_whose_words_the_page_takes_out_is_an_orphan_without_a_split():
    cur, cid = with_comment(FOUR, "Second paragraph", body="Agent asks", by="Claude")
    new, _ = rde.merge_edits(FOUR, cur, [{"i": 2, "html": "<p>here.</p>"}], at="2026-10-18T10:00")
    c = rdc.parse(new).by_id(cid)
    assert c and c.orphan and rde._prose(new).startswith("# Title\n\nFirst paragraph here.\n\nhere.\n\n")


def test_a_comment_the_file_added_whose_words_stay_keeps_its_place():
    cur, cid = with_comment(FOUR, "Second paragraph", body="Agent asks", by="Claude")
    new, _ = rde.merge_edits(FOUR, cur, [{"i": 2, "html": "<p>Second paragraph here, edited.</p>"}],
                             at="2026-10-18T10:00")
    c = rdc.parse(new).by_id(cid)
    assert c and not c.orphan and new.index("Second paragraph") < new.index(f"id={cid}") < new.index("edited")


# Cluster E of the recheck findings: which emoji span of the page the source wrote as a shortcode. A span the source
# wrote as HTML is written as its emoji, as any raw span of the source is written as its words; never as a `:name:`
# the source does not have there.
@pytest.mark.parametrize("src, md", [
    ('`:+1:` <span class="emoji" data-emoji="+1">\U0001F44D</span> here', '`:+1:` \U0001F44D there\n'),
    (':smile: and <span class="emoji" data-emoji="smile">\U0001F604</span> here', ':smile: and \U0001F604 there\n'),
    ('a <span class="emoji" data-emoji="smile">\U0001F604</span> and :smile: here', 'a \U0001F604 and :smile: there\n'),
    ('```\n:smile:\n```\n\nand <span class="emoji" data-emoji="smile">\U0001F604</span> here', None),
])
def test_an_emoji_span_the_source_wrote_as_html_is_not_written_as_a_shortcode(src, md):
    if md is None:
        doc = "# Title\n\n" + src + "\n"
        out, _ = rde.apply_edits(doc, [{"i": 2, "html": '<p>and <span class="emoji" data-emoji="smile">\U0001F604'
                                                        '</span> there</p>'}])
        assert out.endswith("and \U0001F604 there\n"), out
    else:
        assert emoji_saved(src) == md


@pytest.mark.parametrize("junk", ["", "", "0"])
def test_a_token_character_in_the_text_leaves_the_shortcodes_as_shortcodes(junk):
    assert emoji_saved(f"a {junk} b :smile: here") == f"a {junk} b :smile: there\n"


def test_a_shortcode_only_in_code_and_one_outside_it_are_each_kept():
    assert emoji_saved("`:+1:` and :+1: here") == "`:+1:` and :+1: there\n"


def test_the_shortcode_of_a_page_span_is_kept_when_one_of_two_is_deleted():
    src = ":smile: and :smile: here"
    html = '<p><span class="emoji" data-emoji="smile">\U0001F604</span> here</p>'
    out, _ = rde.apply_edits("# T\n\n" + src + "\n", [{"i": 1, "html": html}])
    assert out == "# T\n\n:smile: here\n"
