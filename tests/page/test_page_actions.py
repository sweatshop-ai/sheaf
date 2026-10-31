"""The action buttons at the top of a sheaf's page (SPEC 10.11, #111): the page draws the boxes of the eight words
as the list's buttons, a one-off red with the 5 second Undo and locked once pressed, Share a toggle. A press posts
the list's tick (`POST /_/tick`, 9.10): the markdown on disk is what a tick writes, `- [x] <word>`."""
import pytest

from pagehelp import DOC, at, comment_on, mark, reloaded, toast, type_at_end, until

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
    tab.site.file.write_text(SHEAF, encoding="utf-8")
    tab.page.clock.install()
    tab.open()
    tab.page.wait_for_selector("#rd-actions button")
    return tab


def bar(page):
    return page.locator("#rd-actions button")


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
    """The installed clock runs at the real pace: from now on it moves only when the test runs it."""
    page.clock.pause_at((page.evaluate("Date.now()") + 50) / 1000)        # seconds, in Playwright's Python


def test_the_page_draws_its_actions_as_the_lists_buttons_at_the_top(sheaf):
    p = sheaf.page
    assert bar(p).all_inner_texts() == ["Approve", "Done", "Share"]
    assert [bar(p).nth(k).get_attribute("class") for k in range(3)] == ["rd-act one-off", "rd-act one-off",
                                                                       "rd-act toggle"]
    assert bar(p).nth(2).get_attribute("aria-pressed") == "false"
    # Above the document, never in a block a save sends.
    assert p.evaluate("document.querySelector('main').contains(document.getElementById('rd-actions'))") is False
    assert p.evaluate("document.getElementById('rd-actions').compareDocumentPosition(document.querySelector('main'))"
                      " & Node.DOCUMENT_POSITION_FOLLOWING") != 0


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
    until(lambda: p.locator("#rd-actions button.one-off.pressed").count() == 1, what="the reload with Approve locked")
    locked = p.locator("#rd-actions button.one-off.pressed")
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
    p.locator("main input[type=checkbox]").first.click()
    until(lambda: "at the top of the page" in toast(p), what="the line that points to the button")
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
    until(lambda: bar(p).all_inner_texts() == ["Approve", "Done", "Share", "Run it"], what="its button")
    bar(p).nth(3).click()
    p.clock.run_for(5100)
    until(lambda: "- [x] Run it" in f.read_text(encoding="utf-8"), what="the tick of the new action")


def test_a_refused_press_is_said_and_gives_the_button_back(sheaf):
    p, f = sheaf.page, sheaf.site.file
    p.route("**/_/tick", lambda route: route.fulfill(status=409, content_type="application/json",
                                                       body='{"ok": false, "error": "Approve: refused here."}'))
    bar(p).nth(0).click()
    p.clock.run_for(5100)
    until(lambda: "refused here" in toast(p), what="the refusal")
    assert bar(p).nth(0).inner_text() == "Approve" and bar(p).nth(0).is_enabled()
    assert "- [ ] Approve" in f.read_text(encoding="utf-8")


def test_a_change_from_outside_during_a_press_waits_for_its_answer_before_the_page_reloads(sheaf):
    p, f = sheaf.page, sheaf.site.file
    mark(p)
    bar(p).nth(0).click()
    f.write_text(SHEAF.replace("Body paragraph.", "Body paragraph, changed."), encoding="utf-8")
    p.wait_for_timeout(1500)
    assert p.evaluate("window.__same_load") is True, "the page reloaded under the press"
    assert bar(p).nth(0).inner_text() == "Undo"
    p.clock.run_for(5100)
    # The press names the text the page held: the hub refuses it, and the page says so before it reloads.
    until(lambda: "reload the page" in toast(p), what="the refusal")
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
    until(lambda: "Press it again." in toast(p), what="the line that the press was not sent")
    assert "[x]" not in f.read_text(encoding="utf-8")
    until(lambda: bar(p).all_inner_texts() == ["Approve", "Done", "Done", "Share"], what="the new buttons")


def test_share_is_pressed_and_released_on_the_page(sheaf):
    p, f = sheaf.page, sheaf.site.file
    bar(p).nth(2).click()
    p.clock.run_for(5100)
    until(lambda: "- [x] Share" in f.read_text(encoding="utf-8"), what="the Share tick")
    until(lambda: p.locator("#rd-actions button.toggle[aria-pressed=true]").count() == 1, what="Share pressed")
    p.locator("#rd-actions button.toggle").click()
    p.clock.run_for(5100)
    until(lambda: "- [ ] Share" in f.read_text(encoding="utf-8"), what="the release")
    until(lambda: p.locator("#rd-actions button.toggle[aria-pressed=false]").count() == 1, what="Share released")


def test_a_replys_answer_that_reloads_the_page_waits_for_a_press_in_its_undo(tab):
    p, f = tab.page, tab.site.file
    f.write_text(SHEAF, encoding="utf-8")
    tab.open()
    body = "main"
    comment_on(tab, at(body, "Body"), at(body, "Body", None), "Why?")
    p.clock.install()
    p.reload()
    p.wait_for_selector("#rd-actions button")
    p.click(".rd-badge")
    p.wait_for_selector("#rd-popover button[data-a=reply]")
    p.click("#rd-popover button[data-a=reply]")
    p.fill("#rd-popover textarea", "my reply")
    f.write_text(f.read_text(encoding="utf-8") + "\nFrom outside.\n", encoding="utf-8")
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
    until(lambda: "reload the page" in toast(p), what="the refusal after the reload")


def test_a_press_while_the_page_settles_onto_a_change_is_refused_and_the_page_reloads(sheaf):
    p, f = sheaf.page, sheaf.site.file
    held = []
    p.route("**/_/save", lambda r: held.append(r))
    type_at_end(p, "main p:has-text('Body')", " typed")
    f.write_text(SHEAF.replace("# Plan", "# Plan, outside"), encoding="utf-8")
    until(lambda: held or p.wait_for_timeout(20), what="the settle's save, held")
    mark(p)
    bar(p).nth(0).click()
    # The page is about to reload onto the change: the press is refused, never left to wait for a page that goes.
    assert bar(p).nth(0).inner_text() == "Approve"
    assert "reloading" in toast(p)
    held[0].continue_()
    p.unroute("**/_/save")
    reloaded(p)
    p.wait_for_selector("#rd-actions button")
    bar(p).nth(0).click()
    p.clock.run_for(5100)
    until(lambda: "- [x] Approve" in f.read_text(encoding="utf-8"), what="the press on the reloaded page")
    assert "# Plan, outside" in f.read_text(encoding="utf-8") and " typed" in f.read_text(encoding="utf-8")


def test_on_a_phone_the_buttons_wrap_44_px_high_and_the_page_never_scrolls_sideways(touch_tab):
    p = touch_tab.page
    touch_tab.site.file.write_text(SHEAF.replace("- [ ] Share\n", "- [ ] Share\n- [ ] Stop James\n"
                                                 "- [ ] Move to klium-website-relaunch (ref 18f3a9c2)\n"),
                                   encoding="utf-8")
    p.set_viewport_size({"width": 360, "height": 780})
    touch_tab.open()
    p.wait_for_selector("#rd-actions button")
    boxes = [bar(p).nth(k).bounding_box() for k in range(bar(p).count())]
    assert len(boxes) == 5
    assert all(b["height"] >= 44 and b["width"] >= 44 for b in boxes), boxes
    assert all(b["x"] >= 0 and b["x"] + b["width"] <= 360 for b in boxes), boxes
    assert len({b["y"] for b in boxes}) > 1, "five buttons on one line of 360 px"
    assert p.evaluate("document.documentElement.scrollWidth") <= 360


def test_on_a_phone_a_move_to_whose_slug_has_no_hyphen_breaks_inside_its_button_and_in_the_text(touch_tab):
    # The button breaks it (#112), and so does the document's own line of that box, the theme's (#128).
    p = touch_tab.page
    touch_tab.site.file.write_text(SHEAF.replace(
        "- [ ] Share\n", f"- [ ] Share\n- [ ] Move to {LONG} (ref 18f3a9c2)\n"),
        encoding="utf-8")
    p.set_viewport_size({"width": 360, "height": 780})
    touch_tab.open()
    p.wait_for_selector("#rd-actions button")
    move = bar(p).nth(3).bounding_box()
    assert move["x"] >= 0 and move["x"] + move["width"] <= 360, move
    assert p.evaluate("(e => e.scrollWidth <= e.clientWidth)(document.getElementById('rd-actions'))")
    assert p.evaluate("document.documentElement.scrollWidth") <= 360
    menu = p.locator("#rd-menu-btn").bounding_box()
    assert menu["x"] >= 0 and menu["x"] + menu["width"] <= 360, menu


def test_on_a_phone_a_long_word_in_the_text_breaks_and_a_code_block_scrolls_inside_itself(touch_tab):
    # #128: the document's text breaks a word wider than the screen, inline code too, on screen and in print; a
    # table keeps its words and scrolls in its frame, a code block keeps its lines.
    p = touch_tab.page
    touch_tab.site.file.write_text(f"# {LONG}\n\nThe slug {LONG} is long, and `{LONG}` is code.\n\n"
                                   f"| Slug |\n|---|\n| {LONG} |\n\n```\nmove {LONG} {LONG}\n```\n",
                                   encoding="utf-8")
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
    bar(p).nth(0).click()
    stand_still(p)
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
    p.wait_for_selector("#rd-actions button")
    mark(p)
    bar(p).nth(0).click()
    stand_still(p)
    f.write_text(SHEAF.replace("# Plan", "# Plan, outside"), encoding="utf-8")
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
    p.locator("main li:has-text('Run it') input[type=checkbox]").click()
    until(lambda: "at the top of the page" in toast(p), what="the line that points to the button")
    until(lambda: "- [ ] Run it" in f.read_text(encoding="utf-8"), what="the saved action")
    until(lambda: bar(p).all_inner_texts() == ["Approve", "Done", "Share", "Run it"], what="its button")
    assert "[x]" not in f.read_text(encoding="utf-8")
    assert p.locator("main li:has-text('Run it') input[type=checkbox]").is_checked() is False


def test_a_sign_out_during_a_press_does_not_reload_under_it(sheaf, site):
    # #127, 4: the page reloaded at once and the press was dropped without a line.
    p, f = sheaf.page, sheaf.site.file
    mark(p)
    bar(p).nth(0).click()
    stand_still(p)
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
    p.locator("main li:has-text('Run it') input[type=checkbox]").click()
    reloaded(p)
    until(lambda: bar(p).all_inner_texts() == ["Approve", "Done", "Share", "Run it"], what="its button")
    p.wait_for_timeout(500)
    assert "- [ ] Run it" in f.read_text(encoding="utf-8") and "[x]" not in f.read_text(encoding="utf-8")


PLAIN = SHEAF + "\n- [ ] plain task\n"


def test_a_plain_box_clicked_in_an_edited_block_while_the_hub_is_away_still_ticks(tab, site):
    # #127, 3, gate on 793824c: its save first could not reach the hub, and the click was dropped without a line.
    p, f = tab.page, site.file
    f.write_text(PLAIN, encoding="utf-8")
    tab.open()
    p.wait_for_selector("#rd-actions button")
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
    bar(p).nth(0).click()
    stand_still(p)
    p.clock.run_for(5100)
    until(lambda: held or p.wait_for_timeout(20), what="the tick, held")
    site.hub.entry(DOC).bus.publish("signed-out", {})
    until(lambda: "signed out" in p.inner_text("#rd-notice"), what="the signed-out notice")
    held[0].fulfill(status=401, content_type="application/json", body='{"ok": false, "error": "Not signed in."}')
    until(lambda: "Not signed in." in toast(p), what="the refusal")
    p.wait_for_timeout(500)
    assert p.evaluate("window.__same_load") is True, "the page reloaded over the refusal"
    assert "- [ ] Approve" in f.read_text(encoding="utf-8")
