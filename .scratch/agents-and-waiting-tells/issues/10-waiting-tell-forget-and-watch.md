# 10: Waiting Tells: a forgotten root ends its Tells, and `watch` reads under the lock

**What to build:** A root that is forgotten takes its waiting Tells with it, and the watcher never ends a Tell because it caught a document mid-save. Closes rows 27 and 28 (#212).

**Where (main fac5160):**
- row 27: `hub/waiting.py:195` `end_document` has no caller (grep); `hub/core.py:799` `forget_root`
- row 28: `hub/waiting.py:109-121` `watch` calls `rdc.parse(e.read())` (`:118`) without the document lock; the hub's lock is `place.held(hub, address)` as used at `hub/handler.py:1182`

**Blocked by:** None (can start immediately)

**Status:** done-in-PR

**Size:** one session (waiting.py, core.py, one test file)

- [x] Test first (27): a Tell waits on a document, `forget_root` runs for its root; `tells.json` holds no row of that root, the page gets `tell-cancelled` (reason says the folder was forgotten) and a diagnostics row is written — `test_forgetting_a_root_ends_its_tells_and_the_page_hears_why_and_the_other_roots_tells_stay` (red before the fix: no event); `forget_root` calls the new `Waiting.end_root` before the entries go, page gets `tell-cancelled` `reason: the folder was forgotten`, one `tell-cancelled` diagnostics row, `tells.json` holds no row of the root
- [x] Other roots' Tells are untouched by that forget, also those of the same token — same test: the same token's Tell on `second/plan.md` stays; `test_forgetting_a_root_whose_name_starts_like_another_leaves_that_roots_tells` pins the prefix (`sec` vs `second`)
- [x] Test first (28): the file is truncated and then written by an editor while `watch` runs (hold the file in the truncated state with the document lock); the Tell is not ended; after the write completes, the next pass sees the thread and keeps it — `test_a_document_caught_truncated_in_a_save_does_not_end_its_tell_and_the_next_pass_keeps_it` (red before: the pass ended the Tell at once): the file is held truncated under the Live Document's locks, the pass waits, after the write the Tell is kept, also at the next pass, no diagnostics row
- [x] `watch` takes the document lock, or rereads once after an empty or unparsable read before it ends anything; the PR says which and why — the lock: `watch` reads each document with the new `Live.read_now` (name's lock + Live Document lock, as `knows`), before `_change` takes `tells.lock`, so the lock order of live.py is kept; only rows present at the read are judged from it. No reread: a reread cannot tell a half save from an empty file
- [x] A thread that really is gone still ends its Tell at the next pass (the existing test for a thread closed from outside stays green) — `test_a_thread_closed_from_outside_ends_the_tell_at_the_watchers_next_pass[resolved/deleted]` green
