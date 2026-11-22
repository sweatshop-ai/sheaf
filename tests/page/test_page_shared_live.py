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


# Every join of the tab waits until the test calls `window.__release()`; `window.__held` counts the joins held.
HOLD_JOINS_JS = """(() => {
  const send = window.fetch; let open; const gate = new Promise(r => { open = r; });
  window.__held = 0; window.__release = open;
  window.fetch = function (u, i) {
    if (String(u).includes('/_/live/join')) { window.__held++; return gate.then(() => send.call(window, u, i)); }
    return send.apply(this, arguments);
  };
})()"""


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


# A frozen tab, as the tests make one. CDP `Page.setWebLifecycleState {state: "frozen"}` freezes nothing here: in the
# headless shell, in full Chromium (new headless) and headed under Xvfb, the tab's `freeze` listener never ran, the
# tab still ran script, and it kept `sheaf-live` for 40 s and more (ticket 176). Chromium freezes only a hidden page,
# and every page Playwright drives stays `visible`. So these tests dispatch `freeze` and `resume` on the document and
# mute the tab's BroadcastChannels in between, as a frozen tab hears and says nothing. They test page/live.js's
# listeners and what the other tabs do once a leader lets go, not that Chrome fires the events.
FREEZABLE_JS = """(() => {
  const Native = window.BroadcastChannel, post = Native.prototype.postMessage;
  window.__frozen = false;
  window.__queued = [];        // what the tab's channels received while frozen, delivered after `resume` as Chrome does
  window.BroadcastChannel = class extends Native {
    constructor(name) {
      super(name);
      // Added before the page sets `onmessage`, so it runs first and holds a message back from a frozen tab.
      super.addEventListener('message', ev => {
        if (window.__frozen && !ev.__replayed) { ev.stopImmediatePropagation(); window.__queued.push([this, ev.data]); }
      });
    }
    postMessage(m) { if (!window.__frozen) post.call(this, m); }
  };
  window.__thaw = () => {
    window.__frozen = false;
    document.dispatchEvent(new Event('resume'));
    const q = window.__queued.splice(0);
    q.forEach(([chan, data]) => { const ev = new MessageEvent('message', { data }); ev.__replayed = true; chan.dispatchEvent(ev); });
  };
})()"""

# This tab's Web Locks client id: the holder of a lock it takes for a moment.
CLIENT_ID_JS = """() => { const n = 'id-' + Math.random();
  return navigator.locks.request(n, () => navigator.locks.query().then(s => s.held.find(l => l.name === n).clientId)); }"""
HOLDER_JS = "() => navigator.locks.query().then(s => (s.held.find(l => l.name === 'sheaf-live') || {}).clientId || null)"


def freeze(p):
    """What Chrome does to a background tab it freezes, as far as the other tabs can tell: `freeze` fires, then the tab
    sends nothing and hears nothing until it resumes (FREEZABLE_JS: its channels only; timers and fetches still run)."""
    p.evaluate("() => { document.dispatchEvent(new Event('freeze')); window.__frozen = true; }")


def resume(p):
    """The tab is thawed: `resume` fires, then what its channels received while frozen is delivered."""
    p.evaluate("() => window.__thaw()")


def holder(p):
    """The client id that holds `sheaf-live`, read in tab `p`; a read that falls on a reload is None."""
    try:
        return p.evaluate(HOLDER_JS)
    except Exception as e:
        if any(said in str(e) for said in RELOADING):
            return None
        raise


def freezable(context, site):
    """Three tabs that can be frozen, counted by the hub, and their Web Locks client ids; the first holds the lock."""
    context.add_init_script(FREEZABLE_JS)
    pages = [opened(context, site) for _ in range(3)]
    until(lambda: site.hub.tabs(DOC) == 3, what="three tabs counted")
    ids = [p.evaluate(CLIENT_ID_JS) for p, _ in pages]
    until(lambda: holder(pages[1][0]) == ids[0], what="the first tab holding the lock")
    return pages, ids


def test_a_frozen_leader_hands_the_stream_over_and_takes_it_back_on_resume(shared, site):
    """Chrome freezes a background tab (memory saver, battery saver). A frozen leader would keep its lock and relay
    nothing, so the visible tabs would stop hearing changes. On `freeze` it lets go; on `resume` it queues again.
    The freeze is dispatched, not Chrome's (FREEZABLE_JS): this tests the listeners, not the browser's lifecycle."""
    pages, ids = freezable(shared, site)
    leader = pages[0][0]
    freeze(leader)
    until(lambda: holder(pages[1][0]) in ids[1:], what="the lock passed to a tab that is not frozen")
    until(lambda: site.hub.tabs(DOC) == 2, what="the frozen tab no longer counted")
    f = site.file
    f.write_text(f.read_text(encoding="utf-8") + "\nWhile frozen.\n", encoding="utf-8")
    for n, (p, _) in enumerate(pages[1:], 2):
        until(lambda: shows(p, "While frozen."), what=f"the change in tab {n} while the leader is frozen")
    assert not shows(leader, "While frozen."), "the frozen tab heard a change: it was not muted"
    until(lambda: site.hub.tabs(DOC) == 2, what="two tabs counted after their reload")
    resume(leader)
    until(lambda: site.hub.tabs(DOC) == 3, what="three tabs counted after the resume")
    f.write_text(f.read_text(encoding="utf-8") + "\nAfter the resume.\n", encoding="utf-8")
    for n, (p, _) in enumerate(pages):
        until(lambda: shows(p, "After the resume."), what=f"the change in tab {n + 1} after the resume")
    assert [e for _, e in pages] == [[]] * 3


def test_a_frozen_tab_that_waits_for_the_lock_is_not_handed_it(shared, site):
    """The leader and the second tab freeze: the lock must pass to the third, not to the second, whose request was
    queued first and whose callback could not run. The second freezes first, so that its request is still queued
    when the leader lets go; a dispatched freeze leaves the tab's script running, so had the request stayed, the
    second would take the lock (and, muted, relay to nobody). The freeze is dispatched (FREEZABLE_JS)."""
    pages, ids = freezable(shared, site)
    freeze(pages[1][0])
    freeze(pages[0][0])
    until(lambda: holder(pages[2][0]) == ids[2], what="the lock held by the third tab")
    until(lambda: site.hub.tabs(DOC) == 1, what="only the third tab counted")
    f = site.file
    f.write_text(f.read_text(encoding="utf-8") + "\nWith two tabs frozen.\n", encoding="utf-8")
    until(lambda: shows(pages[2][0], "With two tabs frozen."), what="the change in the third tab")


def test_a_comment_written_while_the_leader_is_frozen_reaches_the_tabs(shared, site):
    """Ticket 171, item 5: an event the hub emits after a frozen leader's stream closed and before a tab joins the
    next leader's reaches no tab. The page makes up for it on the `hello` of its new join (`checkText`). The joins are
    held in every tab, so the comment falls in the gap for certain: the leader freezes, the hub counts no tab, a
    comment is written and taken in, and only then do the tabs join. The freeze is dispatched (FREEZABLE_JS).
    The index page has no test of its own: it reads its list again on every `hello` (`soon()` in page/index.js), and
    while no index stream of any browser is joined the hub tells the index nothing (`touch` and `tick` in
    hub/index.py return at once)."""
    pages, _ = freezable(shared, site)
    comment_in_the_gap(site, pages, lambda: freeze(pages[0][0]))
    assert pages[0][1] == []


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


def comment_in_the_gap(site, pages, cut):
    """Hold every join of the tabs, `cut` the leader (it closes or freezes), write a comment while the hub counts no
    tab, then let the joins go: the other tabs must show the comment, which they hear of only through the `hello` of
    their new join (`checkText`)."""
    for p, _ in pages:
        p.evaluate(HOLD_JOINS_JS)
    cut()            # its stream ends; the lock passes to another tab, whose join waits on the gate
    until(lambda: sum(p.evaluate("window.__held") for p, _ in pages[1:]) >= 1, what="a join held")
    until(lambda: site.hub.tabs(DOC) == 0, what="no tab counted while the joins are held")
    update_file(site.file, lambda t: rdc.add_comment(t, *rdc.find_quote(t, "apples"), "apples", "Why?",
                                                     "Ada", "2026-10-14T10:00")[0])
    # No tab holds a stream now, so the watcher skips the document (`catch_up` in hub/core.py): the hub takes the
    # write in as a request for the page would, and the `comments` event it emits reaches no tab.
    entry = site.hub.entries[DOC]
    until(lambda: (site.hub.catch_up(entry), "Why?" in entry.live.current()[1])[1], what="the hub reading the comment")
    for p, _ in pages[1:]:
        p.evaluate("window.__release()")
    for n, (p, _) in enumerate(pages[1:], 2):
        until(lambda: badges(p) >= 1, what=f"the comment in tab {n}")
    assert [errors for _, errors in pages[1:]] == [[]] * 2


def test_a_comment_written_while_the_leader_hands_over_reaches_the_tabs(shared, site):
    """An event the hub emits after the old leader's stream closed and before a tab joins the new one reaches no
    tab. The page makes up for it on the `hello` of its new join: `checkText` reads the document again, and a
    comment or reply is in the file, so the hash it compares has moved. The joins are held here, in every tab, so
    the gap is as long as the test wants: the leader closes, a comment is written, and only then do the tabs join.
    (The index page reads its list again on every `hello`, `soon()` in page/index.js.)"""
    pages = [opened(shared, site) for _ in range(3)]
    until(lambda: site.hub.tabs(DOC) == 3, what="three tabs counted")
    comment_in_the_gap(site, pages, lambda: pages[0][0].close())


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
    open two connections back to back. The stream journal times the opens on the page's clock: a slow leader only
    spreads them, so the shortest gap tells a loop from a slow page, which a count of connections in a fixed time
    does not."""
    sids = set()

    def refuse(route):
        sids.add(route.request.post_data_json["stream"])
        route.fulfill(status=404, content_type="application/json", body='{"ok": false, "error": "no such stream"}')
    shared.route("**/_/live/join", refuse)
    pages = [opened(shared, site) for _ in range(2)]
    pages[0][0].wait_for_timeout(9000)   # not time.sleep: Playwright answers a routed request only while the test waits
    # The stream journal (pagehelp.STREAM_JOURNAL_JS, in every context) notes each EventSource made, on the page's
    # clock; only the leader's tab makes a `shared=` one.
    made = "window.__sseJournal.filter(e => e[1] === 'new' && e[2].includes('shared=')).map(e => e[0])"
    opens = sorted(t for p, _ in pages for t in p.evaluate(made))
    # The first connection is opened again at the first refusal, at once; the reopens after it wait for RETRY.
    reopens = opens[1:]
    assert len(reopens) >= 3, opens      # nothing timed otherwise
    gaps = [b - a for a, b in zip(reopens, reopens[1:])]
    # RETRY is 2000 ms and the page's timers never fire early: 100 ms is for the journal's clock against the
    # leader's Date.now. A loop opens at once.
    assert min(gaps) >= 1900, gaps
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
