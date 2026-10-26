"""The block model: the base of editing (SPEC 5.1).

Its guarantee is that the blocks tile the text exactly, for every text. The corpus in
tests/corpus/ is public, written for the purpose, and covers every block kind.
"""
import re
from pathlib import Path

import pytest

from sheafmd.blocks import COMMENTABLE_KINDS, LOCKED_KINDS, SENTINEL_RE, instrument, split_md_blocks
from sheafmd.edit import apply_edits

CORPUS = Path(__file__).resolve().parent / "corpus"
# Names that must not appear in a public fixture.
PRIVATE = re.compile("tiroir|acme", re.I)
FILES = sorted(CORPUS.glob("*.md"))
ALL_KINDS = {"blank", "frontmatter", "heading", "para", "list", "quote", "table", "fence",
             "indented_code", "html", "hr"}


def read(path):
    # Bytes, not read_text: the corpus holds CRLF and a file with no final newline.
    return path.read_bytes().decode("utf-8")


def tiles(text):
    return "".join(b.text for b in split_md_blocks(text)) == text


def test_the_corpus_is_there_and_has_no_client_data():
    assert len(FILES) >= 15
    for f in FILES:
        assert not PRIVATE.search(read(f)), f.name


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_the_blocks_tile_every_corpus_file(path):
    assert tiles(read(path))


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_the_blocks_tile_every_cut_of_every_corpus_file(path):
    """Any prefix of a document is a document: a half-typed fence, comment or table."""
    text = read(path)
    for k in list(range(0, min(len(text), 120))) + list(range(0, len(text), 13)):
        assert tiles(text[:k]), (path.name, k, text[:k][-60:])


def test_the_blocks_tile_corpus_files_joined_in_pairs():
    texts = [read(f) for f in FILES]
    for a in texts:
        for b in texts:
            assert tiles(a + b)


def test_the_corpus_covers_every_block_kind():
    seen = {b.kind for f in FILES for b in split_md_blocks(read(f))}
    assert seen == ALL_KINDS


def test_locked_blocks_are_not_editable_and_nothing_else_is_except_an_image_line():
    editable_kinds, locked_kinds = set(), set()
    for f in FILES:
        for b in split_md_blocks(read(f)):
            if b.kind in LOCKED_KINDS:
                assert not b.editable, (f.name, b)
                locked_kinds.add(b.kind)
            elif re.search(r"!\[[^\]]*\]\(", b.content):
                assert not b.editable, (f.name, b)      # an image line is locked
            else:
                assert b.editable, (f.name, b)
                editable_kinds.add(b.kind)
    assert locked_kinds == LOCKED_KINDS
    assert {"para", "heading", "list", "quote", "table", "blank", "hr"} <= editable_kinds


def test_commentable_kinds_are_the_text_blocks():
    assert COMMENTABLE_KINDS == {"para", "heading", "list", "quote", "table"}
    assert not COMMENTABLE_KINDS & LOCKED_KINDS


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_instrument_puts_one_blank_line_before_each_sentinel(path):
    text = read(path)
    inst, blocks = instrument(text)
    assert [b.text for b in blocks] == [b.text for b in split_md_blocks(text)]
    ids = [int(m.group(1)) for m in SENTINEL_RE.finditer(inst)]
    assert ids == sorted(set(ids)) and all(0 <= i < len(blocks) for i in ids)
    # Two blank lines before a sentinel turn a preceding task list loose.
    assert not re.search(r"\n\n\n[ \t]*<!--MDB:", inst)
    for m in SENTINEL_RE.finditer(inst):
        assert inst[m.end():m.end() + 2] == "\n\n"
        assert m.start() == 0 or inst[m.start() - 2:m.start()] == "\n\n"
    # No sentinel for a blank block or for front matter (pandoc reads it only at byte 0).
    for i in ids:
        assert blocks[i].kind not in ("blank", "frontmatter")
    if blocks and blocks[0].kind == "frontmatter":
        assert inst.startswith(blocks[0].content)


def test_a_fence_keeps_what_looks_like_markdown_inside_it():
    blocks = split_md_blocks("```\n# not a heading\n- not a list\n\nstill code\n```\n\nafter\n")
    assert [b.kind for b in blocks if b.kind != "blank"] == ["fence", "para"]


@pytest.mark.parametrize("text", [
    "Text ![plot][p] and more.\n",                 # full reference
    "Text ![plot][] and more.\n",                 # collapsed reference
    "Text ![plot] and more.\n",                   # shortcut reference
    "Text ![plot] [p] and more.\n",               # a space before the label
    "Text ![a [nested] alt](plot.png) here.\n",   # inline, with brackets in the alt text
    "Text ![\nwrapped alt](plot.png) here.\n",
])
def test_every_way_to_write_an_image_locks_the_block(text):
    (b,) = [b for b in split_md_blocks(text) if b.kind == "para"]
    assert not b.editable


@pytest.mark.parametrize("text", [
    'The chart <img src="figures/q3.png" alt="Q3"> shows growth.\n',
    'The chart <IMG SRC="figures/q3.png"> shows growth.\n',
    'The chart <img\nsrc="figures/q3.png"\nalt="Q3"> shows growth.\n',
    '- item with <img src="a.png"> in it\n- another\n',
])
def test_a_raw_img_tag_locks_the_block_like_any_other_image(text):
    """With the file missing the page shows a red [missing image] span for the tag, and
    saving the paragraph wrote that span over it, with no error."""
    (b,) = [b for b in split_md_blocks(text) if b.kind != "blank"]
    assert not b.editable
    new, rep = apply_edits(text, [{"i": 0, "html": "<p>edited</p>"}])
    assert new == text and rep["changed"] == [] and [i for i, _ in rep["skipped"]] == [0]


def test_a_paragraph_without_an_image_stays_editable():
    for text in ["A ! mark and a [link](x.html) and [ref][p].\n", "Hello! [there]\n", "Wow!\n",
                 "An <imgur> tag and an <i>italic</i> one.\n"]:
        (b,) = [b for b in split_md_blocks(text) if b.kind == "para"]
        assert b.editable, text
