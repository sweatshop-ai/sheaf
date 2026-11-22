# test_page_waiting_tell.py's timer test is flaky

**What to build:** `tests/page/test_page_waiting_tell.py::test_the_timer_of_an_earlier_cancel_does_not_take_the_places_of_a_later_cancel` timed out on "waiting for the seen line" on PR #274's head 12c4d36 (CI run 43534443983, slice 1, 2026-11-14) and passed on the re-run of that job; #274 does not touch that file. Find what the test waits on that a loaded runner can delay, and wait on it instead of on the clock.

**Blocked by:** None.

**Status:** open, waiting for the next occurrence; the diagnostics land in #530. No cause was found.

- [ ] The cause of the timeout is found and named (a log of the failed run: `gh api repos/sweatshop-ai/sheaf/actions/jobs/<job>/logs`)
- [ ] The test no longer fails when the runner is slow (run it 20 times on the CI runner host under load)

  Attempts 2026-11-20, none reproduced it: 20 of 20 runs on two starved cores; 48 of 48 runs of the whole file with 12 parallel loops on four cores; the hub's events delayed by 0.2 s and by 0.6 s: passed; 3 of 3 serial runs of the whole page suite on the CI runner host (the same test passed each time). The failed CI log held no trace, because only the last wait of the test was wrapped. #530 wraps every wait: a red now prints the hub's waits, the held events, the popover, the url and the trace. A forced failure on the CI runner host showed that report. The boxes stay unticked.
  Also seen in the third serial run: tests/page/test_page_drafts.py::test_discard_inside_the_upgrade_notice_keeps_the_upgrade_line timed out waiting for the upgrade notice (once in three runs). A separate flake, not investigated.
