# 209: a rename look that runs out of time drops the Forward

**Claimed by:** Kenji

**Status:** done (2026-11-26, PR #694, merged as 9810f310)

**Blocked by:** none

**From:** the handoff of ticket 208 (`.scratch/handoffs/2026-11-26-208-two-tests-that-fail-under-load.md`), notes for the next person.

**Where:** `src/sheafmd/hub/commits.py`, `_pull` and `_renames`.

`_renames` caught `subprocess.SubprocessError`, which includes `TimeoutExpired`, and returned no renames; a non-zero exit of `git diff -M` gave empty output and so no renames as well. On a loaded machine a pull could then move a page without writing its Forward and without carrying its versions, with no diagnostics row. A later poll does not repair it: base and theirs are then equal.

## Serious

- [x] **A.** A `git diff -M` that times out or exits non-zero is never "no rename". The pull is held before anything moves (no Write log window opened, no work tree change, the last-seen ref unmoved), a `push-failed` row says why, and the next poll takes the rename in with its Forward and its versions. Red test first, simulating the timeout. Done: `test_a_rename_look_that_fails_holds_the_pull_and_the_next_poll_writes_the_forward[timeout|exit]`, red on main (the page moved, no Forward), green on #694; the old test that pinned "no renames" now checks the pull is held and no window stays open.
- [x] **B.** Found in review, the same failure one step earlier: the `git diff --name-only --no-renames` in `_pull` that names the files a pull locks and tells the Write log read `stdout` without its exit code. A non-zero exit gave an empty list, and the pull then moved the files under no writer's lock. A non-zero exit now holds the pull with a `push-failed` row. (A timeout there already raised and was a `push-failed` row from the pusher.) Review round 2 found the same read in `moved`, the branch switch, which now returns git's reason and does not move. Done: `test_a_list_of_the_changed_files_that_fails_holds_the_pull` and `..._holds_a_branch_switch`, both red first.

## Minor

- [x] **C.** Review round 1: a look that fails every time holds every pull and push, with one `push-failed` row (the poll's rows are said once). The look now gets a push's time (`PUSH_SECONDS`), not a commit's, and the row carries git's own reason. Left as is beyond that: a pull that cannot know its renames must not go through. Review round 2: the look is also given the pusher's children, so a stopping hub ends it, as it ends a fetch.
