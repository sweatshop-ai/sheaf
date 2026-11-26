# Handoff: ticket 209, a rename look that runs out of time drops the Forward

**Date:** 2026-11-26 · **Ticket:** `.scratch/from-render-doc/209-rename-look-timeout-drops-the-forward.md` · **PR:** #694, merged 9810f310

## Status

Done, boxes A, B and C ticked.

- **A.** `_renames` in `src/sheafmd/hub/commits.py` raises `LookFailed` with git's own reason when `git diff -M` times out, cannot start or exits non-zero. `_pull` runs the look before the Write log window opens and before the work tree moves. On `LookFailed` it writes a `push-failed` row ("the rename look: …") and returns False, so HEAD and the last-seen ref stay where they were and the next poll takes the rename in with its Forward and versions.
- **B.** The `--name-only --no-renames` diff that names the files a pull locks never checked its exit code; a non-zero exit gave an empty list and the pull moved files under no writer's lock. `_pull` now holds on it, and so does `moved` (the branch switch), which returns git's reason without moving.
- **C.** The look gets `PUSH_SECONDS`, not `GIT_SECONDS`, and the pusher's `children`, so a stopping hub ends it as it ends a fetch. Its `Stopped` is no `SubprocessError` and goes up as a stop.

## Tests

In `tests/test_hub_commits.py`, all red on main first, the failures simulated by a stub of `commits._git` (no dependency on load):

- `test_a_rename_look_that_fails_holds_the_pull_and_the_next_poll_writes_the_forward[timeout|exit]`
- `test_a_list_of_the_changed_files_that_fails_holds_the_pull`
- `test_a_list_of_the_changed_files_that_fails_holds_a_branch_switch`
- `test_a_read_of_the_renames_that_times_out_holds_the_pull_and_leaves_no_window_open` (renamed: it used to pin "no renames, the pull goes through").

The file passes locally (129) and in CI run 45760602339.

## Notes for the next person

- A look that keeps failing now holds every pull and push for that repo. That is deliberate: a pull that cannot know its renames must not go through. The poll's rows go through `_once`, so it is one row, not one a minute.
- `boss_merge` wanted a recorded round on the final head: round 3 was a `--since` round on the round-2 fixes, which counted because round 2 had found something.
- Review: rounds 1 to 3 ran as the Opus fallback of `boss_review` (all GO, minors fixed), plus Matt's code-review (standards and spec, no defects).

## Open

Nothing. The worktrees `/tmp/wt-kenji-209` and `/tmp/wt-kenji-209-claim` and the branch `kenji/209-rename-timeout` are removed after this push.
