# 176: The frozen-tab page tests freeze nothing in headless Chromium

**Claimed by:** nobody

**Status:** open

**Blocked by:** none

**From:** the attempt at item 5 of ticket 171 (a hand-over reproduced with a frozen leader), 2026-11-22

**Where (main b4d1d7d7):** `tests/page/test_page_shared_live.py` (`test_a_frozen_leader_hands_the_stream_over_and_takes_it_back_on_resume`, `test_a_frozen_tab_that_waits_for_the_lock_is_not_handed_it`), `src/sheafmd/page/live.js` (the `freeze` and `resume` listeners, `lock()`)

Both frozen-tab tests send CDP `Page.setWebLifecycleState {state: "frozen"}` to a tab and then check that the other tabs still hear a change. A probe on t-compute (headless Chromium from the Playwright the CI installs, three tabs, leader frozen) measured:

- the leader's `freeze` listener ran 0 times (a counter on `document`, read after `{state: "active"}`);
- `navigator.locks.query()` from another tab showed `sheaf-live` held by the leader's client at 1, 5, 15 and 40 s after the freeze;
- the hub counted 3 tabs the whole time.

So the "frozen" leader keeps its lock and its stream and goes on relaying. The two tests pass because nothing changed, not because the hand-over works: the `freeze`/`resume` code in `live.js` is not exercised by any test. Waiting longer does not help, since a Web Lock has no expiry; it is held until the tab lets go, closes or is discarded.

- [ ] Find a way to fire a real freeze in CI: a headed Chromium under Xvfb, `chrome://discards`-style intervention through CDP, or dispatching `freeze`/`resume` on `document` from the test (which tests the listeners but not Chrome's lifecycle). Acceptance: the leader's `freeze` listener runs, the lock moves to another tab, and the hub's count shows the hand-over.
- [ ] Then rewrite the two tests on it, and add item 5 of ticket 171 (a comment written while the leader is frozen and before the next leader's joins, shown by the visible tabs).
- [ ] Until then, the two tests' docstrings should say they do not freeze, or the tests should be marked as such, so they are not read as evidence.
