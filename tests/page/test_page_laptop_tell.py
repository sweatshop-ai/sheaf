"""A Tell that waits for a laptop session (SPEC 9.8, 10.5): the page says "Waiting for <session>", stays until the
member cancels it or retargets it to one of their own agents, and says queued and seen in their own words.
The hub's rows are what the page is told (`telling` with `laptop: true`), served here through the page's own reads."""
import json
import re

import pytest

from pagehelp import until
from sheafmd import comments as rdc
from sheafmd.source import update_file

pytestmark = pytest.mark.page

META = re.compile(r'(<script id="rd-edit-meta" type="application/json">)(.*?)(</script>)', re.S)
SESSION = "Claude Code (Ada) · 6f1c2f0e"
OWN = {"target": "agent:ada-chatgpt", "label": "ChatGPT (Ada)"}


def waiting_on_a_laptop(tab, site, state="waiting"):
    """A comment c1; the hub says its Tell waits for a laptop session in `state`, and names one agent of the member."""
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "apples"), "apples", "Why?",
                                                     "Ada", "2026-10-14T10:00")[0])
    row = [{"id": "c1", "to": SESSION, "state": state, "laptop": True}]
    sent = []

    def page(route):
        html = route.fetch().text()
        m = META.search(html)
        meta = json.loads(m.group(2))
        meta["targets"], meta["telling"] = [OWN], row
        route.fulfill(status=200, content_type="text/html; charset=utf-8",
                      body=html[:m.start(2)] + json.dumps(meta).replace("<", "\\u003c") + html[m.end(2):])

    def doc(route):
        r = route.fetch()
        route.fulfill(response=r, json={**r.json(), "targets": [OWN], "telling": row})

    def retarget(route):
        sent.append(json.loads(route.request.post_data))
        route.fulfill(status=200, content_type="application/json", body='{"ok": true}')

    tab.page.route(tab.site.url, page)
    tab.page.route(re.compile(r"/_/doc\?"), doc)
    tab.page.route("**/_/retarget", retarget)
    tab.open()
    tab.page.click(".rd-badge")
    tab.page.wait_for_selector("#rd-popover")
    return sent


def lines(tab):
    return tab.page.locator("#rd-popover .rd-waits").all_inner_texts()


def test_a_tell_for_a_session_that_is_not_listening_says_waiting_for_it_and_offers_cancel_and_retarget(tab, site):
    waiting_on_a_laptop(tab, site)
    until(lambda: bool(lines(tab)), what="the waiting line")
    assert lines(tab)[0].startswith(f"Waiting for {SESSION}: it is not listening now.")
    assert tab.page.locator("#rd-popover [data-a=cancel-tell]").count() == 1
    assert tab.page.locator("#rd-popover [data-a=retarget]").get_attribute("data-target") == OWN["target"]
    assert not tab.page.query_selector(".rd-badge.rd-working")       # it runs nothing: no spinner, no orange dot


def test_retarget_posts_the_threads_id_and_the_agent_picked(tab, site):
    sent = waiting_on_a_laptop(tab, site)
    until(lambda: tab.page.locator("#rd-popover [data-a=retarget]").count() == 1, what="the Retarget button")
    tab.page.click("#rd-popover [data-a=retarget]")
    until(lambda: bool(sent), what="the retarget request")
    assert [{k: v for k, v in body.items() if k != "doc"} for body in sent] == [{"id": "c1", "target": OWN["target"]}]


def test_a_tell_a_session_listens_for_says_queued_and_one_it_took_says_seen_with_cancel_only(tab, site):
    waiting_on_a_laptop(tab, site, "queued")
    until(lambda: bool(lines(tab)), what="the queued line")
    assert lines(tab)[0].startswith(f"Queued for {SESSION}")
    assert tab.page.locator("#rd-popover [data-a=retarget]").count() == 1


def test_a_tell_the_session_took_offers_cancel_and_no_retarget(tab, site):
    waiting_on_a_laptop(tab, site, "seen")
    until(lambda: bool(lines(tab)), what="the seen line")
    assert lines(tab) == [f"{SESSION} has seen it; its action appears in this thread."]
    assert tab.page.locator("#rd-popover [data-a=cancel-tell]").count() == 1
    assert tab.page.locator("#rd-popover [data-a=retarget]").count() == 0


INSTALL = "claude plugin marketplace add sweatshop-ai/sheaf && claude plugin install sheaf@sheaf --scope user"


def test_a_waiting_tell_says_what_the_plugin_does_and_how_to_install_it(tab, site):
    waiting_on_a_laptop(tab, site)
    until(lambda: bool(lines(tab)), what="the waiting line")
    hint = tab.page.locator("#rd-popover .rd-waits .rd-install-hint")
    assert hint.count() == 1
    assert "receive what you send from a Sheaf page" in hint.inner_text()
    assert hint.locator("code").inner_text() == INSTALL
    link = hint.locator("a")
    assert link.get_attribute("href") == "https://github.com/sweatshop-ai/sheaf#agents"
    assert "noopener" in link.get_attribute("rel").split()


@pytest.mark.parametrize("state", ["queued", "seen"])
def test_a_tell_that_is_not_waiting_shows_no_install_line(tab, site, state):
    waiting_on_a_laptop(tab, site, state)
    until(lambda: bool(lines(tab)), what="the line")
    assert tab.page.locator("#rd-popover .rd-install-hint").count() == 0
