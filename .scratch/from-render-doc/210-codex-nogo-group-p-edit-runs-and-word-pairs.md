# 210: Codex NO-GO group P (edit.py hard-break runs and escaped shortcodes in word pairs)

**Claimed by:** Imani

**Status:** done, merged in #695 (9903db92), CI run 45762958928 green on the PR head d08e9b95

**Blocked by:** none

**From:** Codex recheck pass 7: #685 round 06 and #691 round 02. Both still present on main before this ticket (red tests below).

**Where:** `src/sheafmd/edit.py`: `_source_runs_kept` (which run of breaks is the source's) and `_places_by_order` (where an escaped shortcode goes when the word diff leaves it unmatched).

## Serious

- [x] **A** (#685 round 06): summing similarities let a new run with partial matches on both sides outrank the source run with one unchanged line beside it. Source `Alpha one two three\` / `\` / `Beta four five six` against page runs `Alpha one two three<br><br>Alpha one two<br><br>Beta four five`: the source run was split into paragraphs and the new run kept as hard breaks, the reverse of the edit.
  Fix: a pairing ranks by (pairs, lines beside them unchanged, words kept), so "most pairs first" from #685 round 04 still holds. Test: `tests/test_edit_210.py::test_the_run_with_an_unchanged_line_beside_it_is_the_sources_over_one_with_two_lines_close_to_it`, red on main, green on the PR.
- [x] **B** (#691 round 02): `_word_pairs` could return a partial match that omits an escaped shortcode, so `_places_by_order` skipped its unique-neighbour fallback. Moving `A \:smile:` across two long repeated-word stretches while adding another `:smile:` lost the escape.
  Fix: a literal the diff did not match goes to its neighbours on a side only when the word beside it on that side went unmatched too (it moved with the literal). A deleted literal leaves its neighbours matched where they were, so a `:name:` typed after the same characters elsewhere stays the emoji (#594), in one diff and in a cut one. Tests: `test_an_escape_moved_across_the_anchors_of_a_cut_diff_is_placed_by_its_neighbours` (red on main), `test_an_escape_moved_with_its_words_within_one_diff_is_placed_by_its_neighbours` (red on main), and `test_an_escape_the_reader_deleted_gives_its_escape_to_no_shortcode_typed_after_the_same_characters` (one diff and a cut diff; it guards the review's regression and was red on the PR's second commit).

## Left open

- [ ] **B2** (minor, round 03 of #695): a moved literal whose neighbours are common words or punctuation (`the`, `.`) can have them matched by chance to other copies, and then loses its escape. Main loses it too; not a regression.
- [ ] **B3** (minor, Codex b on the last fix commit): deleting `left \:smile:` together with an edited word beside it, and typing `left :smile:` elsewhere next to one more `:smile:`, gives the escape to the typed one. In the saved text that is the same as moving the phrase, and past the bound main already places it by its neighbours the same way.
- [ ] **B4** (minor, Codex b round 1): each literal that reaches the neighbour probe scans all of `new` (`new.count`), so 10 000 moved escapes in one block take about two seconds. Before #691 the None path did the same scan for every literal.
- [ ] **A2** (minor, spec review): the mirror case (`Alpha one two<br><br>Beta four five<br><br>Beta four five six`) now keeps the second run as the source's, as the rank asks. No input was found where that is wrong.

## Notes

- Review of #695: Matt's code review (standards: no hard violations, naming minors applied; spec: one SERIOUS regression in the first version of B, a deleted escape handed to a typed `:smile:`, fixed test first), Codex b on the branch and on each fix commit (P2 only, see B3 and B4), and the gate's rounds 01 (Opus fallback GO), 02 (NO-GO: the same regression in a cut diff, fixed test first) and 03 (fix pass, GO).

## Known limits (Codex recheck pass 8)

Recorded, no new PR: the stop criterion of 2026-11-26 fixes only defects reachable in normal use, or that lose data without a constructed race.

- #695 round 04:
  > FINDING: [SERIOUS] src/sheafmd/edit.py:1688 — An unmatched adjacent token does not prove the escaped shortcode moved: `SequenceMatcher` can leave one of many identical tokens unmatched. For source `a \:smile: ` followed by 800 `a` words, edited to 801 `a` words followed by `:smile: :smile:`, this fallback incorrectly transfers the deleted escape to the first newly typed shortcode, saving it as literal text instead of an emoji.
