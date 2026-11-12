# 94: The hub can publish a half-written file to open pages

**Status:** open

**From:** render-doc ticket 94 (private archive), triaged 2026-11-12

**Where (main 81afdff):** `src/sheafmd/hub/core.py:1159-1163`, `src/sheafmd/hub/live.py:168`, `:590-604`, `src/sheafmd/hub/waiting.py:157-168`, `tests/page/test_page_writing.py`

**Size:** one item; a design decision first (fix it in the hub, or accept the window)

- [ ] **A torn read of an in-place rewrite reaches open pages.** When an editor, an agent or a CLI rewrites a `.md` in place (truncate, then write), the hub's one-second watcher (`src/sheafmd/hub/core.py:1159-1163`: stat, then `e.live.refresh()`) can read it in between. `LiveDocument.refresh` (`src/sheafmd/hub/live.py:590-604`) reads once, compares the hash, rerenders (`_rerender`, `live.py:168`, one read, no stat after it) and publishes a `changed` event for the torn text. A page with an open comment form holds its reload (SPEC 10.4); the next full read has a `base` the page never adopted, so the page stays on the held reload (in tests, a thread badge that never goes away).
  - To reproduce: write half the file, pause about 1.5 s, write the rest, while a page has a reply form with text open.
  - Possible fix: after `_rerender`, stat the file again and skip the publish when `(mtime_ns, size)` moved, the same idea as `waiting.py:_judged_read` (`src/sheafmd/hub/waiting.py:157-168`, today used only to end Tell waits).
  - Related: about 64 `write_text` calls in `tests/page/test_page_writing.py` rewrite files in place and can hit the same window; only the two deletion helpers were changed to replace the file whole.
