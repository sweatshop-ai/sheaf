"""The last fix round on a merged save: what loses text, or leaves a note where there is none.

Every case here is a save made against an older version of the .md (`merge_edits`),
except the first, which is the same fault in `apply_edits`.
"""
from sheafmd import comments as rdc
from sheafmd import edit as rde
from sheafmd.blocks import split_md_blocks


def kinds(text):
    return [b.kind for b in split_md_blocks(text)]


def test_a_deleted_list_does_not_fuse_the_lead_in_with_the_paragraph_after_it():
    # "Steps:" has no blank line before its list. Take the list away and the two
    # paragraphs around the hole were one paragraph.
    doc = "Intro.\n\nSteps:\n- one\n- two\n\nNext para.\n"
    new, rep = rde.apply_edits(doc, [{"i": 2, "html": ""}])
    assert new == "Intro.\n\nSteps:\n\nNext para.\n"
    assert rep["changed"] == [2]


def test_two_deletions_that_would_join_neighbours_keep_the_agents_paragraph():
    base = "Intro.\n\nSteps:\n- one\n- two\n\nNext para.\n\nEnd.\n"
    cur = base.replace("Next para.", "Next para, revised by the agent.")
    new, rep = rde.merge_edits(base, cur, [{"i": 1, "html": ""}, {"i": 2, "html": ""}])
    assert new == "Intro.\n\nNext para, revised by the agent.\n\nEnd.\n"
    assert rep["changed"] == [2, 1] and rep["conflicts"] == []


def test_a_deletion_between_two_lists_does_not_swallow_the_edit_of_the_first():
    # The agent added a list after the paragraph the page deletes; the page also
    # edits the list above. Removing the paragraph leaves two lists side by side.
    base = "- a one\n- a two\n\nMiddle paragraph.\n"
    cur = base + "\n- b added by agent\n"
    new, rep = rde.merge_edits(base, cur, [
        {"i": 0, "html": "<ul><li>a one, edited</li><li>a two</li></ul>"},
        {"i": 1, "html": ""},
    ])
    assert "a one, edited" in new and "a two" in new
    assert "b added by agent" in new
    assert "Middle paragraph" not in new
    assert rep["conflicts"] == []


def test_a_list_turned_into_a_paragraph_does_not_swallow_the_lead_in_edit():
    base = "Steps:\n- one\n- two\n\nEnd.\n"
    new, rep = rde.merge_edits(base, base, [
        {"i": 0, "html": "<p>Steps, edited:</p>"},
        {"i": 1, "html": "<p>one and two</p>"},
    ])
    assert "Steps, edited:" in new and "one and two" in new and "End." in new
    assert kinds(new) == ["para", "para", "para"]
    assert rep["changed"] == [1, 0] and rep["conflicts"] == []


def test_a_list_turned_into_a_paragraph_that_the_file_also_changed_is_a_note_not_an_orphan():
    base = "Steps:\n- one\n- two\n\nEnd.\n"
    cur = base.replace("- two", "- two\n- three")
    new, rep = rde.merge_edits(base, cur, [{"i": 1, "html": "<p>one and two</p>"}], at="2026-10-14T10:00")
    assert "one and two" in rde._prose(new)
    [note] = [c for c in rdc.parse(new).comments if c.by == "sheaf"]
    assert not note.orphan and "three" in note.body
    assert rep["conflicts"] == [{"i": 1, "kind": "both"}]


def test_a_deletion_between_two_edits_leaves_the_page_edit_of_the_last_list():
    # Fuzz seed 199 of the review: list, paragraph, list; edit, delete, edit.
    base = "- a1\n- a2\n\nMiddle.\n\n- c1\n- c2\n"
    new, rep = rde.merge_edits(base, base, [
        {"i": 0, "html": "<ul><li>a1 edited</li><li>a2</li></ul>"},
        {"i": 1, "html": ""},
        {"i": 2, "html": "<ul><li>c1 edited</li><li>c2</li></ul>"},
    ])
    assert "a1 edited" in new and "c1 edited" in new and "Middle." not in new


# ─────────────────────────────────── a comment or note next to an HTML comment ──
def with_comment(md, quote, body, by):
    blk, s, e = rdc.find_quote(md, quote)
    return rdc.add_comment(md, blk, s, e, quote, body, by, "2026-10-14T09:00")


def readable(text, *ids):
    """Every comment parses, none is malformed, and the ones named are there."""
    parsed = rdc.parse(text)
    assert parsed.malformed == [], parsed.malformed
    assert {c.id for c in parsed.comments} >= set(ids)
    return parsed


def test_a_comment_added_in_the_file_is_not_glued_after_the_orphan_the_edit_left():
    base, c1 = with_comment("Alpha.\n\nBravo makes a bold claim here.\n\nCharlie.\n", "bold claim", "Source?", "Ada")
    cur, c2 = with_comment(base, "Bravo", "Codex asks", "Codex")
    new, rep = rde.merge_edits(base, cur, [{"i": 1, "html": "<p>Bravo, rewritten on the page.</p>"}])
    parsed = readable(new, c1, c2)
    assert parsed.by_id(c1).orphan                       # the page's html had no anchor for it
    assert parsed.by_id(c2).body == "Codex asks"
    assert "rewritten on the page." in rde._prose(new) and rep["conflicts"] == []
    # c2 stays on its quote in the paragraph; c1 is a line of its own after it
    assert not parsed.by_id(c2).standalone and parsed.by_id(c1).standalone
    assert rde._bare(split_md_blocks(new)[1].content) == "Bravo, rewritten on the page."


def test_a_note_is_not_glued_after_a_foreign_comment_that_stayed_where_the_paragraph_was():
    base = "Alpha.\n\nBravo 41 <!-- TODO check -->\n\nCharlie.\n"
    cur = base.replace("Bravo 41", "Bravo 42, as the agent has it")
    new, rep = rde.merge_edits(base, cur, [{"i": 1, "html": ""}], at="2026-10-14T10:00")
    parsed = readable(new)
    assert "<!-- TODO check -->" in new
    [note] = [c for c in parsed.comments if c.by == "sheaf"]
    assert note.orphan and "Bravo 42, as the agent has it" in note.body
    assert "Bravo" not in rde._prose(new).replace(note.body, "")
    assert rep["conflicts"] == [{"i": 1, "kind": "both"}]


def test_a_comment_added_in_the_file_is_not_glued_after_a_foreign_comment_either():
    base = "Alpha.\n\nBravo 41 <!-- TODO check -->\n\nCharlie.\n"
    cur, c1 = with_comment(base, "Bravo", "Codex asks", "Codex")
    new, rep = rde.merge_edits(base, cur, [{"i": 1, "html": ""}])
    parsed = readable(new, c1)
    assert parsed.by_id(c1).orphan and parsed.by_id(c1).body == "Codex asks"
    assert "<!-- TODO check -->" in new


# ───────────────────────────────────────── a deleted paragraph put back for nothing ──
GONE_BASE = "Alpha.\n\nBravo here.\n\nCharlie.\n"
GONE_CUR = "Alpha.\n\nCharlie.\n"


def test_an_edit_that_changes_nothing_does_not_undo_the_files_deletion():
    # The page sends the block dirty, but it still says what it said.
    new, rep = rde.merge_edits(GONE_BASE, GONE_CUR, [{"i": 1, "html": "<p>Bravo here.<b></b></p>"}])
    assert new == GONE_CUR
    assert rep["changed"] == [] and rep["conflicts"] == []


def test_an_edit_that_is_refused_does_not_undo_the_files_deletion_either():
    new, rep = rde.merge_edits(GONE_BASE, GONE_CUR, [{"i": 1, "html": "<p><svg></svg></p>"}])
    assert new == GONE_CUR
    assert rep["changed"] == [] and rep["skipped"] and rep["conflicts"] == []


def test_an_edit_that_does_change_something_still_brings_the_paragraph_back():
    new, rep = rde.merge_edits(GONE_BASE, GONE_CUR, [{"i": 1, "html": "<p>Bravo, edited.</p>"}], at="2026-10-14T10:00")
    assert "Bravo, edited." in rde._prose(new)
    assert rep["conflicts"] == [{"i": 1, "kind": "gone"}]


# ─────────────────────────── an edit paired with a block the page cannot edit ──
LOCKED_NOTE = ("This paragraph was replaced in the file by a block this page cannot edit while it "
               "was being edited on this page. The page's version was:")
HARBOUR = "Alpha.\n\nBravo about the harbour.\n\nCharlie.\n"


def locked_note(new):
    parsed = readable(new)
    [note] = [c for c in parsed.comments if c.by == "sheaf"]
    return note


def test_a_page_edit_paired_with_a_block_that_became_a_fence_is_kept_in_a_note():
    cur = HARBOUR.replace("Bravo about the harbour.", "```\nBravo about the harbour\n```")
    new, rep = rde.merge_edits(HARBOUR, cur, [{"i": 1, "html": "<p>Bravo about the harbour, edited.</p>"}],
                               at="2026-10-14T10:00")
    assert "```\nBravo about the harbour\n```" in new       # the file's block is untouched
    note = locked_note(new)
    assert note.body.startswith(LOCKED_NOTE) and "Bravo about the harbour, edited." in note.body
    assert note.standalone and not note.orphan       # on a line of its own after the fence
    assert rep["changed"] == [1] and rep["skipped"] == []
    assert rep["conflicts"] == [{"i": 1, "kind": "locked"}]


def test_a_page_edit_paired_with_a_paragraph_that_gained_an_image_is_kept_in_a_note():
    cur = HARBOUR.replace("harbour.", "harbour. ![map](map.png)")
    new, rep = rde.merge_edits(HARBOUR, cur, [{"i": 1, "html": "<p>Bravo about the harbour, edited.</p>"}],
                               at="2026-10-14T10:00")
    assert "![map](map.png)" in new
    note = locked_note(new)
    assert note.body.startswith(LOCKED_NOTE) and "Bravo about the harbour, edited." in note.body
    assert rep["skipped"] == [] and rep["conflicts"] == [{"i": 1, "kind": "locked"}]


def test_a_page_edit_paired_with_a_block_that_became_raw_html_is_kept_in_a_note():
    cur = HARBOUR.replace("Bravo about the harbour.", "<div>Bravo about the harbour</div>")
    new, rep = rde.merge_edits(HARBOUR, cur, [{"i": 1, "html": "<p>Bravo about the harbour, edited.</p>"}],
                               at="2026-10-14T10:00")
    assert "<div>Bravo about the harbour</div>" in new
    note = locked_note(new)
    assert note.body.startswith(LOCKED_NOTE) and "Bravo about the harbour, edited." in note.body
    assert [b.kind for b in split_md_blocks(new)].count("html") == 2     # the div and the note's block
    assert rep["skipped"] == [] and rep["conflicts"] == [{"i": 1, "kind": "locked"}]


def test_a_page_edit_that_says_nothing_new_leaves_no_note_on_a_block_that_became_a_fence():
    cur = HARBOUR.replace("Bravo about the harbour.", "```\nBravo about the harbour\n```")
    new, rep = rde.merge_edits(HARBOUR, cur, [{"i": 1, "html": "<p>Bravo about the harbour.<b></b></p>"}])
    assert new == cur
    assert rep["changed"] == [] and rep["conflicts"] == []


def test_a_page_deletion_paired_with_a_block_that_became_a_fence_leaves_the_fence_alone():
    cur = HARBOUR.replace("Bravo about the harbour.", "```\nBravo about the harbour\n```")
    new, rep = rde.merge_edits(HARBOUR, cur, [{"i": 1, "html": ""}])
    assert new == cur and rep["conflicts"] == []


# ───────────────────────── a deleted paragraph that would join the block above ──
# Two lists cannot be told apart by a blank line, so a list the file deleted came back
# as the tail of the list above it and the page's edit was refused.
TWO_LISTS = "- a1\n- a2\n\nMiddle.\n\n- b1\n- b2\n"
A_ONLY = "- a1\n- a2\n"
B_EDITED = "<ul><li>b1 edited</li><li>b2</li></ul>"
A_EDITED = "<ul><li>a1 edited</li><li>a2</li></ul>"


def deleted_note(new):
    parsed = readable(new)
    [note] = [c for c in parsed.comments if c.by == "sheaf"]
    assert "deleted in the file" in note.body
    return note


def test_a_list_deleted_in_the_file_below_a_list_comes_back_with_the_pages_edit():
    new, rep = rde.merge_edits(TWO_LISTS, A_ONLY, [{"i": 2, "html": B_EDITED}], at="2026-10-14T10:00")
    assert "b1 edited" in new and "- b2" in new and "- a1" in new and "- a2" in new
    assert "Middle." not in new
    note = deleted_note(new)
    assert new.index("b2") < note.start         # on the list that came back, after its last line
    assert rep["skipped"] == [] and rep["changed"] == [2]
    assert rep["conflicts"] == [{"i": 2, "kind": "gone"}]


def test_a_list_that_came_back_does_not_swallow_the_page_edit_of_the_list_above_it():
    new, rep = rde.merge_edits(TWO_LISTS, A_ONLY, [
        {"i": 0, "html": A_EDITED},
        {"i": 2, "html": B_EDITED},
    ], at="2026-10-14T10:00")
    assert "a1 edited" in new and "b1 edited" in new and "- a2" in new and "- b2" in new
    deleted_note(new)
    assert rep["skipped"] == [] and sorted(rep["changed"]) == [0, 2]


def test_two_lists_that_came_back_in_one_place_each_keep_their_edit_and_their_order():
    base = "- a1\n- a2\n\nMiddle.\n\n- b1\n- b2\n\nTail.\n\n- c1\n- c2\n"
    new, rep = rde.merge_edits(base, A_ONLY, [
        {"i": 4, "html": "<ul><li>c1 edited</li><li>c2</li></ul>"},
        {"i": 2, "html": B_EDITED},
    ], at="2026-10-14T10:00")
    assert new.index("a2") < new.index("b1 edited") < new.index("c1 edited")
    assert "Middle." not in new and "Tail." not in new
    assert rep["skipped"] == [] and len(rep["conflicts"]) == 2


def test_a_list_that_came_back_next_to_a_paragraph_the_page_also_edited_keeps_both():
    base = "Intro.\n\n- a1\n- a2\n\nMiddle.\n\n- b1\n- b2\n"
    cur = "Intro.\n\n- a1\n- a2\n"
    new, rep = rde.merge_edits(base, cur, [
        {"i": 0, "html": "<p>Intro, edited.</p>"},
        {"i": 3, "html": B_EDITED},
    ], at="2026-10-14T10:00")
    assert "Intro, edited." in new and "b1 edited" in new and "a2" in new
    assert rep["skipped"] == [] and sorted(rep["changed"]) == [0, 3]


def test_a_paragraph_deleted_in_the_file_below_an_unclosed_fence_is_not_lost():
    base = "Intro.\n\n```\ncode\n```\n\nBravo about the harbour.\n"
    cur = "Intro.\n\n```\ncode\n"
    new, rep = rde.merge_edits(base, cur, [{"i": 2, "html": "<p>Bravo about the harbour, edited.</p>"}],
                               at="2026-10-14T10:00")
    assert "Bravo about the harbour, edited." in new and "code" in new
    assert "sheaf-merge" not in new                       # the separator line never stays
    assert rep["skipped"] == [] and rep["changed"] == [2]
    assert rep["conflicts"] == [{"i": 2, "kind": "gone"}]


def test_a_list_that_would_join_the_one_above_and_is_not_changed_stays_deleted():
    new, rep = rde.merge_edits(TWO_LISTS, A_ONLY, [{"i": 2, "html": "<ul><li>b1</li><li>b2<b></b></li></ul>"}])
    assert new == A_ONLY
    assert rep["changed"] == [] and rep["skipped"] == [] and rep["conflicts"] == []


def test_a_list_that_would_join_the_one_above_and_is_deleted_on_the_page_too_stays_deleted():
    new, rep = rde.merge_edits(TWO_LISTS, A_ONLY, [{"i": 2, "html": ""}])
    assert new == A_ONLY and rep["conflicts"] == []


# Two seeds of the random merge fuzz that failed before (the file deletes some blocks and
# adds others, the page edits and deletes): every edit that says something is in the file.
def test_fuzz_seed_33_a_list_deleted_between_lists_and_fences_keeps_the_pages_text():
    base = ("- item 0a here\n- item 0b here\n\n> Quote 1 said this.\n\n- item 2a here\n- item 2b here\n\n"
            "```\ncode 3\n```\n\n```\ncode 4\n```\n\n- item 5a here\n- item 5b here\n\n# Head 6 title\n")
    cur = ("- item 0a here\n- item 0b here\n\n- item 2a here\n- item 2b here\n\n```\ncode 3\n```\n\n"
           "- item 5a here\n- item 5b here\n\n# Head 6 title\n\n- AGENTNEW0 a\n- AGENTNEW0 b\n")
    new, rep = rde.merge_edits(base, cur, [
        {"i": 2, "html": "<ul><li>PAGEEDIT2 one</li><li>two</li></ul>"},
        {"i": 1, "html": "<p>PAGEEDIT1 text</p>"},
        {"i": 0, "html": ""},
        {"i": 6, "html": "<p>PAGEEDIT6 text</p>"},
    ], at="2026-10-14T10:00")
    for kept in ("PAGEEDIT2", "PAGEEDIT1", "PAGEEDIT6", "AGENTNEW0"):
        assert kept in new
    assert rep["skipped"] == [] and "sheaf-merge" not in new
    readable(new)


def test_fuzz_seed_7_a_deleted_list_at_the_top_with_other_edits_does_not_skip_them():
    base = ("- item 0a here\n- item 0b here\n\n# Head 1 title\n\n> Quote 2 said this.\n\n"
            "Para 3 has some words in it.\n\nPara 4 has some words in it.\n")
    cur = ("- AGENTNEW1 a\n- AGENTNEW1 b\n\nAGENTNEW0 a paragraph.\n\n# Head 1 title\n\n"
           "Para 3 has some words in it.\n")
    new, rep = rde.merge_edits(base, cur, [
        {"i": 3, "html": "<p>PAGEEDIT3 text</p>"},
        {"i": 1, "html": "<p>PAGEEDIT1 text</p>"},
        {"i": 4, "html": "<p>PAGEEDIT4 text</p>"},
        {"i": 0, "html": ""},
    ], at="2026-10-14T10:00")
    for kept in ("PAGEEDIT3", "PAGEEDIT1", "PAGEEDIT4", "AGENTNEW0", "AGENTNEW1"):
        assert kept in new
    assert rep["skipped"] == [] and "sheaf-merge" not in new
    readable(new)


# ───────────────────────────── a comment id that two comments of one merge would share ──
# Notes and put-back paragraphs both bring comments into the file, and every comment
# must be read back: a second `id=c1` is malformed, and the one that is refused is the
# one that holds somebody's text.
ADA_C1 = ('<!-- sheaf-comment id=c1 by="Ada" at=2026-10-14T09:00 status=open quote="harbour"\n'
          'Source?\n-->')


def anchor(cid):
    return f'<span class="rd-anchor" data-rd-id="{cid}"></span>'


def test_a_conflict_note_never_takes_the_id_of_a_comment_on_a_paragraph_put_back_later():
    base = f"Alpha opens the report.\n\nBravo is about the harbour{ADA_C1}.\n\nCharlie closes the report today.\n"
    cur = "Alpha opens the report.\n\nCharlie closes the report on Friday.\n"
    new, rep = rde.merge_edits(base, cur, [
        {"i": 1, "html": f"<p>Bravo is about the old harbour{anchor('c1')}.</p>"},
        {"i": 2, "html": "<p>Charlie closes the whole report today.</p>"},
    ], at="2026-10-14T10:00")
    parsed = readable(new, "c1")
    assert parsed.by_id("c1").by == "Ada" and parsed.by_id("c1").body == "Source?"
    notes = [c for c in parsed.comments if c.by == "sheaf"]
    assert len(notes) == 2 and {c.id for c in notes}.isdisjoint({"c1"})
    assert any("The file had:" in c.body and "on Friday" in c.body for c in notes)


def test_a_paragraph_put_back_with_a_comment_the_file_already_holds_does_not_write_it_twice():
    # The agent merged Bravo, comment and all, into Alpha; the page edits Bravo.
    base = f"Alpha is the first paragraph of text here.\n\nBravo says another thing{ADA_C1}.\n\nCharlie.\n"
    cur = base.replace("here.\n\nBravo", "here. Bravo")
    new, rep = rde.merge_edits(base, cur, [
        {"i": 1, "html": f"<p>Bravo says another thing, edited{anchor('c1')}.</p>"},
    ], at="2026-10-14T10:00")
    readable(new, "c1")
    assert new.count("Source?") == 1
    assert "Bravo says another thing, edited." in rde._prose(new)
    assert rep["skipped"] == [] and rep["conflicts"] == [{"i": 1, "kind": "gone"}]


def test_a_paragraph_put_back_with_a_comment_whose_id_the_agent_has_since_used_for_another_gets_a_new_id():
    # The agent deleted Bravo (and its comment c2), then commented on Charlie: c2 again.
    base = "Alpha first paragraph.\n\nBravo second paragraph.\n\nCharlie third paragraph.\n"
    base, c1 = with_comment(base, "Alpha first", "on alpha", "Ada")
    base, c2 = with_comment(base, "Bravo second", "on bravo", "Ada")
    blocks = split_md_blocks(base)
    cur = blocks[0].text + "".join(b.text for b in blocks[2:])
    cur, c3 = with_comment(cur, "Charlie third", "the agent's note", "Codex")
    assert (c1, c2, c3) == ("c1", "c2", "c2")
    new, rep = rde.merge_edits(base, cur, [
        {"i": 1, "html": f"<p>Bravo second paragraph, edited.{anchor('c2')}</p>"},
    ], at="2026-10-14T10:00")
    parsed = readable(new, "c1", "c2")
    assert parsed.by_id("c2").body == "the agent's note"          # the file's comment keeps its id
    [bravo] = [c for c in parsed.comments if c.body == "on bravo"]    # the one put back has another
    assert bravo.id not in ("c1", "c2") and bravo.by == "Ada"
    assert not parsed.by_id("c2").orphan and not bravo.orphan
    assert "Bravo second paragraph, edited." in rde._prose(new)
