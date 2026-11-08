# 09: Waiting Tells: per-owner seen, the route re-checked, a recycled thread id

**What to build:** Three wrong answers in the waiting Tells of ticket 04 are removed: an aggregate `seen` overwrites the per-row value; the box or relay route is re-checked only when the comment goes to a box; a thread id reused by `next_id` can attach an old Tell to a new comment. Closes rows 24, 25, 26 (all #212, all about its own head).

**Where (main fac5160):**
- row 24: `hub/waiting.py:188` (`end()` builds `seen` with `any(...)`) and `:88` (`_end` writes it for every row)
- row 25: `hub/handler.py:1568` (`if to_box and self._work_route(...) != route`), set at `:1540-1548`; `still_visible` at `:1561`
- row 26: `comments.py:352` `next_id` (max+1), `hub/waiting.py:105-128` `watch`; the row holds `by`, `at` (`:141`)

**Blocked by:** None (can start immediately)

**Status:** done-in-PR (sweatshop-ai/sheaf#224)

**Size:** one session (waiting.py, handler.py `/_/comment`, one test file each for waiting and comment)

- [x] Test first (24): two owners' Tells on one thread, one seen and one not; ending the thread tells each owner's page its own `seen`, so the other owner's toast never says "had already seen it" wrongly
  - Evidence: `test_ending_a_thread_tells_each_owners_page_its_own_seen_not_the_other_owners` (both orders); red before the fix, green after
- [x] Test first (25): the route changes between check and write (a box or relay route appears for a comment with `tell` to an agent); the comment is refused or re-routed as `route` says, never queued for the agent
  - Evidence: `test_a_route_that_changes_between_the_check_and_the_write_queues_nothing_for_the_agent[None-box]` and `[None-relay]` were red before the fix; the other four cases (box / relay moving) were already green and stay as guards
- [x] The re-check in (25) runs for the agent route too, not only `to_box`, with one test per route (agent, box, relay)
  - Evidence: the same six-case test: agent (`None-box`, `None-relay`), box (`box-None`, `box-relay`), relay (`relay-None`, `relay-box`); the guard is `(to_box or to_agent) and _work_route(...) != route`
- [x] Test first (26): delete the last thread, add a new comment (same id), the hub having no entry for the document; the old Tell does not attach to the new comment. The row stores the comment's `at` and `by`, and `take` / `watch` compare them
  - Evidence: `test_a_new_comment_that_takes_a_deleted_threads_id_does_not_get_the_old_tell_at_the_listing` (hub entry popped) and `..._at_the_watchers_pass`, plus the same-author-same-minute case; `test_the_row_stores_the_comments_author_and_time`. The row keeps `thread_by`, `thread_at`, `thread_quote` (the row's own `by`/`at` are the Tell's); `_recycled` compares them in `take` and `watch`. An edit or a reply leaves the Tell: `test_an_edit_a_reply_and_a_watcher_pass_leave_the_tell_of_the_same_comment_alone`
- [x] A Tell written before this change (a row without `at` / `by`) still lists and ends as it does today (restart test on an old `tells.json`)
  - Evidence: `test_a_tell_written_before_row_26_still_lists_and_ends_after_a_real_restart`: a real hub process, the keys stripped from `tells.json`, stopped and started again; it lists, ends on `resolve`, and the file is empty
- [x] The diagnostics rows still carry the token name and never the text
  - Evidence: `test_a_new_comment_..._at_the_listing` asserts the `tell-cancelled` row has `token`, `thread`, `reason` and no text; the existing `test_each_step_writes_a_row_...` still passes
