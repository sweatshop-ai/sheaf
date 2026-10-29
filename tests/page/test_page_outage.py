"""Riding through an outage (SPEC 10.7): a banner after 15 s of failed reconnects on a visible tab,
none after a suspend, jobs marked interrupted after a new boot, a new version or moved text settled
and reloaded, a rotated key told as a sign-in message with the edits kept, and a document that is no
longer on the hub told as such, with what was typed kept and offered; a sheaf the hub moved (9.11)
followed to its new address, unless what was typed holds the page.

The tests that count seconds drive the page's clock (Playwright's `page.clock`): only the page's
timers and `Date` are faked, so the browser's own reconnect of the stream (every 2 s) still runs."""
import base64
import json
import os
import re
import time
from types import SimpleNamespace

import pytest

from helpers import PLAN, comment
from pagehelp import (DOC, P1, P2, T0, at, comment_on, draft_key, comment_draft_key, gone, mark, reload_on_clock,
                      reloaded, toast, toasted, type_at_end, until)
from sheafmd import comments as rdc

pytestmark = pytest.mark.page

BANNER = "Hub unreachable, reconnecting… your edits are safe on screen."
START = "run sheaf start"
STOPPED = "The hub was stopped. Run sheaf start to continue; your edits are safe on screen."
GONE = "This document is no longer on the sheaf hub"

# Counts what the stream does, and lets a test say the tab is hidden: the page asks
# `document.visibilityState`, which a headless page always answers "visible".
WATCH = """(() => {
  const ES = window.EventSource;
  window.__stream = {errors: 0, opens: 0};
  window.EventSource = class extends ES {
    constructor(...a) {
      super(...a);
      this.addEventListener('error', () => window.__stream.errors++);
      this.addEventListener('open', () => window.__stream.opens++);
    }
  };
  window.__vis = 'visible';
  Object.defineProperty(document, 'visibilityState', {get: () => window.__vis, configurable: true});
})()"""


def notice(page):
    """What the notice line says, or '' while it is hidden."""
    return page.evaluate("(() => { const n = document.querySelector('#rd-notice');"
                         " return n.hidden ? '' : n.textContent; })()")


def stream(page):
    return page.evaluate("window.__stream")


def show_tab(page, visible):
    page.evaluate(f"window.__vis = {'visible' if visible else 'hidden'!r};"
                  " document.dispatchEvent(new Event('visibilitychange'))")


def open_on_clock(tab, start=T0):
    """The page opened on a clock the test drives, from `start` (ms), with its stream watched."""
    tab.page.add_init_script(WATCH)
    tab.page.clock.install(time=start)
    tab.open()
    tab.page.clock.pause_at(start + 5_000)
    until(lambda: stream(tab.page)["opens"] >= 1, what="the stream to open")
    return tab


@pytest.fixture
def clocked(tab):
    return open_on_clock(tab)


def cut(tab):
    """The hub gone without a word; waits until the page has seen the stream fail."""
    tab.site.kill()
    until(lambda: stream(tab.page)["errors"] >= 1, what="the stream to fail")


def test_no_banner_inside_the_grace_and_the_banner_after_15_seconds_of_failing(clocked):
    p = clocked.page
    cut(clocked)
    p.clock.run_for(14_000)
    assert notice(p) == ""
    p.clock.run_for(2_000)
    assert notice(p) == f"{BANNER} If it does not come back, {START}."   # this hub was not the service


def test_the_banner_leaves_out_the_command_when_the_hub_is_the_service(site, tab):
    site.kill()
    site.start(service=True)
    open_on_clock(tab)
    cut(tab)
    tab.page.clock.run_for(16_000)
    assert notice(tab.page) == BANNER


def test_no_banner_after_a_suspend_and_none_until_a_full_grace_has_passed_again(clocked):
    p = clocked.page
    cut(clocked)
    p.clock.fast_forward(600_000)        # the lid closed for ten minutes: one jump, no ticks
    assert notice(p) == ""
    p.clock.run_for(14_000)
    assert notice(p) == ""
    p.clock.run_for(2_000)
    assert BANNER in notice(p)


def test_coming_back_to_the_tab_starts_the_grace_again(clocked):
    p = clocked.page
    cut(clocked)
    p.clock.run_for(10_000)
    show_tab(p, False)
    show_tab(p, True)
    p.clock.run_for(10_000)              # 20 s since the stream failed, 10 s since the tab came back
    assert notice(p) == ""
    p.clock.run_for(6_000)
    assert BANNER in notice(p)


# The outage flag and a save's request id must not share a name: with the banner up, a save would throw on the flag and the
# draft would not be written. Ctrl+S in an outage says so, and the edit is in the draft with the id of that save.
def test_a_save_after_the_banner_says_the_hub_is_unreachable_and_the_draft_holds_the_edit(clocked):
    p = clocked.page
    cut(clocked)
    p.clock.run_for(16_000)
    assert BANNER in notice(p)
    type_at_end(p, P2, " and plums")
    p.keyboard.press("Control+s")
    toasted(p, "The hub is unreachable; nothing was saved. Your edits stay on screen.")
    d = until(lambda: stored(p, clocked.site), what="the draft in localStorage")
    assert "plums" in d["edits"][0]["html"] and re.fullmatch(r"[A-Za-z0-9_-]{16,64}", d["rid"])


def test_a_hidden_tab_shows_no_banner(clocked):
    p = clocked.page
    show_tab(p, False)
    cut(clocked)
    p.clock.run_for(60_000)
    assert notice(p) == ""
    show_tab(p, True)
    p.clock.run_for(14_000)
    assert notice(p) == ""
    p.clock.run_for(2_000)
    assert BANNER in notice(p)


def test_the_banner_goes_when_the_hub_is_back(clocked):
    p = clocked.page
    cut(clocked)
    p.clock.run_for(16_000)
    assert BANNER in notice(p)
    clocked.site.start()
    until(lambda: notice(p) == "", what="the banner to go once the hub answers")
    toasted(p, "Reconnected to the sheaf hub.")


def test_a_hub_stopped_by_a_person_says_so_at_once(clocked):
    p = clocked.page
    clocked.site.stop("stop")
    until(lambda: notice(p) == STOPPED, what="the stop notice")
    p.clock.run_for(60_000)
    assert notice(p) == STOPPED          # the banner does not talk over it
    clocked.site.start()
    until(lambda: notice(p) == "", what="the stop notice to go once the hub answers")


def test_a_hub_stopped_by_a_signal_says_so_at_once(clocked):
    p = clocked.page
    clocked.site.stop("signal")
    until(lambda: notice(p) == STOPPED, what="the stop notice")
    p.clock.run_for(60_000)
    assert notice(p) == STOPPED          # the banner does not talk over it


def test_a_hub_stopped_for_an_upgrade_shows_no_stop_notice(clocked):
    p = clocked.page
    clocked.site.stop("upgrade")
    until(lambda: stream(p)["errors"] >= 1, what="the stream to fail")
    p.clock.run_for(5_000)
    assert notice(p) == ""


def test_ctrl_s_while_the_hub_is_unreachable_says_nothing_was_saved(tab):
    tab.open()
    tab.site.kill()
    type_at_end(tab.page, P2, " and plums")
    tab.page.keyboard.press("Control+s")
    says = "The hub is unreachable; nothing was saved. Your edits stay on screen."
    toasted(tab.page, says)
    assert toast(tab.page) == says       # that sentence alone, not "save failed: " and then the sentence
    assert "plums" in tab.page.inner_text(P2)


@pytest.fixture
def running_tell(tab):
    """A page whose open thread shows a Tell the hub is working on."""
    tab.page.add_init_script(WATCH)
    tab.open()
    c = comment_on(tab, at(P1, "apples"), at(P1, "apples", None), "Why apples?")
    tab.page.wait_for_selector("#rd-popover .rd-msg")
    tab.site.hub.entry(DOC).live._telling[c.id] = 0
    tab.page.reload()
    tab.page.wait_for_selector("#rd-menu-btn", state="attached")
    tab.page.click(".rd-badge")
    tab.page.wait_for_selector("#rd-popover .rd-pending-tell")
    return tab


# A cancel that the hub does not answer within 30 seconds must not leave the busy button until an event clears it, and
# the hub sends none for a cancel that finds nothing running. The page takes the job off as an answer would; a
# job that still runs shows again with the next snapshot of the hub, or ends in its thread.
def test_a_cancel_the_hub_does_not_answer_within_30_seconds_takes_the_busy_button_away(running_tell):
    p = running_tell.page
    reload_on_clock(p)
    p.click(".rd-badge")
    p.wait_for_selector("#rd-popover .rd-pending-tell")
    held = []
    p.route("**/_/cancel", lambda route: held.append(route))
    p.click("#rd-popover button[data-a=cancel-tell]")
    until(lambda: held or p.wait_for_timeout(20), what="the cancel to go out")
    p.clock.fast_forward(30_500)
    toasted(p, "within 30 seconds")
    until(lambda: p.locator("#rd-popover button[data-a=cancel-tell]").count() == 0, what="the busy button to go")
    assert p.locator("#rd-popover .rd-pending-tell").count() == 0
    p.unroute("**/_/cancel")


def test_a_job_running_before_a_new_boot_shows_interrupted_in_its_thread(running_tell):
    running_tell.site.stop()
    running_tell.site.start()            # a new boot: the hub forgot the job
    running_tell.page.wait_for_selector("#rd-popover .rd-interrupted")
    assert "interrupted by a hub restart, send it again" in running_tell.page.inner_text("#rd-popover")
    assert running_tell.page.query_selector("#rd-popover .rd-pending-tell") is None


def test_the_same_boot_leaves_a_running_job_alone(running_tell):
    running_tell.site.kill()
    until(lambda: running_tell.page.evaluate("window.__stream.errors") >= 1, what="the stream to fail")
    running_tell.site.reopen()
    until(lambda: stream(running_tell.page)["opens"] >= 2, what="the stream to come back")
    assert running_tell.page.query_selector("#rd-popover .rd-interrupted") is None
    assert running_tell.page.query_selector("#rd-popover .rd-pending-tell") is not None


@pytest.mark.parametrize("kind", ["ask", "tell"])
def test_a_job_started_while_the_page_could_not_hear_the_hub_shows_in_its_thread_after_the_hello(tab, kind):
    # `ask-started` and `tell-started` are missed in a blip of the same boot; the hello alone has to bring the
    # job in (a reload would only come when the answer reaches the file and the hash moves).
    tab.page.add_init_script(WATCH)
    tab.open()
    c = comment_on(tab, at(P1, "apples"), at(P1, "apples", None), "Why apples?")
    tab.page.wait_for_selector("#rd-popover .rd-msg")
    tab.site.kill()
    until(lambda: stream(tab.page)["errors"] >= 1, what="the stream to fail")
    hub = tab.site.hub
    if kind == "ask":
        hub.runner._holds.append(SimpleNamespace(kind="ask", address=hub.entry(DOC).address, cid=c.id,
                                                       cancelled=False))
    else:
        hub.entry(DOC).live._telling[c.id] = 0
    tab.site.reopen()
    until(lambda: stream(tab.page)["opens"] >= 2, what="the stream to come back")
    tab.page.wait_for_selector("#rd-popover .rd-pending" if kind == "ask" else "#rd-popover .rd-pending-tell")
    assert tab.page.query_selector("#rd-popover .rd-interrupted") is None


def test_a_doc_answer_read_before_a_job_ended_does_not_bring_the_job_back(tab):
    # The hello's check holds a snapshot that still names the Tell; `tell-failed` ends it while that answer is
    # out, and the older snapshot must not put it back (a thread pending until a reload).
    tab.page.add_init_script(WATCH)
    tab.open()
    c = comment_on(tab, at(P1, "apples"), at(P1, "apples", None), "Why apples?")
    tab.page.wait_for_selector("#rd-popover .rd-msg")
    tab.site.kill()
    until(lambda: stream(tab.page)["errors"] >= 1, what="the stream to fail")
    tab.site.hub.entry(DOC).live._telling[c.id] = 0
    held = []
    tab.page.route("**/_/doc?*", lambda route: held.append(route))
    tab.site.reopen()
    until(lambda: held or tab.page.wait_for_timeout(20), what="the hello's check to go out")
    until(lambda: stream(tab.page)["opens"] >= 2, what="the stream to come back")
    tab.site.hub.entry(DOC).bus.publish("tell-failed", {"id": c.id, "error": "gone"})
    until(lambda: "gone" in toast(tab.page), what="the failure to be heard")
    for route in held:
        route.continue_()
    tab.page.wait_for_timeout(500)
    tab.page.unroute("**/_/doc?*")
    assert tab.page.query_selector("#rd-popover .rd-pending-tell") is None


def interrupted_after_the_reload(tab):
    """Waits for the page to reload and for the thread of the one comment to open by itself, and says
    whether it shows the interrupted row (and no job still running)."""
    reloaded(tab.page, timeout=15)
    tab.page.wait_for_load_state()
    tab.page.wait_for_selector("#rd-menu-btn", state="attached")
    # a reload that knew the open thread opens it again by itself, as the upgrade's and the moved text's both do
    until(lambda: tab.page.query_selector("#rd-popover"), timeout=5, what="the thread to open again")
    tab.page.wait_for_selector("#rd-popover .rd-scroll")
    assert tab.page.query_selector("#rd-popover .rd-pending-tell") is None
    return tab.page.query_selector("#rd-popover .rd-interrupted") is not None


def test_the_interrupted_row_is_still_there_after_the_reload_a_new_version_brings(running_tell, site):
    mark(running_tell.page)
    site.stop("upgrade")
    site.start(version="99.0.0")         # a new boot and a new version: the page reloads onto the new script
    assert interrupted_after_the_reload(running_tell)


def test_the_interrupted_row_is_still_there_after_the_reload_moved_text_brings(running_tell, site):
    site.stop()
    site.file.write_text(site.file.read_text().replace("Last paragraph.", "Last paragraph, edited outside."),
                         encoding="utf-8")
    mark(running_tell.page)
    site.start()                         # a new boot, and the text moved while the hub was away
    assert interrupted_after_the_reload(running_tell)


def test_a_new_version_reloads_the_page_onto_the_new_script(tab, site):
    tab.open()
    mark(tab.page)
    site.stop("upgrade")
    site.start(version="99.0.0")
    reloaded(tab.page)
    until(lambda: tab.page.evaluate("JSON.parse(document.querySelector('script[type=\"application/json\"]')"
                                    ".textContent).version") == "99.0.0", what="the page of the new version")


def test_text_that_moved_while_the_hub_was_away_reloads_the_page_when_it_is_back(tab, site):
    tab.open()
    site.kill()
    site.file.write_text(site.file.read_text().replace("Last paragraph.", "Last paragraph, edited outside."),
                         encoding="utf-8")
    mark(tab.page)
    site.start()
    reloaded(tab.page, timeout=15)
    assert "edited outside" in tab.page.inner_text("main")


def test_text_that_moved_while_the_hub_was_away_is_settled_with_the_edits_and_reloaded(tab, site):
    tab.open()
    site.kill()
    type_at_end(tab.page, P2, " and plums")
    site.file.write_text(site.file.read_text().replace("Last paragraph.", "Last paragraph, edited outside."),
                         encoding="utf-8")
    mark(tab.page)
    site.start()
    reloaded(tab.page, timeout=15)
    md = site.file.read_text()
    assert "and plums" in md and "edited outside" in md       # the hub merged both


def test_a_rotated_key_is_told_as_a_sign_in_message_and_the_edits_are_kept_as_a_draft(tab, site):
    tab.open()
    tab.page.keyboard.press("e")
    # The text changes with no `input` event, so the 500 ms mirror of the draft is never scheduled:
    # a draft found afterwards was written by the sign-in message itself.
    tab.page.evaluate(f"document.querySelector({P2!r}).append(' and plums')")
    draft = f"localStorage.getItem({draft_key(site)!r})"
    site.kill()
    site.start(key=base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode())
    until(lambda: "not signed in" in notice(tab.page), timeout=15, what="the sign-in message")
    n = notice(tab.page)
    assert f"sheaf open {tab.site.url}" in n and "sheaf signin-url" in n
    assert "kept as a draft" in n
    d = tab.page.evaluate(draft)
    assert d and "plums" in d
    assert "plums" in tab.page.inner_text(P2)                 # still on screen


def test_a_tab_that_wrote_no_draft_leaves_the_draft_of_another_tab_alone_when_the_key_is_rotated(tab, context, site):
    # The sign-in path of the box beside the keystroke path (test_page_drafts.py): tab A is dirty, tab B is
    # clean, and B meets the 401 after A has written its draft. B's mirror of nothing must not remove A's.
    tab.open()
    other = context.new_page()
    other.goto(site.url)
    other.wait_for_selector("#rd-menu-btn", state="attached")
    held = []
    other.route("**/_/doc?*", lambda route: held.append(route))        # B asks what happened only when told
    seen, t0 = [], time.monotonic()
    other.on("request", lambda r: seen.append((round(time.monotonic() - t0, 1), f"asks {r.url.split('/_/')[-1][:12]}")))
    other.on("response", lambda r: seen.append((round(time.monotonic() - t0, 1),
                                                f"{r.status} {r.url.split('/_/')[-1][:12]}")))
    other.on("requestfailed", lambda r: seen.append((round(time.monotonic() - t0, 1),
                                                     f"failed {r.url.split('/_/')[-1][:12]}")))
    tab.page.keyboard.press("e")
    tab.page.evaluate(f"document.querySelector({P2!r}).append(' and plums')")
    site.kill()
    site.start(key=base64.urlsafe_b64encode(os.urandom(32)).rstrip(b"=").decode())
    until(lambda: "not signed in" in notice(tab.page), timeout=15, what="the sign-in message in tab A")
    draft = f"localStorage.getItem({draft_key(site)!r})"
    assert "plums" in (tab.page.evaluate(draft) or ""), "tab A wrote no draft"
    until(lambda: held, timeout=15, what="tab B to ask what the closed stream meant")
    seen.append((round(time.monotonic() - t0, 1), f"released {len(held)}"))
    for route in held:
        route.continue_()
    try:
        until(lambda: "not signed in" in notice(other), timeout=15, what="the sign-in message in tab B")
    except AssertionError as e:
        # Say what tab B saw, so that a failure on a slow runner names the step that did not happen.
        try:
            now = repr(notice(other))
        except Exception as unreadable:     # tab B closed or crashed: keep the rest of the message
            now = f"<unreadable: {unreadable}>"
        raise AssertionError(f"{e}; tab B's notice now: {now}; its /_/doc looks held in all: {len(held)}; "
                             f"its traffic since the key test began, as (seconds, what): {seen}") from None
    assert "plums" in (tab.page.evaluate(draft) or ""), "tab B removed the draft of tab A"


def test_a_new_boot_meets_the_popover_of_a_deleted_thread_that_holds_a_reply_without_a_script_error(running_tell):
    # The popover of a thread deleted elsewhere stays while a reply is typed; `touched` then drew the
    # thread that is gone, threw, and stopped `interruptJobs`.
    p, f = running_tell.page, running_tell.site.file
    p.click("#rd-popover button[data-a=reply]")
    p.fill("#rd-popover textarea", "my reply text")
    (c,) = rdc.parse(f.read_text()).comments
    f.write_text(rdc.delete(f.read_text(), c.id), encoding="utf-8")
    p.wait_for_selector("#rd-popover .rd-hold:has-text('deleted')")
    running_tell.site.stop()
    running_tell.site.start()            # a new boot: the page forgets its running jobs
    until(lambda: stream(p)["opens"] >= 2, what="the stream to come back")
    p.wait_for_timeout(500)
    assert running_tell.errors == []
    assert p.input_value("#rd-popover textarea") == "my reply text"


# ── a document that is no longer on the hub (8.2, 8.8, 10.7) ───────────────────


@pytest.fixture
def replying(tab):
    """A page with a paragraph edited and not saved, and the thread of a comment on 'apples' open with a
    reply typed and not sent. Its stream is watched, and every stream it opens from now on is counted
    (`tab.streams`)."""
    tab.page.add_init_script(WATCH)
    tab.open()
    comment_on(tab, at(P1, "apples"), at(P1, "apples", None), "Why apples?")
    tab.page.wait_for_selector("#rd-popover .rd-msg")
    tab.page.reload()
    tab.page.wait_for_selector("#rd-menu-btn", state="attached")
    until(lambda: stream(tab.page)["opens"] >= 1, what="the stream to open")
    tab.page.keyboard.press("e")
    # No `input` event, so no autosave and no mirror of the draft: the edit is on screen only.
    tab.page.evaluate(f"document.querySelector({P2!r}).append(' and plums')")
    tab.page.click(".rd-badge")
    tab.page.click("#rd-popover button[data-a=reply]")
    tab.page.fill("#rd-popover textarea", "my reply text")
    count_streams(tab)
    return tab


def count_streams(tab):
    """Every stream the page opens from now on is counted in `tab.streams`."""
    tab.streams = []
    tab.page.on("request", lambda r: tab.streams.append(r.url) if "/_/live?doc=" in r.url else None)


def kept_on_screen(tab):
    """What was typed is on screen still, and offered to copy in the notice."""
    p = tab.page
    assert p.input_value("#rd-popover textarea") == "my reply text"
    assert "and plums" in p.inner_text(P2)
    copy = p.input_value("#rd-notice textarea")
    assert "my reply text" in copy and "Second paragraph, about pears. and plums" in copy
    assert p.evaluate("document.querySelector('#rd-notice textarea').readOnly") is True


def does_not_reload_or_reconnect(tab, streams):
    """Past the stream's retry (2 s): the page neither reloaded nor opened its stream again."""
    tab.page.wait_for_timeout(3000)
    assert tab.page.evaluate("window.__same_load") is True, "the page reloaded"
    assert len(tab.streams) == streams, "the page opened its stream again"


def test_a_page_whose_root_is_forgotten_says_so_keeps_what_was_typed_and_saves_nothing(replying, site):
    p = replying.page
    mark(p)
    assert site.hub.forget_root("work").name == "work"
    until(lambda: GONE in notice(p), what="the notice that the document is gone")
    n = notice(p)
    assert "forgotten with sheaf roots forget" in n and "Nothing more can be saved from this page" in n
    kept_on_screen(replying)
    assert p.evaluate("document.querySelector('#rd-save').disabled") is True
    assert "plums" in (p.evaluate(f"localStorage.getItem({draft_key(site)!r})") or ""), "the edit is not kept as a draft"
    does_not_reload_or_reconnect(replying, 0)
    assert p.input_value("#rd-popover textarea") == "my reply text"


def test_a_page_with_nothing_typed_whose_root_is_forgotten_says_so_and_does_not_reload(tab, site):
    tab.page.add_init_script(WATCH)
    tab.open()
    until(lambda: stream(tab.page)["opens"] >= 1, what="the stream to open")
    count_streams(tab)
    mark(tab.page)
    assert site.hub.forget_root("work").name == "work"
    until(lambda: GONE in notice(tab.page), what="the notice that the document is gone")
    assert tab.page.query_selector("#rd-notice textarea") is None        # nothing to offer
    does_not_reload_or_reconnect(tab, 0)


def test_a_page_whose_root_was_forgotten_and_its_name_taken_while_its_stream_was_down_says_so_when_it_is_back(
        replying, site, tmp_path):
    """The page could not hear `gone`. Back, it finds another folder's document under its address, which
    never handed out the version the page holds: it says so, and neither reloads into that document nor
    sends anything to it."""
    p = replying.page
    cut(replying)
    assert site.hub.forget_root("work").name == "work"
    other = tmp_path / "y" / "work" / "plan.md"
    other.parent.mkdir(parents=True)
    other.write_text(PLAN.replace("apples", "cherries"), encoding="utf-8")
    assert site.hub.render(other, {}, None)["doc"] == DOC
    kept = other.read_text(encoding="utf-8")
    mark(p)
    site.reopen()
    until(lambda: GONE in notice(p), timeout=15, what="the notice that the document is gone")
    assert "another folder now holds its name" in notice(p)
    kept_on_screen(replying)
    streams, posts = len(replying.streams), []
    p.on("request", lambda r: posts.append(r.url) if r.method == "POST" and "/_/diag" not in r.url else None)
    p.keyboard.press("Control+s")
    toasted(p, "Nothing was sent or saved")
    p.evaluate(f"document.querySelector({P2!r}).lastChild.remove();"     # the edit undone, so the reply may go
               " document.querySelector('#rd-toast').textContent = ''")
    p.click("#rd-popover button[data-f=ok]")
    toasted(p, "Nothing was sent or saved")
    assert posts == []
    does_not_reload_or_reconnect(replying, streams)
    assert p.input_value("#rd-popover textarea") == "my reply text"
    assert other.read_text(encoding="utf-8") == kept


def test_a_page_whose_root_was_forgotten_while_its_stream_was_down_says_so_when_the_hub_has_no_such_document(
        replying, site):
    p = replying.page
    cut(replying)
    assert site.hub.forget_root("work").name == "work"
    mark(p)
    site.reopen()
    until(lambda: GONE in notice(p), timeout=15, what="the notice that the document is gone")
    assert "forgotten with sheaf roots forget. Nothing more can be saved" in notice(p)    # no other folder
    kept_on_screen(replying)
    does_not_reload_or_reconnect(replying, len(replying.streams))


def test_a_page_whose_file_moved_on_while_its_stream_was_down_holds_its_reload_for_the_form_as_before(replying, site):
    """The control: a version the document handed out, so not gone. The reload that the moved text needs
    waits for the reply being written."""
    p = replying.page
    cut(replying)
    site.file.write_text(site.file.read_text().replace("Last paragraph.", "Last paragraph, edited outside."),
                         encoding="utf-8")
    mark(p)
    site.reopen()
    p.wait_for_selector("#rd-popover .rd-hold", timeout=15_000)
    assert GONE not in notice(p)
    assert p.input_value("#rd-popover textarea") == "my reply text"
    assert p.evaluate("window.__same_load") is True


def test_a_page_whose_version_aged_out_and_whose_file_moved_on_while_its_stream_was_down_reloads_as_before(
        tab, site):
    """The store keeps 60 versions of a document, none older than 7 days (7.4): a page left open that long
    holds a version its document no longer knows, and is that document's page all the same, of the same
    root. Its stream back, it reloads onto the file as it is, as any page whose text moved."""
    from sheafmd.source import md_hash
    p = tab.page
    p.add_init_script(WATCH)
    tab.open()
    until(lambda: stream(p)["opens"] >= 1, what="the stream to open")
    held = md_hash(site.file.read_text(encoding="utf-8"))
    cut(tab)
    site.file.write_text(site.file.read_text().replace("Last paragraph.", "Last paragraph, edited outside."),
                         encoding="utf-8")
    e = site.hub.entry(DOC)
    site.hub.catch_up(e)                         # the hub took the new text in, as its watcher does
    e.live._versions.pop(held)                   # and the page's version aged out, in memory and on disk
    site.hub.versions.forget(DOC)
    assert not e.live.knows(held)
    mark(p)
    site.reopen()
    try:
        reloaded(p, timeout=15)
    except AssertionError:
        raise AssertionError(f"the page did not reload; its notice says {notice(p)!r}") from None
    p.wait_for_selector("#rd-menu-btn", state="attached")
    assert "edited outside" in p.inner_text("main") and GONE not in notice(p)


def test_a_page_whose_file_was_deleted_while_its_stream_was_down_tries_again_and_is_back_with_the_file(tab, site):
    """The file gone and its root still there (a branch switched while the stream was down, say): the hub
    answers 404, and the page tries again every 2 s, as before, and is back once the file is."""
    p = tab.page
    p.add_init_script(WATCH)
    tab.open()
    until(lambda: stream(p)["opens"] >= 1, what="the stream to open")
    text = site.file.read_text(encoding="utf-8")
    answers = []
    p.on("response", lambda r: answers.append(r.status) if "/_/doc?" in r.url else None)
    cut(tab)
    site.file.unlink()
    mark(p)
    site.reopen()
    until(lambda: 404 in answers or p.wait_for_timeout(20), timeout=15, what="the page to ask and be told 404")
    p.wait_for_timeout(500)
    assert GONE not in notice(p)
    until(lambda: answers.count(404) >= 2 or p.wait_for_timeout(20), timeout=15,
          what="the page to try again and be told 404 again")
    site.file.write_text(text, encoding="utf-8")
    until(lambda: stream(p)["opens"] >= 2, timeout=15, what="the stream to come back")
    p.wait_for_timeout(500)
    assert GONE not in notice(p) and p.evaluate("window.__same_load") is True
    site.file.write_text(text.replace("Last paragraph.", "Last paragraph, edited outside."), encoding="utf-8")
    reloaded(p, timeout=15)                      # it hears the file again


def test_a_new_version_reloads_onto_the_thread_that_was_open(tab, site):
    tab.page.add_init_script(WATCH)
    tab.open()
    comment_on(tab, at(P1, "apples"), at(P1, "apples", None), "Why apples?")
    tab.page.wait_for_selector("#rd-popover .rd-msg")
    mark(tab.page)
    site.stop("upgrade")
    site.start(version="99.0.0")
    reloaded(tab.page, timeout=15)
    until(lambda: tab.page.query_selector("#rd-popover .rd-msg"), timeout=5, what="the thread to open again")


# The page holds the answer of its save, as a slow hub would: the hub has written the file, the page does not
# know it yet.
HOLD_SAVES = """(() => {
  const was = window.fetch;
  window.__saves = {taken: 0};
  const gate = new Promise(r => { window.__saves.release = r; });
  window.fetch = async (u, o) => {
    const res = await was(u, o);
    if (String(u).includes('/_/save')) { window.__saves.taken++; await gate; }
    return res;
  };
})()"""


def test_a_reconnect_while_the_pages_own_save_is_out_does_not_reload_the_page(tab, site):
    tab.page.add_init_script(WATCH)
    tab.page.add_init_script(HOLD_SAVES)
    tab.open()
    until(lambda: stream(tab.page)["opens"] >= 1, what="the stream to open")
    type_at_end(tab.page, P2, " and plums")
    until(lambda: tab.page.evaluate("window.__saves.taken") >= 1, what="the hub to take the save")
    mark(tab.page)
    site.kill()
    until(lambda: stream(tab.page)["errors"] >= 1, what="the stream to fail")
    site.reopen()
    until(lambda: stream(tab.page)["opens"] >= 2, what="the stream to come back")
    tab.page.wait_for_timeout(1000)
    tab.page.evaluate("window.__saves.release()")
    tab.page.wait_for_timeout(1500)
    assert tab.page.evaluate("window.__same_load") is True, "the page reloaded for its own save"


# A save the hub never answers must not hold `saving` for as long as the page is open: typing would be blocked, and the
# counters of the writes in flight would never fall, so a reload the hub asks for would never run. The page stops waiting
# after 120 s, says the hub is unreachable and keeps the edits; the hub may have written the save all the same,
# so the next send is that save again, with the same request id (`rid`, SPEC 8.5), and the hub writes it once.
@pytest.mark.parametrize("written", [False, True], ids=["never-written", "written-late"])
def test_a_save_the_hub_does_not_answer_within_120_seconds_frees_the_page_and_the_next_send_is_the_same_save_again(
        tab, written):
    tab.open()
    p = tab.page
    reload_on_clock(p)
    type_at_end(p, P2, " and plums")
    held, bodies = [], []

    def hold_first(route):
        bodies.append(route.request.post_data_json)
        if not held:
            held.append(route)
            if written:
                route.fetch()               # the hub writes it; its answer is never given to the page
        else:
            route.continue_()

    p.route("**/_/save", hold_first)
    p.keyboard.press("Control+s")
    until(lambda: held or p.wait_for_timeout(20), what="the save to go out")
    p.clock.fast_forward(120_500)
    says = "The hub is unreachable; nothing was saved. Your edits stay on screen."
    toasted(p, says)
    assert "plums" in p.inner_text(P2)
    # the autosave that waited behind the held save goes out now, or Ctrl+S sends it: either is the next save
    p.keyboard.press("Control+s")
    until(lambda: len(bodies) >= 2, what="the next save to go out")
    p.unroute("**/_/save")
    assert re.fullmatch(r"[A-Za-z0-9_-]{16,64}", bodies[0]["rid"])
    again = bodies[1]                        # the same hash, the same edits, the same request id
    assert (again["rid"], again["hash"]) == (bodies[0]["rid"], bodies[0]["hash"])
    assert [(e["i"], e["html"]) for e in again["edits"]] == [(e["i"], e["html"]) for e in bodies[0]["edits"]]
    assert again["edits"][0]["saved"] == again["edits"][0]["html"]       # for a hub that forgot the id (a restart)
    until(lambda: "plums" in tab.site.file.read_text(encoding="utf-8"), what="the next save to be written")
    p.wait_for_timeout(500)
    text = tab.site.file.read_text(encoding="utf-8")
    assert text.count("plums") == 1          # a late write is answered `again`, not written a second time
    assert "at the same time" not in text
    until(lambda: stored(p, tab.site) is None, what="the draft to go once the save is taken")


def stored(page, site):
    got = page.evaluate(f"localStorage.getItem({draft_key(site)!r})")
    return json.loads(got) if got else None


# The draft the page mirrors is the text of a save that got no answer: it holds that save's request id, so a
# page reloaded or closed after the give-up asks the hub for it again instead of writing it a second time
# (SPEC 10.8). A draft of edits that were not sent holds none.
def test_the_draft_of_a_save_given_up_holds_its_request_id_and_the_hub_is_asked_for_it_again_on_restore(tab):
    tab.open()
    p = tab.page
    reload_on_clock(p)
    type_at_end(p, P2, " and plums")
    until(lambda: stored(p, tab.site), what="the draft of the typed edit")
    assert "rid" not in stored(p, tab.site)
    held, bodies = [], []

    def never_answer(route):
        bodies.append(route.request.post_data_json)
        if not held:
            held.append(route)         # the hub never gets it
        else:
            route.abort()              # nor does it get the save that goes again

    p.route("**/_/save", never_answer)
    p.keyboard.press("Control+s")
    until(lambda: held or p.wait_for_timeout(20), what="the save to go out")
    assert stored(p, tab.site)["rid"] == bodies[0]["rid"]            # from the moment it goes out
    p.clock.fast_forward(120_500)
    toasted(p, "The hub is unreachable; nothing was saved. Your edits stay on screen.")
    d = stored(p, tab.site)
    assert d["rid"] == bodies[0]["rid"] and d["hash"] == bodies[0]["hash"]
    context = p.context
    p.close()                           # only the draft is left
    p = context.new_page()
    sent = []
    p.on("request", lambda r: sent.append(r.post_data_json) if r.url.endswith("/_/save") else None)
    p.goto(tab.site.url)
    p.wait_for_selector("#rd-notice button[data-d=restore]")
    p.click("#rd-notice button[data-d=restore]")
    until(lambda: sent, what="the restore to go out")
    assert sent[0]["rid"] == bodies[0]["rid"]
    until(lambda: "plums" in tab.site.file.read_text(encoding="utf-8"), what="the restored edit to be written")
    assert tab.site.file.read_text(encoding="utf-8").count("plums") == 1


def test_a_page_opened_on_a_draft_the_hub_already_took_drops_it_without_restoring(tab):
    tab.open()
    p = tab.page
    reload_on_clock(p)
    type_at_end(p, P2, " and plums")
    held, bodies = [], []

    def written_never_answered(route):
        bodies.append(route.request.post_data_json)
        if not held:
            held.append(route)
            route.fetch()               # the hub writes it; its answer is never given to the page
        else:
            route.abort()

    p.route("**/_/save", written_never_answered)
    p.keyboard.press("Control+s")
    until(lambda: "plums" in tab.site.file.read_text(encoding="utf-8"), what="the hub to write the save")
    p.clock.fast_forward(120_500)
    toasted(p, "The hub is unreachable; nothing was saved. Your edits stay on screen.")
    assert stored(p, tab.site)["rid"] == bodies[0]["rid"]
    context = p.context
    p.close()
    p = context.new_page()              # a page opened on the same draft
    sent = []
    p.on("request", lambda r: sent.append(r.url) if r.url.endswith("/_/save") else None)
    p.goto(tab.site.url)
    p.wait_for_selector("#rd-menu-btn", state="attached")
    until(lambda: stored(p, tab.site) is None, what="the draft the hub already took to be dropped")
    assert p.query_selector("#rd-notice button[data-d=restore]") is None
    assert not sent
    assert tab.site.file.read_text(encoding="utf-8").count("plums") == 1



# ── notices and toasts ──────────────────────────────────────────────────────────

def test_an_autosave_while_the_hub_is_unreachable_says_nothing(tab):
    # The autosave fires 2.5 s after the last key and fails with the hub away; the banner (15 s) is
    # what tells the person, so the toast of a save they did not ask for stays out.
    tab.open()
    failed = []
    tab.page.on("requestfailed", lambda r: failed.append(r.url) if r.url.endswith("/_/save") else None)
    tab.site.kill()
    type_at_end(tab.page, P2, " and plums")
    until(lambda: failed or tab.page.wait_for_timeout(20), timeout=10, what="the autosave to go out")
    tab.page.wait_for_timeout(300)
    assert toast(tab.page) == ""
    assert "plums" in tab.page.inner_text(P2)


def test_the_signed_out_notice_goes_when_the_hub_says_hello_again(tab, site):
    # A hello clears the hub's own lines; the signed-out notice is one of them.
    tab.page.add_init_script(WATCH)
    tab.open()
    tab.page.keyboard.press("e")
    tab.page.evaluate(f"document.querySelector({P2!r}).append(' and plums')")      # on screen, not saved
    site.hub.entry(DOC).bus.publish("signed-out", {})
    until(lambda: "signed out" in notice(tab.page), what="the signed-out notice")
    until(lambda: stream(tab.page)["opens"] >= 2, timeout=15, what="the stream to come back")
    until(lambda: notice(tab.page) == "", what="the hello to clear the notice")
    assert "plums" in tab.page.inner_text(P2)


def test_the_ask_answer_notice_of_a_stale_page_does_not_tell_the_person_to_save(tab, site):
    # A stale page refuses Save, so the notice says what works: copy the edits, then reload.
    tab.open()
    c = comment_on(tab, at(P1, "apples"), at(P1, "apples", None), "Why apples?")
    tab.page.wait_for_selector("#rd-popover .rd-msg")
    tab.page.keyboard.press("Escape")
    tab.page.keyboard.press("e")
    tab.page.evaluate(f"document.querySelector({P2!r}).append(' and plums')")      # on screen, not saved
    site.hub.entry(DOC).bus.publish(
        "ask-done", {"id": c.id, "textSame": False, "base": "0" * 16, "comments": []})
    until(lambda: "answered comment" in toast(tab.page), what="the notice")
    says = toast(tab.page)
    assert "Save, then reload" not in says
    assert "copy your edits" in says.lower()


def test_an_ask_answer_measured_against_another_text_reloads_a_page_with_no_edits(tab, site):
    # The answer cannot be taken in place (the hub measured it against a text this page does not hold), and
    # nothing is typed: the page reloads onto the file.
    tab.open()
    c = comment_on(tab, at(P1, "apples"), at(P1, "apples", None), "Why apples?")
    tab.page.wait_for_selector("#rd-popover .rd-msg")
    tab.page.keyboard.press("Escape")
    mark(tab.page)
    site.hub.entry(DOC).bus.publish(
        "ask-done", {"id": c.id, "textSame": False, "base": "0" * 16, "comments": []})
    reloaded(tab.page)


def test_an_autosave_missed_in_a_short_outage_is_made_again_when_the_hub_answers(tab):
    # Silent while the hub is away, so it must not be forgotten: no banner has gone up (15 s), and without a
    # key pressed nothing else would save the edit.
    tab.page.add_init_script(WATCH)
    tab.open()
    failed = []
    tab.page.on("requestfailed", lambda r: failed.append(r.url) if r.url.endswith("/_/save") else None)
    tab.site.kill()
    type_at_end(tab.page, P2, " and plums")
    until(lambda: failed or tab.page.wait_for_timeout(20), timeout=10, what="the autosave to fail")
    assert "plums" not in tab.site.file.read_text()
    tab.site.reopen()
    until(lambda: "and plums" in tab.site.file.read_text() or tab.page.wait_for_timeout(50), timeout=15,
          what="the edit to be saved after the hub came back")

def test_an_autosave_missed_while_the_stream_stays_open_is_made_again_after_the_next_request_the_hub_answers(tab):
    # A network error on /_/save with the event stream up brings no hello and no banner, so the hello is not
    # what pays the edit that was owed: the next request the hub answers is.
    comment(tab.site.file, quote="apples", body="Why apples?")
    tab.page.add_init_script(WATCH)
    tab.open()
    failed = []
    tab.page.on("requestfailed", lambda r: failed.append(r.url) if r.url.endswith("/_/save") else None)
    opens = stream(tab.page)["opens"]
    tab.page.route("**/_/save", lambda route: route.abort())
    type_at_end(tab.page, P2, " and plums")
    until(lambda: failed or tab.page.wait_for_timeout(20), timeout=10, what="the autosave to fail")
    tab.page.unroute("**/_/save")
    tab.page.wait_for_timeout(500)
    assert "plums" not in tab.site.file.read_text()
    assert stream(tab.page)["opens"] == opens, "the stream was reopened: this is the hello's case"
    tab.page.click(".rd-badge")                 # an unread thread: opening it tells the hub it was read
    until(lambda: "and plums" in tab.site.file.read_text() or tab.page.wait_for_timeout(50), timeout=10,
          what="the owed autosave to be saved after the hub answered a request")


# ---- the gone notice's offer, and a file that is missing from a root that is still there ----



def beforeunload_asks(page):
    return page.evaluate("(() => { const e = new Event('beforeunload', {cancelable: true});"
                         " window.dispatchEvent(e); return e.defaultPrevented; })()")


def test_a_reply_that_only_the_drafts_store_holds_is_in_the_gone_notice_and_leaving_asks(tab, site):
    """A reply whose send failed while another thread was open is in no form: the store holds it, under the
    root's id, and a page of the folder that takes the name draws it for no thread. The notice offers it to
    copy as it offers what is on screen, and leaving the page asks, as it does for a block not saved."""
    p = tab.page
    p.add_init_script(WATCH)
    tab.open()
    until(lambda: stream(p)["opens"] >= 1, what="the stream to open")
    p.evaluate("(([k, v]) => localStorage.setItem(k, JSON.stringify(v)))", [comment_draft_key(site), [
        {"thread": "1", "born": "2026-10-22T10:00:00Z", "about": "apples", "kind": "reply",
         "body": "a reply only the store holds", "rid": "r1", "at": "2026-10-22T10:01:00Z"}]])
    assert not beforeunload_asks(p)            # its own page draws it again: nothing is lost by leaving
    mark(p)
    assert site.hub.forget_root("work").name == "work"
    until(lambda: GONE in notice(p), what="the notice that the document is gone")
    assert "a reply only the store holds" in p.input_value("#rd-notice textarea")
    assert beforeunload_asks(p)


def test_what_is_typed_and_is_also_in_the_store_is_offered_once(replying, site):
    p = replying.page
    p.evaluate("(([k, v]) => localStorage.setItem(k, JSON.stringify(v)))", [comment_draft_key(site), [
        {"thread": "1", "born": "x", "about": "apples", "kind": "reply", "body": "my reply text", "at": "x"}]])
    assert site.hub.forget_root("work").name == "work"
    until(lambda: GONE in notice(p), what="the notice that the document is gone")
    assert p.input_value("#rd-notice textarea").count("my reply text") == 1


def test_a_save_that_was_out_when_the_document_went_is_not_offered_as_plainly_not_saved(tab, site):
    """The save was sent before the folder was forgotten: the hub may have written it. The notice offers the
    text to copy all the same, and says so."""
    p = tab.page
    p.add_init_script(WATCH)
    tab.open()
    until(lambda: stream(p)["opens"] >= 1, what="the stream to open")
    held = []
    p.route("**/_/save", lambda route: held.append(route))        # the hub does not answer
    p.keyboard.press("e")
    p.evaluate(f"document.querySelector({P2!r}).append(' and plums')")
    p.keyboard.press("Control+s")
    until(lambda: held, what="the save to go out")
    assert site.hub.forget_root("work").name == "work"
    until(lambda: GONE in notice(p), what="the notice that the document is gone")
    assert "and plums" in p.input_value("#rd-notice textarea")
    assert "A save was still out" in notice(p)
    held[0].abort()


def test_a_page_with_no_save_out_is_not_told_one_may_have_gone_through(replying, site):
    assert site.hub.forget_root("work").name == "work"
    until(lambda: GONE in notice(replying.page), what="the notice that the document is gone")
    assert "A save was still out" not in notice(replying.page)


def test_a_change_heard_while_the_check_after_a_reconnect_is_out_does_not_reload_into_the_other_folder(
        tab, site, tmp_path):
    """The page's stream was down while its root was forgotten and another folder took the name. It is back
    and asks the hub what the document is (checkText); before the answer an event of the other folder's
    file reaches it. With nothing typed that would reload the page into that document: the answer says
    gone, and the event waits for it."""
    p = tab.page
    p.add_init_script(WATCH)
    tab.open()
    until(lambda: stream(p)["opens"] >= 1, what="the stream to open")
    cut(tab)
    assert site.hub.forget_root("work").name == "work"
    other = tmp_path / "y" / "work" / "plan.md"
    other.parent.mkdir(parents=True)
    other.write_text(PLAN.replace("apples", "cherries"), encoding="utf-8")
    assert site.hub.render(other, {}, None)["doc"] == DOC
    asked = []
    p.route("**/_/doc?*", lambda route: asked.append(route))      # the answer to the check is held
    mark(p)
    site.reopen()
    until(lambda: asked or p.wait_for_timeout(50), timeout=15, what="the page to ask what the document is")
    other.write_text(other.read_text(encoding="utf-8").replace("Last paragraph.", "Last, edited."), encoding="utf-8")
    site.hub.catch_up(site.hub.entry(DOC))             # the hub takes the new text in: a `changed`
    p.wait_for_timeout(1000)                                      # has gone out and been heard
    for r in asked:
        r.continue_()
    until(lambda: gone(p) or GONE in notice(p) or p.wait_for_timeout(50), timeout=15, what="the page to answer")
    assert not gone(p), "the page reloaded into the other folder's document"
    assert GONE in notice(p)
    p.wait_for_timeout(1500)
    assert p.evaluate("window.__same_load") is True


# Holds the page's asks of `/_/doc` once a stream has opened after `window.__holdFrom` opens: an `open` comes before
# its `hello`, so the check the `hello` starts is held and the retry's own asks (made while no stream is open) are not.
HOLD_DOC_AFTER_OPEN = """(() => {
  const ask = window.fetch;
  window.__holdFrom = Infinity;
  window.__held = 0;
  window.fetch = function (url, ...rest) {
    if (String(url).includes('/_/doc?') && window.__stream.opens > window.__holdFrom) {
      window.__held++;
      return new Promise(() => {});
    }
    return ask.call(this, url, ...rest);
  };
})()"""


def missing_past_the_grace(tab, init=None):
    """The hub back without the file (a branch switched) and the page's clock 20 s on: the outage banner has
    run its course and held its tongue (`lost`), and the notice says what is missing. Returns the file's text."""
    p, site = tab.page, tab.site
    p.add_init_script(WATCH)
    if init:
        p.add_init_script(init)
    p.clock.install(time=T0)
    tab.open()
    until(lambda: stream(p)["opens"] >= 1, what="the stream to open")
    text = site.file.read_text(encoding="utf-8")
    answers = []
    p.on("response", lambda r: answers.append(r.status) if "/_/doc?" in r.url else None)
    cut(tab)
    site.file.unlink()
    site.reopen()
    until(lambda: answers.count(404) >= 1 or p.wait_for_timeout(50), timeout=15, what="the page to be told 404")
    p.clock.pause_at(T0 + 60_000)
    assert p.evaluate("document.querySelector('#rd-state').textContent") == "File missing"    # at once, not at 15 s
    p.clock.run_for(20_000)
    run_until(p, lambda: "file is not on the hub" in notice(p), "the notice that the file is missing")
    return text


def run_until(p, done, what):
    """Runs the page's clock a second at a time until `done()`."""
    until(lambda: done() or p.clock.run_for(1_000), timeout=15, what=what)


def test_a_file_missing_from_a_root_that_is_there_says_so_and_not_that_the_hub_is_unreachable(tab, site):
    """The hub answers, and what is missing is the file (a branch switched). After the grace the page said
    'Hub unreachable', which it is not."""
    p = tab.page
    text = missing_past_the_grace(tab)
    assert "Hub unreachable" not in notice(p) and "Hub unreachable" not in p.inner_text("#rd-menu-btn")
    assert GONE not in notice(p)
    site.file.write_text(text, encoding="utf-8")                  # the file is back: the notice goes
    p.clock.run_for(6_000)
    run_until(p, lambda: notice(p) == "", "the notice to go when the file is back")


def test_a_hub_that_dies_after_the_file_went_missing_past_the_grace_gets_the_unreachable_banner(tab, site):
    """The banner had held its tongue for the missing file; when the hub stops answering at all, the file is
    no longer what is wrong and nothing said so: the line was cleared and no banner came."""
    p = tab.page
    missing_past_the_grace(tab)
    site.kill()
    run_until(p, lambda: "Hub unreachable" in notice(p), "the banner that the hub is unreachable")
    assert "file is not on the hub" not in notice(p)
    assert p.evaluate("document.querySelector('#rd-state').textContent") == "Hub unreachable"


@pytest.mark.parametrize("status, kind, body", [
    (502, "text/html", "<html>Bad gateway</html>"),
    (503, "application/json", '{"error": "unavailable"}'),
    (504, "text/html", "<html>Gateway timeout</html>"),
    (404, "text/html", "<html>Not found</html>"),            # a proxy's page, not the hub's JSON 404
])
def test_a_proxy_answering_in_place_of_the_hub_while_the_file_is_missing_gets_the_unreachable_banner(
        tab, site, status, kind, body):
    """The page asks what the address is (`/_/doc`) and the answer is the proxy's, not the hub's: the hub is
    not answering, whatever the file is doing. A 5xx fell through every branch and left the file-missing
    line up; a 404 that is not JSON threw in `r.json()` into the catch that cleared it without a banner."""
    p = tab.page
    missing_past_the_grace(tab)
    p.route("**/_/doc?*", lambda route: route.fulfill(status=status, content_type=kind, body=body))
    run_until(p, lambda: "Hub unreachable" in notice(p), "the banner that the hub is unreachable")
    assert "file is not on the hub" not in notice(p)


def test_the_menu_does_not_say_file_missing_once_the_file_is_back(tab, site):
    """The `hello` takes the notice away; the menu must follow at once, not when some later answer redraws it
    (the check after the `hello` is held here, as it is on a slow hub)."""
    p = tab.page
    text = missing_past_the_grace(tab, HOLD_DOC_AFTER_OPEN)
    assert p.evaluate("document.querySelector('#rd-state').textContent") == "File missing"
    p.evaluate("window.__holdFrom = window.__stream.opens")      # asks from the next open stream on are held
    site.file.write_text(text, encoding="utf-8")
    run_until(p, lambda: notice(p) == "", "the notice to go when the file is back")
    until(lambda: p.evaluate("window.__held") >= 1, what="the check after the hello to be asked (and held)")
    assert p.evaluate("document.querySelector('#rd-state').textContent") == "Ready"
    assert p.evaluate("document.querySelector('#rd-menu-btn').title") == "Ready"


def test_an_older_answer_to_what_the_address_is_does_not_undo_a_newer_one(tab, site):
    """Two asks are out at once (the tab shown again opens a second stream while the first ask waits): the
    newer one finds the file there, and the older one, answered last, still said it was missing."""
    p = tab.page
    p.add_init_script(WATCH)
    tab.open()
    until(lambda: stream(p)["opens"] >= 1, what="the stream to open")
    text = site.file.read_text(encoding="utf-8")
    asked = []

    def ask(route):
        asked.append(route)
        if len(asked) == 2:
            site.file.write_text(text, encoding="utf-8")        # the file is back by the time of the newer ask
            route.continue_()

    p.route("**/_/doc?*", ask)
    cut(tab)
    site.file.unlink()
    site.reopen()
    until(lambda: asked or p.wait_for_timeout(50), timeout=15, what="the first ask")
    show_tab(p, True)                                                   # a second stream, and a second ask
    until(lambda: len(asked) >= 2 or p.wait_for_timeout(50), timeout=15, what="the second ask")
    p.wait_for_timeout(500)
    asked[0].fulfill(status=404, content_type="application/json", body="{}")        # the older, last
    p.wait_for_timeout(1500)
    assert "file is not on the hub" not in notice(p)
    assert p.evaluate("document.querySelector('#rd-state').textContent") != "File missing"


def test_a_check_after_a_reconnect_that_finds_the_file_missing_says_so(tab, site):
    """The stream is back (the hub says hello) and the page asks what the address is: the answer is a 404
    that names this root, so the file is missing, as when the stream is the one to find it out."""
    p = tab.page
    p.add_init_script(WATCH)
    tab.open()
    until(lambda: stream(p)["opens"] >= 1, what="the stream to open")
    root = p.evaluate(f"fetch('/_/doc?doc=' + encodeURIComponent({DOC!r})).then(r => r.json()).then(j => j.root)")
    assert root
    cut(tab)
    p.route("**/_/doc?*", lambda route: route.fulfill(status=404, content_type="application/json",
                                                       body=json.dumps({"error": "no such document", "root": root})))
    site.reopen()
    until(lambda: "file is not on the hub" in notice(p) or p.wait_for_timeout(50), timeout=15,
          what="the notice that the file is missing")
    assert p.evaluate("document.querySelector('#rd-state').textContent") == "File missing"


def test_an_older_check_that_finds_the_file_missing_does_not_undo_a_newer_one_that_finds_it(tab, site):
    """Two reconnects, two checks out at once (checkText): the newer finds the file there, and the older,
    answered last, says it is missing."""
    p = tab.page
    p.add_init_script(WATCH)
    tab.open()
    until(lambda: stream(p)["opens"] >= 1, what="the stream to open")
    root = p.evaluate(f"fetch('/_/doc?doc=' + encodeURIComponent({DOC!r})).then(r => r.json()).then(j => j.root)")
    asked = []
    p.route("**/_/doc?*", lambda route: asked.append(route))
    for n in (1, 2):
        site.kill()
        until(lambda: stream(p)["errors"] >= n, what="the stream to fail")
        site.reopen()
        until(lambda: len(asked) >= n or p.wait_for_timeout(50), timeout=15, what=f"check {n} to be asked")
    asked[1].continue_()                                                # the newer: the file is there
    p.wait_for_timeout(500)
    asked[0].fulfill(status=404, content_type="application/json",
                     body=json.dumps({"error": "no such document", "root": root}))        # the older, last
    p.wait_for_timeout(1500)
    assert "file is not on the hub" not in notice(p)
    assert p.evaluate("document.querySelector('#rd-state').textContent") != "File missing"


def test_a_change_held_behind_the_pages_own_write_waits_for_the_check_that_write_put_off(tab, site, tmp_path):
    """As above, but the page's own save is out when its stream is back, so the check is put off until the
    save is answered; the event that came meanwhile is held with it, and must not be heard before the check."""
    p = tab.page
    p.add_init_script(WATCH)
    tab.open()
    until(lambda: stream(p)["opens"] >= 1, what="the stream to open")
    cut(tab)
    assert site.hub.forget_root("work").name == "work"
    other = tmp_path / "y" / "work" / "plan.md"
    other.parent.mkdir(parents=True)
    other.write_text(PLAN.replace("apples", "cherries"), encoding="utf-8")
    assert site.hub.render(other, {}, None)["doc"] == DOC
    held = []
    p.route("**/_/save", lambda route: held.append(route))
    p.keyboard.press("e")
    p.evaluate(f"document.querySelector({P2!r}).append(' and plums')")
    p.keyboard.press("Control+s")
    until(lambda: held or p.wait_for_timeout(50), what="the save to go out")
    mark(p)
    site.reopen()
    until(lambda: stream(p)["opens"] >= 2 or p.wait_for_timeout(50), timeout=15, what="the stream to be back")
    other.write_text(other.read_text(encoding="utf-8").replace("Last paragraph.", "Last, edited."), encoding="utf-8")
    site.hub.catch_up(site.hub.entry(DOC))
    p.wait_for_timeout(1000)
    held[0].fulfill(status=200, content_type="application/json",
                    body='{"ok": true, "hash": "x", "changed": [1]}')
    until(lambda: gone(p) or GONE in notice(p) or p.wait_for_timeout(50), timeout=15, what="the page to answer")
    assert not gone(p), "the page reloaded into the other folder's document"
    assert GONE in notice(p)


# ---- a sheaf the hub moved (9.11) ----

def moved_to(site):
    """A second file of the root, where the hub says the page's sheaf now lives."""
    f = site.file.parent / "moved.md"
    f.write_text(PLAN, encoding="utf-8")
    site.hub.roots.for_document(f)
    return "work/moved.md"


def test_a_page_whose_sheaf_the_hub_moved_goes_to_its_new_address(tab, site):
    p = tab.page
    p.add_init_script(WATCH)
    tab.open()
    until(lambda: stream(p)["opens"] >= 1, what="the stream to open")
    to = moved_to(site)
    site.hub.entry(DOC).bus.publish("moved", {"doc": DOC, "to": to})
    until(lambda: p.url == f"{site.base}/{to}" or p.wait_for_timeout(20), what="the page at the new address")
    p.wait_for_selector("#rd-menu-btn", state="attached")


def test_a_page_with_unsaved_text_stays_when_its_sheaf_moved_and_links_to_where_it_went(tab, site):
    p = tab.page
    p.add_init_script(WATCH)
    tab.open()
    until(lambda: stream(p)["opens"] >= 1, what="the stream to open")
    p.keyboard.press("e")
    p.evaluate(f"document.querySelector({P2!r}).append(' and plums')")      # on screen, not saved
    to = moved_to(site)
    site.hub.entry(DOC).bus.publish("moved", {"doc": DOC, "to": to})
    until(lambda: "This sheaf moved to" in notice(p), what="the notice that the sheaf moved")
    assert p.url == site.url and "and plums" in p.inner_text(P2)
    assert p.get_attribute("#rd-notice a", "href") == f"/{to}"
