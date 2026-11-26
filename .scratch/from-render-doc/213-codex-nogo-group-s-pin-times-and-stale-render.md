# 213: pin-time cleanup breaks on a large store and trusts foreign pins; a concurrent render can serve stale settings

**Claimed by:** Kenji

**Status:** done (PR #701, merged as a0895c69)

**Blocked by:** none

**From:** Codex re-check pass 8, PR #687 round 16 and PR #679 round 9 (both NO-GO), group S.

**Where:** `src/sheafmd/hub/commits.py` (pin-time cleanup), `src/sheafmd/hub/state.py` (`_pinned_at`), `src/sheafmd/hub/core.py` (first render, `_making`, `moved_remote`).

## Serious

- [x] **A.** (#687 commits.py:348) Every tracked pin-time path goes on one `update-index`/`ls-tree` command line; a large store passes the argument limit and blocks every hub commit. Red test first.
- [x] **B.** (#687 commits.py:332) Cleanup removes tracked pin times from git only; a clone that received another clone's `.at` files keeps counting them and can trim its own clocks. Keep the design of C in ticket 203. Red test first.
- [x] **C.** (#679 core.py:1173) Renders with settings A, B, B at once: the third sees old == new and can serve HTML rendered with A. Red test first.

## Minor

- [x] **D.** (#679 core.py:615) `_making` is keyed by address only, not root identity.
- [x] **E.** (#679 core.py:1375) `moved_remote` without `making.detached` leaks a watcher when the first render fails.

## Evidence

- **A.** Pin-time paths go to git on stdin (`update-index -z --force-remove --stdin`, helper `_unstage`); the second `ls-tree` with every path on its command line is gone. Test: `test_hub_commits.py::test_pin_times_leave_git_however_many_there_are[write|sweep]` (400 pin times, a command line capped at 8 KiB), red on main with E2BIG.
- **B.** A `.at` holds `<ns> <mark>`, the mark an HMAC of the store's real path by a key in the state folder (`pin-key`, made under `pin-key.lock`). `_pinned_at` believes only this hub's mark for this store, so a foreign time is neither believed nor counted in the trim. The design of C in ticket 203 is kept: the cleanup changes git's index and HEAD only. Tests: `test_hub_state.py::test_pin_times_another_clone_wrote_are_never_believed_or_counted_here`, `::test_a_pin_time_is_this_stores_alone_even_on_the_same_hub`, both red on main.
- **C.** Each settings change gets a number (`Hub._settings_seq`); `Entry.settings_built` records the number the last build read, and a render rebuilds while it is older (replaces `rebuild_due`, so a failed rebuild is still retried, 199). The count of a page goes with its page. Tests: `test_hub_index.py::test_a_render_with_the_settings_another_render_just_set_waits_for_a_page_of_them` (red on main), `::test_the_settings_count_of_a_page_goes_with_its_page`.
- **D.** `_Making` records its root; a mark of a forgotten root is not waited on. Test: `::test_an_open_after_its_root_was_forgotten_and_its_name_taken_never_waits_for_the_old_roots_render`.
- **E.** `moved_remote` marks the entry being made `detached` under the mark's own leaf lock (`lockorder.py`); a first render that fails afterwards forgets it and ends the watch. Test: `::test_a_first_render_that_fails_after_its_page_landed_elsewhere_leaves_no_watch_behind`.
- SPEC 4.2 (`pin-key`, `pin-key.lock`) and 7.4 (the mark).
- Reviews: Matt's code review (standards: no hard violation, naming and SPEC minors applied; spec: GO). Codex b was out of tokens (exit 7), so the gate's Opus fallback stood: round 01 GO on 099fd8d8, round 02 GO on the fix diff 1b855f64; the SPEC wording minor of round 02 was fixed on main with this tick. CI green on 1b855f64 (run 45781075692). One Codex check on the PR follows once Codex b is back.

## Left open (minor)

- A pin time written before this change carries no mark and is not believed until the page pins again (once a day while a form holds); a form open across the upgrade can get a 409 until then. Accepting unmarked times once would let in exactly the foreign times B is about.
- Moving or renaming a root's folder changes the store's real path, so its pin times are not believed until pinned again (SPEC 7.4).
- D compares roots by equality: a root re-added under the same name and folder is the same root and is waited on, as it should be.
