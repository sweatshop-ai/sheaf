"""The popover of a comment is a chat box: narrow, its messages in bubbles, a field to write in under them."""
import pytest

from pagehelp import DOC, until
from sheafmd import comments as rdc
from sheafmd.hub.state import Tokens
from sheafmd.source import update_file

pytestmark = pytest.mark.page

FIELD = "#rd-popover button[data-a=reply]"


def open_thread(tab, site):
    """A comment of Bea's on the page, its thread open."""
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "apples"), "apples", "Why?",
                                                     "Bea", "2026-10-14T10:00")[0])
    tab.open()
    tab.page.click(".rd-badge")
    tab.page.wait_for_selector(FIELD)
    return tab.page


def test_a_thread_opens_with_a_field_to_write_in_under_its_messages(tab, site):
    p = open_thread(tab, site)
    field, box, msg = p.locator(FIELD).bounding_box(), p.locator("#rd-popover").bounding_box(), p.locator("#rd-popover .rd-msg").bounding_box()
    assert p.inner_text(FIELD) == "Write a message…"
    assert field["width"] > box["width"] * 0.8, "the field is a button among the others"
    assert field["y"] >= msg["y"] + msg["height"], "the field is not under the messages"


def test_the_field_becomes_the_real_one_where_it_stood(tab, site):
    p = open_thread(tab, site)
    p.click(FIELD)
    assert p.evaluate("document.activeElement.tagName") == "TEXTAREA"
    assert p.get_attribute("#rd-popover textarea", "placeholder") == "Write a message…"


def test_enter_sends_as_in_a_chat(tab, site):
    p = open_thread(tab, site)
    p.click(FIELD)
    p.fill("#rd-popover textarea", "Because.")
    p.keyboard.press("Enter")
    until(lambda: "Because." in site.file.read_text(encoding="utf-8"), what="the reply in the file")


def test_shift_enter_starts_a_new_line(tab, site):
    p = open_thread(tab, site)
    p.click(FIELD)
    p.keyboard.type("kumquat")
    p.keyboard.press("Shift+Enter")
    p.keyboard.type("two")
    assert p.input_value("#rd-popover textarea") == "kumquat\ntwo"
    assert "kumquat" not in site.file.read_text(encoding="utf-8")


def test_my_messages_stand_on_the_right_and_the_others_on_the_left(tab, site):
    p = open_thread(tab, site)
    p.click(FIELD)
    p.fill("#rd-popover textarea", "Because.")
    p.click("#rd-popover button[data-f=ok]")
    until(lambda: p.locator("#rd-popover .rd-msg").count() == 2, what="the reply in the thread")
    scroll = p.locator("#rd-popover .rd-scroll").bounding_box()
    bea, me = (p.locator("#rd-popover .rd-msg").nth(i).bounding_box() for i in (0, 1))
    assert bea["x"] <= scroll["x"] + 2, "Bea's message is not on the left"
    assert me["x"] + me["width"] >= scroll["x"] + scroll["width"] - 16, "my message is not on the right"
    assert me["width"] < scroll["width"] * 0.9, "my message is a full line, not a bubble"


def test_the_popover_is_narrow_and_tall_on_a_wide_screen(tab, site):
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "apples"), "apples", "\n\n".join(["Why?"] * 200),
                                                     "Bea", "2026-10-14T10:00")[0])
    tab.page.set_viewport_size({"width": 1600, "height": 1000})
    tab.open()
    tab.page.click(".rd-badge")
    tab.page.wait_for_selector(FIELD)
    box = tab.page.locator("#rd-popover").bounding_box()
    assert box["width"] <= 340 and box["height"] <= 560, box
    assert box["height"] > box["width"], box


def agent_on_the_page(tab, site):
    """As open_thread, with an agent as the page's target: what is sent goes to it."""
    Tokens().add("ada-chatgpt", client="ChatGPT")
    site.hub.docs.change(DOC, lambda e: {**e, "target": {"kind": "agent", "token": "ada-chatgpt",
                                                        "id": next(r.id for r in Tokens().list() if r.name == "ada-chatgpt")}})
    return open_thread(tab, site)


def test_talking_to_the_agent_is_the_only_action_of_the_box(tab, site):
    p = agent_on_the_page(tab, site)
    assert p.locator("#rd-popover button[data-a=tell]").count() == 0, "a second way to Tell beside the field"
    p.click(FIELD)
    labels = p.locator("#rd-popover .rd-form button").evaluate_all("bs => bs.map(b => b.getAttribute('data-f'))")
    assert sorted(labels) == ["no", "tell"], labels
    p.fill("#rd-popover textarea", "Please look at this.")
    p.keyboard.press("Enter")
    until(lambda: p.locator("#rd-popover .rd-waits").count() == 1, what="the agent told")
    assert "Please look at this." in site.file.read_text(encoding="utf-8")


def test_without_an_agent_the_message_stays_a_comment_and_the_box_says_why(tab, site):
    p = open_thread(tab, site)
    p.click(FIELD)
    assert p.locator("#rd-popover .rd-form button.rd-tell").count() == 0
    assert p.locator("#rd-popover .rd-form .rd-agent-line").count() == 1
    p.fill("#rd-popover textarea", "Noted.")
    p.keyboard.press("Enter")
    until(lambda: "Noted." in site.file.read_text(encoding="utf-8"), what="the reply in the file")


def test_resolve_is_a_small_button_at_the_top_right_and_stays_while_writing(tab, site):
    p = open_thread(tab, site)
    button, box = p.locator("#rd-popover button[data-a=status]").bounding_box(), p.locator("#rd-popover").bounding_box()
    assert button["y"] - box["y"] < 24 and box["x"] + box["width"] - (button["x"] + button["width"]) < 60, button
    p.click(FIELD)
    assert p.is_visible("#rd-popover button[data-a=status]")
    p.click("#rd-popover button[data-a=status]")
    until(lambda: rdc.parse(site.file.read_text(encoding="utf-8")).comments[0].status == "resolved", what="the thread resolved")


def test_edit_and_delete_wait_in_a_small_menu(tab, site):
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "pears"), "pears", "Mine", "Ada", "2026-10-14T10:00")[0])
    tab.open()
    tab.page.click(".rd-badge")
    p = tab.page
    p.wait_for_selector(FIELD)
    assert not p.is_visible("#rd-popover button[data-a=delete]")
    p.click("#rd-popover .rd-more summary")
    assert p.is_visible("#rd-popover button[data-a=delete]") and p.is_visible("#rd-popover button[data-a=edit]")
