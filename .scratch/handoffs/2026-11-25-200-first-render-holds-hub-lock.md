# Handoff: ticket 200, a first render holds the hub's lock (2026-11-25)

**Status:** ticket written and claimed by Mei; no code yet. To be implemented in a fresh session.

**Ticket:** `.scratch/from-render-doc/200-first-render-holds-hub-lock.md`.

## Facts checked on main (after #673, 9384b5ff)

- `Hub._entry` (`src/sheafmd/hub/core.py`) builds a new entry, `e.live.refresh(force=True)` included, inside `with self._lock:`. `self._lock` is a hub-wide `threading.RLock`.
- That lock is also taken at the top of `_entry` for an entry that already exists. So every `Hub.entry` call, which means all 13 routes that use `Handler._entry` plus Tells, forwards and `_render_entry`, waits for any first render in progress.
- A render runs pandoc at least twice (`render.py` lines with `_pandoc.run`), plus once per table read by `comments._read_tables`. Each run has 120 s, with no total limit.
- Since #673, the render runs on the thread `render <address>`. After a `pending` answer, that thread keeps the lock until pandoc ends.

## Start here

1. Write box A red: test `_join_renders()` and the `Event`-held fake pandoc of the H test in `tests/test_hub_index.py` (199) are the pattern to copy.
2. Then B and C, then the fix (D).
3. Locally, run only `tests/test_hub_index.py` (and `tests/test_hub_handler.py` if `_entry` callers change). No page or browser tests on the laptop.

## State of main when this was written

Main CI run 45714160570 on d0c17818 is red on one test, `tests/test_land_root.py::test_a_repeat_after_the_tip_moved_on_is_answered_with_the_first_answer_for_a_page_that_landed`. It comes from #671 combined with #672 (each alone passes) and is being fixed on another track. It does not touch the hub's render path, so it does not block ticket 200. A red CI on that test alone is not the work of 200.
