"""The action buttons at the top of a rectoverso's page (SPEC 10.11, #111): the page draws the boxes of the eight words
as the list's buttons, a one-off red with the 5 second Undo and locked once pressed; Share is a tick box (test_page_share_box.py). A press posts
the list's tick (`POST /_/tick`, 9.10): the markdown on disk is what a tick writes, `- [x] <word>`."""
import re

import pytest

from pagehelp import settled, open_box, DOC, at, comment_on, draft_key, key, mark, reloaded, select, toast, toasted, toasts_to_the_end, type_at_end, until, rewrite

pytestmark = pytest.mark.page

SHEAF = """# Plan

## Actions

- [ ] Approve
- [ ] Done
- [ ] Share

Body paragraph.
"""
LONG = "klium_website_relaunch_international_2026_phase_two"     # one word wider than a 360 px phone


@pytest.fixture
def sheaf(tab):
    """The tab on a page whose file holds three actions, on a clock of Playwright's."""
    rewrite(tab.site.file, SHEAF)
    tab.page.clock.install()
    tab.open()
    tab.page.wait_for_selector("button.rd-act")
    return tab


class Buttons:
    """The page's action buttons in the order of the file: a one-off sits at its box in the document, a toggle in the
    row above it, so the DOM order is not the file's; each button says its place (`data-i`)."""
    def __init__(self, page):
        self.page = page

    def nth(self, k):
        return self.page.locator(f'button.rd-act[data-i="{k}"]')

    def count(self):
        return self.page.locator("button.rd-act").count()

    def all_inner_texts(self):
        return self.page.evaluate("[...document.querySelectorAll('button.rd-act')]"
                                  ".sort((a, b) => a.dataset.i - b.dataset.i).map(b => b.innerText)")


def bar(page):
    return Buttons(page)


HEARD = """(() => {
  const ES = window.EventSource;
  window.__heard = {};
  window.EventSource = class extends ES {
    constructor(...a) {
      super(...a);
      for (const k of ['changed', 'hello']) this.addEventListener(k, () => { window.__heard[k] = (window.__heard[k] || 0) + 1; });
    }
  };
})()"""


def heard(page, event):
    """How many `event`s the page's stream has brought; the page's own listener has run on each."""
    return page.evaluate(f"window.__heard[{event!r}] || 0")


def stand_still(page):
    """The installed clock runs at the real pace: from now on it moves only when the test runs it. Called before a
    press, so the half second it jumps is not the Undo's. A page that read the clock past that time meanwhile makes
    `pause_at` refuse ("fast-forward to the past"): the time is read again."""
    for _ in range(5):
        try:
            page.clock.pause_at((page.evaluate("Date.now()") + 500) / 1000)       # seconds, in Playwright's Python
            return
        except Exception as e:
            if "past" not in str(e):
                raise
    raise AssertionError("the page clock would not pause")


def test_the_page_draws_a_one_off_where_its_box_is_and_share_as_a_tick_box_with_no_row_above_the_document(sheaf):
    p = sheaf.page
    assert bar(p).all_inner_texts() == ["Approve", "Done"]
    assert [bar(p).nth(k).get_attribute("class") for k in range(2)] == [
        "rd-act one-off rd-inline", "rd-act one-off rd-inline"]
    # The one-offs are in the document, each next to its own hidden box; Share's box is shown, and there is no row
    # (action-buttons 03: Share is a tick box, see test_page_share_box.py).
    assert p.locator("main button.rd-inline").count() == 2
    assert p.locator("main input[type=checkbox]:has(+ button.rd-inline)").evaluate_all(
        "bs => bs.map(b => getComputedStyle(b).display)") == ["none", "none"]
    assert p.locator("main li:has-text('Share') input[type=checkbox]").is_visible()
    assert p.locator("#rd-actions").count() == 0


def test_a_page_with_no_toggle_has_no_row_above_the_document(tab):
    rewrite(tab.site.file, "# Plan\n\n- [ ] Approve\n")
    tab.open()
    tab.page.wait_for_selector("button.rd-act")
    assert tab.page.locator("#rd-actions").count() == 0


def test_two_lines_of_the_same_word_are_two_buttons_and_each_presses_its_own_box(tab):
    f = tab.site.file
    rewrite(f, "# Plan\n\n- [ ] Approve\n- [ ] Approve\n")
    tab.page.clock.install()
    tab.open()
    p = tab.page
    p.wait_for_selector("button.rd-act")
    assert bar(p).count() == 2
    stand_still(p)
    bar(p).nth(1).click()
    p.clock.run_for(5100)
    until(lambda: f.read_text(encoding="utf-8") == "# Plan\n\n- [ ] Approve\n- [x] Approve\n", what="the second tick")
    settled(p)


def test_a_line_that_still_says_move_to_has_its_word_under_the_belongs_to_button(tab):
    rewrite(tab.site.file, "# Plan\n\n- [ ] Move to klium-website (ref 18f3a9c2)\n")
    tab.open()
    p = tab.page
    p.wait_for_selector("button.rd-act")
    assert p.locator("main li").first.evaluate("li => li.innerText.replace(/\\s+/g, ' ').trim()").count("klium-website") == 1


def test_a_selection_on_a_buttons_line_does_not_press_it_and_the_button_is_not_part_of_the_text(tab):
    f = tab.site.file
    rewrite(f, "# Plan\n\n- [ ] Belongs to klium-website (ref 18f3a9c2)\n")
    tab.open()
    p = tab.page
    p.wait_for_selector("button.rd-act")
    select(p, at("main", "(ref"), at("main", "18f3a9c2", None))
    open_box(p)
    assert "- [ ] Belongs to" in f.read_text(encoding="utf-8")
    # The line's own words are under the button, not said twice.
    assert p.locator("main li").first.evaluate("li => li.innerText.replace(/\\s+/g, ' ').trim()").count("klium-website") == 1


def test_a_press_shows_undo_for_five_seconds_then_ticks_the_file_and_the_page_shows_it_locked(sheaf):
    p, f = sheaf.page, sheaf.site.file
    bar(p).nth(0).click()
    assert bar(p).nth(0).inner_text() == "Undo"
    assert bar(p).nth(1).is_disabled()
    p.clock.run_for(4900)
    assert "- [ ] Approve" in f.read_text(encoding="utf-8")
    p.clock.run_for(200)
    until(lambda: "- [x] Approve" in f.read_text(encoding="utf-8"), what="the tick in the file")
    assert f.read_text(encoding="utf-8") == SHEAF.replace("- [ ] Approve", "- [x] Approve")
    until(lambda: p.locator("button.rd-act.one-off.pressed").count() == 1, what="the reload with Approve locked")
    locked = p.locator("button.rd-act.one-off.pressed")
    assert locked.inner_text().startswith("Approve ✓") and locked.is_disabled()


def test_undo_in_the_five_seconds_sends_nothing(sheaf):
    p, f = sheaf.page, sheaf.site.file
    bar(p).nth(0).click()
    p.clock.run_for(3000)
    bar(p).nth(0).click()
    assert bar(p).nth(0).inner_text() == "Approve" and bar(p).nth(1).is_enabled()
    p.clock.run_for(10_000)
    p.wait_for_timeout(300)
    assert f.read_text(encoding="utf-8") == SHEAF


def test_a_click_on_an_action_box_in_the_document_ticks_nothing_and_says_where_its_button_is(sheaf):
    p, f = sheaf.page, sheaf.site.file
    p.locator("main input[type=checkbox]").first.dispatch_event("click")      # hidden behind its button
    toasted(p, "with its button", on_clock=True)
    p.wait_for_timeout(300)
    assert f.read_text(encoding="utf-8") == SHEAF
    assert p.locator("main input[type=checkbox]").first.is_checked() is False


def test_an_action_typed_in_the_document_gets_its_button_once_the_save_is_answered(sheaf):
    p, f = sheaf.page, sheaf.site.file
    type_at_end(p, "main li:has-text('Share')", "")
    p.keyboard.press("Enter")
    p.keyboard.type("Run it")
    p.clock.run_for(3000)
    until(lambda: "- [ ] Run it" in f.read_text(encoding="utf-8"), what="the saved action")
    until(lambda: bar(p).all_inner_texts() == ["Approve", "Done", "Run it"], what="its button")
    bar(p).nth(3).click()
    p.clock.run_for(5100)
    until(lambda: "- [x] Run it" in f.read_text(encoding="utf-8"), what="the tick of the new action")
    settled(p)


def test_a_refused_press_is_said_and_gives_the_button_back(sheaf):
    p, f = sheaf.page, sheaf.site.file
    p.route("**/_/tick", lambda route: route.fulfill(status=409, content_type="application/json",
                                                       body='{"ok": false, "error": "Approve: refused here."}'))
    bar(p).nth(0).click()
    p.clock.run_for(5100)
    toasted(p, "refused here", on_clock=True)
    assert bar(p).nth(0).inner_text() == "Approve" and bar(p).nth(0).is_enabled()
    assert "- [ ] Approve" in f.read_text(encoding="utf-8")


def test_a_change_from_outside_during_a_press_waits_for_its_answer_before_the_page_reloads(sheaf):
    p, f = sheaf.page, sheaf.site.file
    mark(p)
    bar(p).nth(0).click()
    rewrite(f, SHEAF.replace("Body paragraph.", "Body paragraph, changed."))
    p.wait_for_timeout(1500)
    assert p.evaluate("window.__same_load") is True, "the page reloaded under the press"
    assert bar(p).nth(0).inner_text() == "Undo"
    p.clock.run_for(5100)
    # The press names the text the page held: the hub refuses it, and the page says so before it reloads.
    toasted(p, "reload the page", on_clock=True)
    reloaded(p)
    assert "- [ ] Approve" in f.read_text(encoding="utf-8")


def test_a_press_whose_actions_a_save_changed_meanwhile_is_not_sent(sheaf):
    p, f = sheaf.page, sheaf.site.file
    bar(p).nth(1).click()                               # Done
    type_at_end(p, "main li:has-text('Approve')", "")
    p.keyboard.press("Enter")
    p.keyboard.type("Done")
    p.clock.run_for(3000)
    until(lambda: "- [ ] Approve\n- [ ] Done\n- [ ] Done" in f.read_text(encoding="utf-8"), what="the saved action")
    p.clock.run_for(2100)
    toasted(p, "Press it again.", on_clock=True)
    assert "[x]" not in f.read_text(encoding="utf-8")
    until(lambda: bar(p).all_inner_texts() == ["Approve", "Done", "Done"], what="the new buttons")


def test_share_is_ticked_and_unticked_on_the_page_by_its_box(sheaf):
    p, f = sheaf.page, sheaf.site.file
    box = p.locator("main li:has-text('Share') input[type=checkbox]")
    box.click()
    until(lambda: "- [x] Share" in f.read_text(encoding="utf-8"), what="the Share tick")
    until(lambda: box.is_checked(), what="Share ticked on the page")
    box.click()
    until(lambda: "- [ ] Share" in f.read_text(encoding="utf-8"), what="the release")
    until(lambda: not box.is_checked(), what="Share unticked on the page")


def test_a_replys_answer_that_reloads_the_page_waits_for_a_press_in_its_undo(tab):
    p, f = tab.page, tab.site.file
    rewrite(f, SHEAF)
    tab.open()
    body = "main"
    comment_on(tab, at(body, "Body"), at(body, "Body", None), "Why?")
    p.clock.install()
    p.reload()
    p.wait_for_selector("button.rd-act")
    p.click(".rd-badge")
    p.wait_for_selector("#rd-popover textarea")
    p.fill("#rd-popover textarea", "my reply")
    rewrite(f, f.read_text(encoding="utf-8") + "\nFrom outside.\n")
    p.wait_for_selector("#rd-popover .rd-hold")         # the form holds the reload
    mark(p)
    bar(p).nth(0).click()
    p.click("#rd-popover button[data-f=ok]")            # its answer would run the held reload
    until(lambda: "my reply" in f.read_text(encoding="utf-8"), what="the reply in the file")
    p.wait_for_timeout(1500)
    assert p.evaluate("window.__same_load") is True, "the page reloaded under the press"
    p.clock.run_for(5100)
    # The press names the text before the outside change: refused, and said on the page the reload brings.
    reloaded(p)
    toasted(p, "reload the page", on_clock=True)


def test_a_refusal_queued_behind_a_red_toast_is_said_again_when_a_form_held_the_reload_past_7_seconds(tab):
    # Ticket 62 (round 2): toasts queue, so a refusal's 7 s were counted from when it was said, not from when it was shown.
    # A form held the reload for more than 7 s after the refusal, the refusal had been on screen for less than its
    # time (or not at all, behind several red toasts), and the page it brought did not say it again.
    p, f = tab.page, tab.site.file
    rewrite(f, SHEAF)
    tab.open()
    body = "main"
    comment_on(tab, at(body, "Body"), at(body, "Body", None), "Why?")
    p.clock.install()
    p.add_init_script(HEARD)
    p.reload()
    p.wait_for_selector("button.rd-act")
    stand_still(p)                                      # from now on the clock moves only when the test runs it
    p.route("**/_/tick", lambda r: r.abort())
    bar(p).nth(0).click()
    p.clock.run_for(5100)
    until(lambda: toast(p) != "", what="a red toast, up for 7 s")
    p.unroute("**/_/tick")
    p.click(".rd-badge")
    p.wait_for_selector("#rd-popover textarea")
    p.fill("#rd-popover textarea", "my reply")
    mark(p)
    bar(p).nth(0).click()                               # the press, in its Undo
    rewrite(f, f.read_text(encoding="utf-8") + "\nFrom outside.\n")
    until(lambda: heard(p, "changed"), what="the change, whose reload waits for the press")    # the clock is still
    p.clock.run_for(100)
    p.clock.run_for(5000)                               # the press is refused at 10.2 s: its toast waits behind the red one (to 12 s)
    p.clock.run_for(7500)                               # 17.7 s: more than 7 s after the refusal was said, and it is up till 19 s
    assert p.evaluate("window.__same_load") is True, "the page reloaded under the form"
    p.click("#rd-popover button[data-f=ok]")            # the reply goes, and the held reload runs
    until(lambda: "my reply" in f.read_text(encoding="utf-8"), what="the reply in the file")
    reloaded(p)
    toasted(p, "reload the page", on_clock=True)        # the page's own toast of the change first, then the refusal again


def refused(text):
    return '{"ok": false, "error": "%s"}' % text


def held_by_a_form(tab, answers):
    """A page on the clock of the test, with the form of a reply open, Approve pressed (in its Undo) and an outside
    change heard: its reload waits for the press, then for the form. The clock stands still; the reply is sent by
    `p.click("#rd-popover button[data-f=ok]")`. Call `p.route("**/_/tick", ...)` before running the clock."""
    p, f = tab.page, tab.site.file
    rewrite(f, SHEAF)
    tab.open()
    comment_on(tab, at("main", "Body"), at("main", "Body", None), "Why?")
    p.clock.install()
    p.add_init_script(HEARD)
    p.reload()
    p.wait_for_selector("button.rd-act")
    stand_still(p)
    p.click(".rd-badge")
    p.wait_for_selector("#rd-popover textarea")
    p.fill("#rd-popover textarea", "my reply")
    mark(p)
    p.route("**/_/tick", lambda r: r.fulfill(status=409, content_type="application/json", body=answers.pop(0)))
    bar(p).nth(0).click()
    rewrite(f, f.read_text(encoding="utf-8") + "\nFrom outside.\n")
    until(lambda: heard(p, "changed"), what="the change, whose reload waits for the press")
    return p


def test_the_refusal_a_form_held_reload_says_again_is_the_latest_press_not_an_earlier_one(tab):
    # Ticket 80: `pressSaid` was never reset, so refusal A was said again on the page the reload brought, and refusal B,
    # made later while the form still held the reload, was lost with the page.
    answers = [refused("Approve: refused A, reload the page"), refused("Done: refused B, reload the page")]
    p = held_by_a_form(tab, answers)
    p.clock.run_for(5100)
    until(lambda: "refused A" in toast(p), what="the first refusal")
    p.clock.run_for(7000)
    bar(p).nth(1).click()
    p.clock.run_for(5100)
    until(lambda: "refused B" in toast(p), what="the second refusal")
    assert p.evaluate("window.__same_load") is True, "the page reloaded under the form"
    p.click("#rd-popover button[data-f=ok]")
    reloaded(p)
    for _ in range(4):
        if "refused" in toast(p):
            break
        p.clock.run_for(3000)
    assert "refused B" in toast(p), toast(p)


def test_an_earlier_refusal_still_up_is_not_said_again_by_the_reload_of_a_later_press_that_succeeded(tab):
    # Ticket 101 (4): A is refused and still up when B is pressed and taken; the reload then runs inside A's 7 s.
    # The reset in `send()` is what keeps A from coming back: without it the reload carries A.
    answers = [refused("Approve: refused A, reload the page")]
    p = held_by_a_form(tab, answers)
    p.clock.run_for(5100)
    until(lambda: "refused A" in toast(p), what="the first refusal")
    p.unroute("**/_/tick")
    p.route("**/_/tick", lambda r: r.fulfill(status=200, content_type="application/json", body='{"ok": true}'))
    bar(p).nth(1).click()
    p.clock.run_for(5100)                               # B is sent and taken (its tick is faked, so no `changed`); A has been up for 5.1 s of its 7
    p.click("#rd-popover button[data-f=ok]")                # the outside change's held reload runs, inside A's 7 s
    reloaded(p)
    assert "refused A" not in " ".join(toasts_to_the_end(p, on_clock=True))


def test_a_refusal_said_again_on_the_new_page_is_said_again_on_a_second_reload_that_comes_quickly(tab):
    # Ticket 80: the new page's `pressSaid` was null, so a second reload within the 7 s dropped the refusal.
    f = tab.site.file
    p = held_by_a_form(tab, [refused("Approve: refused A, reload the page")])
    p.clock.run_for(5100)
    until(lambda: "refused A" in toast(p), what="the refusal")
    p.click("#rd-popover button[data-f=ok]")
    reloaded(p)
    toasted(p, "refused A", on_clock=True)
    mark(p)
    rewrite(f, f.read_text(encoding="utf-8") + "\nFrom outside, again.\n")
    reloaded(p)
    toasted(p, "refused A", on_clock=True)


def test_a_refusal_is_not_said_again_past_the_seven_seconds_it_was_said_in_however_often_the_page_reloads(tab):
    # Ticket 101 (2): the replayed toast keeps the refusal's own deadline, so reloads do not chain it on.
    f = tab.site.file
    p = held_by_a_form(tab, [refused("Approve: refused A, reload the page")])
    p.clock.run_for(5100)
    until(lambda: "refused A" in toast(p), what="the refusal")
    p.click("#rd-popover button[data-f=ok]")
    reloaded(p)
    toasted(p, "refused A", on_clock=True)
    p.clock.run_for(5000)                               # past the refusal's own 7 s, short of a fresh 7 s from the replay
    for n in range(2):
        mark(p)
        rewrite(f, f.read_text(encoding="utf-8") + "\nFrom outside, %d.\n" % n)
        reloaded(p)
        assert "refused A" not in " ".join(toasts_to_the_end(p, on_clock=True))


def test_a_refusal_said_again_by_a_reload_posts_no_second_incident(tab):
    # Ticket 143 (SPEC 10.11; left by ticket 101, point 2): every `say(text, true)` posts a `toast` incident to /_/diag, and the replay of a refusal
    # on the page a reload brings was one: a second row for a refusal already written down. The first is still one.
    p = held_by_a_form(tab, [refused("Approve: refused A, reload the page")])
    rows = []
    p.on("request", lambda r: rows.append(r.post_data_json) if r.url.endswith("/_/diag") and r.post_data_json["kind"] == "toast" else None)
    p.clock.run_for(5100)
    until(lambda: "refused A" in toast(p), what="the refusal")
    assert len(rows) == 1 and "refused A" in rows[0]["message"], rows       # the first is posted: say() posts before it shows
    p.click("#rd-popover button[data-f=ok]")
    reloaded(p)
    toasted(p, "refused A", on_clock=True)                       # the replay is said; its incident, if any, was posted first
    p.evaluate("0")                                              # events reach the test in order: the request, if there was one, has come
    assert len(rows) == 1, rows


def test_a_refusal_brought_back_by_a_reload_at_5_s_is_not_carried_by_a_second_reload_at_8_s(tab):
    # Ticket 118 (SPEC 10.11): said at 0 s it is up to 7 s; the reload at 5 s brings it back, but with its own deadline,
    # so the reload at 8 s, while the replay is on screen (up to 14.6 s), keeps nothing. The clock is read, not counted:
    # the toasts the page waits for run it on, and the reloads are at 5 s and 8 s from the refusal, not from later.
    f = tab.site.file
    p = held_by_a_form(tab, [refused("Approve: refused A, reload the page")])
    p.clock.run_for(5100)
    until(lambda: "refused A" in toast(p), what="the refusal, at 0 s")
    said_at = p.evaluate("Date.now()")
    p.clock.run_for(5000 - (p.evaluate("Date.now()") - said_at))
    p.click("#rd-popover button[data-f=ok]")           # the reload at 5 s
    reloaded(p)
    p.wait_for_selector("button.rd-act")                # the boot has said what it says
    p.clock.run_for(8000 - (p.evaluate("Date.now()") - said_at))
    assert "refused A" in toast(p)                      # the replay is on screen at 8 s: the limit is the reload's, not the toast's
    mark(p)
    rewrite(f, f.read_text(encoding="utf-8") + "\nFrom outside, at 8 s.\n")
    reloaded(p)
    p.wait_for_selector("button.rd-act")
    assert "refused A" not in " ".join(toasts_to_the_end(p, on_clock=True))


def test_a_refusal_an_older_page_left_as_plain_text_does_not_stop_the_boot(sheaf):
    # Ticket 101, review a: before this ticket the key held the bare text. The page of a deploy reads it without
    # throwing, drops it, and the rest of the boot (the toast the reload left) still runs.
    p = sheaf.page
    # A valid keep for this document: without one the page drops any refusal for lack of a reload, so the last assertion could not fail.
    p.evaluate("([doc]) => { sessionStorage.setItem('rd-keep', JSON.stringify({ doc: doc, y: 0 })); sessionStorage.setItem('rd-press-said', 'Approve: refused, reload the page'); sessionStorage.setItem('rd-toast', 'Kept by the reload.') }", [DOC])
    p.reload()
    toasted(p, "Kept by the reload.")      # said only when the keep names this document: it was read
    assert p.evaluate("sessionStorage.getItem('rd-press-said')") is None
    assert "refused, reload" not in " ".join(toasts_to_the_end(p))


def test_a_keep_that_is_not_json_does_not_stop_the_boot(sheaf):
    # Ticket 112 (c): `rd-keep` was parsed before the keys were removed, so a value that is not JSON broke every load of the tab.
    p = sheaf.page
    p.evaluate("sessionStorage.setItem('rd-keep', 'not json'); sessionStorage.setItem('rd-toast', 'Kept by the reload.')")
    p.reload()
    toasted(p, "Kept by the reload.")
    assert p.evaluate("sessionStorage.getItem('rd-keep')") is None


def test_a_press_while_the_page_settles_onto_a_change_is_refused_and_the_page_reloads(sheaf):
    p, f = sheaf.page, sheaf.site.file
    held = []
    p.route("**/_/save", lambda r: held.append(r))
    type_at_end(p, "main p:has-text('Body')", " typed")
    rewrite(f, SHEAF.replace("# Plan", "# Plan, outside"))
    until(lambda: held or p.wait_for_timeout(20), what="the settle's save, held")
    mark(p)
    bar(p).nth(0).click()
    # The page is about to reload onto the change: the press is refused, never left to wait for a page that goes.
    assert bar(p).nth(0).inner_text() == "Approve"
    assert "reloading" in toast(p)
    held[0].continue_()
    p.unroute("**/_/save")
    reloaded(p)
    p.wait_for_selector("button.rd-act")
    bar(p).nth(0).click()
    p.clock.run_for(5100)
    until(lambda: "- [x] Approve" in f.read_text(encoding="utf-8"), what="the press on the reloaded page")
    settled(p)
    assert "# Plan, outside" in f.read_text(encoding="utf-8") and " typed" in f.read_text(encoding="utf-8")


def test_on_a_phone_the_buttons_wrap_44_px_high_and_the_page_never_scrolls_sideways(touch_tab):
    p = touch_tab.page
    rewrite(touch_tab.site.file, SHEAF.replace("- [ ] Share\n", "- [ ] Share\n- [ ] Stop James\n"
                                                 "- [ ] Belongs to klium-website-relaunch (ref 18f3a9c2)\n"))
    p.set_viewport_size({"width": 360, "height": 780})
    touch_tab.open()
    p.wait_for_selector("button.rd-act")
    boxes = [b.bounding_box() for b in p.locator("button.rd-act").all()]
    assert len(boxes) == 4, "Share is a tick box, not a button"
    assert all(b["height"] >= 44 and b["width"] >= 44 for b in boxes), boxes
    assert all(b["x"] >= 0 and b["x"] + b["width"] <= 360 for b in boxes), boxes
    assert len({b["y"] for b in boxes}) == 4, "each button is on a line of its own"
    assert p.evaluate("document.documentElement.scrollWidth") <= 360


def test_on_a_phone_a_move_to_whose_slug_has_no_hyphen_breaks_inside_its_button_and_in_the_text(touch_tab):
    # The button breaks it (#112), and so does the document's own line of that box, the theme's (#128).
    p = touch_tab.page
    rewrite(touch_tab.site.file, SHEAF.replace(
        "- [ ] Share\n", f"- [ ] Share\n- [ ] Belongs to {LONG} (ref 18f3a9c2)\n"))
    p.set_viewport_size({"width": 360, "height": 780})
    touch_tab.open()
    p.wait_for_selector("button.rd-act")
    move = bar(p).nth(3).bounding_box()
    assert move["x"] >= 0 and move["x"] + move["width"] <= 360, move
    assert p.evaluate("document.documentElement.scrollWidth") <= 360
    menu = p.locator("#rd-menu-btn").bounding_box()
    assert menu["x"] >= 0 and menu["x"] + menu["width"] <= 360, menu


def test_on_a_phone_a_long_word_in_the_text_breaks_and_a_code_block_scrolls_inside_itself(touch_tab):
    # #128: the document's text breaks a word wider than the screen, inline code too, on screen and in print; a
    # table keeps its words and scrolls in its frame, a code block keeps its lines.
    p = touch_tab.page
    rewrite(touch_tab.site.file, f"# {LONG}\n\nThe slug {LONG} is long, and `{LONG}` is code.\n\n"
                                   f"| Slug |\n|---|\n| {LONG} |\n\n```\nmove {LONG} {LONG}\n```\n")
    p.set_viewport_size({"width": 360, "height": 780})
    touch_tab.open()
    assert p.evaluate("document.documentElement.scrollWidth") <= 360
    menu = p.locator("#rd-menu-btn").bounding_box()
    assert menu["x"] >= 0 and menu["x"] + menu["width"] <= 360, menu
    pre = p.locator("main pre")
    assert pre.evaluate("e => e.scrollWidth > e.clientWidth"), "the code block wrapped its line"
    frame = p.locator("main .tblwrap")
    assert frame.evaluate("e => e.scrollWidth > e.clientWidth"), "the table broke its word instead of scrolling"
    p.emulate_media(media="print")
    assert p.locator("main p").first.evaluate("e => getComputedStyle(e).overflowWrap") == "break-word"


# The four P3s #111's gate left (#127).

def test_an_autosave_due_while_a_press_is_out_waits_for_its_answer_and_the_press_ticks(sheaf):
    # #127, 1: the autosave reached the hub just before the tick, which then named a text gone by and was refused.
    p, f = sheaf.page, sheaf.site.file
    held = []
    p.route("**/_/tick", lambda r: held.append(r))
    stand_still(p)
    bar(p).nth(0).click()
    p.clock.run_for(3000)
    type_at_end(p, "main p:has-text('Body')", " typed")
    p.clock.run_for(2100)                               # the tick goes out at 5 s, held
    until(lambda: held or p.wait_for_timeout(20), what="the tick, held")
    p.clock.run_for(1000)                               # the autosave is due at 5.5 s
    p.wait_for_timeout(500)
    assert f.read_text(encoding="utf-8") == SHEAF, "the autosave went while the tick was out"
    held[0].continue_()
    p.unroute("**/_/tick")
    until(lambda: "- [x] Approve" in f.read_text(encoding="utf-8"), what="the tick")
    until(lambda: " typed" in f.read_text(encoding="utf-8"), what="the autosave after it")


def test_every_reload_asked_during_a_press_counts_and_the_settle_still_saves_the_edits(sheaf, site):
    # #127, 2: an upgrade's reload replaced the waiting reload of an outside change, and the settle's save was lost.
    p, f = sheaf.page, sheaf.site.file
    p.add_init_script(HEARD)
    p.reload()
    p.wait_for_selector("button.rd-act")
    mark(p)
    stand_still(p)
    bar(p).nth(0).click()
    rewrite(f, SHEAF.replace("# Plan", "# Plan, outside"))
    until(lambda: heard(p, "changed"), what="the change, whose reload waits for the press")
    p.route("**/_/doc?*", lambda r: r.abort())          # the hello's look at the text finds nothing to add
    site.hub.entry(DOC).bus.publish("hello", {"version": "99.0.0"})
    until(lambda: heard(p, "hello"), what="the upgrade, whose reload waits too")
    p.clock.run_for(4000)
    type_at_end(p, "main p:has-text('Body')", " typed")
    until(lambda: "typed" in p.inner_text("main p:has-text('Body')"), what="the edit on screen")
    p.clock.run_for(1100)                               # the press names the text before the change: refused;
    # the edit's autosave is not due yet
    until(lambda: " typed" in f.read_text(encoding="utf-8"), what="the settle's save of the edit")
    assert "# Plan, outside" in f.read_text(encoding="utf-8")
    reloaded(p)


def test_a_box_of_an_action_typed_and_not_yet_saved_is_not_ticked_by_a_click(sheaf):
    # #127, 3: the box was no button's yet, so a click ticked it through a save.
    p, f = sheaf.page, sheaf.site.file
    type_at_end(p, "main li:has-text('Share')", "")
    p.keyboard.press("Enter")
    p.keyboard.type("Run it")
    p.locator("main li:has-text('Run it') input[type=checkbox]").dispatch_event("click")
    toasted(p, "with its button", on_clock=True)
    until(lambda: "- [ ] Run it" in f.read_text(encoding="utf-8"), what="the saved action")
    until(lambda: bar(p).all_inner_texts() == ["Approve", "Done", "Run it"], what="its button")
    assert "[x]" not in f.read_text(encoding="utf-8")
    assert p.locator("main li:has-text('Run it') input[type=checkbox]").is_checked() is False


def test_a_sign_out_during_a_press_does_not_reload_under_it(sheaf, site):
    # #127, 4: the page reloaded at once and the press was dropped without a line.
    p, f = sheaf.page, sheaf.site.file
    mark(p)
    stand_still(p)
    bar(p).nth(0).click()
    site.hub.entry(DOC).bus.publish("signed-out", {})
    until(lambda: "signed out" in p.inner_text("#rd-notice"), what="the signed-out notice")
    assert p.evaluate("window.__same_load") is True, "the page reloaded under the press"
    assert bar(p).nth(0).inner_text() == "Undo"
    p.clock.run_for(5100)
    until(lambda: "- [x] Approve" in f.read_text(encoding="utf-8"), what="the press, sent")


def test_a_box_typed_in_a_block_whose_save_is_merged_is_not_ticked_before_the_reload(sheaf):
    # #127, 3, gate on 793824c: a merged save brings no actions, so the box may be an action's; it waits for the page
    # the merge's reload brings.
    p, f = sheaf.page, sheaf.site.file
    def merged(route):
        r = route.fetch()
        j = r.json()
        j["merged"] = True
        route.fulfill(response=r, json=j)
    p.route("**/_/save", merged, times=1)
    type_at_end(p, "main li:has-text('Share')", "")
    p.keyboard.press("Enter")
    p.keyboard.type("Run it")
    mark(p)
    p.locator("main li:has-text('Run it') input[type=checkbox]").dispatch_event("click")
    reloaded(p)
    until(lambda: bar(p).all_inner_texts() == ["Approve", "Done", "Run it"], what="its button")
    p.wait_for_timeout(500)
    assert "- [ ] Run it" in f.read_text(encoding="utf-8") and "[x]" not in f.read_text(encoding="utf-8")


PLAIN = SHEAF + "\n- [ ] plain task\n"


def test_a_plain_box_clicked_in_an_edited_block_while_the_hub_is_away_still_ticks(tab, site):
    # #127, 3, gate on 793824c: its save first could not reach the hub, and the click was dropped without a line.
    p, f = tab.page, site.file
    rewrite(f, PLAIN)
    tab.open()
    p.wait_for_selector("button.rd-act")
    type_at_end(p, "main li:has-text('plain task')", " now")
    site.kill()
    p.locator("main li:has-text('plain task') input[type=checkbox]").click()
    until(lambda: p.locator("main li:has-text('plain task') input[type=checkbox]").get_attribute("checked") is not None,
          what="the tick on screen")
    site.reopen()
    until(lambda: "- [x] plain task now" in f.read_text(encoding="utf-8"), timeout=20, what="the owed save")


def test_a_sign_out_while_a_press_is_out_does_not_reload_under_its_answer(sheaf, site):
    # #127, 4, gate on 793824c: the sign-out waited for the tick's answer, then reloaded over its refusal.
    p, f = sheaf.page, sheaf.site.file
    held = []
    p.route("**/_/tick", lambda r: held.append(r))
    mark(p)
    stand_still(p)
    bar(p).nth(0).click()
    p.clock.run_for(5100)
    until(lambda: held or p.wait_for_timeout(20), what="the tick, held")
    site.hub.entry(DOC).bus.publish("signed-out", {})
    until(lambda: "signed out" in p.inner_text("#rd-notice"), what="the signed-out notice")
    held[0].fulfill(status=401, content_type="application/json", body='{"ok": false, "error": "Not signed in."}')
    toasted(p, "Not signed in.", on_clock=True)
    p.wait_for_timeout(500)
    assert p.evaluate("window.__same_load") is True, "the page reloaded over the refusal"
    assert "- [ ] Approve" in f.read_text(encoding="utf-8")


# The P3s #144's gates left (#148).

REFUSED = '{"ok": false, "error": "the rectoverso changed since the page read it (Approve): reload the page"}'


def test_an_upgrade_while_a_press_is_out_says_its_refusal_again_on_the_page_it_brings(sheaf, site):
    # #148, 1: the upgrade waited for the tick through the page's writes, not for the press, and reloaded without it.
    p = sheaf.page
    p.add_init_script(HEARD)
    p.reload()
    p.wait_for_selector("button.rd-act")
    held = []
    p.route("**/_/tick", lambda r: held.append(r))
    stand_still(p)
    bar(p).nth(0).click()
    p.clock.run_for(5100)
    until(lambda: held or p.wait_for_timeout(20), what="the tick, held")
    p.route("**/_/doc?*", lambda r: r.abort())          # the hello's look at the text finds nothing to add
    mark(p)
    site.hub.entry(DOC).bus.publish("hello", {"version": "99.0.0"})
    until(lambda: heard(p, "hello"), what="the upgrade")
    held[0].fulfill(status=409, content_type="application/json", body=REFUSED)
    p.wait_for_timeout(200)
    p.clock.run_for(100)                                # the wait for the page's writes ends after 50 ms
    reloaded(p)
    p.wait_for_selector("button.rd-act")
    toasted(p, "the rectoverso changed", on_clock=True)


def test_a_reload_asked_only_by_an_upgrade_saves_what_was_typed_during_the_press(sheaf, site):
    # #148, 2: the upgrade's reload went straight to location.reload once the press was done.
    p, f = sheaf.page, sheaf.site.file
    p.add_init_script(HEARD)
    p.reload()
    p.wait_for_selector("button.rd-act")
    p.route("**/_/tick", lambda r: r.fulfill(status=409, content_type="application/json", body=REFUSED))
    p.route("**/_/doc?*", lambda r: r.abort())
    stand_still(p)
    bar(p).nth(0).click()
    site.hub.entry(DOC).bus.publish("hello", {"version": "99.0.0"})
    until(lambda: heard(p, "hello"), what="the upgrade, whose reload waits for the press")
    p.clock.run_for(4000)
    type_at_end(p, "main p:has-text('Body')", " typed")
    until(lambda: "typed" in p.inner_text("main p:has-text('Body')"), what="the edit on screen")
    mark(p)
    p.clock.run_for(1100)                               # the press is refused; the edit's autosave is not due yet
    until(lambda: " typed" in f.read_text(encoding="utf-8"), what="the edit, saved before the reload")
    reloaded(p)                                         # the reload is the end of the test: closing the context under it hung the driver (flake e2)
    p.wait_for_selector("#rd-menu-btn", state="attached")


def merged_once(p, key):
    """The first save that sends "Run it" is answered as `key` says, besides what the hub answers."""
    done = []
    def answer(route):
        if done or "Run it" not in (route.request.post_data or ""):
            route.continue_()
            return
        done.append(1)
        r = route.fetch()
        j = r.json()
        j[key] = True
        route.fulfill(response=r, json=j)
    p.route("**/_/save", answer)


def test_a_saved_action_box_is_not_ticked_while_a_press_holds_the_reload_of_its_merged_save(sheaf):
    # #148, 3: the box's block was clean, so no save looked at it, and the box ticked through the next save.
    p, f = sheaf.page, sheaf.site.file
    merged_once(p, "merged")
    stand_still(p)
    type_at_end(p, "main li:has-text('Share')", "")
    p.keyboard.press("Enter")
    p.keyboard.type("Run it")
    bar(p).nth(0).click()
    p.clock.run_for(3000)                               # the autosave goes, merged: its reload waits for the press
    until(lambda: "- [ ] Run it" in f.read_text(encoding="utf-8"), what="the saved action")
    until(lambda: p.evaluate("document.querySelector('#rd-state').textContent") != "Saving…", what="its answer")
    p.locator("main li:has-text('Run it') input[type=checkbox]").dispatch_event("click")
    toasted(p, "tick it once it has", on_clock=True)
    p.wait_for_timeout(500)
    assert "[x] Run it" not in f.read_text(encoding="utf-8")
    bar(p).nth(0).click()                               # Undo


DEAF = """(() => {
  const ES = window.EventSource;
  window.__deaf = false;
  window.EventSource = class extends ES {
    addEventListener(k, f, o) {
      super.addEventListener(k, k === 'changed' ? (ev => { if (!window.__deaf) f(ev); }) : f, o);
    }
  };
})()"""


def test_a_saved_action_box_is_not_ticked_after_a_save_answered_again(sheaf):
    # #148, 3: an `again` answer keeps the hash of the text on screen and brings no buttons. It comes after a send
    # the page gave up on, whose `changed` it did not hear: the stream misses it here too.
    p, f = sheaf.page, sheaf.site.file
    p.add_init_script(DEAF)
    p.reload()
    p.wait_for_selector("button.rd-act")
    p.evaluate("window.__deaf = true")
    merged_once(p, "again")
    type_at_end(p, "main li:has-text('Share')", "")
    p.keyboard.press("Enter")
    p.keyboard.type("Run it")
    until(lambda: "- [ ] Run it" in f.read_text(encoding="utf-8"), what="the saved action")
    until(lambda: p.evaluate("document.querySelector('#rd-state').textContent") != "Saving…", what="its answer")
    mark(p)
    p.locator("main li:has-text('Run it') input[type=checkbox]").dispatch_event("click")
    reloaded(p)
    until(lambda: bar(p).all_inner_texts() == ["Approve", "Done", "Run it"], what="its button")
    p.wait_for_timeout(500)
    assert "[x] Run it" not in f.read_text(encoding="utf-8")


def test_a_comment_sent_while_the_tick_is_out_waits_for_its_answer(sheaf):
    # #148, 4: the comment reached the hub first and the tick, naming the text before it, was refused.
    p, f = sheaf.page, sheaf.site.file
    held = []
    p.route("**/_/tick", lambda r: held.append(r))
    select(p, at("main", "Body"), at("main", "Body", None))
    open_box(p)
    p.fill("#rd-popover textarea", "Why?")
    stand_still(p)
    bar(p).nth(0).click()
    p.clock.run_for(5100)
    until(lambda: held or p.wait_for_timeout(20), what="the tick, held")
    p.click("#rd-popover button[data-f=ok]")
    p.wait_for_timeout(500)
    held[0].continue_()
    p.unroute("**/_/tick")
    until(lambda: "- [x] Approve" in f.read_text(encoding="utf-8"), what="the tick")
    until(lambda: "Why?" in f.read_text(encoding="utf-8"), what="the comment after it")
    settled(p)


def test_a_comment_answered_during_the_undo_does_not_move_the_text_the_press_names(sheaf):
    # #148, 4: the comment's answer moved the page's hash and the press still named the text before it.
    # Ticket 54: the press sends only once the page has the comment's answer, and its wait for that is a timer of
    # the paused page clock. The file having the comment is the hub's doing; the clock runs when the page has the
    # answer too (the new badge), else the press's wait is stranded and the tick never goes (5d7df54 held the answer).
    p, f = sheaf.page, sheaf.site.file
    badges = p.locator("main .rd-badge")
    before = badges.count()
    select(p, at("main", "Body"), at("main", "Body", None))
    open_box(p)
    p.fill("#rd-popover textarea", "Why?")
    stand_still(p)
    bar(p).nth(0).click()
    p.click("#rd-popover button[data-f=ok]")
    until(lambda: "Why?" in f.read_text(encoding="utf-8"), what="the comment, in the file during the Undo")
    until(lambda: badges.count() > before, what="the answer, in the page")
    p.wait_for_timeout(300)
    p.clock.run_for(5100)
    until(lambda: "- [x] Approve" in f.read_text(encoding="utf-8"), what="the tick")
    settled(p)
    assert "Why?" in f.read_text(encoding="utf-8")


def test_a_box_clicked_twice_while_the_tick_is_out_says_saving_and_ticks_once(tab, site):
    # #148, 5: the wait said nothing, and the second click queued a toggle that undid the first.
    p, f = tab.page, site.file
    rewrite(f, PLAIN)
    p.clock.install()
    tab.open()
    p.wait_for_selector("button.rd-act")
    held = []
    p.route("**/_/tick", lambda r: held.append(r))
    stand_still(p)
    bar(p).nth(0).click()
    p.clock.run_for(3000)
    type_at_end(p, "main li:has-text('plain task')", " now")
    p.clock.run_for(2100)
    until(lambda: held or p.wait_for_timeout(20), what="the tick, held")
    box = p.locator("main li:has-text('plain task') input[type=checkbox]")
    box.click()
    box.click()
    until(lambda: p.evaluate("document.querySelector('#rd-state').textContent") == "Saving…", what="Saving…")
    mark(p)
    held[0].continue_()
    p.unroute("**/_/tick")
    until(lambda: "- [x] Approve" in f.read_text(encoding="utf-8"), what="the tick")
    until(lambda: "- [x] plain task now" in f.read_text(encoding="utf-8"), what="the box, ticked once")
    reloaded(p)
    p.wait_for_selector("main li:has-text('plain task')")
    p.wait_for_timeout(500)
    assert "- [x] plain task now" in f.read_text(encoding="utf-8")


def test_a_sign_out_during_a_press_with_nothing_typed_says_so_and_undo_goes_to_the_sign_in(sheaf, site):
    # #148, 6: the notice spoke of edits on screen, and after Undo the page stayed on it.
    p = sheaf.page
    mark(p)
    stand_still(p)
    bar(p).nth(0).click()
    site.hub.entry(DOC).bus.publish("signed-out", {})
    until(lambda: "signed out" in p.inner_text("#rd-notice"), what="the signed-out notice")
    assert "edits" not in p.inner_text("#rd-notice")
    bar(p).nth(0).click()                               # Undo
    reloaded(p)


def test_an_edit_in_the_pressed_actions_own_block_keeps_the_tick(sheaf):
    # #148, 7: the settle's save of the edit was merged against the ticked file and put the box back.
    p, f = sheaf.page, sheaf.site.file
    stand_still(p)
    bar(p).nth(0).click()
    p.clock.run_for(4000)
    type_at_end(p, "main li:has-text('Done')", " now")
    until(lambda: "now" in p.inner_text("main li:has-text('Done')"), what="the edit on screen")
    p.clock.run_for(1100)
    until(lambda: "Done now" in f.read_text(encoding="utf-8"), what="the edit, saved by the reload's settle")
    assert "- [x] Approve" in f.read_text(encoding="utf-8")


def test_a_box_whose_save_is_refused_does_not_tick_because_an_older_save_is_owed(tab, site):
    # #148, 9: tickBox read autosaveOwed, which an earlier save had left.
    p, f = tab.page, site.file
    rewrite(f, PLAIN)
    tab.open()
    p.wait_for_selector("button.rd-act")
    calls = []
    def save(route):
        calls.append(1)
        if len(calls) == 1:
            route.abort()
        else:
            route.fulfill(status=409, content_type="application/json", body='{"ok": false, "error": "refused"}')
    p.route("**/_/save", save)
    type_at_end(p, "main p:has-text('Body')", " typed")
    until(lambda: calls, timeout=10, what="the autosave, cut off: owed")
    p.click("main li:has-text('plain task')")
    p.keyboard.press(key("End"))
    p.keyboard.type(" now")
    p.locator("main li:has-text('plain task') input[type=checkbox]").click()
    until(lambda: len(calls) >= 2, what="its save, refused")
    p.wait_for_timeout(500)
    assert p.locator("main li:has-text('plain task') input[type=checkbox]").get_attribute("checked") is None


def test_an_item_added_above_the_pressed_box_during_the_undo_leaves_the_tick_on_that_box(sheaf):
    # #148, 7, gate on 91b73f3: the box was found again by its number, which the new item had moved onto itself.
    p, f = sheaf.page, sheaf.site.file
    stand_still(p)
    bar(p).nth(1).click()                               # Done
    p.clock.run_for(4000)
    type_at_end(p, "main li:has-text('Approve')", "")
    p.keyboard.press("Enter")
    p.keyboard.type("extra")
    until(lambda: "extra" in p.inner_text("main ul"), what="the new item on screen")
    p.clock.run_for(1100)
    until(lambda: "extra" in f.read_text(encoding="utf-8"), what="the edit, saved by the reload's settle")
    text = f.read_text(encoding="utf-8")
    assert "- [x] Done" in text and "- [ ] Approve" in text and "[x] extra" not in text, text


def test_an_item_typed_above_the_box_just_before_the_press_never_ticks_another_box(sheaf):
    # #148, 7, gate on 3b10c3c: the box was found by its number in the text the buttons were drawn from, which an
    # item on screen and not yet saved had moved onto Done, a one-off the hub then kept ticked. Share's box is
    # pressed at once (action-buttons 03): the box saves its block first, then ticks.
    p, f = sheaf.page, sheaf.site.file
    stand_still(p)
    type_at_end(p, "main li:has-text('Approve')", "")
    p.keyboard.press("Enter")
    p.keyboard.type("extra")
    until(lambda: "extra" in p.inner_text("main ul"), what="the new item on screen")
    ticks = []
    p.on("request", lambda r: ticks.append(r.url) if "/_/tick" in r.url else None)
    p.locator("main li:has-text('Share') input[type=checkbox]").click()
    try:
        def done():
            p.clock.run_for(500)                        # the page's timers run on the installed clock
            return "- [x] Share" in f.read_text(encoding="utf-8") and "extra" in f.read_text(encoding="utf-8")
        until(done, what="the item saved first, then the tick")
    except AssertionError:
        raise AssertionError(f"ticks sent {ticks}; file {f.read_text(encoding='utf-8')!r}; toast {toast(p)!r}")
    p.wait_for_timeout(500)
    text = f.read_text(encoding="utf-8")
    assert "[x] Done" not in text and "[x] extra" not in text, text


def test_share_pressed_with_the_hub_unreachable_and_an_owed_save_says_so_and_ticks_nothing(sheaf):
    # action-buttons 05, Review 4 on 11ff860: pressShare returned on an owed save without a word, so the press looked
    # dropped until the outage banner. It says so; the box stays; the edit is saved once the hub is back, unticked.
    p, f = sheaf.page, sheaf.site.file
    stand_still(p)
    ticks = []
    p.on("request", lambda r: ticks.append(r.url) if "/_/tick" in r.url else None)
    p.route("**/_/save", lambda r: r.abort())
    type_at_end(p, "main li:has-text('Approve')", "")
    p.keyboard.press("Enter")
    p.keyboard.type("extra")
    until(lambda: "extra" in p.inner_text("main ul"), what="the new item on screen")
    box = p.locator("main li:has-text('Share') input[type=checkbox]")
    box.click()
    toasted(p, "press Share again once it is back")
    assert not ticks, ticks
    assert not box.is_checked()
    text = f.read_text(encoding="utf-8")
    assert "extra" not in text and "- [x] Share" not in text, text
    assert "extra" in p.inner_text("main ul")          # the edit stays on the page, unsaved
    p.unroute("**/_/save")
    def owed_edit_saved():
        p.clock.run_for(1100)                           # the autosave's timer runs on the installed clock
        return "extra" in f.read_text(encoding="utf-8")
    until(owed_edit_saved, what="the owed edit, saved once the hub is back")
    p.wait_for_timeout(300)
    text = f.read_text(encoding="utf-8")
    assert "- [x] Share" not in text and not ticks, (text, ticks)


def test_an_upgrade_while_a_comment_waits_for_the_tick_does_not_ask_to_send_it(sheaf, site):
    # #148, gate on 3b10c3c: the comment, sent and waiting for the tick's answer, did not count as a write out, and
    # the upgrade's notice asked to send or cancel it.
    p, f = sheaf.page, sheaf.site.file
    p.add_init_script(HEARD)
    p.reload()
    p.wait_for_selector("button.rd-act")
    held = []
    p.route("**/_/tick", lambda r: held.append(r))
    select(p, at("main", "Body"), at("main", "Body", None))
    open_box(p)
    p.fill("#rd-popover textarea", "Why?")
    stand_still(p)
    bar(p).nth(0).click()
    p.clock.run_for(5100)
    until(lambda: held or p.wait_for_timeout(20), what="the tick, held")
    p.click("#rd-popover button[data-f=ok]")
    p.wait_for_timeout(300)
    p.route("**/_/doc?*", lambda r: r.abort())
    site.hub.entry(DOC).bus.publish("hello", {"version": "99.0.0"})
    until(lambda: heard(p, "hello"), what="the upgrade")
    p.wait_for_timeout(300)
    assert "Send or cancel" not in p.inner_text("#rd-notice")
    mark(p)
    held[0].continue_()
    p.unroute("**/_/tick")
    until(lambda: "- [x] Approve" in f.read_text(encoding="utf-8"), what="the tick")
    until(lambda: "Why?" in f.read_text(encoding="utf-8"), what="the comment after it")
    reloaded(p)                                         # the upgrade's reload, held for the tick, is the end of the test
    p.wait_for_selector("#rd-menu-btn", state="attached")


NOTES = SHEAF.replace("- [ ] Share\n", "- [ ] Share\n- [ ] notes\n")


def test_a_press_whose_block_was_edited_and_not_saved_keeps_the_tick(tab, site):
    # #153, 1: the box was taken only from a clean block, so the settle's merge of a later edit put Approve back.
    p, f = tab.page, site.file
    rewrite(f, NOTES)
    p.clock.install()
    tab.open()
    p.wait_for_selector("button.rd-act")
    stand_still(p)
    type_at_end(p, "main li:has-text('notes')", " now")
    until(lambda: "now" in p.inner_text("main li:has-text('notes')"), what="the edit on screen")
    bar(p).nth(0).click()                               # Approve, its block edited and not saved
    p.clock.run_for(3000)                               # the autosave goes
    until(lambda: "notes now" in f.read_text(encoding="utf-8"), what="the autosave")
    until(lambda: p.evaluate("document.querySelector('#rd-state').textContent") != "Saving…", what="its answer")
    p.click("main li:has-text('notes')")
    p.keyboard.press(key("End"))
    p.keyboard.type(" more")
    until(lambda: "more" in p.inner_text("main li:has-text('notes')"), what="the second edit on screen")
    p.clock.run_for(2100)
    until(lambda: "notes now more" in f.read_text(encoding="utf-8"), what="the edit, saved by the reload's settle")
    text = f.read_text(encoding="utf-8")
    assert re.search(r"^- \[x\] Approve$", text, re.M), text


def test_an_upgrade_while_a_save_waits_for_the_tick_does_not_ask_to_save(sheaf, site):
    # #153, 2: the save waiting for the tick was counted nowhere, and the upgrade's notice asked to save the edits.
    p, f = sheaf.page, sheaf.site.file
    p.add_init_script(HEARD)
    p.reload()
    p.wait_for_selector("button.rd-act")
    held = []
    p.route("**/_/tick", lambda r: held.append(r))
    stand_still(p)
    bar(p).nth(0).click()
    p.clock.run_for(5100)
    until(lambda: held or p.wait_for_timeout(20), what="the tick, held")
    type_at_end(p, "main p:has-text('Body')", " typed")
    p.clock.run_for(2600)                               # the autosave is due and waits for the tick
    until(lambda: p.evaluate("document.querySelector('#rd-state').textContent") == "Saving…", what="Saving…")
    p.route("**/_/doc?*", lambda r: r.abort())
    site.hub.entry(DOC).bus.publish("hello", {"version": "99.0.0"})
    until(lambda: heard(p, "hello"), what="the upgrade")
    p.wait_for_timeout(300)
    assert "Save your edits" not in p.inner_text("#rd-notice")
    held[0].continue_()
    p.unroute("**/_/tick")
    until(lambda: "- [x] Approve" in f.read_text(encoding="utf-8"), what="the tick")
    until(lambda: " typed" in f.read_text(encoding="utf-8"), what="the save after it")


def test_an_upgrade_held_by_a_comment_form_during_a_press_does_not_say_the_text_changed(sheaf, site):
    # #153, 3: the reload held for the form had no reason of its own, and the page it brought said the text changed.
    p = sheaf.page
    p.add_init_script(HEARD)
    p.reload()
    p.wait_for_selector("button.rd-act")
    p.route("**/_/doc?*", lambda r: r.abort())
    stand_still(p)
    bar(p).nth(0).click()
    site.hub.entry(DOC).bus.publish("hello", {"version": "99.0.0"})
    until(lambda: heard(p, "hello"), what="the upgrade, whose reload waits for the press")
    select(p, at("main", "Body"), at("main", "Body", None))
    p.clock.run_for(500)                                # the Comment button shows after the selection settles
    open_box(p)
    p.fill("#rd-popover textarea", "Why?")
    mark(p)
    bar(p).nth(0).click()                               # Undo: the reload now waits for the form
    p.wait_for_timeout(300)
    assert p.evaluate("window.__same_load") is True, "the page reloaded under the comment form"
    p.click("#rd-popover button[data-a=minimize]")     # a new comment has no Cancel: the box is put away
    p.clock.run_for(100)                                # the held reload is lifted by a timer 0
    reloaded(p)
    p.wait_for_selector("button.rd-act")
    toasted(p, "upgraded", on_clock=True)
    assert not any("text changed" in said for said in toasts_to_the_end(p, on_clock=True))


def test_a_restore_waiting_for_the_tick_is_answered_before_the_page_reloads(tab, context, site):
    # #153, 4: the Restore waiting for the tick was counted nowhere, and the reload of the tick's change went under it.
    f = site.file
    rewrite(f, SHEAF)
    tab.open()
    tab.page.wait_for_selector("button.rd-act")
    site.kill()
    type_at_end(tab.page, "main p:has-text('Body')", " typed")
    until(lambda: tab.page.evaluate(f"localStorage.getItem({draft_key(site)!r})"), what="the draft")
    tab.page.close()
    site.start()
    p = context.new_page()
    p.add_init_script(HEARD)
    p.clock.install()
    p.goto(site.url)
    p.wait_for_selector("#rd-notice button[data-d=restore]")
    p.wait_for_selector("button.rd-act")
    held = []
    p.route("**/_/tick", lambda r: held.append(r))
    stand_still(p)
    bar(p).nth(0).click()
    p.clock.run_for(5100)
    until(lambda: held or p.wait_for_timeout(20), what="the tick, held")
    saves = []
    p.route("**/_/save", lambda r: saves.append(r))
    p.click("#rd-notice button[data-d=restore]")       # it waits for the tick's answer
    answer = held[0].fetch()                            # the hub ticks, and its `changed` comes before the answer
    until(lambda: heard(p, "changed") or p.wait_for_timeout(20), what="the tick's change")
    mark(p)
    held[0].fulfill(response=answer)
    p.unroute("**/_/tick")
    until(lambda: saves or p.wait_for_timeout(20), what="the Restore, sent once the tick is answered")
    p.wait_for_timeout(500)
    assert p.evaluate("window.__same_load") is True, "the page reloaded under the Restore"
    saves[0].continue_()
    p.unroute("**/_/save")
    until(lambda: " typed" in f.read_text(encoding="utf-8"), what="the restored edit")
    reloaded(p)
    p.wait_for_selector("button.rd-act")
    p.wait_for_timeout(500)
    assert p.query_selector("#rd-notice button[data-d=restore]") is None, "the draft is offered again"
    assert p.evaluate(f"localStorage.getItem({draft_key(site)!r})") is None


def test_a_comment_opened_while_a_reload_waits_for_the_restore_holds_that_reload(tab, context, site):
    # #153, gate on 49f0491: the reload put off for the Restore went on once it was answered, under the comment
    # form opened meanwhile.
    f = site.file
    rewrite(f, SHEAF)
    tab.open()
    tab.page.wait_for_selector("button.rd-act")
    site.kill()
    type_at_end(tab.page, "main p:has-text('Body')", " typed")
    until(lambda: tab.page.evaluate(f"localStorage.getItem({draft_key(site)!r})"), what="the draft")
    tab.page.close()
    site.start()
    p = context.new_page()
    p.add_init_script(HEARD)
    p.clock.install()
    p.goto(site.url)
    p.wait_for_selector("#rd-notice button[data-d=restore]")
    p.wait_for_selector("button.rd-act")
    held = []
    p.route("**/_/tick", lambda r: held.append(r))
    stand_still(p)
    bar(p).nth(0).click()
    p.clock.run_for(5100)
    until(lambda: held or p.wait_for_timeout(20), what="the tick, held")
    saves = []
    p.route("**/_/save", lambda r: saves.append(r))
    p.click("#rd-notice button[data-d=restore]")
    answer = held[0].fetch()
    until(lambda: heard(p, "changed") or p.wait_for_timeout(20), what="the tick's change")
    mark(p)
    held[0].fulfill(response=answer)
    p.unroute("**/_/tick")
    until(lambda: saves or p.wait_for_timeout(20), what="the Restore, sent once the tick is answered")
    select(p, at("main", "Body"), at("main", "Body", None))
    p.clock.run_for(500)                                # the Comment button shows after the selection settles
    open_box(p)
    p.fill("#rd-popover textarea", "Why?")
    saves[0].continue_()
    p.unroute("**/_/save")
    until(lambda: " typed" in f.read_text(encoding="utf-8"), what="the restored edit")
    p.wait_for_timeout(1000)
    assert p.evaluate("window.__same_load") is True, "the page reloaded under the comment form"
    assert p.input_value("#rd-popover textarea") == "Why?"


def test_an_upgrade_during_the_press_does_not_reload_before_a_restore_waiting_for_the_tick(tab, context, site):
    # #153, gate on 8aeb048: a reload asked only by an upgrade went to location.reload when the press was done,
    # before the Restore parked on its tick was sent.
    f = site.file
    rewrite(f, SHEAF)
    tab.open()
    tab.page.wait_for_selector("button.rd-act")
    site.kill()
    type_at_end(tab.page, "main p:has-text('Body')", " typed")
    until(lambda: tab.page.evaluate(f"localStorage.getItem({draft_key(site)!r})"), what="the draft")
    tab.page.close()
    site.start()
    p = context.new_page()
    p.add_init_script(HEARD)
    p.clock.install()
    p.goto(site.url)
    p.wait_for_selector("#rd-notice button[data-d=restore]")
    p.wait_for_selector("button.rd-act")
    p.route("**/_/doc?*", lambda r: r.abort())
    held = []
    p.route("**/_/tick", lambda r: held.append(r))
    stand_still(p)
    bar(p).nth(0).click()
    site.hub.entry(DOC).bus.publish("hello", {"version": "99.0.0"})
    until(lambda: heard(p, "hello"), what="the upgrade, whose reload waits for the press")
    p.clock.run_for(5100)
    until(lambda: held or p.wait_for_timeout(20), what="the tick, held")
    saves = []
    p.route("**/_/save", lambda r: saves.append(r))
    p.click("#rd-notice button[data-d=restore]")       # it waits for the tick's answer
    mark(p)
    held[0].fulfill(status=409, content_type="application/json", body=REFUSED)
    p.unroute("**/_/tick")
    until(lambda: saves or p.wait_for_timeout(20), what="the Restore, sent once the tick is answered")
    p.wait_for_timeout(500)
    assert p.evaluate("window.__same_load") is True, "the page reloaded under the Restore"
    saves[0].continue_()
    p.unroute("**/_/save")
    until(lambda: " typed" in f.read_text(encoding="utf-8"), what="the restored edit")
    reloaded(p)
