"""Edits over the public corpus: no save, of any block, may lose, move or rewrite a comment.

The corpus in tests/corpus/ holds comments of both markers and foreign comments in
every block kind. Each test sends the blocks the way the page does (pandoc's render,
a comment node of ours replaced by an anchor span, a foreign one left as it is).
"""
import re
from pathlib import Path

import pytest

from sheafmd import comments as rdc
from sheafmd import edit as rde
from sheafmd.blocks import split_md_blocks
from test_save_roundtrip import page_fragment

FILES = sorted((Path(__file__).resolve().parent / "corpus").glob("*.md"))


def read(path):
    return path.read_bytes().decode("utf-8")      # bytes: the corpus holds CRLF


def sent(text, change=lambda frag: frag):
    return [{"i": i, "html": change(page_fragment(b.content))}
            for i, b in enumerate(split_md_blocks(text)) if b.editable and b.content.strip()]


def raws(text):
    return {c.id: text[c.start:c.end] for c in rdc.parse(text).comments}


def first_letter(frag):
    return re.sub(r"(?<=>)([A-Za-z])", r"Z\1", frag, count=1)


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_a_page_save_with_nothing_changed_writes_nothing(path):
    text = read(path)
    new, rep = rde.apply_edits(text, sent(text))
    assert new == text and rep["changed"] == [] and rep["skipped"] == []


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_editing_every_block_keeps_every_comment_of_every_kind_byte_for_byte(path):
    text = read(path)
    new, rep = rde.apply_edits(text, sent(text, first_letter))
    assert rep["skipped"] == []
    assert raws(new) == raws(text)
    assert rde._foreign_comments(new) == rde._foreign_comments(text)
    assert not [c for c in rdc.parse(new).comments if c.orphan]
    assert [m.reason for m in rdc.parse(new).malformed] == [m.reason for m in rdc.parse(text).malformed]


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_deleting_every_block_loses_no_comment(path):
    """Sheaf comments become orphans with their bytes' content and marker; foreign ones stay."""
    text = read(path)
    new, _ = rde.apply_edits(text, [{"i": i, "html": ""} for i, b in enumerate(split_md_blocks(text))
                                    if b.editable])
    before, after = {c.id: c for c in rdc.parse(text).comments}, {c.id: c for c in rdc.parse(new).comments}
    assert set(before) == set(after)
    for cid, c in before.items():
        a = after[cid]
        assert (a.marker, a.by, a.at, a.quote, a.body, a.status) == (c.marker, c.by, c.at, c.quote, c.body, c.status)
        assert [(r.by, r.role, r.text) for r in a.replies] == [(r.by, r.role, r.text) for r in c.replies]
    assert sorted(rde._foreign_comments(new)) == sorted(rde._foreign_comments(text))


def test_the_corpus_is_not_vacuous_for_these_tests():
    """Both markers, foreign comments, and edits that really change blocks."""
    texts = [read(f) for f in FILES]
    markers = {c.marker for t in texts for c in rdc.parse(t).comments}
    assert markers == {"sheaf-comment", "rd-comment"}
    assert sum(len(rde._foreign_comments(t)) for t in texts) >= 4
    assert sum(len(rde.apply_edits(t, sent(t, first_letter))[1]["changed"]) for t in texts) >= 100
