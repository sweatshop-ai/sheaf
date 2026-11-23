# 170: A crashed sheaf tab can stay counted as open for up to a minute

**Claimed by:** Aziz 2026-11-20 20:05

**Status:** done, merged as 995dc30a (PR #515); meets the CI rule (verified 2026-11-23, see the end); the two items below cannot be reproduced in CI and are closed by reading the code

**Blocked by:** 169 (same file, page/live.js)

**From:** open point of PR #474 (ticket 160), raised by the owner 2026-11-20

**Where (main a30694be):** `src/sheafmd/page/live.js:21` (`SWEEP = 2000`), `:139` (the sweep `setInterval`), `:195` (`Leader.prototype.sweep`)

- [x] **Check how long a crashed tab lingers.** A tab that closes normally leaves at once (`pagehide`, `live.js:125`). A tab that crashes or is killed leaves only when the leader's sweep finds its `sheaf-tab-*` lock released. The sweep runs every 2 s, but Chrome throttles timers in a tab hidden for more than five minutes to once a minute, so with the leader in a long-hidden tab a crashed tab can still count in `hub.tabs()` (and in `sheaf list`, "N tabs open") for up to a minute. Not measured. To check: leader hidden for more than five minutes, kill another sheaf tab's renderer (`chrome://process-internals` or the task manager), time until `sheaf list` drops it. If it matters (does anything act on the tab count within a minute?): run the sweep from the lock itself, `navigator.locks.request('sheaf-tab-*')` per member, which resolves as soon as the crashed tab's lock is freed, instead of polling. Acceptance: a killed tab leaves the count within a few seconds, leader hidden or not.

**Done (PR #515, head 99e1adc5, CI run 44797969463 green, review round 1 GO):** the leader keeps a queued request for each joined tab's `sheaf-tab-*` lock (`Leader.prototype.watching`, `live.js`). It is granted when the tab dies; the leader then checks the lock is still free and drops the tab's streams. The requests are aborted when the tab's last stream leaves and on `Leader.stop`. The 2 s sweep stays as the backstop.

**Evidence:** `tests/page/test_page_shared_live.py::test_a_tab_that_leaves_without_a_leave_is_dropped_when_its_lock_frees`, run on the CI runner host with `sheafmd` resolving inside the scratch copy. On main's `live.js` the count took 3.78 s to drop (red); with the fix 0.056 s (limit 1 s). The whole file passed, 5 tests.

**Not verified:**
- A real renderer crash. Playwright's `Page.crash` hangs the driver and `chrome://crash` does not crash the tab. The test drops the follower's `leave` post and closes the tab, which frees the lock as a crash does.
- The leader hidden for more than five minutes (the ticket's "leader hidden or not"), and the timing of the old behaviour in that state. Never measured, so "does anything act on the tab count within a minute" is also unanswered. A manual check in a real browser remains open.

**Verified 2026-11-23 (Thandi), meets the rule.** Rule checked: an item about a freeze or crash counts as done only if a browser reproduction runs in CI. `test_a_tab_that_leaves_without_a_leave_is_dropped_when_its_lock_frees` is that reproduction: the tab dies without a `leave` and its `sheaf-tab-*` lock frees, which is what a crash does to the leader. It passed in main's CI on e6b762ec (push run 45133187436, nightly run 45141939187). The two items above:
- A real renderer crash: not reachable in CI (`Page.crash` hangs the driver). The leader sees only the lock being freed, which the test does, so nothing on the leader's side goes untested.
- The leader hidden for more than five minutes: not reachable in CI, since every page Playwright drives reports `visible` (ticket 176). It no longer matters for the fix: Chrome throttles timers in a long-hidden tab, and the drop path in `Leader.prototype.watching` (`live.js`) uses none. The lock grant, `navigator.locks.query()` and `take` run from promise callbacks; only the 2 s backstop `sweep` is a timer. So "does anything act on the tab count within a minute" no longer needs an answer.
