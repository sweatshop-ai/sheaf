"""Comments in every block kind, with both markers, over the public corpus."""
from pathlib import Path

import pytest

from sheafmd import comments as rdc
from sheafmd.blocks import COMMENTABLE_KINDS, split_md_blocks

CORPUS = Path(__file__).resolve().parent / "corpus" / "comments-in-every-block.md"
TEXT = CORPUS.read_bytes().decode("utf-8")
EXPECTED = [  # id, marker, the kind of block it sits in
    ("c1", "sheaf-comment", "para"), ("c2", "sheaf-comment", "heading"),
    ("c3", "sheaf-comment", "list"), ("c4", "sheaf-comment", "quote"),
    ("c5", "sheaf-comment", "table"), ("c6", "sheaf-comment", "html"),
    ("c7", "rd-comment", "para"), ("c8", "rd-comment", "heading"),
    ("c9", "rd-comment", "list"), ("c10", "rd-comment", "quote"),
    ("c11", "rd-comment", "html"),
]


def test_every_comment_in_every_block_kind_is_found_with_its_marker():
    got = rdc.parse(TEXT)
    blocks = split_md_blocks(TEXT)
    assert got.malformed == []
    assert [(c.id, c.marker, blocks[c.block].kind) for c in got.comments] == EXPECTED
    # A comment on text sits in a commentable block; one on its own line is standalone.
    for c in got.comments:
        kind = blocks[c.block].kind
        assert (kind in COMMENTABLE_KINDS) != c.standalone


def test_foreign_comments_are_not_comments_and_are_not_malformed():
    got = rdc.parse(TEXT)
    assert "@comment{note for later}" not in " ".join(c.body for c in got.comments)
    assert not any("toc" in m.text or "@comment" in m.text for m in got.malformed)


@pytest.mark.parametrize("cid", [e[0] for e in EXPECTED])
def test_changing_one_comment_changes_only_that_comment(cid):
    """The plausible wrong answer rewrites the document or a neighbour; the right one
    changes the bytes of one comment and nothing else."""
    for new in (rdc.set_status(TEXT, cid, "resolved"),
                rdc.reply(TEXT, cid, "Noted.", "Grace", "2026-01-06T09:00", role="answer")):
        before, after = rdc.parse(TEXT).by_id(cid), rdc.parse(new).by_id(cid)
        assert new[:before.start] == TEXT[:before.start]
        assert new[after.end:] == TEXT[before.end:]
        assert after.marker == before.marker and after.id == cid
        others = [c.id for c in rdc.parse(TEXT).comments if c.id != cid]
        for other in others:
            a, b = rdc.parse(TEXT).by_id(other), rdc.parse(new).by_id(other)
            assert TEXT[a.start:a.end] == new[b.start:b.end], other
