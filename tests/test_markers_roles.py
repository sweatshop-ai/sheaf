"""Both comment markers and the reply roles (SPEC 5.2, 5.3; D1, D20).

sheaf writes `sheaf-comment` and reads `sheaf-comment` and `rd-comment` as the same
thing. A reply records its role apart from its author. Legacy replies keep their
bytes whatever sheaf does to the comment around them.
"""
import subprocess

import pypandoc
import pytest

from sheafmd import comments as rdc

MARKERS = ["sheaf-comment", "rd-comment"]
HEAD = 'by="Ada" at=2026-09-19T14:02 status=open quote="The gap is 52%"'


def doc(marker, *replies):
    """One paragraph with one comment on it, replies given as written."""
    lines = "".join(f"{r}\n" for r in replies)
    return f"The gap is **52%**<!-- {marker} id=c1 {HEAD}\nSource?\n{lines}--> and it matters.\n"


def thread(md):
    return rdc.parse(md).comments[0]


# ─────────────────────────────────────────────────────────────── markers ──

@pytest.mark.parametrize("marker", MARKERS)
def test_both_markers_parse_as_the_same_comment(marker):
    c = thread(doc(marker, "@Claude 2026-09-19T14:30: Re-derived."))
    assert (c.id, c.by, c.at, c.status, c.quote, c.body) == (
        "c1", "Ada", "2026-09-19T14:02", "open", "The gap is 52%", "Source?")
    assert c.marker == marker
    assert [(r.by, r.text) for r in c.replies] == [("Claude", "Re-derived.")]


@pytest.mark.parametrize("text,matches", [
    ("<!-- sheaf-comment id=c1", True),
    ("<!-- rd-comment id=c1", True),
    ("<!--rd-comment id=c1", True),
    ("<!--   sheaf-comment id=c1", True),
    ("<!-- sheaf-commentary id=c1", False),
    ("<!-- sheaf-comments id=c1", False),
    ("<!-- comment id=c1", False),
    ("<!-- @comment{note} -->", False),
    ("<!-- toc -->", False),
])
def test_the_one_marker_pattern(text, matches):
    assert bool(rdc.COMMENT_RE.match(text)) is matches
    # The same constant is what every other module builds its patterns from.
    import re
    assert bool(re.match(rf"<!--\s*{rdc.MARKER}\b", text)) is matches


def test_new_comments_are_written_with_the_new_marker():
    assert rdc.Comment(id="c1").marker == "sheaf-comment"
    md, cid = rdc.add_comment("Par one.\n", 0, 0, 3, "Par", "first", "Ada", "2026-10-13T10:00")
    assert cid == "c1"
    assert "<!-- sheaf-comment id=c1 " in md and "rd-comment" not in md


def test_a_comment_keeps_the_marker_it_was_read_with_through_every_rewrite():
    md = doc("rd-comment", "@Claude 2026-09-19T14:30: Re-derived.")
    for new in (rdc.reply(md, "c1", "Thanks", "Ada", "2026-09-20T09:00"),
                rdc.set_status(md, "c1", "resolved"),
                rdc.edit_body(md, "c1", "Source, please?")):
        assert "<!-- rd-comment id=c1 " in new and "sheaf-comment" not in new
    md = doc("sheaf-comment")
    new = rdc.reply(md, "c1", "Thanks", "Ada", "2026-09-20T09:00")
    assert "<!-- sheaf-comment id=c1 " in new and "rd-comment" not in new


def test_both_markers_live_side_by_side_and_ids_do_not_collide():
    md = ("One.<!-- rd-comment id=c3 by=\"Ada\" at=2026-09-19T14:02 status=open quote=\"One\" -->\n\n"
          "Two.<!-- sheaf-comment id=c4 by=\"Ada\" at=2026-09-19T14:02 status=open quote=\"Two\" -->\n\n"
          "Three.\n")
    p = rdc.parse(md)
    assert [(c.id, c.marker) for c in p.comments] == [("c3", "rd-comment"), ("c4", "sheaf-comment")]
    assert rdc.next_id(p) == "c5"
    new, cid = rdc.add_comment(md, *rdc.find_quote(md, "Three"), "Three", "third", "Ada", "2026-10-13T10:00")
    assert cid == "c5"
    assert [c.marker for c in rdc.parse(new).comments] == ["rd-comment", "sheaf-comment", "sheaf-comment"]


def test_next_id_counts_a_malformed_comment_of_either_marker():
    for marker in MARKERS:
        md = f"Text<!-- {marker} id=c9 status=wrong -->\n"
        p = rdc.parse(md)
        assert p.comments == [] and [m.reason for m in p.malformed] == ["unknown status 'wrong'"]
        assert rdc.next_id(p) == "c10"


def test_a_duplicate_id_is_malformed_across_markers():
    md = ('A<!-- rd-comment id=c1 by="x" at=2026-01-01T10:00 status=open quote="A" -->\n\n'
          'B<!-- sheaf-comment id=c1 by="x" at=2026-01-01T10:00 status=open quote="B" -->\n')
    p = rdc.parse(md)
    assert [c.marker for c in p.comments] == ["rd-comment"]
    assert [m.reason for m in p.malformed] == ["duplicate id c1"]


@pytest.mark.parametrize("marker", MARKERS)
def test_a_comment_that_never_closes_is_malformed(marker):
    p = rdc.parse(f"Text<!-- {marker} id=c1 by=\"Ada\"\nno end\n")
    assert p.comments == [] and [m.reason for m in p.malformed] == ["never closed"]


@pytest.mark.parametrize("marker", MARKERS)
def test_an_example_in_code_is_not_a_comment(marker):
    example = f"<!-- {marker} id=c1 by=\"Ada\" at=2026-01-01T10:00 status=open quote=\"x\" -->"
    md = f"Written like this: `{example}` in prose.\n\n```\n{example}\n```\n"
    p = rdc.parse(md)
    assert p.comments == [] and p.malformed == []


def test_other_html_comments_are_not_sheafs_to_read():
    md = "Text<!-- @comment{note for later} -->\n\n<!-- toc -->\n\nMore<!-- sheaf-commentary id=c1 -->\n"
    p = rdc.parse(md)
    assert p.comments == [] and p.malformed == []


# ────────────────────────────────────────────────────────── reply grammar ──

@pytest.mark.parametrize("line,by,role,text", [
    ("@Claude 2026-09-19T14:30 answer: Re-derived.", "Claude", "answer", "Re-derived."),
    ("@Claude 2026-09-19T14:30 action: Fixed it.", "Claude", "action", "Fixed it."),
    ("@Claude 2026-09-19T14:30: No role.", "Claude", None, "No role."),
    ('@"Claude (action)" 2026-09-19T14:30: Legacy.', "Claude (action)", None, "Legacy."),
    ('@"Ada Lovelace" 2026-09-19T14:30 action: Quoted name.', "Ada Lovelace", "action", "Quoted name."),
    ("@Ada 2026-09-19T14:30: answer: this is text, not a role", "Ada", None,
     "answer: this is text, not a role"),
])
def test_a_reply_line_parses_into_author_role_and_text(line, by, role, text):
    [r] = thread(doc("sheaf-comment", line)).replies
    assert (r.by, r.role, r.text) == (by, role, text)


def test_a_word_that_is_not_a_role_does_not_make_a_reply():
    c = thread(doc("sheaf-comment", "@Ada 2026-09-19T14:30 maybe: not a reply"))
    assert c.replies == []
    assert c.body == "Source?\n@Ada 2026-09-19T14:30 maybe: not a reply"


def test_a_multiline_reply_keeps_its_role_and_its_continuation_lines():
    md = doc("sheaf-comment", "@Claude 2026-09-19T14:30 action: First line.", "Second line.")
    [r] = thread(md).replies
    assert (r.role, r.text) == ("action", "First line.\nSecond line.")
    assert rdc.set_status(md, "c1", "resolved").count("@Claude 2026-09-19T14:30 action: First line.\n"
                                                       "Second line.\n") == 1


# ─────────────────────────────────────────────────────────── the role table ──
# SPEC 5.3: what the page and the hub show, derived from how a reply is written.

@pytest.mark.parametrize("marker,line,display,effective", [
    ("sheaf-comment", "@Claude 2026-09-19T14:30 action: x", "Claude", "action"),
    ("rd-comment", "@Claude 2026-09-19T14:30 action: x", "Claude", "action"),
    ("sheaf-comment", '@"Claude (action)" 2026-09-19T14:30: x', "Claude", "action"),
    ("rd-comment", '@"Claude (action)" 2026-09-19T14:30: x', "Claude", "action"),
    ("rd-comment", "@Claude 2026-09-19T14:30: x", "Claude", "answer"),
    ("sheaf-comment", "@Claude 2026-09-19T14:30: x", "Claude", None),
    ("sheaf-comment", "@Ada 2026-09-19T14:30: x", "Ada", None),
    ("rd-comment", "@Ada 2026-09-19T14:30: x", "Ada", None),
    ("sheaf-comment", "@Codex 2026-09-19T14:30 answer: x", "Codex", "answer"),
    ("rd-comment", "@Codex 2026-09-19T14:30: x", "Codex", None),
])
def test_display_and_effective_role(marker, line, display, effective):
    c = thread(doc(marker, line))
    [r] = c.replies
    assert (c.display(r), c.effective_role(r)) == (display, effective)
    # What the page, /_/doc and the door carry.
    [shown] = c.as_dict()["replies"]
    assert shown == {"by": r.by, "display": display, "role": effective, "at": r.at, "text": "x"}


def test_a_written_role_beats_the_legacy_rule():
    c = thread(doc("rd-comment", "@Claude 2026-09-19T14:30 action: x"))
    assert c.effective_role(c.replies[0]) == "action"


def test_a_tell_is_answered_only_by_an_action_reply():
    c = thread(doc("rd-comment",
                   "@Claude 2026-09-19T14:30: legacy ask answer",
                   '@"Claude (action)" 2026-09-19T14:31: legacy action',
                   "@Claude 2026-09-19T14:32 action: new action",
                   "@Ada 2026-09-19T14:33: a person"))
    assert rdc.action_replies(c) == 2
    c = thread(doc("sheaf-comment", "@Claude 2026-09-19T14:30: no role", "@Claude 2026-09-19T14:31 answer: x"))
    assert rdc.action_replies(c) == 0


# ─────────────────────────────────────────── legacy bytes survive a rewrite ──

LEGACY = ["@Claude 2026-09-19T14:30: Re-derived, 52% holds.",
          '@"Claude (action)" 2026-09-19T14:40: Fixed in the table.',
          "@Ada 2026-09-19T15:00: Thanks."]


@pytest.mark.parametrize("change", [
    lambda md: rdc.set_status(md, "c1", "resolved"),
    lambda md: rdc.reply(md, "c1", "More.", "Ada", "2026-09-20T09:00"),
    lambda md: rdc.reply(md, "c1", "Done.", "Claude", "2026-09-20T09:00", resolve=True, role="action"),
    lambda md: rdc.edit_body(md, "c1", "Source, please?"),
])
def test_rewriting_a_legacy_comment_leaves_its_old_reply_bytes_identical(change):
    md = doc("rd-comment", *LEGACY)
    new = change(md)
    assert new != md
    for line in LEGACY:
        assert line + "\n" in new
    assert "<!-- rd-comment id=c1 " in new


def test_a_new_reply_is_written_with_its_role_between_the_time_and_the_colon():
    md = doc("sheaf-comment")
    new = rdc.reply(md, "c1", "Re-derived.", "Claude", "2026-09-20T09:00", role="answer")
    assert "\n@Claude 2026-09-20T09:00 answer: Re-derived.\n" in new
    new = rdc.reply(md, "c1", "Fixed.", "Claude", "2026-09-20T09:00", role="action")
    assert "\n@Claude 2026-09-20T09:00 action: Fixed.\n" in new
    new = rdc.reply(md, "c1", "Thanks.", "Ada", "2026-09-20T09:00")
    assert "\n@Ada 2026-09-20T09:00: Thanks.\n" in new
    c = thread(new)
    assert [(r.by, r.role) for r in c.replies] == [("Ada", None)]


def test_a_quoted_author_with_a_role_round_trips():
    md = doc("sheaf-comment")
    new = rdc.reply(md, "c1", "Hello.", "Ada Lovelace", "2026-09-20T09:00", role="answer")
    assert '\n@"Ada Lovelace" 2026-09-20T09:00 answer: Hello.\n' in new
    assert thread(new).replies[0].by == "Ada Lovelace"


def test_an_unknown_role_is_refused_and_nothing_is_written():
    with pytest.raises(rdc.AnchorError, match="role"):
        rdc.reply(doc("sheaf-comment"), "c1", "x", "Claude", "2026-09-20T09:00", role="reviewer")


def test_format_then_parse_is_the_identity_for_every_marker_and_role():
    for marker in MARKERS:
        for role in (None, "answer", "action"):
            c = rdc.Comment(id="c2", by="Ada", at="2026-09-19T14:02", quote="q", body="Body line.",
                            marker=marker,
                            replies=[rdc.Reply("Claude", "2026-09-19T14:30", "one\ntwo", role)])
            for one_line in (False, True):
                got = rdc.parse(rdc.format(c, one_line)).comments[0]
                assert (got.marker, got.body) == (marker, "Body line.")
                assert [(r.by, r.at, r.role, r.text) for r in got.replies] == [
                    ("Claude", "2026-09-19T14:30", role, "one\ntwo")]


# ───────────────────────────────────────────────────── the bundled pandoc ──

def test_the_selection_anchor_runs_the_bundled_pandoc(monkeypatch):
    seen = []
    real = subprocess.run

    def spy(cmd, *a, **kw):
        seen.append(cmd[0])
        return real(cmd, *a, **kw)

    monkeypatch.setattr(subprocess, "run", spy)
    rdc._sourcepos_html("Some text.\n")
    assert seen == [pypandoc.get_pandoc_path()]


# pandoc 3.8 changed what +sourcepos writes. Before: a <div data-wrapper> around each
# block, one data-pos on each span. After: no wrapper, and each span carries data-pos
# twice, its own range first and its block's second. The anchoring must give the same
# answer for both, or a pandoc change would move comments to the wrong place.
LIST = "- one\n- two items\n"
BEFORE_3_8 = ('<div data-wrapper="1" data-pos="1:1-3:1"><ul>\n'
              '<li><div data-wrapper="1" data-pos="1:3-2:1"><span data-wrapper="1" data-pos="1:3-1:6">one</span></div></li>\n'
              '<li><div data-wrapper="1" data-pos="2:3-3:1"><span data-wrapper="1" data-pos="2:3-2:6">two</span>'
              '<span data-wrapper="1" data-pos="2:6-2:7"> </span><span data-wrapper="1" data-pos="2:7-2:12">items</span>'
              '</div></li>\n</ul></div>\n')
FROM_3_8 = ('<ul data-pos="1:1-3:1">\n'
            '<li><span data-wrapper="1" data-pos="1:3-1:6" data-pos="1:3-2:1">one</span></li>\n'
            '<li><span data-wrapper="1" data-pos="2:3-2:6" data-pos="2:3-3:1">two</span>'
            '<span data-wrapper="1" data-pos="2:6-2:7" data-pos="2:3-3:1"> </span>'
            '<span data-wrapper="1" data-pos="2:7-2:12" data-pos="2:3-3:1">items</span></li>\n</ul>\n')


@pytest.mark.parametrize("shape", [BEFORE_3_8, FROM_3_8], ids=["pandoc<3.8", "pandoc>=3.8"])
def test_anchoring_reads_the_spans_own_position_in_either_pandoc_shape(monkeypatch, shape):
    monkeypatch.setattr(rdc, "_sourcepos_html", lambda block: shape)
    # A selection ending after "two" in the second item: the comment goes right
    # after those three characters, not at the end of the item.
    assert rdc.anchor_point(LIST, 3, 6, "two") == LIST.index("two") + 3
    assert rdc.anchor_point(LIST, 6, 11, "items") == LIST.index("items") + 5
