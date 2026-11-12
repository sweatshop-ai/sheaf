# 160: Seven sheaf tabs in one browser: the seventh page never loads

**Status:** open

**From:** render-doc ticket 160 (private archive), triaged 2026-11-12

**Where (main 81afdff):** `src/sheafmd/page/page.js:3611`, `:3668`, `:3787`, `src/sheafmd/page/index.js:58`, `src/sheafmd/hub/handler.py:246` (the `/_/live` route)

**Size:** one fix of the client side, one README sentence

- [ ] **Live streams use up Chrome's six connections per host.** Chrome allows six HTTP/1.1 connections per host, and the hub speaks HTTP/1.1. Every open sheaf page and the index hold one `GET /_/live` event stream for as long as the tab is open (`src/sheafmd/page/page.js:3668`, `src/sheafmd/page/index.js:58`); the `visibilitychange` handlers (`page.js:3611`, `:3787`) only reconnect, so a hidden tab never closes its stream. With six sheaf tabs of one hub open in one Chrome profile, a seventh page (or the sign-in link `sheaf open` prints) waits forever in Chrome's queue and looks like a dead hub, while `curl` answers in milliseconds. To reproduce: open seven pages of one hub in one profile. Fix options: one stream per browser shared through a `SharedWorker` or `BroadcastChannel` (neither is used in `src` today); or hidden tabs close `/_/live` after N minutes and reopen it on `visibilitychange` (`page.js:3787` already reconnects); or HTTP/2. Acceptance: seven pages open, the seventh loads within a second, and live reload still reaches the first six.

- [ ] **Name the symptom until it is fixed.** The README (and the not-signed-in page) should say: "a page that never loads while other sheaf tabs are open: close older sheaf tabs". Neither README nor SPEC names it today.
