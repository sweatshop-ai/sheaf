# 208: two tests that fail under load on the CI runners

**Claimed by:** Amaia

**Status:** done (PR #692, merged 17394ad5)

**Blocked by:** none

**From:** CI on the loaded CI runners: `test_hub_commits.py::test_a_rename_that_arrives_on_a_pull_writes_a_forward_and_carries_the_versions` failed in run 45722265058 (`assert False` at line 1852, the renamed page absent, 29.7 s), and `test_archive.py::test_archive_after_in_the_roots_toml_changes_the_days` in run 45726607342 (`assert [] == ['loose-bea/2026-11/notes.md']` at line 190, 6.8 s). Both pass on an idle machine. Boxes are lettered A and B within this ticket ("208 A").

**Where:** `tests/test_hub_commits.py`, `tests/test_archive.py`. The product does not race in either: both are fixed in the test.

## Tests

- [x] **A** (`test_hub_commits.py`, the rename on a pull): the poll's path has no time limit but git's: every hub git stops after `GIT_SECONDS` (20 s). On a loaded runner one git of the test's single poll ran out of time. A stopped fetch or diff ends the pull with a `push-failed` row; a stopped rename look (`_renames`, `diff -M`) is caught and reads as no rename, so the pull goes through without the Forward and no row says why. Fix: for this test every hub git gets 600 s (`GIT_SECONDS`, `PUSH_SECONDS` and `_git`'s keyword default patched by `roomy_git`), and the poll and the edit's push settle within 1200 s. A first fix re-polled on a "timed out" row; the review showed it missed the rename look and a timed-out text cut at 300 characters, so it was replaced.
- [x] **B** (`test_archive.py`, `archive_after` in the root's `.sheaf.toml`): the `clock` fixture reads the wall time once, before the page is created; the page's mtime is the real time of its write, and `due()` counts from the later of the mtime and the first sweep. A create that lands more than one second after the fixture leaves the page less than seven days quiet at `+7 days + 1 s`. Fix: the page's mtime is set to the clock after the create (`age(…, 0, clock)`), as the other tests of the file do.

Neither test times computation: the archive clock is a fixed number the test moves, and the rename test only widens git's limits and settle's wait.

## Evidence

- **Red and green under simulated load** (a pytest plugin kept outside the repo; it reads the archive clock 2 s early and makes any hub git given under 25 s run out of time once the rename is pushed). The tests on main fail exactly as on CI: the rename test with `assert False` for a slow fetch and with the Forward missing for a slow `diff -M`, and the archive test with `assert [] == ['loose-bea/2026-11/notes.md']`. The new tests pass. With the clock 2 s early, all 34 tests of `test_archive.py` pass, so no other test in that file has the same dependency.
- **CI:** run 45755219072 on eedcfb36 is green (`ubuntu-24.04 py3.13`). The run before it, 45745525625, failed only `test_public_tree.py::test_this_checkout_holds_no_name`, on a host name in this ticket's From line, which has been removed. Both flaky tests passed in that run as well.
- **Review:** the recorded rounds are GO (rounds 1–3, provisional Opus; Codex at its usage limit). A separate standards and spec review gave a NO-GO on A's first fix, which re-polled on a timeout. It showed that a timed-out rename look leaves no row, and that a long path cuts "timed out" from the row's text. A was then rebuilt as `roomy_git`, and the second pass on that fix was GO. Its one minor finding (the edit's push settling within 30 s) was fixed in the same push.
- Neither test times computation. The archive clock is a number the test sets, and the rename test only widens git's limits and settle's wait.
