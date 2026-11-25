# 198: Codex NO-GO findings on merged PRs #622, #624, #628, #635 and #640 (group I)

**Claimed by:** Wilma

**Status:** in progress (A to D and F fixed in PR #669; E and G left open)

**Blocked by:** none

**From:** the Codex re-check of PRs merged on an Opus review alone. All five returned NO-GO (#622 round 06, #624 round 06, #628 round 06, #635 round 08, #640 round 06). Every finding was checked against main 3b984afe. Boxes are lettered A to G within this ticket ("198 A").

**Counts:** 6 findings, plus 2 minor ones from this ticket's own review (F, G):

- 1 already fixed on main (last section).
- 4 serious ones still present, all fixed here test-first.
- 1 minor fixed (F), 2 minor left open (E, G).

**Where:** `src/sheafmd/source.py` (`_write_atomic`, `_replace_if_ours`), `src/sheafmd/hub/archive.py` (`_unmark`), `src/sheafmd/hub/loose.py`, `src/sheafmd/page/page.js` (`viewRect`, `sizesOf`, `clampMoved`), `src/sheafmd/_pandoc.py`, `src/sheafmd/hub/core.py` (`render`).

## Serious

- [ ] **A** (from #624, `source.py` `_write_atomic`): the `check` that refuses a write when the file changed ran before `_replace_if_ours` read the temporary file back whole, a read as long as the file. An editor's save during that read was still overwritten by the replace. Fix: `_replace_if_ours` takes the `check` and calls it after the read-back, the last step before `os.replace` (on Windows, after the chmod).
  Test: `test_the_check_runs_after_the_new_file_is_read_back_just_before_the_replace` (`tests/test_atomic.py`); red on main ("DID NOT RAISE").
- [ ] **B** (from #635, `hub/archive.py` `_unmark`): the sweep's marks of N addresses with no page cleared each keep mark with its own `keep_held`, so the keep file was read, rewritten and synced N times under the moves lock. Fix: `loose.unkeep_held(root, rels)` takes them all off in one write.
  Test: `test_the_keep_marks_of_many_addresses_with_no_page_go_in_one_write` (`tests/test_trash.py`); red on main (5 writes).
- [ ] **C** (from #628, `page.js` `clampMoved`): the area a moved box was held in was rebuilt from the window's old size but the host's current size. A host sized to the window that shrank with it made a box that was inside the old host and lies wholly past the new one's foot look scrolled away, so it was left out of reach. Fix: `sizesOf` keeps the host's own (unclipped) width and height, and `viewRect(winW, winH, held)` measures the old area with them. The 183 BN case is unchanged: there the host's own height does not change, only its clipping by the window.
  Test: `test_on_the_mounted_page_a_box_inside_a_host_that_shrinks_with_the_window_is_held_inside_the_smaller_host` (`tests/page/test_mount_page.py`, CI only).
- [ ] **D** (from #640, `hub/client.py` `RENDER_TIMEOUT`): a hub render runs pandoc twice (measured: 2 runs on a first render, 2 more on a re-render with new settings), each with its own 120 s, while `sheaf open` waits 130 s. Fix: `_pandoc.budget()` makes the runs inside share one 120 s limit, and `Hub.render` runs inside it; a run with none of the limit left fails at once, as a run that timed out does. SPEC 3.2 and the CHANGELOG say so. A render whose time is spent says "did not finish this render in time: its runs share 120 seconds".
  Test: `test_the_pandoc_runs_of_one_render_share_one_time_limit_shorter_than_the_clients_wait` (`tests/test_hub_index.py`); on main the runs took 140 s of a fake clock.

## Minor

- [ ] **E** (from #624, `tests/helpers.py` `number_places`): two places of a number with the same 16 characters on each side count as one key, so one removed and one added there pass. Left open: its one user (`test_the_page_never_holds_the_session_id_the_socket_or_the_command`, `tests/test_hub_tell.py`) compares the page with a session attached against the same page without one, which differ elsewhere (the agent's name and target), so the key has to be local: a whole-text key would differ for every place. The gap needs the PID to be added where 32 characters on both sides equal those around a place of the same number that went; a wider window narrows it, never closes it.
- [ ] **F** (review of #669, `comments.py` `_read_tables`): the reading of a block was cached also when pandoc failed (None). With D a run fails at once when the render's time is spent, so a block could stay unread for every later render and save of the same text. Fix: the failure is not cached (`_read_tables_kept` raises, `_read_tables` turns it into None), as `edit.py` does with `_Unread`.
  Test: `test_a_pandoc_run_that_fails_is_not_kept_so_the_next_read_of_the_block_asks_pandoc_again` (`tests/test_table_in_container.py`); red before the fix.
- [ ] **G** (review of #669, the rest of D): the budget starts before the render takes the document's lock, so time spent waiting counts against it, but a save holding that lock runs its own pandoc runs with no shared budget. A render that waits behind a long save can still pass 130 s. Left open: bounding a save is a separate change (a save has no client wait to fit), and the case needs a save that itself runs past 120 s.

## Already fixed on main

- #622 SERIOUS (`mcp.py` `_make`, an orphan generated mark is inherited by a later plain create): fixed by 8145a941 (ticket 183 BR, merged in #630) and d553fd1e: a create without `generated` reads the mark left on an address with no page and clears it after the file is written. Tests: `test_a_create_without_generated_clears_a_mark_left_on_an_address_with_no_page`, `test_a_create_without_generated_that_loses_the_name_leaves_the_winners_mark`, `test_a_create_whose_left_mark_cannot_be_cleared_leaves_no_page` (`tests/test_mcp_generated.py`).
