"""The action buttons at the top of a sheaf's page (SPEC 10.11, #111): the page draws the boxes of the eight words
as the list's buttons, a one-off red with the 5 second Undo and locked once pressed, Share a toggle. A press posts
the list's tick (`POST /_/tick`, 9.10): the markdown on disk is what a tick writes, `- [x] <word>`."""
import pytest

from pagehelp import at, comment_on, mark, reloaded, toast, type_at_end, until

pytestmark = pytest.mark.page

SHEAF = """# Plan

## Actions

- [ ] Approve
- [ ] Done
- [ ] Share

Body paragraph.
"""


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


def test_on_a_phone_a_move_to_whose_slug_has_no_hyphen_breaks_inside_its_button(touch_tab):
    # The document's own box of that line is as wide as its word: the theme's, not the buttons' (#128).
    p = touch_tab.page
    touch_tab.site.file.write_text(SHEAF.replace(
        "- [ ] Share\n", "- [ ] Share\n- [ ] Move to klium_website_relaunch_international_2026_phase_two (ref 18f3a9c2)\n"),
        encoding="utf-8")
    p.set_viewport_size({"width": 360, "height": 780})
    touch_tab.open()
    p.wait_for_selector("#rd-actions button")
    move = bar(p).nth(3).bounding_box()
    assert move["x"] >= 0 and move["x"] + move["width"] <= 360, move
    assert p.evaluate("(e => e.scrollWidth <= e.clientWidth)(document.getElementById('rd-actions'))")
