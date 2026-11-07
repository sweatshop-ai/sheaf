"""Replies Ask left in files keep their role `answer` (SPEC 11.2, D25): nothing is migrated, and the hub's own
rewrites of the file around them (a sibling comment resolved, edited, replied to, deleted) leave them as they were."""
import pytest

import sheafmd.comments as rdc
from helpers import comment
from sheafmd.source import md_hash, update_file

DOC = "work/plan.md"
ANSWER = "Because pears ripen late."


def thread_line(text):
    """The line of the answer, as written in the file."""
    return next(ln for ln in text.splitlines() if ANSWER in ln)


@pytest.fixture(params=["sheaf-comment with a written role", "rd-comment with a written role",
                        "rd-comment, a reply by Claude with no role"])
def answered(request, plan):
    """The plan with c1 on the second paragraph holding an Ask's answer, then c2 on the first paragraph."""
    comment(plan)
    legacy = request.param.startswith("rd-comment")
    role = None if "no role" in request.param else "answer"
    update_file(plan, lambda t: rdc.reply(t, "c1", ANSWER, "Claude", "2026-10-14T10:01", role=role))
    if legacy:
        update_file(plan, lambda t: t.replace("sheaf-comment", "rd-comment", 1))
    update_file(plan, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "apples"), "apples", "Why apples?",
                                                "Ada", "2026-10-14T10:02")[0])
    return plan, thread_line(plan.read_text(encoding="utf-8"))


def role_of_c1(plan):
    c = rdc.parse(plan.read_text(encoding="utf-8")).by_id("c1")
    return c.effective_role(c.replies[0])


def test_the_answer_reads_as_an_answer_before_the_hub_touches_the_file(browser, answered):
    plan, _ = answered
    assert role_of_c1(plan) == "answer"
    meta = browser.get("/work/plan.md").text
    assert '"role": "answer"' in meta or '"role":"answer"' in meta


@pytest.mark.parametrize("sibling_op, fields", [
    ("status", {"status": "resolved"}),
    ("edit", {"body": "Why apples, really?"}),
    ("reply", {"body": "Thanks."}),
    ("delete", {}),
])
def test_a_hub_rewrite_for_a_sibling_comment_leaves_the_answer_as_written(browser, answered, sibling_op, fields):
    plan, line = answered
    r = browser.post("/_/comment", {"doc": DOC, "op": sibling_op, "id": "c2",
                                    "hash": md_hash(plan.read_text(encoding="utf-8")), **fields})
    assert r.status == 200, r.text
    after = plan.read_text(encoding="utf-8")
    assert thread_line(after) == line               # the bytes of the answer, untouched
    assert role_of_c1(plan) == "answer"
    shown = {x["id"]: x for x in r.json()["comments"]}
    assert shown["c1"]["replies"][0]["role"] == "answer"


def test_a_hub_rewrite_of_the_thread_itself_keeps_the_answer_a_reply_was_added_after(browser, answered):
    plan, line = answered
    r = browser.post("/_/comment", {"doc": DOC, "op": "reply", "id": "c1", "body": "And later?",
                                    "hash": md_hash(plan.read_text(encoding="utf-8"))})
    assert r.status == 200, r.text
    assert thread_line(plan.read_text(encoding="utf-8")) == line
    assert role_of_c1(plan) == "answer"
