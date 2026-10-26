"""Reply, resolve, edit and delete, and writes from several processes at once."""

import pytest

from sheafmd import comments as rdc

DOC = ("Para one here.\n\n| A | B |\n|---|---|\n| cell | x |\n")


def with_two():
    md, a = rdc.add_comment(DOC, 0, 0, 3, "Par", "first", "Ada", "2026-09-22T10:00")
    md, b = rdc.add_comment(md, 1, *rdc.find_quote(md, "cell")[1:], "cell", "second",
                            "Ada", "2026-09-22T10:01")
    return md, a, b


def test_reply_and_resolve_keep_the_comment_where_it_was():
    md, a, b = with_two()
    md = rdc.reply(md, b, "Done | fixed", by="Claude", at="2026-09-22T11:00", resolve=True)
    c = rdc.parse(md).by_id(b)
    assert c.status == "resolved"
    assert [(r.by, r.text) for r in c.replies] == [("Claude", "Done | fixed")]
    assert "| cell<!-- sheaf-comment id=c2" in md and "\n" not in md[c.start:c.end]
    md = rdc.set_status(md, b, "open")
    assert rdc.parse(md).by_id(b).status == "open"


def test_edit_and_delete():
    md, a, b = with_two()
    md = rdc.edit_body(md, a, "rewritten")
    assert rdc.parse(md).by_id(a).body == "rewritten"
    md = rdc.delete(md, a)
    assert rdc.parse(md).by_id(a) is None
    assert md.startswith("Para one here.\n")


def test_unknown_id_is_an_error():
    with pytest.raises(rdc.AnchorError, match="no comment c9"):
        rdc.reply(DOC, "c9", "x", by="A", at="2026-09-22T10:00")


def test_apply_op_is_the_one_switch_over_the_four_changes():
    md, a, b = with_two()
    at = "2026-09-22T11:00"
    out = rdc.apply_op(md, "reply", {"id": b, "body": "Done", "resolve": True}, "Claude", at, "action")
    c = rdc.parse(out).by_id(b)
    assert c.status == "resolved"
    assert [(r.by, r.text, r.role) for r in c.replies] == [("Claude", "Done", "action")]
    assert out == rdc.reply(md, b, "Done", "Claude", at, True, "action")

    out = rdc.apply_op(out, "status", {"id": b, "status": "open"})
    assert rdc.parse(out).by_id(b).status == "open"
    out = rdc.apply_op(out, "edit", {"id": a, "body": "rewritten"})
    assert rdc.parse(out).by_id(a).body == "rewritten"
    out = rdc.apply_op(out, "delete", {"id": a})
    assert rdc.parse(out).by_id(a) is None


def test_apply_op_refuses_an_operation_it_does_not_know():
    md, a, b = with_two()
    with pytest.raises(rdc.AnchorError, match="unknown operation 'archive'"):
        rdc.apply_op(md, "archive", {"id": a})
