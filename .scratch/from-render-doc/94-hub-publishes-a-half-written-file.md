# 94: The hub can publish a half-written file to open pages

**Claimed by:** Gudrun 2026-11-20 17:42

**Status:** done (PR #483 merged as 7de2b1ca; PR #498 merged as 1ed60690)

**Blocked by:** none

**From:** render-doc ticket 94 (private archive), triaged 2026-11-12

**Where (main 81afdff):** `src/sheafmd/hub/core.py:1159-1163`, `src/sheafmd/hub/live.py:168`, `:590-604`, `src/sheafmd/hub/waiting.py:157-168`, `tests/page/test_page_writing.py`

**Size:** one item; a design decision first (fix it in the hub, or accept the window)

- [x] **A write that lands while a refresh reads and renders no longer reaches open pages** (PR #483, merged as 7de2b1ca, head 90d77b16, new test `test_a_refresh_that_a_write_moved_under_publishes_nothing_and_the_next_one_tells_from_what_the_tabs_hold` in `tests/test_hub_live.py`: red first, then green; `tests/test_hub_live.py` and `tests/test_hub_waiting.py` 163 passed; recorded rounds 1 and 2 GO; CI: slices 2-6 green, slice 1 red only on `tests/page/test_mount_sheaf.py::test_connect_a_laptop_names_it_and_shows_one_line_once`, main's known flake).
- [x] **Accepted, not fixed: a writer that pauses with half a file on disk.** A half-written file between two writes cannot be told from a finished write, so no settle wait closes it short of guessing. SPEC 8.9 says it is published as it stands and that writers replace a file whole (PR #483).
- [ ] **(original item, kept for the record)** A torn read of an in-place rewrite reaches open pages. When an editor, an agent or a CLI rewrites a `.md` in place (truncate, then write), the hub's one-second watcher (`src/sheafmd/hub/core.py:1159-1163`: stat, then `e.live.refresh()`) can read it in between. `LiveDocument.refresh` (`src/sheafmd/hub/live.py:590-604`) reads once, compares the hash, rerenders (`_rerender`, `live.py:168`, one read, no stat after it) and publishes a `changed` event for the torn text. A page with an open comment form holds its reload (SPEC 10.4); the next full read has a `base` the page never adopted, so the page stays on the held reload (in tests, a thread badge that never goes away).
  - To reproduce: write half the file, pause about 1.5 s, write the rest, while a page has a reply form with text open.
  - Possible fix: after `_rerender`, stat the file again and skip the publish when `(mtime_ns, size)` moved, the same idea as `waiting.py:_judged_read` (`src/sheafmd/hub/waiting.py:157-168`, today used only to end Tell waits).
  - [x] Related, next PR: about 64 `write_text` calls in `tests/page/test_page_writing.py` rewrite files in place and can hit the same window. Done in PR #498, merged as 1ed60690 (CI run 44780290654, all six slices green): `rewrite(path, text)` in `tests/page/pagehelp.py` replaces the file whole; 164 in-place calls in 22 files under `tests/page/` now use it.
