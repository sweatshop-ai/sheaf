"""A Tell to an agent waits on the document, and the page says so (SPEC 9.8, 10.5): "Waiting for <agent>…",
then "<agent> has seen it…", with Cancel, across a reload and no orange dot."""
import time

import pytest

from helpers import browser_on, call
from pagehelp import DOC, toast, toasted, until
from sheafmd import comments as rdc
from sheafmd.hub.state import Tokens
from sheafmd.source import update_file

pytestmark = pytest.mark.page


def ask_agent(tab, site):
    """A comment c1 on the page, an agent (ada-chatgpt) as the target, and the thread open."""
    token = Tokens().add("ada-chatgpt", client="ChatGPT")
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "apples"), "apples", "Why?",
                                                     "Ada", "2026-10-14T10:00")[0])
    site.hub.docs.change(DOC, lambda e: {**e, "target": {"kind": "agent", "token": "ada-chatgpt",
                                                        "id": next(r.id for r in Tokens().list() if r.name == "ada-chatgpt")}})
    tab.open()
    tab.page.click(".rd-badge")
    tab.page.wait_for_selector("#rd-popover textarea")
    return token


def line(tab):
    return tab.page.locator("#rd-popover .rd-waits").all_inner_texts()


def test_tell_waits_then_is_seen_and_the_line_survives_a_reload(tab, site):
    token = ask_agent(tab, site)
    name = f"ChatGPT ({site.hub.person})"
    tab.page.wait_for_selector("#rd-popover textarea")
    tab.page.fill("#rd-popover textarea", "Please do.")
    tab.page.click("#rd-popover .rd-form button.rd-tell")
    until(lambda: line(tab) == [f"Waiting for {name}: it sees this the next time you talk to it."], what="the waiting line")
    assert tab.page.query_selector("#rd-popover .rd-dots") is None or "rd-waits" in tab.page.inner_html("#rd-popover")
    assert not tab.page.query_selector(".rd-badge.rd-working")
    call(browser_on(site.hub), "documents", token=token)
    until(lambda: line(tab) == [f"{name} has seen it; its action appears in this thread."], what="the seen line")
    tab.page.reload()
    tab.page.click(".rd-badge")
    until(lambda: line(tab) == [f"{name} has seen it; its action appears in this thread."], what="the line after a reload")


def test_cancel_ends_the_wait_and_says_the_agent_had_seen_it(tab, site):
    token = ask_agent(tab, site)
    tab.page.wait_for_selector("#rd-popover textarea")
    tab.page.fill("#rd-popover textarea", "Please do.")
    tab.page.click("#rd-popover .rd-form button.rd-tell")
    until(lambda: bool(line(tab)), what="the waiting line")
    call(browser_on(site.hub), "documents", token=token)
    until(lambda: "has seen it" in " ".join(line(tab)), what="the seen line")
    tab.page.hover("#rd-popover button[data-a=cancel-tell]")
    tab.page.click("#rd-popover button[data-a=cancel-tell]")
    until(lambda: line(tab) == [], what="the line to go")
    toasted(tab.page, "had already seen it; look at the document before you Tell again.")
    assert site.hub.waiting_tells.waits(DOC) == []


def test_an_action_reply_ends_the_wait(tab, site):
    token = ask_agent(tab, site)
    tab.page.wait_for_selector("#rd-popover textarea")
    tab.page.fill("#rd-popover textarea", "Please do.")
    tab.page.click("#rd-popover .rd-form button.rd-tell")
    until(lambda: bool(line(tab)), what="the waiting line")
    call(browser_on(site.hub), "reply", token=token, doc=DOC, id="c1", text="Done.", role="action")
    until(lambda: line(tab) == [], what="the line to go on the action reply")


def test_a_send_answered_after_the_agent_saw_it_does_not_take_the_seen_line_back(tab, site):
    # The answer to the send holds the Tells as the hub had them when it wrote it; the agent's seeing it is told by an
    # event that a slow answer can pass. "Seen" does not go back to "queued" (ticket 18).
    token = ask_agent(tab, site)
    name = f"ChatGPT ({site.hub.person})"

    def slow(route):
        got = route.fetch()
        tab.page.wait_for_timeout(1500)       # the page hears of the sight meanwhile
        route.fulfill(response=got)
    tab.page.route("**/_/comment", slow)
    tab.page.fill("#rd-popover textarea", "Please do.")
    tab.page.click("#rd-popover .rd-form button.rd-tell")
    until(lambda: line(tab) == [f"Waiting for {name}: it sees this the next time you talk to it."], what="the waiting line")
    call(browser_on(site.hub), "documents", token=token)
    until(lambda: line(tab) == [f"{name} has seen it; its action appears in this thread."], what="the seen line")
    tab.page.wait_for_timeout(2500)
    assert line(tab) == [f"{name} has seen it; its action appears in this thread."], line(tab)


def test_a_seen_tell_is_not_lent_to_the_queued_tell_of_another_agent_on_the_same_thread(tab, site):
    # One thread can wait for two agents (a target changed after the first Tell). The page keeps a Tell seen
    # (ticket 18) only for the agent that saw it; the other agent's queued Tell is said as queued, in a line of its own (23).
    token = ask_agent(tab, site)
    name = f"ChatGPT ({site.hub.person})"
    tab.page.fill("#rd-popover textarea", "Please do.")
    tab.page.click("#rd-popover .rd-form button.rd-tell")
    until(lambda: bool(line(tab)), what="the waiting line")
    call(browser_on(site.hub), "documents", token=token)
    until(lambda: line(tab) == [f"{name} has seen it; its action appears in this thread."], what="the seen line")
    Tokens().add("bea-claude", client="Claude")
    other = next(r for r in Tokens().list() if r.name == "bea-claude")
    thread = rdc.parse(site.file.read_text()).by_id("c1")
    # The snapshot that lists both Tells reaches the page before the event of the second one (two connections).
    emit, held = site.hub.waiting_tells._emit, []
    site.hub.waiting_tells._emit = lambda *a, **k: held.append((a, k)) if a[1] == "tell-queued" else emit(*a, **k)
    site.hub.waiting_tells.queue(DOC, "c1", other, site.hub.person, None, thread)
    site.hub.waiting_tells._emit = emit
    update_file(site.file, lambda t: rdc.reply(t, "c1", "A word from outside.", "Ada", "2026-10-14T11:00"))
    tab.page.wait_for_selector("#rd-popover :text('A word from outside.')")       # the snapshot that lists both Tells is in
    assert line(tab) == [f"{name} has seen it; its action appears in this thread.",
                          "Waiting for Claude (Ada): it sees this the next time you talk to it."], line(tab)
    for a, k in held:                       # the event comes after all: it says the same thing
        emit(*a, **k)
    # The stream keeps its order: an event that carries no Tells, said after the held one, is on the page once the
    # held one has been taken (a snapshot would decide the line by itself).
    emit(DOC, "tell-sent", {"id": "c1"})
    toasted(tab.page, "Sent to your")
    until(lambda: line(tab) == [f"{name} has seen it; its action appears in this thread.",
                                 "Waiting for Claude (Ada): it sees this the next time you talk to it."], what="the line after the event")


def test_an_event_of_one_agent_leaves_the_line_of_the_other_agent_on_the_same_thread(tab, site):
    # Ticket 23: the events name the agent, and each (thread, agent) pair has its own line.
    token = ask_agent(tab, site)
    name = f"ChatGPT ({site.hub.person})"
    other_name = f"Claude ({site.hub.person})"
    tab.page.fill("#rd-popover textarea", "Please do.")
    tab.page.click("#rd-popover .rd-form button.rd-tell")
    until(lambda: bool(line(tab)), what="the waiting line")
    Tokens().add("bea-claude", client="Claude")
    other = next(r for r in Tokens().list() if r.name == "bea-claude")
    thread = rdc.parse(site.file.read_text()).by_id("c1")
    site.hub.waiting_tells.queue(DOC, "c1", other, site.hub.person, None, thread)
    until(lambda: len(line(tab)) == 2, what="a line for each agent")
    call(browser_on(site.hub), "documents", token=token)                       # ChatGPT sees its Tell, Claude does not
    until(lambda: line(tab) == [f"{name} has seen it; its action appears in this thread.",
                                f"Waiting for {other_name}: it sees this the next time you talk to it."], what="only ChatGPT seen")
    call(browser_on(site.hub), "reply", doc=DOC, id="c1", text="Done.", role="action", token=token)
    until(lambda: line(tab) == [f"Waiting for {other_name}: it sees this the next time you talk to it."], what="ChatGPT's line gone")


def test_the_answer_to_a_send_does_not_erase_the_line_of_a_tell_queued_after_the_answer_was_written(tab, site):
    # Codex round 3 of PR 257 (b1): the answer lists the Tells as the hub had them when it wrote it; the event of another
    # agent's Tell queued meanwhile passes it, and the answer must not take that line away.
    ask_agent(tab, site)
    name, other_name = f"ChatGPT ({site.hub.person})", f"Claude ({site.hub.person})"
    Tokens().add("bea-claude", client="Claude")
    other = next(r for r in Tokens().list() if r.name == "bea-claude")
    thread = rdc.parse(site.file.read_text()).by_id("c1")

    def slow(route):
        got = route.fetch()                   # lists the Tell of ChatGPT only
        site.hub.waiting_tells.queue(DOC, "c1", other, site.hub.person, None, thread)
        tab.page.wait_for_timeout(800)        # the page hears of the second Tell meanwhile
        route.fulfill(response=got)
    tab.page.route("**/_/comment", slow)
    tab.page.fill("#rd-popover textarea", "Please do.")
    tab.page.click("#rd-popover .rd-form button.rd-tell")
    until(lambda: len(line(tab)) == 2, what="a line for each agent")
    tab.page.wait_for_timeout(2000)           # the answer has come by now
    assert line(tab) == [f"Waiting for {name}: it sees this the next time you talk to it.",
                         f"Waiting for {other_name}: it sees this the next time you talk to it."], line(tab)


def test_one_cancel_says_in_one_toast_which_agents_had_already_seen_the_tell(tab, site):
    # Codex round 3 of PR 257 (b2): a toast replaces the one before it, so each agent's end must not say its own.
    token = ask_agent(tab, site)
    name, other_name = f"ChatGPT ({site.hub.person})", f"Claude ({site.hub.person})"
    other_token = Tokens().add("bea-claude", client="Claude")
    other = next(r for r in Tokens().list() if r.name == "bea-claude")
    tab.page.fill("#rd-popover textarea", "Please do.")
    tab.page.click("#rd-popover .rd-form button.rd-tell")
    until(lambda: bool(line(tab)), what="the waiting line")
    site.hub.waiting_tells.queue(DOC, "c1", other, site.hub.person, None, rdc.parse(site.file.read_text()).by_id("c1"))
    until(lambda: len(line(tab)) == 2, what="a line for each agent")
    call(browser_on(site.hub), "documents", token=token)
    call(browser_on(site.hub), "documents", token=other_token)
    until(lambda: all("has seen it" in x for x in line(tab)) and len(line(tab)) == 2, what="both seen")
    tab.page.hover("#rd-popover button[data-a=cancel-tell]")
    tab.page.click("#rd-popover button[data-a=cancel-tell]")
    until(lambda: line(tab) == [], what="the lines to go")
    toasted(tab.page, f"{name} and {other_name} had already seen it; look at the document before you Tell again.")


def test_the_timer_of_an_earlier_cancel_does_not_take_the_places_of_a_later_cancel(tab, site):
    # Codex round 4 of PR 257 (P1): a Cancel keeps the places it took off for 5 s, for the events that follow its answer.
    # The timer of the first must not delete what the second kept, or the second says nothing of a Tell already seen.
    token = ask_agent(tab, site)
    name = f"ChatGPT ({site.hub.person})"
    tab.page.fill("#rd-popover textarea", "Please do.")
    tab.page.click("#rd-popover .rd-form button.rd-tell")
    until(lambda: bool(line(tab)), what="the waiting line")
    first = time.monotonic()
    tab.page.hover("#rd-popover button[data-a=cancel-tell]")
    tab.page.click("#rd-popover button[data-a=cancel-tell]")                  # a Tell nobody had seen: its timer starts
    until(lambda: line(tab) == [], what="the first line to go")
    tab.page.fill("#rd-popover textarea", "Please do, again.")
    tab.page.click("#rd-popover .rd-form button.rd-tell")
    until(lambda: bool(line(tab)), what="the second waiting line")
    call(browser_on(site.hub), "documents", token=token)
    until(lambda: line(tab) == [f"{name} has seen it; its action appears in this thread."], what="the seen line")
    emit, held = site.hub.waiting_tells._emit, []
    site.hub.waiting_tells._emit = lambda *a, **k: held.append((a, k)) if a[1] == "tell-cancelled" else emit(*a, **k)
    tab.page.hover("#rd-popover button[data-a=cancel-tell]")
    tab.page.click("#rd-popover button[data-a=cancel-tell]")                  # the answer comes, the event is held
    until(lambda: line(tab) == [] and len(held) == 1, what="the second answer")
    assert time.monotonic() - first < 5, "the test came too late: the first timer has fired already"
    tab.page.wait_for_timeout(max(0, int((first + 5.7 - time.monotonic()) * 1000)))      # the first timer fires meanwhile
    site.hub.waiting_tells._emit = emit
    for a, k in held:
        emit(*a, **k)
    try:
        toasted(tab.page, f"{name} had already seen it; look at the document before you Tell again.")
    except AssertionError as e:
        raise AssertionError(f"{e}; toast={toast(tab.page)!r} held={[x[0][1:3] for x in held]!r} lines={line(tab)!r}") from None


def test_a_snapshot_that_is_not_the_answer_to_a_send_does_not_keep_a_seen_line(tab, site):
    # Only the answer to a send can pass the event of the sight (ticket 18). Any other snapshot (a reconnect, a change
    # of the file) is the hub's state as it is: a new Tell of the same agent that the page never heard of is queued.
    token = ask_agent(tab, site)
    name = f"ChatGPT ({site.hub.person})"
    tab.page.fill("#rd-popover textarea", "Please do.")
    tab.page.click("#rd-popover .rd-form button.rd-tell")
    until(lambda: bool(line(tab)), what="the waiting line")
    call(browser_on(site.hub), "documents", token=token)
    until(lambda: line(tab) == [f"{name} has seen it; its action appears in this thread."], what="the seen line")
    thread = rdc.parse(site.file.read_text()).by_id("c1")
    # The page misses the end of the first Tell and the start of the second (a dropped stream).
    emit = site.hub.waiting_tells._emit
    site.hub.waiting_tells._emit = lambda *a, **k: None
    site.hub.waiting_tells.end(DOC, "c1", "cancelled")
    site.hub.waiting_tells.queue(DOC, "c1", next(r for r in Tokens().list() if r.name == "ada-chatgpt"), site.hub.person, None, thread)
    site.hub.waiting_tells._emit = emit
    update_file(site.file, lambda t: rdc.reply(t, "c1", "A word from outside.", "Ada", "2026-10-14T11:00"))
    tab.page.wait_for_selector("#rd-popover :text('A word from outside.')")
    until(lambda: line(tab) == [f"Waiting for {name}: it sees this the next time you talk to it."], what="the queued line")
