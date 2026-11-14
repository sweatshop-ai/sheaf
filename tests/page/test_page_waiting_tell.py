"""A Tell to an agent waits on the document, and the page says so (SPEC 9.8, 10.5): "Waiting for <agent>…",
then "<agent> has seen it…", with Cancel, across a reload and no orange dot."""
import time

import pytest
from playwright.sync_api import Error as PlaywrightError

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
    """The waiting lines of the open thread. The page reloads after every comment write (an agent's reply too), and
    a read that meets the reload dies with 'Execution context was destroyed': it waits for the new load and reads again."""
    for _ in range(3):
        try:
            return tab.page.locator("#rd-popover .rd-waits").all_inner_texts()
        except PlaywrightError as e:
            if "Execution context was destroyed" not in str(e):
                raise
            tab.page.wait_for_load_state("domcontentloaded")
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
    assert site.hub.waiting_tells.waits(DOC) == []       # a page that reloads has no line yet: the hub says whether the wait ended


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
    tab.page.clock.install()                 # Playwright's clock: it runs on, and the two 5 s timers are driven by run_for, in a fixed order
    token = ask_agent(tab, site)
    name = f"ChatGPT ({site.hub.person})"
    first = time.monotonic()
    trace = []

    def mark(step):
        """What the page shows at a step: the thread's lines, whether its Cancel button is there, the toast."""
        trace.append((round(time.monotonic() - first, 2), step, line(tab),
                      tab.page.locator("#rd-popover button[data-a=cancel-tell]").count(), toast(tab.page)))

    emit = site.hub.waiting_tells._emit
    held = []

    def watch(*a, **k):
        trace.append((round(time.monotonic() - first, 2), "hub emits", a[1:3], a[3:] and str(a[3:])[:80], None))
        if holding and a[1] == "tell-cancelled":
            held.append((a, k))
        else:
            emit(*a, **k)
    holding = False
    site.hub.waiting_tells._emit = watch
    tab.page.fill("#rd-popover textarea", "Please do.")
    tab.page.click("#rd-popover .rd-form button.rd-tell")
    until(lambda: bool(line(tab)), what="the waiting line")
    mark("first line")
    tab.page.hover("#rd-popover button[data-a=cancel-tell]")
    tab.page.click("#rd-popover button[data-a=cancel-tell]")                  # a Tell nobody had seen: its timer starts
    until(lambda: line(tab) == [], what="the first line to go")
    mark("after the first Cancel")
    tab.page.clock.run_for(1500)                                              # the second Cancel's own timer then ends 1.5 s after the first's
    tab.page.fill("#rd-popover textarea", "Please do, again.")
    tab.page.click("#rd-popover .rd-form button.rd-tell")
    until(lambda: bool(line(tab)), what="the second waiting line")
    mark("second line")
    call(browser_on(site.hub), "documents", token=token)
    until(lambda: line(tab) == [f"{name} has seen it; its action appears in this thread."], what="the seen line")
    mark("seen line")
    holding = True
    tab.page.hover("#rd-popover button[data-a=cancel-tell]")
    tab.page.click("#rd-popover button[data-a=cancel-tell]")                  # the answer comes, the event is held
    until(lambda: line(tab) == [] and len(held) == 1, what="the second answer")
    mark("after the second Cancel, event held")
    tab.page.clock.run_for(3600)             # the first timer (5 s after its Cancel) fires; the second (5 s after the second Cancel) does not
    mark("after the first timer")
    holding = False
    for a, k in held:
        emit(*a, **k)
    site.hub.waiting_tells._emit = emit
    try:
        toasted(tab.page, f"{name} had already seen it; look at the document before you Tell again.")
    except AssertionError as e:
        mark("failure")
        raise AssertionError(f"{e}\n" + "\n".join(map(repr, trace))) from None


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


SAW = "had already seen it; look at the document before you Tell again."


def hold_cancels(site):
    """Hold the hub's `tell-cancelled` events, to let the page's Cancel answers come first. Returns (held, release)."""
    emit = site.hub.waiting_tells._emit
    held, state = [], {"on": True}

    def watch(*a, **k):
        if state["on"] and a[1] == "tell-cancelled":
            held.append((a, k))
        else:
            emit(*a, **k)

    def release():
        state["on"] = False
        site.hub.waiting_tells._emit = emit
        for a, k in held:
            emit(*a, **k)
    site.hub.waiting_tells._emit = watch
    return held, release


def two_threads_seen(tab, site):
    """A Tell on each of two threads, to two agents (the target changes between them), both seen. Returns their names."""
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "pears"), "pears", "And?",
                                                     "Ada", "2026-10-14T10:01")[0])
    tokens = [ask_agent(tab, site)]                      # thread 0, to ChatGPT
    tab.page.fill("#rd-popover textarea", "Please do.")
    tab.page.click("#rd-popover .rd-form button.rd-tell")
    until(lambda: bool(line(tab)), what="the waiting line of thread 0")
    tokens.append(Tokens().add("bea-claude", client="Claude"))
    site.hub.docs.change(DOC, lambda e: {**e, "target": {"kind": "agent", "token": "bea-claude",
                                                        "id": next(r.id for r in Tokens().list() if r.name == "bea-claude")}})
    tab.open()
    tab.page.locator(".rd-badge").nth(1).click()         # thread 1, to Claude
    tab.page.wait_for_selector("#rd-popover textarea")
    tab.page.fill("#rd-popover textarea", "Please do.")
    tab.page.click("#rd-popover .rd-form button.rd-tell")
    until(lambda: bool(line(tab)), what="the waiting line of thread 1")
    for token in tokens:
        call(browser_on(site.hub), "documents", token=token)
    until(lambda: "has seen it" in " ".join(line(tab)), what="the seen line of thread 1")
    return [f"ChatGPT ({site.hub.person})", f"Claude ({site.hub.person})"]


def watch_toasts(tab):
    """Record every toast the page shows, with the time it came and whether it was on screen."""
    tab.page.evaluate("""() => { window.__toasts = [];
        const t = document.querySelector('#rd-toast');
        new MutationObserver(() => { if (t.textContent) window.__toasts.push(
            {text: t.textContent, at: performance.now(), shown: t.className.includes('show')}); })
            .observe(t, {childList: true, characterData: true, subtree: true}); }""")


def cancel_both(tab, site):
    """Cancel thread 1 (open), then thread 0, holding the hub's events until both Cancels have reached it."""
    held, release = hold_cancels(site)
    watch_toasts(tab)
    for k in (1, 0):                                     # the open thread first, then the other
        if k == 0:
            tab.page.keyboard.press("Escape")
            tab.page.locator(".rd-badge").nth(0).click()
            tab.page.wait_for_selector("#rd-popover button[data-a=cancel-tell]")
        tab.page.click("#rd-popover button[data-a=cancel-tell]")
        until(lambda: len(held) == (2 if k == 0 else 1), what=f"the Cancel of thread {k} to reach the hub")
    release()


def test_two_cancels_of_two_threads_in_a_row_say_one_toast_each(tab, site):
    # Ticket 42 (Codex round 4 of PR 257, P2): the summary was one object for the whole page, so the events of two
    # separate Cancels that came within 60 ms were one toast, "A and A had already seen it".
    # Ticket 62 (F2): two agents, one per thread, so each toast also shows that it names its own thread's agent only.
    chatgpt, claude = two_threads_seen(tab, site)
    cancel_both(tab, site)
    until(lambda: len([t for t in tab.page.evaluate("window.__toasts") if SAW in t["text"]]) == 2,
          timeout=12, what="a toast for each Cancel")
    said = [t["text"] for t in tab.page.evaluate("window.__toasts") if t["text"].startswith("Cancelled.")]
    assert sorted(said) == sorted([f"Cancelled. {chatgpt} {SAW}", f"Cancelled. {claude} {SAW}"])


def test_the_toast_of_the_first_cancel_stays_up_until_the_second_has_its_turn(tab, site):
    # Ticket 62 (F1): say() had one toast element, so the second thread's toast, about 60 ms after the first, hid it
    # and with it "had already seen it". Toasts queue: each is shown for its own time, none dropped or cut short.
    chatgpt, claude = two_threads_seen(tab, site)
    cancel_both(tab, site)
    until(lambda: len(tab.page.evaluate("window.__toasts")) >= 1, what="the first toast")
    first = tab.page.evaluate("window.__toasts")[0]["text"]
    assert SAW in first
    at = tab.page.evaluate("window.__toasts[0].at")
    until(lambda: tab.page.evaluate(f"performance.now() - {at}") >= 1200, what="1.2 s into the first toast")   # inside its 2.6 s
    assert toast(tab.page) == first, "the second toast took the place of the first before its time"
    until(lambda: len([t for t in tab.page.evaluate("window.__toasts") if SAW in t["text"]]) == 2,
          timeout=12, what="the second toast, after the first")
    seen = [t for t in tab.page.evaluate("window.__toasts") if SAW in t["text"]]
    assert {t["text"] for t in seen} == {f"Cancelled. {chatgpt} {SAW}", f"Cancelled. {claude} {SAW}"}
    assert seen[1]["at"] - seen[0]["at"] >= 2500, "the first toast was cut short"


def test_a_second_cancel_while_the_first_is_out_keeps_what_the_first_saw(tab, site):
    # Ticket 48 (Opus round 5 of PR 257, note 1): the second Cancel's answer found no place left (the first had
    # taken it off) and put {} over the first's, so the first's event no longer said "had already seen it".
    token = ask_agent(tab, site)
    name = f"ChatGPT ({site.hub.person})"
    tab.page.fill("#rd-popover textarea", "Please do.")
    tab.page.click("#rd-popover .rd-form button.rd-tell")
    until(lambda: bool(line(tab)), what="the waiting line")
    call(browser_on(site.hub), "documents", token=token)
    until(lambda: "has seen it" in " ".join(line(tab)), what="the seen line")
    held, release = hold_cancels(site)
    routes, finished = [], []
    tab.page.route("**/_/cancel", lambda route: routes.append(route))
    tab.page.on("requestfinished", lambda r: finished.append(r) if r.url.endswith("/_/cancel") else None)
    button = tab.page.locator("#rd-popover button[data-a=cancel-tell]")
    button.click()
    button.click()                                       # the first request is still out
    until(lambda: len(routes) == 2, what="both Cancels out")
    for r in routes:
        r.continue_()
    until(lambda: len(finished) == 2, what="both answers")  # Ticket 62 (F3): not the first alone
    until(lambda: line(tab) == [] and len(held) >= 1, what="the line off")
    tab.page.evaluate("0")                               # a turn of the page: both answers' `off()` have run
    release()
    toasted(tab.page, f"{name} {SAW}")
