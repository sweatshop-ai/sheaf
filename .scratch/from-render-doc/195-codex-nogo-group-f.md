# 195: Codex NO-GO findings on merged PRs #611, #615, #616, #617 and #618 (group F)

**Claimed by:** Amaia

**Status:** in progress

**Blocked by:** none

**From:** the Codex re-check of PRs merged on an Opus review alone. All five returned NO-GO (#611 round 08, #615 round 06, #616 round 05, #617 round 10, #618 round 05). Every finding was checked against main b95fca00. Boxes are lettered A to E within this ticket ("195 A").

**Counts:** 15 findings:

- 10 already fixed on main (last section).
- 5 still present, all fixed here: 3 serious from #618, 1 serious and 1 minor remnant from #616.

**Where:** `src/sheafmd/hub/live.py` (`refresh`, `rebuild`, `forget`), `src/sheafmd/mcp.py` (`_make`, `_take_back`, `_put_back_mark`), `src/sheafmd/source.py` (`create_file`).

Each box is fixed test-first: a red test on main, then the fix.

## Serious

- [ ] **A** (from #618, `hub/core.py` `render`): `kept` is sampled once. A forget of the root takes no name lock, so it can pop the entry and publish `gone` after that look and before the render takes in the write on disk and rebuilds: the page heard `gone`, then `changed` twice. Fix: a forgotten `LiveDocument` publishes nothing more. `forget` sets the mark first under the document's lock, and `refresh` and `rebuild` read it under the same lock, so either their `changed` comes before the forget (and so before `gone`) or they publish nothing.
  Tests: `test_a_forgotten_document_publishes_no_change` (`tests/test_hub_live.py`), `test_a_render_whose_root_is_forgotten_after_its_entry_is_looked_at_tells_no_change_after_gone` (`tests/test_hub_index_live.py`).
- [ ] **B** (from #618, `hub/live.py` `refresh`): the path for an unchanged hash returned None without checking that the file held still, or that its first stat worked. The caller then keeps the (mtime, size) it saw, and a write in flight that ends with that key is never read. Fix: an unchanged read is settled only when the stamp before and after agree; otherwise RETRY.
  Tests: `test_an_unchanged_read_while_the_file_moves_is_not_taken_as_settled`, `test_an_unchanged_read_of_a_file_that_could_not_be_stat_ed_is_not_taken_as_settled`.
- [ ] **C** (from #618, `hub/core.py` `render`): `render` ignores the RETRY of its refresh, and the rebuild that follows read and published the file with no stability check, so a torn read reached the tabs. Fix: `rebuild` reads through the same check as `refresh` (`_rerender_settled`): a read that a write moved under is dropped, the text the tabs hold is rendered again with the new settings, and the write is left to the next refresh.
  Test: `test_a_rebuild_that_a_write_moved_under_tells_the_tabs_the_text_they_hold`.
- [ ] **E** (from #616, `mcp.py` `_take_back`): a refused create deleted the file at its path without checking that it was still the file it made, so a file that replaced it meanwhile (an editor's save, a sync) was deleted. Fix: `create_file` returns the (st_dev, st_ino) of the file it made, and the take-back deletes the file at the path only when it is that inode. The window between that look and the unlink remains; the name's lock keeps the hub's own writers out of it.
  Tests: `test_a_door_create_taken_back_leaves_a_file_that_replaced_the_one_it_made`, `test_a_door_create_taken_back_deletes_the_file_it_made` (`tests/test_hub_place.py`).

## Minor

- [ ] **D** (from #616, `mcp.py` `_mark_generated`): the finding as written (a `paths.PathError` after the file leaves it present and unmarked) no longer holds: 7d6e44c9 (#622, ticket 183 BD) sets the mark before the file. What remained: that `PathError` (a state folder sheaf will not use, not an OSError) escaped as "The hub failed on this call" instead of the door's "its generated mark could not be written", and `_put_back_mark` let it out of a take-back. Fix: both catch `paths.PathError` with `OSError`.
  Test: `test_a_door_create_whose_state_folder_refuses_the_generated_mark_is_refused_as_not_made`.

## Already fixed on main

- #611 SERIOUS (`hub/live.py`, the watch opens only after the registry lets the name go): fixed by 6da3d378 (#626), `Hub._let_go_root` detaches the root's entries before `roots_mod.forget`. Test: `test_a_text_stored_while_the_registry_lets_the_root_go_is_not_taken_by_the_late_forget`.
- #611 SERIOUS (`hub/state.py`, two forgotten documents that stored one hash each keep it): fixed by 6da3d378 (#626), `forget_texts` takes its writer out of every hash record. Test: `test_a_text_two_forgotten_documents_of_one_address_stored_goes_once_both_have_forgotten`.
- #611 SERIOUS (`hub/state.py`, a rename carries a forgotten document's late texts to the new address): fixed by 6da3d378 (#626), `Versions.rename` deletes the texts only forgotten documents put there before it moves the folder. Test: `test_a_late_text_of_a_forgotten_document_does_not_move_with_the_page_that_leaves_its_address`.
- #615 SERIOUS (`edit.py` `_bare_url_whole` counts parentheses): fixed by 608f945a (#621, ticket 183 BB), pandoc is asked which `)` GFM keeps. Codex's own example `http://x.com/a(\*b))` is a case of `test_a_bare_url_with_a_backslash_whose_parentheses_do_not_balance_keeps_its_text`.
- #617 SERIOUS (`hub/archive.py`, a page gone before the descriptor check answers 409): fixed by 0f3d816b (#627, ticket 183 BK), `FileNotFoundError` there raises `Gone`.
- #617 SERIOUS (`hub/archive.py`, delete needs hard links): fixed by 0f3d816b (#627, ticket 183 BL), the move is one `rename`.
- #617 SERIOUS (`hub/archive.py`, link then unlink can leave the page in two places): fixed by 0f3d816b (#627, ticket 183 BM), same rename.
- #617 SERIOUS (`page/page.js`, a scrolled-away moved box snaps back when the visible area changes size): fixed by 1cbf75f3 and 09eb60d4 (#628, ticket 183 BN), `clampMoved` keeps the top of a box that meets neither the area now nor the one it was held in.
- #617 MINOR (`page/page.js`, the `ResizeObserver` of a moved box is never disconnected): fixed by 1cbf75f3 (#628, ticket 183 BO), disconnected when the box closes.
- #617 SERIOUS (`page/sheaf.js`, `"old  "` renames the folder `"old "` to `"old"`): fixed by 1cbf75f3 (#628, ticket 183 BQ), a field with white space typed around it is compared with the trimmed name.
