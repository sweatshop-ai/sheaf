"""Seven tabs in one browser (ticket 160). A browser opens six connections to a host at most, and
each sheaf tab held one for its event stream: the seventh page never loaded, and a comment sent
from any tab waited for ever. The tabs now share one stream (page/live.js): the seventh loads at
once, the hub counts every tab, and a change on disk still reaches all of them."""
import time

import pytest

from sheafmd import comments as rdc
from sheafmd.source import update_file
from pagehelp import DOC, RELOADING, close_context, new_context, until, rewrite

pytestmark = pytest.mark.page

TABS = 7


@pytest.fixture
def shared(chromium, site):
    c = new_context(chromium, shared=True, viewport={"width": 1100, "height": 800})
    c.add_cookies([site.cookie()])
    yield c
    close_context(c)


def opened(context, site):
    p = context.new_page()
    errors = []
    p.on("pageerror", lambda e: errors.append(str(e)))
    p.goto(site.url)
    p.wait_for_selector("#rd-menu-btn", state="attached")
    return p, errors


def shows(p, text):
    """Whether the page shows `text`. A change from outside reloads the page, so a read can fall on the reload:
    that is not yet."""
    try:
        return text in p.evaluate("document.body.textContent")
    except Exception as e:
        if any(said in str(e) for said in RELOADING):
            return False
        raise


def badges(p):
    """How many comment badges the page shows; a read that falls on a reload counts none."""
    try:
        return p.evaluate("document.querySelectorAll('.rd-badge').length")
    except Exception as e:
        if any(said in str(e) for said in RELOADING):
            return 0
        raise


def test_seven_tabs_load_count_and_all_hear_a_change(shared, site):
    pages = [opened(shared, site) for _ in range(TABS - 1)]
    until(lambda: site.hub.tabs(DOC) == TABS - 1, what="six tabs counted by the hub")
    t0 = time.monotonic()
    pages.append(opened(shared, site))
    assert time.monotonic() - t0 < 1.0, "the seventh tab took more than a second to load"
    until(lambda: site.hub.tabs(DOC) == TABS, what="seven tabs counted by the hub")
    f = site.file
    rewrite(f, f.read_text(encoding="utf-8") + "\nFrom outside.\n")
    for n, (p, _) in enumerate(pages):
        until(lambda: shows(p, "From outside."),
              what=f"the change in tab {n + 1}")
    assert [e for _, e in pages] == [[]] * TABS


def test_a_tab_that_closes_leaves_the_count_and_the_leaders_tab_hands_over(shared, site):
    pages = [opened(shared, site) for _ in range(3)]
    until(lambda: site.hub.tabs(DOC) == 3, what="three tabs counted")
    pages[0][0].close()          # the first tab took the lock: the stream moves to another
    until(lambda: site.hub.tabs(DOC) == 2, what="two tabs counted")
    f = site.file
    rewrite(f, f.read_text(encoding="utf-8") + "\nAfter the hand-over.\n")
    for p, _ in pages[1:]:
        until(lambda: shows(p, "After the hand-over."), what="the change heard")
    # A change from outside reloads both pages; the hub drops a closed page's stream within its next read check.
    until(lambda: site.hub.tabs(DOC) == 2, what="two tabs counted after the reload")


def test_a_frozen_leader_hands_the_stream_over_and_takes_it_back_on_resume(shared, site):
    """Chrome freezes a background tab (memory saver, battery saver). A frozen leader keeps its lock and relays
    nothing, so the visible tabs would stop hearing changes. On `freeze` it lets go; on `resume` it queues again."""
    pages = [opened(shared, site) for _ in range(3)]
    until(lambda: site.hub.tabs(DOC) == 3, what="three tabs counted")
    leader = pages[0][0]         # the first tab took the lock
    cdp = shared.new_cdp_session(leader)
    cdp.send("Page.enable")
    cdp.send("Page.setWebLifecycleState", {"state": "frozen"})
    f = site.file
    f.write_text(f.read_text(encoding="utf-8") + "\nWhile frozen.\n", encoding="utf-8")
    for n, (p, _) in enumerate(pages[1:], 2):
        until(lambda: shows(p, "While frozen."), what=f"the change in tab {n} while the leader is frozen")
    cdp.send("Page.setWebLifecycleState", {"state": "active"})
    until(lambda: site.hub.tabs(DOC) == 3, what="three tabs counted after the resume")
    f.write_text(f.read_text(encoding="utf-8") + "\nAfter the resume.\n", encoding="utf-8")
    for n, (p, _) in enumerate(pages):
        until(lambda: shows(p, "After the resume."), what=f"the change in tab {n + 1} after the resume")


def test_a_frozen_tab_that_waits_for_the_lock_is_not_handed_it(shared, site):
    """The leader and a second tab freeze together: the lock must pass to the third, not to the frozen second,
    whose request was queued and could never run."""
    pages = [opened(shared, site) for _ in range(3)]
    until(lambda: site.hub.tabs(DOC) == 3, what="three tabs counted")
    for p, _ in pages[:2]:
        shared.new_cdp_session(p).send("Page.setWebLifecycleState", {"state": "frozen"})
    f = site.file
    f.write_text(f.read_text(encoding="utf-8") + "\nWith two tabs frozen.\n", encoding="utf-8")
    until(lambda: shows(pages[2][0], "With two tabs frozen."), what="the change in the third tab")


def test_a_tab_that_leaves_without_a_leave_is_dropped_when_its_lock_frees(shared, site):
    """A tab that crashes sends no `pagehide` and says nothing: only its Web Lock is freed. The leader must hear
    that from the lock itself, not from a poll every SWEEP (2 s), which Chrome slows to once a minute in a tab
    hidden for five minutes. The tab here says nothing (its `leave` is dropped) and closes."""
    pages = [opened(shared, site) for _ in range(3)]
    until(lambda: site.hub.tabs(DOC) == 3, what="three tabs counted")
    # Its `pagehide` must not tell the leader: only the freed lock may.
    pages[2][0].evaluate("BroadcastChannel.prototype.postMessage = function () {}")
    pages[2][0].close()
    until(lambda: site.hub.tabs(DOC) == 2, timeout=1.0, what="two tabs counted after the tab went")


def test_a_comment_written_while_the_leader_hands_over_reaches_the_tabs(shared, site):
    """An event the hub emits after the old leader's stream closed and before a tab joins the new one reaches no
    tab. The page makes up for it on the `hello` of its new join: `checkText` reads the document again, and a
    comment or reply is in the file, so the hash it compares has moved. The joins are held here, in every tab, so
    the gap is as long as the test wants: the leader closes, a comment is written, and only then do the tabs join.
    (The index page reads its list again on every `hello`, `soon()` in page/index.js.)"""
    pages = [opened(shared, site) for _ in range(3)]
    until(lambda: site.hub.tabs(DOC) == 3, what="three tabs counted")
    for p, _ in pages:
        p.evaluate("""(() => {
          const send = window.fetch; let open; const gate = new Promise(r => { open = r; });
          window.__held = 0; window.__release = open;
          window.fetch = function (u, i) {
            if (String(u).includes('/_/live/join')) { window.__held++; return gate.then(() => send.call(window, u, i)); }
            return send.apply(this, arguments);
          };
        })()""")
    pages[0][0].close()          # its stream ends; the lock passes to another tab, whose join waits on the gate
    until(lambda: sum(p.evaluate("window.__held") for p, _ in pages[1:]) >= 1, what="a join held")
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "apples"), "apples", "Why?",
                                                     "Ada", "2026-10-14T10:00")[0])
    # No tab holds a stream now, so the watcher skips the document (`catch_up` in hub/core.py): the hub takes the
    # write in as a request for the page would, and the `comments` event it emits reaches no tab.
    e = site.hub.entries[DOC]
    until(lambda: (site.hub.catch_up(e), "Why?" in e.live.current()[1])[1], what="the hub reading the comment")
    for p, _ in pages[1:]:
        p.evaluate("window.__release()")
    for n, (p, _) in enumerate(pages[1:], 2):
        until(lambda: badges(p) >= 1,
              what=f"the comment in tab {n}")
    assert [e for _, e in pages[1:]] == [[]] * 2


def test_a_join_refused_for_another_owner_reopens_the_shared_stream(shared, site):
    """Proxy mode, two members in one browser one after the other: the leader's connection belongs to the first, and
    the hub answers 404 `no such stream` to the second's joins until the connection ends (up to 300 s). The leader
    opens its connection again, which belongs to whoever asks now. Stood in for here: three tabs are open on the
    first connection, which then answers every join 404 as the hub does for another owner, and all three join at once."""
    seen, stale, at = [], [], []

    def refuse(route):
        sid = route.request.post_data_json["stream"]
        seen.append(sid)
        at.append(time.monotonic())
        if sid in stale:
            route.fulfill(status=404, content_type="application/json",
                          body='{"ok": false, "error": "no such stream"}')
        else:
            route.continue_()
    shared.route("**/_/live/join", refuse)
    pages = [opened(shared, site) for _ in range(3)]
    until(lambda: site.hub.tabs(DOC) == 3, what="three tabs counted")
    stale.append(seen[-1])
    for p, _ in pages:
        p.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}))")
    until(lambda: seen[-1] not in stale and site.hub.tabs(DOC) == 3, what="the three tabs counted on the reopened stream")
    pages[0][0].wait_for_timeout(3500)   # a refused tab asks again after 2 s: no join comes that late (not time.sleep:
                                         # Playwright answers a routed request only while the test waits on it)
    # A tab whose pageshow join reaches the leader after the new connection opened joins twice at once; harmless.
    fresh = [t for sid, t in zip(seen, at) if sid not in stale]
    assert len(fresh) >= 3 and fresh[-1] - fresh[0] < 1.5, "a refused tab joined again after the retry"
    f = site.file
    rewrite(f, f.read_text(encoding="utf-8") + "\nOn the new stream.\n")
    for n, (p, errors) in enumerate(pages, 1):
        until(lambda: shows(p, "On the new stream."), what=f"the change in tab {n}")
        assert errors == []


def test_a_join_refused_again_at_once_is_not_retried_in_a_loop(shared, site):
    """A hub that refuses every join (404 whatever the stream) gets the leader's connection opened again at most once
    in RETRY (2 s). Two tabs, so a refused batch holds two joins: a leader that set a reopen for each refusal would
    open two connections back to back. The page's own clock times the opens: a slow leader only spreads them, so the
    shortest gap tells a loop from a slow page, which a count of connections in a fixed time does not."""
    sids = set()

    def refuse(route):
        sids.add(route.request.post_data_json["stream"])
        route.fulfill(status=404, content_type="application/json", body='{"ok": false, "error": "no such stream"}')
    shared.route("**/_/live/join", refuse)
    shared.add_init_script("""(() => { const E = window.EventSource; if (!E) return; window.__opens = [];
      window.EventSource = function (u, o) {
        if (String(u).includes('shared=')) window.__opens.push(Date.now());
        return new E(u, o);
      };
      window.EventSource.prototype = E.prototype;
      ['CONNECTING', 'OPEN', 'CLOSED'].forEach(k => { window.EventSource[k] = E[k]; }); })()""")
    pages = [opened(shared, site) for _ in range(2)]
    pages[0][0].wait_for_timeout(9000)   # not time.sleep: Playwright answers a routed request only while the test waits
    opens = sorted(t for p, _ in pages for t in p.evaluate("window.__opens"))
    # The first connection is opened again at the first refusal, at once; the reopens after it wait for RETRY.
    reopens = opens[1:]
    assert len(reopens) >= 3, opens      # nothing timed otherwise
    gaps = [b - a for a, b in zip(reopens, reopens[1:])]
    assert min(gaps) >= 1500, gaps       # RETRY is 2000; the page's timers never fire early, a loop opens at once
    assert len(sids) >= 3, sids          # the opens were the leader's, and each was refused


def test_a_page_restored_from_the_back_forward_cache_joins_the_stream_again(shared, site):
    """`pagehide` sends the leaves. A page the browser keeps and shows again (`pageshow` with `persisted`) must
    join again: Chrome keeps no page that holds a Web Lock, Firefox and Safari were not checked."""
    pages = [opened(shared, site) for _ in range(2)]
    until(lambda: site.hub.tabs(DOC) == 2, what="two tabs counted")
    second = pages[1][0]
    second.evaluate("window.dispatchEvent(new PageTransitionEvent('pagehide', {persisted: true}))")
    until(lambda: site.hub.tabs(DOC) == 1, what="one tab counted after its pagehide")
    second.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}))")
    until(lambda: site.hub.tabs(DOC) == 2, what="two tabs counted after its pageshow")
    f = site.file
    rewrite(f, f.read_text(encoding="utf-8") + "\nAfter the restore.\n")
    until(lambda: shows(second, "After the restore."), what="the change in the restored tab")


def test_a_join_refused_again_just_after_a_reopen_opens_once_more_and_closes_no_stream(shared, site):
    """A reopened connection whose joins are refused too (a second rollover or member switch within 2 s) must not
    close the tab's streams for good: the leader opens once more when its 2 s are up, and the streams join that."""
    order, refuse = [], set()

    def route(r):
        sid = r.request.post_data_json["stream"]
        if sid not in order:
            order.append(sid)
            if refuse and len(refuse) < 2:
                refuse.add(sid)          # the first connection opened after the trigger is refused too
        if sid in refuse:
            r.fulfill(status=404, content_type="application/json", body='{"ok": false, "error": "no such stream"}')
        else:
            r.continue_()
    shared.route("**/_/live/join", route)
    p, errors = opened(shared, site)
    until(lambda: site.hub.tabs(DOC) == 1, what="one tab counted")
    p.evaluate("""() => { window.__st = []; var s = window.__probe = SheafLive.source(%r);
                          s.onerror = function () { window.__st.push(s.readyState); }; }""" % DOC)
    until(lambda: p.evaluate("window.__probe.readyState") == 1, what="the probe stream open")
    refuse.add(order[-1])
    p.evaluate("window.dispatchEvent(new PageTransitionEvent('pageshow', {persisted: true}))")
    until(lambda: len(order) >= 3, timeout=10, what="a third connection, opened once the 2 s were up")
    until(lambda: p.evaluate("window.__probe.readyState") == 1, timeout=10, what="the probe stream open again")
    assert 2 not in p.evaluate("window.__st"), "a stream was closed for good"
    assert len(refuse) == 2
    f = site.file
    rewrite(f, f.read_text(encoding="utf-8") + "\nOn the third connection.\n")
    until(lambda: shows(p, "On the third connection."), what="the change on the page")
    assert errors == []
