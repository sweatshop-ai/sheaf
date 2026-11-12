# 162: Commit follow-ups: a forgotten root's name, a git flag fixed at registration, a versions store chosen once

**Status:** open

**From:** render-doc ticket 162 (private archive), triaged 2026-11-12

**Where (main 81afdff):** `src/sheafmd/hub/core.py:329-358`, `:480-482`, `:857`; `src/sheafmd/hub/place.py:509-513`; `src/sheafmd/hub/roots.py:272`, `:389`; `src/sheafmd/hub/commits.py:355-371`; `src/sheafmd/hub/live.py:133-136`

**Size:** three items, each a red test at the HTTP seam (`tests/test_hub_commits.py`) then green; SPEC 7.4 and 8.11 say what each fix does

- [ ] **A commit can land in a root that took over the name of a forgotten one.** `Hub.committed` (`src/sheafmd/hub/core.py:329-358`) looks the root up by the address's root name (`self.roots.get(a.root)`, line 339) after the write. `forget_root` (`core.py:857`) takes only the hub lock, not the sheaf name lock, and `place.owns` (`src/sheafmd/hub/place.py:509-513`) returns True where the hub does not place sheaves, so a `sheaf roots forget` plus a new root registered under the same name between the write and that lookup commits (and pushes) the same relative path in the other repo. Fix: pass the root id the write resolved (the `Entry`'s `root.id` for page writes, the root resolved before the write for door writes) and refuse when it no longer matches.

- [ ] **`root.git` is fixed at registration.** The flag is stored in the roots registry and read back as is (`src/sheafmd/hub/roots.py:272`, set at `roots.py:389`). A folder registered before `git init` keeps `git = false`, so with `commit = true` every write records `commit-not-git` (`src/sheafmd/hub/commits.py:361-363`). Fix: when the flag is false, ask git in `Commits.saved` (`git rev-parse --is-inside-work-tree`), or re-detect when the registry reloads. Other readers of `root.git` to check before changing the flag itself: `core.py:235`, `core.py:692`, `roots.py:362` (rule 1 of SPEC 8.2), `roots.py:638`, `the_list.py:954`, `mcp.py:218`.

- [ ] **The versions store is chosen once per open document.** For an ordinary root, `Hub.entry` passes `self._versions_of(root)` to `LiveDocument` when the entry is made (`src/sheafmd/hub/core.py:480-482`; it is re-chosen per call only in the private-roots case). If `.sheaf.toml` switches `versions` between `state` and `root` while a page is open, the document keeps writing the old store, while `Commits.saved` reads the new config per write (`commits.py:355-371`, `rc.versions_inside`) and stages the other folder. A clone then lacks merge bases and a save gets the 409 "copy your edit, then reload" (no text lost). Fix: pick the store per write (as the private-root path already does with a callable, `src/sheafmd/hub/live.py:133-136`), or drop the entries of a root whose `.sheaf.toml` changed.
