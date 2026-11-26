# Handoff: ticket 211, group Q join race (2026-11-26)

## Outcome

The race Codex found in round 2 on #690 is real but harmless. PR #699 (merged 4b23aeb9) adds no product change; it pins the end state with a test.

- A join's look and its join both run under `_join_lock`. When the fresh connection opens, the browser's leader joins every key again (`src/sheafmd/page/live.js`, `onopen`), also under `_join_lock`. That re-join lands on the fresh stream, so the tab ends counted once.
- `test_a_join_that_found_the_old_stream_listed_before_a_reopen_leaves_the_tab_counted_once` forces the interleaving on main, asserts it was forced, and checks the key is on the fresh stream only and the tab counted once.
- A first version put the reopen under `_join_lock`. Round 1 and the spec review found it changed the order, not the end state, and closed the old stream under the hub-wide lock. It was dropped.

## Reviews and CI

Recorded rounds 1 (GO, three minors that led to the rework), 2 (GO, one minor: assert the window was forced, fixed), 3 (`--since`, GO, nothing found). CI on f442a919: ubuntu py3.13 success.

## Open

- Box A of ticket 211 is left unticked by design (the finding does not hold).
- A connection that ends closes its stream without `_join_lock` (server.py, `sub.close()`). The same client re-join covers it; not changed.
