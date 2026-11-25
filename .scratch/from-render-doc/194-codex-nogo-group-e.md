# 194: Codex NO-GO findings on merged PRs #570, #605, #606, #607 and #610 (atomic writer, move race, upgrade wait, cell breaks, documents count)

**Claimed by:** Kenji

**Status:** in progress

**Blocked by:** none

**From:** the Codex re-check of PRs merged on an Opus review alone. All five returned NO-GO. Every finding was checked against main cfc6d17f. Boxes are lettered within this ticket ("194 A").

**Counts:** 9 findings:

- 1 already fixed on main (last section).
- 7 fixed here: 5 serious, 2 minor (one of them a serious finding downgraded, with the reason).
- 2 left open (reasons in their boxes).

**Where:** `src/sheafmd/source.py` (`_write_atomic`, `_holds_bytes`), `src/sheafmd/hub/client.py` (`stays_down`), `src/sheafmd/edit.py` (`_without_placeholder_breaks`, `_cell_breaks`), `src/sheafmd/mcp.py` (`documents`).

Serious boxes are fixed test-first: the red tests are commit 97296a70, on main as it was.

## Serious

- [ ] **A** (from #570, `source.py` `_write_atomic`): the final mode was put on the temp file before the text was written into it, so with a mode open to the group or others a temp file a crash leaves half written was readable by them. Fix: the temp file is 0o600 while it is written; the mode goes on once it is whole and read back.
  Test: `test_the_temp_file_is_the_owners_alone_until_its_text_is_whole[file]` and `[document]` in `tests/test_atomic.py`.
- [ ] **B** (from #570, `source.py` `_write_atomic`): the read-back of the temp file made `write_text_atomic(..., mode=0o200)` (any mode without the owner's read) fail with an `OSError`, where the writer gave any mode before. Fix: the mode is put on through the descriptor that read the temp file back (`_holds_bytes(..., mode)`), so the read comes before the mode. A document (the locked path) keeps the refusal, now made before anything is written: its look after the replace has to read it.
  Test: `test_a_mode_that_leaves_the_owner_no_read_is_still_given`; `test_a_document_whose_owner_bits_lack_read_is_not_called_a_swap` in `tests/test_source.py` still passes.
- [ ] **D** (from #607, `edit.py` `_without_placeholder_breaks`): in a table `_cell_breaks` takes, a break at the end of a mark (`<b>x<br></b>` followed by two no-break spaces) has no next sibling, so it was deleted before `_cell_breaks` could see the typed no-break space: the line the user typed was lost. Fix: the text after the break is its next element in the page (`_text_after`), past the end of the marks it ends.
  Test: `test_two_no_break_spaces_after_a_break_at_the_end_of_bold_keep_the_break` in `tests/test_edit_cell_breaks.py`.
- [ ] **E** (from #607, `edit.py`): the same break in a table that goes as raw HTML kept both no-break spaces, Enter's cut and the typed one, because the cut looked only at `br.next_sibling`. Fix: as D, in the raw-HTML branch and in `_cell_breaks`.
  Test: `test_two_no_break_spaces_after_a_break_at_the_end_of_bold_in_a_table_with_a_backslash_keep_one`.
- [ ] **F** (from #610, `mcp.py` `documents`): once the count limit was reached, a time budget that ran out was not said when nothing had been counted as `more`: the files after the limit were hidden ones the judged caller had to open, so a visible page still ahead was left out without a `more` row or a `stopped` row. Fix: past the limit, a time-out with nothing counted is a `stopped` row.
  Test: `test_a_time_budget_that_runs_out_past_the_count_limit_among_hidden_files_says_the_listing_stopped` in `tests/test_private_root_visible.py`.

## Minor

- [ ] **C** (from #570, `source.py`): the text was encoded after the temp file was opened and before the `with` that closes it, so a text that cannot be encoded (a lone surrogate) leaked the descriptor. Fix: encoded before anything is opened.
  Test: `test_a_text_that_cannot_be_encoded_leaves_no_descriptor_and_no_temp_file[file]` and `[document]`.
- [ ] **G** (from #606, `hub/client.py` `stays_down`, Codex SERIOUS, MINOR here): under the service, a signal was read as one the unit starts again, so the upgrade waited for a hub. That is wrong in three cases: launchd (a signal exits 0, and `KeepAlive.SuccessfulExit=false` starts only a failure), `systemctl stop`, and a unit of an older sheaf (`Restart=on-failure`). Fixed for launchd: on macOS a signal stays down under the service too, so the command says so at once. Downgraded because no case gives a wrong result: the command waits `UPGRADE_WAIT` and says the hub did not come back; if another command starts a hub of this version meanwhile, the command uses a hub that another command started on purpose.
  Test: `test_a_signal_that_wins_under_launchd_starts_no_hub_and_is_said_at_once` in `tests/test_hub_upgrade.py`.
- [ ] **G2** (from #606, the rest of G) left open: on Linux the client cannot tell a `systemctl stop` or an older unit from a signal the unit restarts; the exit row says `signal` for each. The wait and its message are as SPEC 14.3 and `stays_down` say.
- [ ] **H** (from #610, `mcp.py` `LISTED_ALL`, Codex SERIOUS, MINOR here) left open: the lister has no count cap inside the time budget, so a very large plain folder holds every path it found in that half of 10 s. Not fixed here because a cap would not bound the git case: `_git_names` reads every name `git ls-files` gives in one piece before any cap applies. A real bound needs a streaming lister, which is its own ticket.

## Already fixed on main

- #605 SERIOUS (`hub/outgoing.py`, `moved_remote` resolves the root by name again after the move validated the captured root, so a forget and a name takeover in between could write a Forward for the other folder's page and drop its versions and marks): fixed by 730328dd (ticket 182 H), merged after #605's head. A forget takes the moves' lock (`moves_mod.exclusive()` in `Hub.forget_root`), and the move holds that lock (`moves.page_held`) from `hub.file(address, root_id=root.id)` through `moved_remote`, so no forget comes between the two. Test: `test_a_forget_waits_for_a_move_that_drops_the_page_and_leaves_the_folder_that_takes_the_name_its_own` in `tests/test_move_to_tiroir.py`, which checks the other folder's keep mark as well as its file.
