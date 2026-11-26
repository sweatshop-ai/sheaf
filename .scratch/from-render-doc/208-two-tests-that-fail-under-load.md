# 208: two tests that fail under load on the CI runners

**Claimed by:** Amaia

**Status:** in progress

**Blocked by:** none

**From:** CI on the loaded CI runners: `test_hub_commits.py::test_a_rename_that_arrives_on_a_pull_writes_a_forward_and_carries_the_versions` failed in run 45722265058 (`assert False` at line 1852, the renamed page absent, 29.7 s), and `test_archive.py::test_archive_after_in_the_roots_toml_changes_the_days` in run 45726607342 (`assert [] == ['loose-bea/2026-11/notes.md']` at line 190, 6.8 s). Both pass on an idle machine. Boxes are lettered A and B within this ticket ("208 A").

**Where:** `tests/test_hub_commits.py`, `tests/test_archive.py`. The product does not race in either: both are fixed in the test.

## Tests

- [ ] **A** (`test_hub_commits.py`, the rename on a pull): the poll's path has no time limit but git's: every hub git stops after `GIT_SECONDS` (20 s). On a loaded runner one git of the test's single poll ran out of time. A stopped fetch or diff ends the pull with a `push-failed` row; a stopped rename look (`_renames`, `diff -M`) is caught and reads as no rename, so the pull goes through without the Forward and no row says why. Fix: for this test every hub git gets 600 s (`GIT_SECONDS`, `PUSH_SECONDS` and `_git`'s keyword default patched by `roomy_git`), and the poll and the edit's push settle within 1200 s. A first fix re-polled on a "timed out" row; the review showed it missed the rename look and a timed-out text cut at 300 characters, so it was replaced.
- [ ] **B** (`test_archive.py`, `archive_after` in the root's `.sheaf.toml`): the `clock` fixture reads the wall time once, before the page is created; the page's mtime is the real time of its write, and `due()` counts from the later of the mtime and the first sweep. A create that lands more than one second after the fixture leaves the page less than seven days quiet at `+7 days + 1 s`. Fix: the page's mtime is set to the clock after the create (`age(…, 0, clock)`), as the other tests of the file do.

Neither test times computation: the archive clock is a fixed number the test moves, and the rename test only widens git's limits and settle's wait.
