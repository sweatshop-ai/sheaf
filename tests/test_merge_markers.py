"""Merge (SPEC 7.3) for both markers, against a version that is only on disk, and map_block."""
import pytest

from sheafmd import comments as rdc
from sheafmd import edit as rde
from sheafmd import paths
from sheafmd.source import md_hash
from test_merge import BASE, edit, with_comment


def legacy(md):
    """The same document written with the legacy marker: every comment an rd-comment."""
    return md.replace("sheaf-comment", "rd-comment")


@pytest.mark.parametrize("old_marker", [False, True], ids=["sheaf-comment", "rd-comment"])
def test_a_reply_in_the_edited_paragraph_is_kept_whichever_marker_it_has(old_marker):
    base, cid = with_comment(BASE, "First paragraph")
    cur = rdc.reply(base, cid, "Here is the source.", "Claude", "2026-09-28T10:05")
    if old_marker:
        base, cur = legacy(base), legacy(cur)
    anchor = f'<span class="rd-anchor" data-rd-id="{cid}"></span>'
    new, rep = rde.merge_edits(base, cur, [{"i": 1, "html": f"<p>First paragraph{anchor} now longer.</p>"}])
    c = rdc.parse(new).by_id(cid)
    assert c and not c.orphan and c.replies[0].text == "Here is the source."
    assert c.marker == ("rd-comment" if old_marker else "sheaf-comment")
    assert "now longer." in new and rep["conflicts"] == []


@pytest.mark.parametrize("old_marker", [False, True], ids=["sheaf-comment", "rd-comment"])
def test_a_comment_added_in_the_file_is_not_a_change_of_the_paragraph(old_marker):
    """The file's side only gained a comment on the paragraph: no conflict, no note."""
    cur, cid = with_comment(BASE, "First paragraph", body="Claude asks", by="Claude")
    if old_marker:
        cur = legacy(cur)
    new, rep = rde.merge_edits(BASE, cur, edit(1, "First paragraph here, and more."))
    assert rep["conflicts"] == [] and "and more." in new
    assert [c.by for c in rdc.parse(new).comments] == ["Claude"]
    assert rdc.parse(new).by_id(cid).marker == ("rd-comment" if old_marker else "sheaf-comment")


def test_the_conflict_note_is_a_sheaf_comment_by_sheaf_even_in_a_legacy_file():
    base, _ = with_comment(BASE, "Third paragraph")
    base = legacy(base)
    cur = base.replace("First paragraph here.", "First paragraph, Claude's wording.")
    new, rep = rde.merge_edits(base, cur, edit(1, "First paragraph, Ada's wording."), at="2026-10-13T10:00")
    [note] = [c for c in rdc.parse(new).comments if c.by == "sheaf"]
    assert note.marker == "sheaf-comment" and rep["conflicts"] == [{"i": 1, "kind": "both"}]
    assert [c.marker for c in rdc.parse(new).comments if c.by != "sheaf"] == ["rd-comment"]


def test_a_save_against_a_version_only_on_disk_merges_after_a_restart():
    """The hub keeps every text it handed a page in <state>/versions/<doc-key>/<hash>.md.
    After a restart the text is only there: read back by its hash, it is the base."""
    page_text = BASE
    d = paths.state_dir() / "versions" / "0123456789abcdef"
    d.mkdir(parents=True)
    (d / f"{md_hash(page_text)}.md").write_text(page_text, encoding="utf-8")
    del page_text                                     # the restart: nothing in memory
    cur = BASE.replace("Third paragraph here.", "Third paragraph, changed by Claude.") \
              .replace("# Title\n\n", "# Title\n\nA new opening line.\n\n")
    base = (d / f"{md_hash(BASE)}.md").read_text(encoding="utf-8")
    assert md_hash(base) == md_hash(BASE) != md_hash(cur)
    new, rep = rde.merge_edits(base, cur, edit(1, "First paragraph, edited on the page."))
    assert "First paragraph, edited on the page." in new and "First paragraph here." not in new
    assert "A new opening line." in new and "Third paragraph, changed by Claude." in new
    assert rep["conflicts"] == [] and rep["remap"] and rep["changed"] == [1]


def test_an_edit_to_a_block_the_base_does_not_have_is_skipped_not_misplaced():
    new, rep = rde.merge_edits(BASE, BASE, [{"i": 99, "html": "<p>nowhere</p>"}])
    assert new == BASE and rep["changed"] == [] and rep["conflicts"] == []


def test_map_block_finds_an_unchanged_paragraph_where_it_moved_and_nothing_for_a_changed_one():
    cur = BASE.replace("# Title\n\n", "# Title\n\nA new opening line.\n\n") \
              .replace("Second paragraph here.", "Second paragraph, rewritten.")
    assert rde.map_block(BASE, cur, 0) == 0           # heading
    assert rde.map_block(BASE, cur, 1) == 2           # "First paragraph here." moved down one
    assert rde.map_block(BASE, cur, 2) is None        # rewritten
    assert rde.map_block(BASE, cur, 3) == 4           # third


def test_map_block_ignores_comments_of_either_marker():
    with_c, cid = with_comment(BASE, "Second paragraph")
    for cur in (with_c, legacy(with_c)):
        assert rde.map_block(BASE, cur, 2) == 2
