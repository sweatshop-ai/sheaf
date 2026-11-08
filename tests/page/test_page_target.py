"""The page's Agent line names the target and offers Change when the person may pick another (SPEC 9.8, 10.5)."""
import pytest

from pagehelp import DOC, until
from sheafmd.hub.state import Tokens

pytestmark = pytest.mark.page


def menu_text(tab):
    tab.page.click("#rd-menu-btn")
    tab.page.wait_for_selector("#rd-menu.open")
    return tab.page.text_content("#rd-agent")


def test_change_lists_the_other_targets_and_picking_one_moves_the_target(tab, agent, site):
    Tokens().add("ada-chatgpt", client="ChatGPT")
    tab.open()
    assert "Cosima" in menu_text(tab)
    tab.page.click("#rd-target-change")
    listed = tab.page.locator("#rd-targets button").all_inner_texts()
    assert [t.replace("\n", " ").strip() for t in listed] == ["Cosima · Claude Code ✓", f"ChatGPT ({site.hub.person})"]
    tab.page.click("#rd-targets button:not(.rd-current)")
    until(lambda: site.hub.docs.get(DOC)["target"].get("token") == "ada-chatgpt", what="the hub to take the agent")
    assert site.hub.docs.get(DOC)["session"]["session"] == "s-1"
    until(lambda: f"Tell → ChatGPT ({site.hub.person})" in tab.page.text_content("#rd-agent"),
          what="the Agent line to name the agent")
    tab.page.click("#rd-target-change")                                # now the session can be taken back
    assert tab.page.locator("#rd-targets button.rd-current").inner_text().strip().startswith(f"ChatGPT ({site.hub.person})")
    tab.page.click("#rd-targets button:not(.rd-current)")
    until(lambda: "Cosima" in tab.page.text_content("#rd-agent"), what="the session to be the target again")
    assert site.hub.docs.get(DOC)["target"]["session"] == "s-1"


def test_change_is_not_offered_when_there_is_no_other_target(tab, agent):
    tab.open()
    menu_text(tab)
    assert tab.page.query_selector("#rd-target-change") is None


def test_a_revoked_agent_shows_its_line_and_change_offers_the_session(tab, agent, site):
    Tokens().add("ada-chatgpt", client="ChatGPT")
    site.hub.docs.change(DOC, lambda e: {**e, "session": e["target"], "target": {
        "kind": "agent", "token": "ada-chatgpt", "id": next(r.id for r in Tokens().list() if r.name == "ada-chatgpt")}})
    Tokens().revoke("ada-chatgpt")
    tab.open()
    text = menu_text(tab)
    assert "ada-chatgpt can no longer reach this hub: its token was revoked. Pick another target." in text
    tab.page.click("#rd-target-change")
    assert tab.page.locator("#rd-targets button").all_inner_texts() == ["Cosima · Claude Code"]
    assert tab.page.query_selector("#rd-targets button.rd-current") is None      # a revoked agent is no pick, so none is ticked


def test_change_lists_the_targets_and_picks_one_in_a_tab_signed_in_again_after_a_key_rotation(tab, agent, site, context):
    Tokens().add("ada-chatgpt", client="ChatGPT")
    tab.open()
    site.hub.rotate()                                          # every tab is signed out; the targets are the hub's, not the key's
    context.clear_cookies()
    context.add_cookies([site.cookie()])                       # the cookie of the new key
    again = type(tab)(context.new_page(), site).open()
    assert "Cosima" in menu_text(again)
    again.page.click("#rd-target-change")
    listed = again.page.locator("#rd-targets button").all_inner_texts()
    assert [t.replace("\n", " ").strip() for t in listed] == ["Cosima · Claude Code ✓", f"ChatGPT ({site.hub.person})"]
    again.page.click("#rd-targets button:not(.rd-current)")
    until(lambda: site.hub.docs.get(DOC)["target"].get("token") == "ada-chatgpt", what="the hub to take the agent")
    assert again.errors == []
    again.page.close()
