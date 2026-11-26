"""Block changes, matching, rebase and clashes through the Document service (block editor v1, ticket 03, ADR 0007).

Every test drives the service's seam over a real file: `read()`, `save(...)` and `changes_since(base)`.
"""
from pathlib import Path

from sheafmd import adapter as rda
from sheafmd import source as rds
from sheafmd.document import DocumentService

LONG = "The quick brown fox jumps over the lazy dog near the old river bank today."


def make(tmp_path, text, name="d.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p, DocumentService(rda.MarkdownFileAdapter(p))


def disk(p):
    return Path(p).read_text(encoding="utf-8")


def save(svc, markdown, base, session="s1", held=None):
    return svc.save(markdown, held, base, session, author="Ada", note="n")


def kinds(changes):
    return sorted((c["kind"], c.get("type")) for c in changes)


# ── matching: a block edited is still the same block ─────────────────────────

def test_one_word_changed_in_a_paragraph_is_an_edit_of_the_same_block_and_not_a_removal_and_an_insertion(tmp_path):
    p, svc = make(tmp_path, f"# Head\n\n{LONG}\n\nOther.\n")
    tree, base = svc.read()
    old = tree.blocks[1].id
    out = save(svc, f"# Head\n\n{LONG.replace('lazy', 'sleepy')}\n\nOther.\n", base)
    assert out["outcome"] == "written"
    edits = [c for c in out["changes"] if c["kind"] == "edit"]
    assert [c["id"] for c in edits] == [old]                       # comments and Tells pinned to it follow
    assert edits[0]["new_id"] == out["blocks"][1] != old
    assert {c["kind"] for c in out["changes"]} == {"edit"}


def test_the_same_edit_is_found_again_from_the_base_by_changes_since(tmp_path):
    p, svc = make(tmp_path, f"{LONG}\n\nOther.\n")
    tree, base = svc.read()
    save(svc, f"{LONG.replace('lazy', 'sleepy')}\n\nOther.\n", base)
    got = svc.changes_since(base)
    assert [(c["kind"], c["id"]) for c in got] == [("edit", tree.blocks[0].id)]
    assert svc.changes_since(rds.md_hash(disk(p))) == []


def test_a_block_that_changes_type_is_an_edit_of_the_same_block(tmp_path):
    p, svc = make(tmp_path, f"{LONG}\n\nOther.\n")
    tree, base = svc.read()
    out = save(svc, f"## {LONG}\n\nOther.\n", base)
    assert [(c["kind"], c["id"]) for c in out["changes"]] == [("edit", tree.blocks[0].id)]


def test_a_split_is_an_edit_of_the_first_block_and_an_insertion(tmp_path):
    first, second = "The quick brown fox jumps over the lazy dog.", "Near the old river bank it stopped today."
    p, svc = make(tmp_path, f"{first} {second}\n\nTail.\n")
    tree, base = svc.read()
    out = save(svc, f"{first}\n\n{second}\n\nTail.\n", base)
    assert kinds(out["changes"]) == [("edit", "paragraph"), ("insert", "paragraph")]
    assert [c["id"] for c in out["changes"] if c["kind"] == "edit"] == [tree.blocks[0].id]


def test_a_join_is_an_edit_of_the_upper_block_and_a_removal_of_the_lower(tmp_path):
    first, second = "The quick brown fox jumps over the lazy dog.", "Near the old river bank it stopped today."
    p, svc = make(tmp_path, f"{first}\n\n{second}\n\nTail.\n")
    tree, base = svc.read()
    out = save(svc, f"{first} {second}\n\nTail.\n", base)
    got = {c["kind"]: c["id"] for c in out["changes"]}
    assert got == {"edit": tree.blocks[0].id, "remove": tree.blocks[1].id}


def test_a_block_moved_and_edited_in_one_save_is_matched_to_its_old_self(tmp_path):
    p, svc = make(tmp_path, f"One.\n\n{LONG}\n\nTwo.\n\nThree.\n")
    tree, base = svc.read()
    out = save(svc, f"One.\n\nTwo.\n\nThree.\n\n{LONG.replace('lazy', 'sleepy')}\n", base)
    ids = {c["kind"]: c["id"] for c in out["changes"]}
    assert ids["move"] == ids["edit"] == tree.blocks[1].id
    assert "insert" not in ids and "remove" not in ids


def test_a_plain_move_is_a_move_and_a_block_taken_into_a_quote_is_a_move_with_a_new_parent(tmp_path):
    p, svc = make(tmp_path, "One.\n\nTwo.\n\n> Quoted words here.\n")
    tree, base = svc.read()
    out = save(svc, "Two.\n\nOne.\n\n> Quoted words here.\n", base)
    assert [c["kind"] for c in out["changes"]] == ["move"]
    tree, base = svc.read()
    out = save(svc, "One.\n\n> Quoted words here.\n>\n> Two.\n", base)
    mv = [c for c in out["changes"] if c["kind"] == "move"]
    assert [c["id"] for c in mv] == [tree.blocks[0].id] and mv[0]["parent"]
    assert not [c for c in out["changes"] if c["kind"] in ("insert",)]


def test_a_held_id_matches_a_block_whose_words_changed_completely(tmp_path):
    p, svc = make(tmp_path, "Alpha.\n\nBeta.\n")
    tree, base = svc.read()
    out = save(svc, "Alpha.\n\nWholly different text now.\n", base, held=[b.id for b in tree.blocks])
    assert [(c["kind"], c["id"]) for c in out["changes"]] == [("edit", tree.blocks[1].id)]


# ── rebase: a stale base ─────────────────────────────────────────────────────

def stale(tmp_path, text):
    p, svc = make(tmp_path, text)
    tree, base0 = svc.read()
    return p, svc, tree, base0


def test_a_concurrent_edit_of_a_different_block_merges_silently(tmp_path):
    p, svc, tree, base0 = stale(tmp_path, f"One.\n\n{LONG}\n\nThree.\n")
    save(svc, f"One.\n\n{LONG}\n\nThree, by page one.\n", base0, session="page-1")
    out = save(svc, f"One, by page two.\n\n{LONG}\n\nThree.\n", base0, session="page-2")
    assert out["outcome"] == "written"
    assert disk(p) == f"One, by page two.\n\n{LONG}\n\nThree, by page one.\n"


def test_a_move_by_one_member_and_an_edit_by_another_of_the_same_block_both_land(tmp_path):
    p, svc, tree, base0 = stale(tmp_path, f"One.\n\n{LONG}\n\nTwo.\n")
    save(svc, f"One.\n\nTwo.\n\n{LONG}\n", base0, session="page-1")                       # moved to the end
    out = save(svc, f"One.\n\n{LONG.replace('lazy', 'sleepy')}\n\nTwo.\n", base0, session="page-2")
    assert out["outcome"] == "written"
    assert disk(p) == f"One.\n\nTwo.\n\n{LONG.replace('lazy', 'sleepy')}\n"              # edited at its new place


def test_the_edit_lands_when_the_edit_comes_first_and_the_move_second(tmp_path):
    p, svc, tree, base0 = stale(tmp_path, f"One.\n\n{LONG}\n\nTwo.\n")
    save(svc, f"One.\n\n{LONG.replace('lazy', 'sleepy')}\n\nTwo.\n", base0, session="page-1")
    out = save(svc, f"One.\n\nTwo.\n\n{LONG}\n", base0, session="page-2")
    assert out["outcome"] == "written"
    assert disk(p) == f"One.\n\nTwo.\n\n{LONG.replace('lazy', 'sleepy')}\n"


def test_two_moves_of_one_block_the_later_save_wins_with_no_conflict(tmp_path):
    p, svc, tree, base0 = stale(tmp_path, "One.\n\nTwo.\n\nThree.\n\nFour.\n\nFive.\n")
    save(svc, "Three.\n\nOne.\n\nTwo.\n\nFour.\n\nFive.\n", base0, session="page-1")      # Three to the start
    out = save(svc, "One.\n\nTwo.\n\nFour.\n\nFive.\n\nThree.\n", base0, session="page-2")   # Three to the end
    assert out["outcome"] == "written"
    assert disk(p) == "One.\n\nTwo.\n\nFour.\n\nFive.\n\nThree.\n"


def test_edit_against_edit_of_one_block_is_a_conflict_with_the_current_rows_and_nothing_is_written(tmp_path):
    p, svc, tree, base0 = stale(tmp_path, f"One.\n\n{LONG}\n")
    save(svc, f"One.\n\n{LONG.replace('lazy', 'sleepy')}\n", base0, session="page-1")
    before = disk(p)
    out = save(svc, f"One.\n\n{LONG.replace('lazy', 'tired')}\n", base0, session="page-2")
    assert out["outcome"] == "conflict" and out["base"] == rds.md_hash(before)
    assert [r["content"].strip() for r in out["blocks"]] == [LONG.replace("lazy", "sleepy")]
    assert out["blocks"][0]["id"] and out["blocks"][0]["type"] == "paragraph"
    assert disk(p) == before


def test_removal_against_edit_is_a_conflict_in_both_orders(tmp_path):
    p, svc, tree, base0 = stale(tmp_path, f"One.\n\n{LONG}\n\nTwo.\n")
    save(svc, f"One.\n\n{LONG.replace('lazy', 'sleepy')}\n\nTwo.\n", base0, session="page-1")
    out = save(svc, "One.\n\nTwo.\n", base0, session="page-2")                       # removal against edit
    assert out["outcome"] == "conflict"
    assert LONG.replace("lazy", "sleepy") in disk(p)
    (tmp_path / "x").mkdir()
    p2, svc2, tree2, b2 = stale(tmp_path / "x", f"One.\n\n{LONG}\n\nTwo.\n")
    save(svc2, "One.\n\nTwo.\n", b2, session="page-1")                                # the file removed it
    out = save(svc2, f"One.\n\n{LONG.replace('lazy', 'sleepy')}\n\nTwo.\n", b2, session="page-2")
    assert out["outcome"] == "conflict"


def test_both_sides_making_the_same_edit_or_the_same_removal_is_no_conflict(tmp_path):
    p, svc, tree, base0 = stale(tmp_path, f"One.\n\n{LONG}\n\nTwo.\n")
    edited = LONG.replace("lazy", "sleepy")
    save(svc, f"One.\n\n{edited}\n\nTwo.\n", base0, session="page-1")
    out = save(svc, f"One.\n\n{edited}\n\nTwo.\n", base0, session="page-2")
    assert out["outcome"] == "written" and disk(p) == f"One.\n\n{edited}\n\nTwo.\n"


def test_a_rebased_insertion_lands_after_its_preceding_sibling(tmp_path):
    p, svc, tree, base0 = stale(tmp_path, "One.\n\nTwo.\n\nThree.\n")
    save(svc, "Zero.\n\nOne.\n\nTwo.\n\nThree.\n", base0, session="page-1")           # the file grew at the top
    out = save(svc, "One.\n\nTwo.\n\nNew after two.\n\nThree.\n", base0, session="page-2")
    assert out["outcome"] == "written"
    assert disk(p) == "Zero.\n\nOne.\n\nTwo.\n\nNew after two.\n\nThree.\n"


def test_a_rebased_insertion_whose_sibling_is_gone_lands_after_the_nearest_earlier_one(tmp_path):
    p, svc, tree, base0 = stale(tmp_path, "One.\n\nTwo.\n\nThree.\n\nFour.\n")
    save(svc, "One.\n\nThree.\n\nFour.\n", base0, session="page-1")                   # Two is gone
    out = save(svc, "One.\n\nTwo.\n\nNew.\n\nThree.\n\nFour.\n", base0, session="page-2")
    assert out["outcome"] == "written"
    assert disk(p) == "One.\n\nNew.\n\nThree.\n\nFour.\n"


def test_a_rebased_insertion_with_no_surviving_sibling_lands_at_the_start(tmp_path):
    p, svc, tree, base0 = stale(tmp_path, "One.\n\nTwo.\n\nThree.\n")
    save(svc, "Three.\n", base0, session="page-1")
    out = save(svc, "One.\n\nNew.\n\nTwo.\n\nThree.\n", base0, session="page-2")
    assert out["outcome"] == "written"
    assert disk(p) == "New.\n\nThree.\n"


def test_a_stale_base_the_service_has_never_seen_is_still_a_conflict(tmp_path):
    p, svc, tree, base0 = stale(tmp_path, "One.\n\nTwo.\n")
    save(svc, "One, a.\n\nTwo.\n", base0, session="page-1")
    out = save(svc, "One.\n\nTwo, b.\n", "0" * 16, session="page-2")
    assert out["outcome"] == "conflict" and out["base"] == rds.md_hash(disk(p))
