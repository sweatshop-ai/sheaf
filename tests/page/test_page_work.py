"""Work on this (SPEC 10.2, 10.6): on a member's page of a sheaf, the ☰ menu offers the ways to work on the
session behind it (attach on the box, fork to your machine) and lists its sessions; and Ask and Tell reach
James's window on the box when the live session is there, or are off when it runs on someone's laptop.
The page is served by the loopback port with a member's meta block that holds `work` (and `can`) as the
hub's proxy socket writes it: what the script does with it is the same whichever listener served it."""
import json
import re

import pytest

from helpers import BEA
from pagehelp import toast, until
from sheafmd.hub import proxy

pytestmark = pytest.mark.page

META = re.compile(r'(<script id="rd-edit-meta" type="application/json">)(.*?)(</script>)', re.S)
ORIGIN = "https://tt.tiroir.me"
FORK = f"tiroir work {ORIGIN}/list/acme/site/plan.md"
ATTACH = "ssh tiroir-tt -t tmux -S /run/james/tmux.sock attach -t james \\; select-window -t acme-site"
BOX = {"id": "6f1c0e9a-2b3d-4c5e-8f70-1a2b3c4d5e6f", "host": "tiroir-tt", "member": "james",
       "date": "2026-10-28T05:12:03Z"}
LAPTOP = {"id": "0b9d1e7c-4a2f-4e8b-9c3d-5f6a7b8c9d0e", "host": "thierry-laptop", "member": "thierry",
          "date": "2026-10-28T09:40:00Z"}
SENT = "Sent to James's window; his answer appears in this thread."


def as_member(tab, work=None, can=()):
    """The tab's page as Bea, a member of the proxy socket, gets it: her meta block, with `work` and `can`
    as given, in the first render and in the /_/doc answers (which, on the proxy socket, name no agent)."""
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
        route.fulfill(response=r, json={**r.json(), "target": None, "capabilities": [],
                                        "lines": proxy.member_lines()})

    tab.page.route(site.url, page)
    tab.page.route(re.compile(r"/_/doc\?"), doc)


def work(sessions=(BOX,), attach=ATTACH, live="box"):
    w = {"fork": FORK, "sessions": list(sessions), "live": live}
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


def test_a_sheaf_with_no_session_says_so(tab):
    as_member(tab, work(sessions=(), attach=None, live=""))
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
