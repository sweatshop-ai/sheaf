# A page test failed once in CI and passed on the re-run of the same commit

**What to build:** Find out why `test_a_deletion_heard_while_a_reply_is_still_out_leaves_its_form_with_the_line_of_a_gone_thread` timed out once, and make it deterministic.

**Blocked by:** None.

**Status:** ready, not started.

## Evidence

- Test: `tests/page/test_page_writing.py::test_a_deletion_heard_while_a_reply_is_still_out_leaves_its_form_with_the_line_of_a_gone_thread` (defined at line 3333 on main at the time of writing; the failing assertion is the `until(...)` on the "deleted" line, `tests/page/test_page_writing.py:3346` in that run).
- Error: `AssertionError: timed out waiting for the form to say the thread is gone` (raised at `tests/page/pagehelp.py:194`).
- Where: CI run 44790532295, attempt 1, job 136476677290 (`ubuntu-24.04 py3.13 slice 3/6`): `1 failed, 202 passed, 11213 deselected, 1 xfailed in 245.65s`, test at 89 % of the slice.
- The same commit passed on attempt 2 of the same run (only the failed jobs were re-run), so the failure is not deterministic. One failure in the runs read so far: whether it also fails on other commits is not known.
- The change under test in that PR touched only `.github/workflows/ci.yml` concurrency, nothing the test reads.

## What the test waits on

After a deletion is heard while a reply is still being sent, the test fulfils the held request with a 500, then waits for the form to come back (`textarea` count 1) and for the text "deleted" in `#rd-popover .rd-form`. The comment above the last wait says "the form is back before its line": the line is added after the form returns, and the wait for it is `until(...)` with the helper's own timeout. A loaded runner that is slower than the helper's timeout between the two would fail exactly this way. This is the suspect, not a finding.

## DONE WHEN

The test passes 20 of 20 runs on t-compute under load (a loaded host: several other pytest runs at the same time, run with `-n 4` at most), and the cause is named in the commit message, whether a wait that is too short or a real race in the page.
