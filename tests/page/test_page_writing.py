"""Never interrupt writing (SPEC 10.4, D23): while a comment form is open the page does not reload,
the reload that is needed runs when the form is sent or cancelled, and what was typed is never lost."""
import json
import re
import threading
import time
from types import SimpleNamespace

import pytest

from agent_fakes import FakeClaude
from helpers import comment, writes_from_outside
from pagehelp import (DOC, P1, P2, T0, at, comment_draft_key, comment_on, gone, key, mark, reload_on_clock, reloaded,
                      select, toast, toasted, type_at_end, until)
from sheafmd import comments as rdc
from sheafmd.hub import live as hub_live
from sheafmd.hub import state as hub_state
from sheafmd.source import md_hash, update_file

pytestmark = pytest.mark.page



@pytest.fixture
def thread(tab):
    """A page with one comment on 'apples', its thread open."""
    tab.open()
    comment_on(tab, at(P1, "apples"), at(P1, "apples", None), "Why apples?")
    tab.page.wait_for_selector("#rd-popover .rd-msg")
    tab.page.reload()
    tab.page.wait_for_selector("#rd-menu-btn", state="attached")
    tab.page.click(".rd-badge")
    tab.page.wait_for_selector("#rd-popover button[data-a=reply]")
    return tab


def open_reply(tab, text):
    tab.page.click("#rd-popover button[data-a=reply]")
    tab.page.fill("#rd-popover textarea", text)


def test_a_changed_event_while_a_reply_form_holds_text_leaves_the_form_alone(thread):
    open_reply(thread, "my reply text")
    mark(thread.page)
    f = thread.site.file
    f.write_text(f.read_text() + "\nA new paragraph from outside.\n", encoding="utf-8")
    thread.page.wait_for_selector("#rd-popover .rd-hold")
    assert thread.page.input_value("#rd-popover textarea") == "my reply text"
    thread.page.wait_for_timeout(1500)
    assert thread.page.evaluate("window.__same_load") is True, "the page reloaded under the form"
    thread.page.click("#rd-popover button[data-f=ok]")
    reloaded(thread.page)
    md = f.read_text()
    assert "A new paragraph from outside." in md
    (c,) = rdc.parse(md).comments
    assert [r.text for r in c.replies] == ["my reply text"]
    thread.page.wait_for_selector("#rd-popover .rd-msg")
    assert "my reply text" in thread.page.inner_text("#rd-popover")
    toasted(thread.page, "text changed while you wrote")


def test_cancelling_the_form_runs_the_reload_that_waited(thread):
    open_reply(thread, "never mind")
    mark(thread.page)
    f = thread.site.file
    f.write_text(f.read_text() + "\nAnother paragraph.\n", encoding="utf-8")
    thread.page.wait_for_selector("#rd-popover .rd-hold")
    thread.page.click("#rd-popover button[data-f=no]")
    reloaded(thread.page)
    thread.page.wait_for_selector("#rd-popover .rd-msg")
    assert rdc.parse(f.read_text()).comments[0].replies == []


def test_a_reply_that_arrives_from_outside_updates_the_thread_and_leaves_the_form_alone(thread):
    open_reply(thread, "half a sentence")
    mark(thread.page)
    f = thread.site.file
    c = rdc.parse(f.read_text()).comments[0]
    f.write_text(rdc.reply(f.read_text(), c.id, "From the agent.", "Claude", "2026-10-14T10:00:00Z"),
                 encoding="utf-8")
    until(lambda: "From the agent." in thread.page.inner_text("#rd-popover .rd-scroll"), what="the outside reply")
    assert thread.page.input_value("#rd-popover textarea") == "half a sentence"
    assert thread.page.evaluate("window.__same_load") is True


def test_a_click_outside_or_escape_does_not_throw_away_typed_text(thread):
    open_reply(thread, "important words")
    thread.page.mouse.click(5, 400)
    thread.page.keyboard.press("Escape")
    assert thread.page.input_value("#rd-popover textarea") == "important words"
    thread.page.click("#rd-popover button[data-f=no]")
    assert thread.page.query_selector("#rd-popover textarea") is None


def test_a_send_that_fails_gives_the_form_back_with_its_text(thread):
    open_reply(thread, "sent into the void")
    thread.site.kill()
    thread.page.click("#rd-popover button[data-f=ok]")
    toasted(thread.page, "did not go out")
    assert thread.page.input_value("#rd-popover textarea") == "sent into the void"
    thread.site.start()
    thread.page.click("#rd-popover button[data-f=ok]")
    f = thread.site.file
    until(lambda: "sent into the void" in f.read_text(), what="the reply in the file")


def send_closed_and_failed(tab, close, during=None):
    """Ctrl+Enter in the open form; while its request is out, Escape, a click outside or a badge
    (clicked twice); `during` looks at the page then; the hub answers with an error, as one that
    restarts or has lost the thread does."""
    p, held = tab.page, []
    p.route("**/_/comment", lambda route: held.append(route))
    p.keyboard.press("Control+Enter")
    until(lambda: held or p.wait_for_timeout(20), what="the send to go out")
    if close == "Escape":
        p.keyboard.press("Escape")
    elif close == "a badge":
        # The popover sits over the badge below its own: the click is sent as an event.
        p.locator(".rd-badge").dispatch_event("click")
        p.locator(".rd-badge").dispatch_event("click")
    else:
        p.mouse.click(5, 400)
    if during:
        during()
    fail_the_send(p, held)


def fail_the_send(p, held):
    """The hub answers the held request with an error; the page says so."""
    held[0].fulfill(status=500, json={"ok": False, "error": "the hub broke off"})
    toasted(p, "the hub broke off")
    p.unroute("**/_/comment")


def send_held(tab, form, text):
    """Open the reply or edit form, type, send with `/_/comment` held; returns the held requests."""
    p, held = tab.page, []
    p.click(f"#rd-popover button[data-a={form}]")
    p.fill("#rd-popover textarea", text)
    p.route("**/_/comment", lambda route: held.append(route))
    p.keyboard.press("Control+Enter")
    until(lambda: held or p.wait_for_timeout(20), what="the send to go out")
    return held


@pytest.mark.parametrize("close", ["Escape", "a click outside"])
@pytest.mark.parametrize("form", ["reply", "edit"])
def test_a_reply_or_edit_whose_send_fails_after_escape_or_a_click_outside_comes_back_with_its_text(thread, form, close):
    p = thread.page
    p.click(f"#rd-popover button[data-a={form}]")
    p.fill("#rd-popover textarea", "words sent while closing")
    send_closed_and_failed(thread, close)
    assert p.is_visible("#rd-popover textarea"), "the form with the text is not on the page"
    assert p.input_value("#rd-popover textarea") == "words sent while closing"
    p.click("#rd-popover button[data-f=ok]")
    f = thread.site.file
    until(lambda: "words sent while closing" in f.read_text(), what="the text in the file")


# Escape and a click outside during a reply's send kept the popover without a word, and once the hub had
# taken the reply its thread was still open; the badge of the same thread closed it. A reply or an edit
# that is out goes back to its own thread if it fails, so they close the popover as the badge does.
@pytest.mark.parametrize("close", ["Escape", "a click outside"])
@pytest.mark.parametrize("form", ["reply", "edit"])
def test_escape_or_a_click_outside_during_a_reply_or_edits_send_closes_the_popover_and_the_hub_takes_it(thread, form, close):
    p = thread.page
    held = send_held(thread, form, "words that go through")
    if close == "Escape":
        p.keyboard.press("Escape")
    else:
        p.mouse.click(5, 400)
    until(lambda: p.locator("#rd-popover").count() == 0, timeout=3, what=f"{close} to close the popover")
    held[0].continue_()
    p.unroute("**/_/comment")
    until(lambda: "words that go through" in thread.site.file.read_text(), what="the text in the file")
    until(lambda: comment_store(thread) == "", what="the page to take the answer in")
    p.wait_for_timeout(300)
    assert p.locator("#rd-popover").count() == 0, "the answer opened the popover again"


def failed_send(tab, form, text):
    """A reply or an edit sent while the hub is gone: it fails and the form comes back with its text."""
    p = tab.page
    p.click(f"#rd-popover button[data-a={form}]")
    p.fill("#rd-popover textarea", text)
    tab.site.kill()
    p.click("#rd-popover button[data-f=ok]")
    toasted(p, "did not go out")
    tab.site.start()


def reopen_thread(tab):
    tab.page.reload()
    tab.page.wait_for_selector("#rd-menu-btn", state="attached")
    tab.page.click(".rd-badge")
    tab.page.wait_for_selector("#rd-popover .rd-msg")


@pytest.mark.parametrize("form", ["reply", "edit"])
def test_a_reply_or_edit_whose_send_failed_is_still_there_after_the_page_is_closed(thread, form):
    # A new comment was kept in localStorage from its send until the hub took it;
    # a reply or an edit was not, so closing the tab after a failed send lost what had been written.
    failed_send(thread, form, "words the hub never took")
    reopen_thread(thread)
    p = thread.page
    p.wait_for_selector("#rd-popover textarea")
    assert p.input_value("#rd-popover textarea") == "words the hub never took"
    p.click("#rd-popover button[data-f=ok]")
    until(lambda: "words the hub never took" in thread.site.file.read_text(), what="the text in the file")
    until(lambda: comment_store(thread) == "", what="the kept text to go once the hub has taken it")


@pytest.mark.parametrize("form", ["reply", "edit"])
def test_cancelling_a_reply_or_edit_whose_send_failed_clears_what_it_kept(thread, form):
    failed_send(thread, form, "words I gave up on")
    thread.page.click("#rd-popover button[data-f=no]")
    assert comment_store(thread) == ""
    reopen_thread(thread)
    thread.page.wait_for_timeout(300)
    assert thread.page.query_selector("#rd-popover textarea") is None


# A reply or an edit whose send failed came back only when its thread was opened, one entry of a thread at a
# time, and nothing on the next page said it was there; one whose thread was deleted meanwhile, or the edit of
# a comment that is no longer the person's own, could not be reached at all. The page says it in one line beside
# the menu button, and the line's list holds each with its text: one that can still be sent opens its thread,
# one that cannot is there to copy, then to discard.
UNSENT = "#rd-unsent"
UNSENT_LIST = "#rd-popover[data-unsent]"
THREAD_OPEN = "#rd-popover:not([data-unsent]) .rd-msg"


def unsent_list(p):
    """The line's list opened: one (quote, line, text, buttons) per reply or edit it holds."""
    p.click(UNSENT)
    p.wait_for_selector(UNSENT_LIST, timeout=3000)
    return [tuple(e) for e in p.evaluate("""() => Array.from(
      document.querySelectorAll('#rd-popover[data-unsent] .rd-form')).map(f => [
        f.previousElementSibling.textContent, f.querySelector('.rd-hold').textContent,
        f.querySelector('textarea').value, Array.from(f.querySelectorAll('button')).map(b => b.textContent)])""")]


def unsent_line(p, timeout=5000):
    p.wait_for_selector(UNSENT, timeout=timeout)
    return p.inner_text(UNSENT)


def come_back(tab):
    """The page left, then the document opened again; no thread is opened."""
    tab.page.goto("about:blank")
    tab.open()


@pytest.mark.parametrize("form", ["reply", "edit"])
def test_a_reply_or_edit_whose_send_failed_is_said_on_the_next_page_before_its_thread_is_opened(thread, form):
    failed_send(thread, form, "words the hub never took")
    p = thread.page
    assert unsent_line(p) == f"1 {form} not sent · Show"
    come_back(thread)
    assert unsent_line(p) == f"1 {form} not sent · Show"
    assert p.locator("#rd-popover").count() == 0
    ((quote, line, text, buttons),) = unsent_list(p)
    assert quote == "“apples”"
    assert line == f"Your {form} was not sent. It is kept: open its thread to send it."
    assert text == "words the hub never took"
    assert buttons == ["Open the thread", "Discard"]
    p.keyboard.press("Escape")
    until(lambda: p.locator(UNSENT_LIST).count() == 0, timeout=3, what="Escape to close the list")
    unsent_list(p)
    p.click(f"{UNSENT_LIST} button[data-f=open]")
    p.wait_for_selector(THREAD_OPEN)
    assert p.input_value("#rd-popover textarea") == "words the hub never took"
    p.click("#rd-popover button[data-f=ok]")
    until(lambda: "words the hub never took" in thread.site.file.read_text(), what="the text in the file")
    until(lambda: comment_store(thread) == "", what="the kept text to go once the hub has taken it")
    until(lambda: p.locator(UNSENT).count() == 0, timeout=3, what="the line to go once the hub has taken it")


@pytest.mark.parametrize("width", [1100, 390])
def test_the_line_of_a_reply_not_sent_covers_no_badge(thread, width):
    # A list pinned over the top of the text covered the first paragraph's badge.
    p = thread.page
    failed_send(thread, "reply", "words the hub never took")
    p.set_viewport_size({"width": width, "height": 800})
    come_back(thread)
    unsent_line(p)
    assert p.evaluate("""() => {
      const pad = document.body.computedStyleMap().get('padding-bottom').value;
      return document.getElementById('rd-unsent').getBoundingClientRect().top >= innerHeight - pad; }"""), \
        "the line is not in the strip the page keeps free below its text"
    assert p.evaluate("""() => Array.from(document.querySelectorAll('.rd-badge')).every(b => {
      const r = b.getBoundingClientRect();
      return document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) === b; })"""), "a badge is covered"
    p.click(f"{P1} .rd-badge")
    p.wait_for_selector(THREAD_OPEN)
    assert p.input_value("#rd-popover textarea") == "words the hub never took"


def test_a_reply_being_sent_is_not_said_to_be_unsent_until_its_send_fails(thread):
    p = thread.page
    held = send_held(thread, "reply", "words on their way")
    assert "words on their way" in comment_store(thread)
    p.wait_for_timeout(300)
    assert p.locator(UNSENT).count() == 0
    fail_the_send(p, held)
    assert unsent_line(p, timeout=3000) == "1 reply not sent · Show"


def second_page(tab, context):
    """Another page of the same document, in the same browser."""
    b = context.new_page()
    b.goto(tab.site.url)
    b.wait_for_selector("#rd-menu-btn", state="attached")
    return b


# A page already open heard nothing of what another page of the document wrote into the store: a reply that
# page could not send was not said here until a reload, and one it sent afterwards was still said here.
def test_a_reply_another_page_could_not_send_is_said_at_once_on_a_page_already_open(thread, context):
    b = second_page(thread, context)
    b.click(".rd-badge")
    failed_send(SimpleNamespace(page=b, site=thread.site), "reply", "words from the other page")
    assert unsent_line(thread.page, timeout=3000) == "1 reply not sent · Show"
    ((_, _, text, _),) = unsent_list(thread.page)
    assert text == "words from the other page"


def test_a_reply_another_page_sent_is_no_longer_said_on_a_page_already_open(thread, context):
    failed_send(thread, "reply", "words sent at last")
    b = second_page(thread, context)
    assert unsent_line(b) == "1 reply not sent · Show"
    unsent_list(b)
    thread.page.click("#rd-popover button[data-f=ok]")
    until(lambda: "words sent at last" in thread.site.file.read_text(), what="the reply in the file")
    until(lambda: b.locator(f"{UNSENT}, {UNSENT_LIST}").count() == 0, timeout=3,
          what="the line and its list to go on the other page")


# The list is drawn from the store when it is opened. One found empty, the store emptied without this page being
# told (a page hears no storage event for its own writes), opened nothing and left the line.
def test_a_line_whose_list_is_found_empty_goes_when_it_is_clicked(thread):
    failed_send(thread, "reply", "words the hub never took")
    p = thread.page
    come_back(thread)
    unsent_line(p)
    p.evaluate("localStorage.clear()")
    p.click(UNSENT)
    until(lambda: p.locator(UNSENT).count() == 0, timeout=3, what="the line to go")
    assert p.locator("#rd-popover").count() == 0


def test_a_page_with_nothing_kept_says_nothing_is_unsent(thread):
    come_back(thread)
    thread.page.wait_for_timeout(300)
    assert thread.page.locator(f"{UNSENT}, #rd-popover").count() == 0


def test_a_reply_the_hub_took_is_not_said_to_be_unsent_on_the_next_page(thread):
    open_reply(thread, "a reply that went through")
    thread.page.click("#rd-popover button[data-f=ok]")
    until(lambda: "a reply that went through" in thread.site.file.read_text(), what="the reply in the file")
    thread.page.wait_for_selector("#rd-popover .rd-msg:has-text('a reply that went through')")
    assert thread.page.locator(UNSENT).count() == 0
    come_back(thread)
    thread.page.wait_for_timeout(300)
    assert thread.page.locator(f"{UNSENT}, #rd-popover").count() == 0


def test_a_kept_reply_is_not_said_on_a_page_of_another_document(thread):
    failed_send(thread, "reply", "words for the plan only")
    thread.site.file.with_name("other.md").write_text("# Other\n\nAnother document.\n", encoding="utf-8")
    p = thread.page
    p.goto(f"{thread.site.base}/work/other.md")
    p.wait_for_selector("#rd-menu-btn", state="attached")
    p.wait_for_timeout(300)
    assert "Another document." in p.inner_text("main")
    assert p.locator(f"{UNSENT}, #rd-popover").count() == 0
    assert "words for the plan only" in comment_store(thread)


def test_a_reply_and_an_edit_kept_for_two_threads_are_both_listed_and_each_opens_its_own_thread(two_threads):
    tab, p = two_threads, two_threads.page
    failed_send(tab, "reply", "a reply about apples")
    come_back(tab)
    unsent_line(p)
    p.click(f"{P2} .rd-badge")
    p.wait_for_selector(THREAD_OPEN)
    failed_send(tab, "edit", "Why pears, really?")
    come_back(tab)
    assert unsent_line(p) == "1 reply and 1 edit not sent · Show"
    assert [(q, t) for q, _, t, _ in unsent_list(p)] == [("“apples”", "a reply about apples"),
                                                         ("“pears”", "Why pears, really?")]
    p.locator(f"{UNSENT_LIST} button[data-f=open]").nth(1).click()
    p.wait_for_selector(f"{THREAD_OPEN}:has-text('Why pears?')")
    assert p.input_value("#rd-popover textarea") == "Why pears, really?"
    p.click("#rd-popover button[data-f=no]")
    assert unsent_line(p, timeout=3000) == "1 reply not sent · Show"
    p.keyboard.press("Escape")
    assert [(q, t) for q, _, t, _ in unsent_list(p)] == [("“apples”", "a reply about apples")]
    p.click(f"{UNSENT_LIST} button[data-f=open]")
    p.wait_for_selector(f"{THREAD_OPEN}:has-text('Why apples?')")
    assert p.input_value("#rd-popover textarea") == "a reply about apples"


# The entry of a reply is cleared by the id of the send that kept it, not by its thread and kind: a page whose
# send was taken, or whose form was cancelled, left alone the entry another page wrote for a send still out.
@pytest.mark.parametrize("how", ["taken", "cancelled"])
@pytest.mark.parametrize("form", ["reply", "edit"])
def test_a_send_taken_or_cancelled_on_one_page_leaves_the_kept_reply_of_a_send_still_out_on_another(thread, context, how, form):
    a, b = thread.page, second_page(thread, context)
    b.click(".rd-badge")
    other = SimpleNamespace(page=b, site=thread.site)
    held_b = send_held(other, form, "words from page B")
    held_a = send_held(thread, form, "words from page A")
    assert "words from page A" in comment_store(thread)
    if how == "taken":
        held_b[0].continue_()
        until(lambda: "words from page B" in thread.site.file.read_text(), what="B's reply in the file")
    else:
        fail_the_send(b, held_b)
        b.click("#rd-popover button[data-f=no]")
    b.wait_for_timeout(500)
    assert "words from page A" in comment_store(thread), "the entry of A's send went with B's"
    held_a[0].fulfill(status=500, json={"ok": False, "error": "the hub broke off"})
    a.unroute("**/_/comment")
    assert unsent_line(a, timeout=3000) == f"1 {form} not sent · Show"


# A thread holds at most one kept reply and one kept edit; two pages of the document give it both.
def test_a_reply_and_an_edit_kept_for_one_thread_are_both_listed_and_neither_hides_the_other(thread, context):
    a, b = thread.page, context.new_page()
    b.goto(thread.site.url)
    b.wait_for_selector("#rd-menu-btn", state="attached")
    b.click(".rd-badge")
    b.click("#rd-popover button[data-a=edit]")
    b.fill("#rd-popover textarea", "Why apples, really?")
    open_reply(thread, "a reply about apples")
    thread.site.kill()
    a.click("#rd-popover button[data-f=ok]")
    toasted(a, "did not go out")
    b.click("#rd-popover button[data-f=ok]")
    toasted(b, "did not go out")
    thread.site.start()
    come_back(thread)
    assert unsent_line(a) == "1 reply and 1 edit not sent · Show"
    assert [(line.split(".")[0], t) for _, line, t, _ in unsent_list(a)] == [
        ("Your reply was not sent", "a reply about apples"), ("Your edit was not sent", "Why apples, really?")]
    a.locator(f"{UNSENT_LIST} button[data-f=open]").nth(1).click()
    a.wait_for_selector(THREAD_OPEN)
    assert a.input_value("#rd-popover textarea") == "Why apples, really?"
    assert "Your reply to this thread is kept too" in a.inner_text("#rd-popover .rd-form")
    a.click("#rd-popover button[data-f=no]")
    until(lambda: a.input_value("#rd-popover textarea") == "a reply about apples", timeout=3,
          what="the kept reply in the thread once its edit is cancelled")
    assert "kept too" not in a.inner_text("#rd-popover .rd-form")
    a.click("#rd-popover button[data-f=ok]")
    until(lambda: "a reply about apples" in thread.site.file.read_text(), what="the reply in the file")
    until(lambda: comment_store(thread) == "", what="the store to hold nothing")
    assert rdc.parse(thread.site.file.read_text()).comments[0].body == "Why apples?"


@pytest.mark.parametrize("form", ["reply", "edit"])
def test_a_kept_reply_or_edit_whose_thread_was_deleted_after_the_page_was_left_can_be_read_copied_and_let_go(thread, form):
    failed_send(thread, form, "words for a thread that went")
    p = thread.page
    p.goto("about:blank")
    delete_the_thread(thread)
    thread.open()
    unsent_line(p)
    ((quote, line, text, buttons),) = unsent_list(p)
    assert quote == "“apples”"
    went = {"reply": "its thread", "edit": "its comment"}[form]
    assert line == f"Your {form} was not sent, and {went} was deleted, so it cannot be sent. Copy it, then discard it."
    assert text == "words for a thread that went"
    assert buttons == ["Discard"]
    ta = f"{UNSENT_LIST} textarea"
    assert not p.is_editable(ta)
    assert p.evaluate("t => (t.select(), t.value.slice(t.selectionStart, t.selectionEnd))",
                      p.query_selector(ta)) == "words for a thread that went"
    p.click(f"{UNSENT_LIST} button[data-f=no]")
    until(lambda: p.locator(f"{UNSENT}, #rd-popover").count() == 0, timeout=3, what="Discard to take the line away")
    assert comment_store(thread) == ""
    come_back(thread)
    p.wait_for_timeout(300)
    assert p.locator(f"{UNSENT}, #rd-popover").count() == 0


def test_a_kept_edit_of_a_comment_no_longer_the_persons_own_can_be_copied_and_let_go(thread):
    failed_send(thread, "edit", "Why apples, really?")
    p, f = thread.page, thread.site.file
    p.goto("about:blank")
    f.write_text(re.sub(r'by="[^"]*"', 'by="Bea"', f.read_text(), count=1), encoding="utf-8")
    assert rdc.parse(f.read_text()).comments[0].by == "Bea"
    thread.open()
    unsent_line(p)
    ((quote, line, text, buttons),) = unsent_list(p)
    assert line == ("Your edit was not sent, and only your own comments can be edited, so it cannot be sent. "
                    "Copy it, then discard it.")
    assert text == "Why apples, really?"
    assert buttons == ["Discard"]
    p.click(f"{UNSENT_LIST} button[data-f=no]")
    until(lambda: p.locator(f"{UNSENT}, #rd-popover").count() == 0, timeout=3, what="Discard to take the line away")
    assert comment_store(thread) == ""


def asked(page):
    """The types of the dialogs the page raises from now on, each answered with Stay."""
    dialogs = []
    page.on("dialog", lambda d: (dialogs.append(d.type), d.dismiss()))
    return dialogs


def left_with(tab, context):
    """The tab closed the way a person closes it (the page's own leave prompt runs); what the prompt
    asked, as the types of the dialogs it raised. A page that was let go has no dialog and is closed."""
    p = tab.page
    dialogs = asked(p)
    p.close(run_before_unload=True)
    context.new_page().wait_for_timeout(500)    # the dialog event is delivered while an API call is out
    return dialogs, p.is_closed()


@pytest.mark.parametrize("form", ["reply", "edit"])
def test_a_page_with_a_reply_or_edit_being_typed_asks_before_it_is_left(thread, context, form):
    # Only edits on screen asked. A reply or an edit being typed is in no
    # store until it is sent, so a closed tab or a reload threw it away without a word.
    thread.page.click(f"#rd-popover button[data-a={form}]")
    thread.page.fill("#rd-popover textarea", "words I am still writing")
    assert left_with(thread, context) == (["beforeunload"], False)


def test_a_page_with_a_new_comment_being_typed_asks_before_it_is_left(tab, context):
    tab.open()
    select(tab.page, at(P1, "apples"), at(P1, "apples", None))
    tab.page.click("#rd-comment-btn")
    tab.page.fill("#rd-popover textarea", "a comment I am still writing")
    assert left_with(tab, context) == (["beforeunload"], False)


def test_a_page_with_an_empty_form_is_left_without_a_question(thread, context):
    thread.page.click("#rd-popover button[data-a=reply]")
    thread.page.fill("#rd-popover textarea", "  ")
    assert left_with(thread, context) == ([], True)


# A kept comment (data-kept) and a form whose send is out (data-done) hold nothing that the store does not:
# the page is left without a question.
def test_a_page_with_a_kept_comment_is_left_without_a_question(kept, context):
    assert left_with(kept, context) == ([], True)


def test_a_page_with_text_typed_into_a_kept_comment_is_left_without_a_question(kept, context):
    kept.page.fill("#rd-popover textarea", "about the ripe pears, edited")
    assert "about the ripe pears, edited" in comment_store(kept)
    assert left_with(kept, context) == ([], True)


@pytest.mark.parametrize("form", ["reply", "edit"])
def test_a_page_whose_reply_or_edit_is_being_sent_is_left_without_a_question(thread, context, form):
    send_held(thread, form, "words on their way")
    assert "words on their way" in comment_store(thread)
    assert left_with(thread, context) == ([], True)


def test_a_page_whose_new_comment_is_being_sent_is_left_without_a_question(tab, context):
    tab.open()
    open_comment_form(tab, P1, "apples")
    tab.page.fill("#rd-popover textarea", "a comment on its way")
    tab.page.route("**/_/comment", lambda route: None)
    tab.page.keyboard.press("Control+Enter")
    until(lambda: tab.page.locator("#rd-popover .rd-form[data-done]").count(), what="the send to go out")
    assert "a comment on its way" in comment_store(tab)
    assert left_with(tab, context) == ([], True)


# A form filled from what the store keeps (a reply or an edit whose send failed, a comment refused because its
# paragraph changed) is an ordinary form, and the leave question counted its text as typed and in no store.
# It is asked about again once its text is changed, and when its thread is gone: nothing draws that text again.
@pytest.mark.parametrize("form", ["reply", "edit"])
def test_a_reply_or_edit_filled_from_the_store_is_left_without_a_question(thread, context, form):
    failed_send(thread, form, "words the hub never took")
    reopen_thread(thread)
    thread.page.wait_for_selector("#rd-popover textarea")
    assert thread.page.input_value("#rd-popover textarea") == "words the hub never took"
    assert left_with(thread, context) == ([], True)


@pytest.mark.parametrize("form", ["reply", "edit"])
def test_a_reply_or_edit_whose_send_failed_is_left_without_a_question(thread, context, form):
    failed_send(thread, form, "words the hub never took")
    assert thread.page.input_value("#rd-popover textarea") == "words the hub never took"
    assert left_with(thread, context) == ([], True)


@pytest.mark.parametrize("form", ["reply", "edit"])
def test_a_reply_or_edit_filled_from_the_store_and_changed_is_left_without_a_question_as_the_store_follows_it(thread, context, form):
    failed_send(thread, form, "words the hub never took")
    reopen_thread(thread)
    thread.page.fill("#rd-popover textarea", "words the hub never took, and more")
    assert "words the hub never took, and more" in comment_store(thread)
    assert left_with(thread, context) == ([], True)


def test_a_reply_filled_from_the_store_for_a_thread_deleted_elsewhere_asks_before_it_is_left(thread, context):
    failed_send(thread, "reply", "words the hub never took")
    reopen_thread(thread)
    thread.page.wait_for_selector("#rd-popover textarea")
    delete_the_thread(thread)
    thread.page.wait_for_selector("#rd-popover .rd-hold:has-text('deleted')")
    assert "words the hub never took" in comment_store(thread)
    assert left_with(thread, context) == (["beforeunload"], False)


def test_a_new_comment_filled_from_a_kept_one_is_left_without_a_question(kept, context):
    open_comment_form(kept, P2, "ripe pears")
    assert kept.page.input_value("#rd-popover textarea") == "about the pears"
    assert kept.page.locator("#rd-popover .rd-form[data-kept]").count() == 0
    assert left_with(kept, context) == ([], True)


def test_a_new_comment_whose_send_failed_is_left_without_a_question(tab, context):
    tab.open()
    open_comment_form(tab, P1, "apples")
    tab.page.fill("#rd-popover textarea", "never sent")
    tab.site.kill()
    tab.page.click("#rd-popover button[data-f=ok]")
    toasted(tab.page, "did not go out")
    assert "never sent" in comment_store(tab)
    assert left_with(tab, context) == ([], True)


def test_a_new_comment_filled_from_a_kept_one_and_changed_asks_before_it_is_left(kept, context):
    open_comment_form(kept, P2, "ripe pears")
    kept.page.fill("#rd-popover textarea", "about the ripe pears, changed")
    assert left_with(kept, context) == (["beforeunload"], False)


def test_a_reply_the_hub_took_leaves_nothing_in_the_store(thread):
    open_reply(thread, "a reply that went through")
    thread.page.click("#rd-popover button[data-f=ok]")
    until(lambda: "a reply that went through" in thread.site.file.read_text(), what="the reply in the file")
    thread.page.wait_for_selector("#rd-popover .rd-msg:has-text('a reply that went through')")
    assert comment_store(thread) == ""


def still_the_one_form(p):
    """A new comment whose send is out, its popover asked to close: still the one form, no kept notice."""
    p.wait_for_timeout(150)      # the notice, if one is going to be drawn, is drawn on the next tick
    assert p.locator("#rd-popover .rd-form").count() == 1, "a second form is on the page during the send"
    assert "your comment is kept" not in p.inner_text("#rd-popover")
    assert p.locator("#rd-popover[data-kept]").count() == 0
    assert "apples" in p.inner_text("#rd-popover .rd-quote")


# A new comment still being sent showed as "your comment is kept" once its popover had closed, and its
# failed send put the form into that notice: the same text twice. An earlier change had
# already closed the gap (Escape, a click outside and a badge all wait while a send is out, so the popover
# never closes): `still_the_one_form` pins that, and failed on the build before it.
@pytest.mark.parametrize("close", ["Escape", "a click outside"])
def test_a_new_comment_whose_send_fails_after_escape_or_a_click_outside_keeps_its_text(tab, close):
    tab.open()
    open_comment_form(tab, P1, "apples")
    tab.page.fill("#rd-popover textarea", "about the apples")

    def during():
        toasted(tab.page, BEING_SENT)        # it stays, and says why, as for a badge
        still_the_one_form(tab.page)
    send_closed_and_failed(tab, close, during=during)
    assert tab.page.is_visible("#rd-popover textarea"), "the form with the text is not on the page"
    assert tab.page.input_value("#rd-popover textarea") == "about the apples"
    assert tab.page.locator("#rd-popover textarea").count() == 1, "the failed send put its form in beside a second one"
    assert "about the apples" in comment_store(tab)


def test_a_new_comment_still_being_sent_is_not_closed_by_a_badge_clicked_twice(tab):
    tab.open()
    comment_on(tab, at(P2, "pears"), at(P2, "pears", None), "Why pears?")
    tab.page.reload()
    tab.page.wait_for_selector("#rd-menu-btn", state="attached")
    open_comment_form(tab, P1, "apples")
    tab.page.fill("#rd-popover textarea", "about the apples")
    send_closed_and_failed(tab, "a badge", during=lambda: still_the_one_form(tab.page))
    assert tab.page.locator("#rd-popover textarea").count() == 1, "the failed send put its form in beside a second one"
    assert tab.page.input_value("#rd-popover textarea") == "about the apples"


def test_a_new_comment_refused_because_its_paragraph_changed_keeps_its_text(tab):
    tab.open()
    f = tab.site.file
    refuse_a_comment_on_pears(tab)
    assert tab.page.input_value("#rd-popover textarea") == "about the pears"
    assert "pears" in tab.page.inner_text("#rd-popover .rd-quote")
    assert rdc.parse(f.read_text()).comments == []
    key = comment_draft_key(tab.site)
    assert "about the pears" in tab.page.evaluate(f"localStorage.getItem({key!r})")
    select(tab.page, at(P2, "pears"), at(P2, "pears", None))
    tab.page.click("#rd-comment-btn")
    assert tab.page.input_value("#rd-popover textarea") == "about the pears"
    tab.page.click("#rd-popover button[data-f=ok]")
    until(lambda: rdc.parse(f.read_text()).comments, what="the comment in the file")
    until(lambda: tab.page.evaluate(f"localStorage.getItem({key!r})") is None,
          what="the kept comment to leave localStorage")


@pytest.fixture
def kept(tab):
    """A page on which a comment about 'pears' was refused (its paragraph changed under it) and
    kept: the page has reloaded, and the kept text is in localStorage and in the form that says so."""
    tab.open()
    refuse_a_comment_on_pears(tab)
    return tab


def refuse_a_comment_on_pears(tab, old="about pears", new="about ripe pears", more=""):
    f = tab.site.file
    select(tab.page, at(P2, "pears"), at(P2, "pears", None))
    tab.page.click("#rd-comment-btn")
    tab.page.fill("#rd-popover textarea", "about the pears")
    mark(tab.page)
    f.write_text(f.read_text().replace(old, new) + more, encoding="utf-8")
    tab.page.wait_for_selector("#rd-popover .rd-hold")
    tab.page.click("#rd-popover button[data-f=ok]")
    reloaded(tab.page)
    tab.page.wait_for_selector("#rd-popover .rd-hold:has-text('Select the passage again; your comment is kept.')")


def test_a_409_with_the_select_again_code_keeps_the_comment_whatever_its_words(tab):
    tab.open()
    p = tab.page
    p.route("**/_/comment", lambda route: route.fulfill(
        status=409, json={"ok": False, "error": "Another sentence entirely.", "code": "select-again"}))
    select(p, at(P2, "pears"), at(P2, "pears", None))
    p.click("#rd-comment-btn")
    p.fill("#rd-popover textarea", "about the pears")
    mark(p)
    p.click("#rd-popover button[data-f=ok]")
    reloaded(p)
    p.wait_for_selector(KEPT)
    assert p.input_value("#rd-popover textarea") == "about the pears"


def test_a_reply_the_hub_takes_with_the_text_changed_leaves_the_store_empty_after_the_reload(thread):
    # `textSame: false` makes op() start the reload before the send's own `.then` clears the kept reply.
    p = thread.page

    def changed(route):
        r = route.fetch()
        route.fulfill(response=r, json={**r.json(), "textSame": False})
    p.route("**/_/comment", changed)
    p.click("#rd-popover button[data-a=reply]")
    p.fill("#rd-popover textarea", "my reply text")
    mark(p)
    p.keyboard.press("Control+Enter")
    reloaded(p)
    until(lambda: "my reply text" in thread.site.file.read_text(), what="the reply in the file")
    p.wait_for_selector("#rd-menu-btn", state="attached")
    p.wait_for_timeout(500)
    assert comment_store(thread) == ""


def test_a_409_without_the_code_is_a_failure_even_in_the_old_words(tab):
    tab.open()
    p = tab.page
    p.route("**/_/comment", lambda route: route.fulfill(
        status=409, json={"ok": False, "error": "select the text again"}))
    select(p, at(P2, "pears"), at(P2, "pears", None))
    p.click("#rd-comment-btn")
    p.fill("#rd-popover textarea", "about the pears")
    p.click("#rd-popover button[data-f=ok]")
    toasted(p, "select the text again")
    assert p.input_value("#rd-popover textarea") == "about the pears"


def open_comment_form(tab, css, word):
    select(tab.page, at(css, word), at(css, word, None))
    tab.page.click("#rd-comment-btn")
    tab.page.wait_for_selector("#rd-popover textarea")


def test_a_kept_comment_is_not_put_in_the_form_of_another_passage(kept):
    open_comment_form(kept, P1, "apples")
    assert kept.page.input_value("#rd-popover textarea") == ""
    kept.page.click("#rd-popover button[data-f=no]")
    # The text of the other passage stays kept, and is offered when its own passage is commented again.
    key = comment_draft_key(kept.site)
    assert "about the pears" in kept.page.evaluate(f"localStorage.getItem({key!r})")
    open_comment_form(kept, P2, "pears")
    assert kept.page.input_value("#rd-popover textarea") == "about the pears"


def test_cancelling_a_new_comment_whose_send_failed_clears_what_it_kept(tab):
    tab.open()
    open_comment_form(tab, P1, "apples")
    tab.page.fill("#rd-popover textarea", "never sent")
    tab.site.kill()
    tab.page.click("#rd-popover button[data-f=ok]")
    toasted(tab.page, "did not go out")
    key = comment_draft_key(tab.site)
    assert "never sent" in tab.page.evaluate(f"localStorage.getItem({key!r})")
    tab.page.click("#rd-popover button[data-f=no]")
    assert tab.page.evaluate(f"localStorage.getItem({key!r})") is None


KEPT = "#rd-popover .rd-hold:has-text('Select the passage again; your comment is kept.')"


def comment_store(tab):
    """What localStorage holds of the new comments, replies and edits the hub has not taken yet ('' for nothing)."""
    key = comment_draft_key(tab.site)
    return tab.page.evaluate(f"localStorage.getItem({key!r})") or ""


def test_a_comment_sent_on_another_passage_leaves_the_kept_comment_kept(kept):
    open_comment_form(kept, P1, "apples")
    kept.page.fill("#rd-popover textarea", "about the apples")
    kept.page.click("#rd-popover button[data-f=ok]")
    f = kept.site.file
    until(lambda: rdc.parse(f.read_text()).comments, what="the comment in the file")
    assert "about the pears" in comment_store(kept), "the send on another passage deleted the kept comment"
    kept.page.reload()
    kept.page.wait_for_selector(KEPT)
    assert kept.page.input_value("#rd-popover textarea") == "about the pears"


def test_a_failed_send_on_another_passage_keeps_both_texts_and_its_cancel_clears_only_its_own(kept):
    open_comment_form(kept, P1, "apples")
    kept.page.fill("#rd-popover textarea", "about the apples")
    kept.site.kill()
    kept.page.click("#rd-popover button[data-f=ok]")
    toasted(kept.page, "did not go out")
    assert kept.page.input_value("#rd-popover textarea") == "about the apples"
    s = comment_store(kept)
    assert "about the pears" in s and "about the apples" in s
    kept.page.click("#rd-popover button[data-f=no]")
    s = comment_store(kept)
    assert "about the pears" in s and "about the apples" not in s


def test_a_kept_comment_comes_back_when_the_thread_opened_over_it_is_closed(tab):
    tab.open()
    comment_on(tab, at(P1, "apples"), at(P1, "apples", None), "Why apples?")
    tab.page.wait_for_selector("#rd-popover .rd-msg")
    tab.page.keyboard.press("Escape")
    refuse_a_comment_on_pears(tab)
    tab.page.click("#rd-menu-btn")
    tab.page.click("#rd-show")
    tab.page.click("#rd-panel button[data-id]")
    tab.page.wait_for_selector("#rd-popover .rd-msg")
    tab.page.keyboard.press("Escape")
    tab.page.wait_for_selector(KEPT, timeout=3000)
    assert tab.page.input_value("#rd-popover textarea") == "about the pears"


# A kept comment is told by the paragraph it was written in: the
# entry is told by its paragraph (the opening words and which occurrence of them it is), never by its quote alone.
def test_a_kept_comment_is_not_put_in_the_form_of_the_same_word_in_another_paragraph(tab):
    f = tab.site.file
    f.write_text("# Plan\n\nA first paragraph, about pears.\n\nA second paragraph, about pears too.\n",
                 encoding="utf-8")
    tab.open()
    select(tab.page, at("main", "pears too"), at("main", "pears too", 5))
    tab.page.click("#rd-comment-btn")
    tab.page.fill("#rd-popover textarea", "about the second pears")
    mark(tab.page)
    f.write_text(f.read_text().replace("pears too", "ripe pears too"), encoding="utf-8")
    tab.page.wait_for_selector("#rd-popover .rd-hold")
    tab.page.click("#rd-popover button[data-f=ok]")
    reloaded(tab.page)
    tab.page.wait_for_selector(KEPT)
    select(tab.page, at("main", "first paragraph, about pears", 23), at("main", "first paragraph, about pears", 28))
    tab.page.click("#rd-comment-btn")
    tab.page.wait_for_selector("#rd-popover textarea")
    assert tab.page.input_value("#rd-popover textarea") == ""
    tab.page.click("#rd-popover button[data-f=no]")
    assert "about the second pears" in comment_store(tab), "Cancel of another paragraph's form cleared the kept comment"


def test_a_comment_sent_on_the_same_word_of_another_paragraph_leaves_the_kept_comment_kept(tab):
    f = tab.site.file
    f.write_text("# Plan\n\nA first paragraph, about pears.\n\nA second paragraph, about pears too.\n",
                 encoding="utf-8")
    tab.open()
    select(tab.page, at("main", "pears too"), at("main", "pears too", 5))
    tab.page.click("#rd-comment-btn")
    tab.page.fill("#rd-popover textarea", "about the second pears")
    mark(tab.page)
    f.write_text(f.read_text().replace("pears too", "ripe pears too"), encoding="utf-8")
    tab.page.wait_for_selector("#rd-popover .rd-hold")
    tab.page.click("#rd-popover button[data-f=ok]")
    reloaded(tab.page)
    tab.page.wait_for_selector(KEPT)
    select(tab.page, at("main", "first paragraph, about pears", 23), at("main", "first paragraph, about pears", 28))
    tab.page.click("#rd-comment-btn")
    tab.page.fill("#rd-popover textarea", "about the first pears")
    tab.page.click("#rd-popover button[data-f=ok]")
    until(lambda: rdc.parse(f.read_text()).comments, what="the comment in the file")
    until(lambda: "about the first pears" not in comment_store(tab), what="the sent comment to leave the store")
    assert "about the second pears" in comment_store(tab), "the send cleared the other paragraph's kept comment"


def test_a_new_comment_retried_with_other_words_after_a_failed_send_leaves_nothing_kept(tab):
    # Each text sent has its own request id: the entry the failed send wrote is the form's own too.
    tab.open()
    p = tab.page
    tries = []

    def hub(route):
        tries.append(1)
        if len(tries) == 1:
            route.fulfill(status=500, json={"ok": False, "error": "Hub trouble."})
        else:
            route.continue_()
    p.route("**/_/comment", hub)
    select(p, at(P1, "apples"), at(P1, "apples", None))
    p.click("#rd-comment-btn")
    p.fill("#rd-popover textarea", "first words")
    p.click("#rd-popover button[data-f=ok]")
    toasted(p, "Hub trouble.")
    assert "first words" in comment_store(tab)
    p.fill("#rd-popover textarea", "other words")
    p.click("#rd-popover button[data-f=ok]")
    until(lambda: rdc.parse(tab.site.file.read_text()).comments, what="the comment in the file")
    until(lambda: comment_store(tab) == "", what="nothing to stay kept")


def test_a_kept_comment_is_not_put_in_the_form_of_a_paragraph_that_opens_with_the_same_words_and_took_its_index(tab):
    # Two paragraphs open alike, the kept comment is on the second, and a paragraph added above both gives the
    # first the index the second had: the opening words and the index agree, the occurrence does not.
    f = tab.site.file
    f.write_text("# Plan\n\nSame opening words, about apples.\n\nSame opening words, about pears.\n", encoding="utf-8")
    tab.open()
    select(tab.page, at("main", "about pears", 6), at("main", "about pears", None))
    tab.page.click("#rd-comment-btn")
    tab.page.fill("#rd-popover textarea", "about the pears")
    mark(tab.page)
    f.write_text(f.read_text().replace("# Plan\n", "# Plan\n\nAdded above both.\n").replace("about pears", "about ripe pears"),
                 encoding="utf-8")
    tab.page.wait_for_selector("#rd-popover .rd-hold")
    tab.page.click("#rd-popover button[data-f=ok]")
    reloaded(tab.page)
    tab.page.wait_for_selector(KEPT)
    select(tab.page, at("main", "about apples", 6), at("main", "about apples", None))
    tab.page.click("#rd-comment-btn")
    tab.page.wait_for_selector("#rd-popover textarea")
    assert tab.page.input_value("#rd-popover textarea") == ""
    tab.page.click("#rd-popover button[data-f=no]")
    assert "about the pears" in comment_store(tab)
    select(tab.page, at("main", "about ripe pears", 6), at("main", "about ripe pears", None))
    tab.page.click("#rd-comment-btn")
    tab.page.wait_for_selector("#rd-popover textarea")
    assert tab.page.input_value("#rd-popover textarea") == "about the pears"


def test_the_form_of_a_kept_comment_says_which_comment_it_holds(kept):
    # The selection is not the quote of the kept comment: the form says whose text it holds.
    open_comment_form(kept, P2, "ripe pears")
    assert kept.page.input_value("#rd-popover textarea") == "about the pears"
    assert kept.page.inner_text("#rd-popover .rd-kept-quote") == "Your kept comment on \u201cpears\u201d is in this form."


def test_the_form_of_a_selection_with_the_quote_of_the_kept_comment_says_nothing_more(kept):
    open_comment_form(kept, P2, "pears")
    assert kept.page.input_value("#rd-popover textarea") == "about the pears"
    assert kept.page.locator("#rd-popover .rd-kept-quote").count() == 0


def test_a_kept_comment_comes_back_in_the_form_of_another_selection_in_its_paragraph(kept):
    # The paragraph changed, which is why the comment was refused: selected again, the passage
    # rarely gives the same quote.
    open_comment_form(kept, P2, "ripe pears")
    assert kept.page.input_value("#rd-popover textarea") == "about the pears"
    kept.page.click("#rd-popover button[data-f=ok]")
    f = kept.site.file
    (c,) = until(lambda: rdc.parse(f.read_text()).comments, what="the comment in the file")
    assert c.body == "about the pears"
    until(lambda: comment_store(kept) == "", what="the kept comment to leave localStorage")


def test_a_comment_kept_in_the_one_slot_of_an_older_store_still_comes_back(tab):
    tab.open()
    key = comment_draft_key(tab.site)
    slot = json.dumps({"quote": "pears", "body": "about the pears", "at": "2026-10-13T10:00:00.000Z"})
    tab.page.evaluate(f"localStorage.setItem({key!r}, {json.dumps(slot)})")
    tab.page.reload()
    tab.page.wait_for_selector(KEPT)
    assert tab.page.input_value("#rd-popover textarea") == "about the pears"
    open_comment_form(tab, P2, "pears")
    assert tab.page.input_value("#rd-popover textarea") == "about the pears"


# A kept comment is a standing notice, not a form being written: it holds nothing back. Its text is in
# localStorage from every keystroke, so a reload loses none of it; Escape and a click outside leave it
# alone, since it comes back after a close.
def kept_text(tab):
    return tab.page.input_value("#rd-popover textarea")


def outside_change(tab):
    f = tab.site.file
    f.write_text(f.read_text() + "\nA new paragraph from outside.\n", encoding="utf-8")


@pytest.mark.parametrize("what", ["the panel", "the menu", "edit mode"])
def test_escape_closes_what_is_open_behind_a_kept_comment_and_leaves_the_comment(kept, what):
    p = kept.page
    if what == "the panel":
        p.click("#rd-menu-btn")
        p.click("#rd-show")
        p.wait_for_selector("#rd-panel.open")
    elif what == "the menu":
        p.click("#rd-menu-btn")
        p.wait_for_selector("#rd-menu.open")
    else:
        p.keyboard.press("e")
        p.wait_for_selector("body.rd-editing")
    p.keyboard.press("Escape")
    still_open = {"the panel": "#rd-panel.open", "the menu": "#rd-menu.open", "edit mode": "body.rd-editing"}[what]
    until(lambda: p.query_selector(still_open) is None, timeout=3, what=f"Escape to close {what}")
    p.wait_for_timeout(300)       # a closed kept popover would be drawn again on the next tick
    assert kept_text(kept) == "about the pears"
    assert "about the pears" in comment_store(kept)


def test_a_click_outside_leaves_a_kept_comment_on_screen_with_its_text(kept):
    kept.page.mouse.click(20, 500)
    kept.page.wait_for_timeout(300)
    assert kept_text(kept) == "about the pears"
    assert "about the pears" in comment_store(kept)


def test_a_change_from_outside_reloads_a_page_with_a_kept_comment_and_the_comment_comes_back(kept):
    mark(kept.page)
    outside_change(kept)
    reloaded(kept.page)
    kept.page.wait_for_selector(KEPT)
    assert "A new paragraph from outside." in kept.page.inner_text("main")
    assert kept_text(kept) == "about the pears"


def test_text_typed_into_a_kept_comment_comes_back_after_a_reload_from_outside(kept):
    kept.page.fill("#rd-popover textarea", "about the ripe pears, edited")
    mark(kept.page)
    outside_change(kept)
    reloaded(kept.page)
    kept.page.wait_for_selector(KEPT)
    assert kept_text(kept) == "about the ripe pears, edited"
    assert "about the ripe pears, edited" in comment_store(kept)


def test_an_upgraded_hub_reloads_a_page_that_holds_only_a_kept_comment(kept):
    # `writing` counted the kept textarea, so the upgrade notice said "Send or cancel your
    # comment" for a form the person never opened, and the page did not reload.
    mark(kept.page)
    kept.site.kill()
    kept.site.start(version="99.0.0")
    reloaded(kept.page, timeout=20)
    kept.page.wait_for_selector(KEPT)
    assert kept_text(kept) == "about the pears"


@pytest.fixture
def frozen(thread):
    """The thread's page on a clock that stands still, so that the autosave (2.5 s after the last
    keystroke) cannot save a typed edit before the test says so. No timer of the page runs: a `changed`
    event that comes while a save is out is held and replayed on a timer once the answer is in (`heard`),
    so a change from outside waits until the page has taken in the save before it."""
    p = thread.page
    reload_on_clock(p, pause=True)
    return thread


def test_a_save_that_merges_waits_for_the_reply_being_written_before_it_reloads(frozen):
    p, f = frozen.page, frozen.site.file
    type_at_end(p, P2, " and plums")
    p.click(".rd-badge")
    p.wait_for_selector("#rd-popover button[data-a=reply]")
    open_reply(frozen, "my reply text")
    mark(p)
    f.write_text(f.read_text() + "\nA new paragraph from outside.\n", encoding="utf-8")
    p.wait_for_selector("#rd-popover .rd-hold")
    p.keyboard.press("Control+s")           # the file moved on, so the hub merges the edit
    until(lambda: "and plums" in f.read_text(), what="the saved edit in the file")
    p.wait_for_timeout(1500)
    assert p.evaluate("window.__same_load") is True, "the page reloaded under the reply"
    assert p.input_value("#rd-popover textarea") == "my reply text"
    p.click("#rd-popover button[data-f=ok]")
    reloaded(p)
    md = f.read_text()
    assert "and plums" in md and "A new paragraph from outside." in md
    (c,) = rdc.parse(md).comments
    assert [r.text for r in c.replies] == ["my reply text"]


# The same save(true) path as Ctrl+S: the autosave timer (`asTmr`) and the click on a task box.
def test_an_autosave_that_merges_waits_for_the_reply_being_written_before_it_reloads(frozen):
    p, f = frozen.page, frozen.site.file
    type_at_end(p, P2, " and plums")
    p.click(".rd-badge")
    p.wait_for_selector("#rd-popover button[data-a=reply]")
    open_reply(frozen, "my reply text")
    mark(p)
    f.write_text(f.read_text() + "\nA new paragraph from outside.\n", encoding="utf-8")
    p.wait_for_selector("#rd-popover .rd-hold")
    p.clock.run_for(3_000)                  # the page's own timer saves, nobody pressed a key
    until(lambda: "and plums" in f.read_text(), what="the autosaved edit in the file")
    p.wait_for_timeout(1500)
    assert p.evaluate("window.__same_load") is True, "the page reloaded under the reply"
    assert p.input_value("#rd-popover textarea") == "my reply text"
    p.click("#rd-popover button[data-f=ok]")
    reloaded(p)
    md = f.read_text()
    assert "and plums" in md and "A new paragraph from outside." in md
    (c,) = rdc.parse(md).comments
    assert [r.text for r in c.replies] == ["my reply text"]


def test_a_ticked_task_box_that_merges_waits_for_the_reply_being_written_before_it_reloads(frozen):
    p, f = frozen.page, frozen.site.file
    mark(p)
    f.write_text(f.read_text() + "\n- [ ] first task\n- [ ] second task\n", encoding="utf-8")
    reloaded(p)
    p.wait_for_selector("main input[type=checkbox]")
    p.click(".rd-badge")
    p.wait_for_selector("#rd-popover button[data-a=reply]")
    open_reply(frozen, "my reply text")
    mark(p)
    f.write_text(f.read_text() + "\nA new paragraph from outside.\n", encoding="utf-8")
    p.wait_for_selector("#rd-popover .rd-hold")
    p.locator("main input[type=checkbox]").first.click()
    until(lambda: "- [x] first task" in f.read_text(), what="the ticked box in the file")
    p.wait_for_timeout(1500)
    assert p.evaluate("window.__same_load") is True, "the page reloaded under the reply"
    assert p.input_value("#rd-popover textarea") == "my reply text"
    p.click("#rd-popover button[data-f=ok]")
    reloaded(p)
    md = f.read_text()
    assert "- [x] first task" in md and "- [ ] second task" in md and "A new paragraph from outside." in md
    (c,) = rdc.parse(md).comments
    assert [r.text for r in c.replies] == ["my reply text"]


def test_while_a_merge_waits_for_a_reply_a_later_save_does_not_overwrite_what_the_merge_brought_in(frozen):
    # The page still shows the old text, so it must not hold the hash of the merged one: a save
    # of a paragraph the file changed meanwhile would then land on it without a merge.
    p, f = frozen.page, frozen.site.file
    type_at_end(p, P2, " and plums")
    p.click(".rd-badge")
    p.wait_for_selector("#rd-popover button[data-a=reply]")
    open_reply(frozen, "my reply text")
    f.write_text(f.read_text().replace("Last paragraph.", "Last paragraph, rewritten outside."), encoding="utf-8")
    p.wait_for_selector("#rd-popover .rd-hold")
    p.keyboard.press("Control+s")
    until(lambda: "and plums" in f.read_text(), what="the first save in the file")
    # Typing is refused while a save is out: wait until the page has taken its answer in.
    until(lambda: p.text_content("#rd-state") == "Editing", what="the page to take in the first save")
    # The open thread covers that paragraph, so it takes the caret without a click.
    p.focus("main p:nth-of-type(4)")
    p.keyboard.press(key("Control+End"))
    p.keyboard.type(" and kiwis")
    p.keyboard.press("Control+s")
    until(lambda: "and kiwis" in f.read_text(), what="the second save in the file")
    assert "rewritten outside" in f.read_text(), "the second save overwrote the change made outside"
    assert p.input_value("#rd-popover textarea") == "my reply text"


def test_while_a_reply_holds_the_reload_the_edit_and_the_reply_are_taken_after_more_writes_than_the_hub_keeps(
        frozen, monkeypatch):
    # The page keeps the hash of the text on screen until the reload runs, and tells the hub to keep that
    # version beside the newest ones (SPEC 7.4): once, not for every write that comes while it holds.
    p, f = frozen.page, frozen.site.file
    # The hub answers the pin late, as a slow runner does: the request is still out when the hold note is drawn.
    real_pin = hub_live.LiveDocument.pin
    monkeypatch.setattr(hub_live.LiveDocument, "pin", lambda self, h: (time.sleep(0.4), real_pin(self, h))[1])
    pins = []
    p.on("requestfinished", lambda r: pins.append(r.post_data) if r.url.endswith("/_/pin") else None)
    type_at_end(p, P2, " and plums")
    p.click(".rd-badge")
    p.wait_for_selector("#rd-popover button[data-a=reply]")
    open_reply(frozen, "my reply text")
    mark(p)
    held = md_hash(f.read_text())
    update_file(f, lambda t: t + "\nA new paragraph from outside.\n")
    p.wait_for_selector("#rd-popover .rd-hold")
    until(lambda: pins or p.wait_for_timeout(20), what="the page telling the hub which version it keeps")
    many = max(hub_live.VERSIONS, hub_state.VERSIONS_KEPT) + 1
    writes_from_outside(f, frozen.site.hub.entry(DOC).live, many)
    p.keyboard.press("Control+s")
    until(lambda: "and plums" in f.read_text(), what="the saved edit in the file")
    # A send is refused while a save is out: wait until the page has taken its answer in.
    until(lambda: p.text_content("#rd-state") == "Editing", what="the page to take in the save")
    assert p.evaluate("window.__same_load") is True, "the page reloaded under the reply"
    p.click("#rd-popover button[data-f=ok]")
    reloaded(p)
    md = f.read_text()
    assert "A new paragraph from outside." in md and f"From outside {many - 1}." in md
    (c,) = rdc.parse(md).comments
    assert [r.text for r in c.replies] == ["my reply text"]
    assert [json.loads(d)["hash"] for d in pins] == [held]


def fails(e):
    raise e


@pytest.mark.parametrize("answer", ["refused", "failed"])
def test_a_page_asks_the_hub_to_keep_its_version_once_and_again_only_after_a_request_that_failed(thread, monkeypatch,
                                                                                                  answer):
    # One request at a time for the version the page holds: a change that comes while it is out asks nothing. A
    # version the hub does not know (409) stays unknown, so it is never asked for again; a request that failed
    # otherwise is made again with a change that comes after its answer.
    p, f = thread.page, thread.site.file
    live = thread.site.hub.entry(DOC).live
    asked, out, sent, heard = [], [], [], []
    monkeypatch.setattr(hub_live.LiveDocument, "pin", lambda self, h: asked.append(h) or (
        False if answer == "refused" else fails(RuntimeError("the disk went away"))))
    p.on("request", lambda r: sent.append(json.loads(r.post_data)["hash"]) if r.url.endswith("/_/pin") else None)
    p.route("**/_/pin", lambda route: out.append(route))
    # The stream's messages, as the page's EventSource takes them in: the page loads again to open it under the
    # session that counts them.
    cdp = p.context.new_cdp_session(p)
    cdp.on("Network.eventSourceMessageReceived", lambda e: heard.append(e["eventName"]))
    cdp.send("Network.enable")
    p.reload()
    p.wait_for_selector("#rd-menu-btn", state="attached")
    p.click(".rd-badge")
    p.wait_for_selector("#rd-popover button[data-a=reply]")
    open_reply(thread, "my reply text")

    def hears(n):
        until(lambda: heard.count("changed") >= n or p.wait_for_timeout(20), what=f"the page to hear {n} writes")
        p.evaluate("0")                                  # and its listener to have run

    writes_from_outside(f, live, 1)
    p.wait_for_selector("#rd-popover .rd-hold")
    until(lambda: out or p.wait_for_timeout(20), what="the page asking the hub to keep its version")
    writes_from_outside(f, live, 2)
    hears(3)
    assert len(sent) == 1, "a change that came while the request was out asked again"
    with p.expect_response(lambda r: r.url.endswith("/_/pin")):
        out[0].continue_()
    p.unroute("**/_/pin")
    if answer == "failed":
        until(lambda: writes_from_outside(f, live, 1) or p.wait_for_timeout(20) or len(asked) > 1,
              what="a change after the failed request to ask again")
        assert len(sent) > 1 and len(set(sent)) == 1                    # the same version each time
    else:
        writes_from_outside(f, live, 3)
        hears(6)
        assert len(sent) == 1 and len(asked) == 1
    assert p.input_value("#rd-popover textarea") == "my reply text"


def test_a_page_that_keeps_holding_its_reload_pins_its_version_again_every_day_until_the_hold_ends(frozen):
    # The hub deletes a pin last pinned more than 7 days before when it starts (SPEC 7.4), and a form can be
    # held longer than that: the page pins the same version again once a day while it holds, so a restart
    # in the week after finds the pin a day old at most.
    p, f = frozen.page, frozen.site.file
    pins = []
    answered = []
    p.on("request", lambda r: pins.append(json.loads(r.post_data)["hash"]) if r.url.endswith("/_/pin") else None)
    # Counted when the body is in, not at the headers: post() reads the body before it drops its 30-second wait.
    p.on("requestfinished", lambda r: answered.append(1) if r.url.endswith("/_/pin") else None)
    # The first pin's answer is held back, as a slow runner holds it: the test must not move the clock
    # while that request is out, or the page's own 30-second wait for it runs out and gives it up.
    held_pin = []
    p.route("**/_/pin", lambda route: route.continue_() if held_pin else held_pin.append(route))
    p.click(".rd-badge")
    p.wait_for_selector("#rd-popover button[data-a=reply]")
    open_reply(frozen, "my reply text")
    held = md_hash(f.read_text())
    update_file(f, lambda t: t + "\nA new paragraph from outside.\n")
    p.wait_for_selector("#rd-popover .rd-hold")
    until(lambda: pins or p.wait_for_timeout(20), what="the page pinning its version")
    until(lambda: held_pin or p.wait_for_timeout(20), what="the first pin held back")
    held_pin[0].continue_()
    until(lambda: answered or p.wait_for_timeout(20), what="the hub answering the first pin")
    p.evaluate("0")                                  # and the page to have taken the answer in
    p.clock.fast_forward(23 * 3_600_000)
    p.evaluate("0")
    assert pins == [held], "the page pinned again before a day had passed"
    p.clock.fast_forward(2 * 3_600_000)
    until(lambda: len(pins) > 1 or p.wait_for_timeout(20), what="the page pinning its version again")
    assert pins == [held, held]
    until(lambda: len(answered) > 1 or p.wait_for_timeout(20), what="the hub answering the second pin")
    p.evaluate("0")                                  # the day counts from the answer, which the page has taken in
    p.clock.fast_forward(24 * 3_600_000)
    until(lambda: len(pins) > 2 or p.wait_for_timeout(20), what="the page pinning its version a third time")
    mark(p)
    p.click("#rd-popover button[data-f=no]")        # the form is cancelled: the hold is over, the page reloads
    reloaded(p)


def test_a_page_whose_document_is_gone_stops_renewing_its_pin(frozen):
    # meetDocGone clears the hourly timer of the renewal at once, not at its next tick. The timer is the only
    # thing to see: post() refuses everything once the document is gone, so no request tells. The hour
    # interval is watched by wrapping the clock's setInterval.
    p, f = frozen.page, frozen.site.file
    p.add_init_script("""
      (function () {
        window.__hourly = [];
        var set = window.setInterval, clear = window.clearInterval;
        window.setInterval = function (fn, ms) {
          var id = set.apply(this, arguments);
          if (ms === 3600000) window.__hourly.push(id);
          return id;
        };
        window.clearInterval = function (id) {
          window.__hourly = window.__hourly.filter(function (i) { return i !== id; });
          return clear.apply(this, arguments);
        };
      })();""")
    p.reload()
    p.wait_for_selector("#rd-menu-btn", state="attached")
    p.click(".rd-badge")
    p.wait_for_selector("#rd-popover button[data-a=reply]")
    open_reply(frozen, "my reply text")
    update_file(f, lambda t: t + "\nA new paragraph from outside.\n")
    p.wait_for_selector("#rd-popover .rd-hold")
    until(lambda: p.evaluate("window.__hourly.length") or p.wait_for_timeout(20), what="the renewal timer to start")
    assert frozen.site.hub.forget_root("work").name == "work"
    until(lambda: "no longer on the sheaf hub" in (p.inner_text("#rd-notice") if p.query_selector("#rd-notice") else "")
          or p.wait_for_timeout(20), what="the notice that the document is gone")
    assert p.evaluate("window.__hourly.length") == 0, "the renewal timer still runs"


def test_a_renewal_of_the_pin_that_failed_is_made_again_within_the_hour(frozen):
    p, f = frozen.page, frozen.site.file
    pins, fail = [], [False]
    p.on("request", lambda r: pins.append(1) if r.url.endswith("/_/pin") else None)
    p.route("**/_/pin", lambda route: route.abort() if fail[0] else route.continue_())
    p.click(".rd-badge")
    p.wait_for_selector("#rd-popover button[data-a=reply]")
    open_reply(frozen, "my reply text")
    update_file(f, lambda t: t + "\nA new paragraph from outside.\n")
    p.wait_for_selector("#rd-popover .rd-hold")
    until(lambda: pins or p.wait_for_timeout(20), what="the page pinning its version")
    fail[0] = True
    p.clock.fast_forward(25 * 3_600_000)
    until(lambda: len(pins) > 1 or p.wait_for_timeout(20), what="the renewal being tried")
    fail[0] = False
    p.clock.fast_forward(3_600_000)
    until(lambda: len(pins) > 2 or p.wait_for_timeout(20), what="the renewal being made again")
    mark(p)
    p.click("#rd-popover button[data-f=no]")
    reloaded(p)


# The page's own reloads ask nothing: a reload that a form would meet waits for it (an open form or a send out), and says so
# above it.
def settling_with_its_save_held(frozen):
    """An edit on screen, then a change from outside: the page settles (it saves what is on screen, then
    reloads onto the merged file), and that save is held. Returns the held requests."""
    p, f, held = frozen.page, frozen.site.file, []
    type_at_end(p, P2, " and plums")
    p.route("**/_/save", lambda route: held.append(route))
    outside_change(frozen)
    until(lambda: held or p.wait_for_timeout(20), what="the save of the settle to go out")
    return held


def release_the_save(p, held):
    held[0].continue_()
    p.unroute("**/_/save")


# settle() saved what was on screen, then reloaded without looking at the forms again: a reply opened and
# typed while that save was out met the page's own reload and the leave question. Leave lost the reply; Stay
# left the page refusing every key typed in the text, as if it were still settling.
def test_a_reply_typed_while_the_settle_saves_holds_the_reload_without_a_question(frozen):
    p, f = frozen.page, frozen.site.file
    dialogs = asked(p)
    held = settling_with_its_save_held(frozen)
    p.click(".rd-badge")
    open_reply(frozen, "my reply text")
    mark(p)
    release_the_save(p, held)
    until(lambda: "and plums" in f.read_text(), what="the settled edit in the file")
    p.wait_for_selector("#rd-popover .rd-hold")
    p.wait_for_timeout(1500)
    assert dialogs == [], "the page's own reload asked the leave question"
    assert p.evaluate("window.__same_load") is True, "the page reloaded under the reply"
    assert p.input_value("#rd-popover textarea") == "my reply text"
    p.click("#rd-popover button[data-f=ok]")
    reloaded(p)
    md = f.read_text()
    assert "and plums" in md and "A new paragraph from outside." in md
    (c,) = rdc.parse(md).comments
    assert [r.text for r in c.replies] == ["my reply text"]
    assert dialogs == []


def test_the_text_takes_keys_again_once_the_settle_waits_for_a_reply(frozen):
    p, f = frozen.page, frozen.site.file
    asked(p)
    held = settling_with_its_save_held(frozen)
    p.click(".rd-badge")
    open_reply(frozen, "my reply text")
    release_the_save(p, held)
    p.wait_for_selector("#rd-popover .rd-hold")
    until(lambda: p.text_content("#rd-state") == "Editing", what="the page to take in the settle's save")
    p.focus("main p:nth-of-type(4)")
    p.keyboard.press(key("Control+End"))
    p.keyboard.type(" and kiwis")
    assert "and kiwis" in p.inner_text("main"), "the text still refuses keys after the settle"
    p.keyboard.press("Control+s")
    until(lambda: "and kiwis" in f.read_text(), what="the second edit in the file")
    md = f.read_text()
    assert "and plums" in md and "A new paragraph from outside." in md, "the second save overwrote the first"
    assert p.input_value("#rd-popover textarea") == "my reply text"


def test_without_a_form_the_settle_saves_and_reloads_without_a_question(frozen):
    p, f = frozen.page, frozen.site.file
    dialogs = asked(p)
    held = settling_with_its_save_held(frozen)
    mark(p)
    release_the_save(p, held)
    reloaded(p)
    md = f.read_text()
    assert "and plums" in md and "A new paragraph from outside." in md
    p.wait_for_selector("main p:nth-of-type(3):has-text('and plums')")
    assert dialogs == []


# A save that the hub merged gave the page the hash of the merged file, though the page still showed the text it
# had and its block numbers until its reload. A task box ticked meanwhile was saved by its old number into the new
# file ("Last paragraph." became a second task list), and once the reload waited for a reply, what was typed next
# went by those numbers too (skipped on the code block, and on screen only). A save that brings a reload keeps the
# hash of the text on screen, so the hub merges whatever is saved before that reload.
@pytest.mark.parametrize("start", ["the page settles", "a save that merges"])
@pytest.mark.parametrize("tick", [True, False])
def test_what_is_saved_while_the_reload_waits_for_a_reply_is_merged_onto_the_change_from_outside(frozen, start, tick):
    p, f = frozen.page, frozen.site.file
    mark(p)
    f.write_text(f.read_text() + "\n- [ ] first task\n- [ ] second task\n", encoding="utf-8")
    reloaded(p)
    p.wait_for_selector("main input[type=checkbox]")
    type_at_end(p, P2, " and plums")
    held = []
    p.route("**/_/save", lambda route: held.append(route))

    def from_outside():
        f.write_text(f.read_text().replace("Second paragraph", "A paragraph from outside.\n\nSecond paragraph", 1),
                     encoding="utf-8")
    if start == "the page settles":
        from_outside()
    else:
        p.keyboard.press("Control+s")
    until(lambda: held or p.wait_for_timeout(20), what="the first save to go out")
    if start == "a save that merges":
        from_outside()                      # the file moves on while that save is out
        p.wait_for_timeout(800)
    if tick:
        p.locator("main input[type=checkbox]").first.click()       # its save waits for the first
        held.pop(0).continue_()
        until(lambda: held or p.wait_for_timeout(20), what="the save of the tick to go out")
    p.click(".rd-badge")
    open_reply(frozen, "my reply text")
    held.pop(0).continue_()
    p.unroute("**/_/save")
    p.wait_for_selector("#rd-popover .rd-hold")
    until(lambda: p.text_content("#rd-state") == "Editing", what="the page to take in the last save")
    p.focus("main p:nth-of-type(4)")
    p.keyboard.press(key("Control+End"))
    p.keyboard.type(" and kiwis")
    p.keyboard.press("Control+s")
    until(lambda: "and kiwis" in f.read_text(), what="the edit made while the reload waits")
    md = f.read_text()
    assert md.count("A paragraph from outside.") == 1
    assert "about pears. and plums" in md
    assert "Last paragraph. and kiwis" in md
    assert md.count("first task") == 1 and ("- [x] first task" in md) is tick and "- [ ] second task" in md
    assert "at the same time" not in md and "was deleted in the file" not in md
    assert p.input_value("#rd-popover textarea") == "my reply text"


# What is saved before that reload is merged against the text on screen, and so was the page's own first save
# of the block: a second tick in the list, or more typed in the paragraph, met a file block that differed from
# the page's text and got the note "Edited on this page and in the file at the same time". The page sends with
# each edit what it last saved of that block, and the hub knows its own save in the file by it.
def tasks_above_the_last_paragraph(tab):
    p, f = tab.page, tab.site.file
    mark(p)
    f.write_text(f.read_text().replace("Last paragraph.", "- [ ] first task\n- [ ] second task\n\nLast paragraph.", 1),
                 encoding="utf-8")
    reloaded(p)
    p.wait_for_selector("main input[type=checkbox]")
    return p.locator("main input[type=checkbox]")


def split_the_last_paragraph(p):
    """In edit mode, Enter at the end of "Last paragraph." and a line typed after it."""
    p.keyboard.press("e")
    p.click("main p:last-of-type")
    p.keyboard.press(key("End"))
    p.keyboard.press("Enter")
    p.keyboard.type("Split off.")


def no_note_and_the_ticks(md, second):
    assert "at the same time" not in md, "the page's own first save was taken for a change in the file"
    assert md.count("first task") == 1 and "- [x] first task" in md
    assert md.count("second task") == 1 and ("- [x] second task" in md) is second


@pytest.mark.parametrize("outside", [None, ("Last paragraph.", "Last paragraph, edited outside."),
                                     ("Second paragraph", "A paragraph from outside.\n\nSecond paragraph")],
                         ids=["a split paragraph", "an edit below from outside", "a paragraph inserted above from outside"])
@pytest.mark.parametrize("second", [True, False])
def test_a_second_tick_while_the_first_ticks_save_is_out_writes_no_conflict_note(frozen, outside, second):
    p, f = frozen.page, frozen.site.file
    boxes = tasks_above_the_last_paragraph(frozen)
    if outside is None:
        split_the_last_paragraph(p)         # the first tick's save takes the split with it: a remap
    held = []
    p.route("**/_/save", lambda route: route.continue_() if held else held.append(route))
    boxes.nth(0).click()
    until(lambda: held or p.wait_for_timeout(20), what="the first tick's save to go out")
    if outside:
        f.write_text(f.read_text().replace(*outside, 1), encoding="utf-8")
    p.wait_for_timeout(800)
    if second:
        boxes.nth(1).click()                # its save waits for the first
    mark(p)
    held[0].continue_()
    reloaded(p)
    p.wait_for_timeout(500)
    md = f.read_text()
    no_note_and_the_ticks(md, second)
    assert md.count(outside[1] if outside else "Split off.") == 1


@pytest.mark.parametrize("second", [True, False])
def test_a_second_tick_while_a_reply_holds_the_reload_of_the_first_writes_no_conflict_note(frozen, second):
    p, f = frozen.page, frozen.site.file
    boxes = tasks_above_the_last_paragraph(frozen)
    p.click(".rd-badge")
    open_reply(frozen, "my reply text")
    mark(p)
    outside_change(frozen)
    p.wait_for_selector("#rd-popover .rd-hold")
    boxes.nth(0).click()                    # merged onto the change from outside; the reload waits
    until(lambda: "- [x] first task" in f.read_text(), what="the first tick in the file")
    if second:
        boxes.nth(1).click()
        until(lambda: "- [x] second task" in f.read_text(), what="the second tick in the file")
    p.wait_for_timeout(500)
    assert p.input_value("#rd-popover textarea") == "my reply text"
    no_note_and_the_ticks(f.read_text(), second)


def test_a_paragraph_saved_twice_while_the_reload_waits_for_a_reply_writes_no_conflict_note(frozen):
    p, f = frozen.page, frozen.site.file
    type_at_end(p, P2, " and plums")
    p.click(".rd-badge")
    open_reply(frozen, "my reply text")
    mark(p)
    outside_change(frozen)
    p.wait_for_selector("#rd-popover .rd-hold")
    p.keyboard.press("Control+s")           # merged onto the change from outside; the reload waits
    until(lambda: "and plums" in f.read_text(), what="the first save in the file")
    until(lambda: p.text_content("#rd-state") == "Editing", what="the page to take in the first save")
    p.focus(P2)
    p.keyboard.press(key("Control+End"))
    p.keyboard.type(" and kiwis")
    p.keyboard.press("Control+s")
    until(lambda: "and kiwis" in f.read_text(), what="the second save of the paragraph")
    md = f.read_text()
    assert "at the same time" not in md, "the page's own first save was taken for a change in the file"
    assert "about pears. and plums and kiwis" in md and md.count("about pears") == 1
    assert p.input_value("#rd-popover textarea") == "my reply text"


# A save of a paragraph that a reply holds the reload of, merged onto a change from outside, splits it in two (Enter),
# and the page still shows it as one: the next save of it met the two in the file, wrote them again under the first,
# and noted a conflict when the first line had changed too; a second save that took the split line out left it.
@pytest.mark.parametrize("then", ["more typed on the split line", "the first line changed too", "the split line deleted"])
def test_a_paragraph_the_first_save_split_takes_the_next_save_while_the_reload_waits_for_a_reply(frozen, then):
    p, f = frozen.page, frozen.site.file
    last = "main p:last-of-type"
    p.keyboard.press("e")
    p.click(".rd-badge")
    open_reply(frozen, "my reply text")
    mark(p)
    outside_change(frozen)
    p.wait_for_selector("#rd-popover .rd-hold")
    p.focus(last)
    p.keyboard.press(key("Control+End"))
    if then == "the first line changed too":
        p.keyboard.press("ArrowLeft")
        p.keyboard.type(", edited")
        p.keyboard.press(key("End"))
    p.keyboard.press("Enter")
    p.keyboard.type("Split off.")
    p.keyboard.press("Control+s")           # merged onto the change from outside, and split: the reload waits
    until(lambda: "Split off." in f.read_text(), what="the first save in the file")
    until(lambda: p.text_content("#rd-state") == "Editing", what="the page to take in the first save")
    before = f.read_text()
    p.focus(last)
    p.keyboard.press(key("Control+End"))
    if then == "the split line deleted":
        for _ in "Split off.!":
            p.keyboard.press("Backspace")
    else:
        p.keyboard.type(" More.")
    p.keyboard.press("Control+s")
    until(lambda: f.read_text() != before, what="the second save in the file")
    md = f.read_text()
    assert "at the same time" not in md, "the page's own first save was taken for a change in the file"
    assert md.count("Split off") == (0 if then == "the split line deleted" else 1), md
    assert ("Split off. More." in md) is (then != "the split line deleted")
    assert ("Last paragraph, edited." in md) is (then == "the first line changed too")
    assert "A new paragraph from outside." in md
    assert p.input_value("#rd-popover textarea") == "my reply text"


# A block already names an earlier save that was merged (`saved`, the reload waits for the reply), then a save of it
# is given up after 120 s although the hub wrote it, and the block is typed in again before the next save: the one
# `saved` field held the first save, so the file's text (the second save) was met as a change from outside and the
# page's version was written with a conflict note. The save that got no answer goes again first, under its own request
# id, and the hub answers `again`; the save after it then names it (SPEC 8.5, 10.3).
def test_a_block_typed_in_again_after_a_save_given_up_that_the_hub_wrote_meets_no_conflict_with_it(frozen):
    p, f = frozen.page, frozen.site.file
    last = "main p:last-of-type"
    p.keyboard.press("e")
    p.click(".rd-badge")
    open_reply(frozen, "my reply text")
    outside_change(frozen)
    p.wait_for_selector("#rd-popover .rd-hold")
    p.focus(last)
    p.keyboard.press(key("Control+End"))
    p.keyboard.type(" One.")
    p.keyboard.press("Control+s")           # merged onto the change from outside: the reload waits for the reply
    until(lambda: " One." in f.read_text(), what="the first save in the file")
    until(lambda: p.text_content("#rd-state") == "Editing", what="the page to take in the first save")
    bodies, held = [], []

    def written_never_answered(route):
        bodies.append(route.request.post_data_json)
        if not held:
            held.append(route)
            route.fetch()
        else:
            route.continue_()

    p.route("**/_/save", written_never_answered)
    p.focus(last)
    p.keyboard.press(key("Control+End"))
    p.keyboard.type(" Two.")
    p.keyboard.press("Control+s")
    until(lambda: " Two." in f.read_text(), what="the second save in the file")
    p.clock.fast_forward(120_500)
    toasted(p, "The hub is unreachable; nothing was saved. Your edits stay on screen.")
    # the autosave that waited behind the held save goes now, and the page takes no typing while it is out
    until(lambda: len(bodies) >= 2 and p.text_content("#rd-state") == "Editing", what="the save to go again")
    p.focus(last)
    p.keyboard.press(key("Control+End"))
    p.keyboard.type(" Three.")
    p.keyboard.press("Control+s")
    until(lambda: len(bodies) >= 3 and " Three." in f.read_text(), what="the third save in the file")
    p.unroute_all(behavior="ignoreErrors")      # the held save may still be in route.fetch
    second, again, third = bodies[:3]
    assert second["edits"][0]["saved"] and second["rid"]            # it names the first save, which was merged
    assert again["rid"] == second["rid"] and again["hash"] == second["hash"], "the save that got no answer did not go again first"
    assert [e["html"] for e in again["edits"]] == [e["html"] for e in second["edits"]]
    assert third["rid"] != second["rid"] and third["edits"][0]["saved"] == second["edits"][0]["html"]
    md = f.read_text()
    assert "at the same time" not in md, md
    assert md.count(" Two.") == 1 and md.count(" One.") == 1 and " One. Two. Three." in md, md


# The same split, and then a paragraph the file puts between its two halves before the next save: the split line was
# left after the edit a second time, and with the first line changed a note quoted the page's own words as the file's.
@pytest.mark.parametrize("first", ["as rendered", "changed too"])
def test_a_paragraph_the_file_puts_between_the_halves_of_the_first_save_stays_and_the_split_line_is_written_once(
        frozen, first):
    p, f = frozen.page, frozen.site.file
    last = "main p:last-of-type"
    p.keyboard.press("e")
    p.click(".rd-badge")
    open_reply(frozen, "my reply text")
    mark(p)
    outside_change(frozen)
    p.wait_for_selector("#rd-popover .rd-hold")
    p.focus(last)
    p.keyboard.press(key("Control+End"))
    if first == "changed too":
        p.keyboard.press("ArrowLeft")
        p.keyboard.type(", edited")
        p.keyboard.press(key("End"))
    p.keyboard.press("Enter")
    p.keyboard.type("Split off.")
    p.keyboard.press("Control+s")           # merged onto the change from outside, and split: the reload waits
    until(lambda: "Split off." in f.read_text(), what="the first save in the file")
    until(lambda: p.text_content("#rd-state") == "Editing", what="the page to take in the first save")
    f.write_text(f.read_text().replace("\n\nSplit off.", "\n\nA line from outside.\n\nSplit off."), encoding="utf-8")
    before = f.read_text()
    p.focus(last)
    p.keyboard.press(key("Control+End"))
    p.keyboard.type(" More.")
    p.keyboard.press("Control+s")
    until(lambda: f.read_text() != before, what="the second save in the file")
    md = f.read_text()
    line = "Last paragraph, edited." if first == "changed too" else "Last paragraph."
    assert f"{line}\n\nA line from outside.\n\nSplit off. More.\n\nA new paragraph from outside." in md, md
    assert md.count("Split off") == 1 and "at the same time" not in md
    assert p.input_value("#rd-popover textarea") == "my reply text"


# Two paragraphs that the first of those saves wrote with the same words, and a paragraph the file adds after them
# before the next save of both: each edit took the same file block for its own, and the second paragraph's words
# were written over with no note, on screen only until the reload took them away.
def paragraphs_saying(p, text):
    texts = p.evaluate("Array.from(document.querySelectorAll('main p')).map(e => e.textContent.trim())")
    return [k for k, t in enumerate(texts) if t == text]


def type_into(p, k, keys, text):
    p.locator("main p").nth(k).focus()
    for k in keys:
        p.keyboard.press(key(k))
    p.keyboard.type(text)


@pytest.mark.parametrize("outside", ["a paragraph added after them", "nothing"])
def test_two_paragraphs_the_first_save_wrote_alike_keep_the_next_save_of_each_while_the_reload_waits(frozen, outside):
    p, f = frozen.page, frozen.site.file
    mark(p)
    f.write_text(f.read_text().replace("Last paragraph.", "TBD\n\nTBD\n\nLast paragraph."), encoding="utf-8")
    reloaded(p)
    until(lambda: len(paragraphs_saying(p, "TBD")) == 2, what="the two TBD paragraphs")
    p.keyboard.press("e")
    p.click(".rd-badge")
    open_reply(frozen, "my reply text")
    mark(p)
    outside_change(frozen)
    p.wait_for_selector("#rd-popover .rd-hold")
    for k in paragraphs_saying(p, "TBD"):
        type_into(p, k, ["Control+End", "Shift+Home"], "Done")
    p.keyboard.press("Control+s")           # merged onto the change from outside: the reload waits
    until(lambda: f.read_text().count("Done\n\nDone\n\n") == 1, what="the first save in the file")
    until(lambda: p.text_content("#rd-state") == "Editing", what="the page to take in the first save")
    if outside != "nothing":
        f.write_text(f.read_text().replace("Done\n\nDone\n\n", "Done\n\nDone\n\nA note from the agent.\n\n"),
                     encoding="utf-8")
        p.wait_for_timeout(500)
    before = f.read_text()
    first, second = paragraphs_saying(p, "Done")
    type_into(p, first, ["Control+End"], ", first one")
    type_into(p, second, ["Control+End"], ", second one")
    p.keyboard.press("Control+s")
    until(lambda: f.read_text() != before, what="the second save in the file")
    md = f.read_text()
    assert "Done, first one" in md and "Done, second one" in md, md
    assert p.input_value("#rd-popover textarea") == "my reply text"


# The file indents the paragraph being edited into a code block, the same words in a block the page cannot edit:
# the settle's save puts the page's text in a note on it, as on main, and does not take the code block for the
# page's own save and drop the edit.
def test_an_edit_of_a_paragraph_the_file_indents_into_code_is_kept_in_a_note(frozen):
    p, f = frozen.page, frozen.site.file
    type_at_end(p, P2, " and plums")
    mark(p)
    f.write_text(f.read_text().replace("Second paragraph, about pears.", "    Second paragraph, about pears.", 1),
                 encoding="utf-8")
    reloaded(p)
    until(lambda: "and plums" in f.read_text(), what="the page's text in the file")
    md = f.read_text()
    [note] = [c for c in rdc.parse(md).comments if c.by == "sheaf"]
    assert "and plums" in note.body and "    Second paragraph, about pears." in md


# `saved` goes only with a block that the page saved while it kept the hash of the text on screen: one saved
# against the hash of the file, or never saved, is the base block itself, and an edit twice the size of the
# block met the hub's limit on a body sooner.
def test_a_save_says_what_it_saved_before_only_for_a_block_saved_while_the_page_kept_its_hash(frozen):
    p, f = frozen.page, frozen.site.file
    bodies = []
    p.on("request", lambda r: bodies.append(json.loads(r.post_data)) if "/_/save" in r.url else None)
    type_at_end(p, P2, " and plums")
    p.keyboard.press("Control+s")                   # against the hash of the file
    until(lambda: "and plums" in f.read_text(), what="the first save")
    until(lambda: p.text_content("#rd-state") == "Editing", what="the page to take in the first save")
    p.click(".rd-badge")
    open_reply(frozen, "my reply text")
    mark(p)
    outside_change(frozen)
    p.wait_for_selector("#rd-popover .rd-hold")
    for words in (" and kiwis", " and figs"):       # merged, and the page keeps its hash until the reload
        until(lambda: p.text_content("#rd-state") == "Editing", what="the page to take in the last save")
        p.focus(P2)
        p.keyboard.press(key("Control+End"))
        p.keyboard.type(words)
        p.keyboard.press("Control+s")
        until(lambda: words in f.read_text(), what="the save of" + words)
    assert [[("saved" in e) for e in b["edits"]] for b in bodies] == [[False], [False], [True]]
    assert "and kiwis" in bodies[2]["edits"][0]["saved"] and "and figs" not in bodies[2]["edits"][0]["saved"]
    md = f.read_text()
    assert "about pears. and plums and kiwis and figs" in md and "at the same time" not in md


def test_a_change_from_outside_to_the_list_between_two_ticks_still_gets_its_note(frozen):
    p, f = frozen.page, frozen.site.file
    boxes = tasks_above_the_last_paragraph(frozen)
    split_the_last_paragraph(p)
    held = []
    p.route("**/_/save", lambda route: held.append(route))
    boxes.nth(0).click()
    until(lambda: held or p.wait_for_timeout(20), what="the first tick's save to go out")
    boxes.nth(1).click()
    held.pop(0).continue_()
    until(lambda: held or p.wait_for_timeout(20), what="the second tick's save to go out")
    f.write_text(f.read_text().replace("- [ ] second task", "- [ ] second task, renamed outside", 1), encoding="utf-8")
    p.wait_for_timeout(800)
    mark(p)
    release_the_save(p, held)
    reloaded(p)
    md = f.read_text()
    [note] = [c for c in rdc.parse(md).comments if c.by == "sheaf"]
    assert "Edited on this page and in the file at the same time" in note.body and "renamed outside" in note.body
    assert "- [x] first task" in md and "- [x] second task" in md


# Enter in a paragraph: the paragraph is the element being edited, so the browser cannot split it and writes the
# new line as a <div> inside it, which went into the .md as raw <div> and </div> lines around the words. Enter
# after a space leaves it at the cut as a no-break space.
@pytest.mark.parametrize("keys, typed, md", [
    (["End", "Enter"], "Split off.", "Last paragraph.\n\nSplit off.\n"),
    (["End", "Enter", "Enter"], "Split off.", "Last paragraph.\n\nSplit off.\n"),
    (["Home"] + ["ArrowRight"] * 5 + ["Enter"], "", "Last\n\nparagraph.\n"),
    (["End"], " Split off.", "Last paragraph. Split off.\n")],
    ids=["Enter", "Enter twice", "Enter after a space", "no Enter"])
def test_a_line_typed_after_enter_in_a_paragraph_is_a_paragraph_of_its_own_in_the_md(frozen, keys, typed, md):
    p, f = frozen.page, frozen.site.file
    before = f.read_text()
    p.keyboard.press("e")
    p.click("main p:last-of-type")
    for k in keys:
        p.keyboard.press(key(k))
    p.keyboard.type(typed)
    p.keyboard.press("Control+s")
    until(lambda: f.read_text() != before, what="the save in the file")
    got = f.read_text()
    assert "<div>" not in got and "</div>" not in got and " " not in got
    assert got.endswith(md)


def save_with_ctrl_s(p, f):
    """Press Control+S, wait for the file to change, and say whether the page reloads: it does when the save
    changed the number of blocks (the hub answers `remap`, and the page reloads, reloadWhenFree). A script run
    into that reload dies with 'Execution context was destroyed', and the answer's body is gone once the page
    has navigated, so the test reads the file for the answer the hub gave."""
    from sheafmd.blocks import split_md_blocks
    before = f.read_text()
    mark(p)
    p.keyboard.press("Control+s")
    after = until(lambda: f.read_text() != before and f.read_text(), what="the save in the file")
    return len(split_md_blocks(after)) != len(split_md_blocks(before))


def edit_again(p, reloads):
    """Edit mode on the page as the save left it: a page that reloads is waited for (the mark is gone, and
    keeps edit mode on), one that does not is as it was."""
    if reloads:
        reloaded(p)
        p.wait_for_load_state("load")
        p.wait_for_selector("#rd-menu-btn", state="attached")
    # Edit mode is not turned on again: a page that lost it by reloading is the fault this looks for.
    p.wait_for_selector("body.rd-editing main p[contenteditable=true]")


# Keystrokes that left the block as raw HTML in the .md, which the page then locked. Enter inside
# the line an Enter made nests the next <div> in it; Enter at the start of a paragraph and Backspace wraps the
# words in <div><span style="font-size: 1rem">. Every key here was found by driving the page, not guessed.
@pytest.mark.parametrize("keys, typed, md, row", [
    (["End", "Enter", "ArrowLeft", "Enter"], "x", "Last paragraph.\n\nx\n", False),
    (["End", "Enter", "ArrowLeft", "Enter"], "", "Last paragraph.\n", False),
    (["Home", "Enter", "Backspace", "End"], " more", "Last paragraph. more\n", True),
    (["Home", "Enter", "Backspace", "Enter", "ArrowLeft", "Enter"], "x", "x\n\nLast paragraph.\n", True)],
    ids=["Enter in the line Enter made", "the same, nothing typed", "Backspace after Enter at the start",
         "Backspace after Enter at the start, then Enter twice"])
def test_the_keys_that_wrapped_a_paragraph_in_raw_html_save_plain_paragraphs(frozen, keys, typed, md, row):
    from sheafmd import diagnostics
    p, f = frozen.page, frozen.site.file
    before = f.read_text()
    p.keyboard.press("e")
    p.click("main p:last-of-type")
    for k in keys:
        p.keyboard.press(key(k))
    p.keyboard.type(typed)
    if not typed and keys[-1] == "Enter":
        p.keyboard.press("Control+s")
        toasted(p, "→ plan.md")
        assert f.read_text() == before
    else:
        reloads = save_with_ctrl_s(p, f)
        got = f.read_text()
        assert "<div" not in got and "</div>" not in got and "<span" not in got, got
        assert got.endswith(md), got
        # The paragraph is still one the page lets the person edit.
        edit_again(p, reloads)
        assert p.evaluate("document.querySelector('main p:last-of-type').getAttribute('contenteditable')") == "true"
    rows = [r for r in diagnostics.read() if r["kind"] == "markup-unwrapped"]
    assert bool(rows) == row, rows
    if rows:
        assert rows[0]["doc"].endswith("plan.md") and rows[0]["source"] == "hub"


# A paste puts the clipboard's text/html into the paragraph. Each clipboard here is a synthetic text/html written
# by hand in the shape of its source (a mail client, a word processor, a web page); none was copied from the real
# program, and the test says so by its ids.
PASTED = {
    "synthetic-mail-shaped": ('<meta charset="utf-8"><div dir="ltr" style="font-family:Arial"><span style="font-size:12pt">'
                    'Pasted <b>bold</b> and <a href="https://example.com/x">a link</a>.</span></div>'
                    '<div><br></div><div>Second line.</div>',
                    "Pasted **bold** and [a link](https://example.com/x).\n\nSecond line.\n"),
    "synthetic-word-processor-shaped": ('<meta charset="utf-8"><b style="font-weight:normal" id="docs-internal-guid-1">'
                              '<p dir="ltr" style="line-height:1.38"><span style="font-size:11pt;font-weight:400">'
                              'Doc one.</span></p><p dir="ltr"><span style="font-size:11pt">Doc two.</span></p></b>',
                              "Doc one.\n\nDoc two.\n"),
    "synthetic-web-page-shaped": ('<h2 class="title" style="color:red">A heading</h2><p class="lead" style="margin:0">'
                        'Web <em>text</em> <span class="x">here</span>.</p>',
                        "## A heading\n\nWeb *text* here.\n")}


@pytest.mark.parametrize("source", PASTED)
def test_rich_text_pasted_into_a_paragraph_is_saved_as_plain_markdown(frozen, source):
    p, f = frozen.page, frozen.site.file
    html, md = PASTED[source]
    before = f.read_text()
    p.context.grant_permissions(["clipboard-read", "clipboard-write"])
    p.keyboard.press("e")
    p.click("main p:last-of-type")
    p.keyboard.press(key("End"))
    p.evaluate("""async (h) => navigator.clipboard.write([new ClipboardItem({
        'text/html': new Blob([h], {type: 'text/html'}), 'text/plain': new Blob(['plain'], {type: 'text/plain'})})])""", html)
    p.keyboard.press(key("Control+v"))
    reloads = save_with_ctrl_s(p, f)
    got = f.read_text()
    assert "<div" not in got and "<span" not in got and "<a " not in got and "style=" not in got, got
    assert got.endswith(md), got
    edit_again(p, reloads)
    assert p.evaluate("document.querySelectorAll('main p.rd-locked, main h2.rd-locked').length") == 0, "a paragraph was locked"


# Enter where the block is not a paragraph. At the start of a heading the browser writes the new line before the
# heading's words, inside the heading: the words became a paragraph under an empty `## `. In a table cell it writes a
# <br>, and the whole table became raw HTML, a block the page cannot edit again.
HEADED = ("# Plan\n\nFirst paragraph, about apples.\n\n## A heading here\n\n"
          "| Fruit | Note |\n| --- | --- |\n| apples | red ones |\n\nLast paragraph.\n")


@pytest.mark.parametrize("where, keys, typed, md", [
    ("main h2", ["Home", "Enter"], "", None),
    ("main h2", ["Home", "Enter"], "New ", "about apples.\n\n## New A heading here\n\n|"),
    ("main h2", ["Home", "Enter", "ArrowUp"], "Above it.", "about apples.\n\nAbove it.\n\n## A heading here\n\n|"),
    ("main h2", ["End", "Enter"], "Under it.", "## A heading here\n\nUnder it.\n\n|"),
    ("main td:nth-of-type(2)", ["End", "Enter"], "more", "red ones<br>more |"),
    ("main td:nth-of-type(2)", ["End"], ", more", "red ones, more |")],
    ids=["a heading, Enter at the start", "a heading, Enter at the start and words", "a heading, a line typed above",
         "a heading, Enter at the end", "a table cell, Enter", "a table cell, no Enter"])
def test_enter_at_the_start_of_a_heading_or_in_a_table_cell_keeps_the_block_what_it_was(frozen, where, keys, typed, md):
    p, f = frozen.page, frozen.site.file
    mark(p)
    f.write_text(HEADED, encoding="utf-8")
    reloaded(p)
    p.wait_for_selector("main h2")
    p.keyboard.press("e")
    p.click(where)
    for k in keys:
        p.keyboard.press(key(k))
    p.keyboard.type(typed)
    p.keyboard.press("Control+s")
    if md is None:
        toasted(p, "→ plan.md")
        assert f.read_text() == HEADED, "Enter at the start of a heading, and nothing typed, changed the file"
        return
    until(lambda: f.read_text() != HEADED, what="the save in the file")
    got = f.read_text()
    assert md in got and "<table" not in got and "<div" not in got and "## \n" not in got, got
    if where.startswith("main td"):
        # The table is still a table the page can edit.
        p.reload()
        p.wait_for_selector("main td")
        p.keyboard.press("e")
        p.click("main td:nth-of-type(1)")
        p.keyboard.press(key("End"))
        p.keyboard.type(" too")
        p.keyboard.press("Control+s")
        until(lambda: "apples too" in f.read_text(), what="the second edit of the table in the file")
        assert md in f.read_text() and "<table" not in f.read_text()


# The answer of a reply, an edit, a status or a delete that cannot be taken in place (here a comment written in the
# file while it was out, whose anchor the page does not have) reloaded the page at once. Edits typed in the text
# meanwhile raised the leave question then, and Leave lost them but for the draft. They are saved first, as they are
# for a new comment's answer, and the reload asks nothing.
@pytest.mark.parametrize("act", ["reply", "edit", "status", "delete"])
@pytest.mark.parametrize("typed", [True, False])
def test_an_answer_that_reloads_saves_the_edits_typed_while_it_was_out_and_asks_nothing(frozen, act, typed):
    p, f = frozen.page, frozen.site.file
    dialogs = asked(p)
    p.keyboard.press("e")
    p.click(".rd-badge")
    p.wait_for_selector(f"#rd-popover button[data-a={act}]")
    if act in ("reply", "edit"):
        held = send_held(frozen, act, "my words")
    else:
        held = []
        p.route("**/_/comment", lambda route: held.append(route))
        p.click(f"#rd-popover button[data-a={act}]")
        until(lambda: held or p.wait_for_timeout(20), what="the send to go out")
    if typed:
        p.focus(P2)
        p.keyboard.press(key("Control+End"))
        p.keyboard.type(" and plums")
    md = f.read_text()
    blk, s, e = rdc.find_quote(md, "Last paragraph")
    f.write_text(rdc.add_comment(md, blk, s, e, "Last paragraph", "From outside.", "Claude", "2026-10-18T10:00")[0],
                 encoding="utf-8")
    p.wait_for_timeout(800)
    mark(p)
    held.pop(0).continue_()
    p.unroute("**/_/comment")
    until(lambda: dialogs or gone(p), what="the reload or the leave question")
    assert dialogs == [], "the answer's reload asked the leave question over the edit on screen"
    reloaded(p)
    md = f.read_text()
    assert ("about pears. and plums" in md) is typed and "From outside." in md
    assert ("my words" in md) is (act in ("reply", "edit"))


@pytest.mark.parametrize("how", ["a change from outside", "a save that merges"])
def test_the_pages_own_reload_held_for_a_reply_being_typed_asks_nothing(frozen, how):
    p = frozen.page
    dialogs = asked(p)
    if how == "a save that merges":
        type_at_end(p, P2, " and plums")
    p.click(".rd-badge")
    open_reply(frozen, "my reply text")
    mark(p)
    outside_change(frozen)
    p.wait_for_selector("#rd-popover .rd-hold")
    if how == "a save that merges":
        p.keyboard.press("Control+s")
        until(lambda: "and plums" in frozen.site.file.read_text(), what="the merged edit in the file")
    p.wait_for_timeout(1500)
    assert dialogs == [], "the page's own reload asked the leave question"
    assert p.evaluate("window.__same_load") is True
    assert p.input_value("#rd-popover textarea") == "my reply text"


def new_comment_held(tab):
    """On a frozen page: a new comment "about the pears" on "pears", sent with `/_/comment` held; the held requests."""
    p, held = tab.page, []
    select(p, at(P2, "pears"), at(P2, "pears", None))
    p.clock.run_for(50)                     # the Comment button comes on a timer, and this clock stands still
    p.click("#rd-comment-btn")
    p.fill("#rd-popover textarea", "about the pears")
    p.route("**/_/comment", lambda route: held.append(route))
    p.keyboard.press("Control+Enter")
    until(lambda: held or p.wait_for_timeout(20), what="the send to go out")
    return held


# A comment's anchor taken out of a paragraph (its thread deleted in the file, or by this page's Delete) or put into
# it (a new comment's answer) set that paragraph's pristine to what was on screen, words typed and not saved among
# it: they counted as saved, Ctrl+S saved nothing, and the next reload dropped them without the leave question.
# Words typed before the anchor moved and taken out after it leave the paragraph as it was.
@pytest.mark.parametrize("how", ["deleted in the file", "deleted on this page", "a new comment"])
@pytest.mark.parametrize("typed", ["words at the end", "words at the start", "words taken out again", "nothing"])
def test_words_typed_where_a_comments_anchor_goes_or_comes_are_still_unsaved_and_ctrl_s_saves_them(frozen, how, typed):
    p, f = frozen.page, frozen.site.file
    para, held = (P2 if how == "a new comment" else P1), []
    p.keyboard.press("e")
    if how == "deleted on this page":
        p.click(".rd-badge")
        p.wait_for_selector("#rd-popover button[data-a=delete]")
        p.route("**/_/comment", lambda route: held.append(route))
        p.click("#rd-popover button[data-a=delete]")
    elif how == "a new comment":
        held = new_comment_held(frozen)
    if how == "deleted on this page":
        until(lambda: held or p.wait_for_timeout(20), what="the send to go out")
    if typed != "nothing":
        p.focus(para)
        p.keyboard.press(key("Control+Home" if typed == "words at the start" else "Control+End"))
        p.keyboard.type("Now: " if typed == "words at the start" else " and plums")
    mark(p)
    if how == "deleted in the file":
        delete_the_thread(frozen)
    else:
        held.pop(0).continue_()
        p.unroute("**/_/comment")
    badges = 2 if how == "a new comment" else 0
    until(lambda: p.locator("main .rd-badge").count() == badges, what="the anchor to go or come")
    if typed == "words taken out again":
        p.focus(para)
        p.keyboard.press(key("Control+End"))
        for _ in " and plums":
            p.keyboard.press("Backspace")
    p.wait_for_timeout(300)
    assert not gone(p), "the page reloaded"
    edited = typed.startswith("words at")
    assert p.text_content("#rd-state") == ("1 block changed" if edited else "Editing")
    before = f.read_text()
    p.keyboard.press("Control+s")
    if edited:
        until(lambda: f.read_text() != before, what="the typed words in the file")
    else:
        toasted(p, "Nothing changed")
        assert f.read_text() == before
    words = re.sub(r"<!--[\s\S]*?-->", "", f.read_text())
    para_md = "Second paragraph, about pears." if how == "a new comment" else "First paragraph, about apples."
    assert {"words at the end": para_md + " and plums", "words at the start": "Now: " + para_md}.get(typed, para_md) \
        in words.splitlines()
    cs = rdc.parse(f.read_text()).comments
    assert [(c.quote, c.body) for c in cs] == \
        ([("apples", "Why apples?"), ("pears", "about the pears")] if how == "a new comment" else [])


@pytest.mark.parametrize("how", ["deleted in the file", "a new comment"])
def test_words_typed_where_a_comments_anchor_went_or_came_are_saved_by_the_next_reload_without_a_question(frozen, how):
    p, f = frozen.page, frozen.site.file
    dialogs, held = asked(p), []
    p.keyboard.press("e")
    if how == "a new comment":
        held = new_comment_held(frozen)
    p.focus(P2 if how == "a new comment" else P1)
    p.keyboard.press(key("Control+End"))
    p.keyboard.type(" and plums")
    if how == "a new comment":
        held.pop(0).continue_()
        p.unroute("**/_/comment")
    else:
        delete_the_thread(frozen)
    until(lambda: p.locator("main .rd-badge").count() == (2 if how == "a new comment" else 0),
          what="the anchor to go or come")
    p.keyboard.press("Escape")
    mark(p)
    outside_change(frozen)                  # the page settles: it saves what is on screen, then reloads
    reloaded(p)
    until(lambda: "and plums" in f.read_text(), what="the typed words in the file")
    assert dialogs == []
    assert "A new paragraph from outside." in f.read_text()


def replies(f):
    return [r.text for r in rdc.parse(f.read_text()).comments[0].replies]


def test_send_and_ask_starts_one_ask_and_its_answer_comes_into_the_thread(agent, thread):
    open_reply(thread, "and plums?")
    thread.page.click("#rd-popover button[data-f=ask]")
    until(lambda: replies(thread.site.file) == ["and plums?", "The answer."], what="the answer in the file")
    until(lambda: "The answer." in thread.page.inner_text("#rd-popover .rd-scroll"), what="the answer in the thread")
    assert len(agent.calls()) == 1


@pytest.mark.parametrize("what", ["ask", "tell"])
def test_ask_and_tell_of_a_thread_send_the_hash_of_the_text_the_page_holds(agent, thread, what):
    # The id names a thread of that text, and the hub checks it as it checks a reply's.
    held = md_hash(thread.site.file.read_text(encoding="utf-8"))
    sent = []
    thread.page.on("request", lambda r: sent.append(json.loads(r.post_data))
                   if r.method == "POST" and r.url.endswith("/_/" + what) else None)
    thread.page.click(f"#rd-popover button[data-a={what}]")
    until(lambda: sent, what="the request")
    assert [(s["id"], s["hash"]) for s in sent] == [("c1", held)]


def test_send_and_ask_while_a_reload_waits_still_starts_one_ask_and_the_page_sends_no_other(agent, thread):
    # The Ask goes with the reply, so the page that is about to reload has nothing left to send:
    # a follow-up request from it would race the navigation and could be lost with it.
    FakeClaude(agent.dir, sleep=3)           # the Ask is still running when the page has reloaded
    open_reply(thread, "and plums?")
    sent = []
    thread.page.on("request", lambda r: sent.append(r.url) if r.method == "POST" and r.url.endswith("/_/ask") else None)
    mark(thread.page)
    f = thread.site.file
    f.write_text(f.read_text() + "\nA new paragraph from outside.\n", encoding="utf-8")
    thread.page.wait_for_selector("#rd-popover .rd-hold")
    thread.page.click("#rd-popover button[data-f=ask]")
    reloaded(thread.page)
    # The page that comes back is told by the hub that the thread is being answered.
    thread.page.wait_for_selector("#rd-popover .rd-pending")
    until(lambda: replies(f) == ["and plums?", "The answer."], timeout=15, what="the answer in the file")
    until(lambda: "The answer." in thread.page.inner_text("#rd-popover .rd-scroll"), what="the answer in the thread")
    assert len(agent.calls()) == 1
    assert sent == []


def test_a_new_comment_sent_with_ask_while_a_reload_waits_has_its_ask_running_on_the_page_that_comes_back(agent, tab):
    FakeClaude(agent.dir, sleep=3)
    tab.open()
    open_comment_form(tab, P2, "pears")
    tab.page.fill("#rd-popover textarea", "about the pears")
    sent = []
    tab.page.on("request", lambda r: sent.append(r.url) if r.method == "POST" and r.url.endswith("/_/ask") else None)
    mark(tab.page)
    f = tab.site.file
    f.write_text(f.read_text() + "\nA new paragraph from outside.\n", encoding="utf-8")
    tab.page.wait_for_selector("#rd-popover .rd-hold")
    tab.page.click("#rd-popover button[data-f=ask]")
    reloaded(tab.page)
    tab.page.wait_for_selector("#rd-popover .rd-pending")
    until(lambda: replies(f) == ["The answer."], timeout=15, what="the answer in the file")
    until(lambda: "The answer." in tab.page.inner_text("#rd-popover .rd-scroll"), what="the answer in the thread")
    assert rdc.parse(f.read_text()).comments[0].body == "about the pears"
    assert len(agent.calls()) == 1
    assert sent == []


def test_a_page_that_has_written_nothing_takes_in_a_change_from_outside(tab):
    # `writing` (the comment form predicate of the upgrade path) and the counter of this page's
    # own writes were one variable: for an editor the counter was a function, truthy, and every
    # `changed` event was held for a save that never came.
    tab.open()
    mark(tab.page)
    f = tab.site.file
    f.write_text(f.read_text() + "\nA new paragraph from outside.\n", encoding="utf-8")
    reloaded(tab.page)
    assert "A new paragraph from outside." in tab.page.inner_text("main")


def test_after_a_send_that_failed_an_upgraded_hub_meets_the_form_with_text_without_a_script_error(thread):
    # The other half of the same collision: the first own write turned the predicate into NaN
    # (a send that fails leaves it so, nothing reloads), and the upgrade path, which calls it,
    # threw "writing is not a function".
    open_reply(thread, "sent into the void")
    thread.site.kill()
    thread.page.click("#rd-popover button[data-f=ok]")
    toasted(thread.page, "did not go out")
    thread.site.start(version="99.0.0")
    line = ("(() => { const n = document.querySelector('#rd-notice');"
            " return n.hidden ? '' : n.textContent; })()")
    until(lambda: "The sheaf hub was upgraded" in thread.page.evaluate(line) or thread.errors,
          timeout=15, what="the upgrade notice")
    assert thread.errors == []
    assert "Send or cancel your comment" in thread.page.evaluate(line)
    assert thread.page.input_value("#rd-popover textarea") == "sent into the void"


# A badge, a panel item and the Comment button open something else, and opening
# it closed the popover with the text typed in it. They wait until the form is sent or cancelled.
WRITING_FIRST = "Send or cancel the comment you are writing first"
BEING_SENT = "Your comment is being sent"


@pytest.fixture
def two_threads(thread):
    """`thread` plus a second comment on 'pears'; the page reloaded and the first thread open."""
    select(thread.page, at(P2, "pears"), at(P2, "pears", None))
    thread.page.click("#rd-comment-btn")
    thread.page.fill("#rd-popover textarea", "Why pears?")
    thread.page.click("#rd-popover button[data-f=ok]")
    until(lambda: len(rdc.parse(thread.site.file.read_text()).comments) == 2, what="both comments in the file")
    until(lambda: "Why pears?" in thread.page.inner_text("#rd-popover"), what="the hub's answer")
    thread.page.reload()
    thread.page.wait_for_selector("#rd-menu-btn", state="attached")
    thread.page.locator(".rd-badge").first.click()
    thread.page.wait_for_selector("#rd-popover button[data-a=reply]")
    return thread


# The popover sits over the badge below its own, so a click on it is sent as an event.
def still_written(tab, text):
    toasted(tab.page, WRITING_FIRST)
    assert tab.page.input_value("#rd-popover textarea") == text


def test_another_comments_badge_leaves_a_reply_with_text_alone(two_threads):
    open_reply(two_threads, "my reply text")
    two_threads.page.locator(".rd-badge").nth(1).dispatch_event("click")
    still_written(two_threads, "my reply text")
    assert "Why apples?" in two_threads.page.inner_text("#rd-popover")


def test_the_badge_of_the_open_thread_leaves_a_reply_with_text_alone(two_threads):
    open_reply(two_threads, "my reply text")
    two_threads.page.locator(".rd-badge").first.dispatch_event("click")
    still_written(two_threads, "my reply text")


def test_a_panel_item_leaves_a_reply_with_text_alone(two_threads):
    open_reply(two_threads, "my reply text")
    two_threads.page.click("#rd-menu-btn")
    two_threads.page.click("#rd-show")
    two_threads.page.locator("#rd-panel button[data-id]").nth(1).click()
    still_written(two_threads, "my reply text")
    assert "Why apples?" in two_threads.page.inner_text("#rd-popover")


def test_the_comment_button_leaves_a_reply_with_text_alone(two_threads):
    open_reply(two_threads, "my reply text")
    select(two_threads.page, at(P2, "Second"), at(P2, "Second", None))
    two_threads.page.click("#rd-comment-btn")
    still_written(two_threads, "my reply text")
    assert "Why apples?" in two_threads.page.inner_text("#rd-popover")


def test_a_form_without_text_gives_way_to_another_badge(two_threads):
    two_threads.page.click("#rd-popover button[data-a=reply]")
    two_threads.page.locator(".rd-badge").nth(1).dispatch_event("click")
    until(lambda: "Why pears?" in two_threads.page.inner_text("#rd-popover"), what="the second thread")


# `sending` was one counter for the page, so a reply that was out, answered or not, kept Escape, a click
# outside, the badges, the panel and the Comment button from every popover. A form that was sent comes
# back to its own thread (below), so it waits for nothing but its own popover. A new comment has no
# thread to come back to: it still holds those three.
def open_thread_by(tab, how):
    """Open the second thread ('pears') by its badge or its panel item; for the Comment button, a new comment on
    another passage opens instead."""
    p = tab.page
    if how == "a badge":
        p.locator(".rd-badge").nth(1).dispatch_event("click")
    elif how == "a panel item":
        p.click("#rd-menu-btn")
        p.click("#rd-show")
        p.locator("#rd-panel button[data-id]").nth(1).click()
    else:
        select(p, at(P2, "Second"), at(P2, "Second", None))
        p.click("#rd-comment-btn")


@pytest.mark.parametrize("how", ["a badge", "a panel item", "the Comment button"])
def test_another_popover_opens_and_closes_with_escape_while_a_reply_is_out_and_never_answered(two_threads, how):
    p = two_threads.page
    held = send_held(two_threads, "reply", "a reply that is never answered")
    open_thread_by(two_threads, how)
    if how == "the Comment button":
        p.wait_for_selector("#rd-popover textarea")
    else:
        until(lambda: "Why pears?" in p.inner_text("#rd-popover"), what="the second thread")
    assert "Why apples?" not in p.inner_text("#rd-popover")
    p.keyboard.press("Escape")
    until(lambda: p.locator("#rd-popover").count() == 0, what="Escape to close the popover")
    held[0].abort()
    p.unroute("**/_/comment")


def test_a_click_outside_closes_another_popover_while_a_reply_is_out_and_never_answered(two_threads):
    p = two_threads.page
    held = send_held(two_threads, "reply", "a reply that is never answered")
    open_thread_by(two_threads, "a badge")
    until(lambda: "Why pears?" in p.inner_text("#rd-popover"), what="the second thread")
    p.mouse.click(5, 400)
    until(lambda: p.locator("#rd-popover").count() == 0, what="the click outside to close the popover")
    held[0].abort()
    p.unroute("**/_/comment")


def test_a_thread_that_was_left_while_its_reply_is_out_shows_no_second_form_and_no_buttons_when_it_is_opened_again(two_threads):
    p = two_threads.page
    held = send_held(two_threads, "reply", "a reply that is never answered")
    open_thread_by(two_threads, "a badge")
    until(lambda: "Why pears?" in p.inner_text("#rd-popover"), what="the second thread")
    p.locator(".rd-badge").first.dispatch_event("click")
    until(lambda: "Why apples?" in p.inner_text("#rd-popover"), what="the first thread again")
    p.wait_for_timeout(300)
    assert p.locator("#rd-popover textarea").count() == 0, "the reply that is out was offered as a second form"
    assert not p.is_visible("#rd-popover .rd-actions"), "the thread shows its buttons under a send that is out"
    held[0].abort()
    p.unroute("**/_/comment")


# A thread opened again while its reply was out showed no buttons and no form, and said nothing; nor did
# its popover while the send was out.
@pytest.mark.parametrize("form, says", [("reply", "Your reply is being sent"), ("edit", "Your edit is being sent")])
def test_a_thread_says_that_its_reply_or_edit_is_being_sent_until_the_answer_also_when_opened_again(two_threads, form, says):
    p = two_threads.page
    held = send_held(two_threads, form, "words that go through")
    until(lambda: says in p.inner_text("#rd-popover"), timeout=3, what="the line in the popover it was sent from")
    open_thread_by(two_threads, "a badge")
    until(lambda: "Why pears?" in p.inner_text("#rd-popover"), what="the second thread")
    assert says not in p.inner_text("#rd-popover"), "another thread says it is sending"
    p.locator(".rd-badge").first.dispatch_event("click")
    until(lambda: "Why apples?" in p.inner_text("#rd-popover"), what="the first thread again")
    assert says in p.inner_text("#rd-popover")
    held[0].continue_()
    p.unroute("**/_/comment")
    until(lambda: p.is_visible("#rd-popover button[data-a=reply]"), what="the thread's buttons")
    assert says not in p.inner_text("#rd-popover")
    assert "words that go through" in p.inner_text("#rd-popover")


# (The page's own write holds the `changed` event that is heard meanwhile: this pins that it still does
# with another thread open, which a send that is out no longer forbids.)
def test_a_change_from_outside_does_not_reload_under_a_reply_that_is_out_while_another_thread_is_open(two_threads):
    p = two_threads.page
    held = send_held(two_threads, "reply", "a reply that goes through")
    open_thread_by(two_threads, "a badge")
    until(lambda: "Why pears?" in p.inner_text("#rd-popover"), what="the second thread")
    f = two_threads.site.file
    mark(p)
    f.write_text(f.read_text() + "\nA new paragraph from outside.\n", encoding="utf-8")
    p.wait_for_timeout(2500)     # a page with nothing out reloads within a second
    assert p.evaluate("window.__same_load") is True, "the page reloaded under a send that is out"
    held[0].continue_()
    p.unroute("**/_/comment")
    until(lambda: "a reply that goes through" in f.read_text(), what="the reply in the file")
    reloaded(p)


def answer_held_after_the_hub_took_it(p, held):
    """Route handler for `/_/comment`: the hub takes the send at once, its answer waits in `held` until the test
    gives it (`held[0].fulfill(response=held[1])`)."""
    def handler(route):
        held.extend([route, route.fetch()])
    p.route("**/_/comment", handler)


def hearing(tab):
    """Reload the page under a session that counts the stream's messages as its EventSource takes them in; returns
    the list of their names, to wait on instead of a pause."""
    heard = []
    cdp = tab.page.context.new_cdp_session(tab.page)
    cdp.on("Network.eventSourceMessageReceived", lambda e: heard.append(e["eventName"]))
    cdp.send("Network.enable")
    tab.page.reload()
    tab.page.wait_for_selector("#rd-menu-btn", state="attached")
    return heard


def heard_changes(p, heard, n):
    """Wait until the page has heard `n` changes, and its listener has run."""
    until(lambda: heard.count("changed") >= n or p.wait_for_timeout(20), what=f"the page to hear {n} changes")
    p.evaluate("0")


def heard_before_the_send_ends(p):
    """Force the order the page leaves to chance: the events held behind a write are replayed (`replayHeld`, a
    timer of 0 that `post` sets when the answer arrives) before the microtasks that end the send, so one is
    heard while the send is still counted as out."""
    p.evaluate("""() => {
        const set = window.setTimeout;
        window.setTimeout = function (f, ms) {
            if (typeof f === 'function' && f.name === 'replayHeld' && !ms) return Promise.resolve().then(f);
            return set.apply(this, arguments);
        };
    }""")


# A change from outside that is heard in the window between a send's answer and the end of the send waits for
# the sends that are still out, those of other popovers too: the reload then runs when the send ends, and says
# that it waited. (The page's own write holds the event until the answer, so only a forced order reaches it.)
def test_a_change_heard_between_a_replys_answer_and_its_end_reloads_when_the_send_ends_and_says_it_waited(two_threads):
    p, f, held = two_threads.page, two_threads.site.file, []
    heard = hearing(two_threads)
    p.locator(".rd-badge").first.click()
    p.wait_for_selector("#rd-popover button[data-a=reply]")
    p.click("#rd-popover button[data-a=reply]")
    p.fill("#rd-popover textarea", "a reply that goes through")
    answer_held_after_the_hub_took_it(p, held)
    p.keyboard.press("Control+Enter")
    until(lambda: held or p.wait_for_timeout(20), what="the hub to take the reply")
    open_thread_by(two_threads, "a badge")
    until(lambda: "Why pears?" in p.inner_text("#rd-popover"), what="the second thread")
    f.write_text(f.read_text() + "\nA new paragraph from outside.\n", encoding="utf-8")
    heard_changes(p, heard, 2)     # the reply's own and this one, both waiting behind the write
    heard_before_the_send_ends(p)
    mark(p)
    held[0].fulfill(response=held[1])
    p.unroute("**/_/comment")
    reloaded(p)
    p.wait_for_selector("#rd-menu-btn", state="attached")
    toasted(p, "text changed while you wrote")
    assert "a reply that goes through" in f.read_text()


@pytest.mark.parametrize("how", ["a badge", "a panel item", "the Comment button"])
def test_a_new_comment_that_is_being_sent_holds_what_would_close_it_and_says_why(tab, how):
    tab.open()
    comment_on(tab, at(P2, "pears"), at(P2, "pears", None), "Why pears?")
    tab.page.reload()
    tab.page.wait_for_selector("#rd-menu-btn", state="attached")
    open_comment_form(tab, P1, "apples")
    p = tab.page
    p.fill("#rd-popover textarea", "about the apples")
    held = []
    p.route("**/_/comment", lambda route: held.append(route))
    p.keyboard.press("Control+Enter")
    until(lambda: held or p.wait_for_timeout(20), what="the send to go out")
    if how == "a badge":
        p.locator(".rd-badge").dispatch_event("click")
    elif how == "a panel item":
        p.click("#rd-menu-btn")
        p.click("#rd-show")
        p.locator("#rd-panel button[data-id]").first.click()
    else:
        select(p, at(P2, "pears"), at(P2, "pears", None))
        p.click("#rd-comment-btn")
    toasted(p, BEING_SENT)
    p.wait_for_timeout(150)
    assert "apples" in p.inner_text("#rd-popover .rd-quote")
    assert p.locator("#rd-popover .rd-form").count() == 1
    fail_the_send(p, held)
    assert p.input_value("#rd-popover textarea") == "about the apples"


# A new comment whose send never answered held its popover, the badges, the panel and the Comment button
# until the page was reloaded: the page waited for the hub for ever. It waits 30 seconds, then the send
# fails as one the hub refused: the form is back with its text, which stays kept, and the page is free.
LATE = "The hub did not answer within 30 seconds"


def test_a_new_comment_whose_send_never_answers_comes_back_after_30_seconds_and_frees_the_page(tab):
    p = tab.page
    p.clock.install(time=T0)
    tab.open()
    comment_on(tab, at(P2, "pears"), at(P2, "pears", None), "Why pears?")
    p.reload()
    p.wait_for_selector("#rd-menu-btn", state="attached")
    open_comment_form(tab, P1, "apples")
    p.fill("#rd-popover textarea", "about the apples")
    held = []
    p.route("**/_/comment", lambda route: held.append(route))
    p.keyboard.press("Control+Enter")
    until(lambda: held or p.wait_for_timeout(20), what="the send to go out")
    p.locator(".rd-badge").dispatch_event("click")
    toasted(p, BEING_SENT)
    p.clock.fast_forward(29_000)
    p.wait_for_timeout(200)
    assert LATE not in p.inner_text("#rd-toast"), "the page gave up before 30 seconds"
    p.clock.fast_forward(1_500)
    toasted(p, LATE)
    assert p.input_value("#rd-popover textarea") == "about the apples"
    assert "about the apples" in comment_store(tab)
    p.unroute("**/_/comment")
    p.click("#rd-popover button[data-f=no]")
    p.locator(".rd-badge").dispatch_event("click")
    until(lambda: "Why pears?" in p.inner_text("#rd-popover"), what="the thread of the badge")


# The same for a reply: its thread's buttons, the Cancel of a running Ask or Tell among them, were hidden
# for as long as its send was out, so for ever when it never answered.
def test_a_reply_whose_send_never_answers_comes_back_after_30_seconds_with_the_threads_buttons_behind_it(thread):
    p = thread.page
    reload_on_clock(p)
    p.click(".rd-badge")
    p.wait_for_selector("#rd-popover button[data-a=reply]")
    held = send_held(thread, "reply", "a reply that is never answered")
    p.clock.fast_forward(30_500)
    toasted(p, LATE)
    assert p.input_value("#rd-popover textarea") == "a reply that is never answered"
    p.unroute("**/_/comment")
    p.click("#rd-popover button[data-f=no]")
    assert p.is_visible("#rd-popover button[data-a=reply]"), "the thread's buttons did not come back"
    assert held


# The hub may still be writing what the page gave up on: a comment re-renders the page as a save does, so a
# long document, or a save ahead of it, holds it past the 30 seconds. Sent again, it was written twice; taken
# after all, its form stayed on the page under the reply, and its text in the store. The send carries a request
# id that the hub remembers, and the `changed` event of the write names it.
@pytest.fixture
def slow_hub(tab):
    """hold(): the hub stops each comment after its write and before its render, until release()."""
    go = threading.Event()

    def hold():
        tab.site.hub.entry(DOC).live._after_write = lambda: go.wait(30)
    yield SimpleNamespace(hold=hold, release=go.set)
    go.set()


SLOW = "words the hub is slow to write"
TAKEN = "What you sent reached the hub after all"


def given_up(tab, slow_hub, form):
    """A reply, or a new comment on 'pears', written by the hub, which holds it past the page's 30 seconds:
    the page has given up on it and the form is back with its text."""
    p = tab.page
    reload_on_clock(p)
    if form == "reply":
        p.click(".rd-badge")
        open_reply(tab, SLOW)
    else:
        open_comment_form(tab, P2, "pears")
        p.fill("#rd-popover textarea", SLOW)
    slow_hub.hold()
    p.keyboard.press("Control+Enter")
    until(lambda: SLOW in tab.site.file.read_text(), what="the hub's write")
    p.clock.fast_forward(30_500)
    toasted(p, LATE)
    assert p.input_value("#rd-popover textarea") == SLOW


def test_a_reply_given_up_that_the_hub_took_after_all_goes_from_the_page_and_the_store(thread, slow_hub):
    p = thread.page
    given_up(thread, slow_hub, "reply")
    slow_hub.release()
    toasted(p, TAKEN)
    until(lambda: p.locator("#rd-popover textarea").count() == 0, what="the form to go")
    assert p.inner_text("#rd-popover").count(SLOW) == 1
    assert SLOW not in comment_store(thread)
    assert p.is_visible("#rd-popover button[data-a=reply]"), "the thread's buttons did not come back"


def test_a_new_comment_given_up_that_the_hub_took_after_all_is_not_kept_on_the_page_that_comes_back(thread, slow_hub):
    p = thread.page
    given_up(thread, slow_hub, "new comment")
    mark(p)
    slow_hub.release()
    reloaded(p)
    p.wait_for_selector("#rd-menu-btn", state="attached")
    until(lambda: p.locator(".rd-badge").count() == 2, what="the new comment's badge")
    p.wait_for_timeout(300)
    assert p.locator("#rd-popover textarea").count() == 0, "the text came back as a kept comment"
    assert SLOW not in comment_store(thread)


# A page that missed the `changed` event naming its send (an outage, a tab closed) learns from `/_/doc` that the
# hub took it: the kept text goes, as it does when the event comes.
MISSED = "words whose event this page never heard"
MISSED_RID = "r0123456789missed"


def keep_on_disk(tab, *entries):
    key = comment_draft_key(tab.site)
    tab.page.evaluate("([k, v]) => localStorage.setItem(k, v)", [key, json.dumps(entries)])


def test_a_reply_kept_after_the_hub_took_it_is_cleared_when_the_page_loads(thread):
    # The write is made with the tab closed, as the miss it stands for. A page open over it races the
    # test: the `/_/doc` check of its stream's hello, answering after the write, reloads it under the
    # test's own reload (#68).
    live = thread.site.hub.entry(DOC).live
    (c,) = rdc.parse(thread.site.file.read_text()).comments
    keep_on_disk(thread, {"thread": c.id, "born": c.at, "about": c.quote, "kind": "reply", "body": MISSED,
                          "rid": MISSED_RID, "at": "2026-10-22T10:00:00.000Z"})
    thread.page.goto("about:blank")
    live.comment("reply", {"id": c.id, "body": MISSED}, "", rid=MISSED_RID)
    thread.open()
    until(lambda: MISSED not in comment_store(thread), what="the kept reply to leave localStorage")
    thread.page.click(".rd-badge")
    thread.page.wait_for_selector("#rd-popover button[data-a=reply]")
    assert thread.page.locator("#rd-popover textarea").count() == 0, "the reply came back as a kept form"


@pytest.mark.parametrize("same_birth", [True, False])
def test_a_kept_reply_is_offered_only_to_the_thread_of_its_own_birth_not_to_one_with_the_same_id_and_quote(thread, same_birth):
    # A comment deleted and added again with the same quote and author gets the same id; only `at`
    # (`born` in the entry) tells the two apart, so the entry is written with another `at`.
    (c,) = rdc.parse(thread.site.file.read_text()).comments
    keep_on_disk(thread, {"thread": c.id, "born": c.at if same_birth else "2026-01-01T00:00", "about": c.quote,
                          "kind": "reply", "body": "the reply of another birth", "rid": "r0123456789born",
                          "at": "2026-10-22T10:00:00.000Z"})
    thread.page.reload()
    thread.page.wait_for_selector("#rd-menu-btn", state="attached")
    thread.page.click(".rd-badge")
    thread.page.wait_for_selector("#rd-popover .rd-scroll")
    thread.page.wait_for_timeout(500)
    assert (thread.page.locator("#rd-popover textarea").count() == 1) is same_birth


def test_a_thread_with_a_kept_edit_and_a_kept_reply_draws_the_first_of_the_store_and_says_the_other_is_kept(thread):
    # keptThreadForm takes the entry of the other kind first when it comes first in the store; two tabs
    # are the only other way to reach it.
    (c,) = rdc.parse(thread.site.file.read_text()).comments
    entry = {"thread": c.id, "born": c.at, "about": c.quote, "at": "2026-10-22T10:00:00.000Z"}
    keep_on_disk(thread, {**entry, "kind": "edit", "body": "the kept edit", "rid": "r0123456789edit"},
                 {**entry, "kind": "reply", "body": "the kept reply", "rid": "r0123456789repl"})
    thread.page.reload()
    thread.page.wait_for_selector("#rd-menu-btn", state="attached")
    thread.page.click(".rd-badge")
    thread.page.wait_for_selector("#rd-popover textarea")
    assert kept_text(thread) == "the kept edit"
    assert "Your reply to this thread is kept too" in thread.page.inner_text("#rd-popover .rd-also")
    thread.page.click("#rd-popover button[data-f=no]")
    until(lambda: kept_text(thread) == "the kept reply", what="the kept reply to come after the edit")


def test_a_new_comment_kept_after_the_hub_took_it_is_cleared_when_the_page_loads(tab):
    tab.open()
    live = tab.site.hub.entry(DOC).live
    blk, s, e = rdc.find_quote(tab.site.file.read_text(), "pears")
    live.comment("add", {"block": blk, "start": s, "end": e, "quote": "pears", "body": MISSED}, "", rid=MISSED_RID)
    until(lambda: tab.page.locator(".rd-badge").count() == 1, what="the page to hear of the comment")
    keep_on_disk(tab, {"quote": "pears", "body": MISSED, "block": blk, "rid": MISSED_RID,
                       "at": "2026-10-22T10:00:00.000Z"})
    tab.page.reload()
    tab.page.wait_for_selector("#rd-menu-btn", state="attached")
    until(lambda: MISSED not in comment_store(tab), what="the kept comment to leave localStorage")
    tab.page.wait_for_timeout(300)
    assert tab.page.locator("#rd-popover textarea").count() == 0, "the text came back as a kept comment"


@pytest.mark.parametrize("form", ["reply", "new comment"])
def test_a_send_given_up_and_sent_again_while_the_hub_still_writes_it_is_written_once(thread, slow_hub, form):
    p, f = thread.page, thread.site.file
    given_up(thread, slow_hub, form)
    p.focus("#rd-popover textarea")
    p.keyboard.press("Control+Enter")
    p.wait_for_timeout(300)                     # the second request waits in the hub behind the first
    slow_hub.release()
    until(lambda: p.locator("#rd-popover textarea").count() == 0, what="the form to go")
    p.wait_for_timeout(300)
    assert f.read_text().count(SLOW) == 1
    assert SLOW not in comment_store(thread)


# Given up while text is typed in another thread, the reply's text stays in the store for its own thread, and
# the line that said so ("Not sent") replaced the one that says it may have arrived all the same.
def test_a_reply_given_up_while_text_is_typed_in_another_thread_still_says_it_may_have_arrived(two_threads):
    p = two_threads.page
    reload_on_clock(p)
    p.locator(".rd-badge").first.click()
    p.wait_for_selector("#rd-popover button[data-a=reply]")
    held = send_held(two_threads, "reply", "words for the first thread")
    open_thread_by(two_threads, "a badge")
    until(lambda: "Why pears?" in p.inner_text("#rd-popover"), what="the second thread")
    p.click("#rd-popover button[data-a=reply]")
    p.fill("#rd-popover textarea", "words for the second thread")
    p.clock.fast_forward(30_500)
    toasted(p, "is kept")
    assert LATE in toast(p) and "Not sent" not in toast(p)
    assert held and p.input_value("#rd-popover textarea") == "words for the second thread"
    p.unroute("**/_/comment")


# The request id of a send the page gave up on stayed "given up" until the hub's event named it: the same text
# sent again under that id and failing for another reason (the hub away) was said to have been given up on too.
def test_a_text_sent_again_after_a_give_up_and_failing_for_another_reason_is_not_said_to_have_been_given_up_on(two_threads):
    p = two_threads.page
    reload_on_clock(p)
    p.locator(".rd-badge").first.click()
    p.wait_for_selector("#rd-popover button[data-a=reply]")
    held = send_held(two_threads, "reply", "words for the first thread")
    p.clock.fast_forward(30_500)
    toasted(p, LATE)
    p.unroute("**/_/comment")
    again = []
    p.route("**/_/comment", lambda route: again.append(route))
    p.focus("#rd-popover textarea")
    p.keyboard.press("Control+Enter")
    until(lambda: again or p.wait_for_timeout(20), what="the second send to go out")
    open_thread_by(two_threads, "a badge")
    until(lambda: "Why pears?" in p.inner_text("#rd-popover"), what="the second thread")
    p.click("#rd-popover button[data-a=reply]")
    p.fill("#rd-popover textarea", "words for the second thread")
    again[0].abort()
    toasted(p, "Not sent")
    assert LATE not in toast(p)
    assert held
    p.unroute("**/_/comment")


# The failed send again said it did not go out by deleting the marker of the send before it, so when that send,
# which the hub was still writing, was taken after all, the page did not say so. The order is forced: the hub
# holds the write, the page gives up, the send again fails to reach the hub, then the hub finishes the first.
def test_a_send_again_that_fails_to_reach_the_hub_does_not_hide_that_the_send_before_it_was_taken(thread, slow_hub):
    p = thread.page
    given_up(thread, slow_hub, "reply")
    again = []
    p.route("**/_/comment", lambda route: again.append(route))
    p.focus("#rd-popover textarea")
    p.keyboard.press("Control+Enter")
    until(lambda: again or p.wait_for_timeout(20), what="the send again to go out")
    again[0].abort()
    toasted(p, "did not go out")
    assert LATE not in toast(p)
    p.unroute("**/_/comment")
    slow_hub.release()
    toasted(p, TAKEN)
    until(lambda: p.locator("#rd-popover textarea").count() == 0, what="the form to go")
    assert SLOW not in comment_store(thread)


# A panel item checks writingFirst() when it is clicked, then opens its thread
# 60 ms later (after the scroll). A new comment sent inside those 60 ms was closed by openComment, with its
# send out: the guard of writingFirst() has to run again when the thread is opened.
def test_a_new_comment_sent_inside_the_60_ms_after_a_panel_item_was_clicked_is_not_closed_by_it(tab):
    tab.open()
    comment_on(tab, at(P2, "pears"), at(P2, "pears", None), "Why pears?")
    tab.page.reload()
    tab.page.wait_for_selector("#rd-menu-btn", state="attached")
    p, held = tab.page, []
    p.click("#rd-menu-btn")
    p.click("#rd-show")
    open_comment_form(tab, P1, "apples")
    p.route("**/_/comment", lambda route: held.append(route))
    p.evaluate("""() => {
      document.querySelector('#rd-panel button[data-id]').click();
      const ta = document.querySelector('#rd-popover textarea');
      ta.value = 'about the apples';
      ta.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', ctrlKey: true, bubbles: true}));
    }""")
    until(lambda: held or p.wait_for_timeout(20), what="the send to go out")
    p.wait_for_timeout(300)
    assert "apples" in p.inner_text("#rd-popover .rd-quote"), "the thread of the panel item opened over the new comment"
    assert p.locator("#rd-popover .rd-form").count() == 1
    fail_the_send(p, held)
    assert p.locator("#rd-popover textarea").count() == 1
    assert p.input_value("#rd-popover textarea") == "about the apples"


# The answer of a Delete closed whatever popover was open, so a Delete
# whose answer was slow closed a new comment that had been opened and sent meanwhile, with its send out.
def test_the_answer_of_a_delete_does_not_close_a_new_comment_that_is_being_sent(thread):
    p, held = thread.page, []
    p.route("**/_/comment", lambda route: held.append(route))
    p.click("#rd-popover button[data-a=delete]")
    until(lambda: held or p.wait_for_timeout(20), what="the delete to go out")
    open_comment_form(thread, P2, "pears")
    p.fill("#rd-popover textarea", "about the pears")
    p.keyboard.press("Control+Enter")
    until(lambda: len(held) == 2 or p.wait_for_timeout(20), what="the send to go out")
    held[0].continue_()
    until(lambda: not rdc.parse(thread.site.file.read_text()).comments, what="the thread gone from the file")
    p.wait_for_timeout(300)
    assert "pears" in p.inner_text("#rd-popover .rd-quote"), "the answer of the delete closed the new comment"
    assert p.locator("#rd-popover .rd-form").count() == 1
    fail_the_send(p, held[1:])
    assert p.locator("#rd-popover textarea").count() == 1
    assert p.input_value("#rd-popover textarea") == "about the pears"


# The answer of a Delete closed its thread's popover whatever was typed in
# it. A thread deleted elsewhere keeps its popover while text is typed; so does one deleted here.
def test_the_answer_of_a_delete_keeps_the_popover_of_its_thread_while_a_reply_is_typed_in_it(thread):
    p, held = thread.page, []
    p.route("**/_/comment", lambda route: held.append(route))
    p.click("#rd-popover button[data-a=delete]")
    until(lambda: held or p.wait_for_timeout(20), what="the delete to go out")
    p.click("#rd-popover button[data-a=reply]")
    p.fill("#rd-popover textarea", "words typed while the delete was out")
    held[0].continue_()
    until(lambda: not rdc.parse(thread.site.file.read_text()).comments, what="the thread gone from the file")
    p.unroute("**/_/comment")
    p.wait_for_selector("#rd-popover .rd-hold:has-text('deleted')")
    assert p.input_value("#rd-popover textarea") == "words typed while the delete was out"
    p.click("#rd-popover button[data-f=no]")
    until(lambda: p.locator("#rd-popover").count() == 0, what="the popover to close once the form is cancelled")


# The answer of a reply reloaded the page over a second form opened while the send was
# out. It waits for that form, like any held reload. (The second form was a second Reply; the thread's
# buttons are hidden during a send, so it is a new comment, which can be opened while a reply is out.)
def test_a_replys_answer_does_not_reload_over_a_new_comment_form_opened_while_it_was_out(two_threads):
    p = two_threads.page
    held = send_held(two_threads, "reply", "first reply")
    f = two_threads.site.file
    f.write_text(f.read_text() + "\nA new paragraph from outside.\n", encoding="utf-8")
    p.wait_for_timeout(500)
    open_thread_by(two_threads, "the Comment button")
    p.fill("#rd-popover textarea", "second words")
    mark(p)
    held[0].continue_()
    until(lambda: "first reply" in f.read_text(), what="the first reply in the file")
    p.unroute("**/_/comment")
    p.wait_for_selector("#rd-popover .rd-hold")
    p.wait_for_timeout(1500)
    assert p.evaluate("window.__same_load") is True, "the page reloaded under the second form"
    assert p.input_value("#rd-popover textarea") == "second words"
    p.click("#rd-popover button[data-f=ok]")
    reloaded(p)
    until(lambda: any(c.body == "second words" for c in rdc.parse(f.read_text()).comments), what="the second comment in the file")


# Two sends can be out at once (a reply, then a new comment), and the answer of one that needed a reload
# navigated away while the other was still out: its form came back after the reload for a reply the hub
# may have taken. The reload waits for every send that is out.
def first_send_held(tab):
    """Hold the first `/_/comment` request and let the others through; returns the held requests."""
    held = []
    tab.page.route("**/_/comment", lambda route: held.append(route) if not held else route.continue_())
    return held


def test_a_new_comments_answer_does_not_reload_the_page_while_a_reply_is_still_out(two_threads):
    p, f = two_threads.page, two_threads.site.file
    held = first_send_held(two_threads)
    open_reply(two_threads, "first reply")
    p.keyboard.press("Control+Enter")
    until(lambda: held or p.wait_for_timeout(20), what="the reply to go out")
    f.write_text(f.read_text() + "\nA new paragraph from outside.\n", encoding="utf-8")
    p.wait_for_timeout(500)
    open_thread_by(two_threads, "the Comment button")
    p.fill("#rd-popover textarea", "second words")
    mark(p)
    p.keyboard.press("Control+Enter")
    until(lambda: any(c.body == "second words" for c in rdc.parse(f.read_text()).comments), what="the new comment in the file")
    until(lambda: "second words" not in comment_store(two_threads), what="the page to take the answer in")
    p.wait_for_timeout(1000)
    assert p.evaluate("window.__same_load") is True, "the answer of the new comment reloaded the page under the reply"
    held[0].continue_()
    p.unroute("**/_/comment")
    until(lambda: "first reply" in f.read_text(), what="the reply in the file")
    reloaded(p)
    assert "A new paragraph from outside." in p.inner_text("main")


def test_a_new_comment_refused_while_a_reply_is_out_is_kept_and_the_reload_waits_for_the_reply(two_threads):
    p, f = two_threads.page, two_threads.site.file
    held = first_send_held(two_threads)
    open_reply(two_threads, "first reply")
    p.keyboard.press("Control+Enter")
    until(lambda: held or p.wait_for_timeout(20), what="the reply to go out")
    open_thread_by(two_threads, "the Comment button")      # 'Second' in the paragraph about pears
    p.fill("#rd-popover textarea", "about the second word")
    f.write_text(f.read_text().replace("about pears", "about ripe pears"), encoding="utf-8")
    p.wait_for_timeout(500)
    mark(p)
    p.keyboard.press("Control+Enter")
    p.wait_for_selector(KEPT)
    p.wait_for_timeout(1000)
    assert p.evaluate("window.__same_load") is True, "the refusal reloaded the page under the reply"
    assert p.input_value("#rd-popover textarea") == "about the second word"
    held[0].continue_()
    p.unroute("**/_/comment")
    until(lambda: "first reply" in f.read_text(), what="the reply in the file")
    reloaded(p)
    assert "about the second word" in comment_store(two_threads)


# The other way round, a Delete answered while a new comment is out. (A reply cannot be sent while a new
# comment is out: a new comment being sent holds every badge.)
def test_the_answer_of_a_delete_does_not_reload_the_page_while_a_new_comment_is_still_out(thread):
    p, f = thread.page, thread.site.file
    held = []
    p.route("**/_/comment", lambda route: held.append(route))
    p.click("#rd-popover button[data-a=delete]")
    until(lambda: held or p.wait_for_timeout(20), what="the delete to go out")
    open_comment_form(thread, P2, "pears")
    p.fill("#rd-popover textarea", "about the pears")
    p.keyboard.press("Control+Enter")
    until(lambda: len(held) == 2 or p.wait_for_timeout(20), what="the new comment to go out")
    f.write_text(f.read_text() + "\nA new paragraph from outside.\n", encoding="utf-8")
    p.wait_for_timeout(500)
    mark(p)
    held[0].continue_()
    until(lambda: not rdc.parse(f.read_text()).comments, what="the thread gone from the file")
    until(lambda: p.locator(".rd-badge").count() == 0, what="the page to take the answer in")
    p.wait_for_timeout(1000)
    assert p.evaluate("window.__same_load") is True, "the answer of the delete reloaded the page under the new comment"
    held[1].continue_()
    p.unroute("**/_/comment")
    until(lambda: any(c.body == "about the pears" for c in rdc.parse(f.read_text()).comments), what="the new comment in the file")
    reloaded(p)


# A form whose send failed after another thread was opened came back in that thread's
# popover, and still sent to the first. It goes back to its own thread; and it does not take over a popover
# with text typed in it: its text is kept, and the thread has it again when it is opened.
@pytest.mark.parametrize("form", ["reply", "edit"])
def test_a_reply_or_edit_whose_send_fails_after_another_thread_was_opened_comes_back_in_its_own_thread(two_threads, form):
    p = two_threads.page
    held = send_held(two_threads, form, "words for the first thread")
    open_thread_by(two_threads, "a badge")
    until(lambda: "Why pears?" in p.inner_text("#rd-popover"), what="the second thread")
    held[0].fulfill(status=500, json={"ok": False, "error": "the hub broke off"})
    p.unroute("**/_/comment")
    until(lambda: "Why apples?" in p.inner_text("#rd-popover"), what="the first thread to come back")
    assert "Why pears?" not in p.inner_text("#rd-popover")
    assert p.locator("#rd-popover .rd-form").count() == 1
    assert p.input_value("#rd-popover textarea") == "words for the first thread"
    f = two_threads.site.file
    p.click("#rd-popover button[data-f=ok]")
    until(lambda: "words for the first thread" in f.read_text(), what="the text in the file")
    first, second = rdc.parse(f.read_text()).comments
    if form == "reply":
        assert [r.text for r in first.replies] == ["words for the first thread"]
        assert second.replies == []
    else:
        assert second.replies == [] and "Why pears?" in f.read_text()


def test_a_failed_send_does_not_take_over_a_popover_with_text_typed_in_it(two_threads):
    p = two_threads.page
    held = send_held(two_threads, "reply", "words for the first thread")
    open_thread_by(two_threads, "a badge")
    until(lambda: "Why pears?" in p.inner_text("#rd-popover"), what="the second thread")
    p.click("#rd-popover button[data-a=reply]")
    p.fill("#rd-popover textarea", "words for the second thread")
    held[0].fulfill(status=500, json={"ok": False, "error": "the hub broke off"})
    p.unroute("**/_/comment")
    toasted(p, "is kept")
    p.wait_for_timeout(200)
    assert "Why pears?" in p.inner_text("#rd-popover")
    assert p.locator("#rd-popover textarea").count() == 1
    assert p.input_value("#rd-popover textarea") == "words for the second thread"
    p.click("#rd-popover button[data-f=no]")
    p.locator(".rd-badge").first.dispatch_event("click")
    until(lambda: "Why apples?" in p.inner_text("#rd-popover"), what="the first thread")
    until(lambda: p.locator("#rd-popover textarea").count() == 1, what="the kept text in the form")
    assert p.input_value("#rd-popover textarea") == "words for the first thread"


# back() trusted that threadKeep had stored the text. A browser that cannot
# write localStorage (site data blocked, a full quota) stores nothing, and the page said the text was kept
# while the form was dropped. It checks the store first; what is not stored stays on the page.
def block_storage_writes(p):
    p.evaluate("""() => {
      const set = Storage.prototype.setItem;
      Storage.prototype.setItem = function (k, v) {
        if (String(k).startsWith('sheaf-comment-draft')) throw new Error('quota');
        return set.call(this, k, v);
      };
    }""")


def test_a_failed_send_does_not_drop_its_form_when_the_text_could_not_be_kept(two_threads):
    p = two_threads.page
    block_storage_writes(p)
    held = send_held(two_threads, "reply", "words for the first thread")
    open_thread_by(two_threads, "a badge")
    until(lambda: "Why pears?" in p.inner_text("#rd-popover"), what="the second thread")
    p.click("#rd-popover button[data-a=reply]")
    p.fill("#rd-popover textarea", "words for the second thread")
    held[0].fulfill(status=500, json={"ok": False, "error": "the hub broke off"})
    p.unroute("**/_/comment")
    p.wait_for_timeout(400)
    values = [t.input_value() for t in p.locator("#rd-popover textarea").all()]
    assert sorted(values) == ["words for the first thread", "words for the second thread"], values
    assert "This is for the thread “apples”" in p.inner_text("#rd-popover"), "the form does not say whose it is"


def test_the_text_that_could_not_be_kept_is_still_on_the_page_when_the_popover_it_was_put_in_is_redrawn(two_threads):
    p = two_threads.page
    block_storage_writes(p)
    held = send_held(two_threads, "reply", "words for the first thread")
    open_thread_by(two_threads, "a badge")
    until(lambda: "Why pears?" in p.inner_text("#rd-popover"), what="the second thread")
    p.click("#rd-popover button[data-a=reply]")
    p.fill("#rd-popover textarea", "words for the second thread")
    held[0].fulfill(status=500, json={"ok": False, "error": "the hub broke off"})
    p.unroute("**/_/comment")
    until(lambda: p.locator("#rd-popover textarea").count() == 2, what="both forms on the page")
    f = two_threads.site.file
    p.locator("#rd-popover .rd-form").first.locator("button[data-f=ok]").click()
    until(lambda: "words for the second thread" in f.read_text(), what="the second reply in the file")
    p.wait_for_timeout(500)
    values = [t.input_value() for t in p.locator("#rd-popover textarea").all()]
    assert "words for the first thread" in values, f"the first text was lost when the popover was redrawn: {values}"
    # The thread's buttons stay hidden while that form is open: Reply would remove it, Delete would close it.
    assert not p.is_visible("#rd-popover > .rd-actions"), "the thread's buttons are on the page beside the form of another thread"


def test_cancelling_the_form_beside_the_text_that_could_not_be_kept_leaves_that_text_and_hides_the_buttons(two_threads):
    p = two_threads.page
    block_storage_writes(p)
    held = send_held(two_threads, "reply", "words for the first thread")
    open_thread_by(two_threads, "a badge")
    until(lambda: "Why pears?" in p.inner_text("#rd-popover"), what="the second thread")
    p.click("#rd-popover button[data-a=reply]")
    p.fill("#rd-popover textarea", "words for the second thread")
    held[0].fulfill(status=500, json={"ok": False, "error": "the hub broke off"})
    p.unroute("**/_/comment")
    until(lambda: p.locator("#rd-popover textarea").count() == 2, what="both forms on the page")
    p.locator("#rd-popover .rd-form").first.locator("button[data-f=no]").click()
    p.wait_for_timeout(200)
    assert [t.input_value() for t in p.locator("#rd-popover textarea").all()] == ["words for the first thread"]
    assert not p.is_visible("#rd-popover > .rd-actions"), "the thread's buttons are on the page beside the form of another thread"


def test_a_badge_waits_for_the_text_that_could_not_be_kept_even_when_the_form_before_it_is_empty(two_threads):
    p = two_threads.page
    block_storage_writes(p)
    held = send_held(two_threads, "reply", "words for the first thread")
    open_thread_by(two_threads, "a badge")
    until(lambda: "Why pears?" in p.inner_text("#rd-popover"), what="the second thread")
    p.click("#rd-popover button[data-a=reply]")
    p.fill("#rd-popover textarea", "words for the second thread")
    held[0].fulfill(status=500, json={"ok": False, "error": "the hub broke off"})
    p.unroute("**/_/comment")
    until(lambda: p.locator("#rd-popover textarea").count() == 2, what="both forms on the page")
    p.locator("#rd-popover textarea").first.fill("")
    p.locator(".rd-badge").first.dispatch_event("click")
    toasted(p, WRITING_FIRST)
    assert sorted(t.input_value() for t in p.locator("#rd-popover textarea").all()) == ["", "words for the first thread"]


def test_a_failed_send_whose_text_could_not_be_kept_comes_back_in_its_own_thread(two_threads):
    p = two_threads.page
    block_storage_writes(p)
    held = send_held(two_threads, "reply", "words for the first thread")
    open_thread_by(two_threads, "a badge")
    until(lambda: "Why pears?" in p.inner_text("#rd-popover"), what="the second thread")
    fail_the_send(p, held)
    until(lambda: "Why apples?" in p.inner_text("#rd-popover"), what="the first thread to come back")
    assert p.locator("#rd-popover textarea").count() == 1
    assert p.input_value("#rd-popover textarea") == "words for the first thread"


# A write from outside that truncates the file and then fills it can be read half done by the hub's watcher
# (a tick is a second); the page then holds the reload for a form with text in it, and the thread's badge
# stays. The helpers that delete a thread in the file replace it whole, as the hub's own door does.
@pytest.mark.parametrize("delete", [lambda tab: delete_comment(tab, 0), lambda tab: delete_the_thread(tab)],
                         ids=["delete_comment", "delete_the_thread"])
def test_a_thread_deleted_from_outside_replaces_the_file(thread, delete):
    f = thread.site.file
    before = f.stat().st_ino
    delete(thread)
    assert f.stat().st_ino != before, "the file was rewritten in place, so a reader can see it half written"
    assert rdc.parse(f.read_text()).comments == []


# A thread deleted in the file closed its popover under a reply being typed.
def delete_the_thread(tab):
    f = tab.site.file
    (c,) = rdc.parse(f.read_text()).comments
    update_file(f, lambda t: rdc.delete(t, c.id))


def test_a_thread_deleted_elsewhere_keeps_its_popover_while_a_reply_is_typed(thread):
    open_reply(thread, "my reply text")
    delete_the_thread(thread)
    thread.page.wait_for_selector("#rd-popover .rd-hold:has-text('deleted')")
    assert thread.page.input_value("#rd-popover textarea") == "my reply text"
    thread.page.wait_for_timeout(1000)
    assert thread.page.input_value("#rd-popover textarea") == "my reply text"


def test_cancelling_the_form_of_a_deleted_thread_closes_its_popover(thread):
    open_reply(thread, "my reply text")
    delete_the_thread(thread)
    thread.page.wait_for_selector("#rd-popover .rd-hold:has-text('deleted')")
    thread.page.click("#rd-popover button[data-f=no]")
    until(lambda: thread.page.locator("#rd-popover").count() == 0, what="the popover to close")


def test_a_thread_deleted_elsewhere_closes_its_popover_when_nothing_is_typed(thread):
    delete_the_thread(thread)
    until(lambda: thread.page.locator("#rd-popover").count() == 0, what="the popover to close")


# The form of a thread deleted elsewhere said it could not be sent, and its Send still sent it, to be refused
# ("no comment"). Its text is to copy: the buttons that send are off, and Ctrl+Enter says why.
@pytest.mark.parametrize("form", ["reply", "edit"])
def test_the_form_of_a_deleted_thread_cannot_be_sent_only_copied_or_cancelled(thread, form):
    p, sent = thread.page, []
    p.click(f"#rd-popover button[data-a={form}]")
    p.fill("#rd-popover textarea", "words for a gone thread")
    delete_the_thread(thread)
    p.wait_for_selector("#rd-popover .rd-hold:has-text('deleted')")
    assert p.locator("#rd-popover .rd-form button[data-f]:not([data-f=no]):enabled").count() == 0
    assert p.is_enabled("#rd-popover button[data-f=no]")
    p.route("**/_/comment", lambda route: sent.append(route))
    p.focus("#rd-popover textarea")
    p.keyboard.press("Control+Enter")
    toasted(p, "cannot be sent")
    p.wait_for_timeout(200)
    assert sent == [] and p.input_value("#rd-popover textarea") == "words for a gone thread"
    p.unroute("**/_/comment")


# A reply whose thread is deleted elsewhere while it is out is refused ("no comment"), and its form went
# back into whatever popover was open, or, with none open, nowhere on screen; the text was in the store, under
# a thread that no longer exists, so nothing would ever show it again. It comes back in that thread's own
# popover, or beside text typed elsewhere, and says the thread was deleted. The page has not heard of the
# deletion when the refusal comes (an event is held while the page's own write is out, see `heard`): the
# refusal itself says the thread is gone (410).
def delete_comment(tab, n):
    f = tab.site.file
    c = rdc.parse(f.read_text()).comments[n]
    update_file(f, lambda t: rdc.delete(t, c.id))


def gone_and_sent(tab, words):
    """Type a reply into the open first thread, send it with `/_/comment` held, delete that thread in the file."""
    p, held = tab.page, []
    open_reply(tab, words)
    p.route("**/_/comment", lambda route: held.append(route))
    p.keyboard.press("Control+Enter")
    until(lambda: held or p.wait_for_timeout(20), what="the send to go out")
    delete_comment(tab, 0)
    return held


def refused(p, held):
    held[0].continue_()
    p.unroute("**/_/comment")
    toasted(p, "no comment")


def test_a_reply_to_a_thread_deleted_during_its_send_in_the_open_popover_says_so_on_the_form_that_comes_back(thread):
    p = thread.page
    held = gone_and_sent(thread, "words for a gone thread")
    refused(p, held)
    until(lambda: p.locator("#rd-popover textarea").count() == 1, what="the form to come back")
    assert p.input_value("#rd-popover textarea") == "words for a gone thread"
    assert p.locator("#rd-popover .rd-gone").count() == 1
    assert "deleted elsewhere" in p.inner_text("#rd-popover .rd-gone")
    assert p.locator("#rd-popover button[data-f]:not([data-f=no]):enabled").count() == 0, "it can still be sent"
    assert comment_store(thread) == ""


def test_a_reply_to_a_deleted_thread_closed_by_escape_during_its_send_comes_back_with_its_text(thread):
    p = thread.page
    held = gone_and_sent(thread, "words for a gone thread")
    p.keyboard.press("Escape")
    until(lambda: p.locator("#rd-popover").count() == 0, timeout=3, what="Escape to close the popover")
    refused(p, held)
    until(lambda: p.locator("#rd-popover textarea").count() == 1, what="the form to come back")
    assert p.input_value("#rd-popover textarea") == "words for a gone thread"
    assert "deleted" in p.inner_text("#rd-popover .rd-form")
    assert "being sent" not in p.inner_text("#rd-popover")
    assert p.locator("#rd-popover button[data-f]:not([data-f=no]):enabled").count() == 0, "it can still be sent"
    p.click("#rd-popover button[data-f=no]")
    until(lambda: p.locator("#rd-popover").count() == 0, what="the popover to close once the form is cancelled")
    assert comment_store(thread) == ""


# A deletion heard in the window between the answer and the end of the send finds the send of its own open
# popover still out: the popover does not close under it, and the form that the failed send gives back says the
# thread is gone, where the popover was.
def test_a_deletion_heard_while_a_reply_is_still_out_leaves_its_form_with_the_line_of_a_gone_thread(thread):
    p = thread.page
    heard = hearing(thread)
    p.click(".rd-badge")
    p.wait_for_selector("#rd-popover button[data-a=reply]")
    before = p.locator("#rd-popover").bounding_box()
    held = gone_and_sent(thread, "words for a gone thread")
    heard_changes(p, heard, 1)     # the deletion's event reaches the page and waits behind the write
    heard_before_the_send_ends(p)
    held[0].fulfill(status=500, json={"ok": False, "error": "the hub broke off"})
    p.unroute("**/_/comment")
    until(lambda: p.locator("#rd-popover textarea").count() == 1, what="the form to come back")
    assert p.input_value("#rd-popover textarea") == "words for a gone thread"
    assert "deleted" in p.inner_text("#rd-popover .rd-form")
    assert p.locator("#rd-popover button[data-f]:not([data-f=no]):enabled").count() == 0, "it can still be sent"
    after = p.locator("#rd-popover").bounding_box()
    assert abs(after["x"] - before["x"]) < 2 and abs(after["y"] - before["y"]) < 2, (before, after)


# The thread is deleted while a reply or edit of it is out and the send then fails: the form is back on screen
# with its text to copy, and the store keeps nothing for a thread that is gone (nothing would offer it again).
@pytest.mark.parametrize("form", ["reply", "edit"])
def test_a_reply_or_edit_for_a_thread_deleted_elsewhere_during_its_send_leaves_the_store_when_the_send_fails(thread, form):
    p = thread.page
    held = send_held(thread, form, "words for a gone thread")
    assert "words for a gone thread" in comment_store(thread)
    delete_comment(thread, 0)
    p.wait_for_timeout(300)
    held[0].abort()
    p.unroute("**/_/comment")
    until(lambda: p.locator("#rd-popover textarea").count() == 1, what="the form to come back")
    assert p.input_value("#rd-popover textarea") == "words for a gone thread"
    until(lambda: comment_store(thread) == "", what="the store to let the text of a thread that is gone go")
    p.click("#rd-popover button[data-f=no]")
    assert comment_store(thread) == ""


def test_a_reply_to_a_deleted_thread_does_not_come_back_in_another_thread_opened_during_its_send(two_threads):
    p = two_threads.page
    held = gone_and_sent(two_threads, "words for a gone thread")
    p.locator(".rd-badge").last.dispatch_event("click")
    until(lambda: "Why pears?" in p.inner_text("#rd-popover"), what="the second thread")
    refused(p, held)
    until(lambda: p.locator("#rd-popover textarea").count() == 1, what="the form to come back")
    assert "Why pears?" not in p.inner_text("#rd-popover"), "the form came back in another thread"
    assert p.input_value("#rd-popover textarea") == "words for a gone thread"
    assert "deleted" in p.inner_text("#rd-popover .rd-form")


def test_a_reply_to_a_deleted_thread_stays_beside_text_typed_in_another_thread_and_names_its_thread(two_threads):
    p = two_threads.page
    held = gone_and_sent(two_threads, "words for a gone thread")
    p.locator(".rd-badge").last.dispatch_event("click")
    until(lambda: "Why pears?" in p.inner_text("#rd-popover"), what="the second thread")
    p.click("#rd-popover button[data-a=reply]")
    p.fill("#rd-popover textarea", "words for the second thread")
    refused(p, held)
    until(lambda: p.locator("#rd-popover textarea").count() == 2, what="the form beside the one being typed")
    assert "Why pears?" in p.inner_text("#rd-popover")
    first, second = p.locator("#rd-popover .rd-form").all()
    assert first.locator("textarea").input_value() == "words for the second thread"
    assert "deleted" not in first.inner_text()
    assert second.locator("textarea").input_value() == "words for a gone thread"
    assert "“apples”, which was deleted" in second.inner_text()
    assert second.locator("button[data-f]:not([data-f=no]):enabled").count() == 0, "it can still be sent"
    # Its own form cancelled and the second thread deleted in turn: the line about the second thread does not
    # go on the first thread's form, the only one left.
    first.locator("button[data-f=no]").click()
    delete_comment(two_threads, 0)
    until(lambda: p.locator(".rd-badge").count() == 0, what="the second thread to go")
    p.wait_for_timeout(300)
    assert p.locator("#rd-popover .rd-gone").count() == 0, "the line about the second thread went on the first thread's form"
    assert p.input_value("#rd-popover textarea") == "words for a gone thread"


# Refused while a new comment was being sent, it came back into the new comment's popover, and the answer of
# the new comment then opened that comment's thread over it.
def test_a_reply_to_a_deleted_thread_that_came_back_into_a_new_comments_popover_stays_when_the_comment_is_taken(thread):
    p, f = thread.page, thread.site.file
    held = gone_and_sent(thread, "words for a gone thread")
    open_comment_form(thread, P2, "pears")
    p.fill("#rd-popover textarea", "about the pears")
    p.keyboard.press("Control+Enter")
    until(lambda: len(held) == 2 or p.wait_for_timeout(20), what="the new comment to go out")
    held[0].continue_()
    toasted(p, "no comment")
    held[1].continue_()
    p.unroute("**/_/comment")
    until(lambda: any(c.body == "about the pears" for c in rdc.parse(f.read_text()).comments), what="the new comment in the file")
    until(lambda: "about the pears" not in comment_store(thread), what="the page to take the answer in")
    p.wait_for_timeout(300)
    assert p.input_value("#rd-popover textarea") == "words for a gone thread"
    assert "“apples”, which was deleted" in p.inner_text("#rd-popover")


# The thread's buttons were visible again as soon as a form was sent, so Reply clicked a second time
# opened a second form beside the one that came back from a failed send, and Resolve or Delete acted
# under the send. They stay hidden until the answer.
@pytest.mark.parametrize("form", ["reply", "edit"])
def test_the_threads_buttons_stay_hidden_while_a_reply_or_edit_is_being_sent_and_a_failed_send_gives_back_one_form(thread, form):
    p = thread.page
    held = send_held(thread, form, "words in the air")
    p.wait_for_timeout(100)
    assert not p.is_visible("#rd-popover .rd-actions"), "the thread's buttons are on the page during the send"
    fail_the_send(p, held)
    assert p.locator("#rd-popover .rd-form").count() == 1
    assert p.input_value("#rd-popover textarea") == "words in the air"
    assert not p.is_visible("#rd-popover > .rd-actions"), "the thread's buttons are on the page beside the form"


def test_the_threads_buttons_come_back_when_the_send_is_taken(thread):
    p = thread.page
    held = send_held(thread, "reply", "a reply that goes through")
    held[0].continue_()
    p.unroute("**/_/comment")
    f = thread.site.file
    until(lambda: "a reply that goes through" in f.read_text(), what="the reply in the file")
    until(lambda: p.locator("#rd-popover .rd-form").count() == 0, what="the sent form to go")
    assert p.is_visible("#rd-popover button[data-a=reply]"), "the thread's buttons did not come back"
    until(lambda: "a reply that goes through" in p.inner_text("#rd-popover"), what="the reply in the thread")


# `next_id` reuses a deleted last id, and a kept reply or edit was matched
# to its thread by that id alone, so a new comment opened with the old text in its form.
@pytest.mark.parametrize("form, then", [("reply", ""), ("edit", "About the pears")])
def test_a_kept_reply_or_edit_is_not_put_into_a_new_comment_that_got_the_id_of_a_deleted_one(thread, form, then):
    failed_send(thread, form, "words of the comment that is gone")
    (old,) = rdc.parse(thread.site.file.read_text()).comments
    delete_the_thread(thread)
    p = thread.page
    p.reload()
    p.wait_for_selector("#rd-menu-btn", state="attached")
    new = comment_on(thread, at(P2, "pears"), at(P2, "pears", None), "About the pears")
    assert new.id == old.id
    p.wait_for_selector("#rd-popover .rd-msg")
    p.wait_for_timeout(300)
    assert p.query_selector("#rd-popover textarea") is None
    p.click(f"#rd-popover button[data-a={form}]")
    assert p.input_value("#rd-popover textarea") == then


# A kept entry's `block` is the index of the render before the refusal. Once a
# paragraph was added above, that index is another paragraph, and its form took the kept text.
def test_a_kept_comment_is_not_put_into_the_form_of_the_paragraph_that_took_its_block_index(kept):
    f = kept.site.file
    mark(kept.page)
    f.write_text(f.read_text().replace("First paragraph", "A paragraph added above.\n\nFirst paragraph", 1), encoding="utf-8")
    reloaded(kept.page)
    kept.page.wait_for_selector(KEPT)
    open_comment_form(kept, P2, "apples")
    assert kept.page.input_value("#rd-popover textarea") == ""
    kept.page.click("#rd-popover button[data-f=no]")
    assert "about the pears" in comment_store(kept)
    open_comment_form(kept, "main p:nth-of-type(4)", "ripe pears")
    assert kept.page.input_value("#rd-popover textarea") == "about the pears"


# An entry kept by the build that came before the opening words (it has a `block` and no `head`) is
# still matched by its block, as it was: the upgrade must not turn a kept comment into one that stays unseen.
def test_a_kept_comment_without_opening_words_still_comes_back_by_its_block(kept):
    key = comment_draft_key(kept.site)
    ds = json.loads(comment_store(kept))
    for d in ds:
        del d["head"]
    kept.page.evaluate("([k, v]) => localStorage.setItem(k, v)", [key, json.dumps(ds)])
    open_comment_form(kept, P2, "ripe pears")
    assert kept.page.input_value("#rd-popover textarea") == "about the pears"


# Two blocks that open with the same words (two tables with one header
# row, "On the other hand ..." twice) must not trade kept text, or the Cancel of one removes the entry
# of the other. Opening words alone tell a block only when no other block opens like it.
def test_a_kept_comment_is_not_put_into_the_form_of_another_paragraph_that_opens_with_the_same_words(kept):
    f = kept.site.file
    mark(kept.page)
    f.write_text(f.read_text().replace("Second paragraph, about ripe pears.", "Second paragraph, about ripe pears.\n\nSecond paragraph, about plums."), encoding="utf-8")
    reloaded(kept.page)
    kept.page.wait_for_selector(KEPT)
    open_comment_form(kept, "main p:nth-of-type(4)", "plums")
    assert kept.page.input_value("#rd-popover textarea") == ""
    kept.page.click("#rd-popover button[data-f=no]")
    assert "about the pears" in comment_store(kept)
    open_comment_form(kept, P2, "ripe pears")
    assert kept.page.input_value("#rd-popover textarea") == "about the pears"


# A new comment answered while a reply is still out waits for the reply (holdForOpenForm); its popover
# closes, and the reload that runs when the reply is answered opens the new comment's thread, as it
# does when the new comment is answered last.
def test_a_new_comment_answered_while_a_reply_is_out_has_its_thread_open_after_the_reload(two_threads):
    p, f = two_threads.page, two_threads.site.file
    held = first_send_held(two_threads)
    open_reply(two_threads, "first reply")
    p.keyboard.press("Control+Enter")
    until(lambda: held or p.wait_for_timeout(20), what="the reply to go out")
    f.write_text(f.read_text() + "\nA new paragraph from outside.\n", encoding="utf-8")
    p.wait_for_timeout(500)
    open_thread_by(two_threads, "the Comment button")
    p.fill("#rd-popover textarea", "second words")
    mark(p)
    p.keyboard.press("Control+Enter")
    until(lambda: any(c.body == "second words" for c in rdc.parse(f.read_text()).comments), what="the new comment in the file")
    until(lambda: "second words" not in comment_store(two_threads), what="the page to take the answer in")
    held[0].continue_()
    p.unroute("**/_/comment")
    until(lambda: "first reply" in f.read_text(), what="the reply in the file")
    reloaded(p)
    p.wait_for_selector("#rd-popover .rd-msg:has-text('second words')", timeout=5000)


def test_the_badge_of_a_new_comment_answered_while_a_reply_is_out_opens_its_thread_before_the_reload(two_threads):
    p, f = two_threads.page, two_threads.site.file
    held = first_send_held(two_threads)
    open_reply(two_threads, "first reply")
    p.keyboard.press("Control+Enter")
    until(lambda: held or p.wait_for_timeout(20), what="the reply to go out")
    f.write_text(f.read_text() + "\nA new paragraph from outside.\n", encoding="utf-8")
    p.wait_for_timeout(500)
    open_thread_by(two_threads, "the Comment button")
    p.fill("#rd-popover textarea", "second words")
    mark(p)
    p.keyboard.press("Control+Enter")
    until(lambda: any(c.body == "second words" for c in rdc.parse(f.read_text()).comments), what="the new comment in the file")
    until(lambda: "second words" not in comment_store(two_threads), what="the page to take the answer in")
    n = p.locator(".rd-badge").count()

    def opens():
        for i in range(n):
            p.locator(".rd-badge").nth(i).dispatch_event("click")
            if p.locator("#rd-popover .rd-msg:has-text('second words')").count():
                return True
        return False
    until(opens, what="a badge to open the thread of the new comment")
    assert p.evaluate("window.__same_load") is True, "the page reloaded under the reply"
    held[0].continue_()
    p.unroute("**/_/comment")
    until(lambda: "first reply" in f.read_text(), what="the reply in the file")
    reloaded(p)


# What a held reload says after it has run is what it brought. Here only a comment from outside arrived,
# which applyComments could not place.
def test_a_reload_held_for_a_comment_from_outside_does_not_say_the_text_changed(two_threads):
    p, f = two_threads.page, two_threads.site.file
    held = first_send_held(two_threads)
    open_reply(two_threads, "first reply")
    p.keyboard.press("Control+Enter")
    until(lambda: held or p.wait_for_timeout(20), what="the reply to go out")
    comment(f, quote="Last paragraph", body="From outside", by="Ada")
    p.wait_for_timeout(500)
    open_thread_by(two_threads, "the Comment button")
    p.fill("#rd-popover textarea", "second words")
    mark(p)
    p.keyboard.press("Control+Enter")
    until(lambda: any(c.body == "second words" for c in rdc.parse(f.read_text()).comments), what="the new comment in the file")
    until(lambda: "second words" not in comment_store(two_threads), what="the page to take the answer in")
    assert p.evaluate("window.__same_load") is True, "the page reloaded under the reply"
    held[0].continue_()
    p.unroute("**/_/comment")
    reloaded(p)
    p.wait_for_selector("#rd-menu-btn", state="attached")
    p.wait_for_timeout(1500)
    assert "while you wrote" not in toast(p)


def test_a_settle_that_failed_leaves_no_held_reload_to_a_later_upgrade(thread):
    p, f = thread.page, thread.site.file
    p.keyboard.press("e")
    p.route("**/_/save", lambda route: route.fulfill(status=500, json={"ok": False, "error": "the hub broke off"}))
    open_reply(thread, "my reply text")
    f.write_text(f.read_text() + "\nA new paragraph from outside.\n", encoding="utf-8")
    p.wait_for_selector("#rd-popover .rd-hold")
    held = []
    p.route("**/_/comment", lambda route: held.append(route))
    p.keyboard.press("Control+Enter")
    until(lambda: held or p.wait_for_timeout(20), what="the reply to go out")
    p.evaluate(f"document.querySelector({P2!r}).append(' and plums')")      # on screen only, no autosave
    held[0].continue_()
    p.unroute("**/_/comment")
    toasted(p, "could not be merged")
    p.evaluate(f"document.querySelector({P2!r}).lastChild.remove()")       # the edit undone: nothing is dirty
    mark(p)
    thread.site.stop("upgrade")
    thread.site.start(version="99.0.0")
    reloaded(p, timeout=15)
    p.wait_for_selector("#rd-menu-btn", state="attached")
    p.wait_for_timeout(1500)
    assert "while you wrote" not in toast(p)


def test_a_kept_comment_carries_the_root_of_the_folder_that_kept_it(tab):
    tab.open()
    refuse_a_comment_on_pears(tab)
    root = json.loads(tab.page.evaluate("document.querySelector('script[type=\"application/json\"]').textContent"))["root"]
    got = json.loads(tab.page.evaluate(f"localStorage.getItem({comment_draft_key(tab.site)!r})"))
    assert [d["root"] for d in got] == [root]


def test_a_kept_comment_of_another_folder_is_neither_shown_nor_dropped(tab):
    tab.open()
    theirs = {"root": "not-this-one", "quote": "pears", "body": "theirs", "block": 2, "head": "x", "at": "2026-10-21T10:00:00Z"}
    tab.page.evaluate("([k, v]) => localStorage.setItem(k, v)", [comment_draft_key(tab.site), json.dumps([theirs])])
    tab.page.reload()
    tab.page.wait_for_selector("#rd-menu-btn", state="attached")
    assert tab.page.query_selector("#rd-popover[data-kept]") is None
    refuse_a_comment_on_pears(tab)
    assert tab.page.input_value("#rd-popover textarea") == "about the pears"
    got = json.loads(tab.page.evaluate(f"localStorage.getItem({comment_draft_key(tab.site)!r})"))
    assert sorted(d["body"] for d in got) == ["about the pears", "theirs"]
    # Sending it clears only its own entry.
    select(tab.page, at(P2, "pears"), at(P2, "pears", None))
    tab.page.click("#rd-comment-btn")
    tab.page.click("#rd-popover button[data-f=ok]")
    until(lambda: [d["body"] for d in json.loads(tab.page.evaluate(f"localStorage.getItem({comment_draft_key(tab.site)!r})"))] == ["theirs"],
          what="only its own entry to leave the store")


def test_a_kept_comment_of_an_earlier_build_with_no_root_is_this_pages_own(tab):
    tab.open()
    old = {"quote": "pears", "body": "about the pears", "block": 2, "head": "x", "at": "2026-10-01T10:00:00Z"}
    tab.page.evaluate("([k, v]) => localStorage.setItem(k, v)", [comment_draft_key(tab.site), json.dumps([old])])
    select(tab.page, at(P2, "pears"), at(P2, "pears", None))
    tab.page.click("#rd-comment-btn")
    assert tab.page.input_value("#rd-popover textarea") == "about the pears"


# A line typed as `- [ ] text` is a task box after the save, and the box ticks and saves.
@pytest.mark.parametrize("typed, written, checked, after_tick",
                         [("- [ ] taakvakje", "- [ ] taakvakje", False, "- [x] taakvakje"),
                          ("* [x] done one", "- [x] done one", True, "- [ ] done one")],
                         ids=["open", "done"])
def test_a_typed_task_line_is_a_task_box_after_the_save_and_it_ticks(tab, typed, written, checked, after_tick):
    p, f = tab.page, tab.site.file
    tab.open()
    p.keyboard.press("e")
    p.click(P1)
    p.keyboard.press(key("End"))
    p.keyboard.press("Enter")
    p.keyboard.type(typed)
    before = f.read_text()
    mark(p)
    p.keyboard.press("Control+s")
    until(lambda: f.read_text() != before, what="the save in the file")
    saved = f.read_text()
    assert written in saved and "\\[" not in saved
    reloaded(p)
    p.wait_for_selector("main input[type=checkbox]")
    box = p.locator("main input[type=checkbox]")
    assert box.count() == 1 and box.is_checked() is checked
    assert p.locator("main p.rd-locked, main div.rd-locked").count() == 0
    mark(p)
    box.click()
    until(lambda: after_tick in f.read_text(), what="the tick in the file")


def test_a_bracket_pair_in_the_middle_of_a_typed_line_stays_text(tab):
    p, f = tab.page, tab.site.file
    tab.open()
    p.keyboard.press("e")
    p.click(P1)
    p.keyboard.press(key("End"))
    p.keyboard.press("Enter")
    p.keyboard.type("buy [ ] later")
    before = f.read_text()
    mark(p)
    p.keyboard.press("Control+s")
    until(lambda: f.read_text() != before, what="the save in the file")
    reloaded(p)
    assert p.locator("main input[type=checkbox]").count() == 0
    assert "buy [ ] later" in p.inner_text("main")


def test_a_typed_task_box_whose_words_were_deleted_keeps_its_characters_and_no_box_character(tab):
    p, f = tab.page, tab.site.file
    tab.open()
    p.keyboard.press("e")
    p.click(P1)
    p.keyboard.press(key("End"))
    p.keyboard.press("Enter")
    p.keyboard.type("- [ ] x")
    p.keyboard.press("Backspace")
    before = f.read_text()
    mark(p)
    p.keyboard.press("Control+s")
    until(lambda: f.read_text() != before, what="the save in the file")
    saved = f.read_text()
    assert "☐" not in saved and "- [ ]" not in saved.replace("\\- \\[ \\]", "")
    reloaded(p)
    assert p.locator("main input[type=checkbox]").count() == 0


def _enter_in_task_list(tab, tasks, item, keys):
    """A `.md` with the given task lines, edit mode, the caret at the end of the item holding `item`, then `keys`
    typed ("Enter" is pressed, anything else typed); returns the file text after the save."""
    p, f = tab.page, tab.site.file
    f.write_text(f.read_text() + "\n" + tasks, encoding="utf-8")
    tab.open()
    p.keyboard.press("e")
    p.click(f"main li:has-text('{item}')")
    p.keyboard.press(key("End"))
    for k in keys:
        if k == "Enter":
            p.keyboard.press("Enter")
        else:
            p.keyboard.type(k)
    before = f.read_text()
    mark(p)
    p.keyboard.press("Control+s")
    until(lambda: f.read_text() != before, what="the save in the file")
    return f.read_text()


def test_enter_inside_a_task_item_makes_a_task_item_with_an_unticked_box(tab):
    saved = _enter_in_task_list(tab, "- [ ] first task\n- [ ] second task\n", "first task", ["Enter", "new one"])
    assert "- [ ] first task\n- [ ] new one\n- [ ] second task" in saved
    assert "<div" not in saved and "☐" not in saved
    p = tab.page
    p.reload()
    p.wait_for_selector("main input[type=checkbox]")
    assert p.locator("main input[type=checkbox]").count() == 3 and "new one" in p.inner_text("main")
    assert p.locator("main input[type=checkbox]:checked").count() == 0
    assert p.locator("main div.rd-locked, main p.rd-locked").count() == 0


def test_enter_in_a_ticked_task_item_makes_an_unticked_one(tab):
    saved = _enter_in_task_list(tab, "- [x] done task\n- [ ] open task\n", "done task", ["Enter", "new one"])
    assert "- [x] done task\n- [ ] new one\n- [ ] open task" in saved


def test_enter_in_the_middle_of_a_task_item_splits_it_into_two_task_items(tab):
    p = tab.page
    tab.site.file.write_text(tab.site.file.read_text() + "\n- [ ] first task\n", encoding="utf-8")
    tab.open()
    p.keyboard.press("e")
    p.click("main li:has-text('first task')")
    p.keyboard.press(key("End"))
    for _ in range(len(" task")):
        p.keyboard.press("ArrowLeft")
    p.keyboard.press("Enter")
    before = tab.site.file.read_text()
    mark(p)
    p.keyboard.press("Control+s")
    until(lambda: tab.site.file.read_text() != before, what="the save in the file")
    assert "- [ ] first\n- [ ] task\n" in tab.site.file.read_text()


def test_enter_on_an_empty_task_item_ends_the_list(tab):
    saved = _enter_in_task_list(tab, "- [ ] first task\n- [ ] second task\n", "second task",
                                ["Enter", "Enter", "after the list"])
    assert saved.rstrip().endswith("- [ ] first task\n- [ ] second task\n\nafter the list")
    assert "- [ ] after the list" not in saved and "- [ ] \n" not in saved and "☐" not in saved


def test_enter_on_an_empty_task_item_in_the_middle_ends_the_list_there(tab):
    saved = _enter_in_task_list(tab, "- [ ] first task\n- [ ] second task\n", "first task",
                                ["Enter", "Enter", "between"])
    assert "- [ ] first task\n\nbetween\n\n- [ ] second task" in saved


def test_enter_at_the_start_of_a_task_item_moves_the_words_and_leaves_one_box_in_each_item(tab):
    p = tab.page
    tab.site.file.write_text(tab.site.file.read_text() + "\n- [ ] first task\n- [ ] second task\n", encoding="utf-8")
    tab.open()
    p.keyboard.press("e")
    p.click("main li:has-text('first task')")
    p.keyboard.press(key("Home"))
    p.keyboard.press("Enter")
    assert p.locator("main li input[type=checkbox]").count() == 3
    assert p.locator("main li:has-text('first task') input[type=checkbox]").count() == 1


def test_enter_on_the_only_item_of_a_task_list_when_it_is_empty_keeps_the_list(tab):
    p = tab.page
    tab.site.file.write_text(tab.site.file.read_text() + "\n- [ ] only\n", encoding="utf-8")
    tab.open()
    p.keyboard.press("e")
    p.click("main li:has-text('only')")
    p.keyboard.press(key("End"))
    for _ in range(len("only")):
        p.keyboard.press("Backspace")
    p.keyboard.press("Enter")
    assert p.locator("main li input[type=checkbox]").count() == 1


def test_enter_at_the_end_of_a_task_item_then_a_pause_saves_no_box_character(tab):
    p, f = tab.page, tab.site.file
    f.write_text(f.read_text() + "\n- [ ] first task\n- [ ] second task\n", encoding="utf-8")
    tab.open()
    p.keyboard.press("e")
    p.click("main li:has-text('first task')")
    p.keyboard.press(key("End"))
    p.keyboard.press("Enter")
    p.wait_for_timeout(3500)  # the autosave runs on its own after a pause in typing
    assert "☐" not in f.read_text() and "<!--" not in f.read_text().replace("<!-- sheaf", "")
    p.keyboard.type("new one")
    before = f.read_text()
    mark(p)
    p.keyboard.press("Control+s")
    until(lambda: f.read_text() != before, what="the save in the file")
    assert "- [ ] first task\n- [ ] new one\n- [ ] second task" in f.read_text()


def test_enter_on_an_empty_item_then_a_pause_saves_no_comment_marker_between_the_lists(tab):
    p, f = tab.page, tab.site.file
    f.write_text(f.read_text() + "\n- [ ] first task\n- [ ] second task\n", encoding="utf-8")
    tab.open()
    p.keyboard.press("e")
    p.click("main li:has-text('first task')")
    p.keyboard.press(key("End"))
    p.keyboard.press("Enter")
    p.keyboard.press("Enter")
    p.wait_for_timeout(3500)
    assert "<!--" not in f.read_text() and "☐" not in f.read_text()
    p.keyboard.type("between")
    before = f.read_text()
    mark(p)
    p.keyboard.press("Control+s")
    until(lambda: f.read_text() != before, what="the save in the file")
    assert "- [ ] first task\n\nbetween\n\n- [ ] second task" in f.read_text()


def test_enter_at_the_start_of_a_task_item_then_a_save_keeps_the_words_in_a_task_item(tab):
    p, f = tab.page, tab.site.file
    f.write_text(f.read_text() + "\n- [ ] first task\n- [ ] second task\n", encoding="utf-8")
    tab.open()
    p.keyboard.press("e")
    p.click("main li:has-text('first task')")
    p.keyboard.press(key("Home"))
    p.keyboard.press("Enter")
    p.keyboard.type("X")
    before = f.read_text()
    mark(p)
    p.keyboard.press("Control+s")
    until(lambda: f.read_text() != before, what="the save in the file")
    assert "☐" not in f.read_text() and "- [ ] Xfirst task\n- [ ] second task" in f.read_text()


def test_enter_over_all_the_words_of_a_task_item_keeps_its_box(tab):
    p, f = tab.page, tab.site.file
    f.write_text(f.read_text() + "\n- [x] first task\n- [ ] second task\n", encoding="utf-8")
    tab.open()
    p.keyboard.press("e")
    p.click("main li:has-text('first task')")
    p.keyboard.press(key("Home"))
    p.keyboard.press(key("Shift+End"))
    p.keyboard.press("Enter")
    p.keyboard.type("new")
    # the emptied item keeps its ticked box (saved as an emptied ticked item is, whatever emptied it)
    assert p.locator("main li input[type=checkbox]").count() == 3
    assert p.locator("main li input[type=checkbox]:checked").count() == 1
    before = f.read_text()
    mark(p)
    p.keyboard.press("Control+s")
    until(lambda: f.read_text() != before, what="the save in the file")
    assert "- [ ] new\n- [ ] second task" in f.read_text()


def test_enter_in_a_bold_word_in_a_task_item_adds_no_space_before_the_rest_of_it(tab):
    p, f = tab.page, tab.site.file
    f.write_text(f.read_text() + "\n- [ ] a **bold**\n", encoding="utf-8")
    tab.open()
    p.keyboard.press("e")
    p.click("main li:has-text('a bold')")
    p.evaluate("""() => {
      const s = document.querySelector('main li strong'), r = document.createRange();
      r.setStart(s.firstChild, 2); r.collapse(true);
      getSelection().removeAllRanges(); getSelection().addRange(r);
    }""")
    p.keyboard.press("Enter")
    p.keyboard.type("Z")
    before = f.read_text()
    mark(p)
    p.keyboard.press("Control+s")
    until(lambda: f.read_text() != before, what="the save in the file")
    out = f.read_text()
    assert "\u00a0" not in out and "- [ ] a **bo**\n- [ ] Z**ld**" in out


def test_enter_three_times_after_an_item_then_a_pause_saves_no_comment_marker_between_the_lists(tab):
    p, f = tab.page, tab.site.file
    f.write_text(f.read_text() + "\n- [ ] first task\n- [ ] second task\n", encoding="utf-8")
    tab.open()
    p.keyboard.press("e")
    p.click("main li:has-text('first task')")
    p.keyboard.press(key("End"))
    for _ in range(3):
        p.keyboard.press("Enter")
    p.wait_for_timeout(3500)
    assert "<!--" not in f.read_text().replace("<!-- sheaf", "") and "☐" not in f.read_text()
    p.keyboard.type("between")
    before = f.read_text()
    mark(p)
    p.keyboard.press("Control+s")
    until(lambda: f.read_text() != before, what="the save in the file")
    assert "- [ ] first task\n\nbetween\n\n- [ ] second task" in f.read_text()


def _enter_before_the_words_of_the_first_item(tab, box, place):
    """`- [<box>] first task` and a second item; `place(p)` puts the caret or the selection, then Enter, `X`, a save:
    the file text. The caret between the box and the first letter is not at the start of the item for the browser
    (the label's offset 1), but it is for the writer: the words stay in the item and an empty one goes above."""
    p, f = tab.page, tab.site.file
    f.write_text(f.read_text() + f"\n- [{box}] first task\n- [ ] second task\n", encoding="utf-8")
    tab.open()
    p.keyboard.press("e")
    p.click("main li:has-text('first task')")
    place(p)
    p.keyboard.press("Enter")
    p.keyboard.type("X")
    before = f.read_text()
    mark(p)
    p.keyboard.press("Control+s")
    until(lambda: f.read_text() != before, what="the save in the file")
    return f.read_text()


@pytest.mark.parametrize("box", [" ", "x"])
def test_enter_with_the_caret_walked_back_to_the_first_letter_keeps_the_words_in_their_item(tab, box):
    def place(p):
        p.keyboard.press(key("End"))
        for _ in range(len("first task")):
            p.keyboard.press("ArrowLeft")
    saved = _enter_before_the_words_of_the_first_item(tab, box, place)
    assert f"- [{box}] Xfirst task\n- [ ] second task" in saved and "☐" not in saved and "☒" not in saved


def test_enter_with_a_click_just_before_the_first_letter_keeps_the_words_in_their_item(tab):
    def place(p):
        r = p.evaluate("""() => {
          const li = [...document.querySelectorAll('main li')].find(l => l.textContent.includes('first task')), w = document.createTreeWalker(li, NodeFilter.SHOW_TEXT);
          let t; while (w.nextNode()) if (w.currentNode.nodeValue.includes('first')) { t = w.currentNode; break; }
          const g = document.createRange(); g.setStart(t, t.nodeValue.indexOf('first')); g.setEnd(t, t.nodeValue.indexOf('first') + 1);
          const b = g.getBoundingClientRect(); return {x: b.left + 1, y: b.top + b.height / 2};
        }""")
        p.mouse.click(r["x"], r["y"])
    saved = _enter_before_the_words_of_the_first_item(tab, "x", place)
    assert "- [x] Xfirst task\n- [ ] second task" in saved and "☐" not in saved and "☒" not in saved


def test_enter_over_the_box_alone_keeps_the_words_in_their_item(tab):
    def place(p):
        p.keyboard.press(key("Home"))
        p.keyboard.press("Shift+ArrowRight")
    saved = _enter_before_the_words_of_the_first_item(tab, "x", place)
    assert "- [x] Xfirst task\n- [ ] second task" in saved and "☐" not in saved and "☒" not in saved


def test_a_task_typed_in_the_paragraph_that_ending_a_list_left_joins_the_lists(tab):
    p, f = tab.page, tab.site.file
    f.write_text(f.read_text() + "\n- [ ] first task\n- [ ] second task\n", encoding="utf-8")
    tab.open()
    p.keyboard.press("e")
    p.click("main li:has-text('first task')")
    p.keyboard.press(key("End"))
    p.keyboard.press("Enter")
    p.keyboard.press("Enter")
    p.keyboard.type("- [ ] typed")
    before = f.read_text()
    mark(p)
    p.keyboard.press("Control+s")
    until(lambda: f.read_text() != before, what="the save in the file")
    saved = f.read_text()
    assert "- [ ] first task\n- [ ] typed\n- [ ] second task" in saved and "<!--" not in saved.replace("<!-- sheaf", "")


def test_enter_in_the_middle_of_a_task_item_then_typing_saves_no_no_break_space(tab):
    p, f = tab.page, tab.site.file
    f.write_text(f.read_text() + "\n- [ ] first task\n- [ ] two\n", encoding="utf-8")
    tab.open()
    p.keyboard.press("e")
    p.click("main li:has-text('first task')")
    p.keyboard.press(key("End"))
    for _ in range(len(" task")):
        p.keyboard.press("ArrowLeft")
    p.keyboard.press("Enter")
    p.keyboard.type("New")
    before = f.read_text()
    mark(p)
    p.keyboard.press("Control+s")
    until(lambda: f.read_text() != before, what="the save in the file")
    saved = f.read_text()
    assert "\u00a0" not in saved and "- [ ] first\n- [ ] Newtask\n- [ ] two" in saved


def test_enter_over_a_selection_across_two_task_items_changes_nothing(tab):
    p, f = tab.page, tab.site.file
    f.write_text(f.read_text() + "\n- [ ] first task\n- [ ] second task\n", encoding="utf-8")
    tab.open()
    p.keyboard.press("e")
    p.click("main li:has-text('first task')")
    p.keyboard.press(key("End"))
    for _ in range(len("first task")):
        p.keyboard.press("Shift+ArrowLeft")
    p.keyboard.press("Shift+ArrowDown")
    items = (p.locator("main li").count(), p.locator("main li input[type=checkbox]").count())
    p.keyboard.press("Enter")
    assert (p.locator("main li").count(), p.locator("main li input[type=checkbox]").count()) == items
    assert "☐" not in p.inner_text("main")


def _caret_in_last_item(p, words, at_end=True):
    """The caret in the last list item whose text holds `words`, at the end of its last text node holding the last
    word (or at the start of it)."""
    p.evaluate("""([t, e]) => {
      const li = [...document.querySelectorAll('main li')].reverse()
        .find(l => l.textContent.replace(/\\s+/g, ' ').includes(t));
      const w = document.createTreeWalker(li, NodeFilter.SHOW_TEXT);
      let tn = null;
      while (w.nextNode()) if (w.currentNode.nodeValue.includes(t.split(' ').pop())) tn = w.currentNode;
      const r = document.createRange();
      r.setStart(tn, e ? tn.length : 0);
      r.collapse(true);
      li.closest('[contenteditable]').focus();
      const s = getSelection();
      s.removeAllRanges();
      s.addRange(r);
    }""", [words, at_end])


def test_enter_at_the_end_of_a_commented_task_item_leaves_the_comment_with_its_words(tab):
    from helpers import comment
    p, f = tab.page, tab.site.file
    f.write_text(f.read_text() + "\n- [ ] first task\n- [ ] other\n", encoding="utf-8")
    comment(f, quote="first task")
    tab.open()
    p.keyboard.press("e")
    _caret_in_last_item(p, "first task")
    p.keyboard.press("Enter")
    p.keyboard.type("new one")
    before = f.read_text()
    mark(p)
    p.keyboard.press("Control+s")
    until(lambda: f.read_text() != before, what="the save in the file")
    saved = f.read_text()
    assert "☐" not in saved and "- [ ] new one" in saved
    p.reload()
    p.wait_for_selector("main input[type=checkbox]")
    assert p.locator("main li:has(input[type=checkbox]) .rd-anchor").count() == 1
    assert p.locator("main li:has(input[type=checkbox]):has(.rd-anchor)").first.inner_text().strip().startswith("first task")


def test_enter_on_a_loose_task_item_with_an_empty_first_line_keeps_its_other_paragraph(tab):
    p, f = tab.page, tab.site.file
    f.write_text(f.read_text() + "\n- [ ] first\n\n  second para\n- [ ] other\n", encoding="utf-8")
    tab.open()
    p.keyboard.press("e")
    _caret_in_last_item(p, "first")
    for _ in range(5):
        p.keyboard.press("Backspace")
    p.keyboard.press("Enter")
    assert "second para" in p.inner_text("main")


# ── an unreachable hub, said for what failed ───────────────────────────────────

@pytest.mark.parametrize("what", ["ask", "tell", "cancel-tell"])
def test_an_ask_tell_or_cancel_the_hub_cannot_be_reached_for_says_that_it_did_not_go_out(agent, thread, what):
    # "nothing was saved. Your edits stay on screen" is the sentence of a save; these save nothing.
    p = thread.page
    if what == "cancel-tell":
        thread.page.click("#rd-popover button[data-a=tell]")
        p.wait_for_selector("#rd-popover button[data-a=cancel-tell]")
    p.route(f"**/_/{what.split('-')[0]}", lambda route: route.abort())
    p.click(f"#rd-popover button[data-a={what}]")
    until(lambda: "did not go out" in toast(p) or p.wait_for_timeout(20), what="the toast")
    says = toast(p)
    assert "nothing was saved" not in says
    assert says.startswith({"ask": "Ask", "tell": "Tell", "cancel-tell": "Cancel"}[what])
    p.unroute(f"**/_/{what.split('-')[0]}")


# A comment, reply, edit, status change or deletion the hub cannot be reached for saves nothing either: the
# page says what did not go out, as for an Ask, Tell or Cancel, not "nothing was saved".
@pytest.mark.parametrize("what, says", [("reply", "Your reply"), ("edit", "Your edit"), ("status", "The status change"),
                                         ("delete", "The deletion"), ("comment", "Your comment")])
def test_a_comment_reply_edit_status_or_deletion_the_hub_cannot_be_reached_for_says_that_it_did_not_go_out(thread, what, says):
    p = thread.page
    if what == "comment":
        p.keyboard.press("Escape")
        open_comment_form(thread, P2, "pears")
        p.fill("#rd-popover textarea", "never sent")
    elif what in ("reply", "edit"):
        p.click(f"#rd-popover button[data-a={what}]")
        p.fill("#rd-popover textarea", "never sent")
    p.route("**/_/comment", lambda route: route.abort())
    p.click("#rd-popover button[data-f=ok]" if what in ("reply", "edit", "comment") else f"#rd-popover button[data-a={what}]")
    until(lambda: "did not go out" in toast(p) or p.wait_for_timeout(20), what="the toast")
    assert toast(p) == f"{says} did not go out: the hub is unreachable."
    p.unroute("**/_/comment")


# ── the popover that stays over a deleted thread ───────────────────────────────

def test_a_reload_that_waits_for_a_form_in_a_deleted_thread_says_so_on_that_form(thread):
    p = thread.page
    open_reply(thread, "words for a gone thread")
    delete_comment(thread, 0)
    p.wait_for_selector("#rd-popover .rd-gone")
    outside_change(thread)
    p.wait_for_selector("#rd-popover .rd-hold:has-text('The page refreshes when you send or cancel')")
    assert p.input_value("#rd-popover textarea") == "words for a gone thread"


def test_a_reply_refused_because_its_thread_is_gone_comes_back_where_the_popover_was(thread):
    p = thread.page
    before = p.locator("#rd-popover").bounding_box()
    held = gone_and_sent(thread, "words for a gone thread")
    refused(p, held)
    until(lambda: p.locator("#rd-popover textarea").count() == 1, what="the form to come back")
    after = p.locator("#rd-popover").bounding_box()
    assert abs(after["x"] - before["x"]) < 2 and abs(after["y"] - before["y"]) < 2, (before, after)


# ── a reply shows in its thread at once, though the reload waits ────────────────

def test_a_reply_taken_while_the_reload_waits_for_another_send_shows_in_its_thread_at_once(two_threads):
    # A comment from outside that applyComments cannot place makes every answer ask for a reload, which
    # waits for the first reply, still out. The second reply is in the file and its thread is open: it shows.
    p, f = two_threads.page, two_threads.site.file
    held = first_send_held(two_threads)
    open_reply(two_threads, "first reply")
    p.keyboard.press("Control+Enter")
    until(lambda: held or p.wait_for_timeout(20), what="the first reply to go out")
    comment(f, quote="Last paragraph", body="From outside", by="Ada")
    p.wait_for_timeout(500)
    open_thread_by(two_threads, "a badge")
    p.wait_for_selector("#rd-popover button[data-a=reply]")
    mark(p)
    open_reply(two_threads, "second reply")
    p.keyboard.press("Control+Enter")
    until(lambda: "second reply" in f.read_text(), what="the second reply in the file")
    p.wait_for_selector("#rd-popover .rd-msg:has-text('second reply')", timeout=5000)
    assert p.evaluate("window.__same_load") is True, "the page reloaded under the first reply"
    held[0].continue_()
    p.unroute("**/_/comment")
    reloaded(p)


# What is typed into the form that a failed send brings back, and a form that is emptied and closed: the
# store follows both.
def fail_a_reply(tab, text):
    p, held = tab.page, []
    p.click("#rd-popover button[data-a=reply]")
    p.fill("#rd-popover textarea", text)
    p.route("**/_/comment", lambda route: held.append(route))
    p.keyboard.press("Control+Enter")
    try:
        until(lambda: held or p.wait_for_timeout(20), what="the send to go out")
        held[0].abort()
        p.unroute("**/_/comment")
        p.wait_for_selector("#rd-popover textarea")
    except Exception as e:
        raise RuntimeError(f"the failed send did not bring its form back: {e}") from e


def test_text_typed_into_the_form_a_failed_send_brought_back_comes_back_after_the_tab_is_closed(thread):
    p = thread.page
    fail_a_reply(thread, "sent words")
    p.click("#rd-popover textarea")
    p.keyboard.press(key("End"))
    p.keyboard.type(" and more")
    p.reload()
    p.wait_for_selector("#rd-menu-btn", state="attached")
    p.click(".rd-badge")
    p.wait_for_selector("#rd-popover textarea")
    assert kept_text(thread) == "sent words and more", "the later typing is not in the store"


def test_a_form_that_a_failed_send_brought_back_and_was_emptied_and_closed_with_escape_is_not_offered_again(thread):
    p = thread.page
    fail_a_reply(thread, "sent words")
    p.fill("#rd-popover textarea", "")
    p.keyboard.press("Escape")
    p.wait_for_selector("#rd-popover", state="detached")
    p.click(".rd-badge")
    p.wait_for_selector("#rd-popover .rd-scroll")
    p.wait_for_timeout(300)
    assert p.locator("#rd-popover textarea").count() == 0, "the emptied form is offered again"
    assert "sent words" not in comment_store(thread), "the emptied form's text is still in the store"


# ── a send the hub took, heard before the page gave up on it ─────────────────────

@pytest.fixture
def answer_after_event(tab):
    """hold(): the hub tells the tabs of each comment it writes at once, and answers the request only at release()."""
    go = threading.Event()

    def hold():
        live = tab.site.hub.entry(DOC).live
        announce = live._announce

        def slow(*args, **kwargs):
            got = announce(*args, **kwargs)
            go.wait(30)
            return got
        live._announce = slow
    yield SimpleNamespace(hold=hold, release=go.set)
    go.set()


def test_a_reply_the_hub_took_and_told_of_before_the_page_gave_up_goes_from_the_page_when_it_gives_up(thread, answer_after_event):
    p = thread.page
    reload_on_clock(p)
    p.click(".rd-badge")
    open_reply(thread, SLOW)
    answer_after_event.hold()
    p.keyboard.press("Control+Enter")
    until(lambda: SLOW in thread.site.file.read_text(), what="the hub's write")
    until(lambda: SLOW not in comment_store(thread), what="the page to hear the event of the write")
    p.clock.fast_forward(30_500)
    toasted(p, TAKEN)
    until(lambda: p.locator("#rd-popover textarea").count() == 0, what="the form to go")
    try:
        until(lambda: p.inner_text("#rd-popover").count(SLOW) == 1, what="the reply in its thread")
    except AssertionError as e:
        # It timed out on CI and passed everywhere else (#46): say what the page held, so the next red names it.
        shown = p.inner_text("#rd-popover")
        raise AssertionError(f"{e}: the reply is {shown.count(SLOW)} times in the popover {shown!r}; the file "
                             f"{'holds' if SLOW in thread.site.file.read_text() else 'lacks'} it; the page keeps "
                             f"{comment_store(thread)!r}") from None
    assert SLOW not in comment_store(thread)
    assert p.is_visible("#rd-popover button[data-a=reply]"), "the thread's buttons did not come back"
    answer_after_event.release()


# ── a thread that is gone: the answer that says so, and the form that cannot be sent ─────

def test_a_thread_the_hub_answers_gone_for_closes_its_popover_at_once(thread):
    # The deletion's own event is not coming here: the page learns only from the refusal (410).
    p = thread.page
    p.route("**/_/comment", lambda route: route.fulfill(
        status=410, content_type="application/json", body=json.dumps({"ok": False, "error": "no comment c1 in this document"})))
    p.click("#rd-popover button[data-a=status]")
    until(lambda: p.locator("#rd-popover").count() == 0, what="the popover of the thread that is gone to close")
    p.unroute("**/_/comment")


def test_ctrl_enter_does_not_send_a_reply_into_the_comment_that_took_the_id_of_its_thread(thread):
    p, f, sent = thread.page, thread.site.file, []
    open_reply(thread, "words for the first thread")
    (old,) = rdc.parse(f.read_text()).comments

    def swap(t):
        t = rdc.delete(t, old.id)
        blk, s, e = rdc.find_quote(t, "pears")
        return rdc.add_comment(t, blk, s, e, "pears", "About the pears", "Ada", "2026-10-14T10:00")[0]
    update_file(f, swap)
    (new,) = rdc.parse(f.read_text()).comments
    assert new.id == old.id
    p.wait_for_selector("#rd-popover .rd-msg:has-text('About the pears')")
    p.route("**/_/comment", lambda route: sent.append(route))
    p.focus("#rd-popover textarea")
    p.keyboard.press("Control+Enter")
    toasted(p, "cannot be sent")
    p.wait_for_timeout(200)
    assert sent == [] and "words for the first thread" not in f.read_text()
    p.unroute("**/_/comment")


# ── an older reply has no birth to agree with ─────────────────────

def test_a_reply_kept_with_no_birth_by_an_earlier_build_comes_back_in_its_threads_form(thread):
    (c,) = rdc.parse(thread.site.file.read_text()).comments
    keep_on_disk(thread, {"thread": c.id, "kind": "reply", "body": "an older entry's reply", "at": "2026-10-20T10:00:00Z"})
    p = thread.page
    p.reload()
    p.wait_for_selector("#rd-menu-btn", state="attached")
    p.click(".rd-badge")
    p.wait_for_selector("#rd-popover textarea")
    assert p.input_value("#rd-popover textarea") == "an older entry's reply"


def test_text_typed_again_into_a_form_that_a_failed_send_brought_back_and_was_emptied_comes_back_after_the_tab_is_closed(thread):
    p = thread.page
    fail_a_reply(thread, "sent words")
    p.fill("#rd-popover textarea", "")
    p.fill("#rd-popover textarea", "words typed again")
    p.reload()
    p.wait_for_selector("#rd-menu-btn", state="attached")
    p.click(".rd-badge")
    p.wait_for_selector("#rd-popover textarea")
    assert kept_text(thread) == "words typed again"


def test_text_typed_into_a_form_drawn_from_a_reply_kept_with_no_request_id_is_kept_as_typed(thread):
    (c,) = rdc.parse(thread.site.file.read_text()).comments
    keep_on_disk(thread, {"thread": c.id, "kind": "reply", "body": "an older entry's reply", "at": "2026-10-20T10:00:00Z"})
    p = thread.page
    p.reload()
    p.wait_for_selector("#rd-menu-btn", state="attached")
    p.click(".rd-badge")
    p.wait_for_selector("#rd-popover textarea")
    p.fill("#rd-popover textarea", "an older entry's reply, and more")
    p.reload()
    p.wait_for_selector("#rd-menu-btn", state="attached")
    p.click(".rd-badge")
    p.wait_for_selector("#rd-popover textarea")
    assert kept_text(thread) == "an older entry's reply, and more"


def stored_bodies(tab):
    raw = comment_store(tab)
    return sorted(d["body"] for d in json.loads(raw)) if raw else []


# A write of a send replaces only the entry of another send of the same thread and kind that another page has out.
@pytest.mark.parametrize("form", ["reply", "edit"])
def test_two_sends_of_one_thread_and_kind_out_on_two_pages_each_keep_their_text(thread, context, form):
    a, b = thread.page, second_page(thread, context)
    b.click(".rd-badge")
    held_b = send_held(SimpleNamespace(page=b, site=thread.site), form, "words from page B")
    held_a = send_held(thread, form, "words from page A")
    assert stored_bodies(thread) == ["words from page A", "words from page B"], "a write replaced the other send's entry"
    fail_the_send(b, held_b)
    held_a[0].fulfill(status=500, json={"ok": False, "error": "the hub broke off"})
    a.unroute("**/_/comment")
    assert unsent_line(a, timeout=3000) == f"2 {dict(reply='replies', edit='edits')[form]} not sent · Show"
    come_back(thread)
    unsent_line(a)
    assert sorted(t for _, _, t, _ in unsent_list(a)) == ["words from page A", "words from page B"]


# The text of a send that is out on another page is that page's: drawn here it would be sent twice.
def test_a_page_that_opens_a_thread_while_a_send_of_it_is_out_on_another_page_does_not_draw_its_text(thread, context):
    a = thread.page
    held = send_held(thread, "reply", "words still on their way")
    b = second_page(thread, context)
    assert b.locator(UNSENT).count() == 0, "a send that is out is said as not sent"
    b.click(".rd-badge")
    b.wait_for_selector("#rd-popover button[data-a=reply]")
    b.wait_for_timeout(500)
    assert b.locator("#rd-popover textarea").count() == 0, "the text of a send that is out was put into a form"
    held[0].fulfill(status=500, json={"ok": False, "error": "the hub broke off"})
    a.unroute("**/_/comment")
    assert unsent_line(b, timeout=3000) == "1 reply not sent · Show"
    assert [t for _, _, t, _ in unsent_list(b)] == ["words still on their way"]
    b.click(f"{UNSENT_LIST} button[data-f=open]")
    b.wait_for_selector(THREAD_OPEN)
    assert b.input_value("#rd-popover textarea") == "words still on their way"


# Discard names the entry it lists. An entry another send wrote since is not that one: it stays, unseen text is
# not discarded, and the list shows it.
def test_discard_in_the_unsent_list_leaves_an_entry_another_send_wrote_since_and_lists_it(thread):
    failed_send(thread, "reply", "first words")
    p = thread.page
    come_back(thread)
    unsent_line(p)
    p.click(UNSENT)
    p.wait_for_selector(UNSENT_LIST)
    (c,) = rdc.parse(thread.site.file.read_text()).comments
    keep_on_disk(thread, {"thread": c.id, "born": c.at, "about": c.quote, "kind": "reply", "body": "second words",
                          "rid": "b" * 24, "at": "2026-10-24T10:00:00.000Z"})
    p.click(f"{UNSENT_LIST} button[data-f=no]")
    until(lambda: p.evaluate("() => Array.from(document.querySelectorAll('#rd-popover[data-unsent] textarea')).map(t => t.value)")
          == ["second words"], what="the list to show the entry written since")
    assert stored_bodies(thread) == ["second words"]


def test_discard_in_the_unsent_list_takes_the_text_typed_into_a_returned_form_since(thread, context):
    failed_send(thread, "reply", "first words")
    a = thread.page
    b = second_page(thread, context)
    a.fill("#rd-popover textarea", "first words, and more")
    until(lambda: stored_bodies(thread) == ["first words, and more"], what="the typed text in the store")
    b.wait_for_selector(UNSENT)
    b.click(UNSENT)
    b.wait_for_selector(UNSENT_LIST)
    b.click(f"{UNSENT_LIST} button[data-f=no]")
    until(lambda: stored_bodies(thread) == [], what="the entry to go")


# A form never sent writes nothing, so its Cancel clears nothing of another send's.
@pytest.mark.parametrize("form", ["reply", "edit"])
def test_cancel_of_a_form_that_was_never_sent_leaves_the_kept_text_of_a_send_out_on_another_page(thread, context, form):
    a, b = thread.page, second_page(thread, context)
    a.click(f"#rd-popover button[data-a={form}]")
    a.fill("#rd-popover textarea", "typed, never sent")
    b.click(".rd-badge")
    held = send_held(SimpleNamespace(page=b, site=thread.site), form, "words from page B")
    a.click("#rd-popover button[data-f=no]")
    b.wait_for_timeout(500)
    assert stored_bodies(thread) == ["words from page B"]
    held[0].fulfill(status=500, json={"ok": False, "error": "the hub broke off"})
    b.unroute("**/_/comment")
    assert unsent_line(a, timeout=3000) == f"1 {form} not sent · Show"


# An entry with no request id (an older entry's) goes with any clear (SPEC 10.8): here the Cancel of the form it fills.
def test_cancel_clears_an_entry_that_has_no_request_id(thread):
    (c,) = rdc.parse(thread.site.file.read_text()).comments
    keep_on_disk(thread, {"thread": c.id, "kind": "reply", "body": "an older entry's reply", "at": "2026-10-20T10:00:00Z"})
    p = thread.page
    p.reload()
    p.wait_for_selector("#rd-menu-btn", state="attached")
    p.click(".rd-badge")
    p.wait_for_selector("#rd-popover textarea")
    p.click("#rd-popover button[data-f=no]")
    until(lambda: stored_bodies(thread) == [], what="the entry to go")


# Open the thread on a listed entry draws that entry's text, also when the thread holds another of its kind.
def test_open_the_thread_on_the_second_of_two_kept_replies_draws_that_reply(thread, context):
    a, b = thread.page, second_page(thread, context)
    b.click(".rd-badge")
    held_b = send_held(SimpleNamespace(page=b, site=thread.site), "reply", "words from page B")
    held_a = send_held(thread, "reply", "words from page A")
    fail_the_send(b, held_b)
    held_a[0].fulfill(status=500, json={"ok": False, "error": "the hub broke off"})
    a.unroute("**/_/comment")
    come_back(thread)
    unsent_line(a)
    texts = [t for _, _, t, _ in unsent_list(a)]
    assert sorted(texts) == ["words from page A", "words from page B"]
    for n, text in enumerate(texts):
        if n:
            come_back(thread)
            unsent_list(a)
        a.locator(f"{UNSENT_LIST} button[data-f=open]").nth(n).click()
        a.wait_for_selector(THREAD_OPEN)
        assert a.input_value("#rd-popover textarea") == text


# ---- the kept popover, the thread that opens by itself, the kept comment's match ----

PINNED = "#rd-popover[data-kept]"


def kept_entry(quote, body, block, head, occ=0, rid="k1", **more):
    return {"quote": quote, "body": body, "block": block, "head": head, "occ": occ, "rid": rid,
            "at": "2026-10-24T10:00:00.000Z", **more}


# A press outside the thread closes it and the kept popover is drawn again at once, pinned at the top right;
# a drag that starts with that press and ends over the pinned spot let go of the mouse on the popover, which the
# page does not read as a selection of the document. The kept popover waits for the mouse to be let go.
def test_a_drag_that_starts_outside_a_thread_and_ends_over_the_place_of_the_kept_comment_gets_the_comment_button(kept):
    p = kept.page
    open_comment_form(kept, P1, "apples")
    p.fill("#rd-popover textarea", "about the apples")
    p.keyboard.press("Control+Enter")
    until(lambda: "about the apples" not in comment_store(kept), what="the new comment to be taken")
    p.wait_for_selector("#rd-popover .rd-msg")           # its thread is open over the kept comment
    spot = p.evaluate("(() => { const r = document.createElement('div'); r.style.cssText = 'position:fixed;top:80px;right:390px;width:200px;height:60px';"
                      " document.body.appendChild(r); const b = r.getBoundingClientRect(); r.remove(); return [b.x + b.width / 2, b.y + b.height / 2]; })()")
    start = p.locator(P2).bounding_box()
    p.mouse.move(start["x"] + 4, start["y"] + start["height"] / 2)
    p.mouse.down()
    p.mouse.move(spot[0], spot[1], steps=8)
    p.mouse.up()
    p.wait_for_selector("#rd-comment-btn", timeout=3000)
    p.wait_for_selector(PINNED)


# Opening the thread of a failed send took the keyboard from a kept comment being typed in, closed it, and
# took the Comment button of a selection away. It opens only when nothing is being written or selected.
def reply_out_and_popover_left(tab, text):
    p, held = tab.page, []
    open_reply(tab, text)
    p.route("**/_/comment", lambda route: held.append(route))
    p.keyboard.press("Control+Enter")
    until(lambda: held or p.wait_for_timeout(20), what="the reply to go out")
    p.keyboard.press("Escape")
    until(lambda: p.locator("#rd-popover").count() == 0, what="Escape to close the popover")
    return held


def fail_held(p, held):
    held[0].fulfill(status=500, json={"ok": False, "error": "the hub broke"})
    p.unroute("**/_/comment")


def test_a_failed_reply_leaves_a_kept_comment_being_typed_in_open_and_says_where_the_reply_is_kept(thread):
    p = thread.page
    (c,) = rdc.parse(thread.site.file.read_text()).comments
    keep_on_disk(thread, kept_entry("pears", "about the pears", 3, "Second parag"))
    p.reload()
    p.wait_for_selector(PINNED)
    held = []
    p.route("**/_/comment", lambda route: held.append(route))
    p.locator(".rd-badge").dispatch_event("click")       # the kept comment sits over the badge
    p.wait_for_selector("#rd-popover button[data-a=reply]")
    open_reply(thread, "my reply")
    p.keyboard.press("Control+Enter")
    until(lambda: held or p.wait_for_timeout(20), what="the reply to go out")
    p.keyboard.press("Escape")
    p.wait_for_selector(PINNED)
    p.click(PINNED + " textarea")
    p.keyboard.type(" and more")
    fail_held(p, held)
    toasted(p, "Your text is kept in the thread it was for")
    p.wait_for_timeout(300)
    assert p.locator(PINNED).count() == 1, "the failed reply closed the kept comment"
    assert p.input_value(PINNED + " textarea") == "about the pears and more"
    assert p.evaluate("document.activeElement.tagName") == "TEXTAREA" and p.evaluate("!!document.activeElement.closest('[data-kept]')")
    assert "my reply" in comment_store(thread)


def test_a_failed_reply_does_not_take_the_comment_button_of_a_selection_away(thread):
    p = thread.page
    held = reply_out_and_popover_left(thread, "my reply")
    select(p, at(P2, "pears"), at(P2, "pears", None))
    p.wait_for_selector("#rd-comment-btn")
    fail_held(p, held)
    toasted(p, "Your text is kept in the thread it was for")
    p.wait_for_timeout(300)
    assert p.locator("#rd-comment-btn").count() == 1, "the failed reply took the Comment button away"
    assert p.locator("#rd-popover").count() == 0, "the failed reply opened its thread over the selection"
    p.click(".rd-badge")                       # the thread still has the reply, in its form
    p.wait_for_selector("#rd-popover textarea")
    assert p.input_value("#rd-popover textarea") == "my reply"


# A kept comment is told by the words its paragraph opens with; when the paragraph changed inside them and another
# paragraph now opens with them, neither the head nor the quote found it, and it waited for Discard. A second key,
# the words the paragraph ends with, finds it.
def test_a_kept_comment_whose_paragraph_changed_in_its_opening_words_is_found_though_another_paragraph_opens_like_it(tab):
    tab.open()
    refuse_a_comment_on_pears(tab, old="Second paragraph, about pears.", new="Secund paragraph, about pears.",
                              more="\nSecond paragraph that is another one.\n")
    p = tab.page
    open_comment_form(tab, P2, "pears")
    assert p.input_value("#rd-popover textarea") == "about the pears"
    assert "Your kept comment" not in p.inner_text("#rd-popover")


def test_a_kept_comment_goes_to_the_paragraph_that_ends_with_its_words_not_to_one_that_took_over_its_opening_words(tab):
    f = tab.site.file
    f.write_text(f.read_text().replace("First paragraph, about apples.", "Second paragraph, about apples.")
                 .replace("Second paragraph, about pears.", "Secund paragraph, about pears."), encoding="utf-8")
    tab.open()
    keep_on_disk(tab, kept_entry("pears", "about the pears", 3, "Secondparagr", tail=",aboutpears."))
    p = tab.page
    p.reload()
    p.wait_for_selector(PINNED)
    open_comment_form(tab, P1, "apples")
    assert p.input_value("#rd-popover textarea") == "", "the paragraph that took over the opening words got the comment"
    p.click("#rd-popover button[data-f=no]")
    open_comment_form(tab, P2, "pears")
    assert p.input_value("#rd-popover textarea") == "about the pears"


# Two kept comments with one quote, in two paragraphs: the input handler of the kept popover cleared by quote, so
# editing one replaced the other.
def test_two_kept_comments_with_one_quote_in_two_paragraphs_do_not_replace_each_other_when_one_is_edited(tab):
    tab.open()
    keep_on_disk(tab, kept_entry("pears", "first, about the pears", 2, "Second parag", rid="k1"),
                 kept_entry("pears", "second, about other pears", 5, "Another para", rid="k2", at="2026-10-24T10:00:01.000Z"))
    p = tab.page
    p.reload()
    p.wait_for_selector(PINNED)
    areas = p.locator(PINNED + " textarea")
    assert areas.count() == 2
    areas.nth(0).click()
    p.keyboard.press(key("End"))
    p.keyboard.type(" and more")
    until(lambda: "and more" in comment_store(tab), what="the edit to reach the store")
    stored = json.loads(comment_store(tab))
    assert sorted(d["body"] for d in stored) == ["first, about the pears and more", "second, about other pears"]
    assert [d.get("rid") for d in sorted(stored, key=lambda d: d["body"])] == [None, "k2"], "an edited text keeps the id of the send it no longer is"
    areas.nth(1).locator("xpath=..").locator("[data-f=no]").click()
    stored = json.loads(comment_store(tab))
    assert [d["body"] for d in stored] == ["first, about the pears and more"], "Discard cleared by quote"


# The 409 of a new comment, with a form open that is not out: the form of a reply to a deleted thread, drawn in
# the new comment's popover after the reply's refusal. The reload waits for it.
def test_a_new_comment_refused_while_a_failed_reply_form_is_open_in_its_popover_keeps_the_reload_waiting(thread):
    p, f = thread.page, thread.site.file
    held = gone_and_sent(thread, "words for a gone thread")
    open_comment_form(thread, P2, "pears")
    p.fill("#rd-popover textarea", "about the pears")
    f.write_text(f.read_text().replace("about pears", "about ripe pears"), encoding="utf-8")
    p.wait_for_timeout(500)
    mark(p)
    p.keyboard.press("Control+Enter")
    until(lambda: len(held) == 2 or p.wait_for_timeout(20), what="the new comment to go out")
    held[0].continue_()
    toasted(p, "no comment")
    held[1].continue_()
    p.unroute("**/_/comment")
    until(lambda: p.locator("#rd-popover .rd-form[data-for]").count() == 1, what="the failed reply's form")
    p.wait_for_timeout(1000)
    assert p.evaluate("window.__same_load") is True, "the refusal reloaded the page under the open form"
    assert p.input_value("#rd-popover textarea") == "words for a gone thread"
    p.click("#rd-popover button[data-f=no]")
    reloaded(p)
    p.wait_for_selector(KEPT)
    assert p.input_value("#rd-popover textarea") == "about the pears"
