"""Saving an edited block must never lose, move or rewrite a comment.

Fragments are built the way the page builds them: the block rendered by pandoc,
each comment node replaced by an empty anchor span (the page swaps each comment for an
anchor span, and `clean()` in page.js empties it before it sends the edit).
"""
import re

from helpers import pandoc
from sheafmd import comments as rdc
from sheafmd import edit as rde
from sheafmd.blocks import split_md_blocks


def page_fragment(block_md):
    out = pandoc(["-f", "gfm", "-t", "html5", "--no-highlight"], block_md)
    return re.sub(rf"<!--\s*{rdc.MARKER}\s+id=(\S+)[\s\S]*?-->",
                  r'<span class="rd-anchor" data-rd-id="\1"></span>', out).strip()


def C(cid, body="note", quote="q"):
    return rdc.Comment(id=cid, by="Ada", at="2026-09-22T10:00", quote=quote, body=body)


PARA = "The gap is **52%**" + rdc.format(C("c1", "Source?\n- old"), False) + " and it matters.\n"
LIST = "- item one" + rdc.format(C("c2"), False) + " end\n- item two\n"
HEAD = "## A heading" + rdc.format(C("c3"), True) + "\n"
TABLE = "| A | B |\n|---|---|\n| cell" + rdc.format(C("c4", "a | b"), True) + " | x |\n"
DOC = "# Title\n\n" + PARA + "\n" + LIST + "\n" + HEAD + "\n" + TABLE


def blocks_of(md):
    return {i: b for i, b in enumerate(split_md_blocks(md))}


def raw(md, cid):
    c = rdc.parse(md).by_id(cid)
    return md[c.start:c.end]


def test_untouched_blocks_are_not_rewritten():
    edits = [{"i": i, "html": page_fragment(b.content)} for i, b in blocks_of(DOC).items() if i]
    new, rep = rde.apply_edits(DOC, edits)
    assert new == DOC and rep["changed"] == []


def test_editing_each_kind_of_block_keeps_its_comment_byte_identical():
    bl = blocks_of(DOC)
    edits = [
        {"i": 1, "html": page_fragment(bl[1].content).replace("matters", "counts")},
        {"i": 2, "html": page_fragment(bl[2].content).replace("item two", "item 2")},
        {"i": 3, "html": re.sub(r"A\s+heading", "The heading", page_fragment(bl[3].content))},
        {"i": 4, "html": page_fragment(bl[4].content).replace(">x<", ">y<")},
    ]
    new, rep = rde.apply_edits(DOC, edits)
    assert sorted(rep["changed"]) == [1, 2, 3, 4]
    for cid in ("c1", "c2", "c3", "c4"):
        assert raw(new, cid) == raw(DOC, cid), cid
    assert "it counts." in new and "item 2" in new and "## The heading<!--" in new
    assert "| cell<!--" in new and "| y" in new
    assert [c.id for c in rdc.parse(new).comments if c.orphan] == []


def test_forged_comment_text_in_the_payload_is_ignored():
    bl = blocks_of(DOC)
    frag = page_fragment(bl[1].content).replace("matters", "counts").replace(
        '<span class="rd-anchor" data-rd-id="c1"></span>',
        '<span class="rd-anchor" data-rd-id="c1">EVIL</span><!-- rd-comment id=c1 status=resolved -->')
    new, _ = rde.apply_edits(DOC, [{"i": 1, "html": frag}])
    assert raw(new, "c1") == raw(DOC, "c1")
    assert "EVIL" not in new


def test_deleting_the_anchor_makes_an_orphan_after_the_block():
    bl = blocks_of(DOC)
    frag = page_fragment(bl[1].content).replace('<span class="rd-anchor" data-rd-id="c1"></span>', "")
    new, rep = rde.apply_edits(DOC, [{"i": 1, "html": frag}])
    c = rdc.parse(new).by_id("c1")
    assert c.orphan and c.standalone and c.body == "Source?\n- old"
    # C() writes a sheaf-comment, and an orphan keeps the marker it was read with.
    assert f"The gap is **52%** and it matters.\n\n<!-- {rdc.WRITE_MARKER} id=c1" in new
    assert rep["remap"]


def test_deleting_whole_blocks_keeps_their_comments_as_orphans():
    bl = blocks_of(DOC)
    edits = [{"i": 1, "html": ""}, {"i": 2, "html": "<ul><li></li></ul>"},
             {"i": 4, "html": ""}]
    new, _ = rde.apply_edits(DOC, edits)
    got = {c.id: c for c in rdc.parse(new).comments}
    for cid in ("c1", "c2", "c4"):
        assert got[cid].orphan and got[cid].standalone, cid
    assert "it matters" not in new and "item two" not in new and "| cell" not in new
    # Orphans render as nothing.
    out = pandoc(["-f", "gfm", "-t", "html"], new)
    visible = re.sub(r"<!--[\s\S]*?-->", "", out)
    assert "note" not in visible and "old" not in visible


def test_emptying_the_text_but_leaving_the_anchor_is_a_deletion():
    frag = '<p><span class="rd-anchor" data-rd-id="c1"></span></p>'
    new, _ = rde.apply_edits(DOC, [{"i": 1, "html": frag}])
    c = rdc.parse(new).by_id("c1")
    assert c.orphan and c.standalone


# ---- task boxes --------------------------------------------------------------
TASKS = ("# Steps\n\n"
         "* [ ] Approuvé\n"
         "* [X] Signed by   Pierre\n"
         "  on the 29th\n"
         "  * [ ] nested" + rdc.format(C("c1"), False) + " step\n"
         "\nAfter.\n")


def tick(frag, n, on):
    boxes = list(re.finditer(r"<input[^>]*>", frag))
    m = boxes[n]
    new = '<input type="checkbox" checked="" />' if on else '<input type="checkbox" />'
    return frag[:m.start()] + new + frag[m.end():]


def test_a_tick_changes_one_character_of_the_source():
    frag = page_fragment(blocks_of(TASKS)[1].content)
    for n, on, old, new_line in ((0, True, "* [ ] Approuvé", "* [x] Approuvé"),
                                 (1, False, "* [X] Signed", "* [ ] Signed"),
                                 (2, True, "  * [ ] nested", "  * [x] nested")):
        new, rep = rde.apply_edits(TASKS, [{"i": 1, "html": tick(frag, n, on)}])
        assert rep["changed"] == [1] and not rep["remap"]
        assert new == TASKS.replace(old, new_line), n


def test_a_tick_on_a_list_moved_in_the_file_lands_on_the_same_item():
    base = TASKS
    cur = base.replace("# Steps\n\n", "# Steps\n\nA line Claude added.\n\n")
    frag = tick(page_fragment(blocks_of(base)[1].content), 0, True)
    new, rep = rde.merge_edits(base, cur, [{"i": 1, "html": frag}])
    assert new == cur.replace("* [ ] Approuvé", "* [x] Approuvé")
    assert rep["conflicts"] == []


def test_editing_the_text_of_a_task_list_keeps_its_boxes():
    frag = page_fragment(blocks_of(TASKS)[1].content).replace("Approuvé", "Approuvé now")
    new, rep = rde.apply_edits(TASKS, [{"i": 1, "html": frag}])
    assert rep["changed"] == [1]
    assert "[ ] Approuvé now" in new and "[x] Signed by" in new and "[ ] nested" in new, new
    assert raw(new, "c1") == raw(TASKS, "c1")


# ---- comments sheaf did not write --------------------------------------------
# Another review tool's comments, a toc directive, a cspell line, an internal
# note: none of them is sheaf's to change.
REDLINE = '<!-- @comment{"id":"a1","text":"check this"} -->'
FOREIGN = "# Title\n\nThe gap is " + REDLINE + "52% this month.\n\nNext.\n"


def test_editing_a_paragraph_keeps_a_foreign_comment_byte_identical():
    frag = page_fragment(blocks_of(FOREIGN)[1].content).replace("month.", "month, measured.")
    new, rep = rde.apply_edits(FOREIGN, [{"i": 1, "html": frag}])
    assert rep["changed"] == [1]
    assert new == FOREIGN.replace("month.", "month, measured.")


def test_a_foreign_comment_the_edit_dropped_stays_on_its_own_line():
    # The comment node is not in the page's HTML.
    new, rep = rde.apply_edits(FOREIGN, [{"i": 1, "html": "<p>The gap is 52% this month, measured.</p>"}])
    assert rep["changed"] == [1]
    assert new == "# Title\n\nThe gap is 52% this month, measured.\n\n" + REDLINE + "\n\nNext.\n"


def test_deleting_the_passage_leaves_its_foreign_comment_in_place():
    new, _ = rde.apply_edits(FOREIGN, [{"i": 1, "html": ""}])
    assert new == "# Title\n\n" + REDLINE + "\n\nNext.\n"


def test_a_foreign_comment_added_in_the_payload_is_ignored():
    frag = page_fragment(blocks_of(FOREIGN)[1].content).replace(
        "month.", "month.<!-- injected -->").replace("52%", "53%")
    new, _ = rde.apply_edits(FOREIGN, [{"i": 1, "html": frag}])
    assert "injected" not in new and REDLINE + "53%" in new


def test_foreign_and_rd_comments_in_one_block_both_survive():
    doc = "# T\n\nGap <!-- cspell:disable-line --> is " + rdc.format(C("c1"), False) + " big.\n"
    frag = page_fragment(blocks_of(doc)[1].content).replace("big", "huge")
    new, rep = rde.apply_edits(doc, [{"i": 1, "html": frag}])
    assert rep["changed"] == [1]
    assert new == doc.replace("big", "huge")
