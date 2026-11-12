"""The popover of a comment is a chat box: narrow, its messages in bubbles, a field to write in under them."""
import pytest

from pagehelp import DOC, P1, P2, at, box, comment_draft_key, mark, open_box, pasted, reloaded, select, toast, until
from sheafmd import comments as rdc
from sheafmd.hub.state import Tokens
from sheafmd.source import update_file

pytestmark = pytest.mark.page

FIELD = "#rd-popover textarea"
THREAD = "#rd-popover .rd-msg"
THREAD_BOX = "#rd-popover"


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


def test_without_an_agent_the_message_stays_a_comment_and_the_box_carries_no_hint(tab, site):
    """Restated on 2026-11-09 (G): the box no longer says why, anywhere, desktop too ("Render this page from an agent session...")."""
    p = open_thread(tab, site)
    assert p.locator("#rd-popover .rd-form button.rd-tell").count() == 0
    assert p.locator("#rd-popover .rd-agent-line").count() == 0
    assert "agent session" not in p.inner_text("#rd-popover")
    p.fill("#rd-popover textarea", "Noted.")
    p.keyboard.press("Enter")
    until(lambda: "Noted." in site.file.read_text(encoding="utf-8"), what="the reply in the file")


def test_the_minus_resolves_an_open_thread_and_stays_while_writing(tab, site):
    """The minus is Resolve and the cross is Close (swapped on 2026-11-09 after a trial: the cross resolved a thread by accident)."""
    p = open_thread(tab, site)
    button, box = p.locator("#rd-popover button[title=Resolve]").bounding_box(), p.locator("#rd-popover").bounding_box()
    assert button["y"] - box["y"] < 24 and box["x"] + box["width"] - (button["x"] + button["width"]) < 90, button
    assert p.inner_text("#rd-popover button[title=Resolve]") == "\u2212" and p.inner_text("#rd-popover button[title=Close]") == "\u00D7"
    assert p.locator("#rd-popover button[title=Minimize]").count() == 0
    p.fill(FIELD, "half a thought")
    assert p.is_visible("#rd-popover button[title=Resolve]")
    p.click("#rd-popover button[title=Resolve]")
    until(lambda: rdc.parse(site.file.read_text(encoding="utf-8")).comments[0].status == "resolved", what="the thread resolved")
    until(lambda: not p.is_visible("#rd-popover textarea") or p.input_value("#rd-popover textarea") == "", what="the box to close")
    until(lambda: p.locator("#rd-unsent").count() == 1, what="the text kept in the unsent list")


def test_the_cross_closes_an_open_thread_and_keeps_everything(tab, site):
    p = open_thread(tab, site)
    p.fill(FIELD, "half a thought")
    p.click("#rd-popover button[title=Close]")
    assert p.locator("#rd-popover").count() == 0
    assert rdc.parse(site.file.read_text(encoding="utf-8")).comments[0].status == "open", "the cross resolved the thread"
    p.click(".rd-badge")
    until(lambda: p.input_value(FIELD) == "half a thought", what="the text back in the box")


def test_there_is_no_minus_where_there_is_nothing_to_resolve(tab, site):
    p = open_thread(tab, site)
    p.keyboard.press("Escape")
    select(p, at(P1, "apples"), at(P1, "apples", None))
    open_box(p)
    assert p.locator("#rd-popover button[title=Close]").count() == 1
    assert p.locator("#rd-popover button[title=Resolve]").count() == 0, "a new message offers Resolve"


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


def long_thread(tab, site):
    """A comment of Bea's with 200 paragraphs, its thread open on the last of them."""
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "apples"), "apples", "\n\n".join(["Why?"] * 200),
                                                     "Bea", "2026-10-14T10:00")[0])
    tab.open()
    tab.page.click(".rd-badge")
    tab.page.wait_for_selector(FIELD)
    return tab.page


def in_view(p, nth):
    """Is the nth message of the thread inside the visible part of the thread?"""
    return p.evaluate("""(n) => {
      const s = document.querySelector('#rd-popover .rd-scroll').getBoundingClientRect();
      const m = document.querySelectorAll('#rd-popover .rd-msg')[n].getBoundingClientRect();
      return m.top >= s.top - 1 && m.bottom <= s.bottom + 1;
    }""", nth)


def test_after_a_send_the_thread_shows_the_message_just_sent(tab, site):
    p = long_thread(tab, site)
    p.fill(FIELD, "Because.")
    p.keyboard.press("Enter")
    until(lambda: p.locator(THREAD).count() == 2, what="the reply in the thread")
    until(lambda: in_view(p, 1), what="the sent message in view")


def test_after_a_send_of_a_text_of_several_lines_the_thread_shows_the_message_just_sent(tab, site):
    p = long_thread(tab, site)
    p.fill(FIELD, "\n".join(["a line of the answer"] * 12))
    p.keyboard.press("Enter")
    until(lambda: p.locator(THREAD).count() == 2, what="the reply in the thread")
    until(lambda: in_view(p, 1), what="the sent message in view")


def test_an_answer_that_arrives_while_the_thread_is_at_its_end_keeps_it_there(tab, site):
    p = long_thread(tab, site)
    update_file(site.file, lambda t: rdc.reply(t, "c1", "An answer", "Bea", "2026-10-14T11:00"))
    until(lambda: "An answer" in p.inner_text(THREAD_BOX), what="the answer in the thread")
    until(lambda: in_view(p, 1), what="the answer in view")


def test_a_reader_who_came_back_to_the_end_stays_there_when_the_field_grows(tab, site):
    p = long_thread(tab, site)
    p.evaluate("""() => { const s = document.querySelector('#rd-popover .rd-scroll'); s.scrollTop = 0; }""")
    p.evaluate("""() => { const s = document.querySelector('#rd-popover .rd-scroll'); s.scrollTop = s.scrollHeight; }""")
    p.fill(FIELD, "\n".join(["a line being typed"] * 12))
    until(lambda: p.evaluate("(() => { const s = document.querySelector('#rd-popover .rd-scroll'); return s.scrollTop + s.clientHeight >= s.scrollHeight - 4; })()"),
          what="the thread at its end")


def test_an_answer_does_not_pull_down_a_reader_of_older_messages(tab, site):
    p = long_thread(tab, site)
    p.evaluate("document.querySelector('#rd-popover .rd-scroll').scrollTop = 1000")
    until(lambda: p.evaluate("document.querySelector('#rd-popover .rd-scroll').scrollTop") == 1000, what="the reader mid-thread")
    update_file(site.file, lambda t: rdc.reply(t, "c1", "An answer", "Bea", "2026-10-14T11:00"))
    until(lambda: "An answer" in p.inner_text(THREAD_BOX), what="the answer in the thread")
    until(lambda: p.evaluate("document.querySelector('#rd-popover .rd-scroll').scrollTop") == 1000, what="the reader's place kept")


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


def real_selection(page, css, word):
    """A double click with the real mouse on `word` under `css`: the page hears mousedown, mouseup, click."""
    b = box(page, css, word)
    page.mouse.dblclick(b["x"] + b["width"] / 2, b["y"] + b["height"] / 2)


def test_a_real_ctrl_c_in_the_empty_field_puts_the_passage_on_the_clipboard(tab, site):
    """The keystroke and the clipboard are the browser's own: the copy event above is built by hand."""
    tab.open()
    real_selection(tab.page, P1, "apples")
    tab.page.wait_for_selector(FIELD)
    assert tab.page.evaluate("document.activeElement.value") == ""
    tab.page.keyboard.press("ControlOrMeta+c")
    assert pasted(tab.page) == "apples"


def test_a_real_ctrl_c_copies_what_is_selected_in_the_field_once_it_holds_text(tab, site):
    tab.open()
    real_selection(tab.page, P1, "apples")
    tab.page.wait_for_selector(FIELD)
    tab.page.fill(FIELD, "my words")
    tab.page.keyboard.press("ControlOrMeta+a")
    tab.page.keyboard.press("ControlOrMeta+c")
    assert pasted(tab.page) == "my words"


def test_a_real_ctrl_c_on_text_selected_in_a_bubble_copies_that_text_not_the_cited_passage(tab, site):
    p = open_thread(tab, site)
    p.locator(THREAD).first.click(click_count=3)
    until(lambda: p.evaluate("getSelection().toString().trim()") == "Why?", what="the bubble's text selected")
    p.keyboard.press("ControlOrMeta+c")
    assert pasted(p).strip() == "Why?"


def test_a_real_ctrl_c_on_a_bubble_of_the_thread_just_started_copies_that_text_not_the_cited_passage(tab, site):
    tab.open()
    real_selection(tab.page, P1, "apples")
    tab.page.wait_for_selector(FIELD)
    tab.page.fill(FIELD, "Why the apples?")
    tab.page.keyboard.press("Enter")
    tab.page.wait_for_selector("#rd-popover .rd-msg")
    p = tab.page
    p.locator(THREAD).first.click(click_count=3)
    until(lambda: p.evaluate("getSelection().toString().trim()") == "Why the apples?", what="the bubble's text selected")
    p.keyboard.press("ControlOrMeta+c")
    assert pasted(p).strip() == "Why the apples?"


def test_in_edit_mode_a_selection_only_selects(tab, site):
    tab.open()
    tab.page.click("#rd-mode button[data-m=edit]")
    select(tab.page, at(P1, "apples"), at(P1, "apples", None))
    tab.page.wait_for_timeout(500)
    assert tab.page.locator("#rd-popover").count() == 0
    assert tab.page.locator("#rd-comment-btn").count() == 0
    tab.page.click("#rd-mode button[data-m=save]")
    select(tab.page, at(P1, "apples"), at(P1, "apples", None))
    tab.page.wait_for_selector(FIELD)


def test_a_minimized_new_message_is_named_a_message_in_the_not_sent_line(tab, site):
    tab.open()
    select(tab.page, at(P1, "apples"), at(P1, "apples", None))
    tab.page.fill(FIELD, "Why apples?")
    tab.page.keyboard.press("Escape")
    until(lambda: tab.page.locator("#rd-unsent").count() == 1, what="the not-sent line")
    assert tab.page.inner_text("#rd-unsent") == "1 message not sent · Show"


def show_resolved(page):
    """The badge of a resolved thread is hidden until the comments panel lists them (its filter sets this class)."""
    page.evaluate("document.body.classList.add('rd-show-resolved')")


def test_a_resolved_thread_closes_with_the_cross_and_reopens_from_the_menu(tab, site):
    update_file(site.file, lambda t: rdc.set_status(rdc.add_comment(t, *rdc.find_quote(t, "apples"), "apples", "Why?",
                                                                    "Ada", "2026-10-14T10:00")[0], "c1", "resolved"))
    tab.open()
    p = tab.page
    show_resolved(p)
    p.click(".rd-badge")
    p.wait_for_selector(FIELD)
    assert p.get_attribute("#rd-popover .rd-head > button:last-child", "title") == "Close"
    assert p.locator("#rd-popover .rd-head button[title=Resolve]").count() == 0, "a resolved thread offers Resolve"
    assert p.inner_text("#rd-popover .rd-head > button:last-child") == "\u00D7"
    p.click("#rd-popover .rd-more summary")
    assert p.is_visible("#rd-popover .rd-more button[data-a=status]:has-text('Reopen')")
    assert p.is_visible("#rd-popover .rd-more button[data-a=edit]") and p.is_visible("#rd-popover .rd-more button[data-a=delete]")
    p.click("#rd-popover .rd-head > button:last-child")
    assert p.locator("#rd-popover").count() == 0
    assert rdc.parse(site.file.read_text(encoding="utf-8")).comments[0].status == "resolved", "the cross reopened the thread"


def test_a_resolved_thread_of_another_person_has_no_edit_or_delete(tab, site):
    update_file(site.file, lambda t: rdc.set_status(rdc.add_comment(t, *rdc.find_quote(t, "apples"), "apples", "Why?",
                                                                    "Bea", "2026-10-14T10:00")[0], "c1", "resolved"))
    tab.open()
    show_resolved(tab.page)
    tab.page.click(".rd-badge")
    tab.page.wait_for_selector(FIELD)
    tab.page.click("#rd-popover .rd-more summary")
    assert tab.page.locator("#rd-popover .rd-more button").evaluate_all("bs => bs.map(b => b.textContent)") == ["Reopen"]


def test_an_empty_box_does_not_hold_a_reload_but_typed_text_does(tab, site):
    p = open_thread(tab, site)
    mark(p)
    site.file.write_text(site.file.read_text(encoding="utf-8") + "\nFrom outside.\n", encoding="utf-8")
    reloaded(p)
    p.wait_for_selector(".rd-badge")
    p.wait_for_timeout(500)                             # the reload keeps the thread open; open it only if it is not
    if not p.query_selector(FIELD):
        p.click(".rd-badge")
    p.wait_for_selector(FIELD)
    p.fill(FIELD, "half a thought")
    mark(p)
    site.file.write_text(site.file.read_text(encoding="utf-8") + "\nAnd again.\n", encoding="utf-8")
    p.wait_for_selector("#rd-popover .rd-hold")
    p.wait_for_timeout(1000)
    assert p.evaluate("window.__same_load") is True, "the page reloaded under the typed text"
    assert p.input_value(FIELD) == "half a thought"


def test_emptying_the_last_typed_field_lifts_the_held_reload(tab, site):
    """An empty field is not writing: the reload that waited for the text runs once the field is emptied, without
    the box being closed."""
    p = open_thread(tab, site)
    p.fill(FIELD, "half a thought")
    mark(p)
    site.file.write_text(site.file.read_text(encoding="utf-8") + "\nFrom outside.\n", encoding="utf-8")
    p.wait_for_selector("#rd-popover .rd-hold")
    p.wait_for_timeout(500)
    assert p.evaluate("window.__same_load") is True, "the page reloaded under the typed text"
    p.fill(FIELD, "")
    reloaded(p)


def test_enter_during_an_ime_composition_does_not_send(tab, site):
    p = open_thread(tab, site)
    p.fill(FIELD, "konnichi")
    p.evaluate("""() => document.querySelector('#rd-popover textarea').dispatchEvent(
        new KeyboardEvent('keydown', {key: 'Enter', isComposing: true, bubbles: true, cancelable: true}))""")
    p.wait_for_timeout(500)
    assert "konnichi" not in site.file.read_text(encoding="utf-8"), "Enter that confirms a composition sent the message"
    assert p.input_value(FIELD) == "konnichi"


def test_a_reply_kept_by_the_older_page_is_listed_as_a_reply_and_comes_back_in_its_thread(tab, site):
    import json
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "apples"), "apples", "Why?",
                                                     "Bea", "2026-10-14T10:00")[0])
    tab.open()
    old = [{"thread": "c1", "kind": "reply", "body": "from the old page", "about": "apples", "born": "2026-10-14T10:00",
            "at": "2026-10-14T11:00:00.000Z"}]
    tab.page.evaluate("([k, v]) => localStorage.setItem(k, v)", [comment_draft_key(site), json.dumps(old)])
    tab.page.reload()
    until(lambda: tab.page.locator("#rd-unsent").count() == 1, what="the not-sent line")
    assert tab.page.inner_text("#rd-unsent") == "1 reply not sent · Show"
    tab.page.click(".rd-badge")
    until(lambda: tab.page.input_value(FIELD) == "from the old page", what="the old text in the box")


def test_a_click_on_the_document_minimizes_the_box_and_keeps_the_text(tab, site):
    p = open_thread(tab, site)
    p.fill(FIELD, "half a thought")
    p.mouse.click(5, 700)                                # the margin of the document, away from the box
    until(lambda: p.locator("#rd-popover").count() == 0, what="the box to close")
    p.click(".rd-badge")
    until(lambda: p.input_value(FIELD) == "half a thought", what="the text back in the box")


def test_a_click_on_a_page_control_is_not_a_click_beside_the_box(tab, site):
    p = open_thread(tab, site)
    p.fill(FIELD, "half a thought")
    p.click("#rd-mode button[data-m=edit]")
    p.wait_for_timeout(500)
    assert p.locator("#rd-popover").count() == 1, "the mode switch closed the box"
    assert p.input_value(FIELD) == "half a thought"


# ---- text the store cannot keep: the box stays (SPEC 10.4, Isolde 2026-11-09) -------------------------------

def store_full(p, full=True):
    """The comment store refuses writes (quota full, storage blocked), or accepts them again."""
    p.evaluate("""(full) => {
      if (!window.__realSet) window.__realSet = Storage.prototype.setItem;
      Storage.prototype.setItem = function (k, v) {
        if (full && String(k).startsWith('sheaf-comment-draft')) throw new Error('quota');
        return window.__realSet.call(this, k, v);
      };
    }""", full)


def two_threads(tab, site):
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "pears"), "pears", "Why pears?",
                                                     "Bea", "2026-10-14T10:01")[0])
    return open_thread(tab, site)


WAYS = {
    "escape": lambda p: p.keyboard.press("Escape"),
    "a click beside": lambda p: p.mouse.click(5, 700),
    "minimize": lambda p: p.click("#rd-popover button[data-a=minimize]"),
    "resolve": lambda p: p.click("#rd-popover button[data-a=status]"),
    "another badge": lambda p: p.locator(".rd-badge").nth(1).dispatch_event("click"),
}


@pytest.mark.parametrize("way", list(WAYS))
def test_text_the_store_cannot_keep_holds_the_box_open_and_says_so(tab, site, way):
    p = two_threads(tab, site)
    store_full(p)
    p.fill(FIELD, "words I must not lose")
    WAYS[way](p)
    until(lambda: "could not be kept" in toast(p), what="the toast that says the text could not be kept")
    assert p.locator("#rd-popover").count() == 1, f"{way} closed the box on text that was not kept"
    assert p.input_value(FIELD) == "words I must not lose"
    assert "resolved" not in site.file.read_text(encoding="utf-8").split("Why?")[-1].split("Why pears?")[0], \
        "the thread was resolved while its text could not go to the not-sent list"


def test_a_new_message_the_store_cannot_keep_stays_open_on_its_close(tab, site):
    p = open_thread(tab, site)
    p.keyboard.press("Escape")
    store_full(p)
    select(p, at(P1, "apples"), at(P1, "apples", None))
    open_box(p)
    p.fill(FIELD, "a new message that cannot be kept")
    p.click("#rd-popover button[data-a=minimize]")
    until(lambda: "could not be kept" in toast(p), what="the toast")
    assert p.locator("#rd-popover").count() == 1
    assert p.input_value(FIELD) == "a new message that cannot be kept"


def test_an_empty_field_closes_even_when_the_store_is_full(tab, site):
    p = open_thread(tab, site)
    store_full(p)
    p.keyboard.press("Escape")
    until(lambda: p.locator("#rd-popover").count() == 0, what="the box to close")


def test_the_box_closes_normally_once_the_store_works_again(tab, site):
    p = open_thread(tab, site)
    store_full(p)
    p.fill(FIELD, "kept at last")
    p.keyboard.press("Escape")
    until(lambda: "could not be kept" in toast(p), what="the refusal")
    store_full(p, False)
    p.keyboard.press("Escape")
    until(lambda: p.locator("#rd-popover").count() == 0, what="the box to close")
    p.click(".rd-badge")
    until(lambda: p.input_value(FIELD) == "kept at last", what="the text back in the box")


def test_choosing_edit_while_a_reply_is_typed_keeps_the_reply(tab, site):
    """Edit replaces the field by the edit form: the reply typed there must not be thrown away, and Cancel brings it back."""
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "pears"), "pears", "Mine", "Ada", "2026-10-14T10:00")[0])
    tab.open()
    tab.page.click(".rd-badge")
    p = tab.page
    p.wait_for_selector(FIELD)
    p.fill(FIELD, "my reply, half written")
    p.click("#rd-popover .rd-more summary")
    p.click("#rd-popover button[data-a=edit]")
    until(lambda: p.input_value(FIELD) == "Mine", what="the edit form, filled with the message")
    p.click("#rd-popover button[data-f=no]")
    until(lambda: p.input_value(FIELD) == "my reply, half written", what="the reply back in the field after Cancel")


def my_thread(tab, site):
    """A comment of Ada's own on the page, its thread open: the menu offers Edit."""
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "pears"), "pears", "Mine", "Ada", "2026-10-14T10:00")[0])
    tab.open()
    tab.page.click(".rd-badge")
    tab.page.wait_for_selector(FIELD)
    return tab.page


def choose_edit(p):
    if not p.is_visible("#rd-popover button[data-a=edit]"):       # the menu stays open after a choice
        p.click("#rd-popover .rd-more summary")
    p.click("#rd-popover button[data-a=edit]")


def test_choosing_edit_when_the_store_cannot_keep_the_reply_leaves_the_reply_in_the_field(tab, site):
    """Edit would replace the field: a reply the store refuses has nowhere else to go, so Edit does not open and says so."""
    p = my_thread(tab, site)
    store_full(p)
    p.fill(FIELD, "a reply that cannot be kept")
    choose_edit(p)
    until(lambda: "could not be kept" in toast(p), what="the toast that says the text could not be kept")
    assert p.input_value(FIELD) == "a reply that cannot be kept"
    assert p.locator("#rd-popover [data-f=no]").count() == 0, "the edit form replaced the reply"


def test_choosing_edit_again_on_a_changed_edit_form_keeps_the_changes(tab, site):
    """The edit form stands, with what was typed in it: a second Edit must not bring back the old text, which the next Save or Cancel would clear from the store."""
    p = my_thread(tab, site)
    choose_edit(p)
    until(lambda: p.input_value(FIELD) == "Mine", what="the edit form, filled with the message")
    p.fill(FIELD, "Mine, changed")
    choose_edit(p)
    assert p.input_value(FIELD) == "Mine, changed", "the second Edit brought back the old text"
    assert p.locator("#rd-popover [data-f=no]").count() == 1


def test_choosing_edit_again_on_an_unchanged_edit_form_opens_it_afresh(tab, site):
    p = my_thread(tab, site)
    choose_edit(p)
    until(lambda: p.input_value(FIELD) == "Mine", what="the edit form")
    choose_edit(p)
    assert p.input_value(FIELD) == "Mine"
    assert p.locator("#rd-popover [data-f=no]").count() == 1


def second_form_beside_the_first(p):
    """What a failed send of another thread leaves in this box: a second form, the cursor in it."""
    p.evaluate("""() => {
      const first = document.querySelector('#rd-popover .rd-form');
      const second = first.cloneNode(true);
      second.querySelector('textarea').value = 'the other form';
      first.after(second);
      second.querySelector('textarea').focus();
    }""")


def an_answer_arrives(site, p):
    """A reply written to the file: the page redraws the thread (fillPopover)."""
    update_file(site.file, lambda t: rdc.reply(t, "c1", "An answer", "Bea", "2026-10-14T11:00"))
    until(lambda: "An answer" in p.inner_text(THREAD_BOX), what="the answer in the thread")


def test_a_redraw_leaves_the_cursor_in_the_form_it_was_in(tab, site):
    """With two forms in the box the cursor must not jump to the first while the second is typed in."""
    p = open_thread(tab, site)
    second_form_beside_the_first(p)
    an_answer_arrives(site, p)
    assert p.evaluate("document.activeElement.value") == "the other form", "the cursor jumped to the first form"


def test_a_redraw_leaves_the_cursor_in_the_only_form(tab, site):
    p = open_thread(tab, site)
    p.focus(FIELD)
    an_answer_arrives(site, p)
    assert p.evaluate("document.activeElement.tagName") == "TEXTAREA"
    assert p.locator("#rd-popover .rd-form").count() == 1


def test_a_redraw_keeps_the_caret_of_the_field_when_a_button_has_the_cursor(tab, site):
    """Tab to Send, then an answer arrives: the typed text keeps its caret, it does not jump to the start."""
    p = open_thread(tab, site)
    p.fill(FIELD, "hello")
    p.press(FIELD, "Tab")
    assert p.evaluate("document.activeElement.tagName") == "BUTTON"
    an_answer_arrives(site, p)
    assert p.evaluate("document.activeElement.tagName") == "TEXTAREA"
    assert p.evaluate("document.activeElement.selectionStart") == 5


def test_choosing_edit_on_an_edit_form_the_message_moved_away_from_opens_it_afresh(tab, site):
    """A live update changed the message while the edit form stood untouched: Edit shows the new text, not the stale one."""
    p = my_thread(tab, site)
    choose_edit(p)
    until(lambda: p.input_value(FIELD) == "Mine", what="the edit form")
    update_file(site.file, lambda t: rdc.edit_body(t, "c1", "Mine v2"))
    until(lambda: p.evaluate("document.querySelector('#rd-popover').innerText.includes('Mine v2')") or p.input_value(FIELD) == "Mine v2", what="the live update")
    choose_edit(p)
    assert p.input_value(FIELD) == "Mine v2"


def test_closing_an_edit_form_that_was_not_changed_leaves_nothing_unsent(tab, site):
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "pears"), "pears", "Mine", "Ada", "2026-10-14T10:00")[0])
    tab.open()
    tab.page.click(".rd-badge")
    p = tab.page
    p.wait_for_selector(FIELD)
    p.click("#rd-popover .rd-more summary")
    p.click("#rd-popover button[data-a=edit]")
    until(lambda: p.input_value(FIELD) == "Mine", what="the edit form")
    p.click("#rd-popover button[title=Close]")
    assert p.locator("#rd-popover").count() == 0
    assert p.locator("#rd-unsent").count() == 0, "an edit nobody made is listed as not sent"
    p.click(".rd-badge")
    until(lambda: p.locator(FIELD).count() == 1, what="the box again")
    assert p.locator("#rd-popover [data-f=no]").count() == 0, "the thread reopened in the edit form"


@pytest.mark.parametrize("init", [{"isComposing": True}, {"isComposing": False, "keyCode": 229}], ids=["composing", "safari-keycode-229"])
def test_the_enter_that_confirms_an_ime_composition_sends_nothing(tab, site, init):
    """Safari ends the composition before the keydown of the Enter that confirms it: isComposing is false there, keyCode is 229."""
    p = open_thread(tab, site)
    p.fill(FIELD, "konnichiwa")
    p.evaluate("(init) => document.querySelector('#rd-popover textarea').dispatchEvent(new KeyboardEvent('keydown', "
               "Object.assign({key: 'Enter', bubbles: true, cancelable: true}, init)))", init)
    p.wait_for_timeout(500)
    assert p.input_value(FIELD) == "konnichiwa"
    assert len(rdc.parse(site.file.read_text(encoding="utf-8")).comments[0].replies) == 0, "the confirming Enter sent the message"


def test_a_thread_on_a_page_that_cannot_save_keeps_the_cross_and_no_write_control(tab, site, context, tmp_path):
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "apples"), "apples", "Why?",
                                                     "Bea", "2026-10-14T10:00")[0])
    # The same page opened from a file: no hub to save to, so every write control is off.
    saved = tmp_path / "page.html"
    saved.write_text(context.request.get(site.url).text(), encoding="utf-8")
    p = context.new_page()
    p.goto(saved.as_uri())
    p.click(".rd-badge")
    p.wait_for_selector("#rd-popover")
    assert p.locator("#rd-popover .rd-head button[data-a=minimize]").count() == 1, "no Close on a thread that cannot save"
    for gone in ("status", "edit", "delete"):
        assert p.locator(f"#rd-popover [data-a={gone}]").count() == 0, gone
    p.click("#rd-popover button[data-a=minimize]")
    assert p.locator("#rd-popover").count() == 0
    p.click(".rd-badge")
    p.wait_for_selector("#rd-popover")
    p.keyboard.press("Escape")
    assert p.locator("#rd-popover").count() == 0, "Escape does not close it"
    p.click(".rd-badge")
    p.wait_for_selector("#rd-popover")
    p.mouse.click(5, 5)
    assert p.locator("#rd-popover").count() == 0, "a click beside the box does not close it"


def test_a_minimized_message_whose_field_is_emptied_is_gone_from_the_store_when_the_box_closes(tab, site):
    tab.open()
    p = tab.page
    select(p, at(P1, "apples"), at(P1, "apples", None))
    p.fill(FIELD, "Why apples?")
    p.keyboard.press("Escape")
    until(lambda: p.locator("#rd-unsent").count() == 1, what="the not-sent line")
    select(p, at(P1, "apples"), at(P1, "apples", None))
    p.wait_for_selector(FIELD)
    until(lambda: p.input_value(FIELD) == "Why apples?", what="the kept text back in the box")
    p.fill(FIELD, "")
    p.keyboard.press("Escape")
    until(lambda: p.locator("#rd-unsent").count() == 0, what="the not-sent line gone")
    assert "Why apples?" not in (p.evaluate("JSON.stringify(Object.values(localStorage))")), "the emptied draft stayed in the store"
    select(p, at(P1, "apples"), at(P1, "apples", None))
    p.wait_for_selector(FIELD)
    assert p.input_value(FIELD) == "", "the erased text came back"


def test_closing_an_empty_new_message_that_was_never_kept_changes_nothing(tab, site):
    tab.open()
    p = tab.page
    select(p, at(P1, "apples"), at(P1, "apples", None))
    p.wait_for_selector(FIELD)
    p.keyboard.press("Escape")
    assert p.locator("#rd-popover").count() == 0
    assert p.locator("#rd-unsent").count() == 0


def test_the_not_sent_list_opened_beside_an_open_box_holds_the_typed_text_as_the_count_does(tab, site):
    tab.open()
    p = tab.page
    select(p, at(P1, "apples"), at(P1, "apples", None))
    p.fill(FIELD, "Why apples?")
    p.keyboard.press("Escape")
    until(lambda: p.locator("#rd-unsent").count() == 1, what="the not-sent line")
    select(p, at(P2, "pears"), at(P2, "pears", None))
    p.fill(FIELD, "And pears?")
    p.click("#rd-unsent")
    until(lambda: p.locator("#rd-popover[data-unsent]").count() == 1, what="the list")
    until(lambda: p.inner_text("#rd-unsent") == "2 messages not sent · Show", what="the count")
    assert p.locator("#rd-popover[data-unsent] .rd-form").count() == 2, "the list does not match the count"
    assert "pears" in p.inner_text("#rd-popover[data-unsent]")


def test_the_not_sent_list_without_an_open_box_lists_what_was_kept(tab, site):
    tab.open()
    p = tab.page
    select(p, at(P1, "apples"), at(P1, "apples", None))
    p.fill(FIELD, "Why apples?")
    p.keyboard.press("Escape")
    until(lambda: p.locator("#rd-unsent").count() == 1, what="the not-sent line")
    p.click("#rd-unsent")
    until(lambda: p.locator("#rd-popover[data-unsent] .rd-form").count() == 1, what="the list")


def stored_drafts(page):
    return page.evaluate("Object.values(localStorage).map(v => { try { return JSON.parse(v); } catch (e) { return null; } }).flat().filter(x => x && x.min)")


def test_a_message_kept_by_a_close_that_was_then_aborted_is_removed_when_its_field_is_emptied(tab, site):
    tab.open()
    p = tab.page
    select(p, at(P1, "apples"), at(P1, "apples", None))
    p.fill(FIELD, "first words")
    # What closePopover does to every form before it closes; another form's refusal would leave this box open.
    p.evaluate("document.querySelector('#rd-popover .rd-form').stash()")
    p.fill(FIELD, "first words, more")
    p.evaluate("document.querySelector('#rd-popover .rd-form').stash()")
    assert [d["body"] for d in stored_drafts(p)] == ["first words, more"], "a second stash of the same form made a second draft"
    p.fill(FIELD, "")
    p.keyboard.press("Escape")
    until(lambda: p.locator("#rd-unsent").count() == 0, what="the not-sent line gone")
    assert stored_drafts(p) == [], "the emptied draft stayed in the store"
