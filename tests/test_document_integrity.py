"""Save and rebase correctness: data-integrity findings of the recheck of the merged PRs 693 and 696 (ticket 28, part a).

Every test drives the Document service over a real file, as `test_document.py` does.
"""
from pathlib import Path

from sheafmd import adapter as rda
from sheafmd import source as rds
from sheafmd.document import DocumentService


def make(tmp_path, text, name="d.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p, DocumentService(rda.MarkdownFileAdapter(p))


def disk(p):
    return Path(p).read_text(encoding="utf-8")


def save(svc, markdown, base, session="s1", held=None, **kw):
    return svc.save(markdown, held, base, session, author="Ada", note="n", **kw)


def types(svc):
    return [b.type for b in svc.read()[0].blocks]


# ── write.py: the original bytes of a block are put back only where they read as the page's block ─────────────

def test_a_new_paragraph_above_a_setext_heading_is_not_absorbed_into_it(tmp_path):
    p, svc = make(tmp_path, "Title\n=====\n")
    _, base = svc.read()
    out = save(svc, "New\n# Title\n", base)
    assert out["outcome"] == "written"
    assert types(svc) == ["paragraph", "heading"]


def test_leading_blank_lines_do_not_come_before_front_matter_the_page_adds(tmp_path):
    p, svc = make(tmp_path, "\n\nBody.\n")
    _, base = svc.read()
    out = save(svc, "---\ntitle: x\n---\n\nBody.\n", base)
    assert out["outcome"] == "written"
    assert types(svc)[0] == "frontmatter"


def test_deleting_the_first_of_two_equal_paragraphs_keeps_the_spelling_of_the_one_that_stays(tmp_path):
    p, svc = make(tmp_path, "*Twin*\n\n_Twin_\n")
    _, base = svc.read()
    out = save(svc, "_Twin_\n", base)
    assert out["outcome"] == "written"
    assert disk(p) == "_Twin_\n"


# ── document.py: the record of a write, and the base a save names ──────────────────────────────────────────────

def test_a_second_save_of_the_session_between_the_write_and_its_record_is_not_a_conflict(tmp_path):
    p, svc = make(tmp_path, "One.\n\nTwo.\n")
    _, base0 = svc.read()
    seen = []

    def by(path, change, move=None):                  # the lock is released when the writer returns
        r = rds.update_file(path, change, move=move)
        seen.append(save(svc, "One, b.\n\nTwo.\n", base0, "page-1"))
        return r

    out = svc.write(lambda t, o: svc.settle(t, "One, a.\n\nTwo.\n", None, base0, "page-1"), "page-1", by=by)
    assert out["outcome"] == "written"
    assert [s["outcome"] for s in seen] == ["written"]
    assert disk(p) == "One, b.\n\nTwo.\n"


def test_a_failed_write_leaves_no_record_of_it(tmp_path):
    p, svc = make(tmp_path, "One.\n\nTwo.\n")
    _, base0 = svc.read()

    def by(path, change, move=None):
        change("One.\n\nTwo.\n")                        # the change ran under the lock, the write never happened
        raise OSError("disk full")

    try:
        svc.write(lambda t, o: svc.settle(t, "One, a.\n\nTwo.\n", None, base0, "page-1"), "page-1", by=by)
    except OSError:
        pass
    assert svc._next == {}


def test_a_restore_by_an_outside_writer_in_the_middle_of_the_session_own_chain_is_not_its_own_write(tmp_path):
    p, svc = make(tmp_path, "One.\n\nTwo.\n")
    _, a = svc.read()
    save(svc, "One, b.\n\nTwo.\n", a)                                   # A -> B
    b_text = disk(p)
    b = rds.md_hash(b_text)
    save(svc, "One, c.\n\nTwo.\n", b)                                   # B -> C
    p.write_text(b_text, encoding="utf-8")                              # an outside writer restores B
    out = save(svc, "One, z.\n\nTwo.\n", a)                             # the page, still on A
    assert out["outcome"] == "conflict"
    assert disk(p) == b_text


def test_a_base_text_that_does_not_hash_to_the_base_is_not_believed(tmp_path):
    p, svc = make(tmp_path, "One.\n\nTwo.\n")
    old_hash = rds.md_hash("One.\n\nTwo.\n")
    p.write_text("One, theirs.\n\nTwo.\n", encoding="utf-8")            # a concurrent edit the service never saw
    svc2 = DocumentService(rda.MarkdownFileAdapter(p))                  # it never held the base text
    out = svc2.save("One, mine.\n\nTwo.\n", None, old_hash, "s1", base_text="One, theirs.\n\nTwo.\n")
    assert out["outcome"] == "conflict"
    assert disk(p) == "One, theirs.\n\nTwo.\n"


def test_a_base_text_that_does_hash_to_the_base_still_rebases(tmp_path):
    p, svc = make(tmp_path, "One.\n\nTwo.\n")
    old_hash = rds.md_hash("One.\n\nTwo.\n")
    p.write_text("One.\n\nTwo, theirs.\n", encoding="utf-8")
    svc2 = DocumentService(rda.MarkdownFileAdapter(p))
    out = svc2.save("One, mine.\n\nTwo.\n", None, old_hash, "s1", base_text="One.\n\nTwo.\n")
    assert out["outcome"] == "written"
    assert disk(p) == "One, mine.\n\nTwo, theirs.\n"


def test_a_session_next_save_on_its_base_does_not_clash_with_its_own_earlier_edit_after_another_session_merged(tmp_path):
    p, svc = make(tmp_path, "One.\n\nTwo.\n")
    _, base0 = svc.read()
    assert save(svc, "One, a.\n\nTwo.\n", base0, "page-1")["outcome"] == "written"
    assert save(svc, "One.\n\nTwo, theirs.\n", base0, "page-2")["outcome"] == "written"
    out = save(svc, "One, a2.\n\nTwo.\n", base0, "page-1")              # still on its first base
    assert out["outcome"] == "written"
    assert disk(p) == "One, a2.\n\nTwo, theirs.\n"


def test_a_stale_deletion_of_a_paragraph_the_previous_save_rewrote_completely_clashes(tmp_path):
    p, svc = make(tmp_path, "Alpha beta gamma delta.\n\nTail.\n")
    tree, base0 = svc.read()
    held = [b.id for b in tree.blocks]
    rewrite = "Entirely other sentence about something else.\n\nTail.\n"
    assert save(svc, rewrite, base0, "page-1", held=held)["outcome"] == "written"
    out = save(svc, "Tail.\n", base0, "page-2", held=[held[1]])
    assert out["outcome"] == "conflict"
    assert disk(p) == rewrite


def test_the_new_id_of_a_stale_insertion_names_its_own_paragraph_and_not_an_identical_one_of_the_other_writer(tmp_path):
    p, svc = make(tmp_path, "One.\n\nTwo.\n")
    _, base0 = svc.read()
    assert save(svc, "New para.\n\nOne.\n\nTwo.\n", base0, "page-1")["outcome"] == "written"
    out = save(svc, "One.\n\nTwo.\n\nNew para.\n", base0, "page-2")
    assert out["outcome"] == "written"
    assert disk(p) == "New para.\n\nOne.\n\nTwo.\n\nNew para.\n"
    ins = [c for c in out["changes"] if c["kind"] == "insert"]
    assert [c["new_id"] for c in ins] == [out["blocks"][3]]
