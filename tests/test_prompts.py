"""What the hub says to a session: the Ask prompt, the Tell message and the Cancel message
(SPEC 11.2, 11.3). The wording is the contract, so these tests hold it whole."""
import sheafmd.comments as rdc
from sheafmd.agents import prompts
from sheafmd.links import RULE

MD = "# Title\n\nThe price is high.\n"


def thread():
    md, cid = rdc.add_comment(MD, *rdc.find_quote(MD, "price"), "price", "Is this right?", "Ada",
                             "2026-10-14T10:00")
    md = rdc.reply(md, cid, "I think so.", "Bob", "2026-10-14T10:05")
    md = rdc.reply(md, cid, "Checked.", "Claude", "2026-10-14T10:09", role="action")
    return rdc.parse(md).by_id(cid)


def test_the_ask_prompt_is_the_one_of_the_spec():
    c = thread()
    assert prompts.ask("/w/plan.md", c, links=True) == (
        'A comment was left on the document /w/plan.md, at line 3, on the passage "price". '
        "The thread so far:\n\n"
        "Ada (2026-10-14T10:00): Is this right?\n"
        "Bob (2026-10-14T10:05): I think so.\n"
        "Claude (2026-10-14T10:09): Checked.\n\n"
        "Answer the last message in the thread, the way you would answer it here in the "
        "conversation: short, in the language it was written in, and only from what you know or "
        f"can read. Do not edit any file. {RULE} Your answer is written into the document as "
        "your reply, as it is, so give only the answer: no preamble, no sign-off.")


def test_the_link_rule_is_left_out_of_the_ask_prompt_when_the_root_turns_links_off():
    p = prompts.ask("/w/plan.md", thread(), links=False)
    assert RULE not in p
    assert "Do not edit any file. Your answer is written into the document" in p


def test_the_tell_message_names_the_page_the_person_and_both_ways_to_answer():
    c = thread()
    assert prompts.tell("work/plan.md", "/w/plan.md", "Grace", c, links=True) == (
        "Tell from sheaf, on the page of work/plan.md (/w/plan.md).\n"
        f"Grace pressed Tell on comment {c.id} by Ada, at line 3, on the passage \"price\": "
        "act on it here, in this conversation.\n\n"
        "Thread:\n"
        "Ada (2026-10-14T10:00): Is this right?\n"
        "Bob (2026-10-14T10:05): I think so.\n"
        "Claude (2026-10-14T10:09): Checked.\n\n"
        f"{RULE}\n\n"
        "When you are done, answer in the thread so the page shows it, with the role action:\n"
        f'- with the sheaf MCP tool: reply(doc="work/plan.md", id="{c.id}", '
        'text="<what you did>", role="action")\n'
        f'- or in a shell: sheaf reply /w/plan.md {c.id} "<what you did>" --role action')


def test_the_link_rule_is_left_out_of_the_tell_message_with_its_blank_line():
    m = prompts.tell("work/plan.md", "/w/plan.md", "Grace", thread(), links=False)
    assert RULE not in m
    assert "Checked.\n\nWhen you are done" in m


def test_the_cancel_message_says_stop_undo_nothing_and_do_not_reply():
    assert prompts.cancel("work/plan.md", "Grace", "c3") == (
        "Tell from sheaf, on the page of work/plan.md: Grace pressed Cancel on comment c3. "
        "Stop working on it, undo nothing on your own, and do not reply in the thread. If you "
        "already changed something for it, say what in this conversation.")


def test_a_legacy_action_reply_is_shown_under_its_plain_author_name():
    md, cid = rdc.add_comment(MD, *rdc.find_quote(MD, "price"), "price", "Q", "Ada",
                             "2026-10-14T10:00")
    md = rdc.reply(md, cid, "done", "Claude (action)", "2026-10-14T10:01")
    p = prompts.ask("/w/plan.md", rdc.parse(md).by_id(cid), links=True)
    assert "Claude (2026-10-14T10:01): done" in p
