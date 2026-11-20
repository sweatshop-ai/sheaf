# 169: A leader tab that Chrome freezes stops the live updates of every sheaf tab of that browser

**Claimed by:** Alonso 2026-11-20 17:44

**Status:** done, merged as 31e0a78d (PR #484)

**Blocked by:** none

**From:** open point of PR #474 (ticket 160), raised by the owner 2026-11-20

**Where (main a30694be):** `src/sheafmd/page/live.js` (the tab holding the Web Lock `sheaf-live` owns `/_/live?shared=` and relays over a BroadcastChannel)

- [x] **Check whether a frozen leader starves the other tabs.** Since #474 one tab per browser holds the live stream and relays every event to the others. Chrome freezes background tabs (Page Lifecycle `freeze`, memory saver, battery saver). A frozen leader keeps its Web Lock, so no other tab takes over, and its connection may stay open without anything relaying: the other tabs would stop seeing changes on disk, comments and replies, with no error. Not reproduced. To reproduce: open three sheaf pages, put the leader in a background tab, freeze it (`chrome://discards` → Freeze, or memory saver), change the `.md` on disk, see whether the visible tabs update. If they do not: on `freeze` the leader releases the lock and closes its stream (and takes it back on `resume`), or the followers detect a silent leader (no relayed heartbeat for N seconds) and ask for the lock. Acceptance: with the leader frozen, a change on disk reaches the visible tabs within a few seconds.

**Evidence (2026-11-20):** not reproduced by hand; the fix follows the ticket's own proposal. On `freeze` the leader closes its stream and releases the lock, a tab still queued for the lock aborts its request (a frozen follower must not inherit it), and on `resume` a tab rejoins its streams and queues again (`live.js`). Browser tests `test_a_frozen_leader_hands_the_stream_over_and_takes_it_back_on_resume` and `test_a_frozen_tab_that_waits_for_the_lock_is_not_handed_it` (`tests/page/test_page_shared_live.py`) freeze tabs through CDP and check the visible tabs update; CI run 44786538734 on head 657b8e99 passed all 6 slices, and the recorded review round was GO. The tests ran in CI only, not on the laptop. Events that land during a hand-over are not replayed: ticket 171, fifth item.
