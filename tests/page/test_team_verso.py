"""The Team verso on a client page (SPEC 9.11): the page told a `team` list shows two tabs, "Client (n)" and "Team (n)", with the line "Only
the agency sees this", and asks the member to choose between two send buttons, neither the one Enter sends. A Team comment puts no anchor in
the text and sends no place in it. A page told no `team` is what it was. CI only: it needs a browser, never run on the laptop."""
import json

import pytest
from pagehelp import DOC, P2, at, open_box, select, toasted, until

pytestmark = pytest.mark.page

TEAM_COMMENT = {"id": "t1", "by": "Ada", "at": "2026-11-17T10:00", "status": "open", "quote": "Second paragraph", "body": "for the team",
                "replies": []}


def told_team(page, team, answer=None):
    """The page for DOC with a `team` list in its meta (what the agency's hub adds to a client page), and the writes it makes to /_/comment
    answered here: the list of bodies sent, in order."""
    sent = []

    def serve(route):
        got = route.fetch()
        body = got.text().replace(f'"doc": "{DOC}"', f'"doc": "{DOC}", "team": {json.dumps(team)}')
        route.fulfill(response=got, body=body.replace('"team":', '"team_me": "Ada", "team":', 1))

    def write(route):
        sent.append(json.loads(route.request.post_data))
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True, "team": [TEAM_COMMENT] if answer is None else answer}))
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


def test_a_reply_on_a_team_comment_shows_its_text(tab, site):
    told_team(tab.page, [{**TEAM_COMMENT, "replies": [{"by": "Bo", "at": "2026-11-17T11:00", "text": "agreed, for now"}]}])
    tab.open()
    tab.page.click("#rd-menu-btn")
    tab.page.click("#rd-show")
    tab.page.wait_for_selector("#rd-panel.open")
    tab.page.click("#rd-panel button[data-tab=team]")
    until(lambda: "agreed, for now" in tab.page.locator("#rd-panel").inner_text(), what="the reply in the Team tab")


def team_tab(tab):
    tab.open()
    tab.page.click("#rd-menu-btn")
    tab.page.click("#rd-show")
    tab.page.wait_for_selector("#rd-panel.open")
    tab.page.click("#rd-panel button[data-tab=team]")
    return tab.page.locator("#rd-panel .rd-team")


def buttons(item):
    return sorted(b.get_attribute("data-act") for b in item.locator("button[data-act]").all())


def test_a_member_replies_to_a_team_comment_from_the_page(tab, site):
    sent = told_team(tab.page, [TEAM_COMMENT], [{**TEAM_COMMENT, "replies": [{"by": "Ada", "at": "2026-11-17T12:00", "text": "noted"}]}])
    item = team_tab(tab)
    item.locator("button[data-act=reply]").click()
    tab.page.fill("#rd-panel .rd-team textarea", "noted")
    item.locator("button[data-act=send]").click()
    until(lambda: sent, what="the write")
    assert sent[0]["op"] == "reply" and sent[0]["id"] == "t1" and sent[0]["body"] == "noted"
    until(lambda: "noted" in tab.page.locator("#rd-panel").inner_text(), what="the reply in the tab")


def test_a_reply_sent_with_no_text_says_so_and_sends_nothing(tab, site):
    sent = told_team(tab.page, [TEAM_COMMENT])
    item = team_tab(tab)
    item.locator("button[data-act=reply]").click()
    item.locator("button[data-act=send]").click()
    toasted(tab.page, "Write something first.")
    assert sent == []


def test_a_member_resolves_and_reopens_a_team_comment(tab, site):
    sent = told_team(tab.page, [TEAM_COMMENT], [{**TEAM_COMMENT, "status": "resolved"}])
    item = team_tab(tab)
    item.locator("button[data-act=status]").click()
    until(lambda: sent, what="the write")
    assert sent[0]["op"] == "status" and sent[0]["id"] == "t1" and sent[0]["status"] == "resolved"
    until(lambda: tab.page.locator("#rd-panel .rd-team.rd-res").count() == 1, what="the resolved comment")
    tab.page.locator("#rd-panel .rd-team button[data-act=status]").click()
    until(lambda: len(sent) == 2, what="the second write")
    assert sent[1]["status"] == "open"


def test_an_author_edits_their_own_team_comment(tab, site):
    sent = told_team(tab.page, [TEAM_COMMENT], [{**TEAM_COMMENT, "body": "reworded"}])
    item = team_tab(tab)
    item.locator("button[data-act=edit]").click()
    assert tab.page.locator("#rd-panel .rd-team textarea").input_value() == "for the team"
    tab.page.fill("#rd-panel .rd-team textarea", "reworded")
    item.locator("button[data-act=send]").click()
    until(lambda: sent, what="the write")
    assert sent[0]["op"] == "edit" and sent[0]["id"] == "t1" and sent[0]["body"] == "reworded"
    until(lambda: "reworded" in tab.page.locator("#rd-panel").inner_text(), what="the new text")


def test_an_author_deletes_their_own_team_comment_after_confirming(tab, site):
    sent = told_team(tab.page, [TEAM_COMMENT], [])
    item = team_tab(tab)
    item.locator("button[data-act=delete]").click()
    tab.page.wait_for_timeout(300)
    assert sent == []
    tab.page.locator("#rd-panel .rd-team button[data-act=delete]").click()
    until(lambda: sent, what="the write")
    assert sent[0]["op"] == "delete" and sent[0]["id"] == "t1"
    until(lambda: "No Team comments" in tab.page.locator("#rd-panel").inner_text(), what="the empty tab")


def test_edit_and_delete_are_the_authors_and_delete_waits_until_no_one_else_replied(tab, site):
    theirs = {**TEAM_COMMENT, "id": "t2", "by": "Bo"}
    answered = {**TEAM_COMMENT, "id": "t3", "replies": [{"by": "Bo", "at": "2026-11-17T11:00", "text": "hm"}]}
    told_team(tab.page, [TEAM_COMMENT, theirs, answered])
    team_tab(tab)
    items = tab.page.locator("#rd-panel .rd-team")
    assert buttons(items.nth(0)) == ["delete", "edit", "reply", "status"]
    assert buttons(items.nth(1)) == ["reply", "status"]
    assert buttons(items.nth(2)) == ["edit", "reply", "status"]


def test_a_redraw_of_the_panel_keeps_the_text_of_a_reply_being_written(tab, site):
    told_team(tab.page, [TEAM_COMMENT])
    item = team_tab(tab)
    item.locator("button[data-act=reply]").click()
    tab.page.fill("#rd-panel .rd-team textarea", "half a thought")
    tab.page.click("#rd-panel button[data-tab=client]")
    tab.page.click("#rd-panel button[data-tab=team]")
    assert tab.page.locator("#rd-panel .rd-team textarea").input_value() == "half a thought"


def test_opening_a_form_on_another_team_comment_does_not_carry_the_first_forms_text_over(tab, site):
    told_team(tab.page, [TEAM_COMMENT, {**TEAM_COMMENT, "id": "t2", "by": "Bo"}])
    team_tab(tab)
    items = tab.page.locator("#rd-panel .rd-team")
    items.nth(0).locator("button[data-act=reply]").click()
    tab.page.fill("#rd-panel .rd-team textarea", "for the first")
    items.nth(1).locator("button[data-act=reply]").click()
    assert tab.page.locator("#rd-panel .rd-team[data-team=t2] textarea").input_value() == ""


T2 = {**TEAM_COMMENT, "id": "t2", "by": "Bo"}


def test_a_write_on_one_team_comment_leaves_the_open_form_and_text_of_another_alone(tab, site):
    told_team(tab.page, [TEAM_COMMENT, T2], [TEAM_COMMENT, {**T2, "status": "resolved"}])
    team_tab(tab)
    tab.page.locator("#rd-panel .rd-team[data-team=t1] button[data-act=reply]").click()
    tab.page.fill("#rd-panel .rd-team[data-team=t1] textarea", "for the first")
    tab.page.locator("#rd-panel .rd-team[data-team=t2] button[data-act=status]").click()
    until(lambda: tab.page.locator("#rd-panel .rd-team[data-team=t2] button[data-act=status]").inner_text() == "Reopen", what="the resolve to show")
    assert tab.page.locator("#rd-panel .rd-team[data-team=t1] textarea").input_value() == "for the first"


def test_opening_a_form_on_a_second_team_comment_keeps_the_first_forms_text(tab, site):
    told_team(tab.page, [TEAM_COMMENT, T2])
    team_tab(tab)
    tab.page.locator("#rd-panel .rd-team[data-team=t1] button[data-act=reply]").click()
    tab.page.fill("#rd-panel .rd-team[data-team=t1] textarea", "for the first")
    tab.page.locator("#rd-panel .rd-team[data-team=t2] button[data-act=reply]").click()
    assert tab.page.locator("#rd-panel .rd-team[data-team=t1] textarea").input_value() == "for the first"
    assert tab.page.locator("#rd-panel .rd-team[data-team=t2] textarea").input_value() == ""


def test_a_form_open_on_a_comment_that_was_deleted_does_not_move_to_the_one_that_takes_its_id(tab, site):
    # the hub numbers a new comment after the highest, so t3 deleted and a new t3 added is one id for two comments
    t3 = {**TEAM_COMMENT, "id": "t3", "at": "2026-11-17T10:00"}
    new_t3 = {**t3, "by": "Bo", "at": "2026-11-18T09:00", "body": "another"}
    told_team(tab.page, [TEAM_COMMENT, t3], [TEAM_COMMENT, new_t3])
    team_tab(tab)
    tab.page.locator("#rd-panel .rd-team[data-team=t3] button[data-act=reply]").click()
    tab.page.fill("#rd-panel .rd-team[data-team=t3] textarea", "for the old one")
    tab.page.locator("#rd-panel .rd-team[data-team=t1] button[data-act=status]").click()
    until(lambda: "another" in tab.page.locator("#rd-panel").inner_text(), what="the new t3 in the list")
    assert tab.page.locator("#rd-panel .rd-team[data-team=t3] textarea").count() == 0


def test_a_delete_waiting_for_its_second_click_does_not_move_to_the_comment_that_takes_its_id(tab, site):
    t3 = {**TEAM_COMMENT, "id": "t3"}
    new_t3 = {**t3, "at": "2026-11-18T09:00", "body": "another"}
    told_team(tab.page, [T2, t3], [T2, new_t3])
    team_tab(tab)
    delete = tab.page.locator("#rd-panel .rd-team[data-team=t3] button[data-act=delete]")
    delete.click()
    assert delete.inner_text() == "Confirm delete"
    tab.page.locator("#rd-panel .rd-team[data-team=t2] button[data-act=status]").click()
    until(lambda: "another" in tab.page.locator("#rd-panel").inner_text(), what="the new t3 in the list")
    assert tab.page.locator("#rd-panel .rd-team[data-team=t3] button[data-act=delete]").inner_text() == "Delete"


def test_the_text_of_a_team_form_survives_the_panel_of_a_refused_draft(tab, context, site):
    from test_page_drafts import lose_an_edit
    lose_an_edit(tab)
    page = context.new_page()
    told_team(page, [TEAM_COMMENT])
    page.route("**/_/save", lambda route: route.fulfill(status=500, content_type="application/json", body='{"error": "refused"}'))
    page.goto(tab.site.url)
    page.wait_for_selector("#rd-notice button[data-d=restore]")
    page.click("#rd-menu-btn")
    page.click("#rd-show")
    page.wait_for_selector("#rd-panel.open")
    page.click("#rd-panel button[data-tab=team]")
    page.click("#rd-panel .rd-team button[data-act=reply]")
    page.fill("#rd-panel .rd-team textarea", "half a thought")
    page.click("#rd-notice button[data-d=restore]")
    page.wait_for_selector("#rd-panel .rd-draft")
    page.click("#rd-menu-btn")
    page.click("#rd-show")
    page.click("#rd-panel button[data-tab=team]")
    assert page.locator("#rd-panel .rd-team textarea").input_value() == "half a thought"


def test_a_delete_the_hub_refuses_is_asked_for_again_from_the_start(tab, site):
    told_team(tab.page, [{**TEAM_COMMENT, "id": "t3"}])
    team_tab(tab)
    tab.page.route("**/_/comment", lambda route: route.fulfill(status=500, content_type="application/json", body='{"error": "refused"}'))
    delete = tab.page.locator("#rd-panel .rd-team[data-team=t3] button[data-act=delete]")
    delete.click()
    assert delete.inner_text() == "Confirm delete"
    delete.click()
    until(lambda: "refused" in tab.page.evaluate("document.querySelector('#rd-toast').textContent"), what="the refusal")
    assert tab.page.locator("#rd-panel .rd-team[data-team=t3] button[data-act=delete]").inner_text() == "Delete"
