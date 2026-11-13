"""What the hub says to a session: the Tell message and the Cancel message
(SPEC 11.2, 11.3). The wording is the contract, so these tests hold it whole."""
from pathlib import Path

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


def test_ask_is_retired_there_is_no_ask_prompt_and_no_drop_of_kind_ask():
    assert not hasattr(prompts, "ask")
    drop = {"kind": "ask", "member": "Grace", "sheaf": "work/plan.md", "text": "Is this right?",
            "thread": "c1"}
    assert prompts.dropped(drop) is None
    assert prompts.dropped({**drop, "kind": "tell"}) is not None


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
        f'- or in a shell: sheaf reply /w/plan.md {c.id} "<what you did>" --role action\n\n'
        f"{prompts.READABLE}")


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
    p = prompts.tell("work/plan.md", "/w/plan.md", "Grace", rdc.parse(md).by_id(cid), links=True)
    assert "Claude (2026-10-14T10:01): done" in p


SPEC = (Path(__file__).resolve().parent.parent / "SPEC.md").read_text()


def test_the_message_to_an_agent_is_the_one_quoted_in_the_spec():
    """SPEC 11.3 quotes `prompts.tell_agent`; the words an agent acts on are the SPEC's, placeholders filled."""
    c = thread()
    quoted = SPEC.split("Message to an agent (`prompts.tell_agent`)", 1)[1].split("It names no file path", 1)[0]
    block = "\n".join(l[2:] if l.startswith("> ") else l[1:] for l in quoted.splitlines() if l.startswith(">"))
    want = (block.replace("{author} ({at}): {body}", "Ada (2026-10-14T10:00): Is this right?")
            .replace("{each reply the same way}", "Bob (2026-10-14T10:05): I think so.\n"
                     "Claude (2026-10-14T10:09): Checked.")
            .replace("{root}/{path}", "work/plan.md").replace("{me}", "Grace").replace("{id}", c.id)
            .replace("{author}", "Ada").replace("{quote}", "price").replace("{RULE}", RULE))
    assert prompts.tell_agent("work/plan.md", "Grace", c, links=True) == want
