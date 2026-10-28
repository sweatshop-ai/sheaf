"""Work on this (SPEC 10.2, 10.6): on a member's page of a sheaf, the ☰ menu offers the ways to work on the
session behind it (attach on the box, fork to your machine) and lists its sessions; and Ask and Tell reach
James's window on the box when the live session is there, or are off when it runs on someone's laptop.
The page is served by the loopback port with a member's meta block that holds `work` (and `can`) as the
hub's proxy socket writes it: what the script does with it is the same whichever listener served it."""
import json
import re

import pytest

from helpers import BEA
from pagehelp import P1, at, select, toast, until
from sheafmd import comments as rdc
from sheafmd.hub import proxy
from sheafmd.source import update_file

pytestmark = pytest.mark.page

META = re.compile(r'(<script id="rd-edit-meta" type="application/json">)(.*?)(</script>)', re.S)
ORIGIN = "https://tt.tiroir.me"
FORK = f"tiroir work {ORIGIN}/list/acme/site/plan.md"
ATTACH = "ssh tiroir-tt -t tmux -S /run/james/tmux.sock attach -t james \\; select-window -t =acme_site"
BOX = {"id": "6f1c0e9a-2b3d-4c5e-8f70-1a2b3c4d5e6f", "host": "tiroir-tt", "member": "james",
       "date": "2026-10-28T05:12:03Z"}
LAPTOP = {"id": "0b9d1e7c-4a2f-4e8b-9c3d-5f6a7b8c9d0e", "host": "thierry-laptop", "member": "thierry",
          "date": "2026-10-28T09:40:00Z"}
SENT = "Sent to James’s window; his answer appears in this thread."


def as_member(tab, work=None, can=(), doc_work=None, doc_can=None):
    """The tab's page as Bea, a member of the proxy socket, gets it: her meta block, with `work` and `can`
    as given, in the first render and in the /_/doc answers (which, on the proxy socket, name no agent and
    carry the same `work` and `can` as the meta, 9.12). `doc_work` and `doc_can` make the /_/doc answers
    say otherwise: a fork the hub has seen since the page was served."""
    site = tab.site
    bea = proxy.Member(BEA, "Bea", (str(site.file.parent),))
    real = site.hub.page
    site.hub.page = lambda e, nonce, member=None: real(e, nonce, member=bea)

    def page(route):
        html = route.fetch().text()
        m = META.search(html)
        meta = json.loads(m.group(2))
        meta["can"] = list(can)
        if work is not None:
            meta["work"] = work
        route.fulfill(status=200, content_type="text/html; charset=utf-8",
                      body=html[:m.start(2)] + json.dumps(meta).replace("<", "\\u003c") + html[m.end(2):])

    def doc(route):
        r = route.fetch()
        j = {**r.json(), "target": None, "capabilities": list(can if doc_can is None else doc_can),
             "lines": proxy.member_lines()}
        w = work if doc_work is None else doc_work
        if w is not None:
            j["work"] = w
        docs.append(j)
        route.fulfill(response=r, json=j)

    docs = []
    tab.docs = docs

    tab.page.route(site.url, page)
    tab.page.route(re.compile(r"/_/doc\?"), doc)


def work(sessions=(BOX,), attach=ATTACH, live="box", fork=FORK):
    w = {"sessions": list(sessions), "live": live}
    if fork is not None:
        w["fork"] = fork
    if attach is not None:
        w["attach"] = attach
    return w


def menu_items(page):
    page.click("#rd-menu-btn")
    return page.locator("#rd-menu button").all_inner_texts()


def open_work(page):
    page.click("#rd-menu-btn")
    page.click("#rd-work-btn")
    page.wait_for_selector("#rd-work", state="visible")


# ---- the menu entry -----------------------------------------------------------------------------------------

def test_a_page_without_work_has_no_work_on_this_entry(tab):
    as_member(tab)
    tab.open()
    assert not any("Work on this" in t for t in menu_items(tab.page))


def test_a_sheaf_has_work_on_this_in_the_document_group(tab):
    as_member(tab, work())
    tab.open()
    items = [t.split("\n")[0] for t in menu_items(tab.page)]
    assert "Work on this" in items
    groups = tab.page.locator("#rd-menu .rd-group").all_inner_texts()
    assert groups[0].lower() == "document"
    # In the Document group: after its first group heading and before the Comments one.
    order = tab.page.evaluate("""() => [...document.querySelectorAll('#rd-menu .rd-group, #rd-menu button')]
                                         .map(e => e.textContent)""")
    w = next(i for i, t in enumerate(order) if t.startswith("Work on this"))
    assert order.index(next(t for t in order if t.lower() == "comments")) > w > 0


# ---- the popover --------------------------------------------------------------------------------------------

def test_work_on_this_opens_the_two_ways_and_the_sessions(tab):
    older = [{**LAPTOP, "id": f"0b9d1e7c-4a2f-4e8b-9c3d-5f6a7b8c9d0{k}", "date": f"2026-10-2{k}T08:00:00Z"}
             for k in range(5)]
    as_member(tab, work(sessions=[BOX] + older[::-1]))
    tab.open()
    open_work(tab.page)
    w = tab.page.locator("#rd-work")
    heads = w.locator("h4").all_text_contents()
    assert heads == ["Attach on the box", "Fork to your machine", "Sessions"]
    assert w.locator(".rd-cmd code").all_inner_texts() == [ATTACH, FORK]
    assert w.locator(".rd-cmd button").all_inner_texts() == ["Copy", "Copy"]
    assert "Runs on your laptop: fetches the session through this hub, forks it under your name." in w.inner_text()
    # Newest first, as the front matter lists them, and five at most.
    assert w.locator(".rd-sess").all_inner_texts() == [
        "James on tiroir-tt · 2026-10-28 05:12 UTC",
        "Thierry on thierry-laptop · 2026-10-24 08:00 UTC",
        "Thierry on thierry-laptop · 2026-10-23 08:00 UTC",
        "Thierry on thierry-laptop · 2026-10-22 08:00 UTC",
        "Thierry on thierry-laptop · 2026-10-21 08:00 UTC"]
    assert not tab.page.locator("#rd-menu").is_visible()


def test_without_a_shell_there_is_no_attach_command(tab):
    as_member(tab, work(attach=None))
    tab.open()
    open_work(tab.page)
    assert tab.page.locator("#rd-work h4").all_text_contents() == ["Fork to your machine", "Sessions"]
    assert tab.page.locator("#rd-work .rd-cmd code").all_inner_texts() == [FORK]


def test_a_sheaf_with_no_session_on_the_box_offers_no_fork(tab):
    as_member(tab, work(sessions=[LAPTOP], attach=None, live="laptop", fork=None))
    tab.open()
    open_work(tab.page)
    assert tab.page.locator("#rd-work h4").all_text_contents() == ["Sessions"]
    assert tab.page.locator("#rd-work .rd-cmd").count() == 0
    assert "No session of this sheaf ran on the box: there is none to fork." in tab.page.inner_text("#rd-work")


def test_a_sheaf_with_no_session_says_so(tab):
    as_member(tab, work(sessions=(), attach=None, live="", fork=None))
    tab.open()
    open_work(tab.page)
    assert tab.page.locator("#rd-work .rd-sess").count() == 0
    assert "No session yet." in tab.page.inner_text("#rd-work")


def test_copy_puts_the_command_on_the_clipboard_and_says_copied(tab, context, site):
    context.grant_permissions(["clipboard-read", "clipboard-write"], origin=site.base)
    as_member(tab, work())
    tab.open()
    open_work(tab.page)
    tab.page.locator("#rd-work .rd-cmd button").nth(1).click()
    until(lambda: toast(tab.page) == "Copied", what="the Copied toast")
    assert tab.page.evaluate("navigator.clipboard.readText()") == FORK


def test_without_the_clipboard_api_copy_selects_the_command(tab):
    tab.page.add_init_script("Object.defineProperty(navigator, 'clipboard', {value: undefined});")
    as_member(tab, work())
    tab.open()
    open_work(tab.page)
    tab.page.locator("#rd-work .rd-cmd button").nth(0).click()
    until(lambda: tab.page.evaluate("getSelection().toString()") == ATTACH, what="the command selected")
    assert tab.page.locator("#rd-work").is_visible()
    tab.page.wait_for_timeout(500)        # past the 350 ms after which a selection would get its Comment button
    assert not tab.page.locator("#rd-comment-btn").is_visible()


def test_escape_closes_the_popover_and_nothing_else(tab):
    as_member(tab, work())
    tab.open()
    tab.page.keyboard.press("e")          # edit mode is the last thing Escape closes (10.2)
    open_work(tab.page)
    tab.page.keyboard.press("Escape")
    assert not tab.page.locator("#rd-work").is_visible()
    assert tab.page.evaluate("document.body.classList.contains('rd-editing')")


def test_a_click_outside_closes_the_popover(tab):
    as_member(tab, work())
    tab.open()
    open_work(tab.page)
    tab.page.click("main h1")
    assert not tab.page.locator("#rd-work").is_visible()


# ---- Ask and Tell on a box-hosted sheaf (10.6, 9.12) ---------------------------------------------------------

BOX_CAN = ("box-ask", "box-tell")
START, END = at(P1, "apples"), at(P1, "apples", None)


def agent_buttons(page, scope):
    """The Ask and Tell buttons of the form or the actions in `scope`: (label, enabled) each."""
    out = []
    for k in ("ask", "tell"):
        b = page.locator(f"{scope} button.rd-{k}").first
        out.append((b.inner_text(), b.is_enabled()))
    return out


def comment_form(tab):
    select(tab.page, START, END)
    tab.page.click("#rd-comment-btn")
    tab.page.wait_for_selector("#rd-popover .rd-form")


def sent_to_box(tab):
    """The bodies of the page's /_/comment requests, which go on to the hub without ask and tell (the loopback
    hub has no James); and the paths of any /_/ask or /_/tell request, which a box sheaf never sends."""
    bodies, others = [], []

    def comment(route):
        b = json.loads(route.request.post_data)
        bodies.append(b)
        route.continue_(post_data=json.dumps({**b, "ask": False, "tell": False}))

    tab.page.route(re.compile(r"/_/comment$"), comment)
    tab.page.route(re.compile(r"/_/(ask|tell)$"), lambda route: (others.append(route.request.url), route.abort()))
    return bodies, others


def test_on_a_box_sheaf_ask_and_tell_name_james_and_outlast_the_doc_answer(tab):
    as_member(tab, work(), can=BOX_CAN)
    tab.open()
    until(lambda: tab.docs, what="the page's /_/doc answer")
    comment_form(tab)
    assert agent_buttons(tab.page, "#rd-popover .rd-form") == [("Ask James", True), ("Tell James", True)]
    assert tab.page.locator("#rd-popover .rd-agent-line").count() == 0
    tab.page.click("#rd-menu-btn")
    assert tab.page.inner_text("#rd-agent") == "Ask and Tell → James’s window on the box"


@pytest.mark.parametrize("k", ["ask", "tell"])
def test_a_comment_sent_to_james_goes_with_the_comment_and_says_so_without_a_spinner(tab, k):
    as_member(tab, work(), can=BOX_CAN)
    tab.open()
    bodies, others = sent_to_box(tab)
    comment_form(tab)
    tab.page.fill("#rd-popover textarea", "What does James think?")
    tab.page.click(f"#rd-popover .rd-form button.rd-{k}")
    until(lambda: SENT in tab.page.inner_text("#rd-popover"), what="the sent line in the thread")
    assert [(b["op"], b["ask"], b["tell"]) for b in bodies] == [("add", k == "ask", k == "tell")]
    assert others == []
    assert tab.page.locator("#rd-popover .rd-pending, #rd-popover .rd-dots").count() == 0
    assert tab.page.locator("#rd-popover .rd-busy").count() == 0


def test_the_threads_own_ask_opens_the_reply_form_and_sends_through_the_comment(tab):
    update_file(tab.site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "apples"), "apples", "Why?",
                                                         "Ada", "2026-10-14T10:00")[0])
    as_member(tab, work(), can=BOX_CAN)
    tab.open()
    bodies, others = sent_to_box(tab)
    tab.page.click(".rd-badge")
    tab.page.click("#rd-popover .rd-actions button.rd-ask")
    tab.page.wait_for_selector("#rd-popover .rd-form textarea")
    tab.page.fill("#rd-popover .rd-form textarea", "And you, James?")
    tab.page.click("#rd-popover .rd-form button.rd-ask")
    until(lambda: SENT in tab.page.inner_text("#rd-popover"), what="the sent line in the thread")
    assert [(b["op"], b["ask"], b["tell"]) for b in bodies] == [("reply", True, False)]
    assert others == []


def test_a_sheaf_live_on_a_laptop_turns_ask_and_tell_off_with_its_line(tab):
    as_member(tab, work(sessions=[LAPTOP, BOX], live="laptop"))
    tab.open()
    comment_form(tab)
    line = "This session runs on Thierry’s machine: open it there."
    assert [e for _, e in agent_buttons(tab.page, "#rd-popover .rd-form")] == [False, False]
    assert tab.page.locator("#rd-popover .rd-agent-line").all_inner_texts() == [line]
    assert proxy.PROXY_LINE not in tab.page.inner_text("#rd-popover")


def test_a_fork_the_doc_answer_reports_turns_box_ask_and_tell_off(tab):
    as_member(tab, work(), can=BOX_CAN, doc_work=work(sessions=[LAPTOP, BOX], live="laptop"), doc_can=())
    tab.open()
    until(lambda: tab.docs, what="the page's /_/doc answer")
    comment_form(tab)
    assert [e for _, e in agent_buttons(tab.page, "#rd-popover .rd-form")] == [False, False]
    assert "Thierry’s machine" in tab.page.inner_text("#rd-popover .rd-agent-line")


def test_the_menu_button_closes_the_popover(tab):
    as_member(tab, work())
    tab.open()
    open_work(tab.page)
    tab.page.click("#rd-menu-btn")
    assert not tab.page.locator("#rd-work").is_visible() and tab.page.locator("#rd-menu").is_visible()


# ── review round 3 (Codex) ───────────────────────────────────────────────────
def test_a_sheaf_of_james_with_no_session_yet_names_james(tab):
    as_member(tab, work(sessions=[], live="", fork=None, attach=None), can=BOX_CAN)
    tab.open()
    comment_form(tab)
    assert agent_buttons(tab.page, "#rd-popover .rd-form") == [("Ask James", True), ("Tell James", True)]


def test_the_sent_line_outlasts_the_reload_a_recorded_session_brings(tab):
    # The hub records James's session after the drop: a front matter change, which reloads the page.
    as_member(tab, work(), can=BOX_CAN)
    tab.open()
    sent_to_box(tab)
    comment_form(tab)
    tab.page.fill("#rd-popover textarea", "What does James think?")
    tab.page.click("#rd-popover .rd-form button.rd-tell")
    until(lambda: SENT in tab.page.inner_text("#rd-popover"), what="the sent line in the thread")
    update_file(tab.site.file, lambda t: t + "\nOne more paragraph.\n")
    until(lambda: "One more paragraph." in tab.page.inner_text("body"), what="the reload")
    until(lambda: tab.page.locator("#rd-popover").is_visible() and SENT in tab.page.inner_text("#rd-popover"),
          what="the sent line after the reload")


def test_the_sent_line_keeps_the_name_it_was_sent_to_after_a_fork(tab):
    # Sent to James; a fork the /_/doc answer reports moves the live session to Thierry's laptop before James replies.
    as_member(tab, work(), can=BOX_CAN)
    tab.open()
    sent_to_box(tab)
    comment_form(tab)
    tab.page.fill("#rd-popover textarea", "What does James think?")
    tab.page.click("#rd-popover .rd-form button.rd-tell")
    until(lambda: SENT in tab.page.inner_text("#rd-popover"), what="the sent line in the thread")
    tab.page.unroute(re.compile(r"/_/doc\?"))

    def forked(route):
        r = route.fetch()
        route.fulfill(response=r, json={**r.json(), "target": None, "capabilities": [], "lines": proxy.member_lines(),
                                         "work": work(sessions=[LAPTOP, BOX], live="laptop")})

    tab.page.route(re.compile(r"/_/doc\?"), forked)
    update_file(tab.site.file, lambda t: t + "\nOne more paragraph.\n")
    until(lambda: "One more paragraph." in tab.page.inner_text("body"), what="the reload")
    until(lambda: tab.page.locator("#rd-popover").is_visible() and SENT in tab.page.inner_text("#rd-popover"),
          what="the sent line, still naming James")
