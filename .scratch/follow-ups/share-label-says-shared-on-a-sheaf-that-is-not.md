# A `- [x] Shared with the team` box can sit on a sheaf that is not shared

**What to build:** Review 3 of PR #293 (Sonnet, run by Anika) found two realistic cases around the Share tick box's label. (1) A door write, or a non-owner's save that renames and ticks in one edit, can leave `- [x] Shared with the team` on a sheaf whose `visibility` is `owner`: the label says something false, and the owner must click twice to reach the true state (the same was possible with `- [x] Share`, which says less). (2) A plain task `- [x] Shared with the team` in any existing document is now Share's control: a non-owner's untick of it is refused ("Only the owner of this sheaf can withdraw its Share."). Decide whether the box should be drawn from the sheaf's real visibility (a ticked box on an owner-only sheaf shown unticked, or the line normalised when the hub reads it), and pin both cases and the mixed `Share` / `Shared with the team` boxes with tests.

**Blocked by:** None.

**Status:** open

- [ ] A door write of `- [x] Shared with the team` on an owner-only sheaf: what the page shows is decided and tested
- [ ] A save that renames `- [ ] Share` to `- [x] Shared with the team` shares nothing (tested), and a page with one box of each spelling behaves as one Share
