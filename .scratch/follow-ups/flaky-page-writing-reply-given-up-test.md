# test_page_writing's reply_given_up test is flaky

**What to build:** `tests/page/test_page_writing.py::test_a_reply_given_up_that_the_hub_took_after_all_goes_from_the_page_and_the_store` fails intermittently with `assert 0 == 1` (`'words the hub is slow to write'` not in `#rd-popover` after the form went). Seen failing on #282's head 881784d (CI job 132257457063, 2026-11-14 00:30Z, passed on re-run of that job, and in the same run's second attempt) and on main's 6c55e1e (job 132269528325, 01:05Z); passing on 0d08bbd. It failed on 881784d before #274's code was in that branch, so #274 is not the cause. Cause not found. What the test does (read, not run): it waits for the form to go (`until(lambda: not typed(p))`) and then reads `#rd-popover` text once; whether the thread's message is drawn by then is not verified. Wait on the message being drawn, not on the form going.

(Written by Vikram, handed over in his handoff of 2026-11-14.)

**Blocked by:** None.

**Status:** open

- [ ] The cause of the failure is found and named (the logs of the two failed jobs: `gh api repos/sweatshop-ai/sheaf/actions/jobs/<job>/logs`)
- [ ] The test no longer fails when the runner is slow (run it 20 times on t-compute under load)
