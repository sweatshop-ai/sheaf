# 206: Codex NO-GO finding on merged PR #660 (group N, a shared stream reopened during a join)

**Claimed by:** Kenji

**Status:** in progress

**Blocked by:** none

**From:** the Codex re-check of #660 (ticket 193's fix), round 05, NO-GO with one serious finding. Checked against main 89612e52: it still holds.

**Where:** `src/sheafmd/hub/handler.py`, `_live_join`.

## Serious

- [ ] **A** (from #660, `_live_join`): the join looks its shared stream up, then builds the tab's stream outside any lock. A reopen of the same id in that time lists a fresh stream and closes the old one. If the tab joins the fresh stream first, the old join then resumes: the old stream is no longer listed, so the fresh one never barred it, its own `join` drops the tab's stream because it is closed, and its leave of the key on every other stream of the owner removes the key from the fresh stream. The tab is then counted nowhere and gets no events. Fix: under the join lock, a stream that is no longer the listed one for its id, or is closed, joins nothing and makes no other stream leave.
