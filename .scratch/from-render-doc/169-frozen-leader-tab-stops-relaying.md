# 169: A leader tab that Chrome freezes stops the live updates of every sheaf tab of that browser

**Status:** open, to check

**Blocked by:** none

**From:** open point of PR #474 (ticket 160), raised by Thierry 2026-11-20

**Where (main a30694be):** `src/sheafmd/page/live.js` (the tab holding the Web Lock `sheaf-live` owns `/_/live?shared=` and relays over a BroadcastChannel)

- [ ] **Check whether a frozen leader starves the other tabs.** Since #474 one tab per browser holds the live stream and relays every event to the others. Chrome freezes background tabs (Page Lifecycle `freeze`, memory saver, battery saver). A frozen leader keeps its Web Lock, so no other tab takes over, and its connection may stay open without anything relaying: the other tabs would stop seeing changes on disk, comments and replies, with no error. Not reproduced. To reproduce: open three sheaf pages, put the leader in a background tab, freeze it (`chrome://discards` → Freeze, or memory saver), change the `.md` on disk, see whether the visible tabs update. If they do not: on `freeze` the leader releases the lock and closes its stream (and takes it back on `resume`), or the followers detect a silent leader (no relayed heartbeat for N seconds) and ask for the lock. Acceptance: with the leader frozen, a change on disk reaches the visible tabs within a few seconds.
