# 171: Shared live stream: four smaller follow-ups of #474

**Status:** open, to check

**From:** open points of PR #474 (ticket 160), raised by Thierry 2026-11-20. The two larger ones are tickets 169 and 170.

**Where (main a30694be):** `src/sheafmd/hub/events.py:118` (`Shared`), `:130` (`POLL_S`), `:186` (`Shared.get`), `:63` (`accept`); `src/sheafmd/page/live.js:125` (`pagehide`); `src/sheafmd/hub/handler.py:280` (`/_/live/join`)

- [ ] **`Shared.get` polls its members every 50 ms** (`events.py:130`). Up to 50 ms extra latency per event, and 20 wake-ups a second per open browser even when nothing happens. Replace with a `Condition` the member Subscriptions notify. Acceptance: an idle browser costs no wake-ups, an event goes out without the poll delay.

- [ ] **A member's `accept` runs on the one shared thread** (`events.py:63`, called from `Shared.get`). `accept` can ask git, so one slow member delays the events of every tab of that browser. Check how slow `accept` gets on a large repo; if it matters, run it per member off the shared thread, or cache its git answer.

- [ ] **Proxy mode, two members in one browser one after the other.** The leader's connection stays the first member's until it reconnects, and `/_/live/join` answers 404 for the second until then. Check what the second member sees in the meantime (no live updates, an error?); fix by reconnecting the shared stream when a join is refused for another member.

- [ ] **`pagehide` sends leaves and nothing rejoins on `pageshow`** (`live.js:125`). A page restored from the back/forward cache would have no live stream. The held Web Lock keeps the page out of Chrome's bfcache today, so Chrome is safe; Firefox and Safari not checked. Check there; fix by rejoining on `pageshow` with `persisted`.
