# Handoff: ticket 204, Codex NO-GO group L on #662

**Status:** done. PR #688 merged as 60f4a683 on 2026-11-26.

## Result

The three serious findings of the #662 re-check (round 03) all held on main and are fixed in #688, each test-first:

- **A**: the take-back of a refused create deletes only the file it made; any other file goes back to its name or is kept aside and named.
- **B**: a page deleted into the trash ends its stream with `gone`; nothing is published after it.
- **C**: a torn-read recovery whose second render fails leaves the hub serving the page it served before.

## Review

- Hand round: Matt's code-review (standards, spec) and Codex over the whole PR, then Codex over the fix diff only. Every finding verified and fixed. Records: `pm/reviews/sweatshop-ai/sheaf/pr688/round01.out`, `round01-fixes.out`, `verdicts.md`.
- Recorded round for the merge gate: `boss_review.py` round 2, Opus fallback (Codex at its usage limit until 2026-11-27), GO with one minor finding: a file put back is briefly missing from its name, and one kept aside shows only in diagnostics. Accepted as the documented trade-off.

## Open

- Residual: a write through a held descriptor between the take-back's last look and its unlink is not seen (documented in `_delete_if_made`).
- Seen in CI, not ours: `test_hub_index.py::test_the_warnings_of_a_render_that_answered_pending_go_to_the_next_open` leaves the 0.2 s answer limit on for its second render; handed to the owner of #679.
