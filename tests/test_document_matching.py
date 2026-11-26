"""Matching, moves and rebase placement: the findings of the recheck of the merged PR 696 (ticket 28, part b).

Every test but the last drives the Document service over a real file, as `test_document_changes.py` does.
"""
from pathlib import Path

from sheafmd import adapter as rda
from sheafmd.blocks import derive, read_tree
from sheafmd.document import DocumentService


def make(tmp_path, text, name="d.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p, DocumentService(rda.MarkdownFileAdapter(p))


def disk(p):
    return Path(p).read_text(encoding="utf-8")


def save(svc, markdown, base, session="s1", held=None):
    return svc.save(markdown, held, base, session, author="Ada", note="n")


# ── rebase.py: a concurrent block does not run into an unterminated code fence ────────────────────────────────

def test_a_paragraph_added_by_the_other_writer_is_not_swallowed_by_a_code_fence_the_page_ends_with(tmp_path):
    p, svc = make(tmp_path, "Intro.\n\nTail.\n")
    _, base = svc.read()
    assert save(svc, "Intro.\n\nTail.\n\nConcurrent.\n", base, "a")["outcome"] == "written"
    out = save(svc, "Intro.\n\n```\ncode\n", base, "b")                # the page replaced Tail by a fence open to the end
    assert out["outcome"] == "written"
    got = [b.type for b in svc.read()[0].blocks]
    assert got == ["paragraph", "code", "paragraph"]
    assert "Concurrent." in disk(p).rsplit("```", 1)[1]


# ── changes.py: words, identity of a split or a join, repeated ids, containers, limit ─────────────────────────

def test_concurrent_edits_of_two_one_word_paragraphs_of_one_quote_are_one_clash(tmp_path):
    p, svc = make(tmp_path, "> One\n>\n> Two\n")
    _, base = svc.read()
    assert save(svc, "> Uno\n>\n> Two\n", base, "a")["outcome"] == "written"
    before = disk(p)
    out = save(svc, "> One\n>\n> Due\n", base, "b")
    assert out["outcome"] == "conflict"
    assert [r["type"] for r in out["blocks"]] == ["quote"]
    assert disk(p) == before


FIRST, SECOND = "First two.", "Second has four words."


def test_a_split_gives_the_identity_to_the_first_fragment_even_when_the_second_is_longer(tmp_path):
    p, svc = make(tmp_path, f"{FIRST} {SECOND}\n\nTail.\n")
    tree, base = svc.read()
    out = save(svc, f"{FIRST}\n\n{SECOND}\n\nTail.\n", base)
    edit = [c for c in out["changes"] if c["kind"] == "edit"]
    assert [(c["id"], c["new_id"]) for c in edit] == [(tree.blocks[0].id, out["blocks"][0])]
    assert [c["new_id"] for c in out["changes"] if c["kind"] == "insert"] == [out["blocks"][1]]


def test_a_join_keeps_the_identity_of_the_upper_paragraph_even_when_the_lower_is_longer(tmp_path):
    p, svc = make(tmp_path, f"{FIRST}\n\n{SECOND}\n\nTail.\n")
    tree, base = svc.read()
    out = save(svc, f"{FIRST} {SECOND}\n\nTail.\n", base)
    got = {c["kind"]: c["id"] for c in out["changes"]}
    assert got == {"edit": tree.blocks[0].id, "remove": tree.blocks[1].id}


def test_a_second_fragment_carrying_a_copied_id_is_an_insertion_and_claims_no_block_the_page_deleted(tmp_path):
    p, svc = make(tmp_path, "Alpha beta gamma delta epsilon.\n\nKeep words stay.\n\nZeta eta theta iota kappa.\n")
    tree, base = svc.read()
    a, keep, z = (b.id for b in tree.blocks)
    page = "Alpha beta gamma delta epsilon.\n\nZeta eta theta iota lambda.\n\nKeep words stay.\n"
    out = save(svc, page, base, held=[a, a, keep])
    kinds = sorted((c["kind"], c["id"]) for c in out["changes"])
    assert kinds == sorted([("insert", None), ("remove", z)])


def test_a_quoted_paragraph_moved_out_by_its_id_while_an_equal_top_level_one_is_deleted(tmp_path):
    p, svc = make(tmp_path, "> Same words here.\n\nSame words here.\n")
    tree, base = svc.read()
    quote, top = tree.blocks
    inner = quote.children[0]
    out = save(svc, "Same words here.\n", base, held=[inner.id])
    got = sorted((c["kind"], c["id"]) for c in out["changes"])
    assert got == sorted([("move", inner.id), ("remove", top.id), ("remove", quote.id)])
    assert [c for c in out["changes"] if c["kind"] == "move"][0]["parent"] is None


def test_moving_a_quote_into_another_quote_reports_the_quote_and_not_its_paragraph(tmp_path):
    p, svc = make(tmp_path, "> Quote one text.\n\n> Other quote.\n")
    tree, base = svc.read()
    q1, q2 = tree.blocks
    out = save(svc, "> Other quote.\n>\n> > Quote one text.\n", base, held=[q2.id])
    moves = [c["id"] for c in out["changes"] if c["kind"] == "move"]
    assert moves == [q1.id]
    assert q1.children[0].id not in moves


def test_a_bulk_rewrite_does_not_compare_every_leftover_pair(monkeypatch):
    from sheafmd import edit
    n = 80
    old = "".join(f"Paragraph number {i} about topic {i} of the report.\n\n" for i in range(n))
    new = "".join(f"Paragraph number {i} about subject {i} of the report.\n\n" for i in range(n))
    calls = []
    real = edit._similarity
    monkeypatch.setattr(edit, "_similarity", lambda *a: calls.append(1) or real(*a))
    derive(read_tree(old), read_tree(new))
    assert len(calls) <= edit.ALIGN_LIMIT
