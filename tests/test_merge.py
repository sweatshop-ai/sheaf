"""A save made against an older version of the .md: merged paragraph by paragraph."""
import pytest

from sheafmd import comments as rdc
from sheafmd import edit as rde

BASE = "# Title\n\nFirst paragraph here.\n\nSecond paragraph here.\n\nThird paragraph here.\n"


def edit(i, text, anchors=""):
    return [{"i": i, "html": f"<p>{text}{anchors}</p>"}]


def with_comment(md, quote, body="Why?", by="Ada"):
    blk, s, e = rdc.find_quote(md, quote)
    return rdc.add_comment(md, blk, s, e, quote, body, by, "2026-09-28T10:00")


def test_different_paragraphs_both_survive():
    cur = BASE.replace("Third paragraph here.", "Third paragraph, changed by Claude.")
    new, rep = rde.merge_edits(BASE, cur, edit(1, "First paragraph, edited on the page."))
    assert "First paragraph, edited on the page." in new
    assert "Third paragraph, changed by Claude." in new
    assert rep["conflicts"] == [] and rep["remap"]


def test_a_paragraph_inserted_above_does_not_misplace_the_edit():
    cur = BASE.replace("# Title\n\n", "# Title\n\nA new opening line.\n\n")
    new, rep = rde.merge_edits(BASE, cur, edit(2, "Second, edited."))
    assert "A new opening line." in new and "Second, edited." in new
    assert "First paragraph here." in new and "Second paragraph here." not in new


def test_a_reply_in_the_edited_paragraph_is_kept():
    base, cid = with_comment(BASE, "First paragraph")
    cur = rdc.reply(base, cid, "Here is the source.", "Claude", "2026-09-28T10:05")
    anchor = f'<span class="rd-anchor" data-rd-id="{cid}"></span>'
    new, rep = rde.merge_edits(base, cur, [{"i": 1, "html": f"<p>First paragraph{anchor} now longer.</p>"}])
    c = rdc.parse(new).by_id(cid)
    assert c and not c.orphan and c.replies[0].text == "Here is the source."
    assert "now longer." in new and rep["conflicts"] == []


def test_a_new_comment_in_the_edited_paragraph_is_not_orphaned():
    cur, cid = with_comment(BASE, "First paragraph", body="Claude asks", by="Claude")
    new, rep = rde.merge_edits(BASE, cur, edit(1, "First paragraph here, and more."))
    c = rdc.parse(new).by_id(cid)
    assert c and not c.orphan and c.body == "Claude asks"
    assert "and more." in new and rep["conflicts"] == []


def test_same_paragraph_on_both_sides_keeps_the_page_and_notes_the_file():
    cur = BASE.replace("First paragraph here.", "First paragraph, Claude's wording.")
    new, rep = rde.merge_edits(BASE, cur, edit(1, "First paragraph, Ada's wording."), at="2026-09-28T10:00")
    assert "Ada's wording." in rde._prose(new)
    assert "Claude's wording." not in rde._prose(new)
    [note] = [c for c in rdc.parse(new).comments if c.by == "sheaf"]
    assert "Claude's wording." in note.body and not note.orphan
    assert rep["conflicts"] == [{"i": 1, "kind": "both"}]


def test_a_paragraph_deleted_in_the_file_comes_back_with_the_edit():
    cur = BASE.replace("First paragraph here.\n\n", "")
    new, rep = rde.merge_edits(BASE, cur, edit(1, "First paragraph, edited."), at="2026-09-28T10:00")
    prose = rde._prose(new)
    assert prose.index("First paragraph, edited.") < prose.index("Second paragraph here.")
    assert rep["conflicts"] == [{"i": 1, "kind": "gone"}]
    assert any(c.by == "sheaf" for c in rdc.parse(new).comments)


# A save that brings a reload keeps the hash of the text on screen until that reload, so the page's second save
# of a block is merged against its own first one. Each edit says what the page last saved of the
# block (`saved`), and a file block that is that save is the page's own, not a change in the file.
def second_save(i, html, saved):
    return [{"i": i, "html": html, "saved": saved}]


def test_a_block_that_is_what_the_page_last_saved_of_it_takes_the_next_edit_without_a_note():
    cur = BASE.replace("First paragraph here.", "First paragraph, edited once.") \
              .replace("Third paragraph here.", "Third paragraph, changed by Claude.")
    new, rep = rde.merge_edits(BASE, cur, second_save(1, "<p>First paragraph, edited twice.</p>",
                                                     "<p>First paragraph, edited once.</p>"), at="2026-10-18T10:00")
    assert "First paragraph, edited twice." in new and "edited once" not in new
    assert "Third paragraph, changed by Claude." in new
    assert rep["conflicts"] == [] and not any(c.by == "sheaf" for c in rdc.parse(new).comments)


@pytest.mark.parametrize("saved", [None, "<p>First paragraph here.</p>", "<p>First paragraph, edited once.</p>"],
                         ids=["nothing", "the base", "the pages first save"])
def test_a_block_the_file_changed_after_the_pages_last_save_of_it_still_gets_the_note(saved):
    cur = BASE.replace("First paragraph here.", "First paragraph, edited once, and Claude's words.")
    edits = [{"i": 1, "html": "<p>First paragraph, edited twice.</p>"} | ({"saved": saved} if saved else {})]
    new, rep = rde.merge_edits(BASE, cur, edits, at="2026-10-18T10:00")
    assert "First paragraph, edited twice." in rde._prose(new)
    [note] = [c for c in rdc.parse(new).comments if c.by == "sheaf"]
    assert "Claude's words." in note.body
    assert rep["conflicts"] == [{"i": 1, "kind": "both"}]


def test_the_note_of_a_conflict_in_the_pages_first_save_stays_and_the_second_save_adds_none():
    cur = BASE.replace("First paragraph here.", "First paragraph, Claude's wording.")
    once, rep = rde.merge_edits(BASE, cur, edit(1, "First paragraph, page once."), at="2026-10-18T10:00")
    assert rep["conflicts"] == [{"i": 1, "kind": "both"}]
    new, rep = rde.merge_edits(BASE, once, second_save(1, "<p>First paragraph, page twice.</p>",
                                                      "<p>First paragraph, page once.</p>"), at="2026-10-18T10:01")
    [note] = [c for c in rdc.parse(new).comments if c.by == "sheaf"]
    assert "Claude's wording." in note.body and not note.orphan
    assert "First paragraph, page twice." in rde._prose(new) and rep["conflicts"] == []


# A paragraph that the file indented by four spaces or a tab is an indented code block with the same words, a
# block the page cannot edit. It is never the page's own save, whatever `saved` says: the page's text goes into a
# note on it, and is not dropped as an edit of a block that cannot be written.
@pytest.mark.parametrize("indent", ["    ", "\t"], ids=["four spaces", "a tab"])
@pytest.mark.parametrize("words", ["First paragraph here.", "First paragraph, saved once."],
                         ids=["the block as rendered", "the pages first save"])
def test_a_paragraph_the_file_indented_into_code_is_not_the_pages_own_save(indent, words):
    cur = BASE.replace("First paragraph here.", indent + words)
    new, rep = rde.merge_edits(BASE, cur, second_save(1, "<p>First paragraph, brave words typed.</p>",
                                                      f"<p>{words}</p>"), at="2026-10-18T10:00")
    assert rep["conflicts"] == [{"i": 1, "kind": "locked"}]
    [note] = [c for c in rdc.parse(new).comments if c.by == "sheaf"]
    assert "brave words typed." in note.body and indent + words in new


TASKS = "# Title\n\n- [ ] first task\n- [ ] second task\n\nLast paragraph.\n"


def boxes(first, second):
    on = lambda b: ' checked=""' if b else ""      # noqa: E731
    return (f'<ul class="task-list"><li><input type="checkbox"{on(first)}>first task</li>'
            f'<li><input type="checkbox"{on(second)}>second task</li></ul>')


@pytest.mark.parametrize("cur", [
    TASKS.replace("- [ ] first", "- [x] first").replace("Last paragraph.", "Last paragraph.\n\nSplit off."),
    TASKS.replace("- [ ] first", "- [x] first").replace("Last paragraph.", "Last paragraph, edited outside."),
    TASKS.replace("- [ ] first", "- [x] first").replace("# Title\n\n", "# Title\n\nA paragraph from outside.\n\n")],
    ids=["a split paragraph", "an edit below", "a paragraph inserted above"])
def test_a_second_tick_after_the_pages_own_first_tick_writes_no_note(cur):
    new, rep = rde.merge_edits(TASKS, cur, second_save(1, boxes(True, True), boxes(True, False)),
                               at="2026-10-18T10:00")
    assert "- [x] first task\n- [x] second task" in new and new.count("first task") == 1
    assert rep["conflicts"] == [] and "at the same time" not in new


def test_a_comment_added_in_the_file_to_the_pages_own_save_is_kept_with_the_next_edit():
    once = BASE.replace("First paragraph here.", "First paragraph, edited once.")
    cur, cid = with_comment(once, "edited once", body="Claude asks", by="Claude")
    new, rep = rde.merge_edits(BASE, cur, second_save(1, "<p>First paragraph, edited once, and twice.</p>",
                                                     "<p>First paragraph, edited once.</p>"), at="2026-10-18T10:00")
    c = rdc.parse(new).by_id(cid)
    assert c and not c.orphan and c.body == "Claude asks"
    assert "edited once, and twice." in rde._prose(new) and rep["conflicts"] == []


# The page's first save of a block can write it as several (Enter splits a paragraph): the page still shows the one
# block, and its next save of it is merged against those. They are the page's own save too: the next edit takes their
# place, with no note and no copy of the line split off left after it.
SPLITS = {
    "a line split off": ("Third paragraph here.<div>Split off.</div>", "Third paragraph here.<div>Split off. More.</div>",
                         "Third paragraph here.\n\nSplit off. More.\n"),
    "the first line changed too": ("Third paragraph, edited.<div>Split off.</div>",
                                   "Third paragraph, edited.<div>Split off. More.</div>",
                                   "Third paragraph, edited.\n\nSplit off. More.\n"),
    "the split line deleted": ("Third paragraph here.<div>Split off.</div>", "Third paragraph here.",
                               "Second paragraph here.\n\nThird paragraph here.\n"),
    "a line typed above": ("New first.<div>Third paragraph here.</div>", "New first, more.<div>Third paragraph here.</div>",
                           "Second paragraph here.\n\nNew first, more.\n\nThird paragraph here.\n"),
    "no split": ("Third paragraph, edited.", "Third paragraph, edited. More.",
                 "Second paragraph here.\n\nThird paragraph, edited. More.\n"),
}


@pytest.mark.parametrize("scene", SPLITS)
def test_the_blocks_the_pages_first_save_split_a_block_into_take_its_next_edit_without_a_note(scene):
    first, second, end = SPLITS[scene]
    cur, rep = rde.apply_edits(BASE, [{"i": 3, "html": f"<p>{first}</p>"}])
    assert rep["remap"] is (scene != "no split")
    new, rep = rde.merge_edits(BASE, cur, second_save(3, f"<p>{second}</p>", f"<p>{first}</p>"), at="2026-10-18T10:00")
    assert new.endswith(end), new
    assert rep["conflicts"] == [] and "at the same time" not in new
    assert new.count("Split off") <= 1 and new.count("New first") <= 1


def test_a_change_in_the_file_to_a_line_the_pages_first_save_split_off_is_kept():
    cur = BASE.replace("Third paragraph here.", "Third paragraph here.\n\nSplit off, and Claude's words.")
    new, rep = rde.merge_edits(BASE, cur, second_save(3, "<p>Third paragraph here.<div>Split off. More.</div></p>",
                                                     "<p>Third paragraph here.<div>Split off.</div></p>"),
                               at="2026-10-18T10:00")
    assert "Split off. More." in new and "Split off, and Claude's words." in new


def test_the_comments_of_a_block_the_pages_first_save_split_keep_their_replies_and_what_the_file_added():
    base, cid = with_comment(BASE, "Third paragraph")
    anchor = f'<span class="rd-anchor" data-rd-id="{cid}"></span>'
    first = f"<p>Third paragraph{anchor} here.<div>Split off.</div></p>"
    once, _ = rde.apply_edits(base, [{"i": 3, "html": first}])
    cur = rdc.reply(once, cid, "Here is the source.", "Claude", "2026-10-18T10:05")
    cur, new_id = with_comment(cur, "Split off", body="Claude asks", by="Claude")
    new, rep = rde.merge_edits(base, cur, second_save(3, f"<p>Third paragraph{anchor} here.<div>Split off. More.</div></p>",
                                                     first), at="2026-10-18T10:06")
    c, n = rdc.parse(new).by_id(cid), rdc.parse(new).by_id(new_id)
    assert c and not c.orphan and [r.text for r in c.replies] == ["Here is the source."]
    assert n and not n.orphan and n.body == "Claude asks"
    assert rde._prose(new).endswith("Third paragraph here.\n\nSplit off. More.\n")
    assert rep["conflicts"] == []


# A file block that the merge pairs with another base block is never taken for the page's own save, though it says
# the same: the file deleted the page's first save there.
def test_a_block_the_merge_pairs_with_another_base_block_is_not_the_pages_own_save():
    cur = BASE.replace("Second paragraph here.\n\n", "")
    new, rep = rde.merge_edits(BASE, cur, second_save(2, "<p>Third paragraph here. More.</p>",
                                                     "<p>Third paragraph here.</p>"), at="2026-10-18T10:00")
    assert rep["conflicts"] == [{"i": 2, "kind": "gone"}]
    assert rde._prose(new).endswith("Third paragraph here. More.\n\nThird paragraph here.\n")


# Two edits of one save never take the same file block. Two paragraphs that the page's first save wrote with the same
# words, then a paragraph added near them or one of them taken out in the file, and both saved again: each edit took
# the block by itself, and the second written was laid over the first with no note. Each person's words stay.
TWIN = "# Title\n\nIntro words here.\n\nTBD\n\nTBD\n\nEnd words here.\n"


@pytest.mark.parametrize("change", [
    ("Done\n\nDone\n\n", "Done\n\nDone\n\nA note from the agent.\n\n"),
    ("Done\n\nDone\n\n", "Done\n\nA note from the agent.\n\nDone\n\n"),
    ("Done\n\nDone\n\n", "A note from the agent.\n\nDone\n\nDone\n\n"),
    ("Done\n\nDone\n\n", "Done\n\n"),
    ("", "")],
    ids=["a paragraph added after both", "one added between", "one added before both", "one taken out", "nothing"])
def test_two_edits_of_one_save_keep_their_words_where_the_pages_first_save_wrote_the_same_twice(change):
    once, _ = rde.apply_edits(TWIN, [{"i": 2, "html": "<p>Done</p>"}, {"i": 3, "html": "<p>Done</p>"}])
    edits = [{"i": 2, "html": "<p>Done, first one</p>", "saved": "<p>Done</p>"},
             {"i": 3, "html": "<p>Done, second one</p>", "saved": "<p>Done</p>"}]
    new, rep = rde.merge_edits(TWIN, once.replace(*change), edits, at="2026-10-18T10:00")
    prose = rde._prose(new)
    assert "Done, first one" in prose and "Done, second one" in prose, new
    assert prose.index("first one") < prose.index("second one")


def test_two_split_first_saves_that_share_a_line_keep_both_edits():
    base = "# Title\n\nPara one words.\n\n## Head two\n\nEnd words here.\n"
    s1, s2 = "<p>Para one words.<div>Shared line.</div></p>", "<h2><div>Shared line.</div>Head two</h2>"
    once, _ = rde.apply_edits(base, [{"i": 1, "html": s1}, {"i": 2, "html": s2}])
    cur = once.replace("Shared line.\n\nShared line.\n\n", "Shared line.\n\n")
    edits = [{"i": 1, "html": "<p>Para one words.<div>Shared line, by edit one.</div></p>", "saved": s1},
             {"i": 2, "html": "<h2><div>Shared line, by edit two.</div>Head two</h2>", "saved": s2}]
    new, rep = rde.merge_edits(base, cur, edits, at="2026-10-18T10:00")
    prose = rde._prose(new)
    assert "by edit one" in prose and "by edit two" in prose, new
    assert prose.index("by edit one") < prose.index("by edit two") < prose.index("## Head two")


def test_a_paragraph_the_file_deleted_comes_back_after_the_one_before_it_that_the_page_rewrote_whole():
    base = "# Title\n\nAlpha paragraph here.\n\nThird paragraph here.\n\nOmega paragraph here.\n"
    once = "<p>Wholly other words, written on the page.</p>"
    cur = rde.apply_edits(base, [{"i": 2, "html": once}])[0].replace("\n\nOmega paragraph here.", "")
    new, rep = rde.merge_edits(base, cur, [{"i": 2, "html": "<p>Wholly other words, written on the page, twice.</p>",
                                            "saved": once},
                                           {"i": 3, "html": "<p>Omega paragraph here, edited.</p>"}],
                               at="2026-10-18T10:00")
    prose = rde._prose(new)
    assert prose.index("written on the page, twice.") < prose.index("Omega paragraph here, edited.")


# The file changes a block next to one that the page's first save split, before the page saves it again: it deletes
# the block right after the split, changes the first half, or puts a paragraph between the two halves. The page's
# split line was then left after the edit, a second time, and where the page had changed the first line a note quoted
# the page's own words as the file's. The edit takes the place of the page's own lines; what the file did to a line
# the edit leaves as the page saved it stands, and only a line that both changed gets the note.
FOUR = BASE + "\nFourth paragraph here.\n"
FIRST_LINES = {"as rendered": "Second paragraph here.", "edited by the page": "Second paragraph here, edited."}
REST = "\n\nThird paragraph here.\n\nFourth paragraph here.\n"


def by_claude(line):
    return line[:-1] + ", by Claude."


NEXT_TO_THE_SPLIT = {
    "the block after it deleted": (lambda t, first: t.replace("Third paragraph here.\n\n", ""),
                                   lambda first: f"{first}\n\nSplit off. More.\n\nFourth paragraph here.\n"),
    "the first half changed": (lambda t, first: t.replace(first, by_claude(first)),
                               lambda first: f"{by_claude(first)}\n\nSplit off. More." + REST),
    "a block put between": (lambda t, first: t.replace("Split off.", "Claude's line.\n\nSplit off."),
                            lambda first: f"{first}\n\nClaude's line.\n\nSplit off. More." + REST),
}


def split_then(first, change, second=None, more=()):
    """The page's first save splits "Split off." from the end of the second paragraph, the file changes, and the
    page's next save of the paragraph types " More." on that line (and puts `second` on the first, if given)."""
    saved = f"<p>{first}<div>Split off.</div></p>"
    once, rep = rde.apply_edits(FOUR, [{"i": 2, "html": saved}])
    assert rep["remap"]
    html = f"<p>{second or first}<div>Split off. More.</div></p>"
    return rde.merge_edits(FOUR, change(once, first), second_save(2, html, saved) + list(more), at="2026-10-18T10:00")


@pytest.mark.parametrize("first", FIRST_LINES.values(), ids=FIRST_LINES.keys())
@pytest.mark.parametrize("scene", NEXT_TO_THE_SPLIT)
def test_a_change_in_the_file_next_to_a_line_the_pages_first_save_split_off_leaves_that_line_once(scene, first):
    change, end = NEXT_TO_THE_SPLIT[scene]
    new, rep = split_then(first, change)
    assert new == "# Title\n\nFirst paragraph here.\n\n" + end(first), new
    assert rep["conflicts"] == []


@pytest.mark.parametrize("first", FIRST_LINES.values(), ids=FIRST_LINES.keys())
def test_a_first_half_that_the_file_and_the_pages_next_save_both_changed_gets_the_note_once(first):
    new, rep = split_then(first, NEXT_TO_THE_SPLIT["the first half changed"][0], second=first[:-1] + ", retyped.")
    assert rde._prose(new) == f"# Title\n\nFirst paragraph here.\n\n{first[:-1]}, retyped.\n\nSplit off. More." + REST
    [note] = [c for c in rdc.parse(new).comments if c.by == "sheaf"]
    assert note.body.endswith("The file had:\n\n" + by_claude(first)) and not note.orphan
    assert rep["conflicts"] == [{"i": 2, "kind": "both"}]


@pytest.mark.parametrize("first", FIRST_LINES.values(), ids=FIRST_LINES.keys())
def test_the_block_after_the_split_edited_on_the_page_and_deleted_in_the_file_comes_back_as_deleted(first):
    new, rep = split_then(first, NEXT_TO_THE_SPLIT["the block after it deleted"][0],
                          more=[{"i": 3, "html": "<p>Third paragraph, edited on the page.</p>"}])
    assert rde._prose(new) == (f"# Title\n\nFirst paragraph here.\n\n{first}\n\nSplit off. More.\n\n"
                               "Third paragraph, edited on the page.\n\nFourth paragraph here.\n")
    [note] = [c for c in rdc.parse(new).comments if c.by == "sheaf"]
    assert note.body == rde.GONE_NOTE
    assert rep["conflicts"] == [{"i": 3, "kind": "gone"}]


@pytest.mark.parametrize("first", FIRST_LINES.values(), ids=FIRST_LINES.keys())
def test_a_first_half_the_file_changed_and_the_pages_next_save_takes_out_gets_the_note_once(first):
    saved = f"<p>{first}<div>Split off.</div></p>"
    cur = rde.apply_edits(FOUR, [{"i": 2, "html": saved}])[0].replace(first, by_claude(first))
    new, rep = rde.merge_edits(FOUR, cur, second_save(2, "<p>Split off. More.</p>", saved), at="2026-10-18T10:00")
    assert rde._prose(new) == "# Title\n\nFirst paragraph here.\n\nSplit off. More." + REST
    [note] = [c for c in rdc.parse(new).comments if c.by == "sheaf"]
    assert note.body.endswith("The file had:\n\n" + by_claude(first)) and not note.orphan
    assert rep["conflicts"] == [{"i": 2, "kind": "both"}]


def split_with_comments():
    base, cid = with_comment(FOUR, "Second paragraph")
    anchor = f'<span class="rd-anchor" data-rd-id="{cid}"></span>'
    saved = f"<p>Second paragraph{anchor} here.<div>Split off.</div></p>"
    once, _ = rde.apply_edits(base, [{"i": 2, "html": saved}])
    return base, cid, once, saved, f"<p>Second paragraph{anchor} here.<div>Split off. More.</div></p>"


def test_the_comments_around_a_block_the_file_put_between_the_halves_of_a_split_are_kept_once():
    base, cid, once, saved, html = split_with_comments()
    cur = rdc.reply(once.replace("Split off.", "Claude's line.\n\nSplit off."), cid, "Here is the source.", "Claude",
                    "2026-10-18T10:05")
    cur, new_id = with_comment(cur, "Claude's line", body="Claude asks", by="Claude")
    new, rep = rde.merge_edits(base, cur, second_save(2, html, saved), at="2026-10-18T10:06")
    c, n = rdc.parse(new).by_id(cid), rdc.parse(new).by_id(new_id)
    assert c and not c.orphan and [r.text for r in c.replies] == ["Here is the source."]
    assert n and not n.orphan and n.body == "Claude asks" and new.count("Claude asks") == 1
    assert rde._prose(new) == ("# Title\n\nFirst paragraph here.\n\nSecond paragraph here.\n\nClaude's line.\n\n"
                               "Split off. More." + REST)
    assert rep["conflicts"] == []


def test_the_comments_of_a_first_half_the_file_changed_and_of_the_split_line_are_kept_once():
    base, cid, once, saved, html = split_with_comments()
    cur, new_id = with_comment(once.replace("Second paragraph", "Second paragraph, by Claude,", 1), "Split off",
                               body="Claude asks", by="Claude")
    new, rep = rde.merge_edits(base, cur, second_save(2, html, saved), at="2026-10-18T10:06")
    c, n = rdc.parse(new).by_id(cid), rdc.parse(new).by_id(new_id)
    assert c and not c.orphan and new.count("Why?") == 1
    assert n and not n.orphan and new.count("Claude asks") == 1
    assert rde._prose(new) == ("# Title\n\nFirst paragraph here.\n\nSecond paragraph, by Claude, here.\n\n"
                               "Split off. More." + REST)
    assert rep["conflicts"] == []


def test_a_comment_whose_words_the_next_save_takes_out_stays_before_the_split_line_the_file_changed():
    base, cid, once, saved, html = split_with_comments()
    cur = once.replace("Split off.", "Split off, and Claude's words.")
    new, rep = rde.merge_edits(base, cur, second_save(2, "<p>Split off. More.</p>", saved), at="2026-10-18T10:06")
    c = rdc.parse(new).by_id(cid)
    assert c and c.orphan and new.count("Why?") == 1
    assert new.index("Split off. More.") < new.index(f"id={cid}") < new.index("Split off, and Claude's words.")
    assert "Second paragraph" not in rde._prose(new) and rep["conflicts"] == []


@pytest.mark.parametrize("first", FIRST_LINES.values(), ids=FIRST_LINES.keys())
def test_the_block_after_the_split_edited_on_the_page_comes_back_after_the_split_line_where_the_file_also_added_one(first):
    added = lambda t, first: t.replace("Third paragraph here.\n\n", "").replace("Split off.", "Split off.\n\nClaude's line.")  # noqa: E731
    new, rep = split_then(first, added, more=[{"i": 3, "html": "<p>Third paragraph, edited on the page.</p>"}])
    assert rde._prose(new) == (f"# Title\n\nFirst paragraph here.\n\n{first}\n\nSplit off. More.\n\n"
                               "Third paragraph, edited on the page.\n\nClaude's line.\n\nFourth paragraph here.\n")
    [note] = [c for c in rdc.parse(new).comments if c.by == "sheaf"]
    assert note.body == rde.GONE_NOTE
    assert rep["conflicts"] == [{"i": 3, "kind": "gone"}]


# The controls: without a split, the edit of the page's own save takes the block whatever the file did after it; a
# block the file deleted further off changes nothing; a change the file made to the split line itself stays beside
# the edit; a file block that the merge pairs with another base block by its words is never the page's own.
@pytest.mark.parametrize("first", FIRST_LINES.values(), ids=FIRST_LINES.keys())
def test_without_a_split_the_block_after_the_pages_own_save_deleted_in_the_file_leaves_the_edit_alone(first):
    cur = rde.apply_edits(FOUR, [{"i": 2, "html": f"<p>{first}</p>"}])[0].replace("Third paragraph here.\n\n", "")
    new, rep = rde.merge_edits(FOUR, cur, second_save(2, f"<p>{first} More.</p>", f"<p>{first}</p>"),
                               at="2026-10-18T10:00")
    assert new == f"# Title\n\nFirst paragraph here.\n\n{first} More.\n\nFourth paragraph here.\n"
    assert rep["conflicts"] == []


@pytest.mark.parametrize("first", FIRST_LINES.values(), ids=FIRST_LINES.keys())
def test_a_block_the_file_deleted_away_from_the_split_leaves_the_split_line_once(first):
    new, rep = split_then(first, lambda t, first: t.replace("First paragraph here.\n\n", ""))
    assert new == f"# Title\n\n{first}\n\nSplit off. More." + REST
    assert rep["conflicts"] == []


@pytest.mark.parametrize("first", FIRST_LINES.values(), ids=FIRST_LINES.keys())
def test_the_split_line_the_file_changed_stays_beside_the_edit(first):
    new, rep = split_then(first, lambda t, first: t.replace("Split off.", "Split off, and Claude's words."))
    assert new == (f"# Title\n\nFirst paragraph here.\n\n{first}\n\nSplit off. More.\n\nSplit off, and Claude's words."
                   + REST)
    assert rep["conflicts"] == []


@pytest.mark.parametrize("first", FIRST_LINES.values(), ids=FIRST_LINES.keys())
def test_the_split_line_the_file_changed_stays_beside_a_next_save_of_the_first_line_alone(first):
    saved = f"<p>{first}<div>Split off.</div></p>"
    cur = rde.apply_edits(FOUR, [{"i": 2, "html": saved}])[0].replace("Split off.", "Split off, and Claude's words.")
    new, rep = rde.merge_edits(FOUR, cur, second_save(2, f"<p>{first[:-1]}, retyped.<div>Split off.</div></p>", saved),
                               at="2026-10-18T10:00")
    assert new == (f"# Title\n\nFirst paragraph here.\n\n{first[:-1]}, retyped.\n\nSplit off.\n\n"
                   "Split off, and Claude's words." + REST)
    assert rep["conflicts"] == []


def test_a_split_line_with_the_words_of_the_block_after_it_is_not_taken_from_that_block():
    saved = "<p>Second paragraph here.<div>Third paragraph here.</div></p>"
    cur = rde.apply_edits(FOUR, [{"i": 2, "html": saved}])[0].replace("Third paragraph here.\n\n", "", 1)
    new, rep = rde.merge_edits(FOUR, cur, second_save(2, "<p>Second paragraph here.<div>Third paragraph here. More."
                                                         "</div></p>", saved), at="2026-10-18T10:00")
    assert new == "# Title\n\nFirst paragraph here.\n\nSecond paragraph here.\n\nThird paragraph here. More." + REST


def test_words_typed_inside_the_split_line_take_it_where_the_file_deleted_the_block_after_it():
    saved = "<p>Second paragraph here.<div>Split off.</div></p>"
    cur = rde.apply_edits(FOUR, [{"i": 2, "html": saved}])[0].replace("Third paragraph here.\n\n", "")
    new, rep = rde.merge_edits(FOUR, cur, second_save(2, "<p>Second paragraph here.<div>Split right off.</div></p>",
                                                     saved), at="2026-10-18T10:00")
    assert new == ("# Title\n\nFirst paragraph here.\n\nSecond paragraph here.\n\nSplit right off.\n\n"
                   "Fourth paragraph here.\n")
    assert rep["conflicts"] == []


def test_a_line_split_off_above_keeps_its_place_where_the_file_deleted_the_block_before_it():
    saved = "<p>New first.<div>Second paragraph here.</div></p>"
    cur = rde.apply_edits(FOUR, [{"i": 2, "html": saved}])[0].replace("First paragraph here.\n\n", "")
    new, rep = rde.merge_edits(FOUR, cur, second_save(2, "<p>New first, more.<div>Second paragraph here.</div></p>",
                                                     saved), at="2026-10-18T10:00")
    assert new == "# Title\n\nNew first, more.\n\nSecond paragraph here." + REST
    assert rep["conflicts"] == []


@pytest.mark.parametrize("first", FIRST_LINES.values(), ids=FIRST_LINES.keys())
def test_the_block_before_a_line_typed_above_edited_on_the_page_and_deleted_in_the_file_comes_back_as_deleted(first):
    saved = f"<p>New first.<div>{first}</div></p>"
    cur = rde.apply_edits(FOUR, [{"i": 2, "html": saved}])[0].replace("First paragraph here.\n\n", "")
    new, rep = rde.merge_edits(FOUR, cur, [{"i": 1, "html": "<p>First paragraph, edited on the page.</p>"},
                                           {"i": 2, "html": f"<p>New first, more.<div>{first}</div></p>", "saved": saved}],
                               at="2026-10-18T10:00")
    assert rde._prose(new) == f"# Title\n\nFirst paragraph, edited on the page.\n\nNew first, more.\n\n{first}" + REST
    [note] = [c for c in rdc.parse(new).comments if c.by == "sheaf"]
    assert note.body == rde.GONE_NOTE
    assert rep["conflicts"] == [{"i": 1, "kind": "gone"}]


def test_a_block_the_merge_paired_by_its_place_with_a_base_block_whose_own_save_says_it_stays_that_blocks():
    s2, s3 = "<p>Second paragraph here.<div>Dup line.</div></p>", "<p>Dup line.</p>"
    cur = rde.apply_edits(FOUR, [{"i": 2, "html": s2}, {"i": 3, "html": s3}])[0].replace("Dup line.\n\n", "", 1)
    new, rep = rde.merge_edits(FOUR, cur, [{"i": 2, "html": "<p>Second paragraph here.<div>Dup line, by two.</div></p>",
                                            "saved": s2},
                                           {"i": 3, "html": "<p>Dup line, by three.</p>", "saved": s3}],
                               at="2026-10-18T10:00")
    assert new == ("# Title\n\nFirst paragraph here.\n\nSecond paragraph here.\n\nDup line, by two.\n\n"
                   "Dup line, by three.\n\nFourth paragraph here.\n")
    assert rep["conflicts"] == []


# The file's text after the block right after the split was deleted is also what it would be had the file written
# that block over with the split line's words and deleted the split line. Where the page's next save takes those
# words out, they are kept, as the file may have written them.
def test_a_split_line_the_next_save_takes_out_stays_where_the_file_may_have_written_its_words():
    saved = "<p>Second paragraph here.<div>Split off.</div></p>"
    cur = rde.apply_edits(FOUR, [{"i": 2, "html": saved}])[0].replace("Third paragraph here.\n\n", "")
    new, rep = rde.merge_edits(FOUR, cur, second_save(2, "<p>Second paragraph here.</p>", saved),
                               at="2026-10-18T10:00")
    assert new == "# Title\n\nFirst paragraph here.\n\nSecond paragraph here.\n\nSplit off.\n\nFourth paragraph here.\n"
    assert rep["conflicts"] == []


def _conversions(monkeypatch, blocks: int) -> int:
    """How many HTML-to-markdown conversions (pandoc runs) one merged save starts, where the file replaced
    a range of `blocks` distinct base blocks by as many blocks that all say the first half of the split block
    the page saved before, and the page saves that block again (`_own_span` fails, `_own_rows` scans)."""
    runs = []
    convert = rde.html_block_to_md
    monkeypatch.setattr(rde, "html_block_to_md",
                        lambda fragment, *a: runs.append(fragment) or convert(fragment, *a))
    base = "Alpha words here. Beta words here.\n\n" + "".join(f"Distinct base block number {k}.\n\n" for k in range(blocks))
    cur = "Alpha words here.\n\n" * (blocks + 1)
    rde.merge_edits(base, cur, [{"i": 0, "html": "<p>Alpha words here. Beta words changed.</p>",
                                 "saved": "<p>Alpha words here.</p><p>Beta words here.</p>"}])
    return len(runs)


def test_conversions_of_one_merged_save_do_not_grow_with_the_blocks_scanned(monkeypatch):
    assert _conversions(monkeypatch, 32) <= _conversions(monkeypatch, 4)
