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
    tab.page.wait_for_selector("#rd-popover button[data-a=reply]")
    return token


def line(tab):
    return tab.page.locator("#rd-popover .rd-waits").all_inner_texts()


def test_tell_waits_then_is_seen_and_the_line_survives_a_reload(tab, site):
    token = ask_agent(tab, site)
    name = f"ChatGPT ({site.hub.person})"
    tab.page.click("#rd-popover button[data-a=tell]")
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
    tab.page.click("#rd-popover button[data-a=tell]")
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
    tab.page.click("#rd-popover button[data-a=tell]")
    until(lambda: bool(line(tab)), what="the waiting line")
    call(browser_on(site.hub), "reply", token=token, doc=DOC, id="c1", text="Done.", role="action")
    until(lambda: line(tab) == [], what="the line to go on the action reply")
