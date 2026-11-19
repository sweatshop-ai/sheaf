# projects.toml is parsed about 801 times per listing

**What to build:** Read and parse each root's `projects.toml` once per listing, not once per page check.

**Blocked by:** None. Same shape as #459, which memoizes `git_place` per listing (`config.git_places_remembered()`); reuse that per-listing scope.

**Status:** ready

## Problem

`Hub.projects_of(root)` (`src/sheafmd/hub/core.py:1401`) caches the entries by file key, but it calls `projects.load(root.path, self)` first (`src/sheafmd/hub/projects.py:42`, `parse` at `:74`) on every call. `load` opens the file beneath the root and returns `(key, got)`, so the open and the parse run before the cache is consulted. `Index.data` reaches it once per `visible` call (`core.py:1293`), which a listing makes 800 times.

## Evidence

Profile of one cold listing of a copy of a production hub's data (same paths, sizes and mtimes, bodies replaced by filler; sheafmd 75bbddb6; 2026-11-19):

- 800 `visible` calls and 801 `projects.load` runs for 1067 pages in one `GET /_/mount?sheaf=1`.
- 3.1 s of the 9 s still profiled after #459's git fix is this parse; 3.4 s unprofiled.
- `core.py:445 file` and `place.py:226 _found` realpath calls are the rest of the 9 s.

## Acceptance criteria

- [ ] A test counts the opens/parses of `projects.toml` for one listing of a root with 48 pages in 4 folders (as `tests/test_listing_git_calls.py` does for git in #459) and fails on current main with a count near the number of `visible` calls.
- [ ] After the change the count is bounded by the number of roots, not pages.
- [ ] An edit of `projects.toml` between two listings still takes effect at the next listing (the existing "read again only when the file changed" behaviour).
- [ ] The measured count before and after is stated in the PR body (before: 801 per listing on that copy).
