# 206: Codex NO-GO finding on merged PR #660 (group N, a shared stream reopened during a join)

**Claimed by:** Kenji

**Status:** done: merged in #690 (bf5af361) on 2026-11-26, CI `ubuntu-24.04 py3.13` run 45737415656: 11339 passed, one failure, `test_land_root`, which is main's own until #677 lands

**Blocked by:** none

**From:** the Codex re-check of #660 (ticket 193's fix), round 05, NO-GO with one serious finding. Checked against main 89612e52: it still holds.

**Where:** `src/sheafmd/hub/handler.py`, `_live_join`.

## Serious

- [x] **A** (from #660, `_live_join`): the join looks its shared stream up, then builds the tab's stream outside any lock. A reopen of the same id in that time lists a fresh stream and closes the old one. If the tab joins the fresh stream first, the old join then resumes: the old stream is no longer listed, so the fresh one never barred it, its own `join` drops the tab's stream because it is closed, and its leave of the key on every other stream of the owner removes the key from the fresh stream. The tab is then counted nowhere and gets no events. Fix: under the join lock, a stream that is no longer the listed one for its id, or is closed, joins nothing and makes no other stream leave.
  Test: `tests/test_hub_shared_live.py`, `test_a_join_whose_connection_was_opened_again_meanwhile_leaves_the_fresh_one_its_key` (red before the fix: the fresh stream lost the key).
- [x] **A2** (Codex on #690, serious): the stream can still close after the join found it listed and before the join itself; `Shared.join` then took nothing, yet the other streams of the owner left the key. Fix: `Shared.join` returns whether it took the stream, and the others leave the key only when it did.
  Test: `test_a_join_whose_connection_closes_after_it_was_found_listed_takes_the_key_from_no_other` (red before the fix).

## Notes

- Review of #690: Matt's code review (standards: names in the test and the PR number in the changelog, applied; the private `_sid` read and the comment covering three tickets left as they are, the same module and still readable; spec: GO). Codex, second account, on the branch: NO-GO with A2, fixed test-first; Codex on the fix commit only: GO. The recorded round of the merge gate fell back to Opus (the gate's Codex call met the default account's usage limit): GO, provisional.
- A connection that ends (not reopens) after the check gives the same result as the serial order (the join, then the close): the tab is counted nowhere until its browser joins it again. No new loss.
