# 170: A crashed sheaf tab can stay counted as open for up to a minute

**Status:** open, to check

**Blocked by:** none

**From:** open point of PR #474 (ticket 160), raised by Thierry 2026-11-20

**Where (main a30694be):** `src/sheafmd/page/live.js:21` (`SWEEP = 2000`), `:139` (the sweep `setInterval`), `:195` (`Leader.prototype.sweep`)

- [ ] **Check how long a crashed tab lingers.** A tab that closes normally leaves at once (`pagehide`, `live.js:125`). A tab that crashes or is killed leaves only when the leader's sweep finds its `sheaf-tab-*` lock released. The sweep runs every 2 s, but Chrome throttles timers in a tab hidden for more than five minutes to once a minute, so with the leader in a long-hidden tab a crashed tab can still count in `hub.tabs()` (and in `sheaf list`, "N tabs open") for up to a minute. Not measured. To check: leader hidden for more than five minutes, kill another sheaf tab's renderer (`chrome://process-internals` or the task manager), time until `sheaf list` drops it. If it matters (does anything act on the tab count within a minute?): run the sweep from the lock itself, `navigator.locks.request('sheaf-tab-*')` per member, which resolves as soon as the crashed tab's lock is freed, instead of polling. Acceptance: a killed tab leaves the count within a few seconds, leader hidden or not.
