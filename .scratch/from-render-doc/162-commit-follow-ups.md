# 162: Commit follow-ups: a forgotten root's name, a git flag fixed at registration, a versions store chosen once

**Claimed by:** Tiago 2026-11-20 17:44

**Status:** done, merged as 568e5521 (PR 495); the follow-up item below is open

**Blocked by:** none

**From:** render-doc ticket 162 (private archive), triaged 2026-11-12

**Where (main 81afdff):** `src/sheafmd/hub/core.py:329-358`, `:480-482`, `:857`; `src/sheafmd/hub/place.py:509-513`; `src/sheafmd/hub/roots.py:272`, `:389`; `src/sheafmd/hub/commits.py:355-371`; `src/sheafmd/hub/live.py:133-136`

**Size:** three items, each a red test at the HTTP seam (`tests/test_hub_commits.py`) then green; SPEC 7.4 and 8.11 say what each fix does

- [x] **A commit can land in a root that took over the name of a forgotten one.** `Hub.committed` (`src/sheafmd/hub/core.py:329-358`) looks the root up by the address's root name (`self.roots.get(a.root)`, line 339) after the write. `forget_root` (`core.py:857`) takes only the hub lock, not the sheaf name lock, and `place.owns` (`src/sheafmd/hub/place.py:509-513`) returns True where the hub does not place sheaves, so a `sheaf roots forget` plus a new root registered under the same name between the write and that lookup commits (and pushes) the same relative path in the other repo. Fix: pass the root id the write resolved (the `Entry`'s `root.id` for page writes, the root resolved before the write for door writes) and refuse when it no longer matches.

  Done: `Hub.committed(root_id=)` refuses with a `commit-refused` row; every caller passes it. Evidence: `test_a_commit_never_lands_in_a_root_that_took_the_name_of_one_forgotten_under_the_write` failed without the change, passes with it; `tests/test_hub_commits.py` 121 passed.

- [x] **`root.git` is fixed at registration.** The flag is stored in the roots registry and read back as is (`src/sheafmd/hub/roots.py:272`, set at `roots.py:389`). A folder registered before `git init` keeps `git = false`, so with `commit = true` every write records `commit-not-git` (`src/sheafmd/hub/commits.py:361-363`). Fix: when the flag is false, ask git in `Commits.saved` (`git rev-parse --is-inside-work-tree`), or re-detect when the registry reloads. Other readers of `root.git` to check before changing the flag itself: `core.py:235`, `core.py:692`, `roots.py:362` (rule 1 of SPEC 8.2), `roots.py:638`, `the_list.py:954`, `mcp.py:218`.

  Done: every reader in `commits.py` goes through `_is_git`, which asks git (`--show-toplevel`) when the flag is false. Evidence: `test_a_folder_registered_before_git_init_commits_once_it_is_a_repo` red before, green after. The readers outside `commits.py` are the follow-up item below.

- [x] **The versions store is chosen once per open document.** For an ordinary root, `Hub.entry` passes `self._versions_of(root)` to `LiveDocument` when the entry is made (`src/sheafmd/hub/core.py:480-482`; it is re-chosen per call only in the private-roots case). If `.sheaf.toml` switches `versions` between `state` and `root` while a page is open, the document keeps writing the old store, while `Commits.saved` reads the new config per write (`commits.py:355-371`, `rc.versions_inside`) and stages the other folder. A clone then lacks merge bases and a save gets the 409 "copy your edit, then reload" (no text lost). Fix: pick the store per write (as the private-root path already does with a callable, `src/sheafmd/hub/live.py:133-136`), or drop the entries of a root whose `.sheaf.toml` changed.

  Done: `Hub.entry` passes a callable, so each write reads `.sheaf.toml`. Evidence: `test_a_page_open_when_versions_moves_into_the_root_keeps_its_versions_where_the_root_now_says` red before, green after; CI run 44785853229 all six slices green.

- [ ] **Follow-up: the other readers of `root.git`, outside `commits.py`.** PR 495 makes every reader in `commits.py` ask git when the flag is false (`_is_git`); these still read the registry's flag as of registration (lines on PR 495's head, `cc492931`). Check each against a folder registered before `git init`, and decide per reader whether it should ask git too:
  - `src/sheafmd/hub/core.py:262`, `Hub._register_private_roots`: a private root whose registry flag is false is refused.
  - `src/sheafmd/hub/core.py:821`: a reader of `root.git` in the write-log path (`if lines and root is not None and root.git`).
  - `src/sheafmd/hub/roots.py:381`: rule 1 of SPEC 8.2 (`not r.git`, which roots enclose a folder).
  - `src/sheafmd/hub/roots.py:668`: `_git_names(top) if root.git`.
  - `src/sheafmd/hub/the_list.py:1000`: `if not lines or not root.git`.
  - `src/sheafmd/mcp.py:265`: `if root.git`.
