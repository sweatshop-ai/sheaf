"""The Team verso on a client page (SPEC 9.11): the page told a `team` list shows two tabs, "Client (n)" and "Team (n)", with the line "Only
the agency sees this", and asks the member to choose between two send buttons, neither the one Enter sends. A Team comment puts no anchor in
the text and sends no place in it. A page told no `team` is what it was. CI only: it needs a browser, never run on the laptop."""
import json

import pytest
from pagehelp import DOC, P2, at, open_box, select, until

pytestmark = pytest.mark.page

TEAM_COMMENT = {"id": "t1", "by": "Ada", "at": "2026-11-17T10:00", "status": "open", "quote": "Second paragraph", "body": "for the team",
                "replies": []}


def told_team(page, team):
    """The page for DOC with a `team` list in its meta (what the agency's hub adds to a client page), and the writes it makes to /_/comment
    answered here: the list of bodies sent, in order."""
    sent = []

    def serve(route):
        got = route.fetch()
        route.fulfill(response=got, body=got.text().replace(f'"doc": "{DOC}"', f'"doc": "{DOC}", "team": {json.dumps(team)}'))

    def write(route):
        sent.append(json.loads(route.request.post_data))
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "team": [TEAM_COMMENT]}))
    page.route(f"**/{DOC}", serve)
    page.route("**/_/comment", write)
    return sent


def form(tab):
    select(tab.page, at(P2, "pears"), at(P2, "pears", None))
    open_box(tab.page)
    return tab.page.locator("#rd-popover .rd-form")


def test_a_client_page_asks_for_a_choice_between_two_send_buttons(tab, site):
    told_team(tab.page, [])
    tab.open()
    f = form(tab)
    assert f.locator("button[data-f=client]").inner_text().startswith("Comment to client")
    assert f.locator("button[data-f=team]").inner_text().startswith("Comment to team")
    assert f.locator("button.rd-send").count() == 0


def test_enter_in_the_field_sends_neither(tab, site):
    sent = told_team(tab.page, [])
    tab.open()
    form(tab)
    tab.page.fill("#rd-popover textarea", "words")
    tab.page.press("#rd-popover textarea", "Enter")
    tab.page.wait_for_timeout(400)
    assert sent == []


def test_a_team_comment_is_sent_by_its_quote_with_no_place_in_the_text_and_adds_no_anchor(tab, site):
    sent = told_team(tab.page, [])
    tab.open()
    f = form(tab)
    tab.page.fill("#rd-popover textarea", "for the team")
    f.locator("button[data-f=team]").click()
    until(lambda: sent, what="the write")
    assert sent[0]["side"] == "team" and sent[0]["body"] == "for the team" and sent[0]["quote"]
    assert not {"block", "start", "end"} & set(sent[0])
    assert tab.page.locator(".rd-badge").count() == 0
    until(lambda: "Team (1)" in tab.page.locator("#rd-panel").inner_text(), what="the Team tab")
    assert "Only the agency sees this" in tab.page.locator("#rd-panel").inner_text()


def test_a_client_comment_names_its_side_and_its_place(tab, site):
    sent = told_team(tab.page, [])
    tab.open()
    f = form(tab)
    tab.page.fill("#rd-popover textarea", "for the client")
    f.locator("button[data-f=client]").click()
    until(lambda: sent, what="the write")
    assert sent[0]["side"] == "client" and {"block", "start", "end"} <= set(sent[0])


def test_a_page_told_no_team_is_what_it_was(tab, site):
    tab.open()
    f = form(tab)
    assert f.locator("button[data-f=team]").count() == 0 and f.locator("button[data-f=ok]").count() == 1
