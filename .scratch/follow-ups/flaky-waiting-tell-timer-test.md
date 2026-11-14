# test_page_waiting_tell.py's timer test is flaky

**What to build:** `tests/page/test_page_waiting_tell.py::test_the_timer_of_an_earlier_cancel_does_not_take_the_places_of_a_later_cancel` timed out on "waiting for the seen line" on PR #274's head 12c4d36 (CI run 43534443983, slice 1, 2026-11-14) and passed on the re-run of that job; #274 does not touch that file. Find what the test waits on that a loaded runner can delay, and wait on it instead of on the clock.

**Blocked by:** None.

**Status:** open

- [ ] The cause of the timeout is found and named (a log of the failed run: `gh api repos/sweatshop-ai/sheaf/actions/jobs/<job>/logs`)
- [ ] The test no longer fails when the runner is slow (run it 20 times on t-compute under load)
