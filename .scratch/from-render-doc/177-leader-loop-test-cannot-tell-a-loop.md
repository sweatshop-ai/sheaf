# 177: The refused-join loop test cannot tell a leader loop from the page's own pace

**Claimed by:** nobody

**Status:** open

**Blocked by:** PR #539

**From:** the final review round of PR #539 (ticket 171, items 3 and 4), a minor test-only finding, 2026-11-22

**Where:** `tests/page/test_page_shared_live.py`, the test of PR #539 that refuses every join for 9 s and asserts `len(sids) <= 7` (6 stream ids measured)

The bound of 7 stream ids in 9 s is what the page reaches when it reopens once per RETRY (2 s) plus the page's own `streamClosed` retries. A leader that reopened in a tight loop would also stay under it if each reopen took long enough, so the test does not separate the two.

- [ ] Count the leader's reopens directly (a probe on `Leader.prototype.reopen`, or the times of the `/_/live?shared=` requests) and assert at most one per RETRY. Acceptance: the test fails when the once-only `deferred` guard in `Leader.prototype.post` is removed.
