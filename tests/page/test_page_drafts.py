"""Unsaved edits survive a hub that is away or a tab that is gone (SPEC 10.8)."""
import json
import re

import pytest

from helpers import comment
from pagehelp import P1, P2, T0, at, comment_draft_key, draft_key, mark, reloaded, select, toast, toasted, type_at_end, until
from sheafmd import comments as rdc

pytestmark = pytest.mark.page


class _Navigating:
    """What `stored` answers while the page is reloading: falsy, so that `until` waits past it, and
    not None, so that "no draft" is never read from it."""

    def __bool__(self):
        return False


NAVIGATING = _Navigating()


def stored(page, site):
    try:
        got = page.evaluate(f"localStorage.getItem({draft_key(site)!r})")
    except Exception:           # the page is reloading: not gone yet
        return NAVIGATING
    return json.loads(got) if got else None


def lose_an_edit(tab):
    tab.open()
    tab.site.kill()
    type_at_end(tab.page, P2, " and plums")
    until(lambda: stored(tab.page, tab.site), what="the draft in localStorage")
    tab.page.close()
    tab.site.start()
    return tab


@pytest.fixture
def lost_edit(tab):
    """Edits typed while the hub went away: they are in localStorage and nowhere else."""
    return lose_an_edit(tab)


def test_a_tab_that_wrote_no_draft_leaves_the_draft_of_another_tab_alone(tab, context, site):
    # Two tabs of one document share one draft key. Tab B has nothing dirty and no
    # offered draft (it was opened first); it touches a word and puts it back, which mirrors an empty
    # draft half a second later. That removed the draft tab A had written, the only stored copy of A's
    # edits. The hub is gone, so A's autosave cannot take its edits and remove the draft itself.
    tab.open()
    other = context.new_page()
    other.goto(site.url)
    other.wait_for_selector("#rd-menu-btn", state="attached")
    site.kill()
    type_at_end(tab.page, P2, " and plums")
    until(lambda: stored(tab.page, site), what="tab A's draft in localStorage")
    type_at_end(other, P2, "x")
    other.keyboard.press("Backspace")
    other.wait_for_timeout(1200)
    d = stored(tab.page, site)
    assert d and "plums" in d["edits"][0]["html"]


def test_edits_are_mirrored_to_localstorage_and_removed_when_a_save_leaves_nothing(tab):
    tab.open()
    type_at_end(tab.page, P2, " and plums")
    d = until(lambda: stored(tab.page, tab.site), what="the draft in localStorage")
    assert d["edits"] and "plums" in d["edits"][0]["html"] and d["hash"] and d["at"]
    until(lambda: "plums" in tab.site.file.read_text(), what="the autosave")
    until(lambda: stored(tab.page, tab.site) is None, what="the draft to go once saved")


def test_a_draft_found_on_load_is_restored_into_the_file(lost_edit, context):
    page = context.new_page()
    page.goto(lost_edit.site.url)
    page.wait_for_selector("#rd-notice:has-text('Unsaved edits from')")
    assert "plums" not in lost_edit.site.file.read_text()
    page.click("#rd-notice button[data-d=restore]")
    until(lambda: "and plums" in lost_edit.site.file.read_text(), what="the restored edit")
    until(lambda: stored(page, lost_edit.site) is None, what="the draft to go once restored")


# A Restore the hub wrote but did not answer (the page gives up after 120 s) was pressed again and wrote the
# edit twice. The Restore goes under a request id, kept in the draft, so that the second one, from this page or
# from a page opened after it, is answered `again` (SPEC 8.5, 10.8).
def test_a_second_restore_of_a_draft_whose_first_got_no_answer_goes_under_the_same_request_id(lost_edit, context):
    held, bodies, kept = [], [], []

    def written_never_answered(route):
        bodies.append(route.request.post_data_json)
        if not held:
            held.append(route)
            kept.append(stored(page, lost_edit.site))     # before the write: the hub then names the id and the page drops the draft
            route.fetch()               # the hub writes it; the answer is never given to the page
        else:
            route.continue_()

    page = context.new_page()
    page.route("**/_/save", written_never_answered)
    page.goto(lost_edit.site.url)
    page.wait_for_selector("#rd-notice button[data-d=restore]")
    page.click("#rd-notice button[data-d=restore]")
    until(lambda: "and plums" in lost_edit.site.file.read_text(), what="the first restore to be written")
    assert re.fullmatch(r"[A-Za-z0-9_-]{16,64}", bodies[0]["rid"])
    assert kept[0]["rid"] == bodies[0]["rid"]          # the draft keeps it
    page.unroute("**/_/save")
    page.close()
    page = context.new_page()
    page.on("request", lambda r: bodies.append(r.post_data_json) if r.url.endswith("/_/save") else None)
    page.goto(lost_edit.site.url)
    # the hub took that id: the page drops the draft, or, if it asked first, it is answered `again`
    until(lambda: stored(page, lost_edit.site) is None, what="the draft to go")
    assert all(b["rid"] == bodies[0]["rid"] for b in bodies)
    page.wait_for_timeout(500)
    assert lost_edit.site.file.read_text().count("plums") == 1


def test_a_restore_the_hub_took_is_not_written_back_when_its_answer_times_out_behind_a_held_reload(tab, context):
    f = tab.site.file
    comment(f, quote="apples", body="Why apples?")
    lose_an_edit(tab)
    page = context.new_page()
    page.clock.install(time=T0)
    page.goto(tab.site.url)
    page.wait_for_selector("#rd-notice button[data-d=restore]")
    page.click(".rd-badge")
    page.click("#rd-popover button[data-a=reply]")
    page.fill("#rd-popover textarea", "my reply text")      # an open form holds the reload
    held = []

    def written_never_answered(route):
        if not held:
            held.append(route)
            route.fetch()               # the hub writes it and names the id; the answer is never given to the page
        else:
            route.continue_()

    page.route("**/_/save", written_never_answered)
    page.click("#rd-notice button[data-d=restore]")
    until(lambda: "and plums" in f.read_text(), what="the restore to be written")
    until(lambda: stored(page, tab.site) is None, what="the draft to go")
    page.clock.fast_forward(120_500)
    page.wait_for_timeout(500)
    assert stored(page, tab.site) is None, "the draft the hub took was written back"


def test_a_draft_restored_while_a_reply_is_typed_reloads_only_once_the_reply_is_sent(tab, context):
    f = tab.site.file
    comment(f, quote="apples", body="Why apples?")
    lose_an_edit(tab)
    page = context.new_page()
    page.goto(tab.site.url)
    page.wait_for_selector("#rd-notice button[data-d=restore]")
    page.click(".rd-badge")
    page.click("#rd-popover button[data-a=reply]")
    page.fill("#rd-popover textarea", "my reply text")
    mark(page)
    page.click("#rd-notice button[data-d=restore]")
    until(lambda: "and plums" in f.read_text(), what="the restored edit")
    page.wait_for_timeout(1500)
    assert page.evaluate("window.__same_load") is True, "the page reloaded under the reply form"
    assert page.input_value("#rd-popover textarea") == "my reply text"
    assert "refreshes when you send or cancel" in page.inner_text("#rd-popover .rd-hold")
    assert page.query_selector("#rd-notice button[data-d=restore]") is None, "Restore is still offered"
    page.click("#rd-popover button[data-f=ok]")
    reloaded(page)
    (c,) = rdc.parse(f.read_text()).comments
    assert [r.text for r in c.replies] == ["my reply text"]
    page.wait_for_selector(f"{P2}:has-text('and plums')")
    page.wait_for_selector("#rd-popover .rd-msg:has-text('my reply text')")
    toasted(page, "Your restored edits are in.")
    assert "while you wrote" not in toast(page)
    assert stored(page, tab.site) is None


def test_a_task_box_ticked_while_the_hub_is_away_is_kept_as_a_draft_and_restored(tab, context):
    # A tick is an edit that no key press made, so nothing mirrored it. The
    # save that follows the click failed, and the tick stayed on screen and in no store.
    f = tab.site.file
    f.write_text(f.read_text() + "\n- [ ] first task\n- [ ] second task\n", encoding="utf-8")
    tab.open()
    tab.site.kill()
    tab.page.locator("main input[type=checkbox]").first.click()
    d = until(lambda: stored(tab.page, tab.site), what="the draft in localStorage")
    assert "checked" in d["edits"][0]["html"] and "first task" in d["edits"][0]["html"]
    tab.page.close()
    tab.site.start()
    page = context.new_page()
    page.goto(tab.site.url)
    page.wait_for_selector("#rd-notice button[data-d=restore]")
    assert "- [x] first task" not in f.read_text()
    page.click("#rd-notice button[data-d=restore]")
    until(lambda: "- [x] first task" in f.read_text(), what="the restored tick")
    assert "- [ ] second task" in f.read_text()


def test_a_draft_can_be_discarded(lost_edit, context):
    page = context.new_page()
    page.goto(lost_edit.site.url)
    page.click("#rd-notice button[data-d=discard]")
    assert stored(page, lost_edit.site) is None
    assert "plums" not in lost_edit.site.file.read_text()


def test_a_draft_the_hub_refuses_opens_a_panel_with_its_text_to_copy(lost_edit, context):
    page = context.new_page()
    page.goto(lost_edit.site.url)
    page.wait_for_selector("#rd-notice button[data-d=restore]")
    d = stored(page, lost_edit.site)
    d["hash"] = "0000000000000000"
    page.evaluate(f"localStorage.setItem({draft_key(lost_edit.site)!r}, {json.dumps(json.dumps(d))})")
    page.reload()
    page.click("#rd-notice button[data-d=restore]")
    page.wait_for_selector("#rd-panel.open pre.rd-draft")
    assert "plums" in page.inner_text("#rd-panel pre.rd-draft")
    assert stored(page, lost_edit.site) is not None


# A Restore goes through the same save as any other and gives up after 120 s (SPEC 10.3). The hub may have
# written it all the same, and the offer stays (or comes back with the reload that write brings), so a second
# Restore must say what the first sent (`saved`, SPEC 7.3): the hub finds it in the file instead of taking it
# for a second edit.
@pytest.mark.parametrize("written", [False, True], ids=["never-written", "written-late"])
def test_a_restore_the_hub_does_not_answer_within_120_seconds_names_itself_when_pressed_again(lost_edit, context, written):
    page = context.new_page()
    page.clock.install(time=T0)
    page.goto(lost_edit.site.url)
    page.wait_for_selector("#rd-notice button[data-d=restore]")
    held, bodies = [], []

    def hold_first(route):
        bodies.append(route.request.post_data_json)
        if not held:
            held.append(route)
            if written:
                # the hub writes it without keeping its id, as a hub that restarted since has forgotten it (a hub
                # that kept it would name it and take the offer away, 8.5); its answer is never given to the page
                body = {k: v for k, v in bodies[0].items() if k != "rid"}
                route.fetch(post_data=json.dumps(body))
        else:
            route.continue_()

    page.route("**/_/save", hold_first)
    page.click("#rd-notice button[data-d=restore]")
    until(lambda: held or page.wait_for_timeout(20), what="the restore to go out")
    mark(page)
    page.clock.fast_forward(120_500)
    # the draft in the store names the send, for the page that offers it again: a late write the hub made
    # reloads this one, and a person may come back to it in another tab too
    until(lambda: (stored(page, lost_edit.site) or {}).get("edits", [{}])[0].get("saved"), what="the draft to name the send")
    if written:
        # the page reloads itself as the give-up frees the reload the late write asked for, at a moment the test
        # does not pick: a reload of its own then lands on that navigation and is aborted. It waits for it instead.
        reloaded(page)
    else:
        page.reload()
    page.wait_for_selector("#rd-notice button[data-d=restore]")
    page.click("#rd-notice button[data-d=restore]")
    until(lambda: len(bodies) >= 2, what="the second restore to go out")
    page.unroute("**/_/save")
    assert bodies[1]["edits"][0]["saved"] == bodies[0]["edits"][0]["html"]
    until(lambda: "and plums" in lost_edit.site.file.read_text(), what="the restored edit")
    page.wait_for_timeout(500)
    assert lost_edit.site.file.read_text().count("plums") == 1      # found in the file, not taken for a second edit


def test_a_draft_that_is_offered_is_not_overwritten_or_removed_by_what_is_typed_and_saved_meanwhile(lost_edit, context):
    page = context.new_page()
    page.goto(lost_edit.site.url)
    page.wait_for_selector("#rd-notice button[data-d=restore]")
    type_at_end(page, P1, " and kiwis")
    until(lambda: "and kiwis" in lost_edit.site.file.read_text(), what="the autosave")
    page.wait_for_timeout(800)      # the mirror runs half a second after a save too
    d = stored(page, lost_edit.site)
    assert d and "plums" in d["edits"][0]["html"], "the offered draft was overwritten or removed"
    page.click("#rd-notice button[data-d=restore]")
    until(lambda: "and plums" in lost_edit.site.file.read_text(), what="the restored edit")


def test_restore_with_a_kept_comment_on_screen_reloads_and_the_kept_comment_comes_back(lost_edit, context):
    # The kept comment is a standing notice, not a form being written: it must not
    # hold the reload that Restore asks for, with nothing on screen to say it is held.
    page = context.new_page()
    page.goto(lost_edit.site.url)
    page.wait_for_selector("#rd-notice button[data-d=restore]")
    slot = json.dumps([{"quote": "pears", "body": "about the pears", "at": "2026-10-13T10:00:00.000Z"}])
    ckey = comment_draft_key(lost_edit.site)
    page.evaluate(f"localStorage.setItem({ckey!r}, {json.dumps(slot)})")
    page.reload()
    page.wait_for_selector("#rd-notice button[data-d=restore]")
    page.wait_for_selector("#rd-popover .rd-hold:has-text('your comment is kept')")
    mark(page)
    page.click("#rd-notice button[data-d=restore]")
    until(lambda: "and plums" in lost_edit.site.file.read_text(), what="the restored edit")
    reloaded(page)
    page.wait_for_selector(f"{P2}:has-text('and plums')")
    page.wait_for_selector("#rd-popover .rd-hold:has-text('your comment is kept')")
    assert page.input_value("#rd-popover textarea") == "about the pears"


def test_the_upgrade_notice_leaves_the_restore_and_discard_of_an_offered_draft(lost_edit, context):
    # The notice replaced the whole line, and with it the two buttons: the
    # draft stayed in localStorage, undecided, with no way to decide it until the page was reloaded.
    page = context.new_page()
    page.goto(lost_edit.site.url)
    page.wait_for_selector("#rd-notice button[data-d=restore]")
    lost_edit.site.kill()
    type_at_end(page, P2, " and kiwis")
    lost_edit.site.start(version="99.0.0")
    until(lambda: "The sheaf hub was upgraded" in page.inner_text("#rd-notice"), timeout=15, what="the upgrade notice")
    assert page.locator("#rd-notice button[data-d=restore]").count() == 1
    assert page.locator("#rd-notice button[data-d=discard]").count() == 1
    d = stored(page, lost_edit.site)
    assert d and "plums" in d["edits"][0]["html"], "the offered draft was overwritten or removed"


def test_a_page_that_is_stale_with_edits_on_screen_still_asks_before_it_is_left(tab):
    # The leave prompt switched off by `stale`: once the file changed under the edits and
    # the merge failed, Save is refused and the person is told to copy the text and reload. Closing
    # the tab then went through without a question, with the edits only on screen (and not even in
    # the draft while an offered draft is undecided).
    tab.open()
    p, dialogs = tab.page, []
    p.on("dialog", lambda d: (dialogs.append(d.type), d.dismiss()))
    p.route("**/_/save", lambda route: route.fulfill(status=409, json={"ok": False, "error": "no merge"}))
    type_at_end(tab.page, P2, " and plums")
    f = tab.site.file
    f.write_text(f.read_text() + "\nA new paragraph from outside.\n", encoding="utf-8")
    until(lambda: "could not be merged" in p.evaluate("document.querySelector('#rd-toast').textContent"),
          what="the page to go stale")
    p.close(run_before_unload=True)
    p.wait_for_timeout(500)          # the dialog event is delivered while the API is called
    assert dialogs == ["beforeunload"]


# While a draft found on load is undecided the page leaves it as it is, so its own edits are on screen only,
# with the leave question; a tick whose save failed is one of them. They were mirrored again only from the next
# key pressed after the person chose, and a tick has none: after Discard it stayed on screen and in no store.
# The page mirrors them the moment the offer is decided.
def offered_with_a_failed_tick(tab, context, tick=True):
    """A document with two task boxes and an edit lost while the hub was away; a page that offers that edit,
    on which the first box is ticked and its save fails (with `tick`). Returns the page."""
    f = tab.site.file
    f.write_text(f.read_text() + "\n- [ ] first task\n- [ ] second task\n", encoding="utf-8")
    lose_an_edit(tab)
    page = context.new_page()
    page.goto(tab.site.url)
    page.wait_for_selector("#rd-notice button[data-d=restore]")
    failed = []

    def first_save_fails(route):
        if failed:
            route.continue_()
            return
        failed.append(route)
        route.fulfill(status=500, json={"ok": False, "error": "the hub broke off"})
    page.route("**/_/save", first_save_fails)
    if tick:
        page.locator("main input[type=checkbox]").first.click()
        until(lambda: "the hub broke off" in page.evaluate("document.querySelector('#rd-toast').textContent"),
              what="the tick's save to fail")
        d = stored(page, tab.site)
        assert d and "plums" in d["edits"][0]["html"], "the offered draft was overwritten or removed"
    return page


def test_a_tick_whose_save_failed_while_a_draft_is_offered_is_kept_once_the_draft_is_discarded(tab, context):
    page = offered_with_a_failed_tick(tab, context)
    page.click("#rd-notice button[data-d=discard]")
    d = stored(page, tab.site)
    assert d, "the tick is on screen only"
    assert len(d["edits"]) == 1
    assert "checked" in d["edits"][0]["html"] and "first task" in d["edits"][0]["html"]
    assert "plums" not in json.dumps(d)


def test_with_no_edit_of_its_own_discard_leaves_no_draft(tab, context):
    page = offered_with_a_failed_tick(tab, context, tick=False)
    page.click("#rd-notice button[data-d=discard]")
    assert stored(page, tab.site) is None


def test_a_tick_whose_save_failed_while_a_draft_is_offered_is_kept_once_the_draft_is_restored(tab, context):
    # Restore reloads, and that reload waits for the reply being typed: meanwhile the tick is kept.
    f = tab.site.file
    comment(f, quote="apples", body="Why apples?")
    page = offered_with_a_failed_tick(tab, context)
    page.click(".rd-badge")
    page.click("#rd-popover button[data-a=reply]")
    page.fill("#rd-popover textarea", "my reply text")
    page.click("#rd-notice button[data-d=restore]")
    until(lambda: "and plums" in f.read_text(), what="the restored edit")
    page.wait_for_selector("#rd-popover .rd-hold")
    d = until(lambda: stored(page, tab.site), what="the tick in localStorage")
    assert "checked" in d["edits"][0]["html"] and "plums" not in json.dumps(d)
    page.keyboard.press("Control+s")            # a comment is sent only with no edit on screen
    until(lambda: "- [x] first task" in f.read_text(), what="the saved tick")
    until(lambda: stored(page, tab.site) is None, what="the draft to go once the tick is saved")
    mark(page)
    page.click("#rd-popover button[data-f=ok]")
    reloaded(page)
    md = f.read_text()
    assert "- [x] first task" in md and "and plums" in md
    (c,) = rdc.parse(md).comments
    assert [r.text for r in c.replies] == ["my reply text"]


# ── a draft belongs to the folder that wrote it (SPEC 10.8) ──────────────────

def root_of(page):
    return json.loads(page.evaluate("document.querySelector('script[type=\"application/json\"]').textContent"))["root"]


def set_item(page, name, value):
    page.evaluate("([k, v]) => localStorage.setItem(k, v)", [name, value])


def lost_edit_key(context, site):
    """The text of the draft under the key, read from a page of the same origin."""
    page = context.new_page()
    try:
        page.goto(site.base + "/_/health")
        return page.evaluate(f"localStorage.getItem({draft_key(site)!r})")
    finally:
        page.close()


def another_folder_takes_the_name(site):
    """The hub away, its registry gone, then back: the folder `work` is registered anew, with an id of its own
    (SPEC 8.2), under the same name and port."""
    from sheafmd.hub.roots import Roots
    site.kill()
    Roots._file().unlink()
    site.start()


def test_a_draft_carries_the_root_of_the_folder_that_wrote_it(tab):
    tab.open()
    tab.site.kill()
    type_at_end(tab.page, P2, " and plums")
    d = until(lambda: stored(tab.page, tab.site), what="the draft in localStorage")
    assert d["root"] == root_of(tab.page)


def test_a_draft_typed_in_one_folder_is_not_offered_in_another_under_the_same_name(lost_edit, context, site):
    written = json.loads(until(lambda: lost_edit_key(context, site), what="the draft in localStorage"))
    another_folder_takes_the_name(site)
    page = context.new_page()
    page.goto(site.url)
    page.wait_for_selector("#rd-menu-btn", state="attached")
    assert written["root"] and root_of(page) != written["root"]
    page.wait_for_timeout(800)
    assert "Unsaved edits" not in page.evaluate("document.querySelector('#rd-notice').textContent")
    assert page.evaluate(f"localStorage.getItem({draft_key(site)!r})") is not None


def test_a_draft_of_an_older_build_with_no_root_is_still_offered(tab, context, site):
    tab.open()
    set_item(tab.page, draft_key(site), json.dumps({"hash": "x", "at": "2026-10-01T10:00:00Z",
                                              "edits": [{"i": 0, "html": "<p>a</p>"}]}))
    page = context.new_page()
    page.goto(site.url)
    until(lambda: "Unsaved edits" in page.evaluate("document.querySelector('#rd-notice').textContent"),
          what="the offer of the draft")


def test_discard_removes_only_the_draft_this_tab_was_offered(lost_edit, context, site):
    # Between the offer and the click another tab of this document wrote the key afresh.
    page = context.new_page()
    page.goto(site.url)
    page.wait_for_selector("#rd-notice button[data-d=discard]")
    theirs = json.dumps({"root": root_of(page), "hash": "y", "at": "2026-10-21T10:00:00Z",
                         "edits": [{"i": 0, "html": "<p>theirs</p>"}]})
    set_item(page, draft_key(site), theirs)
    page.click("#rd-notice button[data-d=discard]")
    assert page.evaluate(f"localStorage.getItem({draft_key(site)!r})") == theirs


# ── Discard and Restore inside the upgrade notice ──────────────────────────────

def upgraded_over_an_offer(lost_edit, context, writing=False):
    """A page that offers the lost edit and has met an upgraded hub with something of its own on screen:
    edits, or (with `writing`) a comment being written."""
    page = context.new_page()
    page.goto(lost_edit.site.url)
    page.wait_for_selector("#rd-notice button[data-d=restore]")
    lost_edit.site.kill()
    if writing:
        select(page, at(P2, "pears"), at(P2, "pears", None))
        page.click("#rd-comment-btn")
        page.fill("#rd-popover textarea", "about the pears")
    else:
        type_at_end(page, P2, " and kiwis")
    lost_edit.site.start(version="99.0.0")
    until(lambda: "The sheaf hub was upgraded" in page.inner_text("#rd-notice"), timeout=15, what="the upgrade notice")
    return page


def test_discard_inside_the_upgrade_notice_keeps_the_upgrade_line(lost_edit, context):
    page = upgraded_over_an_offer(lost_edit, context)
    page.click("#rd-notice button[data-d=discard]")
    assert "The sheaf hub was upgraded" in page.inner_text("#rd-notice")
    assert page.locator("#rd-notice button[data-d]").count() == 0


def test_restore_inside_the_upgrade_notice_keeps_the_upgrade_line_while_the_reload_waits(lost_edit, context):
    # A comment being written holds the reload that Restore asks for, so the notice is still on screen.
    page = upgraded_over_an_offer(lost_edit, context, writing=True)
    page.click("#rd-notice button[data-d=restore]")
    until(lambda: "and plums" in lost_edit.site.file.read_text(), what="the restored edit")
    until(lambda: page.locator("#rd-notice button[data-d]").count() == 0, what="the offer's buttons to go")
    page.wait_for_timeout(300)
    assert "The sheaf hub was upgraded" in page.inner_text("#rd-notice")
    assert page.locator("#rd-notice button[data-d]").count() == 0
