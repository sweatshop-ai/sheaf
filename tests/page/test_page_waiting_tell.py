"""A Tell to an agent waits on the document, and the page says so (SPEC 9.8, 10.5): "Waiting for <agent>…",
then "<agent> has seen it…", with Cancel, across a reload and no orange dot."""
import pytest

from helpers import browser_on, call
from pagehelp import DOC, toasted, until
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
    # (ticket 18) only for the agent that saw it; the other agent's queued Tell is said as queued.
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
    assert line(tab) == ["Waiting for Claude (Ada): it sees this the next time you talk to it."], line(tab)
    for a, k in held:                       # the event comes after all: it says the same thing
        emit(*a, **k)
    until(lambda: line(tab) == ["Waiting for Claude (Ada): it sees this the next time you talk to it."], what="the line after the event")
