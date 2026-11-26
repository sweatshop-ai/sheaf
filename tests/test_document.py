"""The Document service and the plain-block tree (block editor v1, ticket 02).

Every test drives the service's seam, `read()` and `save(...)`, over a real file through the Markdown-file
adapter; the tree reader is checked through what the service hands back.
"""
import subprocess
from pathlib import Path

import pytest

from sheafmd import adapter as rda
from sheafmd import source as rds
from sheafmd.blocks import read_tree
from sheafmd.blocks.flat import split_md_blocks
from sheafmd.document import DocumentService

ROOT = Path(__file__).resolve().parent.parent
CORPUS = sorted((Path(__file__).resolve().parent / "corpus").glob("*.md"))

DOC = (
    "---\ntitle: T\n---\n\n"
    "# Head\n\n"
    "First paragraph.\n\n"
    "```chart\n{\"a\": 1}\n```\n\n"
    "| a | b |\n|---|---|\n| 1 | 2 |\n\n"
    "Last paragraph.\n"
)


def make(tmp_path, text=DOC, name="d.md"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return p, DocumentService(rda.MarkdownFileAdapter(p))


def disk(p):
    return p.read_text(encoding="utf-8")


def save(svc, markdown, base, session="s1", held=None):
    return svc.save(markdown, held, base, session, author="Ada", note="n")


# ── read ─────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("path", CORPUS, ids=lambda p: p.name)
def test_read_gives_the_tree_and_the_base_of_every_file_of_the_edit_corpus(tmp_path, path):
    text = path.read_text(encoding="utf-8")
    p, svc = make(tmp_path, text)
    tree, base = svc.read()
    assert base == rds.md_hash(text)
    assert tree.text == text
    ids = [b.id for b in tree.blocks]
    assert len(ids) == len(set(ids))
    assert all(b.type and b.caps for b in tree.blocks)


def test_the_tree_holds_each_block_with_its_type_attributes_and_capabilities(tmp_path):
    _, svc = make(tmp_path)
    tree, _ = svc.read()
    types = [b.type for b in tree.blocks]
    assert types == ["frontmatter", "heading", "paragraph", "code", "table", "paragraph"]
    head = tree.blocks[1]
    assert head.attrs == {"level": 1} and head.content == "# Head\n"
    assert tree.blocks[3].attrs == {"lang": "chart"}
    # a block the page may not edit (a fence, front matter) can still be moved and removed
    assert tree.blocks[3].caps == frozenset({"move", "remove"})
    assert tree.blocks[2].caps == frozenset({"edit", "move", "remove"})


def test_a_quote_and_a_list_hold_their_blocks_and_items_as_children(tmp_path):
    _, svc = make(tmp_path, "> one\n>\n> two\n\n- a\n- b\n")
    tree, _ = svc.read()
    quote, lst = tree.blocks
    assert [c.type for c in quote.children] == ["paragraph", "paragraph"]
    assert [c.type for c in lst.children] == ["item", "item"]
    assert [c.type for c in lst.children[0].children] == ["paragraph"]
    every = [b.id for b in tree.walk()]
    assert len(every) == len(set(every)) == 8


# ── ids ──────────────────────────────────────────────────────────────────────

def test_a_plain_block_keeps_its_id_when_another_block_is_edited_and_changes_it_when_its_own_is(tmp_path):
    _, svc = make(tmp_path)
    a, _ = svc.read()
    changed = DOC.replace("First paragraph.", "First paragraph, edited.")
    p2, svc2 = make(tmp_path, changed, "e.md")
    b, _ = svc2.read()
    ids_a, ids_b = [x.id for x in a.blocks], [x.id for x in b.blocks]
    assert ids_a[2] != ids_b[2]
    assert [i for k, i in enumerate(ids_a) if k != 2] == [i for k, i in enumerate(ids_b) if k != 2]


def test_two_equal_blocks_get_the_same_hash_and_a_suffix_on_the_second(tmp_path):
    _, svc = make(tmp_path, "Same.\n\nOther.\n\nSame.\n\nSame.\n")
    tree, _ = svc.read()
    ids = [b.id for b in tree.blocks]
    assert ids[2] == ids[0] + "-2" and ids[3] == ids[0] + "-3"
    assert len(set(ids)) == 4


def test_a_type_change_changes_the_id_even_when_the_text_is_the_same(tmp_path):
    _, a = make(tmp_path, "Word\n")
    _, b = make(tmp_path, "# Word\n", "e.md")
    assert a.read()[0].blocks[0].id != b.read()[0].blocks[0].id


# ── byte for byte ────────────────────────────────────────────────────────────

def test_saving_the_text_as_it_is_writes_nothing_new(tmp_path):
    p, svc = make(tmp_path)
    _, base = svc.read()
    out = save(svc, DOC, base)
    assert out["outcome"] == "written" and out["base"] == base
    assert disk(p) == DOC


def test_an_edit_leaves_every_other_block_front_matter_and_the_chart_fence_byte_for_byte(tmp_path):
    odd = ("---\ntitle: T\nlist:   [a,   b]\n---\n\n"
           "First paragraph.\n\n"
           "~~~~chart\n{\"a\":   1}\n~~~~\n\n\n"
           "| a  | b |\n|:--|--:|\n| 1 | 2 |\n\n"
           "Last.")
    p, svc = make(tmp_path, odd)
    tree, base = svc.read()
    edited = odd.replace("First paragraph.", "First paragraph, edited.")
    out = save(svc, edited, base)
    assert out["outcome"] == "written"
    assert disk(p) == edited
    assert out["blocks"] == [b.id for b in svc.read()[0].blocks]


def test_the_page_sending_the_document_with_pandocs_own_spelling_changes_no_byte(tmp_path):
    """A fence of another length, a re-padded table and a re-marked fence are pandoc's cosmetic rewrites."""
    text = ("Intro.\n\n"
            "~~~~chart\n{\"a\": 1}\n~~~~\n\n"
            "| a | b |\n|:--|--:|\n| 1 | 22 |\n\n"
            "```js\nx = 1\n```\n")
    p, svc = make(tmp_path, text)
    _, base = svc.read()
    cosmetic = ("Intro.\n\n"
                "```chart\n{\"a\": 1}\n```\n\n"
                "| a   |   b |\n|:----|----:|\n| 1   |  22 |\n\n"
                "~~~js\nx = 1\n~~~\n")
    assert cosmetic != text
    out = save(svc, cosmetic, base)
    assert out["outcome"] == "written" and out["base"] == base
    assert disk(p) == text


def test_a_cosmetic_rewrite_beside_a_real_edit_keeps_the_original_bytes_of_the_cosmetic_block(tmp_path):
    text = "Intro.\n\n| a | b |\n|:--|--:|\n| 1 | 22 |\n\nEnd.\n"
    p, svc = make(tmp_path, text)
    _, base = svc.read()
    sent = "Intro, edited.\n\n| a   |   b |\n|:----|----:|\n| 1   |  22 |\n\nEnd.\n"
    save(svc, sent, base)
    assert disk(p) == "Intro, edited.\n\n| a | b |\n|:--|--:|\n| 1 | 22 |\n\nEnd.\n"


def test_the_spacing_between_unchanged_blocks_is_the_files_own(tmp_path):
    text = "One.\n\n\n\nTwo.\n\nThree.\n"
    p, svc = make(tmp_path, text)
    _, base = svc.read()
    save(svc, "One.\n\nTwo.\n\nThree, edited.\n", base)
    assert disk(p) == "One.\n\n\n\nTwo.\n\nThree, edited.\n"


def test_a_block_added_after_the_last_one_of_a_file_with_no_final_newline_does_not_run_into_it(tmp_path):
    p, svc = make(tmp_path, "One.\n\nTwo.")
    _, base = svc.read()
    save(svc, "One.\n\nTwo.\n\nThree.\n", base)
    assert disk(p) == "One.\n\nTwo.\n\nThree.\n"


def test_blocks_that_touch_in_the_file_still_touch_after_an_edit_of_one_of_them(tmp_path):
    text = "# Head\nA line under it.\nMore.\n- item\n\nEnd.\n"
    p, svc = make(tmp_path, text)
    _, base = svc.read()
    sent = text.replace("A line under it.", "A line under it, edited.")
    save(svc, sent, base)
    assert disk(p) == sent


def test_a_block_that_touched_the_next_one_in_the_file_is_set_apart_when_another_follows_it(tmp_path):
    text = "Para\n- item\n\nEnd.\n"
    p, svc = make(tmp_path, text)
    _, base = svc.read()
    save(svc, "End.\n\nPara\n\nOther.\n", base)
    assert disk(p) == "End.\n\nPara\n\nOther.\n"


def test_a_deleted_block_takes_only_its_own_bytes(tmp_path):
    p, svc = make(tmp_path, "One.\n\nTwo.\n\n\nThree.\n")
    _, base = svc.read()
    save(svc, "One.\n\nThree.\n", base)
    assert disk(p) == "One.\n\nThree.\n"


def test_a_block_matched_by_the_id_the_page_held_is_written_back_as_the_file_had_it(tmp_path):
    p, svc = make(tmp_path, "Twin.\n\nTwin.\n")
    tree, base = svc.read()
    held = [b.id for b in tree.blocks]
    out = save(svc, "Twin.\n\nTwin.\n\nNew.\n", base, held=held + [None])
    assert out["outcome"] == "written" and disk(p) == "Twin.\n\nTwin.\n\nNew.\n"


# ── the three outcomes and the page session ──────────────────────────────────

def test_two_successive_saves_of_one_page_session_on_the_old_base_never_conflict(tmp_path):
    p, svc = make(tmp_path, "One.\n\nTwo.\n")
    _, base0 = svc.read()
    a = save(svc, "One, a.\n\nTwo.\n", base0, session="page-1")
    b = save(svc, "One, a.\n\nTwo, b.\n", base0, session="page-1")      # the page never waited for a's answer
    c = save(svc, "One, a.\n\nTwo, c.\n", base0, session="page-1")
    assert [a["outcome"], b["outcome"], c["outcome"]] == ["written"] * 3
    assert disk(p) == "One, a.\n\nTwo, c.\n"


def test_another_page_session_on_that_old_base_is_a_conflict_and_writes_nothing(tmp_path):
    p, svc = make(tmp_path, "One.\n\nTwo.\n")
    _, base0 = svc.read()
    save(svc, "One, a.\n\nTwo.\n", base0, session="page-1")
    out = save(svc, "One.\n\nTwo, theirs.\n", base0, session="page-2")
    assert out["outcome"] == "conflict" and out["base"] == rds.md_hash(disk(p))
    assert disk(p) == "One, a.\n\nTwo.\n"


def test_a_write_from_outside_the_service_between_two_saves_of_a_page_breaks_its_own_chain(tmp_path):
    p, svc = make(tmp_path, "One.\n\nTwo.\n")
    _, base0 = svc.read()
    save(svc, "One, a.\n\nTwo.\n", base0, session="page-1")
    p.write_text("One, a.\n\nTwo, someone else.\n", encoding="utf-8")
    out = save(svc, "One, b.\n\nTwo.\n", base0, session="page-1")
    assert out["outcome"] == "conflict"
    assert disk(p) == "One, a.\n\nTwo, someone else.\n"


def test_a_save_on_the_current_base_by_any_session_is_written(tmp_path):
    p, svc = make(tmp_path, "One.\n\nTwo.\n")
    _, base = svc.read()
    assert save(svc, "One.\n\nTwo!\n", base, session="anyone")["outcome"] == "written"


def test_a_file_that_is_not_markdown_is_refused_through_the_adapter(tmp_path):
    p, svc = make(tmp_path, "One.\n", "d.txt")
    _, base = svc.read()
    out = save(svc, "Two.\n", base)
    assert out["outcome"] == "refused" and "not a .md" in out["reason"]
    assert disk(p) == "One.\n"


def test_a_document_pandoc_cannot_read_is_still_saved_as_the_page_sent_it(tmp_path, monkeypatch):
    from sheafmd import _pandoc
    p, svc = make(tmp_path, "One.\n")
    _, base = svc.read()
    monkeypatch.setattr(_pandoc, "run", lambda args, text: subprocess.CompletedProcess(args, 1, "", "no"))
    out = save(svc, "Two.\n", base)
    assert out["outcome"] == "written" and disk(p) == "Two.\n"


def test_an_edited_link_or_footnote_definition_is_written_and_not_put_back_as_the_file_had_it(tmp_path):
    p, svc = make(tmp_path, "See [a] and [b].[^1]\n\n[a]: https://one.example\n\n[b]: https://two.example\n\n[^1]: Old note.\n")
    _, base = svc.read()
    new = "See [a] and [b].[^1]\n\n[a]: https://changed.example\n\n[b]: https://two.example\n\n[^1]: New note.\n"
    assert save(svc, new, base)["outcome"] == "written"
    assert disk(p) == new


def test_two_definitions_that_swap_places_are_written_in_the_order_the_page_sent(tmp_path):
    p, svc = make(tmp_path, "See [a] and [b].\n\n[a]: https://one.example\n\n[b]: https://two.example\n")
    _, base = svc.read()
    new = "See [a] and [b].\n\n[b]: https://two.example\n\n[a]: https://one.example\n"
    save(svc, new, base)
    assert disk(p) == new


def test_a_last_block_without_a_final_newline_is_not_run_into_a_block_that_touches_it_in_the_page(tmp_path):
    p, svc = make(tmp_path, "One.\n\nTwo.")
    _, base = svc.read()
    save(svc, "One.\n\nTwo.\n- item\n", base)
    assert disk(p) == "One.\n\nTwo.\n- item\n"


def test_reading_a_file_pandoc_cannot_read_says_so(tmp_path, monkeypatch):
    from sheafmd import _pandoc
    from sheafmd.blocks import Unreadable
    p, svc = make(tmp_path, "One.\n")
    monkeypatch.setattr(_pandoc, "run", lambda args, text: subprocess.CompletedProcess(args, 1, "", "no"))
    with pytest.raises(Unreadable):
        svc.read()


# ── the tree reader on its own ───────────────────────────────────────────────

def test_the_tiles_of_a_tree_join_back_to_the_text():
    text = "\n\nA.\n\n\n# B\n\n```\nc\n```\n"
    tree = read_tree(text)
    assert tree.lead + "".join(b.content + b.gap for b in tree.blocks) == text


# ── a real set of existing files ─────────────────────────────────────────────

def tracked_markdown():
    got = subprocess.run(["git", "ls-files", "-z", "*.md"], cwd=ROOT, capture_output=True)
    names = [n for n in got.stdout.decode("utf-8").split("\0") if n] if got.returncode == 0 else []
    files = [ROOT / n for n in names]
    return [f for f in files if f.is_file() and f.stat().st_size < 150_000]


REAL = tracked_markdown()


def first_paragraph(text):
    off = 0
    for t in split_md_blocks(text):
        if t.kind == "para" and "![" not in t.content and t.content.strip() and not t.content.lstrip().startswith(("<", "[")) \
                and ":" not in t.content.split("\n")[0][:3]:
            return off, t
        off += len(t.text)
    return None


@pytest.mark.skipif(not REAL, reason="no tracked Markdown to read (not a git checkout)")
def test_the_set_of_the_repositorys_own_markdown_is_not_empty():
    assert len(REAL) > 20


@pytest.mark.parametrize("path", REAL, ids=lambda p: str(p.relative_to(ROOT)))
def test_on_a_real_file_a_save_of_the_same_text_and_a_save_with_one_edit_change_only_that_block(tmp_path, path):
    text = path.read_text(encoding="utf-8")
    p, svc = make(tmp_path, text)
    tree, base = svc.read()
    assert tree.text == text
    out = save(svc, text, base)
    assert out["outcome"] == "written" and out["base"] == base and disk(p) == text
    found = first_paragraph(text)
    if found is None:
        return
    off, tile = found
    body = tile.content
    ends = body.endswith("\n")
    edited_body = body.rstrip("\n") + " (edited)" + ("\n" if ends else "")
    sent = text[:off] + edited_body + text[off + len(body):]
    out = save(svc, sent, base)
    assert out["outcome"] == "written"
    assert disk(p) == sent


def pandoc_spelling(text):
    """The file as pandoc writes Markdown: every fence, table and list marker in pandoc's own form."""
    from sheafmd import _pandoc
    got = _pandoc.run(["-f", "gfm+fenced_divs+bracketed_spans", "-t", "gfm+fenced_divs+bracketed_spans", "--wrap=preserve"], text)
    return got.stdout if got.returncode == 0 else None


@pytest.mark.parametrize("path", REAL, ids=lambda p: str(p.relative_to(ROOT)))
def test_on_a_real_file_pandocs_own_spelling_of_the_text_leaves_every_block_it_reads_alike_as_the_file_had_it(tmp_path, path):
    text = path.read_text(encoding="utf-8")
    spelled = pandoc_spelling(text)
    if spelled is None:
        pytest.skip("pandoc does not read this file")
    p, svc = make(tmp_path, text)
    tree, base = svc.read()
    try:
        theirs = read_tree(spelled)
    except Exception:
        pytest.skip("pandoc's spelling does not read back")
    out = save(svc, spelled, base)
    assert out["outcome"] == "written"
    mine = {}
    for b in tree.blocks:
        mine.setdefault((b.type, b.ast), set()).add(b.content)       # equal blocks may be spelled alike or not
    for b in read_tree(disk(p)).blocks:
        if b.key in mine:
            assert b.content in mine[b.key]
    if [(b.type, b.ast) for b in theirs.blocks] == [(b.type, b.ast) for b in tree.blocks]:
        assert disk(p) == text
