# 09: Waiting Tells: per-owner seen, the route re-checked, a recycled thread id

**What to build:** Three wrong answers in the waiting Tells of ticket 04 are removed: an aggregate `seen` overwrites the per-row value; the box or relay route is re-checked only when the comment goes to a box; a thread id reused by `next_id` can attach an old Tell to a new comment. Closes rows 24, 25, 26 (all #212, all about its own head).

**Where (main fac5160):**
- row 24: `hub/waiting.py:188` (`end()` builds `seen` with `any(...)`) and `:88` (`_end` writes it for every row)
- row 25: `hub/handler.py:1568` (`if to_box and self._work_route(...) != route`), set at `:1540-1548`; `still_visible` at `:1561`
- row 26: `comments.py:352` `next_id` (max+1), `hub/waiting.py:105-128` `watch`; the row holds `by`, `at` (`:141`)

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

**Size:** one session (waiting.py, handler.py `/_/comment`, one test file each for waiting and comment)

- [ ] Test first (24): two owners' Tells on one thread, one seen and one not; ending the thread tells each owner's page its own `seen`, so the other owner's toast never says "had already seen it" wrongly
- [ ] Test first (25): the route changes between check and write (a box or relay route appears for a comment with `tell` to an agent); the comment is refused or re-routed as `route` says, never queued for the agent
- [ ] The re-check in (25) runs for the agent route too, not only `to_box`, with one test per route (agent, box, relay)
- [ ] Test first (26): delete the last thread, add a new comment (same id), the hub having no entry for the document; the old Tell does not attach to the new comment. The row stores the comment's `at` and `by`, and `take` / `watch` compare them
- [ ] A Tell written before this change (a row without `at` / `by`) still lists and ends as it does today (restart test on an old `tells.json`)
- [ ] The diagnostics rows still carry the token name and never the text
