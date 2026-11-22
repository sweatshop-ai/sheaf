# 177: The refused-join loop test cannot tell a leader loop from the page's own pace

**Claimed by:** Kenji 2026-11-22

**Status:** done: PR #578 merged as b8967bec (head 2f008488, GO round 1 provisional, CI run 45065643984 green)

**Blocked by:** PR #539

**From:** the final review round of PR #539 (ticket 171, items 3 and 4), a minor test-only finding, 2026-11-22

**Where:** `tests/page/test_page_shared_live.py`, the test of PR #539 that refuses every join for 9 s and asserts `len(sids) <= 7` (6 stream ids measured)

The bound of 7 stream ids in 9 s is what the page reaches when it reopens once per RETRY (2 s) plus the page's own `streamClosed` retries. A leader that reopened in a tight loop would also stay under it if each reopen took long enough, so the test does not separate the two.

- [x] Count the leader's reopens directly (a probe on `Leader.prototype.reopen`, or the times of the `/_/live?shared=` requests) and assert at most one per RETRY. Acceptance: the test fails when the once-only `deferred` guard in `Leader.prototype.post` is removed.

- [x] Also (review round 4 of PR #542, minor): `test_a_comment_written_while_the_leader_hands_over_reaches_the_tabs` collects each tab's `pageerror`s through `opened()` and never asserts them. Assert the visible tabs' error lists are empty at the end, as the seven-tab test does.

## Evidence (PR #578, head 2f008488)

- Item 1: the test times every `/_/live?shared=` EventSource from the stream journal and asserts the reopens after the first are at least 1900 ms apart (RETRY 2000). Run on t-compute with `if (!self.deferred) {` replaced by `if (true) {`: FAILED, gaps `[1999.6, 0.7, 2000.6, 0.6, 2000.2, 0.6, ...]`; the old test from main PASSED on that same code. Unchanged code: 5 of 5 passed, whole file 10 passed.
- Item 2: `assert [e for _, e in pages[1:]] == [[]] * 2`; passed on t-compute and in CI run 45065643984 (`test_a_comment_written_while_the_leader_hands_over_reaches_the_tabs PASSED`).
