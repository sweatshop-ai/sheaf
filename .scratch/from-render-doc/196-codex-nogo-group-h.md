# 196: Codex NO-GO group H (moves' lock, forget, delete, service signal)

**Status:** open

**Blocked by:** none

**From:** the Codex re-check of merged PRs #621 #626 #630 #633 (2026-11-25), the latest round of each (7, 7, 7 and 8). Triaged against main 3b984afe. Letters A to F, in PR order.

**Counts:** 6 findings:

- 3 still present: 0 serious, 3 minor (C and E fixed in #668; F left open).
- 1 filed in the review: G, minor, left open.
- 3 already fixed on main.

Ratings follow the rule of 183: serious is a wrong result in ordinary use, a crash, data loss, or a security or privacy breach; minor needs a narrow race, a failed disk write or an unusual name. Codex marked all six serious.

## Open, minor

- [ ] **C** (from #626): `Hub._let_go_root` (`hub/core.py`) decided whether the registry had let the name go by `self.roots.get(name)`. `Roots.forget` pops the root from memory before `_save()`, so a `roots.json` that could not be written left the root in the file but not in memory: `get` answered None, the failure was swallowed as `forget-failed`, and the documents were popped and their versions dropped while the root came back at the next reload. `get` also answers None for a private root, so any failed forget of one read as let go. Fix: `Roots.forget` puts the root (and its `added`) back when `_save` raises, and the hub asks a new `Roots.held(name)`, which sees private roots too, both for the check after a failure and for the root it returns on the let-go branch (where `get` gave None for a private root, so `index.forgot` was skipped; found in the review). Tests: `test_a_forget_whose_roots_json_cannot_be_written_keeps_the_root_in_the_hub_too`, `test_a_private_roots_forget_that_fails_before_the_registry_let_go_keeps_its_documents` (`tests/test_hub_index_live.py`), both red on main.
- [ ] **E** (from #630): the clear of a mark left on an address (`Door._make`) and `_put_back_mark` compare marks by equality, and a mark's `at` has the minute's grain. The setter of the left mark that marks the new page between its file and the clear, in the same minute, writes an equal mark, and the clear takes it. Fix: every setting writes a random `set` into the mark (SPEC 8.3), so no two marks are equal. Test: `test_the_clear_of_a_left_mark_leaves_the_same_setters_mark_set_meanwhile_in_the_same_minute` (`tests/test_mcp_generated.py`), red on main.
- [ ] **F** (from #633): Delete (`handler._delete`) checks the owner again at each round of `moves.page_held`, but not that the file is the one the first look found. A page removed and replaced at its address while Delete waits for a render (up to 120 s, outside the moves' lock) is the one trashed. Left open: no file identity tells a replacement from the page's own save, because every save renames a new inode over the name (`beneath.Opened.write`); an inode check would refuse a Delete that waited behind an ordinary autosave, which is the usual case. A fix needs an identity that survives saves (a page id, or the write log's lines for the address since the first look). Needs the owner's loose page removed and re-created by another writer inside a render wait.
- [ ] **G** (from the review of #668, older than it): `Roots.forget` (`hub/roots.py`) reloads the file and then removes by name. If another process forgot the root and registered another folder under the same name between this hub's earlier look and this forget, the forget takes out the other process's new root. Compare the popped root's `id` with the one the caller meant (`held`) before removing. Left open: needs two processes forgetting and registering one name at the same moment.

## Already fixed on main

- **A** (from #621): a failed pandoc probe of a bare URL was cached as False for the hub's lifetime. Fixed in 0082c3a2 (ticket 183 BT): `_pandoc_links_bare` raises `_Unread`, which `lru_cache` does not keep, and `_bare_url_whole` refuses the save (`edit.py`).
- **B** (from #621): `stays_down("signal", True)` held every signalled hub under a service for restarted, but launchd restarts only a failed exit. Fixed in 25d10469 (ticket 194): a signal stays down on macOS under the service too (`hub/client.py`, `stays_down`).
- **D** (from #630): `_take_back` unlinked whatever file was at the name when the clear of a left mark failed. Fixed in bad6b30c (ticket 195 E): the file is unlinked only when its inode is the one `create_file` made; a replaced one stays and is a diagnostics row.
