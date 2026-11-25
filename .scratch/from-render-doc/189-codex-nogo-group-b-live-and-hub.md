# 189: Codex NO-GO findings on merged PRs #539, #568, #573, #572, #550, #512 (live connection and hub)

**Claimed by:** Habib

**Status:** done (PR #654, merge 57b21811)

**Blocked by:** none

**From:** the Codex re-check of PRs merged on an Opus review alone. Each of the six returned NO-GO. Every finding was checked against main f3e370bc. Boxes are lettered A to E within this ticket ("189 A").

**Counts:** 10 findings:

- 5 already fixed on main (last section).
- 5 still present: 4 serious, 1 minor.

**Where:** `src/sheafmd/page/live.js` (A), `src/sheafmd/hub/incoming.py` (B), `tests/test_hub_abandoned.py` (C), `src/sheafmd/hub/roots.py` (D, E).

Each serious box is fixed test-first: a red test on main, then the fix.

## Serious

- [x] **A** (from #568, `page/live.js`): a join whose answer is lost (network error after the hub took it) leaves its key on the shared stream. The leader drops the key and tells the tab its stream was refused; the index page asks for a new stream under a new key. The old key gets no `leave`, so the hub counts one more tab for the life of the connection, and each such failure spends one of the connection's 200 streams. Fix: a join with no answer is followed by a `leave` of its key, in the key's post order.
  Done in #654: `page/live.js` sends a `leave` after a join whose answer was lost, in the key's post order. Test `test_a_join_whose_answer_is_lost_leaves_no_stream_on_the_hub` (`tests/page/test_page_index.py`): red at 9f439a22 on the CI host ("timed out waiting for one index stream on the hub, not two"), green 3 times at 7067e82e there, and green in CI run 45575444551 (attempt 4).
- [x] **B** (from #550, `hub/incoming.py` `_root_shape`): the paths of a root's move go into a set before their type is checked. A page `{"path": []}` raises `TypeError: unhashable type` instead of the refusal "a page of the root's move has no path". Fix: check every page's shape first, then the duplicates.
  Done in #654: `_root_shape` checks every page's shape before the duplicates. Test `test_a_page_path_of_another_json_type_is_refused_as_no_path` (`tests/test_land_root.py`, three cases), red on main, then green.
- [x] **D** (from #512, `hub/roots.py` `_git_names`): the `git ls-files` of a git root keeps its own 20 s timeout whatever the caller's deadline, so one git root can run past the 10 s budget of the MCP listing, and a git call that timed out reads as `failed` ("git gave no answer"), never as `stopped`. Fix: the git call gets the time left to the deadline, and a call cut by the deadline is `stopped`.
  Done in #654: `_git_names` gives git the time left (at most 20 s); a call cut by the deadline is `stopped`, a timeout with time left is still `failed`. Tests in `tests/test_hub_roots.py`: `test_a_git_root_gives_git_no_more_than_the_time_left_and_a_cut_call_is_stopped`, `test_a_git_root_whose_deadline_passed_does_not_ask_git`, `test_a_git_timeout_with_time_left_is_still_no_answer`.
- [x] **E** (from #512, `hub/roots.py` `_walk`): the deadline is checked between folders only, and `os.walk` reads a whole folder before it yields it: one huge or slow folder runs past the budget before any check. Fix: the walk reads each folder entry by entry and checks the deadline as it goes.
  Done in #654: `_walk` reads each folder entry by entry with `os.scandir` and checks the deadline per entry; a folder made a link after it was read is not entered (Codex review). Tests in `tests/test_hub_roots.py`: `test_a_walk_stops_at_its_deadline_inside_one_huge_folder`, `test_a_walk_in_time_lists_what_os_walk_listed`, `test_a_folder_made_a_link_after_it_was_read_is_not_entered`. One Codex suggestion was not taken: yielding the names of a folder cut by the deadline, which `_capped` drops anyway as it checks the deadline per name.

## Minor

- [x] **C** (from #550, `tests/test_hub_abandoned.py`): the stand-in stream `Held` has no `close()`, which `_Http._stream` calls in its `finally`. The server thread raises `AttributeError`, and the test cannot tell a clean end of the stream from one ended by that error. Fix: give `Held` its `close()` and assert the server thread raised nothing.
  Done in #654: `Held` has its `close()`, and the test's server records what its threads raise and asserts nothing. Without `close()` the assertion fails on the `AttributeError`.

## Already fixed on main

- #539 SERIOUS (a 409 on the shared stream keeps the refused id): fixed by 8f6d8f7b (ticket 187 CA), which opens the connection again under a new id after a terminal refusal.
- #539 MINOR (a deferred reopen fires on an unrelated connection): fixed by 8f6d8f7b, which clears the pending reopen when the connection is refused.
- #573 SERIOUS (the generated mark checked before the write lock of `/_/sessions`): fixed by 7d6e44c9 (ticket 183 BE), which checks it again under the file's lock.
- #573 SERIOUS (a read-only generated page shows one notice): fixed by cfc9d231 (ticket 156), which shows both.
- #572 SERIOUS (a half-closed root-owned caller told 503 with no row): fixed by 23f9eb43 (ticket 139), which keeps another user's 403 and its row, root included.
