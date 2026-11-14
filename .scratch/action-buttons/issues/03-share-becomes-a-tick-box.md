# 03: Share becomes a tick box

**What to build:** Share (9.11), today a blue toggle button in the row above the document, becomes a tick box with its label, `- [ ] Shared with the team`; only the owner may tick or untick it, as today. Existing files keep working: `- [ ] Share` is read as before.

**Blocked by:** 02

**Claimed by:** Anika 2026-11-14 02:10

**Status:** ready-for-agent

- [x] The owner ticks and unticks it by its label; another member's tick is refused as today (`test_a_click_on_any_of_the_words_of_the_label_ticks_share_and_a_second_click_unticks_it`, `test_a_member_who_is_not_the_owner_is_told_so_and_nothing_is_written` (tests/page/test_page_share_box.py), `test_the_labelled_box_ticked_by_a_member_who_is_not_the_owner_is_refused_and_writes_nothing` (tests/test_hub_visibility.py), green in CI on e0d074b, run 43581327422)
- [x] `- [ ] Share` and `- [ ] Shared with the team` both work; the list keeps its button (`test_the_older_share_line_works_the_same_way`, `test_the_owners_tick_of_the_labelled_box_shares_the_sheaf_as_share_does`, `test_the_row_keeps_its_share_button_for_a_box_that_says_shared_with_the_team`, `test_the_hub_never_writes_the_new_label_into_a_file_that_holds_the_old_line`, green in CI on e0d074b)
- [ ] The tiroir-tt routines that read the box still find it (check `thinkingtoo/tt-tiroir` before merging): checked read-only at 93aa1e2 on 2026-11-14; `digest.py` and `plan-privacy-probe.py` write `- [ ] Share` and tick the word `Share`, unaffected, but `routines/record-routine/record.py` (WORDS line 22, `_BOX_RE` line 29) does not read `- [x] Shared with the team`, so such a Share would be recorded without its "Shared by" comment; the hub never writes the new label into a file, so nothing opens by itself; the one-word fix is a stage for Thierry (`.scratch/follow-ups/tt-tiroir-record-routine-reads-the-share-label.md`)
