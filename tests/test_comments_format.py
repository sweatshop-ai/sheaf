"""The comment format: what is in the .md, and what a reader gets back from it."""
import pytest
from helpers import pandoc

from sheafmd import comments as rdc
from sheafmd.blocks import split_md_blocks


def test_parses_the_example_from_the_spec():
    md = ('The gap is **52%**<!-- rd-comment id=c3 by="Ada" at=2026-09-19T14:02 '
          'status=open quote="The gap is 52%"\n'
          'Source? This looks like the old figure.\n'
          '@Claude 2026-09-19T14:30: Re-derived from GSC, 52% holds.\n'
          '--> and it matters.\n')
    [c] = rdc.parse(md).comments
    assert (c.id, c.by, c.at, c.status, c.quote) == (
        "c3", "Ada", "2026-09-19T14:02", "open", "The gap is 52%")
    assert c.body == "Source? This looks like the old figure."
    assert [(r.by, r.at, r.text) for r in c.replies] == [
        ("Claude", "2026-09-19T14:30", "Re-derived from GSC, 52% holds.")]
    assert md[c.start:c.end].startswith("<!-- rd-comment id=c3")
    assert md[c.start:c.end].endswith("-->")
    assert c.line == 1


def test_authors_own_comments_and_sentinels_are_not_review_comments():
    md = "<!-- TODO: rewrite -->\n\n<!--MDB:3-->\n\nText<!-- rd-comment id=c1 by=\"A\" at=2026-01-01T00:00 status=open quote=\"Text\" -->\n"
    got = rdc.parse(md)
    assert [c.id for c in got.comments] == ["c1"]
    assert got.malformed == []


def test_comment_inside_a_fence_is_code_not_a_comment():
    md = "```\nx<!-- rd-comment id=c1 by=\"A\" at=2026-01-01T00:00 status=open quote=\"x\" -->\n```\n"
    assert rdc.parse(md).comments == []


def test_malformed_comments_are_reported_with_their_line():
    md = ("a<!-- rd-comment id=c1 by=\"A\" at=2026-01-01T00:00 status=open quote=\"a\" -->\n\n"
          "b<!-- rd-comment id=c1 by=\"A\" at=2026-01-01T00:00 status=open quote=\"b\" -->\n\n"
          "c<!-- rd-comment by=\"A\" status=open -->\n\n"
          "d<!-- rd-comment id=c4 status=maybe -->\n\n"
          "e<!-- rd-comment id=c5 status=open status=resolved -->\n\n"
          "f<!-- rd-comment id=c6 status=open quote=\"f\" never closed\n")
    got = rdc.parse(md)
    assert [c.id for c in got.comments] == ["c1"]
    reasons = {m.line: m.reason for m in got.malformed}
    assert set(reasons) == {3, 5, 7, 9, 11}
    assert "duplicate id" in reasons[3]
    assert "id" in reasons[5]
    assert "status" in reasons[7]
    assert "duplicate key" in reasons[9]
    assert "never closed" in reasons[11]


def test_round_trip_of_awkward_text_multi_line():
    c = rdc.Comment(id="c7", by="Jean Paul", at="2026-09-22T10:00", status="open",
                    quote='a "quoted" | pipe',
                    body="Line one -- with dashes --> and <b>\n\n- looks like a list\n# and a heading\n@not a reply 2026-01-01T00:00: x\n3. numbered & more")
    c.replies.append(rdc.Reply("Claude", "2026-09-22T11:00", "Fixed.\nSecond line"))
    raw = rdc.format(c, one_line=False)
    assert "\n\n" not in raw
    back = rdc.parse("Text" + raw + " tail\n").comments[0]
    assert (back.by, back.quote, back.body) == (c.by, c.quote, c.body)
    assert [(r.by, r.text) for r in back.replies] == [("Claude", "Fixed.\nSecond line")]


@pytest.mark.parametrize("line", ["___", "_ _ _", "_____ "])
def test_a_line_of_underscores_in_a_comment_or_reply_cannot_split_its_paragraph(line):
    """`___` is a thematic break, and one can interrupt a paragraph: the comment's
    body line then ended the paragraph, parse read nothing and reported a comment
    that was never closed, and reply and resolve found no comment c1."""
    md, cid = rdc.add_comment("Alpha beta gamma.\n\nNext.\n", 0, 0, 5, "Alpha",
                              f"Sign here:\n{line}\nthanks", by="Ada", at="2026-10-14T10:00")
    assert [b.kind for b in split_md_blocks(md)] == ["para", "para"]
    got = rdc.parse(md)
    assert got.malformed == [] and [c.body for c in got.comments] == [f"Sign here:\n{line}\nthanks"]
    md = rdc.reply(md, cid, f"Signed:\n{line}\nbye", "Claude", "2026-10-14T11:00")
    assert [b.kind for b in split_md_blocks(md)] == ["para", "para"]
    md = rdc.set_status(md, cid, "resolved")
    [c] = rdc.parse(md).comments
    assert c.status == "resolved" and c.replies[0].text == f"Signed:\n{line}\nbye"


def test_a_backtick_in_a_comment_does_not_pair_with_one_after_it():
    """CommonMark reads left to right: the comment starts first and owns the backtick
    in its body, so the `make` after it is a code span of its own. parse blanked the
    code spans first, paired the body's backtick with the one before `make`, and read
    no comment: it could not be listed, replied to or resolved."""
    md, cid = rdc.add_comment("Press the key, then run `make` to build.\n", 0, 0, 11, "Press the key",
                              "which key? the ` one?", by="Ada", at="2026-10-14T10:00")
    got = rdc.parse(md)
    assert got.malformed == [] and [(c.id, c.body) for c in got.comments] == [(cid, "which key? the ` one?")]
    md = rdc.reply(md, cid, "this one: `\u2318` (two)", "Claude", "2026-10-14T11:00", resolve=True)
    [c] = rdc.parse(md).comments
    assert c.status == "resolved" and c.replies[0].text == "this one: `\u2318` (two)"


@pytest.mark.parametrize("one_line", [False, True])
def test_a_backtick_in_a_comment_cannot_pair_with_an_unpaired_one_before_it(one_line):
    """An unpaired backtick before a comment opened a code span that closed on the
    backtick format wrote raw into the comment: the page showed the comment's head as
    code, and parse masked it and read no comment (#136). A backtick is written as an
    entity, so the comment holds none, and it reads back as a backtick."""
    c = rdc.Comment(id="c1", by="A`da", at="2026-10-31T10:00", status="open",
                    quote="the ` key", body="which ` key?\n`first` on a line")
    c.replies.append(rdc.Reply("Claude", "2026-10-31T11:00", "this ` one"))
    raw = rdc.format(c, one_line=one_line)
    md = f"Use the ` key here{raw} tail.\n"
    out = pandoc(["-f", "gfm", "-t", "html"], md)
    assert "<code>" not in out and "&lt;!--" not in out and "sheaf-comment" in out, out
    [back] = rdc.parse(md).comments
    assert (back.by, back.quote, back.body) == (c.by, c.quote, c.body)
    assert [r.text for r in back.replies] == ["this ` one"]
    assert "`" not in raw


def test_a_head_after_an_earlier_code_span_and_one_inside_a_longer_span_are_read_as_before():
    head = '<!-- sheaf-comment id=c%d by="Ada" at=2026-10-14T10:00 status=open quote="x"\nbody\n-->'
    md = f"Run `make` first.{head % 1} Then ``a ` b {head % 9} c`` end.\n"
    assert [c.id for c in rdc.parse(md).comments] == ["c1"]


def test_round_trip_one_line():
    c = rdc.Comment(id="c8", by="T", at="2026-09-22T10:00", status="resolved",
                    quote="q", body="a | b\n\nc")
    raw = rdc.format(c, one_line=True)
    assert "\n" not in raw and "|" not in raw
    assert rdc.parse("x" + raw + "\n").comments[0].body == "a | b\n\nc"


@pytest.mark.parametrize("marker", ["sheaf-comment", "rd-comment"])
def test_written_comment_is_invisible_in_every_block_kind(marker):
    c = rdc.Comment(id="c9", by="T", at="2026-09-22T10:00", status="open", marker=marker,
                    quote="q", body="has -- dashes\n- and a list line\n\nand a gap")
    multi, one = rdc.format(c, one_line=False), rdc.format(c, one_line=True)
    docs = {
        "para": f"Para text{multi} tail.\n",
        "list": f"- item one{multi} tail\n- item two\n",
        "quote": f"> quoted{multi} tail\n",
        "heading": f"## Heading{one}\n",
        "table": f"| A | B |\n|---|---|\n| cell{one} | x |\n",
    }
    for kind, md in docs.items():
        out = pandoc(["-f", "gfm", "-t", "html"], md)
        assert marker in out, kind
        assert "&lt;!--" not in out and "dashes" not in out.replace(multi, "").replace(one, ""), (kind, out)
        visible = out.split("<!--")[0] + out.split("-->")[-1]
        assert "dashes" not in visible, (kind, out)
    assert "<li>item two</li>" in pandoc(["-f", "gfm", "-t", "html"], docs["list"])


def test_next_id_is_highest_plus_one():
    md = "a<!-- rd-comment id=c2 status=open -->\n\nb<!-- rd-comment id=c10 status=open -->\n"
    assert rdc.next_id(rdc.parse(md)) == "c11"
    assert rdc.next_id(rdc.parse("nothing\n")) == "c1"


def test_a_comment_written_inside_inline_code_is_an_example_not_a_comment():
    md = "Pandoc keeps it (`<p>…<!-- rd-comment … --></p>`), and ``x <!-- rd-comment id=c9 -->`` too.\n"
    got = rdc.parse(md)
    assert got.comments == [] and got.malformed == []


def test_the_tail_of_a_comment_whose_head_was_deleted_is_malformed():
    # An agent replaced the paragraph's whole line, head of the comment included.
    md = ("- New text of the paragraph.\n"
          "Ok, can you make a plan?\n"
          "-->, otherwise every check repeats the false alarm.\n")
    got = rdc.parse(md)
    assert got.comments == []
    assert [(m.line, m.reason.split(":")[0]) for m in got.malformed] == \
        [(3, "a closing --> with no opening")]


def test_an_arrow_in_prose_and_a_whole_comment_are_not_strays():
    md = ("Render --> share copy.\n\n"
          "Text<!-- rd-comment id=c1 by=\"T\" at=2026-10-13T10:00 status=open quote=\"Text\"\n"
          "Body.\n"
          "-->.\n\n"
          "<!-- toc -->\n")
    got = rdc.parse(md)
    assert [c.id for c in got.comments] == ["c1"]
    assert got.malformed == []


def test_reading_a_block_of_many_code_spans_scans_it_once_not_once_per_span(monkeypatch):
    """`_mask_code` searched for a comment head from the position after
    every span, so a table with a code span in each row was read in quadratic time
    (0.45 s for 8,000 rows, 30 s for 32,000). Measured as work, not as seconds: the
    characters the comment pattern is run over must stay a small multiple of the
    document, however many spans it holds."""
    rows = 3000
    md = ("| h |\n|---|\n" + "".join(f"| `c{i}` |\n" for i in range(rows // 2))
          + 'x<!-- rd-comment id=c1 by="A" at=2026-01-01T00:00 status=open quote="x"\n'
            "a `tick in the body\n-->\n"
          + "".join(f"| `d{i}` |\n" for i in range(rows // 2)))
    scanned = []

    class Counting:
        def __init__(self, real):
            self.real = real

        def search(self, text, pos=0, *rest):
            scanned.append(len(text) - pos)
            return self.real.search(text, pos, *rest)

        def __getattr__(self, name):
            return getattr(self.real, name)

    monkeypatch.setattr(rdc, "COMMENT_RE", Counting(rdc.COMMENT_RE))
    got = rdc.parse(md)
    assert [c.id for c in got.comments] == ["c1"] and got.malformed == []
    assert sum(scanned) <= 4 * len(md)


# ── a line break in an author's name cannot split the comment's head ──

AT = "2026-10-14T10:00"
ODD_NAMES = ["Eve\nMallory", "Eve\r\nMallory", "Eve\rMallory", "Eve\tMallory", "Eve Mallory", "Eve Mallory"]


def read_back(md):
    """The file as a reader that takes \\r and \\r\\n for a line break (Path.read_text) gets it."""
    return md.replace("\r\n", "\n").replace("\r", "\n")


@pytest.mark.parametrize("name", ODD_NAMES)
def test_a_line_break_or_other_whitespace_in_the_author_of_a_comment_round_trips(name):
    out, _ = rdc.add_comment("Alpha beta.\n", 0, 0, 5, "Alpha", "review text", name, AT)
    parsed = rdc.parse(read_back(out))
    [c] = parsed.comments
    assert (c.by, c.quote, c.body) == (name, "Alpha", "review text")
    assert parsed.malformed == []
    head = out[out.index("<!--"):].split("\n")[0]
    assert 'quote="Alpha"' in head and f"at={AT}" in head       # the head is one line


@pytest.mark.parametrize("name", ODD_NAMES)
def test_a_line_break_or_other_whitespace_in_the_author_of_a_reply_is_a_reply_not_body_text(name):
    x = rdc.Comment(id="c1", by="Ada", at="2026-10-14T09:00", quote="Alpha", body="note")
    md = "Alpha" + rdc.format(x, False) + ".\n"
    out = rdc.reply(md, "c1", "reply text", name, AT, role="action")
    [c] = rdc.parse(read_back(out)).comments
    assert c.body == "note" and [(r.by, r.text, r.role) for r in c.replies] == [(name, "reply text", "action")]


def test_a_line_break_in_the_author_of_a_one_line_comment_round_trips():
    out, _ = rdc.add_comment("# Alpha beta\n", 0, 0, 5, "Alpha", "review text", "Eve\nMallory", AT)
    [c] = rdc.parse(out).comments
    assert (c.by, c.quote, c.body) == ("Eve\nMallory", "Alpha", "review text")
    assert out.count("\n") == 1


def test_a_plain_author_and_one_with_a_space_are_written_as_before():
    out, _ = rdc.add_comment("Alpha beta.\n", 0, 0, 5, "Alpha", "review text", "Eve Mallory", AT)
    assert 'by="Eve Mallory"' in out and "&#" not in out
    [c] = rdc.parse(out).comments
    assert (c.by, c.quote, c.body) == ("Eve Mallory", "Alpha", "review text")
    plain = rdc.reply(out, c.id, "ok", "Eve", AT)
    assert "\n@Eve " in plain and rdc.parse(plain).comments[0].replies[0].by == "Eve"
