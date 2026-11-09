"""The popover of a comment is a chat box: narrow, its messages in bubbles, a field to write in under them."""
import pytest

from pagehelp import DOC, P1, at, select, until
from sheafmd import comments as rdc
from sheafmd.hub.state import Tokens
from sheafmd.source import update_file

pytestmark = pytest.mark.page

FIELD = "#rd-popover textarea"
THREAD = "#rd-popover .rd-msg"


def open_thread(tab, site):
    """A comment of Bea's on the page, its thread open."""
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "apples"), "apples", "Why?",
                                                     "Bea", "2026-10-14T10:00")[0])
    tab.open()
    tab.page.click(".rd-badge")
    tab.page.wait_for_selector(FIELD)
    return tab.page


def test_a_thread_opens_with_the_cursor_in_the_field_under_its_messages(tab, site):
    p = open_thread(tab, site)
    field, box, msg = p.locator(FIELD).bounding_box(), p.locator("#rd-popover").bounding_box(), p.locator(THREAD).bounding_box()
    assert p.evaluate("document.activeElement.tagName") == "TEXTAREA", "the cursor is not in the field"
    assert field["width"] > box["width"] * 0.7, "the field is not the width of the box"
    assert field["y"] >= msg["y"] + msg["height"], "the field is not under the messages"


def test_enter_sends_as_in_a_chat(tab, site):
    p = open_thread(tab, site)
    p.fill("#rd-popover textarea", "Because.")
    p.keyboard.press("Enter")
    until(lambda: "Because." in site.file.read_text(encoding="utf-8"), what="the reply in the file")


def test_shift_enter_starts_a_new_line(tab, site):
    p = open_thread(tab, site)
    p.keyboard.type("kumquat")
    p.keyboard.press("Shift+Enter")
    p.keyboard.type("two")
    assert p.input_value("#rd-popover textarea") == "kumquat\ntwo"
    assert "kumquat" not in site.file.read_text(encoding="utf-8")


def test_my_messages_stand_on_the_right_and_the_others_on_the_left(tab, site):
    p = open_thread(tab, site)
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
    labels = p.locator("#rd-popover .rd-form button").evaluate_all("bs => bs.map(b => b.getAttribute('data-f'))")
    assert labels == ["tell"], labels
    p.fill("#rd-popover textarea", "Please look at this.")
    p.keyboard.press("Enter")
    until(lambda: p.locator("#rd-popover .rd-waits").count() == 1, what="the agent told")
    assert "Please look at this." in site.file.read_text(encoding="utf-8")


def test_without_an_agent_the_message_stays_a_comment_and_the_box_says_why(tab, site):
    p = open_thread(tab, site)
    assert p.locator("#rd-popover .rd-form button.rd-tell").count() == 0
    assert p.locator("#rd-popover .rd-form .rd-agent-line").count() == 1
    p.fill("#rd-popover textarea", "Noted.")
    p.keyboard.press("Enter")
    until(lambda: "Noted." in site.file.read_text(encoding="utf-8"), what="the reply in the file")


def test_resolve_is_a_small_button_at_the_top_right_and_stays_while_writing(tab, site):
    p = open_thread(tab, site)
    button, box = p.locator("#rd-popover button[data-a=status]").bounding_box(), p.locator("#rd-popover").bounding_box()
    assert button["y"] - box["y"] < 24 and box["x"] + box["width"] - (button["x"] + button["width"]) < 60, button
    p.fill(FIELD, "half a thought")
    assert p.is_visible("#rd-popover button[data-a=status]")
    assert p.get_attribute("#rd-popover button[data-a=status]", "title") == "Resolve"
    p.click("#rd-popover button[data-a=status]")
    until(lambda: rdc.parse(site.file.read_text(encoding="utf-8")).comments[0].status == "resolved", what="the thread resolved")
    until(lambda: not p.is_visible("#rd-popover textarea") or p.input_value("#rd-popover textarea") == "", what="the box to close")
    until(lambda: p.locator("#rd-unsent").count() == 1, what="the text kept in the unsent list")


def test_edit_and_delete_wait_in_a_small_menu(tab, site):
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "pears"), "pears", "Mine", "Ada", "2026-10-14T10:00")[0])
    tab.open()
    tab.page.click(".rd-badge")
    p = tab.page
    p.wait_for_selector(FIELD)
    assert not p.is_visible("#rd-popover button[data-a=delete]")
    p.click("#rd-popover .rd-more summary")
    assert p.is_visible("#rd-popover button[data-a=delete]") and p.is_visible("#rd-popover button[data-a=edit]")


def test_a_long_thread_opens_on_its_last_message_and_scrolls_up(tab, site):
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "apples"), "apples", "\n\n".join(["Why?"] * 200),
                                                     "Bea", "2026-10-14T10:00")[0])
    tab.open()
    tab.page.click(".rd-badge")
    tab.page.wait_for_selector(FIELD)
    top, room, full = tab.page.locator("#rd-popover .rd-scroll").evaluate("s => [s.scrollTop, s.clientHeight, s.scrollHeight]")
    assert full > room and top >= full - room - 4, (top, room, full)


def test_minimize_closes_the_box_and_the_text_comes_back_even_after_a_reload(tab, site):
    p = open_thread(tab, site)
    p.fill(FIELD, "half a thought")
    p.click("#rd-popover button[data-a=minimize]")
    assert p.locator("#rd-popover").count() == 0
    p.click(".rd-badge")
    until(lambda: p.input_value(FIELD) == "half a thought", what="the text back in the box")
    p.reload()
    p.click(".rd-badge")
    until(lambda: p.input_value(FIELD) == "half a thought", what="the text back after a reload")
    assert rdc.parse(site.file.read_text(encoding="utf-8")).comments[0].status == "open"


def test_escape_is_minimize(tab, site):
    p = open_thread(tab, site)
    p.fill(FIELD, "half a thought")
    p.keyboard.press("Escape")
    assert p.locator("#rd-popover").count() == 0
    p.click(".rd-badge")
    until(lambda: p.input_value(FIELD) == "half a thought", what="the text back in the box")


def test_selecting_text_opens_the_box_with_the_cursor_in_it(tab, site):
    tab.open()
    select(tab.page, at(P1, "apples"), at(P1, "apples", None))
    tab.page.wait_for_selector(FIELD)
    assert tab.page.locator("#rd-comment-btn").count() == 0
    assert tab.page.evaluate("document.activeElement.tagName") == "TEXTAREA"
    until(lambda: tab.page.locator("#rd-popover").count() == 1, what="the box to stay")


def test_ctrl_c_in_an_empty_field_copies_the_passage(tab, site):
    tab.open()
    select(tab.page, at(P1, "apples"), at(P1, "apples", None))
    tab.page.wait_for_selector(FIELD)
    got = tab.page.evaluate("""() => { const d = new DataTransfer();
        document.activeElement.dispatchEvent(new ClipboardEvent('copy', {clipboardData: d, bubbles: true, cancelable: true}));
        return d.getData('text/plain'); }""")
    assert got == "apples"


def test_in_edit_mode_a_selection_only_selects(tab, site):
    tab.open()
    tab.page.click("#rd-mode button[data-m=edit]")
    select(tab.page, at(P1, "apples"), at(P1, "apples", None))
    tab.page.wait_for_timeout(500)
    assert tab.page.locator("#rd-popover").count() == 0
    assert tab.page.locator("#rd-comment-btn").count() == 0
    tab.page.click("#rd-mode button[data-m=comment]")
    select(tab.page, at(P1, "apples"), at(P1, "apples", None))
    tab.page.wait_for_selector(FIELD)
