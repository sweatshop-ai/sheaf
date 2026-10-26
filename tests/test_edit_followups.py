"""Follow-ups for the edit path and the merge (what a save writes into the
file when a block is emptied, put back, or lands next to a block it can join)."""
import pytest
from helpers import pandoc

from sheafmd import comments as rdc
from sheafmd import edit as rde


def doc(*paragraphs):
    return "\n\n".join(paragraphs) + "\n"


def kinds(text):
    return [b.kind for b in rde.split_md_blocks(text)]


# ── a paragraph put back in front of front matter the file gained ──

def test_a_paragraph_put_back_at_the_top_goes_after_the_front_matter_the_file_gained():
    base = doc("Alpha first words here.", "Bravo.")
    cur = "---\ntitle: x\n---\n\nTotally new opening by agent.\n\nBravo.\n"
    new, rep = rde.merge_edits(base, cur, [{"i": 0, "html": "<p>Alpha first words here, edited.</p>"}],
                               at="2026-10-14T10:00")
    assert new.startswith("---\ntitle: x\n---\n\nAlpha first words here, edited.")
    assert kinds(new)[0] == "frontmatter" and "hr" not in kinds(new) and "heading" not in kinds(new)
    assert new.index("Alpha first words here, edited.") < new.index("Totally new opening by agent.")
    assert new.endswith("Totally new opening by agent.\n\nBravo.\n")
    assert rep["conflicts"] == [{"i": 0, "kind": "gone"}] and rdc.parse(new).malformed == []


def test_a_paragraph_put_back_above_the_only_block_left_is_still_after_the_front_matter():
    base = doc("Alpha first words here.", "Bravo.")
    cur = "---\ntitle: x\n---\n"
    new, rep = rde.merge_edits(base, cur, [{"i": 0, "html": "<p>Alpha first words here, edited.</p>"}])
    assert new.startswith("---\ntitle: x\n---\n") and kinds(new)[0] == "frontmatter"
    assert "hr" not in kinds(new) and "Alpha first words here, edited." in new


# ── an emptied block ──
# A browser keeps a <br> in a contenteditable block that was emptied (so that it keeps a
# line's height), and the page sends it. Pandoc writes a hard break there as a backslash,
# which must not go into the file as a line of its own.

EMPTIED = [
    "<p><br></p>", "<p> <br> </p>", "<p><br><br></p>", "<div><br></div>", "<br>",
    "<h2><br></h2>", "<ul><li><br></li></ul>", "<ol><li><br></li></ol>",
    "<blockquote><p><br></p></blockquote>", "<p><b><br></b></p>", "<p>&nbsp;</p>",
]


@pytest.mark.parametrize("html", EMPTIED)
def test_a_block_emptied_in_the_browser_is_deleted_as_an_empty_one_is(html):
    for text, i in [(doc("Alpha", "Bravo", "Charlie"), 1), (doc("Alpha", "- b1\n- b2", "Charlie"), 1),
                    (doc("Alpha", "## Bravo", "Charlie"), 1)]:
        gone = rde.apply_edits(text, [{"i": i, "html": ""}])
        got = rde.apply_edits(text, [{"i": i, "html": html}])
        assert got == gone
        assert "\\" not in got[0] and got[1]["deleted"] == [i]


@pytest.mark.parametrize("html", ["<p><br></p>", "<ul><li><br></li></ul>"])
def test_a_block_emptied_in_the_browser_is_deleted_in_a_merge_too(html):
    base = doc("Alpha", "- b1\n- b2", "Charlie")
    cur = doc("Intro added by an agent.", "Alpha", "- b1\n- b2", "Charlie")
    new, rep = rde.merge_edits(base, cur, [{"i": 1, "html": html}], at="2026-10-14T10:00")
    assert new == doc("Intro added by an agent.", "Alpha", "Charlie") and "\\" not in new
    assert rep["conflicts"] == []


def test_a_comment_on_a_block_emptied_in_the_browser_becomes_an_orphan_without_a_backslash():
    c = rdc.Comment(id="c1", by="Ada", at="2026-10-14T09:00", quote="Bravo", body="note")
    text = doc("Alpha", "Bravo" + rdc.format(c, one_line=False), "Charlie")
    anchor = '<span class="rd-anchor" data-rd-id="c1"></span>'
    new, rep = rde.apply_edits(text, [{"i": 1, "html": f"<p>{anchor}<br></p>"}])
    assert "\\" not in new
    assert rdc.parse(new).by_id("c1").orphan and rdc.parse(new).malformed == []
    assert [b.content.strip() for b in rde.split_md_blocks(new) if b.content.strip()][-1] == "Charlie"


def test_a_trailing_line_break_is_not_written_as_a_backslash_after_the_words():
    """The last <br> of a block shows nothing in a browser, so the words are all there is;
    a hard break in the middle of a paragraph is kept."""
    new, _ = rde.apply_edits(doc("Alpha", "Bravo", "Charlie"), [{"i": 1, "html": "<p>Bravo, edited.<br></p>"}])
    assert new == doc("Alpha", "Bravo, edited.", "Charlie")
    new, _ = rde.apply_edits(doc("Alpha", "Bravo", "Charlie"), [{"i": 1, "html": "<p>Bra<br>vo, edited.<br></p>"}])
    assert new == doc("Alpha", "Bra\\\nvo, edited.", "Charlie")
    table = ("<table><thead><tr><th>A</th><th>B</th></tr></thead>"
             "<tbody><tr><td>x<br></td><td>y<br></td></tr></tbody></table>")
    assert rde.html_block_to_md(table) == rde.html_block_to_md(table.replace("<br>", ""))


# ── a paragraph deleted between two lists ──
# A blank line cannot separate two lists, so the two read as one loose list. What the
# markdown reader honours is a comment line between them (CommonMark's own answer).

def lists_in(md):
    html = pandoc(["-f", "gfm", "-t", "html"], md)
    return html.count("<ul>") + html.count("<ol")


@pytest.mark.parametrize("first, last", [("- a1", "- c1"), ("1. a1", "1. c1"), ("- a1\n- a2", "- c1\n- c2")])
def test_a_paragraph_deleted_between_two_lists_leaves_two_lists(first, last):
    text = doc(first, "Middle.", last)
    for new in (rde.apply_edits(text, [{"i": 1, "html": ""}])[0],
                rde.merge_edits(text, text, [{"i": 1, "html": ""}])[0],
                rde.merge_edits(text, doc("Intro by agent.", first, "Middle.", last),
                                [{"i": 1, "html": ""}])[0]):
        assert "Middle." not in new and lists_in(new) == 2
        assert "a1" in new and "c1" in new
        assert new.count("<!--") == 1 and rdc.parse(new).malformed == []


def test_a_paragraph_deleted_between_a_list_and_an_indented_code_block_leaves_the_code_apart():
    text = doc("- a1", "Middle.", "    code line")
    new, rep = rde.apply_edits(text, [{"i": 1, "html": ""}])
    html = pandoc(["-f", "gfm", "-t", "html"], new)
    assert "Middle." not in new and "<pre><code>code line" in html and lists_in(new) == 1
    assert kinds(new) == ["list", "html", "indented_code"]


# ── a paragraph put back with a comment the file holds in another state ──
# One comment is one comment: the agent joined the paragraph and its comment into the one
# above, and has since resolved it or answered it. The page's copy of the comment is the
# old one; the file's is the one to keep, and there must not be a second under a new id.

ADA_C1 = ('<!-- sheaf-comment id=c1 by="Ada" at=2026-10-14T09:00 status=open quote="another thing"\n'
          'Source?\n-->')


def anchor(cid):
    return f'<span class="rd-anchor" data-rd-id="{cid}"></span>'


@pytest.mark.parametrize("change", ["resolved", "answered", "body edited"])
def test_a_paragraph_put_back_with_a_comment_the_file_changed_does_not_write_it_a_second_time(change):
    base = f"Alpha is the first paragraph of text here.\n\nBravo says another thing{ADA_C1}.\n\nCharlie.\n"
    cur = base.replace("here.\n\nBravo", "here. Bravo")
    cur = {"resolved": lambda m: rdc.set_status(m, "c1", "resolved"),
           "answered": lambda m: rdc.reply(m, "c1", "Re-derived.", "Claude", "2026-10-14T09:30", role="answer"),
           "body edited": lambda m: rdc.edit_body(m, "c1", "Source? Checked."),
           }[change](cur)
    new, rep = rde.merge_edits(base, cur, [
        {"i": 1, "html": f"<p>Bravo says another thing, edited{anchor('c1')}.</p>"},
    ], at="2026-10-14T10:00")
    parsed = rdc.parse(new)
    assert parsed.malformed == []
    [ada] = [c for c in parsed.comments if c.by == "Ada"]
    assert ada.id == "c1" and new.count("Source?") == 1
    assert ada.status == ("resolved" if change == "resolved" else "open")
    assert [r.text for r in ada.replies] == (["Re-derived."] if change == "answered" else [])
    assert ada.body == ("Source? Checked." if change == "body edited" else "Source?")
    assert "Bravo says another thing, edited." in rde._prose(new) and rep["skipped"] == []


def test_a_paragraph_put_back_with_another_comment_under_the_same_id_still_gets_a_new_id():
    """Same id, but not the same comment (another author, another time, another quote)."""
    base = f"Alpha is the first paragraph of text here.\n\nBravo says another thing{ADA_C1}.\n\nCharlie.\n"
    other = ADA_C1.replace('by="Ada"', 'by="Codex"').replace("T09:00", "T09:40").replace("Source?", "Agent note")
    cur = f"Alpha is the first paragraph of text here{other}. Bravo changed.\n\nCharlie.\n"
    new, rep = rde.merge_edits(base, cur, [
        {"i": 1, "html": f"<p>Bravo says another thing, edited{anchor('c1')}.</p>"},
    ], at="2026-10-14T10:00")
    parsed = rdc.parse(new)
    assert parsed.malformed == []
    assert {c.body for c in parsed.comments if c.by != "sheaf"} == {"Source?", "Agent note"}
    assert len({c.id for c in parsed.comments}) == len(parsed.comments)


# ── a comment the file no longer holds is not brought back by the page ──
# Decided, pinned here: the file wins on which comments exist. The page carries an anchor,
# never a comment's text, and `sheaf comment delete` must stay deleted whoever has the page
# open. (Where the file deleted the whole paragraph, the base's comments come back with it:
# the paragraph is put back from the base.)

def test_a_comment_the_agent_deleted_with_the_paragraph_it_replaced_is_not_brought_back_by_the_pages_anchor():
    base = f"Alpha is the first paragraph of text here.\n\nBravo says another thing{ADA_C1}.\n\nCharlie.\n"
    cur = "Alpha is the first paragraph of text here.\n\nA new paragraph by the agent, about other matters.\n\nCharlie.\n"
    new, rep = rde.merge_edits(base, cur, [
        {"i": 1, "html": f"<p>Bravo says another thing, edited{anchor('c1')}.</p>"},
    ], at="2026-10-14T10:00")
    assert rep["conflicts"] == [{"i": 1, "kind": "both"}] and rep["skipped"] == []
    assert "Bravo says another thing, edited." in rde._prose(new)
    parsed = rdc.parse(new)
    assert parsed.malformed == [] and parsed.by_id("c1") is None and "Source?" not in new
    [note] = parsed.comments                                   # the note of the "both" conflict
    assert note.by == "sheaf" and "A new paragraph by the agent, about other matters." in note.body


def test_a_comment_the_agent_deleted_alone_is_not_brought_back_by_the_pages_anchor():
    base = f"Alpha is the first paragraph of text here.\n\nBravo says another thing{ADA_C1}.\n\nCharlie.\n"
    cur = rdc.delete(base, "c1")
    new, rep = rde.merge_edits(base, cur, [
        {"i": 1, "html": f"<p>Bravo says another thing, edited{anchor('c1')}.</p>"},
    ], at="2026-10-14T10:00")
    assert new == cur.replace("another thing.", "another thing, edited.")
    assert rep["conflicts"] == [] and "Source?" not in new and rdc.parse(new).comments == []


# ── a list put back beside the block that follows it ──
# The page's edit of a deleted list is written before the next block of the file, and a
# blank line cannot keep two lists apart, nor a list from an indented code block.

def test_a_list_put_back_before_another_list_does_not_join_it():
    base = doc("Intro.", "- b1\n- b2", "Middle.", "- c1\n- c2")
    cur = doc("Intro.", "- c1\n- c2")
    new, rep = rde.merge_edits(base, cur, [{"i": 1, "html": "<ul><li>b1 edited</li><li>b2</li></ul>"}],
                               at="2026-10-14T10:00")
    assert kinds(new) == ["para", "list", "html", "list"] and lists_in(new) == 2
    assert "b1 edited" in new and "c1" in new and "Middle." not in new
    note = readable_note(new)
    assert note.block == 1 and not note.orphan                # on the list put back, not on the file's
    assert rep["conflicts"] == [{"i": 1, "kind": "gone"}] and rep["changed"] == [1]
    assert rde._prose(rde.split_md_blocks(new)[3].content) == "- c1\n- c2\n"      # the file's list as it was


def test_a_list_put_back_before_an_indented_code_block_does_not_swallow_it():
    base = doc("Intro.", "- b1\n- b2", "Middle.", "    code line")
    cur = doc("Intro.", "    code line")
    new, rep = rde.merge_edits(base, cur, [{"i": 1, "html": "<ul><li>b1 edited</li><li>b2</li></ul>"}],
                               at="2026-10-14T10:00")
    assert kinds(new) == ["para", "list", "html", "indented_code"]
    assert "<pre><code>code line" in pandoc(["-f", "gfm", "-t", "html"], new)
    assert readable_note(new).block == 1 and rep["conflicts"] == [{"i": 1, "kind": "gone"}]


def test_two_lists_put_back_in_a_row_before_a_third_keep_their_order_and_stay_three_lists():
    base = doc("Intro.", "- b1", "Middle.", "- c1", "Between.", "- d1")
    cur = doc("Intro.", "- d1")
    new, rep = rde.merge_edits(base, cur, [{"i": 1, "html": "<ul><li>b1 edited</li></ul>"},
                                           {"i": 3, "html": "<ul><li>c1 edited</li></ul>"}],
                               at="2026-10-14T10:00")
    assert lists_in(new) == 3
    assert new.index("b1 edited") < new.index("c1 edited") < new.index("- d1")
    assert rdc.parse(new).malformed == [] and len(rdc.parse(new).comments) == 2


# ── a note that would be written inside a fence the file never closed ──
# A comment in code is text, so `sheaf comments` would not list the note.

def readable_note(new):
    parsed = rdc.parse(new)
    [note] = [c for c in parsed.comments if c.by == "sheaf"]
    assert parsed.malformed == []
    return note


def test_the_note_on_a_paragraph_put_back_inside_an_unclosed_fence_is_a_comment_not_code():
    base = "Intro.\n\n```\ncode\n```\n\nBravo.\n"
    cur = "Intro.\n\n```\ncode\n"
    new, rep = rde.merge_edits(base, cur, [{"i": 2, "html": "<p>Bravo, edited.</p>"}], at="2026-10-14T10:00")
    note = readable_note(new)
    assert note.body.startswith("This paragraph was deleted in the file") and note.standalone
    assert "Bravo, edited." in new and "code" in new
    assert rep["conflicts"] == [{"i": 2, "kind": "gone"}] and rep["changed"] == [2]
    assert [b.kind for b in rde.split_md_blocks(new)] == ["para", "html", "fence"]


def test_the_note_on_a_paragraph_the_file_turned_into_an_unclosed_fence_is_a_comment_not_code():
    base = doc("Intro.", "Bravo.")
    cur = "Intro.\n\n```\ncode\n"
    new, rep = rde.merge_edits(base, cur, [{"i": 1, "html": "<p>Bravo, edited.</p>"}], at="2026-10-14T10:00")
    note = readable_note(new)
    assert "Bravo, edited." in note.body and note.standalone
    assert rep["conflicts"] == [{"i": 1, "kind": "locked"}]
    assert [b.kind for b in rde.split_md_blocks(new)] == ["para", "html", "fence"]


def test_a_note_after_a_closed_fence_stays_after_it():
    base = doc("Intro.", "```\ncode\n```", "Bravo.")
    cur = doc("Intro.", "```\ncode\n```")
    new, rep = rde.merge_edits(base, cur, [{"i": 2, "html": "<p>Bravo, edited.</p>"}], at="2026-10-14T10:00")
    readable_note(new)
    assert [b.kind for b in rde.split_md_blocks(new)] == ["para", "fence", "para"]


def test_a_paragraph_deleted_between_a_list_and_a_paragraph_adds_no_separator():
    for text in (doc("- a1", "Middle.", "Charlie."), doc("Alpha.", "Middle.", "- c1")):
        new, _ = rde.apply_edits(text, [{"i": 1, "html": ""}])
        assert "<!--" not in new


def refused(md, html):
    """The save of block 0 is skipped with a reason, and the file's text is as it was."""
    out, rep = rde.apply_edits(md, [{"i": 0, "html": html}])
    return out == md and rep["changed"] == [] and [i for i, _ in rep["skipped"]] == [0]


# ── edited HTML reaches the .md as text, never as active markup ──

def test_an_image_with_an_event_handler_in_an_edit_is_not_written_into_the_md():
    out, _ = rde.apply_edits("Hello world.\n", [{"i": 0, "html": "<p>Hello<img src=x onerror=alert(1)> world.</p>"}])
    assert "onerror" not in out and "alert" not in out
    assert out.startswith("Hello") and out.rstrip().endswith("world.")


def test_a_javascript_link_in_an_edit_keeps_its_words_and_loses_its_address():
    out, _ = rde.apply_edits("Hello world.\n", [{"i": 0, "html": '<p>Hello <a href="javascript:alert(1)">click</a> world.</p>'}])
    assert "javascript" not in out.lower() and "alert" not in out
    assert out == "Hello click world.\n"


def test_a_javascript_link_hidden_by_case_or_a_newline_is_removed_too():
    for href in ("JavaScript:alert(1)", " java\nscript:alert(1)", "vbscript:x", "data:text/html,x"):
        out, _ = rde.apply_edits("Hello world.\n", [{"i": 0, "html": f'<p>Hello <a href="{href}">click</a> world.</p>'}])
        assert out == "Hello click world.\n", (href, out)


def test_an_event_handler_on_a_kept_element_is_removed_and_the_element_stays():
    out, _ = rde.apply_edits("Hello world.\n", [{"i": 0, "html": '<p>Hello <b onclick="x()">bold</b> world.</p>'}])
    assert out == "Hello **bold** world.\n"


@pytest.mark.parametrize("html", [
    "<p>Hello</p><SVG onload=alert(1)><circle></circle></SVG>",
    "<p>Hello</p><Svg><circle></circle></Svg>",
    "<FIGURE><img src=x onerror=alert(1)></FIGURE>",
    "<p>Hello</p><Figure></Figure>",
    '<p>Hello <img src="DATA:text/html,x" onerror=alert(1)></p>',
    '<p>Hello <img src="Data:image/png;base64,AAAA"></p>',
    "<p>Hello <img src='data:image/png;base64,AAAA'></p>",
])
def test_a_chart_a_figure_or_an_embedded_image_is_refused_in_any_letter_case(html):
    assert refused("Hello world.\n", html)


def test_a_data_src_attribute_is_not_an_embedded_image():
    """`data-src` is dropped with the other data-* attributes; it is not an image's src."""
    for attr in ('data-src="DATA:text/plain,x"', "data-src='data:text/plain,x'"):
        out, rep = rde.apply_edits("Hello world.\n", [{"i": 0, "html": f"<p>Hello <span {attr}>changed</span>.</p>"}])
        assert out == "Hello changed.\n" and rep["skipped"] == [], (attr, out, rep)


def test_a_src_on_an_element_that_is_not_an_image_does_not_refuse_the_edit():
    """Only an <img> embeds an image. The sanitiser drops a data address from the `src` of any
    other element, and the words around it are an edit like any other: the edit of a
    span with `src="DATA:..."` or `src='data:...'` was once saved, and the refusal that read every
    element lost it."""
    for attr in ('src="DATA:text/plain,x"', "src='data:text/plain,x'", 'SRC="Data:image/png;base64,AAAA"'):
        out, rep = rde.apply_edits("Hello old.\n", [{"i": 0, "html": f"<p>Hello <span {attr}>changed</span>.</p>"}])
        assert out == "Hello changed.\n" and rep["skipped"] == [] and rep["changed"] == [0], (attr, out, rep)
        assert "data:" not in out.lower()


def test_a_src_on_a_span_keeps_a_link_address_and_an_image_with_a_data_address_is_still_refused():
    """The controls: a span's https `src` is as it was, and the same words around an <img> with a
    data address are still refused, in any letter case."""
    out, rep = rde.apply_edits("Hello old.\n", [{"i": 0, "html": '<p>Hello <span src="https://x.test/a.png">changed</span>.</p>'}])
    assert rep["skipped"] == [] and "changed" in out
    for img in ('<img src="DATA:image/png;base64,AAAA">', "<img src='data:image/png;base64,AAAA'>"):
        assert refused("Hello old.\n", f'<p>Hello <span src="DATA:text/plain,x">changed</span> {img}.</p>')


def test_a_paragraph_that_only_mentions_a_data_address_in_its_text_is_still_saved():
    """Text is not an attribute: the page's outerHTML leaves quotes in text as they are, so a
    paragraph about `src='data:...'` must not read as an embedded image."""
    md = "Write `src='data:x'` or `src=data:x` for an inline image.\n"
    html = ("<p>Write <code>src='data:x'</code> or <code>src=data:x</code> and "
            "<code>SRC = \"DATA:x\"</code> for an inline image, edited.</p>")
    out, rep = rde.apply_edits(md, [{"i": 0, "html": html}])
    assert rep["skipped"] == [] and rep["changed"] == [0] and "edited" in out, (out, rep)
    assert "src='data:x'" in out and "src=data:x" in out


@pytest.mark.parametrize("tag", [
    '<img src="&#100;ata:image/png;base64,AAAA">',
    '<img src=data:image/png;base64,AAAA>',
    '<img src = "data:image/png;base64,AAAA">',
    '<img alt="x"src="data:image/png;base64,AAAA">',
    '<img\nsrc="data:image/png;base64,AAAA">',
    '<img\tSRC="DATA:image/png;base64,AAAA">',
    '<img src=" data:image/png;base64,AAAA">',
])
def test_an_image_whose_src_is_a_data_address_is_refused_however_it_is_written(tag):
    assert refused("Hello world.\n", f"<p>Hello {tag}</p>")


def test_the_lowercase_chart_figure_and_embedded_image_are_still_refused():
    for html in ("<p>Hello</p><svg><circle></circle></svg>", "<figure><img src=\"x.png\"></figure>",
                 '<p>Hello <img src="data:image/png;base64,AAAA"></p>'):
        assert refused("Hello world.\n", html)


def test_a_link_to_https_and_a_task_box_survive_an_edit():
    out, _ = rde.apply_edits("See the page.\n", [{"i": 0, "html": '<p>See <a href="https://example.com/x">the page</a> now.</p>'}])
    assert out == "See [the page](https://example.com/x) now.\n"
    tasks, _ = rde.apply_edits("- [ ] one\n- [x] two\n", [{"i": 0, "html":
        '<ul><li><input type="checkbox" disabled> one more</li><li><input type="checkbox" checked disabled> two</li></ul>'}])
    assert "[ ] one more" in tasks and "[x] two" in tasks


# ── a comment the file gained lands on the block that holds its words ──

AT = "2026-10-14T10:00"


def agent_note(cid="c1", quote="Alpha", by="Codex", at="2026-10-14T09:30", body="on alpha"):
    return rdc.Comment(id=cid, by=by, at=at, quote=quote, body=body)


def the_note(out, by="Codex"):
    return next(c for c in rdc.parse(out).comments if c.by == by)


def test_a_comment_the_file_gained_stays_on_its_words_when_the_page_splits_the_paragraph():
    base = "Alpha Beta.\n"
    cur = "Alpha" + rdc.format(agent_note(), False) + " Beta.\n"
    out, rep = rde.merge_edits(base, cur, [{"i": 0, "html": "<p>Alpha edited.</p><p>Beta.</p>"}], AT)
    note = the_note(out)
    assert out[:note.start].endswith("Alpha") and "Beta" not in out[:note.start], out
    assert out.index("Alpha") < note.start < out.index("Beta.") and " edited." in out[note.end:]
    assert rep["conflicts"] == [] and rdc.parse(out).malformed == []


def test_a_comment_on_the_words_that_went_to_the_second_block_follows_them_there():
    base = "Alpha Beta.\n"
    cur = "Alpha Beta" + rdc.format(agent_note(quote="Beta", body="on beta"), False) + ".\n"
    out, _ = rde.merge_edits(base, cur, [{"i": 0, "html": "<p>Alpha edited.</p><p>Beta.</p>"}], AT)
    note = the_note(out)
    assert out[:note.start].endswith("Beta"), out
    assert out.index("Alpha") < out.index("Beta") <= note.start


def test_two_comments_the_file_gained_each_follow_their_own_words_across_a_split():
    base = "Alpha Beta.\n"
    cur = ("Alpha" + rdc.format(agent_note("c1", "Alpha", body="on alpha"), False)
           + " Beta" + rdc.format(agent_note("c2", "Beta", by="Eve", body="on beta"), False) + ".\n")
    out, _ = rde.merge_edits(base, cur, [{"i": 0, "html": "<p>Alpha edited.</p><p>Beta.</p>"}], AT)
    first, second = the_note(out), the_note(out, "Eve")
    assert out[:first.start].endswith("Alpha") and "Beta" not in out[:first.start]
    assert out[:second.start].endswith("Beta")


def test_when_none_of_the_blocks_holds_the_words_the_comment_goes_to_the_last_that_says_something():
    base = "Alpha Beta.\n"
    cur = "Alpha" + rdc.format(agent_note(), False) + " Beta.\n"
    out, _ = rde.merge_edits(base, cur, [{"i": 0, "html": "<p>One.</p><p>Two.</p>"}], AT)
    note = the_note(out)
    assert out[:note.start].endswith("Two.") and rdc.parse(out).malformed == [], out


def test_without_a_split_the_comment_the_file_gained_keeps_its_place():
    base = "Alpha Beta.\n"
    cur = "Alpha" + rdc.format(agent_note(), False) + " Beta.\n"
    out, _ = rde.merge_edits(base, cur, [{"i": 0, "html": "<p>Alpha edited. Beta.</p>"}], AT)
    note = the_note(out)
    assert out[:note.start].endswith("Alpha") and "Beta" not in out[:note.start], out


# ── an id the file reused for a new comment is not the page's old comment ──

STALE_ANCHOR = '<span class="rd-anchor" data-rd-id="c1"></span>'


def test_a_new_comment_with_the_id_of_a_deleted_one_is_not_moved_to_the_deleted_ones_anchor():
    old = agent_note("c1", "Alpha", by="Ada", at="2026-10-14T09:00", body="old note")
    new = agent_note("c1", "Beta", body="new note")
    base = "Alpha" + rdc.format(old, False) + " and Beta words.\n"
    cur = "Alpha and Beta" + rdc.format(new, False) + " words.\n"
    out, rep = rde.merge_edits(base, cur, [{"i": 0, "html": f"<p>Alpha{STALE_ANCHOR} and Beta words edited.</p>"}], AT)
    parsed = rdc.parse(out)
    assert [c.id for c in parsed.comments] == ["c1"] and parsed.malformed == []
    note = the_note(out)
    assert note.body == "new note" and out[:note.start].endswith("Beta"), out
    assert rep["conflicts"] == []


def test_with_a_fresh_id_the_comment_the_file_gained_keeps_its_place():
    old = agent_note("c1", "Alpha", by="Ada", at="2026-10-14T09:00", body="old note")
    new = agent_note("c2", "Beta", body="new note")
    base = "Alpha" + rdc.format(old, False) + " and Beta words.\n"
    cur = "Alpha and Beta" + rdc.format(new, False) + " words.\n"
    out, _ = rde.merge_edits(base, cur, [{"i": 0, "html": f"<p>Alpha{STALE_ANCHOR} and Beta words edited.</p>"}], AT)
    assert out[:the_note(out).start].endswith("Beta"), out


def test_a_comment_the_file_changed_but_did_not_replace_stays_where_the_page_put_its_anchor():
    """Same id, author, time and words: the agent resolved it. The page may have moved its anchor."""
    held = agent_note("c1", "Alpha", by="Ada", at="2026-10-14T09:00", body="old note")
    base = "Alpha" + rdc.format(held, False) + " and Beta words.\n"
    held.status = "resolved"
    cur = "Alpha" + rdc.format(held, False) + " and Beta words.\n"
    moved = '<p>Alpha and Beta<span class="rd-anchor" data-rd-id="c1"></span> words edited.</p>'
    out, rep = rde.merge_edits(base, cur, [{"i": 0, "html": moved}], AT)
    note = the_note(out, "Ada")
    assert note.status == "resolved" and out[:note.start].endswith("Beta"), out
    assert [c.id for c in rdc.parse(out).comments] == ["c1"] and rep["conflicts"] == []


# ── a comment the file gained stays on its own occurrence of a repeated quote ──

def test_a_comment_the_file_gained_on_the_second_of_two_equal_passages_stays_on_it():
    base = "foo and foo.\n"
    cur = "foo and foo" + rdc.format(agent_note(quote="foo", body="second one"), False) + ".\n"
    out, _ = rde.merge_edits(base, cur, [{"i": 0, "html": "<p>foo and foo now.</p>"}], AT)
    assert out[:the_note(out).start].endswith("foo and foo"), out


def test_a_comment_on_the_first_of_two_equal_passages_stays_on_the_first():
    base = "foo and foo.\n"
    cur = "foo" + rdc.format(agent_note(quote="foo", body="first one"), False) + " and foo.\n"
    out, _ = rde.merge_edits(base, cur, [{"i": 0, "html": "<p>foo and foo now.</p>"}], AT)
    assert out[:the_note(out).start] == "foo", out


def test_a_comment_on_the_third_of_three_equal_passages_stays_on_it_through_an_edit_before_it():
    base = "foo, foo and foo.\n"
    cur = "foo, foo and foo" + rdc.format(agent_note(quote="foo", body="third"), False) + ".\n"
    out, _ = rde.merge_edits(base, cur, [{"i": 0, "html": "<p>Well, foo, foo and foo.</p>"}], AT)
    assert out[:the_note(out).start].endswith("foo, foo and foo"), out


def test_a_comment_on_the_second_equal_passage_follows_it_into_the_second_block_of_a_split():
    base = "foo and foo.\n"
    cur = "foo and foo" + rdc.format(agent_note(quote="foo", body="second one"), False) + ".\n"
    out, _ = rde.merge_edits(base, cur, [{"i": 0, "html": "<p>foo and</p><p>foo.</p>"}], AT)
    assert out[:the_note(out).start].endswith("foo and\n\nfoo"), out


def test_a_comment_whose_occurrence_the_page_removed_goes_to_the_end_of_the_block():
    base = "foo and foo.\n"
    cur = "foo and foo" + rdc.format(agent_note(quote="foo", body="second one"), False) + ".\n"
    out, _ = rde.merge_edits(base, cur, [{"i": 0, "html": "<p>foo only.</p>"}], AT)
    assert out[:the_note(out).start] == "foo only.", out


def test_a_comment_on_a_unique_quote_keeps_its_place_among_other_words():
    base = "foo and bar.\n"
    cur = "foo and bar" + rdc.format(agent_note(quote="bar", body="n"), False) + ".\n"
    out, _ = rde.merge_edits(base, cur, [{"i": 0, "html": "<p>foo and bar now.</p>"}], AT)
    assert out[:the_note(out).start].endswith("foo and bar"), out


# ── Enter in a paragraph or a heading ──
# The block is the element being edited, so the browser cannot split it: each line after Enter is a <div>
# inside it, which pandoc wrote into the .md as raw <div> and </div> lines around the words.

@pytest.mark.parametrize("html, md", [
    ("<p>Last paragraph.<div>Split off.</div></p>", "Last paragraph.\n\nSplit off."),
    ("<p>Last paragraph.<div><br></div><div>Split off.</div></p>", "Last paragraph.\n\nSplit off."),
    ("<p>First,<div>second,</div><div>third.</div></p>", "First,\n\nsecond,\n\nthird."),
    ("<p>Some <b>bold</b> words.<div>And <i>more</i>.</div></p>", "Some **bold** words.\n\nAnd *more*."),
    ("<h2>A title<div>A line under it.</div></h2>", "## A title\n\nA line under it."),
    ("<p>Last&nbsp;<div>paragraph.</div></p>", "Last\n\nparagraph."),
    ("<p>Last<div>&nbsp;paragraph.</div></p>", "Last\n\nparagraph."),
    ("<p>One&nbsp;line.</p>", "One\u00a0line."),
    ("<p>One line.</p>", "One line.")],
    ids=["Enter at the end", "Enter twice", "two lines", "inline marks", "a heading", "Enter after a space",
         "Enter before a space", "a no-break space and no Enter", "no Enter"])
def test_a_line_after_enter_is_a_paragraph_of_its_own(html, md):
    assert rde.html_block_to_md(html) == md


# Enter or Shift+Enter inside a line that is already a <div> nests the next <div> in it; the .md got a raw
# <div> block around the words, which the page then locked.
@pytest.mark.parametrize("html, md", [
    ("<p>One<div>Two<div>Three</div></div></p>", "One\n\nTwo\n\nThree"),
    ("<p>One<br>Two<div>Three<br><div><br></div></div></p>", "One\\\nTwo\n\nThree"),
    ("<p>One<div><div>Two</div></div></p>", "One\n\nTwo"),
    ("<p><div>Only line<div><br></div></div></p>", "Only line"),
    ("<p>One<div>Two<div>Three</div>Four</div></p>", "One\n\nTwo\n\nThree\n\nFour"),
    ("<h2>Title<div>Two<div>Three</div></div></h2>", "## Title\n\nTwo\n\nThree")],
    ids=["nested", "nested after a line break", "nested only", "empty nested", "words after the nested", "a heading"])
def test_a_div_nested_in_a_line_is_a_paragraph_of_its_own(html, md):
    assert rde.html_block_to_md(html) == md


# A line typed as `- [ ] x` at the start of a paragraph is a task item, not the characters.
@pytest.mark.parametrize("html, md", [
    ("<p>- [ ] buy milk</p>", "- [ ] buy milk"),
    ("<p>- [x] buy milk</p>", "- [x] buy milk"),
    ("<p>- [X] buy milk</p>", "- [x] buy milk"),
    ("<p>* [ ] buy milk</p>", "- [ ] buy milk"),
    ("<p>- [ ] buy <b>fresh</b> milk</p>", "- [ ] buy **fresh** milk"),
    ("<p>Intro<div>- [ ] after Enter</div></p>", "Intro\n\n- [ ] after Enter"),
    ("<p>- [ ] one<div>- [x] two</div></p>", "- [ ] one\n- [x] two"),
    ("<p>- [ ] one</p>\n<p>- [x] two</p>", "- [ ] one\n- [x] two"),
    ("<p>-\u00a0[ ]\u00a0pasted</p>", "- [ ] pasted"),
    ("<p>- [ ] <b>bold</b> start</p>", "- [ ] **bold** start"),
    ("<p>- [ ] <code>x</code></p>", "- [ ] `x`"),
    ("<p>- [ ] </p>", "\\- \\[ \\]"),
    ("<p>buy milk [ ] then more</p>", "buy milk \\[ \\] then more"),
    ("<p>See - [ ] here</p>", "See - \\[ \\] here"),
    ("<p>-[ ] no space</p>", "-\\[ \\] no space"),
    ("<p>- [] empty</p>", "\\- \\[\\] empty"),
    ("<p>1. [ ] numbered</p>", "1\\. \\[ \\] numbered")],
    ids=["open", "done", "capital X", "asterisk", "inline mark", "after Enter", "two lines", "newline between", "no-break spaces", "marked first word", "code first", "no words", "mid-sentence",
         "dash mid-sentence", "no space after the dash", "no space in the brackets", "numbered"])
def test_a_typed_task_line_becomes_a_task_item_and_other_text_stays_literal(html, md):
    assert rde.html_block_to_md(html) == md


# A box with nothing after it that shows (a break, a comment, an empty mark) is no task: the typed words stay.
@pytest.mark.parametrize("html, md", [
    ("<p>- [ ] <br></p>", "\\- \\[ \\]"),
    ("<p>- [ ]\u00a0<br></p>", "\\- \\[ \\]\u00a0"),
    ("<p>- [ ] <!-- c --></p>", "\\- \\[ \\]"),
    ("<p>- [ ] <b></b></p>", "\\- \\[ \\]"),
    ("<p>- [ ] <span> </span></p>", "\\- \\[ \\]"),
    ("<p>- [ ] <br>more</p>", "- [ ] more"),
    ("<p>- [ ] <b></b><br>x</p>", "- [ ] x"),
    ("<p>- [ ] <span></span><br>x</p>", "- [ ] x"),
    ("<p>- [ ] <br><br>x</p>", "- [ ] x"),
    ("<p>- [ ] \u200b</p>", "\\- \\[ \\] \u200b"),
    ("<p>- [ ] <b>\u200b</b></p>", "\\- \\[ \\] **\u200b**"),
    ("<p>- [ ] \u200bwords</p>", "- [ ] words"),
    ("<p>- [ ] <em><br>words</em></p>", "- [ ] *words*"),
    ("<p>- [ ] <em><b><br></b>words</em> end</p>", "- [ ] *words* end"),
    ("<p>- [ ] <del><br>words</del></p>", "- [ ] ~~words~~"),
    ("<p>- [ ] <a href='https://x.y/'><br>words</a></p>", "- [ ] [words](https://x.y/)"),
    ("<p>- [ ] <img src='https://x.y/a.png'></p>", "- [ ] ![](https://x.y/a.png)"),
    ("<p>- [ ] <img src='https://x.y/a.png'> words</p>", "- [ ] ![](https://x.y/a.png) words")],
    ids=["break", "no-break space and a break", "comment", "empty mark", "blank span", "break then words", "empty mark then break", "empty span then break", "two breaks", "a zero-width space", "a zero-width space in a mark", "a zero-width space then words", "a break opening a mark", "a break in a mark in a mark", "a break in a strike", "a break in a link", "an image alone", "an image and words"])
def test_a_typed_task_box_with_nothing_after_it_stays_the_typed_characters(html, md):
    assert rde.html_block_to_md(html) == md


def test_a_typed_task_line_in_code_or_a_quote_stays_literal():
    assert "- [ ] x" in rde.html_block_to_md("<pre><code>- [ ] x\n</code></pre>")
    assert "[ ]" in rde.html_block_to_md("<blockquote><p>- [ ] x</p></blockquote>").replace("\\", "")
    assert "- [ ] x" not in rde.html_block_to_md("<blockquote><p>- [ ] x</p></blockquote>")


# Enter inside a task item: the browser writes a <div> in the <li>; each line is a task item after it.
@pytest.mark.parametrize("html, md", [
    ('<ul><li><input type="checkbox"> b<div>- [ ] a</div></li></ul>', "- [ ] b\n- [ ] a"),
    ('<ul><li><input type="checkbox"> b<div>a</div></li></ul>', "- [ ] b\n- [ ] a"),
    ('<ul><li><input type="checkbox" checked> b<div>- [x] a</div></li></ul>', "- [x] b\n- [x] a"),
    ('<ul><li><input type="checkbox"> b<div>a</div><div>c</div></li><li><input type="checkbox" checked> z</li></ul>',
     "- [ ] b\n- [ ] a\n- [ ] c\n- [x] z"),
    ('<ul><li><input type="checkbox"> b<div>a<div>c</div></div></li></ul>', "- [ ] b\n- [ ] a\n- [ ] c"),
    ('<ul><li><input type="checkbox"> b<div><br></div></li></ul>', "- [ ] b"),
    ('<ul><li><input type="checkbox"> b<div>a</div>tail</li></ul>', "- [ ] b\n- [ ] a\n- [ ] tail"),
    ('<ul><li><input type="checkbox"> b<div>a</div><div></div></li></ul>', "- [ ] b\n- [ ] a"),
    ('<ul><li><input type="checkbox"> b<div><div><br></div></div></li></ul>', "- [ ] b"),
    ('<ul><li><input type="checkbox"> b<div>\u200b</div></li></ul>', "- [ ] b"),
    ('<ul><li><input type="checkbox"> b<div>- [ ] </div></li></ul>', "- [ ] b\n- \\- \\[ \\]"),
    ('<ul><li><input type="checkbox"> b<div>- [ ] <br></div></li></ul>', "- [ ] b\n- \\- \\[ \\]"),
    ('<ul><li><input type="checkbox"> <div>b</div></li><li><input type="checkbox"> c</li></ul>', "- [ ] b\n- [ ] c"),
    ('<ul><li><input type="checkbox"><div>a</div></li></ul>', "- [ ] a"),
    ('<ul><li><input type="checkbox"> b<div>a</div><ul><li><input type="checkbox"> n</li></ul></li></ul>', "- [ ] b\n- [ ] a\n  - [ ] n"),
    ('<ul><li><input type="checkbox"> b<div><br>a</div></li></ul>', "- [ ] b\n- [ ] a"),
    ('<ul><li><input type="checkbox"> b<div>a</div><br>t</li></ul>', "- [ ] b\n- [ ] a\n- [ ] t"),
    ('<ul><li><input type="checkbox"> b<div><div>a</div>tail</div></li></ul>', "- [ ] b\n- [ ] a\n- [ ] tail"),
    ('<ul><li><input type="checkbox"> b<div><p>a</p></div></li></ul>', "- [ ] b\n- [ ] a"),
    ('<ul><li><input type="checkbox"> b<div><em><br>a</em></div></li></ul>', "- [ ] b\n- [ ] *a*"),
    ('<ul><li><input type="checkbox" checked> b<div>a</div></li></ul>', "- [x] b\n- [ ] a"),
    ('<ul class="task-list"><li><label><input type="checkbox">b</label><div>a</div></li></ul>', "- [ ] b\n- [ ] a"),
    ('<ul class="task-list"><li><label><input type="checkbox">b<div>a</div></label></li></ul>', "- [ ] b\n- [ ] a"),
    ('<ul class="task-list"><li><p><label><input type="checkbox">b</label></p><div>- [x] a</div></li><li><p><label><input type="checkbox">c</label></p></li></ul>', "- [ ] b\n\n- [x] a\n\n- [ ] c"),
    ('<ul><li><label><input type="checkbox"></label><div>b</div></li></ul>', "- [ ] b"),
    ('<ul><li><input type="checkbox"> b<div><input type="checkbox" checked> a</div></li></ul>', "- [ ] b\n- [x] a"),
    ('<ul><li><input type="checkbox"> b<div><ul><li>q</li></ul></div></li></ul>', "- [ ] b\n  - q"),
    ('<ul><li><label><input type="checkbox">a<div>b</div><div>c</div></label></li></ul>', "- [ ] a\n- [ ] b\n- [ ] c"),
    ('<ul><li><p><label><input type="checkbox">a<div>b</div><div>c</div></label></p></li></ul>', "- [ ] a\n\n- [ ] b\n\n- [ ] c"),
    ('<ul><li><label><input type="checkbox">a<div>b</div>tail</label></li></ul>', "- [ ] a\n- [ ] b\n- [ ] tail"),
    ('<ul><li><input type="checkbox">a<div><ol><li>z</li></ol>b</div></li></ul>', "- [ ] a\n  1.  z\n- [ ] b"),
    ('<ul><li><input type="checkbox">a<div><p>b</p><p>c</p></div></li></ul>', "- [ ] a\n- [ ] b\n- [ ] c"),
    ('<ul><li><p><label><input type="checkbox">a<div>b</div></label></p><p>more</p></li></ul>', "- [ ] a\n\n- [ ] b\n\n  more"),
    ('<ul><li><p><label><input type="checkbox">a<div>b</div>c</label>d</p></li></ul>', "- [ ] a\n\n- [ ] b\n\n- [ ] cd"),
    ('<ul><li><input type="checkbox">a<div>- [x] <img src="https://x.y/i.png"></div></li></ul>', "- [ ] a\n- [x] ![](https://x.y/i.png)"),
    ('<ul><li><input type="checkbox">a<div>- [ ] </div><ul><li>sub</li></ul></li></ul>', "- [ ] a\n- \\- \\[ \\]\n  - sub"),
    ('<ul><li><input type="checkbox">a<div>- [ ] <br>words</div></li></ul>', "- [ ] a\n- [ ] words"),
    ('<ul><li><input type="checkbox">a<div>- [ ] <ul><li>sub</li></ul>tail</div></li></ul>', "- [ ] a\n- \\- \\[ \\]\n  - sub\n\n  tail"),
    ('<ul><li><input type="checkbox">a<div>- [x] u<div>w</div></div></li></ul>', "- [ ] a\n- [x] u\n- [ ] w"),
    ('<ul><li><input type="checkbox">a<div><span class="rd-anchor"></span><br>b</div></li></ul>', "- [ ] a\n- [ ] <span class=\"rd-anchor\"></span>b")],
    ids=["typed task line", "plain words", "done", "two lines and a next item", "nested line", "empty line",
         "words after a line", "an empty div", "an empty nested div", "a zero-width line", "a typed box and no words", "a typed box and a break", "Enter right after the box", "Enter right after a bare box", "a sublist after a line", "a line that opens with a break", "words after a break after a line", "a line holding a line and words", "a line holding a paragraph", "a line that opens with a mark and a break", "a line under a done item", "as the page renders it", "a line inside the label", "a loose list", "Enter right after the box in a label", "a ticked box in a line", "a line of only a list", "two lines in a label", "two lines in a loose label", "words after a line in a label", "a line that opens with a list", "two paragraphs in a line", "a paragraph after a line", "text after a label in a paragraph", "a typed box and an image", "a typed box and a sublist", "a typed box, a break and words", "a typed box, a sublist and words", "a ticked box, words and a nested line", "an anchor then a break"])
def test_enter_inside_a_task_item_makes_a_task_item_not_raw_html(html, md):
    out = rde.html_block_to_md(html)
    assert out == md and "<div" not in out


# An item the page made with Enter and nothing typed yet is not saved (pandoc would write `- ☐`), and an empty
# paragraph between two lists, where Enter on an empty item ended one, goes with the two lists made one again.
@pytest.mark.parametrize("html, md", [
    ('<ul><li><label><input type="checkbox"> a</label></li><li data-rd-fresh=""><label><input type="checkbox"> </label></li></ul>', "- [ ] a"),
    ('<ul><li><label><input type="checkbox"> a</label></li><li data-rd-fresh=""><p><label><input type="checkbox"></label></p></li><li><label><input type="checkbox"> b</label></li></ul>', "- [ ] a\n- [ ] b"),
    ('<ul><li data-rd-fresh=""><label><input type="checkbox"></label></li><li><label><input type="checkbox"> a</label></li></ul>', "- [ ] a"),
    ('<ul><li><label><input type="checkbox"> a</label></li></ul><p data-rd-fresh=""><br></p><ul><li><label><input type="checkbox"> b</label></li></ul>', "- [ ] a\n- [ ] b"),
    ('<ul><li>plain</li><li><label><input type="checkbox"> x</label></li></ul><p data-rd-fresh=""><br></p><ul><li><label><input type="checkbox"> b</label></li></ul>', "- plain\n- [ ] x\n- [ ] b"),
    ('<ul><li><label><input type="checkbox"> a</label></li></ul><p data-rd-fresh="">between</p><ul><li><label><input type="checkbox"> b</label></li></ul>', "- [ ] a\n\nbetween\n\n- [ ] b"),
    ('<ul><li><label><input type="checkbox"> a</label></li><li data-rd-fresh=""><label><input type="checkbox"> typed</label></li></ul>', "- [ ] a\n- [ ] typed"),
    ('<ul><li data-rd-fresh=""><label><input type="checkbox"> a<ul><li>sub</li></ul></label></li></ul>', "- [ ] a\n  - sub"),
    ('<ul><li><label><input type="checkbox" checked=""> a</label></li><li data-rd-fresh=""><label><input type="checkbox"> \u200b</label></li></ul>', "- [x] a"),
    ('<ul><li><label><input type="checkbox"> a</label></li></ul><p data-rd-fresh=""><br><div><br></div></p><ul><li><label><input type="checkbox"> b</label></li></ul>', "- [ ] a\n- [ ] b"),
    ('<ul><li><label><input type="checkbox"> a</label></li></ul><p data-rd-fresh=""><br><div><br></div><div><br></div></p><ul><li><label><input type="checkbox"> b</label></li></ul>', "- [ ] a\n- [ ] b"),
    ('<ul><li><label><input type="checkbox"> a</label></li></ul><p data-rd-fresh=""><br><div>typed</div></p><ul><li><label><input type="checkbox"> b</label></li></ul>', "- [ ] a\n\ntyped\n\n- [ ] b")],
    ids=["an empty item after one", "an empty loose item between", "an empty item first", "an empty paragraph between two lists",
         "an empty paragraph between a list with a plain item and a task list", "a paragraph with words between two lists",
         "an item with words", "an item with a sublist", "a zero-width item", "an empty paragraph with a line in it between two lists",
         "an empty paragraph with two lines in it between two lists", "an empty paragraph with a typed line between two lists"])
def test_an_empty_task_item_and_paragraph_the_page_made_are_not_saved(html, md):
    out = rde.html_block_to_md(html)
    assert out == md and "☐" not in out and "<!--" not in out and "data-rd" not in out


# Enter on an empty item ends a list: a list, a paragraph and a list in one block. A task typed in the paragraph
# joins the lists around it, or pandoc would write `<!-- -->` on both sides of it.
@pytest.mark.parametrize("html, md", [
    ('<ul><li><label><input type="checkbox"> a</label></li></ul><p>- [ ] typed</p><ul><li><label><input type="checkbox"> b</label></li></ul>',
     "- [ ] a\n- [ ] typed\n- [ ] b"),
    ('<ul><li><label><input type="checkbox"> a</label></li></ul><p>- [x] typed</p>', "- [ ] a\n- [x] typed"),
    ('<p>- [ ] typed</p><ul><li><label><input type="checkbox"> b</label></li></ul>', "- [ ] typed\n- [ ] b"),
    ('<ul><li><label><input type="checkbox"> a</label></li></ul><p>- [ ] one</p><p>- [ ] two</p><ul><li><label><input type="checkbox"> b</label></li></ul>',
     "- [ ] a\n- [ ] one\n- [ ] two\n- [ ] b"),
    ('<ul><li><label><input type="checkbox"> a</label></li></ul><p>words</p><p>- [ ] typed</p><ul><li><label><input type="checkbox"> b</label></li></ul>',
     "- [ ] a\n\nwords\n\n- [ ] typed\n- [ ] b")],
    ids=["between two lists", "after a list", "before a list", "two between two lists", "after a paragraph of words"])
def test_a_typed_task_line_beside_a_list_in_the_block_joins_it_with_no_comment_marker(html, md):
    out = rde.html_block_to_md(html)
    assert out == md and "<!--" not in out


@pytest.mark.parametrize("html, md", [
    ('<ul><li><label><input type="checkbox"> a</label></li><li data-rd-fresh=""><label><input type="checkbox"> \u00a0Newtask</label></li></ul>', "- [ ] a\n- [ ] Newtask"),
    ('<ul><li data-rd-fresh=""><label><input type="checkbox">&nbsp;</label>&nbsp;<em>word</em></li></ul>', "- [ ] *word*"),
    ('<ul><li><label><input type="checkbox"> a</label></li><li data-rd-fresh=""><label><input type="checkbox"> New task</label></li></ul>', "- [ ] a\n- [ ] New task"),
    ('<ul><li data-rd-fresh=""><label><input type="checkbox"><br>b</label></li></ul>', "- [ ] b"),
    ('<ul><li data-rd-fresh=""><label><input type="checkbox">\u00a0New<img src="https://x.y/i.png"> w</label></li></ul>', "- [ ] New![](https://x.y/i.png) w"),
    ('<ul><li data-rd-fresh=""><label><input type="checkbox"> <code> b c</code></label></li></ul>', "- [ ] ` b c`")],
    ids=["a no-break space before the typed words", "a no-break space before a mark", "plain words", "a soft break that opened the item",
         "typed words before an image", "code keeps its own space"])
def test_the_no_break_space_the_browser_writes_before_words_typed_in_an_item_the_page_made_is_not_saved(html, md):
    out = rde.html_block_to_md(html)
    assert out == md and "\u00a0" not in out and "&nbsp;" not in out


def test_an_item_or_paragraph_that_was_in_the_file_is_kept_however_little_it_holds():
    md = "* [ ] a\n* [ ] &nbsp;\n* [ ] b\n"
    out, _ = rde.apply_edits(md, [{"i": 0, "html": "<ul><li><label><input type=\"checkbox\"> ax</label></li>"
                                  "<li><label><input type=\"checkbox\"> \u00a0</label></li>"
                                  "<li><label><input type=\"checkbox\"> b</label></li></ul>"}])
    assert out.count("[ ]") == 3


def test_a_saved_typed_task_line_is_a_task_item_in_the_file():
    md, _ = rde.apply_edits(doc("First.", "Second."), [{"i": 1, "html": "<p>- [ ] test</p>"}])
    assert md == doc("First.", "- [ ] test")


def unwrapped_rows():
    from sheafmd import diagnostics
    return [r for r in diagnostics.read() if r["kind"] == "markup-unwrapped"]


# A <div> or a <span style> the browser wrote that the source block did not have never reaches the .md: it is
# unwrapped, and a diagnostics row says so. What the source had stays as it was.
@pytest.mark.parametrize("html, md", [
    ("<div>Whole paragraph, wrapped.</div>", "Whole paragraph, wrapped."),
    ("<p><div style='margin: 0'>Styled line.</div></p>", "Styled line."),
    ("<p><span style=\"font-size: 1rem;\">Merged words.</span></p>", "Merged words."),
    ("<p>Some <span style=\"color: red\">red</span> words.</p>", "Some red words."),
    ("<p><b><span style=\"font-weight: 400\">Inner</span></b> words.</p>", "**Inner** words.")],
    ids=["a div around the block", "a styled div", "a span around the block", "a span inside", "a span in a mark"])
def test_markup_the_source_did_not_have_is_unwrapped_and_logged(html, md):
    new, rep = rde.apply_edits("Before.\n\nOld words.\n", [{"i": 1, "html": html}])
    assert new == f"Before.\n\n{md}\n" and rep["changed"] == [1]
    [row] = unwrapped_rows()
    assert row["source"] == "hub" and "<div" not in new and "<span" not in new


# What a paste brings in (the clipboard's text/html of a mail client, a word processor, a web page) is styled
# markup; the markdown keeps the words and their plain marks only.
@pytest.mark.parametrize("html, md", [
    ('<p><div dir="ltr" style="font-family:Arial"><span style="font-size:12pt">Pasted <b>bold</b> and '
     '<a href="https://example.com/x" style="font-size: 12pt">a link</a>.</span></div><div><br></div>'
     '<div>Second line.</div></p>',
     "Pasted **bold** and [a link](https://example.com/x).\n\nSecond line."),
    ('<p><b style="font-weight:normal" id="docs-internal-guid-1"><span style="font-weight:400">Doc one.</span></b></p>',
     "Doc one."),
    ('<p class="lead" style="margin:0">Web <em>text</em> <span class="x">here</span> and '
     '<a class="ext" href="https://example.com/y" target="_blank">there</a>.</p>',
     "Web *text* here and [there](https://example.com/y).")],
    ids=["a mail client", "a word processor", "a web page"])
def test_pasted_markup_is_saved_as_plain_markdown(html, md):
    new, rep = rde.apply_edits("Before.\n\nOld words.\n", [{"i": 1, "html": html}])
    assert new == f"Before.\n\n{md}\n"


def test_a_table_keeps_its_column_alignment_through_an_edit():
    src = "| Fruit | Qty |\n| :--- | ---: |\n| apples | 3 |\n"
    new, rep = rde.apply_edits(src, [{"i": 0, "html": (
        '<div class="tblwrap"><table><thead><tr><th style="text-align: left;">Fruit</th>'
        '<th style="text-align: right;">Qty</th></tr></thead><tbody><tr><td style="text-align: left;">pears</td>'
        '<td style="text-align: right;">3</td></tr></tbody></table></div>')}])
    assert ":---" in new and "---:" in new and "pears" in new and "<" not in new


# A <div> is a line: unwrapped, its words must not run into the text around it ("Hi" and "line two" must
# not become "Hiline two").
@pytest.mark.parametrize("src, html, md", [
    ("Hi\n", '<p>Hi<div style="font-family:Arial">line two</div><div style="font-family:Arial">line three</div></p>',
     "Hi\n\nline two\n\nline three"),
    ("Hi\n", '<p>Hi<div dir="ltr">Dear Ada,<div><br></div><div>Thanks</div></div></p>',
     "Hi\n\nDear Ada,\n\nThanks"),
    ("Hi\n", '<p>Hi<div data-block="true">pasted line</div></p>', "Hi\n\npasted line"),
    ("- one\n", "<ul><li>one<div>new</div></li></ul>", "- one  \n  new"),
    ("- one\n", "<ul><li><div>one</div><div>new</div></li></ul>", "- one  \n  new")],
    ids=["styled lines", "a mail's nested lines", "a data attribute", "a list item", "a list item of lines"])
def test_a_div_unwrapped_keeps_its_words_apart_from_the_text_around_it(src, html, md):
    out = rde.html_block_to_md(html, src, [])
    assert "<div" not in out and out.replace("\\\n", "  \n") == md


def test_a_cell_of_lines_keeps_them_apart():
    html = "<table><thead><tr><th>A</th></tr></thead><tbody><tr><td><div>1</div><div>2</div></td></tr></tbody></table>"
    out = rde.html_block_to_md(html, "| A |\n| - |\n| 1 |\n", [])
    assert "<div" not in out and "12" not in out and "1<br>2" in out


def test_the_note_of_a_block_the_file_locked_holds_no_raw_div():
    note = rde._page_text('<p>Hi<div style="x">Two</div><span style="y">three</span></p>')
    assert "<div" not in note and "<span" not in note and "Hi" in note and "Two" in note and "three" in note


def test_a_math_span_the_render_wrote_is_not_unwrapped():
    html = '<p>Area <span class="math inline"><em>x</em><sup>2</sup></span> more.</p>'
    assert rde.html_block_to_md(html, "Area $x^2$.\n", []) == rde.html_block_to_md(html)
    strays = []
    rde.html_block_to_md(html, "Area $x^2$.\n", strays)
    assert strays == []


def test_a_span_the_source_has_stays_byte_for_byte_and_is_not_logged():
    src = 'Some <span style="color: red">red</span> words.\n'
    new, rep = rde.apply_edits("Before.\n\n" + src, [
        {"i": 1, "html": '<p>Some <span style="color: red">red</span> words, more.</p>'}])
    assert new == 'Before.\n\nSome <span style="color: red">red</span> words, more.\n'
    assert not unwrapped_rows()


def test_a_save_that_changes_nothing_logs_nothing_about_markup():
    rde.apply_edits("Before.\n\nWords.\n", [{"i": 1, "html": "<p>Words.</p>"}])
    assert not unwrapped_rows()


# The no-break space goes only where Enter cut the line: one at the start of the paragraph, at the end of its
# last line, or in code at the cut was typed there, and stays as it would without the Enter.
@pytest.mark.parametrize("before, after", [
    ("&nbsp;&nbsp;Indented", "next"), ("Some", "last line&nbsp;"), ("<code>&nbsp;x&nbsp;</code>", "next"),
    ("a <code>x&nbsp;</code>", "<code>&nbsp;y</code> b")],
    ids=["at the start", "at the end", "code at the edges", "code at the cut"])
def test_enter_takes_a_no_break_space_from_the_cut_only(before, after):
    split = rde.html_block_to_md(f"<p>{before}<div>{after}</div></p>")
    assert split == rde.html_block_to_md(f"<p>{before}</p>") + "\n\n" + rde.html_block_to_md(f"<p>{after}</p>")


def test_a_paragraph_split_by_enter_is_saved_as_two_paragraphs():
    text = doc("Alpha.", "Bravo.")
    new, rep = rde.apply_edits(text, [{"i": 1, "html": "<p>Bravo.<div>Charlie.</div></p>"}])
    assert new == doc("Alpha.", "Bravo.", "Charlie.") and rep["remap"]


@pytest.mark.parametrize("line", [False, True], ids=["in the paragraph", "in the line after Enter"])
def test_a_comment_keeps_its_words_when_its_paragraph_is_split_by_enter(line):
    text = doc("Alpha.", "Bravo, about pears.")
    blk, s, e = rdc.find_quote(text, "about pears")
    text, cid = rdc.add_comment(text, blk, s, e, "about pears", "Why?", "Ada", "2026-10-18T10:00")
    a = f'<span class="rd-anchor" data-rd-id="{cid}"></span>'
    html = (f"<p>Bravo.<div>Charlie, about pears{a}.</div></p>" if line
            else f"<p>Bravo, about pears{a}.<div>Charlie.</div></p>")
    new, _ = rde.apply_edits(text, [{"i": 1, "html": html}])
    [c] = rdc.parse(new).comments
    assert c.id == cid and not c.orphan and "<div>" not in new
    want = doc("Alpha.", "Bravo.", "Charlie, about pears.") if line else doc("Alpha.", "Bravo, about pears.", "Charlie.")
    assert rde._prose(new) == want


# ── Enter in a heading or a table cell ──
# Enter at the start of a heading writes the new line, and any line typed on it, before the heading's words, inside
# the heading: the words must not become a paragraph with an empty `## ` left. Lines before the words are paragraphs above
# the heading, and the words stay the heading. Enter at its end, or after a word, makes a paragraph after it.

@pytest.mark.parametrize("html, md", [
    ("<h2><div><br></div>A title</h2>", "## A title"),
    ("<h2><div><br></div><div><br></div>A title</h2>", "## A title"),
    ("<h2><div>Above it.</div>A title</h2>", "Above it.\n\n## A title"),
    ("<h2><div><br></div>New A title</h2>", "## New A title"),
    ("<h2><div><br></div>A title<div>A line under it.</div></h2>", "## A title\n\nA line under it."),
    ("<h2><div>Above it.&nbsp;</div>A title</h2>", "Above it.\n\n## A title"),
    ("<h2>A title<div>A line under it.</div></h2>", "## A title\n\nA line under it."),
    ("<h2>A title</h2>", "## A title"),
    ("<p><div>Above it.</div>A paragraph.</p>", "Above it.\n\nA paragraph.")],
    ids=["Enter at the start", "Enter twice at the start", "a line typed above", "words typed at the start",
         "a line above and one under", "a space typed at the end of the line above", "Enter at the end", "no Enter",
         "a paragraph"])
def test_enter_at_the_start_of_a_heading_keeps_the_heading_and_puts_the_new_lines_above_it(html, md):
    assert rde.html_block_to_md(html) == md


def test_a_comment_on_a_heading_stays_on_it_after_enter_at_its_start():
    text = doc("# Title", "## A title here", "Last.")
    blk, s, e = rdc.find_quote(text, "title here")
    text, cid = rdc.add_comment(text, blk, s, e, "title here", "Why?", "Ada", "2026-10-18T10:00")
    a = f'<span class="rd-anchor" data-rd-id="{cid}"></span>'
    new, _ = rde.apply_edits(text, [{"i": 1, "html": f"<h2><div>Above it.</div>A title here{a}</h2>"}])
    [c] = rdc.parse(new).comments
    assert c.id == cid and not c.orphan
    assert rde._prose(new) == doc("# Title", "Above it.", "## A title here", "Last.")


# A GFM table cell holds one line. Enter in a cell writes a <br> there (Chromium), and pandoc wrote the whole table
# as raw HTML, a block the page cannot edit. The line break stays in the cell as <br>, which GFM takes as it is; the
# no-break space Enter leaves at the cut goes, and a break that ends the cell shows nothing and goes too.
TABLE = "| Fruit | Note |\n| --- | --- |\n| apples | red ones |\n"


def table(note, head="Fruit", fruit="apples"):
    """The table as the page sends it."""
    return (f'<div class="tblwrap"><table>\n<thead>\n<tr>\n<th>{head}</th>\n<th>Note</th>\n</tr>\n</thead>\n'
            f"<tbody>\n<tr>\n<td>{fruit}</td>\n<td>{note}</td>\n</tr>\n</tbody>\n</table></div>")


@pytest.mark.parametrize("note, head, cell, head_md", [
    ("red ones<br>more", "Fruit", "red ones<br>more", "Fruit"),
    ("red<br>&nbsp;ones", "Fruit", "red<br>ones", "Fruit"),
    ("red ones<br><br>more", "Fruit", "red ones<br><br>more", "Fruit"),
    ("red&nbsp;&nbsp;<br>&nbsp;&nbsp;ones", "Fruit", "red\u00a0<br>\u00a0ones", "Fruit"),
    ("red ones<br><br>", "Fruit", "red ones", "Fruit"),
    ("<br>red ones", "Fruit", "<br>red ones", "Fruit"),
    ("red ones", "Fruit<br>kind", "red ones", "Fruit<br>kind"),
    ("red ones, and more", "Fruit", "red ones, and more", "Fruit")],
    ids=["Enter and a line", "Enter in the middle", "Enter twice", "two no-break spaces at the cut", "Enter at the end",
         "Enter at the start",
         "a header cell", "no Enter"])
def test_a_line_break_in_a_table_cell_stays_in_the_cell_and_the_table_stays_a_table(note, head, cell, head_md):
    new, _ = rde.apply_edits(TABLE, [{"i": 0, "html": table(note, head)}])
    assert kinds(new) == ["table"] and "<table" not in new, new
    rows = [[c.strip() for c in ln.strip("|").split("|")] for ln in new.splitlines()]
    assert rows[0] == [head_md, "Note"] and rows[2] == ["apples", cell], new


def test_a_table_with_a_line_break_in_a_cell_saved_as_it_was_is_unchanged():
    md = "| Fruit | Note |\n|---|---|\n| apples | red<br>ones |\n"
    new, rep = rde.apply_edits(md, [{"i": 0, "html": table("red<br>ones")}])
    assert new == md and rep["changed"] == []


def test_a_line_break_in_a_paragraph_is_still_a_hard_break():
    assert rde.html_block_to_md("<p>One line<br>and the next.</p>") == "One line\\\nand the next."


def test_a_backslash_before_a_line_break_in_a_cell_keeps_every_character_of_the_cell():
    # Pandoc's writer takes a character after a backslash it escapes, here a character of the break's stand-in: the
    # table goes the way it went before, as raw HTML, with the cell's words exact.
    new, _ = rde.apply_edits(TABLE, [{"i": 0, "html": table("red ones\\<br>x")}])
    assert not any("" <= ch <= "" for ch in new), repr(new)
    assert "red ones\\" in new and "<br" in new and "x" in new


def test_backslashes_in_a_cell_with_a_line_break_all_come_back_on_the_page():
    # Pandoc's writer leaves two backslashes as they are, which the .md reads as one: such a table goes the way it
    # went before, as raw HTML, and the page shows what was typed.
    new, _ = rde.apply_edits(TABLE, [{"i": 0, "html": table("red ones C:\\\\<br>x")}])
    assert "red ones C:\\\\" in pandoc(["-f", "gfm", "-t", "html"], new), new


# Pandoc's writer reads every cell of a table the same way, so a backslash in another cell than the one Enter broke
# (another cell, the header, a link's address) went into the pipe table and read as one, or took the character after
# it. A table that holds a backslash anywhere goes the old way, as raw HTML; one that holds none keeps its pipe table.
@pytest.mark.parametrize("note, head, shown", [
    ("red ones C:\\\\", "Fruit", "red ones C:\\\\"),
    ("red ones", "Fruit C:\\\\", "Fruit C:\\\\"),
    ('<a href="https://example.org/a\\\\b">red ones</a>', "Fruit", 'href="https://example.org/a\\\\b"'),
    ("a\\*b", "Fruit", "a\\*b")],
    ids=["two backslashes in another cell", "in the header", "in a link's address", "before punctuation"])
def test_a_backslash_anywhere_in_a_table_with_a_line_break_comes_back_on_the_page(note, head, shown):
    new, _ = rde.apply_edits(TABLE, [{"i": 0, "html": table(note, head, fruit="apples<br>x")}])
    assert shown in pandoc(["-f", "gfm", "-t", "html"], new), new


def test_a_table_with_a_line_break_and_no_backslash_keeps_its_pipe_table():
    new, _ = rde.apply_edits(TABLE, [{"i": 0, "html": table("red ones, C: and D:", fruit="apples<br>x")}])
    assert kinds(new) == ["table"] and "<table" not in new and "| apples<br>x |" in new, new


# The pipe table is read with GFM's emoji extension, which a raw HTML table is not: a shortcode in it would show as its
# emoji, and a later edit of the table must not write the emoji in its place. A table that holds a shortcode's shape goes the
# old way too; a lone colon (a time of day) is no shortcode, and its table keeps the pipe table.
def test_an_emoji_shortcode_in_a_table_with_a_line_break_comes_back_as_its_words():
    new, _ = rde.apply_edits(TABLE, [{"i": 0, "html": table("a:b:<br>c")}])
    assert "a:b:" in pandoc(["-f", "gfm", "-t", "html"], new), new


def test_a_table_with_a_line_break_and_a_time_of_day_keeps_its_pipe_table():
    new, _ = rde.apply_edits(TABLE, [{"i": 0, "html": table("at 10:30<br>sharp")}])
    assert kinds(new) == ["table"] and "<table" not in new and "| at 10:30<br>sharp |" in new, new


def test_a_typed_task_box_followed_only_by_a_comment_keeps_its_characters():
    block = rde.split_md_blocks(f"Alpha{ADA_C1}\n")[0]
    md, _ = rde._convert_with_comments(block, f"<p>- [ ] {anchor('c1')}</p>")
    assert md.startswith("\\- \\[ \\]") and "☐" not in md and "sheaf-comment id=c1" in md


def test_a_line_in_a_task_item_keeps_a_comment_anchor_that_holds_white_space():
    out = rde.html_block_to_md('<ul><li><input type="checkbox"> b<div><span class="rd-anchor" data-rd-id="c1"> </span>a</div></li></ul>')
    assert "rd-anchor" in out and "<div" not in out and out.count("[ ]") == 2


def test_a_line_that_holds_a_heading_stays_in_its_task_item_and_gets_no_box_character():
    out = rde.html_block_to_md('<ul><li><input type="checkbox">a<div><h3>b</h3></div></li></ul>', "- [ ] a", [])
    assert "☐" not in out and "<div" not in out and out.startswith("- [ ] a") and "### b" in out


def test_a_typed_box_directly_before_a_nested_line_keeps_its_characters():
    out = rde.html_block_to_md('<ul><li><input type="checkbox">a<div>- [x] <div>words</div></div></li></ul>', "- [ ] a", [])
    assert out == "- [ ] a\n- \\- \\[x\\]\\\n  words"
