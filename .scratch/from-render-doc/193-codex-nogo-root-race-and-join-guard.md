# 193: Codex NO-GO findings on merged PRs #599 and #601 (root replaced mid-write, shared-stream join guard)

**Claimed by:** Habib

**Status:** done (PR #660, merge 9d674600)

**Blocked by:** none

**From:** the Codex re-check of PRs merged on an Opus review alone. Both returned NO-GO. Every finding was checked against main 308474e8 or later. Boxes are lettered A and B within this ticket ("193 A").

**Counts:** 4 findings:

- 2 already fixed on main (last section).
- 2 still present: 1 serious, 1 minor.

**Where:** `src/sheafmd/hub/handler.py` (`_live_join`, `_SharedStream`).

The serious box is fixed test-first: a red test on main, then the fix.

## Serious

- [x] **A** (from #601, `hub/handler.py` `_live_join`): the guard against a late join on an older shared stream reads only the history (`had`) of the streams still registered. Two cases lose that history. If the newer stream that had the key and left it closes, `_shared_closed` drops it. If the browser reconnects under the same stream id, the newer stream is replaced by a fresh one with an empty `had`. Either way, a join that the old leader sent late on the older stream, still open, is accepted, and the hub keeps a ghost stream for a tab that is on the newer connection. Fix: the history is kept on the stream that must refuse the late join, the older one. A key taken by a newer stream is barred on every older stream of the same owner, and that bar lives as long as the older stream.
  Done in #660: `_SharedStream.taken_by_newer` bars the key on every older stream of the owner, and `_live_join` drops a join the stream `bars`. Tests in `tests/test_hub_shared_live.py`: `test_a_late_join_on_the_old_connection_after_the_new_one_closed_is_dropped` and `test_a_late_join_on_the_old_connection_after_the_new_one_came_back_under_its_id_is_dropped`, red at 2387f22d and green at 3500c9a3 (CI run 45602703093).

## Minor

- [x] **B** (from #601, `hub/handler.py` `had`): every key ever joined on a connection stays in `had` for the connection's life. `SHARED_MAX` bounds only the keys still joined, so a long-lived connection whose tabs come and go grows without bound. Fix: the bars that replace `had` are bounded, the oldest dropped first.
  Done in #660: at most `BARRED_MAX` (1000) bars per stream, the oldest dropped first. Test `test_the_keys_an_old_connection_is_barred_from_are_bounded`, red at 2387f22d, green at 3500c9a3.

## Already fixed on main

- #599 SERIOUS (`mcp.py`, a root replaced after `_located_in` lets `place.ahead`, `hub.file` or the trailing `place.place` resolve the replacement root): fixed by e15ea754 (ticket 181 A), which passes the located root's id to all three. `place._where` and `Hub.file` raise `NotFound` when the address names another root now. Test: `test_a_door_update_never_moves_a_file_of_a_root_that_took_the_name_after_the_write_was_located[ahead]` and `[after]` in `tests/test_hub_place.py`.
- #599 SERIOUS (`mcp.py`, a root replaced before `committed` makes `place.owns` raise `RuntimeError` instead of the root-id refusal): fixed by 5f8f1a18 (ticket 181 A), where `place.owns` counts an address held through `place.held` whatever root its name names now, so the commit is refused with its row. Test: the `[written]` case of the same test.
