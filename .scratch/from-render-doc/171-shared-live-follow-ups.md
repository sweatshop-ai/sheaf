# 171: Shared live stream: five smaller follow-ups of #474

**Status:** open, to check

**Blocked by:** 169, 170 (same file, page/live.js; its items build on both)

**From:** open points of PR #474 (ticket 160), raised by the owner 2026-11-20. The two larger ones are tickets 169 and 170. The fifth item came out of the review of PR #484 (ticket 169).

**Where (main a30694be):** `src/sheafmd/hub/events.py:118` (`Shared`), `:130` (`POLL_S`), `:186` (`Shared.get`), `:63` (`accept`); `src/sheafmd/page/live.js:125` (`pagehide`); `src/sheafmd/hub/handler.py:280` (`/_/live/join`)

- [ ] **`Shared.get` polls its members every 50 ms** (`events.py:130`). Up to 50 ms extra latency per event, and 20 wake-ups a second per open browser even when nothing happens. Replace with a `Condition` the member Subscriptions notify. Acceptance: an idle browser costs no wake-ups, an event goes out without the poll delay.

- [ ] **A member's `accept` runs on the one shared thread** (`events.py:63`, called from `Shared.get`). `accept` can ask git, so one slow member delays the events of every tab of that browser. Check how slow `accept` gets on a large repo; if it matters, run it per member off the shared thread, or cache its git answer.

- [ ] **Proxy mode, two members in one browser one after the other.** The leader's connection stays the first member's until it reconnects, and `/_/live/join` answers 404 for the second until then. Check what the second member sees in the meantime (no live updates, an error?); fix by reconnecting the shared stream when a join is refused for another member.

- [ ] **`pagehide` sends leaves and nothing rejoins on `pageshow`** (`live.js:125`). A page restored from the back/forward cache would have no live stream. The held Web Lock keeps the page out of Chrome's bfcache today, so Chrome is safe; Firefox and Safari not checked. Check there; fix by rejoining on `pageshow` with `persisted`.

- [ ] **Events that land during a leader hand-over are not replayed** (`live.js`, `Leader.stop` and the `who` rejoin; found in the review of #484). When the leader freezes, closes or crashes, its stream ends, and the next leader opens a new one and every tab joins it again. An event the hub emits between the old stream closing and the tab's new join reaches no tab, and the stream has no event id to resume from. Read from `page.js:4468`: every join is answered by a `hello`, and `meetHello` runs `checkText()`, so a change to the document text in the gap is caught. Nothing in `meetHello` refetches comments, replies, agent progress or the index list, so an event of those kinds in the gap is lost until the next one of its kind. **Reproduction:** three tabs of one browser, the leader frozen (`Page.setWebLifecycleState` `frozen`, as in `test_a_frozen_leader_hands_the_stream_over_and_takes_it_back_on_resume`); while it is frozen and before a follower joins the new leader, post a comment from the API; assert the visible tabs show it within a few seconds. Do the same for the index page's list. **Proposed fix:** the hub numbers the events of each document and puts the latest number in `hello`; a page keeps the last number it saw and, when a `hello` carries a higher one that is not simply the next, refetches comments and replies (and the index its list) as `checkText()` does for the text. Cheaper first step: run that refetch on every `hello` after the first one of the page, since a `hello` after the first means the stream was re-opened. Acceptance: the reproduction passes with the leader frozen at the moment of the event.
