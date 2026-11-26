# 211: a reopen of a shared stream races a join that found the old one listed

**Claimed by:** Kenji

**Status:** in progress (2026-11-26)

**Blocked by:** none

**From:** Codex re-check of PR #690, round 2 (NO-GO), group Q of the boss's seventh pass.

**Where:** `src/sheafmd/hub/handler.py`, `_live_join` and `_shared_stream`.

## Serious

- [ ] **A.** `_live_join` checks under `_join_lock` that its stream is still listed, then joins it. `_shared_stream`, a reopen under the same id, replaces the listed stream without `_join_lock`, and closes the old one after. Between the check and the join the reopen can list the fresh stream; if the stale join takes the old stream's lock before `old.close()`, it succeeds, takes the key from the browser's other connections, and is then closed: the tab is counted nowhere. The reopen must replace and close under `_join_lock`, so a join is wholly before it or wholly after it. Red test first, the interleaving forced.
