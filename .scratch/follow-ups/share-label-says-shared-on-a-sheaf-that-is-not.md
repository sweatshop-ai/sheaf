# A `- [x] Shared with the team` box can sit on a sheaf that is not shared

**What to build:** Review 3 of PR #293 (Sonnet, run by Anika) found two realistic cases around the Share tick box's label. (1) A door write, or a non-owner's save that renames and ticks in one edit, can leave `- [x] Shared with the team` on a sheaf whose `visibility` is `owner`: the label says something false, and the owner must click twice to reach the true state (the same was possible with `- [x] Share`, which says less). (2) A plain task `- [x] Shared with the team` in any existing document is now Share's control: a non-owner's untick of it is refused ("Only the owner of this sheaf can withdraw its Share."). Decide whether the box should be drawn from the sheaf's real visibility (a ticked box on an owner-only sheaf shown unticked, or the line normalised when the hub reads it), and pin both cases and the mixed `Share` / `Shared with the team` boxes with tests.

**Blocked by:** None.

**Status:** done (PR 511, merged as 539f9c8f; decision: normalise at the save path, option C)

- [x] A door write of `- [x] Shared with the team` on an owner-only sheaf: what the page shows is decided and tested (decided: left unticked, as the door already does; `tests/test_hub_visibility.py::test_a_door_create_with_a_ticked_labelled_box_on_an_owner_only_sheaf_leaves_it_unticked` passed; CI run 44793287154 green; the hand-ticked-on-disk residual is stated in SPEC 9.11)
- [x] A save that renames `- [ ] Share` to `- [x] Shared with the team` shares nothing (tested), and a page with one box of each spelling behaves as one Share (`test_the_owners_save_that_renames_and_ticks_share_in_one_edit_leaves_the_box_unticked` red before the fix, green after; `test_a_page_with_a_box_of_each_spelling_is_shared_by_either_and_withdrawn_by_neither_alone` and the case-4 test pass; test_hub_visibility, test_share and 4 more files passed locally, CI 6 of 6 slices; boss_review round 1 GO)
