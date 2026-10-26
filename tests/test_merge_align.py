"""Merge (SPEC 7.3): where an edited paragraph goes when the file also gained, lost or
changed paragraphs around it. The page's edit has to land on the paragraph it was
made on, never on a neighbour."""
import pytest

from sheafmd import comments as rdc
from sheafmd import edit as rde


def doc(*paragraphs):
    return "\n\n".join(paragraphs) + "\n"


def prose(text):
    """The paragraphs of a document, comments left out."""
    return [rde._prose(b.content).strip() for b in rde.split_md_blocks(text)]


def page_edit(i, text):
    return {"i": i, "html": f"<p>{text}</p>"}


def sheaf_notes(text):
    return [c for c in rdc.parse(text).comments if c.by == "sheaf"]


def comment(cid, by, quote, body, orphan=False):
    c = rdc.Comment(id=cid, by=by, at="2026-10-14T09:00", status="open", quote=quote, body=body, orphan=orphan)
    return rdc.format(c, one_line=False)


def block_holding(text, paragraph):
    """The source of the block of `text` that holds `paragraph`."""
    return next(b.content for b in rde.split_md_blocks(text) if paragraph in rde._prose(b.content))


# ── the order of the blocks a merge puts back ──

def test_two_paragraphs_deleted_in_the_file_and_edited_on_the_page_keep_their_order():
    base = doc("Alpha", "Bravo", "Charlie", "Delta")
    cur = doc("Alpha", "Delta")
    new, rep = rde.merge_edits(base, cur, [page_edit(1, "Bravo, edited."), page_edit(2, "Charlie, edited.")])
    assert prose(new) == ["Alpha", "Bravo, edited.", "Charlie, edited.", "Delta"]
    assert sorted(c["i"] for c in rep["conflicts"]) == [1, 2]
    assert {c["kind"] for c in rep["conflicts"]} == {"gone"}


def test_a_deleted_paragraph_and_its_unchanged_neighbour_can_both_be_edited():
    """Bravo is gone from the file, Charlie is where it was: each edit lands on its own."""
    base = doc("Alpha", "Bravo", "Charlie", "Delta")
    cur = doc("Alpha", "Charlie", "Delta")
    new, rep = rde.merge_edits(base, cur, [page_edit(1, "Bravo, edited."), page_edit(2, "Charlie, edited.")])
    assert prose(new) == ["Alpha", "Bravo, edited.", "Charlie, edited.", "Delta"]
    assert rep["conflicts"] == [{"i": 1, "kind": "gone"}]


# ── a paragraph that comes back sits on its own ──

def test_a_restored_paragraph_is_not_glued_to_the_block_before_it():
    """The agent deleted Bravo together with its blank lines, so "Steps:" and the list
    touch. Bravo comes back as its own paragraph between them: it is not a lazy
    continuation of "Steps:", and the list is not overwritten by the page's edit."""
    base = "Steps:\n\nBravo para.\n\n- one\n- two\n"
    cur = "Steps:\n- one\n- two\n"
    new, rep = rde.merge_edits(base, cur, [page_edit(1, "Bravo para, edited.")])
    assert prose(new) == ["Steps:", "Bravo para, edited.", "- one\n- two"]
    assert rep["conflicts"] == [{"i": 1, "kind": "gone"}]
    [note] = sheaf_notes(new)
    assert "deleted in the file" in note.body and not note.orphan


def test_the_last_paragraph_deleted_in_the_file_comes_back_for_the_pages_edit():
    base = "Alpha\n\nBravo\n"
    new, rep = rde.merge_edits(base, "Alpha\n", [page_edit(1, "Bravo, edited.")])
    assert prose(new) == ["Alpha", "Bravo, edited."]
    assert rep["conflicts"] == [{"i": 1, "kind": "gone"}]
    assert not new.endswith("\n\n")


def test_the_last_paragraph_comes_back_after_a_file_with_no_final_newline():
    new, rep = rde.merge_edits("Alpha\n\nBravo", "Alpha", [page_edit(1, "Bravo, edited.")])
    assert prose(new) == ["Alpha", "Bravo, edited."]
    assert rep["conflicts"] == [{"i": 1, "kind": "gone"}]


def test_a_paragraph_that_cannot_be_put_back_as_a_block_is_written_where_it_was_not_lost():
    """The file lost the closing fence, so everything after "unclosed" is code: a
    paragraph put back there is text inside the fence. It used to be skipped, and the
    page reloaded without what was typed. Now the file's own lines stay as they are and
    the page's text follows them, with the note for a paragraph the file deleted. The
    note goes above the fence: inside it, it would be code, not a comment."""
    base = "Alpha\n\n```\nunclosed\n```\n\nBravo\n"
    cur = "Alpha\n\n```\nunclosed\n"
    new, rep = rde.merge_edits(base, cur, [page_edit(2, "Bravo, edited.")])
    assert new.startswith("Alpha\n\n<!--") and new.endswith("\n```\nunclosed\n\nBravo, edited.\n")
    assert rep["changed"] == [2] and rep["skipped"] == []
    assert rep["conflicts"] == [{"i": 2, "kind": "gone"}]


# ── the conflict note's timestamp ──

@pytest.mark.parametrize("base, cur, edit_i", [
    (doc("Alpha", "Bravo 41", "Charlie"), doc("Alpha", "Xray(new)", "Bravo 42", "Charlie"), 1),
    (doc("Alpha", "Bravo about the harbour", "Charlie about the market square"),
     doc("Alpha", "Xray, a new thought", "Yankee, another new thought", "Zulu, and a third"), 1),
    (doc("Alpha", "Bravo 41", "Charlie"), doc("Alpha", "Bravo 42", "Charlie"), 1),
])
def test_a_note_carries_the_timestamp_the_merge_was_given(base, cur, edit_i):
    """The plan loop used to reuse the name of the `at` argument for a block index, so
    every note of a merge with an unequal replaced range said at=3."""
    new, rep = rde.merge_edits(base, cur, [page_edit(edit_i, "Bravo, edited on the page.")],
                               at="2026-10-14T10:00")
    [note] = sheaf_notes(new)
    assert note.at == "2026-10-14T10:00"


# ── the page deletes a paragraph the file also changed ──

@pytest.mark.parametrize("html", ["", "<p></p>"])
def test_a_comment_the_file_added_to_a_paragraph_the_page_deletes_becomes_an_orphan(html):
    base = doc("Alpha", "Bravo here.", "Charlie.")
    cur = doc("Alpha", "Bravo here." + comment("c1", "Codex", "Bravo here", "agent note"), "Charlie.")
    new, rep = rde.merge_edits(base, cur, [{"i": 1, "html": html}])
    assert prose(new) == ["Alpha", "", "Charlie."]            # the orphan has a block of its own
    c = rdc.parse(new).by_id("c1")
    assert c.orphan and c.body == "agent note" and rdc.parse(new).malformed == []
    assert rdc.parse(block_holding(new, "Charlie.")).comments == []


def test_the_note_for_a_paragraph_changed_in_the_file_and_deleted_on_the_page_is_an_orphan():
    base = doc("Alpha", "Bravo 41", "Charlie.")
    cur = doc("Alpha", "Bravo 42", "Charlie.")
    new, rep = rde.merge_edits(base, cur, [{"i": 1, "html": ""}], at="2026-10-14T10:00")
    assert rep["conflicts"] == [{"i": 1, "kind": "both"}] and rep["changed"] == [1]
    [note] = sheaf_notes(new)
    assert note.orphan and "Bravo 42" in note.body and note.body.startswith("Edited on this page and in the file")
    assert note.at == "2026-10-14T10:00"
    assert [p for p in prose(new) if p] == ["Alpha", "Charlie."]
    assert rdc.parse(block_holding(new, "Charlie.")).comments == []


@pytest.mark.parametrize("file_changed", [False, True])
def test_the_last_paragraph_can_be_deleted_on_the_page_while_the_file_added_to_it(file_changed):
    base = doc("Alpha", "Bravo here.")
    bravo = "Bravo 42" if file_changed else "Bravo here."
    cur = doc("Alpha", bravo + comment("c1", "Codex", "Bravo", "agent note"))
    new, rep = rde.merge_edits(base, cur, [{"i": 1, "html": ""}], at="2026-10-14T10:00")
    assert [p for p in prose(new) if p] == ["Alpha"]
    assert rdc.parse(new).by_id("c1").orphan
    assert all(c.orphan for c in rdc.parse(new).comments) and rdc.parse(new).malformed == []


def test_a_paragraph_deleted_on_both_sides_leaves_the_file_as_it_is():
    base = doc("Alpha", "Bravo", "Charlie")
    cur = doc("Alpha", "Charlie")
    new, rep = rde.merge_edits(base, cur, [{"i": 1, "html": ""}])
    assert new == cur
    assert rep["conflicts"] == [] and rep["changed"] == []


def test_a_paragraph_with_a_comment_of_its_own_deleted_on_the_page_keeps_every_comment_as_an_orphan():
    old = comment("c1", "Ada", "Bravo", "old note")
    base = doc("Alpha", "Bravo 41" + old, "Charlie.")
    cur = doc("Alpha", "Bravo 42" + old + comment("c2", "Codex", "Bravo", "agent note"), "Charlie.")
    new, rep = rde.merge_edits(base, cur, [{"i": 1, "html": ""}], at="2026-10-14T10:00")
    comments = rdc.parse(new).comments
    assert sorted(c.id for c in comments) == ["c1", "c2", "c3"]
    assert all(c.orphan for c in comments) and rdc.parse(new).malformed == []
    assert [p for p in prose(new) if p] == ["Alpha", "Charlie."]
    assert rdc.parse(block_holding(new, "Charlie.")).comments == []


# ── a note or lifted comment never goes inside code ──

CODE_ENDING = [
    ("- Build it:\n\n  ```\n  make all\n  ```\n",
     "- Build it now:\n\n  ```\n  make all\n  ```\n",
     "<ul><li><p>Build it, on the page:</p><pre><code>make all\n</code></pre></li></ul>"),
    ("> Note:\n>\n> ```\n> make\n> ```\n",
     "> Note now:\n>\n> ```\n> make\n> ```\n",
     "<blockquote><p>Note on the page:</p><pre><code>make\n</code></pre></blockquote>"),
]


@pytest.mark.parametrize("base_block, cur_block, html", CODE_ENDING)
def test_the_note_for_a_block_that_ends_in_code_goes_after_the_block_on_its_own_line(base_block, cur_block, html):
    base, cur = f"Alpha\n\n{base_block}\nOmega\n", f"Alpha\n\n{cur_block}\nOmega\n"
    new, rep = rde.merge_edits(base, cur, [{"i": 1, "html": html}], at="2026-10-14T10:00")
    assert rep["conflicts"] == [{"i": 1, "kind": "both"}]
    [note] = sheaf_notes(new)
    assert rdc.parse(new).malformed == []
    kinds = [(b.kind, b.content) for b in rde.split_md_blocks(new)]
    assert kinds[-1] == ("para", "Omega\n")
    host = rde.split_md_blocks(new)[note.block]
    assert host.kind == "html" and note.standalone                       # a line of its own
    assert "make" in "".join(b.content for b in rde.split_md_blocks(new)[1:note.block])


def test_a_comment_the_file_added_to_a_block_that_ends_in_code_does_not_land_in_the_code():
    base = "Alpha\n\n- Build it:\n\n  ```\n  make all\n  ```\n\nOmega\n"
    cur = ("Alpha\n\n- Build it:" + comment("c1", "Codex", "make all", "which target?")
           + "\n\n  ```\n  make all\n  ```\n\nOmega\n")
    html = "<ul><li><p>Build it:</p><pre><code>make all\n</code></pre></li></ul>"
    new, rep = rde.merge_edits(base, cur, [{"i": 1, "html": html}])
    assert rep["conflicts"] == [] and rdc.parse(new).malformed == []
    c = rdc.parse(new).by_id("c1")
    blocks = rde.split_md_blocks(new)
    assert c.standalone and blocks[c.block].kind == "html" and c.body == "which target?"
    assert "<!--" not in blocks[1].content and "make all" in blocks[1].content
    assert blocks[-1].content == "Omega\n"


# ── pairing an unequal replaced range ──

def test_a_paragraph_inserted_beside_the_edited_one_does_not_take_the_edit():
    """The agent added Xray above Bravo and changed Bravo (41 -> 42). One replaced
    range, two blocks on the file's side: the page's Bravo belongs on Bravo 42."""
    base = doc("Alpha", "Bravo 41", "Charlie")
    cur = doc("Alpha", "Xray(new)", "Bravo 42", "Charlie")
    new, rep = rde.merge_edits(base, cur, [page_edit(1, "Bravo, edited on the page.")], at="2026-10-14T10:00")
    assert prose(new) == ["Alpha", "Xray(new)", "Bravo, edited on the page.", "Charlie"]
    assert rep["conflicts"] == [{"i": 1, "kind": "both"}]
    [note] = sheaf_notes(new)
    assert "Bravo 42" in note.body and "Xray" not in note.body and not note.orphan


def test_the_spec_example_edit_b_while_the_agent_changes_c_and_adds_d_above_a():
    base = doc("# Title", "Alpha (A)", "Bravo (B)", "Charlie (C)")
    cur = doc("# Title", "Delta (D), new", "Alpha (A)", "Bravo (B)", "Charlie (C), changed by the agent")
    new, rep = rde.merge_edits(base, cur, [page_edit(2, "Bravo (B), edited on the page.")])
    assert prose(new) == ["# Title", "Delta (D), new", "Alpha (A)", "Bravo (B), edited on the page.",
                          "Charlie (C), changed by the agent"]
    assert rep["conflicts"] == [] and sheaf_notes(new) == []


def test_a_paragraph_added_below_the_changed_one_does_not_take_the_edit_either():
    base = doc("Alpha", "Bravo 41", "Charlie")
    cur = doc("Alpha", "Bravo 42", "Xray(new)", "Charlie")
    new, rep = rde.merge_edits(base, cur, [page_edit(1, "Bravo, edited on the page.")])
    assert prose(new) == ["Alpha", "Bravo, edited on the page.", "Xray(new)", "Charlie"]
    assert rep["conflicts"] == [{"i": 1, "kind": "both"}]


def test_an_edit_goes_to_the_paragraph_it_resembles_when_the_range_is_shorter_on_the_file_side():
    """Two base paragraphs, one on the file: Charlie is the one that is still there."""
    base = doc("Alpha", "Bravo about the harbour", "Charlie about the market square", "Delta")
    cur = doc("Alpha", "Charlie about the market square, longer now", "Delta")
    new, rep = rde.merge_edits(base, cur, [page_edit(2, "Charlie about the market, edited.")])
    assert prose(new) == ["Alpha", "Charlie about the market, edited.", "Delta"]
    assert rep["conflicts"] == [{"i": 2, "kind": "both"}]


def test_a_block_with_no_match_in_an_unequal_range_counts_as_gone():
    """Bravo and Charlie were replaced by three paragraphs that are none of them
    Bravo: the page's Bravo comes back with its edit, and a note says it was deleted."""
    base = doc("Alpha", "Bravo about the harbour", "Charlie about the market square")
    cur = doc("Alpha", "Xray, a new thought", "Yankee, another new thought", "Zulu, and a third")
    new, rep = rde.merge_edits(base, cur, [page_edit(1, "Bravo about the harbour, edited.")])
    assert prose(new) == ["Alpha", "Bravo about the harbour, edited.", "Xray, a new thought",
                          "Yankee, another new thought", "Zulu, and a third"]
    assert rep["conflicts"] == [{"i": 1, "kind": "gone"}]
    [note] = sheaf_notes(new)
    assert "deleted in the file" in note.body


def test_identical_paragraphs_keep_their_order_so_the_edit_lands_on_the_right_one():
    """Two paragraphs that read the same, both reworded by the agent with a new one
    between them. The page edited the second: it is the second that changes."""
    base = doc("# Title", "Note.", "Note.", "End.")
    cur = doc("# Title", "Note!", "A brand new section from the agent.", "Note!", "End.")
    new, rep = rde.merge_edits(base, cur, [page_edit(2, "Note, edited.")])
    assert prose(new) == ["# Title", "Note!", "A brand new section from the agent.", "Note, edited.", "End."]
    assert rep["conflicts"] == [{"i": 2, "kind": "both"}]


@pytest.mark.parametrize("which", [1, 2])
def test_identical_paragraphs_that_cannot_be_told_apart_give_a_note_not_a_silent_placement(which):
    """Two paragraphs that read the same and only one of them on the file side: the
    merge cannot know which one the agent kept. Either the edit lands on it or the
    edited paragraph is put back; both come with a note, and the agent's text stays."""
    base = doc("# Title", "Note.", "Note.", "End.")
    cur = doc("# Title", "Note!", "End.")
    new, rep = rde.merge_edits(base, cur, [page_edit(which, "Note, edited.")])
    assert prose(new).count("Note, edited.") == 1
    assert rep["conflicts"] != [] and len(sheaf_notes(new)) == 1
    assert "Note!" in prose(new) or "Note!" in sheaf_notes(new)[0].body
    assert prose(new)[0] == "# Title" and prose(new)[-1] == "End."


def test_an_equal_sized_range_pairs_by_text_too_so_an_inserted_paragraph_does_not_take_the_edit():
    """Base A/B/C/D, file A/X/B'/D: Charlie was deleted and Xray added above Bravo, so
    base and file have two blocks each in the changed range. Position would give the
    page's Bravo to Xray; Bravo's best match is B', so the edit goes there."""
    base = doc("Alpha", "Bravo about the harbour", "Charlie about the market square", "Delta")
    cur = doc("Alpha", "Xray, a new thought", "Bravo about the harbour, longer now", "Delta")
    new, rep = rde.merge_edits(base, cur, [page_edit(1, "Bravo about the harbour, edited.")])
    assert prose(new) == ["Alpha", "Xray, a new thought", "Bravo about the harbour, edited.", "Delta"]
    assert rep["conflicts"] == [{"i": 1, "kind": "both"}]
    [note] = sheaf_notes(new)
    assert "longer now" in note.body and "Xray" not in note.body


def test_an_equal_sized_range_edited_in_place_beyond_recognition_is_paired_by_position():
    """Bravo rewritten in place by the agent: nothing in the range looks like it, so
    position decides: one block for one block, a conflict."""
    base = doc("Alpha", "Bravo about the harbour", "Charlie")
    cur = doc("Alpha", "Something else entirely", "Charlie")
    new, rep = rde.merge_edits(base, cur, [page_edit(1, "Bravo about the harbour, edited.")])
    assert prose(new) == ["Alpha", "Bravo about the harbour, edited.", "Charlie"]
    assert rep["conflicts"] == [{"i": 1, "kind": "both"}]


def test_in_an_equal_sized_range_the_block_with_no_match_takes_the_position_the_others_leave_free():
    """Bravo was reworded a little, Charlie rewritten beyond recognition: Bravo goes
    to its match, Charlie to the one block the range has left, by position."""
    base = doc("Alpha", "Bravo about the harbour", "Charlie about the market square", "Delta")
    cur = doc("Alpha", "Bravo about the harbour today", "Something else entirely", "Delta")
    new, rep = rde.merge_edits(base, cur, [page_edit(1, "Bravo about the harbour, edited."),
                                           page_edit(2, "Charlie, edited.")])
    assert prose(new) == ["Alpha", "Bravo about the harbour, edited.", "Charlie, edited.", "Delta"]
    assert sorted((c["i"], c["kind"]) for c in rep["conflicts"]) == [(1, "both"), (2, "both")]


def test_in_an_equal_sized_range_position_never_takes_a_block_that_is_already_somebodys_match():
    """Base P/Q, file Q'/Z: Q is Q', so P (no match) cannot take the block at its
    position, which is Q'. It counts as deleted and comes back with a note."""
    base = doc("Alpha", "Papa about the harbour", "Quebec about the market square", "Delta")
    cur = doc("Alpha", "Quebec about the market square, longer now", "Zulu, a new thought", "Delta")
    new, rep = rde.merge_edits(base, cur, [page_edit(1, "Papa, edited on the page.")])
    assert prose(new) == ["Alpha", "Papa, edited on the page.", "Quebec about the market square, longer now",
                          "Zulu, a new thought", "Delta"]
    assert rep["conflicts"] == [{"i": 1, "kind": "gone"}]


def test_in_an_equal_sized_range_identical_paragraphs_keep_their_order():
    base = doc("# Title", "Note.", "Note.", "End.")
    cur = doc("# Title", "Note!", "Note!!", "End.")
    new, rep = rde.merge_edits(base, cur, [page_edit(2, "Note, edited.")])
    assert prose(new) == ["# Title", "Note!", "Note, edited.", "End."]
    assert rep["conflicts"] == [{"i": 2, "kind": "both"}]


def test_an_equal_sized_range_too_large_to_compare_keeps_the_positional_pairing(monkeypatch):
    monkeypatch.setattr(rde, "ALIGN_LIMIT", 2)
    base = doc("Alpha", "Bravo about the harbour", "Charlie about the market square", "Delta")
    cur = doc("Alpha", "Xray, a new thought", "Bravo about the harbour, longer now", "Delta")
    new, rep = rde.merge_edits(base, cur, [page_edit(1, "Bravo about the harbour, edited.")])
    assert prose(new) == ["Alpha", "Bravo about the harbour, edited.", "Bravo about the harbour, longer now", "Delta"]
    assert rep["conflicts"] == [{"i": 1, "kind": "both"}]


def test_a_range_too_large_to_compare_leaves_the_files_paragraphs_alone(monkeypatch):
    """Above the limit nothing is paired: the edited paragraph is put back with a
    note, and no paragraph of the file is overwritten."""
    monkeypatch.setattr(rde, "ALIGN_LIMIT", 2)
    base = doc("Alpha", "Bravo 41", "Charlie")
    cur = doc("Alpha", "Xray(new)", "Bravo 42", "Yankee(new)", "Charlie")
    new, rep = rde.merge_edits(base, cur, [page_edit(1, "Bravo, edited on the page.")])
    assert "Xray(new)" in prose(new) and "Bravo 42" in prose(new) and "Yankee(new)" in prose(new)
    assert prose(new).count("Bravo, edited on the page.") == 1
    assert rep["conflicts"] == [{"i": 1, "kind": "gone"}]
