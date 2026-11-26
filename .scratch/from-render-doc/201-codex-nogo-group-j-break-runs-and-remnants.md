# 201: Codex NO-GO findings on merged PR #656 (group J, edit.py break runs and heading remnants)

**Claimed by:** Alonso

**Status:** done: merged in #685 (0d0e3541) on 2026-11-26, CI `ubuntu-24.04 py3.13` run 45732976044: 11327 passed, one failure, `test_land_root`, which is main's own until #677 lands

**Blocked by:** none

**From:** the Codex re-check of #656 (ticket 188's fix), round 05, NO-GO. Two findings, both marked serious, both still present on main fac56748 (red tests below).

**Where:** `src/sheafmd/edit.py`: `_split_at_double_breaks` with the new `_source_runs_kept` and `_line_kept` (which run of breaks is the source's), `_lines_as_paragraphs` (`remnant` and the new `targets`, what an emptied first half of a split heading leaves).

## Serious

- [x] **A** (`_split_at_double_breaks`): a run of the source's hard breaks was recognised only when a line beside it stayed unchanged; editing both lines in one save split one paragraph into two, and a new run nearby took the old run's match first-come. Fix (`_source_runs_kept`): every run of the page is paired in order with the source's render runs, each pair of the same length and with some word of a line beside it still there (`_line_kept`: the share of words both lines have, punctuation aside); the pairing has the most pairs, then the most words kept. The cut loop skips a run whose breaks are in a pair.
  Tests: `tests/test_edit_201.py`, `test_the_source_run_of_hard_breaks_is_kept_whatever_the_lines_beside_it_say` (5 cases), `test_a_new_run_with_none_of_the_source_runs_words_beside_it_still_splits` (2), `test_two_runs_that_each_keep_a_word_are_both_the_sources_over_one_that_keeps_more`.
- [x] **B** (`_lines_as_paragraphs`, `remnant`): every empty inline element but an image or a box was deleted when the second half of a split heading became the heading, so an empty link target (`<a id="x"></a>`) was lost. Fix: the elements with an `id` or a `name` in what the emptied half left (`targets`, not the page's own markup) go to the start of the promoted half, in their order; pandoc writes them as `<span id="x"></span>`, as it does in any heading.
  Tests: `test_an_empty_link_target_left_in_an_emptied_first_half_stays_in_the_heading` (4 cases).

## Left open

- [ ] **A2** (minor, from the review rounds of #685): a new run of the source run's length that shares one word (even `the`) with a line beside it is paired with it once the source's own run is gone or moved, and is saved as hard breaks instead of two paragraphs. Nothing in the saved HTML tells such a paste from an edit of the source's lines; a stop-word list or a minimum share would move the line, not remove it. No text is lost.

## Notes

- Review of #685: Matt's code review (the spec half found the first pairing let a later new run take the source's pair and kept a pasted run with no word in common; both fixed, with tests), then Codex b, which gave no verdict: Opus fallback GO (rounds 01 to 03, provisional), each later round on the fix diff only. Codex's own recheck (round 04) gave NO-GO on the pairing counting words before pairs; fixed test first in 84bfbe62, fallback GO on that diff (round 05).
- A review point that does not hold: `\w` counting `_` as a word character; both sides are compared as rendered text, where `_Alpha_` is already `Alpha`.
