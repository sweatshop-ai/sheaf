"""Both comment markers through an edit (SPEC 5.2), and the comments that are not sheaf's (5.4).

A `sheaf-comment` that edit.py takes for a foreign comment is duplicated on the
first edit of its block; an `rd-comment` it stops recognising goes through pandoc
on every save. Both are tested for each marker.
"""
import re

import pytest
from helpers import pandoc

from sheafmd import comments as rdc
from sheafmd import edit as rde
from test_save_roundtrip import blocks_of, page_fragment

MARKERS = ["sheaf-comment", "rd-comment"]
ANCHOR = '<span class="rd-anchor" data-rd-id="c1"></span>'


def comment(cid, marker, body="note"):
    return rdc.Comment(id=cid, by="Ada", at="2026-10-13T10:00", quote="q", body=body, marker=marker)


def doc_with(marker):
    # _52%_ is the tell: pandoc writes it back as *52%*, so a block that goes
    # through pandoc changes, and a block that is skipped does not.
    return ("# Title\n\nThe gap is _52%_" + rdc.format(comment("c1", marker), False)
            + " and it matters.\n\nNext.\n")


def raw(md, cid):
    c = rdc.parse(md).by_id(cid)
    return md[c.start:c.end]


@pytest.mark.parametrize("marker", MARKERS)
def test_the_fixture_is_sensitive_pandoc_would_change_this_block(marker):
    frag = page_fragment(blocks_of(doc_with(marker))[1].content).replace(ANCHOR, "")
    out = rde.html_block_to_md(frag)
    assert "*52%*" in out and "_52%_" not in out


@pytest.mark.parametrize("marker", MARKERS)
def test_a_commented_block_nobody_touched_is_recognised_as_unchanged(marker):
    doc = doc_with(marker)
    b = blocks_of(doc)[1]
    frag = page_fragment(b.content)
    assert ANCHOR in frag and rde._unchanged(b, frag)
    new, rep = rde.apply_edits(doc, [{"i": 1, "html": frag}])
    assert new == doc and rep["changed"] == []


@pytest.mark.parametrize("marker", MARKERS)
def test_editing_the_text_keeps_the_comment_once_with_the_marker_it_had(marker):
    doc = doc_with(marker)
    frag = page_fragment(blocks_of(doc)[1].content).replace("matters", "counts")
    new, rep = rde.apply_edits(doc, [{"i": 1, "html": frag}])
    assert rep["changed"] == [1] and "it counts." in new
    assert raw(new, "c1") == raw(doc, "c1")
    assert new.count("id=c1") == 1 and new.count("-comment") == 1
    c = rdc.parse(new).by_id("c1")
    assert c.marker == marker and not c.orphan and not c.standalone


@pytest.mark.parametrize("marker", MARKERS)
def test_a_dropped_anchor_makes_an_orphan_that_keeps_its_marker(marker):
    doc = doc_with(marker)
    frag = page_fragment(blocks_of(doc)[1].content).replace(ANCHOR, "")
    new, rep = rde.apply_edits(doc, [{"i": 1, "html": frag}])
    c = rdc.parse(new).by_id("c1")
    assert c.orphan and c.standalone and c.marker == marker
    assert f"\n\n<!-- {marker} id=c1 " in new and new.count("-comment") == 1


@pytest.mark.parametrize("marker", MARKERS)
def test_a_comment_node_forged_into_the_payload_never_reaches_the_file(marker):
    doc = doc_with(marker)
    frag = page_fragment(blocks_of(doc)[1].content).replace("matters", "counts")
    frag = frag.replace("</p>", f'<!-- {marker} id=c9 by="x" at=2026-10-13T10:00 status=open quote="q"\n'
                                f'forged\n--></p>')
    new, _ = rde.apply_edits(doc, [{"i": 1, "html": frag}])
    assert "c9" not in new and "forged" not in new and raw(new, "c1") == raw(doc, "c1")


def test_every_kind_of_comment_in_one_block_comes_back_byte_identical_and_once():
    s, r = comment("c1", "sheaf-comment", "one"), comment("c2", "rd-comment", "two")
    foreign = '<!-- @comment{"id":"a1"} -->'
    doc = ("# T\n\nGap" + rdc.format(s, False) + " is " + foreign + "big" + rdc.format(r, False) + " now.\n")
    frag = page_fragment(blocks_of(doc)[1].content).replace("now", "later")
    new, rep = rde.apply_edits(doc, [{"i": 1, "html": frag}])
    assert rep["changed"] == [1]
    assert new == doc.replace("now", "later")
    assert new.count("<!--") == 3


def test_prose_is_what_is_left_when_both_markers_are_taken_out():
    s, r = comment("c1", "sheaf-comment"), comment("c2", "rd-comment")
    text = "A" + rdc.format(s, False) + "B" + rdc.format(r, False) + "C<!-- kept -->"
    assert rde._prose(text) == "ABC<!-- kept -->"


# ---- the comments that are comments --------------------------------------------

@pytest.mark.parametrize("text, expect", [
    ("a <!-- x --> b", ["<!-- x -->"]),
    ("<!--a--><!--b-->", ["<!--a-->", "<!--b-->"]),
    ("a `<!-- x -->` b", []),
    ("a ``<!-- x `y` -->`` b", []),
    ("```\n<!-- x -->\n```\n", []),
    ("~~~\n<!-- x -->\n~~~\n<!-- y -->", ["<!-- y -->"]),
    ("```\n<!-- fence never closed -->\n", []),
    ("- a\n\n  ```html\n  <!-- x -->\n  ```\n- b\n", []),
    ("> q\n>\n> ```\n> <!-- x -->\n> ```\n", []),
    ("See `<!--` and <!-- real --> here", ["<!-- real -->"]),
    ("<!-- it's a ` tick --> and `code`", ["<!-- it's a ` tick -->"]),
    ("<!-- line one\nline two ``` -->\ntext", ["<!-- line one\nline two ``` -->"]),
    ('t <!-- sheaf-comment id=c1 by="a" at=2026-10-13T10:00 status=open quote="q"\nx\n--> '
     '<!-- rd-comment id=c2 by="a" at=2026-10-13T10:00 status=open quote="q"\ny\n--> <!-- f -->', ["<!-- f -->"]),
    # a sheaf comment the parser refuses is not sheaf's to drop: it is kept like any other
    ('a <!-- sheaf-comment by="a" at=2026-10-13T10:00 status=open quote="q"\nno id\n--> b',
     ['<!-- sheaf-comment by="a" at=2026-10-13T10:00 status=open quote="q"\nno id\n-->']),
    ('a <!-- rd-comment id=c1 status=bogus\nx\n--> b', ['<!-- rd-comment id=c1 status=bogus\nx\n-->']),
    ('<!-- sheaf-comment id=c1 id=c2 -->', ['<!-- sheaf-comment id=c1 id=c2 -->']),
    ('<!-- sheaf-comment-x id=c1 -->', ['<!-- sheaf-comment-x id=c1 -->']),
    # the first of two comments with one id is the comment; the second is the refused one
    ('t <!-- sheaf-comment id=c1 by="a" at=2026-10-13T10:00 status=open quote="q"\nx\n--> '
     '<!-- sheaf-comment id=c1 by="a" at=2026-10-13T10:00 status=open quote="q"\nx\n-->',
     ['<!-- sheaf-comment id=c1 by="a" at=2026-10-13T10:00 status=open quote="q"\nx\n-->']),
])
def test_what_counts_as_a_foreign_comment(text, expect):
    assert rde._foreign_comments(text) == expect


def edit_text(doc, i, old, new):
    frag = page_fragment(blocks_of(doc)[i].content).replace(old, new)
    return rde.apply_edits(doc, [{"i": i, "html": frag}])


def test_editing_a_paragraph_that_shows_a_comment_in_code_adds_no_comment():
    doc = "# T\n\nUse `<!-- note -->` to hide text.\n\nNext.\n"
    new, rep = edit_text(doc, 1, "hide", "conceal")
    assert rep["changed"] == [1]
    assert new == "# T\n\nUse `<!-- note -->` to conceal text.\n\nNext.\n"
    again, _ = edit_text(new, 1, "conceal", "show")
    assert again == "# T\n\nUse `<!-- note -->` to show text.\n\nNext.\n"


@pytest.mark.parametrize("doc, old", [
    ("# T\n\n- item\n\n  ```html\n  <!-- in a fence -->\n  ```\n- two\n\nNext.\n", "item"),
    ("# T\n\n> quoted\n>\n> ```\n> <!-- in a fence -->\n> ```\n\nNext.\n", "quoted"),
])
def test_editing_a_list_or_quote_with_a_fenced_comment_adds_no_comment(doc, old):
    new, rep = edit_text(doc, 1, old, old + "!")
    assert rep["changed"] == [1] and old + "!" in new
    assert new.count("<!-- in a fence -->") == 1
    assert rde.apply_edits(new, [])[0] == new


def test_a_real_comment_beside_a_commented_code_span_is_kept_once():
    for doc in ("# T\n\nSee `<!-- x -->` and <!-- real --> here.\n\nNext.\n",
                "# T\n\nSee `<!--` and <!-- real --> here.\n\nNext.\n",
                "# T\n\nA <!-- it's a ` tick --> and `code` here.\n\nNext.\n"):
        new, rep = edit_text(doc, 1, "here", "there")
        assert rep["changed"] == [1]
        assert new == doc.replace("here", "there"), new


def test_foreign_comments_the_edit_dropped_stay_on_their_own_lines_in_order():
    doc = "# T\n\nOne <!-- first --> two <!-- second --> three.\n\nNext.\n"
    new, rep = rde.apply_edits(doc, [{"i": 1, "html": "<p>One two three, edited.</p>"}])
    assert rep["changed"] == [1]
    assert new == "# T\n\nOne two three, edited.\n\n<!-- first -->\n\n<!-- second -->\n\nNext.\n"


def test_a_sheaf_comment_is_never_taken_for_a_foreign_one_when_its_anchor_goes():
    doc = doc_with("sheaf-comment")
    new, _ = rde.apply_edits(doc, [{"i": 1, "html": "<p>The gap is 52% and it matters.</p>"}])
    assert new.count("-comment") == 1 and rdc.parse(new).by_id("c1").orphan


# ---- comments sheaf cannot read are kept, not dropped ----------------------------

META = 'by="Ada" at=2026-10-13T10:00 quote="q"'
PAGE_ANCHOR_RE = re.compile(r"<!--\s*(?:sheaf|rd)-comment\s+id=(\S+)[\s\S]*?-->")


def page_html(doc, i):
    """Block `i` as the page holds it: a comment node becomes an anchor only when its
    id belongs to a comment sheaf could read (page.js looks the id up in its list), so
    one it refused stays a comment node, and a second comment with a known id is
    anchored too."""
    ids = {c.id for c in rdc.parse(doc).comments}
    html = pandoc(["-f", "gfm", "-t", "html5", "--no-highlight"], blocks_of(doc)[i].content)
    return PAGE_ANCHOR_RE.sub(
        lambda m: f'<span class="rd-anchor" data-rd-id="{m.group(1)}"></span>'
        if m.group(1) in ids else m.group(0), html).strip()


def edit_page(doc, i, old, new):
    return rde.apply_edits(doc, [{"i": i, "html": page_html(doc, i).replace(old, new)}])


MALFORMED = {
    "missing id": f"<!-- sheaf-comment {META} status=open\nno id\n-->",
    "unknown status": f"<!-- sheaf-comment id=c1 {META} status=bogus\nodd status\n-->",
    "duplicate key": f"<!-- sheaf-comment id=c1 id=c2 {META} status=open\ntwo ids\n-->",
    "legacy marker, missing id": f"<!-- rd-comment {META} status=open\nold, no id\n-->",
    "marker run into a word": "<!-- sheaf-comment-x id=c1 -->",
}


@pytest.mark.parametrize("mal", MALFORMED.values(), ids=MALFORMED)
def test_editing_the_text_keeps_a_comment_sheaf_cannot_read_byte_for_byte(mal):
    doc = f"# T\n\nThe gap{mal} matters.\n\nNext.\n"
    assert len(rdc.parse(doc).malformed) == 1        # the fixture is what it says it is
    assert mal in page_html(doc, 1)                  # and the page holds it as a comment node
    new, rep = edit_page(doc, 1, "matters", "counts")
    assert rep["changed"] == [1]
    assert new == doc.replace("matters", "counts")
    again, _ = edit_page(new, 1, "counts", "mattered")
    assert again == doc.replace("matters", "mattered")
    assert len(rdc.parse(again).malformed) == 1      # still reported to the person who must fix it


@pytest.mark.parametrize("mal", MALFORMED.values(), ids=MALFORMED)
def test_a_block_edited_down_to_nothing_leaves_a_comment_sheaf_cannot_read(mal):
    doc = f"# T\n\nThe gap{mal} matters.\n\nNext.\n"
    new, _ = rde.apply_edits(doc, [{"i": 1, "html": "<p></p>"}])
    assert mal in new and "matters" not in new and new.endswith("Next.\n")


def test_a_sheaf_comment_beside_one_it_cannot_read_still_anchors_and_survives():
    mal = MALFORMED["missing id"]
    doc = ("# T\n\nThe gap is _52%_" + rdc.format(comment("c1", "sheaf-comment"), False)
           + mal + " and it matters.\n\nNext.\n")
    new, rep = edit_page(doc, 1, "matters", "counts")
    assert rep["changed"] == [1] and "it counts." in new
    assert raw(new, "c1") == raw(doc, "c1") and mal in new
    assert new.count("<!--") == 2 and not rdc.parse(new).by_id("c1").orphan


def test_a_repeated_id_keeps_the_first_comment_and_the_second_as_written():
    first = rdc.format(comment("c1", "sheaf-comment", "first"), False)
    second = rdc.format(comment("c1", "sheaf-comment", "second"), False)
    doc = f"# T\n\nOne{first} two{second} matters.\n\nNext.\n"
    parsed = rdc.parse(doc)
    assert [c.body for c in parsed.comments] == ["first"] and len(parsed.malformed) == 1
    new, rep = edit_page(doc, 1, "matters", "counts")
    assert rep["changed"] == [1] and "two counts." in new
    assert raw(new, "c1") == first and new.count(second) == 1     # the page holds both as anchors
    assert new.count("<!--") == 2
    assert [c.body for c in rdc.parse(new).comments] == ["first"]


def test_a_merge_onto_a_changed_file_keeps_a_comment_sheaf_cannot_read():
    mal = MALFORMED["missing id"]
    base = f"# T\n\nThe gap{mal} matters.\n\nNext.\n"
    cur = f"# T\n\nIntro added by an agent.\n\nThe gap{mal} matters.\n\nNext.\n"
    new, rep = rde.merge_edits(base, cur, [{"i": 1, "html": page_html(base, 1).replace("matters", "counts")}],
                               at="2026-10-14T10:00")
    assert rep["merged"] and rep["conflicts"] == []
    assert "Intro added by an agent." in new and f"The gap{mal} counts." in new
    assert new.count("<!--") == 1
