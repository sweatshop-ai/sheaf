# 176: The frozen-tab page tests freeze nothing in headless Chromium

**Claimed by:** Zeynep (track sheaf-backlog), 2026-11-22

**Status:** done in branch zeynep/176-frozen-tab (PR to come)

**Blocked by:** none

**From:** the attempt at item 5 of ticket 171 (a hand-over reproduced with a frozen leader), 2026-11-22

**Where (main b4d1d7d7):** `tests/page/test_page_shared_live.py` (`test_a_frozen_leader_hands_the_stream_over_and_takes_it_back_on_resume`, `test_a_frozen_tab_that_waits_for_the_lock_is_not_handed_it`), `src/sheafmd/page/live.js` (the `freeze` and `resume` listeners, `lock()`)

Both frozen-tab tests send CDP `Page.setWebLifecycleState {state: "frozen"}` to a tab and then check that the other tabs still hear a change. A probe on t-compute (headless Chromium from the Playwright the CI installs, three tabs, leader frozen) measured:

- the leader's `freeze` listener ran 0 times (a counter on `document`, read after `{state: "active"}`);
- `navigator.locks.query()` from another tab showed `sheaf-live` held by the leader's client at 1, 5, 15 and 40 s after the freeze;
- the hub counted 3 tabs the whole time.

So the "frozen" leader keeps its lock and its stream and goes on relaying. The two tests pass because nothing changed, not because the hand-over works: the `freeze`/`resume` code in `live.js` is not exercised by any test. Waiting longer does not help, since a Web Lock has no expiry; it is held until the tab lets go, closes or is discarded.

- [x] Find a way to fire a real freeze in CI: a headed Chromium under Xvfb, `chrome://discards`-style intervention through CDP, or dispatching `freeze`/`resume` on `document` from the test (which tests the listeners but not Chrome's lifecycle). Acceptance: the leader's `freeze` listener runs, the lock moves to another tab, and the hub's count shows the hand-over. **Done, with the last resort: no real freeze is reachable.** Probe on the CI runner image (Chromium 145.0.7632.6, Playwright chromium-1208), three tabs, `Page.setWebLifecycleState frozen` on the leader: in the headless shell, in full Chromium in new headless (`channel="chromium"`), headed under Xvfb, and headed launched by hand and attached with `connect_over_cdp` with the tabs in one window, the `freeze` listener ran 0 times, the tab still answered `evaluate`, `sheaf-live` did not move and the hub count did not change. Every page Playwright drives reports `visibilityState` `visible`, background tabs included, and Chromium freezes only a hidden page. The tests now dispatch `freeze` and `resume` on `document` and in between the tab sends nothing on its BroadcastChannels while what it receives waits until after `resume`, as Chrome queues it (`FREEZABLE_JS` in the test file; its timers, fetches and lock requests still run): the listener runs, the lock moves to another tab (checked by Web Locks client id) and the hub count drops to 2 (to 1 with two tabs frozen). **These tests test page/live.js's listeners and what the other tabs do once a leader lets go, not that Chrome fires the events.** The probe also found ticket 180 (full Chromium: the leader drops each new tab after its join).
- [x] Then rewrite the two tests on it, and add item 5 of ticket 171 (a comment written while the leader is frozen and before the next leader's joins, shown by the visible tabs). **Done:** `test_a_frozen_leader_hands_the_stream_over_and_takes_it_back_on_resume`, `test_a_frozen_tab_that_waits_for_the_lock_is_not_handed_it` (the second tab freezes first, so its queued request is still there when the leader lets go), `test_a_comment_written_while_the_leader_is_frozen_reaches_the_tabs`. 11 of 11 in the file pass, three runs in a row on the CI runner image, and also with the `live.js` of PR #588 (ticket 180). Mutations: no `stop()` on `freeze` fails the three frozen tests; the queued request not aborted on `freeze` fails the two-tabs test only; no `checkText()` in `meetHello` fails the item-5 test, the closed-leader test and the resume test (the resumed tab missed a change while frozen and catches up only through it). No `rejoin()` on `resume` is not caught, and rightly: the next leader's `who`, queued while the tab was frozen and delivered after `resume` as Chrome does, runs the same `rejoin()`.
- [x] Until then, the two tests' docstrings should say they do not freeze, or the tests should be marked as such, so they are not read as evidence. **Done:** the comment above `FREEZABLE_JS` and every frozen test's docstring say the freeze is dispatched, not Chrome's.
