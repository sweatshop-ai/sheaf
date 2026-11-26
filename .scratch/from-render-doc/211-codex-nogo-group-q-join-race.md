# 211: a reopen of a shared stream races a join that found the old one listed

**Claimed by:** Kenji

**Status:** done (2026-11-26, PR #699): box A does not hold; a regression test pins why

**Blocked by:** none

**From:** Codex re-check of PR #690, round 2 (NO-GO), group Q of the boss's seventh pass.

**Where:** `src/sheafmd/hub/handler.py`, `_live_join` and `_shared_stream`.

## Serious

- [ ] **A.** `_live_join` checks under `_join_lock` that its stream is still listed, then joins it. `_shared_stream`, a reopen under the same id, replaces the listed stream without `_join_lock`, and closes the old one after. Between the check and the join the reopen can list the fresh stream; if the stale join takes the old stream's lock before `old.close()`, it succeeds, takes the key from the browser's other connections, and is then closed: the tab is counted nowhere. The reopen must replace and close under `_join_lock`, so a join is wholly before it or wholly after it. Red test first, the interleaving forced.

  **Does not hold (left unticked, by design).** The interleaving is real; the harm is not. On main the join's look and its join both run under `_join_lock`, and the browser's leader joins every key again when the fresh connection opens (`src/sheafmd/page/live.js`, `onopen`). That join needs `_join_lock` too, so it always comes after the stale one and lands on the fresh stream: the tab ends counted once. A first fix put the reopen's replacement and close under `_join_lock`. It forced the order but left the final state the same (two reviewers and the recorded round said so), and it ran `old.close()` under the hub-wide lock that every join waits on. It was dropped. `test_a_join_that_found_the_old_stream_listed_before_a_reopen_leaves_the_tab_counted_once` forces the interleaving on main and checks the end state: the key only on the fresh stream, none on the browser's other connection, one tab.
